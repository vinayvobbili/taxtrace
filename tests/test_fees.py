"""Made-up Edward Jones statements: an invented account, firm and amounts."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from conftest import printed
from test_k1 import draw

from taxtrace import cli, fees


def page(this_year: str, *reinvestments: str, name: str = "Initech Holdings") -> list[str]:
    return [f"Statement for {name}", "Value Summary                       This Period        This Year",
            f"Fees and Charges                       0.00              {this_year}",
            *[f"03/05 Reinvestment into Globex Corp @ 50.0000 Reinvestment Fee ${fee} 0.02500 -41.20"
              for fee in reinvestments]]


def make(folder: Path, account: str, year: int, month: int, *lines: str) -> Path:
    return draw(folder / f"XXXX{account}-{month:02d}_{year}-edj-statement.pdf", [list(lines)])


def test_file_name_gives_account_year_month():
    assert fees.identify("XXXX4321-12_2025-edj-statement.pdf") == ("4321", 2025, 12)
    assert fees.identify("notes.pdf") is None
    assert fees.identify("XXXX4321-13_2025-edj-statement.pdf") is None


def test_reads_this_year_and_every_reinvestment_fee():
    s = fees.read("XXXX4321-12_2025-edj-statement.pdf", ["\n".join(page("1,234.56", "1.25", "2.50"))])
    assert (s.this_year, s.reinvestment) == (Decimal("1234.56"), Decimal("3.75"))


def test_negative_this_year_is_a_positive_fee():
    s = fees.read("XXXX4321-12_2025-edj-statement.pdf", ["\n".join(page("-87.00"))])
    assert s.this_year == Decimal("87.00")


def test_december_sets_the_year_and_reinvestment_is_apart():
    given = [fees.read(f"XXXX4321-{m:02d}_2025-edj-statement.pdf", ["\n".join(page(amount, "1.00"))])
             for m, amount in ((6, "40.00"), (12, "99.00"))]
    year = fees.total(given)["4321"][2025]
    assert (year.annual, year.reinvestment) == (Decimal("99.00"), Decimal("2.00"))


def test_missing_december_and_zero_fees_and_duplicates():
    june = fees.read("XXXX4321-06_2024-edj-statement.pdf", ["\n".join(page("40.00", "1.25"))])
    zero = fees.read("XXXX4321-12_2025-edj-statement.pdf", ["\n".join(page("0.00"))])
    out = "\n".join(fees.lines(fees.total([june, june, zero])))
    assert "2024: no December statement given" in out
    assert "Reinvestment fees (sum of statements given): 1.25" in out  # the repeated June counted once
    assert "Fees and Charges (annual, December statements): 0.00" in out


def test_cli_totals_a_folder_and_prints_no_names(tmp_path: Path, workspace_home: Path, capsys):
    folder = tmp_path / "EJ"
    make(folder, "4321", 2025, 12, *page("1,234.56", "1.25"))
    make(folder, "4321", 2025, 3, *page("300.00", "2.00"))
    make(folder, "4321", 2024, 5, *page("100.00", "0.50"))
    make(folder, "4410", 2025, 12, *page("0.00"))
    assert cli.main(["fees", str(folder)]) == 0
    out = printed(capsys)
    assert "account ending 4321" in out and "account ending 4410" in out
    assert "1,234.56" in out and "2024: no December statement given" in out
    assert "Fees and Charges (annual, December statements): 1,234.56" in out
    assert "Reinvestment fees (sum of statements given): 3.75" in out
    assert "Initech" not in out and "Globex" not in out and "40.00" not in out


def test_cli_defaults_to_the_workspaces_ej_history(workspace_home: Path, capsys):
    make(workspace_home / fees.HOME_FOLDER, "4321", 2025, 12, *page("10.00"))
    assert cli.main(["fees"]) == 0
    assert "Fees and Charges (annual, December statements): 10.00" in printed(capsys)


def test_cli_without_statements_says_so(tmp_path: Path, workspace_home: Path, capsys):
    assert cli.main(["fees", str(tmp_path)]) == 1
    assert "no Edward Jones statements found" in printed(capsys)
