"""Form W-2 read off its boxes: wages, the tax withheld, box 12's codes and the state's lines.

The IRS's form and a payroll company's approved substitute hold the same boxes in different places, with some labels
shortened ("Wages, tips, other comp."), and print two or four copies to a page. So a box is found by the words of its
label, not by where it sits, and its value is the amount under that label (or beside it, on a form that prints them on
one row), inside its column and above the next label down. Copies on one page are the same form, and the first is read;
one that shows other wages is a question, since it may be another employer's.

Only the last four digits of the employee's Social Security number are kept, to say whose W-2 it is. Box 13's checkboxes
aren't read. The form's own arithmetic is checked: Social Security tax is 6.2% of its wages, and Medicare tax at least
1.45% of its wages (more with the additional Medicare tax on high pay).
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from .k1 import EIN, TIN, Value
from .prior import YEAR, Check, Question, _rows, amount

BOXES = {
    "1": "Wages, tips, other compensation", "2": "Federal income tax withheld", "3": "Social security wages",
    "4": "Social security tax withheld", "5": "Medicare wages and tips", "6": "Medicare tax withheld",
    "7": "Social security tips", "8": "Allocated tips", "10": "Dependent care benefits", "11": "Nonqualified plans",
    "16": "State wages, tips, etc.", "17": "State income tax", "18": "Local wages, tips, etc.",
    "19": "Local income tax",
}
LABELS = {"1": "wagestipsother", "2": "federalincometax", "3": "socialsecuritywages", "4": "socialsecuritytax",
          "5": "medicarewages", "6": "medicaretax", "7": "socialsecuritytips", "8": "allocatedtips",
          "10": "dependentcare", "11": "nonqualified", "16": "statewages", "17": "stateincometax",
          "18": "localwages", "19": "localincometax"}
MONEY = re.compile(r"^\$?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}$")
BOX_12 = re.compile(r"^12[a-dA-D](?![a-z])")  # a tight form glues the number to its label: "12aSee"
NUMBER = re.compile(r"^\d{1,2}(?=[a-z])")  # the same glue, once squeezed: "10dependent"
CODE = re.compile(r"^[A-HJ-NP-Z]{1,2}$")  # box 12's codes: letters, without I and O
STATE = re.compile(r"^[A-Z]{2}$")
PLAIN_EIN = re.compile(r"^\d{2}-?\d{7}$")
NAME_GAP = 30.0  # points: words further apart than this aren't one name
EIN_DOWN, EIN_LEFT, EIN_RIGHT = 20.0, 50.0, 70.0  # points: where an EIN sits around its label's "identification"
ROW = 3.0  # points: labels this close in height are on one row
NEAR_ROW = 14.0  # points: a label this close in height, to the right, still ends a box's column
LEFT = 13.0  # points: a box's number, and an amount under it, can start this far left of its label's words
CODE_LEFT = 5.0  # points: the small vertical "Code" sits at box 12's number; a real code is right of it
DOWN = 34.0  # points: how far below its label a value can sit, when no label is under it
SOCIAL_SECURITY, MEDICARE = Decimal("0.062"), Decimal("0.0145")
SLACK = Decimal(1)  # a dollar of rounding


@dataclass
class Place:
    box: str
    x0: float
    x1: float  # where the label's own words end
    top: float
    right: float = 612.0
    bottom: float = 0.0


@dataclass
class W2:
    file: str
    page: int
    year: int | None = None
    ein: str = ""
    employer: str = ""
    employee: str = ""  # the last four digits of the employee's Social Security number
    state: str = ""  # box 15
    amounts: dict[str, Value] = field(default_factory=dict)
    box_12: dict[str, Value] = field(default_factory=dict)  # by its code
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
        return [*self.amounts.values(), *self.box_12.values()]

    def to_json(self) -> dict:
        out = asdict(self)
        out["form"] = "W-2"
        out["amounts"] = {box: {**{k: str(v) if isinstance(v, Decimal) else v for k, v in value.items()},
                                "label": BOXES[box]} for box, value in out["amounts"].items()}
        out["box_12"] = {code: {k: str(v) if isinstance(v, Decimal) else v for k, v in value.items()}
                         for code, value in out["box_12"].items()}
        return out


def is_form(page_text: str) -> bool:
    """Whether a page's text (`text.pages`) could hold a W-2."""
    squeezed = _squeezed(page_text)
    return LABELS["1"] in squeezed and LABELS["2"] in squeezed and ("w2" in squeezed or "wageandtax" in squeezed)


def _squeezed(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _places(rows: list[list[dict]], box: str, phrase: str) -> list[Place]:
    """Every place a row reads the phrase: one for each copy on the page."""
    found = []
    for row in rows:
        for i, first in enumerate(row):
            read, j = NUMBER.sub("", _squeezed(first["text"])), i + 1
            while j < len(row) and len(read) < len(phrase):
                read += _squeezed(row[j]["text"])
                j += 1
            if read.startswith(phrase) and _squeezed(first["text"]):
                found.append(Place(box, first["x0"], row[j - 1]["x1"], first["top"]))
    return found


def _box_12_places(words: list[dict]) -> list[Place]:
    """Box 12's labels: they have no value of their own here, but the boxes around them end at them."""
    return [Place(m.group().lower(), w["x0"], w["x1"], w["top"]) for w in words if (m := BOX_12.match(w["text"]))]


def _bounded(places: list[Place]) -> None:
    """A box ends where the next label starts: right of it on about its row, or under it in its column.

    "About" because the IRS's columns don't line up: box 11's label sits between the rows of 10 and 12a, to its right.
    """
    for p in places:
        p.right = min([612.0, *(o.x0 - LEFT for o in places if abs(o.top - p.top) <= NEAR_ROW and o.x0 > p.x1)])
    for p in places:
        under = [o.top for o in places if o.top > p.top + ROW and o.x0 < p.right and p.x0 - LEFT < o.right]
        p.bottom = min([p.top + DOWN, *under])


def _value(place: Place, words: list[dict]) -> dict | None:
    """The first amount under a label, or beside it on its own row."""
    under = [w for w in words if place.top + ROW < w["top"] < place.bottom]
    beside = [w for w in words if abs(w["top"] - place.top) <= ROW and w["x0"] > place.x1]
    inside = [w for w in under + beside if MONEY.match(w["text"]) and place.x0 - LEFT <= w["x0"] < place.right]
    return min(inside, key=lambda w: (round(w["top"]), w["x0"]), default=None)


def _worth(word: dict, page: int) -> Value:
    return Value(amount(word["text"].lstrip("$")), page, word["top"], word["x0"], word["text"])


def _box_12(f: W2, words: list[dict], places: list[Place]) -> None:
    """Box 12's rows of the first copy: each code just left of its amount, on its row. The IRS form's small vertical
    "Code" sits at the label's own left edge, so it's skipped."""
    labels = sorted((p for p in places if BOX_12.match(p.box)), key=lambda p: (round(p.top), p.x0))
    seen: set[str] = set()
    for label in labels:
        if label.box in seen:  # a later copy's
            continue
        seen.add(label.box)
        name = label.box
        row = [w for w in words
               if label.top - 1 <= w["top"] < label.bottom and label.x0 + CODE_LEFT < w["x0"] < label.right]
        for worth in (w for w in row if MONEY.match(w["text"])):
            code = next((w["text"] for w in sorted(row, key=lambda w: -w["x0"]) if CODE.match(w["text"])
                         and abs(w["top"] - worth["top"]) <= ROW and w["x0"] < worth["x0"]), "")
            if code:
                f.box_12[code] = _worth(worth, f.page)
            else:
                f.ask(f"box {name} has an amount with no code that could be read", worth["text"])


def form(name: str, page: int, words: list[dict]) -> W2 | None:
    """One W-2, or None if the page has no amount under box 1's label."""
    rows = _rows(words, 1.5)
    every = {box: _places(rows, box, phrase) for box, phrase in LABELS.items()}
    if not every["1"]:
        return None
    all_places = [p for places in every.values() for p in places] + _box_12_places(words)
    _bounded(all_places)
    first = {box: places[0] for box, places in every.items() if places}
    f = W2(file=name, page=page)
    for box, place in first.items():
        if (word := _value(place, words)) is not None:
            f.amounts[box] = _worth(word, page)
    if "1" not in f.amounts:
        return None
    others = {w["text"] for p in every["1"][1:] if (w := _value(p, words))}
    if others - {f.amounts["1"].quote}:
        f.ask("the copies on this page show different box 1 wages: it may hold more than one employer's W-2, and only "
              "the first is read")
    _box_12(f, words, all_places)
    _fields(f, rows, words, first)
    _checks(f, words, first)
    return f


def _name(row: list[dict]) -> str:
    """The employer's name: a form can print the employee's Social Security number further along the same row."""
    kept: list[dict] = []
    for word in row:
        if TIN.match(word["text"]) or (kept and word["x0"] - kept[-1]["x1"] > NAME_GAP):
            break
        kept.append(word)
    return " ".join(w["text"] for w in kept)


def _ein(words: list[dict]) -> str:
    """The number under the "identification number" label, which a payroll company can print without its dash."""
    label = next((w for w in words if w["text"].lower().startswith("identification")), None)
    if label:
        under = [w for w in words if label["top"] + ROW < w["top"] < label["top"] + EIN_DOWN
                 and label["x0"] - EIN_LEFT <= w["x0"] < label["x0"] + EIN_RIGHT and PLAIN_EIN.match(w["text"])]
        if under:
            digits = under[0]["text"].replace("-", "")
            return f"{digits[:2]}-{digits[2:]}"
    return next((w["text"] for w in words if EIN.match(w["text"])), "")


def _fields(f: W2, rows: list[list[dict]], words: list[dict], first: dict[str, Place]) -> None:
    f.ein = _ein(words)
    f.employee = next((m.group(1) for w in words if (m := TIN.match(w["text"]))), "")
    for row in rows:  # the year sits on the form's title row, or just by it
        if "wage" in _squeezed(" ".join(w["text"] for w in row)) and "statement" in _squeezed(
                " ".join(w["text"] for w in row)):
            near = [w for w in words if abs(w["top"] - row[0]["top"]) <= 14 and YEAR.fullmatch(w["text"])]
            if near:
                f.year = int(near[0]["text"])
                break
    heading = next((r for r in rows if _squeezed(" ".join(w["text"] for w in r)).find("employersname") >= 0), None)
    if heading:
        start = next(i for i in range(len(heading)) if _squeezed(heading[i]["text"]).startswith("employer"))
        left = heading[start]["x0"]
        boxes = min((p.x0 for p in first.values() if abs(p.top - heading[0]["top"]) <= ROW), default=612.0) - LEFT
        lines = _rows([w for w in words if heading[0]["top"] + ROW < w["top"] < heading[0]["top"] + 50
                       and left - LEFT <= w["x0"] < boxes], 1.5)
        f.employer = _name(lines[0]) if lines else ""
    if "16" in first:
        beside = [w for w in words if first["16"].top + ROW < w["top"] < first["16"].top + 40
                  and w["x0"] < first["16"].x0 and STATE.match(w["text"])]
        f.state = min(beside, key=lambda w: (round(w["top"]), w["x0"]))["text"] if beside else ""


def _checks(f: W2, words: list[dict], first: dict[str, Place]) -> None:
    f.check("box 1 has the year's wages", "1" in f.amounts)
    f.check("box 2 is read", "2" in f.amounts)
    f.check("the tax year is printed", f.year is not None)
    if f.amount("3"):
        f.check("box 4 is 6.2% of box 3", abs(f.amount("3") * SOCIAL_SECURITY - f.amount("4")) <= SLACK,
                f"{f.amounts['3'].quote} against {f.amounts.get('4').quote if '4' in f.amounts else 'nothing'}")
    if f.amount("5"):
        f.check("box 6 is at least 1.45% of box 5", f.amount("6") + SLACK >= f.amount("5") * MEDICARE,
                f"{f.amounts['5'].quote} against {f.amounts.get('6').quote if '6' in f.amounts else 'nothing'}")
    if "16" in first:
        place = first["16"]
        amounts = [w for w in words if MONEY.match(w["text"]) and place.x0 - LEFT <= w["x0"] < place.right
                   and place.top + ROW < w["top"] < place.bottom]
        if len({round(w["top"]) for w in amounts}) > 1:
            f.ask("box 16 has more than one state's row, and only the first is read")
    if f.amount("10"):
        f.ask("box 10: dependent care benefits go on Form 2441, and any above the limit are taxable",
              f.amounts["10"].quote)
    if f.amount("8"):
        f.ask("box 8: allocated tips aren't in box 1 and are reported as income (Form 4137)", f.amounts["8"].quote)
    if f.amount("11"):
        f.ask("box 11: a nonqualified plan's payments: already in box 1, shown for Social Security",
              f.amounts["11"].quote)
    if "W" in f.box_12:
        f.ask("box 12 code W: HSA contributions through your employer, which go on Form 8889", f.box_12["W"].quote)
    if any(w["text"].upper() in ("W-2C", "W-2CS") for w in words):
        f.ask("a corrected W-2 (W-2c): it replaces the original's boxes it shows, so check this against the original")
    if not f.employer:
        f.ask("the employer's name couldn't be read")


def read(name: str, pages: dict[int, list[dict]]) -> list[W2]:
    """The W-2s among a document's pages, given each page's words by page number; a repeat counts once."""
    found = [f for n, words in sorted(pages.items()) if (f := form(name, n, words)) is not None]
    for n, later in enumerate(found):
        if first := next((f for f in found[:n] if f.copy_of is None and _same(f, later)), None):
            later.copy_of = first.page
            later.questions.clear()
    return found


def _same(a: W2, b: W2) -> bool:
    return a.ein == b.ein and {k: v.quote for k, v in a.amounts.items()} == {k: v.quote for k, v in b.amounts.items()}
