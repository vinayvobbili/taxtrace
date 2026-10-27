"""Where a person's tax documents and everything taxtrace derives from them live.

Outside any git repository, always: TAXTRACE_HOME, or ~/TaxData. Put it in a synced folder (Google Drive
for desktop, iCloud Drive) to have it backed up.
"""

from __future__ import annotations

import functools
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

TERMS_FILE = "redact-terms.txt"
OCR_CACHE = "ocr-cache"
REDACTED = "redacted"
MANIFEST = "imports.jsonl"
CARRYFORWARDS = "carryforwards"
K1 = "k1"
PASSIVE = "passive"
FORMS = "forms"  # information returns read off their forms: 1098s, India's ITR
SCHEDULE_E = "schedule-e"
FOREIGN = "foreign"
FX = "fx"  # public exchange rates, fetched once
QBI = "qbi"  # Form 8995, the qualified business income deduction
ESTIMATES = "estimates"  # the year's estimated tax against the safe harbor, quarter by quarter
# taxtrace's own files and folders in the workspace, never read back as documents: its output and its settings
DERIVED = {OCR_CACHE, REDACTED, MANIFEST, TERMS_FILE, CARRYFORWARDS, K1, PASSIVE, FORMS, SCHEDULE_E, FOREIGN, FX, QBI}
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
    from . import gate

    if gate.ready():  # trusted by the approval helper only: each read asks for Apple Watch or Touch ID
        return f"{gate.store_hint(KEYCHAIN_SERVICE, KEYCHAIN_DEFAULT)} (or the file's name, or its issuer's)"
    # -T "" trusts no app, so macOS asks the person (Allow / Deny) every time anything reads the entry,
    # this tool included: nothing running as them can take the password without their click.
    return (f"security add-generic-password -s {KEYCHAIN_SERVICE} -a {KEYCHAIN_DEFAULT} -T \"\" -w "
            f"(or -a '<file name>' for one file)")


def keychain_entries(path: Path) -> Iterator[tuple[str, str]]:
    """(account, password) for a locked PDF from the macOS Keychain: the file's own entry, then its issuer's (the
    name before the first "-": `kotak` for kotak-7016-2026-01.pdf, for a bank whose monthly statements share one
    password), then the default one.

    Lazily, since each read can be an approval: a file its own entry opens never asks for the default one.
    Kept there, never in a file or on a command line, so they can't land in shell history, a repo or a chat. Store
    one with `keychain_hint()`: `-w` last, with no value, makes `security` ask for it without echoing.
    """
    if sys.platform != "darwin":
        return
    issuer = path.stem.split("-", 1)[0].lower() if "-" in path.stem else ""
    for account in dict.fromkeys(a for a in (path.name, issuer, KEYCHAIN_DEFAULT) if a):
        if (password := _keychain_password(KEYCHAIN_SERVICE, account)) is not None:
            yield account, password


@functools.cache
def _keychain_password(service: str, account: str) -> str | None:
    """Read once per run: an entry made with `-T ""` asks the person (Allow / Deny) on every read, so a folder of
    returns that share the default password costs one prompt, not one per file. With the approval helper built
    (`taxtrace keychain setup`), that prompt takes Apple Watch or Touch ID instead of the typed password."""
    from . import gate

    if gate.adopted(service, account):  # other entries don't trust the helper: through it they'd ask twice
        found = gate.read(service, account, f"open your tax documents (Keychain entry '{account}')")
        return found.rstrip("\n") if found is not None else None
    r = subprocess.run(["security", "find-generic-password", "-s", service, "-a", account, "-w"],
                       capture_output=True, text=True)
    return r.stdout.rstrip("\n") if r.returncode == 0 else None


def sources() -> list[Path]:
    """The workspace's documents, without what taxtrace derived from them (masked text, OCR copies)."""
    root = home()
    if not root.is_dir():
        return []
    return sorted(p for p in root.iterdir() if p.name not in DERIVED and not p.name.startswith("."))


def pdf_passwords(path: Path) -> Iterator[str]:
    return (password for _, password in keychain_entries(path))


def shape(secret: str) -> str:
    """What a password looks like without what it is: `a` lowercase, `A` uppercase, `9` digit, `_` space, `*` other.

    Enough to spot a capital, a stray space or a digit too many against a rule like "four letters of the last
    name and five digits, lowercase" (`aaaa99999`), with nothing of the password itself.
    """
    def cls(c: str) -> str:
        if c.isdigit():
            return "9"
        if c.isalpha():
            return "a" if c.islower() else "A"
        return "_" if c.isspace() else "*"

    return f"{len(secret)} characters: {''.join(cls(c) for c in secret)}"


def ocr_cache() -> Path:
    """Searchable copies of scanned PDFs, by sha256: tax data, so in the workspace like the originals."""
    return outside_git(home() / OCR_CACHE)


def redact_terms(path: Path | None = None) -> list[str]:
    """Extra words to mask, one per line: names that are also ordinary words, and the like."""
    path = path or home() / TERMS_FILE
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text().splitlines() if ln.strip() and not ln.startswith("#")]
