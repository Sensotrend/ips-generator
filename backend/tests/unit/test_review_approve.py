"""Attestation of the approved Composition (D-4)."""

from __future__ import annotations

import datetime as dt

import pytest

from app.fhir.models import Bundle, Composition
from app.pipeline.assemble import assemble
from app.review.approve import attest_bundle
from app.schemas.api import ReviewerRole
from app.schemas.intermediate import EnrichedIps, IpsExtraction
from tests.api_support import DATASET

NOW = dt.datetime(2026, 10, 13, 12, 0, tzinfo=dt.UTC)


def _bundle() -> Bundle:
    gold = IpsExtraction.model_validate_json(
        (DATASET / "fi01_discharge_internal_txt" / "gold.json").read_bytes()
    )
    return assemble(EnrichedIps.from_extraction(gold), now=NOW).bundle


@pytest.mark.parametrize(
    ("role", "mode"), [(ReviewerRole.PATIENT, "personal"), (ReviewerRole.CLINICIAN, "professional")]
)
def test_attest(role: ReviewerRole, mode: str) -> None:
    bundle = _bundle()
    attested = attest_bundle(bundle, role=role, reviewer_name="Dr Test", at=NOW)
    composition = attested.entry[0].resource  # type: ignore[index]
    assert isinstance(composition, Composition)
    assert composition.status == "final"
    assert composition.attester is not None
    attester = composition.attester[0]
    assert attester.mode == mode
    assert attester.time == "2026-10-13T12:00:00+00:00"
    assert attester.party is not None
    if role is ReviewerRole.PATIENT:
        assert composition.subject is not None
        assert attester.party.reference == composition.subject.reference
    else:
        assert attester.party.display == "Dr Test"
    assert composition.text is not None
    assert "final" in composition.text.div
    # The original is untouched and the author stays the Device.
    original = bundle.entry[0].resource  # type: ignore[index]
    assert isinstance(original, Composition)
    assert original.status == "preliminary"
    assert composition.author == original.author


def test_naive_time_rejected() -> None:
    with pytest.raises(ValueError, match="timezone"):
        attest_bundle(
            _bundle(), role=ReviewerRole.PATIENT, reviewer_name="x", at=dt.datetime(2026, 1, 1)
        )
