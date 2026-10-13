"""Step 4b: deterministic derivation of patient facts from a Finnish personal identity code.

PLAN.md §7.1 D-10. Runs after grounding (``ground.apply_grounding``) and before assembly, on the
grounded ``PatientExtraction``: only identifiers whose quote was verified in the document are
used. Pure functions, no I/O, **no logging**: identity codes and the values derived from them
are PHI (CLAUDE.md). Results go to ``EnrichedIps.patient_derived`` (never into the LLM layer)
plus review flags for the review UI (Phase 3).

The Finnish personal identity code (henkilötunnus, HETU; sv. personbeteckning)
----------------------------------------------------------------------------------
Verified 2026-10-13 against:

* Valtioneuvoston asetus väestötietojärjestelmästä 128/2010, § 2 as amended by 690/2022 (in
  force 2023-01-01), https://finlex.fi/api/media/statute/17253/mainPdf/main.pdf : the code is
  ``DDMMYY`` + century sign + three-digit individual number + check character. Century sign
  ``+`` = 1800s; ``-`` or ``Y X W V U`` = 1900s; ``A B C D E F`` = 2000s. The individual
  number "on miespuolisilla pariton ja naispuolisilla parillinen" (odd for men, even for
  women). Check character = the nine-digit number ``DDMMYYNNN`` mod 31 indexed into
  ``0123456789ABCDEFHJKLMNPRSTUVWXY`` (no G, I, O, Q, Z).
* DVV, https://dvv.fi/henkilotunnus and https://dvv.fi/en/personal-identity-code : "in
  practice, all individual numbers issued are between 002 and 899"; worked example
  ``131052-308T``.
* Reform: government proposal HE 132/2022 would have issued gender-neutral codes from
  2027-01-01 (https://vm.fi/hanke?tunnus=VM183%3A00%2F2020). The bill **lapsed in Parliament
  in February 2023** (Finance Finland, https://www.finanssiala.fi/aiheet/henkilotunnusten-uudistaminen/,
  updated 2025-01-17); the new century signs came by the decree above instead. No enacted
  gender-neutral code was found as of 2026-10-13, so under the law in force the parity of
  002-899 encodes the registered sex.

Decisions
---------
* **Recognition.** An identifier is taken as a HETU when its value (trimmed, NFKC, Unicode
  dashes as ``-``, upper-cased) has the syntax above, a real calendar date, individual number
  002-999 and the right check character, **and** its value occurs in its own grounded
  ``source_quote`` (normalised as in grounding). ``recognised_by`` is ``label`` when the
  type/issuer text names the code (henkilötunnus, hetu, sotu, personbeteckning, "personal
  identity code", ...), else ``format``. An identifier labelled with another country's scheme
  (personnummer, CPR, fødselsnummer, SSN, "Swedish ...", ...; checked first) is never used:
  a Swedish personnummer ``YYMMDD-NNNC`` has the same shape and passes the mod-31 check about
  once in 31. A HETU written without any label is accepted on format; such a false positive
  stays possible, which is one reason every derived value is flagged for review.
* **Several codes.** If the recognised identifiers hold more than one distinct code, nothing
  is derived and ``patient.identifiers`` is flagged ``identity_code_ambiguous``. The same code
  repeated is one code (the first identifier is the source).
* **Birth date** is derived from any valid code, including individual numbers 900-999
  (temporary/test codes; the eval dataset uses only those, so they must be accepted). The date
  is a structural part of the code, and every derived value is flagged for confirmation.
* **Sex** is derived only for individual numbers **002-899** (DVV-issued codes, statutory
  parity rule). 900-999 are not issued by DVV and the parity rule is not defined for them,
  so no sex is derived. Caveat: should a gender-neutral reform be enacted later, its codes
  could not be told apart by format; ``SEX_FROM_PARITY`` is the single switch to turn this
  off, and every derived sex is flagged ``derived_from_identity_code`` for the reviewer.
* **Stated values win.** A stated full birth date or a stated gender is never overwritten. If
  the code disagrees, the stated value is kept and the field is flagged
  ``identity_code_conflict``. A stated *partial* birth date (``YYYY`` / ``YYYY-MM``) that is a
  prefix of the derived date is completed from the code (``completes_stated``; flagged as
  derived); an inconsistent partial date is a conflict.
"""

from __future__ import annotations

import datetime as dt
import re
import unicodedata
from dataclasses import dataclass
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from app.pipeline.ground import ReviewFlag, ReviewReason, normalise
from app.schemas.intermediate import (
    AdministrativeGender,
    Derivation,
    DerivationMethod,
    DerivedBirthDate,
    DerivedGender,
    EnrichedIps,
    IdentifierRecognition,
    PatientDerivations,
    PatientExtraction,
    PatientIdentifier,
)

__all__ = [
    "CHECK_CHARACTERS",
    "SEX_FROM_PARITY",
    "FinnishIdentityCode",
    "PatientDerivationResult",
    "apply_derivations",
    "check_character",
    "derive_patient_facts",
    "parse_hetu",
]

CHECK_CHARACTERS: Final = "0123456789ABCDEFHJKLMNPRSTUVWXY"
"""Check character for remainders 0-30 (VNA 128/2010 § 2)."""

SEX_FROM_PARITY: Final = True
"""Derive sex from the parity of individual numbers 002-899 (see module docstring)."""

_CENTURY: Final[dict[str, int]] = {
    "+": 1800,
    **dict.fromkeys("-YXWVU", 1900),
    **dict.fromkeys("ABCDEF", 2000),
}
_SYNTAX: Final = re.compile(r"(\d{2})(\d{2})(\d{2})([-+A-FU-Y])(\d{3})([0-9A-FHJ-NPR-Y])")
_DASHES: Final = str.maketrans(dict.fromkeys("\u2010\u2011\u2012\u2013\u2014\u2015\u2212", "-"))

_HETU_LABEL_PREFIXES: Final = (
    "henkilötunnu",
    "henkilotunnu",
    "hetu",
    "sotu",
    "sosiaaliturvatunnu",
    "personbeteckn",
)
_HETU_LABEL_PHRASES: Final = ("identity code", "identification code", "identity number")
_FOREIGN_LABEL_PREFIXES: Final = (
    "personnummer",
    "samordningsnummer",
    "cpr",
    "fødselsnummer",
    "fodselsnummer",
    "kennitala",
    "isikukood",
    "pesel",
    "bsn",
    "ssn",
    "nhs",
    "swedish",
    "danish",
    "norwegian",
    "icelandic",
    "estonian",
)
_FOREIGN_LABEL_PHRASES: Final = ("social security",)


@dataclass(frozen=True, slots=True)
class FinnishIdentityCode:
    """A syntactically valid HETU. Never log or print instances (PHI)."""

    code: str
    """Normalised code (upper case, ASCII hyphen)."""
    birth_date: dt.date
    individual_number: int

    @property
    def is_temporary(self) -> bool:
        """900-999: not issued by DVV (temporary/test codes)."""
        return self.individual_number >= 900

    @property
    def sex(self) -> AdministrativeGender | None:
        """Registered sex by parity, only for DVV-issued numbers 002-899."""
        if self.is_temporary or not SEX_FROM_PARITY:
            return None
        if self.individual_number % 2:
            return AdministrativeGender.MALE
        return AdministrativeGender.FEMALE

    def __repr__(self) -> str:  # keep the code out of tracebacks and debug output
        return "FinnishIdentityCode(<redacted>)"


def check_character(nine_digits: str) -> str:
    """Check character of ``DDMMYYNNN`` (birth date digits + individual number)."""
    if not re.fullmatch(r"\d{9}", nine_digits):
        raise ValueError("expected nine digits")
    return CHECK_CHARACTERS[int(nine_digits) % 31]


def _normalise_code(value: str) -> str:
    return unicodedata.normalize("NFKC", value).translate(_DASHES).strip().upper()


def parse_hetu(value: str) -> FinnishIdentityCode | None:
    """The code in ``value`` if it is a valid HETU (syntax, calendar date, individual number
    002-999, check character), else ``None``. The whole value must be the code."""
    code = _normalise_code(value)
    match = _SYNTAX.fullmatch(code)
    if match is None:
        return None
    day, month, year, sign, individual, check = match.groups()
    number = int(individual)
    if number < 2:  # 000 and 001 are never issued
        return None
    if check_character(day + month + year + individual) != check:
        return None
    try:
        birth = dt.date(_CENTURY[sign] + int(year), int(month), int(day))
    except ValueError:
        return None
    return FinnishIdentityCode(code=code, birth_date=birth, individual_number=number)


# --------------------------------------------------------------------------------------------
# Derivation
# --------------------------------------------------------------------------------------------


class PatientDerivationResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    derived: PatientDerivations = Field(default_factory=PatientDerivations)
    flags: tuple[ReviewFlag, ...] = ()


def _label_kind(identifier: PatientIdentifier) -> IdentifierRecognition | None:
    """``label`` / ``format`` / ``None`` (labelled as another country's scheme)."""
    label = normalise(" ".join(t for t in (identifier.type_text, identifier.issuer_text) if t))
    tokens = re.findall(r"\w+", label)
    if any(t.startswith(_FOREIGN_LABEL_PREFIXES) for t in tokens) or any(
        p in label for p in _FOREIGN_LABEL_PHRASES
    ):
        return None
    if any(t.startswith(_HETU_LABEL_PREFIXES) for t in tokens) or any(
        p in label for p in _HETU_LABEL_PHRASES
    ):
        return IdentifierRecognition.LABEL
    return IdentifierRecognition.FORMAT


def _recognise(
    identifier: PatientIdentifier,
) -> tuple[FinnishIdentityCode, IdentifierRecognition] | None:
    recognised_by = _label_kind(identifier)
    if recognised_by is None:
        return None
    parsed = parse_hetu(identifier.value)
    if parsed is None or normalise(parsed.code) not in normalise(identifier.source_quote):
        return None
    return parsed, recognised_by


def derive_patient_facts(patient: PatientExtraction) -> PatientDerivationResult:
    """Derive birth date / sex from the patient's Finnish personal identity code (module
    docstring). ``patient`` must be the *grounded* extraction's patient."""
    found: list[tuple[int, FinnishIdentityCode, IdentifierRecognition]] = []
    for index, identifier in enumerate(patient.identifiers):
        recognised = _recognise(identifier)
        if recognised is not None:
            found.append((index, *recognised))
    if not found:
        return PatientDerivationResult()
    if len({code.code for _, code, _ in found}) > 1:
        flag = ReviewFlag(path="patient.identifiers", reason=ReviewReason.IDENTITY_CODE_AMBIGUOUS)
        return PatientDerivationResult(flags=(flag,))

    index, code, recognised_by = found[0]
    source_path = f"patient.identifiers[{index}]"
    flags: list[ReviewFlag] = []

    birth_date: DerivedBirthDate | None = None
    derived_date = code.birth_date.isoformat()
    stated_date = patient.birth_date.value if patient.birth_date else None
    if stated_date is None or (len(stated_date) < 10 and derived_date.startswith(stated_date)):
        birth_date = DerivedBirthDate(
            value=derived_date,
            derivation=Derivation(
                method=DerivationMethod.FI_HETU,
                source_path=source_path,
                recognised_by=recognised_by,
                completes_stated=stated_date is not None,
            ),
        )
        flags.append(
            ReviewFlag(path="patient.birth_date", reason=ReviewReason.DERIVED_FROM_IDENTITY_CODE)
        )
    elif stated_date != derived_date:
        flags.append(
            ReviewFlag(path="patient.birth_date", reason=ReviewReason.IDENTITY_CODE_CONFLICT)
        )

    gender: DerivedGender | None = None
    sex = code.sex
    if sex is not None:
        if patient.gender is None:
            gender = DerivedGender(
                value=sex,
                derivation=Derivation(
                    method=DerivationMethod.FI_HETU,
                    source_path=source_path,
                    recognised_by=recognised_by,
                ),
            )
            flags.append(
                ReviewFlag(path="patient.gender", reason=ReviewReason.DERIVED_FROM_IDENTITY_CODE)
            )
        elif patient.gender.value is not sex:
            flags.append(
                ReviewFlag(path="patient.gender", reason=ReviewReason.IDENTITY_CODE_CONFLICT)
            )

    return PatientDerivationResult(
        derived=PatientDerivations(birth_date=birth_date, gender=gender), flags=tuple(flags)
    )


def apply_derivations(enriched: EnrichedIps) -> tuple[EnrichedIps, tuple[ReviewFlag, ...]]:
    """``enriched`` with ``patient_derived`` (re)computed from its patient, plus the flags."""
    result = derive_patient_facts(enriched.patient)
    return enriched.model_copy(update={"patient_derived": result.derived}), result.flags
