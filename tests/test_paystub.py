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
    (96, 197.7, "Gross Earnings"), (173, 197.7, "Pre-Tax Deductions"), (260, 197.7, "Federal Taxable Wages"),
    (370, 197.7, "Tax Deductions"), (448, 197.7, "Other Deductions"), (567, 197.7, "Net Pay"),
    (23, 208.2, "Current"), (124, 208.2, "7,500.00"), (221, 208.2, "811.67"), (318, 208.2, "6,688.33"),
    (399, 208.2, "2,183.25"), (484, 208.2, "161.67"), (565, 208.2, "4,343.41"),
    (23, 219.4, "Year to Date"), (115, 219.4, "154,500.00"), (210, 219.4, "16,240.00"), (309, 219.4, "138,260.00"),
    (394, 219.4, "41,700.00"), (480, 219.4, "3,400.00"), (561, 219.4, "93,160.00"),
    (23, 296.9, "Annual Incentive Bonus"), (239, 296.9, "0.00"), (298, 296.9, "12,000.00"),
    (347, 296.9, "401k Before-Tax"), (510, 296.9, "750.00"), (558, 296.9, "13,500.00"),
    (347, 444.0, "401k Loan Repay 1"), (503, 444.0, "120.00"), (561, 444.0, "2,280.00"),
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
    # the loan's repayment isn't a deferral; 24,500 less 13,500 so far and 750 for each of the 4 left
    assert list(stub.deferred) == ["pretax"] and stub.deferred["pretax"].label == "401k Before-Tax"
    assert stub.salary == paystub.Taxed(Decimal(7500), Decimal(142500), "Salary")
    assert stub.deferral_room() == Decimal(8000) and stub.deferral_rates() == (Decimal(10), Decimal(37))
    assert stub.taxable_wages == paystub.Taxed(Decimal("6688.33"), Decimal(138260), "Federal Taxable Wages")
    assert stub.projected_wages() == Decimal("165013.32") and stub.projected_wages(True) == Decimal("157013.32")
    assert stub.failed == [] and len(stub.questions) == 2


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
    assert "paid Oct 31, 2026, twice a month, 4 paychecks left in 2026; federal and state tax withheld; 6 of 6 " \
           "checks pass" in out
    assert "401(k): pretax deferrals; room left under the 2026 limit #,###.##; pre-tax is 10% of salary now, 37% " \
           "for the 4 paychecks left fills it" in out
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
    # 27,839.46 withheld against 26,400 due leaves 1,439.46; 24% of the 8,000 room is 1,920
    assert "the withholding could fall by #,###.## and still meet every quarter" in out
    assert "filling the 401(k)'s room withholds about #,###.## less: every quarter isn't met; ###.## more withheld " \
           "(a W-4 extra amount) makes it up" in out
    assert json.loads((workspace_home / "estimates" / "2026.json").read_text())["withheld"] == "27839.46"
