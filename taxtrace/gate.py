"""Keychain reads approved with Apple Watch or Touch ID instead of a typed password (macOS).

The classic Keychain prompt, the one an entry made with `-T ""` shows on every read, only takes the login
password. A small helper, built here from `macos/keychain_gate.swift`, asks through macOS's LocalAuthentication
instead, which takes Apple Watch, Touch ID or the password. Entries stored with `-T <helper>` trust only that
helper, and it reads one only after the person approves, so every read is still theirs to allow.

The helper is built once and kept: an entry trusts the exact binary, so rebuilding it means storing the entries
again. `setup` rebuilds only when the source changed.

A read goes through the helper only for an entry `setup` moved over to this build of it (`adopted`). Any other
entry doesn't trust the helper, and reading it through the helper would ask twice: the approval, then the
classic prompt. Those are read the classic way, with its one prompt.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

SOURCE = Path(__file__).with_name("macos") / "keychain_gate.swift"
IDENTIFIER = "io.github.taxtrace.keychain-gate"


class GateError(RuntimeError):
    pass


def helper_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "taxtrace" / "keychain-gate"


def _stamp() -> Path:
    return helper_path().with_suffix(".sha256")


def _adopted_list() -> Path:
    return helper_path().with_suffix(".adopted")


def ready() -> bool:
    return sys.platform == "darwin" and os.access(helper_path(), os.X_OK)


def adopted(service: str, account: str) -> bool:
    """Whether `setup` moved this entry over to the helper as built now: only then do its reads go through it."""
    listed = _adopted_list()
    return ready() and listed.exists() and f"{service}\t{account}" in listed.read_text().splitlines()


def adopted_accounts(service: str) -> list[str]:
    """The accounts of `service` that `setup` moved over, in the order it moved them."""
    listed = _adopted_list()
    if not listed.exists():
        return []
    return [line.split("\t", 1)[1] for line in listed.read_text().splitlines() if line.startswith(f"{service}\t")]


def current() -> bool:
    """Whether the built helper is from today's source."""
    stamp = _stamp()
    return ready() and stamp.exists() and stamp.read_text().strip() == hashlib.sha256(SOURCE.read_bytes()).hexdigest()


def build() -> bool:
    """Build and sign the helper if it's missing or its source changed. True when it was (re)built."""
    if sys.platform != "darwin":
        raise GateError("Apple Watch and Touch ID approval is macOS only")
    if current():
        return False
    if not (swiftc := shutil.which("swiftc")):
        raise GateError("swiftc not found: install the Xcode command line tools (xcode-select --install)")
    out = helper_path()
    out.parent.mkdir(parents=True, exist_ok=True)
    part = out.with_suffix(".part")
    for cmd in ([swiftc, "-O", "-swift-version", "5", "-o", str(part), str(SOURCE)],
                ["codesign", "--force", "--sign", "-", "--identifier", IDENTIFIER, str(part)]):
        run = subprocess.run(cmd, capture_output=True, text=True)
        if run.returncode:
            part.unlink(missing_ok=True)
            raise GateError(f"{Path(cmd[0]).name} failed: {run.stderr.strip()[-400:]}")
    part.replace(out)
    _stamp().write_text(hashlib.sha256(SOURCE.read_bytes()).hexdigest() + "\n")
    _adopted_list().unlink(missing_ok=True)  # entries trusted the old binary: `setup` moves them over again
    return True


refused: set[tuple[str, str]] = set()  # entries whose read this run the person didn't approve


def read(service: str, account: str, reason: str) -> str | None:
    """The entry's password once the person approves; None if there's no such entry or they didn't approve (noted
    in `refused`, so a locked file can say why it stayed locked)."""
    run = subprocess.run([str(helper_path()), service, account, reason], capture_output=True, text=True)
    if run.returncode == 3:
        raise GateError(run.stderr.strip())
    if run.returncode == 1:
        refused.add((service, account))
    return run.stdout if run.returncode == 0 else None


def adopt(service: str, account: str) -> bool:
    """Store an existing entry again trusting only the helper, without the secret being retyped or passing through
    here. Its classic prompt shows one last time. False if there's no such entry."""
    run = subprocess.run([str(helper_path()), "--adopt", service, account], capture_output=True, text=True)
    if run.returncode == 5:  # only the entry's owner may remove it: `security`, which made it, does
        owned = run.stdout or account
        removed = subprocess.run(["security", "delete-generic-password", "-s", service, "-a", owned],
                                 capture_output=True, text=True)
        if removed.returncode:
            raise GateError(f"{run.stderr.strip()}; security couldn't remove it either ({removed.returncode})")
        run = subprocess.run([str(helper_path()), "--restore", service, owned], capture_output=True, text=True)
    if run.returncode not in (0, 2):
        raise GateError(run.stderr.strip())
    if run.returncode == 0 and not adopted(service, account):
        with _adopted_list().open("a") as listed:
            listed.write(f"{service}\t{account}\n")
    return run.returncode == 0


def store_hint(service: str, account: str) -> str:
    """The command that stores an entry trusting only the helper: `-w` last asks for the password unechoed."""
    return f"security add-generic-password -s {service} -a '{account}' -T '{helper_path()}' -w"
