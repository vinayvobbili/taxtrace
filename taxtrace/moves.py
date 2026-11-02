"""A year's tax-saving moves, ranked by the dollars each saves, with its deadline.

Each move's saving is what it takes off the year's tax at your own brackets: the wages the latest pay stub projects
and last year's other income, past the standard deduction, plus the state's flat rate where the state allows it too.
Moves are stacked in a fixed order, each from the income the ones before it left, so two moves in one bracket aren't
counted at a rate neither gets:

- The 401(k)'s room, up to what the plan's percentage cap can still reach in the paychecks left (`plan_cap=N`).
- Stock losses, up to the room `sales` found against other income. A loss is worth having only while it isn't undone:
  nothing bought back for 30 days, in any account.
- The rental's property tax paid by December 31 (`rental_tax=AMOUNT`), when no escrow pays it: a cash-basis deduction
  on Schedule E in the year it's paid.
- A spouse's or your own IRA, at what `ira` finds deductible, by next April 15.
- Cash gifts to charity without itemizing, up to $2,000 filing jointly ($1,000 otherwise) from 2026, federal only.
  Giving a dollar saves only part of one, so it's for giving you'd do anyway (`charity=AMOUNT`, what you'd give).

`jobchange` adds what it found: Social Security withheld past the wage base coming back, and what an unpaid 401(k)
loan would cost. What a return-time item saves, like the foreign tax credit, is the return's to work out, so those are
listed without a figure. A move done is kept with `--confirm done_401k=yes`, and shown last.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, ROUND_UP, Decimal, InvalidOperation

from . import ira, paystub
from .prior import Question

CENT = Decimal("0.01")
CHARITY = {"joint": Decimal(2000)}  # without itemizing, from 2026; $1,000 for every other filing
CHARITY_OTHER = Decimal(1000)
CHARITY_FROM = 2026
AMOUNTS = ("plan_cap", "rental_tax", "charity", "other")
DONE = ("401k", "losses", "rental_tax", "spouse_ira", "own_ira", "charity")
AT_THE_RETURN = (
    "the foreign tax credit and last year's carryover (`foreign`)",
    "every rental expense on Schedule E, the repairs and the insurance's rental share too (`rental`)",
    "the qualified business income deduction (`qbi`) and passive losses carried in (`passive`)",
)


@dataclass
class Move:
    key: str
    name: str
    action: str
    by: date
    amount: Decimal  # what it moves: deferred, deducted, paid
    saving: Decimal  # off the year's tax
    done: bool = False


@dataclass
class Plan:
    year: int
    income: Decimal | None = None  # what the moves are stacked on
    moves: list[Move] = field(default_factory=list)
    at_the_return: tuple[str, ...] = AT_THE_RETURN
    questions: list[Question] = field(default_factory=list)

    def ask(self, text: str) -> None:
        self.questions.append(Question(text, 0, ""))

    @property
    def open_saving(self) -> Decimal:
        return sum((m.saving for m in self.moves if not m.done), Decimal(0))


def confirmation(spec: str) -> tuple[str, str]:
    """'plan_cap=20', 'rental_tax=3,000', 'charity=500', 'done_401k=yes'."""
    key, sep, value = (s.strip().lower() for s in spec.partition("="))
    usage = ValueError("--confirm takes plan_cap=N, rental_tax=AMOUNT, charity=AMOUNT, other=AMOUNT or done_MOVE=yes "
                       f"({', '.join(DONE)})")
    if sep and key.startswith("done_") and key[5:] in DONE and value in ("yes", "no"):
        return key, value
    if not sep or key not in AMOUNTS:
        raise usage
    try:
        number = Decimal(value.replace(",", "").lstrip("$"))
    except InvalidOperation:
        raise usage from None
    if not number.is_finite() or number < 0:
        raise usage
    return key, str(number)


def build(year: int, *, stub: dict | None, returns: list[dict], confirmed: dict | None = None, filing: str = "",
          sales: dict | None = None, jobchange: dict | None = None) -> Plan:
    confirmed = confirmed or {}
    plan = Plan(year)
    filing = filing or "joint"
    if stub is None or not stub.get("taxable_wages"):
        plan.ask(f"no {year} pay stub with its federal taxable wages has been read (`taxtrace paystub`)")
        return plan
    read = paystub.from_json(stub)
    other = Decimal(confirmed["other"]) if "other" in confirmed else ira.last_other(year, returns)
    if other is None:
        plan.ask(f"the {year - 1} Form 1040's income lines aren't read (`taxtrace prior`), so only the wages are "
                 f"counted: `--confirm other=AMOUNT` for {year}'s income besides them")
        other = Decimal(0)
    income = read.projected_wages() + other
    if paystub.tax_on(income, year, filing) is None:
        plan.ask(f"{year}'s brackets for this filing status aren't in taxtrace yet")
        return plan
    plan.income = income
    state = paystub.STATE_RATES.get((read.state, year), Decimal(0))
    year_end, april = date(year, 12, 31), date(year + 1, 4, 15)

    def add(key: str, name: str, action: str, by: date, amount: Decimal, *, state_too: bool = True) -> None:
        nonlocal income
        if amount <= 0:
            return
        federal = paystub.tax_on(income, year, filing) - paystub.tax_on(income - amount, year, filing)
        saving = (federal + (amount * state if state_too else 0)).quantize(CENT, ROUND_HALF_UP)
        plan.moves.append(Move(key, name, action, by, amount, saving, confirmed.get(f"done_{key}") == "yes"))
        income -= amount

    room, percent = _deferrals(read, confirmed)
    add("401k", "Fill the 401(k)", f"raise the pre-tax deferral to {percent}% of salary" if percent else
        "defer more pre-tax from the paychecks left", (read.paydays() or [year_end])[-1], room)
    if sales is None:
        plan.ask(f"stock sales aren't worked out yet (`taxtrace sales --year {year}`), so the losses aren't ranked")
    else:
        add("losses", "Harvest stock losses", "sell at a loss, and buy nothing the same for 30 days in any account",
            year_end, Decimal(sales["room"]))
    add("rental_tax", "Pay the rental's property tax", "pay it by December 31 for this year's Schedule E", year_end,
        Decimal(confirmed.get("rental_tax", 0)))
    _iras(plan, year, stub, returns, confirmed, add, april)
    limit = CHARITY.get(filing, CHARITY_OTHER) if year >= CHARITY_FROM else Decimal(0)
    given = min(limit, Decimal(confirmed["charity"])) if "charity" in confirmed else limit
    add("charity", "Give to charity in cash", "only giving you'd do anyway: keep the receipts", year_end, given,
        state_too=False)
    if limit and "charity" not in confirmed:
        plan.ask("the charity move takes the whole limit and assumes you don't itemize: `--confirm charity=AMOUNT` "
                 "for what you'd give")
    _job(plan, jobchange)
    plan.moves.sort(key=lambda m: (m.done, -m.saving))
    return plan


def _deferrals(read: paystub.Paystub, confirmed: dict) -> tuple[Decimal, Decimal | None]:
    """What more the 401(k) can take in the paychecks left, and the pre-tax percentage that gets there."""
    room, left = read.deferral_room() or Decimal(0), read.paychecks_left()
    pretax = read.deferred.get("pretax")
    if not (room and left and pretax and read.salary and read.salary.current):
        return Decimal(0), None
    fills = ((pretax.current + room / left) / read.salary.current * 100).quantize(Decimal(1), ROUND_UP)
    if "plan_cap" not in confirmed:
        return room, fills
    cap = Decimal(confirmed["plan_cap"])
    reachable = max(Decimal(0), read.salary.current * cap / 100 - pretax.current) * left
    return min(room, reachable), min(cap, fills)


def _iras(plan: Plan, year: int, stub: dict, returns: list[dict], confirmed: dict, add, by: date) -> None:
    other = {"other": confirmed["other"]} if "other" in confirmed else {}
    outlook = ira.build(year, stub=stub, returns=returns, confirmed=other)
    case = next((c for c in outlook.cases if c.name == "401(k) filled"), None)
    if case is None:
        plan.ask(f"{year}'s IRA deductions aren't worked out (`taxtrace ira --year {year}`)")
        return
    add("spouse_ira", "Contribute to the IRA of the spouse without a 401(k)", "contribute and deduct it, for this year",
        by, case.other_spouse)
    add("own_ira", "Contribute to your own IRA", "contribute and deduct it, for this year", by, case.covered_spouse)


def _job(plan: Plan, jobchange: dict | None) -> None:
    cases = (jobchange or {}).get("cases", [])
    if len(cases) < 2:
        return
    leave = date.fromisoformat(jobchange["leave"])
    case = cases[1]
    if Decimal(case["loan_cost"]):
        plan.moves.append(Move("loan", "Repay or roll over the 401(k) loan", "repay it before leaving, or roll the "
                               "same amount over by next October 15, if you leave as planned", leave,
                               Decimal(case["loan_taxed"]), Decimal(case["loan_cost"])))
    if Decimal(case["social_security_back"]):
        back = Decimal(case["social_security_back"])
        plan.moves.append(Move("social_security", "Claim Social Security withheld twice", "Schedule 3 line 11, if you "
                               "leave as planned", date(plan.year + 1, 4, 15), back, back))


def to_json(p: Plan) -> dict:
    return {"year": p.year, "income": str(p.income) if p.income is not None else None,
            "open_saving": str(p.open_saving),
            "moves": [{"key": m.key, "name": m.name, "action": m.action, "by": m.by.isoformat(),
                       "amount": str(m.amount), "saving": str(m.saving), "done": m.done} for m in p.moves],
            "at_the_return": list(p.at_the_return), "questions": [q.text for q in p.questions]}
