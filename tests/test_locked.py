from __future__ import annotations

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
    monkeypatch.setattr(workspace, "pdf_password", lambda path: None)
    assert cli.main(["redact", str(locked), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "password-protected" in printed and "security add-generic-password -s taxtrace" in printed
    assert PASSWORD not in printed and not list(out.iterdir())

    monkeypatch.setattr(workspace, "pdf_password", lambda path: PASSWORD if path == locked else None)
    assert cli.main(["redact", str(locked), "--out", str(out)]) == 0
    [written] = list(out.iterdir())
    assert "Form 8582 Worksheet 5" in written.read_text()


def test_keychain_lookup_misses_cleanly(tmp_path: Path):
    assert workspace.pdf_password(tmp_path / "no-such-file-taxtrace-test.pdf") is None
