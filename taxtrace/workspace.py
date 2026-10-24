"""Where a person's tax documents and everything taxtrace derives from them live.

Outside any git repository, always: TAXTRACE_HOME, or ~/TaxData. Put it in a synced folder (Google Drive
for desktop, iCloud Drive) to have it backed up.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

TERMS_FILE = "redact-terms.txt"
KEYCHAIN_SERVICE = "taxtrace"


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


def keychain_hint() -> str:
    return f"security add-generic-password -s {KEYCHAIN_SERVICE} -a '<file name>' -w"


def pdf_password(path: Path) -> str | None:
    """A locked PDF's password from the macOS Keychain, stored under the file's name.

    Kept there, never in a file or on a command line, so it can't land in shell history, a repo or a chat. Store
    one with `keychain_hint()`: `-w` last, with no value, makes `security` ask for it without echoing.
    """
    if sys.platform != "darwin":
        return None
    found = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", path.name, "-w"],
                           capture_output=True, text=True)
    return found.stdout.rstrip("\n") if found.returncode == 0 else None


def redact_terms(path: Path | None = None) -> list[str]:
    """Extra words to mask, one per line: names that are also ordinary words, and the like."""
    path = path or home() / TERMS_FILE
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
