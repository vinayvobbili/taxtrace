"""Form D-403 NC K-1: a partner's share of a partnership's North Carolina income, adjustments and credits.

Like the federal K-1 (`k1`), it's a printed form read by where things sit (`text.words`). Each of its eleven lines
has its amount in the Amount column, printed just above the line's label (above its last row, where a label takes
two), so an amount goes to the line whose label row is just under it. The partnership's FEIN, the partner's number
(only its last four digits are kept) and the three Yes/No questions are read by their labels; a question's mark sits
just right of its answer.

Line 1 is already in federal adjusted gross income, so it's checked against the same partnership's federal K-1;
lines 2 to 5 go on the D-400 (Schedule S and the credits form); lines 6 to 9 are for nonresidents and 10 and 11 for
taxed partnerships only, so either is a failed check where the form's own answers say it doesn't apply.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from .k1 import MARKS, ROW, Value, _same_row, _value
from .prior import CENT, Check, Question, _number

LINES = {
    1: "Income (loss)", 2: "Additions to income (loss)", 3: "Deductions from income (loss)", 4: "Tax credits",
    5: "Tax withheld from compensation paid for services performed in N.C.",
    6: "Line 1 attributable to North Carolina", 7: "Line 2 attributable to North Carolina",
    8: "Line 3 attributable to North Carolina", 9: "Net tax paid by the partnership",
    10: "Loss attributable to North Carolina", 11: "Income attributable to North Carolina",
}
GOES = {  # where an individual's D-400 takes each line, as the form prints it
    1: "already in federal adjusted gross income", 2: "Form D-400 Schedule S, Part A",
    3: "Form D-400 Schedule S, Part B", 4: "Form D-400TC", 5: "Form D-400, line 20 (N.C. residents only)",
    6: "Form D-400 Schedule PN (nonresidents)", 7: "Form D-400 Schedule PN-1 (nonresidents)",
    8: "Form D-400 Schedule PN-1 (nonresidents)", 9: "Form D-400, line 21c", 10: "Form D-400 Schedule S, Part A",
    11: "Form D-400 Schedule S, Part B",
}
NONRESIDENT, TAXED = (6, 7, 8, 9), (10, 11)
LINE = re.compile(r"^(\d{1,2})\.$")
FEIN = re.compile(r"^(\d{2})-?(\d{7})$")
NUMBER9 = re.compile(r"^(?:\d{3}-?\d{2}-?|[X*]{3}-[X*]{2}-)(\d{4})$")  # the partner's SSN, of which 4 digits are kept
FORM_YEAR = re.compile(r"^(?:19|20)\d\d$")
UNDER = 9.0  # points: how far below its amount a line's label row sits
# the form's line 1: "From federal Schedule K-1 for Form 1065. Add Part III, Lines 1 through 11" (6b and 6c are
# part of 6a, and 9b and 9c of 9a, so they aren't added again); deductions (12, 13) aren't taken off
INCOME = ("1", "2", "3", "4c", "5", "6a", "7", "8", "9a", "10", "11")


@dataclass
class NCK1:
    file: str
    page: int
    year: int | None = None
    ein: str = ""  # as the federal K-1 prints it, "12-3456789"
    partnership: str = ""
    partner: str = ""  # the last four digits of the partner's identifying number
    taxed_partnership: bool | None = None  # None: neither answer marked
    resident: bool | None = None  # the partner, on the last day of the partnership's year
    disregarded_entity: bool | None = None
    lines: dict[int, Value] = field(default_factory=dict)
    copy_of: int | None = None
    checks: list[Check] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    def check(self, what: str, ok: bool, quote: str = "") -> None:
        self.checks.append(Check(what, ok, self.page, quote))

    def ask(self, question: str, quote: str = "") -> None:
        self.questions.append(Question(question, self.page, quote))

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def amount(self, line: int) -> Decimal:
        return self.lines[line].amount if line in self.lines else Decimal(0)

    def values(self) -> list[Value]:
        """Every value read off the form, for `k1.verify`."""
        return list(self.lines.values())

    def to_json(self) -> dict:
        out = asdict(self)
        out["form"] = "D-403"
        out["lines"] = {str(n): {**{k: str(v) if isinstance(v, Decimal) else v for k, v in value.items()},
                                 "label": LINES[n], "goes": GOES[n]} for n, value in out["lines"].items()}
        return out


def is_form(page_text: str) -> bool:
    """Whether a page's text (`text.pages`) could be a D-403 NC K-1."""
    return "NC K-1" in page_text and "D-403" in page_text and "Partner's Share of" in page_text


def read(name: str, pages: dict[int, list[dict]]) -> list[NCK1]:
    """The NC K-1s among a document's pages, given each page's words by page number; a repeat counts once."""
    found = [nc for n, words in sorted(pages.items()) if (nc := form(name, n, words)) is not None]
    for n, later in enumerate(found):
        if first := next((f for f in found[:n] if f.copy_of is None and _same(f, later)), None):
            later.copy_of = first.page
            later.questions.clear()
    return found


def _same(a: NCK1, b: NCK1) -> bool:
    return (a.ein, a.partner) == (b.ein, b.partner) and \
        {n: v.quote for n, v in a.lines.items()} == {n: v.quote for n, v in b.lines.items()}


def form(name: str, page: int, words: list[dict]) -> NCK1 | None:
    """One NC K-1, or None if the page has no Amount column with numbered lines beside it."""
    head = next((w for w in sorted(words, key=lambda w: (w["top"], w["x0"])) if w["text"] == "Amount"), None)
    labels = sorted(((int(m.group(1)), w) for w in words if (m := LINE.match(w["text"])) and w["x0"] < 60
                     and head is not None and w["top"] > head["top"]), key=lambda t: t[1]["top"])
    if head is None or not labels:
        return None
    nc = NCK1(file=name, page=page)
    _header(nc, words)
    left = sorted({round(w["top"], 1) for w in words if w["x1"] < head["x0"] - 10 and w["top"] > head["top"]})
    for w in words:
        if not (_number(w["text"]) and w["x0"] > head["x0"] - 40 and w["x1"] < head["x1"] + 30
                and w["top"] > head["top"] + 2):
            continue
        row = next((t for t in left if w["top"] < t <= w["top"] + UNDER), None)
        line = next((n for n, label in reversed(labels) if label["top"] <= row + 1), None) if row else None
        if line is None:
            nc.ask("an amount in the Amount column with no line's label under it", w["text"])
        elif line in nc.lines:
            nc.ask(f"line {line}: two amounts", f"{nc.lines[line].quote} and {w['text']}")
        else:
            nc.lines[line] = _value(w, page)
    _checks(nc)
    return nc


def _header(nc: NCK1, words: list[dict]) -> None:
    rows = sorted(words, key=lambda w: (w["top"], w["x0"]))
    if share := next((w for w in rows if w["text"] == "Share"), None):
        if year := next((w for w in rows if FORM_YEAR.match(w["text"]) and _same_row(w, share, 2)), None):
            nc.year = int(year["text"])
    if label := next((w for w in rows if w["text"] == "Employer"), None):
        below = [w for w in rows if label["top"] < w["top"] <= label["top"] + 15]
        if ein := next((m for w in below if (m := FEIN.match(w["text"])) and w["x0"] < 200), None):
            nc.ein = f"{ein.group(1)}-{ein.group(2)}"
            row = next(w for w in below if FEIN.match(w["text"]))
            nc.partnership = " ".join(w["text"] for w in below if _same_row(w, row, 1) and w["x0"] > 200)
    if label := next((w for w in rows if w["text"] == "Identifying"), None):
        below = [w for w in rows if label["top"] < w["top"] <= label["top"] + 15 and w["x0"] < 200]
        if number := next((m for w in below if (m := NUMBER9.match(w["text"]))), None):
            nc.partner = number.group(1)
    for attr, word in (("taxed_partnership", "Taxed"), ("resident", "resident"), ("disregarded_entity", "disregarded")):
        if (w := next((o for o in rows if o["text"] == word), None)) is not None:
            setattr(nc, attr, _answer(rows, w))


def _answer(rows: list[dict], question: dict) -> bool | None:
    """Yes, No, or None: the mark just right of the answer it's for, on or just above the answers' row."""
    # the answers sit on the question's own row (a little above its text) or a row or two under it
    yes = next((w for w in rows if w["text"] == "Yes" and w["top"] >= question["top"] - ROW and
                any(o["text"] == "No" and _same_row(o, w, 1) for o in rows)), None)
    if yes is None or yes["top"] > question["top"] + 30:
        return None
    options = [o for o in rows if o["text"] in ("Yes", "No") and _same_row(o, yes, 1)]
    for mark in (w for w in rows if w["text"] in MARKS and yes["top"] - 8 <= w["top"] <= yes["top"] + ROW):
        if left := max((o for o in options if o["x0"] < mark["x0"]), key=lambda o: o["x0"], default=None):
            return left["text"] == "Yes"
    return None


def _checks(nc: NCK1) -> None:
    for lines, attr, answer, who in ((NONRESIDENT, "resident", True, "nonresident partners"),
                                     (TAXED, "taxed_partnership", False, "taxed partnerships")):
        if getattr(nc, attr) is answer:
            used = [n for n in lines if nc.amount(n)]
            nc.check(f"lines {lines[0]} to {lines[-1]} are for {who} only, and the form says this K-1 isn't one",
                     not used, ", ".join(nc.lines[n].quote for n in used))
    if nc.amount(2) or nc.amount(3):
        nc.ask("lines 2 and 3: each addition or deduction goes on Schedule S on the line for its kind (bonus "
               "depreciation, Section 179 expense, ...); the form doesn't say which, so the partnership's NC K-1 "
               "Supplemental Schedule or last year's Schedule S does")
    if nc.amount(4):
        nc.ask("line 4: which credit it is (the partnership's NC K-1 Supplemental Schedule names it) decides where "
               "it goes on Form D-400TC", nc.lines[4].quote)


def tie(nc: NCK1, federal: list[tuple[str, Decimal]]) -> None:
    """Line 1 against the same partnership's federal K-1 (its boxes and amounts): Part III's lines 1 to 11."""
    total = sum((a for box, a in federal if box in INCOME), Decimal(0))
    if not any(box == "4c" for box, _ in federal):  # a K-1 without a total gives 4a and 4b
        total += sum((a for box, a in federal if box in ("4a", "4b")), Decimal(0))
    nc.check("line 1 is the federal K-1's Part III lines 1 to 11 added up",
             abs(total - nc.amount(1)) <= CENT, f"{total} against {nc.lines[1].quote if 1 in nc.lines else 'none'}")
