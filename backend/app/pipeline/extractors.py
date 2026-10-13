"""Extractors used by the API/worker pipeline (`app.pipeline.run`).

* `ClaudeExtractor` calls the real extraction step (`app.pipeline.extract.extract`).
* `LuvnDumpExtractor` reads a LUVN patient dump (JSON) with the deterministic parser in
  `app.sources.luvn.parse`: no LLM, no cost. `build_extractor` puts it in front of the configured
  extractor (`StructuredFirstExtractor`), so a LUVN dump is always parsed and any other document
  goes on to the configured extractor.
* `ReplayExtractor` (**development only**) answers with the gold extraction of an eval dataset
  case (``evals/dataset/<case>/document.*`` + ``gold.json``) whose document bytes are
  byte-identical (SHA-256) to the upload. It lets the whole app run end to end without paid API
  calls; any other document fails with `ReplayMissError`.

Neither logs document content; error messages are fixed strings.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.config import ExtractorKind, Settings
from app.llm.client import LlmClient
from app.schemas.intermediate import IpsExtraction
from app.schemas.source import IngestedDocument
from app.sources.luvn.parse import is_luvn_dump, parse_dump

logger = logging.getLogger(__name__)

__all__ = [
    "ClaudeExtractor",
    "Extractor",
    "ExtractorConfigError",
    "ExtractorOutput",
    "LuvnDumpExtractor",
    "ReplayExtractor",
    "ReplayMissError",
    "StructuredFirstExtractor",
    "build_extractor",
]


@dataclass(frozen=True)
class ExtractorOutput:
    extraction: IpsExtraction
    model: str
    """Model actually used (``replay`` for the replay extractor)."""
    prompt_version: str | None = None


class Extractor(Protocol):
    name: str

    def __call__(self, data: bytes, doc: IngestedDocument) -> ExtractorOutput: ...


class ExtractorConfigError(RuntimeError):
    """The configured extractor cannot be used in this environment."""


class ReplayMissError(LookupError):
    """The replay extractor has no gold answer for this document."""

    def __init__(self) -> None:
        super().__init__(
            "replay extractor has no answer for this document; use one of the eval documents"
        )


class ReplayExtractor:
    """Gold extractions of the eval dataset, keyed by the SHA-256 of the document bytes."""

    name = "replay"

    def __init__(self, dataset_dir: Path) -> None:
        if not dataset_dir.is_dir():
            raise ExtractorConfigError("replay dataset directory not found")
        self._gold: dict[str, Path] = {}
        for case_dir in sorted(p for p in dataset_dir.iterdir() if p.is_dir()):
            gold = case_dir / "gold.json"
            if not gold.is_file():
                continue
            for document in case_dir.glob("document.*"):
                digest = hashlib.sha256(document.read_bytes()).hexdigest()
                self._gold[digest] = gold
        if not self._gold:
            raise ExtractorConfigError("replay dataset contains no cases")
        logger.info("replay extractor loaded %d dataset documents", len(self._gold))

    def __len__(self) -> int:
        return len(self._gold)

    def knows(self, data: bytes) -> bool:
        return hashlib.sha256(data).hexdigest() in self._gold

    def __call__(self, data: bytes, doc: IngestedDocument) -> ExtractorOutput:
        gold = self._gold.get(hashlib.sha256(data).hexdigest())
        if gold is None:
            raise ReplayMissError
        return ExtractorOutput(
            extraction=IpsExtraction.model_validate_json(gold.read_bytes()),
            model="replay",
            prompt_version=None,
        )


class ClaudeExtractor:
    """The real (paid) extraction step."""

    name = "claude"

    def __init__(self, client: LlmClient | None = None) -> None:
        self._client = client

    def __call__(self, data: bytes, doc: IngestedDocument) -> ExtractorOutput:
        from app.pipeline.extract import extract  # imported lazily: pulls in the SDK

        result = extract(doc, client=self._client)
        return ExtractorOutput(
            extraction=result.extraction,
            model=result.model_used,
            prompt_version=result.prompt_version,
        )


class LuvnDumpExtractor:
    """Deterministic parser for LUVN patient dumps (no LLM)."""

    name = "luvn-dump"
    model = "luvn-dump-parser"

    @staticmethod
    def accepts(data: bytes, doc: IngestedDocument) -> bool:
        if doc.media_type != "application/json":
            return False
        try:
            return is_luvn_dump(json.loads(data))
        except ValueError:  # not JSON (cannot happen after ingest), or not UTF-8
            return False

    def __call__(self, data: bytes, doc: IngestedDocument) -> ExtractorOutput:
        return ExtractorOutput(
            extraction=parse_dump(json.loads(data), doc), model=self.model, prompt_version=None
        )


class StructuredFirstExtractor:
    """Use the deterministic LUVN parser for LUVN dumps, the fallback extractor for the rest."""

    def __init__(self, fallback: Extractor) -> None:
        self._fallback = fallback
        self._luvn = LuvnDumpExtractor()
        self.name = fallback.name

    def __call__(self, data: bytes, doc: IngestedDocument) -> ExtractorOutput:
        if self._luvn.accepts(data, doc):
            return self._luvn(data, doc)
        return self._fallback(data, doc)


def build_extractor(settings: Settings) -> Extractor:
    """The extractor selected by ``EXTRACTOR``, behind the LUVN dump parser.

    Replay refuses to run outside development.
    """
    if settings.extractor is ExtractorKind.REPLAY:
        if not settings.is_development:
            raise ExtractorConfigError("EXTRACTOR=replay is only allowed with APP_ENV=development")
        return StructuredFirstExtractor(ReplayExtractor(settings.replay_dataset_dir))
    return StructuredFirstExtractor(ClaudeExtractor())
