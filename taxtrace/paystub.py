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

The 401(k) deferrals ("401k Before-Tax", "401(k) Roth"; not a loan's repayment) are read the same way, with the
salary row, so what's left under the year's limit after the paychecks left is known, and the pre-tax percentage of
salary that would fill it: a pre-tax deferral lowers the year's taxable wages dollar for dollar.
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
RETIREMENT = re.compile(r"^401\(?k\)?$", re.IGNORECASE)  # "401k Before-Tax", "401(k) Roth"; not "401k Loan Repay"
LIMITS = {2025: Decimal(23500), 2026: Decimal(24500)}  # a 401(k)'s elective deferrals in a year, before age 50
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
    deferred: dict[str, Taxed] = field(default_factory=dict)  # a 401(k)'s "pretax" and "roth" deferrals
    salary: Taxed | None = None  # the earnings table's "Salary" row, what a deferral's percentage is of
    taxable_wages: Taxed | None = None  # the summary's federal taxable wages: what the W-2's box 1 adds up
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

    def projected_wages(self, fill_401k: bool = False) -> Decimal | None:
        """The year's federal taxable wages (the W-2's box 1): the year to date's and this paycheck's for each left,
        less the 401(k)'s room left when it's filled."""
        t = self.taxable_wages
        if t is None:
            return None
        return t.year_to_date + t.current * self.paychecks_left() - ((self.deferral_room() or 0) if fill_401k else 0)

    def deferral_room(self) -> Decimal | None:
        """What more the year's 401(k) limit takes past the year to date's deferrals and this paycheck's for each
        left; None when there's no deferral row or no limit for the year."""
        if not (self.deferred and self.paid and self.paid.year in LIMITS):
            return None
        left = self.paychecks_left()
        planned = sum((d.year_to_date + d.current * left for d in self.deferred.values()), Decimal(0))
        return max(Decimal(0), LIMITS[self.paid.year] - planned)

    def deferral_rates(self) -> tuple[Decimal, Decimal] | None:
        """The pre-tax deferral as a percentage of salary now, and what it would be to fill the room left over the
        paychecks left; None when it can't be worked out."""
        room, left = self.deferral_room(), self.paychecks_left()
        pretax = self.deferred.get("pretax")
        if room is None or not left or pretax is None or not self.salary or not self.salary.current:
            return None
        now = pretax.current / self.salary.current * 100
        return now.quantize(Decimal(1)), ((pretax.current + room / left) / self.salary.current * 100).quantize(
            Decimal(1))

    def to_json(self) -> dict:
        def pair(t: Taxed) -> dict:
            return {"current": str(t.current), "year_to_date": str(t.year_to_date), "label": t.label}

        rates = self.deferral_rates()
        return {"form": "paystub", "file": self.file, "year": self.paid.year if self.paid else None,
                "period_start": _iso(self.period_start), "period_end": _iso(self.period_end),
                "paid": _iso(self.paid), "frequency": self.frequency, "paychecks_left": self.paychecks_left(),
                "withheld": {k: pair(t) for k, t in self.withheld.items()},
                "projected_federal": str(p) if (p := self.projected()) is not None else None,
                "deferred": {k: pair(t) for k, t in self.deferred.items()},
                "salary": pair(self.salary) if self.salary else None,
                "taxable_wages": pair(self.taxable_wages) if self.taxable_wages else None,
                "projected_wages": {"as_is": str(self.projected_wages()), "401k_filled": str(
                    self.projected_wages(fill_401k=True))} if self.taxable_wages else None,
                "deferral_room": str(r) if (r := self.deferral_room()) is not None else None,
                "deferral_percent": {"now": str(rates[0]), "to_fill": str(rates[1])} if rates else None}


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
            if tax not in stub.withheld and at is not None and (taxed := _after(texts, at)):
                stub.withheld[tax] = taxed
        for j, t in enumerate(texts):
            if RETIREMENT.match(t) and (deferred := _after(texts, j)) and "loan" not in deferred.label.lower():
                stub.deferred.setdefault("roth" if "roth" in deferred.label.lower() else "pretax", deferred)
            elif t == "Salary" and stub.salary is None and j + 1 < len(texts) and MONEY.match(texts[j + 1]):
                stub.salary = _after(texts, j)
    stub.taxable_wages = _column(rows, ("Federal", "Taxable", "Wages"))
    _checks(stub)
    return stub


def _column(rows: list[list[dict]], label: tuple[str, ...]) -> Taxed | None:
    """The summary table's column under a heading: the amounts on its "Current" and "Year to Date" rows that sit
    under the heading's words."""
    span = next(((row[j]["x0"], row[j + len(label) - 1]["x1"]) for row in rows for j in range(len(row))
                 if tuple(w["text"] for w in row[j:j + len(label)]) == label), None)
    if span is None:
        return None

    def under(row: list[dict]) -> Decimal | None:
        return next((amount(w["text"]) for w in row if MONEY.match(w["text"]) and w["x0"] < span[1]
                     and w["x1"] > span[0]), None)

    current = next((under(r) for r in rows if [w["text"] for w in r[:1]] == ["Current"]
                    and len(r) > 1 and MONEY.match(r[1]["text"])), None)
    to_date = next((under(r) for r in rows if [w["text"] for w in r[:3]] == ["Year", "to", "Date"]
                    and len(r) > 3 and MONEY.match(r[3]["text"])), None)
    return None if current is None or to_date is None else Taxed(current, to_date, " ".join(label))


def _after(texts: list[str], at: int) -> Taxed | None:
    """The label starting at `at` and the two amounts after it, this paycheck's and the year to date's, up to the
    next column's words."""
    end = next((k for k in range(at, len(texts)) if MONEY.match(texts[k])), len(texts))
    amounts = []
    for t in texts[end:]:
        if not MONEY.match(t):
            break
        amounts.append(t)
    if len(amounts) < 2:
        return None
    return Taxed(amount(amounts[0]), amount(amounts[-1]), " ".join(texts[at:end]))


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
    for kind, d in stub.deferred.items():
        check(f"the {kind} 401(k) deferral this paycheck is part of the year to date's",
              0 <= d.current <= d.year_to_date)
    if stub.paid:
        stub.questions.append(Question(
            f"the paychecks left in {stub.paid.year} are taken to withhold what this one did: a bonus, a stock "
            "vesting or a new W-4 before December 31 changes that", 1, ""))
    if stub.deferral_room():
        stub.questions.append(Question(
            "the 401(k) has room left this year: each pre-tax dollar deferred before December 31 isn't taxed this "
            "year (the plan may cap the percentage, and net pay has to cover the other deductions); age 50 or over, "
            "the catch-up allows $8,000 more", 1, ""))
