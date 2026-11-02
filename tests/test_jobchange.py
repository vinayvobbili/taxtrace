"""A year with a change of job, from a made-up pay stub and a made-up last return. Every value is invented."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import printed
from test_k1 import draw
from test_paystub import PAYSLIP

from taxtrace import cli, jobchange, paystub, text

LAST_YEAR = {"year": 2025, "f1040": {"lines": {"2b": "1000", "3b": "2000", "8": "3000", "11": "180000", "24": "30000"}}}


@pytest.fixture
def stub(tmp_path: Path) -> dict:
    path = draw(tmp_path / "payslip.pdf", [PAYSLIP])
    return paystub.read(path.name, text.words(path, 1)).to_json()


def test_the_stub_reads_social_security_and_the_loan_apart_from_the_deferrals(stub: dict):
    assert stub["social_security"]["current"] == "465.00" and stub["social_security"]["year_to_date"] == "8835.00"
    assert stub["loan_repayment"]["current"] == "120.00" and list(stub["deferred"]) == ["pretax"]
    back = paystub.from_json(stub)
    assert back.paychecks_left() == 4 and back.withheld["federal"].current == Decimal("1105.20")
    assert back.salary.current == 7500 and back.state == "NC"


def test_as_it_stands_is_the_stubs_own_projection(stub: dict):
    c = jobchange.build(2026, stub=stub, returns=[LAST_YEAR]).cases[0]
    assert c.paychecks == 4 and c.wages == Decimal("165013.32") and c.withheld == Decimal("27839.46")
    assert c.deferred == 16500 and c.room == 8000
    assert c.social_security == Decimal("10695.00") and c.social_security_back == 0


def test_leaving_stops_the_paychecks_and_a_new_job_withholds_social_security_again(stub: dict):
    confirmed = {"leave": "2026-12-11", "start": "2026-12-14", "new_salary": "196000", "sign_on": "15000"}
    stay, leave = jobchange.build(2026, stub=stub, returns=[LAST_YEAR], confirmed=confirmed).cases
    assert (stay.paychecks, leave.paychecks) == (4, 2)
    # 18 of 365 days of 196,000, plus the sign-on
    new = Decimal(196000) * 18 / 365 + 15000
    assert leave.new_wages == new.quantize(Decimal("0.01"))
    assert leave.old_wages == Decimal("138260") + 2 * Decimal("6688.33")
    # 8,835 + 2 × 465 at the old job, and 6.2% of the new pay at the new one; past the base's 11,439 comes back
    old_ss, new_ss = Decimal(9765), new * Decimal("0.062")
    assert leave.social_security == (old_ss + new_ss).quantize(Decimal("0.01"))
    past = max(Decimal(0), old_ss + new_ss - Decimal("11439.00"))
    assert leave.social_security_back == past.quantize(Decimal("0.01"))


def test_the_limit_is_shared_across_both_plans(stub: dict):
    confirmed = {"leave": "2026-12-11", "start": "2026-12-14", "new_salary": "1200000", "new_percent": "50"}
    _, leave = jobchange.build(2026, stub=stub, returns=[LAST_YEAR], confirmed=confirmed).cases
    assert leave.deferred == 24500 and leave.room == 0  # 15,000 at the old plan, and only the rest at the new


def test_past_the_wage_base_comes_back_as_a_credit(stub: dict):
    confirmed = {"leave": "2026-12-11", "start": "2026-12-14", "new_salary": "600000"}
    _, leave = jobchange.build(2026, stub=stub, returns=[LAST_YEAR], confirmed=confirmed).cases
    assert leave.social_security_back > 0
    assert leave.social_security - leave.social_security_back == Decimal("11439.00")


def test_an_unpaid_loan_is_taxed_with_the_ten_percent_when_leaving_and_not_when_repaid(stub: dict):
    confirmed = {"leave": "2026-12-11", "start": "2026-12-14", "loan": "12000"}
    stay, leave = jobchange.build(2026, stub=stub, returns=[LAST_YEAR], confirmed=confirmed).cases
    assert stay.loan_cost == 0 and leave.loan_taxed == 12000
    assert leave.loan_cost >= Decimal(1200) + Decimal(1200)  # the 10%, the 12% bracket or more, and the state's
    _, repaid = jobchange.build(2026, stub=stub, returns=[LAST_YEAR],
                                confirmed=confirmed | {"loan_repaid": "yes"}).cases
    assert repaid.loan_cost == 0 and repaid.balance < leave.balance


def test_leaving_after_the_year_changes_nothing_this_year(stub: dict):
    change = jobchange.build(2026, stub=stub, returns=[LAST_YEAR], confirmed={"leave": "2027-02-26"})
    assert change.after_year and len(change.cases) == 1
    assert any("changes nothing on the 2026 return" in q.text for q in change.questions)


def test_a_new_percentage_moves_the_wages_and_the_withholding(stub: dict):
    stands = jobchange.build(2026, stub=stub, returns=[LAST_YEAR]).cases[0]
    raised = jobchange.build(2026, stub=stub, returns=[LAST_YEAR], confirmed={"percent": "20"}).cases[0]
    assert raised.wages == stands.wages - 4 * (1500 - Decimal(750))  # 20% of 7,500 is 1,500 against 750
    assert raised.withheld < stands.withheld and raised.deferred == 13500 + 4 * 1500


def test_no_stub_asks_for_one():
    change = jobchange.build(2026, stub=None, returns=[])
    assert not change.cases and "pay stub" in change.questions[0].text


@pytest.mark.parametrize("spec", ["leave=soon", "new_salary=lots", "loan_repaid=maybe", "nothing"])
def test_a_confirmation_that_isnt_one_is_refused(spec: str):
    with pytest.raises(ValueError, match="--confirm takes"):
        jobchange.confirmation(spec)


def test_cli_masks_the_amounts_and_keeps_what_is_confirmed(tmp_path: Path, workspace_home: Path, capsys):
    path = draw(tmp_path / "Payslip.pdf", [PAYSLIP])
    assert cli.main(["paystub", str(path)]) == 0
    capsys.readouterr()
    args = ["jobchange", "--year", "2026", "--confirm", "leave=2026-12-11", "--confirm", "start=2026-12-14",
            "--confirm", "new_salary=196,000", "--confirm", "loan=12,000"]
    assert cli.main(args) == 0
    out = printed(capsys)
    assert "leaving Dec 11: 2 paychecks left" in out and "4 paychecks left" in out
    for secret in ("196,000", "165,013", "27,839", "12,000"):
        assert secret not in out
    saved = json.loads((workspace_home / "jobchange" / "2026.json").read_text())
    assert saved["rollover_deadline"] == "2027-10-15" and len(saved["cases"]) == 2
    assert Decimal(saved["cases"][1]["loan_taxed"]) == 12000
    assert cli.main(["jobchange", "--year", "2026"]) == 0  # the confirmed values are kept
    assert "leaving Dec 11" in printed(capsys)
    assert cli.main(["jobchange", "--year", "2026", "--show"]) == 2  # never amounts to a session that reads the output
