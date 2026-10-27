"""Forms 1099-DIV and 1099-INT on a broker's consolidated 1099 statement: each box's amount, the payer and the year.

A consolidated statement prints each form as a column of rows, "Box 1a Total Ordinary Dividends ... 1,234.56", the
forms side by side under their titles ("1099-INT Interest Income - 2025 Statement for recipient", "1099-DIV Dividends
and Distributions - 2025 ..."). A form's column runs from its title to the next title right of it. A row is a box's
id ("1a", "5", "12", with or without "Box" before it), its label, and what's printed well right of the label: an
amount, or words (box 8's country). A box id printed a little under its label's line ("Box 2f" below "Section 897
capital gain") is on that row. The year is the title's; the payer's TIN and the account number are read by their
labels, as the 1098's are (`f1098`).

Where the boxes go: 1099-DIV box 1a and 1b to Schedule B and the qualified dividends worksheet, 2a to Schedule D,
box 5 (section 199A dividends) to Form 8995 line 6 (`qbi`), box 7 (foreign tax paid) to Form 1116 or straight to
Schedule 3; 1099-INT box 1 to Schedule B. The boxes that change where an amount goes are questions. The form's own
arithmetic is checked: the qualified dividends (1b), section 199A dividends (5) and section 897 ordinary dividends
(2e) are each part of the ordinary dividends (1a), and the capital gain parts (2b, 2c, 2d, 2f) part of 2a.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from .k1 import EIN, Value
from .prior import YEAR, Check, Question, _rows, amount

TITLES = {"1099-DIV": "Dividends", "1099-INT": "Interest"}  # a form's title, and the word that follows it
TITLE = re.compile(r"1099-(?:DIV\s+Dividends|INT\s+Interest)")
BOX = re.compile(r"^\d{1,2}[a-h]?$")
MONEY = re.compile(r"^\(?-?\$?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}\)?$")
SLACK = 2.5  # points: a box id printed this far under its label's line is on that row
GAP = 20.0  # points: words this far right of a label's last word are what the box holds
PARTS = {"1a": ("1b", "2e", "5"), "2a": ("2b", "2c", "2d", "2f")}  # 1099-DIV: boxes that are part of another


@dataclass
class F1099:
    form: str  # "1099-DIV" or "1099-INT"
    file: str
    page: int
    year: int | None = None
    payer_tin: str = ""  # as printed, "12-3456789"
    account: str = ""
    corrected: bool = False
    amounts: dict[str, Value] = field(default_factory=dict)
    labels: dict[str, str] = field(default_factory=dict)  # each box's label, as printed
    words: dict[str, str] = field(default_factory=dict)  # a box that holds words, not an amount: 1099-DIV box 8
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
        out["amounts"] = {box: {**{k: str(v) if isinstance(v, Decimal) else v for k, v in value.items()},
                                "label": self.labels.get(box, "")} for box, value in out["amounts"].items()}
        return out


def is_form(page_text: str) -> bool:
    """Whether a page's text (`text.pages`) could hold a 1099-DIV or 1099-INT."""
    return bool(TITLE.search(page_text))


def read(name: str, pages: dict[int, list[dict]]) -> list[F1099]:
    """The 1099-DIVs and 1099-INTs among a document's pages, given each page's words by page number; a repeat
    counts once."""
    found = [f for n, words in sorted(pages.items()) for f in on_page(name, n, words)]
    for n, later in enumerate(found):
        if first := next((f for f in found[:n] if f.copy_of is None and _same(f, later)), None):
            later.copy_of = first.page
            later.questions.clear()
    return found


def _same(a: F1099, b: F1099) -> bool:
    return (a.form, a.payer_tin, a.account) == (b.form, b.payer_tin, b.account) and \
        {n: v.quote for n, v in a.amounts.items()} == {n: v.quote for n, v in b.amounts.items()}


def on_page(name: str, page: int, words: list[dict]) -> list[F1099]:
    """The forms one page prints, each from its column of box rows; a title with no box rows under it is none."""
    titles = sorted(((w, row) for row in _rows(words, 1.5) for i, w in enumerate(row)
                     if w["text"] in TITLES and i + 1 < len(row) and row[i + 1]["text"] == TITLES[w["text"]]),
                    key=lambda t: t[0]["x0"])
    found = []
    for k, (title, row) in enumerate(titles):
        left = title["x0"] - 4
        right = next((t["x0"] - 4 for t, _ in titles[k + 1:] if abs(t["top"] - title["top"]) <= SLACK), 10_000.0)
        f = F1099(form=title["text"], file=name, page=page)
        heading = " ".join(w["text"] for w in row if left <= w["x0"] < right)
        f.year = next((int(m.group(1)) for m in [YEAR.search(heading.replace(title["text"], ""))] if m), None)
        below = [w for w in words if left <= w["x0"] < right and w["top"] > title["top"] + SLACK]
        for line in _rows(below, SLACK):
            _box(f, line, page)
        if f.amounts or f.words:
            _fields(f, words)
            _checks(f)
            found.append(f)
    return found


def _box(f: F1099, line: list[dict], page: int) -> None:
    """One row: [Box] id, its label, then what the box holds."""
    texts = [w["text"] for w in line]
    start = 1 if texts and texts[0] == "Box" else 0
    if len(line) < start + 2 or not BOX.match(texts[start]) or not re.search(r"[A-Za-z]", texts[start + 1]) \
            or texts[start] in f.labels:  # a numbered note under the form isn't a box read already
        return
    box, label, end = texts[start], [line[start + 1]], start + 2
    while end < len(line) and line[end]["x0"] - label[-1]["x1"] < GAP:
        label.append(line[end])
        end += 1
    held = line[end:]
    f.labels[box] = " ".join(w["text"] for w in label)
    if len(held) == 1 and MONEY.match(held[0]["text"]):
        w = held[0]
        f.amounts[box] = Value(amount(w["text"]), page, w["top"], w["x0"], w["text"])
    elif held:
        f.words[box] = " ".join(w["text"] for w in held)


def _fields(f: F1099, words: list[dict]) -> None:
    f.payer_tin = next((w["text"] for w in words if EIN.match(w["text"])), "")
    if number := next((w for w in words if w["text"] == "Number:" and any(
            a["text"] == "Account" and abs(a["top"] - w["top"]) <= 1.5 and 0 <= w["x0"] - a["x1"] < 10
            for a in words)), None):
        f.account = next((w["text"] for w in sorted(words, key=lambda w: w["top"])
                          if number["top"] + 4 < w["top"] < number["top"] + 16
                          and number["x0"] - 150 <= w["x0"] <= number["x1"] and re.search(r"\d", w["text"])), "")
    f.corrected = any(w["text"] == "CORRECTED" for w in words)


def _checks(f: F1099) -> None:
    f.check("the calendar year is printed", f.year is not None)
    if f.form == "1099-DIV":
        f.check("box 1a, the ordinary dividends, is read", "1a" in f.amounts)
        for whole, parts in PARTS.items():
            for part in parts:
                if f.amount(part):
                    f.check(f"box {part} is part of box {whole}", f.amount(part) <= f.amount(whole),
                            f"{f.amounts[part].quote} against {f.amounts[whole].quote if whole in f.amounts else '0'}")
        _dividend_questions(f)
    else:
        f.check("box 1, the interest, is read", "1" in f.amounts)
        _interest_questions(f)
    if f.corrected:
        f.ask(f"a corrected {f.form}: it replaces the one the payer sent first, so read only this one")


def _dividend_questions(f: F1099) -> None:
    def ask(box: str, text: str) -> None:
        if f.amount(box):
            f.ask(f"box {box}: {text}", f.amounts[box].quote)

    ask("2b", "unrecaptured section 1250 gain: it goes to the Schedule D tax worksheet, at up to 25%")
    ask("2c", "section 1202 gain: part of it may be excluded (qualified small business stock)")
    ask("2d", "collectibles (28%) gain: it goes to the 28% rate gain worksheet")
    ask("3", "nondividend distributions: a return of capital, not income; it lowers the shares' basis, and only "
             "what's past the basis is a capital gain")
    ask("4", "federal income tax withheld: a payment on Form 1040 line 25b")
    ask("7", "foreign tax paid: a credit, on Form 1116, or straight on Schedule 3 line 1 when all of the year's is "
             "passive, reported on 1099s, and at most $600 filing jointly ($300 otherwise)"
             + (f"; country: {f.words['8']}" if f.words.get("8") else ""))
    ask("9", "a cash liquidation distribution: it's a return of the shares' basis first, then a capital gain")
    ask("10", "a noncash liquidation distribution: its fair market value is a return of basis first, then a gain")
    ask("12", "exempt-interest dividends: not taxed, but reported on Form 1040 line 2a; the state may tax the part "
              "from other states' bonds")
    ask("13", "specified private activity bond interest dividends: an AMT preference item (Form 6251)")


def _interest_questions(f: F1099) -> None:
    def ask(box: str, text: str) -> None:
        if f.amount(box):
            f.ask(f"box {box}: {text}", f.amounts[box].quote)

    ask("2", "early withdrawal penalty: an adjustment to income on Schedule 1 line 18")
    ask("3", "U.S. savings bond and Treasury interest: federally taxed, but North Carolina doesn't tax it (a "
             "deduction on the NC return)")
    ask("4", "federal income tax withheld: a payment on Form 1040 line 25b")
    ask("6", "foreign tax paid: a credit, on Form 1116 or straight on Schedule 3 line 1")
    ask("8", "tax-exempt interest: not taxed, but reported on Form 1040 line 2a")
    ask("9", "specified private activity bond interest: an AMT preference item (Form 6251)")
    ask("10", "market discount: taxed as interest only if you chose to include it each year; otherwise when sold")
    for box in ("11", "12", "13"):
        ask(box, "bond premium: it reduces the interest the bond paid (Schedule B shows it as an adjustment)")
