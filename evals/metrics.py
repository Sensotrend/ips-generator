"""Per-case scores and dataset aggregates (PLAN.md §6 Phase 1, §7.1 D-3).

Definitions
-----------
* **Items** (``allergies``, ``medications``, ``problems``): predicted items are matched one-to-one
  to gold items (`evals.matching`, then the optional judge). TP = matched pairs, FP = unmatched
  predicted items, FN = unmatched gold items. A section that is ``none_known`` or
  ``no_information`` has no items. Precision = TP/(TP+FP), recall = TP/(TP+FN), F1 their
  harmonic mean; ``None`` when the denominator is 0.
* **D-7 statements** (``allergy_statements``): scoped "no known ..." statements inside allergies
  ``items_found``, matched like items by their quote; field ``scope``.
* **Patient** (``patient_names``, ``patient_identifiers``: matched like items;
  ``patient_birth_date``, ``patient_gender``: a single value, TP when equal, FP + FN when
  different, FP / FN when only one side has it). ``patient`` sums the four. These score the
  LLM layer: gold keeps ``birth_date: null`` when only a HETU is present.
* **Effective patient values** (D-10; ``patient_birth_date_effective``,
  ``patient_gender_effective``): the value the Patient resource carries (derived from a Finnish
  personal identity code if there is one, else stated) vs the case's true value in
  ``meta.json`` ``expected_patient``, scored like a single value. Empty when the case has no
  ``expected_patient``. **Derived accuracy** (``derived``): over the values that were derived,
  the share equal to the true value (``n`` = number of derived values).
* **Micro** averages sum TP/FP/FN over cases; **macro** averages per-case F1 over the cases
  where the section has at least one gold or predicted item (both empty = undefined, skipped).
* **Section state** (allergies/medications/problems): ``items_found`` / ``none_known`` /
  ``no_information`` of the *grounded* prediction vs gold; accuracy and a confusion matrix.
  **Critical** state errors: predicting ``none_known`` when gold has items, or ``items_found``
  when gold says none known. **False assurance**: ``none_known`` when gold is
  ``no_information``. A failed extraction has state ``error`` (always wrong).
* **Field accuracy** over matched pairs: enumerated fields exact; dates exact, plus a lenient
  rate where one date is a prefix of the other (``2024`` vs ``2024-03``); printed codes compared
  case- and space-insensitively; strength without spaces and with ``,`` = ``.``; dosage text and
  body site by presence only.
* **Validator pass**: Matchbox reports 0 errors **and** no unmatched Bundle entry. Pass rate is
  over all cases that were run (failed extractions and assemblies count as not passing): the
  Phase 1 "done when" metric (>= 90%).

Scores are computed on the grounded extraction (what the pipeline would assemble); the counts of
the raw (pre-grounding) extraction are kept as ``raw_counts`` to separate grounding losses from
extraction errors.
"""

from __future__ import annotations

import statistics
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.intermediate import (
    AllergiesFound,
    AllergyItem,
    ConditionItem,
    ImmunizationItem,
    IpsExtraction,
    ItemsFound,
    MedicationItem,
    NoKnownAllergyStatement,
    PatientContactExtraction,
    PatientDerivations,
    PregnancyFactItem,
    SocialHistoryItem,
    VitalSignItem,
)
from evals.matching import (
    Candidate,
    DocumentIndex,
    Match,
    MatchResult,
    TextKind,
    match_candidates,
    text_tokens,
)

__all__ = [
    "CRITICAL_STATE_ERRORS",
    "DERIVED_FIELDS",
    "EFFECTIVE_PATIENT_SECTIONS",
    "EXTRA_SECTIONS",
    "ITEM_SECTIONS",
    "PATIENT_SECTIONS",
    "SCORED_SECTIONS",
    "CaseResult",
    "CaseScore",
    "Counts",
    "FieldTally",
    "JudgeItem",
    "LeftoverJudge",
    "RunSummary",
    "SectionScore",
    "UsageRecord",
    "ValidationRecord",
    "aggregate",
    "score_case",
    "section_state",
]

ITEM_SECTIONS: Final = ("allergies", "medications", "problems")
EXTRA_SECTIONS: Final = (
    "vital_signs",
    "social_history",
    "immunizations",
    "pregnancy",
    "patient_contacts",
)
"""Optional sections (schema 1.2.0): scored only for cases whose ``meta.json`` has
``extra_sections: true``, i.e. whose gold annotates all of them."""
PATIENT_SECTIONS: Final = (
    "patient_names",
    "patient_identifiers",
    "patient_birth_date",
    "patient_gender",
)
EFFECTIVE_PATIENT_SECTIONS: Final = (
    "patient_birth_date_effective",
    "patient_gender_effective",
)
DERIVED_FIELDS: Final = ("birth_date", "gender")
SCORED_SECTIONS: Final = (
    *ITEM_SECTIONS,
    "allergy_statements",
    *EXTRA_SECTIONS,
    *PATIENT_SECTIONS,
    *EFFECTIVE_PATIENT_SECTIONS,
)
STATES: Final = ("items_found", "none_known", "no_information", "error")
CRITICAL_STATE_ERRORS: Final = frozenset(
    {("items_found", "none_known"), ("none_known", "items_found")}
)
"""(gold, predicted) pairs counted as critical."""
FALSE_ASSURANCE: Final = ("no_information", "none_known")

_KIND: Final[dict[str, TextKind]] = {
    "allergies": "allergy",
    "medications": "medication",
    "problems": "condition",
    "vital_signs": "fact",
    "social_history": "fact",
    "immunizations": "fact",
    "pregnancy": "fact",
    "patient_contacts": "name",
}


# --------------------------------------------------------------------------------------------
# Result models
# --------------------------------------------------------------------------------------------


def _ratio(num: int, den: int) -> float | None:
    return num / den if den else None


class Counts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tp: int = 0
    fp: int = 0
    fn: int = 0

    def __add__(self, other: Counts) -> Counts:
        return Counts(tp=self.tp + other.tp, fp=self.fp + other.fp, fn=self.fn + other.fn)

    @property
    def precision(self) -> float | None:
        return _ratio(self.tp, self.tp + self.fp)

    @property
    def recall(self) -> float | None:
        return _ratio(self.tp, self.tp + self.fn)

    @property
    def f1(self) -> float | None:
        return _ratio(2 * self.tp, 2 * self.tp + self.fp + self.fn)

    @property
    def empty(self) -> bool:
        return self.tp + self.fp + self.fn == 0

    def prf(self) -> dict[str, Any]:
        return {
            **self.model_dump(),
            "precision": self.precision,
            "recall": self.recall,
            "f1": self.f1,
        }


class FieldTally(BaseModel):
    model_config = ConfigDict(extra="forbid")

    correct: int = 0
    lenient: int = 0
    total: int = 0

    def add(self, correct: bool, lenient: bool) -> None:
        self.total += 1
        self.correct += int(correct)
        self.lenient += int(lenient)


class MatchRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pred: int
    gold: int
    method: str
    score: float


class SectionScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    counts: Counts = Field(default_factory=Counts)
    matches: list[MatchRecord] = Field(default_factory=list)
    unmatched_pred: list[str] = Field(default_factory=list)
    """Primary texts of unmatched predicted items (synthetic data only)."""
    unmatched_gold: list[str] = Field(default_factory=list)
    fields: dict[str, FieldTally] = Field(default_factory=dict)


class StateOutcome(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gold: str
    pred: str

    @property
    def correct(self) -> bool:
        return self.gold == self.pred


class CaseScore(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sections: dict[str, SectionScore]
    states: dict[str, StateOutcome]
    derived: dict[str, bool] = Field(default_factory=dict)
    """Derived patient field (``birth_date``, ``gender``) -> equals the true value. Only fields
    that were derived and whose true value is known."""


class UsageRecord(BaseModel):
    """Extraction (and judge) usage of one case."""

    model_config = ConfigDict(extra="forbid")

    model_requested: str | None = None
    model_used: str | None = None
    fallback_used: bool = False
    attempts: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    cost_usd: float = 0.0
    latency_s: float | None = None
    judge_cost_usd: float = 0.0
    judge_calls: int = 0


class IssueRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    severity: str
    message_id: str | None
    path: str
    message: str


class ValidationRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    errors: int
    warnings: int
    unmatched_entries: list[int]
    passed: bool
    issues: list[IssueRecord]
    """Errors, warnings and unmatched-slice information issues (synthetic data only)."""


class CaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    language: str
    format: str
    doc_type: str
    status: Literal["ok", "extraction_failed", "skipped"]
    error: str | None = None
    score: CaseScore | None = None
    raw_counts: dict[str, Counts] = Field(default_factory=dict)
    grounding: dict[str, int] = Field(default_factory=dict)
    dropped: int = 0
    review_flags: dict[str, int] = Field(default_factory=dict)
    assembly_ok: bool | None = None
    assembly_error: str | None = None
    assembly_warnings: int = 0
    validation: ValidationRecord | None = None
    usage: UsageRecord | None = None


# --------------------------------------------------------------------------------------------
# Per-case scoring
# --------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class JudgeItem:
    """A leftover item shown to the judge."""

    index: int
    text: str
    quote: str
    details: str


type LeftoverJudge = Callable[
    [str, Sequence[JudgeItem], Sequence[JudgeItem]], Sequence[tuple[int, int]]
]
"""(section, predicted leftovers, gold leftovers) -> matched (pred index, gold index) pairs."""


def section_state(extraction: IpsExtraction, section: str) -> str:
    kind: str = getattr(extraction, section).kind
    return kind


def _items(extraction: IpsExtraction | None, section: str) -> list[Any]:
    if extraction is None:
        return []
    value = getattr(extraction, section)
    return list(value.items) if isinstance(value, ItemsFound) else []


def _extra_items(extraction: IpsExtraction | None, section: str) -> list[Any]:
    if extraction is None:
        return []
    if section == "patient_contacts":
        return list(extraction.patient.contacts)
    return list(getattr(extraction, section))


def _statements(extraction: IpsExtraction | None) -> list[NoKnownAllergyStatement]:
    if extraction is None or not isinstance(extraction.allergies, AllergiesFound):
        return []
    return list(extraction.allergies.none_known_statements)


def _primary_text(item: Any) -> str:
    if isinstance(item, AllergyItem):
        return item.substance_text
    if isinstance(item, MedicationItem):
        return item.medication_text
    if isinstance(item, ConditionItem):
        return item.condition_text
    if isinstance(item, VitalSignItem):
        diastolic = f" {_plain(item.diastolic)}" if item.diastolic is not None else ""
        return f"{item.kind.value} {_plain(item.value)}{diastolic}"
    if isinstance(item, SocialHistoryItem):
        return f"{item.kind.value} {item.tobacco_status.value}"
    if isinstance(item, ImmunizationItem):
        return f"{item.vaccine_text} {item.occurrence or ''}".strip()
    if isinstance(item, PregnancyFactItem):
        value = item.date or (str(item.count) if item.count is not None else item.status.value)
        return f"{item.kind.value} {value}"
    if isinstance(item, PatientContactExtraction):
        return item.name_text
    raise TypeError(type(item).__name__)


def _plain(value: Any) -> str:
    return format(value.normalize(), "f")


def _candidates(
    texts: Sequence[str], facts: Sequence[Any], kind: TextKind, index: DocumentIndex
) -> list[Candidate]:
    return [
        Candidate(
            index=i,
            text=text,
            tokens=text_tokens(text, kind),
            span=index.locate(fact.source_quote, fact.page, fact.locator),
        )
        for i, (text, fact) in enumerate(zip(texts, facts, strict=True))
    ]


def _details(item: Any) -> str:
    if isinstance(item, MedicationItem):
        parts = [item.strength_text, item.dose_form_text, item.dosage.text, item.status.value]
        return " | ".join(p for p in parts if p)
    if isinstance(item, ConditionItem):
        return " | ".join(p for p in (item.body_site_text, item.clinical_status.value) if p)
    if isinstance(item, AllergyItem):
        return " | ".join((item.type.value, item.category.value))
    return ""


def _apply_judge(
    section: str,
    result: MatchResult,
    pred_items: Sequence[Any],
    gold_items: Sequence[Any],
    judge: LeftoverJudge,
) -> MatchResult:
    if not result.unmatched_pred or not result.unmatched_gold:
        return result
    pred_left = [
        JudgeItem(
            i, _primary_text(pred_items[i]), pred_items[i].source_quote, _details(pred_items[i])
        )
        for i in result.unmatched_pred
    ]
    gold_left = [
        JudgeItem(
            i, _primary_text(gold_items[i]), gold_items[i].source_quote, _details(gold_items[i])
        )
        for i in result.unmatched_gold
    ]
    pairs = judge(section, pred_left, gold_left)
    free_pred, free_gold = set(result.unmatched_pred), set(result.unmatched_gold)
    extra: list[Match] = []
    for p, g in pairs:  # ignore invalid or duplicate indexes from the judge
        if p in free_pred and g in free_gold:
            free_pred.discard(p)
            free_gold.discard(g)
            extra.append(Match(pred=p, gold=g, score=0.0, method="judge"))
    return MatchResult(
        matches=tuple(sorted((*result.matches, *extra), key=lambda m: m.gold)),
        unmatched_pred=tuple(sorted(free_pred)),
        unmatched_gold=tuple(sorted(free_gold)),
    )


def _section_score(
    result: MatchResult,
    pred_texts: Sequence[str],
    gold_texts: Sequence[str],
    fields: dict[str, FieldTally] | None = None,
) -> SectionScore:
    return SectionScore(
        counts=Counts(
            tp=len(result.matches), fp=len(result.unmatched_pred), fn=len(result.unmatched_gold)
        ),
        matches=[
            MatchRecord(pred=m.pred, gold=m.gold, method=m.method, score=m.score)
            for m in result.matches
        ],
        unmatched_pred=[pred_texts[i] for i in result.unmatched_pred],
        unmatched_gold=[gold_texts[i] for i in result.unmatched_gold],
        fields=fields or {},
    )


# ---- field comparison ----------------------------------------------------------------------


def _enum(a: Any, b: Any) -> tuple[bool, bool]:
    equal = a == b
    return equal, equal


def _date(a: str | None, b: str | None) -> tuple[bool, bool]:
    if a == b:
        return True, True
    if a is None or b is None:
        return False, False
    return False, a.startswith(b) or b.startswith(a)


def _code(a: str | None, b: str | None) -> tuple[bool, bool]:
    def norm(v: str | None) -> str:
        return "".join((v or "").split()).casefold()

    return _enum(norm(a), norm(b))


def _strength(a: str | None, b: str | None) -> tuple[bool, bool]:
    def norm(v: str | None) -> str:
        return "".join((v or "").split()).casefold().replace(",", ".")

    return _enum(norm(a), norm(b))


def _digits(a: str | None, b: str | None) -> tuple[bool, bool]:
    def norm(v: str | None) -> str:
        return "".join(c for c in (v or "") if c.isdigit())

    return _enum(norm(a), norm(b))


def _present(a: Any, b: Any) -> tuple[bool, bool]:
    return _enum(bool(a), bool(b))


type FieldCheck = Callable[[Any, Any], tuple[bool, bool]]

_FIELDS: Final[dict[str, dict[str, FieldCheck]]] = {
    "allergies": {
        "type": lambda p, g: _enum(p.type, g.type),
        "category": lambda p, g: _enum(p.category, g.category),
        "criticality": lambda p, g: _enum(p.criticality, g.criticality),
        "clinical_status": lambda p, g: _enum(p.clinical_status, g.clinical_status),
        "verification_status": lambda p, g: _enum(p.verification_status, g.verification_status),
        "onset": lambda p, g: _date(p.onset, g.onset),
        "printed_code": lambda p, g: _code(p.printed_code, g.printed_code),
        "reactions_present": lambda p, g: _present(p.reactions, g.reactions),
    },
    "medications": {
        "status": lambda p, g: _enum(p.status, g.status),
        "dosage_text_present": lambda p, g: _present(p.dosage.text, g.dosage.text),
        "as_needed": lambda p, g: _enum(p.dosage.as_needed, g.dosage.as_needed),
        "strength": lambda p, g: _strength(p.strength_text, g.strength_text),
        "effective_start": lambda p, g: _date(p.effective_start, g.effective_start),
        "effective_end": lambda p, g: _date(p.effective_end, g.effective_end),
        "printed_code": lambda p, g: _code(p.printed_code, g.printed_code),
    },
    "problems": {
        "clinical_status": lambda p, g: _enum(p.clinical_status, g.clinical_status),
        "verification_status": lambda p, g: _enum(p.verification_status, g.verification_status),
        "onset": lambda p, g: _date(p.onset, g.onset),
        "abatement": lambda p, g: _date(p.abatement, g.abatement),
        "printed_code": lambda p, g: _code(p.printed_code, g.printed_code),
        "body_site_present": lambda p, g: _present(p.body_site_text, g.body_site_text),
    },
    "allergy_statements": {"scope": lambda p, g: _enum(p.scope, g.scope)},
    "vital_signs": {
        "kind": lambda p, g: _enum(p.kind, g.kind),
        "value": lambda p, g: _enum(p.value, g.value),
        "diastolic": lambda p, g: _enum(p.diastolic, g.diastolic),
        "unit": lambda p, g: _strength(p.unit_text, g.unit_text),
        "effective": lambda p, g: _date(p.effective, g.effective),
    },
    "social_history": {
        "kind": lambda p, g: _enum(p.kind, g.kind),
        "tobacco_status": lambda p, g: _enum(p.tobacco_status, g.tobacco_status),
        "date": lambda p, g: _date(p.date, g.date),
    },
    "immunizations": {
        "status": lambda p, g: _enum(p.status, g.status),
        "occurrence": lambda p, g: _date(p.occurrence, g.occurrence),
        "printed_code": lambda p, g: _code(p.printed_code, g.printed_code),
    },
    "pregnancy": {
        "kind": lambda p, g: _enum(p.kind, g.kind),
        "status": lambda p, g: _enum(p.status, g.status),
        "date": lambda p, g: _date(p.date, g.date),
        "count": lambda p, g: _enum(p.count, g.count),
    },
    "patient_contacts": {
        "relationship_present": lambda p, g: _present(p.relationship_text, g.relationship_text),
        "phone": lambda p, g: _digits(p.phone, g.phone),
    },
}


def _field_tallies(
    section: str, matches: Iterable[Match], pred: Sequence[Any], gold: Sequence[Any]
) -> dict[str, FieldTally]:
    checks = _FIELDS.get(section, {})
    tallies = {name: FieldTally() for name in checks}
    for match in matches:
        for name, check in checks.items():
            tallies[name].add(*check(pred[match.pred], gold[match.gold]))
    return tallies


def _single_value(pred: Any, gold: Any) -> SectionScore:
    """Birth date / gender: one value or none on each side."""
    return _compare_values(getattr(pred, "value", None), getattr(gold, "value", None))


def _compare_values(p: str | None, g: str | None) -> SectionScore:
    counts = Counts()
    if p is not None and g is not None and p == g:
        counts.tp = 1
    else:
        counts.fp = int(p is not None)
        counts.fn = int(g is not None)
    return SectionScore(
        counts=counts,
        unmatched_pred=[str(p)] if counts.fp else [],
        unmatched_gold=[str(g)] if counts.fn else [],
    )


def score_case(
    pred: IpsExtraction | None,
    gold: IpsExtraction,
    index: DocumentIndex,
    *,
    judge: LeftoverJudge | None = None,
    derived: PatientDerivations | None = None,
    expected_patient: dict[str, str | None] | None = None,
    score_extra: bool = False,
) -> CaseScore:
    """Score ``pred`` (``None`` = extraction failed) against ``gold`` for one document.

    ``derived`` are the D-10 derivations made from ``pred``; ``expected_patient`` the case's
    true birth date / gender (``None``: effective-value sections stay empty); ``score_extra``
    scores the optional sections (the case's gold annotates them), else they stay empty."""
    sections: dict[str, SectionScore] = {}
    for section in ITEM_SECTIONS:
        pred_items, gold_items = _items(pred, section), _items(gold, section)
        pred_texts = [_primary_text(i) for i in pred_items]
        gold_texts = [_primary_text(i) for i in gold_items]
        kind = _KIND[section]
        result = match_candidates(
            _candidates(pred_texts, pred_items, kind, index),
            _candidates(gold_texts, gold_items, kind, index),
        )
        if judge is not None:
            result = _apply_judge(section, result, pred_items, gold_items, judge)
        sections[section] = _section_score(
            result,
            pred_texts,
            gold_texts,
            _field_tallies(section, result.matches, pred_items, gold_items),
        )

    pred_st, gold_st = _statements(pred), _statements(gold)
    pred_q, gold_q = [s.source_quote for s in pred_st], [s.source_quote for s in gold_st]
    result = match_candidates(
        _candidates(pred_q, pred_st, "statement", index),
        _candidates(gold_q, gold_st, "statement", index),
    )
    sections["allergy_statements"] = _section_score(
        result,
        pred_q,
        gold_q,
        _field_tallies("allergy_statements", result.matches, pred_st, gold_st),
    )

    for section in EXTRA_SECTIONS:
        if not score_extra:
            sections[section] = SectionScore()
            continue
        pred_items, gold_items = _extra_items(pred, section), _extra_items(gold, section)
        pred_texts = [_primary_text(i) for i in pred_items]
        gold_texts = [_primary_text(i) for i in gold_items]
        kind = _KIND[section]
        result = match_candidates(
            _candidates(pred_texts, pred_items, kind, index),
            _candidates(gold_texts, gold_items, kind, index),
        )
        sections[section] = _section_score(
            result,
            pred_texts,
            gold_texts,
            _field_tallies(section, result.matches, pred_items, gold_items),
        )

    pred_names = list(pred.patient.names) if pred else []
    pred_ids = list(pred.patient.identifiers) if pred else []
    for key, kind, pred_facts, gold_facts, attr in (
        ("patient_names", "name", pred_names, gold.patient.names, "text"),
        ("patient_identifiers", "identifier", pred_ids, gold.patient.identifiers, "value"),
    ):
        p_texts = [getattr(f, attr) for f in pred_facts]
        g_texts = [getattr(f, attr) for f in gold_facts]
        result = match_candidates(
            _candidates(p_texts, pred_facts, kind, index),
            _candidates(g_texts, gold_facts, kind, index),
        )
        sections[key] = _section_score(result, p_texts, g_texts)
    sections["patient_birth_date"] = _single_value(
        pred.patient.birth_date if pred else None, gold.patient.birth_date
    )
    sections["patient_gender"] = _single_value(
        pred.patient.gender if pred else None, gold.patient.gender
    )

    derived = derived or PatientDerivations()
    derived_correct: dict[str, bool] = {}
    for field in DERIVED_FIELDS:
        stated = getattr(pred.patient, field) if pred else None
        derived_value = getattr(derived, field)
        effective = derived_value.value if derived_value else getattr(stated, "value", None)
        key = f"patient_{field}_effective"
        if expected_patient is None:
            sections[key] = SectionScore()
            continue
        truth = expected_patient.get(field)
        sections[key] = _compare_values(str(effective) if effective is not None else None, truth)
        if derived_value is not None and truth is not None:
            derived_correct[field] = str(derived_value.value) == truth

    states = {
        section: StateOutcome(
            gold=section_state(gold, section),
            pred=section_state(pred, section) if pred is not None else "error",
        )
        for section in ITEM_SECTIONS
    }
    return CaseScore(sections=sections, states=states, derived=derived_correct)


def item_counts(
    pred: IpsExtraction, gold: IpsExtraction, index: DocumentIndex, *, score_extra: bool = False
) -> dict[str, Counts]:
    """Item counts only (no judge), e.g. for the raw pre-grounding extraction."""
    score = score_case(pred, gold, index, score_extra=score_extra)
    return {name: s.counts for name, s in score.sections.items()}


# --------------------------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------------------------


class SectionAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tp: int
    fp: int
    fn: int
    precision: float | None
    recall: float | None
    f1: float | None
    macro_precision: float | None
    macro_recall: float | None
    macro_f1: float | None
    macro_n: int
    """Cases in the macro average (at least one gold or predicted item)."""


class StateAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n: int
    correct: int
    accuracy: float | None
    confusion: dict[str, dict[str, int]]
    """gold state -> predicted state -> count."""


class FieldAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n: int
    accuracy: float | None
    lenient_accuracy: float | None


class GroupAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n: int
    f1: dict[str, float | None]
    state_accuracy: float | None
    validation_passed: int | None
    validation_pass_rate: float | None


class UsageAggregate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    extraction_cost_usd: float = 0.0
    judge_cost_usd: float = 0.0
    judge_calls: int = 0
    total_cost_usd: float = 0.0
    cost_per_case_usd: float | None = None
    latency_mean_s: float | None = None
    latency_median_s: float | None = None
    latency_max_s: float | None = None
    fallbacks: int = 0
    refusals: int = 0
    repair_attempts: int = 0
    errors: dict[str, int] = Field(default_factory=dict)


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    n_cases: int
    n_scored: int
    n_extraction_failed: int
    n_skipped: int
    sections: dict[str, SectionAggregate]
    patient: SectionAggregate
    raw_sections: dict[str, SectionAggregate]
    """Item metrics of the raw extraction, before grounding dropped anything."""
    match_methods: dict[str, int]
    states: dict[str, StateAggregate]
    state_accuracy: float | None
    critical_state_errors: list[str]
    """``case_id section gold->pred``."""
    false_assurance: list[str]
    fields: dict[str, dict[str, FieldAggregate]]
    derived: dict[str, FieldAggregate]
    """D-10: derived patient values (n) and the share equal to the true value."""
    grounding: dict[str, int]
    dropped_facts: int
    review_flags: dict[str, int]
    assembly_attempted: int
    assembly_ok: int
    validation_ran: bool
    validation_passed: int | None
    validation_pass_rate: float | None
    validation_failures: dict[str, list[str]]
    """case_id -> reasons (error message ids/paths, unmatched entries, or failed step)."""
    by_language: dict[str, GroupAggregate]
    by_format: dict[str, GroupAggregate]
    usage: UsageAggregate


def _aggregate_section(scores: Sequence[SectionScore] | Sequence[Counts]) -> SectionAggregate:
    counts = [s.counts if isinstance(s, SectionScore) else s for s in scores]
    total = sum(counts, Counts())
    defined = [c for c in counts if not c.empty]

    def mean(values: Iterable[float | None]) -> float | None:
        present = [v for v in values if v is not None]
        return statistics.fmean(present) if present else None

    return SectionAggregate(
        tp=total.tp,
        fp=total.fp,
        fn=total.fn,
        precision=total.precision,
        recall=total.recall,
        f1=total.f1,
        macro_precision=mean(c.precision for c in defined),
        macro_recall=mean(c.recall for c in defined),
        macro_f1=mean(c.f1 for c in defined),
        macro_n=len(defined),
    )


def _passed(case: CaseResult) -> bool:
    return case.validation is not None and case.validation.passed


def _group(cases: Sequence[CaseResult], validation_ran: bool) -> GroupAggregate:
    scored = [c.score for c in cases if c.score is not None]
    states = [s for score in scored for s in score.states.values()]
    passed = sum(_passed(c) for c in cases) if validation_ran else None
    return GroupAggregate(
        n=len(cases),
        f1={
            section: _aggregate_section([s.sections[section] for s in scored]).f1
            for section in ITEM_SECTIONS
        },
        state_accuracy=_ratio(sum(s.correct for s in states), len(states)),
        validation_passed=passed,
        validation_pass_rate=_ratio(passed, len(cases)) if passed is not None else None,
    )


def aggregate(cases: Sequence[CaseResult], *, validation_ran: bool) -> RunSummary:
    """Dataset-level metrics over ``cases`` (skipped cases are excluded from everything)."""
    run = [c for c in cases if c.status != "skipped"]
    scored = [c.score for c in run if c.score is not None]

    sections = {
        name: _aggregate_section([s.sections[name] for s in scored]) for name in SCORED_SECTIONS
    }
    patient = _aggregate_section(
        [sum((s.sections[n].counts for n in PATIENT_SECTIONS), Counts()) for s in scored]
    )
    raw_sections = {
        name: _aggregate_section([c.raw_counts[name] for c in run if name in c.raw_counts])
        for name in ITEM_SECTIONS
    }
    methods: Counter[str] = Counter(
        m.method for s in scored for name in ITEM_SECTIONS for m in s.sections[name].matches
    )

    states: dict[str, StateAggregate] = {}
    critical: list[str] = []
    assurance: list[str] = []
    for section in ITEM_SECTIONS:
        confusion: dict[str, dict[str, int]] = {g: dict.fromkeys(STATES, 0) for g in STATES[:3]}
        correct = 0
        for case in run:
            if case.score is None:
                continue
            outcome = case.score.states[section]
            confusion[outcome.gold][outcome.pred] += 1
            correct += outcome.correct
            label = f"{case.case_id} {section} {outcome.gold}->{outcome.pred}"
            if (outcome.gold, outcome.pred) in CRITICAL_STATE_ERRORS:
                critical.append(label)
            if (outcome.gold, outcome.pred) == FALSE_ASSURANCE:
                assurance.append(label)
        n = sum(sum(row.values()) for row in confusion.values())
        states[section] = StateAggregate(
            n=n, correct=correct, accuracy=_ratio(correct, n), confusion=confusion
        )
    total_states = sum(s.n for s in states.values())

    fields: dict[str, dict[str, FieldAggregate]] = {}
    for section, checks in _FIELDS.items():
        fields[section] = {}
        for name in checks:
            tally = FieldTally()
            for s in scored:
                t = s.sections[section].fields.get(name)
                if t is not None:
                    tally.correct += t.correct
                    tally.lenient += t.lenient
                    tally.total += t.total
            fields[section][name] = FieldAggregate(
                n=tally.total,
                accuracy=_ratio(tally.correct, tally.total),
                lenient_accuracy=_ratio(tally.lenient, tally.total),
            )

    derived: dict[str, FieldAggregate] = {}
    for name in DERIVED_FIELDS:
        outcomes = [s.derived[name] for s in scored if name in s.derived]
        derived[name] = FieldAggregate(
            n=len(outcomes),
            accuracy=_ratio(sum(outcomes), len(outcomes)),
            lenient_accuracy=None,
        )

    grounding: Counter[str] = Counter()
    flags: Counter[str] = Counter()
    for case in run:
        grounding.update(case.grounding)
        flags.update(case.review_flags)

    validation_failures: dict[str, list[str]] = {}
    passed: int | None = None
    if validation_ran:
        passed = 0
        for case in run:
            if _passed(case):
                passed += 1
                continue
            validation_failures[case.case_id] = _failure_reasons(case)

    by_language: dict[str, list[CaseResult]] = defaultdict(list)
    by_format: dict[str, list[CaseResult]] = defaultdict(list)
    for case in run:
        by_language[case.language].append(case)
        by_format[case.format].append(case)

    return RunSummary(
        n_cases=len(cases),
        n_scored=len(scored),
        n_extraction_failed=sum(c.status == "extraction_failed" for c in cases),
        n_skipped=sum(c.status == "skipped" for c in cases),
        sections=sections,
        patient=patient,
        raw_sections=raw_sections,
        match_methods=dict(methods),
        states=states,
        state_accuracy=_ratio(sum(s.correct for s in states.values()), total_states),
        critical_state_errors=critical,
        false_assurance=assurance,
        fields=fields,
        derived=derived,
        grounding=dict(grounding),
        dropped_facts=sum(c.dropped for c in run),
        review_flags=dict(flags),
        assembly_attempted=sum(c.assembly_ok is not None for c in run),
        assembly_ok=sum(bool(c.assembly_ok) for c in run),
        validation_ran=validation_ran,
        validation_passed=passed,
        validation_pass_rate=_ratio(passed, len(run)) if passed is not None else None,
        validation_failures=validation_failures,
        by_language={k: _group(v, validation_ran) for k, v in sorted(by_language.items())},
        by_format={k: _group(v, validation_ran) for k, v in sorted(by_format.items())},
        usage=_usage(run),
    )


def _failure_reasons(case: CaseResult) -> list[str]:
    if case.status == "extraction_failed":
        return [f"extraction failed: {case.error}"]
    if not case.assembly_ok:
        return [f"assembly failed: {case.assembly_error}"]
    if case.validation is None:
        return ["not validated"]
    reasons = [
        f"{i.severity} {i.message_id or '-'} at {i.path}: {i.message[:160]}"
        for i in case.validation.issues
        if i.severity in ("error", "fatal")
    ]
    reasons += [f"unmatched Bundle.entry[{n}]" for n in case.validation.unmatched_entries]
    return reasons


def _usage(cases: Sequence[CaseResult]) -> UsageAggregate:
    records = [c.usage for c in cases if c.usage is not None]
    agg = UsageAggregate()
    latencies = [r.latency_s for r in records if r.latency_s is not None]
    for r in records:
        agg.input_tokens += r.input_tokens
        agg.output_tokens += r.output_tokens
        agg.cache_creation_input_tokens += r.cache_creation_input_tokens
        agg.cache_read_input_tokens += r.cache_read_input_tokens
        agg.extraction_cost_usd += r.cost_usd
        agg.judge_cost_usd += r.judge_cost_usd
        agg.judge_calls += r.judge_calls
        agg.fallbacks += int(r.fallback_used)
        agg.repair_attempts += max(0, r.attempts - 1)
    errors: Counter[str] = Counter(c.error for c in cases if c.error)
    agg.errors = dict(errors)
    agg.refusals = errors.get("ExtractionRefusedError", 0)
    agg.total_cost_usd = agg.extraction_cost_usd + agg.judge_cost_usd
    agg.cost_per_case_usd = agg.total_cost_usd / len(cases) if cases else None
    if latencies:
        agg.latency_mean_s = statistics.fmean(latencies)
        agg.latency_median_s = statistics.median(latencies)
        agg.latency_max_s = max(latencies)
    return agg
