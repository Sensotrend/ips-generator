"""Tests of the eval harness (``evals/``): matching, metrics, cost guard, run modes.

No network: live extraction and the judge use fakes. The gold self-test (gold as prediction must
score 100%) runs over the whole dataset.
"""

from __future__ import annotations

import datetime as dt
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.llm.client import LlmClient, LlmProvider
from app.llm.models import Effort, PipelineStep, StepModelConfig
from app.llm.prompts import load_extract_prompt
from app.pipeline.derive import derive_patient_facts
from app.pipeline.extract import ExtractionRefusedError, ExtractionResult, TokenUsage
from app.schemas.intermediate import SCHEMA_VERSION, IpsExtraction
from evals.cases import EvalCase, load_cases, select_cases
from evals.cli import main as cli_main
from evals.judge import LlmJudge
from evals.matching import (
    Candidate,
    DocumentIndex,
    match_candidates,
    text_similarity,
    text_tokens,
    tokens_match,
)
from evals.metrics import ITEM_SECTIONS, JudgeItem, score_case
from evals.pricing import CostGuard, UnknownModelPriceError, cost_usd, price_for
from evals.runner import (
    CachedExtractor,
    LiveExtractor,
    Prediction,
    PredictionMeta,
    evaluate_case,
    gold_extractor,
    run_eval,
    save_prediction,
)

NOW = dt.datetime(2026, 10, 8, 12, 0, tzinfo=dt.UTC)
CASES = load_cases()
STEP = StepModelConfig(step=PipelineStep.EXTRACT, model="claude-opus-5-5", effort=Effort.HIGH)


def _case(case_id: str) -> EvalCase:
    return select_cases(CASES, [case_id])[0]


def _prediction(case: EvalCase, extraction: IpsExtraction) -> Prediction:
    return Prediction(
        meta=PredictionMeta(case_id=case.case_id, source="live", ok=True), extraction=extraction
    )


def _gold_dict(case: EvalCase) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(case.gold_path.read_text("utf-8"))
    return data


# ---- matching ------------------------------------------------------------------------------


def test_tokens_match_tolerates_inflection_but_not_short_words() -> None:
    assert tokens_match("diabetes", "diabeteksen")
    assert tokens_match("astma", "astmaa")
    assert not tokens_match("kipu", "kipua")  # too short to be safe
    assert not tokens_match("hypotyreoosi", "hypertensio")


def test_text_tokens_strip_codes_strength_and_allergy_words() -> None:
    assert text_tokens("Bisoprolol 5 mg (C07AB07)", "medication") == ("bisoprolol",)
    assert text_tokens("Metformin 1 g", "medication") == text_tokens("Metformin", "medication")
    assert text_tokens("Tyypin 2 diabetes E11.9", "condition") == ("tyypin", "2", "diabetes")
    assert text_tokens("Kala-allergia", "allergy") == text_tokens("Kala", "allergy")
    assert text_tokens("030551-9315", "identifier") == text_tokens("0305519315", "identifier")


def test_text_similarity_is_order_insensitive() -> None:
    a = text_tokens("Type 2 diabetes mellitus", "condition")
    b = text_tokens("Diabetes mellitus, type 2", "condition")
    assert text_similarity(a, b) == 1.0
    assert text_similarity(a, ()) == 0.0


def test_quote_overlap_matches_differently_named_item() -> None:
    case = _case("fi01")
    index = DocumentIndex(case.document)
    quote = "Metformin 1 g tabl 1x2"
    span = index.locate(quote, 1, "line 35")
    assert span is not None
    pred = [Candidate(0, "Glucophage", text_tokens("Glucophage", "medication"), span)]
    gold = [Candidate(0, "Metformin", text_tokens("Metformin", "medication"), span)]
    result = match_candidates(pred, gold)
    assert [(m.pred, m.gold, m.method) for m in result.matches] == [(0, 0, "quote")]
    # Same text without any quote overlap is still a match; unrelated text without overlap not.
    far = [Candidate(0, "Metformin", gold[0].tokens, None)]
    assert match_candidates(far, gold).matches[0].method == "text"
    other = [Candidate(0, "Ramipril", text_tokens("Ramipril", "medication"), None)]
    assert match_candidates(other, gold).unmatched_gold == (0,)


# ---- gold self-test ------------------------------------------------------------------------


def test_gold_as_prediction_scores_perfectly(tmp_path: Path) -> None:
    output = run_eval(
        CASES, extractor=gold_extractor, run_dir=tmp_path / "run", metadata={}, now=NOW
    )
    summary = output.summary
    assert summary.n_scored == len(CASES) > 20
    for name, section in summary.sections.items():
        assert section.fp == section.fn == 0, name
        if section.tp:
            assert section.precision == section.recall == section.f1 == 1.0
            assert section.macro_f1 == 1.0
    assert summary.patient.f1 == 1.0
    for name in ("patient_birth_date_effective", "patient_gender_effective"):
        assert summary.sections[name].f1 == 1.0
    # D-10: every HETU-only case gets its birth date derived, correctly; 900-999 codes: no sex.
    hetu_only = sum("hetu_without_birth_date" in c.meta["features"] for c in CASES)
    assert summary.derived["birth_date"].n == hetu_only > 0
    assert summary.derived["birth_date"].accuracy == 1.0
    assert summary.derived["gender"].n == 0
    assert summary.review_flags == {"derived_from_identity_code": hetu_only}
    for name in ITEM_SECTIONS:
        assert summary.states[name].accuracy == 1.0
        assert summary.raw_sections[name].recall == 1.0
    assert summary.critical_state_errors == summary.false_assurance == []
    for fields in summary.fields.values():
        for field in fields.values():
            assert field.n == 0 or field.accuracy == 1.0
    assert summary.dropped_facts == 0
    assert summary.grounding["not_found"] == 0
    assert summary.assembly_ok == summary.assembly_attempted == len(CASES)
    assert summary.validation_pass_rate is None  # not validated here
    results = json.loads((tmp_path / "run" / "results.json").read_text("utf-8"))
    assert len(results["cases"]) == len(CASES)
    assert (tmp_path / "run" / "summary.md").read_text("utf-8").startswith("### ")


# ---- perturbations -------------------------------------------------------------------------


def test_dropped_item_lowers_recall_only() -> None:
    case = _case("fi01")
    data = _gold_dict(case)
    del data["medications"]["items"][1]
    result = evaluate_case(case, _prediction(case, IpsExtraction.model_validate(data)), now=NOW)
    assert result.score is not None
    counts = result.score.sections["medications"].counts
    assert counts.fn == 1
    assert counts.fp == 0
    assert counts.recall is not None
    assert counts.recall < 1.0
    assert counts.precision == 1.0
    assert result.score.sections["medications"].unmatched_gold == ["Metformin"]


def test_spurious_item_lowers_precision_only() -> None:
    case = _case("fi01")
    data = _gold_dict(case)
    spurious = {**data["medications"]["items"][0], "medication_text": "Zzyzxomab"}
    data["medications"]["items"].append(spurious)
    result = evaluate_case(case, _prediction(case, IpsExtraction.model_validate(data)), now=NOW)
    assert result.score is not None
    counts = result.score.sections["medications"].counts
    assert (counts.fp, counts.fn) == (1, 0)
    assert counts.precision is not None
    assert counts.precision < 1.0
    assert counts.recall == 1.0


def test_none_known_instead_of_items_is_a_critical_state_error(tmp_path: Path) -> None:
    case = _case("fi01")
    data = _gold_dict(case)
    quote = data["allergies"]["items"][0]
    data["allergies"] = {
        "kind": "none_known",
        "source_quote": quote["source_quote"],
        "page": quote["page"],
        "locator": quote["locator"],
        "confidence": "high",
        "scope": "all",
    }
    flipped = IpsExtraction.model_validate(data)

    def extractor(c: EvalCase) -> Prediction:
        return _prediction(c, flipped)

    output = run_eval([case], extractor=extractor, run_dir=tmp_path, metadata={}, now=NOW)
    state = output.summary.states["allergies"]
    assert state.accuracy == 0.0
    assert state.confusion["items_found"]["none_known"] == 1
    assert output.summary.critical_state_errors == [
        f"{case.case_id} allergies items_found->none_known"
    ]
    assert output.summary.sections["allergies"].recall == 0.0


def test_failed_extraction_counts_as_misses_and_state_errors(tmp_path: Path) -> None:
    case = _case("fi05")

    def refuse(_doc: Any, *, client: Any) -> ExtractionResult:
        raise ExtractionRefusedError(category="bio", model="claude-opus-5-5", request_id=None)

    extractor = LiveExtractor(
        cast(LlmClient, object()),
        STEP,
        load_extract_prompt(),
        CostGuard(10.0),
        estimates={case.case_id: 0.1},
        extract_fn=refuse,
    )
    output = run_eval(
        [case],
        extractor=extractor,
        run_dir=tmp_path,
        metadata={},
        save_predictions=True,
        now=NOW,
    )
    (result,) = output.cases
    assert result.status == "extraction_failed"
    assert output.summary.usage.refusals == 1
    assert output.summary.state_accuracy == 0.0
    assert output.summary.sections["problems"].recall == 0.0
    meta = json.loads((tmp_path / "cases" / case.case_id / "prediction.json").read_text("utf-8"))
    assert meta["error"] == "ExtractionRefusedError"
    assert meta["cost_is_estimate"] is True


def test_judge_pairs_leftovers() -> None:
    case = _case("fi01")
    data = _gold_dict(case)
    data["problems"]["items"][0]["condition_text"] = "Zzyzx disease"
    data["problems"]["items"][0]["source_quote"] = data["patient"]["names"][0]["source_quote"]
    data["problems"]["items"][0]["locator"] = data["patient"]["names"][0]["locator"]
    pred = IpsExtraction.model_validate(data)
    gold = case.load_gold()
    index = DocumentIndex(case.document)
    assert score_case(pred, gold, index).sections["problems"].counts.fn == 1

    seen: list[tuple[str, int, int]] = []

    def judge(section: str, p: Any, g: Any) -> list[tuple[int, int]]:
        seen.append((section, len(p), len(g)))
        return [(p[0].index, g[0].index), (99, 0)]  # invalid pair ignored

    score = score_case(pred, gold, index, judge=judge)
    assert seen == [("problems", 1, 1)]
    assert score.sections["problems"].counts.fn == 0
    assert any(m.method == "judge" for m in score.sections["problems"].matches)


# ---- cost guard and live mode --------------------------------------------------------------


def test_prices_and_cost() -> None:
    usage = TokenUsage(input_tokens=1_000_000, output_tokens=1_000_000)
    assert cost_usd("claude-opus-5-5", usage) == pytest.approx(24.0)
    assert cost_usd("claude-sonnet-5-5", usage) == pytest.approx(12.0)
    small = TokenUsage(input_tokens=100_000, output_tokens=100_000)
    assert cost_usd("claude-haiku-5-5", small) == pytest.approx(0.06)
    assert cost_usd("claude-haiku-5-5", usage) == pytest.approx(3.0)  # >100K-token prompt
    assert cost_usd(
        "claude-opus-5-5", TokenUsage(cache_read_input_tokens=1_000_000)
    ) == pytest.approx(0.2)
    assert price_for("claude-opus-5-5-20261001") == price_for("claude-opus-5-5")
    with pytest.raises(UnknownModelPriceError):
        price_for("some-other-model")


def test_cost_guard_reserves_and_settles() -> None:
    guard = CostGuard(1.0)
    assert guard.try_reserve(0.6)
    assert not guard.try_reserve(0.6)
    guard.settle(0.6, 0.2)
    assert guard.spent_usd == pytest.approx(0.2)
    assert guard.try_reserve(0.6)


def _fake_result(extraction: IpsExtraction, usage: TokenUsage) -> ExtractionResult:
    return ExtractionResult(
        extraction=extraction,
        model_requested="claude-opus-5-5",
        model_used="claude-opus-5-5",
        fallback_used=False,
        prompt_version="extract_vX",
        schema_version=SCHEMA_VERSION,
        usage=usage,
        attempts=1,
        request_ids=("req_fake",),
    )


def test_cost_guard_stops_live_run(tmp_path: Path) -> None:
    cases = select_cases(CASES, ["fi01", "fi02", "fi03"])
    calls: list[str] = []
    by_doc = {id(c.document): c for c in cases}

    def fake_extract(doc: Any, *, client: Any) -> ExtractionResult:
        case = by_doc[id(doc)]
        calls.append(case.case_id)
        # 200K input + 5K output on Opus = $0.90
        return _fake_result(case.load_gold(), TokenUsage(input_tokens=200_000, output_tokens=5_000))

    guard = CostGuard(1.0)
    extractor = LiveExtractor(
        cast(LlmClient, object()),
        STEP,
        load_extract_prompt(),
        guard,
        estimates=dict.fromkeys((c.case_id for c in cases), 0.4),
        extract_fn=fake_extract,
    )
    output = run_eval(
        cases,
        extractor=extractor,
        run_dir=tmp_path,
        metadata={},
        save_predictions=True,
        now=NOW,
    )
    assert calls == ["fi01_discharge_internal_txt"]
    assert [c.status for c in output.cases] == ["ok", "skipped", "skipped"]
    assert guard.spent_usd == pytest.approx(0.9)
    assert output.summary.usage.extraction_cost_usd == pytest.approx(0.9)
    assert output.summary.n_skipped == 2
    saved = json.loads((tmp_path / "cases" / cases[1].case_id / "prediction.json").read_text())
    assert saved["skipped"] is True
    assert saved["error"] == "CostLimitReached"


def test_live_cli_without_confirmation_makes_no_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_client(*_a: Any, **_k: Any) -> None:
        raise AssertionError("must not create an API client")

    monkeypatch.setattr("evals.cli.create_client", no_client)
    code = cli_main(
        ["--predictions", "live", "--cases", "fi01", "--runs-dir", str(tmp_path), "--quiet"]
    )
    assert code == 1
    assert list(tmp_path.iterdir()) == []


# ---- cached mode ---------------------------------------------------------------------------


def test_cached_mode_rescores_a_saved_run(tmp_path: Path) -> None:
    cases = select_cases(CASES, ["en02", "sv04", "fi12"])
    source = tmp_path / "source"
    for case in cases:
        if case.case_id.startswith("fi12"):
            continue  # deliberately missing from the run
        meta = PredictionMeta(
            case_id=case.case_id,
            source="live",
            ok=True,
            model_requested="claude-opus-5-5",
            model_used="claude-opus-5-5",
            attempts=1,
            usage=TokenUsage(input_tokens=1000, output_tokens=500),
            cost_usd=0.014,
            latency_s=12.5,
        )
        save_prediction(source, Prediction(meta=meta, extraction=case.load_gold()))
    output = run_eval(
        cases,
        extractor=CachedExtractor(source),
        run_dir=tmp_path / "rescore",
        metadata={},
        now=NOW,
    )
    statuses = {c.case_id: c.status for c in output.cases}
    assert statuses == {
        "en02_referral_diabetes_md": "ok",
        "fi12_lab_results_comma_csv": "skipped",
        "sv04_outpatient_sections_json": "ok",
    }
    assert output.summary.sections["problems"].f1 == 1.0
    assert output.summary.usage.extraction_cost_usd == pytest.approx(0.028)
    assert output.summary.usage.latency_mean_s == pytest.approx(12.5)


# ---- judge (fake SDK) ----------------------------------------------------------------------


def test_judge_session_calls_once_and_caches(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []

    def create(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return SimpleNamespace(
            model="claude-sonnet-5-5",
            stop_reason="end_turn",
            usage=SimpleNamespace(
                input_tokens=1000,
                output_tokens=100,
                cache_creation_input_tokens=0,
                cache_read_input_tokens=0,
            ),
            content=[
                SimpleNamespace(type="text", text='{"matches": [{"predicted": 3, "gold": 5}]}')
            ],
        )

    sdk = SimpleNamespace(beta=SimpleNamespace(messages=SimpleNamespace(create=create)))
    client = LlmClient(provider=LlmProvider.ANTHROPIC, sdk=cast(Any, sdk))
    step = StepModelConfig(
        step=PipelineStep.EVAL_JUDGE, model="claude-sonnet-5-5", effort=Effort.MEDIUM
    )
    judge = LlmJudge(client, step, CostGuard(1.0))
    cache = tmp_path / "judge.json"
    items_p = [JudgeItem(3, "DM2", "DM2 dg 2015", "")]
    items_g = [JudgeItem(5, "Tyypin 2 diabetes", "Tyypin 2 diabetes (E11.9)", "")]

    session = judge.session(cache)
    assert list(session("problems", items_p, items_g)) == [(3, 5)]
    assert list(session("problems", items_p, items_g)) == [(3, 5)]
    assert len(calls) == 1
    assert calls[0]["output_config"]["effort"] == "medium"
    assert session.cost_usd == pytest.approx((1000 * 2 + 100 * 10) / 1e6)
    # A new session (e.g. a cached re-score) reuses the stored decision without a call.
    again = judge.session(tmp_path / "other.json", seed_file=cache)
    assert list(again("problems", items_p, items_g)) == [(3, 5)]
    assert len(calls) == 1

    broke = LlmJudge(client, step, CostGuard(0.0)).session(None)
    assert list(broke("problems", items_p, items_g)) == []
    assert broke.skipped == 1


def test_wrong_derived_birth_date_is_scored_against_the_truth() -> None:
    case = _case("fi02")  # HETU only; expected_patient.birth_date comes from the HETU
    gold = case.load_gold()
    index = DocumentIndex(case.document)
    expected = case.expected_patient
    assert expected is not None
    assert expected["birth_date"] is not None
    derivation = derive_patient_facts(gold.patient)
    good = score_case(gold, gold, index, derived=derivation.derived, expected_patient=expected)
    assert good.derived == {"birth_date": True}
    assert good.sections["patient_birth_date_effective"].counts.tp == 1
    wrong = derivation.derived.model_copy(
        update={
            "birth_date": derivation.derived.birth_date.model_copy(  # type: ignore[union-attr]
                update={"value": "1900-01-01"}
            )
        }
    )
    bad = score_case(gold, gold, index, derived=wrong, expected_patient=expected)
    assert bad.derived == {"birth_date": False}
    counts = bad.sections["patient_birth_date_effective"].counts
    assert (counts.tp, counts.fp, counts.fn) == (0, 1, 1)
    # The LLM-layer birth date metric is unaffected (gold birth_date stays null).
    assert bad.sections["patient_birth_date"].counts.tp == 0
    assert bad.sections["patient_birth_date"].counts.fp == 0
