"""A line's budget basis: how it was set and the past payments it came from, in the budget file, shown by the Budget
tab's info icon and set with `taxtrace budget basis`. Made-up plans and payees only (Initech, Globex, Umbrella)."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from taxtrace import budget, budget_basis, budget_demo, cli, web
from taxtrace.budget import BudgetError

PLAN = """\
# Initech's made-up household
year = 2031

[[lines]]
name = "Groceries"
group = "essentials"
monthly = 400   # a round number
  [lines.basis]
  method = "average of three months, rounded up"
  period = "2030-08 to 2030-10"
  amount_per_month = 395
  note = "Dinner parties not counted."
  items = [
    { month = "2030-10", payee = "Globex Grocery", amount = 410.50 },
    { month = "2030-09", payee = "Globex Grocery", amount = 380.00 },
    { month = "2030-09", payee = "Soylent Market", amount = 22.25 },
  ]

[[lines]]
name = "Initech Utilities"
group = "fixed"
  [[lines.sub]]
  name = "Power"
  monthly = 120
  [[lines.sub]]
  name = "Water"
  monthly = 55

[[funds]]
name = "Rainy day"
monthly = 100
"""

PIPE_ITEMS = """\
Made-up payments
2030-10-04 | Checking 4417 | Initech Power Co | Utilities | 131.40 |
2030-11-03 | Checking 4417 | Initech Power Co | Utilities | 109.85 |
2030-11-09 | Checking 4417 | Globex Water | Utilities | 44.10 |
"""


@pytest.fixture
def folder(tmp_path: Path) -> Path:
    (tmp_path / "budget-2031.toml").write_text(PLAN, encoding="utf-8")
    return tmp_path


def basis_of(folder: Path, name: str):
    return budget.load_plan(folder).find(name).basis


def test_a_basis_is_read_from_the_budget_file():
    plan = budget.parse_plan(PLAN)
    b = plan.find("Groceries").basis
    assert (b.method, b.period) == ("average of three months, rounded up", "2030-08 to 2030-10")
    assert b.amount_per_month == 395
    first = b.items[0]
    assert (first.month, first.payee, first.amount) == ("2030-10", "Globex Grocery", Decimal("410.50"))
    assert plan.find("Power").basis is None and plan.find("Rainy day").basis is None


def test_the_status_carries_the_basis_newest_first_with_its_total_and_months():
    plan = budget.parse_plan(PLAN)
    s = budget.status(plan, [], {}, "2031-03", date(2031, 3, 15))
    b = next(x for x in s["lines"] if x["name"] == "Groceries")["basis"]
    assert [(i["month"], i["payee"]) for i in b["items"]] == [
        ("2030-10", "Globex Grocery"), ("2030-09", "Soylent Market"), ("2030-09", "Globex Grocery")]
    assert (b["total"], b["months"], b["amount_per_month"]) == (812.75, 2, 395)
    assert b["note"] == "Dinner parties not counted."
    utilities = next(x for x in s["lines"] if x["name"] == "Initech Utilities")
    assert utilities["basis"] is None and all(sub["basis"] is None for sub in utilities["subs"])
    assert s["funds"][0]["basis"] is None


@pytest.mark.parametrize("bad, why", [
    ('basis = "x"', "basis is a table"),
    ('[lines.basis]\nitems = "x"', "basis items is a list"),
    ('[lines.basis]\nitems = [{ month = "March", payee = "Globex", amount = 1 }]', "isn't a month"),
    ('[lines.basis]\nitems = [{ month = "2030-10", amount = 1 }]', "needs a month, a payee and an amount"),
    ('[lines.basis]\nmethod = 5', "method is text"),
    ('[lines.basis]\namount_per_month = "NaN"', "isn't an amount"),
])
def test_a_broken_basis_says_what_is_wrong(bad, why):
    text = 'year = 2031\n[[lines]]\nname = "Groceries"\ngroup = "essentials"\nmonthly = 400\n' + bad + "\n"
    with pytest.raises(BudgetError, match=why):
        budget.parse_plan(text)


def test_setting_a_basis_edits_the_file_as_text_and_keeps_its_comments(folder):
    items = budget_basis.items_from(_write(folder, PIPE_ITEMS))
    budget_basis.set_basis(folder, "Power", method="the last bill, rounded up", period="2030-10",
                           amount_per_month="120", items=items)
    text = (folder / "budget-2031.toml").read_text()
    assert "# Initech's made-up household" in text and "monthly = 400   # a round number" in text
    b = basis_of(folder, "Power")
    assert (b.method, b.period, b.amount_per_month) == ("the last bill, rounded up", "2030-10", 120)
    newest = b.items[0]
    assert (newest.month, newest.payee, newest.amount) == ("2030-11", "Initech Power Co", Decimal("109.85"))
    assert "4417" not in text  # the account stays behind
    assert basis_of(folder, "Water") is None and basis_of(folder, "Groceries").method.startswith("average")


def _write(folder: Path, text: str) -> Path:
    path = folder / "payments.txt"
    path.write_text(text, encoding="utf-8")
    return path


def test_given_parts_replace_and_the_rest_stays(folder):
    budget_basis.set_basis(folder, "groceries", note="Changed.", amount_per_month="400")
    b = basis_of(folder, "Groceries")
    assert (b.note, b.amount_per_month, b.method) == ("Changed.", 400, "average of three months, rounded up")
    assert len(b.items) == 3
    assert (folder / "budget-2031.toml").read_text().count("[lines.basis]") == 1


def test_a_parent_and_a_fund_take_a_basis_too_and_clear_removes_it(folder):
    budget_basis.set_basis(folder, "Initech Utilities", method="the sub-lines added up")
    budget_basis.set_basis(folder, "Rainy day", method="set by decision", period="2031")
    assert basis_of(folder, "Initech Utilities").method == "the sub-lines added up"
    assert basis_of(folder, "Rainy day").period == "2031"
    assert basis_of(folder, "Power") is None  # the parent's table did not land on a sub-line
    budget_basis.set_basis(folder, "Groceries", clear=True)
    assert basis_of(folder, "Groceries") is None and "Globex Grocery" not in (folder / "budget-2031.toml").read_text()


def test_a_name_that_is_not_in_the_plan_is_an_error_and_nothing_is_written(folder):
    before = (folder / "budget-2031.toml").read_text()
    with pytest.raises(BudgetError, match="isn't a line, sub-line or fund"):
        budget_basis.set_basis(folder, "Nowhere", method="x")
    with pytest.raises(BudgetError, match="isn't an amount"):
        budget_basis.set_basis(folder, "Power", amount_per_month="lots")
    assert (folder / "budget-2031.toml").read_text() == before


def test_a_file_without_payments_is_refused(folder):
    with pytest.raises(BudgetError, match="doesn't look like a transactions export"):
        budget_basis.items_from(_write(folder, "nothing here\n"))
    with pytest.raises(BudgetError, match="no payments found"):
        budget_basis.items_from(_write(folder, "2030-10-04 | Checking | Initech Power Co | Utilities | 0.00 |\n"))


def test_the_command_lists_shows_and_sets(folder, capsys, monkeypatch):
    monkeypatch.delenv("TAXTRACE_HOME", raising=False)
    path = _write(folder, PIPE_ITEMS)
    assert cli.main(["budget", "basis", "--dir", str(folder)]) == 0
    listed = capsys.readouterr().out
    assert "Groceries" in listed and "3 past payments" in listed and "no basis recorded yet" in listed
    assert cli.main(["budget", "basis", "Water", "--dir", str(folder)]) == 0
    assert "Water: no basis recorded yet" in capsys.readouterr().out
    given = ["--method", "a quote", "--items-from", str(path), "--dir", str(folder)]
    assert cli.main(["budget", "basis", "Water", *given]) == 0
    out = capsys.readouterr().out
    assert "method: a quote" in out and "3 past payments" in out and "Initech Power Co" in out and "4417" not in out
    assert cli.main(["budget", "basis", "Nowhere", "--dir", str(folder)]) == 2


def test_the_made_up_household_has_a_basis_on_some_of_its_lines():
    plan, _, _ = budget_demo.demo(date(2031, 6, 15))
    assert plan.find("Groceries").basis.items and plan.find("Power").basis.period == "2030-09 to 2030-12"
    assert plan.find("Travel").basis.method.startswith("set by decision")
    assert plan.find("Housing").basis is None


def test_the_page_has_one_modal_for_the_info_icons_with_the_empty_state():
    html = web.page("t0ken").decode()
    js = html.split("function openModal")[1].split("function paymentsModal")[0]
    assert "showModal()" in js and 'e.target === dlg' in js and "opener.focus()" in js
    assert "How this budget was set" in js and "No basis recorded yet." in js and "taxtrace budget basis" in js
    css = html.split("<style>")[1].split("</style>")[0]
    assert ".bmodal::backdrop" in css and ".ibtn" in css and 'data-width="wide"] .bmodal' in css


def test_the_info_icon_is_on_every_kind_of_card():
    html = web.page("t0ken").decode()
    assert html.count("basisBtn(") >= 4  # the definition, a line card, a group header and a fund card
    assert json.dumps(html).count("nameRow(") >= 4
