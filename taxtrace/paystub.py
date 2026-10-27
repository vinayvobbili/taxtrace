"""A pay stub: the pay period, the payment date and the income tax withheld, this paycheck and the year so far.

A payroll system's payslip (Oracle's, Workday's, ADP's) prints a header row of labels with the values on the row
under it ("Period Date ... Payment Date", then "01-OCT-2026 - 15-OCT-2026 ... 15-OCT-2026"), and a table of taxes,
one row each, its label then this paycheck's amount and the year to date's ("FIT Withheld 412.50 9,876.54"). Dates
print as 15-OCT-2026, 10/15/2026 or 2026-10-15. Federal income tax is "FIT" or "Federal Income Tax", the state's
"SIT" or "State Income Tax".

What the year's paychecks will withhold in all is the year to date's plus this paycheck's for each one left: the
pay period's length says how often you're paid (weekly, every two weeks, twice a month, monthly), and each later
paycheck is paid as long after its period ends as this one was. A bonus, a stock vesting or a new W-4 changes that,
so it's a question.
"""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from itertools import pairwise

from .prior import Check, Question, _rows, amount

MONEY = re.compile(r"^\(?-?\$?(?:\d{1,3}(?:,\d{3})+|\d+)\.\d{2}\)?$")
DATES = ("%d-%b-%Y", "%m/%d/%Y", "%Y-%m-%d")
TAXES = {"federal": (("FIT",), ("Federal", "Income", "Tax")), "state": (("SIT",), ("State", "Income", "Tax"))}
SLACK = 1.5


@dataclass
class Taxed:
    current: Decimal
    year_to_date: Decimal
    label: str  # as printed: "SIT Withheld (NC)"


@dataclass
class Paystub:
    file: str
    period_start: date | None = None
    period_end: date | None = None
    paid: date | None = None
    withheld: dict[str, Taxed] = field(default_factory=dict)  # "federal", "state"
    checks: list[Check] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    @property
    def frequency(self) -> str:
        """"weekly", "biweekly", "semimonthly" or "monthly", from the pay period's length; "" when it isn't one."""
        if not (self.period_start and self.period_end):
            return ""
        days = (self.period_end - self.period_start).days + 1
        return {7: "weekly", 14: "biweekly"}.get(days, "semimonthly" if 13 <= days <= 16 else
                                                    "monthly" if 28 <= days <= 31 else "")

    def paychecks_left(self) -> int:
        """The paychecks still to come in the payment date's year, after this one."""
        if not (self.paid and self.period_end and self.frequency):
            return 0
        lag, end, left = self.paid - self.period_end, self.period_end, 0
        while True:
            end = _next_end(end, self.frequency)
            if (end + lag).year != self.paid.year:
                return left
            left += 1

    def projected(self, tax: str = "federal") -> Decimal | None:
        """What the year's paychecks withhold in all: the year to date's and this one's for each left."""
        t = self.withheld.get(tax)
        return None if t is None else t.year_to_date + t.current * self.paychecks_left()

    def to_json(self) -> dict:
        return {"form": "paystub", "file": self.file, "year": self.paid.year if self.paid else None,
                "period_start": _iso(self.period_start), "period_end": _iso(self.period_end),
                "paid": _iso(self.paid), "frequency": self.frequency, "paychecks_left": self.paychecks_left(),
                "withheld": {k: {"current": str(t.current), "year_to_date": str(t.year_to_date), "label": t.label}
                             for k, t in self.withheld.items()},
                "projected_federal": str(p) if (p := self.projected()) is not None else None}


def _iso(day: date | None) -> str | None:
    return day.isoformat() if day else None


def _next_end(end: date, frequency: str) -> date:
    last = calendar.monthrange(end.year, end.month)[1]
    if frequency in ("weekly", "biweekly"):
        return end + timedelta(days=7 if frequency == "weekly" else 14)
    if frequency == "semimonthly" and end.day < last:
        return end.replace(day=last)
    after = end + timedelta(days=last - end.day + 1)  # the next month's first day
    return after.replace(day=15) if frequency == "semimonthly" else \
        after.replace(day=calendar.monthrange(after.year, after.month)[1])


def _date(token: str) -> date | None:
    for fmt in DATES:
        try:  # a range's dash can join the date after it: "-31-OCT-2026"
            return datetime.strptime(token.strip("-–"), fmt).date()
        except ValueError:
            continue
    return None


def is_form(words: list[dict]) -> bool:
    """Whether a page's words (`text.words`) are a pay stub's: a payment date and a federal income tax row."""
    texts = [w["text"] for w in words]
    pairs = set(pairwise(texts))
    return ("Payment", "Date") in pairs and (("FIT", "Withheld") in pairs or ("Federal", "Income") in pairs)


def read(name: str, words: list[dict]) -> Paystub:
    stub = Paystub(file=name)
    rows = _rows(words, SLACK)
    for i, row in enumerate(rows):
        texts = [w["text"] for w in row]
        if "Payment" in texts and stub.paid is None and i + 1 < len(rows):
            dates = [d for w in rows[i + 1] if (d := _date(w["text"]))]
            if len(dates) >= 3:
                stub.period_start, stub.period_end, stub.paid = dates[0], dates[1], dates[-1]
        for tax, labels in TAXES.items():
            # the label can share its row with another column's words left of it: what's right of it is the tax's
            at = next((j for label in labels for j in range(len(texts)) if texts[j:j + len(label)] == list(label)),
                      None)
            if tax in stub.withheld or at is None:
                continue
            amounts = [t for t in texts[at:] if MONEY.match(t)]
            if len(amounts) >= 2:
                stub.withheld[tax] = Taxed(amount(amounts[0]), amount(amounts[-1]),
                                           " ".join(t for t in texts[at:] if not MONEY.match(t)))
    _checks(stub)
    return stub


def _checks(stub: Paystub) -> None:
    def check(what: str, ok: bool) -> None:
        stub.checks.append(Check(what, ok, 1))

    check("the pay period and the payment date are read", stub.paid is not None)
    if stub.period_start and stub.period_end:
        check("the pay period is weekly, every two weeks, twice a month or monthly", bool(stub.frequency))
    check("the federal income tax withheld is read", "federal" in stub.withheld)
    for tax, t in stub.withheld.items():
        check(f"the {tax} income tax withheld this paycheck is part of the year to date's",
              0 <= t.current <= t.year_to_date)
    if stub.paid:
        stub.questions.append(Question(
            f"the paychecks left in {stub.paid.year} are taken to withhold what this one did: a bonus, a stock "
            "vesting or a new W-4 before December 31 changes that", 1, ""))
