"""Tests for step 5, terminology coding (app/pipeline/terminology.py).

No network and no paid calls: a fake FHIR terminology server (httpx.MockTransport) and a real
`anthropic.Anthropic` client talking to a scripted in-process Messages API. Synthetic data only.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from app.fhir.constants import SNOMED_CT
from app.llm.models import get_model_settings
from app.pipeline.extract import FALLBACK_BETA
from app.pipeline.terminology import (
    FIELD_SPECS,
    MAX_TOKENS,
    CodingLimits,
    CodingResult,
    FieldOutcome,
    PrintedCodeStatus,
    code_enriched,
    collect_targets,
)
from app.schemas.intermediate import (
    AllergyItem,
    CodingSelectedBy,
    ConditionItem,
    EnrichedIps,
    ItemsFound,
    MedicationItem,
    path_pattern,
)
from app.terminology.scopes import ATC, ICD_10
from app.terminology.tools import ToolName
from tests.terminology_fakes import (
    MODEL,
    FakeClaude,
    FakeTxServer,
    answer,
    message,
    tool_turn,
    tool_use,
)

FIXTURE = Path(__file__).parent.parent / "fixtures" / "intermediate"
ENRICHED_JSON = (FIXTURE / "enriched_discharge_summary_fi.json").read_text(encoding="utf-8")

# Patient data and non-term content of the fixture that must never leave the process.
PATIENT_MARKERS = (
    "Virtanen",
    "Matti",
    "Juhani",
    "150372-9477",
    "Henkilötunnus",
    "Sukupuoli",
    "lihaskipujen",  # a note
    "todettu 2018",  # inside a source quote only
    "huulten turvotus (2015)",  # source quote fragment
    "enintään 6",  # dosage text
    "line 14",  # locator
)
LIMITS = CodingLimits(
    search_count=10,
    max_tool_calls_per_field=3,
    max_tool_calls_per_document=40,
    fields_per_conversation=20,
    max_turns=4,
)
NOW = "2026-10-13T10:00:00+00:00"


@pytest.fixture(autouse=True)
def _default_models(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("IPS_MODEL_TERMINOLOGY", raising=False)
    monkeypatch.delenv("IPS_EFFORT_TERMINOLOGY", raising=False)
    get_model_settings.cache_clear()
    yield
    get_model_settings.cache_clear()


def fi_enriched(**changes: Any) -> EnrichedIps:
    """The synthetic Finnish discharge summary without codings."""
    data = json.loads(ENRICHED_JSON)
    for section in ("allergies", "medications", "problems"):
        for item in data[section].get("items", []):
            item["codings"] = []
    data.update(changes)
    return EnrichedIps.model_validate(data)


def en_enriched() -> EnrichedIps:
    """English variant: exact terminology terms where the deterministic pass can match."""
    data = json.loads(fi_enriched().model_dump_json())
    data["document_language"] = "en"
    allergy = data["allergies"]["items"][0]["extracted"]
    allergy["substance_text"] = "peanut"
    allergy["reactions"][0]["manifestations"] = ["Hives", "lip swelling"]
    problems = data["problems"]["items"]
    problems[0]["extracted"]["condition_text"] = "Type 2 diabetes mellitus"
    problems[0]["extracted"]["printed_code"] = "E11"
    problems[0]["extracted"]["printed_code_system_text"] = "ICD-10"
    problems[0]["extracted"]["severity"] = "mild"
    problems[1]["extracted"]["condition_text"] = "Type 2 diabetes"  # partial: never exact
    problems[1]["extracted"]["severity"] = "moderate"  # display is "Moderate severity"
    meds = data["medications"]["items"]
    meds[0]["extracted"]["medication_text"] = "Metformin"
    meds[0]["extracted"]["dosage"]["route_text"] = "oral route"
    return EnrichedIps.model_validate(data)


def field_ids(enriched: EnrichedIps) -> dict[tuple[str, str], str]:
    """``(text, path) -> field_id`` as the coder numbers them."""
    targets, _ = collect_targets(enriched)
    return {(t.text, t.path): t.field_id for t in targets}


def report_for(result: CodingResult, path: str, text_item_index: int = 0) -> Any:
    matches = [f for f in result.report.fields if f.path == path]
    return matches[text_item_index]


def codings_of(result: CodingResult, section: str, index: int, path: str) -> list[Any]:
    sec = getattr(result.enriched, section)
    assert isinstance(sec, ItemsFound)
    return list(sec.items[index].codings_for(path))


# --------------------------------------------------------------------------------------------
# Targets
# --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("section", "model"),
    [("allergies", AllergyItem), ("medications", MedicationItem), ("problems", ConditionItem)],
)
def test_every_codable_path_has_a_field_spec(section: str, model: Any) -> None:
    for pattern in model.codable_paths:
        assert (section, pattern) in FIELD_SPECS, pattern
    assert {p for s, p in FIELD_SPECS if s == section} == set(model.codable_paths)


def test_collect_targets_reads_only_codable_term_fields() -> None:
    enriched = fi_enriched()
    targets, skipped = collect_targets(enriched)
    assert skipped == []
    texts = sorted(t.text for t in targets)
    assert texts == sorted(
        [
            "urtikaria",
            "huulten turvotus",
            "Maapähkinä",
            "p.o.",
            "tabl",
            "Metformin",
            "tabl",
            "Ramipril",
            "tabl",
            "Panadol",
            "Simvastatiini",
            "Tyypin 2 diabetes",
            "Verenpainetauti",
            "uniapnea",
        ]
    )
    for target in targets:
        assert path_pattern(target.path) in {p for _, p in FIELD_SPECS}
        assert target.language == "fi"
    metformin = next(t for t in targets if t.text == "Metformin")
    assert (metformin.printed_code, metformin.printed_code_system_text) == ("A10BA02", "ATC")
    assert next(t for t in targets if t.text == "p.o.").printed_code is None


def test_already_coded_paths_are_skipped_and_kept() -> None:
    enriched = EnrichedIps.model_validate_json(ENRICHED_JSON)  # has two codings
    server = FakeTxServer()
    result = code_enriched(enriched, tx=server.client(), limits=LIMITS)
    skipped = [f for f in result.report.fields if f.reason == "already_coded"]
    assert {f.path for f in skipped} == {"medication_text", "condition_text"}
    assert codings_of(result, "medications", 0, "medication_text")[0].code == "A10BA02"


# --------------------------------------------------------------------------------------------
# Deterministic pass
# --------------------------------------------------------------------------------------------


def test_deterministic_finnish_printed_codes_are_candidates_not_codings() -> None:
    server = FakeTxServer()
    result = code_enriched(fi_enriched(), tx=server.client(), limits=LIMITS)

    metformin = report_for(result, "medication_text")
    assert metformin.outcome is FieldOutcome.SKIPPED
    assert metformin.reason == "no_llm"
    assert metformin.printed_code is not None
    assert metformin.printed_code.status is PrintedCodeStatus.EXISTS
    assert (metformin.printed_code.system, metformin.printed_code.code) == (ATC, "A10BA02")
    assert metformin.printed_code.display == "metformin"

    diabetes = report_for(result, "condition_text")
    assert diabetes.printed_code is not None
    assert diabetes.printed_code.status is PrintedCodeStatus.EXISTS  # unlabelled -> ICD-10
    assert diabetes.printed_code.system == ICD_10
    # Finnish text: no exact-match searches at all, only the two printed-code lookups.
    assert [r.url.path for r in server.requests] == ["/r4/CodeSystem/$lookup"] * 2
    assert all(not item.codings for item in _all_items(result.enriched))
    assert result.report.counts == {"skipped": 14}


def test_printed_code_not_found_and_unresolved() -> None:
    data = json.loads(fi_enriched().model_dump_json())
    data["problems"]["items"][0]["extracted"]["printed_code"] = "E11.8"  # not in the fake
    data["problems"]["items"][1]["extracted"]["printed_code"] = "X99"
    data["problems"]["items"][1]["extracted"]["printed_code_system_text"] = "ICPC-2"
    data["problems"]["items"][1]["extracted"]["source_quote"] = "Verenpainetauti X99"
    server = FakeTxServer()
    result = code_enriched(EnrichedIps.model_validate(data), tx=server.client(), limits=LIMITS)
    first, second, _ = [f for f in result.report.fields if f.path == "condition_text"]
    assert first.printed_code is not None
    assert first.printed_code.status is PrintedCodeStatus.NOT_FOUND
    assert second.printed_code is not None
    assert second.printed_code.status is PrintedCodeStatus.UNRESOLVED_SYSTEM


def test_deterministic_exact_match_for_english_terms() -> None:
    server = FakeTxServer()
    result = code_enriched(en_enriched(), tx=server.client(), limits=LIMITS, now=_now)

    condition = codings_of(result, "problems", 0, "condition_text")
    assert [(c.system, c.code) for c in condition] == [(ICD_10, "E11"), (SNOMED_CT, "44054006")]
    lookup = condition[1].lookup
    assert lookup.selected_by is CodingSelectedBy.DETERMINISTIC
    assert lookup.operation == "ValueSet/$expand"
    assert lookup.query == "Type 2 diabetes mellitus"
    assert lookup.server == "https://tx.example.org/r4"
    assert condition[0].lookup.operation == "CodeSystem/$lookup"
    assert condition[0].display == "Type 2 diabetes mellitus"  # from the server, not the text

    assert [c.code for c in codings_of(result, "problems", 0, "severity")] == ["255604002"]
    assert codings_of(result, "problems", 1, "severity") == []  # "moderate" is not exact
    assert codings_of(result, "problems", 1, "condition_text") == []  # partial term
    hives = codings_of(result, "allergies", 0, "reactions[0].manifestations[0]")
    assert [c.code for c in hives] == ["126485001"]  # synonym match
    assert [c.code for c in codings_of(result, "allergies", 0, "substance_text")] == ["762952008"]
    medication = codings_of(result, "medications", 0, "medication_text")
    assert [(c.system, c.code) for c in medication] == [(ATC, "A10BA02")]
    assert [c.code for c in codings_of(result, "medications", 0, "dosage.route_text")] == [
        "26643006"
    ]
    ramipril = codings_of(result, "medications", 1, "medication_text")  # "Ramipril" = ATC display
    assert [(c.system, c.code) for c in ramipril] == [(ATC, "C09AA05")]
    assert result.report.counts["coded_deterministic"] == 7


def test_deterministic_requires_unique_exact_match() -> None:
    from app.terminology.scopes import SearchScope
    from tests.terminology_fakes import DEFAULT_CONCEPTS, sct

    concepts = (*DEFAULT_CONCEPTS, sct("999999001", "Peanut", SearchScope.ALLERGY_SUBSTANCE))
    server = FakeTxServer(concepts=concepts)
    result = code_enriched(en_enriched(), tx=server.client(), limits=LIMITS)
    assert codings_of(result, "allergies", 0, "substance_text") == []


def test_terminology_errors_leave_fields_text_only() -> None:
    server = FakeTxServer(fail_with=[503] * 200)
    result = code_enriched(en_enriched(), tx=server.client(max_retries=0), limits=LIMITS)
    assert all(not item.codings for item in _all_items(result.enriched))
    assert any(f.reason == "terminology_error" for f in result.report.fields)


# --------------------------------------------------------------------------------------------
# LLM pass
# --------------------------------------------------------------------------------------------


def _now() -> Any:
    import datetime as dt

    return dt.datetime.fromisoformat(NOW)


def _all_items(enriched: EnrichedIps) -> list[Any]:
    items: list[Any] = []
    for section in ("allergies", "medications", "problems"):
        value = getattr(enriched, section)
        if isinstance(value, ItemsFound):
            items += value.items
    return items


def test_llm_codes_from_returned_candidates() -> None:
    enriched = fi_enriched()
    ids = field_ids(enriched)
    diabetes = ids[("Tyypin 2 diabetes", "condition_text")]
    peanut = ids[("Maapähkinä", "substance_text")]
    metformin = ids[("Metformin", "medication_text")]
    claude = FakeClaude(
        tool_turn(
            tool_use("search_snomed", field_id=diabetes, scope="problem", query="type 2 diabetes"),
            tool_use("search_snomed", field_id=peanut, scope="allergy_substance", query="peanut"),
            tool_use(
                "search_medication",
                field_id=metformin,
                terminology="snomed_product",
                query="metformin",
            ),
        ),
        answer(
            (diabetes, "snomed_ct", "44054006"),
            (diabetes, "icd_10", "E11.9"),  # printed code confirmed in the first turn
            (peanut, "snomed_ct", "762952008"),
            (metformin, "snomed_ct", "776713006"),
            (metformin, "atc", "A10BA02"),  # printed code
        ),
    )
    server = FakeTxServer()
    result = code_enriched(
        enriched, tx=server.client(), llm=claude.client(), limits=LIMITS, now=_now
    )

    condition = codings_of(result, "problems", 0, "condition_text")
    assert [(c.system, c.code, c.display) for c in condition] == [
        (SNOMED_CT, "44054006", "Type 2 diabetes mellitus"),
        (ICD_10, "E11.9", "Type 2 diabetes mellitus : Without complications"),
    ]
    lookup = condition[0].lookup
    assert lookup.selected_by is CodingSelectedBy.TOOL_LOOP
    assert lookup.model == MODEL
    assert lookup.query == "type 2 diabetes"
    assert lookup.retrieved_at.isoformat() == NOW
    assert condition[1].lookup.query == "E11.9"
    assert condition[1].lookup.operation == "CodeSystem/$lookup"
    medication = codings_of(result, "medications", 0, "medication_text")
    assert [(c.system, c.code) for c in medication] == [
        (SNOMED_CT, "776713006"),
        (ATC, "A10BA02"),
    ]

    report = result.report
    assert report.counts["coded"] == 3
    assert report.counts["coded_tool_loop"] == 3
    assert report.counts["no_match"] == 11
    assert report.tool_calls == 3
    assert report.rejected_choices == 0
    assert report.model_turns == 2
    assert report.models_used == [MODEL]
    assert report.prompt_version == "terminology_v1"
    assert report.request_ids == ["req_1", "req_2"]
    assert report.usage.input_tokens == 2000


def test_request_shape() -> None:
    claude = FakeClaude(answer())
    code_enriched(fi_enriched(), tx=FakeTxServer().client(), llm=claude.client(), limits=LIMITS)
    request = claude.requests[0]
    body = claude.body(0)
    assert request.headers["anthropic-beta"] == FALLBACK_BETA
    assert body["model"] == "claude-sonnet-5-5"
    assert body["max_tokens"] == MAX_TOKENS
    assert body["fallbacks"] == "default"
    assert body["tool_choice"] == {"type": "auto"}
    assert body["output_config"]["effort"] == "medium"
    assert body["output_config"]["format"]["type"] == "json_schema"
    assert body["cache_control"] == {"type": "ephemeral"}
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["system"][0]["text"].startswith("You code clinical terms")
    assert "thinking" not in body
    assert [t["name"] for t in body["tools"]] == [n.value for n in ToolName]
    for tool in body["tools"]:
        assert tool["strict"] is True
        assert tool["input_schema"]["additionalProperties"] is False
        assert set(tool["input_schema"]["required"]) == set(tool["input_schema"]["properties"])
        assert "eager_input_streaming" not in tool
    content = body["messages"][0]["content"]
    boundary = content.split("<fields_", 1)[1].split(">", 1)[0]
    assert f"</fields_{boundary}>" in content
    lines = content.split(f"<fields_{boundary}>\n", 1)[1].split(f"\n</fields_{boundary}>")[0]
    fields = [json.loads(line) for line in lines.splitlines()]
    assert len(fields) == 14
    assert set(fields[0]) <= {"field_id", "kind", "language", "text", "printed_code"}
    metformin = next(f for f in fields if f["text"] == "Metformin")
    assert metformin["printed_code"] == {
        "status": "exists",
        "system": "atc",
        "code": "A10BA02",
        "server_display": "metformin",
    }


def test_no_fallbacks_param_without_provider_support() -> None:
    from app.config import LlmProvider

    claude = FakeClaude(answer())
    code_enriched(
        fi_enriched(),
        tx=FakeTxServer().client(),
        llm=claude.client(LlmProvider.BEDROCK),
        limits=LIMITS,
    )
    assert "fallbacks" not in claude.body(0)
    assert "anthropic-beta" not in claude.requests[0].headers


def test_invented_code_is_rejected() -> None:
    enriched = fi_enriched()
    diabetes = field_ids(enriched)[("Tyypin 2 diabetes", "condition_text")]
    claude = FakeClaude(answer((diabetes, "snomed_ct", "44054006")))  # never searched
    result = code_enriched(enriched, tx=FakeTxServer().client(), llm=claude.client(), limits=LIMITS)
    assert codings_of(result, "problems", 0, "condition_text") == []
    field = report_for(result, "condition_text")
    assert field.outcome is FieldOutcome.REJECTED
    assert field.rejected_choices == 1
    assert result.report.rejected_choices == 1


def test_candidate_from_wrong_scope_or_unknown_field_is_rejected() -> None:
    enriched = fi_enriched()
    ids = field_ids(enriched)
    diabetes = ids[("Tyypin 2 diabetes", "condition_text")]
    route = ids[("p.o.", "dosage.route_text")]
    claude = FakeClaude(
        tool_turn(tool_use("search_snomed", field_id=route, scope="route", query="oral")),
        answer(
            (diabetes, "snomed_ct", "26643006"),  # a route code for a condition
            ("f999", "snomed_ct", "26643006"),  # unknown field
            (route, "snomed_ct", "26643006"),
            (route, "snomed_ct", "26643006"),  # duplicate system for the field
        ),
    )
    result = code_enriched(enriched, tx=FakeTxServer().client(), llm=claude.client(), limits=LIMITS)
    assert codings_of(result, "problems", 0, "condition_text") == []
    assert [c.code for c in codings_of(result, "medications", 0, "dosage.route_text")] == [
        "26643006"
    ]
    assert result.report.rejected_choices == 3


def test_printed_code_needs_server_confirmation() -> None:
    data = json.loads(fi_enriched().model_dump_json())
    data["problems"]["items"][0]["extracted"]["printed_code"] = "E11.8"  # does not exist
    enriched = EnrichedIps.model_validate(data)
    diabetes = field_ids(enriched)[("Tyypin 2 diabetes", "condition_text")]
    claude = FakeClaude(
        tool_turn(tool_use("lookup_code", field_id=diabetes, system="icd_10", code="E11.8")),
        answer((diabetes, "icd_10", "E11.8")),
    )
    result = code_enriched(enriched, tx=FakeTxServer().client(), llm=claude.client(), limits=LIMITS)
    tool_result = claude.body(1)["messages"][2]["content"][0]
    assert json.loads(tool_result["content"])["exists"] is False
    assert codings_of(result, "problems", 0, "condition_text") == []
    assert result.report.rejected_choices == 1


def test_lookup_code_only_for_printed_codes() -> None:
    enriched = fi_enriched()
    ids = field_ids(enriched)
    hypertension = ids[("Verenpainetauti", "condition_text")]  # no printed code
    claude = FakeClaude(
        tool_turn(tool_use("lookup_code", field_id=hypertension, system="icd_10", code="I10")),
        answer(),
    )
    server = FakeTxServer()
    code_enriched(enriched, tx=server.client(), llm=claude.client(), limits=LIMITS)
    tool_result = claude.body(1)["messages"][2]["content"][0]
    assert tool_result["is_error"] is True
    assert "I10" not in " ".join(server.bodies())


def test_tool_errors_unknown_field_and_rejected_query() -> None:
    enriched = fi_enriched()
    peanut = field_ids(enriched)[("Maapähkinä", "substance_text")]
    claude = FakeClaude(
        tool_turn(
            tool_use("search_snomed", field_id="f999", scope="problem", query="asthma"),
            tool_use(
                "search_snomed", field_id=peanut, scope="allergy_substance", query="150372-9477"
            ),
        ),
        answer(),
    )
    server = FakeTxServer()
    code_enriched(enriched, tx=server.client(), llm=claude.client(), limits=LIMITS)
    results = claude.body(1)["messages"][2]["content"]
    assert [r.get("is_error") for r in results] == [True, True]
    assert "150372-9477" not in " ".join(server.bodies())


def test_loop_bounds_per_field_and_turns() -> None:
    enriched = fi_enriched()
    peanut = field_ids(enriched)[("Maapähkinä", "substance_text")]

    def search() -> dict[str, Any]:
        return tool_turn(
            tool_use("search_snomed", field_id=peanut, scope="allergy_substance", query="peanut"),
            tool_use("search_snomed", field_id=peanut, scope="allergy_substance", query="nut"),
        )

    claude = FakeClaude(search(), search(), search(), answer())
    result = code_enriched(enriched, tx=FakeTxServer().client(), llm=claude.client(), limits=LIMITS)
    assert len(claude.requests) == LIMITS.max_turns
    assert [claude.body(i)["tool_choice"]["type"] for i in range(4)] == [
        "auto",
        "auto",
        "auto",
        "none",
    ]
    # 6 tool_use blocks, only 3 (the per-field budget) executed; the rest answered with errors.
    errors = [
        r
        for i in range(1, 4)
        for r in claude.body(i)["messages"][-1]["content"]
        if r.get("is_error")
    ]
    assert len(errors) == 3
    assert result.report.tool_calls == 6
    assert report_for(result, "substance_text").tool_calls == 3
    # history is append-only: every request extends the previous one
    for i in range(1, 4):
        assert (
            claude.body(i)["messages"][: len(claude.body(i - 1)["messages"])]
            == claude.body(i - 1)["messages"]
        )


def test_document_budget_stops_tools_and_skips_later_batches() -> None:
    enriched = fi_enriched()
    ids = field_ids(enriched)
    first = ids[("urtikaria", "reactions[0].manifestations[0]")]
    limits = CodingLimits(
        max_tool_calls_per_field=3,
        max_tool_calls_per_document=1,
        fields_per_conversation=7,
        max_turns=4,
    )
    claude = FakeClaude(
        tool_turn(
            tool_use("search_snomed", field_id=first, scope="clinical_finding", query="urticaria")
        ),
        answer(),
    )
    result = code_enriched(enriched, tx=FakeTxServer().client(), llm=claude.client(), limits=limits)
    assert claude.body(1)["tool_choice"] == {"type": "none"}  # budget used up -> final turn
    assert len(claude.requests) == 2
    assert result.report.counts["skipped"] == 7
    assert {f.reason for f in result.report.fields if f.outcome is FieldOutcome.SKIPPED} == {
        "document_tool_budget"
    }


def test_refusal_marks_batch_and_next_batch_continues() -> None:
    enriched = fi_enriched()
    limits = CodingLimits(fields_per_conversation=7, max_turns=3)
    claude = FakeClaude(
        message(
            stop_reason="refusal",
            stop_details={"type": "refusal", "category": "bio", "explanation": None},
        ),
        answer(),
    )
    result = code_enriched(enriched, tx=FakeTxServer().client(), llm=claude.client(), limits=limits)
    assert result.report.refusals == 1
    assert result.report.counts == {"error": 7, "no_match": 7}
    assert {f.reason for f in result.report.fields if f.outcome is FieldOutcome.ERROR} == {
        "refused"
    }


def test_truncated_and_invalid_answers_are_errors() -> None:
    claude = FakeClaude(
        message(stop_reason="max_tokens"),
        message({"type": "text", "text": "not json"}),
    )
    limits = CodingLimits(fields_per_conversation=7, max_turns=3)
    result = code_enriched(
        fi_enriched(), tx=FakeTxServer().client(), llm=claude.client(), limits=limits
    )
    reasons = [f.reason for f in result.report.fields if f.outcome is FieldOutcome.ERROR]
    assert set(reasons) == {"invalid_answer", "truncated"}
    assert len(reasons) == 14


def test_api_errors_are_isolated_per_batch() -> None:
    import httpx2

    class Overloaded(FakeClaude):
        def __call__(self, request: httpx2.Request) -> httpx2.Response:
            self.requests.append(request)
            if len(self.requests) == 1:
                return httpx2.Response(
                    529,
                    json={"type": "error", "error": {"type": "overloaded_error", "message": "x"}},
                )
            return httpx2.Response(200, headers={"request-id": "r"}, json=answer())

    claude = Overloaded()
    limits = CodingLimits(fields_per_conversation=7, max_turns=3)
    result = code_enriched(
        fi_enriched(), tx=FakeTxServer().client(), llm=claude.client(), limits=limits
    )
    assert result.report.counts == {"error": 7, "no_match": 7}


# --------------------------------------------------------------------------------------------
# Privacy
# --------------------------------------------------------------------------------------------


def test_no_patient_data_leaves_the_process(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    enriched = fi_enriched()
    ids = field_ids(enriched)
    peanut = ids[("Maapähkinä", "substance_text")]
    claude = FakeClaude(
        tool_turn(
            tool_use("search_snomed", field_id=peanut, scope="allergy_substance", query="peanut")
        ),
        answer((peanut, "snomed_ct", "762952008")),
    )
    server = FakeTxServer()
    result = code_enriched(enriched, tx=server.client(), llm=claude.client(), limits=LIMITS)

    outbound = server.bodies() + [r.content.decode() for r in claude.requests]
    outbound_text = json.dumps(outbound, ensure_ascii=False) + " ".join(outbound)
    for marker in PATIENT_MARKERS:
        assert marker not in outbound_text, marker
    # Terms do leave (that is the point), but never into logs or the report.
    report_json = result.report.model_dump_json()
    for term in ("Maapähkinä", "urtikaria", "Tyypin 2 diabetes", "Panadol", "peanut"):
        assert term not in caplog.text
        assert term not in report_json
    for marker in PATIENT_MARKERS:
        assert marker not in caplog.text


def test_result_round_trips_and_original_is_unchanged() -> None:
    enriched = en_enriched()
    before = enriched.model_dump_json()
    result = code_enriched(enriched, tx=FakeTxServer().client(), limits=LIMITS)
    assert enriched.model_dump_json() == before
    assert EnrichedIps.model_validate_json(result.enriched.model_dump_json()) == result.enriched
    assert [i.id for i in _all_items(result.enriched)] == [i.id for i in _all_items(enriched)]
