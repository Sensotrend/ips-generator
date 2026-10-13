"""Tests for `app.schemas.source`."""

from __future__ import annotations

import pydantic
import pytest

from app.schemas.source import IngestedDocument, SourceSegment


def _doc() -> IngestedDocument:
    return IngestedDocument(
        media_type="text/plain",
        segments=[
            SourceSegment(page=1, locator="line 1", text="Potilas: Testi Åberg"),
            SourceSegment(page=1, locator="line 3", text="Lääkitys: Burana 600 mg"),
            SourceSegment(page=2, locator="line 4", text="Allergiat:\nei tiedossa"),
        ],
        page_count=2,
    )


def test_render_for_llm_format() -> None:
    assert _doc().render_for_llm() == (
        '<document media_type="text/plain" pages="2">\n'
        '<segment page="1" locator="line 1">Potilas: Testi Åberg</segment>\n'
        '<segment page="1" locator="line 3">Lääkitys: Burana 600 mg</segment>\n'
        '<segment page="2" locator="line 4">\nAllergiat:\nei tiedossa\n</segment>\n'
        "</document>"
    )


def test_render_pdf_segment_without_locator_and_escaped_locator() -> None:
    doc = IngestedDocument(
        media_type="application/pdf",
        segments=[
            SourceSegment(page=1, locator=None, text="Sivu 1"),
            SourceSegment(page=1, locator="$['a\"b']", text="x"),
        ],
    )
    rendered = doc.render_for_llm()
    assert '<segment page="1">Sivu 1</segment>' in rendered
    assert "locator=\"$['a&quot;b']\"" in rendered


def test_lookup_helpers() -> None:
    doc = _doc()
    assert doc.pages == [1, 2]
    assert doc.page_text(1) == "Potilas: Testi Åberg\nLääkitys: Burana 600 mg"
    assert doc.page_text(5) == ""
    assert doc.find_segment(1, "line 3") is not None
    assert doc.find_segment(1, "line 2") is None
    assert dict(doc.iter_page_texts())[2] == "Allergiat:\nei tiedossa"
    assert doc.full_text.startswith("Potilas: Testi Åberg\n")
    assert doc.segments[0].marker() == "page 1, line 1"
    assert SourceSegment(page=3, locator=None, text="").marker() == "page 3"


def test_frozen_and_validated() -> None:
    doc = _doc()
    with pytest.raises(pydantic.ValidationError):
        doc.media_type = "text/csv"  # type: ignore[misc]
    with pytest.raises(pydantic.ValidationError):
        SourceSegment(page=0, locator=None, text="x")
