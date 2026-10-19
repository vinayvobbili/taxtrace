"""Build taxtrace/data/vocab.txt, the words `taxtrace redact` lets through.

    .venv/bin/python scripts/build_vocab.py            # download (cached) and rebuild
    .venv/bin/python scripts/build_vocab.py --offline  # rebuild from the cache only

A word is kept only if it appears in lowercase somewhere in the IRS's own publications and
instructions. People's names, street names and towns are capitalized wherever they appear, so they
never make it in; the redactor masks every word that isn't in the list. Rerun this when the IRS
publishes a new year's forms, and commit the result.
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.request
from pathlib import Path

import pdfplumber

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "taxtrace" / "data" / "vocab.txt"
CACHE = Path.home() / ".cache" / "taxtrace" / "corpus"
IRS = "https://www.irs.gov/pub/irs-pdf/"
SOURCES = [
    "p17",  # Your Federal Income Tax: the broadest vocabulary
    "p527",  # Residential Rental Property
    "p946",  # How To Depreciate Property
    "p925",  # Passive Activity and At-Risk Rules
    "p514",  # Foreign Tax Credit for Individuals
    "p54",  # Tax Guide for U.S. Citizens and Resident Aliens Abroad
    "i1040gi", "i1040se", "i4562", "i8582", "i1116", "i8938", "i1099int", "i1098", "fw2",
]
LOWER_WORD = re.compile(r"(?<![A-Za-z])[a-z]+(?![A-Za-z])")


def fetch(name: str, offline: bool) -> Path | None:
    path = CACHE / f"{name}.pdf"
    if not path.exists() and not offline:
        CACHE.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(IRS + path.name, timeout=60) as resp:
            path.write_bytes(resp.read())
    return path if path.exists() else None


def words(pdf: Path) -> set[str]:
    found: set[str] = set()
    with pdfplumber.open(pdf) as doc:
        for page in doc.pages:
            found.update(m.group(0) for m in LOWER_WORD.finditer(page.extract_text() or ""))
    return found


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--offline", action="store_true", help="use only the cached PDFs")
    args = ap.parse_args(argv)
    vocab: set[str] = set()
    for name in SOURCES:
        pdf = fetch(name, args.offline)
        if pdf is None:
            print(f"missing {name}.pdf (run without --offline)", file=sys.stderr)
            return 1
        vocab |= words(pdf)
    vocab = {w for w in vocab if len(w) > 1}
    OUT.write_text("\n".join(sorted(vocab)) + "\n")
    print(f"{len(vocab)} words -> {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
