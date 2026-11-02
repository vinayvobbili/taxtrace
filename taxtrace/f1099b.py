"""Form 1099-B on a broker's consolidated 1099 statement: each sale's dates, proceeds, basis and wash sale adjustment.

The form prints as tables under its title ("1099-B Proceeds From Broker and Barter Exchange Transactions - 2026"),
one for each kind of sale, under a heading that says which: "Long-Term Transactions for Which Basis is Reported to the
IRS; Report on Form 8949, Part II, with Box D checked." Short-term and long-term decide the rate, and whether the
basis was reported decides the box on Form 8949: A and D when it was, B and E when it wasn't.

A table's header names its columns over two rows ("Date Sold or Disposed", "Gross Proceeds", "Cost or Other Basis",
"Unadjusted Gain/Loss", "Accrued Market Discount", "Wash Sale Loss Disallowed", "Federal Income Tax"). A sale is a row
with the date sold and at least two amounts, and each amount belongs to the column it sits under. The security's name
is the row above, or on the sale's own row left of its first date; a symbol prints as "Symbol: ACME" or "(ACME)".
A table can run on to the next page, under the same heading.

What a sale adds to Schedule D is its proceeds less its basis, plus any market discount and wash sale loss
disallowed: "unadjusted" means before those two. A disallowed loss isn't gone, it moved to the basis of what was
bought back, and Form 8949 marks the sale with code W.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from itertools import combinations

from .k1 import EIN
from .prior import YEAR, Check, Question, _rows, amount

TITLE = re.compile(r"1099-B\s+Proceeds\s+From\s+Broker", re.IGNORECASE)
HEADING = re.compile(r"(Short|Long)-Term\s+Transactions.*?(Not\s+)?Reported", re.IGNORECASE)
BOX_CHECKED = re.compile(r"Box\s+([A-F])\s+checked", re.IGNORECASE)
MONEY = re.compile(r"^\(?-?\$?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}\)?-?$")
DAY = re.compile(r"^\d{1,2}/\d{1,2}/\d{2,4}$")
SYMBOL = re.compile(r"(?:Symbol:?\s+([A-Z][A-Z.]{0,5})\b|\(([A-Z][A-Z.]{0,5})\))")
SLACK = 1.5
TITLE_SLACK = 4.0
# a column's word in the header, and what it's kept as; the first of a column's words found is its place
COLUMNS = (("Proceeds", "proceeds"), ("Cost", "basis"), ("Basis", "basis"), ("Unadjusted", "gain"),
           ("Gain/Loss", "gain"), ("Accrued", "discount"), ("Wash", "wash"), ("Federal", "withheld"),
           ("Allowed", "not_allowed"))
BOXES = {("short", True): "A", ("short", False): "B", ("long", True): "D", ("long", False): "E"}


@dataclass
class Sale:
    description: str
    symbol: str
    sold: date
    acquired: date | None  # None: "VARIOUS", or not printed
    proceeds: Decimal
    basis: Decimal | None
    term: str  # "short" or "long"
    box: str  # Form 8949's: A, B, D or E
    gain_printed: Decimal | None = None
    discount: Decimal = Decimal(0)
    wash: Decimal = Decimal(0)
    withheld: Decimal = Decimal(0)
    page: int = 0

    @property
    def gain(self) -> Decimal | None:
        """What it adds to Schedule D; None when the basis wasn't reported or printed."""
        return None if self.basis is None else self.proceeds - self.basis + self.discount + self.wash

    def to_json(self) -> dict:
        def plain(v):
            return str(v) if isinstance(v, Decimal) else v

        return {"description": self.description, "symbol": self.symbol, "sold": self.sold.isoformat(),
                "acquired": self.acquired.isoformat() if self.acquired else None, "proceeds": str(self.proceeds),
                "basis": plain(self.basis), "term": self.term, "box": self.box, "gain": plain(self.gain),
                "discount": str(self.discount), "wash": str(self.wash), "withheld": str(self.withheld),
                "page": self.page}


@dataclass
class F1099B:
    file: str
    year: int | None = None
    payer_tin: str = ""
    account: str = ""
    corrected: bool = False
    sales: list[Sale] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def to_json(self) -> dict:
        return {"form": "1099-B", "file": self.file, "year": self.year, "payer_tin": self.payer_tin,
                "account": self.account, "corrected": self.corrected, "sales": [s.to_json() for s in self.sales],
                "checks": [{"what": c.what, "ok": c.ok} for c in self.checks],
                "questions": [q.text for q in self.questions]}


def is_form(page_text: str) -> bool:
    """Whether a page's text (`text.pages`) could hold a 1099-B's sales: instructions name the form, not this title."""
    return bool(TITLE.search(" ".join(page_text.split())))


def read(name: str, pages: dict[int, list[dict]]) -> F1099B | None:
    """The sales among a document's pages, given each page's words by page number; None when there are none."""
    form = F1099B(file=name)
    term, covered, columns, box = "", True, {}, ""
    for n, words in sorted(pages.items()):
        rows = _rows(words, SLACK)
        label = ""
        for i, row in enumerate(rows):
            line = " ".join(w["text"] for w in row)
            if m := HEADING.search(line):
                term, covered = m.group(1).lower(), not m.group(2)
                box = (b.group(1).upper() if (b := BOX_CHECKED.search(line)) else BOXES[term, covered])
                columns, label = {}, ""
                continue
            if found := _header(row, rows[i + 1] if i + 1 < len(rows) else []):
                columns, label = found, ""
                continue
            sale = _sale(row, columns, term, box, label, n) if term and columns else None
            if sale:
                form.sales.append(sale)
            elif term and columns and row and not row[0]["text"].lower().startswith("total") and not any(
                    MONEY.match(w["text"]) for w in row):
                label = line
    if not form.sales:
        return None
    _fields(form, pages)
    _checks(form)
    return form


def survey(pages: dict[int, list[dict]]) -> list[str]:
    """Each page's shape in counts, with no values, for when no sales were read: its headings and table headers, and
    how many rows hold how many dates and amounts. A sale needs a date and two amounts on one row."""
    found = []
    for n, words in sorted(pages.items()):
        rows = _rows(words, SLACK)
        headings = sum(bool(HEADING.search(" ".join(w["text"] for w in row))) for row in rows)
        headers = sum(bool(_header(row, rows[i + 1] if i + 1 < len(rows) else [])) for i, row in enumerate(rows))
        shapes = Counter((sum(bool(DAY.match(w["text"])) for w in row), sum(bool(MONEY.match(w["text"])) for w in row))
                         for row in rows)
        held = ", ".join(f"{count} with {days} dates and {money} amounts"
                         for (days, money), count in sorted(shapes.items()) if days or money)
        found.append(f"page {n}: {headings} headings, {headers} table headers, rows: {held or 'no dates or amounts'}")
    return found


def _header(row: list[dict], below: list[dict]) -> dict[str, float]:
    """A table's columns, each kept's middle, when this row and the next are a header; {} otherwise."""
    texts = {w["text"] for w in row}
    if not ({"Proceeds", "Sold"} & texts and "Cost" in texts):
        return {}
    columns: dict[str, float] = {}
    for word, kept in COLUMNS:
        if kept not in columns and (w := next((w for w in (*row, *below) if w["text"] == word), None)):
            columns[kept] = (w["x0"] + w["x1"]) / 2
    return columns


def _sale(row: list[dict], columns: dict[str, float], term: str, box: str, label: str, page: int) -> Sale | None:
    days = [w for w in row if DAY.match(w["text"])]
    money = [w for w in row if MONEY.match(w["text"])]
    if not days or len(money) < 2:
        return None
    held = {kept: amount(w["text"].rstrip("-")) * (-1 if w["text"].endswith("-") else 1)
            for kept, w in _under_columns(money, columns)}
    if "proceeds" not in held:
        return None
    sold = _day(days[-1]["text"])
    acquired = _day(days[0]["text"]) if len(days) > 1 else None
    left = " ".join(w["text"] for w in row if w["x1"] <= days[0]["x0"] and not re.fullmatch(r"[\d,.]+", w["text"]))
    description = " ".join(s for s in (label, left) if s and s.lower() not in ("sale", "sell", "redemption"))
    m = SYMBOL.search(description)
    return Sale(description, (m.group(1) or m.group(2)) if m else "", sold, acquired, held["proceeds"],
                held.get("basis"), term, box, held.get("gain"), held.get("discount", Decimal(0)),
                held.get("wash", Decimal(0)), held.get("withheld", Decimal(0)), page)


def _under_columns(money: list[dict], columns: dict[str, float]) -> list[tuple[str, dict]]:
    """Each amount with its column: in order, one to a column, closest overall. Amounts print right-aligned, so a short
    one can sit nearer the next column's header than its own."""
    money = sorted(money, key=lambda w: w["x0"])
    names = sorted(columns, key=lambda k: columns[k])
    if len(money) > len(names):
        return []
    best = min(combinations(names, len(money)),
               key=lambda chosen: sum(abs(columns[k] - (w["x0"] + w["x1"]) / 2)
                                      for k, w in zip(chosen, money, strict=True)))
    return list(zip(best, money, strict=True))


def _day(token: str) -> date:
    return datetime.strptime(token, "%m/%d/%Y" if len(token.rsplit("/", 1)[1]) == 4 else "%m/%d/%y").date()


def _year(words: list[dict]) -> int | None:
    """The year on the title's line, which can print in another font, a little off the line of the words around it."""
    for title in (w for w in words if w["text"] == "1099-B"):
        line = sorted((w for w in words if abs(w["top"] - title["top"]) <= TITLE_SLACK and w["x0"] > title["x0"]),
                      key=lambda w: w["x0"])
        if m := YEAR.search(" ".join(w["text"] for w in line)):
            return int(m.group(1))
    return None


def _fields(form: F1099B, pages: dict[int, list[dict]]) -> None:
    for words in pages.values():
        form.year = form.year or _year(words)
        form.payer_tin = form.payer_tin or next((w["text"] for w in words if EIN.match(w["text"])), "")
        form.corrected = form.corrected or any(w["text"] == "CORRECTED" for w in words)


def _checks(form: F1099B) -> None:
    def check(what: str, ok: bool) -> None:
        form.checks.append(Check(what, ok, 0))

    check("the calendar year is printed", form.year is not None)
    check("every sale was made in the form's year", form.year is None or all(s.sold.year == form.year
                                                                             for s in form.sales))
    bad = [s for s in form.sales if s.basis is not None and s.gain_printed is not None
           and abs(s.proceeds - s.basis - s.gain_printed) > Decimal("0.01")
           and abs(s.proceeds - s.basis + s.discount + s.wash - s.gain_printed) > Decimal("0.01")]
    check("each sale's printed gain or loss is its proceeds less its basis", not bad)
    late = [s for s in form.sales if s.acquired and s.term == "short" and (s.sold - s.acquired).days > 366]
    check("a sale marked short-term was held a year or less", not late)
    unknown = sum(s.basis is None for s in form.sales)
    if unknown:
        form.questions.append(Question(f"{unknown} sales have no basis printed: without it the whole proceeds are "
                                       "taxed, so find what you paid (the box on Form 8949 is B or E)", 0, ""))
    washed = sum(bool(s.wash) for s in form.sales)
    if washed:
        form.questions.append(Question(f"{washed} sales have a wash sale loss disallowed: Form 8949 code W, and the "
                                       "loss moved to the basis of the shares bought back", 0, ""))
    withheld = sum(bool(s.withheld) for s in form.sales)
    if withheld:
        form.questions.append(Question(f"{withheld} sales had federal income tax withheld: a payment on Form 1040 "
                                       "line 25b", 0, ""))
    if form.corrected:
        form.questions.append(Question("a corrected 1099-B: it replaces the one the broker sent first, so read only "
                                       "this one", 0, ""))
