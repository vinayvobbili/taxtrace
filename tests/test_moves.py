"""A year's tax-saving moves, from a made-up pay stub and a made-up last return. Every value is invented."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import printed
from test_k1 import draw
from test_paystub import PAYSLIP

from taxtrace import cli, moves, paystub, text, web

LAST_YEAR = {"year": 2025, "f1040": {"lines": {"2b": "1000", "3b": "2000", "8": "3000", "11": "180000", "24": "30000"}}}
SALES = {"room": "1800"}


@pytest.fixture
def stub(tmp_path: Path) -> dict:
    path = draw(tmp_path / "payslip.pdf", [PAYSLIP])
    return paystub.read(path.name, text.words(path, 1)).to_json()


def by_key(plan: moves.Plan) -> dict[str, moves.Move]:
    return {m.key: m for m in plan.moves}


def test_each_move_saves_at_the_brackets_with_the_state_where_it_counts(stub: dict):
    plan = moves.build(2026, stub=stub, returns=[LAST_YEAR], sales=SALES)
    got = by_key(plan)
    assert plan.income == Decimal("165013.32") + 6000
    # past the 32,200 deduction and into the 22% bracket: 22 cents and the state's 3.99 for each of the 8,000
    assert got["401k"].amount == 8000 and got["401k"].saving == Decimal("2079.20")
    assert got["losses"].saving == (Decimal(1800) * Decimal("0.2599")).quantize(Decimal("0.01"))
    # the charity's federal only
    assert got["charity"].amount == 2000 and got["charity"].saving == Decimal(2000) * Decimal("0.22")
    assert got["spouse_ira"].amount == 7500 and got["own_ira"].amount == 0 if "own_ira" in got else True
    assert (got["401k"].by, got["losses"].by) == (date(2026, 12, 31), date(2026, 12, 31))
    assert got["spouse_ira"].by == date(2027, 4, 15)


def test_the_moves_rank_by_dollars_with_what_is_done_last(stub: dict):
    plan = moves.build(2026, stub=stub, returns=[LAST_YEAR], sales=SALES, confirmed={"done_401k": "yes"})
    assert plan.moves[-1].key == "401k" and plan.moves[-1].done
    savings = [m.saving for m in plan.moves if not m.done]
    assert savings == sorted(savings, reverse=True)
    assert plan.open_saving == sum(savings)


def test_a_plans_cap_limits_what_the_401k_can_still_reach(stub: dict):
    plan = moves.build(2026, stub=stub, returns=[LAST_YEAR], confirmed={"plan_cap": "20"})
    got = by_key(plan)["401k"]
    assert got.amount == 4 * (1500 - Decimal(750)) and "20" in got.action  # 20% of 7,500 against 750, 4 paychecks


def test_the_moves_are_stacked_so_a_bracket_isnt_counted_twice(stub: dict):
    # 1,000 into the 24% bracket, which starts 211,400 past the 32,200 deduction
    high = {"year": 2025, "f1040": {"lines": {"8": "79586.68"}}}
    plan = moves.build(2026, stub=stub, returns=[high], sales={"room": "3000"})
    assert plan.income == Decimal("244600.00")
    got = by_key(plan)
    # the 401(k) takes the 1,000 at 24% and 7,000 at 22%, and the losses after it get 22% only
    assert got["401k"].saving == Decimal(240) + Decimal(1540) + Decimal(8000) * Decimal("0.0399")
    assert got["losses"].saving == Decimal(3000) * Decimal("0.2599")


def test_rental_tax_and_what_a_job_change_found_join_the_list(stub: dict):
    change = {"leave": "2026-12-11", "cases": [{}, {"loan_cost": "3000.00", "loan_taxed": "12000",
                                                     "social_security_back": "900.00"}]}
    plan = moves.build(2026, stub=stub, returns=[LAST_YEAR], jobchange=change, confirmed={"rental_tax": "3000"})
    got = by_key(plan)
    assert got["rental_tax"].amount == 3000 and got["loan"].saving == 3000 and got["loan"].by == date(2026, 12, 11)
    assert got["social_security"].saving == 900


def test_the_page_serves_the_latest_years_saved_plans(workspace_home: Path):
    assert web.plans() == {"year": None, "moves": None, "jobchange": None, "sales": None}
    for folder, year, saved in (("moves", 2025, {"open_saving": "1"}), ("moves", 2026, {"open_saving": "2"}),
                                ("sales", 2026, {"room": "3"})):
        (workspace_home / folder).mkdir(parents=True, exist_ok=True)
        (workspace_home / folder / f"{year}.json").write_text(json.dumps(saved))
    (workspace_home / "moves" / "2027-confirmed.json").write_text("{}")  # what was confirmed isn't a year's plan
    assert web.plans() == {"year": 2026, "moves": {"open_saving": "2"}, "jobchange": None, "sales": {"room": "3"}}
    page = web.page("t0ken").decode()
    assert 0 < page.index('id="todo"') < page.index('id="plan"') < page.index("Documents by folder")


def test_nothing_to_stack_on_asks_for_a_stub():
    plan = moves.build(2026, stub=None, returns=[])
    assert not plan.moves and "pay stub" in plan.questions[0].text


@pytest.mark.parametrize("spec", ["plan_cap=lots", "rental_tax=-1", "done_nothing=yes", "done_401k=maybe", "x=1", "y"])
def test_a_confirmation_that_isnt_one_is_refused(spec: str):
    with pytest.raises(ValueError, match="--confirm takes"):
        moves.confirmation(spec)


def test_cli_ranks_with_amounts_masked_and_saves_them_for_the_page(tmp_path: Path, workspace_home: Path, capsys):
    path = draw(tmp_path / "Payslip.pdf", [PAYSLIP])
    assert cli.main(["paystub", str(path)]) == 0
    capsys.readouterr()
    assert cli.main(["moves", "--year", "2026", "--confirm", "plan_cap=20"]) == 0
    out = printed(capsys)
    assert "1. " in out and "Fill the 401(k)" in out and "at the return" in out
    for secret in ("1,800.00", "165,013", "2,079"):
        assert secret not in out
    saved = json.loads((workspace_home / "moves" / "2026.json").read_text())
    assert saved["moves"] and Decimal(saved["open_saving"]) > 0
    assert cli.main(["moves", "--year", "2026", "--show"]) == 2
    assert cli.main(["moves", "--year", "2026", "--confirm", "nothing"]) == 2
