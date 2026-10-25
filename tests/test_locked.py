from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from conftest import PRIOR_RETURN, make_pdf

from taxtrace import cli, text, workspace

PASSWORD = "not-a-real-password"


@pytest.fixture
def locked(tmp_path: Path) -> Path:
    return make_pdf(tmp_path / "docs" / "locked_2024_Return.pdf", PRIOR_RETURN, password=PASSWORD)


def test_a_locked_pdf_says_so(locked: Path):
    with pytest.raises(text.Locked, match="password-protected"):
        text.pages(locked)
    with pytest.raises(text.Locked, match="doesn't open it"):
        text.pages(locked, "wrong")
    assert "Form 4562" in text.pages(locked, PASSWORD)[0]


def test_redact_takes_the_password_from_the_keychain(locked: Path, tmp_path: Path, monkeypatch, capsys):
    out = tmp_path / "redacted"
    monkeypatch.setattr(workspace, "pdf_passwords", lambda path: [])
    assert cli.main(["redact", str(locked), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "password-protected" in printed and "security add-generic-password -s taxtrace -a default" in printed
    assert "wrote 0 of 1 files" in printed
    assert PASSWORD not in printed and not list(out.iterdir())

    # The file's own entry is wrong; the default one opens it.
    monkeypatch.setattr(workspace, "pdf_passwords", lambda path: ["stale", PASSWORD] if path == locked else [])
    assert cli.main(["redact", str(locked), "--out", str(out)]) == 0
    assert "wrote 1 of 1 files" in capsys.readouterr().out
    [written] = list(out.iterdir())
    assert "Form 8582 Worksheet 5" in written.read_text()


def test_wrong_passwords_only_still_say_locked(locked: Path, tmp_path: Path, monkeypatch, capsys):
    monkeypatch.setattr(workspace, "pdf_passwords", lambda path: ["stale"])
    assert cli.main(["redact", str(locked), "--out", str(tmp_path / "r")]) == 0
    assert "doesn't open it" in capsys.readouterr().out


def test_a_web_page_saved_as_pdf_is_skipped_not_a_crash(tmp_path: Path, capsys):
    page = tmp_path / "package.pdf"
    page.write_bytes(b"<!DOCTYPE html><html></html>")
    with pytest.raises(text.UnsupportedDocument, match="not a readable PDF") as err:
        text.pages(page)
    assert not isinstance(err.value, text.Locked)
    assert cli.main(["k1", str(page)]) == 0
    assert "not a readable PDF" in capsys.readouterr().out


def test_shape_shows_classes_never_characters():
    assert workspace.shape("abcd12345") == "9 characters: aaaa99999"
    assert workspace.shape("Abcd 1234!") == "10 characters: Aaaa_9999*"


def test_unlock_reports_shapes_and_which_entry_opens(locked: Path, tmp_path: Path, monkeypatch, capsys):
    plain = make_pdf(tmp_path / "docs" / "plain.pdf", PRIOR_RETURN)
    monkeypatch.setattr(workspace, "keychain_entries", lambda path: [("default", "Wrong 1")])
    assert cli.main(["unlock", str(locked), str(plain)]) == 1
    out = capsys.readouterr().out
    assert "Keychain entry 'default': 7 characters: Aaaaa_9" in out
    assert "no stored password opens it" in out and "plain.pdf: not locked" in out
    assert "Wrong" not in out

    monkeypatch.setattr(workspace, "keychain_entries",
                        lambda path: [("locked_2024_Return.pdf", "stale"), ("default", PASSWORD)])
    assert cli.main(["unlock", str(locked)]) == 0
    out = capsys.readouterr().out
    assert "opens with 'default'" in out and PASSWORD not in out and "stale" not in out


def test_keychain_lookup_misses_cleanly(tmp_path: Path, monkeypatch):
    # Never the real default entry: this machine may hold one.
    monkeypatch.setattr(workspace, "KEYCHAIN_DEFAULT", "no-such-account-taxtrace-test")
    assert list(workspace.pdf_passwords(tmp_path / "no-such-file-taxtrace-test.pdf")) == []


def test_a_file_its_own_entry_opens_never_asks_for_the_default_one(tmp_path: Path, monkeypatch):
    # The default entry's read is an approval of its own (Watch, Touch ID or the login password): not needed here.
    asked = []

    def security(cmd, **kw):
        asked.append(cmd[cmd.index("-a") + 1])
        return subprocess.CompletedProcess(cmd, 0, stdout=f"{PASSWORD}\n")
    monkeypatch.setattr(workspace.sys, "platform", "darwin")
    monkeypatch.setattr(workspace.subprocess, "run", security)
    workspace._keychain_password.cache_clear()
    try:
        own = make_pdf(tmp_path / "docs" / "Fund K-1.pdf", PRIOR_RETURN, password=PASSWORD)
        assert cli.main(["unlock", str(own)]) == 0
    finally:
        workspace._keychain_password.cache_clear()
    assert asked == ["Fund K-1.pdf"]


def test_the_keychain_is_asked_once_per_entry_however_many_files_share_it(tmp_path: Path, monkeypatch):
    # Each read of an entry made with -T "" is an Allow prompt for the person: four locked returns, one prompt.
    asked = []

    def security(cmd, **kw):
        asked.append(cmd[cmd.index("-a") + 1])
        found = cmd[-2] == "default"
        return subprocess.CompletedProcess(cmd, 0 if found else 44, stdout=f"{PASSWORD}\n" if found else "")
    monkeypatch.setattr(workspace.sys, "platform", "darwin")
    monkeypatch.setattr(workspace.subprocess, "run", security)
    workspace._keychain_password.cache_clear()
    try:
        files = [make_pdf(tmp_path / "docs" / f"{year} Return.pdf", PRIOR_RETURN, password=PASSWORD)
                 for year in (2021, 2022)]
        assert cli.main(["unlock", str(tmp_path / "docs")]) == 0
    finally:
        workspace._keychain_password.cache_clear()  # nothing faked outlives this test
    assert sorted(asked) == sorted([f.name for f in files] + ["default"])


def test_with_no_paths_named_the_workspace_is_read_without_its_derived_folders(workspace_home: Path, capsys):
    make_pdf(workspace_home / "2023" / "1099-INT.pdf", PRIOR_RETURN)
    for derived in (workspace.OCR_CACHE, workspace.REDACTED):
        make_pdf(workspace_home / derived / "copy.pdf", PRIOR_RETURN)
    (workspace_home / workspace.MANIFEST).write_text("{}\n")
    assert cli.main(["unlock"]) == 0
    assert capsys.readouterr().out.splitlines() == ["1099-INT.pdf: not locked"]

