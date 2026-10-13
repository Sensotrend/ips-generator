"""The case definition shared by the builder and the case modules."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Case:
    case_id: str
    language: str
    """Main language (= gold ``document_language``), or ``main+other`` for mixed documents."""
    fmt: str
    """``txt``, ``json``, ``csv`` or ``pdf`` (also the document's file extension)."""
    doc_type: str
    features: tuple[str, ...]
    notes: str
    document: Any
    """txt/csv: str; json: str or JSON value; pdf: list of pages, each a list of lines."""
    gold: dict[str, Any]
