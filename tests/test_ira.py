"""IRA deductions and the Roth IRA's limit at a year's projected income, from a made-up pay stub and filed return
shaped as `paystub` and `prior` save them."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import printed

from taxtrace import cli, ira

STUB = {"form": "paystub", "year": 2026, "paid": "2026-10-31",
        "projected_wages": {"as_is": "238000.00", "401k_filled": "230000.00"}}
FILED = {"year": 2025, "f1040": {"lines": {"1z": "204310", "2b": "41", "3b": "2486", "7a": "61317", "8": "3721",
                                           "10": "0", "11a": "271875"}}}


def test_the_deduction_shrinks_across_the_range_rounded_up_to_ten_and_200_at_least():
    phase = (Decimal(242000), Decimal(252000))
    assert ira.deductible(Decimal(7500), Decimal(242000), phase) == 7500
    assert ira.deductible(Decimal(7500), Decimal(244248), phase) == 5820  # 7,500 less 22.48% of it, 5,814 up to 5,820
    assert ira.deductible(Decimal(7500), Decimal(251900), phase) == 200
    assert ira.deductible(Decimal(7500), Decimal(252000), phase) == 0


def test_filling_the_401k_brings_the_spouse_without_one_under_the_range():
    o = ira.build(2026, stub=STUB, returns=[FILED])
    assert o.other == Decimal(6248)  # interest, dividends and Schedule 1 income; not 2025's capital gain
    as_is, filled = o.cases
    assert (as_is.magi, as_is.other_spouse, as_is.covered_spouse, as_is.roth) == (Decimal(244248), 5820, 0, 5820)
    assert (filled.magi, filled.other_spouse, filled.roth) == (Decimal(236248), 7500, 7500)
    assert [q.text.split(" ")[0] for q in o.questions] == ["2026's"]


def test_the_years_own_other_income_and_whats_missing():
    o = ira.build(2026, stub=STUB, returns=[FILED], confirmed={"other": "20000"})
    assert o.cases[1].magi == Decimal(250000) and o.cases[1].other_spouse == 1500 and not o.questions
    assert ira.build(2026, stub=None, returns=[FILED]).questions[0].text.startswith("no 2026 pay stub")
    bare = {"year": 2025, "f1040": {"lines": {"24": "31906"}}}
    assert "aren't read" in ira.build(2026, stub=STUB, returns=[bare]).questions[0].text
    with pytest.raises(ValueError):
        ira.confirmation("wages=5")


def test_cli_prints_the_deductions_not_the_income(workspace_home: Path, capsys):
    for folder, name, data in (("forms", "Payslip.json", STUB), ("carryforwards", "2025 Return.json", FILED)):
        (workspace_home / folder).mkdir(parents=True, exist_ok=True)
        (workspace_home / folder / name).write_text(json.dumps(data))
    assert cli.main(["ira", "--year", "2026"]) == 0
    out = printed(capsys)
    assert "2026 IRAs: up to 7,500 each" in out
    assert "as is: income ###,###, inside the 242,000-252,000 range; deductible: 5,820 for the spouse without a " \
           "401(k), 0 for the one with it; Roth IRA: 5,820 each" in out
    assert "401(k) filled: income ###,###, under the 242,000-252,000 range; deductible: 7,500" in out
    for secret in ("244,248", "236,248", "6,248", "238,000"):
        assert secret not in out
    assert json.loads((workspace_home / "ira" / "2026.json").read_text())["cases"][0]["magi"] == "244248.00"
