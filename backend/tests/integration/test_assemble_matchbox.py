"""Assembled Bundles validate against IPS 2.0.1 in Matchbox (skipped when unreachable).

Definition of done (CLAUDE.md, PLAN Phase 1): 0 errors **and** no unmatched Bundle entry (an
entry failing its IPS profile is only visible as an unmatched slice, see validate.py), except the
D-15 non-IPS Observations that ``blocking_unmatched_entries`` allows.
Start Matchbox with ``docker compose -f infra/docker-compose.yml up -d matchbox``.
"""

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

from app.config import get_settings
from app.fhir.models import Observation
from app.pipeline.assemble import assemble
from app.pipeline.validate import MatchboxClient, blocking_unmatched_entries
from app.schemas.intermediate import EnrichedIps, IpsExtraction
from tests.assembly_cases import NOW, all_variants

pytestmark = pytest.mark.integration

VARIANTS = all_variants()
DATASET = Path(__file__).parents[3] / "evals" / "dataset"


@pytest.fixture(scope="module")
def matchbox() -> Iterator[MatchboxClient]:
    base_url = get_settings().matchbox_url.rstrip("/")
    try:
        httpx.get(f"{base_url}/metadata", timeout=5.0).raise_for_status()
    except httpx.HTTPError:
        pytest.skip(f"Matchbox not reachable at {base_url}")
    with MatchboxClient(base_url) as client:
        yield client


@pytest.mark.parametrize("name", sorted(VARIANTS))
def test_assembled_bundle_is_valid_ips(matchbox: MatchboxClient, name: str) -> None:
    result = matchbox.validate(assemble(VARIANTS[name], now=NOW).bundle)
    assert result.errors == [], [(i.path, i.message) for i in result.errors]
    assert result.unmatched_bundle_entries == []


def test_questionnaire_case_with_non_ips_pregnancy_observations(matchbox: MatchboxClient) -> None:
    """fi19 (synthetic, D-15): stand-in dates validate, and the only unmatched entries are the
    allow-listed last menstrual period, gravidity and parity Observations."""
    gold = DATASET / "fi19_summary_multi_context_txt" / "gold.json"
    enriched = EnrichedIps.from_extraction(IpsExtraction.model_validate_json(gold.read_text()))
    bundle = assemble(enriched, now=NOW).bundle
    result = matchbox.validate(bundle)
    assert result.errors == [], [(i.path, i.message) for i in result.errors]
    assert blocking_unmatched_entries(result, bundle) == []
    entries = bundle.entry or []
    unmatched_codes = set()
    for index in result.unmatched_bundle_entries:
        resource = entries[index].resource
        assert isinstance(resource, Observation)
        unmatched_codes.add((resource.code.coding or [])[0].code)
    assert unmatched_codes == {"8665-2", "11996-6", "11977-6"}
