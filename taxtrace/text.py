"""A document's text, page by page, with the layout kept so columns still line up.

Every later step quotes from these pages, so this is the one place text comes out of a file: a value's
quote is checked against exactly what this returns.
"""

from __future__ import annotations

from pathlib import Path

TEXT_SUFFIXES = {".txt", ".csv", ".tsv"}
PDF_SUFFIXES = {".pdf"}
SUPPORTED = TEXT_SUFFIXES | PDF_SUFFIXES


class UnsupportedDocument(ValueError):
    pass


def pages(path: Path) -> list[str]:
    suffix = path.suffix.lower()
    if suffix in PDF_SUFFIXES:
        import pdfplumber

        with pdfplumber.open(path) as doc:
            return [page.extract_text(layout=True) or "" for page in doc.pages]
    if suffix in TEXT_SUFFIXES:
        return [path.read_text(errors="replace")]
    raise UnsupportedDocument(f"{path.suffix or 'no extension'}: not readable yet")


def documents(paths: list[Path]) -> list[Path]:
    """The supported files among `paths`, folders searched recursively, in a stable order."""
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            found.extend(p for p in sorted(path.rglob("*")) if p.is_file() and p.suffix.lower() in SUPPORTED)
        elif path.is_file():
            found.append(path)
    return found
