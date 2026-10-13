"""D-10: birth date / sex from a Finnish personal identity code (``app.pipeline.derive``).

Codes used here are never real people's: DVV's published example ``131052-308T``, individual
numbers 900-999 (never issued by DVV), or 1840 birth dates with century sign ``+`` (nobody born
in 1840 was alive when the codes were introduced in 1964). Expected check characters come from
the independent `_code` helper below, not from the module under test.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

import pytest

from app.pipeline.derive import (
    apply_derivations,
    check_character,
    derive_patient_facts,
    parse_hetu,
)
from app.pipeline.ground import ReviewFlag, ReviewReason
from app.schemas.intermediate import (
    AdministrativeGender,
    DerivationMethod,
    DerivedBirthDate,
    DerivedGender,
    EnrichedIps,
    IdentifierRecognition,
    PatientExtraction,
)
from tests.assembly_cases import NEVER_ISSUED_HETU, build

_TABLE = "0123456789ABCDEFHJKLMNPRSTUVWXY"  # VNA 128/2010 § 2 (690/2022)


def _code(ddmmyy: str, sign: str, individual: int) -> str:
    """Independent HETU builder for the tests."""
    digits = f"{ddmmyy}{individual:03d}"
    return f"{ddmmyy}{sign}{individual:03d}{_TABLE[int(digits) % 31]}"


def _patient(
    *identifiers: dict[str, Any],
    birth_date: str | None = None,
    gender: str | None = None,
) -> PatientExtraction:
    def fact(quote: str, **extra: Any) -> dict[str, Any]:
        return {"source_quote": quote, "page": 1, "locator": "", "confidence": "high", **extra}

    return PatientExtraction.model_validate(
        {
            "names": [],
            "birth_date": fact(f"s. {birth_date}", value=birth_date) if birth_date else None,
            "gender": fact(f"sukupuoli {gender}", value=gender) if gender else None,
            "identifiers": list(identifiers),
        }
    )


def _ident(
    value: str, type_text: str = "Henkilötunnus", quote: str | None = None
) -> dict[str, Any]:
    return {
        "source_quote": quote if quote is not None else f"{type_text}: {value}".strip(": "),
        "page": 1,
        "locator": "",
        "value": value,
        "type_text": type_text,
        "issuer_text": "",
        "confidence": "high",
    }


# ---- parse_hetu --------------------------------------------------------------------------


def test_dvv_published_example() -> None:
    parsed = parse_hetu("131052-308T")
    assert parsed is not None
    assert parsed.birth_date == dt.date(1952, 10, 13)
    assert parsed.individual_number == 308
    assert parsed.sex is AdministrativeGender.FEMALE  # 308 is even
    assert check_character("131052308") == "T"


@pytest.mark.parametrize(
    ("sign", "year"),
    [
        ("+", 1840),
        ("-", 1940),
        *[(s, 1940) for s in "YXWVU"],
        *[(s, 2040) for s in "ABCDEF"],
    ],
)
def test_every_century_sign(sign: str, year: int) -> None:
    parsed = parse_hetu(_code("150340", sign, 947))
    assert parsed is not None
    assert parsed.birth_date == dt.date(year, 3, 15)


def test_leap_day_and_calendar_validation() -> None:
    assert parse_hetu(_code("290244", "-", 951)) is not None  # 1944 is a leap year
    assert parse_hetu(_code("290243", "-", 951)) is None
    assert parse_hetu(_code("310499", "-", 951)) is None
    assert parse_hetu(_code("001399", "-", 951)) is None


def test_invalid_check_character() -> None:
    valid = _code("150340", "-", 947)
    wrong = valid[:-1] + ("0" if valid[-1] != "0" else "1")
    assert parse_hetu(wrong) is None
    for letter in "GIOQZ":  # never check characters
        assert parse_hetu(valid[:-1] + letter) is None


@pytest.mark.parametrize(
    "value",
    [
        "",
        "131052308T",  # no century sign
        "131052*308T",  # unknown sign
        "131052-308",  # no check character
        "1310522-308T",
        "131052-308TT",
        "HETU 131052-308T",  # the value must be the code only
        "131052 -308T",
        "13105-2308T",
    ],
)
def test_malformed_input(value: str) -> None:
    assert parse_hetu(value) is None


def test_normalisation_of_case_dashes_and_whitespace() -> None:
    for value in (" 131052-308t ", "131052\u2013308T", "131052\u2212308T"):
        parsed = parse_hetu(value)
        assert parsed is not None
        assert parsed.code == "131052-308T"


def test_individual_numbers_000_and_001_are_never_issued() -> None:
    assert parse_hetu(_code("010140", "+", 0)) is None
    assert parse_hetu(_code("010140", "+", 1)) is None
    assert parse_hetu(_code("010140", "+", 2)) is not None


def test_sex_only_for_dvv_range_002_to_899() -> None:
    male, female = parse_hetu(_code("010140", "+", 123)), parse_hetu(_code("010140", "+", 124))
    assert male is not None
    assert male.sex is AdministrativeGender.MALE
    assert female is not None
    assert female.sex is AdministrativeGender.FEMALE
    for individual in (900, 947, 998, 999):
        temporary = parse_hetu(_code("010140", "+", individual))
        assert temporary is not None
        assert temporary.is_temporary
        assert temporary.sex is None  # synthetic/temporary: birth date only


def test_repr_hides_the_code() -> None:
    parsed = parse_hetu("131052-308T")
    assert "131052" not in repr(parsed)
    assert "308T" not in repr(parsed)


def test_check_character_rejects_non_digits() -> None:
    with pytest.raises(ValueError, match="nine digits"):
        check_character("13105230X")


# ---- derive_patient_facts ----------------------------------------------------------------


def test_no_identifier_derives_nothing() -> None:
    result = derive_patient_facts(_patient())
    assert result.derived.birth_date is None
    assert result.derived.gender is None
    assert result.flags == ()


def test_non_hetu_identifier_derives_nothing() -> None:
    result = derive_patient_facts(_patient(_ident("SYN-0042817", "MRN")))
    assert result.derived.birth_date is None
    assert result.flags == ()


def test_birth_date_from_temporary_code_without_sex() -> None:
    code = _code("120468", "-", 957)
    result = derive_patient_facts(_patient(_ident(code)))
    birth = result.derived.birth_date
    assert birth is not None
    assert birth.value == "1968-04-12"
    assert birth.derived is True
    assert birth.derivation.method is DerivationMethod.FI_HETU
    assert birth.derivation.source_path == "patient.identifiers[0]"
    assert birth.derivation.recognised_by is IdentifierRecognition.LABEL
    assert not birth.derivation.completes_stated
    assert result.derived.gender is None
    assert result.flags == (
        ReviewFlag(path="patient.birth_date", reason=ReviewReason.DERIVED_FROM_IDENTITY_CODE),
    )


def test_birth_date_and_sex_from_dvv_range_code() -> None:
    result = derive_patient_facts(_patient(_ident(NEVER_ISSUED_HETU, "hetu")))
    assert result.derived.birth_date is not None
    assert result.derived.birth_date.value == "1840-01-01"
    assert result.derived.gender is not None
    assert result.derived.gender.value is AdministrativeGender.MALE
    assert result.derived.gender.derivation.source_path == "patient.identifiers[0]"
    assert {f.path for f in result.flags} == {"patient.birth_date", "patient.gender"}
    assert {f.reason for f in result.flags} == {ReviewReason.DERIVED_FROM_IDENTITY_CODE}


@pytest.mark.parametrize(
    "label", ["Henkilötunnus", "HETU", "Hetu / Personbeteckning", "personbeteckning", "Sotu"]
)
def test_labels_recognised(label: str) -> None:
    result = derive_patient_facts(_patient(_ident(_code("150340", "-", 947), label)))
    assert result.derived.birth_date is not None
    assert result.derived.birth_date.derivation.recognised_by is IdentifierRecognition.LABEL


@pytest.mark.parametrize("label", ["", "id", "Patient ID"])
def test_unlabelled_or_generic_label_recognised_by_format(label: str) -> None:
    code = _code("150340", "-", 947)
    result = derive_patient_facts(_patient(_ident(code, label, quote=f"{label} {code}")))
    assert result.derived.birth_date is not None
    assert result.derived.birth_date.derivation.recognised_by is IdentifierRecognition.FORMAT


@pytest.mark.parametrize(
    "label", ["Personnummer", "CPR-nr", "Fødselsnummer", "SSN", "Swedish personal identity number"]
)
def test_other_countries_schemes_are_never_used(label: str) -> None:
    # Same shape and a valid mod-31 check character, but labelled as another scheme.
    result = derive_patient_facts(_patient(_ident(_code("150340", "-", 947), label)))
    assert result.derived.birth_date is None
    assert result.flags == ()


def test_value_must_occur_in_its_quote() -> None:
    code = _code("150340", "-", 947)
    other = _code("150340", "-", 949)
    result = derive_patient_facts(_patient(_ident(code, quote=f"Henkilötunnus: {other}")))
    assert result.derived.birth_date is None


def test_stated_full_birth_date_consistent_is_kept_without_flags() -> None:
    patient = _patient(_ident(_code("150340", "-", 947)), birth_date="1940-03-15")
    result = derive_patient_facts(patient)
    assert result.derived.birth_date is None
    assert result.flags == ()


def test_stated_birth_date_conflict_keeps_stated_and_flags() -> None:
    patient = _patient(_ident(_code("150340", "-", 947)), birth_date="1940-03-16")
    result = derive_patient_facts(patient)
    assert result.derived.birth_date is None
    assert result.flags == (
        ReviewFlag(path="patient.birth_date", reason=ReviewReason.IDENTITY_CODE_CONFLICT),
    )


@pytest.mark.parametrize("stated", ["1940", "1940-03"])
def test_consistent_partial_birth_date_is_completed(stated: str) -> None:
    patient = _patient(_ident(_code("150340", "-", 947)), birth_date=stated)
    result = derive_patient_facts(patient)
    birth = result.derived.birth_date
    assert birth is not None
    assert birth.value == "1940-03-15"
    assert birth.derivation.completes_stated
    assert result.flags == (
        ReviewFlag(path="patient.birth_date", reason=ReviewReason.DERIVED_FROM_IDENTITY_CODE),
    )
    assert patient.birth_date is not None
    assert patient.birth_date.value == stated  # the stated value is untouched


@pytest.mark.parametrize("stated", ["1941", "1940-04"])
def test_inconsistent_partial_birth_date_is_a_conflict(stated: str) -> None:
    patient = _patient(_ident(_code("150340", "-", 947)), birth_date=stated)
    result = derive_patient_facts(patient)
    assert result.derived.birth_date is None
    assert [f.reason for f in result.flags] == [ReviewReason.IDENTITY_CODE_CONFLICT]


def test_stated_gender_consistent_is_kept_without_flags() -> None:
    result = derive_patient_facts(_patient(_ident(NEVER_ISSUED_HETU), gender="male"))
    assert result.derived.gender is None
    assert all(f.path != "patient.gender" for f in result.flags)


@pytest.mark.parametrize("stated", ["female", "other"])
def test_stated_gender_conflict_keeps_stated_and_flags(stated: str) -> None:
    result = derive_patient_facts(_patient(_ident(NEVER_ISSUED_HETU), gender=stated))
    assert result.derived.gender is None
    assert (
        ReviewFlag(path="patient.gender", reason=ReviewReason.IDENTITY_CODE_CONFLICT)
        in result.flags
    )


def test_stated_gender_never_conflicts_with_a_temporary_code() -> None:
    # 900-999 carry no sex: an odd number next to a stated "female" is not a conflict.
    result = derive_patient_facts(_patient(_ident(_code("030352", "-", 919)), gender="female"))
    assert all(f.path != "patient.gender" for f in result.flags)


def test_multiple_identifiers_use_the_hetu() -> None:
    code = _code("150340", "-", 947)
    patient = _patient(_ident("SYN-0042817", "MRN"), _ident(code), _ident(code, "hetu"))
    result = derive_patient_facts(patient)
    assert result.derived.birth_date is not None
    assert result.derived.birth_date.derivation.source_path == "patient.identifiers[1]"


def test_different_codes_are_ambiguous() -> None:
    patient = _patient(_ident(_code("150340", "-", 947)), _ident(_code("160340", "-", 947)))
    result = derive_patient_facts(patient)
    assert result.derived.birth_date is None
    assert result.derived.gender is None
    assert result.flags == (
        ReviewFlag(path="patient.identifiers", reason=ReviewReason.IDENTITY_CODE_AMBIGUOUS),
    )


def test_derivation_logs_nothing(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.DEBUG):
        derive_patient_facts(_patient(_ident(NEVER_ISSUED_HETU)))
    assert caplog.records == []


def test_apply_derivations_sets_patient_derived_only() -> None:
    enriched = build()  # synthetic fixture: HETU 150372-9477, no birth date, gender stated
    updated, flags = apply_derivations(enriched)
    assert updated.patient == enriched.patient
    assert updated.patient_derived.birth_date is not None
    assert updated.patient_derived.birth_date.value == "1972-03-15"
    assert updated.patient_derived.gender is None
    assert [f.reason for f in flags] == [ReviewReason.DERIVED_FROM_IDENTITY_CODE]
    assert enriched.patient_derived.birth_date is None  # input not mutated
    round_trip = EnrichedIps.model_validate_json(updated.model_dump_json())
    assert round_trip.patient_derived == updated.patient_derived


# ---- enriched-layer models -----------------------------------------------------------------


def _derivation() -> dict[str, Any]:
    return {"method": "fi-hetu", "source_path": "patient.identifiers[0]", "recognised_by": "label"}


def test_derived_models_reject_partial_dates_and_non_binary_gender() -> None:
    with pytest.raises(ValueError, match="full date"):
        DerivedBirthDate.model_validate({"value": "1940", "derivation": _derivation()})
    with pytest.raises(ValueError, match="male or female"):
        DerivedGender.model_validate({"value": "other", "derivation": _derivation()})
    with pytest.raises(ValueError, match="Input should be True"):
        DerivedBirthDate.model_validate(
            {"value": "1940-03-15", "derived": False, "derivation": _derivation()}
        )
