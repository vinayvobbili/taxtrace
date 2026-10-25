"""India's income tax return (ITR-2, as the e-filing site prints it): what India taxed and what it kept.

A US person who sells a home in India files there as a non-resident; the buyer withholds TDS at registration and the
return settles it, often with a refund. The US return needs four things from it: the sale itself (its dates, the
consideration, the cost and improvements, Schedule CG), the interest India saw (Schedule OS), the tax India finally
kept (Part B-TTI's aggregate liability, which is the taxes paid less the refund) for Form 1116, and the refund.

The printed return is typed text, one row per line, each ending with its row code and its amount ("Aggregate
liability (15+16e) 17 1,23,456"), amounts in Indian grouping (lakhs: 12,34,567). India's year runs April to March:
assessment year 2025-26 is the financial year April 2024 to March 2025, so the sale's date says which US year it
falls in, not the return's year.

Nothing that names the person is kept: no PAN, no acknowledgement number, no address.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal

from .prior import Check, Question, amount

INR = r"-?(?:\d{1,3}(?:,\d{2})*,\d{3}|\d+)"  # 12,34,567 or 950 or 0
ROW_END = re.compile(rf"\s(?P<code>\S+)\s+(?P<value>{INR})\s*$")  # the row code, then the amount
DATES = re.compile(r"(\d{2}/\d{2}/\d{4})\s+(\d{2}/\d{2}/\d{4})")
IMPROVEMENT = re.compile(rf"^\s*(?P<no>\d+)\s+(?P<value>{INR})\s+(?P<year>\d{{4}}-\d{{2}})\b")
TOTAL = re.compile(rf"^\s*Total\s+(?P<value>{INR})\s*$")
FILED = re.compile(r"Date of Filing\s*:\s*(\d{1,2}-[A-Z][a-z]{2}-\d{4})")
YEAR = re.compile(r"Assessment\s+Year[\s\S]{0,400}?\b(20\d\d)-(\d\d)\b")
FORM = re.compile(r"\b(ITR-\d)\b")
STATUS = re.compile(r"Residential Status in India\s+(Non[- ]?Resident|Resident but not Ordinarily Resident|Resident)",
                    re.IGNORECASE)
TAX = {  # Part B-TTI's rows, by their labels' first words
    "tax_on_income": "Tax Payable on Total Income", "gross_liability": "Gross tax liability",
    "net_liability": "Net tax liability", "interest_and_fee": "Total Interest and Fee Payable",
    "aggregate": "Aggregate liability", "advance_tax": "Advance Tax", "tds": "TDS (total of column",
    "tcs": "TCS (total of column", "self_assessment": "Self Assessment Tax", "taxes_paid": "Total Taxes Paid",
    "payable": "Amount payable", "refund": "Refund (If",
}
INTEREST = {"interest": "Interest, Gross", "savings": "From Savings Bank"}  # Schedule OS
SALE = {  # one property's rows in Schedule CG, from its dates down to its gain
    "consideration": "Full value of consideration received", "stamp_value": "Value of property as per stamp",
    "adopted": "of Capital Gains [in case", "cost": "Cost of acquisition without",
    "transfer_expenses": "Expenditure wholly and exclusively in connection with transfer",
    "balance": "Balance (",
}
GAIN = re.compile(r"(Long|Short)-term Capital Gains on immovable property \(\s*\d*c\s*-\s*\d*d\s*\)", re.IGNORECASE)
EXEMPTION = re.compile(rf"^\s*Total\s+[AB]\d*d\s+(?P<value>{INR})\s*$")
RUPEE = Decimal("1")  # the return rounds to whole rupees
TEN = Decimal("10")  # and the tax payable or refund to the nearest ten rupees (section 288B)


@dataclass
class Amount:
    amount: Decimal
    page: int
    quote: str  # the row as printed: its label, code and amount


@dataclass
class Improvement:
    amount: Amount
    year: str  # India's financial year it was made in, "2014-15": the date itself isn't printed


@dataclass
class Sale:
    term: str  # "long" or "short", as India counts it (24 months for land and buildings)
    acquired: str  # dd/mm/yyyy, as printed
    sold: str
    page: int
    amounts: dict[str, Amount] = field(default_factory=dict)  # consideration, stamp_value, adopted, cost, ...
    improvements: list[Improvement] = field(default_factory=list)
    exemption: Amount | None = None  # sections 54/54EC/54F: reinvested, not taxed in India
    gain: Amount | None = None

    @property
    def sold_on(self) -> date:
        d, m, y = (int(x) for x in self.sold.split("/"))
        return date(y, m, d)


@dataclass
class Return:
    file: str
    version: str = ""  # "ITR-2" ("form" is what every saved form's kind is called: "ITR" here)
    year: str = ""  # the assessment year, "2025-26"
    filed: str = ""  # as printed, "28-Aug-2025"
    status: str = ""  # residential status: "Non Resident" for a US person
    tax: dict[str, Amount] = field(default_factory=dict)
    interest: dict[str, Amount] = field(default_factory=dict)
    tds_schedules: Amount | None = None  # the TDS schedules' totals, added up
    sales: list[Sale] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    @property
    def financial_year(self) -> tuple[date, date] | None:
        """India's year this return is for: April of the assessment year's first year minus one, to March."""
        if not self.year:
            return None
        start = int(self.year[:4])
        return date(start - 1, 4, 1), date(start, 3, 31)

    @property
    def kept(self) -> Decimal | None:
        """The tax India kept: what was paid less the refund, which is the aggregate liability when they agree."""
        if "taxes_paid" not in self.tax:
            return None
        refund = self.tax["refund"].amount if "refund" in self.tax else Decimal(0)
        return self.tax["taxes_paid"].amount - refund

    def check(self, what: str, ok: bool, page: int, quote: str = "") -> None:
        self.checks.append(Check(what, ok, page, quote))

    def ask(self, text: str, page: int, quote: str = "") -> None:
        self.questions.append(Question(text, page, quote))

    def to_json(self) -> dict:
        return {"form": "ITR", **asdict(self), "kept": str(self.kept) if self.kept is not None else None,
                "financial_year": [str(d) for d in self.financial_year] if self.financial_year else None}


def is_return(pages: list[str]) -> bool:
    first = pages[0] if pages else ""
    return "INCOME TAX RETURN" in first and bool(YEAR.search(first))


def _value(line: str, label: str) -> Decimal | None:
    """The amount at the end of a row that has `label`, after its row code; None for a row without both."""
    if label not in " ".join(line.split()):
        return None
    m = ROW_END.search(line)
    return amount(m.group("value")) if m else None


def _lines(pages: list[str]) -> list[tuple[int, str]]:
    return [(n, line) for n, page in enumerate(pages, 1) for line in page.splitlines()]


def read(name: str, pages: list[str]) -> Return:
    found = Return(name)
    first = pages[0] if pages else ""
    if m := FORM.search(first):
        found.version = m.group(1)
    if m := YEAR.search(first):
        found.year = f"{m.group(1)}-{m.group(2)}"
    if m := FILED.search(first):
        found.filed = m.group(1)
    lines = _lines(pages)
    for n, line in lines:
        if not found.status and (m := STATUS.search(" ".join(line.split()))):
            found.status = " ".join(m.group(1).replace("-", " ").split())
        for key, label in [*TAX.items(), *INTEREST.items()]:
            target = found.tax if key in TAX else found.interest
            if key not in target and (v := _value(line, label)) is not None:
                target[key] = Amount(v, n, " ".join(line.split()))
    found.sales = _sales(lines)
    found.tds_schedules = _tds_schedules(lines)
    _checks(found)
    return found


def _sales(lines: list[tuple[int, str]]) -> list[Sale]:
    """Each property in Schedule CG: from the row with its two dates down to the row with its gain."""
    sales: list[Sale] = []
    term, current = "short", None
    for i, (n, line) in enumerate(lines):
        flat = " ".join(line.split())
        if flat.startswith("B(I)"):  # A(I) is short-term, B(I) long-term
            term = "long"
        if "Date of Purchase/Acquisition" in flat and "Date of Sale/Transfer" in flat:
            following = next((ln for _, ln in lines[i + 1:i + 4] if DATES.search(ln)), None)
            if following:
                m = DATES.search(following)
                current = Sale(term, m.group(1), m.group(2), n)
                sales.append(current)
            continue
        if current is None:
            continue
        for key, label in SALE.items():
            if key not in current.amounts and (v := _value(line, label)) is not None:
                current.amounts[key] = Amount(v, n, flat)
        if (m := IMPROVEMENT.match(line)) and "cost" in current.amounts:
            current.improvements.append(Improvement(Amount(amount(m.group("value")), n, flat), m.group("year")))
        if (m := EXEMPTION.match(line)) and current.exemption is None:
            current.exemption = Amount(amount(m.group("value")), n, flat)
        if GAIN.search(flat) and (m := ROW_END.search(line)):
            current.gain = Amount(amount(m.group("value")), n, flat)
            current.term = GAIN.search(flat).group(1).lower()
            current = None
    return sales


def _tds_schedules(lines: list[tuple[int, str]]) -> Amount | None:
    """The TDS schedules' totals (salary, Form 16A, Form 16B/16C), from the first SCHEDULE TDS to the TCS one."""
    inside, total, quotes, page = False, Decimal(0), [], 0
    for n, line in lines:
        flat = " ".join(line.split())
        if flat.startswith("SCHEDULE TDS"):
            inside, page = True, page or n
        elif flat.startswith("SCHEDULE") and inside:
            break
        elif inside and (m := TOTAL.match(line)):
            total += amount(m.group("value"))
            quotes.append(flat)
    return Amount(total, page, "; ".join(quotes)) if quotes else None


def _checks(found: Return) -> None:
    t = found.tax
    if not t:
        found.ask("Part B-TTI wasn't found: is this the whole return?", 1)
        return
    page = next(iter(t.values())).page
    paid = [t[k].amount for k in ("advance_tax", "tds", "tcs", "self_assessment") if k in t]
    if "taxes_paid" in t and paid:
        found.check("taxes paid: advance tax, TDS, TCS and self-assessment tax add up to the total",
                    abs(sum(paid) - t["taxes_paid"].amount) <= RUPEE, page, t["taxes_paid"].quote)
    if {"aggregate", "taxes_paid"} <= t.keys():
        over = t["taxes_paid"].amount - t["aggregate"].amount
        if over > 0:
            found.check("the refund is the taxes paid less the aggregate liability",
                        "refund" in t and abs(t["refund"].amount - over) < TEN, page,
                        t["refund"].quote if "refund" in t else "")
        else:
            found.check("the amount payable is the aggregate liability less the taxes paid",
                        "payable" in t and abs(t["payable"].amount + over) < TEN, page,
                        t["payable"].quote if "payable" in t else "")
    if {"aggregate", "net_liability"} <= t.keys():
        extra = t["interest_and_fee"].amount if "interest_and_fee" in t else Decimal(0)
        found.check("the aggregate liability is the net tax liability plus interest and fees",
                    abs(t["net_liability"].amount + extra - t["aggregate"].amount) <= RUPEE, page,
                    t["aggregate"].quote)
    if found.tds_schedules is not None and "tds" in t:
        found.check("the TDS schedules add up to Part B-TTI's TDS",
                    abs(found.tds_schedules.amount - t["tds"].amount) <= RUPEE, found.tds_schedules.page,
                    found.tds_schedules.quote)
    if found.status and "non" not in found.status.lower():
        found.ask(f"the return says {found.status}: a US person living in the US files India's return as a "
                  "non-resident", 1)
    for n, sale in enumerate(found.sales, 1):
        _sale_checks(found, n, sale)


def _sale_checks(found: Return, n: int, sale: Sale) -> None:
    """Checks and questions about one sale, named by its place in Schedule CG ("sale 1"), not by its date: what's
    printed is masked, and a date isn't."""
    a, p = sale.amounts, sale.page
    if {"balance", "adopted", "cost"} <= a.keys():
        spent = a["cost"].amount + sum((i.amount.amount for i in sale.improvements), Decimal(0))
        spent += a["transfer_expenses"].amount if "transfer_expenses" in a else Decimal(0)
        found.check(f"sale {n}: the balance is the consideration adopted less cost, improvements and "
                    "transfer expenses", abs(a["adopted"].amount - spent - a["balance"].amount) <= RUPEE, p,
                    a["balance"].quote)
    if sale.gain is not None and "balance" in a:
        exempt = sale.exemption.amount if sale.exemption else Decimal(0)
        found.check(f"sale {n}: the gain is the balance less exemptions",
                    abs(a["balance"].amount - exempt - sale.gain.amount) <= RUPEE, sale.gain.page, sale.gain.quote)
    fy = found.financial_year
    if fy and not fy[0] <= sale.sold_on <= fy[1]:
        found.check(f"sale {n}: in the return's financial year", False, p)
    if "consideration" not in a or sale.gain is None:
        found.ask(f"sale {n}: the consideration or the gain wasn't found", p)
    if {"stamp_value", "consideration"} <= a.keys() and a["stamp_value"].amount > a["consideration"].amount:
        found.ask(f"sale {n}: India taxed the stamp value, above the price received; the US return uses "
                  "the price actually received", p, a["stamp_value"].quote)
    if sale.improvements:
        found.ask(f"sale {n}: improvements are printed with only India's financial year; each needs the "
                  "date it was paid, to turn it into dollars at that day's rate", sale.improvements[0].amount.page,
                  sale.improvements[0].amount.quote)
    found.ask(f"sale {n}: did this person own the whole property? A co-owner files their own return in "
              "India, and only this person's share is here", p)
