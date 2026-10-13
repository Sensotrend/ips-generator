"""Tests for `app.pipeline.ingest` (all fixtures are synthetic)."""

from __future__ import annotations

import io
import json
import logging
from pathlib import Path

import pytest
from PIL import Image
from reportlab.lib.pagesizes import A4
from reportlab.lib.pdfencrypt import StandardEncryption
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from app.pipeline import ingest as ingest_module
from app.pipeline.ingest import (
    CorruptDocumentError,
    DocumentTooLargeError,
    EmptyDocumentError,
    EncryptedDocumentError,
    IngestError,
    NoTextLayerError,
    UnsupportedMediaTypeError,
    ingest,
)

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "ingest"


def _read(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


# ---- PDF builders (deterministic: reportlab `invariant=1`) ---------------------------------

_TEXT_PAGE = [
    "Lähete (synteettinen testiaineisto)",
    "Potilas: Testi Öberg, s. 03.04.1971",
    "Lääkitys: Metformiini 500 mg 1 x 2",
    "Allergiat: penisilliini",
]


def _make_pdf(pages: list[list[str] | None], encrypt: StandardEncryption | None = None) -> bytes:
    """Build a PDF; each page is a list of text lines, or None for an image-only page."""
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4, invariant=1, encrypt=encrypt)
    for lines in pages:
        if lines is None:
            img = Image.new("RGB", (60, 80), (200, 200, 200))
            c.drawImage(ImageReader(img), 50, 400, width=300, height=400)
        else:
            y = 800
            for line in lines:
                c.drawString(50, y, line)
                y -= 20
        c.showPage()
    c.save()
    return buf.getvalue()


# ---- plaintext ----------------------------------------------------------------------------


def test_plaintext_finnish_utf8_line_segments() -> None:
    doc = ingest(_read("fi_discharge_note.txt"), "text/plain")
    assert doc.media_type == "text/plain"
    assert doc.page_count == 1
    by_locator = {s.locator: s.text for s in doc.segments}
    assert by_locator["line 3"] == "Potilas: Testi Äijälä-Öhman, s. 01.02.1950"
    assert by_locator["line 12"] == "- Burana 600 mg tarvittaessa, enintään 3 x päivässä"
    assert "Ålandsk" in by_locator["line 14"]
    # blank lines produce no segments but keep numbering
    assert "line 2" not in by_locator
    assert all(s.page == 1 for s in doc.segments)


def test_plaintext_cp1252_fallback() -> None:
    doc = ingest(_read("cp1252_note.txt"), "text/plain")
    texts = [s.text for s in doc.segments]
    assert texts[1] == "Potilas: Testi Kärkkäinen"
    assert texts[3] == "Allergia: pähkinät \u2013 lievä reaktio"  # cp1252 0x96


def test_plaintext_declared_charset_is_honoured() -> None:
    data = "Lääke: Ibuprofeeni".encode("latin-1")
    doc = ingest(data, "text/plain; charset=ISO-8859-1")
    assert doc.segments[0].text == "Lääke: Ibuprofeeni"


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ("﻿Potilas: Testi Åström\n".encode(), "Potilas: Testi Åström"),
        ("﻿Potilas: Testi Åström\n".encode("utf-16-le"), "Potilas: Testi Åström"),
        ("﻿Potilas: Testi Åström\n".encode("utf-16-be"), "Potilas: Testi Åström"),
    ],
)
def test_plaintext_bom_handling(data: bytes, expected: str) -> None:
    assert ingest(data, "text/plain").segments[0].text == expected


def test_plaintext_normalises_minimally() -> None:
    # decomposed ä (a + U+0308) → NFC; trailing spaces stripped; tabs/inner spaces kept;
    # control characters removed.
    data = "Diagnoosi:\tEteisvärinä   \x07\nRivi  kaksi\n".encode()
    doc = ingest(data, "text/markdown")
    assert doc.media_type == "text/plain"
    assert [s.text for s in doc.segments] == ["Diagnoosi:\tEteisvärinä", "Rivi  kaksi"]


def test_plaintext_form_feed_pages() -> None:
    data = b"Page one line\nsecond\n\fPage two\n\f\fPage four\n\f"
    doc = ingest(data, "text/plain")
    assert [(s.page, s.locator, s.text) for s in doc.segments] == [
        (1, "line 1", "Page one line"),
        (1, "line 2", "second"),
        (2, "line 3", "Page two"),
        (4, "line 4", "Page four"),
    ]
    assert doc.page_count == 4
    assert doc.page_text(1) == "Page one line\nsecond"


# ---- JSON ---------------------------------------------------------------------------------


def test_json_leaf_segments_with_key_paths() -> None:
    doc = ingest(_read("nested.json"), "application/json")
    assert doc.media_type == "application/json"
    seg = {s.locator: s.text for s in doc.segments}
    assert seg["$.patient.name.given[0]"] == "patient.name.given[0]: Testi"
    assert seg["$.patient.name.family"] == "patient.name.family: Åkerlund"
    assert seg["$.medications[2].name"] == "medications[2].name: Burana 600 mg"
    assert seg["$.medications[2].dose"] == "medications[2].dose: null"
    assert seg["$.medications[0].active"] == "medications[0].active: true"
    assert seg["$.allergies"] == "allergies: []"
    assert seg["$.problems[0].onset.year"] == "problems[0].onset.year: 2015"
    assert seg["$['lab results']['P-Krea']"] == "['lab results']['P-Krea']: 84.5"
    # document order is preserved
    locators = [s.locator for s in doc.segments]
    assert locators.index("$.patient.name.family") < locators.index("$.medications[0].name")
    assert all(s.page == 1 for s in doc.segments)


def test_json_scalar_root() -> None:
    doc = ingest(b'"Potilas: Testi"', "application/json")
    assert doc.segments[0].locator == "$"
    assert doc.segments[0].text == "Potilas: Testi"


def test_json_large_flat_array_and_segment_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    data = json.dumps({"rows": list(range(100))}).encode()
    assert len(ingest(data, "application/json").segments) == 100
    monkeypatch.setattr(ingest_module, "MAX_SEGMENTS", 50)
    with pytest.raises(DocumentTooLargeError):
        ingest(data, "application/json")


def test_json_too_deep() -> None:
    data = ("[" * 200 + "]" * 200).encode()
    with pytest.raises(DocumentTooLargeError):
        ingest(data, "application/json")


def test_json_malformed_error_has_no_content() -> None:
    with pytest.raises(CorruptDocumentError) as exc_info:
        ingest(b'{"name": "Testi Salainen",', "application/json")
    assert "Salainen" not in str(exc_info.value)
    assert exc_info.value.__cause__ is None


# ---- CSV ----------------------------------------------------------------------------------


def test_csv_semicolon_with_header() -> None:
    doc = ingest(_read("medications_semicolon.csv"), "text/csv")
    assert doc.media_type == "text/csv"
    assert [(s.locator, s.text) for s in doc.segments] == [
        (
            "row 2",
            "Lääke: Metformiini | Vahvuus: 500 mg | Annostus: 1 x 2 | Aloitettu: 12.03.2021",
        ),
        (
            "row 3",
            "Lääke: Bisoprololi | Vahvuus: 2,5 mg | Annostus: 1 x 1 | Aloitettu: 05.11.2022",
        ),
        # row 4 is blank; empty cells are omitted
        ("row 5", "Lääke: Burana | Vahvuus: 600 mg"),
    ]


def test_csv_comma_quoted_and_no_header() -> None:
    data = b'Metformin,"500 mg, tablet",2021\nSimvastatin,20 mg,2019\n'
    doc = ingest(data, "text/csv")
    assert [s.text for s in doc.segments] == [
        "column 1: Metformin | column 2: 500 mg, tablet | column 3: 2021",
        "column 1: Simvastatin | column 2: 20 mg | column 3: 2019",
    ]
    assert doc.segments[0].locator == "row 1"


def test_csv_tab_delimited() -> None:
    data = "Lääke\tAnnos\nBurana\t600 mg\n".encode()
    doc = ingest(data, "text/tab-separated-values")
    assert doc.segments[0].text == "Lääke: Burana | Annos: 600 mg"


def test_csv_ms_excel_media_type_with_csv_filename() -> None:
    doc = ingest(_read("medications_semicolon.csv"), "application/vnd.ms-excel", "export.csv")
    assert doc.media_type == "text/csv"


# ---- PDF ----------------------------------------------------------------------------------


def test_pdf_text_layer_one_segment_per_page() -> None:
    data = _make_pdf([_TEXT_PAGE, ["Sivu 2: Diagnoosit", "Tyypin 2 diabetes"]])
    doc = ingest(data, "application/pdf")
    assert doc.media_type == "application/pdf"
    assert doc.page_count == 2
    assert [(s.page, s.locator) for s in doc.segments] == [(1, None), (2, None)]
    assert doc.page_text(1) == "\n".join(_TEXT_PAGE)
    assert "Tyypin 2 diabetes" in doc.page_text(2)
    assert doc.pages_without_text == ()


def test_pdf_is_deterministic() -> None:
    assert _make_pdf([_TEXT_PAGE]) == _make_pdf([_TEXT_PAGE])


def test_pdf_image_only_rejected() -> None:
    with pytest.raises(NoTextLayerError, match="OCR"):
        ingest(_make_pdf([None, None]), "application/pdf")


def test_pdf_mostly_images_rejected() -> None:
    with pytest.raises(NoTextLayerError):
        ingest(_make_pdf([_TEXT_PAGE, None, None]), "application/pdf")


def test_pdf_mixed_pages_accepted_and_flagged() -> None:
    doc = ingest(_make_pdf([_TEXT_PAGE, None, _TEXT_PAGE]), "application/pdf")
    assert doc.page_count == 3
    assert doc.pages == [1, 3]
    assert doc.pages_without_text == (2,)


def test_pdf_user_password_rejected() -> None:
    enc = StandardEncryption("user-secret", ownerPassword="owner-secret")
    with pytest.raises(EncryptedDocumentError):
        ingest(_make_pdf([_TEXT_PAGE], encrypt=enc), "application/pdf")


def test_pdf_owner_password_only_is_readable() -> None:
    # Permission-only encryption (empty user password) is common in exports and is readable.
    enc = StandardEncryption("", ownerPassword="owner-secret", canCopy=0)
    doc = ingest(_make_pdf([_TEXT_PAGE], encrypt=enc), "application/pdf")
    assert "Metformiini" in doc.page_text(1)


def test_pdf_corrupt() -> None:
    with pytest.raises(CorruptDocumentError):
        ingest(b"%PDF-1.7\n this is not really a pdf \n%%EOF", "application/pdf")


def test_pdf_page_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingest_module, "MAX_PDF_PAGES", 1)
    with pytest.raises(DocumentTooLargeError):
        ingest(_make_pdf([_TEXT_PAGE, _TEXT_PAGE]), "application/pdf")


# ---- sniffing & media types ---------------------------------------------------------------


def test_pdf_magic_overrides_declared_type() -> None:
    doc = ingest(_make_pdf([_TEXT_PAGE]), "text/plain", "note.txt")
    assert doc.media_type == "application/pdf"


def test_declared_pdf_without_magic_is_corrupt() -> None:
    with pytest.raises(CorruptDocumentError):
        ingest(b"just text", "application/pdf")


@pytest.mark.parametrize(
    "data",
    [b"\x89PNG\r\n\x1a\n" + b"\x00" * 20, b"\xff\xd8\xff\xe0" + b"\x00" * 20, b"PK\x03\x04rest"],
)
def test_binary_formats_rejected_even_if_declared_text(data: bytes) -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        ingest(data, "text/plain")


@pytest.mark.parametrize("media_type", ["image/png", "application/msword", "text/html"])
def test_unsupported_media_types(media_type: str) -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        ingest(b"hello", media_type)


@pytest.mark.parametrize(
    ("filename", "data", "expected"),
    [
        ("meds.csv", b"a;b\n1;2\n", "text/csv"),
        ("data.json", b'{"a": 1}', "application/json"),
        ("note.md", b"# Otsikko\n", "text/plain"),
        (None, b'  {"a": 1}', "application/json"),
        (None, b"Potilas: Testi\n", "text/plain"),
    ],
)
def test_octet_stream_resolved_by_extension_or_content(
    filename: str | None, data: bytes, expected: str
) -> None:
    assert ingest(data, "application/octet-stream", filename).media_type == expected


def test_fhir_json_media_type() -> None:
    doc = ingest(b'{"resourceType": "Patient"}', "application/fhir+json")
    assert doc.segments[0].text == "resourceType: Patient"


def test_binary_without_bom_rejected() -> None:
    with pytest.raises(UnsupportedMediaTypeError):
        ingest(b"abc\x00def", "text/plain")


# ---- limits & empty -----------------------------------------------------------------------


@pytest.mark.parametrize("data", [b"", b"   \n\n\t  \n"])
def test_empty_documents(data: bytes) -> None:
    with pytest.raises(EmptyDocumentError):
        ingest(data, "text/plain")


def test_empty_csv_rows_only() -> None:
    with pytest.raises(EmptyDocumentError):
        ingest(b"a;b\n;\n", "text/csv")


def test_text_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ingest_module, "MAX_TEXT_BYTES", 10)
    with pytest.raises(DocumentTooLargeError):
        ingest(b"Potilas: Testi Potilas\n", "text/plain")


def test_errors_share_base_class() -> None:
    assert issubclass(NoTextLayerError, IngestError)
    assert issubclass(IngestError, ValueError)


def test_does_not_log_document_contents(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    ingest(_read("fi_discharge_note.txt"), "text/plain")
    ingest(_make_pdf([_TEXT_PAGE]), "application/pdf")
    assert "Äijälä" not in caplog.text
    assert "Öberg" not in caplog.text
