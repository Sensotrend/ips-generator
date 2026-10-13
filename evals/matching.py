"""Deterministic matching of predicted items to gold items (PLAN.md §7.1 D-3).

Per section, every (predicted, gold) pair gets two signals:

* **text similarity** of the primary text (``substance_text``, ``medication_text``,
  ``condition_text``, a patient name, an identifier value, a statement's quote). Both sides are
  reduced to word tokens (`text_tokens`): printed codes (ATC ``C07AB07``, ICD-10 ``E11.9``)
  removed, for medications also strengths (``40 mg``, ``1 g``, ``100 mikrog/annos``); then
  `app.pipeline.ground.normalise` (NFKC, dashes/quotes, case-fold, whitespace) and split on
  non-word characters (punctuation dropped). Similarity is a token-bag F1 (order-insensitive),
  where two tokens are equal if identical or, for tokens of 5+ characters, if they share a
  prefix of at least ``max(4, shorter length - 3)`` characters. That cheap rule tolerates
  Finnish/Swedish inflection and compounding suffixes (``diabetes``/``diabeteksen``,
  ``astma``/``astmaa``, ``pähkinä``/``pähkinäallergia``) without a stemmer. For allergies the
  words allergy/intolerance themselves (``allergia``, ``allergi``, ``intoleranssi``, ...) are
  dropped, so ``Kala-allergia`` compares equal to ``Kala``.
* **quote overlap**: the character span of each ``source_quote`` in the normalised document
  (`DocumentIndex.locate`; the occurrence in the stated page/locator wins, otherwise the first;
  a quote that is not verbatim falls back to its longest common block if that covers 60% of the
  quote). ``containment`` = overlap / shorter span, ``jaccard`` = overlap / longer span. Gold
  quotes are verbatim, so this is a strong signal that two items talk about the same line.

A pair is *eligible* if

1. text similarity >= `TEXT_THRESHOLD` (method ``text``), or
2. jaccard >= `QUOTE_THRESHOLD` (both quotes cover mostly the same span; method ``quote``),
   or containment >= `CONTAINMENT_THRESHOLD` with text similarity >= `PARTIAL_TEXT_THRESHOLD`
   (method ``quote``).

Its score is ``text similarity + containment``. Assignment is one-to-one and greedy by score
(ties by predicted index, then gold index); the datasets are tiny and an eligible pair almost
always has one obvious partner, so greedy equals the optimal assignment in practice. Leftovers
go to the LLM judge when enabled (`evals.judge`), else they count as FP (predicted) / FN (gold).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Final, Literal

from app.pipeline.ground import normalise
from app.schemas.source import IngestedDocument

__all__ = [
    "CONTAINMENT_THRESHOLD",
    "PARTIAL_TEXT_THRESHOLD",
    "QUOTE_THRESHOLD",
    "TEXT_THRESHOLD",
    "Candidate",
    "DocumentIndex",
    "Match",
    "MatchMethod",
    "MatchResult",
    "TextKind",
    "greedy_assign",
    "match_candidates",
    "pair_score",
    "text_similarity",
    "text_tokens",
    "tokens_match",
]

TEXT_THRESHOLD: Final = 0.8
QUOTE_THRESHOLD: Final = 0.5
CONTAINMENT_THRESHOLD: Final = 0.9
PARTIAL_TEXT_THRESHOLD: Final = 0.3
_LOCATE_FALLBACK_COVERAGE: Final = 0.6
_LOCATE_FALLBACK_MIN_CHARS: Final = 8

MatchMethod = Literal["text", "quote", "judge"]
TextKind = Literal["allergy", "medication", "condition", "name", "identifier", "statement"]

# ATC (C07AB07) and ICD-10 (E11.9, I10, J18.9) codes, matched before case-folding.
_PRINTED_CODE_RE: Final = re.compile(r"\b(?:[A-Z]\d{2}[A-Z]{2}\d{2}|[A-Z]\d{2}(?:\.\d{1,4})?)\b")
_STRENGTH_RE: Final = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*"
    r"(?:mg|g|mcg|µg|μg|ug|mikrog|ng|ml|l|mmol|ie|iu|ky|u|units?|yks|%)"
    r"(?:\s*/\s*(?:ml|g|l|dose|annos|dos|h|vrk|d|24\s*h))?(?!\w)",
    re.IGNORECASE,
)
_TOKEN_RE: Final = re.compile(r"\w+")
_ALLERGY_WORDS: Final = frozenset(
    {
        "allergia",
        "allergi",
        "allergy",
        "allergies",
        "allergic",
        "intoleranssi",
        "intolerans",
        "intolerance",
        "yliherkkyys",
        "överkänslighet",
    }
)


# --------------------------------------------------------------------------------------------
# Text similarity
# --------------------------------------------------------------------------------------------


def text_tokens(text: str, kind: TextKind) -> tuple[str, ...]:
    """Comparison tokens of a primary text (see the module docstring)."""
    if kind in ("allergy", "medication", "condition"):
        text = _PRINTED_CODE_RE.sub(" ", text)
    if kind == "medication":
        text = _STRENGTH_RE.sub(" ", text)
    if kind == "identifier":
        return (re.sub(r"[\W_]+", "", normalise(text)),)
    tokens = _TOKEN_RE.findall(normalise(text).replace("_", " "))
    if kind == "allergy":
        tokens = [t for t in tokens if t not in _ALLERGY_WORDS] or tokens
    return tuple(tokens)


def tokens_match(a: str, b: str) -> bool:
    """Equal, or inflection-tolerant prefix match for tokens of 5+ characters."""
    if a == b:
        return True
    shorter = min(len(a), len(b))
    if shorter < 5:
        return False
    common = 0
    for x, y in zip(a, b, strict=False):
        if x != y:
            break
        common += 1
    return common >= max(4, shorter - 3)


def text_similarity(a: Sequence[str], b: Sequence[str]) -> float:
    """Token-bag F1 with `tokens_match` as equality (each token used once)."""
    if not a or not b:
        return 0.0
    if tuple(a) == tuple(b):
        return 1.0
    unused = list(b)
    matched = 0
    for token in a:
        for i, other in enumerate(unused):
            if tokens_match(token, other):
                matched += 1
                del unused[i]
                break
    return 2 * matched / (len(a) + len(b))


# --------------------------------------------------------------------------------------------
# Quote spans
# --------------------------------------------------------------------------------------------


type Span = tuple[int, int]


class DocumentIndex:
    """Normalised document text with segment offsets, for locating quotes as spans."""

    def __init__(self, doc: IngestedDocument) -> None:
        parts: list[str] = []
        self._segments: list[tuple[int, int, int, str | None]] = []  # start, end, page, locator
        offset = 0
        for segment in doc.segments:
            text = normalise(segment.text)
            if not text:
                continue
            if parts:
                offset += 1  # joining space
            self._segments.append((offset, offset + len(text), segment.page, segment.locator))
            parts.append(text)
            offset += len(text)
        self.text = " ".join(parts)

    def _segment_of(self, position: int) -> tuple[int, str | None] | None:
        for start, end, page, locator in self._segments:
            if start <= position < end:
                return page, locator
        return None

    def locate(
        self, quote: str, page: int | None = None, locator: str | None = None
    ) -> Span | None:
        """Span of ``quote`` in `text`, preferring the occurrence at ``page``/``locator``."""
        needle = normalise(quote)
        if not needle:
            return None
        occurrences: list[int] = []
        start = self.text.find(needle)
        while start != -1:
            occurrences.append(start)
            start = self.text.find(needle, start + 1)
        if occurrences:
            stated = (page, locator or None)
            for position in occurrences:
                segment = self._segment_of(position)
                if segment is not None and (segment[0], segment[1] or None) == stated:
                    return position, position + len(needle)
            for position in occurrences:
                segment = self._segment_of(position)
                if segment is not None and segment[0] == page:
                    return position, position + len(needle)
            return occurrences[0], occurrences[0] + len(needle)
        # Not verbatim (fuzzy-grounded prediction): longest common block, if it covers most of it.
        matcher = SequenceMatcher(None, self.text, needle, autojunk=False)
        block = matcher.find_longest_match(0, len(self.text), 0, len(needle))
        if block.size >= max(_LOCATE_FALLBACK_MIN_CHARS, _LOCATE_FALLBACK_COVERAGE * len(needle)):
            begin = max(0, block.a - block.b)
            return begin, min(len(self.text), begin + len(needle))
        return None


def span_overlap(a: Span | None, b: Span | None) -> tuple[float, float]:
    """(containment, jaccard-like) overlap of two spans; (0, 0) if either is missing."""
    if a is None or b is None:
        return 0.0, 0.0
    inter = max(0, min(a[1], b[1]) - max(a[0], b[0]))
    if inter == 0:
        return 0.0, 0.0
    len_a, len_b = a[1] - a[0], b[1] - b[0]
    return inter / min(len_a, len_b), inter / max(len_a, len_b)


# --------------------------------------------------------------------------------------------
# Assignment
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Candidate:
    """One item as seen by the matcher."""

    index: int
    text: str
    tokens: tuple[str, ...]
    span: Span | None


@dataclass(frozen=True)
class Match:
    pred: int
    gold: int
    score: float
    method: MatchMethod


@dataclass(frozen=True)
class MatchResult:
    matches: tuple[Match, ...]
    unmatched_pred: tuple[int, ...]
    unmatched_gold: tuple[int, ...]


def pair_score(pred: Candidate, gold: Candidate) -> tuple[float, MatchMethod] | None:
    """Score and method of an eligible pair, ``None`` if the pair cannot match."""
    similarity = text_similarity(pred.tokens, gold.tokens)
    containment, jaccard = span_overlap(pred.span, gold.span)
    score = similarity + containment
    if similarity >= TEXT_THRESHOLD:
        return score, "text"
    if jaccard >= QUOTE_THRESHOLD or (
        containment >= CONTAINMENT_THRESHOLD and similarity >= PARTIAL_TEXT_THRESHOLD
    ):
        return score, "quote"
    return None


def greedy_assign(
    n_pred: int,
    n_gold: int,
    score: Callable[[int, int], tuple[float, MatchMethod] | None],
) -> MatchResult:
    """One-to-one assignment, highest score first (ties: lower pred index, then gold index)."""
    pairs: list[tuple[float, int, int, MatchMethod]] = []
    for p in range(n_pred):
        for g in range(n_gold):
            scored = score(p, g)
            if scored is not None:
                pairs.append((scored[0], p, g, scored[1]))
    pairs.sort(key=lambda t: (-t[0], t[1], t[2]))
    used_pred: set[int] = set()
    used_gold: set[int] = set()
    matches: list[Match] = []
    for value, p, g, method in pairs:
        if p in used_pred or g in used_gold:
            continue
        used_pred.add(p)
        used_gold.add(g)
        matches.append(Match(pred=p, gold=g, score=round(value, 4), method=method))
    matches.sort(key=lambda m: m.gold)
    return MatchResult(
        matches=tuple(matches),
        unmatched_pred=tuple(p for p in range(n_pred) if p not in used_pred),
        unmatched_gold=tuple(g for g in range(n_gold) if g not in used_gold),
    )


def match_candidates(pred: Sequence[Candidate], gold: Sequence[Candidate]) -> MatchResult:
    """Deterministic matching of two candidate lists (indexes are list positions)."""
    result = greedy_assign(len(pred), len(gold), lambda p, g: pair_score(pred[p], gold[g]))
    return MatchResult(
        matches=tuple(
            Match(pred=pred[m.pred].index, gold=gold[m.gold].index, score=m.score, method=m.method)
            for m in result.matches
        ),
        unmatched_pred=tuple(pred[p].index for p in result.unmatched_pred),
        unmatched_gold=tuple(gold[g].index for g in result.unmatched_gold),
    )
