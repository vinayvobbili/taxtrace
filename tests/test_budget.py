"""`taxtrace budget`: the plan, payee rules, importing exports and the status math. Made-up households only: every
payee is an invented company (Initech, Globex, Umbrella and friends) and every amount is invented."""

from __future__ import annotations

import json
import re
import subprocess
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import printed

from taxtrace import budget, budget_demo, budget_import, cli, workspace
from taxtrace.budget import BudgetError, Month, Txn

DATA = Path(__file__).parent / "data"
PIPE = DATA / "pipe-transactions.txt"

PLAN = """\
year = 2031
[[lines]]
name = "Housing"
group = "fixed"
icon = "🏠"
monthly = 3300

[[lines]]
name = "Groceries"
group = "essentials"
monthly = 410

[[lines]]
name = "Fuel and transit"
group = "essentials"
monthly = 480

[[lines]]
name = "Health"
group = "fixed"
monthly = 75

[[lines]]
name = "Shopping"
group = "discretionary"
monthly = 220
cap = true

[[lines]]
name = "Dining out"
group = "discretionary"
monthly = 90
cap = true

[[lines]]
name = "Utilities"
group = "fixed"
  [[lines.sub]]
  name = "Power"
  monthly = 120
  overrides = { "2031-01" = 165 }
  [[lines.sub]]
  name = "Water"
  monthly = 55

[[lines]]
name = "Fun"
group = "family"
  [[lines.sub]]
  name = "Streaming"
  monthly = 75

[[funds]]
name = "Travel"
icon = "✈️"
monthly = 260
opening = 100
planned = { "2031-07" = 1350 }
"""

RULES = """\
[[rules]]
match = "Globex"
line = "shopping"

[[rules]]
match = "Globex Grocery"
line = "Groceries"

[[rules]]
match = ["Soylent Diner", "Wonka Treats"]
line = "Dining out"

[[rules]]
match = "Vandelay Pharmacy"
line = "Health"

[[rules]]
match = "Initech Fuel"
line = "Fuel and transit"

[[rules]]
match = "Umbrella Streaming"
line = "Streaming"

[[rules]]
match = "Monarch Air"
line = "Travel"

[[rules]]
match = "Card Payment"
exclude = true

[[rules]]
match = "Umbrella County Tax"
exclude = true
one_off = true
"""
# What the pipe fixture's March comes to, line by line, with the rules above.
MARCH = {"Groceries": "88.20", "Dining out": "74.05", "Streaming": "12.75", "Health": "54.30", "Shopping": "105.00",
         "Fuel and transit": "64.10"}
# Every payee in this file, the fixture and the made-up household is an invented company's, or a generic phrase.
INVENTED = {"initech", "globex", "umbrella", "vandelay", "acme", "soylent", "wonka", "bluth", "kramerica", "monarch"}
GENERIC = {"card payment thank you", "card payment", "transfer to savings", "savings sweep"}


@pytest.fixture
def plan() -> budget.Plan:
    return budget.parse_plan(PLAN)


@pytest.fixture
def rules(plan) -> list[budget.Rule]:
    return budget.parse_rules(RULES, plan)


@pytest.fixture
def folder(workspace_home: Path, tmp_path: Path, monkeypatch) -> Path:
    """A budget folder with the plan and rules above, and a private folder for raw files beside the workspace."""
    monkeypatch.setenv(budget_import.PRIVATE_ENV, str(tmp_path / "private"))
    path = workspace_home / workspace.BUDGET
    path.mkdir(parents=True)
    (path / "budget-2031.toml").write_text(PLAN, encoding="utf-8")
    (path / "rules.toml").write_text(RULES, encoding="utf-8")
    return path


def txn(day: str, payee: str, value: str, **kw) -> Txn:
    return Txn(day=date.fromisoformat(day), payee=payee, amount=Decimal(value), **kw)


# -- the plan -----------------------------------------------------------------------------------------------------

def test_a_plan_has_lines_in_groups_sub_lines_overrides_and_funds(plan):
    assert [line.name for line in plan.lines][:3] == ["Housing", "Groceries", "Fuel and transit"]
    utilities = plan.find("utilities")
    assert utilities.budget("2031-01") == 220 and utilities.budget("2031-02") == 175
    assert plan.top("Power") is utilities and plan.find("Power").group == "fixed"
    travel = plan.find("Travel")
    assert plan.target(travel) == Decimal(3120) and travel.planned == {"2031-07": Decimal(1350)}
    assert plan.yearly(plan.find("Groceries")) == Decimal(4920)


@pytest.mark.parametrize("text, says", [
    ("", "year"),
    ("year = 2031", "no lines"),
    ('year = 2031\n[[lines]]\nname = "A"\ngroup = "fun"\nmonthly = 1', "group is one of"),
    ('year = 2031\n[[lines]]\nname = "A"\ngroup = "fixed"', "monthly budget"),
    ('year = 2031\n[[lines]]\nname = "A"\ngroup = "fixed"\nmonthly = -5', "isn't an amount"),
    ('year = 2031\n[[lines]]\nname = "A"\ngroup = "fixed"\nmonthly = 1\noverrides = { "March" = 2 }', "YYYY-MM"),
    ('year = 2031\n[[lines]]\nname = "A"\ngroup = "fixed"\nmonthly = 1\n[[funds]]\nname = "a"', "named twice"),
    ("year = [", "valid TOML"),
])
def test_a_plan_that_doesnt_add_up_says_why(text, says):
    with pytest.raises(BudgetError, match=says):
        budget.parse_plan(text)


def test_the_newest_years_plan_is_the_one_read(tmp_path):
    for year in (2030, 2031):
        (tmp_path / f"budget-{year}.toml").write_text(PLAN.replace("2031", str(year)))
    assert budget.load_plan(tmp_path).year == 2031
    assert budget.load_plan(tmp_path / "none") is None


# -- payee rules --------------------------------------------------------------------------------------------------

def test_rules_name_the_line_as_the_plan_spells_it(rules):
    assert rules[0].line == "Shopping" and rules[2].words == ("Soylent Diner", "Wonka Treats")
    assert rules[-1].exclude and rules[-1].one_off and rules[-1].line is None


@pytest.mark.parametrize("payee, line", [
    ("GLOBEX GROCERY #0042", "Groceries"),  # the longer match beats "Globex"
    ("Globex Outlet", "Shopping"),
    ("globex outlet refund", "Shopping"),
    ("SQ *SOYLENT DINER - DOWNTOWN...", "Dining out"),
    ("Initech Fuel 0042", "Fuel and transit"),
    ("Initech Card Payment", None),  # excluded
    ("Initechfuel", "unmatched"),  # whole words only
    ("Kramerica Gizmos", "unmatched"),
])
def test_the_longest_whole_word_match_wins_in_any_case(rules, payee, line):
    rule = budget.match_rule(rules, payee)
    if line == "unmatched":
        assert rule is None
    else:
        assert rule is not None and rule.line == line


@pytest.mark.parametrize("text, rule", [
    ("Globex Grocery -> Groceries", budget.Rule(("Globex Grocery",), "Groceries")),
    ("Acme Card / Bluth Card -> EXCLUDE", budget.Rule(("Acme Card", "Bluth Card"), None, exclude=True)),
    ("Umbrella County Tax -> EXCLUDE ONE-OFF", budget.Rule(("Umbrella County Tax",), None, True, True)),
    ("Monarch Roofing -> Home repairs ONE-OFF", budget.Rule(("Monarch Roofing",), "Home repairs", one_off=True)),
])
def test_a_rule_written_on_one_line(text, rule):
    assert budget.parse_rule_text(text) == rule
    again = budget.parse_rules(budget.rule_toml(rule))
    assert again == [rule]


@pytest.mark.parametrize("text, says", [
    ('[[rules]]\nline = "Groceries"', "match is"),
    ('[[rules]]\nmatch = "Acme"', "give it a line"),
    ('[[rules]]\nmatch = "Acme"\nline = "Rockets"', "isn't a line or fund"),
])
def test_a_rule_that_cant_work_says_why(plan, text, says):
    with pytest.raises(BudgetError, match=says):
        budget.parse_rules(text, plan)


def test_sorting_counts_lines_leaves_out_transfers_and_marks_refunds(plan, rules):
    sort = lambda t: budget.sort_txn(t, rules, plan)  # noqa: E731
    assert sort(txn("2031-03-02", "Globex Grocery", "88.20")).counted
    refund = sort(txn("2031-03-02", "Globex Outlet", "-24.99"))
    assert refund.refund and refund.counted and refund.line == "Shopping"
    assert sort(txn("2031-03-02", "Initech Card Payment", "1180.00")).excluded == "rule"
    assert sort(txn("2031-03-02", "Initech Payroll", "-2350.00", flags=("INCOME",))).excluded == "transfer"
    assert sort(txn("2031-03-02", "Bluth Bank Move", "500.00", category="Transfer")).excluded == "transfer"
    assert sort(txn("2031-03-02", "Bluth Rebate", "-12.75")).excluded == "credit"
    assert sort(txn("2031-03-02", "Kramerica Gizmos", "57.80")).unmatched
    tax = sort(txn("2031-03-02", "Umbrella County Tax", "245.00"))
    assert tax.excluded == "rule" and tax.one_off
    assert sort(txn("2031-03-02", "Monarch Air", "129.99")).fund


def test_refunds_can_be_left_out_instead_of_netted(rules):
    plan = budget.parse_plan('refunds = "exclude"\n' + PLAN)
    refund = budget.sort_txn(txn("2031-03-02", "Globex Outlet", "-24.99"), rules, plan)
    assert refund.refund and refund.excluded == "refund" and not refund.counted


# -- reading exports ----------------------------------------------------------------------------------------------

def test_pipe_separated_transactions_are_read_with_their_flags():
    parsed = budget_import.parse(PIPE.read_text())
    assert parsed.kind == "pipe" and len(parsed.rows) == 14
    assert parsed.skipped == 9  # the heading, notes, section names and totals
    pending = [t for t in parsed.rows if t.pending]
    assert [t.payee for t in pending] == ["GLOBEX GROCERY #0042", "Soylent Diner", "Umbrella Streaming"]
    payroll = next(t for t in parsed.rows if t.payee == "Initech Payroll")
    assert payroll.amount == Decimal("-2350.00") and payroll.flags == ("INCOME",)
    assert next(t for t in parsed.rows if t.payee.startswith("Umbrella County")).flags == ("ONE-OFF TAX",)
    assert all(t.account != "unknown" for t in parsed.rows)


CSV_SIGNED = """Date,Description,Amount
03/02/2031,GLOBEX GROCERY #0042,-88.20
03/04/2031,SOYLENT DINER,-37.25
03/05/2031,GLOBEX OUTLET,-129.99
03/05/2031,GLOBEX OUTLET,24.99
03/06/2031,INITECH PAYROLL,2350.00
03/07/2031,VANDELAY PHARMACY,-54.30
"""
CSV_REORDERED = """Account activity, made up
Exported 04/01/2031

Amount,Status,Payee,Transaction Date,Category
88.20,Posted,Globex Grocery #0042,2031-03-02,Groceries
37.25,Pending,Soylent Diner,2031-03-04,Dining
129.99,Posted,Globex Outlet,2031-03-05,Shopping
-24.99,Posted,Globex Outlet,2031-03-05,Shopping
-2350.00,Posted,Initech Payroll,2031-03-06,Paycheck
54.30,Posted,Vandelay Pharmacy,2031-03-07,Health
"""
CSV_DEBIT_CREDIT = """Posted Date,Details,Debit,Credit,Type
2031-03-02,GLOBEX GROCERY #0042,88.20,,DEBIT
2031-03-04,SOYLENT DINER,"$37.25",,DEBIT
2031-03-05,GLOBEX OUTLET,129.99,,DEBIT
2031-03-05,GLOBEX OUTLET,,24.99,CREDIT
2031-03-06,INITECH PAYROLL,,"2,350.00",CREDIT
2031-03-07,VANDELAY PHARMACY,54.30,,DEBIT
"""


@pytest.mark.parametrize("text", [CSV_SIGNED, CSV_REORDERED, CSV_DEBIT_CREDIT])
def test_csv_columns_are_found_by_name_in_any_order_and_sign(plan, rules, text):
    parsed = budget_import.parse(text)
    assert parsed.kind == "csv" and len(parsed.rows) == 6
    sorted_ = [budget.sort_txn(t, rules, plan) for t in parsed.rows]
    totals = {}
    for s in sorted_:
        if s.counted:
            totals[s.line] = totals.get(s.line, 0) + s.txn.amount
    assert totals == {"Groceries": Decimal("88.20"), "Dining out": Decimal("37.25"), "Shopping": Decimal("105.00"),
                      "Health": Decimal("54.30")}
    assert sum(s.refund for s in sorted_) == 1
    assert next(s for s in sorted_ if s.txn.payee.upper() == "INITECH PAYROLL").excluded in ("transfer", "credit")


def test_a_pending_status_column_marks_pending_rows():
    rows = budget_import.parse(CSV_REORDERED).rows
    assert [t.payee for t in rows if t.pending] == ["Soylent Diner"]
    assert budget_import.parse(CSV_REORDERED).columns["date"] == "Transaction Date"


def test_the_sign_can_be_given_when_the_rows_cant_tell():
    text = "Date,Description,Amount\n2031-03-02,Globex Outlet,-24.99\n"
    assert budget_import.parse(text).rows[0].amount == Decimal("24.99")  # most rows negative: spending is
    assert budget_import.parse(text, sign="spend-positive").rows[0].amount == Decimal("-24.99")


def test_a_file_without_the_columns_says_what_it_needs():
    with pytest.raises(BudgetError, match="date, a description and an amount"):
        budget_import.parse("When,What\n2031-03-02,Globex\n")


@pytest.mark.parametrize("text, value", [("$1,234.56", "1234.56"), ("(12.75)", "-12.75"), ("12.75-", "-12.75"),
                                         ("−18.40", "-18.40"), ("", None), ("n/a", None)])
def test_amounts_in_the_shapes_exports_write_them(text, value):
    assert budget_import.parse_amount(text) == (Decimal(value) if value else None)


# -- importing a month --------------------------------------------------------------------------------------------

def test_importing_the_pipe_list_totals_each_line(folder, plan, rules):
    report = budget_import.import_file(PIPE, "2031-03", folder, plan, rules)
    assert (report.parsed, report.added, report.pending, report.refunds) == (14, 14, 3, 1)
    assert (report.excluded, report.one_off, report.unmatched, report.unmatched_payees) == (4, 1, 1, 1)
    saved = json.loads((folder / "actuals" / "2031-03.json").read_text())
    assert saved["totals"] == MARCH
    assert len(saved["transactions"]) == 14 and saved["trial"] is False


def test_importing_the_same_file_again_changes_nothing(folder, plan, rules):
    budget_import.import_file(PIPE, "2031-03", folder, plan, rules)
    before = (folder / "actuals" / "2031-03.json").read_text()
    again = budget_import.import_file(PIPE, "2031-03", folder, plan, rules)
    assert (again.added, again.unchanged, again.gone) == (0, 14, 0)
    assert json.loads((folder / "actuals" / "2031-03.json").read_text())["totals"] == json.loads(before)["totals"]


def test_a_row_that_posted_since_replaces_its_pending_self(folder, plan, rules, tmp_path):
    first = tmp_path / "march.csv"
    first.write_text("Date,Description,Amount,Status\n2031-03-04,Soylent Diner,37.25,Pending\n"
                     "2031-03-02,Globex Grocery,88.20,Posted\n")
    budget_import.import_file(first, "2031-03", folder, plan, rules, source="card")
    first.write_text("Date,Description,Amount,Status\n2031-03-05,Soylent Diner,37.25,Posted\n"
                     "2031-03-02,Globex Grocery,88.20,Posted\n")
    report = budget_import.import_file(first, "2031-03", folder, plan, rules, source="card")
    assert (report.added, report.unchanged, report.gone) == (1, 1, 1)
    month = budget.load_actuals(folder)["2031-03"]
    assert len(month.txns) == 2 and not any(t.pending for t in month.txns)


def test_the_same_rows_from_another_file_are_duplicates(folder, plan, rules, tmp_path):
    path = tmp_path / "march.csv"
    path.write_text(CSV_REORDERED)
    budget_import.import_file(path, "2031-03", folder, plan, rules, source="one")
    report = budget_import.import_file(path, "2031-03", folder, plan, rules, source="two")
    assert report.duplicates == 6 and report.added == 0
    assert len(budget.load_actuals(folder)["2031-03"].txns) == 6


def test_rows_from_other_months_are_left_out(folder, plan, rules):
    report = budget_import.import_file(PIPE, "2031-04", folder, plan, rules)
    assert report.other_months == 14 and report.added == 0


def test_a_trial_month_is_marked(folder, plan, rules, tmp_path):
    path = tmp_path / "trial.txt"
    path.write_text(PIPE.read_text().replace("2031-03", "2030-11"))
    report = budget_import.import_file(path, "2030-11", folder, plan, rules, trial=True)
    assert report.trial and budget.load_actuals(folder)["2030-11"].trial


def test_the_raw_file_is_kept_on_this_computer_only(folder, plan, rules, tmp_path, workspace_home):
    private = budget_import.check_private(budget_import.private_home(), workspace_home)
    report = budget_import.import_file(PIPE, "2031-03", folder, plan, rules, keep_to=private)
    assert report.kept == private.resolve() / "statements" / "2031-03" / PIPE.name and report.kept.exists()
    assert not report.kept.is_relative_to(workspace_home.resolve())


def test_a_private_folder_inside_the_workspace_or_a_repo_is_refused(workspace_home, tmp_path):
    with pytest.raises(BudgetError, match="inside the workspace"):
        budget_import.check_private(workspace_home / "raw", workspace_home)
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    with pytest.raises(workspace.InsideGitRepo):
        budget_import.check_private(repo / "raw", workspace_home)


def test_the_private_folder_defaults_outside_the_workspace(monkeypatch):
    assert budget_import.private_home({budget_import.PRIVATE_ENV: "/x/raw"}) == Path("/x/raw")
    assert "budget-private" in str(budget_import.private_home({}))


def test_raw_and_pasted_folders_are_never_documents():
    assert {workspace.STATEMENTS, workspace.PASTED} <= workspace.DERIVED


# -- status -------------------------------------------------------------------------------------------------------

@pytest.fixture
def quarter() -> dict[str, Month]:
    """Groceries 400, 500 and 200 (to mid-March); dining 130 in January (over its cap); travel 50 in January;
    utilities 60 not split; a trial month before the year."""
    return {
        "2031-01": Month("2031-01", [txn("2031-01-05", "Globex Grocery", "400"),
                                     txn("2031-01-09", "Soylent Diner", "130"),
                                     txn("2031-01-11", "Monarch Air", "50"),
                                     txn("2031-01-12", "Initech Power Co", "60")]),
        "2031-02": Month("2031-02", [txn("2031-02-05", "Globex Grocery", "500")]),
        "2031-03": Month("2031-03", [txn("2031-03-05", "Globex Grocery", "200", pending=True)]),
        "2030-11": Month("2030-11", [txn("2030-11-05", "Globex Grocery", "999")], trial=True),
    }


def line(s: dict, name: str) -> dict:
    return next(x for x in s["lines"] if x["name"] == name)


def test_year_to_date_budget_spent_pace_and_monthly_average(plan, rules, quarter):
    s = budget.status(plan, rules, quarter, "ytd", date(2031, 3, 15))
    assert s["months"] == ["2031-01", "2031-02", "2031-03"]
    g = line(s, "Groceries")
    assert (g["budget"], g["spent"], g["remaining"], g["monthly"]) == (1230, 1100, 130, 410)
    assert g["pct"] == 89.4 and g["near"] and not g["over"]
    assert g["pace"] == pytest.approx(1100 / (820 + 410 * 15 / 31) * 100, abs=.1)
    assert g["avg"] == pytest.approx(1100 / (2 + 15 / 31), abs=.01)
    assert g["yearly"] == 4920
    assert s["elapsed"] == pytest.approx(2.48, abs=.01) and s["label"] == "2031 year to date: Jan to Mar"


def test_year_to_date_leaves_a_trial_month_out(plan, rules, quarter):
    s = budget.status(plan, rules, quarter, "ytd", date(2031, 3, 15))
    assert line(s, "Groceries")["spent"] == 1100
    trial = budget.status(plan, rules, quarter, "2030-11", date(2031, 3, 15))
    assert trial["trial"] and line(trial, "Groceries")["spent"] == 999 and trial["label"].endswith("(trial month)")
    assert [m["trial"] for m in trial["available"]] == [True, False, False, False]


def test_the_default_is_the_year_once_it_has_a_month_else_the_latest_month(plan, rules, quarter):
    assert budget.status(plan, rules, quarter, today=date(2031, 3, 15))["view"] == "ytd"
    trial_only = {"2030-11": quarter["2030-11"]}
    assert budget.status(plan, rules, trial_only, today=date(2030, 11, 24))["view"] == "2030-11"
    assert budget.status(plan, rules, {}, today=date(2030, 11, 24))["view"] == "ytd"


def test_year_to_date_stops_at_the_latest_month_imported(plan, rules, quarter):
    s = budget.status(plan, rules, {"2031-01": quarter["2031-01"]}, "ytd", date(2031, 4, 20))
    assert s["months"] == ["2031-01"] and line(s, "Groceries")["budget"] == 410


def test_a_month_shows_its_over_cap_lines(plan, rules, quarter):
    s = budget.status(plan, rules, quarter, "2031-01", date(2031, 3, 15))
    dining = line(s, "Dining out")
    assert dining["over"] and dining["cap"] and dining["remaining"] == -40 and dining["pct"] == 144.4
    assert s["totals"]["over"] == 1 and s["totals"]["spent"] == 530  # the fund's 50 and the unmatched 60 aren't


def test_a_part_month_paces_against_the_days_gone(plan, rules, quarter):
    s = budget.status(plan, rules, quarter, "2031-03", date(2031, 3, 15))
    g = line(s, "Groceries")
    assert g["pace"] == pytest.approx(200 / (410 * 15 / 31) * 100, abs=.1)
    assert s["label"] == "March 2031, 15 of 31 days" and s["other"]["pending"] == {"count": 1, "total": 200}


def test_sub_lines_carry_the_budget_and_unsplit_spending_shows(plan, rules, quarter):
    rules = [*rules, budget.Rule(("Initech Power Co",), "Utilities")]
    u = line(budget.status(plan, rules, quarter, "2031-01", date(2031, 3, 15)), "Utilities")
    assert u["budget"] == 220 and u["spent"] == 60
    assert [(x["name"], x["budget"], x["spent"]) for x in u["subs"]] == [("Power", 165, 0), ("Water", 55, 0),
                                                                          ("Not split", None, 60)]


def test_a_funds_balance_is_opening_plus_transfers_less_spending(plan, rules, quarter):
    s = budget.status(plan, rules, quarter, "ytd", date(2031, 3, 15))
    travel = s["funds"][0]
    assert (travel["transfers"], travel["spent"], travel["balance"], travel["target"]) == (780, 50, 830, 3120)
    assert travel["pct"] == pytest.approx(830 / 3120 * 100, abs=.1)
    outside = budget.status(plan, rules, quarter, "2030-11", date(2031, 3, 15))["funds"][0]
    assert outside["balance"] is None  # the fund starts with the plan's year


def test_groups_add_up_and_the_rows_outside_the_lines_are_counted(plan, rules, folder):
    budget_import.import_file(PIPE, "2031-03", folder, plan, rules)
    s = budget.status(plan, rules, budget.load_actuals(folder), "2031-03", date(2031, 3, 31))
    assert sum(g["spent"] for g in s["groups"].values()) == pytest.approx(s["totals"]["spent"]) == 398.40
    o = s["other"]
    assert (o["pending"]["count"], o["refunds"]["count"], o["one_off"]["count"]) == (3, 1, 1)
    assert o["excluded"]["count"] == 4 and o["unmatched"] == {"count": 1, "total": 57.8, "payees": 1}


def test_payments_behind_a_line_never_show_an_account_number(plan, rules, folder):
    budget_import.import_file(PIPE, "2031-03", folder, plan, rules)
    actuals = budget.load_actuals(folder)
    rows = budget.payments(plan, rules, actuals, "2031-03", "Health", date(2031, 3, 31))
    assert rows == [{"date": "2031-03-17", "payee": "Vandelay Pharmacy", "amount": 54.3, "line": "Health",
                     "pending": False, "refund": False, "one_off": False, "excluded": None, "account": "Checking ••••"}]
    assert [r["payee"] for r in budget.payments(plan, rules, actuals, "2031-03", "unmatched")] == ["Kramerica Gizmos"]
    assert len(budget.payments(plan, rules, actuals, "2031-03", "Fun")) == 1  # its sub-line's rows


@pytest.mark.parametrize("label, shown", [("Checking 4417", "Checking ••••"), ("Card 1234-5678-9012", "Card ••••"),
                                          ("Initech Rewards card", "Initech Rewards card")])
def test_account_digits_are_masked(label, shown):
    assert budget.mask_account(label) == shown


# -- the command --------------------------------------------------------------------------------------------------

def test_init_writes_the_made_up_sample_to_a_sample_folder_only(workspace_home, capsys):
    assert cli.main(["budget", "init", "--year", "2031"]) == 0
    sample = workspace_home / "budget" / "sample"
    assert sorted(p.name for p in sample.iterdir()) == ["budget-2031.toml", "rules.toml",
                                                        "sample-transactions-2031-01.txt"]
    assert not (workspace_home / "budget" / "budget-2031.toml").exists()
    assert cli.main(["budget", "init", "--year", "2031"]) == 2  # never over a sample already there
    assert "--force" in capsys.readouterr().err


def test_import_then_status_from_the_command(folder, capsys):
    assert cli.main(["budget", "import", str(PIPE), "--month", "2031-03"]) == 0
    out = printed(capsys)
    assert "14 rows read (pipe)" in out and "3 pending, 1 refunds" in out and "1 rows from 1 payees" in out
    assert cli.main(["budget", "status", "--month", "2031-03"]) == 0
    out = printed(capsys)
    assert "Budget March 2031" in out and re.search(r"Groceries\s+410\.00\s+88\.20\s+321\.80\s+22%", out)
    assert "Shopping" in out and "CAP" in out and "Travel" in out


def test_rules_list_add_and_unmatched_from_the_command(folder, capsys):
    cli.main(["budget", "import", str(PIPE), "--month", "2031-03"])
    capsys.readouterr()
    assert cli.main(["budget", "rules", "--unmatched"]) == 0
    assert "Kramerica Gizmos (1 row)" in printed(capsys)
    assert cli.main(["budget", "rules", "--add", "Kramerica Gizmos -> shopping"]) == 0
    assert "added: Kramerica Gizmos -> Shopping" in printed(capsys)
    saved = json.loads((folder / "actuals" / "2031-03.json").read_text())
    assert saved["totals"]["Shopping"] == "162.80"  # re-sorted with the new rule
    assert cli.main(["budget", "rules"]) == 0
    assert "10 rules" in printed(capsys)
    assert cli.main(["budget", "rules", "--add", "Kramerica -> Rockets"]) == 2


def test_status_without_a_plan_says_how_to_start(workspace_home, capsys):
    assert cli.main(["budget", "status"]) == 1
    assert "budget init" in capsys.readouterr().err


def test_the_budget_folder_inside_a_repo_is_refused(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    monkeypatch.setenv("TAXTRACE_HOME", str(repo / "TaxData"))
    assert cli.main(["budget", "status"]) == 2


# -- the made-up household ----------------------------------------------------------------------------------------

def test_the_demo_household_has_thirteen_lines_in_four_groups_and_its_rules_fit():
    plan, rules, months = budget_demo.demo(date(2031, 3, 15))
    assert len(plan.lines) == 13 and {line.group for line in plan.lines} == set(budget.GROUPS)
    assert list(months) == ["2031-01", "2031-02", "2031-03"]
    assert max(t.day for t in months["2031-03"].txns) <= date(2031, 3, 15)
    s = budget.status(plan, rules, months, "ytd", date(2031, 3, 15))
    assert s["other"]["unmatched"]["payees"] == 1 and s["totals"]["spent"] > 0 and s["funds"]


def test_the_demo_is_the_same_every_time():
    a = budget_demo.demo(date(2031, 3, 15))[2]
    b = budget_demo.demo(date(2031, 3, 15))[2]
    assert [t.to_json() for t in a["2031-02"].txns] == [t.to_json() for t in b["2031-02"].txns]


def _payees() -> set[str]:
    found = {p for p, *_ in budget_demo.MONTH_SHAPE} | {p for p, *_ in budget_demo.LEFT_OUT}
    found |= {p for p, _ in budget_demo.ODD}
    found |= {w for r in budget.parse_rules(budget_demo.SAMPLE_RULES) for w in r.words}
    found |= {t.payee for t in budget_import.parse(PIPE.read_text()).rows}
    for text in (CSV_SIGNED, CSV_REORDERED, CSV_DEBIT_CREDIT):
        found |= {t.payee for t in budget_import.parse(text).rows}
    found |= {w for r in budget.parse_rules(RULES) for w in r.words}
    return found


def test_every_payee_in_the_fixtures_is_invented():
    """The audit's guard against a real merchant copied into a fixture: each payee names an invented company."""
    for payee in _payees():
        words = set(budget.norm(payee).split())
        assert words & INVENTED or budget.norm(payee) in GENERIC, payee


def test_the_budget_code_names_no_issuer():
    """Columns are found by their names, never by a bank's or card's: the code holds only invented companies."""
    for module in (budget, budget_import, budget_demo):
        source = Path(module.__file__).read_text(encoding="utf-8")
        brands = set(re.findall(r"\b([A-Z][a-z]+) (?:Bank|Card|Mortgage|Payroll|Grocery|Pharmacy)\b", source))
        assert {b.lower() for b in brands} <= INVENTED, brands
