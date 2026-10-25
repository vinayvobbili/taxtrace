"""Bring a folder or zip of documents into the workspace, sorted by tax year.

Made for what a tax preparer's portal hands back (one folder per year, often zipped), but any folder works, and so
does a single file, such as a K-1 just downloaded from a partnership's portal:

- a filed return goes to `prior-returns/`, whatever year's folder it sat in;
- anything else goes to `<year>/`, the year read from its folder's name, else from its own;
- identity documents (driver's licenses, Social Security cards, passports) are skipped: they're no tax
  input, and a copy not made is a copy that can't leak;
- a file whose exact bytes are already in the workspace is skipped, so importing twice changes nothing.

Nothing is opened beyond its first bytes (to give a nameless PDF its `.pdf`), and every file placed is
recorded in `imports.jsonl` with its source and sha256.
"""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from . import workspace

PRIOR_RETURNS = "prior-returns"
UNSORTED = "unsorted"
MANIFEST = workspace.MANIFEST
# A preparer's copy of a filed return is usually named for it, or marked signed (the return, or its 8879).
RETURN = re.compile(r"tax[ _-]*returns?|return[ _-]*documents|(?<![A-Za-z])signed", re.I)
IDENTITY = re.compile(r"driv(?:er|ing)[ _-]*licen[cs]e|(?<![A-Za-z])(?:DL|SSN)(?![A-Za-z])|passport|"
                      r"social[ _-]*security[ _-]*card", re.I)
YEAR = re.compile(r"(?<!\d)(20\d\d)(?!\d)")
SKIP = {".DS_Store", "Thumbs.db"}


@dataclass
class Placement:
    source: str
    dest: str | None  # relative to the workspace; None when skipped
    reason: str


def _sources(src: Path) -> Iterator[tuple[str, Callable[[], bytes]]]:
    """(name, reader) for every file in a folder or zip, or for one file (a K-1 just downloaded).

    A folder's own name leads its files' names, since it often says the year ("2025 TAX"). A zip's doesn't: an
    export is named for the day it was made.
    """
    if src.is_dir():
        for path in sorted(p for p in src.rglob("*") if p.is_file()):
            yield f"{src.name}/{path.relative_to(src).as_posix()}", path.read_bytes
    elif zipfile.is_zipfile(src):
        with zipfile.ZipFile(src) as zf:
            for info in sorted(zf.infolist(), key=lambda i: i.filename):
                if not info.is_dir():
                    yield info.filename, (lambda info=info: zf.read(info))
    elif src.is_file():
        yield src.name, src.read_bytes
    else:
        raise ValueError(f"{src.name}: no such file or folder")


def tax_year(name: str) -> str | None:
    """The year of the first folder that names one, else of the file name itself."""
    *folders, filename = PurePosixPath(name).parts
    for part in [*folders, filename]:
        if m := YEAR.search(part):
            return m.group(1)
    return None


def destination(name: str, year: str | None = None) -> tuple[str | None, str]:
    """Where a file goes; `year`, when given, is the tax year of everything that isn't a filed return."""
    filename = PurePosixPath(name).name
    if filename in SKIP:
        return None, "system file"
    if IDENTITY.search(filename):
        return None, "identity document"
    if RETURN.search(filename):
        return PRIOR_RETURNS, "filed return"
    if year:
        return year, "tax year given"
    year = tax_year(name)
    return (year, "tax year") if year else (UNSORTED, "no year in its name")


def _with_suffix(filename: str, data: bytes) -> str:
    if not PurePosixPath(filename).suffix and data.startswith(b"%PDF"):
        return filename + ".pdf"
    return filename


def _known_hashes(home: Path) -> set[str]:
    manifest = home / MANIFEST
    if not manifest.exists():
        return set()
    return {json.loads(line)["sha256"] for line in manifest.read_text().splitlines() if line.strip()}


def import_documents(src: Path, home: Path, dry_run: bool = False, year: str | None = None) -> list[Placement]:
    known = _known_hashes(home)
    placed: list[Placement] = []
    records: list[dict] = []
    planned: set[Path] = set()  # this run's targets, so a dry run names clashes the way a real one would
    for name, read in _sources(src):
        folder, reason = destination(name, year)
        if folder is None:
            placed.append(Placement(name, None, reason))
            continue
        data = read()
        if PurePosixPath(name).suffix.lower() == ".pdf" and not data.startswith(b"%PDF"):
            placed.append(Placement(name, None, "not a PDF: a web page saved as .pdf?"))
            continue
        digest = hashlib.sha256(data).hexdigest()
        if digest in known:
            placed.append(Placement(name, None, "already imported"))
            continue
        known.add(digest)
        target = home / folder / _with_suffix(PurePosixPath(name).name, data)

        def taken(t: Path, digest: str = digest) -> bool:
            return t in planned or (t.exists() and hashlib.sha256(t.read_bytes()).hexdigest() != digest)

        n = 2
        while taken(target):
            target = target.with_name(f"{target.stem.removesuffix(f' ({n - 1})')} ({n}){target.suffix}")
            n += 1
        rel = target.relative_to(home).as_posix()
        if target.exists():
            placed.append(Placement(name, None, "already in the workspace"))
            continue
        planned.add(target)
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        placed.append(Placement(name, rel, reason))
        records.append({"source": name, "from": src.name, "sha256": digest, "dest": rel,
                        "at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    if records and not dry_run:
        with (home / MANIFEST).open("a") as f:
            f.writelines(json.dumps(r) + "\n" for r in records)
    return placed
