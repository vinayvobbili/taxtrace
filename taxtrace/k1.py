"""Schedule K-1 (Form 1065): a partner's share of a partnership's year, read off the form's face by where things sit.

The face is a printed form, not lines of text: a value sits in its box under the box's number, with the box's code
(boxes 11, 13 and 14 to 20) at its left, so in reading order a value lands next to whatever label is beside it on
the page. It's read from the page's words and their positions instead (`text.words`). Part III's two columns are
found by their first boxes ("1 Ordinary business income" and "14 Self-employment earnings"), and each value goes
to the nearest box number above it in its column. Parts I and II are read by their labels: a value or a check mark
on a label's row, with the Beginning and Ending columns told apart by their headings.

Every value keeps its page, its position and its text exactly as printed, and `verify` checks each is still there.
Whatever doesn't add up (the capital account, a share over 100%) is a failed check; whatever the face can't settle
(an amount on the partnership's statement, a final K-1, more than one activity) is a question.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from .prior import CENT, YEAR, Check, Question, _number, amount

BOX = re.compile(r"^(\d{1,2})([abc])?$")
GLUED = re.compile(r"^(\d{1,2})([A-Z][a-z].*)$")  # "14Self-employment": a box number run into its label
CODE = re.compile(r"^([A-Z]{1,2})(\*)?$")
SHARE = re.compile(r"^\d{1,3}\.\d+$")  # "12.3456789", the % sign printed apart
EIN = re.compile(r"^(?:\d{2}|[X*]{2})-(?:\d{3}|[X*]{3})\d{4}$")  # some partner copies print it XX-XXX1234
TIN = re.compile(r"^(?:\d{3}|[X*]{3})-(?:\d{2}|[X*]{2})-(\d{4})$")  # the partner's, often printed XXX-XX-1234
MARKS = {"X", "x", "4", "✔", "✓", "✗"}  # a check mark: ZapfDingbats draws one as the letter "4"
STATEMENT = {"STMT", "*STMT", "STMT*", "*"}
CODED = {"11", "13", "14", "15", "17", "18", "19", "20"}  # boxes whose every amount has a code
CHECKBOXES = {"16", "22", "23"}
ROW = 4.5  # points: a value or mark sits up to this far above or below its label's line
BAND = 7.0  # points: how far a box number or code sits from the column's first box number
CAPITAL = {  # item L's lines, by the first two words of each label
    "beginning": ("Beginning", "capital"), "contributed": ("Capital", "contributed"),
    "current_year": ("Current", "year"), "other": ("Other", "increase"),
    "withdrawals": ("Withdrawals", "and"), "ending": ("Ending", "capital"),
}
LIABILITIES = {"nonrecourse": "Nonrecourse", "qualified_nonrecourse": "financing", "recourse": "Recourse"}
SHARES = ("Profit", "Loss", "Capital")
BOXES = {
    "1": "Ordinary business income (loss)", "2": "Net rental real estate income (loss)",
    "3": "Other net rental income (loss)", "4a": "Guaranteed payments for services",
    "4b": "Guaranteed payments for capital", "4c": "Total guaranteed payments", "5": "Interest income",
    "6a": "Ordinary dividends", "6b": "Qualified dividends", "6c": "Dividend equivalents", "7": "Royalties",
    "8": "Net short-term capital gain (loss)", "9a": "Net long-term capital gain (loss)",
    "9b": "Collectibles (28%) gain (loss)", "9c": "Unrecaptured section 1250 gain",
    "10": "Net section 1231 gain (loss)", "11": "Other income (loss)", "12": "Section 179 deduction",
    "13": "Other deductions", "14": "Self-employment earnings (loss)", "15": "Credits",
    "16": "Schedule K-3 is attached", "17": "Alternative minimum tax (AMT) items", "18": "Tax-exempt income and "
    "nondeductible expenses", "19": "Distributions", "20": "Other information", "21": "Foreign taxes paid or accrued",
    "22": "More than one activity for at-risk purposes", "23": "More than one activity for passive activity purposes",
}


@dataclass
class Value:
    """One amount as printed on the face: what it is, where it sits, and its text exactly."""

    amount: Decimal | None  # None: the face says the amount is on the partnership's statement
    page: int
    top: float
    x0: float
    quote: str


@dataclass
class Item:
    box: str
    code: str  # "" for a box without codes
    value: Value
    statement: bool = False  # the code or amount points to the partnership's attached statement


@dataclass
class StatementItem:
    """An amount on the partnership's attached statement, for a box and code the face sends there."""

    box: str
    code: str
    description: str
    amount: Decimal
    section: str  # the statement's heading above it ("LINE 20, CODE Z SECTION 199A INFORMATION")
    page: int
    quote: str  # the line exactly as `text.pages` gives it
    business: str = ""  # the trade or business a 199A amount is for ("Real Estate for Development")
    aggregate: str = ""  # a total for an aggregated group of businesses: it repeats their amounts
    members: tuple[str, ...] = ()  # the businesses in that group

    @property
    def kind(self) -> str:
        """Which Section 199A amount this is: qbi, wages, ubia, reit or ptp ("" for another amount)."""
        text = self.description.upper()
        for kind, words in QBI_KINDS:
            if any(w in text for w in words):
                return kind
        return ""


QBI_KINDS = (("wages", ("W-2 WAGES",)), ("ubia", ("UBIA", "UNADJUSTED BASIS")), ("reit", ("REIT DIVIDENDS",)),
             ("ptp", ("PUBLICLY TRADED PARTNERSHIP",)), ("qbi", ("QUALIFIED BUSINESS INCOME",)))


@dataclass
class K1:
    file: str
    page: int
    year: int | None = None
    ein: str = ""
    partnership: str = ""
    partner: str = ""  # the last four digits of the partner's SSN or TIN (E): whose K-1 this is
    copy_of: int | None = None  # the page of an earlier face this one repeats exactly
    final: bool = False
    amended: bool = False
    publicly_traded: bool = False
    general_partner: bool | None = None  # None: neither box checked
    domestic: bool | None = None
    entity_type: str = ""  # I1, "Individual"
    retirement_plan: bool = False  # I2: an IRA's K-1, whose items stay in the account
    shares: dict[str, dict[str, Value]] = field(default_factory=dict)  # J: "profit" -> {"beginning", "ending"}
    liabilities: dict[str, dict[str, Value]] = field(default_factory=dict)  # K1
    lower_tier: bool = False  # K2
    guaranteed: bool = False  # K3
    capital: dict[str, Value] = field(default_factory=dict)  # L
    built_in_gain: bool | None = None  # M
    section_704c: dict[str, Value] = field(default_factory=dict)  # N
    items: list[Item] = field(default_factory=list)  # Part III, in box order
    k3_attached: bool = False  # box 16
    more_than_one_activity: dict[str, bool] = field(default_factory=dict)  # boxes 22, 23
    statement: list[StatementItem] = field(default_factory=list)  # from the pages after the face
    checks: list[Check] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    def check(self, what: str, ok: bool, quote: str = "") -> None:
        """`what` names boxes and lines only; the amounts go in `quote`, which is printed masked."""
        self.checks.append(Check(what, ok, self.page, quote))

    def ask(self, question: str, quote: str = "") -> None:
        self.questions.append(Question(question, self.page, quote))

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def box(self, box: str, code: str = "") -> list[Item]:
        return [i for i in self.items if i.box == box and (not code or i.code == code)]

    def values(self) -> list[Value]:
        """Every value read off the face, for `verify`."""
        found = [i.value for i in self.items]
        found += [v for part in (self.shares, self.liabilities) for cols in part.values() for v in cols.values()]
        return found + list(self.capital.values()) + list(self.section_704c.values())

    def to_json(self) -> dict:
        def plain(obj):
            if isinstance(obj, Decimal):
                return str(obj)
            if isinstance(obj, dict):
                return {k: plain(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [plain(v) for v in obj]
            return obj

        out = plain(asdict(self))
        for row in out["items"]:
            row["label"] = BOXES.get(row["box"], "")
        return out


def read(name: str, pages: dict[int, list[dict]], texts: list[str] | None = None) -> list[K1]:
    """The K-1 faces among a document's pages, given each page's words (`text.words`) by page number.

    With the document's text (`text.pages`), each face also gets the amounts on the statement pages after it, up to
    the next face. A face that repeats an earlier one exactly (the same partnership, partner and amounts) is a second
    copy: it's kept, marked `copy_of`, and counts once. The same amounts for another partner (a spouse) are their
    own K-1.
    """
    found = [k1 for n, words in sorted(pages.items()) if (k1 := face(name, n, words)) is not None]
    for n, k1 in enumerate(found):
        if texts is not None:
            stop = found[n + 1].page - 1 if n + 1 < len(found) else len(texts)
            k1.statement = statements(texts, k1.page + 1, stop)
            _aggregate_checks(k1)
        _statement_questions(k1)
    for n, later in enumerate(found):
        if first := next((k for k in found[:n] if k.copy_of is None and _same(k, later)), None):
            later.copy_of = first.page
            later.questions.clear()  # asked once, on the first copy
    return found


def _same(a: K1, b: K1) -> bool:
    return (a.ein, a.partner, [v.quote for v in a.values()]) == (b.ein, b.partner, [v.quote for v in b.values()])


def is_face(page_text: str) -> bool:
    """Whether a page's text (`text.pages`) could be a K-1's face: worth reading its words for."""
    return "Ordinary business income" in page_text and "Self-employment" in page_text and "Part III" in page_text


def face(name: str, page: int, words: list[dict]) -> K1 | None:
    """One K-1 face, or None if the page isn't one (no "1 Ordinary" and "14 Self-employment" boxes)."""
    words = _unglued(words)
    left, right = _anchor(words, "1", "Ordinary"), _anchor(words, "14", "Self-employment")
    if left is None or right is None:
        return None
    k1 = K1(file=name, page=page)
    _header(k1, words, left)
    _parts_one_two(k1, [w for w in words if w["x1"] < left["x0"] - BAND])
    _part_three(k1, words, left, right)
    _checks(k1)
    return k1


def _unglued(words: list[dict]) -> list[dict]:
    """Words with a box number run into its label ("14Self-employment", as some preparers' PDFs print them) split
    in two, the number's width its share of the characters."""
    out = []
    for w in words:
        if m := GLUED.match(w["text"]):
            cut = w["x0"] + (w["x1"] - w["x0"]) * len(m.group(1)) / len(w["text"])
            out += [{**w, "text": m.group(1), "x1": cut}, {**w, "text": m.group(2), "x0": cut}]
        else:
            out.append(w)
    return out


def _anchor(words: list[dict], number: str, label: str) -> dict | None:
    for w in words:
        if w["text"] == number and any(o["text"].startswith(label) and _same_row(o, w) and
                                       0 <= o["x0"] - w["x1"] < 20 for o in words):
            return w
    return None


def _same_row(a: dict, b: dict, slack: float = ROW) -> bool:
    return abs(a["top"] - b["top"]) <= slack


def _value(w: dict, page: int) -> Value:
    if w["text"].upper() in STATEMENT:
        return Value(None, page, w["top"], w["x0"], w["text"])
    return Value(amount(w["text"]), page, w["top"], w["x0"], w["text"])


def _marked(words: list[dict], option: dict) -> bool:
    """A check mark in the box just left of an option's text ("X Limited partner")."""
    return any(w["text"] in MARKS and _same_row(w, option) and 0 < option["x0"] - w["x1"] <= 20 for w in words)


def _find(words: list[dict], first: str, second: str | None = None, below: float = -1.0) -> dict | None:
    """The first word `first` (followed on its row by `second`) below `below` points, top to bottom."""
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if w["top"] > below and w["text"] == first and (
                second is None or any(o["text"] == second and _same_row(o, w, 1) and o["x0"] > w["x0"]
                                      for o in words)):
            return w
    return None


def _header(k1: K1, words: list[dict], left: dict) -> None:
    above = [w for w in words if w["top"] < left["top"]]
    for flag in ("Final", "Amended"):
        if (w := _find(above, flag, "K-1")) is not None:
            setattr(k1, flag.lower(), _marked(above, w))
    if (w := _find(words, "calendar", "year")) is not None:
        row = " ".join(o["text"] for o in sorted(words, key=lambda o: o["x0"]) if _same_row(o, w, 1))
        if m := YEAR.search(row):
            k1.year = int(m.group(1))


def _parts_one_two(k1: K1, words: list[dict]) -> None:
    """Parts I and II: the left half of the face, read label by label."""
    if ein := next((w for w in sorted(words, key=lambda w: w["top"]) if EIN.match(w["text"])), None):
        k1.ein = ein["text"]
    if tin := next((m for w in sorted(words, key=lambda w: w["top"]) if (m := TIN.match(w["text"]))), None):
        k1.partner = tin.group(1)
    if (label := _find(words, "B")) is not None:  # the line under "B Partnership's name, address, ..."
        # the first row under it: the next line, or one with a blank line between (some preparers' layouts)
        if rows := sorted({w["top"] for w in words if label["top"] + 3 < w["top"] < label["top"] + 26}):
            k1.partnership = " ".join(w["text"] for w in sorted(words, key=lambda w: w["x0"])
                                      if abs(w["top"] - rows[0]) <= 1)
    if (w := _find(words, "publicly", "traded")) is not None and (check := _row_word(words, w, "Check")):
        k1.publicly_traded = _marked(words, check)
    for attr, yes, no in (("general_partner", "General", "Limited"), ("domestic", "Domestic", "Foreign")):
        a, b = _find(words, yes), _find(words, no)
        if a is not None and _marked(words, a):
            setattr(k1, attr, True)
        elif b is not None and _marked(words, b):
            setattr(k1, attr, False)
    if (w := _find(words, "partner?")) is not None:
        k1.entity_type = " ".join(o["text"] for o in sorted(words, key=lambda o: o["x0"])
                                  if _same_row(o, w) and o["x0"] > w["x1"] + 3)
    if (w := _find(words, "retirement")) is not None:
        here = _row_word(words, w, "here") or w
        k1.retirement_plan = any(o["text"] in MARKS and _same_row(o, w) and o["x0"] > here["x1"] for o in words)
    j = _find(words, "J")
    for label in SHARES:
        if (w := _find(words, label, below=j["top"] if j else -1)) is not None and w["x0"] < 100:
            k1.shares[label.lower()] = _columns(words, w, k1.page, SHARE)
    k = _find(words, "liabilities:")
    for key, label in LIABILITIES.items():
        if k is not None and (w := _find(words, label, below=k["top"])) is not None and w["x0"] < 100:
            k1.liabilities[key] = _columns(words, w, k1.page)
    # K2's box ends its one line; K3's label takes two, and its box can sit at the end of either
    for attr, word, lines in (("lower_tier", "lower-tier", 0), ("guaranteed", "guarantees", 14)):
        if (w := _find(words, word)) is not None:
            setattr(k1, attr, any(o["text"] in MARKS and w["top"] - ROW <= o["top"] <= w["top"] + lines + ROW
                                  and o["x0"] > max(w["x1"], 240) for o in words))
    if (analysis := _find(words, "Analysis")) is not None:
        for key, (first, second) in CAPITAL.items():
            if (w := _find(words, first, second, below=analysis["top"])) is not None and \
                    (v := _right_of(words, w, k1.page)) is not None:
                k1.capital[key] = v
    if (w := _find(words, "built-in")) is not None:
        yes, no = _find(words, "Yes", below=w["top"]), _find(words, "No", below=w["top"])
        if yes is not None and _marked(words, yes):
            k1.built_in_gain = True
        elif no is not None and _marked(words, no):
            k1.built_in_gain = False
    if (w := _find(words, "704(c)")) is not None:
        for key in ("Beginning", "Ending"):
            if (row := _find(words, key, below=w["top"])) is not None and \
                    (v := _right_of(words, row, k1.page)) is not None:
                k1.section_704c[key.lower()] = v


def _row_word(words: list[dict], w: dict, text: str) -> dict | None:
    return next((o for o in words if o["text"] == text and _same_row(o, w)), None)


def _right_of(words: list[dict], label: dict, page: int) -> Value | None:
    """The amount at the right end of a label's row (item L, N)."""
    found = [o for o in words if _same_row(o, label) and o["x0"] > label["x0"] + 60 and _number(o["text"])]
    return _value(max(found, key=lambda o: o["x1"]), page) if found else None


def _columns(words: list[dict], label: dict, page: int, pattern: re.Pattern | None = None) -> dict[str, Value]:
    """A row's Beginning and Ending values, told apart by the nearest such headings above the row."""
    heads = [h for h in words if h["text"] in ("Beginning", "Ending") and h["top"] < label["top"] and
             h["x0"] > label["x0"] + 40]
    begin = max((h for h in heads if h["text"] == "Beginning"), key=lambda h: h["top"], default=None)
    end = max((h for h in heads if h["text"] == "Ending"), key=lambda h: h["top"], default=None)
    if begin is None or end is None:
        return {}
    middle = ((begin["x0"] + begin["x1"]) / 2 + (end["x0"] + end["x1"]) / 2) / 2
    out: dict[str, Value] = {}
    for o in words:
        if _same_row(o, label) and o["x0"] > label["x1"] and (pattern.match(o["text"]) if pattern else
                                                               _number(o["text"])):
            out["beginning" if (o["x0"] + o["x1"]) / 2 < middle else "ending"] = _value(o, page)
    return out


def _part_three(k1: K1, words: list[dict], left: dict, right: dict) -> None:
    """Part III: each value under the nearest box number above it in its column, with the code at its left."""
    columns = {id(col): sorted((w for w in words if BOX.match(w["text"]) and abs(w["x0"] - col["x0"]) <= BAND and
                                w["top"] >= col["top"] - 1), key=lambda w: w["top"]) for col in (left, right)}
    # below the last box's line (23, or 21) is the form's footer: "(Form 1065) 2025" isn't box 21's amount
    end = max(n["top"] for numbers in columns.values() for n in numbers) + 12
    for col, nxt in ((left, right), (right, None)):
        x = col["x0"]
        numbers = columns[id(col)]
        inside = [w for w in words if w["x0"] > x + 12 and (nxt is None or w["x1"] < nxt["x0"] - 4) and
                  col["top"] + 1 < w["top"] < end]
        # a code sits under its box number (centered) or just right of it, before the amount
        codes = [w for w in words if CODE.match(w["text"]) and x - BAND <= w["x0"] <= x + 14]
        for n, number in enumerate(numbers):
            box = number["text"]
            stop = numbers[n + 1]["top"] if n + 1 < len(numbers) else float("inf")
            span = [w for w in inside if number["top"] < w["top"] < stop - 1 and not _same_row(w, number, 1.5)]
            if box in CHECKBOXES:
                checked = any(w["text"] in MARKS for w in span) or any(
                    w["text"] in MARKS and _same_row(w, number, 1.5) and w["x0"] > number["x1"] for w in inside)
                if box == "16":
                    k1.k3_attached = checked
                else:
                    k1.more_than_one_activity[box] = checked
                continue
            pointed: set[float] = set()  # rows already pointing to the statement: "* STMT" is one item
            for w in sorted(span, key=lambda w: (w["top"], w["x0"])):
                to_statement = w["text"].upper() in STATEMENT or (
                    w["text"] == "See" and _row_word(span, w, "statement") is not None)
                if not (_number(w["text"]) or to_statement) or (to_statement and w["top"] in pointed):
                    continue
                code = next((c for c in codes if _same_row(c, w, 3) and c["top"] > number["top"] + 1.5), None)
                letters, star = (CODE.match(code["text"]).groups() if code else ("", None))
                if to_statement:
                    pointed.add(w["top"])
                    value = Value(None, k1.page, w["top"], w["x0"], w["text"])
                else:
                    value = _value(w, k1.page)
                k1.items.append(Item(box, letters, value, statement=bool(star) or value.amount is None))


def _checks(k1: K1) -> None:
    cap = k1.capital
    if {"beginning", "ending"} <= cap.keys():
        moved = sum((cap[k].amount or Decimal(0) for k in ("contributed", "current_year", "other") if k in cap),
                    Decimal(0))
        out = abs(cap["withdrawals"].amount or Decimal(0)) if "withdrawals" in cap else Decimal(0)
        total = cap["beginning"].amount + moved - out
        k1.check("item L: the beginning capital account plus this year's changes is the ending",
                 abs(total - cap["ending"].amount) <= CENT, f"{total} against {cap['ending'].quote}")
    for kind, cols in k1.shares.items():
        for col, v in cols.items():
            k1.check(f"item J: the {col} {kind} share is between 0% and 100%", 0 <= v.amount <= 100, v.quote)
    for item in k1.items:
        if item.box in CODED and not item.statement:  # a statement gives its own codes
            k1.check(f"box {item.box}: its amount has a code", bool(item.code), item.value.quote)
    if k1.retirement_plan:
        return  # an IRA's items stay in the account: nothing on this K-1 goes on the return, so nothing to ask
    if k1.final:
        k1.ask("a final K-1: was the partnership interest sold or the partnership wound up? Its passive losses "
               "carried over from earlier years may be allowed in full this year.")
    for box, checked in k1.more_than_one_activity.items():
        if checked:
            k1.ask(f"box {box}: the partnership has more than one activity; its statement says how the items "
                   "split between them")
    paid = sum((i.value.amount or Decimal(0) for i in k1.box("19")), Decimal(0))
    on_statement = any(i.statement for i in k1.box("19"))
    if "withdrawals" in k1.capital and not on_statement and paid != abs(k1.capital["withdrawals"].amount):
        k1.ask("box 19's distributions aren't item L's withdrawals: property distributed at its basis?",
               f"{paid} against {k1.capital['withdrawals'].quote}")


def _aggregate_checks(k1: K1) -> None:
    """Each aggregated group's 199A total is the sum of the same amount for the businesses in the group."""
    for total in k1.statement:
        if not total.aggregate or not total.kind:
            continue
        parts = [s for s in k1.statement if not s.aggregate and s.business in total.members and s.kind == total.kind
                 and (s.box, s.code) == (total.box, total.code)]
        if not total.members or not parts:
            k1.ask(f"box {total.box} code {total.code}: an aggregated group's {total.kind} total, and no amounts for "
                   "the businesses in the group to check it against", total.quote)
            continue
        k1.check(f"box {total.box} code {total.code}: an aggregated group's {total.kind} is its businesses' added up",
                 abs(sum(s.amount for s in parts) - total.amount) <= CENT,
                 f"{sum(s.amount for s in parts)} against {total.quote.strip()}")


def _statement_questions(k1: K1) -> None:
    """A box the face sends to the statement is a question only when the statement gives it no amount."""
    if k1.retirement_plan:
        return
    for item in k1.items:
        if item.statement and not any(s.box == item.box and (s.code == item.code or not item.code)
                                      for s in k1.statement):
            k1.ask(f"box {item.box}" + (f" code {item.code}" if item.code else "") +
                   ": the amount is on the partnership's statement, and no statement page after the face gives it",
                   item.value.quote)


# "LINE 20, CODE Z ...", "LINE 20Z ...", "Line 20, AF ...", "Box 19C: ...", "Line 13 - Other Deductions"
REF = re.compile(r"^\s*(?i:line|box)\s+(\d{1,2})\s*(?:[,:-]\s*)?(?:(?i:code)\s+)?([A-Z]{1,2})?\b\s*[:-]?\s*")
# "Schedule K-1, Line 20, Code Z", "SCHEDULE K-1 BUSINESS INTEREST EXPENSE, BOX 20, CODE N"
ANYWHERE = re.compile(r"(?i:line|box)\s+(\d{1,2}),?\s+(?i:code)\s+([A-Z]{1,2})\b")
# a statement's own title with no box in it ("SCHEDULE K-1 WITHDRAWALS AND DISTRIBUTIONS"): it ends the box above
TITLE = re.compile(r"^\s*SCHEDULE K-1\b")
ROW_CODE = re.compile(r"^\s*([A-Z]{1,2})(?:-\s|\s{2,})\s*")  # a table row: "C    Meals (general)", "AE- DEDUCTIONS"
# the amount ending a line: set apart by a column gap, or a "$", "(" or minus sign (never "Line 1", an EIN, or a %);
# some preparers print whole dollars with a period after them ("1,234.")
TRAILING = re.compile(r"(?:^\s*|\s{2,}|\s(?=-?\$|\(|-\d))(-?\$?-?\(?\$?[\d,]*\d(?:\.\d+)?\)?)\.?\s*$")
COLUMN_HEADS = re.compile(r"^\s*(?:Code\s+)?Description\s+Amount\s*$|^\s*Explanation\s*$", re.IGNORECASE)
SHORT = 30  # characters: a label wrapped onto the lines around its amount is short
# an underlined heading, as layout text draws it: "S_e_c_t_i_o_n_" (an underlined amount, "____5_", isn't one)
HEADING = re.compile(r"(?:[A-Za-z0-9]_){4,}")
LONE_YEAR = re.compile(r"^\s*(?:19|20)\d\d\s*$")  # a tax year on a line of its own, not an amount
RECONCILE = re.compile(r"(?i)\b(?:section|item)\s+L\b")  # item L's reconciliation repeats the face's amounts
BUSINESS = re.compile(r"(?i)^\s*trade or business:\s*(.+?)\s*$")  # whose 199A amounts follow
GROUPING = re.compile(r"(?i)\belected to aggregate\b")  # the businesses named next are one group
AGGREGATE = re.compile(r"(?i)^\s*totals?:\s*(aggregated group\b.*?)\s*$")  # the group's totals follow


def statements(texts: list[str], first: int, last: int) -> list[StatementItem]:
    """The amounts on pages `first` to `last` (1-based) that a line or table ties to a box, and its code if any.

    A "Line 20, Code Z" or "Box 19C" reference sets the box and code for the lines under it, until the next
    reference or heading. Each line ending in an amount under one becomes an item, its description the line's
    text (or the lines around a lone amount, where a label wraps around it). Totals and item L's reconciliation,
    which repeat amounts given elsewhere, are left out. An aggregated group's 199A totals are kept, marked as
    the group's, so they can be checked against its businesses' amounts and never added to them.
    """
    found: list[StatementItem] = []
    for page in range(first, min(last, len(texts)) + 1):
        lines = [raw.replace("_", "") for raw in texts[page - 1].splitlines()]
        raws = texts[page - 1].splitlines()
        box = code = section = ""
        reconciling = False  # under item L's reconciliation, whose rows repeat the face
        business = aggregate = ""
        members: list[str] = []
        grouping = False  # between "elected to aggregate" and the group's totals
        tied = ("", "")  # the box and code the business or group was named under: it holds only there
        for n, line in enumerate(lines):
            if not line.strip() or COLUMN_HEADS.match(line) or LONE_YEAR.match(line):
                continue  # a table's column headings neither start nor end a section
            if trade := BUSINESS.match(line):
                business, aggregate, tied = trade.group(1), "", (box, code)
                if grouping:
                    members.append(business)
                continue
            if GROUPING.search(line):
                grouping, members = True, []
                continue
            if group := AGGREGATE.match(line):
                business, aggregate, grouping, tied = "", group.group(1), False, (box, code)
                continue
            ref = REF.match(line)
            ends = TRAILING.search(line[ref.end():] if ref else line)
            if not ref and not ends and (mid := ANYWHERE.search(line)):
                box, code, section, reconciling = mid.group(1), mid.group(2), line.strip(), False
                continue
            if not ref and not ends and TITLE.match(line):
                box, code, section, reconciling = "", "", line.strip(), False
                continue
            if RECONCILE.search(line):
                box, code, section, reconciling = "", "", line.strip(), True
                continue
            if reconciling and (ends or not (ref or HEADING.search(raws[n]))):
                continue  # a reconciliation row; a reference or heading without an amount ends it
            reconciling = False
            if ref:
                box, code, section = ref.group(1), ref.group(2) or "", line.strip()
                rest = line[ref.end():]
            elif HEADING.search(raws[n]):  # another heading ends the reference above it
                box, code, section = "", "", line.strip()
                continue
            elif box and (row := ROW_CODE.match(line)):
                code, rest = row.group(1), line[row.end():]
            else:
                rest = line
            if not box or not (ends := TRAILING.search(rest)):
                continue
            description = rest[:ends.start()].strip(" .:-")
            if description.lower().startswith("total"):
                continue
            around = [lines[i].strip() for i in (n - 1, n + 1) if 0 <= i < len(lines)]
            # rule lines (underlines drawn in characters) are no part of a label
            text_only = [a for a in around if a and not TRAILING.search(a) and any(c.isalnum() for c in a)]
            if not description:  # a lone amount: its label wraps around it
                description = " ".join(text_only)
            elif len(text_only) == 2 and all(len(a) <= SHORT for a in text_only):  # a label in three lines
                description = f"{text_only[0]} {description} {text_only[1]}"
            if not description or description.lower().startswith("total"):
                continue
            try:
                value = amount(ends.group(1).replace("$", ""))
            except ValueError:
                continue
            item = StatementItem(box, code, description, value, section, page, raws[n].rstrip())
            if (box, code) == tied:
                item.business, item.aggregate = business, aggregate
                item.members = tuple(members) if aggregate else ()
            found.append(item)
    return found


def verify(k1: K1, words: list[dict], texts: list[str] | None = None) -> list[str]:
    """Each face value's text still at its place on its page, and each statement line still on its page."""
    problems = [f"p{v.page}: {v.quote!r} isn't at {v.top}, {v.x0}" for v in k1.values()
                if not any(w["text"] == v.quote and abs(w["top"] - v.top) < 0.6 and abs(w["x0"] - v.x0) < 0.6
                           for w in words)]
    if texts is not None:
        problems += [f"p{s.page}: {s.quote.strip()!r} isn't on the page" for s in k1.statement
                     if s.quote not in texts[s.page - 1]]
    return problems
