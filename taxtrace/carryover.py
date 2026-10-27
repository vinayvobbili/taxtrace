"""The preparer's Carryover Worksheet: what a filed return carries to next year's, on one page.

Drake prints it after the return ("List of items that will carryover to the <year> tax return"), in sections
(Itemized Deductions, Expenses, Losses, Credits, Other, Passive Activity, At Risk Limitations). A row is a label
and its amounts: one under "Carryover Amount", or a regular tax and an AMT amount ("AMT ... Reg. Tax ..."), or one
each for the taxpayer and the spouse (IRA basis). Rows are read by position (`text.words`); a label ends at its
leader dots, and a number right after a word ("Estimated Tax Payment 3") is part of the label, not an amount.
Anything under Passive Activity or At Risk Limitations is asked about: no copy seen so far had rows there.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .prior import Question, _rows, amount

HEADING = "Carryover Worksheet"
TO_YEAR = re.compile(r"carryover\s+to\s+the\s+((?:19|20)\d\d)\s+tax\s+return", re.IGNORECASE)
VALUE = re.compile(r"^-?[\d,]*\d(?:\.\d*)?$")
MARKERS = {"AMT": "amt", "AM": "amt", "Reg.": "regular", "Taxpayer": "taxpayer", "Spouse": "spouse"}
UNREAD = ("Passive Activity", "At Risk Limitations")
LEFT = 300  # amounts sit right of the labels' column


@dataclass
class Item:
    section: str  # "Credits"
    label: str  # "Foreign Tax credit"
    amounts: dict[str, object]  # "amount", or "regular" and "amt", or "taxpayer" and "spouse": Decimal
    page: int
    quote: str


def is_page(page: str) -> bool:
    return any(HEADING in " ".join(ln.split()) for ln in page.splitlines()[:3] if ln.strip())


def to_year(page: str) -> int | None:
    """The year the worksheet carries to, from its own heading."""
    m = TO_YEAR.search(" ".join(page.split()[:40]))
    return int(m.group(1)) if m else None


def read(n: int, words: list[dict]) -> tuple[list[Item], list[Question]]:
    items: list[Item] = []
    questions: list[Question] = []
    section = ""
    started = False
    for row in _rows(words):
        texts = [w["text"] for w in row]
        if not started:
            started = "Carryover" in texts and "Amount" in texts
            if started:
                section = " ".join(w["text"] for w in row if w["x0"] < LEFT)
            continue
        if len(row) == 1 and len(texts[0]) == 1:
            continue  # a letter of the "Client Copy" watermark
        if row[0]["x0"] < 50:  # a section's heading, or the form's id at the foot ("WK_CARRY.LD")
            if all(t.isalpha() for t in texts):
                section = " ".join(texts)
            continue
        label, amounts = _split(row)
        quote = " ".join(texts)
        if section in UNREAD:
            questions.append(Question(f"The Carryover Worksheet lists something under {section}: read it by hand.",
                                      n, quote))
            continue
        if amounts:
            items.append(Item(section, label, amounts, n, quote))
    return items, questions


def _split(row: list[dict]) -> tuple[str, dict]:
    """A row's label, cut at its leader dots, and its amounts, each under the marker left of it."""
    label: list[str] = []
    amounts: dict = {}
    key, prev = "amount", None
    for w in row:
        t = w["text"]
        if t in MARKERS and w["x0"] >= LEFT:
            key = MARKERS[t]
        elif t in ("T", "Tax") and prev is not None and prev["text"] in ("AM", "Reg."):
            pass  # "AM T", "Reg. Tax"
        elif (w["x0"] >= LEFT and VALUE.match(t)
              and (prev is None or prev["text"].endswith(".") or w["x0"] - prev["x1"] > 10)):
            amounts[key] = amounts.get(key, 0) + amount(t)
        elif not amounts and key == "amount":
            label.append(t)
        prev = w
    return re.sub(r"\.{2,}.*$", "", " ".join(label)).strip(), amounts
