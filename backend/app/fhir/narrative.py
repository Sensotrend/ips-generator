"""Deterministic XHTML narratives (``Narrative.div``) for sections and resources.

FHIR narrative rules (R4 §2.4 / txt-1, txt-2): the ``div`` is XHTML in the
``http://www.w3.org/1999/xhtml`` namespace, uses only basic formatting elements, has no scripts,
event attributes or external references, and contains non-whitespace text. IPS requires
``Composition.section.text`` on every section.

Callers pass **plain text** only; every value is escaped here (``&``, ``<``, ``>``) and
characters that are illegal in XML 1.0 are removed, so document text can never inject markup.
Labels are English; values stay in the document's language (nothing is translated).
"""

from __future__ import annotations

import html
import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.fhir.models import Narrative

XHTML_NS = "http://www.w3.org/1999/xhtml"

_XML_ILLEGAL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f￾￿]")


def escape(text: str) -> str:
    """Escape plain text for XHTML element content."""
    return html.escape(_XML_ILLEGAL.sub("", text), quote=False)


@dataclass(frozen=True, slots=True)
class NarrativeLine:
    """One rendered fact: a bold title and ``label: value`` details (all plain text)."""

    title: str
    details: tuple[tuple[str, str], ...] = ()

    def to_xhtml(self) -> str:
        out = f"<b>{escape(self.title)}</b>"
        if self.details:
            out += " — " + "; ".join(f"{escape(k)}: {escape(v)}" for k, v in self.details)
        return out


def _div(inner: str) -> Narrative:
    return Narrative(status="generated", div=f'<div xmlns="{XHTML_NS}">{inner}</div>')


def text_narrative(text: str) -> Narrative:
    """A narrative with one paragraph of plain text."""
    return _div(f"<p>{escape(text)}</p>")


def line_narrative(line: NarrativeLine) -> Narrative:
    """A resource narrative for a single fact."""
    return _div(f"<p>{line.to_xhtml()}</p>")


def list_narrative(lines: Sequence[NarrativeLine]) -> Narrative:
    """A section narrative: one list item per fact."""
    if not lines:
        raise ValueError("a list narrative needs at least one line")
    items = "".join(f"<li>{line.to_xhtml()}</li>" for line in lines)
    return _div(f"<ul>{items}</ul>")
