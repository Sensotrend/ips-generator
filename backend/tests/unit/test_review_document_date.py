"""The document date (schema 1.3.0, PLAN.md D-15) is a reviewable fact: accepting, editing,
rejecting or resetting it changes the stand-in effective dates in the Bundle."""

import datetime as dt
from typing import Any
from uuid import UUID

import pytest

from app.fhir.common import NoteCode
from app.fhir.models import Observation
from app.pipeline.assemble import assemble
from app.review.draft import (
    DraftState,
    ReviewError,
    apply_actions,
    effective_enriched,
    find_fact,
    iter_facts,
    new_draft,
)
from app.review.view import build_draft_view
from app.schemas.api import EditAction, JobStatus, RejectAction, ResetAction
from app.schemas.intermediate import EnrichedIps
from tests.assembly_cases import build

NOW = dt.datetime(2026, 10, 14, tzinfo=dt.UTC)
QUOTE = "Koontipäivä: 12.10.2026"


def _draft(document_date: str | None = "2026-10-12") -> DraftState:
    data = build().model_dump(mode="json")
    data["vital_signs"] = [
        {
            "extracted": {
                "source_quote": "Pituus 168 cm",
                "page": 1,
                "locator": "line 3",
                "kind": "height",
                "value": "168",
                "diastolic": "",
                "unit_text": "cm",
                "effective": "",
                "note": "",
                "confidence": "high",
            }
        }
    ]
    data["document_date"] = (
        {
            "source_quote": QUOTE,
            "page": 1,
            "locator": "line 1",
            "value": document_date,
            "confidence": "high",
        }
        if document_date
        else None
    )
    return new_draft(EnrichedIps.model_validate(data))


def _height_date(state: DraftState) -> str | None:
    bundle = assemble(effective_enriched(state).enriched, now=NOW).bundle
    for entry in bundle.entry or []:
        if isinstance(entry.resource, Observation):
            return entry.resource.effective_date_time
    return None  # no Observation: the height stayed narrative-only


def _view(state: DraftState) -> Any:
    return build_draft_view(state, job_id=UUID(int=1), version=1, status=JobStatus.REVIEW, now=NOW)


def _value(state: DraftState) -> dict[str, Any]:
    fact = find_fact(state.current, "document_date")
    assert fact.value is not None
    return fact.value.model_dump(mode="json")


def test_document_date_is_a_reviewable_fact_after_the_patient() -> None:
    facts = list(iter_facts(_draft().current))
    paths = [f.path for f in facts]
    assert "document_date" in paths
    assert paths.index("document_date") > max(
        i for i, p in enumerate(paths) if p.startswith("patient")
    )
    fact = facts[paths.index("document_date")]
    assert fact.kind == "document_date"
    assert fact.section is None
    assert fact.item_id is None


def test_view_exposes_the_document_date_and_the_stand_in_note() -> None:
    view = _view(_draft())
    assert view.document_date is not None
    assert view.document_date.kind == "document_date"
    assert view.document_date.value["value"] == "2026-10-12"
    assert view.document_date.source is not None
    assert view.document_date.source.quote == QUOTE
    vitals = next(s for s in view.sections if s.key == "vital_signs")
    assert NoteCode.EFFECTIVE_IS_DOCUMENT_DATE.value in {n.code for n in vitals.items[0].notes}


def test_no_document_date_no_fact() -> None:
    state = _draft(None)
    assert "document_date" not in {f.path for f in iter_facts(state.current)}
    assert _view(state).document_date is None
    with pytest.raises(ReviewError):
        find_fact(state.current, "document_date")


def test_rejecting_the_document_date_removes_the_stand_in_dates() -> None:
    state = _draft()
    assert _height_date(state) == "2026-10-12"
    rejected = apply_actions(
        state, [RejectAction(action="reject", path="document_date")], actor="t", now=NOW
    )
    assert effective_enriched(rejected).enriched.document_date is None
    assert _height_date(rejected) is None  # back to narrative-only (vs-1)
    vitals = next(s for s in _view(rejected).sections if s.key == "vital_signs")
    codes = {n.code for n in vitals.items[0].notes}
    assert NoteCode.EFFECTIVE_IS_DOCUMENT_DATE.value not in codes
    assert NoteCode.VITAL_SIGN_NOT_DATED.value in codes
    assert (
        rejected.current.document_date is not None
    )  # the draft keeps it; only the Bundle drops it


def test_editing_the_document_date_moves_the_stand_in_dates_and_reset_restores() -> None:
    state = _draft()
    edited = apply_actions(
        state,
        [
            EditAction(
                action="edit", path="document_date", value={**_value(state), "value": "2026-10-11"}
            )
        ],
        actor="t",
        now=NOW,
    )
    assert _height_date(edited) == "2026-10-11"
    view = _view(edited)
    assert view.document_date is not None
    assert view.document_date.decision == "edited"
    assert view.document_date.pipeline_value is not None
    assert view.document_date.pipeline_value["value"] == "2026-10-12"
    reset = apply_actions(
        edited, [ResetAction(action="reset", path="document_date")], actor="t", now=NOW
    )
    assert _height_date(reset) == "2026-10-12"


def test_a_partial_edited_date_gives_no_stand_in() -> None:
    state = _draft()
    edited = apply_actions(
        state,
        [
            EditAction(
                action="edit", path="document_date", value={**_value(state), "value": "2026-10"}
            )
        ],
        actor="t",
        now=NOW,
    )
    assert _height_date(edited) is None


@pytest.mark.parametrize(
    "change", [{"value": "12.10.2026"}, {"value": ""}, {"source_quote": "Päivämäärä: 11.10.2026"}]
)
def test_invalid_or_provenance_edits_are_refused(change: dict[str, str]) -> None:
    state = _draft()
    with pytest.raises(ReviewError):
        apply_actions(
            state,
            [EditAction(action="edit", path="document_date", value={**_value(state), **change})],
            actor="t",
            now=NOW,
        )
