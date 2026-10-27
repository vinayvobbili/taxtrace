"""An Indian bank's interest certificate on its deposits: each account's interest and the tax kept on it in a year.

A bank prints one a year, "for the financial year ended 31st March 2026": a row per deposit account, its number,
branch code and type, the balance on March 31, the interest paid and the interest accrued in the year, then the
"Total Tax Deducted" (the TDS, with cess and surcharge) and a second tax column, then a TOTAL row. It is what gives
a term deposit's TDS: a deposit that adds its interest to itself pays none out, so its statements show no TDS row,
only its value falling when the tax is taken from the interest at the year's end.

Checks: the rows' interest paid, interest accrued and both tax columns add up to the TOTAL row. Nothing that names
the holder is kept, and of an account number only its last four digits.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from .prior import Check, Question, _rows
from .statement import MONEY, _last_four, money

YEAR_ENDED = re.compile(r"financial year ended\s+(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\.?,?\s+(\d{4})", re.I)
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
# the tax column after "Total Tax Deducted": its own heading's first word, on the heading's first line
SECOND_TAX = re.compile(r"\bTOTAL TAX (\S+) TAX\b", re.I)
ACCOUNT_NUMBER = re.compile(r"[\dX]{8,}")


@dataclass
class Deposit:
    account: str  # the last four digits
    type: str  # as the bank prints it
    balance: Decimal  # on the year's last day
    paid: Decimal  # interest paid in the year
    accrued: Decimal  # interest accrued in the year, not paid
    tax: Decimal  # the total tax deducted: the TDS, with cess and surcharge
    second_tax: Decimal  # the column after it, headed `Certificate.second_tax_label`
    page: int
    quote: str


@dataclass
class Certificate:
    file: str
    year_ended: str = ""  # dd-mm-yyyy, the financial year's last day
    second_tax_label: str = ""  # the heading of the tax column after the total tax deducted
    deposits: list[Deposit] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def check(self, what: str, ok: bool, page: int, quote: str = "") -> None:
        self.checks.append(Check(what, ok, page, quote))

    def to_json(self) -> dict:
        return {"form": "INTEREST CERTIFICATE", **asdict(self)}


def is_certificate(page: str) -> bool:
    flat = " ".join(page.split()).lower()
    return "interest" in flat and "tax deducted" in flat and bool(YEAR_ENDED.search(flat))


def read(name: str, pages: list[str], words: dict[int, list[dict]]) -> Certificate:
    found = Certificate(name)
    flat = " ".join(" ".join(pages).split())
    if (m := YEAR_ENDED.search(flat)) and m.group(2)[:3].lower() in MONTHS:
        found.year_ended = f"{int(m.group(1)):02d}-{MONTHS.index(m.group(2)[:3].lower()) + 1:02d}-{m.group(3)}"
    else:
        found.questions.append(Question("the financial year the certificate is for wasn't read", 1, ""))
    totals: tuple[list[Decimal], int, str] | None = None
    for n in sorted(words):
        for row in _rows(words[n]):
            texts = [w["text"] for w in row]
            text = " ".join(texts)
            if m := SECOND_TAX.search(text):
                found.second_tax_label = f"{m.group(1)} TAX DEDUCTED"
            amounts = [money(t) for t in texts if MONEY.match(t)]
            if texts[0].upper() == "TOTAL" and amounts:
                totals = (amounts, n, text)
            elif ACCOUNT_NUMBER.fullmatch(texts[0]) and (account := _last_four(texts[0])):
                if len(amounts) != 5:
                    found.questions.append(Question(
                        f"account {account}'s row doesn't read as the balance, interest paid, interest accrued and "
                        "two tax columns", n, text))
                    continue
                # between the account and the balance: the branch code (digits), then the account's type
                first = next(i for i, t in enumerate(texts) if MONEY.match(t))
                kind = " ".join(t for t in texts[1:first] if not t.isdigit())
                found.deposits.append(Deposit(account, kind, *amounts, page=n, quote=text))
    if not found.deposits:
        found.questions.append(Question("no deposit account's row was read", 1, ""))
    elif totals is None:
        found.questions.append(Question("the certificate's TOTAL row wasn't read", found.deposits[-1].page, ""))
    else:
        amounts, n, text = totals
        added = [sum((getattr(d, f) for d in found.deposits), Decimal(0))
                 for f in ("paid", "accrued", "tax", "second_tax")]
        found.check("the rows add up to the TOTAL row (interest paid, accrued and both tax columns)",
                    amounts == added, n, text)
    return found
