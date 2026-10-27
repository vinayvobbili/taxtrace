"""A payslip laid out the way a payroll system prints one, for a made-up employee and employer. Every value is
invented."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from conftest import printed
from test_k1 import draw, edited

from taxtrace import cli, paystub, text

# (x, top, text): the header's labels over their values, the taxes' table right of the earnings' rows
PAYSLIP = [
    (23, 55.1, "Employee Name"), (281, 55.1, "Person Number"), (383, 55.1, "Period Date"),
    (512, 55.1, "Payment Date"),
    (23, 65.1, "Jordan Q. Quillfeather"), (281, 65.1, "4410227"), (383, 65.1, "16-OCT-2026"), (434, 65.1, "-"),
    (439, 65.1, "31-OCT-2026"), (512, 65.1, "31-OCT-2026"),
    (23, 104.2, "Marlowe Group"), (383, 104.2, "Annual"), (512, 104.2, "180,000.00"),
    (23, 306.7, "Salary"), (224, 306.7, "7,500.00"), (294, 306.7, "142,500.00"),
    (347, 306.7, "Health Care FSA"), (514, 306.7, "41.67"), (563, 306.7, "791.73"),
    (442, 348.7, "Tax Deductions"),
    (347, 358.7, "Description"), (505, 358.7, "Current"), (550, 358.7, "Year to Date"),
    (23, 368.5, "Group Legal"), (239, 368.5, "0.00"), (310, 368.5, "86.45"),
    (347, 368.5, "FIT Withheld"), (510, 368.5, "1,105.20"), (561, 368.5, "23,418.66"),
    (347, 378.2, "Social Security Employee Withheld"), (510, 378.2, "465.00"), (561, 378.2, "8,835.00"),
    (347, 397.7, "SIT Withheld (NC)"), (510, 397.7, "318.75"), (566, 397.7, "6,056.25"),
]
SECRETS = ["1,105.20", "23,418.66", "318.75", "6,056.25", "Quillfeather", "Marlowe", "4410227"]


def test_the_period_payment_date_and_taxes_are_read_and_the_year_projected(tmp_path: Path):
    path = draw(tmp_path / "payslip.pdf", [PAYSLIP])
    words = text.words(path, 1)
    assert paystub.is_form(words)
    stub = paystub.read(path.name, words)
    assert (stub.period_start, stub.period_end, stub.paid) == (date(2026, 10, 16), date(2026, 10, 31),
                                                              date(2026, 10, 31))
    assert stub.withheld["federal"] == paystub.Taxed(Decimal("1105.20"), Decimal("23418.66"), "FIT Withheld")
    assert stub.withheld["state"].label == "SIT Withheld (NC)"
    # twice a month: November 15 and 30, December 15 and 31
    assert (stub.frequency, stub.paychecks_left()) == ("semimonthly", 4)
    assert stub.projected() == Decimal("23418.66") + 4 * Decimal("1105.20")
    assert stub.failed == [] and len(stub.questions) == 1


def test_a_paycheck_paid_after_its_period_and_every_two_weeks_counts_by_its_payment_date():
    stub = paystub.Paystub("p.pdf", date(2026, 11, 29), date(2026, 12, 12), date(2026, 12, 18))
    assert stub.frequency == "biweekly" and stub.paychecks_left() == 0  # the next, Dec 26's period, pays Jan 1
    stub = paystub.Paystub("p.pdf", date(2026, 10, 1), date(2026, 10, 31), date(2026, 10, 30))
    assert stub.frequency == "monthly" and stub.paychecks_left() == 2


def test_a_year_to_date_smaller_than_this_paycheck_fails(tmp_path: Path):
    stub = paystub.read("p.pdf", text.words(draw(tmp_path / "p.pdf", [edited(PAYSLIP, **{"23,418.66": "900.00"})]),
                                            1))
    assert [c.what for c in stub.failed] == [
        "the federal income tax withheld this paycheck is part of the year to date's"]


def test_cli_prints_no_amounts_and_estimates_takes_the_projection(tmp_path: Path, workspace_home: Path, capsys):
    path = draw(tmp_path / "Payslip.pdf", [PAYSLIP])
    assert cli.main(["paystub", str(path)]) == 0
    out = printed(capsys)
    assert "paid Oct 31, 2026, twice a month, 4 paychecks left in 2026; federal and state tax withheld; 5 of 5 " \
           "checks pass" in out
    for secret in SECRETS:
        assert secret not in out
    saved = json.loads((workspace_home / "forms" / "Payslip.json").read_text())
    assert saved["projected_federal"] == "27839.46" and saved["form"] == "paystub"
    filed = {"year": 2025, "f1040": {"lines": {"11a": "211875", "24": "24000"}}}
    (workspace_home / "carryforwards").mkdir(parents=True)
    (workspace_home / "carryforwards" / "2025 Return.json").write_text(json.dumps(filed))
    assert cli.main(["estimates", "--year", "2026"]) == 0
    out = printed(capsys)
    assert "withholding: the pay stub paid Oct 31, 2026 and its 4 paychecks left" in out
    assert "quarter 4, due Jan 15, 2027: met" in out
    assert json.loads((workspace_home / "estimates" / "2026.json").read_text())["withheld"] == "27839.46"
