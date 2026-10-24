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
    monkeypatch.setattr(gate.sys, "platform", "darwin")
    workspace._keychain_password.cache_clear()
    yield no_real_gate
    workspace._keychain_password.cache_clear()  # nothing faked outlives this test


def test_without_the_helper_nothing_goes_through_it(no_real_gate: Path):
    assert not gate.ready()


def test_tax_document_passwords_come_through_the_helper(fake_gate: Path, monkeypatch: pytest.MonkeyPatch):
    real_run = subprocess.run

    def no_security(cmd, **kw):
        assert cmd[0] != "security", "the classic Keychain prompt was used"
        return real_run(cmd, **kw)
    monkeypatch.setattr(subprocess, "run", no_security)
    monkeypatch.setattr(workspace.sys, "platform", "darwin")
    assert workspace.pdf_passwords(Path("2024 Return.pdf")) == ["not-a-real-password"]  # the file's own entry: none
    assert workspace._keychain_password("taxtrace", "denied") is None


def test_the_chat_key_comes_through_the_helper(fake_gate: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(chat.sys, "platform", "darwin")
    assert chat.api_key("anthropic") == "sk-not-a-real-key"
    monkeypatch.delenv("ANTHROPIC_API_KEY")
    with pytest.raises(chat.Unavailable, match="wasn't approved"):
        chat.api_key("no-such-item")


def test_entries_move_over_without_the_secret_retyped(fake_gate: Path):
    assert gate.adopt("taxtrace", "default") is True
    assert gate.adopt("taxtrace", "no-such-entry") is False
    with pytest.raises(gate.GateError, match="taxtrace-backup"):  # says where the secret is kept
        gate.adopt("taxtrace", "stuck")


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


def test_new_entries_are_stored_for_the_helper_once_it_is_built(fake_gate: Path):
    assert f"-T '{fake_gate}' -w" in workspace.keychain_hint()


@pytest.mark.skipif(sys.platform != "darwin" or not shutil.which("swiftc"), reason="needs macOS and swiftc")
def test_the_helper_builds_signs_and_refuses_bad_usage(no_real_gate: Path):
    assert gate.build() is True
    assert gate.current() and gate.build() is False  # built once, kept: entries trust this exact binary
    sign = subprocess.run(["codesign", "-dv", str(no_real_gate)], capture_output=True, text=True)
    assert f"Identifier={gate.IDENTIFIER}" in sign.stderr
    assert subprocess.run([str(no_real_gate)], capture_output=True).returncode == 3
    # a missing entry is reported without asking anyone to approve anything
    assert gate.read("taxtrace-test-no-such-service", "nobody", "test") is None
