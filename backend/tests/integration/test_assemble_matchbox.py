"""Assembled Bundles validate against IPS 2.0.1 in Matchbox (skipped when unreachable).

Definition of done (CLAUDE.md, PLAN Phase 1): 0 errors **and** no unmatched Bundle entry (an
entry failing its IPS profile is only visible as an unmatched slice, see validate.py).
Start Matchbox with ``docker compose -f infra/docker-compose.yml up -d matchbox``.
"""

from collections.abc import Iterator

import httpx
import pytest

from app.config import get_settings
from app.pipeline.assemble import assemble
from app.pipeline.validate import MatchboxClient
from tests.assembly_cases import NOW, all_variants

pytestmark = pytest.mark.integration

VARIANTS = all_variants()


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
