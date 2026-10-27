"""Each spouse's FBAR from a made-up foreign side: invented banks, accounts and balances."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import printed

from taxtrace import cli, fbar, foreign

FOUND = {
    "year": 2026, "estimated": False, "reporting": {"fbar": True, "fbar_spouse": False},
    "accounts": [
        {"account": "3301", "currency": "INR", "holder": "self", "files": ["godavari-3301-2026-03.pdf"], "missing": [],
         "highest": {"dollars": "1834.20"}},
        {"account": "5520", "currency": "INR", "holder": "self", "files": ["godavari-5520-2026-03.pdf"], "missing": [],
         "highest": {"dollars": "9000.01"}},
        {"account": "8811", "currency": "INR", "holder": "joint", "files": ["kaveri-8811-2026-09.pdf"],
         "missing": ["2026-10-01..2026-12-31"], "highest": {"dollars": "250.00"}},
        {"account": "4402", "currency": "INR", "holder": "spouse", "files": ["kaveri-4402-2026-03.pdf"], "missing": [],
         "highest": None},
        {"account": "7781", "currency": "INR", "holder": "", "files": ["godavari-7781-2026-03.pdf"], "missing": []},
    ],
}
STATEMENTS = [{"account": "5520", "operation": "SINGLE", "end": "28-02-2026"},
              {"account": "5520", "operation": "FORMER OR SURVIVOR", "end": "31-03-2026"},
              {"account": "4402", "operation": "SINGLE", "end": "31-03-2026"}]
CONFIRMED = {"bank_godavari": "Godavari Grameena Bank; 12 Tank Bund Road, Vennelapadu 533999, India",
             "joint_3301": "no", "owner_godavari": "Kanakadurga Peddireddi; 9-3 Lotus Lane, Vennelapadu 533999, India"}


def test_each_spouses_accounts_their_parts_and_maximum_values():
    found = fbar.build(2026, FOUND, STATEMENTS, CONFIRMED)
    mine, theirs = found.filers["self"], found.filers["spouse"]
    assert [(i.account, i.part, i.maximum, i.estimate, i.bank) for i in mine] == [
        ("3301", "II", 1835, False, "Godavari Grameena Bank"),  # alone, as confirmed; rounded up to the dollar
        ("5520", "III", 9001, False, "Godavari Grameena Bank"),  # its latest statement: former or survivor
        ("8811", "III", 250, True, "")]  # the spouses' joint account is on both, and its year isn't covered yet
    assert [(i.account, i.part, i.maximum, i.estimate) for i in theirs] == [
        ("8811", "III", 250, True), ("4402", "II", None, True)]
    assert mine[0].address == "12 Tank Bund Road, Vennelapadu 533999, India"
    assert found.due == {"self": True, "spouse": False}
    assert [q.text[:40] for q in found.questions] == [
        "account 3: its bank's name and mailing a", "account 4: its bank's name and mailing a",
        "account 5: whose it is isn't confirmed ("]
    sheet = fbar.checklist(found)
    assert "Your FBAR (due): 3 account(s)" in sheet and "Your spouse’s FBAR (not due): 2 account(s)" in sheet
    assert "  Part II, account ending 3301: Bank, INR\n    maximum value $1,835\n" in sheet
    assert "maximum value $250 (an estimate so far)" in sheet and "Still to settle:" in sheet
    assert [(i.owners, i.principal[:11]) for i in mine] == [(None, ""), (1, "Kanakadurga"), (1, "spouse")]
    assert ("joint owners besides you: 1; principal joint owner: Kanakadurga Peddireddi; 9-3 Lotus Lane, "
            "Vennelapadu 533999, India") in sheet
    assert "joint owners besides you: 1; principal joint owner: the other spouse" in sheet


def test_an_account_held_with_someone_unnamed_asks_who():
    found = fbar.build(2026, FOUND, STATEMENTS, {k: v for k, v in CONFIRMED.items() if k != "owner_godavari"})
    assert found.filers["self"][1].owners is None
    assert any(q.text.startswith("account 2: held with someone else: their name and address for Part III")
               for q in found.questions)


def test_an_account_no_statement_or_confirmation_calls_joint_is_asked_about():
    found = fbar.build(2026, FOUND, STATEMENTS, {k: v for k, v in CONFIRMED.items() if k != "joint_3301"})
    assert found.filers["self"][0].part == "" and any(q.text.startswith("account 1: is it held with anyone else")
                                                      for q in found.questions)


def test_confirmations_for_the_fbar_are_checked():
    assert foreign.confirmation("joint_3301=YES") == ("joint_3301", "yes")
    assert foreign.confirmation("bank_Godavari=Godavari Grameena Bank;12 Tank Bund Road") == (
        "bank_godavari", "Godavari Grameena Bank; 12 Tank Bund Road")
    for bad in ["joint_33=yes", "joint_3301=maybe", "bank_godavari=Godavari Grameena Bank", "bank_g0d=X; Y"]:
        with pytest.raises(ValueError):
            foreign.confirmation(bad)


def test_cli_writes_the_checklist_and_prints_it_masked(workspace_home: Path, capsys):
    assert cli.main(["fbar", "--year", "2026"]) == 1  # no foreign side saved yet
    out = workspace_home / "foreign"
    out.mkdir(parents=True, exist_ok=True)
    (out / "2026.json").write_text(json.dumps(FOUND))
    (out / "2026-confirmed.json").write_text(json.dumps(CONFIRMED))
    forms = workspace_home / "forms"
    forms.mkdir(parents=True, exist_ok=True)
    (forms / "bank-5520-20260301.json").write_text(json.dumps(STATEMENTS))
    capsys.readouterr()
    assert cli.main(["fbar", "--year", "2026"]) == 0
    shown = printed(capsys)
    for secret in ["3301", "5520", "1,835", "9001", "Godavari", "Tank Bund"]:
        assert secret not in shown
    assert "your FBAR, due: 3 account(s)" in shown
    assert "Part II, account ending ####: maximum value known; bank named" in shown
    assert "Part III, account ending ####: maximum value an estimate; bank to name" in shown
    assert "question: account 3: its bank's name and mailing address (`taxtrace foreign --confirm" in shown
    assert "maximum value $1,835" in (out / "fbar-2026.txt").read_text()
    assert json.loads((out / "fbar-2026.json").read_text())["due"] == {"self": True, "spouse": False}
