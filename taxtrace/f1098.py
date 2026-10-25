"""Form 1098, Mortgage Interest Statement: what a lender received on a mortgage in a year, read by where it sits.

Like the K-1s (`k1`), it's a printed form read from its words and their positions (`text.words`). Each box is found
by its number and the first words of its label ("1 Mortgage interest received"), matched without spaces, since a
lender's print can split a word ("M ortgage"). A box's value is what sits under its label: from its number to the
next words right of the label on the label's row, down to the next box's label. The lender's TIN, the borrower's
(only its last four digits are kept), the account number and the year are read by their labels the same way.

Box 1 is the interest (Schedule E line 12 for a rental, Schedule A line 8a for a home); box 8 or 7 says which
property it's for. Box 10 is whatever else the lender reports (often taxes or insurance paid from escrow), so it's
a question, as are the boxes that change where an amount goes (a refund of interest, insurance premiums, points).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from .k1 import EIN, MARKS, ROW, TIN, Value, _marked
from .prior import DATE, YEAR, Check, Question, _rows, amount

BOXES = {
    "1": "Mortgage interest received from payer(s)/borrower(s)", "2": "Outstanding mortgage principal",
    "3": "Mortgage origination date", "4": "Refund of overpaid interest", "5": "Mortgage insurance premiums",
    "6": "Points paid on purchase of principal residence",
    "7": "Address of property securing mortgage is the same as the payer's/borrower's address",
    "8": "Address or description of property securing mortgage", "9": "Number of properties securing the mortgage",
    "10": "Other", "11": "Mortgage acquisition date",
}
LABELS = {  # the first words of each box's label, as the form prints them
    "1": "Mortgage interest received", "2": "Outstanding mortgage principal", "3": "Mortgage origination date",
    "4": "Refund of overpaid interest", "5": "Mortgage insurance premiums", "6": "Points paid on purchase",
    "7": "If address of property", "8": "Address or description", "9": "Number of properties", "10": "Other",
    "11": "Mortgage acquisition date",
}
FIELDS = {"lender_tin": "RECIPIENT'S/LENDER'S TIN", "payer_tin": "PAYER'S/BORROWER'S TIN",
          "account": "Account number", "year": "For calendar year", "lender": "RECIPIENT'S/LENDER'S name"}
AMOUNTS = ("1", "2", "4", "5", "6", "10")
# an amount, with any description the lender printed right after it ("$1,486.20COUNTYTAX")
AMOUNT = re.compile(r"^(-?\(?\$?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d{2})?\)?)([A-Za-z*].*)?$")
DAY = re.compile(rf"^(?:{DATE})$")
COUNT = re.compile(r"^\d{1,2}$")
GAP = 8.0  # points: a word this far right of a label's last word is the next box's
DOWN = 16.0  # points: how far below its label a box's value can sit, when no label is under it
RATE = Decimal("0.15")  # a year's interest above this share of the principal is a misread, not a mortgage


@dataclass
class Label:
    box: str  # a box number, or a field's name ("account")
    words: list[dict]  # the box number (if printed) and the label's words
    left: float
    right: float
    top: float
    bottom: float = 0.0


@dataclass
class F1098:
    file: str
    page: int
    year: int | None = None
    lender: str = ""
    lender_tin: str = ""  # as printed, "12-3456789"
    payer: str = ""  # the last four digits of the borrower's TIN
    account: str = ""
    corrected: bool = False
    amounts: dict[str, Value] = field(default_factory=dict)  # boxes 1, 2, 4, 5, 6 and 10
    origination: str = ""  # box 3, as printed
    acquisition: str = ""  # box 11
    same_address: bool = False  # box 7: the property is the borrower's own address
    address: str = ""  # box 8: the property's address or description
    properties: int | None = None  # box 9
    other: str = ""  # box 10: what the lender says its amount is
    copy_of: int | None = None
    checks: list[Check] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    def check(self, what: str, ok: bool, quote: str = "") -> None:
        """`what` names boxes only; the amounts go in `quote`, which is printed masked."""
        self.checks.append(Check(what, ok, self.page, quote))

    def ask(self, question: str, quote: str = "") -> None:
        self.questions.append(Question(question, self.page, quote))

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def amount(self, box: str) -> Decimal:
        value = self.amounts.get(box)
        return value.amount if value is not None and value.amount is not None else Decimal(0)

    def values(self) -> list[Value]:
        """Every value read off the form, for `k1.verify`."""
        return list(self.amounts.values())

    def to_json(self) -> dict:
        out = asdict(self)
        out["form"] = "1098"
        out["amounts"] = {box: {**{k: str(v) if isinstance(v, Decimal) else v for k, v in value.items()},
                                "label": BOXES[box]} for box, value in out["amounts"].items()}
        return out


def is_form(page_text: str) -> bool:
    """Whether a page's text (`text.pages`) could be a Form 1098."""
    return "1098" in page_text and "Outstanding mortgage principal" in page_text and "interest received" in page_text


def read(name: str, pages: dict[int, list[dict]]) -> list[F1098]:
    """The 1098s among a document's pages, given each page's words by page number; a repeat counts once."""
    found = [f for n, words in sorted(pages.items()) if (f := form(name, n, words)) is not None]
    for n, later in enumerate(found):
        if first := next((f for f in found[:n] if f.copy_of is None and _same(f, later)), None):
            later.copy_of = first.page
            later.questions.clear()
    return found


def _same(a: F1098, b: F1098) -> bool:
    return (a.lender_tin, a.account) == (b.lender_tin, b.account) and \
        {n: v.quote for n, v in a.amounts.items()} == {n: v.quote for n, v in b.amounts.items()}


def _squeezed(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _label(rows: list[list[dict]], box: str, phrase: str, number: bool) -> Label | None:
    """The first place, top to bottom, where a row reads `phrase` (after the box's number, if `number`)."""
    want = _squeezed(phrase)
    for row in rows:
        for i, first in enumerate(row):
            read, j = "", i
            while j < len(row) and len(read) < len(want):
                read += _squeezed(row[j]["text"])
                j += 1
            if not read.startswith(want) or not _squeezed(first["text"]):
                continue
            words = row[i:j]
            if number:
                ahead = next((w for r in rows for w in r if w["text"] == box and abs(w["top"] - first["top"]) <= ROW
                              and 0 <= first["x0"] - w["x1"] < 12), None)
                if ahead is None:
                    continue
                words = [ahead, *words]
            beyond, end = 612.0, words[-1]["x1"]
            for w in row[j:]:  # the label's own words go on a space apart; the next box's start further off
                if w["x0"] > end + GAP:
                    beyond = w["x0"]
                    break
                end = w["x1"]
            return Label(box, words, words[0]["x0"] - 4, beyond, max(w["top"] for w in words))
    return None


def _inside(label: Label, words: list[dict]) -> list[dict]:
    """The words under a label, left to right on each row, top to bottom."""
    own = {id(w) for w in label.words}
    return sorted((w for w in words if id(w) not in own and label.top + 2 < w["top"] < label.bottom - 1
                   and label.left <= w["x0"] < label.right), key=lambda w: (round(w["top"]), w["x0"]))


def form(name: str, page: int, words: list[dict]) -> F1098 | None:
    """One Form 1098, or None if the page has no box 1 ("1 Mortgage interest received") and box 2."""
    rows = _rows(words, 1.5)
    labels = {box: found for box, phrase in LABELS.items() if (found := _label(rows, box, phrase, True))}
    if "1" not in labels or "2" not in labels:
        return None
    labels |= {key: found for key, phrase in FIELDS.items() if (found := _label(rows, key, phrase, False))}
    for label in labels.values():  # a box ends where the next box's label starts, right of it or under it
        label.right = min([label.right, *(o.left for o in labels.values()
                                          if abs(o.top - label.top) <= ROW and o.left > label.left)])
    for label in labels.values():
        under = [o.top for o in labels.values() if o.top > label.top + 2 and o.left < label.right
                 and label.left < o.right]
        label.bottom = min(under, default=label.top + DOWN)
    f = F1098(file=name, page=page)
    for box in AMOUNTS:
        if box in labels:
            inside = _inside(labels[box], words)
            if (w := next((w for w in inside if AMOUNT.match(w["text"])), None)) is not None:
                glued = AMOUNT.match(w["text"])
                f.amounts[box] = Value(amount(glued.group(1)), page, w["top"], w["x0"], w["text"])
                if box == "10":
                    f.other = glued.group(2) or " ".join(o["text"] for o in inside
                                                         if abs(o["top"] - w["top"]) <= 1.5 and o["x0"] > w["x0"])
    for attr, box in (("origination", "3"), ("acquisition", "11")):
        if box in labels:
            setattr(f, attr, next((w["text"] for w in _inside(labels[box], words) if DAY.match(w["text"])), ""))
    if "7" in labels:
        seven = labels["7"]
        f.same_address = any(w["text"] in MARKS and seven.top - ROW <= w["top"] < seven.bottom
                             and seven.left - 16 <= w["x0"] < seven.right for w in words)
    if "8" in labels:
        f.address = " ".join(w["text"] for w in _inside(labels["8"], words))
    if "9" in labels and (w := next((w for w in _inside(labels["9"], words) if COUNT.match(w["text"])), None)):
        f.properties = int(w["text"])
    _fields(f, labels, words)
    _checks(f)
    return f


def _fields(f: F1098, labels: dict[str, Label], words: list[dict]) -> None:
    texts = {key: [w["text"] for w in _inside(labels[key], words)] for key in FIELDS if key in labels}
    f.lender_tin = next((t for t in texts.get("lender_tin", []) if EIN.match(t)), "")
    f.payer = next((m.group(1) for t in texts.get("payer_tin", []) if (m := TIN.match(t))), "")
    f.account = next((t for t in texts.get("account", []) if any(c.isdigit() for c in t)), "")
    f.year = next((int(m.group(1)) for t in texts.get("year", []) if (m := YEAR.fullmatch(t))), None)
    if "lender" in labels:  # the lender's block is left of the boxes, its lines indented from the label's
        label, boxes = labels["lender"], min(labels[box].left for box in LABELS if box in labels)
        lines = [row for row in _rows([w for w in words if label.top + 2 < w["top"] < label.top + 50
                                       and w["x1"] < boxes], 1.5) if row[0]["x0"] > label.left + 8]
        f.lender = " ".join(w["text"] for w in lines[0]) if lines else ""
    if corrected := next((w for w in words if w["text"] == "CORRECTED"), None):
        f.corrected = _marked(words, corrected)


def _checks(f: F1098) -> None:
    f.check("box 1 has the year's interest", "1" in f.amounts)
    f.check("the calendar year is printed", f.year is not None)
    if f.amount("1") and f.amount("2"):
        f.check("box 1 is under 15% of box 2's principal", f.amount("1") <= f.amount("2") * RATE,
                f"{f.amounts['1'].quote} against {f.amounts['2'].quote}")
    if f.corrected:
        f.ask("a corrected 1098: it replaces the one the lender sent first, so read only this one")
    if not (f.address or f.same_address):
        f.ask("which property the mortgage is on: box 8 is blank and box 7 isn't checked")
    if f.amount("4"):
        f.ask("box 4: interest refunded from an earlier year, which that year deducted: it goes back as income "
              "where it was deducted (Schedule E for a rental, Schedule 1 line 8z if it was itemized)",
              f.amounts["4"].quote)
    if f.amount("5"):
        f.ask("box 5: mortgage insurance premiums: whether and where they're deducted depends on the property "
              "(a rental's are a Schedule E expense)", f.amounts["5"].quote)
    if f.amount("6"):
        f.ask("box 6: points paid on buying a main home: deducted on Schedule A, not Schedule E", f.amounts["6"].quote)
    if f.amount("10"):
        f.ask("box 10 (other): it isn't interest; what the lender says it is (often taxes or insurance paid from "
              "escrow) decides where it goes, once, so it isn't counted again from the escrow statement", f.other)
    if f.properties is not None and f.properties > 1:
        f.ask("box 9: more than one property secures the mortgage, so the interest is split between them",
              str(f.properties))
