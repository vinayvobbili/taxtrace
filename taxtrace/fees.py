"""What a brokerage charged, read off Edward Jones monthly statements.

Two figures, kept apart so nothing counts twice. "Fees and Charges" in the Value Summary has a "This Year" column:
on a December statement that is the year's total, so it is taken from December statements only. A "Reinvestment Fee
$1.25" line on a statement's activity is charged on its own, month by month: every one on the statements given is
summed, so that column covers only the months handed in.

A statement's file name carries what the text leaves out: the last four digits of the account, the month and the
year, as in XXXX4321-12_2025-edj-statement.pdf. Nothing but those digits, the year and amounts is ever kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

NAME = re.compile(r"(\d{4})-(\d{1,2})_(\d{4})-edj-statement", re.IGNORECASE)
AMOUNT = r"\(?-?\$?\s*\d[\d,]*\.\d{2}\)?"
FEES = re.compile(rf"Fees and Charges\s+({AMOUNT})\s+({AMOUNT})")  # This Period, then This Year
REINVESTMENT = re.compile(rf"Reinvestment Fee\s+({AMOUNT})", re.IGNORECASE)
HOME_FOLDER = "EJ-history"


@dataclass
class Statement:
    account: str
    year: int
    month: int
    this_year: Decimal | None  # "Fees and Charges", This Year column; None when the statement doesn't print it
    reinvestment: Decimal


@dataclass
class Year:
    annual: Decimal | None = None  # from the December statement; None: no December statement given
    reinvestment: Decimal = Decimal("0")
    months: set[int] = field(default_factory=set)


def money(printed: str) -> Decimal:
    """'1,234.56', '-1,234.56', '$1.25' or '(1.25)' as a positive amount: a fee is reported as what was paid."""
    return abs(Decimal(re.sub(r"[^\d.]", "", printed)))


def identify(name: str) -> tuple[str, int, int] | None:
    """(account's last four digits, year, month) from a statement's file name, or None when it isn't one."""
    m = NAME.search(name)
    if not m or not 1 <= int(m.group(2)) <= 12:
        return None
    return m.group(1), int(m.group(3)), int(m.group(2))


def read(name: str, pages: list[str]) -> Statement | None:
    """A statement's fees from its text, or None when the file name isn't a statement's."""
    who = identify(name)
    if who is None:
        return None
    joined = "\n".join(pages)
    fees = FEES.search(joined)
    return Statement(who[0], who[1], who[2], money(fees.group(2)) if fees else None,
                     sum((money(m) for m in REINVESTMENT.findall(joined)), Decimal("0")))


def total(statements: list[Statement]) -> dict[str, dict[int, Year]]:
    """Per account, per year. A statement given twice counts once; December's "This Year" is the year's total."""
    seen: dict[tuple[str, int, int], Statement] = {}
    for s in statements:
        seen[(s.account, s.year, s.month)] = s
    accounts: dict[str, dict[int, Year]] = {}
    for (account, year, month), s in sorted(seen.items()):
        y = accounts.setdefault(account, {}).setdefault(year, Year())
        y.months.add(month)
        y.reinvestment += s.reinvestment
        if month == 12 and s.this_year is not None:
            y.annual = s.this_year
    return accounts


def lines(accounts: dict[str, dict[int, Year]]) -> list[str]:
    """The table for each account, then the grand totals: only amounts, years and last four digits."""
    out: list[str] = []
    grand_annual = grand_reinvest = Decimal("0")
    for account in sorted(accounts):
        out += [f"account ending {account}",
                f"  {'year':<6}{'Fees and Charges':>18}{'Reinvestment fees':>20}  statements"]
        for year in sorted(accounts[account]):
            y = accounts[account][year]
            annual = f"{y.annual:,.2f}" if y.annual is not None else "no December"
            out.append(f"  {year:<6}{annual:>18}{y.reinvestment:>20,.2f}  {len(y.months)} of 12")
            grand_annual += y.annual or 0
            grand_reinvest += y.reinvestment
        for year in sorted(accounts[account]):
            if accounts[account][year].annual is None:
                out.append(f"  {year}: no December statement given, so no Fees and Charges for the year")
    out += [f"Fees and Charges (annual, December statements): {grand_annual:,.2f}",
            f"Reinvestment fees (sum of statements given): {grand_reinvest:,.2f}"]
    return out


def default_folder(home: Path) -> Path | None:
    """The workspace's EJ-history folder, wherever it sits inside it."""
    if (home / HOME_FOLDER).is_dir():
        return home / HOME_FOLDER
    return next((p for p in sorted(home.rglob(HOME_FOLDER)) if p.is_dir()), None) if home.is_dir() else None
