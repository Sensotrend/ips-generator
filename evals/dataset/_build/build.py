"""Deterministic builder for the Phase 1 eval dataset (``evals/dataset/``).

Run from ``backend/`` (it uses the backend's ingester, grounding and schema)::

    uv run python ../evals/dataset/_build/build.py

For every case defined in ``cases_*.py`` it

1. renders the document (``document.txt|json|csv|pdf``; PDFs with reportlab, ``invariant=1`` so
   the bytes are reproducible),
2. ingests it with ``app.pipeline.ingest.ingest`` and, for PDFs, checks that the text layer
   reproduces the authored lines,
3. resolves ``page``/``locator`` of every gold fact by locating its ``source_quote`` (a quote
   that occurs more than once must say which occurrence it means),
4. validates the gold with ``IpsExtraction`` and checks that ``ground()`` finds every quote
   ``exact`` at the resolved location and that ``apply_grounding`` raises no flags,
5. writes ``gold.json`` and ``meta.json``, and regenerates the feature matrix in ``README.md``.

``meta.json`` ``expected_patient`` holds the *true* birth date and gender the IPS Patient should
carry (D-10): the stated value when the document states one, else, for the birth date, the
date a case's synthetic HETU was generated from (``gold.HETU_BIRTH_DATES``, the authoring
input; never the pipeline's parser). Gender is never expected from a HETU: the dataset's codes
use individual numbers 900-999, which carry no sex (``app.pipeline.derive``). The gold
extraction itself keeps ``birth_date: null`` when only a HETU is present (LLM-layer truth).

Case directories that no longer have a definition are deleted.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any

BUILD_DIR = Path(__file__).resolve().parent
DATASET_DIR = BUILD_DIR.parent
REPO_ROOT = DATASET_DIR.parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(BUILD_DIR))

from case import Case  # noqa: E402
from gold import HETU_BIRTH_DATES  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.pdfgen import canvas  # noqa: E402

from app.pipeline.ground import GroundingStatus, apply_grounding, ground  # noqa: E402
from app.pipeline.ingest import ingest  # noqa: E402
from app.schemas.intermediate import IpsExtraction  # noqa: E402
from app.schemas.source import IngestedDocument  # noqa: E402

MEDIA_TYPES = {
    "txt": "text/plain",
    "json": "application/json",
    "csv": "text/csv",
    "pdf": "application/pdf",
}
LANGUAGES = ("fi", "sv", "en", "fi+sv", "fi+en")
DOC_TYPES = (
    "discharge_summary",
    "referral_letter",
    "prescription",
    "medication_list",
    "lab_report",
    "outpatient_note",
)

FEATURES: dict[str, str] = {
    "nkda_plus_food_allergy": "NKDA-type statement next to a food allergy (D-7)",
    "none_known_allergies": "Explicit 'no known allergies' (allergies none_known)",
    "section_no_information": "At least one section with no information at all",
    "no_regular_medication": "Explicit 'no regular medication' (medications none_known)",
    "regular_none_plus_new_course": "'No regular medication' plus a newly prescribed drug",
    "printed_icd10": "ICD-10 codes printed next to diagnoses (D-9)",
    "printed_atc": "ATC codes printed next to medications (D-9)",
    "resolved_condition": "Resolved/past condition alongside active ones (D-8)",
    "family_history_distractor": "Family history that must not become a problem",
    "duplicated_medication": "Same medication in narrative/summary and list (report once)",
    "stopped_medication": "Stopped / discontinued medication",
    "paused_medication": "Paused medication (on_hold)",
    "as_needed_dosing": "As-needed (PRN) dosing",
    "partial_dates": "Year-only or month-year dates",
    "abbreviations": "Clinical abbreviations (p.o., x2, tabl, RR, DM2, ...)",
    "typos": "Spelling mistakes kept verbatim in quotes",
    "prompt_injection": "Embedded instructions / fake markup aimed at the model",
    "other_person_mentioned": "Facts about another person (caregiver, relative)",
    "hetu_without_birth_date": "HETU present, no birth date stated (birth_date null, D-10)",
    "lab_report_all_no_information": "Lab report with nothing for the three sections",
    "multi_page_pdf": "PDF with more than one page",
    "mostly_empty_page": "PDF page with (almost) no text",
    "mixed_language": "Document mixing two languages",
    "caps_headings": "Headings in capitals",
    "messy_formatting": "Inconsistent formatting, mixed line breaks, stray whitespace",
    "decimal_comma": "Finnish/Swedish decimal commas",
    "suspected_condition": "Suspected / provisional diagnosis",
    "multi_segment_quote": "Gold quote spans several segments (JSON leaves / lines)",
    "procedure_distractor": "Operation/procedure listed that is not a problem",
    "indication_not_problem": "Medication indication that must not become a problem",
    "gender_stated": "Gender explicitly stated",
    "birth_date_stated": "Birth date explicitly stated",
    "allergy_reactions": "Allergy with stated reaction(s)",
    "intolerance": "Intolerance (not allergy)",
    "physio_questionnaire_candidate": "Built to pre-fill the physiotherapy low-back questionnaire",
    "maternity_questionnaire_candidate": "Built to pre-fill the maternity clinic questionnaire",
    "multi_context_candidate": "One summary built for maternity, physiotherapy and unplanned care use",
    "severe_allergy_criticality": "Allergy worded as severe hypersensitivity with criticality high (criticality high, reaction severity severe)",
    "non_schema_facts": "Facts for other IPS sections in the text (vital signs, results, vaccinations, procedures, devices, plan of care, pregnancy history, social history, ...); gold ignores them (outside the schema)",
}


# ---- rendering ----------------------------------------------------------------------------

_PDF_TOP = 800.0
_PDF_BOTTOM = 50.0
_PDF_LEADING = 14.0


def render_pdf(pages: list[list[str]]) -> bytes:
    """Lines starting with ``"# "`` are bold headings (marker stripped)."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4, invariant=1)
    pdf.setTitle("Synthetic test document")
    pdf.setAuthor("ips-generator eval dataset (synthetic)")
    for lines in pages:
        y = _PDF_TOP
        for line in lines:
            if y < _PDF_BOTTOM:
                raise ValueError("too many lines for one PDF page")
            if line.startswith("# "):
                pdf.setFont("Helvetica-Bold", 11)
                pdf.drawString(50, y, line[2:])
            else:
                pdf.setFont("Helvetica", 10)
                pdf.drawString(50, y, line)
            y -= _PDF_LEADING
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def render(case: Case) -> bytes:
    if case.fmt == "pdf":
        return render_pdf(case.document)
    if case.fmt == "json" and not isinstance(case.document, str):
        return (json.dumps(case.document, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    text: str = case.document
    return text.encode("utf-8")


def _pdf_expected_text(lines: list[str]) -> str:
    stripped = [re.sub(r" +", " ", ln.removeprefix("# ")).strip() for ln in lines]
    return "\n".join(ln for ln in stripped).strip("\n")


def check_pdf_text(case: Case, doc: IngestedDocument) -> None:
    for number, lines in enumerate(case.document, start=1):
        expected = _pdf_expected_text(lines)
        actual = doc.page_text(number)
        # Blank authored lines produce no text line in the PDF text layer.
        expected = "\n".join(ln for ln in expected.split("\n") if ln.strip())
        if actual != expected:
            raise AssertionError(f"{case.case_id}: PDF page {number} text layer differs")


# ---- gold resolution ----------------------------------------------------------------------


def _occurrences(doc: IngestedDocument, quote: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    for number in doc.pages:
        segments = doc.segments_on_page(number)
        starts: list[int] = []
        position = 0
        for segment in segments:
            starts.append(position)
            position += len(segment.text) + 1
        text = doc.page_text(number)
        index = text.find(quote)
        while index != -1:
            segment_index = max(i for i, start in enumerate(starts) if start <= index)
            found.append((number, segments[segment_index].locator or ""))
            index = text.find(quote, index + 1)
    return found


def _position(doc: IngestedDocument, quote: str, nth: int | None) -> tuple[int, int]:
    """(page, offset in the page text) of the chosen occurrence of ``quote``."""
    hits: list[tuple[int, int]] = []
    for number in doc.pages:
        text = doc.page_text(number)
        index = text.find(quote)
        while index != -1:
            hits.append((number, index))
            index = text.find(quote, index + 1)
    return hits[nth or 0]


def check_item_order(case: Case, doc: IngestedDocument) -> None:
    """Items (and allergy statements) are listed in the document order of their quotes."""
    for section in ("allergies", "medications", "problems"):
        data = case.gold[section]
        for key in ("items", "none_known_statements"):
            positions = [
                _position(doc, fact["source_quote"], fact.get("_nth")) for fact in data.get(key, [])
            ]
            if positions != sorted(positions):
                raise AssertionError(f"{case.case_id}: {section}.{key} not in document order")
    lists = {
        name: case.gold.get(name, []) for name in ("vital_signs", "social_history", "immunizations")
    }
    lists["pregnancy"] = case.gold.get("pregnancy", [])
    lists["patient.contacts"] = case.gold["patient"].get("contacts", [])
    for name, facts in lists.items():
        positions = [_position(doc, fact["source_quote"], fact.get("_nth")) for fact in facts]
        if positions != sorted(positions):
            raise AssertionError(f"{case.case_id}: {name} not in document order")


def resolve(node: Any, doc: IngestedDocument, case_id: str) -> Any:
    if isinstance(node, list):
        return [resolve(value, doc, case_id) for value in node]
    if not isinstance(node, dict):
        return node
    out = {key: resolve(value, doc, case_id) for key, value in node.items() if key != "_nth"}
    if "source_quote" in node:
        quote = node["source_quote"]
        nth = node.get("_nth")
        hits = _occurrences(doc, quote)
        if not hits:
            raise AssertionError(f"{case_id}: quote not in document: {quote!r}")
        if nth is None and len(hits) > 1:
            raise AssertionError(f"{case_id}: ambiguous quote ({len(hits)} hits): {quote!r}")
        page, locator = hits[nth or 0]
        out["page"] = page
        out["locator"] = locator
    return out


# ---- checks -------------------------------------------------------------------------------


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


_HETU = re.compile(r"\b(\d{6})[-+A-FU-Y](\d{3})[0-9A-Y]\b")


def check_case(case: Case, doc: IngestedDocument, gold: dict[str, Any]) -> None:
    _require(case.language in LANGUAGES, case.case_id)
    _require(case.fmt in MEDIA_TYPES, case.case_id)
    _require(case.doc_type in DOC_TYPES, case.case_id)
    unknown = set(case.features) - set(FEATURES)
    _require(not unknown, f"{case.case_id}: unknown features {unknown}")
    _require(gold["document_language"] == case.language.split("+")[0], case.case_id)
    for match in _HETU.finditer(doc.full_text):
        _require(int(match.group(2)) >= 900, f"{case.case_id}: non-synthetic HETU")
    extraction = IpsExtraction.model_validate(gold)
    report = ground(extraction, doc)
    for fact in report.facts:
        if fact.status is not GroundingStatus.EXACT:
            raise AssertionError(f"{case.case_id}: {fact.path} grounded {fact.status}")
    grounded = apply_grounding(extraction, report)
    _require(not grounded.flags, f"{case.case_id}: grounding flags {grounded.flags}")


# ---- output -------------------------------------------------------------------------------


def expected_patient(case: Case, gold: dict[str, Any]) -> dict[str, str | None]:
    """True birth date / gender of the patient (see the module docstring)."""
    patient = gold["patient"]
    births = {
        HETU_BIRTH_DATES[i["value"]] for i in patient["identifiers"] if i["value"] in HETU_BIRTH_DATES
    }
    _require(len(births) <= 1, f"{case.case_id}: identifiers with different HETU birth dates")
    stated = patient["birth_date"]["value"] if patient["birth_date"] else None
    if stated is not None and births:
        _require(births == {stated}, f"{case.case_id}: stated birth date differs from the HETU")
    birth = stated if stated is not None else next(iter(births), None)
    gender = patient["gender"]["value"] if patient["gender"] else None
    return {"birth_date": birth, "gender": gender}


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_case(case: Case) -> None:
    directory = DATASET_DIR / case.case_id
    if directory.exists():
        shutil.rmtree(directory)
    directory.mkdir(parents=True)
    data = render(case)
    media_type = MEDIA_TYPES[case.fmt]
    doc = ingest(data, media_type)
    if case.fmt == "pdf":
        check_pdf_text(case, doc)
    gold = resolve(case.gold, doc, case.case_id)
    check_item_order(case, doc)
    check_case(case, doc, gold)
    (directory / f"document.{case.fmt}").write_bytes(data)
    write_json(directory / "gold.json", gold)
    write_json(
        directory / "meta.json",
        {
            "case_id": case.case_id,
            "language": case.language,
            "format": case.fmt,
            "media_type": media_type,
            "doc_type": case.doc_type,
            "features": list(case.features),
            "notes": case.notes,
            "expected_patient": expected_patient(case, gold),
            **({"extra_sections": True} if case.extra_sections else {}),
        },
    )


def _section_kind(gold: dict[str, Any], section: str) -> str:
    kind: str = gold[section]["kind"]
    return {"items_found": "items", "none_known": "none", "no_information": "-"}[kind]


def feature_matrix(cases: list[Case]) -> str:
    lines = [
        "| case | lang | format | doc type | allergies | meds | problems | features |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case in cases:
        sections = [_section_kind(case.gold, s) for s in ("allergies", "medications", "problems")]
        lines.append(
            f"| `{case.case_id}` | {case.language} | {case.fmt} | {case.doc_type} | "
            + " | ".join(sections)
            + " | "
            + ", ".join(case.features)
            + " |"
        )
    lines += ["", "Feature coverage (number of cases):", "", "| feature | cases | description |"]
    lines.append("| --- | --- | --- |")
    for feature, description in FEATURES.items():
        count = sum(feature in case.features for case in cases)
        lines.append(f"| `{feature}` | {count} | {description} |")
    lines += ["", "Totals:", ""]
    for label, key in (("language", "language"), ("format", "fmt"), ("doc type", "doc_type")):
        counts: dict[str, int] = {}
        for case in cases:
            value = getattr(case, key)
            counts[value] = counts.get(value, 0) + 1
        lines.append(f"- {label}: " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
    return "\n".join(lines)


def write_readme(cases: list[Case]) -> None:
    template = (BUILD_DIR / "README.template.md").read_text(encoding="utf-8")
    readme = template.replace("{{CASE_COUNT}}", str(len(cases))).replace(
        "{{FEATURE_MATRIX}}", feature_matrix(cases)
    )
    (DATASET_DIR / "README.md").write_text(readme, encoding="utf-8")


def all_cases() -> list[Case]:
    import cases_en
    import cases_fi
    import cases_mixed
    import cases_questionnaire
    import cases_sv

    cases: list[Case] = [*cases_fi.CASES, *cases_sv.CASES, *cases_en.CASES, *cases_mixed.CASES, *cases_questionnaire.CASES]
    ids = [case.case_id for case in cases]
    duplicates = {i for i in ids if ids.count(i) > 1}
    _require(not duplicates, f"duplicate case ids: {duplicates}")
    return cases


def main() -> None:
    cases = all_cases()
    for case in cases:
        build_case(case)
    keep = {case.case_id for case in cases}
    for directory in DATASET_DIR.iterdir():
        if directory.is_dir() and (directory / "meta.json").exists() and directory.name not in keep:
            shutil.rmtree(directory)
    write_readme(cases)
    print(f"built {len(cases)} cases in {DATASET_DIR}")


if __name__ == "__main__":
    main()
