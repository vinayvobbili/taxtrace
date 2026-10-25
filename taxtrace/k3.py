"""Schedule K-3 (Form 1065): a partner's share of a partnership's international items, for Form 1116.

What a return takes from it is the foreign tax credit's limitation: Part II's gross income and deductions by source
and category (column (a) U.S. source, (b) to (f) foreign source by category, the last column the total), and Part
III's foreign taxes. Like the K-1 (`k1`) it's a printed form, read by where things sit (`text.words`): each amount
goes to the nearest line number above it, to the row (A, B, C: one per country) beside it, with that row's country
code, and to the column whose heading ends left of the amount's right edge.

Each row's columns have to add up to its total, and each total line to the lines its label names ("combine lines 1
through 23", "subtract line 54 from line 24"). Box E's marks say which parts apply. Foreign taxes are a question:
Form 1116 needs them by category, and the table that gives that isn't read yet.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from .k1 import EIN, MARKS, TIN, Value, _same_row, _value
from .prior import CENT, YEAR, Check, Question, _number

COLUMN = re.compile(r"^\(([a-h])\)$")
LINE = re.compile(r"^\d{1,2}$")
ROWS = {"A", "B", "C", "D", "E", "F", "G"}
COUNTRY = re.compile(r"^[A-Z]{2}$")
PART = re.compile(r"^(I|II|III|IV|V|VI|VII|VIII|IX|X|XI|XII|XIII)$")
COMBINE = re.compile(r"(?i)combine\s+lines\s+(\d+)\s+through\s+(\d+)")
SUBTRACT = re.compile(r"(?i)subtract\s+line\s+(\d+)\s+from\s+line\s+(\d+)")
NEAR = 4.0  # points: an amount sits this close to its row's letter and country


@dataclass
class Cell:
    """One amount in Part II: its line, its row (A, B, C, or "" for the line's own), country and column."""

    line: int
    row: str
    country: str
    column: str  # "a" (U.S. source) to "g" (total)
    value: Value


@dataclass
class K3:
    file: str
    page: int  # the K-3's first page
    year: int | None = None
    ein: str = ""
    partner: str = ""  # the last four digits of the partner's SSN or TIN
    parts: dict[str, bool] = field(default_factory=dict)  # box E: "II" -> applies
    cells: list[Cell] = field(default_factory=list)  # Part II, Sections 1 and 2
    labels: dict[int, str] = field(default_factory=dict)  # Part II's line labels, for the totals they name
    total: str = ""  # Part II's total column
    foreign_taxes: list[Value] = field(default_factory=list)  # any amount in Part III, Section 4
    checks: list[Check] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    def check(self, what: str, ok: bool, quote: str = "", page: int | None = None) -> None:
        self.checks.append(Check(what, ok, page or self.page, quote))

    def ask(self, question: str, quote: str = "") -> None:
        self.questions.append(Question(question, self.page, quote))

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def amount(self, line: int, column: str, row: str | None = None) -> Decimal:
        """A line's amount in one column: its own row's (row ""), one country row's, or (None) all its rows'."""
        found = [c.value.amount for c in self.cells if c.line == line and c.column == column and
                 (row is None or c.row == row)]
        return sum(found, Decimal(0))

    def foreign_columns(self) -> set[str]:
        """The foreign-source columns ((b) to (f)) with an amount anywhere on Part II: Form 1116's categories."""
        return {c.column for c in self.cells if c.column not in ("a", self.total) and c.value.amount}

    def values(self) -> list[Value]:
        """Every value read off the form, for `k1.verify` (each page's own)."""
        return [c.value for c in self.cells] + self.foreign_taxes

    def to_json(self) -> dict:
        def plain(obj):
            if isinstance(obj, Decimal):
                return str(obj)
            if isinstance(obj, dict):
                return {str(k): plain(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [plain(v) for v in obj]
            return obj

        return {**plain(asdict(self)), "form": "K-3"}


def is_page(page_text: str) -> bool:
    """Whether a page's text (`text.pages`) is one of a Schedule K-3's: its first page, or one headed with its name.

    A K-1 or a letter that only mentions the K-3 isn't one.
    """
    return _first(page_text) or ("Schedule K-3 (Form 1065)" in " ".join(page_text.split()) and
                                 "Name of partner" in page_text)


def _first(page_text: str) -> bool:
    return "Credits, etc." in page_text and "International" in page_text and "Information About the Partner" in \
        page_text


def read(name: str, pages: dict[int, list[dict]], texts: list[str]) -> list[K3]:
    """The K-3s among a document's pages (each from its first page to the next one's), by each page's words."""
    found: list[K3] = []
    for n, words in sorted(pages.items()):
        page_text = texts[n - 1]
        if _first(page_text) or not found:
            found.append(K3(file=name, page=n))
            _header(found[-1], words)
        if "Part II" in page_text and "Foreign Tax Credit Limitation" in page_text:
            _part_two(found[-1], n, words)
        if "Foreign Taxes" in page_text and "Part III" in page_text:
            _foreign_taxes(found[-1], n, words)
    for k3 in found:
        _checks(k3)
    return found


def _header(k3: K3, words: list[dict]) -> None:
    rows = sorted(words, key=lambda w: (w["top"], w["x0"]))
    if ein := next((w for w in rows if EIN.match(w["text"])), None):
        k3.ein = ein["text"]
    if tin := next((m for w in rows if (m := TIN.match(w["text"]))), None):
        k3.partner = tin.group(1)
    if calendar := next((w for w in rows if w["text"] == "calendar"), None):
        if m := YEAR.search(" ".join(w["text"] for w in rows if _same_row(w, calendar, 1))):
            k3.year = int(m.group(1))
    yes, no = (next((w for w in rows if w["text"] == t and w["x0"] > 400), None) for t in ("Yes", "No"))
    if yes is None or no is None:
        return
    for w in rows:  # "1 Does Part I apply?": the mark on its row under Yes or No
        if w["text"] == "Part" and any(o["text"] == "Does" and _same_row(o, w, 1) and o["x1"] < w["x0"] for o in rows):
            roman = next((o for o in rows if _same_row(o, w, 1) and o["x0"] > w["x1"] and o["x0"] - w["x1"] < 8), None)
            if roman is None or not PART.match(roman["text"]):
                continue
            mark = next((o for o in rows if o["text"] in MARKS and abs(o["top"] - w["top"]) <= 2 and
                         o["x0"] > yes["x0"] - 10), None)
            if mark is not None:
                centre = (mark["x0"] + mark["x1"]) / 2
                k3.parts[roman["text"]] = abs(centre - (yes["x0"] + yes["x1"]) / 2) < \
                    abs(centre - (no["x0"] + no["x1"]) / 2)


def _part_two(k3: K3, page: int, words: list[dict]) -> None:
    """Part II's grid on one page: from its column headings down to Part III or the footer."""
    def starts(w: dict, first: str, then: str) -> bool:
        return w["text"] == first and any(o["text"] == then and _same_row(o, w, 1) and o["x0"] > w["x0"]
                                          for o in words)

    third = min((w["top"] for w in words if starts(w, "Part", "III")), default=float("inf"))
    heads: dict[str, dict] = {}
    for w in sorted(words, key=lambda w: w["top"]):  # Part II's own headings, not a later part's on the page
        if (m := COLUMN.match(w["text"])) and w["top"] < third:
            heads.setdefault(m.group(1), w)
    if "a" not in heads:
        return
    k3.total = max(heads)
    top = heads["a"]["top"] + 8
    bottom = min([third] + [w["top"] for w in words if w["top"] > top and starts(w, "Schedule", "K-3")])
    left = heads["a"]["x0"]
    region = [w for w in words if top < w["top"] < bottom - 1]
    lines = sorted(((int(w["text"]), w) for w in region if LINE.match(w["text"]) and w["x0"] < 50),
                   key=lambda t: t[1]["top"])
    for n, (line, label) in enumerate(lines):  # its label runs to the next line's number
        stop = lines[n + 1][1]["top"] - 1 if n + 1 < len(lines) else bottom
        k3.labels.setdefault(line, " ".join(
            w["text"] for w in sorted(region, key=lambda w: (round(w["top"]), w["x0"]))
            if label["top"] - 1 <= w["top"] < stop and label["x1"] < w["x0"] < left - 4))
    letters = [w for w in region if w["text"] in ROWS and 44 <= w["x0"] <= 52]
    columns = sorted(heads.items(), key=lambda t: t[1]["x0"])
    for w in region:
        if not (_number(w["text"]) and w["x0"] > left + 10):
            continue
        line = next((n for n, label in reversed(lines) if label["top"] <= w["top"] + NEAR), None)
        if line is None:
            k3.ask("Part II: an amount above the first line's number", w["text"])
            continue
        row = next((r["text"] for r in letters if abs(r["top"] - w["top"]) <= NEAR), "")
        country = next((o["text"] for o in region if COUNTRY.match(o["text"]) and 52 < o["x0"] < left and
                        abs(o["top"] - w["top"]) <= 1.5), "")
        column = next((c for c, h in reversed(columns) if h["x0"] < w["x1"] - 2), "a")
        k3.cells.append(Cell(line, row, country, column, _value(w, page)))


def _foreign_taxes(k3: K3, page: int, words: list[dict]) -> None:
    """Any amount in Part III, Section 4's tables: past the description column, above the next section or footer."""
    heading = next((w for w in words if w["text"] == "Taxes" and any(  # "Section 4—Foreign Taxes"
        o["text"].endswith("Foreign") and _same_row(o, w, 1) and o["x1"] < w["x0"] for o in words)), None)
    if heading is None:
        return
    stops = [w["top"] for w in words if w["top"] > heading["top"] + 2 and (
        (w["text"] == "Schedule" and any(o["text"] == "K-3" and _same_row(o, w, 1) for o in words)) or
        (w["text"].startswith("Section") and w["x0"] < 60))]
    bottom = min(stops, default=float("inf"))
    k3.foreign_taxes += [_value(w, page) for w in words if _number(w["text"]) and w["x0"] > 150 and
                         heading["top"] + 2 < w["top"] < bottom - 1]


def tie(k3: K3, federal: list[tuple[str, Decimal]]) -> None:
    """Part II's lines that are a K-1 box (interest is box 5) against the same partnership's K-1 (box, amount)."""
    for line, label in sorted(k3.labels.items()):
        box = next((b for words, b in K1_BOXES if label.lower().startswith(words)), None)
        if box is None or not any(c.line == line for c in k3.cells):
            continue
        given = sum((a for b, a in federal if b == box), Decimal(0))
        own = any(c.line == line and c.row == "" and c.column == k3.total for c in k3.cells)
        found = k3.amount(line, k3.total, "" if own else None)  # the line's own total, or its countries' added up
        k3.check(f"Part II line {line}: its total ({k3.total}) is the K-1's box {box}", abs(found - given) <= CENT,
                 f"{found} against {given}")


# Part II's lines whose label names a K-1 box's item (by the label's first words)
K1_BOXES = (("guaranteed payments", "4c"), ("interest income", "5"), ("ordinary dividends", "6a"),
            ("royalties", "7"), ("net short-term capital gain", "8"), ("net long-term capital gain", "9a"),
            ("collectibles", "9b"), ("unrecaptured section 1250 gain", "9c"), ("net section 1231 gain", "10"))


def verify(k3: K3, pages: dict[int, list[dict]]) -> list[str]:
    """Each value's text still at its place on its own page (`pages`: each page's words)."""
    return [f"p{v.page}: {v.quote!r} isn't at {v.top}, {v.x0}" for v in k3.values()
            if not any(w["text"] == v.quote and abs(w["top"] - v.top) < 0.6 and abs(w["x0"] - v.x0) < 0.6
                       for w in pages.get(v.page, []))]


def _checks(k3: K3) -> None:
    rows = sorted({(c.line, c.row) for c in k3.cells})
    for line, row in rows:
        parts = sum((c.value.amount for c in k3.cells if (c.line, c.row) == (line, row) and c.column != k3.total),
                    Decimal(0))
        total = next((c for c in k3.cells if (c.line, c.row, c.column) == (line, row, k3.total)), None)
        k3.check(f"Part II line {line}{' row ' + row if row else ''}: its columns add up to its total ({k3.total})",
                 total is not None and abs(parts - total.value.amount) <= CENT,
                 f"{parts} against {total.value.quote if total else 'none'}", total.value.page if total else None)
    for line, label in k3.labels.items():
        own = {c.column for c in k3.cells if c.line == line and c.row == ""}
        if m := COMBINE.search(label):
            first, last = int(m.group(1)), int(m.group(2))
            for column in sorted(own):
                summed = sum((k3.amount(n, column) for n in range(first, last + 1)), Decimal(0))
                k3.check(f"Part II line {line}, column ({column}): lines {first} through {last} added up",
                         abs(summed - k3.amount(line, column, "")) <= CENT,
                         f"{summed} against {k3.amount(line, column, '')}")
        elif m := SUBTRACT.search(label):
            less, start = int(m.group(1)), int(m.group(2))
            for column in sorted(own):
                net = k3.amount(start, column, "") - k3.amount(less, column, "")
                k3.check(f"Part II line {line}, column ({column}): line {start} less line {less}",
                         abs(net - k3.amount(line, column, "")) <= CENT, f"{net} against {k3.amount(line, column, '')}")
    if k3.parts.get("II") and not k3.cells:
        k3.ask("box E says Part II applies, and no amount was read from it")
    if k3.foreign_taxes:
        k3.ask("Part III, Section 4 has foreign taxes: Form 1116 takes them by category and country, and taxtrace "
               "doesn't read that table yet", ", ".join(v.quote for v in k3.foreign_taxes))
