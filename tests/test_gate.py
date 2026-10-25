"""Keychain reads through the Apple Watch / Touch ID approval helper, with a stand-in helper (no prompts)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from taxtrace import chat, cli, gate, workspace

# Stands in for the Swift helper: entry `taxtrace/default` and the chat's key exist; "denied" isn't approved.
FAKE = """#!/bin/sh
if [ "$1" = --adopt ]; then
  case "$2/$3" in
    taxtrace/default) exit 0 ;;
    taxtrace/stuck) echo "couldn't save the new entry; the secret is in taxtrace.taxtrace-backup" >&2; exit 4 ;;
    taxtrace/refused) echo "the old entry's read wasn't allowed (-128); nothing changed" >&2; exit 1 ;;
    owned/) printf 'me'; echo "only the old entry's owner may remove it; the secret is in owned.taxtrace-backup" >&2
      exit 5 ;;
    *) exit 2 ;;
  esac
fi
if [ "$1" = --restore ]; then
  case "$2/$3" in
    owned/me) exit 0 ;;
    *) exit 2 ;;
  esac
fi
case "$1/$2" in
  taxtrace/default) printf 'not-a-real-password' ;;
  anthropic/) printf 'sk-not-a-real-key' ;;
  taxtrace/denied) exit 1 ;;
  *) exit 2 ;;
esac
"""


@pytest.fixture
def fake_gate(no_real_gate: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    no_real_gate.parent.mkdir(parents=True)
    no_real_gate.write_text(FAKE)
    no_real_gate.chmod(0o755)
    no_real_gate.with_suffix(".adopted").write_text("taxtrace\tdefault\nanthropic\t\ntaxtrace\tdenied\n")
    monkeypatch.setattr(gate.sys, "platform", "darwin")
    workspace._keychain_password.cache_clear()
    yield no_real_gate
    workspace._keychain_password.cache_clear()  # nothing faked outlives this test


def test_without_the_helper_nothing_goes_through_it(no_real_gate: Path):
    assert not gate.ready()


def test_tax_document_passwords_come_through_the_helper(fake_gate: Path, monkeypatch: pytest.MonkeyPatch):
    real_run = subprocess.run
    classic = []

    def spy(cmd, **kw):
        if cmd[0] == "security":  # the classic prompt, for an entry setup didn't move over
            classic.append(cmd[cmd.index("-a") + 1])
            return subprocess.CompletedProcess(cmd, 44, "", "")  # 44: no such entry
        return real_run(cmd, **kw)
    monkeypatch.setattr(subprocess, "run", spy)
    monkeypatch.setattr(workspace.sys, "platform", "darwin")
    # the file's own entry: none
    assert list(workspace.pdf_passwords(Path("2024 Return.pdf"))) == ["not-a-real-password"]
    assert classic == ["2024 Return.pdf"]  # never the default entry, which goes through the helper only
    assert workspace._keychain_password("taxtrace", "denied") is None


def test_an_entry_setup_did_not_move_is_read_the_classic_way(no_real_gate: Path, monkeypatch: pytest.MonkeyPatch):
    """Through the helper it would ask twice: the approval, then the classic prompt, since it isn't trusted."""
    no_real_gate.parent.mkdir(parents=True)
    no_real_gate.write_text("#!/bin/sh\nexit 9\n")
    no_real_gate.chmod(0o755)
    monkeypatch.setattr(gate.sys, "platform", "darwin")
    assert gate.ready() and not gate.adopted("taxtrace", "default")


def test_the_chat_key_comes_through_the_helper(fake_gate: Path, monkeypatch: pytest.MonkeyPatch):
    real_run = subprocess.run

    def no_such_item(cmd, **kw):  # `security` is macOS only: CI runs on Linux
        if cmd[0] == "security":
            return subprocess.CompletedProcess(cmd, 44, "", "")
        return real_run(cmd, **kw)
    monkeypatch.setattr(subprocess, "run", no_such_item)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(chat.sys, "platform", "darwin")
    assert chat.api_key("anthropic") == "sk-not-a-real-key"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(chat.Unavailable, match="wasn't approved"):
        chat.api_key("no-such-item")  # not moved to the helper: asked the classic way, and there's none


def test_entries_move_over_without_the_secret_retyped(fake_gate: Path):
    fake_gate.with_suffix(".adopted").unlink()
    assert gate.adopt("taxtrace", "default") is True
    assert gate.adopted("taxtrace", "default")  # from now on its reads go through the helper
    assert gate.adopt("taxtrace", "default") is True
    assert fake_gate.with_suffix(".adopted").read_text() == "taxtrace\tdefault\n"  # listed once
    assert gate.adopt("taxtrace", "no-such-entry") is False
    with pytest.raises(gate.GateError, match="taxtrace-backup"):  # says where the secret is kept
        gate.adopt("taxtrace", "stuck")
    with pytest.raises(gate.GateError, match="wasn't allowed"):  # a denied prompt isn't "no such entry"
        gate.adopt("taxtrace", "refused")
    assert not gate.adopted("taxtrace", "refused")


def test_an_entry_only_its_owner_may_remove_is_removed_by_security_then_restored(
        fake_gate: Path, monkeypatch: pytest.MonkeyPatch):
    real_run = subprocess.run
    removed = []

    def spy(cmd, **kw):
        if cmd[0] == "security":
            removed.append(cmd[1:])
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return real_run(cmd, **kw)
    monkeypatch.setattr(subprocess, "run", spy)
    assert gate.adopt("owned", "") is True
    assert removed == [["delete-generic-password", "-s", "owned", "-a", "me"]]  # the account the helper found
    assert gate.adopted("owned", "")


def test_setup_moves_every_entry_over(monkeypatch: pytest.MonkeyPatch, capsys):
    moved = []
    monkeypatch.setattr(gate, "build", lambda: True)
    monkeypatch.setattr(gate, "adopt", lambda service, account: moved.append((service, account)) or bool(account))
    monkeypatch.setattr(chat, "keychain_has", lambda item: item == "anthropic")
    assert cli.main(["keychain", "setup", "--account", "2024 Return.pdf"]) == 0
    assert moved == [("taxtrace", "default"), ("taxtrace", "2024 Return.pdf"), ("anthropic", "")]
    out = capsys.readouterr().out
    assert "taxtrace/default: now asks for Apple Watch or Touch ID" in out
    assert "anthropic: no such entry, skipped" in out


def test_status_says_how_each_entry_is_read_without_reading_it(fake_gate: Path, monkeypatch: pytest.MonkeyPatch,
                                                               capsys):
    present = ("taxtrace", "anthropic", "anthropic.taxtrace-backup")
    monkeypatch.setattr(chat, "keychain_has", lambda item: item in present)
    assert cli.main(["keychain", "status", "--account", "2024 Return.pdf"]) == 0
    out = capsys.readouterr().out
    assert "taxtrace/default: Apple Watch or Touch ID\n" in out
    assert "taxtrace/2024 Return.pdf: the classic prompt (password, then Allow): run setup to move it" in out
    assert "anthropic: Apple Watch or Touch ID; a backup copy is left over, setup clears it" in out


def test_new_entries_are_stored_for_the_helper_once_it_is_built(fake_gate: Path):
    assert f"-T '{fake_gate}' -w" in workspace.keychain_hint()


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("swiftc"), reason="needs macOS and swiftc")
def test_the_helper_builds_signs_and_refuses_bad_usage(no_real_gate: Path):
    no_real_gate.parent.mkdir(parents=True)
    no_real_gate.with_suffix(".adopted").write_text("taxtrace\tdefault\n")
    assert gate.build() is True
    assert not gate.adopted("taxtrace", "default")  # trusted the old binary: setup moves it over again
    assert gate.current() and gate.build() is False  # built once, kept: entries trust this exact binary
    sign = subprocess.run(["codesign", "-dv", str(no_real_gate)], capture_output=True, text=True)
    assert f"Identifier={gate.IDENTIFIER}" in sign.stderr
    assert subprocess.run([str(no_real_gate)], capture_output=True).returncode == 3
    # a missing entry is reported without asking anyone to approve anything
    assert gate.read("taxtrace-test-no-such-service", "nobody", "test") is None
