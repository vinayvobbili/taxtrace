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
KEYCHAIN_DEFAULT = "default"  # tried after the file's own entry: one password for every return a preparer sends


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
    return (f"security add-generic-password -s {KEYCHAIN_SERVICE} -a {KEYCHAIN_DEFAULT} -w "
            f"(or -a '<file name>' for one file)")


def pdf_passwords(path: Path) -> list[str]:
    """Passwords to try on a locked PDF, from the macOS Keychain: the file's own entry, then the default one.

    Kept there, never in a file or on a command line, so they can't land in shell history, a repo or a chat. Store
    one with `keychain_hint()`: `-w` last, with no value, makes `security` ask for it without echoing.
    """
    if sys.platform != "darwin":
        return []
    found = []
    for account in (path.name, KEYCHAIN_DEFAULT):
        r = subprocess.run(["security", "find-generic-password", "-s", KEYCHAIN_SERVICE, "-a", account, "-w"],
                           capture_output=True, text=True)
        if r.returncode == 0:
            found.append(r.stdout.rstrip("\n"))
    return found


def redact_terms(path: Path | None = None) -> list[str]:
    """Extra words to mask, one per line: names that are also ordinary words, and the like."""
    path = path or home() / TERMS_FILE
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
