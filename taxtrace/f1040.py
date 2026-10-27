"""Form 1040 as filed: its income lines, and the lines next year's estimated tax and its penalty go by.

Each line is found by its number and words of its label, since a print's other rows end in numbers too (the
routing number's digits): the wages (line 1z), the taxable interest (2b), the ordinary dividends (3b), the capital
gain (7), the additional income from Schedule 1 (8: the rental, the K-1s), the total income (9), the adjustments
(10), the adjusted gross income (line 11, or 11a and 11b since 2025, when page 2 starts by
repeating it), the total tax (24), the tax withheld (25d), the year's estimated tax payments (26), the refundable
credits (32), the total payments (33), the overpayment (34), what of it was applied to next year's estimated tax
(36) and the estimated tax penalty (38). A line left empty is zero. A preparer's worksheet titled "Form 1040" that
"is not filed with the return" isn't the form.

The form's own arithmetic is checked: line 11 is line 9 less line 10, line 33 adds up lines 25d, 26 and 32, line
34 is line 33 less line 24 when that's more than zero, and line 36 is part of line 34.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from . import text
from .f8995 import AMOUNT, _amount
from .prior import CENT, Check

PAGE_1 = ("add lines 1a through 1h", "this is your total income")  # not NC's D-400, also an "Income Tax Return"
PAGE_2 = re.compile(r"^Form\s+1040\s+\((?:19|20)\d\d\).*\bPage\s*2\b")  # "Form 1040 (2025) <names> Page 2"
HEAD = 8  # lines: a preparer's page 1 can open with the SSN's box ahead of the form's title
LINE = re.compile(rf"(?<!\S)(?P<no>\d{{1,2}}[a-dz]?)\s+(?P<amount>{AMOUNT})\s*$")
# each line's number as printed, and words its label row holds
LINES = {
    "1z": ("add lines 1a through 1h",), "2b": ("taxable interest",), "3b": ("ordinary dividends",),
    "7": ("capital gain",), "7a": ("capital gain",), "8": ("additional income",), "9": ("your total income",),
    "10": ("adjustments to income",),
    "11": ("adjusted gross income",), "11a": ("adjusted gross income",), "11b": ("adjusted gross income",),
    "24": ("this is your total tax",), "25d": ("add lines 25a",), "26": ("estimated tax payments",),
    "32": ("total other payments",), "33": ("total payments",), "34": ("amount you overpaid",),
    "36": ("applied to your",), "38": ("estimated tax penalty",),
}


@dataclass
class Filed:
    lines: dict[str, Decimal] = field(default_factory=dict)  # by the line's number as printed: "11a", "24"
    pages: list[int] = field(default_factory=list)

    def line(self, n: str) -> Decimal:
        return self.lines.get(n, Decimal(0))

    @property
    def agi(self) -> Decimal | None:
        """The adjusted gross income: line 11 (11a since 2025); None when it wasn't read."""
        return next((self.lines[n] for n in ("11", "11a", "11b") if n in self.lines), None)


def is_page(page: str) -> bool:
    if "not filed" in " ".join(text.headings(page, HEAD)):
        return False
    flat = " ".join(page.lower().split())  # page 1's title can be drawn, not text: its own lines say what it is
    return any(PAGE_2.match(line) for line in text.headings(page, 3)) or all(p in flat for p in PAGE_1)


def read(pages: list[str]) -> tuple[Filed | None, list[Check]]:
    """The return's Form 1040, with the checks of its arithmetic; None when it has none."""
    filed = Filed()
    for n, page in enumerate(pages, 1):
        if not is_page(page):
            continue
        filed.pages.append(n)
        for row in page.splitlines():
            if (m := LINE.search(row)) and (words := LINES.get(m.group("no"))) and \
                    all(w in " ".join(row.lower().split()) for w in words):
                filed.lines.setdefault(m.group("no"), _amount(m.group("amount")))
    if not filed.pages:
        return None, []
    return filed, _checks(filed)


def _checks(f: Filed) -> list[Check]:
    page = f.pages[0]
    zero = Decimal(0)
    checks = [Check("Form 1040: the adjusted gross income (line 11) and the total tax (line 24) are on the page",
                    f.agi is not None and "24" in f.lines, page)]
    if "33" in f.lines:
        checks.append(Check("Form 1040: line 33 adds up lines 25d, 26 and 32",
                            abs(f.line("25d") + f.line("26") + f.line("32") - f.line("33")) <= CENT, page))
        checks.append(Check("Form 1040: line 34 is line 33 less line 24, zero at least",
                            abs(max(zero, f.line("33") - f.line("24")) - f.line("34")) <= CENT, page))
    if "9" in f.lines and f.agi is not None:
        checks.append(Check("Form 1040: line 11 is line 9 less line 10",
                            abs(f.line("9") - f.line("10") - f.agi) <= CENT, page))
    if "11a" in f.lines and "11b" in f.lines:
        checks.append(Check("Form 1040: line 11b is line 11a", abs(f.line("11a") - f.line("11b")) <= CENT, page))
    checks.append(Check("Form 1040: line 36 is part of line 34", f.line("36") <= f.line("34"), page))
    return checks
