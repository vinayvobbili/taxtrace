"""Where a person's tax documents and everything taxtrace derives from them live.

Outside any git repository, always: TAXTRACE_HOME, or ~/TaxData. Put it in a synced folder (Google Drive
for desktop, iCloud Drive) to have it backed up.
"""

from __future__ import annotations

import os
from pathlib import Path

TERMS_FILE = "redact-terms.txt"


def home() -> Path:
    return Path(os.environ.get("TAXTRACE_HOME") or Path.home() / "TaxData").expanduser()


class InsideGitRepo(RuntimeError):
    pass


def outside_git(path: Path) -> Path:
    """`path`, after making sure no folder above it is a git work tree: tax data is never committed."""
    path = path.expanduser().resolve()
    for folder in (path, *path.parents):
        if (folder / ".git").exists():
            raise InsideGitRepo(f"{path} is inside the git repository at {folder}; tax data stays out of git")
    return path


def redact_terms(path: Path | None = None) -> list[str]:
    """Extra words to mask, one per line: names that are also ordinary words, and the like."""
    path = path or home() / TERMS_FILE
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
