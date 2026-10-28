"""Keychain reads through the Apple Watch / Touch ID approval helper, with a stand-in helper (no prompts)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from taxtrace import chat, cli, gate, text, workspace

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
  taxtrace/denied|taxtrace/denied.pdf) exit 1 ;;
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
    listed = fake_gate.with_suffix(".adopted")
    listed.write_text(listed.read_text() + "taxtrace\tQuillfeather K-1.pdf\n")  # moved by an earlier setup
    assert cli.main(["keychain", "status", "--account", "2024 Return.pdf"]) == 0
    out = capsys.readouterr().out
    assert "taxtrace/default: Apple Watch or Touch ID\n" in out
    assert "Return.pdf: the classic prompt (password, then Allow): run setup to move it" in out
    assert "K-1.pdf: Apple Watch or Touch ID\n" in out and "Quillfeather" not in out  # listed without being named
    assert "anthropic: Apple Watch or Touch ID; a backup copy is left over, setup clears it" in out


def test_another_tool_reads_a_moved_entry_through_the_helper(fake_gate: Path, monkeypatch: pytest.MonkeyPatch,
                                                             capsys):
    reasons = []
    real_read = gate.read
    monkeypatch.setattr(gate, "read", lambda s, a, reason: reasons.append(reason) or real_read(s, a, reason))
    assert cli.main(["keychain", "read", "anthropic", "--for", "jobwatch"]) == 0
    assert capsys.readouterr().out == "sk-not-a-real-key"  # as is, for the calling process
    assert reasons == ["read the Keychain item anthropic for jobwatch"]
    # an entry setup didn't move isn't read here: that would bring back the classic prompt
    assert cli.main(["keychain", "read", "jobwatch-imap", "--for", "jobwatch"]) == 1
    assert cli.main(["keychain", "read", "anthropic"]) == 2  # the prompt must say who asks
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True)
    assert cli.main(["keychain", "read", "anthropic", "--for", "jobwatch"]) == 2
    assert "sk-not-a-real-key" not in capsys.readouterr().out


def test_check_says_how_reads_can_be_approved_without_rebuilding_the_helper(monkeypatch: pytest.MonkeyPatch,
                                                                            capsys):
    ran = []
    monkeypatch.setattr(gate.sys, "platform", "darwin")
    monkeypatch.setattr(gate.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(gate, "build", lambda: pytest.fail("the helper the entries trust was rebuilt"))
    monkeypatch.setattr(gate.subprocess, "run", lambda cmd, **kw: ran.append(cmd) or subprocess.CompletedProcess(
        cmd, 0, "Apple Watch: available\n", ""))
    assert cli.main(["keychain", "check", "--try"]) == 0
    assert capsys.readouterr().out == "Apple Watch: available\n"
    assert ran == [["/usr/bin/swift", str(gate.CHECK), "--try"]]


def test_a_locked_file_whose_keychain_read_was_refused_says_so(fake_gate: Path, tmp_path: Path, capsys):
    from conftest import PRIOR_RETURN, make_pdf

    listed = fake_gate.with_suffix(".adopted")
    listed.write_text(listed.read_text() + "taxtrace\tdenied.pdf\n")
    locked = make_pdf(tmp_path / "denied.pdf", PRIOR_RETURN, password="anything")  # its own entry isn't approved
    gate.refused.clear()
    try:
        with pytest.raises(text.Locked, match="wasn't approved"):
            cli._unlocked(locked)
    finally:
        gate.refused.clear()


def test_new_entries_are_stored_for_the_helper_once_it_is_built(fake_gate: Path):
    assert workspace.keychain_hint().startswith("taxtrace keychain store 'default'")


def test_store_saves_an_entry_for_the_helper_and_notes_it(fake_gate: Path, monkeypatch, capsys):
    ran = []
    monkeypatch.setattr(gate.subprocess, "run", lambda cmd, **kw: ran.append((cmd, kw))
                        or subprocess.CompletedProcess(cmd, 0))
    assert not gate.adopted("taxtrace", "bankcert")
    assert cli.main(["keychain", "store", "bankcert"]) == 0
    (stored, kw), (moved, _) = ran
    # `security` asks for the password on the terminal (no -w value, nothing captured): it never passes through here
    assert stored == ["security", "add-generic-password", "-U", "-s", "taxtrace", "-a", "bankcert", "-T", "", "-w"]
    assert not kw
    # then the helper saves it as its own: one `security` made would add macOS's prompt to every read
    assert moved == [str(fake_gate), "--adopt", "taxtrace", "bankcert"]
    assert gate.adopted("taxtrace", "bankcert")  # so its reads go through the helper, one prompt each
    assert "taxtrace/bankcert: stored; its reads ask for Apple Watch or Touch ID" in capsys.readouterr().out
    assert cli.main(["keychain", "store"]) == 2


class FakeSecurity:
    """Stands in for /usr/bin/security over a dict of entries: the chat's key is the helper's, under account `me`."""

    def __init__(self, refuse_delete: bool = False):
        self.entries = {("anthropic", "me"): "helper's"}
        self.argv: list[list[str]] = []
        self.refuse_delete = refuse_delete

    def __call__(self, cmd, input=None, **kw):
        if Path(cmd[0]).name != "security":  # by its full path or bare: the real one would show a Keychain prompt
            return self.real(cmd, input=input, **kw)
        self.argv.append(cmd)
        if cmd[1] == "-i":  # add-generic-password -U -s S -a A -T T -w SECRET
            words = input.split()
            self.entries[(words[3], words[5])] = words[9]
            return subprocess.CompletedProcess(cmd, 0, "", "")
        service = cmd[cmd.index("-s") + 1]
        account = cmd[cmd.index("-a") + 1] if "-a" in cmd else None
        found = [k for k in self.entries if k[0] == service and account in (None, k[1])]
        if cmd[1] == "delete-generic-password":
            if not found or (self.refuse_delete and service == "anthropic"):
                return subprocess.CompletedProcess(cmd, 44, "", "")
            del self.entries[found[0]]
            return subprocess.CompletedProcess(cmd, 0, "", "")
        if "-w" in cmd:
            return subprocess.CompletedProcess(cmd, 0 if found else 44, self.entries[found[0]] if found else "", "")
        return subprocess.CompletedProcess(cmd, 0 if found else 44, f'    "acct"<blob>="{found[0][1]}"\n' if found
                                           else "", "")


def test_release_moves_the_chat_key_back_to_reading_without_a_prompt(fake_gate: Path, monkeypatch, capsys):
    security = FakeSecurity()
    security.real = subprocess.run
    monkeypatch.setattr(subprocess, "run", security)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cli.main(["keychain", "release", "anthropic"]) == 0
    assert "anthropic: released; it reads without a prompt" in capsys.readouterr().out
    # saved again by `security` under the same account, trusting it; the backup copy is gone
    assert security.entries == {("anthropic", "me"): "sk-not-a-real-key"}
    assert not any("sk-not-a-real-key" in " ".join(cmd) for cmd in security.argv)  # only ever on stdin
    assert not gate.adopted("anthropic", "") and gate.adopted("taxtrace", "default")  # documents stay gated
    monkeypatch.setattr(gate, "read", lambda *a: pytest.fail("the chat's key still went through the helper"))
    assert chat.api_key("anthropic") == "sk-not-a-real-key"  # the classic read, which no longer asks
    assert cli.main(["keychain", "release", "anthropic"]) == 1  # already released


def test_release_changes_nothing_when_the_entry_cant_be_removed(fake_gate: Path, monkeypatch):
    security = FakeSecurity(refuse_delete=True)
    security.real = subprocess.run
    monkeypatch.setattr(subprocess, "run", security)
    with pytest.raises(gate.GateError, match="nothing changed"):
        gate.release("anthropic", "", "test")
    assert security.entries == {("anthropic", "me"): "helper's"} and gate.adopted("anthropic", "")


def test_release_leaves_document_passwords_and_refused_reads_alone(fake_gate: Path, monkeypatch, capsys):
    monkeypatch.setattr(gate, "release", lambda *a: pytest.fail("a document password was released"))
    assert cli.main(["keychain", "release", "taxtrace"]) == 2
    assert cli.main(["keychain", "release"]) == 2
    monkeypatch.undo()
    monkeypatch.setattr(gate, "read", lambda *a: None)  # the approval was declined
    assert cli.main(["keychain", "release", "anthropic"]) == 1
    assert "the read wasn't approved; nothing changed" in capsys.readouterr().out


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
