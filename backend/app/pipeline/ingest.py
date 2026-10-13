"""Step 1: ingest and normalise a source document into located text segments.

Phase 1 inputs (PLAN.md §7.1 D-2): plaintext/markdown, JSON, CSV and PDFs with a text layer.
Scans, photos and OCR come in Phase 4; image-only PDFs are rejected with `NoTextLayerError`.

Segmentation (locators are documented in `app/schemas/source.py`):

- **plaintext / markdown — one segment per non-blank line**, locator ``line N`` (global 1-based
  line number, so it matches any editor and the UI can highlight exactly that line). Form feeds
  (``\\f``, as written by ``pdftotext``) start a new page; line numbers keep counting across pages.
- **JSON — one segment per leaf value**, locator ``$.a.b[2].c``; the segment text repeats the key
  path (``a.b[2].c: value``) so the meaning of a bare value survives without its surroundings.
  Empty objects/arrays are leaves too (``allergies: []`` can mean "none known").
- **CSV — one segment per record**, locator ``row N`` (1-based record number as a spreadsheet
  shows it; the header is ``row 1``), text ``header: value | header: value`` with empty cells
  omitted.
- **PDF — one segment per page** (locator ``None``) from the `pdfplumber` text layer.

Normalisation is deliberately minimal, because grounding matches the model's ``source_quote``
against segment text:

- byte-order marks are removed; ``\\r\\n`` and ``\\r`` become ``\\n``;
- Unicode is normalised to NFC (PDFs and macOS often emit decomposed ``a`` + U+0308 for ``ä``,
  which would never match the model's composed output);
- control characters other than ``\\n`` and ``\\t`` are removed;
- trailing whitespace is stripped from each line, and blank lines/pages produce no segment;
- CSV cells are stripped of surrounding whitespace.

Nothing else (no case folding, no collapsing of inner whitespace, no de-hyphenation) is changed;
`ground.py` is responsible for whitespace-tolerant matching.

Document contents are never logged and never included in exception messages.
"""

from __future__ import annotations

import codecs
import csv
import io
import json
import logging
import re
import unicodedata
from collections.abc import Iterator
from typing import Any, Final

import pdfplumber
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfplumber.utils.exceptions import PdfminerException

from app.schemas.source import IngestedDocument, SourceSegment

logger = logging.getLogger(__name__)

# ---- limits -------------------------------------------------------------------------------

MAX_PDF_BYTES: Final = 25 * 1024 * 1024
"""Maximum PDF upload size."""
MAX_TEXT_BYTES: Final = 5 * 1024 * 1024
"""Maximum size for plaintext, JSON and CSV (5 MiB of text is far beyond any clinical summary)."""
MAX_PDF_PAGES: Final = 300
MAX_SEGMENTS: Final = 50_000
"""Upper bound on segments per document (JSON leaves, CSV rows, text lines)."""
MAX_JSON_DEPTH: Final = 64

MIN_MEANINGFUL_CHARS_PER_PAGE: Final = 20
"""A PDF page counts as having a text layer if it has at least this many letters/digits."""
MIN_TEXT_PAGE_FRACTION: Final = 0.5
"""Reject a PDF unless at least this fraction of its pages has a meaningful text layer."""

# ---- canonical media types ------------------------------------------------------------------

TEXT_PLAIN: Final = "text/plain"
APPLICATION_JSON: Final = "application/json"
TEXT_CSV: Final = "text/csv"
APPLICATION_PDF: Final = "application/pdf"

_PLAINTEXT_TYPES: Final = frozenset({"text/plain", "text/markdown", "text/x-markdown"})
_JSON_TYPES: Final = frozenset({"application/json", "text/json"})
_CSV_TYPES: Final = frozenset(
    {"text/csv", "application/csv", "text/tab-separated-values", "text/x-csv"}
)
_GENERIC_TYPES: Final = frozenset({"", "application/octet-stream", "binary/octet-stream"})
_EXTENSIONS: Final = {
    ".txt": TEXT_PLAIN,
    ".text": TEXT_PLAIN,
    ".md": TEXT_PLAIN,
    ".markdown": TEXT_PLAIN,
    ".json": APPLICATION_JSON,
    ".csv": TEXT_CSV,
    ".tsv": TEXT_CSV,
    ".pdf": APPLICATION_PDF,
}
# Magic numbers of formats we recognise but do not (yet) support.
_UNSUPPORTED_MAGIC: Final = (
    (b"\x89PNG\r\n\x1a\n", "PNG image"),
    (b"\xff\xd8\xff", "JPEG image"),
    (b"GIF87a", "GIF image"),
    (b"GIF89a", "GIF image"),
    (b"II*\x00", "TIFF image"),
    (b"MM\x00*", "TIFF image"),
    (b"PK\x03\x04", "ZIP container (e.g. DOCX)"),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "legacy MS Office document"),
    (b"{\\rtf", "RTF document"),
)


# ---- errors -------------------------------------------------------------------------------


class IngestError(ValueError):
    """Base class for documents that cannot be ingested. Messages never contain document text."""


class UnsupportedMediaTypeError(IngestError):
    """The (declared or sniffed) format is not supported in this phase."""


class DocumentTooLargeError(IngestError):
    """The document exceeds a size, page, segment or nesting limit."""


class EmptyDocumentError(IngestError):
    """The document contains no text."""


class CorruptDocumentError(IngestError):
    """The document cannot be decoded or parsed (malformed JSON/CSV, broken PDF, ...)."""


class EncryptedDocumentError(IngestError):
    """The PDF is password protected."""


class NoTextLayerError(IngestError):
    """The PDF has no meaningful text layer (scanned/image-only); OCR arrives in Phase 4."""


# ---- entry point --------------------------------------------------------------------------


def ingest(data: bytes, media_type: str, filename: str | None = None) -> IngestedDocument:
    """Normalise a document into located text segments.

    `media_type` is the declared type (e.g. an upload's Content-Type, parameters such as
    ``charset`` are honoured); `filename` is only used for its extension when the declared type is
    generic. Obvious mismatches are sniffed from the content: ``%PDF`` data is always parsed as PDF,
    and known binary formats (images, DOCX, ...) are rejected even if declared as text.

    Raises a subclass of `IngestError` on failure.
    """
    base_type, charset = _parse_media_type(media_type)
    kind = _resolve_kind(data, base_type, filename)

    limit = MAX_PDF_BYTES if kind == APPLICATION_PDF else MAX_TEXT_BYTES
    if len(data) > limit:
        raise DocumentTooLargeError(
            f"Document is {len(data)} bytes; the limit for {kind} is {limit} bytes."
        )
    if not data.strip():
        raise EmptyDocumentError("Document is empty.")

    if kind == APPLICATION_PDF:
        doc = _ingest_pdf(data)
    else:
        text = _decode_text(data, charset)
        if kind == APPLICATION_JSON:
            doc = _ingest_json(text)
        elif kind == TEXT_CSV:
            tab_hint = base_type == "text/tab-separated-values" or (
                filename is not None and filename.lower().endswith(".tsv")
            )
            doc = _ingest_csv(text, tab_hint=tab_hint)
        else:
            doc = _ingest_plaintext(text)

    if not doc.segments:
        raise EmptyDocumentError("Document contains no text.")
    if len(doc.segments) > MAX_SEGMENTS:
        raise DocumentTooLargeError(
            f"Document has {len(doc.segments)} segments; the limit is {MAX_SEGMENTS}."
        )
    # Metadata only: never log document contents.
    logger.info(
        "ingested document: media_type=%s bytes=%d pages=%d segments=%d pages_without_text=%d",
        doc.media_type,
        len(data),
        doc.page_count,
        len(doc.segments),
        len(doc.pages_without_text),
    )
    return doc


# ---- media type resolution ----------------------------------------------------------------


def _parse_media_type(media_type: str) -> tuple[str, str | None]:
    base, _, params = media_type.partition(";")
    charset: str | None = None
    for param in params.split(";"):
        key, _, value = param.partition("=")
        if key.strip().lower() == "charset" and value.strip():
            charset = value.strip().strip('"').lower()
    return base.strip().lower(), charset


def _resolve_kind(data: bytes, base_type: str, filename: str | None) -> str:
    head = data[:1024]
    if b"%PDF-" in head:
        return APPLICATION_PDF
    for magic, label in _UNSUPPORTED_MAGIC:
        if data.startswith(magic):
            raise UnsupportedMediaTypeError(
                f"Content looks like a {label}, which is not supported yet "
                "(Phase 1 accepts plaintext, JSON, CSV and text-layer PDF)."
            )

    if base_type in _GENERIC_TYPES or (
        # Windows browsers commonly send this for .csv uploads.
        base_type == "application/vnd.ms-excel"
        and filename is not None
        and filename.lower().endswith(".csv")
    ):
        ext = _extension(filename)
        if ext in _EXTENSIONS:
            base_type = _EXTENSIONS[ext]
        elif head.lstrip(b"\xef\xbb\xbf \t\r\n")[:1] in (b"{", b"["):
            base_type = APPLICATION_JSON
        else:
            base_type = TEXT_PLAIN

    if base_type == APPLICATION_PDF:
        raise CorruptDocumentError("Declared as PDF but the content has no PDF header.")
    if base_type in _PLAINTEXT_TYPES:
        return TEXT_PLAIN
    if base_type in _JSON_TYPES or (
        base_type.startswith("application/") and base_type.endswith("+json")
    ):
        return APPLICATION_JSON
    if base_type in _CSV_TYPES:
        return TEXT_CSV
    raise UnsupportedMediaTypeError(
        f"Media type {base_type!r} is not supported "
        "(Phase 1 accepts plaintext, markdown, JSON, CSV and text-layer PDF)."
    )


def _extension(filename: str | None) -> str:
    if not filename or "." not in filename:
        return ""
    return "." + filename.rsplit(".", 1)[1].lower()


# ---- text decoding & normalisation --------------------------------------------------------

_BOMS: Final = (
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
)
# C0/C1 controls except \t (09), \n (0a) and \f (0c, page break); DEL; zero-width no-break space.
_CONTROL_CHARS: Final = re.compile(r"[\x00-\x08\x0b\x0e-\x1f\x7f-\x9f﻿]")


def _decode_text(data: bytes, charset: str | None) -> str:
    """Decode bytes: BOM → declared charset → UTF-8 → cp1252 → latin-1 (never fails)."""
    for bom, encoding in _BOMS:
        if data.startswith(bom):
            try:
                return _normalise(data[len(bom) :].decode(encoding))
            except UnicodeDecodeError:
                raise CorruptDocumentError(
                    f"Document has a {encoding} byte-order mark but is not valid {encoding}."
                ) from None

    if b"\x00" in data[:4096]:
        # Text never contains NUL; this is binary or BOM-less UTF-16/32.
        raise UnsupportedMediaTypeError("Content looks binary, not text.")

    candidates: list[str] = []
    if charset:
        candidates.append(charset)
    candidates += ["utf-8", "cp1252", "latin-1"]
    for encoding in candidates:
        try:
            return _normalise(data.decode(encoding))
        except (UnicodeDecodeError, LookupError):
            continue
    raise AssertionError("unreachable: latin-1 decodes any byte string")  # pragma: no cover


def _normalise(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = unicodedata.normalize("NFC", text)
    return _CONTROL_CHARS.sub("", text)


def _clean_line(line: str) -> str:
    return line.rstrip()


# ---- plaintext ----------------------------------------------------------------------------


def _ingest_plaintext(text: str) -> IngestedDocument:
    segments: list[SourceSegment] = []
    line_no = 0
    for page_index, page_text in enumerate(text.split("\f")):
        page = page_index + 1
        for raw_line in page_text.split("\n"):
            line_no += 1
            line = _clean_line(raw_line)
            if line.strip():
                segments.append(SourceSegment(page=page, locator=f"line {line_no}", text=line))
            if len(segments) > MAX_SEGMENTS:
                raise DocumentTooLargeError(f"Document has more than {MAX_SEGMENTS} lines.")
        # A form feed is not a line break: the last (possibly empty) piece of this page and the
        # first piece of the next page are the same physical line, as editors number it.
        line_no -= 1
    # Drop trailing empty pages (a final form feed is common) from the page count.
    page_count = max((s.page for s in segments), default=1)
    return IngestedDocument(media_type=TEXT_PLAIN, segments=segments, page_count=page_count)


# ---- JSON ---------------------------------------------------------------------------------

_IDENTIFIER: Final = re.compile(r"^[^\W\d]\w*$")


def _ingest_json(text: str) -> IngestedDocument:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        # exc.msg is a fixed parser message; it never contains document text.
        raise CorruptDocumentError(
            f"Invalid JSON: {exc.msg} at line {exc.lineno}, column {exc.colno}."
        ) from None
    except RecursionError:
        raise DocumentTooLargeError("JSON is nested too deeply.") from None

    segments = [
        SourceSegment(page=1, locator=locator, text=_json_leaf_text(locator, leaf))
        for locator, leaf in _json_leaves(value)
    ]
    return IngestedDocument(media_type=APPLICATION_JSON, segments=segments)


def _json_leaves(root: Any) -> Iterator[tuple[str, Any]]:
    """Yield `(locator, leaf)` in document order, iteratively (no recursion limit issues)."""
    stack: list[tuple[str, Any, int]] = [("$", root, 0)]
    count = 0
    while stack:
        path, value, depth = stack.pop()
        if depth > MAX_JSON_DEPTH:
            raise DocumentTooLargeError(f"JSON is nested deeper than {MAX_JSON_DEPTH} levels.")
        if isinstance(value, dict) and value:
            children = [(path + _json_key(str(k)), v) for k, v in value.items()]
        elif isinstance(value, list) and value:
            children = [(f"{path}[{i}]", v) for i, v in enumerate(value)]
        else:
            count += 1
            if count > MAX_SEGMENTS:
                raise DocumentTooLargeError(f"JSON has more than {MAX_SEGMENTS} leaf values.")
            yield path, value
            continue
        stack.extend((p, v, depth + 1) for p, v in reversed(children))


def _json_key(key: str) -> str:
    if _IDENTIFIER.match(key):
        return f".{key}"
    return "['" + key.replace("\\", "\\\\").replace("'", "\\'") + "']"


def _json_leaf_text(locator: str, value: Any) -> str:
    if isinstance(value, str):
        rendered = _normalise(value)
    elif isinstance(value, dict):
        rendered = "{}"
    elif isinstance(value, list):
        rendered = "[]"
    else:  # number, bool, null
        rendered = json.dumps(value)
    key_path = locator.removeprefix("$").removeprefix(".")
    return f"{key_path}: {rendered}" if key_path else rendered


# ---- CSV ----------------------------------------------------------------------------------

_DELIMITERS: Final = (";", "\t", ",", "|")  # tie-break order: Finnish exports favour ';'
_SNIFF_ROWS: Final = 50
_NUMERIC_OR_DATE: Final = re.compile(r"^[\d\s.,:/+\-]+$")


def _ingest_csv(text: str, *, tab_hint: bool = False) -> IngestedDocument:
    delimiter = "\t" if tab_hint else _detect_delimiter(text)
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter, strict=False))
    except csv.Error as exc:
        raise CorruptDocumentError(f"Malformed CSV ({type(exc).__name__}).") from None

    rows = [[cell.strip() for cell in row] for row in rows]
    first_nonempty = next((i for i, r in enumerate(rows) if any(r)), None)
    if first_nonempty is None:
        return IngestedDocument(media_type=TEXT_CSV, segments=[])

    header_row = rows[first_nonempty]
    has_header = _looks_like_header(header_row)
    headers = header_row if has_header else []
    data_start = first_nonempty + 1 if has_header else first_nonempty

    segments: list[SourceSegment] = []
    for index in range(data_start, len(rows)):
        row = rows[index]
        pairs = [
            f"{headers[i] if i < len(headers) and headers[i] else f'column {i + 1}'}: {cell}"
            for i, cell in enumerate(row)
            if cell
        ]
        if pairs:
            segments.append(
                SourceSegment(page=1, locator=f"row {index + 1}", text=" | ".join(pairs))
            )
            if len(segments) > MAX_SEGMENTS:
                raise DocumentTooLargeError(f"CSV has more than {MAX_SEGMENTS} rows.")
    return IngestedDocument(media_type=TEXT_CSV, segments=segments)


def _detect_delimiter(text: str) -> str:
    """Pick the delimiter whose sample rows most consistently match the first row's width."""
    sample_lines = [ln for ln in text.split("\n") if ln.strip()][:_SNIFF_ROWS]
    sample = "\n".join(sample_lines)
    best: tuple[float, int, int] | None = None
    best_delim = ","
    for priority, delim in enumerate(_DELIMITERS):
        try:
            rows = [r for r in csv.reader(io.StringIO(sample), delimiter=delim) if any(r)]
        except csv.Error:
            continue
        if not rows or len(rows[0]) < 2:
            continue
        width = len(rows[0])
        consistency = sum(1 for r in rows if len(r) == width) / len(rows)
        score = (consistency, width, -priority)
        if best is None or score > best:
            best, best_delim = score, delim
    return best_delim


def _looks_like_header(row: list[str]) -> bool:
    cells = [c for c in row if c]
    return (
        len(cells) == len(row)
        and len(set(cells)) == len(cells)
        and not any(_NUMERIC_OR_DATE.match(c) for c in cells)
    )


# ---- PDF ----------------------------------------------------------------------------------

_CID_TOKEN: Final = re.compile(r"\(cid:\d+\)")


def _ingest_pdf(data: bytes) -> IngestedDocument:
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except PdfminerException as exc:
        cause = exc.args[0] if exc.args else exc
        if isinstance(cause, PDFPasswordIncorrect):
            raise EncryptedDocumentError(
                "PDF is password protected; remove the password and upload again."
            ) from None
        raise CorruptDocumentError(f"PDF could not be opened ({type(cause).__name__}).") from None
    except Exception as exc:  # pdfminer raises a variety of parser errors
        raise CorruptDocumentError(f"PDF could not be opened ({type(exc).__name__}).") from None

    segments: list[SourceSegment] = []
    without_text: list[int] = []
    with pdf:
        try:
            page_count = len(pdf.pages)
        except Exception as exc:
            raise CorruptDocumentError(
                f"PDF page tree could not be read ({type(exc).__name__})."
            ) from None
        if page_count == 0:
            raise EmptyDocumentError("PDF has no pages.")
        if page_count > MAX_PDF_PAGES:
            raise DocumentTooLargeError(
                f"PDF has {page_count} pages; the limit is {MAX_PDF_PAGES}."
            )
        for number, page in enumerate(pdf.pages, start=1):
            try:
                raw = page.extract_text() or ""
            except Exception as exc:
                raise CorruptDocumentError(
                    f"Text of PDF page {number} could not be extracted ({type(exc).__name__})."
                ) from None
            finally:
                page.close()
            text = "\n".join(_clean_line(ln) for ln in _normalise(raw).split("\n")).strip("\n")
            meaningful = sum(ch.isalnum() for ch in _CID_TOKEN.sub("", text))
            if meaningful < MIN_MEANINGFUL_CHARS_PER_PAGE:
                without_text.append(number)
            if text.strip():
                segments.append(SourceSegment(page=number, locator=None, text=text))

    text_pages = page_count - len(without_text)
    if text_pages == 0 or text_pages / page_count < MIN_TEXT_PAGE_FRACTION:
        raise NoTextLayerError(
            f"PDF has no usable text layer on {len(without_text)} of {page_count} pages "
            "(likely a scan or image-only PDF). OCR for scanned documents is not supported yet; "
            "please upload a PDF with selectable text."
        )
    return IngestedDocument(
        media_type=APPLICATION_PDF,
        segments=segments,
        page_count=page_count,
        pages_without_text=tuple(without_text),
    )
