"""Versioned prompt files (CLAUDE.md: bump the version when changing a prompt).

A prompt lives in ``<name>_<version>.md`` next to this module. A changed prompt is a new file
with a new version (``extract_v2.md``), never an edit of a released one, so ``Prompt.id`` in
Provenance and eval results always identifies the exact text. The text is returned
byte-for-byte as stored: it is the cached prefix of every request, so nothing request-specific
(dates, ids) may ever be templated into it.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

__all__ = [
    "EXTRACT_PROMPT_VERSION",
    "TERMINOLOGY_PROMPT_VERSION",
    "Prompt",
    "load_extract_prompt",
    "load_prompt",
    "load_terminology_prompt",
]

PROMPTS_DIR = Path(__file__).parent
EXTRACT_PROMPT_VERSION = "v6"
"""Current extraction prompt; bump together with ``SCHEMA_VERSION`` when the schema changes."""
TERMINOLOGY_PROMPT_VERSION = "v1"
"""Current terminology-coding prompt (pipeline step 5, `app.pipeline.terminology`)."""

_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_VERSION_RE = re.compile(r"^v\d+$")


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str

    @property
    def id(self) -> str:
        """Stable identifier recorded with every result, e.g. ``extract_v1``."""
        return f"{self.name}_{self.version}"

    @property
    def sha256(self) -> str:
        """Content hash, to detect an edited released prompt in audits."""
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@lru_cache
def load_prompt(name: str, version: str) -> Prompt:
    """Load ``<name>_<version>.md``; raises `FileNotFoundError` if it does not exist."""
    if not _NAME_RE.fullmatch(name) or not _VERSION_RE.fullmatch(version):
        raise ValueError(f"invalid prompt name/version: {name!r} {version!r}")
    path = PROMPTS_DIR / f"{name}_{version}.md"
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError(f"prompt file {path.name} is empty")
    return Prompt(name=name, version=version, text=text)


def load_extract_prompt() -> Prompt:
    """The system prompt of pipeline step 3 (extraction)."""
    return load_prompt("extract", EXTRACT_PROMPT_VERSION)


def load_terminology_prompt() -> Prompt:
    """The system prompt of pipeline step 5 (terminology tool loop)."""
    return load_prompt("terminology", TERMINOLOGY_PROMPT_VERSION)
