"""Made-up cost summaries: invented accounts, holders and amounts."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from conftest import printed
from test_k1 import draw

from taxtrace import cli, costs

D = Decimal


def sheet(year: int, rows: list[str], total: str, span: str | None = None) -> list[str]:
    span = span or f"January 1, {year} - December 31, {year}"
    return ["Prepared for: Pat Initech & Sam Initech   November 17, 2026", f"Costs by Account   {span}",
            "Account Number Account Holder Fees and Charges Commissions Margin Loan Interest Insurance Total",
            *rows, total]


ROWS = [" 12345678  Initech, Pat CLOSED $95.00  $210.00   $0.00   $0.00  $305.00",
        " 23456789  Initech, Pat & Sam  $12.00  $1,250.50 $0.00   $400.00 $1,662.50"]
TOTAL = "Total                       $107.00 $1,460.50  $0.00  $400.00 $1,967.50"


def test_file_name_gives_year_or_trailing():
    assert costs.identify("cost-summary-2023.pdf") == 2023
    assert costs.identify("cost-summary-trailing-12-months.pdf") == costs.TRAILING
    assert costs.identify("notes.pdf") is None


def test_reads_rows_keeps_last_four_and_closed_flag():
    r = costs.read("cost-summary-2023.pdf", ["\n".join(sheet(2023, ROWS, TOTAL))])
    assert [(a, c) for a, c, _ in r.accounts] == [("5678", True), ("6789", False)]
    assert r.accounts[1][2] == (D("12.00"), D("1250.50"), D("0"), D("400.00"), D("1662.50"))
    assert r.printed_total[4] == D("1967.50")
    assert costs.check(r) == ["  2023: Total row matches the account rows"]


def test_year_comes_from_the_date_range_when_the_name_has_none():
    r = costs.read("cost-summary.pdf", ["\n".join(sheet(2022, ROWS, TOTAL))])
    assert r.period == 2022
    r = costs.read("cost-summary.pdf", ["\n".join(sheet(2022, ROWS, TOTAL, "January 1, 2022 - June 30, 2023"))])
    assert r.period == costs.TRAILING


def test_a_total_that_differs_is_said_plainly():
    bad = TOTAL.replace("$1,967.50", "$1,970.00")
    r = costs.read("cost-summary-2023.pdf", ["\n".join(sheet(2023, ROWS, bad))])
    assert "DIFFERS" in costs.check(r)[0] and "Total (rows 1,967.50, Total row 1,970.00)" in costs.check(r)[0]
    near = TOTAL.replace("$1,967.50", "$1,967.51")
    assert "matches" in costs.check(costs.read("cost-summary-2023.pdf", ["\n".join(sheet(2023, ROWS, near))]))[0]


def test_lifetime_excludes_trailing_and_missing_years_are_named():
    a = costs.read("cost-summary-2021.pdf", ["\n".join(sheet(2021, ROWS, TOTAL))])
    b = costs.read("cost-summary-2023.pdf", ["\n".join(sheet(2023, ROWS, TOTAL))])
    total = "Total $12.00 $1,250.50 $0.00 $400.00 $1,662.50"
    t = costs.read("cost-summary-trailing-12-months.pdf", ["\n".join(sheet(2026, ROWS[1:], total))])
    out = "\n".join(costs.lines(costs.total([a, b, a, t])))
    assert "3,935.00" in out and "5,902.50" not in out  # two years, the repeated 2021 counted once, trailing left out
    assert "missing years: 2020, 2022, 2024, 2025" in out
    assert "trailing 12 months" in out


def test_a_year_with_no_rows():
    r = costs.read("cost-summary-2020.pdf", ["Costs by Account", "nothing here"])
    assert "no account rows found" in "\n".join(costs.lines(costs.total([r])))


def test_cli_totals_a_folder_and_prints_no_names_or_full_numbers(tmp_path: Path, workspace_home: Path, capsys):
    for year in range(2020, 2026):
        draw(tmp_path / f"cost-summary-{year}.pdf", [sheet(year, ROWS, TOTAL)])
    assert cli.main(["costs", str(tmp_path)]) == 0
    out = printed(capsys)
    assert "ending 5678" in out and "CLOSED" in out and "every year 2020-2025 is present" in out
    assert "11,805.00" in out  # six years of 1,967.50
    assert "Initech" not in out and "12345678" not in out and "23456789" not in out


def test_cli_defaults_to_the_workspaces_ej_history(workspace_home: Path, capsys):
    draw(workspace_home / costs.HOME_FOLDER / "cost-summary-2025.pdf", [sheet(2025, ROWS, TOTAL)])
    assert cli.main(["costs"]) == 0
    assert "missing years: 2020, 2021, 2022, 2023, 2024" in printed(capsys)


def test_cli_without_reports_says_so(tmp_path: Path, workspace_home: Path, capsys):
    assert cli.main(["costs", str(tmp_path)]) == 1
    assert "no cost summaries found" in printed(capsys)
