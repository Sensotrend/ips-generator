"""Helpers for authoring gold extractions (``IpsExtraction``, schema 1.1.1) in case modules.

Every helper returns a plain dict in the exact JSON shape the LLM produces (absent text is ``""``,
absent enums are ``"not_stated"``), with ``page``/``locator`` left as placeholders. The builder
(`build.py`) resolves ``page``/``locator`` by locating each ``source_quote`` in the ingested
document, so authors only write the verbatim quote. ``nth`` selects the n-th occurrence (0-based,
in document order) and must be given when the quote text occurs more than once (the builder
rejects ambiguous quotes).
"""

from __future__ import annotations

from typing import Any

from app.pipeline.derive import check_character  # backend/ is on sys.path (see build.py)

Fact = dict[str, Any]

NO_INFO: Fact = {"kind": "no_information"}


def _prov(quote: str, nth: int | None) -> Fact:
    return {"source_quote": quote, "page": 0, "locator": "", "_nth": nth}


# ---- patient -------------------------------------------------------------------------------


def name(
    quote: str,
    text: str | None = None,
    family: str = "",
    given: list[str] | None = None,
    confidence: str = "high",
    nth: int | None = None,
) -> Fact:
    return {
        **_prov(quote, nth),
        "text": text if text is not None else quote,
        "family": family,
        "given": given or [],
        "confidence": confidence,
    }


def ident(
    quote: str,
    value: str,
    type_text: str = "",
    issuer_text: str = "",
    confidence: str = "high",
    nth: int | None = None,
) -> Fact:
    return {
        **_prov(quote, nth),
        "value": value,
        "type_text": type_text,
        "issuer_text": issuer_text,
        "confidence": confidence,
    }


def birth(quote: str, value: str, confidence: str = "high", nth: int | None = None) -> Fact:
    return {**_prov(quote, nth), "value": value, "confidence": confidence}


def gender(quote: str, value: str, confidence: str = "high", nth: int | None = None) -> Fact:
    return {**_prov(quote, nth), "value": value, "confidence": confidence}


def patient(
    names: list[Fact] | None = None,
    birth_date: Fact | None = None,
    gender: Fact | None = None,
    identifiers: list[Fact] | None = None,
) -> Fact:
    return {
        "names": names or [],
        "birth_date": birth_date,
        "gender": gender,
        "identifiers": identifiers or [],
    }


# ---- allergies -----------------------------------------------------------------------------


def reaction(*manifestations: str, severity: str = "not_stated") -> Fact:
    return {"manifestations": list(manifestations), "severity": severity}


def allergy(
    quote: str,
    substance: str,
    *,
    code: str = "",
    code_system: str = "",
    type: str = "not_stated",
    category: str = "not_stated",
    criticality: str = "not_stated",
    clinical_status: str = "not_stated",
    verification_status: str = "not_stated",
    onset: str = "",
    reactions: list[Fact] | None = None,
    note: str = "",
    confidence: str = "high",
    nth: int | None = None,
) -> Fact:
    return {
        **_prov(quote, nth),
        "substance_text": substance,
        "printed_code": code,
        "printed_code_system_text": code_system,
        "type": type,
        "category": category,
        "criticality": criticality,
        "clinical_status": clinical_status,
        "verification_status": verification_status,
        "onset": onset,
        "reactions": reactions or [],
        "note": note,
        "confidence": confidence,
    }


def nka_statement(quote: str, scope: str, confidence: str = "high", nth: int | None = None) -> Fact:
    """A scoped "no known ..." statement inside allergies ``items_found`` (D-7)."""
    return {**_prov(quote, nth), "confidence": confidence, "scope": scope}


def allergies_found(items: list[Fact], statements: list[Fact] | None = None) -> Fact:
    return {"kind": "items_found", "items": items, "none_known_statements": statements or []}


def no_known_allergies(
    quote: str, scope: str, confidence: str = "high", nth: int | None = None
) -> Fact:
    return {"kind": "none_known", **_prov(quote, nth), "confidence": confidence, "scope": scope}


# ---- medications ---------------------------------------------------------------------------


def dosage(
    text: str = "",
    dose: str = "",
    unit: str = "",
    freq: str = "",
    period: str = "",
    period_unit: str = "not_stated",
    prn: bool = False,
    route: str = "",
) -> Fact:
    return {
        "text": text,
        "dose_value": dose,
        "dose_unit": unit,
        "frequency": freq,
        "period": period,
        "period_unit": period_unit,
        "as_needed": prn,
        "route_text": route,
    }


def daily(text: str, dose: str, unit: str, freq: str, route: str = "") -> Fact:
    """Shorthand for ``dose unit, freq times per 1 day``."""
    return dosage(text, dose, unit, freq, "1", "d", False, route)


def med(
    quote: str,
    text: str,
    *,
    code: str = "",
    code_system: str = "",
    strength: str = "",
    form: str = "",
    dose: Fact | None = None,
    status: str = "active",
    start: str = "",
    end: str = "",
    reason: str = "",
    note: str = "",
    confidence: str = "high",
    nth: int | None = None,
) -> Fact:
    return {
        **_prov(quote, nth),
        "medication_text": text,
        "printed_code": code,
        "printed_code_system_text": code_system,
        "strength_text": strength,
        "dose_form_text": form,
        "dosage": dose or dosage(),
        "status": status,
        "effective_start": start,
        "effective_end": end,
        "reason_text": reason,
        "note": note,
        "confidence": confidence,
    }


# ---- problems ------------------------------------------------------------------------------


def cond(
    quote: str,
    text: str,
    *,
    code: str = "",
    code_system: str = "",
    status: str = "not_stated",
    verification: str = "not_stated",
    severity: str = "not_stated",
    body_site: str = "",
    onset: str = "",
    abatement: str = "",
    note: str = "",
    confidence: str = "high",
    nth: int | None = None,
) -> Fact:
    return {
        **_prov(quote, nth),
        "condition_text": text,
        "printed_code": code,
        "printed_code_system_text": code_system,
        "clinical_status": status,
        "verification_status": verification,
        "severity": severity,
        "body_site_text": body_site,
        "onset": onset,
        "abatement": abatement,
        "note": note,
        "confidence": confidence,
    }


# ---- sections ------------------------------------------------------------------------------


def found(*items: Fact) -> Fact:
    return {"kind": "items_found", "items": list(items)}


def none_known(quote: str, confidence: str = "high", nth: int | None = None) -> Fact:
    return {"kind": "none_known", **_prov(quote, nth), "confidence": confidence}


def extraction(
    language: str, pat: Fact, allergies: Fact, medications: Fact, problems: Fact
) -> Fact:
    return {
        "document_language": language,
        "patient": pat,
        "allergies": allergies,
        "medications": medications,
        "problems": problems,
    }


# ---- synthetic Finnish personal identity codes ---------------------------------------------

HETU_BIRTH_DATES: dict[str, str] = {}
"""Every code made by `hetu` -> the birth date it was made from (the authoring input). The
builder uses it as the *true* birth date of HETU-only cases (``meta.json`` ``expected_patient``),
independent of the pipeline's parser in ``app.pipeline.derive``."""


def hetu(birth: str, individual: int) -> str:
    """Synthetic Finnish personal identity code for ``birth`` (YYYY-MM-DD).

    Only individual numbers 900-999 (the range never issued to real people) are allowed. The
    check character comes from ``app.pipeline.derive.check_character`` (one implementation of
    the mod-31 table; the unit tests check it against DVV's published example).
    """
    if not 900 <= individual <= 999:
        raise ValueError("synthetic HETUs must use individual numbers 900-999")
    year, month, day = birth.split("-")
    century = {"18": "+", "19": "-", "20": "A"}[year[:2]]
    digits = f"{day}{month}{year[2:]}{individual:03d}"
    code = f"{day}{month}{year[2:]}{century}{individual:03d}{check_character(digits)}"
    HETU_BIRTH_DATES[code] = birth
    return code
