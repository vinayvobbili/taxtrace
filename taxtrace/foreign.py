"""A year's foreign side in dollars: a property sold abroad (Form 8949) and the tax kept there (Form 1116).

A sale's gain is worked out in dollars, not in the other country's currency: the price received at the rate on the
day of the sale, the cost at the rate on the day it was bought, each improvement at the rate on the day it was paid.
A currency that fell against the dollar over the years leaves a dollar gain far smaller than the gain taxed abroad,
or a loss, which on a home held for personal use can't be deducted.

The credit is for the tax the other country finally kept: what was withheld less what it refunded, both at the rate
on the day the tax was paid (a refund is translated at the rate the tax was, so the credit doesn't move with the
currency). Gains from selling property are passive category income on Form 1116.

A foreign bank account's statements (`taxtrace bank`) give the interest credited in the calendar year (Schedule B, and
passive income on Form 1116) at the IRS's yearly average rate, the TDS withheld on it (a tax Form 1116 credits) at
each day's rate, and the highest balance and the one on December 31 at the Treasury's December 31 rate: what the
FBAR ($10,000 at any time, all accounts together) and Form 8938 (by filing status) are tested against. A home held
directly isn't a Form 8938 asset; the account its price was paid into is. India's statements run April to March, so
a calendar year takes two: until both are read, the interest and the highest balance are only what's covered, and
the foreign side asks for the rest. The refund on India's return is looked for among the statements' deposits: what
arrived beyond the refund is India's interest on it, income in the year it arrived.

What only the person knows is confirmed once (`foreign --confirm`) and kept for later runs: who owned the property
(on a joint return, either spouse's sale counts in full; anyone else's share doesn't), the date each improvement was
paid, how the property was used when the dollar result is a loss, and the filing status Form 8938's thresholds
follow.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from .fx import NoRate, Rate, Rates
from .prior import Question
from .statement import day as statement_day

OWNERS = ("self", "spouse", "joint", "other")  # "joint": the two spouses; "other": someone else shared it
USES = ("investment", "personal", "rental")
FILINGS = ("joint", "single", "separate", "head")  # married filing jointly or separately, single, head of household
CONFIRMS = {
    "owner": OWNERS,
    "improvement_dates": "dates",  # the day each improvement in Schedule CG was paid, in order, comma-separated,
    # or "average": the dates aren't known, and each financial year's mean rate stands
    "use": USES,  # how the property was used, which matters when the dollar result is a loss
    "filing": FILINGS,  # for Form 8938's thresholds
}
AVERAGE = "average"
FBAR = Decimal(10000)  # all foreign accounts' highest balances together, at any time in the year
# Form 8938 for someone living in the US: (on December 31, at any time in the year), all the assets together
FORM_8938 = {"joint": (Decimal(100000), Decimal(150000))} | {
    f: (Decimal(50000), Decimal(75000)) for f in ("single", "separate", "head")}
TEN = Decimal("10")  # India rounds a refund to the nearest ten rupees


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
class Account:
    country: str
    account: str  # the last four digits
    currency: str
    covered: list[str] = field(default_factory=list)  # the year's days the statements cover, "YYYY-MM-DD..YYYY-MM-DD"
    missing: list[str] = field(default_factory=list)  # and the ones they don't
    interest: Converted | None = None  # credited in the year (what's covered), at the IRS's yearly average
    highest: Converted | None = None  # the highest balance in what's covered, at the Treasury's December 31 rate
    december_31: Converted | None = None
    files: list[str] = field(default_factory=list)


@dataclass
class Refund:
    country: str
    expected: Decimal  # the refund on the return
    arrived: str = ""  # the ISO day a statement shows it deposited, or "" when none does
    interest: Converted | None = None  # what came beyond the refund: interest on it, income when it arrives
    file: str = ""


@dataclass
class Foreign:
    year: int
    sales: list[Sale] = field(default_factory=list)
    taxes: list[ForeignTax] = field(default_factory=list)
    accounts: list[Account] = field(default_factory=list)
    refunds: list[Refund] = field(default_factory=list)
    # whether the year's foreign accounts must be reported: True, False, or None until a missing statement is read
    reporting: dict[str, bool | None] = field(default_factory=dict)
    # the year isn't over: the accounts are at the latest day's rate until its average and December 31 rate come out
    estimated: bool = False
    questions: list[Question] = field(default_factory=list)

    def ask(self, text: str, page: int = 0, quote: str = "") -> None:
        self.questions.append(Question(text, page, quote))

    @property
    def interest(self) -> Decimal:
        """Schedule B's foreign interest in dollars: the accounts' and India's interest on its refund."""
        return sum((c.dollars for c in [*(a.interest for a in self.accounts), *(r.interest for r in self.refunds)]
                    if c), Decimal(0))

    def to_json(self) -> dict:
        found = asdict(self)
        for sale, row in zip(self.sales, found["sales"], strict=True):
            row["basis"], row["gain"] = str(sale.basis), str(sale.gain)
        found["interest"] = str(self.interest)
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


def build(year: int, *, itrs: list[dict], rates: Rates, confirmed: dict | None = None,
          statements: list[dict] | None = None, today: date | None = None) -> Foreign:
    """The year's foreign sales, taxes and accounts from India's returns (`taxtrace itr`) and the banks' statements
    (`taxtrace bank`), converted with `rates`."""
    confirmed, statements, today = confirmed or {}, statements or [], today or date.today()
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
            _refund(found, ret, statements, rates)
    by_account: dict[str, list[dict]] = {}
    for s in statements:
        by_account.setdefault(s.get("account") or s["file"], []).append(s)
    for n, (_, mine) in enumerate(sorted(by_account.items()), 1):
        _account(found, n, mine, rates, today)
    if found.accounts:
        _reporting(found, confirmed)
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


def _rows(statements: list[dict]) -> list[tuple[date, dict, dict]]:
    """Each statement's rows once, in date order, with the statement they came from: statements that overlap print
    the same rows twice."""
    seen, found = set(), []
    for s in statements:
        for r in s["rows"]:
            key = (r["on"], r["withdrawal"], r["deposit"], r["balance"])
            if key not in seen:
                seen.add(key)
                found.append((statement_day(r["on"]), r, s))
    return sorted(found, key=lambda t: t[0])


def _refund(found: Foreign, ret: dict, statements: list[dict], rates: Rates) -> None:
    """India's refund on the return, looked for among the statements' tax refund deposits."""
    row = ret.get("tax", {}).get("refund")
    if not row or not Decimal(row["amount"]) > 0:
        return
    refund = Refund("India", Decimal(row["amount"]), file=ret["file"])
    found.refunds.append(refund)
    deposits = [(on, r) for on, r, _ in _rows(statements)
                if r["kind"] == "tax refund" and Decimal(r["deposit"]) >= refund.expected - TEN]
    if not deposits:
        if statements:
            found.ask("India's refund isn't among the bank statements' deposits read: has it arrived, and into "
                      "which account?", row.get("page", 0))
        return
    on, r = deposits[0]
    refund.arrived = str(on)
    extra = Decimal(r["deposit"]) - refund.expected
    if extra > TEN and on.year == found.year:
        try:
            rate = rates.yearly(found.year)
        except NoRate as err:
            found.ask(f"India's interest on its refund: {err}")
            return
        refund.interest = Converted("interest on India's refund", extra, rate.dollars(extra), rate, r["page"],
                                    r["quote"])


def _covered(statements: list[dict], year: int) -> tuple[list[tuple[date, date]], list[tuple[date, date]]]:
    """The year's days the statements cover, merged, and the gaps between."""
    first, last = date(year, 1, 1), date(year, 12, 31)
    spans = sorted((max(statement_day(s["start"]), first), min(statement_day(s["end"]), last))
                   for s in statements if s.get("start") and s.get("end"))
    covered: list[tuple[date, date]] = []
    for start, end in spans:
        if start > end:
            continue
        if covered and start <= covered[-1][1] + timedelta(days=1):
            covered[-1] = (covered[-1][0], max(covered[-1][1], end))
        else:
            covered.append((start, end))
    missing, at = [], first
    for start, end in covered:
        if start > at:
            missing.append((at, start - timedelta(days=1)))
        at = max(at, end + timedelta(days=1))
    if at <= last:
        missing.append((at, last))
    return covered, missing


def _account(found: Foreign, n: int, statements: list[dict], rates: Rates, today: date) -> None:
    year = found.year
    first = statements[0]
    account = Account("India", first.get("account", ""), first.get("currency", ""),
                      files=[s["file"] for s in statements])
    found.accounts.append(account)
    covered, missing = _covered(statements, year)
    account.covered = [f"{a}..{b}" for a, b in covered]
    account.missing = [f"{a}..{b}" for a, b in missing]
    if missing:
        found.ask(f"account {n}: its statements don't cover " + ", ".join(f"{a} to {b}" for a, b in missing)
                  + f" of {year}: the interest and the highest balance need them (India's statements run April to "
                    "March)")
    if not covered:
        return
    rows = _rows(statements)
    # the balance at each change in the year: each statement's opening balance, then each row's
    points: list[tuple[date, Decimal, dict]] = []
    for s in statements:
        if s["rows"] and s.get("start"):
            r = s["rows"][0]
            opening = Decimal(r["balance"]) - Decimal(r["deposit"]) + Decimal(r["withdrawal"])
            points.append((statement_day(s["start"]), opening, r))
    points += [(on, Decimal(r["balance"]), r) for on, r, _ in rows]
    inside = [(on, b, r) for on, b, r in points if any(a <= on <= z for a, z in covered)]
    try:
        yearly, december = rates.yearly(year), rates.year_end(year)
    except NoRate as err:
        if year < today.year:
            found.ask(f"account {n}: {err}")
            return
        # neither exists while the year is still going: the latest day's rate stands in for both until then
        try:
            yearly = december = rates.daily(today)
        except NoRate as late:
            found.ask(f"account {n}: {late}")
            return
        found.estimated = True

    def convert(what: str, amount: Decimal, rate: Rate, r: dict) -> Converted:
        return Converted(what, amount, rate.dollars(amount), rate, r["page"], r["quote"])

    interest = [(on, r) for on, r, _ in rows if r["kind"] == "interest" and on.year == year]
    if interest:
        total = sum((Decimal(r["deposit"]) for _, r in interest), Decimal(0))
        account.interest = convert("interest", total, yearly, interest[0][1])
    for on, r, s in rows:
        if on.year == year and r["kind"] in ("tds", "tds refund"):
            amount = Decimal(r["withdrawal"]) - Decimal(r["deposit"])
            try:
                rate = rates.daily(on)
            except NoRate as err:
                found.ask(f"account {n}'s TDS: {err}")
                continue
            found.taxes.append(ForeignTax("India", "passive", convert("TDS on interest", amount, rate, r),
                                          file=s["file"]))
    if inside:
        _, high, r = max(inside, key=lambda t: t[1])
        account.highest = convert("highest balance", high, december, r)
    end = date(year, 12, 31)
    if any(a <= end <= z for a, z in covered):
        before = [(on, b, r) for on, b, r in points if on <= end]
        if before:
            _, balance, r = max(before, key=lambda t: t[0])  # the last change on or before December 31
            account.december_31 = convert("balance on December 31", balance, december, r)


def _reporting(found: Foreign, confirmed: dict) -> None:
    """Whether the FBAR and Form 8938 are due, from all the accounts together: True or False when the statements
    settle it, None while a missing one could change it."""
    complete = all(not a.missing for a in found.accounts)
    highest = sum((a.highest.dollars for a in found.accounts if a.highest), Decimal(0))
    found.reporting["fbar"] = True if highest > FBAR else (False if complete else None)
    filing = confirmed.get("filing")
    if filing is None:
        found.reporting["form_8938"] = None
        found.ask("how you file, for Form 8938's thresholds (`--confirm filing=joint|single|separate|head`)")
        return
    at_end, any_time = FORM_8938[filing]
    year_end = [a.december_31 for a in found.accounts]
    if highest > any_time or (all(year_end) and sum(c.dollars for c in year_end) > at_end):
        found.reporting["form_8938"] = True
    else:
        found.reporting["form_8938"] = False if complete and all(year_end) else None
