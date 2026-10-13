"""Live checks against tx.fhir.org (marked ``network``; skipped when it is unreachable).

Only well-known clinical terms and codes are sent (no document data). These pin the server
behaviour documented in `app.terminology.scopes` (verified 2026-10-13).
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from app.fhir.constants import SNOMED_CT
from app.pipeline.terminology import CodingLimits, code_enriched
from app.schemas.intermediate import EnrichedIps, ItemsFound
from app.terminology.client import TerminologyClient
from app.terminology.scopes import ATC, EDQM, ICD_10, SearchScope

pytestmark = pytest.mark.network

TX = "https://tx.fhir.org/r4"


@pytest.fixture(scope="module")
def tx() -> Iterator[TerminologyClient]:
    try:
        httpx.get(f"{TX}/metadata?_summary=true", timeout=10.0).raise_for_status()
    except httpx.HTTPError:
        pytest.skip("tx.fhir.org not reachable")
    with TerminologyClient(TX, min_interval_s=0.3) as client:
        yield client


@pytest.mark.parametrize(
    ("scope", "text", "system", "code"),
    [
        (SearchScope.PROBLEM, "Type 2 diabetes mellitus", SNOMED_CT, "44054006"),
        (SearchScope.ALLERGY_SUBSTANCE, "Peanut", SNOMED_CT, "762952008"),
        (SearchScope.MEDICINAL_PRODUCT, "Metformin", SNOMED_CT, "776713006"),
        (SearchScope.ATC, "metformin", ATC, "A10BA02"),
        (SearchScope.CLINICAL_FINDING, "urticaria", SNOMED_CT, "126485001"),
        (SearchScope.ROUTE, "oral", SNOMED_CT, "26643006"),
        (SearchScope.DOSE_FORM, "film-coated tablet", EDQM, "10221000"),
        (SearchScope.SEVERITY, "mild", SNOMED_CT, "255604002"),
    ],
)
def test_search_finds_known_term(
    tx: TerminologyClient, scope: SearchScope, text: str, system: str, code: str
) -> None:
    result = tx.search(scope, text, count=10)
    found = [(c.system, c.code) for c in result.concepts]
    assert (system, code) in found, found
    assert all(c.version for c in result.concepts)


def test_icd10_lookup(tx: TerminologyClient) -> None:
    found = tx.lookup(ICD_10, "E11.9")
    assert found.concept is not None
    assert found.concept.display.startswith("Type 2 diabetes mellitus")
    assert tx.lookup(ICD_10, "E11.99").concept is None


def test_atc_lookup(tx: TerminologyClient) -> None:
    found = tx.lookup(ATC, "A10BA02")
    assert found.concept is not None
    assert found.concept.display == "metformin"


def test_snomed_lookup_designations(tx: TerminologyClient) -> None:
    found = tx.lookup(SNOMED_CT, "91935009")
    assert found.concept is not None
    assert "Allergy to peanuts" in {d.value for d in found.concept.designations}


def test_validate_code_checks_display(tx: TerminologyClient) -> None:
    assert tx.validate_code(SNOMED_CT, "44054006", "Type 2 diabetes mellitus").result is True
    assert tx.validate_code(ICD_10, "E11.9", "Asthma").result is False


def test_deterministic_pass_on_english_terms(tx: TerminologyClient) -> None:
    from pathlib import Path

    data = EnrichedIps.model_validate_json(
        (
            Path(__file__).parents[1]
            / "fixtures"
            / "intermediate"
            / "enriched_discharge_summary_fi.json"
        ).read_text(encoding="utf-8")
    ).model_dump(mode="json")
    data["document_language"] = "en"
    for section in ("allergies", "medications", "problems"):
        for item in data[section]["items"]:
            item["codings"] = []
    data["problems"]["items"][0]["extracted"]["condition_text"] = "Type 2 diabetes mellitus"
    data["allergies"]["items"][0]["extracted"]["substance_text"] = "Peanut"
    result = code_enriched(EnrichedIps.model_validate(data), tx=tx, limits=CodingLimits())
    problems = result.enriched.problems
    assert isinstance(problems, ItemsFound)
    codes = {(c.system, c.code) for c in problems.items[0].codings_for("condition_text")}
    assert (SNOMED_CT, "44054006") in codes
    assert (ICD_10, "E11.9") not in codes  # printed code display differs: candidate only
    allergies = result.enriched.allergies
    assert isinstance(allergies, ItemsFound)
    assert [c.code for c in allergies.items[0].codings_for("substance_text")] == ["762952008"]
