"""Schedule B (Form 1116): foreign tax carried over from earlier years, by the year it arose.

Foreign tax the Form 1116 limit keeps from being credited carries back a year and forward ten, separately for each
category of income (passive, general...) and again for the alternative minimum tax. Schedule B (Rev. 12-2022) tracks
it in columns, one per year: page 1's (i) to (vi) are the 10th to 5th preceding years and (vii) their subtotal; page
2's (viii) is that subtotal again, (ix) to (xii) the 4th to 1st preceding years, (xiii) the current year and (xiv)
the total. Its lines: 1 carryover from the prior year, 2 adjustments (a to g), 3 the adjusted carryover (1 and 2), 4
used this year, 5 expired, 6 generated this year, 7 carried back (4, 5 and 7 as negative numbers), and 8, what goes
to the following year (3 through 7). Next year's line 1 is this year's line 8.

Amounts are read by position (`text.words`): each goes to the column whose heading starts left of its end, and to
the line whose number came last above it. The AMT copy's page 1 says "For 1116 AMT"; its page 2 says nothing, so each
page 2 goes with the nearest page 1 (the one before it, on a tie), and the subtotals carried between them are checked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal

from . import text
from .prior import CENT, Check, Question, _rows, amount

FIRST = re.compile(r"SCHEDULE B\b.*Foreign Tax Carryover", re.IGNORECASE)
SECOND = re.compile(r"Schedule B \(Form 1116\).*Page 2", re.IGNORECASE)
AMT = re.compile(r"\bFor\s+1116\s+AMT\b")
VALUE = re.compile(r"^(?:-?[\d,]*\d(?:\.\d*)?|-?\([\d,]*\d(?:\.\d*)?\))$")  # never "1116)" from the footer
ROMANS = ("i", "ii", "iii", "iv", "v", "vi", "vii", "viii", "ix", "x", "xi", "xii", "xiii", "xiv")
PAGE_1, PAGE_2 = ROMANS[:7], ROMANS[7:]
CATEGORIES = {"a": "reserved", "b": "foreign branch", "c": "passive", "d": "general", "e": "section 901(j)",
              "f": "re-sourced by treaty", "g": "lump-sum"}
LINES = range(1, 9)


@dataclass
class Schedule:
    category: str  # "passive", or "" when no box is checked
    amt: bool  # the alternative minimum tax copy
    lines: dict[int, dict[int, Decimal]]  # line: {the year the tax arose: amount}
    totals: dict[int, Decimal]  # line: column (xiv)
    pages: list[int] = field(default_factory=list)

    @property
    def following(self) -> dict[int, Decimal]:
        """Line 8: what carries to the following year, by the year each tax arose."""
        return {y: v for y, v in self.lines.get(8, {}).items() if v}

    def name(self) -> str:
        return f"Schedule B (Form 1116), {self.category or 'category unknown'}" + (" AMT" if self.amt else "")


def is_page(page: str) -> bool:
    """Whether a page is either page of Schedule B (Form 1116), whose amounts are read by position."""
    return _which(page) is not None


def _which(page: str) -> int | None:
    """1 or 2 for Schedule B's pages: page 2 names itself in its first lines, page 1 in its very first."""
    heads = text.headings(page, 3)
    if SECOND.search(" ".join(heads)):
        return 2
    return 1 if heads and FIRST.search(heads[0]) else None


def read(year: int | None, pages: list[str], words: dict[int, list[dict]]) -> tuple[
        list[Schedule], list[Check], list[Question]]:
    """Each category's Schedule B in a return for `year`, with the checks of its sums and what couldn't be read."""
    firsts, seconds = [], []
    for n, page in enumerate(pages, 1):
        if n in words and (which := _which(page)):
            (firsts if which == 1 else seconds).append(n)
    schedules: list[Schedule] = []
    checks: list[Check] = []
    questions: list[Question] = []
    if year is None:
        if firsts or seconds:
            questions.append(Question("Which tax year is this return? Schedule B (Form 1116)'s columns are years "
                                      "counted back from it.", (firsts or seconds)[0], ""))
        return schedules, checks, questions
    pairs = dict.fromkeys(firsts)
    for n in seconds:
        free = [f for f in firsts if pairs[f] is None]
        if not free:
            questions.append(Question("Schedule B (Form 1116) has a page 2 without its page 1: read it by hand.", n,
                                      ""))
            continue
        pairs[min(free, key=lambda f: (abs(f - n), f > n))] = n
    for first, second in pairs.items():
        schedule = Schedule(_category(words[first]), bool(AMT.search(pages[first - 1])), {}, {},
                            [first] + ([second] if second else []))
        if not schedule.category:
            questions.append(Question("Schedule B (Form 1116): which category of income is this? No box is "
                                      "checked.", first, ""))
        cells = _cells(words[first], PAGE_1)
        if second:
            for line, row in _cells(words[second], PAGE_2).items():
                cells.setdefault(line, {}).update(row)
        _sort(schedule, cells, year)
        checks.extend(_checks(schedule, cells))
        schedules.append(schedule)
    return schedules, checks, questions


def _category(words: list[dict]) -> str:
    """The category whose box holds the page's X: the letter left of it on the nearest row."""
    for x in (w for w in words if w["text"] == "X"):
        letters = [w for w in words if w["text"] in CATEGORIES and abs(w["top"] - x["top"]) < 10
                   and w["x0"] < x["x0"]]
        if letters:
            nearest = min(abs(w["top"] - x["top"]) for w in letters)
            row = [w for w in letters if abs(w["top"] - x["top"]) <= nearest + 2]
            return CATEGORIES[max(row, key=lambda w: w["x0"])["text"]]
    return ""


def _cells(words: list[dict], romans: tuple[str, ...]) -> dict[int, dict[str, Decimal]]:
    """{line: {column: amount}} from one page; line 2's adjustments (a to g) added up."""
    heads: dict[str, dict] = {}
    for w in sorted(words, key=lambda w: w["top"]):
        if (m := re.match(r"^\(([ivx]+)\)$", w["text"])) and m.group(1) in romans:
            heads.setdefault(m.group(1), w)
    if not heads:
        return {}
    below = max(h["top"] for h in heads.values()) + 5
    left = min(h["x0"] for h in heads.values()) - 10
    columns = sorted(heads.items(), key=lambda t: t[1]["x0"])
    cells: dict[int, dict[str, Decimal]] = {}
    line = 0
    for row in _rows([w for w in words if w["top"] > below]):
        if any(w["text"] == "Paperwork" for w in row):
            break
        if row[0]["x0"] < 55 and row[0]["text"].isdigit() and int(row[0]["text"]) in LINES:
            line = int(row[0]["text"])
        for w in row:
            if line and w["x0"] > left and VALUE.match(w["text"]):
                column = next((c for c, h in reversed(columns) if h["x0"] < w["x1"] - 2), columns[0][0])
                cells.setdefault(line, {})
                cells[line][column] = cells[line].get(column, Decimal(0)) + amount(w["text"])
    return cells


def _year_of(column: str, year: int) -> int | None:
    """The year a column's tax arose: (i) is the 10th year before, (xiii) this one; subtotals and totals have none."""
    if column in ROMANS[:6]:
        return year - 10 + ROMANS.index(column)
    if column in ("ix", "x", "xi", "xii", "xiii"):
        return year - 4 + ROMANS.index(column) - ROMANS.index("ix")
    return None


def _sort(schedule: Schedule, cells: dict[int, dict[str, Decimal]], year: int) -> None:
    for line, row in cells.items():
        for column, value in row.items():
            if (arose := _year_of(column, year)) is not None:
                schedule.lines.setdefault(line, {})[arose] = value
            elif column == "xiv":
                schedule.totals[line] = value


def _checks(schedule: Schedule, cells: dict[int, dict[str, Decimal]]) -> list[Check]:
    page = schedule.pages[-1]
    checks = []

    def get(line: int, column: str) -> Decimal:
        return cells.get(line, {}).get(column, Decimal(0))

    used = sorted({c for row in cells.values() for c in row}, key=ROMANS.index)
    for column in used:
        checks.append(Check(f"{schedule.name()}, column ({column}): line 3 is lines 1 and 2 combined",
                            abs(get(1, column) + get(2, column) - get(3, column)) <= CENT, page))
        checks.append(Check(f"{schedule.name()}, column ({column}): line 8 is lines 3 through 7 combined",
                            abs(sum((get(n, column) for n in range(3, 8)), Decimal(0)) - get(8, column)) <= CENT,
                            page))
    for line in cells:
        first = sum((get(line, c) for c in ROMANS[:6]), Decimal(0))
        if first or get(line, "vii") or get(line, "viii"):
            checks.append(Check(f"{schedule.name()}, line {line}: page 1's subtotal (vii) adds up its columns and "
                                "is page 2's (viii)", abs(first - get(line, "vii")) <= CENT
                                and abs(get(line, "vii") - get(line, "viii")) <= CENT, page))
        rest = sum((get(line, c) for c in ("viii", "ix", "x", "xi", "xii", "xiii")), Decimal(0))
        if rest or get(line, "xiv"):
            checks.append(Check(f"{schedule.name()}, line {line}: the total (xiv) adds up its columns",
                                abs(rest - get(line, "xiv")) <= CENT * 6, page))
    if get(8, "i"):  # the tenth year back is its last: nothing of it goes on
        checks.append(Check(f"{schedule.name()}: the tenth preceding year's carryover expires, not carried on",
                            False, schedule.pages[0]))
    return checks


def link(earlier: list[Schedule], earlier_year: int, later: list[Schedule], later_year: int) -> list[Check]:
    """A year's line 8 against the next year's line 1, by category and year of origin."""
    if later_year != earlier_year + 1:
        return []
    checks = []
    by_kind = {(s.category, s.amt): s for s in later}
    for s in earlier:
        then = by_kind.get((s.category, s.amt))
        carried = s.following
        if then is None:
            if carried:
                checks.append(Check(f"{s.name()}: {earlier_year}'s carryover is on {later_year}'s Schedule B",
                                    False, s.pages[0]))
            continue
        brought = {y: v for y, v in then.lines.get(1, {}).items() if v}
        checks.append(Check(f"{s.name()}: {earlier_year}'s carryover to the following year is {later_year}'s "
                            "carryover from the prior year", carried.keys() == brought.keys()
                            and all(abs(carried[y] - brought[y]) <= CENT for y in carried), then.pages[0]))
    return checks
