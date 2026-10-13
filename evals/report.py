"""Markdown summary of a run (printed, written to ``summary.md``, optionally appended to
``evals/RESULTS.md``)."""

from __future__ import annotations

from typing import Any

from evals.metrics import ITEM_SECTIONS, PATIENT_SECTIONS, RunSummary, SectionAggregate

__all__ = ["render_markdown"]


def _pct(value: float | None) -> str:
    return "-" if value is None else f"{100 * value:.1f}%"


def _num(value: float | None, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _section_row(name: str, s: SectionAggregate) -> str:
    return (
        f"| {name} | {_num(s.precision)} | {_num(s.recall)} | {_num(s.f1)} | "
        f"{_num(s.macro_f1)} ({s.macro_n}) | {s.tp} / {s.fp} / {s.fn} |"
    )


def render_markdown(metadata: dict[str, Any], summary: RunSummary) -> str:
    m = metadata
    judge = f"`{m.get('judge_model')}` @ `{m.get('judge_effort')}`" if m.get("judge") else "off"
    lines: list[str] = [
        f"### {m.get('run_id', 'run')}",
        "",
        f"- Date: {m.get('date')} · git `{m.get('git_commit')}`"
        f"{' (dirty)' if m.get('git_dirty') else ''}",
        f"- Predictions: **{m.get('predictions')}**"
        + (f" (from `{m['source_run']}`)" if m.get("source_run") else ""),
        f"- Extract model: `{m.get('extract_model')}` @ effort `{m.get('extract_effort')}` · "
        f"prompt `{m.get('prompt_version')}` · schema `{m.get('schema_version')}`",
        f"- Judge: {judge} · Matchbox validation: {'on' if m.get('validate') else 'off'}",
        f"- Env overrides: {m.get('env_overrides') or 'none'}",
        f"- Dataset: {summary.n_cases} of {m.get('dataset_size')} cases "
        f"(scored {summary.n_scored}, extraction failed {summary.n_extraction_failed}, "
        f"skipped {summary.n_skipped})",
        "",
        "**Items** (micro P / R / F1; macro F1 over cases with items, n in brackets)",
        "",
        "| section | P | R | F1 | macro F1 | TP / FP / FN |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name in (*ITEM_SECTIONS, "allergy_statements"):
        lines.append(_section_row(name, summary.sections[name]))
    lines.append(_section_row("patient (all)", summary.patient))
    for name in PATIENT_SECTIONS:
        lines.append(_section_row(name, summary.sections[name]))
    raw = ", ".join(f"{name} {_num(s.recall)}" for name, s in summary.raw_sections.items())
    lines += [
        "",
        f"Recall before grounding: {raw}. Match methods: {summary.match_methods or 'none'}.",
        "",
        "**Section state** (items_found / none_known / no_information)",
        "",
        f"Overall accuracy {_pct(summary.state_accuracy)}. "
        f"Critical errors (none_known <-> items_found): {len(summary.critical_state_errors)}"
        + (
            f" - {'; '.join(summary.critical_state_errors)}"
            if summary.critical_state_errors
            else ""
        )
        + f". False assurance (none_known where gold has no information): "
        f"{len(summary.false_assurance)}"
        + (f" - {'; '.join(summary.false_assurance)}" if summary.false_assurance else "")
        + ".",
        "",
        "| section | accuracy | n |",
        "| --- | --- | --- |",
    ]
    for name, state in summary.states.items():
        lines.append(f"| {name} | {_pct(state.accuracy)} | {state.n} |")
    lines += ["", "**Field accuracy on matched items** (exact; lenient for dates)", ""]
    lines += ["| section | field | accuracy | lenient | n |", "| --- | --- | --- | --- | --- |"]
    for section, fields in summary.fields.items():
        for name, f in fields.items():
            lines.append(
                f"| {section} | {name} | {_pct(f.accuracy)} | {_pct(f.lenient_accuracy)} | {f.n} |"
            )
    validation = (
        f"**{summary.validation_passed}/{summary.n_cases - summary.n_skipped} "
        f"({_pct(summary.validation_pass_rate)})** pass (0 errors and no unmatched entries)"
        if summary.validation_ran
        else "not run"
    )
    lines += [
        "",
        f"**Grounding**: {summary.grounding or 'n/a'}; dropped facts {summary.dropped_facts}; "
        f"review flags {summary.review_flags or 'none'}.",
        "",
        f"**Assembly**: {summary.assembly_ok}/{summary.assembly_attempted} ok. "
        f"**Validation**: {validation}.",
    ]
    for case_id, reasons in summary.validation_failures.items():
        shown = "; ".join(reasons[:5]) + (
            f"; ... {len(reasons) - 5} more" if len(reasons) > 5 else ""
        )
        lines.append(f"- `{case_id}`: {shown}")
    lines += ["", "**By language / format** (micro F1 allergies / medications / problems)", ""]
    lines += [
        "| group | n | F1 A / M / P | state acc | validator pass |",
        "| --- | --- | --- | --- | --- |",
    ]
    for label, groups in (("lang", summary.by_language), ("format", summary.by_format)):
        for key, g in groups.items():
            f1 = " / ".join(_num(g.f1[s], 2) for s in ITEM_SECTIONS)
            lines.append(
                f"| {label} {key} | {g.n} | {f1} | {_pct(g.state_accuracy)} | "
                f"{_pct(g.validation_pass_rate)} |"
            )
    u = summary.usage
    lines += [
        "",
        f"**Usage**: input {u.input_tokens}, output {u.output_tokens}, cache write "
        f"{u.cache_creation_input_tokens}, cache read {u.cache_read_input_tokens} tokens; "
        f"cost ${u.total_cost_usd:.4f} (extraction ${u.extraction_cost_usd:.4f}, judge "
        f"${u.judge_cost_usd:.4f} in {u.judge_calls} calls; per case "
        f"${_num(u.cost_per_case_usd, 4)}); latency mean {_num(u.latency_mean_s, 1)} s, "
        f"median {_num(u.latency_median_s, 1)} s, max {_num(u.latency_max_s, 1)} s; "
        f"fallbacks {u.fallbacks}, refusals {u.refusals}, repair turns {u.repair_attempts}, "
        f"errors {u.errors or 'none'}.",
        "",
    ]
    return "\n".join(lines)
