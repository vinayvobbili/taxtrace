"""A document's text, page by page, with the layout kept so columns still line up.

Every later step quotes from these pages, so this is the one place text comes out of a file: a value's
quote is checked against exactly what this returns.

A scanned PDF has pictures of pages and no text. Given an `ocr_cache` folder, such a file goes through
ocrmypdf (Tesseract, on this machine) once, and the searchable copy is kept there under the original's
sha256: OCR isn't byte-for-byte repeatable, and a quote must keep matching the text it was checked against.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import zipfile
from collections.abc import Iterator
from pathlib import Path
from xml.etree import ElementTree

TEXT_SUFFIXES = {".txt", ".csv", ".tsv"}
PDF_SUFFIXES = {".pdf"}
OFFICE_SUFFIXES = {".docx", ".xlsx"}  # zip files of XML, read with the standard library
SUPPORTED = TEXT_SUFFIXES | PDF_SUFFIXES | OFFICE_SUFFIXES
WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
SHEET = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
RELS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
REL_ID = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
CELL = " | "  # between a table's or a sheet's cells
# A page with less text than this is a picture of a page (or blank, which OCR leaves blank).
OCR_MIN_CHARS = 20
# pdfminer warns about each font a PDF describes loosely ("Could not get FontBBox"), and the text still reads
logging.getLogger("pdfminer").setLevel(logging.ERROR)


class UnsupportedDocument(ValueError):
    pass


class Locked(UnsupportedDocument):
    """A password-protected PDF, and the password given (if any) didn't open it."""


def pages(path: Path, password: str | None = None, ocr_cache: Path | None = None) -> list[str]:
    suffix = path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        found = _pdf_pages(path, password)
        # A locked file can't go through ocrmypdf; its text layer is what there is.
        if ocr_cache is not None and password is None and needs_ocr(found):
            try:
                found = _pdf_pages(ocr(path, ocr_cache), None)
            except UnsupportedDocument:
                # without ocrmypdf (or when it fails) a document with some text still reads; one blank page
                # among typed ones shouldn't cost the rest
                if not has_text(found):
                    raise
        return found
    if suffix in TEXT_SUFFIXES:
        return [path.read_text(errors="replace")]
    if suffix in OFFICE_SUFFIXES:
        try:
            with zipfile.ZipFile(path) as z:
                return [_docx(z)] if suffix == ".docx" else _xlsx(z)
        except (zipfile.BadZipFile, KeyError, ElementTree.ParseError):
            # a password-protected Office file isn't a zip at all, but an encrypted container
            raise UnsupportedDocument(f"{suffix}: not a readable file (damaged, or password-protected)") from None
    raise UnsupportedDocument(f"{path.suffix or 'no extension'}: not readable yet")


def _docx(z: zipfile.ZipFile) -> str:
    """A Word document's text, one line per paragraph and per table row (its cells apart), as one page."""
    body = ElementTree.fromstring(z.read("word/document.xml")).find(f"{WORD}body")
    return "\n".join(_blocks(body)) if body is not None else ""


def _blocks(parent: ElementTree.Element) -> Iterator[str]:
    for child in parent:
        if child.tag == f"{WORD}p":
            yield _paragraph(child)
        elif child.tag == f"{WORD}tbl":
            for row in child.iter(f"{WORD}tr"):
                yield CELL.join(" ".join(map(_paragraph, cell.iter(f"{WORD}p"))) for cell in row.findall(f"{WORD}tc"))
        elif child.tag == f"{WORD}sdt" and (content := child.find(f"{WORD}sdtContent")) is not None:
            yield from _blocks(content)  # a form's fill-in field: the answer is inside


def _paragraph(p: ElementTree.Element) -> str:
    return "".join((e.text or "") if e.tag == f"{WORD}t" else "\t" for e in p.iter()
                   if e.tag in (f"{WORD}t", f"{WORD}tab"))


def _xlsx(z: zipfile.ZipFile) -> list[str]:
    """A workbook's sheets, one page each: its name, then one line per row with the cells apart, as stored."""
    names = set(z.namelist())
    shared = [] if "xl/sharedStrings.xml" not in names else [
        "".join(t.text or "" for t in si.iter(f"{SHEET}t"))
        for si in ElementTree.fromstring(z.read("xl/sharedStrings.xml")).findall(f"{SHEET}si")]
    targets = {r.get("Id"): r.get("Target", "") for r in
               ElementTree.fromstring(z.read("xl/_rels/workbook.xml.rels")).findall(f"{RELS}Relationship")}
    found = []
    for sheet in ElementTree.fromstring(z.read("xl/workbook.xml")).iter(f"{SHEET}sheet"):
        target = targets.get(sheet.get(REL_ID), "")
        rows = []
        for row in ElementTree.fromstring(z.read(target.lstrip("/") if target.startswith("/") else f"xl/{target}")
                                          ).iter(f"{SHEET}row"):
            cells: dict[int, str] = {}
            for c in row.findall(f"{SHEET}c"):
                kind, v = c.get("t"), c.find(f"{SHEET}v")
                value = ("".join(t.text or "" for t in c.iter(f"{SHEET}t")) if kind == "inlineStr"
                         else "" if v is None or v.text is None else shared[int(v.text)] if kind == "s" else v.text)
                cells[_column(c.get("r", ""), len(cells))] = value
            if any(cells.values()):
                rows.append(CELL.join(cells.get(n, "") for n in range(max(cells) + 1)).rstrip(" |"))
        found.append("\n".join([f"[{sheet.get('name', '')}]", *rows]))
    return found


def _column(ref: str, default: int) -> int:
    """'C7' as 2: a cell's column from its reference, or the next column when it has none."""
    letters = "".join(ch for ch in ref if ch.isalpha())
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - ord("A") + 1
    return n - 1 if letters else default


def _pdf_pages(path: Path, password: str | None) -> list[str]:
    import pdfplumber
    from pdfminer.pdfdocument import PDFPasswordIncorrect
    from pdfplumber.utils.exceptions import PdfminerException

    try:
        with pdfplumber.open(path, password=password or "") as doc:
            return [page.extract_text(layout=True, x_density=_x_density(page)) or "" for page in doc.pages]
    except PdfminerException as err:
        # pdfplumber wraps pdfminer's error as the first argument.
        if not (err.args and isinstance(err.args[0], PDFPasswordIncorrect)):
            raise UnsupportedDocument("not a readable PDF (a web page saved as .pdf, or a damaged file)") from None
        raise Locked("password-protected" if password is None else "the stored password doesn't open it") from None


def _x_density(page) -> float:
    """Points per character column for layout text: pdfplumber's 7.25, or the page's median glyph width if wider.

    OCR text layers use glyphs wider than 7.25 points, and on the default grid every letter gets a column of its
    own ("F o r m 8 5 8 2"). Printed forms are narrower, and keep the default.
    """
    from statistics import median

    widths = [c["width"] for c in page.chars if c["text"].strip()]
    return max(7.25, median(widths)) if widths else 7.25


def needs_ocr(found: list[str]) -> bool:
    return any(len(page.strip()) < OCR_MIN_CHARS for page in found)


def has_text(found: list[str]) -> bool:
    return any(len(page.strip()) >= OCR_MIN_CHARS for page in found)


def ocr(path: Path, cache: Path) -> Path:
    """A searchable copy of a scanned PDF, made once and kept in `cache` under the original's sha256."""
    out = cache / f"{hashlib.sha256(path.read_bytes()).hexdigest()}.pdf"
    if out.exists():
        return out
    exe = shutil.which("ocrmypdf")
    if exe is None:
        raise UnsupportedDocument("a scan with no text layer; install ocrmypdf to read it (brew install ocrmypdf)")
    cache.mkdir(parents=True, exist_ok=True)
    part = out.with_suffix(".part")
    # --skip-text leaves pages that have text alone; --output-type pdf skips PDF/A, which needs Ghostscript.
    run = subprocess.run([exe, "--skip-text", "--output-type", "pdf", "--optimize", "0", "--quiet",
                          str(path), str(part)], capture_output=True)
    if run.returncode != 0:
        part.unlink(missing_ok=True)
        raise UnsupportedDocument(f"OCR failed (ocrmypdf exit {run.returncode})")  # its stderr names the file
    part.replace(out)
    return out


def words(path: Path, page: int, password: str | None = None) -> list[dict]:
    """One PDF page's words with where they sit (points from the top left): what a parser of a printed form, whose
    values aren't in reading order next to their labels, places them by."""
    import pdfplumber

    with pdfplumber.open(path, password=password or "") as doc:
        found = doc.pages[page - 1].extract_words(keep_blank_chars=False, use_text_flow=False)
    return [{"text": w["text"], "x0": round(w["x0"], 1), "x1": round(w["x1"], 1), "top": round(w["top"], 1)}
            for w in found]


def headings(page: str, lines: int = 2) -> list[str]:
    """A page's first non-blank lines, which on a tax form name the form, with column gaps closed up."""
    return [" ".join(ln.split()) for ln in page.splitlines() if ln.strip()][:lines]


def documents(paths: list[Path]) -> list[Path]:
    """The supported files among `paths`, folders searched recursively, in a stable order."""
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            found.extend(p for p in sorted(path.rglob("*")) if p.is_file() and p.suffix.lower() in SUPPORTED)
        elif path.is_file():
            found.append(path)
    return found
