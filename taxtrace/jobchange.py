"""What a change of job does to a year's return: the year as the pay stub projects it, against leaving on one day and
starting elsewhere on another.

Two employers in a year change four things, and neither payroll knows about the other:

- The 401(k)'s limit is one limit across both plans, so what's room at the new plan is the year's limit less what the
  old one took. Going past it is yours to catch: the excess has to come out by April 15.
- Social Security stops at the year's wage base at each employer, not across them, so the new one withholds again from
  its first dollar. What's withheld past the base comes back as a credit on Schedule 3 line 11, with no form to ask
  for it. It's cash until the return, not a cost.
- A 401(k) loan comes due on leaving. What's unpaid is treated as a distribution (a plan loan offset): taxed in the
  year, and 10% more under age 59½, unless it's repaid or the same amount is rolled to an IRA or the new plan by the
  return's due date with extensions, October 15 of the next year.
- A bonus, a sign-on or a paid-out vacation is withheld at the flat 22% (`SUPPLEMENTAL`), whatever your bracket, which
  can leave a balance due.

Leaving after December 31 changes nothing on this year's return. The cases are rough on purpose: wages and last
year's other income at the year's brackets past the standard deduction, without the capital gain rates or credits.
They're for comparing two ways of leaving, and the difference between them is what to read.

What only you know is kept with `--confirm`: `leave=YYYY-MM-DD`, `start=YYYY-MM-DD`, `new_salary=AMOUNT` (a year's),
`sign_on=AMOUNT`, `payout=AMOUNT` (paid on leaving), `percent=N` (the old plan's pre-tax percentage for the paychecks
left, when it has changed since the stub), `new_percent=N` (the new plan's), `loan=AMOUNT` (what's owed when you
leave), `loan_repaid=yes` and `other=AMOUNT` (the year's income besides the wages).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from . import estimates, ira, paystub
from .prior import Question

CENT = Decimal("0.01")
SOCIAL_SECURITY = Decimal("0.062")
WAGE_BASE = {2025: Decimal(176100), 2026: Decimal(184500)}
SUPPLEMENTAL = Decimal("0.22")  # the flat federal withholding on pay outside the salary
EARLY = Decimal("0.10")  # the additional tax on a distribution before age 59½
DAYS = ("leave", "start")
AMOUNTS = ("new_salary", "sign_on", "payout", "percent", "new_percent", "loan", "other")


@dataclass
class Case:
    name: str
    paychecks: int  # the old job's paychecks left in the year
    old_wages: Decimal  # the W-2's box 1 from the old job
    new_wages: Decimal = Decimal(0)
    withheld: Decimal = Decimal(0)  # federal income tax, both jobs
    social_security: Decimal | None = None  # withheld, both jobs
    social_security_back: Decimal = Decimal(0)  # the credit on Schedule 3 line 11
    deferred: Decimal = Decimal(0)  # 401(k) deferrals, both plans
    room: Decimal | None = None  # what's left under the year's limit after them
    over_limit: bool = False
    loan_taxed: Decimal = Decimal(0)
    loan_cost: Decimal = Decimal(0)  # the federal tax, the 10% and the state's on it
    tax: Decimal | None = None
    balance: Decimal | None = None  # owed with the return; negative, a refund
    quarters_short: list[int] = field(default_factory=list)  # against the safe harbor (`estimates`)

    @property
    def wages(self) -> Decimal:
        return self.old_wages + self.new_wages


@dataclass
class Comparison:
    year: int
    leave: date | None = None
    start: date | None = None
    after_year: bool = False  # leaving after December 31
    cases: list[Case] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    def ask(self, text: str) -> None:
        self.questions.append(Question(text, 0, ""))


def confirmation(spec: str) -> tuple[str, str]:
    """'leave=2026-12-11', 'new_salary=196,000', 'loan_repaid=yes'."""
    key, sep, value = (s.strip().lower() for s in spec.partition("="))
    usage = ValueError("--confirm takes leave=YYYY-MM-DD, start=YYYY-MM-DD, new_salary=AMOUNT, sign_on=AMOUNT, "
                       "payout=AMOUNT, percent=N, new_percent=N, loan=AMOUNT, loan_repaid=yes|no or other=AMOUNT")
    if not sep:
        raise usage
    try:
        if key in DAYS:
            return key, date.fromisoformat(value).isoformat()
        if key == "loan_repaid" and value in ("yes", "no"):
            return key, value
        if key in AMOUNTS:
            number = Decimal(value.replace(",", "").lstrip("$"))
            if number.is_finite() and number >= 0:
                return key, str(number)
    except (ArithmeticError, ValueError):
        pass
    raise usage


def build(year: int, *, stub: dict | None, returns: list[dict], confirmed: dict | None = None,
          filing: str = "") -> Comparison:
    """The year as it stands against the year with the change `confirmed` describes."""
    confirmed = confirmed or {}
    out = Comparison(year)
    for key, attr in (("leave", "leave"), ("start", "start")):
        if key in confirmed:
            setattr(out, attr, date.fromisoformat(confirmed[key]))
    if stub is None or not stub.get("taxable_wages") or not stub.get("withheld", {}).get("federal"):
        out.ask(f"no {year} pay stub with its federal taxable wages and tax withheld has been read "
                "(`taxtrace paystub`)")
        return out
    if year not in WAGE_BASE or year not in paystub.LIMITS:
        out.ask(f"{year}'s Social Security wage base and 401(k) limit aren't in taxtrace yet")
        return out
    read = paystub.from_json(stub)
    if read.social_security is None:
        out.ask("the pay stub's Social Security row isn't read: run `taxtrace paystub` on it again, or the credit for "
                "tax withheld past the wage base can't be worked out")
    other = Decimal(confirmed["other"]) if "other" in confirmed else ira.last_other(year, returns)
    if other is None:
        out.ask(f"the {year - 1} Form 1040's income lines aren't read (`taxtrace prior`), so only the wages are "
                f"counted: `--confirm other=AMOUNT` for {year}'s income besides them")
        other = Decimal(0)
    filing = filing or "joint"
    out.cases.append(_case("as it stands", year, read, None, None, confirmed, returns, other, filing))
    if out.leave is None:
        out.ask("no change is set yet: `--confirm leave=YYYY-MM-DD start=YYYY-MM-DD`")
    elif out.leave.year > year:
        out.after_year = True
        out.ask(f"leaving after December 31 changes nothing on the {year} return: two W-2s, the 401(k)'s shared limit "
                f"and a loan coming due all fall in {out.leave.year}")
    else:
        name = f"leaving {out.leave:%b} {out.leave.day}"
        out.cases.append(_case(name, year, read, out.leave, out.start, confirmed, returns, other, filing))
        _questions(out, confirmed, read)
    return out


def _questions(out: Comparison, confirmed: dict, read: paystub.Paystub) -> None:
    if out.start and "new_salary" not in confirmed:
        out.ask("the new job's salary is taken to be this one's: `--confirm new_salary=AMOUNT`")
    if out.start and "new_percent" not in confirmed:
        out.ask("no deferrals are counted at the new plan: many have a waiting period, so ask when you can start "
                "(`--confirm new_percent=N`)")
    if read.loan and "loan" not in confirmed and confirmed.get("loan_repaid") != "yes":
        out.ask("the pay stub shows a 401(k) loan: what's unpaid when you leave is taxed, plus 10% under age 59½, "
                "unless it's repaid or rolled over by next October 15. `--confirm loan=AMOUNT`, or `loan_repaid=yes`")
    out.ask("what's left to vest in the old plan's match, and the bonus's payout date against your last day: leaving "
            "first can forfeit either; the plan's and the bonus plan's documents say")
    out.ask("a pay period cut short is counted whole, and the new paychecks evenly through what's left of the year")


def _case(name: str, year: int, read: paystub.Paystub, leave: date | None, start: date | None, confirmed: dict,
          returns: list[dict], other: Decimal, filing: str) -> Case:
    lag = read.paid - read.period_end
    days = [d for d in read.paydays() if leave is None or d - lag <= leave]
    payout = Decimal(confirmed.get("payout", 0)) if leave else Decimal(0)
    wage, federal, deferred = _paycheck(read, confirmed, year, filing)
    limit = paystub.LIMITS[year]
    so_far = sum((d.year_to_date for d in read.deferred.values()), Decimal(0))
    old_deferred = min(limit, so_far + deferred * len(days))
    case = Case(name, len(days), read.taxable_wages.year_to_date + wage * len(days) + payout)
    case.withheld = read.withheld["federal"].year_to_date + federal * len(days) + payout * SUPPLEMENTAL
    base_tax = WAGE_BASE[year] * SOCIAL_SECURITY
    old_ss = None
    if read.social_security:
        old_ss = min(base_tax, read.social_security.year_to_date + read.social_security.current * len(days)
                     + payout * SOCIAL_SECURITY)
    new_gross, new_deferred = Decimal(0), Decimal(0)
    if start and start.year == year:
        salary = Decimal(confirmed["new_salary"]) if "new_salary" in confirmed else _annual_salary(read)
        share = Decimal((date(year, 12, 31) - start).days + 1) / ((date(year, 12, 31) - date(year - 1, 12, 31)).days)
        pay = salary * share if salary is not None else Decimal(0)
        sign_on = Decimal(confirmed.get("sign_on", 0))
        new_gross = pay + sign_on
        wanted = pay * Decimal(confirmed.get("new_percent", 0)) / 100
        new_deferred = max(Decimal(0), min(wanted, limit - old_deferred))
        case.new_wages = new_gross - new_deferred
        kept = 1 - Decimal(confirmed.get("new_percent", 0)) / 100
        taxed = paystub.tax_on((salary or Decimal(0)) * kept, year, filing)
        case.withheld += (taxed if taxed is not None else Decimal(0)) * share + sign_on * SUPPLEMENTAL
    if old_ss is not None:
        new_ss = min(new_gross, WAGE_BASE[year]) * SOCIAL_SECURITY
        case.social_security = _cents(old_ss + new_ss)
        case.social_security_back = _cents(max(Decimal(0), old_ss + new_ss - base_tax))
    case.deferred = old_deferred + new_deferred
    case.room = max(Decimal(0), limit - case.deferred)
    # the stub's deferrals past the limit are the payroll's to stop; a new plan's aren't checked against the old one's
    case.over_limit = (bool(start) and Decimal(confirmed.get("new_percent", 0)) > 0
                       and new_deferred <= 0 < limit - so_far)
    income = case.wages + other
    if leave and leave.year == year and confirmed.get("loan_repaid") != "yes" and "loan" in confirmed:
        case.loan_taxed = Decimal(confirmed["loan"])
    tax = paystub.tax_on(income + case.loan_taxed, year, filing)
    if tax is not None:
        before = paystub.tax_on(income, year, filing)
        rate = paystub.STATE_RATES.get((read.state, year), Decimal(0))
        early = case.loan_taxed * EARLY
        case.loan_cost = _cents(tax - before + early + case.loan_taxed * rate)
        case.tax = _cents(tax + early)
        case.balance = _cents(case.tax - case.withheld - case.social_security_back)
    case.withheld = _cents(case.withheld)
    case.old_wages, case.new_wages, case.deferred, case.room = (
        _cents(case.old_wages), _cents(case.new_wages), _cents(case.deferred), _cents(case.room))
    plan = estimates.build(year, returns=returns, confirmed={"withheld": str(case.withheld)}, filing=filing)
    case.quarters_short = plan.short
    return case


def _paycheck(read: paystub.Paystub, confirmed: dict, year: int, filing: str) -> tuple[Decimal, Decimal, Decimal]:
    """A paycheck left's federal taxable wages, federal tax withheld and 401(k) deferrals, at `percent` if it's set."""
    wage, federal = read.taxable_wages.current, read.withheld["federal"].current
    deferred = sum((d.current for d in read.deferred.values()), Decimal(0))
    pretax = read.deferred.get("pretax")
    if "percent" not in confirmed or not (pretax and read.salary and read.frequency):
        return wage, federal, deferred
    planned = (read.salary.current * Decimal(confirmed["percent"]) / 100).quantize(CENT, ROUND_HALF_UP)
    change = planned - pretax.current
    periods = paystub.PERIODS[read.frequency]
    annual = wage * periods
    before, after = paystub.tax_on(annual, year, filing), paystub.tax_on(annual - change * periods, year, filing)
    moved = (before - after) / periods if before is not None and after is not None else Decimal(0)
    return wage - change, federal - moved, deferred + change


def _annual_salary(read: paystub.Paystub) -> Decimal | None:
    return read.salary.current * paystub.PERIODS[read.frequency] if read.salary and read.frequency else None


def _cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, ROUND_HALF_UP)


def rollover_deadline(year: int) -> date:
    """The last day to roll a plan loan offset over: the return's due date with extensions."""
    day = date(year + 1, 10, 15)
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day


def to_json(c: Comparison) -> dict:
    def plain(v):
        return str(v) if isinstance(v, Decimal) else v

    return {"year": c.year, "leave": c.leave.isoformat() if c.leave else None,
            "start": c.start.isoformat() if c.start else None, "after_year": c.after_year,
            "rollover_deadline": rollover_deadline(c.year).isoformat(),
            "cases": [{"name": k.name, "paychecks": k.paychecks, "wages": str(k.wages), "old_wages": str(k.old_wages),
                       "new_wages": str(k.new_wages), "withheld": str(k.withheld),
                       "social_security": plain(k.social_security), "social_security_back": str(k.social_security_back),
                       "deferred": str(k.deferred), "room": plain(k.room), "over_limit": k.over_limit,
                       "loan_taxed": str(k.loan_taxed), "loan_cost": str(k.loan_cost), "tax": plain(k.tax),
                       "balance": plain(k.balance), "quarters_short": k.quarters_short} for k in c.cases],
            "questions": [q.text for q in c.questions]}
