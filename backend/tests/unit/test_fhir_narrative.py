"""Deterministic XHTML narratives: escaping and structure."""

import xml.etree.ElementTree as ET

import pytest

from app.fhir.narrative import (
    XHTML_NS,
    NarrativeLine,
    escape,
    line_narrative,
    list_narrative,
    text_narrative,
)


def test_escape_neutralises_markup() -> None:
    assert escape('<script>alert("x")</script> & co') == (
        '&lt;script&gt;alert("x")&lt;/script&gt; &amp; co'
    )


def test_escape_removes_xml_illegal_characters() -> None:
    assert escape("a\x00b\x0bc\x1fd\ttab\nline") == "abcd\ttab\nline"


def test_hostile_text_stays_well_formed_text() -> None:
    hostile = '</div><img src="x" onerror="alert(1)"/>&amp;\x01'
    narrative = list_narrative([NarrativeLine(hostile, (("note <b>", hostile),))])
    root = ET.fromstring(narrative.div)  # noqa: S314 - our own output, must be well-formed
    assert root.tag == f"{{{XHTML_NS}}}div"
    assert not root.findall(f".//{{{XHTML_NS}}}img")
    assert hostile.replace("\x01", "") in "".join(root.itertext())


def test_narratives_are_generated_xhtml_divs() -> None:
    for narrative in (
        text_narrative("No information available"),
        line_narrative(NarrativeLine("Metformin", (("status", "active"),))),
        list_narrative([NarrativeLine("A"), NarrativeLine("B")]),
    ):
        assert narrative.status == "generated"
        assert narrative.div.startswith(f'<div xmlns="{XHTML_NS}">')
        ET.fromstring(narrative.div)  # noqa: S314 - our own output


def test_line_rendering() -> None:
    line = NarrativeLine("Maapähkinä", (("category", "food"), ("onset", "2015")))
    assert line.to_xhtml() == "<b>Maapähkinä</b> — category: food; onset: 2015"
    assert NarrativeLine("Verenpainetauti").to_xhtml() == "<b>Verenpainetauti</b>"


def test_list_narrative_needs_lines() -> None:
    with pytest.raises(ValueError, match="at least one"):
        list_narrative([])
