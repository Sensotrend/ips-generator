"""Step 4: deterministic grounding of every ``source_quote`` against the ingested document.

PLAN.md §2 step 4 and D3. Pure functions, no I/O, no logging of content.

Facts
-----
A *fact* is any model in the extraction that has a ``source_quote`` (items, "none known"
statements, patient names / identifiers / birth date / gender). Facts are found by walking the
extraction generically, so schema additions (new sections, an optional statement inside a
section) are covered without code changes. Each fact has a stable *path*: attribute names and
list indexes from the `IpsExtraction` root, e.g. ``patient.names[0]``, ``patient.birth_date``,
``allergies.items[2]``, ``allergies.none_known_statements[0]``. A section that is itself a
statement (``none_known``) has the section's path, e.g. ``medications``.

Matching ladder (first rung that matches wins)
----------------------------------------------
1. ``exact`` - the quote occurs verbatim in the stated page's text (segments joined by ``\\n``),
   starting inside the stated segment (``page`` + ``locator``).
2. ``normalised`` - same, after normalising both sides (`normalise`): Unicode NFKC (composes
   decomposed ``a`` + U+0308 into ``ä``, folds ligatures and no-break spaces), dashes and
   minus signs to ``-``, typographic quotes to ``'`` / ``"``, soft hyphens and zero-width
   characters removed, case-folded, every whitespace run (including line breaks between
   segments) collapsed to one space.
3. ``relocated`` - the quote (verbatim or normalised) occurs elsewhere: another segment of the
   stated page or another page. The report gives the corrected ``page`` / ``locator``.
4. ``fuzzy`` - best token-aligned window of the document, both sides reduced to word tokens,
   has a character similarity (``difflib`` ratio) of at least `FUZZY_THRESHOLD`. Windows are
   ``n-1 .. n+1`` tokens for an ``n``-token quote and anchored on tokens shared with the quote.
   Every number token of the quote (dose, strength, date) must occur exactly in the window, so
   "Ramipril 10 mg" never fuzzily matches "Ramipril 5 mg".
   Quotes shorter than `FUZZY_MIN_CHARS` normalised characters never match fuzzily (a short
   quote such as ``mies`` would match too much).
   "None known" statements never match fuzzily: one changed word changes their scope ("Ei
   tiedossa olevia allergioita" vs "... lääkeaineallergioita"), so they must match verbatim
   or normalised.
5. ``not_found``.

Policy (`apply_grounding`)
--------------------------
* ``exact`` / ``normalised``: kept as is.
* ``relocated``: kept, ``page`` / ``locator`` corrected to where the quote was found, flagged.
* ``fuzzy``: kept unchanged (the quote is not verbatim, so its stated location is kept and the
  best match is only reported), flagged.
* ``not_found``: removed. A list element is dropped (including a scoped "no known ..."
  statement in allergies ``none_known_statements``); an optional single fact (birth date,
  gender) becomes ``null``. A section whose ``none_known`` statement is not found, or whose
  ``items_found`` ``items`` list ends up empty, becomes ``no_information`` **and is flagged**
  (even if scoped statements survive): an unverified claim must not turn into "none known",
  and "no information" is the honest machine-readable state until a reviewer looks at it.

Printed codes (D-9)
-------------------
After the policy above, a non-empty ``printed_code`` on a kept item must occur in that item's
``source_quote`` (normalised, as a whole token sequence). Otherwise it is not what the document
printed next to the entry: ``printed_code`` and ``printed_code_system_text`` are cleared and the
item is flagged ``printed_code_not_in_quote``. A ``printed_code_system_text`` without a code is
cleared silently. This lives here rather than in a Pydantic validator because it repairs and
flags instead of rejecting the whole extraction.
"""

from __future__ import annotations

import bisect
import re
import unicodedata
from collections import Counter
from collections.abc import Iterator
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from enum import StrEnum
from typing import Any, Final

from pydantic import BaseModel, ConfigDict

from app.schemas.intermediate import IpsExtraction, NoKnownAllergyStatement, NoneKnown
from app.schemas.source import IngestedDocument, SourceSegment

__all__ = [
    "FUZZY_MIN_CHARS",
    "FUZZY_THRESHOLD",
    "FactGrounding",
    "GroundedExtraction",
    "GroundingReport",
    "GroundingStatus",
    "ReviewFlag",
    "ReviewReason",
    "apply_grounding",
    "ground",
    "iter_facts",
    "normalise",
    "printed_code_in_quote",
]

FUZZY_THRESHOLD: Final = 0.85
"""Minimum ``difflib`` ratio for a fuzzy match. Tolerates a typo or OCR-like slip per ~7
characters (e.g. ``Penisilliini`` vs ``Penisillini``) but not a different word."""

FUZZY_MIN_CHARS: Final = 8
"""Normalised quotes shorter than this are never matched fuzzily."""


class GroundingStatus(StrEnum):
    EXACT = "exact"
    NORMALISED = "normalised"
    RELOCATED = "relocated"
    FUZZY = "fuzzy"
    NOT_FOUND = "not_found"


class FactGrounding(BaseModel):
    """Grounding outcome for one fact. Contains positions only, never document text."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    status: GroundingStatus
    stated_page: int
    stated_locator: str | None
    found_page: int | None
    """Where the quote (or its best fuzzy match) starts; ``None`` if not found."""
    found_locator: str | None
    score: float
    """1.0 for exact/normalised/relocated, the similarity for fuzzy, the best score below the
    threshold (or 0.0) for not_found."""


class GroundingReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    facts: tuple[FactGrounding, ...]

    @property
    def counts(self) -> dict[GroundingStatus, int]:
        counts = dict.fromkeys(GroundingStatus, 0)
        for fact in self.facts:
            counts[fact.status] += 1
        return counts

    @property
    def all_grounded(self) -> bool:
        return all(f.status is not GroundingStatus.NOT_FOUND for f in self.facts)

    def get(self, path: str) -> FactGrounding | None:
        return next((f for f in self.facts if f.path == path), None)


class ReviewReason(StrEnum):
    RELOCATED = "relocated"  # quote found elsewhere; page/locator corrected
    FUZZY_MATCH = "fuzzy_match"  # quote not verbatim in the document
    DROPPED_NOT_FOUND = "dropped_not_found"  # fact removed: quote not in the document
    SECTION_UNVERIFIED = "section_unverified"  # section set to no_information by grounding
    PRINTED_CODE_NOT_IN_QUOTE = "printed_code_not_in_quote"  # printed_code cleared (D-9)
    # Raised by app.pipeline.derive (D-10), not by grounding:
    DERIVED_FROM_IDENTITY_CODE = "derived_from_identity_code"  # reviewer must confirm
    IDENTITY_CODE_CONFLICT = "identity_code_conflict"  # stated value kept; code disagrees
    IDENTITY_CODE_AMBIGUOUS = "identity_code_ambiguous"  # several different codes; no derivation


class ReviewFlag(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    """Path in the *grounded* extraction; for dropped facts, the path in the original one. For
    derivation flags, the patient field the derived value is for (``patient.birth_date``,
    ``patient.gender``) or ``patient.identifiers``."""
    reason: ReviewReason


class GroundedExtraction(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    extraction: IpsExtraction
    flags: tuple[ReviewFlag, ...]
    dropped: tuple[str, ...]
    """Paths (in the original extraction) of facts removed because they were not found."""


# --------------------------------------------------------------------------------------------
# Normalisation
# --------------------------------------------------------------------------------------------

_DASHES: Final = "\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d"
_SINGLE_QUOTES: Final = "\u2018\u2019\u201a\u201b\u2032\u0060\u00b4"
_DOUBLE_QUOTES: Final = "\u201c\u201d\u201e\u201f\u2033\u00ab\u00bb"
_INVISIBLE: Final = "\u00ad\u200b\u200c\u200d\u2060\ufeff"  # soft hyphen, zero-width
_TRANSLATE: Final = str.maketrans(
    {
        **dict.fromkeys(_DASHES, "-"),
        **dict.fromkeys(_SINGLE_QUOTES, "'"),
        **dict.fromkeys(_DOUBLE_QUOTES, '"'),
        **dict.fromkeys(_INVISIBLE, None),
    }
)
_WHITESPACE: Final = re.compile(r"\s+")
_TOKEN: Final = re.compile(r"\w+")


def normalise(text: str) -> str:
    """Comparison form of ``text`` (see the module docstring, rung 2)."""
    text = unicodedata.normalize("NFKC", text).translate(_TRANSLATE).casefold()
    return _WHITESPACE.sub(" ", text).strip()


# --------------------------------------------------------------------------------------------
# Document index
# --------------------------------------------------------------------------------------------


@dataclass
class _Page:
    number: int
    segments: list[SourceSegment]
    raw: str
    raw_starts: list[int]
    norm: str
    norm_starts: list[int]
    tokens: list[str] = field(default_factory=list)
    token_starts: list[int] = field(default_factory=list)
    token_index: dict[str, list[int]] = field(default_factory=dict)

    def segment_at(self, offset: int, *, normalised: bool) -> SourceSegment:
        starts = self.norm_starts if normalised else self.raw_starts
        return self.segments[bisect.bisect_right(starts, offset) - 1]

    def span(self, segment_index: int, *, normalised: bool) -> tuple[int, int]:
        starts = self.norm_starts if normalised else self.raw_starts
        text = self.norm if normalised else self.raw
        end = starts[segment_index + 1] if segment_index + 1 < len(starts) else len(text) + 1
        return starts[segment_index], end


def _index_page(number: int, segments: list[SourceSegment]) -> _Page:
    raw_parts: list[str] = []
    raw_starts: list[int] = []
    norm_parts: list[str] = []
    norm_starts: list[int] = []
    raw_pos = norm_pos = 0
    for segment in segments:
        raw_starts.append(raw_pos)
        raw_parts.append(segment.text)
        raw_pos += len(segment.text) + 1  # "\n" separator, as IngestedDocument.page_text()
        norm_text = normalise(segment.text)
        norm_starts.append(norm_pos)
        norm_parts.append(norm_text)
        norm_pos += len(norm_text) + 1  # " " separator
    page = _Page(
        number=number,
        segments=segments,
        raw="\n".join(raw_parts),
        raw_starts=raw_starts,
        norm=" ".join(norm_parts),
        norm_starts=norm_starts,
    )
    for match in _TOKEN.finditer(page.norm):
        page.token_index.setdefault(match.group(), []).append(len(page.tokens))
        page.tokens.append(match.group())
        page.token_starts.append(match.start())
    return page


def _index(doc: IngestedDocument) -> dict[int, _Page]:
    return {number: _index_page(number, doc.segments_on_page(number)) for number in doc.pages}


# --------------------------------------------------------------------------------------------
# Facts
# --------------------------------------------------------------------------------------------


def iter_facts(model: BaseModel, prefix: str = "") -> Iterator[tuple[str, BaseModel]]:
    """Yield ``(path, fact)`` for every model with a ``source_quote``, in schema order."""
    if "source_quote" in type(model).model_fields:
        yield prefix, model
    for name in type(model).model_fields:
        value = getattr(model, name)
        path = f"{prefix}.{name}" if prefix else name
        if isinstance(value, BaseModel):
            yield from iter_facts(value, path)
        elif isinstance(value, list):
            for index, element in enumerate(value):
                if isinstance(element, BaseModel):
                    yield from iter_facts(element, f"{path}[{index}]")


def _locator_of(fact: BaseModel) -> str | None:
    locator = getattr(fact, "locator", None)
    return locator if isinstance(locator, str) and locator else None


# --------------------------------------------------------------------------------------------
# Matching
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _Match:
    status: GroundingStatus
    page: int | None
    locator: str | None
    score: float


def _find_in_segment(page: _Page, segment_index: int, needle: str, *, normalised: bool) -> bool:
    """True if ``needle`` occurs starting inside the given segment."""
    start, end = page.span(segment_index, normalised=normalised)
    haystack = page.norm if normalised else page.raw
    found = haystack.find(needle, start)
    return found != -1 and found < end


def _find_anywhere(page: _Page, quote: str, norm_quote: str) -> SourceSegment | None:
    found = page.raw.find(quote)
    if found != -1:
        return page.segment_at(found, normalised=False)
    found = page.norm.find(norm_quote)
    if found != -1:
        return page.segment_at(found, normalised=True)
    return None


def _fuzzy(page: _Page, quote_tokens: list[str]) -> tuple[float, int | None]:
    """Best ratio of a token-aligned window on ``page`` and the token index where it starts."""
    target = " ".join(quote_tokens)
    n = len(quote_tokens)
    starts: set[int] = set()
    for offset, token in enumerate(quote_tokens):
        for position in page.token_index.get(token, ()):
            for shift in (-1, 0, 1):
                start = position - offset + shift
                if 0 <= start < len(page.tokens):
                    starts.add(start)
    numbers = Counter(t for t in quote_tokens if any(c.isdigit() for c in t))
    best, best_start = 0.0, None
    for start in sorted(starts):
        for size in sorted({max(1, n - 1), n, n + 1}):
            window = page.tokens[start : start + size]
            if not window or numbers - Counter(window):
                continue  # every number in the quote (dose, strength, date) must match exactly
            matcher = SequenceMatcher(None, target, " ".join(window), autojunk=False)
            if matcher.real_quick_ratio() <= best or matcher.quick_ratio() <= best:
                continue
            ratio = matcher.ratio()
            if ratio > best:
                best, best_start = ratio, start
    return best, best_start


def _ground_fact(fact: BaseModel, pages: dict[int, _Page]) -> _Match:
    quote = str(getattr(fact, "source_quote", ""))
    stated_page = int(getattr(fact, "page", 0))
    stated_locator = _locator_of(fact)
    norm_quote = normalise(quote)
    if not norm_quote:
        return _Match(GroundingStatus.NOT_FOUND, None, None, 0.0)

    page = pages.get(stated_page)
    if page is not None:
        segment_index = next(
            (i for i, s in enumerate(page.segments) if s.locator == stated_locator), None
        )
        if segment_index is not None:
            if _find_in_segment(page, segment_index, quote, normalised=False):
                return _Match(GroundingStatus.EXACT, stated_page, stated_locator, 1.0)
            if _find_in_segment(page, segment_index, norm_quote, normalised=True):
                return _Match(GroundingStatus.NORMALISED, stated_page, stated_locator, 1.0)

    # Search the stated page first, then the others in order.
    order = sorted(pages, key=lambda number: (number != stated_page, number))
    for number in order:
        segment = _find_anywhere(pages[number], quote, norm_quote)
        if segment is not None:
            return _Match(GroundingStatus.RELOCATED, segment.page, segment.locator, 1.0)

    if isinstance(fact, (NoneKnown, NoKnownAllergyStatement)):
        return _Match(GroundingStatus.NOT_FOUND, None, None, 0.0)
    quote_tokens = _TOKEN.findall(norm_quote)
    if len(norm_quote) < FUZZY_MIN_CHARS or not quote_tokens:
        return _Match(GroundingStatus.NOT_FOUND, None, None, 0.0)
    best: tuple[float, int | None, str | None] = (0.0, None, None)
    for number in order:
        score, start = _fuzzy(pages[number], quote_tokens)
        if start is not None and score > best[0]:
            seg = pages[number].segment_at(pages[number].token_starts[start], normalised=True)
            best = (score, number, seg.locator)
    score, found_page, found_locator = best
    if score >= FUZZY_THRESHOLD:
        return _Match(GroundingStatus.FUZZY, found_page, found_locator, round(score, 3))
    return _Match(GroundingStatus.NOT_FOUND, None, None, round(score, 3))


def ground(extraction: IpsExtraction, doc: IngestedDocument) -> GroundingReport:
    """Check every fact's ``source_quote`` against ``doc``."""
    pages = _index(doc)
    results: list[FactGrounding] = []
    for path, fact in iter_facts(extraction):
        match = _ground_fact(fact, pages)
        results.append(
            FactGrounding(
                path=path,
                status=match.status,
                stated_page=int(getattr(fact, "page", 0)),
                stated_locator=_locator_of(fact),
                found_page=match.page,
                found_locator=match.locator,
                score=match.score,
            )
        )
    return GroundingReport(facts=tuple(results))


# --------------------------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------------------------

_PATH_PART: Final = re.compile(r"([a-z_]+)((?:\[\d+\])*)")
_NO_INFORMATION: Final = {"kind": "no_information"}


def _parse_path(path: str) -> list[str | int]:
    parts: list[str | int] = []
    for name, indexes in _PATH_PART.findall(path):
        parts.append(name)
        parts.extend(int(i) for i in re.findall(r"\d+", indexes))
    return parts


def _resolve(root: Any, parts: list[str | int]) -> Any:
    node = root
    for part in parts:
        node = node[part]
    return node


def apply_grounding(extraction: IpsExtraction, report: GroundingReport) -> GroundedExtraction:
    """Apply the module's grounding policy. Returns a new extraction; the input is not mutated."""
    data: dict[str, Any] = extraction.model_dump(mode="python")
    flags: list[ReviewFlag] = []
    dropped: list[str] = []
    removals: dict[tuple[str | int, ...], set[int]] = {}  # list path -> indexes to drop
    unverified_sections: set[str] = set()
    kept_list_flags: list[tuple[tuple[str | int, ...], int, ReviewReason]] = []

    for fact in report.facts:
        parts = _parse_path(fact.path)
        if fact.status is GroundingStatus.NOT_FOUND:
            dropped.append(fact.path)
            flags.append(ReviewFlag(path=fact.path, reason=ReviewReason.DROPPED_NOT_FOUND))
            if isinstance(parts[-1], int):
                removals.setdefault(tuple(parts[:-1]), set()).add(parts[-1])
            elif len(parts) == 1:  # a section-level statement such as none_known
                unverified_sections.add(str(parts[0]))
            else:  # optional single fact, e.g. patient.birth_date
                _resolve(data, parts[:-1])[parts[-1]] = None
            continue
        if fact.status is GroundingStatus.RELOCATED:
            target = _resolve(data, parts)
            target["page"] = fact.found_page
            target["locator"] = fact.found_locator
        if fact.status in (GroundingStatus.RELOCATED, GroundingStatus.FUZZY):
            reason = (
                ReviewReason.RELOCATED
                if fact.status is GroundingStatus.RELOCATED
                else ReviewReason.FUZZY_MATCH
            )
            if isinstance(parts[-1], int):
                kept_list_flags.append((tuple(parts[:-1]), parts[-1], reason))
            else:
                flags.append(ReviewFlag(path=fact.path, reason=reason))

    for list_path, indexes in removals.items():
        container = _resolve(data, list(list_path))
        container[:] = [v for i, v in enumerate(container) if i not in indexes]
        parent = _resolve(data, list(list_path[:-1]))
        is_items = len(list_path) == 2 and list_path[1] == "items"
        if is_items and parent.get("kind") == "items_found" and not container:
            unverified_sections.add(str(list_path[0]))

    for list_path, index, reason in kept_list_flags:
        if str(list_path[0]) in unverified_sections and len(list_path) == 2:
            continue
        new_index = index - sum(1 for i in removals.get(list_path, ()) if i < index)
        flags.append(ReviewFlag(path=_format_path([*list_path, new_index]), reason=reason))

    for section in sorted(unverified_sections):
        data[section] = dict(_NO_INFORMATION)
        flags.append(ReviewFlag(path=section, reason=ReviewReason.SECTION_UNVERIFIED))

    grounded = IpsExtraction.model_validate(data)
    if _check_printed_codes(grounded, data, flags):
        grounded = IpsExtraction.model_validate(data)

    return GroundedExtraction(extraction=grounded, flags=tuple(flags), dropped=tuple(dropped))


def printed_code_in_quote(code: str, quote: str) -> bool:
    """True if ``code`` occurs in ``quote`` (both normalised) and is not part of a longer code:
    "E11" is not in "(E11.9)", but "E11.9" is in "E11.9." at the end of a sentence."""
    norm_code = normalise(code)
    if not norm_code:
        return False
    pattern = rf"(?<!\w)(?<!\w[.\-]){re.escape(norm_code)}(?![.\-]?\w)"
    return re.search(pattern, normalise(quote)) is not None


def _check_printed_codes(
    extraction: IpsExtraction, data: dict[str, Any], flags: list[ReviewFlag]
) -> bool:
    """Clear (in ``data``) printed codes that are not in their item's quote and append a flag for
    each. Paths are those of ``extraction``, which ``data`` mirrors. True if ``data`` changed."""
    changed = False
    for path, fact in iter_facts(extraction):
        if "printed_code" not in type(fact).model_fields:
            continue
        code = getattr(fact, "printed_code", None)
        system = getattr(fact, "printed_code_system_text", None)
        target = _resolve(data, _parse_path(path))
        if code and not printed_code_in_quote(code, str(getattr(fact, "source_quote", ""))):
            target["printed_code"] = target["printed_code_system_text"] = None
            flags.append(ReviewFlag(path=path, reason=ReviewReason.PRINTED_CODE_NOT_IN_QUOTE))
            changed = True
        elif not code and system:
            target["printed_code_system_text"] = None
            changed = True
    return changed


def _format_path(parts: list[str | int]) -> str:
    path = ""
    for part in parts:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else part
    return path
