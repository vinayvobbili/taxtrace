from __future__ import annotations

import re
from pathlib import Path

import pytest
from conftest import AMOUNTS, NAMES, PRIOR_RETURN

from taxtrace import cli, workspace
from taxtrace.redact import redact, vocabulary


def test_amounts_keep_their_shape_not_their_digits():
    assert redact("Total depreciation  $9,892.00").text == "Total depreciation  $#,###.##"
    assert redact("Unallowed loss -23,906").text == "Unallowed loss -##,###"


def test_names_and_places_are_masked_without_being_listed():
    r = redact("Jordan Quillfeather, 4417 Brambleworth Ct, Zentonville")
    assert r.text == "****** ************, #### ************ Ct, ***********"
    assert r.words_masked == 4


def test_tax_words_stay():
    line = "Prior year unallowed losses carried forward"
    assert redact(line).text == line
    assert {"depreciation", "carryover", "basis", "macrs", "hvac"} <= vocabulary()


def test_form_and_line_numbers_stay_but_nothing_else_does():
    assert redact("Form 4562 Line 22 Part II").text == "Form 4562 Line 22 Part II"
    assert redact("W-2 box 1, 1099-INT, D-400").text == "W-2 box #, 1099-INT, D-400"
    # A number after a label is still masked when it's part of an amount.
    assert redact("Line 1,250.00").text == "Line #,###.##"
    # "line" inside another word is no label.
    assert redact("pipeline 22").text.endswith("##")


def test_years_stay_only_where_they_cant_be_an_amount():
    assert redact("in service 06/15/2019").text == "in service ##/##/2019"
    assert redact("Tax year 2025").text == "Tax year 2025"
    assert redact("Insurance        2019").text == "Insurance        ####"
    assert redact("Quillfeather_2025", bare_years=True).text == "************_2025"


def test_terms_mask_names_that_are_also_words():
    r = redact("Paid to Will Banks for roof repair", terms=["Will Banks"])
    assert r.text == "Paid to **** ***** for roof repair"


def test_cli_writes_masked_layout_and_prints_no_names(prior_return: Path, tmp_path: Path, capsys):
    out = tmp_path / "redacted"
    assert cli.main(["redact", str(prior_return.parent), "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    [written] = list(out.iterdir())
    body = written.read_text()
    for secret in NAMES:
        assert secret not in printed and secret not in written.name and secret not in body
    for amount in AMOUNTS:
        assert amount not in body
    assert not re.search(r"\d", re.sub(r"=== page \d+ ===|Form \d+|Line \d+|Worksheet \d+|/2019|/2023", "", body))
    assert "2025" in written.name
    assert "=== page 2 ===" in body and "Form 8582 Worksheet 5" in body
    assert "Residential bldg" in body and "Roof replacement" in body
    assert len(PRIOR_RETURN) == body.count("=== page")


def test_refuses_to_write_into_a_git_repo(prior_return: Path, tmp_path: Path, capsys):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    assert cli.main(["redact", str(prior_return), "--out", str(repo / "out")]) == 2
    assert "stays out of git" in capsys.readouterr().err


def test_workspace_terms_file(workspace_home: Path):
    workspace_home.mkdir()
    (workspace_home / workspace.TERMS_FILE).write_text("# names\nWill Banks\n\n")
    assert workspace.redact_terms() == ["Will Banks"]


@pytest.mark.parametrize("word", ["denver", "tucson", "smith", "john"])
def test_vocabulary_has_no_places_or_names(word):
    assert word not in vocabulary()
