"""Ingested source document: located text segments produced by `app.pipeline.ingest`.

Every downstream step (extraction, grounding, the review UI) refers back to the source through
`(page, locator)` pairs, so this contract is shared and must stay stable.

Locator conventions (set by the ingester, see `app/pipeline/ingest.py`):

- plaintext / markdown: ``"line N"`` (1-based line number in the whole file)
- JSON: ``"$.medications[2].name"`` (JSONPath-like path of a leaf value)
- CSV: ``"row N"`` (1-based record number in the file; the header row is ``row 1``)
- PDF: ``None`` (one segment per page; the page number is the location)
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class SourceSegment(BaseModel):
    """A located piece of source text.

    `text` is what grounding matches `source_quote` against, so it is kept as close to the
    source as possible (see the normalisation notes in `app/pipeline/ingest.py`).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    page: Annotated[int, Field(ge=1)]
    """1-based page number; 1 for non-paged inputs (JSON, CSV, plaintext without form feeds)."""
    locator: str | None
    """Position within the page, e.g. ``"line 12"``, ``"row 4"``, ``"$.medications[2].name"``;
    ``None`` when the segment is a whole PDF page."""
    text: str

    def marker(self) -> str:
        """Human/LLM-readable position label, e.g. ``page 1, line 12`` or ``page 2``."""
        if self.locator is None:
            return f"page {self.page}"
        return f"page {self.page}, {self.locator}"


class IngestedDocument(BaseModel):
    """A source document normalised into ordered, located text segments."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    media_type: str
    """Effective (sniffed, canonical) media type: ``text/plain``, ``application/json``,
    ``text/csv`` or ``application/pdf``."""
    segments: list[SourceSegment]
    """Segments in document order."""
    page_count: Annotated[int, Field(ge=1)] = 1
    """Number of pages in the source (PDF pages, or form-feed separated plaintext pages)."""
    pages_without_text: tuple[int, ...] = ()
    """PDF pages whose text layer is missing or not meaningful (e.g. an embedded scan). The
    document was still accepted because most pages have text; downstream should flag these
    pages for review since their content is invisible to extraction."""

    # ---- lookup helpers -------------------------------------------------------------------

    @property
    def pages(self) -> list[int]:
        """Sorted page numbers that have at least one segment."""
        return sorted({s.page for s in self.segments})

    def segments_on_page(self, page: int) -> list[SourceSegment]:
        return [s for s in self.segments if s.page == page]

    def page_text(self, page: int) -> str:
        """Plain text of one page (segments joined by newlines, no markers).

        Use this, not `render_for_llm`, when matching a `source_quote` reported for `page`.
        """
        return "\n".join(s.text for s in self.segments_on_page(page))

    def find_segment(self, page: int, locator: str | None) -> SourceSegment | None:
        """Exact lookup by `(page, locator)`; `None` if no such segment exists."""
        for s in self.segments:
            if s.page == page and s.locator == locator:
                return s
        return None

    def iter_page_texts(self) -> Iterator[tuple[int, str]]:
        """Yield `(page, page_text)` for every page that has segments."""
        for page in self.pages:
            yield page, self.page_text(page)

    @property
    def full_text(self) -> str:
        """All segment texts joined by newlines, without markers (for search/metrics)."""
        return "\n".join(s.text for s in self.segments)

    # ---- LLM rendering ----------------------------------------------------------------------

    def render_for_llm(self) -> str:
        """Render the document for the extraction prompt.

        Each segment is wrapped in a ``<segment>`` tag whose attributes are exactly the values the
        model must copy into an extracted fact's ``page`` and ``locator`` fields; the tag body is
        the verbatim segment text the model quotes from. Example::

            <document media_type="text/plain" pages="1">
            <segment page="1" locator="line 1">Potilas: Testi Potilas</segment>
            <segment page="1" locator="line 3">Lääkitys: Burana 600 mg 1x3</segment>
            </document>

        PDF page segments have no ``locator`` attribute. Segment text is not escaped, so quotes
        stay byte-identical to the source.
        """
        lines = [f'<document media_type="{self.media_type}" pages="{self.page_count}">']
        for s in self.segments:
            attrs = f'page="{s.page}"'
            if s.locator is not None:
                attrs += f' locator="{_escape_attr(s.locator)}"'
            if "\n" in s.text:
                lines.append(f"<segment {attrs}>\n{s.text}\n</segment>")
            else:
                lines.append(f"<segment {attrs}>{s.text}</segment>")
        lines.append("</document>")
        return "\n".join(lines)


def _escape_attr(value: str) -> str:
    return value.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")
