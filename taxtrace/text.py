"""A document's text, page by page, with the layout kept so columns still line up.

Every later step quotes from these pages, so this is the one place text comes out of a file: a value's
quote is checked against exactly what this returns.

A scanned PDF has pictures of pages and no text. Given an `ocr_cache` folder, such a file goes through
ocrmypdf (Tesseract, on this machine) once, and the searchable copy is kept there under the original's
sha256: OCR isn't byte-for-byte repeatable, and a quote must keep matching the text it was checked against.
"""

from __future__ import annotations

import hashlib
import shutil
import subprocess
from pathlib import Path

TEXT_SUFFIXES = {".txt", ".csv", ".tsv"}
PDF_SUFFIXES = {".pdf"}
SUPPORTED = TEXT_SUFFIXES | PDF_SUFFIXES
# A page with less text than this is a picture of a page (or blank, which OCR leaves blank).
OCR_MIN_CHARS = 20


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
            found = _pdf_pages(ocr(path, ocr_cache), None)
        return found
    if suffix in TEXT_SUFFIXES:
        return [path.read_text(errors="replace")]
    raise UnsupportedDocument(f"{path.suffix or 'no extension'}: not readable yet")


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
