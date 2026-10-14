"""Tests for step 4, deterministic grounding (app/pipeline/ground.py)."""

from __future__ import annotations

import copy
import json
import unicodedata
from pathlib import Path
from typing import Any

import pytest

from app.pipeline.ground import (
    FUZZY_THRESHOLD,
    GroundingReport,
    GroundingStatus,
    ReviewFlag,
    ReviewReason,
    apply_grounding,
    ground,
    iter_facts,
    normalise,
    printed_code_in_quote,
)
from app.pipeline.ingest import ingest
from app.schemas.intermediate import AllergiesFound, IpsExtraction, ItemsFound, NoInformation
from app.schemas.source import IngestedDocument, SourceSegment

FIXTURES = Path(__file__).parent.parent / "fixtures"
SOURCE = ingest((FIXTURES / "intermediate" / "discharge_summary_fi.txt").read_bytes(), "text/plain")
RAW: dict[str, Any] = json.loads(
    (FIXTURES / "intermediate" / "extraction_discharge_summary_fi.json").read_text(encoding="utf-8")
)

S = GroundingStatus


def raw() -> dict[str, Any]:
    return copy.deepcopy(RAW)


def with_quote(
    section: str, index: int, quote: str, locator: str | None = None, page: int = 1
) -> IpsExtraction:
    data = raw()
    item = data[section]["items"][index]
    item["source_quote"] = quote
    item["page"] = page
    if locator is not None:
        item["locator"] = locator
    return IpsExtraction.model_validate(data)


def status_of(extraction: IpsExtraction, path: str, doc: IngestedDocument = SOURCE) -> Any:
    fact = ground(extraction, doc).get(path)
    assert fact is not None
    return fact


def make_doc(*segments: tuple[int, str | None, str], media_type: str = "text/plain") -> Any:
    return IngestedDocument(
        media_type=media_type,
        segments=[SourceSegment(page=p, locator=loc, text=t) for p, loc, t in segments],
        page_count=max(p for p, _, _ in segments),
    )


def single_med_extraction(quote: str, locator: str = "", page: int = 1) -> IpsExtraction:
    data = raw()
    item = data["medications"]["items"][0]
    item.update(source_quote=quote, locator=locator, page=page)
    data["medications"]["items"] = [item]
    return IpsExtraction.model_validate(data)


# --------------------------------------------------------------------------------------------
# Normalisation and fact discovery
# --------------------------------------------------------------------------------------------


def test_normalise() -> None:
    decomposed = unicodedata.normalize("NFD", "Äijälä")
    assert normalise(f"  {decomposed}\u00a0\u2013  Öhman\n\u201cx\u201d  ") == 'äijälä - öhman "x"'
    assert normalise("\ufb01lm\u00adtabletti") == "filmtabletti"


def test_iter_facts_finds_every_quoted_fact() -> None:
    paths = [path for path, _ in iter_facts(IpsExtraction.model_validate(raw()))]
    assert paths == [
        "patient.names[0]",
        "patient.gender",
        "patient.identifiers[0]",
        "allergies.items[0]",
        "allergies.none_known_statements[0]",
        "medications.items[0]",
        "medications.items[1]",
        "medications.items[2]",
        "medications.items[3]",
        "problems.items[0]",
        "problems.items[1]",
        "problems.items[2]",
    ]


def test_iter_facts_includes_none_known_statements_and_birth_date() -> None:
    data = raw()
    data["medications"] = {
        "kind": "none_known",
        "source_quote": "Ei säännöllistä lääkitystä",
        "page": 1,
        "locator": "line 13",
        "confidence": "high",
    }
    data["patient"]["birth_date"] = {
        "source_quote": "150372",
        "page": 1,
        "locator": "line 3",
        "value": "1972-03-15",
        "confidence": "medium",
    }
    paths = [path for path, _ in iter_facts(IpsExtraction.model_validate(data))]
    assert "medications" in paths
    assert "patient.birth_date" in paths


# --------------------------------------------------------------------------------------------
# Ladder rungs
# --------------------------------------------------------------------------------------------


def test_fixture_is_fully_exact() -> None:
    report = ground(IpsExtraction.model_validate(raw()), SOURCE)
    expected = dict.fromkeys(GroundingStatus, 0) | {S.EXACT: 12}
    assert report.counts == expected
    assert report.all_grounded
    fact = report.get("allergies.items[0]")
    assert fact is not None
    assert (fact.found_page, fact.found_locator, fact.score) == (1, "line 6", 1.0)


def test_normalised_dash_case_and_whitespace() -> None:
    quote = "MAAPÄHKINÄ \u2013 urtikaria   ja huulten turvotus (2015)"
    fact = status_of(with_quote("allergies", 0, quote), "allergies.items[0]")
    assert fact.status is S.NORMALISED
    assert fact.found_locator == "line 6"


def test_normalised_finnish_decomposed_characters() -> None:
    quote = unicodedata.normalize("NFD", "Henkilötunnus: 150372-9477")
    assert quote != "Henkilötunnus: 150372-9477"
    data = raw()
    data["patient"]["identifiers"][0]["source_quote"] = quote
    fact = status_of(IpsExtraction.model_validate(data), "patient.identifiers[0]")
    assert fact.status is S.NORMALISED


def test_relocated_to_another_line() -> None:
    extraction = with_quote("medications", 1, "Ramipril 5 mg tabl 1 x 1 aamulla", locator="line 14")
    fact = status_of(extraction, "medications.items[1]")
    assert fact.status is S.RELOCATED
    assert (fact.stated_locator, fact.found_page, fact.found_locator) == ("line 14", 1, "line 15")


def test_relocated_to_unknown_locator() -> None:
    extraction = with_quote("medications", 1, "Ramipril 5 mg", locator="line 999")
    assert status_of(extraction, "medications.items[1]").found_locator == "line 15"


def test_relocated_across_pages() -> None:
    doc = ingest("Sivu 1: Esitiedot\n\fLääkitys: Atorvastatiini 20 mg\n".encode(), "text/plain")
    assert doc.page_count == 2
    extraction = single_med_extraction("Atorvastatiini 20 mg", locator="line 2", page=1)
    fact = status_of(extraction, "medications.items[0]", doc)
    assert fact.status is S.RELOCATED
    assert (fact.found_page, fact.found_locator) == (2, "line 2")


def test_quote_spanning_lines_exact_and_normalised() -> None:
    doc = ingest(b"Allergiat: Penisilliini -\nurtikaria ja huulten turvotus.\n", "text/plain")
    spanning = single_med_extraction("Penisilliini -\nurtikaria", locator="line 1")
    assert status_of(spanning, "medications.items[0]", doc).status is S.EXACT
    joined = single_med_extraction("Penisilliini - urtikaria ja", locator="line 1")
    assert status_of(joined, "medications.items[0]", doc).status is S.NORMALISED


def test_spanning_quote_must_start_in_stated_segment() -> None:
    doc = ingest(b"Allergiat: Penisilliini -\nurtikaria\n", "text/plain")
    extraction = single_med_extraction("Penisilliini - urtikaria", locator="line 2")
    fact = status_of(extraction, "medications.items[0]", doc)
    assert (fact.status, fact.found_locator) == (S.RELOCATED, "line 1")


def test_pdf_page_segments_without_locator() -> None:
    doc = make_doc(
        (1, None, "EPIKRIISI\nPotilas: Testi"),
        (2, None, "Lääkitys:\nMetformiini 500 mg\n1 x 2"),
        media_type="application/pdf",
    )
    exact = single_med_extraction("Metformiini 500 mg\n1 x 2", locator="", page=2)
    assert status_of(exact, "medications.items[0]", doc).status is S.EXACT
    moved = single_med_extraction("Metformiini 500 mg 1 x 2", locator="", page=1)
    fact = status_of(moved, "medications.items[0]", doc)
    assert (fact.status, fact.found_page, fact.found_locator) == (S.RELOCATED, 2, None)


def test_fuzzy_match_reports_score_and_location() -> None:
    quote = "Maapähknä - urtikaria ja huulten turvotus (2015)"  # one letter missing
    fact = status_of(with_quote("allergies", 0, quote, locator="line 8"), "allergies.items[0]")
    assert fact.status is S.FUZZY
    assert FUZZY_THRESHOLD <= fact.score < 1.0
    assert (fact.found_page, fact.found_locator) == (1, "line 6")


def test_fuzzy_with_extra_token() -> None:
    quote = "Ramipril 5 mg tabl 1 x 1 joka aamulla"
    fact = status_of(with_quote("medications", 1, quote, locator="line 15"), "medications.items[1]")
    assert fact.status is S.FUZZY


def test_fuzzy_never_changes_a_number() -> None:
    quote = "Ramipril 10 mg tabl 1 x 1 aamulla"  # the document says 5 mg
    fact = status_of(with_quote("medications", 1, quote, locator="line 15"), "medications.items[1]")
    assert fact.status is S.NOT_FOUND


def test_not_found() -> None:
    quote = "Amoksisilliini aiheutti ihottumaa"
    fact = status_of(with_quote("allergies", 0, quote), "allergies.items[0]")
    assert fact.status is S.NOT_FOUND
    assert fact.found_page is None
    assert fact.score < FUZZY_THRESHOLD


def test_short_quotes_are_never_fuzzy() -> None:
    data = raw()
    data["patient"]["gender"]["source_quote"] = "mis"  # vs "mies"
    fact = status_of(IpsExtraction.model_validate(data), "patient.gender")
    assert fact.status is S.NOT_FOUND


def test_csv_row_locators() -> None:
    doc = ingest((FIXTURES / "ingest" / "medications_semicolon.csv").read_bytes(), "text/csv")
    exact = single_med_extraction("Lääke: Bisoprololi | Vahvuus: 2,5 mg", locator="row 3")
    assert status_of(exact, "medications.items[0]", doc).status is S.EXACT
    moved = single_med_extraction("Bisoprololi | Vahvuus: 2,5 mg", locator="row 2")
    fact = status_of(moved, "medications.items[0]", doc)
    assert (fact.status, fact.found_locator) == (S.RELOCATED, "row 3")


def test_json_path_locators() -> None:
    doc = ingest((FIXTURES / "ingest" / "nested.json").read_bytes(), "application/json")
    exact = single_med_extraction("Simvastatin 20 mg", locator="$.medications[1].name")
    assert status_of(exact, "medications.items[0]", doc).status is S.EXACT
    moved = single_med_extraction("1 x 1 illalla", locator="$.medications[1].name")
    fact = status_of(moved, "medications.items[0]", doc)
    assert (fact.status, fact.found_locator) == (S.RELOCATED, "$.medications[1].dose")


# --------------------------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------------------------


def _report(*statuses: tuple[str, GroundingStatus], extraction: IpsExtraction) -> GroundingReport:
    """Report from `ground`, with selected facts overridden (to test the policy in isolation)."""
    overrides = dict(statuses)
    facts = []
    for fact in ground(extraction, SOURCE).facts:
        status = overrides.get(fact.path)
        if status is S.NOT_FOUND:
            fact = fact.model_copy(
                update={"status": status, "found_page": None, "found_locator": None}
            )
        elif status is not None:
            fact = fact.model_copy(update={"status": status})
        facts.append(fact)
    return GroundingReport(facts=tuple(facts))


def test_apply_drops_not_found_items_and_remaps_flags() -> None:
    extraction = IpsExtraction.model_validate(raw())
    before = extraction.model_dump()
    report = _report(
        ("medications.items[1]", S.NOT_FOUND),
        ("medications.items[3]", S.FUZZY),
        extraction=extraction,
    )
    result = apply_grounding(extraction, report)

    meds = result.extraction.medications
    assert isinstance(meds, ItemsFound)
    assert [m.medication_text for m in meds.items] == ["Metformin", "Panadol", "Simvastatiini"]
    assert result.dropped == ("medications.items[1]",)
    assert set(result.flags) == {
        ReviewFlag(path="medications.items[1]", reason=ReviewReason.DROPPED_NOT_FOUND),
        ReviewFlag(path="medications.items[2]", reason=ReviewReason.FUZZY_MATCH),
    }
    assert extraction.model_dump() == before  # input not mutated


def test_apply_empty_section_becomes_flagged_no_information() -> None:
    extraction = IpsExtraction.model_validate(raw())
    report = _report(("allergies.items[0]", S.NOT_FOUND), extraction=extraction)
    result = apply_grounding(extraction, report)
    assert isinstance(result.extraction.allergies, NoInformation)
    assert ReviewFlag(path="allergies", reason=ReviewReason.SECTION_UNVERIFIED) in result.flags


def test_apply_unverified_none_known_becomes_no_information() -> None:
    data = raw()
    data["medications"] = {
        "kind": "none_known",
        "source_quote": "Ei säännöllistä lääkitystä",  # not in the document
        "page": 1,
        "locator": "line 13",
        "confidence": "high",
    }
    extraction = IpsExtraction.model_validate(data)
    report = ground(extraction, SOURCE)
    assert report.get("medications") is not None
    result = apply_grounding(extraction, report)
    assert isinstance(result.extraction.medications, NoInformation)
    assert result.dropped == ("medications",)
    assert ReviewFlag(path="medications", reason=ReviewReason.SECTION_UNVERIFIED) in result.flags


def test_apply_optional_fact_set_to_none() -> None:
    data = raw()
    data["patient"]["birth_date"] = {
        "source_quote": "s. 15.03.1972",
        "page": 1,
        "locator": "line 2",
        "value": "1972-03-15",
        "confidence": "high",
    }
    extraction = IpsExtraction.model_validate(data)
    result = apply_grounding(extraction, ground(extraction, SOURCE))
    assert result.extraction.patient.birth_date is None
    assert result.dropped == ("patient.birth_date",)


def test_ungrounded_document_date_is_dropped_not_a_section() -> None:
    data = raw()
    data["document_date"] = {
        "source_quote": "Koontipäivä: 12.10.2026",
        "page": 1,
        "locator": "line 1",
        "value": "2026-10-12",
        "confidence": "high",
    }
    extraction = IpsExtraction.model_validate(data)
    report = ground(extraction, SOURCE)
    assert report.get("document_date") is not None
    result = apply_grounding(extraction, report)
    assert result.extraction.document_date is None
    assert result.dropped == ("document_date",)
    assert ReviewFlag(path="document_date", reason=ReviewReason.DROPPED_NOT_FOUND) in result.flags
    assert not any(f.reason is ReviewReason.SECTION_UNVERIFIED for f in result.flags)


def test_apply_relocated_corrects_location() -> None:
    extraction = with_quote("medications", 1, "Ramipril 5 mg tabl 1 x 1 aamulla", locator="line 3")
    result = apply_grounding(extraction, ground(extraction, SOURCE))
    meds = result.extraction.medications
    assert isinstance(meds, ItemsFound)
    assert meds.items[1].locator == "line 15"
    assert ReviewFlag(path="medications.items[1]", reason=ReviewReason.RELOCATED) in result.flags
    original = extraction.medications
    assert isinstance(original, ItemsFound)
    assert original.items[1].locator == "line 3"


def test_apply_all_grounded_is_identity() -> None:
    extraction = IpsExtraction.model_validate(raw())
    result = apply_grounding(extraction, ground(extraction, SOURCE))
    assert result.extraction == extraction
    assert result.flags == ()
    assert result.dropped == ()


@pytest.mark.parametrize("path", ["patient.names[0]", "patient.identifiers[0]"])
def test_apply_drops_patient_list_facts(path: str) -> None:
    extraction = IpsExtraction.model_validate(raw())
    result = apply_grounding(extraction, _report((path, S.NOT_FOUND), extraction=extraction))
    field = path.split(".")[1].split("[")[0]
    assert getattr(result.extraction.patient, field) == []


# --------------------------------------------------------------------------------------------
# Scoped "no known ..." statements inside allergies items_found (D-7)
# --------------------------------------------------------------------------------------------


def test_not_found_statement_is_dropped_and_items_kept() -> None:
    data = raw()
    data["allergies"]["none_known_statements"][0]["source_quote"] = "No known drug allergies"
    extraction = IpsExtraction.model_validate(data)
    report = ground(extraction, SOURCE)
    fact = report.get("allergies.none_known_statements[0]")
    assert fact is not None
    assert fact.status is S.NOT_FOUND

    result = apply_grounding(extraction, report)

    allergies = result.extraction.allergies
    assert isinstance(allergies, AllergiesFound)
    assert [a.substance_text for a in allergies.items] == ["Maapähkinä"]
    assert allergies.none_known_statements == []
    assert result.dropped == ("allergies.none_known_statements[0]",)
    assert result.flags == (
        ReviewFlag(
            path="allergies.none_known_statements[0]", reason=ReviewReason.DROPPED_NOT_FOUND
        ),
    )


def test_none_known_statement_never_matches_fuzzily() -> None:
    # The document says "no known *drug* allergies"; a near-identical quote claiming no known
    # allergies at all would widen the scope, so it must not survive as a fuzzy match.
    data = raw()
    statement = data["allergies"]["none_known_statements"][0]
    statement.update(source_quote="Ei tiedossa olevia allergioita", scope="all")
    fact = status_of(IpsExtraction.model_validate(data), "allergies.none_known_statements[0]")
    assert fact.status is S.NOT_FOUND


def test_relocated_statement_is_corrected_and_flagged() -> None:
    data = raw()
    data["allergies"]["none_known_statements"][0]["locator"] = "line 9"
    extraction = IpsExtraction.model_validate(data)
    result = apply_grounding(extraction, ground(extraction, SOURCE))
    allergies = result.extraction.allergies
    assert isinstance(allergies, AllergiesFound)
    assert allergies.none_known_statements[0].locator == "line 6"
    path = "allergies.none_known_statements[0]"
    assert result.flags == (ReviewFlag(path=path, reason=ReviewReason.RELOCATED),)


def test_all_items_dropped_makes_section_unverified_despite_statement() -> None:
    extraction = IpsExtraction.model_validate(raw())
    report = _report(("allergies.items[0]", S.NOT_FOUND), extraction=extraction)
    result = apply_grounding(extraction, report)
    assert isinstance(result.extraction.allergies, NoInformation)
    assert ReviewFlag(path="allergies", reason=ReviewReason.SECTION_UNVERIFIED) in result.flags


# --------------------------------------------------------------------------------------------
# Printed codes (D-9)
# --------------------------------------------------------------------------------------------


def test_fixture_printed_codes_are_kept() -> None:
    extraction = IpsExtraction.model_validate(raw())
    result = apply_grounding(extraction, ground(extraction, SOURCE))
    meds, problems = result.extraction.medications, result.extraction.problems
    assert isinstance(meds, ItemsFound)
    assert isinstance(problems, ItemsFound)
    assert (meds.items[0].printed_code, meds.items[0].printed_code_system_text) == (
        "A10BA02",
        "ATC",
    )
    assert (problems.items[0].printed_code, problems.items[0].printed_code_system_text) == (
        "E11.9",
        None,
    )


@pytest.mark.parametrize(
    ("section", "index", "code"),
    [
        ("problems", 1, "I10"),  # supplied from knowledge: not printed next to the entry
        ("problems", 0, "E11"),  # only part of the printed "E11.9"
        ("medications", 1, "C09AA05"),
        ("allergies", 0, "T78.1"),
    ],
)
def test_printed_code_not_in_quote_is_cleared_and_flagged(
    section: str, index: int, code: str
) -> None:
    data = raw()
    item = data[section]["items"][index]
    item["printed_code"] = code
    item["printed_code_system_text"] = "ICD-10"
    extraction = IpsExtraction.model_validate(data)

    result = apply_grounding(extraction, ground(extraction, SOURCE))

    grounded = getattr(result.extraction, section)
    assert isinstance(grounded, ItemsFound)
    kept = grounded.items[index]
    assert (kept.printed_code, kept.printed_code_system_text) == (None, None)
    path = f"{section}.items[{index}]"
    assert result.flags == (ReviewFlag(path=path, reason=ReviewReason.PRINTED_CODE_NOT_IN_QUOTE),)
    assert result.dropped == ()


def test_printed_code_flag_uses_grounded_path() -> None:
    data = raw()
    data["problems"]["items"][2]["printed_code"] = "G47.3"  # not in the quote
    extraction = IpsExtraction.model_validate(data)
    report = _report(("problems.items[0]", S.NOT_FOUND), extraction=extraction)
    result = apply_grounding(extraction, report)
    path = "problems.items[1]"  # was items[2] before items[0] was dropped
    assert ReviewFlag(path=path, reason=ReviewReason.PRINTED_CODE_NOT_IN_QUOTE) in result.flags


def test_system_text_without_code_is_cleared() -> None:
    data = raw()
    data["problems"]["items"][1]["printed_code_system_text"] = "ICD-10"
    extraction = IpsExtraction.model_validate(data)
    result = apply_grounding(extraction, ground(extraction, SOURCE))
    problems = result.extraction.problems
    assert isinstance(problems, ItemsFound)
    assert problems.items[1].printed_code_system_text is None
    assert result.flags == ()


@pytest.mark.parametrize(
    ("code", "quote", "expected"),
    [
        ("E11.9", "Tyypin 2 diabetes (E11.9), todettu 2018", True),
        ("e11.9", "Tyypin 2 diabetes (E11.9)", True),  # normalised like quotes
        ("E11.9", "Diagnoosi: E11.9.", True),
        ("E11", "Tyypin 2 diabetes (E11.9)", False),  # part of a longer code
        ("11.9", "Tyypin 2 diabetes (E11.9)", False),
        ("1", "Tyypin 2 diabetes (E11.9)", False),
        ("A10BA0", "Metformin (ATC A10BA02)", False),
        ("", "anything", False),
    ],
)
def test_printed_code_in_quote(code: str, quote: str, expected: bool) -> None:
    assert printed_code_in_quote(code, quote) is expected
