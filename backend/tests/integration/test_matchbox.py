"""Validate fixture Bundles in a running Matchbox (skipped when Matchbox is unreachable).

Start it with ``docker compose -f infra/docker-compose.yml up -d matchbox``.
"""

import json
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from app.config import get_settings
from app.fhir.models import Bundle
from app.pipeline.validate import MatchboxClient

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).parents[1] / "fixtures"
BUNDLES = sorted((FIXTURES / "ips-examples").glob("*.json")) + sorted(
    (FIXTURES / "ips-variants").glob("*.json")
)


@pytest.fixture(scope="module")
def matchbox() -> Iterator[MatchboxClient]:
    base_url = get_settings().matchbox_url.rstrip("/")
    try:
        httpx.get(f"{base_url}/metadata", timeout=5.0).raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"Matchbox not reachable at {base_url}")
    with MatchboxClient(base_url) as client:
        yield client


@pytest.mark.parametrize("path", BUNDLES, ids=lambda p: p.name)
def test_fixture_bundle_is_valid_ips(matchbox: MatchboxClient, path: Path) -> None:
    bundle = Bundle.model_validate(json.loads(path.read_text(encoding="utf-8")))
    result = matchbox.validate(bundle)
    assert result.is_valid, [(i.path, i.message) for i in result.errors]
    # Every entry must be checked against its IPS profile (see validate.py module docstring).
    assert result.unmatched_bundle_entries == []


def test_text_only_codes_raise_no_code_issues(matchbox: MatchboxClient) -> None:
    """Phase 1 risk (PLAN §7.1): CodeableConcepts with only ``text`` are valid IPS 2.0.1."""
    path = FIXTURES / "ips-variants" / "Bundle-minimal-text-only-codes.json"
    result = matchbox.validate(json.loads(path.read_text(encoding="utf-8")))
    assert result.is_valid
    coded_paths = (".code", "medicationCodeableConcept")
    flagged = [
        i
        for i in result.issues
        if i.severity != "information"
        and any(i.path.endswith(p) for p in coded_paths)
        and "category" not in i.path
    ]
    assert flagged == []


def test_broken_entry_is_reported_only_as_unmatched_slice(matchbox: MatchboxClient) -> None:
    """Documents the Matchbox behaviour behind ``unmatched_bundle_entries``."""
    path = FIXTURES / "ips-variants" / "Bundle-minimal-known-absent.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    index = next(
        n
        for n, e in enumerate(raw["entry"])
        if e["resource"]["resourceType"] == "MedicationStatement"
    )
    del raw["entry"][index]["resource"]["_effectiveDateTime"]  # effective[x] is 1..1 in IPS
    result = matchbox.validate(raw)
    assert result.is_valid  # the profile error is not surfaced ...
    assert result.unmatched_bundle_entries == [index]  # ... only this informational trace
