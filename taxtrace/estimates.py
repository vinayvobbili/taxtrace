"""A year's estimated tax: whether what's withheld and paid during the year meets the safe harbor, quarter by quarter.

No underpayment penalty (Form 2210) is due when the year's payments reach the smaller of 90% of the year's own tax
and 100% of last year's, 110% when last year's adjusted gross income was over $150,000 ($75,000 married filing
separately). Last year's tax is the Carryover Worksheet's "Federal tax liability" row, the figure the preparer's
Form 2210 uses, or else the filed Form 1040's total tax (line 24) less its refundable credits (line 32).

That amount is due in four quarters, a quarter of it each by April 15, June 15, September 15 and January 15, and
each quarter is checked on its own: a payment counts on the day it's made, so a January payment can't make up an
earlier quarter. Tax withheld from pay counts as paid evenly through the year however late it was withheld, so
more withholding before the year ends makes up every quarter, and less takes from every quarter: the margin is
what it could fall by with each still met. Deferring the 401(k)'s room left (`paystub`) withholds less, about 24
cents a dollar, so that's checked against the margin. Last year's overpayment applied to this year (its
line 36) counts as paid on April 15.

The year's withholding is the latest pay stub's projection (`paystub`): its year to date's, and its paycheck's for
each one left. What only you know is kept with `--confirm`: `withheld=AMOUNT` (the year's federal tax withheld in
all, in place of the pay stub's projection: more W-2s, a 1099's), `paid_YYYY-MM-DD=AMOUNT` (an estimated payment and
the day it was made) and `tax=AMOUNT` (the year's own tax, once it's known).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, ROUND_UP, Decimal

from .prior import Check, Question

CENT = Decimal("0.01")
NINETY = Decimal("0.90")
HIGHER = Decimal("1.10")  # last year's tax, when its AGI was over the threshold
THRESHOLD = {"separate": Decimal(75000)}  # last year's AGI past which 110% applies; $150,000 for every other filing
OVER = Decimal(150000)
DEFERRAL_WITHHOLDING = Decimal("0.24")  # a pre-tax dollar's withholding at the 24% bracket's rate: on the safe side
LIABILITY = "federal tax liability for"  # the Carryover Worksheet's row: "Federal tax liability for 2025 calculation"


def due(year: int) -> list[date]:
    """The four quarters' due days (a weekend or holiday moves one to the next business day; a payment made by
    then is on time)."""
    return [date(year, 4, 15), date(year, 6, 15), date(year, 9, 15), date(year + 1, 1, 15)]


@dataclass
class Quarter:
    due: date
    required: Decimal  # what's due by then, all quarters so far
    paid: Decimal  # what's counted by then: the withholding's share, the payments made by then
    short: Decimal  # what the quarter is short, zero when met


@dataclass
class Plan:
    year: int
    last_tax: Decimal | None = None  # last year's tax, for the safe harbor
    last_agi: Decimal | None = None
    rate: Decimal | None = None  # 100% or 110% of last year's tax
    required: Decimal | None = None  # the year's required payments in all
    withheld: Decimal | None = None
    withholding_from: str = ""  # "confirmed", or the pay stub it's projected from
    applied: Decimal = Decimal(0)  # last year's overpayment applied to this year (its line 36)
    payments: dict[str, Decimal] = field(default_factory=dict)  # ISO day: an estimated payment
    quarters: list[Quarter] = field(default_factory=list)
    more_withholding: Decimal = Decimal(0)  # more withheld before the year ends that meets every quarter
    january: Decimal = Decimal(0)  # a January payment that meets the last quarter (only it)
    margin: Decimal = Decimal(0)  # what the withholding could fall by with every quarter still met
    deferral_cut: Decimal | None = None  # what filling the 401(k)'s room would take off the withholding
    checks: list[Check] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    def ask(self, question: str) -> None:
        self.questions.append(Question(question, 0, ""))

    @property
    def short(self) -> list[int]:
        """The quarters (1 to 4) that are short."""
        return [k for k, q in enumerate(self.quarters, 1) if q.short > 0]


def confirmation(spec: str) -> tuple[str, str]:
    """'withheld=24,000', 'tax=31,000' or 'paid_2026-09-15=2,500'."""
    key, sep, value = (s.strip().lower() for s in spec.partition("="))
    ok = key in ("withheld", "tax") or bool(re.fullmatch(r"paid_\d{4}-\d{2}-\d{2}", key))
    number = Decimal(-1)
    try:
        if ok and key.startswith("paid_"):
            date.fromisoformat(key[5:])
        number = Decimal(value.replace(",", "").lstrip("$"))
    except (ArithmeticError, ValueError):  # a day that isn't one, an amount that isn't a number
        ok = False
    if not sep or not ok or not number.is_finite() or number < 0:
        raise ValueError("--confirm takes withheld=AMOUNT, tax=AMOUNT, or paid_YYYY-MM-DD=AMOUNT")
    return key, str(number)


def last_tax(filed: dict) -> tuple[Decimal | None, str]:
    """Last year's tax for the safe harbor, from a saved return (`prior`), and where it came from."""
    row = next((i for i in filed.get("carryovers", []) if i["label"].lower().startswith(LIABILITY)), None)
    if row and "amount" in row["amounts"]:
        return Decimal(row["amounts"]["amount"]), "the Carryover Worksheet"
    lines = (filed.get("f1040") or {}).get("lines", {})
    if "24" in lines:
        return Decimal(lines["24"]) - Decimal(lines.get("32", 0)), "Form 1040 lines 24 less 32"
    return None, ""


def latest_stub(forms: list[dict], year: int) -> dict | None:
    """The year's last pay stub read (`taxtrace paystub`), by its payment date."""
    stubs = [f for f in forms if f.get("form") == "paystub" and f.get("year") == year and f.get("paid")]
    return max(stubs, key=lambda f: f["paid"], default=None)


def build(year: int, *, returns: list[dict], confirmed: dict | None = None, filing: str = "",
          stub: dict | None = None) -> Plan:
    """The year's estimated tax plan from last year's filed return (`prior`), the year's latest pay stub
    (`paystub`, whose projection is the year's withholding unless one is confirmed) and what's confirmed."""
    confirmed = confirmed or {}
    plan = Plan(year)
    filed = next((r for r in returns if r.get("year") == year - 1 and (r.get("f1040") or r.get("carryovers"))),
                 None)
    if filed is None:
        plan.ask(f"the {year - 1} return isn't read (`taxtrace prior`): its tax is the safe harbor's")
        return plan
    plan.last_tax, source = last_tax(filed)
    lines = {k: Decimal(v) for k, v in (filed.get("f1040") or {}).get("lines", {}).items()}
    plan.last_agi = next((lines[n] for n in ("11", "11a", "11b") if n in lines), None)
    plan.applied = lines.get("36", Decimal(0))
    if plan.last_tax is None:
        plan.ask(f"the {year - 1} return's tax isn't read: neither the Carryover Worksheet's federal tax liability "
                 "nor Form 1040 line 24")
        return plan
    if source == "the Carryover Worksheet" and "24" in lines:
        figured = lines["24"] - lines.get("32", Decimal(0))
        plan.checks.append(Check(f"the Carryover Worksheet's {year - 1} tax is Form 1040 line 24 less line 32",
                                 abs(figured - plan.last_tax) <= 1, 0))
    if plan.last_agi is None:
        plan.ask(f"the {year - 1} Form 1040's adjusted gross income (line 11) isn't read: over $150,000 ($75,000 "
                 "married filing separately) the safe harbor is 110% of its tax, so 110% is taken")
    plan.rate = HIGHER if plan.last_agi is None or plan.last_agi > THRESHOLD.get(filing, OVER) else Decimal(1)
    plan.required = (plan.last_tax * plan.rate).quantize(CENT, ROUND_HALF_UP)
    if "tax" in confirmed:
        plan.required = min(plan.required, (Decimal(confirmed["tax"]) * NINETY).quantize(CENT, ROUND_HALF_UP))
    else:
        plan.ask(f"{year}'s own tax isn't known yet: 90% of it is the safe harbor when that's less than last year's "
                 f"(`--confirm tax=AMOUNT` once the return is worked out)")
    plan.payments = {k[5:]: Decimal(v) for k, v in sorted(confirmed.items()) if k.startswith("paid_")}
    if "withheld" in confirmed:
        plan.withheld, plan.withholding_from = Decimal(confirmed["withheld"]), "confirmed"
    elif stub and stub.get("projected_federal") is not None:
        plan.withheld = Decimal(stub["projected_federal"])
        paid = date.fromisoformat(stub["paid"])
        plan.withholding_from = (f"the pay stub paid {paid:%b} {paid.day}, {paid.year} and its "
                                 f"{stub['paychecks_left']} paychecks left")
    else:
        plan.ask(f"how much federal tax {year}'s W-2s and 1099s withhold in all, the year's last paychecks "
                 "included: read the latest pay stub (`taxtrace paystub`), or `--confirm withheld=AMOUNT`")
        return plan
    for k, day in enumerate(due(year), 1):
        required = (plan.required * k / 4).quantize(CENT, ROUND_HALF_UP)
        paid = (plan.withheld * k / 4).quantize(CENT, ROUND_HALF_UP) + plan.applied + sum(
            (v for d, v in plan.payments.items() if date.fromisoformat(d) <= day), Decimal(0))
        plan.quarters.append(Quarter(day, required, paid, max(Decimal(0), required - paid)))
    # more withholding counts a quarter of itself in each quarter, so it has to cover each quarter's shortfall
    # by that quarter's share: four times the first's, twice the second's...
    plan.more_withholding = max((q.short * 4 / k for k, q in enumerate(plan.quarters, 1)),
                                default=Decimal(0)).quantize(CENT, ROUND_UP)
    plan.january = plan.quarters[-1].short
    # and less withholding takes a quarter of itself from each: what it could fall by with every quarter still met
    plan.margin = max(Decimal(0), min((q.paid - q.required) * 4 / k for k, q in enumerate(plan.quarters, 1))
                      ).quantize(CENT, ROUND_HALF_UP)
    if stub and stub.get("deferral_room"):
        # deferring the 401(k)'s room left takes it out of the taxable wages the paychecks left withhold on
        plan.deferral_cut = (Decimal(stub["deferral_room"]) * DEFERRAL_WITHHOLDING).quantize(CENT, ROUND_HALF_UP)
    return plan


def to_json(plan: Plan) -> dict:
    def plain(v):
        return str(v) if isinstance(v, Decimal) else v

    return {"year": plan.year, "last_tax": plain(plan.last_tax), "last_agi": plain(plan.last_agi),
            "rate": plain(plan.rate), "required": plain(plan.required), "withheld": plain(plan.withheld),
            "withholding_from": plan.withholding_from,
            "applied": plain(plan.applied), "payments": {d: str(v) for d, v in plan.payments.items()},
            "quarters": [{"due": q.due.isoformat(), "required": str(q.required), "paid": str(q.paid),
                          "short": str(q.short)} for q in plan.quarters],
            "more_withholding": str(plan.more_withholding), "january": str(plan.january),
            "margin": str(plan.margin), "deferral_cut": plain(plan.deferral_cut),
            "checks": [{"what": c.what, "ok": c.ok} for c in plan.checks],
            "questions": [q.text for q in plan.questions]}
