"""Schedules 1, D and E, Form 4797 and North Carolina's D-400 as filed: the lines a rehearsal compares a build with.

These forms print a numbered line's amount at the end of its row. Schedule D's sales rows have no number on the
row with their amounts, so they go by their words ("Box D or Box J"), and the last amount is column (h), the gain.
A preparer's D-400 prints each amount on the row above its label, and an official print can have it on the label's row.
A line left empty is zero.

Each form's own arithmetic is checked, and the forms against Form 1040: a misread line shows up as a failed check.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from . import text
from .f8995 import AMOUNT, _amount
from .prior import Check

LINE = re.compile(rf"(?<!\S)(?P<no>\d{{1,2}}[a-z]?)\s+(?P<amount>{AMOUNT})\s*$")
WHOLE = re.compile(rf"^(?:{AMOUNT})$")
LABEL = re.compile(rf"(?<!\S)(?P<no>\d{{1,2}}[a-e]?)\.(?:\s+(?P<amount>{AMOUNT}))?\s*$")
TITLE_1 = re.compile(r"^SCHEDULE\s+1\b.*Additional Income|^Schedule\s+1\s+\(Form\s+1040\)", re.I)
TITLE_D = re.compile(r"^SCHEDULE\s+D\b.*Capital Gains|^Schedule\s+D\s+\(Form\s+1040\)", re.I)
TITLE_E = re.compile(r"^Supplemental Income and Loss|^Schedule\s+E\s+\(Form\s+1040\)", re.I)
TITLE_4797 = re.compile(r"^4797\s+Sales of Business Property|^Form\s+4797\s+\(", re.I)
E_LINES = ("23a", "23b", "23c", "23d", "23e", "24", "25", "26", "30", "31", "32", "37", "39", "40", "41")
F4797_LINES = ("2", "6", "7", "20", "21", "22", "23", "24", "32")
TITLE_1116 = re.compile(r"^Form\s+1116\s+\(.*Page\s*2", re.I)
F1116_WORDS = ("foreign tax credit", "use a separate form 1116")
AMT_COPY = "min tax purposes only"  # the preparer's alternative minimum tax copy of the form, which isn't filed
# by page, since page 1's Part II has rows of dates that end like a line number and an amount
F1116_PAGE_1 = ("1a", "7")
F1116_PAGE_2 = ("9", "10", "11", "12", "13", "14", "15", "16", "17", "18", "20", "21", "23", "24", "32", "33", "34",
                "35")
LINE_1116 = re.compile(rf"(?<![\d,.])(?P<no>\d{{1,2}}[a-z]?)\s+(?P<amount>{AMOUNT})\s*$")  # also "y15 18,000"
DATED_TAX = re.compile(rf"^\s*[A-C]\s+\d\d?-\d\d?-\d{{4}}\b.*?(?P<amount>{AMOUNT})\s*$")  # Part II's row, column (u)
# by their words, since a print can garble these numbers and line 3e has an amount in each column
F1116_LABELS = {no: re.compile(rf"{words}.*?(?P<amount>{AMOUNT})\s*$", re.I) for no, words in (
    ("3d", "gross foreign source income"), ("3e", "gross income from all sources"), ("3g", "multiply line 3c by"))}
D400_WORDS = ("federal adjusted gross income", "n.c. taxable income", "n.c. income tax")
SALES_ROWS = {  # Schedule D's rows with columns of amounts: words on the row, and the line's number
    "go to line 1b": "1a", "box a or box g": "1b", "box b or box h": "2", "box c or box i": "3",
    "go to line 8b": "8a", "box d or box j": "8b", "box e or box k": "9", "box f or box l": "10",
}
D_LINES = ("4", "5", "6", "7", "11", "12", "13", "14", "15", "16", "18", "19", "21")
SHORT = ("1a", "1b", "2", "3", "4", "5", "6")
LONG = ("8a", "8b", "9", "10", "11", "12", "13", "14")
INCOME = ("1", "2a", "3", "4", "5", "6", "7", "9")
ADJUSTMENTS = (*map(str, range(11, 24)), "25")
OTHER_INCOME = tuple(f"8{c}" for c in "abcdefghijklmnopqrstuvz")
PAYMENTS = ("20a", "20b", "21a", "21b", "21c", "21d", "22")
HEAD = 3  # lines: where a form's title is
SLACK = Decimal(1)  # whole-dollar forms round each line


@dataclass
class Schedule:
    lines: dict[str, Decimal] = field(default_factory=dict)  # by the line's number as printed: "8b", "10b"
    pages: list[int] = field(default_factory=list)

    def line(self, n: str) -> Decimal:
        return self.lines.get(n, Decimal(0))

    def total(self, lines: tuple[str, ...]) -> Decimal:
        return sum((self.line(n) for n in lines), Decimal(0))


def _titled(page: str, title: re.Pattern) -> bool:
    return any(title.match(line) for line in text.headings(page, HEAD))


def is_d400(page: str) -> bool:
    flat = " ".join(page.lower().split())
    return "d-400" in " ".join(text.headings(page, HEAD)).lower() and all(w in flat for w in D400_WORDS)


def _schedule_1(pages: list[str]) -> Schedule | None:
    found = Schedule()
    for n, page in enumerate(pages, 1):
        if _titled(page, TITLE_1):
            found.pages.append(n)
            for row in page.splitlines():
                if m := LINE.search(row):
                    found.lines.setdefault(m.group("no"), _amount(m.group("amount")))
    return found if found.pages else None


def _numbered(pages: list[str], title: re.Pattern, lines: tuple[str, ...]) -> Schedule | None:
    """The form's pages under that title, and those of its numbered lines with an amount at the end of their row."""
    found = Schedule()
    for n, page in enumerate(pages, 1):
        if _titled(page, title):
            found.pages.append(n)
            for row in page.splitlines():
                if (m := LINE.search(row)) and m.group("no") in lines:
                    found.lines.setdefault(m.group("no"), _amount(m.group("amount")))
    return found if found.pages else None


def _form_1116(pages: list[str]) -> Schedule | None:
    """The first Form 1116 filed: its AMT copy isn't, and a second category's would need its own reading."""
    found = Schedule()
    for n, page in enumerate(pages, 1):
        flat = " ".join(page.lower().split())
        if AMT_COPY in flat or not (_titled(page, TITLE_1116) or all(w in flat for w in F1116_WORDS)):
            continue
        found.pages.append(n)
        wanted = F1116_PAGE_2 if _titled(page, TITLE_1116) else F1116_PAGE_1
        for row in page.splitlines():
            for no, label in F1116_LABELS.items():
                if wanted is F1116_PAGE_1 and (m := label.search(row)):
                    found.lines.setdefault(no, _amount(m.group("amount")))
            if wanted is F1116_PAGE_1 and (m := DATED_TAX.search(row)):
                found.lines.setdefault("dated_tax", _amount(m.group("amount")))
            if (m := LINE_1116.search(row)) and m.group("no") in wanted:
                found.lines.setdefault(m.group("no"), _amount(m.group("amount")))
    return found if found.pages else None


def _schedule_d(pages: list[str]) -> Schedule | None:
    found = Schedule()
    for n, page in enumerate(pages, 1):
        if not _titled(page, TITLE_D):
            continue
        found.pages.append(n)
        for row in page.splitlines():
            flat = " ".join(row.lower().split())
            if sales := next((no for words, no in SALES_ROWS.items() if words in flat), None):
                last = flat.split()[-1]
                if WHOLE.match(last):
                    found.lines.setdefault(sales, _amount(last))
            elif (m := LINE.search(row)) and m.group("no") in D_LINES:
                found.lines.setdefault(m.group("no"), _amount(m.group("amount")))
    return found if found.pages else None


def _above(rows: list[str], at: int) -> str | None:
    """The amount on the row above a label: the watermark's stray letters can share it, but not other words."""
    above = next((r.split() for r in reversed(rows[:at]) if r.strip()), [])
    amounts = [t for t in above if WHOLE.match(t)]
    return amounts[0] if len(amounts) == 1 and all(len(t) == 1 or t in amounts for t in above) else None


def _d400(pages: list[str]) -> Schedule | None:
    found = Schedule()
    for n, page in enumerate(pages, 1):
        if not is_d400(page):
            continue
        found.pages.append(n)
        rows = page.splitlines()
        for at, row in enumerate(rows):
            if m := LABEL.search(row):
                printed = m.group("amount") or _above(rows, at)
                if printed is not None:
                    found.lines.setdefault(m.group("no"), _amount(printed))
    return found if found.pages else None


def _near(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= SLACK


def _checks_1(s: Schedule, f1040) -> list[Check]:
    page = s.pages[0]
    checks = [Check("Schedule 1: line 9 adds up lines 8a through 8z", _near(s.total(OTHER_INCOME), s.line("9")), page),
              Check("Schedule 1: line 10 adds up lines 1 through 7 and 9", _near(s.total(INCOME), s.line("10")), page),
              Check("Schedule 1: line 26 adds up lines 11 through 23 and 25",
                    _near(s.total(ADJUSTMENTS), s.line("26")), page)]
    if f1040 is not None:
        checks.append(Check("Schedule 1: line 10 is Form 1040's line 8", _near(s.line("10"), f1040.line("8")), page))
        checks.append(Check("Schedule 1: line 26 is Form 1040's line 10", _near(s.line("26"), f1040.line("10")), page))
    return checks


def _checks_d(s: Schedule, f1040) -> list[Check]:
    page = s.pages[0]
    checks = [Check("Schedule D: line 7 adds up lines 1a through 6", _near(s.total(SHORT), s.line("7")), page),
              Check("Schedule D: line 15 adds up lines 8a through 14", _near(s.total(LONG), s.line("15")), page),
              Check("Schedule D: line 16 is lines 7 and 15", _near(s.line("7") + s.line("15"), s.line("16")), page)]
    if f1040 is not None:
        carried = s.line("21") if s.line("16") < 0 else s.line("16")
        seven = f1040.lines.get("7a", f1040.line("7"))
        checks.append(Check("Schedule D: what it carries is Form 1040's line 7", _near(carried, seven), page))
    return checks


def _checks_e(s: Schedule, one: Schedule | None) -> list[Check]:
    page = s.pages[0]
    checks = [Check("Schedule E: line 26 is lines 24 and 25", _near(s.line("24") + s.line("25"), s.line("26")), page),
              Check("Schedule E: line 32 is lines 30 and 31", _near(s.line("30") + s.line("31"), s.line("32")), page),
              Check("Schedule E: line 41 adds up lines 26, 32, 37, 39 and 40",
                    _near(s.total(("26", "32", "37", "39", "40")), s.line("41")), page)]
    if one is not None:
        checks.append(Check("Schedule E: line 41 is Schedule 1's line 5", _near(s.line("41"), one.line("5")), page))
    return checks


def _checks_4797(s: Schedule, capital: Schedule | None) -> list[Check]:
    page = s.pages[0]
    adjusted, gain = s.line("21") - s.line("22"), s.line("20") - s.line("23")
    checks = [Check("Form 4797: line 23 is line 21 less line 22", _near(adjusted, s.line("23")), page),
              Check("Form 4797: line 24 is line 20 less line 23", _near(gain, s.line("24")), page),
              Check("Form 4797: line 6 is line 32", _near(s.line("6"), s.line("32")), page)]
    if capital is not None:
        checks.append(Check("Form 4797: line 7 is Schedule D's line 11", _near(s.line("7"), capital.line("11")), page))
    return checks


def _checks_1116(s: Schedule, f1040) -> list[Check]:
    page = s.pages[0]
    credit = s.line("33") - s.line("34")
    checks = [Check("Form 1116: line 14 adds up lines 11, 12 and 13",
                    _near(s.total(("11", "12", "13")), s.line("14")), page),
              Check("Form 1116: line 17 is lines 15 and 16", _near(s.line("15") + s.line("16"), s.line("17")), page),
              Check("Form 1116: line 35 is line 33 less line 34", _near(credit, s.line("35")), page)]
    if f1040 is not None:
        checks.append(Check("Form 1116: line 20 is Form 1040's line 16", _near(s.line("20"), f1040.line("16")), page))
        checks.append(Check("Form 1116: line 35 is within Form 1040's line 20",
                            s.line("35") <= f1040.line("20") + SLACK, page))
        if f1040.agi is not None and "14" in f1040.lines:
            # lower when the worksheet for line 18 takes out the income taxed at lower rates
            checks.append(Check("Form 1116: line 18 is at most Form 1040's income less line 14",
                                s.line("18") <= f1040.agi - f1040.line("14") + SLACK, page))
    return checks


def _checks_d400(s: Schedule, f1040) -> list[Check]:
    page = s.pages[0]
    checks = [
        Check("D-400: line 8 is lines 6 and 7", _near(s.line("6") + s.line("7"), s.line("8")), page),
        Check("D-400: line 12a adds up lines 9, 10b and 11",
              _near(s.line("9") + s.line("10b") + s.line("11"), s.line("12a")), page),
        Check("D-400: line 12b is line 8 less line 12a", _near(s.line("8") - s.line("12a"), s.line("12b")), page),
        Check("D-400: line 17 is line 15 less line 16", _near(s.line("15") - s.line("16"), s.line("17")), page),
        Check("D-400: line 19 is lines 17 and 18", _near(s.line("17") + s.line("18"), s.line("19")), page),
        Check("D-400: line 23 adds up lines 20a through 22", _near(s.total(PAYMENTS), s.line("23")), page),
        Check("D-400: line 25 is line 23 less line 24", _near(s.line("23") - s.line("24"), s.line("25")), page),
    ]
    if f1040 is not None and f1040.agi is not None:
        checks.append(Check("D-400: line 6 is Form 1040's adjusted gross income", _near(s.line("6"), f1040.agi), page))
    return checks


@dataclass
class Forms:
    schedule_1: Schedule | None = None
    schedule_d: Schedule | None = None
    schedule_e: Schedule | None = None
    form_4797: Schedule | None = None
    d400: Schedule | None = None
    form_1116: Schedule | None = None
    checks: list[Check] = field(default_factory=list)


def read(pages: list[str], f1040=None) -> Forms:
    """A return's forms, each None when it has none, with the checks of their arithmetic."""
    f = Forms(_schedule_1(pages), _schedule_d(pages), _numbered(pages, TITLE_E, E_LINES),
              _numbered(pages, TITLE_4797, F4797_LINES), _d400(pages), _form_1116(pages))
    if f.schedule_1:
        f.checks += _checks_1(f.schedule_1, f1040)
    if f.schedule_d:
        f.checks += _checks_d(f.schedule_d, f1040)
    if f.schedule_e:
        f.checks += _checks_e(f.schedule_e, f.schedule_1)
    if f.form_4797:
        f.checks += _checks_4797(f.form_4797, f.schedule_d)
    if f.d400:
        f.checks += _checks_d400(f.d400, f1040)
    if f.form_1116:
        f.checks += _checks_1116(f.form_1116, f1040)
    return f
