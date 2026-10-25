"""A year's foreign side in dollars: a property sold abroad (Form 8949) and the tax kept there (Form 1116).

A sale's gain is worked out in dollars, not in the other country's currency: the price received at the rate on the
day of the sale, the cost at the rate on the day it was bought, each improvement at the rate on the day it was paid.
A currency that fell against the dollar over the years leaves a dollar gain far smaller than the gain taxed abroad,
or a loss, which on a home held for personal use can't be deducted.

The credit is for the tax the other country finally kept: what was withheld less what it refunded, both at the rate
on the day the tax was paid (a refund is translated at the rate the tax was, so the credit doesn't move with the
currency). Gains from selling property are passive category income on Form 1116.

What only the person knows is confirmed once (`foreign --confirm`) and kept for later runs: who owned the property
(on a joint return, either spouse's sale counts in full; anyone else's share doesn't), the date each improvement was
paid, and how the property was used when the dollar result is a loss.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal

from .fx import NoRate, Rate, Rates
from .prior import Question

OWNERS = ("self", "spouse", "joint", "other")  # "joint": the two spouses; "other": someone else shared it
USES = ("investment", "personal", "rental")
CONFIRMS = {
    "owner": OWNERS,
    "improvement_dates": "dates",  # the day each improvement in Schedule CG was paid, in order, comma-separated,
    # or "average": the dates aren't known, and each financial year's mean rate stands
    "use": USES,  # how the property was used, which matters when the dollar result is a loss
}
AVERAGE = "average"


@dataclass
class Converted:
    what: str
    amount: Decimal  # in the other currency
    dollars: Decimal
    rate: Rate
    page: int
    quote: str


@dataclass
class Sale:
    description: str  # what Form 8949 column (a) says; never the address
    acquired: str  # ISO dates
    sold: str
    term: str  # "long" when held more than a year
    proceeds: Converted
    cost: Converted
    improvements: list[Converted] = field(default_factory=list)
    expenses: Converted | None = None
    gain_abroad: Decimal | None = None  # the other country's own gain, in its currency, for comparison
    file: str = ""

    @property
    def basis(self) -> Decimal:
        return self.cost.dollars + sum((i.dollars for i in self.improvements), Decimal(0)) + (
            self.expenses.dollars if self.expenses else Decimal(0))

    @property
    def gain(self) -> Decimal:
        return self.proceeds.dollars - self.basis


@dataclass
class ForeignTax:
    country: str
    category: str  # Form 1116's category: "passive" for a gain on property
    kept: Converted  # withheld less refunded
    file: str = ""


@dataclass
class Foreign:
    year: int
    sales: list[Sale] = field(default_factory=list)
    taxes: list[ForeignTax] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    def ask(self, text: str, page: int = 0, quote: str = "") -> None:
        self.questions.append(Question(text, page, quote))

    def to_json(self) -> dict:
        found = asdict(self)
        for sale, row in zip(self.sales, found["sales"], strict=True):
            row["basis"], row["gain"] = str(sale.basis), str(sale.gain)
        return found


def confirmation(spec: str) -> tuple[str, str]:
    """'owner=spouse' as ("owner", "spouse"); 'improvement_dates=2014-09-15' checked as dates."""
    key, sep, value = spec.partition("=")
    key, value = key.strip().replace("-", "_"), value.strip()
    if not sep or key not in CONFIRMS:
        raise ValueError(f"--confirm takes one of {', '.join(CONFIRMS)}, as KEY=VALUE")
    if CONFIRMS[key] == "dates":
        if value.lower() == AVERAGE:
            return key, AVERAGE
        try:
            days = [str(date.fromisoformat(d.strip())) for d in value.split(",") if d.strip()]
        except ValueError:
            raise ValueError(f"{key} is dates as YYYY-MM-DD, comma-separated") from None
        return key, ",".join(days)
    if value.lower() not in CONFIRMS[key]:
        raise ValueError(f"{key} is one of {', '.join(CONFIRMS[key])}")
    return key, value.lower()


def _day(printed: str) -> date:
    d, m, y = (int(x) for x in printed.split("/"))  # India prints dd/mm/yyyy
    return date(y, m, d)


def _held_over_a_year(acquired: date, sold: date) -> bool:
    try:
        return sold > acquired.replace(year=acquired.year + 1)
    except ValueError:  # bought on February 29
        return sold > date(acquired.year + 1, 3, 1)


def build(year: int, *, itrs: list[dict], rates: Rates, confirmed: dict | None = None) -> Foreign:
    """The year's foreign sales and taxes from India's returns (`taxtrace itr`), converted with `rates`."""
    confirmed = confirmed or {}
    found = Foreign(year)
    for ret in itrs:
        mine = [(n, row) for n, row in enumerate(ret.get("sales", []), 1) if _day(row["sold"]).year == year]
        for n, row in mine:
            _sale(found, ret, n, row, rates, confirmed)
        if mine:
            try:
                _tax(found, ret, rates.daily(min(_day(row["sold"]) for _, row in mine)))
            except NoRate as err:
                found.ask(f"India's tax: {err}")
    return found


def _sale(found: Foreign, ret: dict, n: int, row: dict, rates: Rates, confirmed: dict) -> None:
    a = row["amounts"]
    acquired, sold = _day(row["acquired"]), _day(row["sold"])
    if "consideration" not in a or "cost" not in a:
        found.ask(f"sale {n}: India's return lacks the consideration or the cost", row["page"])
        return

    def convert(what: str, value: dict, rate: Rate) -> Converted:
        amount = Decimal(value["amount"])
        return Converted(what, amount, rate.dollars(amount), rate, value["page"], value["quote"])

    try:
        on_sale, on_purchase = rates.daily(sold), rates.daily(acquired)
    except NoRate as err:
        found.ask(f"sale {n}: {err}", row["page"])
        return
    sale = Sale(description="House, India", acquired=str(acquired), sold=str(sold),
                term="long" if _held_over_a_year(acquired, sold) else "short",
                proceeds=convert("price received", a["consideration"], on_sale),
                cost=convert("cost", a["cost"], on_purchase),
                gain_abroad=Decimal(row["gain"]["amount"]) if row.get("gain") else None, file=ret["file"])
    if a.get("transfer_expenses") and Decimal(a["transfer_expenses"]["amount"]):
        sale.expenses = convert("transfer expenses", a["transfer_expenses"], on_sale)
    averaged = confirmed.get("improvement_dates") == AVERAGE
    paid = [] if averaged else [d for d in confirmed.get("improvement_dates", "").split(",") if d]
    for i, imp in enumerate(row.get("improvements", [])):
        if i < len(paid):
            rate = rates.daily(date.fromisoformat(paid[i]))
        else:  # until its date is known, the mean rate over India's financial year it was made in
            start = int(imp["year"][:4])
            rate = rates.average(date(start, 4, 1), date(start + 1, 3, 31))
        sale.improvements.append(convert(f"improvement ({imp['year']})", imp["amount"], rate))
    if len(paid) < len(sale.improvements) and not averaged:
        found.ask(f"sale {n}: the date each improvement was paid; until then it's at its financial year's mean rate "
                  "(`--confirm improvement_dates=YYYY-MM-DD,...`)", row["page"])
    owner = confirmed.get("owner")
    if owner is None:
        found.ask(f"sale {n}: who owned the property: you, your spouse, both of you, or shared with someone else "
                  "(`--confirm owner=self|spouse|joint|other`)", row["page"])
    elif owner == "other":
        found.ask(f"sale {n}: shared with someone outside the return: only your household's share counts, and "
                  "India's return shows only its filer's share", row["page"])
    if sale.gain < 0 and confirmed.get("use") is None:
        found.ask(f"sale {n}: a loss in dollars: was the property held for investment, used personally, or rented "
                  "(`--confirm use=investment|personal|rental`)? A loss on a personal home isn't deductible",
                  row["page"])
    found.sales.append(sale)


def _tax(found: Foreign, ret: dict, rate: Rate) -> None:
    """The tax India kept on the whole return, at the rate of the day it was withheld: the buyer's TDS at the sale."""
    kept = ret.get("kept")
    if kept is None or not Decimal(kept) > 0:
        return
    row = ret.get("tax", {}).get("aggregate", {})
    amount = Decimal(kept)
    found.taxes.append(ForeignTax("India", "passive", Converted("tax kept", amount, rate.dollars(amount), rate,
                                                                row.get("page", 0), row.get("quote", "")),
                                  file=ret["file"]))
