"""The safe harbor quarter by quarter, from a made-up filed return shaped as `prior` saves it."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import printed

from taxtrace import cli, estimates

FILED = {"file": "2025 Return.pdf", "year": 2025,
         "carryovers": [{"section": "Other", "label": "Federal tax liability for 2025 calculation",
                         "amounts": {"amount": "32000"}, "page": 80, "quote": ""}],
         "f1040": {"lines": {"11a": "211875", "24": "32000", "32": "0", "34": "1214", "36": "0"}, "pages": [1, 2]}}


def plan(**confirmed) -> estimates.Plan:
    return estimates.build(2026, returns=[FILED], confirmed={k: str(v) for k, v in confirmed.items()},
                           filing="joint")


def test_withholding_that_reaches_110_percent_meets_every_quarter():
    p = plan(withheld=35200)
    assert (p.last_tax, p.rate, p.required) == (Decimal(32000), Decimal("1.10"), Decimal("35200.00"))
    assert p.short == [] and p.more_withholding == 0 and p.january == 0 and p.margin == 0
    assert [c.ok for c in p.checks] == [True]
    assert [q.text.split(" ")[0] for q in p.questions] == ["2026's"]  # the year's own tax isn't known yet


def test_a_late_payment_counts_only_from_its_day_and_more_withholding_covers_every_quarter():
    p = plan(withheld=27200, **{"paid_2026-09-30": 4000})
    # 35,200 is due, 8,800 a quarter; withholding counts 6,800 a quarter; the payment came after the third's day
    assert [q.short for q in p.quarters] == [Decimal(2000), Decimal(4000), Decimal(6000), Decimal(4000)]
    assert p.short == [1, 2, 3, 4]
    assert p.more_withholding == Decimal(8000) and p.january == Decimal(4000)


def test_last_years_overpayment_applied_counts_in_april_and_the_years_own_tax_can_lower_it():
    applied = {**FILED, "f1040": {"lines": {**FILED["f1040"]["lines"], "34": "9000", "36": "9000"}}}
    p = estimates.build(2026, returns=[applied], confirmed={"withheld": "26200"})
    assert p.short == [] and p.applied == Decimal(9000)
    # the applied 9,000 counts whole from April, so the first quarter has room to spare: the last one binds
    assert p.quarters[0].paid - p.quarters[0].required == Decimal(6750) and p.margin == 0
    p = plan(withheld=27000, tax=30000)  # 90% of 30,000 is 27,000, less than 110% of last year's
    assert p.required == Decimal("27000.00") and p.short == [] and not p.questions


def test_last_years_agi_at_most_150000_takes_100_percent_and_separate_filers_75000():
    lower = {**FILED, "f1040": {"lines": {**FILED["f1040"]["lines"], "11a": "120000"}}}
    assert estimates.build(2026, returns=[lower], filing="joint").rate == 1
    assert estimates.build(2026, returns=[lower], filing="separate").rate == Decimal("1.10")


def test_without_the_worksheet_the_tax_is_line_24_less_line_32_and_without_a_return_its_a_question():
    bare = {**FILED, "carryovers": [], "f1040": {"lines": {"11": "211875", "24": "32500", "32": "500"}}}
    assert estimates.build(2026, returns=[bare]).last_tax == Decimal(32000)
    assert estimates.build(2026, returns=[]).questions[0].text.startswith("the 2025 return isn't read")
    assert "how much federal tax" in plan().questions[-1].text and plan().quarters == []


def test_confirmation_takes_withholding_payments_by_day_and_the_tax():
    assert estimates.confirmation("Withheld = $24,000") == ("withheld", "24000")
    assert estimates.confirmation("paid_2026-09-15=2500") == ("paid_2026-09-15", "2500")
    for bad in ("paid_2026-13-01=5", "withheld=lots", "withheld=-5", "bonus=5", "withheld"):
        with pytest.raises(ValueError):
            estimates.confirmation(bad)


def test_cli_prints_no_amounts(workspace_home: Path, capsys):
    (workspace_home / "carryforwards").mkdir(parents=True)
    (workspace_home / "carryforwards" / "2025 Return.json").write_text(json.dumps(FILED))
    assert cli.main(["estimates", "--year", "2026", "--confirm", "withheld=27200"]) == 0
    out = printed(capsys)
    assert "2026 estimated tax: the safe harbor is 110% of 2025's tax; 0 estimated payments" in out
    assert "quarter 1, due Apr 15, 2026: short #,###.##" in out and "quarter 4, due Jan 15, 2027: short" in out
    assert "more withholding before December 31 of #,###.## meets every quarter; a January payment of #,###.## " \
           "meets quarter 4 only" in out
    for secret in ("27200", "27,200", "35,200", "2,000", "8,000", "211875"):
        assert secret not in out
    saved = json.loads((workspace_home / "estimates" / "2026.json").read_text())
    assert saved["more_withholding"] == "8000.00" and saved["quarters"][0]["short"] == "2000.00"
    assert json.loads((workspace_home / "estimates" / "2026-confirmed.json").read_text()) == {"withheld": "27200"}
