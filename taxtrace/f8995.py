"""Form 8995 as filed: the simplified qualified business income deduction, each business's income, and the loss
carried to next year.

Line 1 lists each trade or business (a K-1's partnership, "K1P: <name>", or the rental, "Schedule E: <address>")
with its taxpayer identification number and its qualified business income or (loss); a return with more than five
continues them on a "Line 1, Continued" page. Lines 2 to 17 each end with the line's number and its amount, though
the amount can sit on the row under its label. A loss prints in parentheses, "( 12,345 )".

The form's own arithmetic is checked: line 2 adds up line 1, 4 is lines 2 and 3 (zero at least), 5 and 9 are 20%,
16 and 17 the losses carried on (zero at most), and so on. Next year's line 3 is this year's line 16.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from . import text
from .prior import CENT, Check, amount

FIRST = re.compile(r"\b8995\b(?!-A)\s+Qualified Business Income Deduction", re.IGNORECASE)
CONTINUED = re.compile(r"\b8995\b(?!-A)\s+\S+\s+Deduction,\s+Line 1\b", re.IGNORECASE)  # "Line 1, Continued"
AMOUNT = r"\(\s*[\d,]*\s*\)|-?[\d,]*\d"
LINE = re.compile(rf"(?<!\S)(?P<no>\d{{1,2}})\s+(?P<amount>{AMOUNT})\s*$")
# an EIN, or an SSN printed whole, with all but its last four digits masked ("XXX-XX-1234"), or all of them
TIN = r"[\dX*]{2}-[\dX*]{3}\d{4}|[\dX*]{3}-[\dX*]{2}-[\dX*]{4}"
BUSINESS = re.compile(rf"^\s*(?:(?:i|ii|iii|iv|v)\s+)?(?P<name>\S.*?)\s+\S*?(?P<tin>{TIN})\s+(?P<amount>{AMOUNT})\s*$")
TWENTY = Decimal("0.20")


@dataclass
class Business:
    name: str  # as line 1 (a) prints it: "K1P: <partnership>", "Schedule E: <address>"
    tin: str
    income: Decimal  # (c): qualified business income or (loss)
    page: int
    quote: str


@dataclass
class Filed:
    businesses: list[Business] = field(default_factory=list)
    lines: dict[int, Decimal] = field(default_factory=dict)  # 2 to 17
    pages: list[int] = field(default_factory=list)

    def line(self, n: int) -> Decimal:
        return self.lines.get(n, Decimal(0))


def _heads(page: str) -> str:
    return " ".join(text.headings(page, 3))


def is_page(page: str) -> bool:
    return bool(FIRST.search(_heads(page)) or CONTINUED.search(_heads(page)))


def _amount(printed: str) -> Decimal:
    return amount(printed.replace(" ", "")) if re.search(r"\d", printed) else Decimal(0)


def read(pages: list[str]) -> tuple[Filed | None, list[Check]]:
    """The return's Form 8995, with the checks of its arithmetic; None when it has none."""
    filed = Filed()
    for n, page in enumerate(pages, 1):
        if not is_page(page):
            continue
        filed.pages.append(n)
        first = bool(FIRST.search(_heads(page)))
        for row in page.splitlines():
            if m := BUSINESS.match(row):
                filed.businesses.append(Business(" ".join(m.group("name").split()), m.group("tin"),
                                                 _amount(m.group("amount")), n, " ".join(row.split())))
            elif first and (m := LINE.search(row)) and 2 <= int(m.group("no")) <= 17:
                filed.lines.setdefault(int(m.group("no")), _amount(m.group("amount")))
    if not filed.pages:
        return None, []
    return filed, _checks(filed)


def _twenty(value: Decimal) -> Decimal:
    return (value * TWENTY).quantize(CENT, ROUND_HALF_UP)


def _checks(f: Filed) -> list[Check]:
    page = f.pages[0]
    zero = Decimal(0)
    sums = [
        ("line 2 adds up line 1's businesses", sum((b.income for b in f.businesses), zero), 2),
        ("line 4 is lines 2 and 3, zero at least", max(zero, f.line(2) + f.line(3)), 4),
        ("line 5 is 20% of line 4", _twenty(f.line(4)), 5),
        ("line 8 is lines 6 and 7, zero at least", max(zero, f.line(6) + f.line(7)), 8),
        ("line 9 is 20% of line 8", _twenty(f.line(8)), 9),
        ("line 10 is lines 5 and 9", f.line(5) + f.line(9), 10),
        ("line 13 is line 11 less line 12, zero at least", max(zero, f.line(11) - f.line(12)), 13),
        ("line 14 is 20% of line 13", _twenty(f.line(13)), 14),
        ("line 15 is the smaller of lines 10 and 14", min(f.line(10), f.line(14)), 15),
        ("line 16 is lines 2 and 3, zero at most", min(zero, f.line(2) + f.line(3)), 16),
        ("line 17 is lines 6 and 7, zero at most", min(zero, f.line(6) + f.line(7)), 17),
    ]
    checks = [Check(f"Form 8995: {what}", abs(expected - f.line(n)) <= CENT, page) for what, expected, n in sums]
    missing = [n for n in (2, 4, 10, 15, 16) if n not in f.lines]
    if missing:
        checks.append(Check(f"Form 8995: lines {', '.join(map(str, missing))} are on the page", False, page))
    return checks


def link(earlier: Filed, earlier_year: int, later: Filed, later_year: int) -> list[Check]:
    """A year's losses carried on (lines 16 and 17) against the next year's carried in (lines 3 and 7)."""
    if later_year != earlier_year + 1:
        return []
    return [Check(f"Form 8995: {earlier_year}'s line {a} is {later_year}'s line {b}",
                  abs(earlier.line(a) - later.line(b)) <= CENT, later.pages[0]) for a, b in ((16, 3), (17, 7))]
