"""`taxtrace budget check`: a spreadsheet's CSV exports against the budget file, with a map saying which column holds
which line. Made-up plan, lines and amounts only (Initech, Globex, Umbrella); every CSV is built here."""

from __future__ import annotations

import csv
import io
import os
import time
from decimal import Decimal
from pathlib import Path

import pytest
from test_web_budget import get, server  # noqa: F401

from taxtrace import budget, budget_sheet, cli, web, workspace

PLAN = """\
year = 2031
[[lines]]
name = "Housing"
group = "fixed"
monthly = 3300

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

[[funds]]
name = "Travel"
monthly = 260
transfers = { "2031-01" = 0 }
planned = { "2031-07" = 1350 }

[[funds]]
name = "Reserve"
monthly = 235

[[properties]]
name = "Globex Flat"
  [[properties.income]]
  name = "Rent"
  monthly = 1500
  [[properties.costs]]
  name = "HOA"
  monthly = 90
  [[properties.costs]]
  name = "Property tax"
  monthly = 180
  funded_by = "Reserve"
"""
# The tracker tab: a title row above the header, one row per month, a totals row and a baseline row below.
MAP = """\
[[sources]]
file = "sheet-exports/tracker.csv"
kind = "month-grid"
month_column = "Month"
total_row = "2031 total"
total = "Spending lines total"
watch = ["budget", "CAP"]
  [sources.lines]
  "Housing" = "Housing budget"
  "Dining out" = "Dining out CAP"
  "Power" = "Power budget"
  "Water" = "Water budget"
  "Rent" = "Rent budget"
  "HOA" = "HOA budget"
  "Property tax" = "Property tax budget"
  [sources.transfers]
  "Travel" = "Travel transfer"
  "Reserve" = "Reserve transfer"
  [sources.planned]
  "Travel" = "Travel spent plan"

[[sources]]
file = "sheet-exports/detail.csv"
kind = "year-table"
name_column = "Sub-line"
annual_column = "Annual budget"
monthly_column = "Monthly budget"
  [sources.lines]
  "Power" = "Power"
  "Water" = "Water"
"""
HEADER = ["Month", "Housing budget", "Dining out CAP", "Power budget", "Water budget", "Rent budget", "HOA budget",
          "Property tax budget", "Spending lines total", "Travel transfer", "Travel spent plan", "Reserve transfer"]


def money(v) -> str:
    return f"${Decimal(v):,.0f}"


def tracker(plan: budget.Plan) -> list[list[str]]:
    """The tracker's rows as the plan says them: a title row, the header, twelve months, the totals, a baseline."""
    def row(m: str) -> list[str]:
        by = {x.name: x for x in (*plan.lines, *plan.lines[2].subs, *plan.properties[0].lines())}
        travel, reserve = plan.funds
        cells = [by[n].budget(m) for n in ("Housing", "Dining out", "Power", "Water")]
        cells += [by[n].budget(m) for n in ("Rent", "HOA", "Property tax")]
        return [m, *(money(c) for c in cells), money(sum(x.budget(m) for x in plan.lines)),
                money(travel.transfer(m)), money(travel.planned.get(m, 0)), money(reserve.transfer(m))]
    rows = [row(m) for m in plan.months()]
    total = ["2031 total", *(money(sum(Decimal(r[i].replace("$", "").replace(",", "")) for r in rows))
                             for i in range(1, len(HEADER)))]
    return [["Budget tracker 2031"], HEADER, *rows, total, ["2030 baseline", "$3,100"]]


def detail(plan: budget.Plan) -> list[list[str]]:
    power, water = plan.lines[2].subs
    return [["Utilities detail"], ["Sub-line", "Annual budget", "Monthly budget"],
            ["💡 Power", money(plan.yearly(power)), money(power.monthly)],
            ["🚰 Water", money(plan.yearly(water)), money(water.monthly)]]


def csv_text(rows: list[list[str]]) -> str:
    out = io.StringIO()
    csv.writer(out).writerows(rows)
    return out.getvalue()


@pytest.fixture
def plan() -> budget.Plan:
    return budget.parse_plan(PLAN)


@pytest.fixture
def folder(workspace_home: Path, plan) -> Path:
    """A budget folder with the plan, the map and both exports, all in step."""
    path = workspace_home / workspace.BUDGET
    (path / "sheet-exports").mkdir(parents=True)
    (path / "budget-2031.toml").write_text(PLAN, encoding="utf-8")
    (path / "sheet-map.toml").write_text(MAP, encoding="utf-8")
    export(path, "tracker", tracker(plan))
    export(path, "detail", detail(plan))
    return path


def export(folder: Path, name: str, rows: list[list[str]]) -> Path:
    path = folder / "sheet-exports" / f"{name}.csv"
    path.write_text(csv_text(rows), encoding="utf-8")
    return path


def edit(folder: Path, name: str, rows_fn) -> None:
    """Change an export's rows: `rows_fn(rows)` edits them in place."""
    path = folder / "sheet-exports" / f"{name}.csv"
    rows = list(csv.reader(io.StringIO(path.read_text(encoding="utf-8"))))
    rows_fn(rows)
    path.write_text(csv_text(rows), encoding="utf-8")


def cell(rows: list[list[str]], month: str, column: str, value: str) -> None:
    head = next(r for r in rows if column in r)
    row = next(r for r in rows if r and r[0] == month)
    row[head.index(column)] = value


def add_column(rows: list[list[str]], header: str) -> None:
    """A column of $60 under `header`, on the header row and every month's row (the title and baseline rows alone
    are left short, as a sheet's export leaves them)."""
    for row in rows:
        if row and row[0] == "Month":
            row.append(header)
        elif row and budget_sheet.sheet_month(row[0]):
            row.append("$60")


def run(capsys, *args: str) -> tuple[int, str, str]:
    code = cli.main(["budget", "check", *args])
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# -- agreeing -----------------------------------------------------------------------------------------------------

def test_a_sheet_that_matches_is_in_sync(folder, capsys):
    code, out, err = run(capsys)
    assert code == 0 and err == "", out + err
    assert "11 lines compared" in out and "they agree" in out
    assert "only in" not in out and "difference" not in out


def test_counts_come_before_the_list(folder, capsys):
    edit(folder, "tracker", lambda rows: cell(rows, "2031-03", "Dining out CAP", "$130"))
    out = run(capsys)[1]
    assert out.index("lines compared") < out.index("Dining out")


def test_a_changed_cap_is_listed_with_its_month_and_both_figures(folder, capsys):
    edit(folder, "tracker", lambda rows: cell(rows, "2031-03", "Dining out CAP", "$130"))
    code, out, _ = run(capsys)
    assert code == 1
    assert "1 difference\n" in out
    [row] = [line for line in out.splitlines() if line.strip().startswith("Dining out")]
    assert row.split() == ["Dining", "out", "2031-03", "130.00", "90.00", "40.00"]


def test_every_month_that_differs_is_listed(folder, capsys):
    def rows_fn(rows):
        cell(rows, "2031-02", "Housing budget", "$3,350")
        cell(rows, "2031-11", "Housing budget", "$3,250")
    edit(folder, "tracker", rows_fn)
    out = run(capsys)[1]
    assert "2 differences" in out
    assert "2031-02" in out and "2031-11" in out and "50.00" in out and "-50.00" in out


def test_a_month_can_be_written_in_any_common_way(folder, capsys):
    def rows_fn(rows):
        for row, text in zip(rows[2:5], ["Jan 2031", "February 2031", "3/1/2031"], strict=True):
            row[0] = text
    edit(folder, "tracker", rows_fn)
    assert run(capsys)[0] == 0


@pytest.mark.parametrize("text,month", [("2031-03", "2031-03"), ("2031-03-01", "2031-03"), ("3/1/2031", "2031-03"),
                                        ("03/2031", "2031-03"), ("Mar 2031", "2031-03"), ("March 2031", "2031-03"),
                                        ("2031 total", None), ("", None), ("2031-13", None)])
def test_sheet_months(text, month):
    assert budget_sheet.sheet_month(text) == month


@pytest.mark.parametrize("text,value", [("$1,250", "1250"), ("-$40", "-40"), ("(40)", "-40"), ("12.5", "12.5"),
                                        ("", "0"), ("  $7 ", "7")])
def test_sheet_amounts(text, value):
    assert budget_sheet.sheet_amount(text, "x") == Decimal(value)


@pytest.mark.parametrize("text", ["n/a", "no actuals yet", "NaN", "Infinity", "12%"])
def test_a_cell_that_is_not_an_amount_names_where(text):
    with pytest.raises(budget_sheet.SheetError, match=r"tracker\.csv, 'Housing budget' for 2031-03"):
        budget_sheet.sheet_amount(text, "tracker.csv, 'Housing budget' for 2031-03")


# -- the tolerance ------------------------------------------------------------------------------------------------

def test_a_difference_within_the_tolerance_is_no_difference(folder, capsys):
    edit(folder, "tracker", lambda rows: cell(rows, "2031-04", "Housing budget", "3300.40"))
    assert run(capsys)[0] == 0


def test_one_past_the_tolerance_is_listed(folder, capsys):
    edit(folder, "tracker", lambda rows: cell(rows, "2031-04", "Housing budget", "3300.60"))
    code, out, _ = run(capsys)
    assert code == 1 and "0.60" in out


def test_the_tolerance_can_be_given_or_kept_in_the_map(folder, capsys):
    edit(folder, "tracker", lambda rows: cell(rows, "2031-04", "Housing budget", "3300.60"))
    assert run(capsys, "--tolerance", "1")[0] == 0
    assert run(capsys, "--tolerance", "0.10")[0] == 1
    (folder / "sheet-map.toml").write_text("tolerance = 2\n" + MAP, encoding="utf-8")
    assert run(capsys)[0] == 0
    assert run(capsys, "--tolerance", "0")[0] == 1


def test_a_tolerance_that_is_not_an_amount_is_a_usage_error(folder, capsys):
    code, _, err = run(capsys, "--tolerance", "lots")
    assert code == 2 and "--tolerance" in err


# -- sub-lines, funds, properties, totals -------------------------------------------------------------------------

def test_a_sub_line_difference_is_listed_by_the_sub_lines_name(folder, capsys):
    edit(folder, "tracker", lambda rows: cell(rows, "2031-01", "Power budget", "$120"))
    out = run(capsys)[1]
    assert any(line.split()[:2] == ["Power", "2031-01"] for line in out.splitlines())  # January is overridden to 165


def test_a_property_line_difference_is_listed(folder, capsys):
    edit(folder, "tracker", lambda rows: cell(rows, "2031-06", "HOA budget", "$100"))
    code, out, _ = run(capsys)
    assert code == 1
    [row] = [line for line in out.splitlines() if line.strip().startswith("HOA")]
    assert row.split() == ["HOA", "2031-06", "100.00", "90.00", "10.00"]


def test_a_funds_transfer_and_planned_spending_are_each_compared(folder, capsys):
    def rows_fn(rows):
        cell(rows, "2031-05", "Travel transfer", "$300")
        cell(rows, "2031-07", "Travel spent plan", "$1,000")
    edit(folder, "tracker", rows_fn)
    out = run(capsys)[1]
    assert "Travel (transfer)" in out and "Travel (planned)" in out and "-350.00" in out


def test_a_total_that_no_longer_adds_up_is_listed_for_the_year(folder, capsys):
    def rows_fn(rows):
        total = next(r for r in rows if r[0] == "2031 total")
        total[HEADER.index("Spending lines total")] = "$99,999"
    edit(folder, "tracker", rows_fn)
    out = run(capsys)[1]
    [row] = [line for line in out.splitlines() if line.strip().startswith("Spending lines (total)")]
    assert row.split()[3:] == ["year", "99,999.00", "42,825.00", "57,174.00"]


def test_the_yearly_and_monthly_figures_of_a_year_table(folder, capsys):
    def rows_fn(rows):
        next(r for r in rows if r[0].endswith("Water"))[1:] = ["$700", "$60"]
    edit(folder, "detail", rows_fn)
    code, out, _ = run(capsys)
    assert code == 1
    water = [line.split() for line in out.splitlines() if line.strip().startswith("Water")]
    assert ["Water", "year", "700.00", "660.00", "40.00"] in water
    assert ["Water", "each", "month", "60.00", "55.00", "5.00"] in water


def test_a_blank_budget_cell_counts_as_no_budget(folder, capsys):
    edit(folder, "tracker", lambda rows: cell(rows, "2031-09", "Rent budget", ""))
    out = run(capsys)[1]
    assert "Rent" in out and "0.00" in out and "1,500.00" in out


# -- a line on one side only --------------------------------------------------------------------------------------

def test_a_line_the_map_names_that_taxtrace_lacks_is_only_in_the_sheet(folder, capsys):
    (folder / "sheet-map.toml").write_text(MAP.replace('"Water" = "Water budget"',
                                                       '"Water" = "Water budget"\n  "Pet sitting" = "Pet sitting"'),
                                           encoding="utf-8")
    edit(folder, "tracker", lambda rows: add_column(rows, "Pet sitting"))
    code, out, _ = run(capsys)
    assert code == 1
    assert "only in the Sheet:" in out and "Pet sitting (column 'Pet sitting'" in out


def test_a_line_the_map_leaves_out_is_only_in_taxtrace(folder, capsys):
    (folder / "sheet-map.toml").write_text(MAP.replace('  "Water" = "Water budget"\n', "")
                                           .replace('  "Water" = "Water"\n', ""), encoding="utf-8")
    code, out, _ = run(capsys)
    assert code == 1
    assert "only in taxtrace:\n    Water\n" in out


def test_a_fund_the_map_leaves_out_is_only_in_taxtrace_by_its_transfer(folder, capsys):
    (folder / "sheet-map.toml").write_text(MAP.replace('  "Reserve" = "Reserve transfer"\n', ""), encoding="utf-8")
    assert "only in taxtrace:\n    Reserve (transfer)\n" in run(capsys)[1]


def test_a_new_column_that_looks_like_a_budget_is_reported_when_watched(folder, capsys):
    edit(folder, "tracker", lambda rows: add_column(rows, "Pet sitting budget"))
    out = run(capsys)[1]
    assert "Pet sitting budget (column in sheet-exports/tracker.csv, not in the map)" in out


def test_a_column_the_map_says_to_ignore_is_not_reported(folder, capsys):
    edit(folder, "tracker", lambda rows: add_column(rows, "Variance (actual - budget)"))
    assert "Variance" in run(capsys)[1]
    ignoring = 'watch = ["budget", "CAP"]\nignore = ["Variance (actual - budget)"]'
    (folder / "sheet-map.toml").write_text(MAP.replace('watch = ["budget", "CAP"]', ignoring), encoding="utf-8")
    assert run(capsys)[0] == 0


# -- what can't be read -------------------------------------------------------------------------------------------

def test_no_map_is_a_read_error_that_says_where_to_put_it(folder, capsys):
    (folder / "sheet-map.toml").unlink()
    code, out, err = run(capsys)
    assert code == 2 and out == "" and "sheet-map.toml" in err and str(folder) in err


def test_a_missing_export_names_the_file_and_how_to_refresh(folder, capsys):
    (folder / "sheet-exports" / "detail.csv").unlink()
    code, _, err = run(capsys)
    assert code == 2 and "detail.csv" in err and "Export each tab" in err


@pytest.mark.parametrize("bad,says", [
    ("[[sources]\n", "isn't valid TOML"),
    ("", "no sources"),
    ('[[sources]]\nfile = "a.csv"\nkind = "pivot"\n', "kind is one of"),
    ('[[sources]]\nfile = "a.csv"\nkind = "month-grid"\n', "month_column"),
    ('[[sources]]\nfile = "a.csv"\nkind = "month-grid"\nmonth_column = "Month"\n', "map at least one line"),
    ('[[sources]]\nfile = "a.csv"\nkind = "year-table"\nname_column = "Line"\n  [sources.lines]\n  "A" = "A"\n',
     "annual_column or a monthly_column"),
    ('[[sources]]\nfile = "a.csv"\nkind = "month-grid"\nmonth_column = "Month"\nmonths = "soon"\n'
     '  [sources.lines]\n  "A" = "A"\n', "months is a range"),
    ('tolerance = "a bit"\n[[sources]]\nfile = "a.csv"\nkind = "month-grid"\nmonth_column = "M"\n'
     '  [sources.lines]\n  "A" = "A"\n', "tolerance is an amount"),
    ('[[sources]]\nfile = "a.csv"\nkind = "month-grid"\nmonth_column = "M"\n  [sources.lines]\n  "A" = 3\n',
     "maps each budget name"),
])
def test_a_bad_map_says_what_is_wrong(folder, capsys, bad, says):
    (folder / "sheet-map.toml").write_text(bad, encoding="utf-8")
    code, _, err = run(capsys)
    assert code == 2 and says in err


def test_a_column_that_is_not_in_the_export_is_named_with_its_file(folder, capsys):
    (folder / "sheet-map.toml").write_text(MAP.replace('"Housing budget"', '"Rent and mortgage"'), encoding="utf-8")
    code, _, err = run(capsys)
    assert code == 2 and "sheet-exports/tracker.csv" in err and "Rent and mortgage" in err


def test_a_row_that_is_not_in_the_year_table_is_named(folder, capsys):
    (folder / "sheet-map.toml").write_text(MAP.replace('"Water" = "Water"', '"Water" = "Sewer"'), encoding="utf-8")
    code, _, err = run(capsys)
    assert code == 2 and "detail.csv" in err and "Sewer" in err


def test_a_missing_month_row_is_named(folder, capsys):
    edit(folder, "tracker", lambda rows: rows.remove(next(r for r in rows if r[0] == "2031-08")))
    code, _, err = run(capsys)
    assert code == 2 and "no row for 2031-08" in err


def test_two_rows_for_a_month_are_refused(folder, capsys):
    edit(folder, "tracker", lambda rows: rows.insert(4, list(rows[3])))
    code, _, err = run(capsys)
    assert code == 2 and "two rows for 2031-02" in err


def test_an_amount_that_is_text_names_the_column_and_month(folder, capsys):
    edit(folder, "tracker", lambda rows: cell(rows, "2031-05", "Housing budget", "see notes"))
    code, _, err = run(capsys)
    assert code == 2 and "'Housing budget' for 2031-05" in err and "see notes" in err


def test_a_fund_mapped_as_a_line_and_a_line_mapped_as_a_fund_are_refused(folder, capsys):
    (folder / "sheet-map.toml").write_text(MAP.replace('"Housing" = "Housing budget"', '"Travel" = "Housing budget"'),
                                           encoding="utf-8")
    assert "sinking fund" in run(capsys)[2]
    (folder / "sheet-map.toml").write_text(
        MAP.replace('"Reserve" = "Reserve transfer"', '"Housing" = "Reserve transfer"'), encoding="utf-8")
    assert "not a sinking fund" in run(capsys)[2]


def test_no_budget_file_is_a_read_error(workspace_home, capsys):
    (workspace_home / workspace.BUDGET).mkdir(parents=True)
    assert run(capsys)[0] == 2


# -- exports named on the command line ----------------------------------------------------------------------------

def test_sheet_stands_in_for_the_maps_file_of_the_same_name(folder, plan, tmp_path, capsys):
    rows = tracker(plan)
    cell(rows, "2031-03", "Housing budget", "$3,500")
    other = tmp_path / "elsewhere" / "tracker.csv"
    other.parent.mkdir()
    other.write_text(csv_text(rows), encoding="utf-8")
    code, out, _ = run(capsys, "--sheet", str(other))
    assert code == 1 and "200.00" in out
    assert run(capsys)[0] == 0  # the map's own export is untouched


def test_a_sheet_the_map_does_not_know_is_refused(folder, tmp_path, capsys):
    stray = tmp_path / "notes.csv"
    stray.write_text("a,b\n", encoding="utf-8")
    code, _, err = run(capsys, "--sheet", str(stray))
    assert code == 2 and "notes.csv isn't one of the files" in err


def test_another_map_can_be_named(folder, tmp_path, capsys):
    other = tmp_path / "my-map.toml"
    other.write_text(MAP.replace("sheet-exports/", ""), encoding="utf-8")
    code, _, err = run(capsys, "--map", str(other))
    assert code == 2 and "tracker.csv isn't in" in err  # its files are looked for beside it


def test_checking_writes_nothing(folder, capsys):
    edit(folder, "tracker", lambda rows: cell(rows, "2031-03", "Dining out CAP", "$130"))
    files = sorted(p for p in folder.rglob("*") if p.is_file())
    before = {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files}
    run(capsys)
    assert sorted(p for p in folder.rglob("*") if p.is_file()) == files
    assert {p: (p.read_bytes(), p.stat().st_mtime_ns) for p in files} == before


def test_the_output_has_amounts_and_names_only(folder, capsys):
    edit(folder, "tracker", lambda rows: cell(rows, "2031-03", "Dining out CAP", "$130"))
    out = run(capsys)[1]
    assert "nan" not in out.lower() and "inf" not in out.lower()
    assert "Account" not in out and "•" not in out


# -- status and the page ------------------------------------------------------------------------------------------

def test_status_says_whether_the_sheet_still_agrees(folder, capsys):
    cli.main(["budget", "status"])
    assert "Sheet check: in sync" in capsys.readouterr().out
    edit(folder, "tracker", lambda rows: cell(rows, "2031-03", "Dining out CAP", "$130"))
    cli.main(["budget", "status"])
    assert "Sheet check: 1 difference, run taxtrace budget check" in capsys.readouterr().out
    (folder / "sheet-exports" / "tracker.csv").unlink()
    cli.main(["budget", "status"])
    assert "Sheet check: unavailable, run taxtrace budget check" in capsys.readouterr().out


def test_status_stays_quiet_without_a_map(folder, capsys):
    (folder / "sheet-map.toml").unlink()
    cli.main(["budget", "status"])
    assert "Sheet check" not in capsys.readouterr().out


def test_the_check_reports_the_exports_modified_time(folder, plan):
    old = time.mktime((2020, 3, 2, 9, 30, 0, 0, 0, -1))
    os.utime(folder / "sheet-exports" / "tracker.csv", (old, old))
    data = budget_sheet.summary(folder)  # detail.csv is newer: the older export is the one reported
    assert data["state"] == "in_sync" and data["exported"] == "2020-03-02"


def test_the_page_asks_for_the_sheet_apart_and_never_shows_nan(folder, server):  # noqa: F811
    status, data = get(server, "/api/budget/sheet")
    assert status == 200 and data["state"] == "in_sync" and data["count"] == 0 and data["lines"] == 11
    assert data["exported"] and "Export each tab" in data["refresh"]
    edit(folder, "tracker", lambda rows: cell(rows, "2031-03", "Dining out CAP", "$130"))
    status, data = get(server, "/api/budget/sheet")
    assert data["state"] == "differs" and data["count"] == 1
    assert data["diffs"][0] == {"line": "Dining out", "period": "2031-03", "sheet": 130.0, "taxtrace": 90.0,
                                "difference": 40.0, "file": "sheet-exports/tracker.csv"}


def test_the_badge_is_unavailable_without_a_map_or_an_export(workspace_home, server):  # noqa: F811
    assert get(server, "/api/budget/sheet")[1]["state"] == "unavailable"  # no budget folder at all
    folder = workspace_home / workspace.BUDGET
    folder.mkdir(parents=True)
    (folder / "budget-2031.toml").write_text(PLAN, encoding="utf-8")
    data = get(server, "/api/budget/sheet")[1]
    assert data["state"] == "unavailable" and "sheet-map.toml" in data["reason"]
    assert "Export each tab" in data["refresh"]
    (folder / "sheet-map.toml").write_text(MAP, encoding="utf-8")
    assert "tracker.csv" in get(server, "/api/budget/sheet")[1]["reason"]
    (folder / "sheet-map.toml").write_text("not toml [", encoding="utf-8")
    assert get(server, "/api/budget/sheet")[1]["state"] == "unavailable"


def test_the_page_needs_its_token_for_the_sheet_check(folder, server):  # noqa: F811
    assert get(server, "/api/budget/sheet", token="wrong")[0] != 200


def test_the_demo_has_an_example_that_agrees_and_one_that_differs():
    ok = web.budget_sheet_check(demo=True)
    assert ok["state"] == "in_sync" and ok["count"] == 0 and ok["lines"] > 10 and ok["exported"]
    bad = web.budget_sheet_check(demo=True, differs=True)
    assert bad["state"] == "differs"
    assert bad["only_sheet"] == ["Pet sitting (column 'Pet sitting budget' in demo-tracker.csv)"]
    assert [(d["line"], d["sheet"] - d["taxtrace"]) for d in bad["diffs"]] == [("Dining out", 40.0)] * 2
    assert not [k for k in ("nan", "inf") if k in str(bad).lower().replace("info", "")]


def test_the_demo_ignores_the_workspace(folder, capsys):
    (folder / "sheet-map.toml").unlink()
    assert web.budget_sheet_check(demo=True)["state"] == "in_sync"


def test_the_page_has_the_badge_and_its_three_states():
    page = (Path(web.__file__).parent / "static" / "index.html").read_text(encoding="utf-8")
    for text in ('id="budget-sheet"', "Sheet in sync", "Sheet differs:", "Sheet check unavailable", "/api/budget/sheet",
                 "Sheet export read"):
        assert text in page
    assert page.index("loadSheetCheck();  // not awaited") < page.index('renderBudget(await api("/api/budget?"')

