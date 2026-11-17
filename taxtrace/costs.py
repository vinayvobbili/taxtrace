"""What a brokerage's annual "Summary of Your Costs Paid to <firm>" reports add up to.

Page 1 has a "Costs by Account" table: a row per account (8-digit number, holder, an optional CLOSED flag, then Fees and
Charges, Commissions, Margin Loan Interest, Insurance and Total) and a Total row. The file name says which report it
is: cost-summary-2023.pdf for a calendar year, cost-summary-trailing-12-months.pdf for the rolling one, which overlaps
the years and so is shown apart from the lifetime total. Each Total row is checked against the sum of its account rows.
Only the last four digits of an account, years and amounts are ever kept: holders' names and full numbers are dropped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

NAME = re.compile(r"cost-summary(?:-(\d{4}|trailing-12-months))?", re.IGNORECASE)
AMOUNT = r"\(?-?\$?\s*\d[\d,]*\.\d{2}\)?"
FIVE = rf"((?:{AMOUNT}\s+){{4}}{AMOUNT})\s*$"
ROW = re.compile(rf"^\s*(\d{{8}})\s+(.*?)\s*{FIVE}")
TOTAL = re.compile(rf"^\s*Total\s+{FIVE}", re.IGNORECASE)
RANGE = re.compile(r"[A-Z][a-z]+ \d{1,2}, (\d{4})\s*[-–]\s*[A-Z][a-z]+ \d{1,2}, (\d{4})")
CLOSED = re.compile(r"\bCLOSED\b", re.IGNORECASE)
HOME_FOLDER = "EJ-history"
COLUMNS = ("Fees and Charges", "Commissions", "Margin Loan Interest", "Insurance", "Total")
YEARS = range(2020, 2026)
TRAILING = "trailing"
ZERO = (Decimal("0"),) * 5


@dataclass
class Report:
    period: int | str  # the calendar year, or TRAILING
    accounts: list[tuple[str, bool, tuple[Decimal, ...]]] = field(default_factory=list)  # last four, closed, amounts
    printed_total: tuple[Decimal, ...] | None = None


def money(printed: str) -> Decimal:
    """'$1,250.50' or '(12.00)' as a positive amount: a cost is reported as what was paid."""
    return abs(Decimal(re.sub(r"[^\d.]", "", printed)))


def amounts(printed: str) -> tuple[Decimal, ...]:
    return tuple(money(a) for a in re.findall(AMOUNT, printed))


def identify(name: str) -> int | str | None:
    """The calendar year, or TRAILING, from a report's file name; None when it isn't one."""
    m = NAME.search(name)
    if not m:
        return None
    if not m.group(1):
        return TRAILING if "trailing" in name.lower() else 0  # 0: a cost summary whose year the text must give
    return TRAILING if m.group(1).lower().startswith("trailing") else int(m.group(1))


def read(name: str, pages: list[str]) -> Report | None:
    """A report from its text, or None when the file name isn't a cost summary's. No year in the name: the dates."""
    period = identify(name)
    if period is None:
        return None
    joined = "\n".join(pages)
    if period == 0:
        span = RANGE.search(joined)
        if not span:
            return None
        period = int(span.group(1)) if span.group(1) == span.group(2) else TRAILING
    report = Report(period)
    for line in joined.splitlines():
        if row := ROW.match(line):
            report.accounts.append((row.group(1)[-4:], bool(CLOSED.search(row.group(2))), amounts(row.group(3))))
        elif (tot := TOTAL.match(line)) and report.printed_total is None:
            report.printed_total = amounts(tot.group(1))
    return report


def total(reports: list[Report]) -> dict[int | str, Report]:
    """One report per period; a file given twice counts once."""
    return {r.period: r for r in reports}


def summed(report: Report) -> tuple[Decimal, ...]:
    return tuple(sum((a[2][i] for a in report.accounts), Decimal("0")) for i in range(5))


def table(report: Report) -> list[str]:
    head = f"  {'account':<13}{'closed':<8}" + "".join(f"{c:>22}" for c in COLUMNS)
    out = [head]
    for account, closed, values in report.accounts:
        flag = "CLOSED" if closed else ""
        out.append(f"  {'ending ' + account:<13}{flag:<8}" + "".join(f"{v:>22,.2f}" for v in values))
    return out


def lines(reports: dict[int | str, Report]) -> list[str]:
    """Each report's table and cross-check, the lifetime total of the calendar years, the trailing report, the gaps."""
    out: list[str] = []
    lifetime = list(ZERO)
    for period in sorted(p for p in reports if p != TRAILING):
        r = reports[period]
        out += [f"{period}"] + (table(r) if r.accounts else ["  no account rows found"])
        out += check(r)
        lifetime = [a + b for a, b in zip(lifetime, summed(r), strict=True)]
    years = sorted(p for p in reports if p != TRAILING)
    out += [f"lifetime total, calendar years {years[0]}-{years[-1]} ({len(years)} reports)" if years
            else "lifetime total: no calendar-year reports"]
    out += [f"  {c:<22}{v:>14,.2f}" for c, v in zip(COLUMNS, lifetime, strict=True)]
    if TRAILING in reports:
        r = reports[TRAILING]
        out += ["trailing 12 months (overlaps the years, not in the lifetime total)"]
        out += table(r) if r.accounts else ["  no account rows found"]
        out += check(r)
    missing = [y for y in YEARS if y not in reports]
    every = f"every year {YEARS[0]}-{YEARS[-1]} is present"
    out.append(f"missing years: {', '.join(map(str, missing))}" if missing else every)
    return out


def check(report: Report) -> list[str]:
    """Say plainly when the printed Total row and the account rows differ by more than a cent."""
    if report.printed_total is None:
        return [f"  {report.period}: no Total row found to check against"] if report.accounts else []
    sums = summed(report)
    off = [f"{c} (rows {s:,.2f}, Total row {p:,.2f})"
           for c, s, p in zip(COLUMNS, sums, report.printed_total, strict=True) if abs(s - p) > Decimal("0.01")]
    if off:
        return [f"  {report.period}: DIFFERS, the account rows do not add up to the Total row: " + "; ".join(off)]
    return [f"  {report.period}: Total row matches the account rows"]


def default_folder(home: Path) -> Path | None:
    """The workspace's EJ-history folder, wherever it sits inside it."""
    if (home / HOME_FOLDER).is_dir():
        return home / HOME_FOLDER
    return next((p for p in sorted(home.rglob(HOME_FOLDER)) if p.is_dir()), None) if home.is_dir() else None
