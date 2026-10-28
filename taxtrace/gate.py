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

`release` undoes the move for a secret that guards little and that a tool reads unattended: an API key with a
spend limit, say. It goes back to trusting `security`, and reads without any prompt.
"""

from __future__ import annotations

import hashlib
import os
import re
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


CHECK = SOURCE.with_name("approval_check.swift")


def check(attempt: bool = False) -> str:
    """Which ways macOS offers to approve a read right now (Touch ID, Apple Watch, the password), each with why
    not; with `attempt`, the result of one Touch ID / Apple Watch prompt. Run from source by `swift`, so the
    helper the entries trust isn't rebuilt, and no Keychain entry is touched."""
    if sys.platform != "darwin":
        raise GateError("Apple Watch and Touch ID approval is macOS only")
    if not (swift := shutil.which("swift")):
        raise GateError("swift not found: install the Xcode command line tools (xcode-select --install)")
    run = subprocess.run([swift, str(CHECK), *(["--try"] if attempt else [])], capture_output=True, text=True)
    if run.returncode:
        raise GateError(f"the approval check failed: {run.stderr.strip()[-400:]}")
    return run.stdout


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
    if run.returncode == 0:
        _list(service, account)
    return run.returncode == 0


def _list(service: str, account: str) -> None:
    """Note that the entry trusts the helper, so its reads go through it: read any other way, it asks twice."""
    if not adopted(service, account):
        with _adopted_list().open("a") as listed:
            listed.write(f"{service}\t{account}\n")


def store(service: str, account: str) -> bool:
    """Store (or replace) an entry, then move it over to the helper (`adopt`), so its reads take Apple Watch or Touch
    ID alone. `security` asks the person for the password itself, unechoed, on the terminal this runs in: it never
    passes through here. An entry `security` makes is `security`'s even when it lists the helper as trusted, and
    macOS adds its own prompt to each of the helper's reads: only one the helper saved itself goes without it, so
    the move costs one classic prompt (password, then Allow), now instead of on every read."""
    if not ready():
        raise GateError("the approval helper isn't built: run taxtrace keychain setup first")
    run = subprocess.run(["security", "add-generic-password", "-U", "-s", service, "-a", account, "-T", "", "-w"])
    return run.returncode == 0 and adopt(service, account)


SECURITY = "/usr/bin/security"
# what `security -i` takes unquoted in its command stream; anything else is refused rather than escaped
PLAIN = re.compile(r"[A-Za-z0-9._@+=:/-]+")
ACCOUNT = re.compile(r'"acct"<blob>="([^"]*)"')


def release(service: str, account: str, reason: str) -> bool:
    """Store a moved entry back the classic way, trusting `security`, so it reads without any prompt: for a secret
    that guards little, such as an API key with a spend limit, that a tool running unattended needs (an approval
    nobody is there to give times out). One approval reads it, then `security` saves it again, the secret going in
    on stdin (its `-i` command stream), never in a command line. A backup copy is kept until the new entry is saved,
    so a failure can't lose it. False if the read wasn't approved."""
    if not adopted(service, account):
        raise GateError(f"{service} isn't read with Apple Watch or Touch ID: nothing to release")
    secret = read(service, account, reason)
    if secret is None:
        return False
    owner = account or _account(service)
    if not (PLAIN.fullmatch(secret) and PLAIN.fullmatch(service) and PLAIN.fullmatch(owner)):
        raise GateError("the entry has characters security's command stream would need quoted; nothing changed")
    backup = f"{service}.taxtrace-backup"
    _add(backup, owner, secret)
    removed = subprocess.run([SECURITY, "delete-generic-password", "-s", service, "-a", owner], capture_output=True,
                             text=True)
    if removed.returncode:
        subprocess.run([SECURITY, "delete-generic-password", "-s", backup, "-a", owner], capture_output=True)
        raise GateError(f"security couldn't remove the entry ({removed.returncode}); nothing changed")
    try:
        _add(service, owner, secret)
    except GateError as err:
        raise GateError(f"{err}; the secret is in {backup}") from None
    subprocess.run([SECURITY, "delete-generic-password", "-s", backup, "-a", owner], capture_output=True)
    _unlist(service, account)
    return True


def _account(service: str) -> str:
    """The account of the service's first entry, from its attributes: no prompt."""
    found = subprocess.run([SECURITY, "find-generic-password", "-s", service], capture_output=True, text=True)
    if found.returncode or not (match := ACCOUNT.search(found.stdout)):
        raise GateError(f"no {service} entry in the Keychain")
    return match.group(1)


def _add(service: str, account: str, secret: str) -> None:
    """Save (or replace) an entry trusting `security`, the secret on stdin; checked by its attributes after."""
    run = subprocess.run([SECURITY, "-i"], input=f"add-generic-password -U -s {service} -a {account} -T {SECURITY} "
                                                 f"-w {secret}\n", capture_output=True, text=True)
    saved = subprocess.run([SECURITY, "find-generic-password", "-s", service, "-a", account], capture_output=True)
    if run.returncode or saved.returncode:
        raise GateError(f"security couldn't save {service}")  # its output can hold the command, so it isn't shown


def _unlist(service: str, account: str) -> None:
    listed = _adopted_list()
    if listed.exists():
        kept = [line for line in listed.read_text().splitlines() if line != f"{service}\t{account}"]
        listed.write_text("".join(f"{line}\n" for line in kept))


def store_hint(service: str, account: str) -> str:
    """The command that stores an entry so it takes Apple Watch or Touch ID (`store`)."""
    return f"taxtrace keychain store '{account}'"
