"""A rental property in the budget: rent in and costs out, apart from the household's own lines and totals. Made-up
plans and payees only (Initech, Globex, Umbrella)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from taxtrace import budget, budget_basis, budget_demo, cli, web
from taxtrace.budget import BudgetError, Month, Txn

HOUSEHOLD = """\
year = 2031

[[lines]]
name = "Groceries"
group = "essentials"
monthly = 400

[[funds]]
name = "Rental reserve"
monthly = 100
"""
PROPERTY = """
[[properties]]
name = "Initech Row 12"
icon = "🏘️"
  [[properties.income]]
  name = "Rent"
  monthly = 1500
    [properties.income.basis]
    method = "the lease"
  [[properties.costs]]
  name = "HOA"
  monthly = 90
  [[properties.costs]]
  name = "Property tax"
  monthly = 180
  funded_by = "Rental reserve"
  [[properties.costs]]
  name = "Repairs"
  monthly = 100
    [properties.costs.basis]
    method = "proposed: one plumber visit every second month"
    items = [{ month = "2030-10", payee = "Acme Plumbing", amount = 210.00 }]
"""
RULES = """\
[[rules]]
match = "Initech Tenant"
line = "Rent"

[[rules]]
match = "Initech HOA"
line = "HOA"

[[rules]]
match = "Acme Plumbing"
line = "Repairs"

[[rules]]
match = "Globex Grocery"
line = "Groceries"
"""
NO_PROPERTY_RULES = """\
[[rules]]
match = "Globex Grocery"
line = "Groceries"
"""


def t(day: str, payee: str, amount: str, **kw) -> Txn:
    return Txn(day=date.fromisoformat(day), payee=payee, amount=Decimal(amount), **kw)


MARCH = Month("2031-03", [
    t("2031-03-01", "Initech Tenant", "-1500.00", flags=("INCOME",)),  # money in, as exports write it
    t("2031-03-04", "Initech HOA", "90.00"),
    t("2031-03-06", "Acme Plumbing", "140.00"),
    t("2031-03-09", "Globex Grocery", "88.20"),
    t("2031-03-10", "Globex Grocery", "-12.00"),  # a refund on a household line
])
TODAY = date(2031, 3, 31)


def status(extra: str = PROPERTY, rules: str = RULES, month: Month = MARCH) -> dict:
    plan = budget.parse_plan(HOUSEHOLD + extra)
    return budget.status(plan, budget.parse_rules(rules, plan), {"2031-03": month}, "2031-03", TODAY)


def test_a_property_is_read_with_its_income_costs_funding_and_basis():
    plan = budget.parse_plan(HOUSEHOLD + PROPERTY)
    p = plan.properties[0]
    assert (p.name, p.icon, [x.name for x in p.income], [x.name for x in p.costs]) == (
        "Initech Row 12", "🏘️", ["Rent"], ["HOA", "Property tax", "Repairs"])
    assert [x.kind for x in p.lines()] == ["income", "cost", "cost", "cost"]
    assert p.costs[1].funded_by == "Rental reserve" and p.income[0].basis.method == "the lease"
    assert plan.find("hoa") is p.costs[0] and plan.property("initech row 12") is p
    assert p.net("2031-03") == 1500 - 90 - 180 - 100


@pytest.mark.parametrize("bad, why", [
    ('[[properties]]\nname = "X"\n', "give the property income"),
    ('[[properties]]\n[[properties.income]]\nname = "Rent"\nmonthly = 1', "every property needs a name"),
    ('[[properties]]\nname = "X"\n[[properties.income]]\nname = "Rent"', "give it a monthly amount"),
    ('[[properties]]\nname = "X"\n[[properties.income]]\nname = "Rent"\nmonthly = 1\nfunded_by = "Rental reserve"',
     "funded_by is for costs"),
    ('[[properties]]\nname = "X"\n[[properties.costs]]\nname = "HOA"\nmonthly = 1\nfunded_by = "Nowhere"',
     "isn't a sinking fund"),
    ('[[properties]]\nname = "X"\n[[properties.costs]]\nname = "Groceries"\nmonthly = 1', "named twice"),
])
def test_a_broken_property_says_what_is_wrong(bad, why):
    with pytest.raises(BudgetError, match=why):
        budget.parse_plan(HOUSEHOLD + bad)


def test_the_property_nets_rent_less_costs_for_the_month_and_the_year():
    p = status()["properties"][0]
    tot = p["totals"]
    assert (tot["income_budget"], tot["income_received"]) == (1500, 1500)
    assert (tot["cost_budget"], tot["cost_spent"]) == (370, 230)
    assert (tot["net_budget"], tot["net"]) == (1130, 1270)
    assert (tot["monthly_income"], tot["monthly_costs"]) == (1500, 370)
    assert (tot["monthly_net"], tot["yearly_net"]) == (1130, 13560)
    rent, hoa, tax, repairs = p["income"] + p["costs"]
    assert (rent["kind"], rent["spent"], rent["over"], rent["remaining"]) == ("income", 1500, False, 0)
    assert (hoa["spent"], hoa["pct"]) == (90, 100) and tax["funded_by"] == "Rental reserve"
    assert (repairs["spent"], repairs["over"], repairs["basis"]["items"][0]["payee"]) == (140, True, "Acme Plumbing")
    assert p["basis"] is None


def test_the_household_tiles_lines_and_groups_are_the_same_with_or_without_the_property():
    with_property, without = status(), status("", NO_PROPERTY_RULES)
    for key in ("totals", "groups", "lines", "funds"):
        assert with_property[key] == without[key], key
    for key in ("pending", "refunds", "one_off"):
        assert with_property["other"][key] == without["other"][key], key
    assert with_property["totals"]["spent"] == 76.2 and with_property["totals"]["over"] == 0
    assert without["properties"] == []


def test_rent_counts_as_received_whichever_sign_the_export_gives_it_and_never_as_spending():
    deposit = Month("2031-03", [t("2031-03-01", "Initech Tenant", "1500.00")])
    rent = status(month=deposit)["properties"][0]["income"][0]
    assert (rent["spent"], rent["count"]) == (1500, 1)
    s = status()
    assert s["other"]["excluded"]["count"] == 0 and s["other"]["unmatched"]["count"] == 0
    assert s["totals"]["spent"] == 76.2


def test_rent_over_the_plan_is_never_flagged_over():
    extra = Month("2031-03", [t("2031-03-01", "Initech Tenant", "-1500.00"),
                              t("2031-03-20", "Initech Tenant", "-300.00")])
    rent = status(month=extra)["properties"][0]["income"][0]
    assert (rent["spent"], rent["over"], rent["near"], rent["remaining"]) == (1800, False, False, -300)


def test_the_payments_behind_rent_are_positive_and_add_up_to_what_was_received():
    plan = budget.parse_plan(HOUSEHOLD + PROPERTY)
    rows = budget.payments(plan, budget.parse_rules(RULES, plan), {"2031-03": MARCH}, "2031-03", "Rent", TODAY)
    assert [(r["payee"], r["amount"]) for r in rows] == [("Initech Tenant", 1500)]
    assert budget.payments_total(rows, "Rent") == 1500


def test_a_rule_cannot_aim_at_the_property_itself():
    plan = budget.parse_plan(HOUSEHOLD + PROPERTY)
    with pytest.raises(BudgetError, match="isn't a line or fund"):
        budget.parse_rules('[[rules]]\nmatch = "Initech Tenant"\nline = "Initech Row 12"\n', plan)


def test_a_property_and_its_lines_take_a_basis_like_any_line(tmp_path: Path):
    (tmp_path / "budget-2031.toml").write_text(HOUSEHOLD + PROPERTY, encoding="utf-8")
    budget_basis.set_basis(tmp_path, "HOA", method="the association's notice", period="2031")
    budget_basis.set_basis(tmp_path, "Initech Row 12", note="Net of the tenant's deposit.")
    budget_basis.set_basis(tmp_path, "Rent", note="Due on the first.")
    plan = budget.load_plan(tmp_path)
    assert plan.find("HOA").basis.period == "2031" and plan.property("Initech Row 12").basis.note.startswith("Net")
    assert plan.find("Rent").basis.method == "the lease" and plan.find("Rent").basis.note == "Due on the first."
    assert plan.find("Repairs").basis.items[0].payee == "Acme Plumbing"
    assert plan.find("Property tax").basis is None


def test_the_status_command_prints_the_property_net(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.delenv("TAXTRACE_HOME", raising=False)
    (tmp_path / "budget-2031.toml").write_text(HOUSEHOLD + PROPERTY, encoding="utf-8")
    (tmp_path / "rules.toml").write_text(RULES, encoding="utf-8")
    plan = budget.load_plan(tmp_path)
    rules = budget.load_rules(tmp_path, plan)
    budget.save_month(tmp_path, MARCH, plan, rules)
    assert cli.main(["budget", "status", "--month", "2031-03", "--dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "Initech Row 12 (rental)" in out and "in: Rent" in out and "cost: Property tax" in out
    assert "funded by Rental reserve" in out and "1,130.00 a month, 13,560.00 a year" in out


def test_the_made_up_household_has_a_rental_property_that_nets_a_positive_amount():
    d = web.budget_screen(demo=True, today=date(2031, 6, 15))
    p = d["properties"][0]
    assert p["name"] == "Initech Row 12" and [x["name"] for x in p["income"]] == ["Rent"]
    assert [x["name"] for x in p["costs"]] == ["HOA", "Property tax", "Building policy", "Repairs", "Cleaning"]
    assert p["totals"]["monthly_net"] == 1500 - 90 - 180 - 55 - 100 - 50
    assert p["totals"]["income_received"] > 0 and p["income"][0]["basis"]["items"]
    household = budget_demo.demo(date(2031, 6, 15))[0]
    assert len(d["lines"]) == len(household.lines) == 13 and "Rental reserve" in [f["name"] for f in d["funds"]]


def test_the_page_has_a_properties_section_with_green_rent_cards():
    html = web.page("t0ken").decode()
    render = html.split("function renderBudget")[1]
    assert '"Properties"' in render and "propertyBlock(" in render
    js = html.split("function propertyBlock")[0].split("function lineCard")[1]
    assert '"Received"' in html.split("function spentFig")[1].split("function")[0] and "Still to come" in js
    css = html.split("<style>")[1].split("</style>")[0]
    assert ".grp-property.income" in css and ".nettile" in css and ".donut.income" in css
