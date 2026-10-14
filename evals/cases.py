"""Dataset cases (``evals/dataset/<case_id>/{document.*, gold.json, meta.json}``)."""

from __future__ import annotations

import fnmatch
import json
from collections.abc import Sequence
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path
from typing import Any

from app.pipeline.ingest import ingest
from app.schemas.intermediate import IpsExtraction
from app.schemas.source import IngestedDocument

__all__ = ["DATASET_DIR", "EVALS_DIR", "EvalCase", "load_cases", "select_cases"]

EVALS_DIR = Path(__file__).resolve().parent
DATASET_DIR = EVALS_DIR / "dataset"


@dataclass(frozen=True)
class EvalCase:
    case_id: str
    directory: Path
    meta: dict[str, Any]

    @property
    def language(self) -> str:
        return str(self.meta["language"])

    @property
    def format(self) -> str:
        return str(self.meta["format"])

    @property
    def doc_type(self) -> str:
        return str(self.meta["doc_type"])

    @property
    def media_type(self) -> str:
        return str(self.meta["media_type"])

    @property
    def document_path(self) -> Path:
        return self.directory / f"document.{self.format}"

    @property
    def gold_path(self) -> Path:
        return self.directory / "gold.json"

    @property
    def expected_patient(self) -> dict[str, str | None] | None:
        """True birth date / gender of the patient (``meta.json``, D-10), ``None`` if absent."""
        value = self.meta.get("expected_patient")
        if not isinstance(value, dict):
            return None
        return {key: value.get(key) for key in ("birth_date", "gender")}

    @property
    def extra_sections(self) -> bool:
        """Does the gold annotate the optional sections (``meta.json`` ``extra_sections``)?"""
        return bool(self.meta.get("extra_sections"))

    def load_gold(self) -> IpsExtraction:
        return IpsExtraction.model_validate_json(self.gold_path.read_bytes())

    @cached_property
    def document(self) -> IngestedDocument:
        return ingest(self.document_path.read_bytes(), self.media_type)


def load_cases(dataset_dir: Path = DATASET_DIR) -> list[EvalCase]:
    """All cases of the dataset, sorted by id."""
    cases: list[EvalCase] = []
    for directory in sorted(p for p in dataset_dir.iterdir() if (p / "meta.json").is_file()):
        meta = json.loads((directory / "meta.json").read_text("utf-8"))
        cases.append(EvalCase(case_id=directory.name, directory=directory, meta=meta))
    return cases


def select_cases(cases: Sequence[EvalCase], patterns: Sequence[str] | None) -> list[EvalCase]:
    """Cases whose id matches any pattern: a glob (``fi0*``) or an id prefix (``fi01``)."""
    if not patterns:
        return list(cases)
    selected = [
        case
        for case in cases
        if any(fnmatch.fnmatchcase(case.case_id, p) or case.case_id.startswith(p) for p in patterns)
    ]
    if not selected:
        raise ValueError(f"no case matches {list(patterns)}")
    return selected
