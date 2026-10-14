"""Helpers for authoring gold extractions (``IpsExtraction``, schema 1.4.0) in case modules.

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


def document_date(
    quote: str, value: str, confidence: str = "high", nth: int | None = None
) -> Fact:
    """The date the document states for itself (``document_date``, schema 1.3.0)."""
    return {**_prov(quote, nth), "value": value, "confidence": confidence}


def gender(quote: str, value: str, confidence: str = "high", nth: int | None = None) -> Fact:
    return {**_prov(quote, nth), "value": value, "confidence": confidence}


def contact(
    quote: str,
    name_text: str,
    *,
    relationship: str = "",
    phone: str = "",
    confidence: str = "high",
    nth: int | None = None,
) -> Fact:
    """A contact person of the patient (``patient.contacts``)."""
    return {
        **_prov(quote, nth),
        "name_text": name_text,
        "relationship_text": relationship,
        "phone": phone,
        "confidence": confidence,
    }


def patient(
    names: list[Fact] | None = None,
    birth_date: Fact | None = None,
    gender: Fact | None = None,
    identifiers: list[Fact] | None = None,
    contacts: list[Fact] | None = None,
) -> Fact:
    return {
        "names": names or [],
        "birth_date": birth_date,
        "gender": gender,
        "identifiers": identifiers or [],
        "contacts": contacts or [],
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


# ---- optional sections (schema 1.2.0) ------------------------------------------------------


def vital(
    quote: str,
    kind: str,
    value: str,
    *,
    unit: str = "",
    diastolic: str = "",
    effective: str = "",
    note: str = "",
    confidence: str = "high",
    nth: int | None = None,
) -> Fact:
    return {
        **_prov(quote, nth),
        "kind": kind,
        "value": value,
        "diastolic": diastolic,
        "unit_text": unit,
        "effective": effective,
        "note": note,
        "confidence": confidence,
    }


def social(
    quote: str,
    kind: str,
    use_text: str,
    *,
    tobacco_status: str = "not_stated",
    date: str = "",
    confidence: str = "high",
    nth: int | None = None,
) -> Fact:
    return {
        **_prov(quote, nth),
        "kind": kind,
        "tobacco_status": tobacco_status,
        "use_text": use_text,
        "date": date,
        "confidence": confidence,
    }


def vaccine(
    quote: str,
    vaccine_text: str,
    *,
    occurrence: str = "",
    status: str = "completed",
    code: str = "",
    code_system: str = "",
    note: str = "",
    confidence: str = "high",
    nth: int | None = None,
) -> Fact:
    return {
        **_prov(quote, nth),
        "vaccine_text": vaccine_text,
        "printed_code": code,
        "printed_code_system_text": code_system,
        "status": status,
        "occurrence": occurrence,
        "note": note,
        "confidence": confidence,
    }


def pregnancy_fact(
    quote: str,
    kind: str,
    *,
    status: str = "not_stated",
    date: str = "",
    count: str = "",
    note: str = "",
    confidence: str = "high",
    nth: int | None = None,
) -> Fact:
    return {
        **_prov(quote, nth),
        "kind": kind,
        "status": status,
        "date": date,
        "count": count,
        "note": note,
        "confidence": confidence,
    }


# ---- results, procedures, devices (schema 1.4.0) -------------------------------------------


def result(
    quote: str,
    test: str,
    *,
    value: str = "",
    comparator: str = "not_stated",
    value_text: str = "",
    unit: str = "",
    effective: str = "",
    category: str = "laboratory",
    note: str = "",
    confidence: str = "high",
    nth: int | None = None,
) -> Fact:
    return {
        **_prov(quote, nth),
        "category": category,
        "test_text": test,
        "value": value,
        "comparator": comparator,
        "value_text": value_text,
        "unit_text": unit,
        "effective": effective,
        "note": note,
        "confidence": confidence,
    }


def procedure(
    quote: str,
    procedure_text: str,
    *,
    performed: str = "",
    site: str = "",
    note: str = "",
    confidence: str = "high",
    nth: int | None = None,
) -> Fact:
    return {
        **_prov(quote, nth),
        "procedure_text": procedure_text,
        "body_site_text": site,
        "performed": performed,
        "note": note,
        "confidence": confidence,
    }


def device(
    quote: str,
    device_text: str,
    *,
    brand: str = "",
    note: str = "",
    confidence: str = "high",
    nth: int | None = None,
) -> Fact:
    return {
        **_prov(quote, nth),
        "device_text": device_text,
        "brand_text": brand,
        "note": note,
        "confidence": confidence,
    }


def extraction(
    language: str,
    pat: Fact,
    allergies: Fact,
    medications: Fact,
    problems: Fact,
    *,
    vital_signs: list[Fact] | None = None,
    social_history: list[Fact] | None = None,
    immunizations: list[Fact] | None = None,
    pregnancy: list[Fact] | None = None,
    results: list[Fact] | None = None,
    procedures: list[Fact] | None = None,
    devices: list[Fact] | None = None,
) -> Fact:
    return {
        "document_language": language,
        "patient": pat,
        "allergies": allergies,
        "medications": medications,
        "problems": problems,
        "vital_signs": vital_signs or [],
        "social_history": social_history or [],
        "immunizations": immunizations or [],
        "pregnancy": pregnancy or [],
        "results": results or [],
        "procedures": procedures or [],
        "devices": devices or [],
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
