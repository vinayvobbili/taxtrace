"""A consolidated 1099 statement's 1099-INT and 1099-DIV, drawn side by side the way a broker prints them, for a
made-up broker and account. Every value is invented."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from conftest import make_pdf, printed
from test_f1098 import FORM_1098
from test_k1 import draw, edited

from taxtrace import cli, f1099, k1, text, workspace

BROKER = "Marlowe Brokerage"
# (x, top, text): the 1099-INT's column at the left, the 1099-DIV's right of it; a box's id apart from its label
STATEMENT = [
    (180, 74.4, "2025 CONSOLIDATED 1099 STATEMENT"),
    (30, 91.7, "Recipient's Name:"), (30, 103.3, "Jordan Q. Quillfeather"),
    (200, 109.4, "(Includes 1099-INT, 1099-DIV)"),
    (30, 160.1, f"{BROKER} Account Number:"), (30, 171.7, "604-17228-1-3"),
    (420, 163.7, "Payer's Identification Number:"), (420, 175.3, "47-1029384"),
    (30, 192.5, "Recipient's Identification Number:"), (30, 204.1, "XXX-XX-4410"),
    (30, 255.5, "1099-INT Interest Income - 2025 Statement for recipient"),
    (310, 255.5, "1099-DIV Dividends and Distributions - 2025 Statement for recipient"),
    (150, 267.4, "(OMB NO. 1545-0112)"), (430, 267.4, "(OMB NO. 1545-0110)"),
    (30, 282.4, "Box"), (48, 282.4, "1"), (62, 282.4, "Interest Income"), (285, 282.4, "41.27"),
    (310, 282.4, "Box"), (326, 282.4, "1a"), (340, 282.4, "Total Ordinary Dividends"), (560, 282.4, "2,486.31"),
    (30, 296.4, "Box"), (48, 296.4, "3"), (62, 296.4, "Interest on U.S. Savings Bonds and Treasury"),
    (285, 296.4, "0.00"),
    (310, 296.4, "Box"), (326, 296.4, "1b"), (340, 296.4, "Qualified Dividends"), (560, 296.4, "1,902.55"),
    (310, 310.5, "Box"), (326, 310.5, "2a"), (340, 310.5, "Total Capital Gain Distributions"), (560, 310.5, "1,317.40"),
    (310, 324.7, "Box"), (326, 324.7, "2e"), (340, 324.7, "Section 897 ordinary dividends"), (560, 324.7, "0.00"),
    (340, 338.8, "Section 897 capital gain"), (560, 338.8, "0.00"), (310, 340.9, "Box"), (326, 340.9, "2f"),
    (310, 354.9, "Box"), (326, 354.9, "3"), (340, 354.9, "Nondividend Distributions"), (560, 354.9, "0.00"),
    (310, 369.5, "Box"), (326, 369.5, "5"), (340, 369.5, "Section 199A Dividends"), (560, 369.5, "64.18"),
    (310, 383.8, "Box"), (326, 383.8, "7"), (340, 383.8, "Foreign Tax Paid"), (560, 383.8, "38.92"),
    (310, 398.2, "Box"), (326, 398.2, "8"), (340, 398.2, "Foreign Country or U.S. Possession"),
    (540, 398.2, "Various"),
    (310, 412.5, "Box"), (326, 412.5, "12"), (340, 412.5, "Exempt-Interest Dividends"), (560, 412.5, "15.06"),
    (30, 470.0, "1 This is important tax information and is being furnished to the IRS."),
]
SECRETS = ["2,486", "1,902", "1,317", "64.18", "38.92", "15.06", "41.27", "604-17228", "1029384", "4410", "Marlowe"]


def read(path: Path) -> list[f1099.F1099]:
    pages = text.pages(path)
    return f1099.read(path.name, {n: text.words(path, n) for n, p in enumerate(pages, 1) if f1099.is_form(p)})


def test_each_box_is_read_by_its_row_in_its_forms_column(tmp_path: Path):
    path = draw(tmp_path / "1099.pdf", [STATEMENT])
    interest, dividends = read(path)
    assert (interest.form, dividends.form) == ("1099-INT", "1099-DIV")
    assert {box: v.amount for box, v in interest.amounts.items()} == {"1": Decimal("41.27"), "3": 0}
    assert {box: v.amount for box, v in dividends.amounts.items()} == {
        "1a": Decimal("2486.31"), "1b": Decimal("1902.55"), "2a": Decimal("1317.40"), "2e": 0, "2f": 0, "3": 0,
        "5": Decimal("64.18"), "7": Decimal("38.92"), "12": Decimal("15.06")}
    assert dividends.labels["2f"] == "Section 897 capital gain" and dividends.words == {"8": "Various"}
    assert {(f.year, f.payer_tin, f.account) for f in (interest, dividends)} == {(2025, "47-1029384", "604-17228-1-3")}
    assert interest.failed == dividends.failed == [] and interest.questions == []
    assert [q.text.split(":")[0] for q in dividends.questions] == ["box 7", "box 12"]
    assert "country: Various" in dividends.questions[0].text
    assert k1.verify(dividends, text.words(path, 1)) == [] and k1.verify(interest, text.words(path, 1)) == []


def test_a_part_larger_than_its_whole_fails_and_a_repeat_counts_once(tmp_path: Path):
    more = edited(STATEMENT, **{"1,902.55": "3,100.00"})
    _, dividends, _, copy = read(draw(tmp_path / "1099.pdf", [more, more]))
    assert [(c.what, c.quote) for c in dividends.failed] == [("box 1b is part of box 1a", "3,100.00 against 2,486.31")]
    assert copy.copy_of == 1 and copy.questions == []


def test_other_forms_are_not_read_as_a_1099(tmp_path: Path):
    path = draw(tmp_path / "1098.pdf", [FORM_1098])
    assert not f1099.is_form(text.pages(path)[0])
    assert f1099.on_page("1098.pdf", 1, text.words(path, 1)) == []


def test_cli_prints_no_amounts_or_names(tmp_path: Path, workspace_home: Path, capsys):
    path = draw(tmp_path / "2025 Consolidated 1099.pdf", [STATEMENT])
    assert cli.main(["1099", str(path), "--layout"]) == 0
    out = printed(capsys)
    for secret in SECRETS:
        assert secret not in out
    assert "2025 Form 1099-DIV from ##-#######, amounts in boxes 1a, 1b, 2a, 2e, 2f, 3, 5, 7, 12; 4 of 4 checks " \
           "pass, 2 questions" in out
    assert "box 5 Section ###A Dividends: ##.## at" in out and "box 8 Foreign Country or U.S. Possession: " in out
    saved = json.loads((workspace_home / "forms" / "2025 Consolidated 1099.json").read_text())
    assert [f["form"] for f in saved] == ["1099-INT", "1099-DIV"]
    box_5 = saved[1]["amounts"]["5"]
    assert (box_5["amount"], box_5["label"]) == ("64.18", "Section 199A Dividends")


def test_a_locked_document_is_skipped_without_asking_the_keychain_unless_unlock(tmp_path: Path, workspace_home: Path,
                                                                                 monkeypatch, capsys):
    locked = make_pdf(tmp_path / "docs" / "W-2.pdf", [["Form W-2 Wage and Tax Statement"]], password="not-real")
    asked = []
    monkeypatch.setattr(workspace, "pdf_passwords", lambda path: asked.append(path) or ["not-real"])
    assert cli.main(["1099", str(locked)]) == 0
    assert asked == [] and "locked, skipped without asking the Keychain (--unlock to ask)" in printed(capsys)
    assert cli.main(["1099", str(locked), "--unlock"]) == 0
    assert asked == [locked]
