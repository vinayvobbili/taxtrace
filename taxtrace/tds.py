"""India's quarterly TDS certificate: what a bank paid a customer in a quarter and the tax it deducted and deposited.

A bank issues one per quarter: Form 16A until March 2026, Form 131 (India's Income-tax Act, 2025) from April 2026.
Both give the quarter ("From 01-Jan-2026 To 31-Mar-2026", or "01/Apr/2026 ... 30/Jun/2026"), the deductor (the
bank), a "Summary of payment" (each payment or credit of interest: the amount, the nature of payment's section
code, the date), the quarter's row (Q1-Q4: the tax deducted and the tax deposited) and the challans that paid the
tax to the government (each one's tax and the day it was deposited). The tax isn't given per payment or per
account: the certificate covers every account the customer holds there.

India's quarters fall inside calendar quarters, so a certificate says exactly how much tax the bank took from the
customer in three months of the US year. A term deposit's statements show no TDS row, only its value: the foreign
side compares the quarter's tax with the TDS it found and counts the rest as tax taken from a deposit.

Checks: the payments add up to their total, the challans to theirs, and the challans to the quarter's deposited
tax. Nothing that names the customer is kept: not their name, their PAN or their address.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from .prior import Check, Question, _rows

FORM = re.compile(r"\bFORM\s+NO\.?\s*(16A|131)\b", re.I)
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
DAY = re.compile(r"^(\d{2})[-/](\d{2}|[A-Za-z]{3})[-/](\d{4})$")  # 31-03-2026, 31-Mar-2026, 31/Mar/2026
PERIOD = re.compile(r"(\d{2}[-/][A-Za-z]{3}[-/]\d{4})\s+(\d{2}[-/][A-Za-z]{3}[-/]\d{4})")
MONEY = re.compile(r"^₹?(\d{1,3}(?:,\d{2,3})+|\d+)\.\d{2}$")
QUARTER = re.compile(r"^Q[1-4]$")


def _day(printed: str) -> str:
    """'31/Mar/2026', '31-Mar-2026' or '31-03-2026' as '31-03-2026'."""
    d, m, y = DAY.match(printed).groups()
    month = m if m.isdigit() else f"{MONTHS.index(m.lower()) + 1:02d}"
    return f"{d}-{month}-{y}"


def _money(printed: str) -> Decimal:
    return Decimal(printed.lstrip("₹").replace(",", ""))


@dataclass
class Line:
    on: str  # dd-mm-yyyy
    amount: Decimal  # a payment's amount, or a challan's tax
    page: int
    quote: str


@dataclass
class Certificate:
    file: str
    number: str = ""  # the form's: "16A" or "131"
    deductor: str = ""  # the bank's name, as printed
    start: str = ""  # the quarter, dd-mm-yyyy
    end: str = ""
    quarter: str = ""  # India's: "Q4" of its year
    deducted: Decimal | None = None
    deposited: Decimal | None = None
    payments: list[Line] = field(default_factory=list)  # interest paid or credited in the quarter
    challans: list[Line] = field(default_factory=list)  # the tax paid to the government, and when
    checks: list[Check] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def check(self, what: str, ok: bool, page: int, quote: str = "") -> None:
        self.checks.append(Check(what, ok, page, quote))

    def to_json(self) -> dict:
        return {"form": "TDS CERTIFICATE", **asdict(self)}


def is_certificate(page: str) -> bool:
    flat = " ".join(page.split())
    return bool(FORM.search(flat)) and "Summary of payment" in flat


def read(name: str, pages: list[str], words: dict[int, list[dict]]) -> Certificate:
    found = Certificate(name)
    flat = " ".join(" ".join(pages).split())
    if m := FORM.search(flat):
        found.number = m.group(1).upper()
    if m := PERIOD.search(flat):
        found.start, found.end = _day(m.group(1)), _day(m.group(2))
    else:
        found.questions.append(Question("the quarter the certificate is for wasn't read", 1, ""))
    section, totals = "", {}  # what part of the form a row is in; each part's total row
    deductor_next = False
    for n in sorted(words):
        for row in _rows(words[n]):
            texts = [w["text"] for w in row]
            text = " ".join(texts)
            amounts = [_money(t) for t in texts if MONEY.match(t)]
            days = [_day(t) for t in texts if DAY.match(t)]
            if deductor_next:  # Form 16A: the deductor's name heads the left column under its label
                found.deductor = " ".join(w["text"] for w in row if w["x0"] < 300)
                deductor_next = False
            if "Name and address of the" in text and not found.deductor:
                deductor_next = True
            elif texts[0] == "Name" and not found.deductor and found.number == "131":  # Part A's first row
                found.deductor = " ".join(w["text"] for w in row[1:])
            if "Summary of payment" in text:
                section = "payments"
            elif "Summary of tax deducted" in text:
                section = "quarter"
            elif "DETAILS OF TAX DEDUCTED AND DEPOSITED" in text:
                section = "book" if "BOOK" in text else "challans"
            elif texts[0] == "Total" and amounts:
                totals.setdefault(section, (amounts, n, text))
            elif section == "quarter" and QUARTER.match(texts[0]) and len(amounts) >= 2:
                found.quarter, found.deducted, found.deposited = texts[0], amounts[0], amounts[-1]
            elif section in ("payments", "challans", "book") and texts[0].isdigit() and amounts and days:
                line = Line(days[0], amounts[0], n, text)
                if section == "payments":
                    found.payments.append(line)
                elif amounts[0]:
                    found.challans.append(line)
    if found.deducted is None:
        found.questions.append(Question("the quarter's tax deducted wasn't read", 1, ""))
        return found
    for part, lines, what in (("payments", found.payments, "the payments add up to their total"),
                              ("challans", found.challans, "the challans add up to their total")):
        if part in totals:
            amounts, n, text = totals[part]
            found.check(what, sum((x.amount for x in lines), Decimal(0)) == amounts[0], n, text)
    found.check("the challans paid the quarter's deposited tax",
                sum((c.amount for c in found.challans), Decimal(0)) == found.deposited, 1, "")
    return found
