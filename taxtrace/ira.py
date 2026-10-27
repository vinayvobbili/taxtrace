"""How much of a year's traditional IRA contribution each spouse can deduct, and whether a Roth IRA is open, from
the year's income as the latest pay stub and last year's return project it.

A married couple filing jointly can each contribute up to the year's limit ($7,500 in 2026), a spouse without pay
on the other's. The deduction phases out over a range of modified adjusted gross income: for a spouse covered by a
workplace plan (a 401(k)) the lower range, for a spouse who isn't but is married to one who is, the higher one. In
the range, the deduction is the limit less its share of how far into the range the income is, rounded up to the
next $10, and $200 at least while there's any. A Roth IRA contribution phases out over its own range.

The year's income is the pay stub's federal taxable wages projected to December 31 (`paystub`), as they are and
with the 401(k)'s room filled, and last year's other income: its taxable interest, ordinary dividends and
Schedule 1 income (the rental, the K-1s), less its adjustments. Last year's capital gain is left out, since a sale
seldom repeats. `--confirm other=AMOUNT` puts the year's own figure in its place.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_UP, Decimal

from .prior import Question

LIMIT = {2025: Decimal(7000), 2026: Decimal(7500)}
# married filing jointly: (start, end) of each phase-out range of modified AGI
COVERED = {2025: (Decimal(126000), Decimal(146000)), 2026: (Decimal(129000), Decimal(149000))}
SPOUSE_COVERED = {2025: (Decimal(236000), Decimal(246000)), 2026: (Decimal(242000), Decimal(252000))}
ROTH = {2025: (Decimal(236000), Decimal(246000)), 2026: (Decimal(242000), Decimal(252000))}
OTHER_LINES = ("2b", "3b", "8")  # last year's Form 1040 lines that recur: interest, dividends, Schedule 1 income


def deductible(limit: Decimal, magi: Decimal, phase: tuple[Decimal, Decimal]) -> Decimal:
    """The deductible part of a full contribution at this income (Pub. 590-A's worksheet)."""
    start, end = phase
    if magi <= start:
        return limit
    if magi >= end:
        return Decimal(0)
    allowed = limit - limit * (magi - start) / (end - start)
    allowed = (allowed / 10).quantize(Decimal(1), ROUND_UP) * 10
    return max(allowed, Decimal(200))


@dataclass
class Case:
    name: str  # "as is", "401(k) filled"
    magi: Decimal
    covered_spouse: Decimal  # what the spouse with the 401(k) can deduct
    other_spouse: Decimal  # what the spouse without one can deduct
    roth: Decimal  # what a Roth IRA takes, each


@dataclass
class Outlook:
    year: int
    limit: Decimal | None = None
    wages: dict[str, Decimal] = field(default_factory=dict)  # "as is", "401(k) filled"
    other: Decimal | None = None
    other_from: str = ""
    cases: list[Case] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    def ask(self, text: str) -> None:
        self.questions.append(Question(text, 0, ""))


def confirmation(spec: str) -> tuple[str, str]:
    """'other=12,500': the year's income besides the wages, in place of last year's."""
    key, sep, value = (s.strip().lower() for s in spec.partition("="))
    try:
        number = Decimal(value.replace(",", "").lstrip("$"))
    except ArithmeticError:
        number = Decimal("NaN")
    if not sep or key != "other" or not number.is_finite():
        raise ValueError("--confirm takes other=AMOUNT (the year's income besides the wages)")
    return key, str(number)


def build(year: int, *, stub: dict | None, returns: list[dict], confirmed: dict | None = None) -> Outlook:
    confirmed = confirmed or {}
    out = Outlook(year, LIMIT.get(year))
    if out.limit is None or year not in SPOUSE_COVERED:
        out.ask(f"{year}'s IRA limit and phase-out ranges aren't in taxtrace yet")
        return out
    wages = (stub or {}).get("projected_wages")
    if not wages:
        out.ask(f"no {year} pay stub with its federal taxable wages has been read (`taxtrace paystub`)")
        return out
    out.wages = {"as is": Decimal(wages["as_is"]), "401(k) filled": Decimal(wages["401k_filled"])}
    if "other" in confirmed:
        out.other, out.other_from = Decimal(confirmed["other"]), "confirmed"
    else:
        lines = next(((r.get("f1040") or {}).get("lines", {}) for r in returns
                      if r.get("year") == year - 1 and r.get("f1040")), {})
        if not lines:
            out.ask(f"the {year - 1} return's Form 1040 isn't read (`taxtrace prior`): its interest, dividends and "
                    f"Schedule 1 income stand in for {year}'s, or `--confirm other=AMOUNT`")
            return out
        if not any(n in lines for n in OTHER_LINES):
            out.ask(f"the {year - 1} Form 1040's income lines (2b, 3b, 8) aren't read: run `taxtrace prior` on it "
                    "again")
            return out
        out.other = sum((Decimal(lines.get(n, 0)) for n in OTHER_LINES), Decimal(0)) - Decimal(lines.get("10", 0))
        out.other_from = f"{year - 1}'s interest, dividends and Schedule 1 income"
        out.ask(f"{year}'s income besides the wages is taken to be {year - 1}'s, less its capital gain: a higher rent, "
                f"a fund's year-end capital gain distribution or a sale moves it (`--confirm other=AMOUNT`)")
    for name, w in out.wages.items():
        magi = w + out.other
        out.cases.append(Case(name, magi, deductible(out.limit, magi, COVERED[year]),
                              deductible(out.limit, magi, SPOUSE_COVERED[year]),
                              deductible(out.limit, magi, ROTH[year])))  # a Roth's limit shrinks the same way
    return out


def to_json(o: Outlook) -> dict:
    return {"year": o.year, "limit": str(o.limit) if o.limit is not None else None,
            "wages": {k: str(v) for k, v in o.wages.items()}, "other": str(o.other) if o.other is not None else None,
            "other_from": o.other_from,
            "cases": [{"name": c.name, "magi": str(c.magi), "covered_spouse": str(c.covered_spouse),
                       "other_spouse": str(c.other_spouse), "roth": str(c.roth)} for c in o.cases],
            "questions": [q.text for q in o.questions]}
