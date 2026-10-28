"""A variable universal life policy's annual statement, read for what the policy costs you: as shares, never amounts.

The insurer's statement gives, as of two dates (the previous statement and this one), the death benefit, the contract
fund (what the premiums, less the policy's charges, grew to), the surrender charge and the cash value (the fund less
that charge: what surrendering pays). It also says what the net payments so far add up to against what the no-lapse
guarantees need, and the fund's return. What decides keep, cut to the minimum or exchange is how these compare, so
`shares` turns them into percentages and multiples that can be read without the policy's figures.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from .prior import amount

MONEY = r"\$\s*(\d[\d,]*\.\d{2})"
DAY = r"([A-Z][a-z]+\.? \d{1,2}, \d{4})"
PREMIUM = re.compile(rf"Annual Billed Premium\s*{MONEY}")
TYPE = re.compile(r"Death Benefit Type\s+Type ([AB])\b")
ISSUED = re.compile(rf"Contract Date\s+{DAY}")
AS_OF = re.compile(rf"As of {DAY}:")
PAID = re.compile(rf"Your accumulated net payments of\s*{MONEY}")
NEEDED = re.compile(rf"needed for a No-Lapse Guarantee were\s*{MONEY}")
LIFETIME = re.compile(rf"No-Lapse Guarantee that extends beyond the first (\d+) policy years to age (\d+) "
                      rf"were\s*{MONEY}")
RETURNS = re.compile(r"Contract Fund Rate of Return(.*?)Annualized Return", re.DOTALL)
PERCENT = re.compile(r"(-?\d+(?:\.\d+)?)%")


def _both(label: str) -> re.Pattern[str]:
    """A row of the values table: the label, then the previous statement's value and this one's."""
    return re.compile(rf"{label}\s*-?\s*{MONEY}\s*-?\s*{MONEY}")


ROWS = {"death_benefit": _both("Base Policy Death Benefit"), "fund": _both("Contract Fund"),
        "surrender": _both("Surrender Charge"), "cash": _both("Cash Value")}


@dataclass
class Statement:
    file: str
    kind: str  # the death benefit type: "B" pays the face amount plus the fund, "A" the face amount
    issued: date
    as_of: date | None
    premium: Decimal  # the annual billed premium
    previous: dict[str, Decimal]  # ROWS' values at the previous statement
    current: dict[str, Decimal]
    paid: Decimal  # accumulated net payments
    needed: Decimal  # what the no-lapse guarantee needs now
    lifetime_needed: Decimal  # what the guarantee to `lifetime_age` needs
    lifetime_age: int
    returns: tuple[str, ...]  # the fund's return this year, then a year since the contract date, as printed


def _day(text: str) -> date:
    return datetime.strptime(text.replace(".", ""), "%B %d, %Y").date()


def read(name: str, pages: list[str]) -> Statement | None:
    """The statement among a document's pages, or None when it isn't a variable universal life statement."""
    whole = " ".join(" ".join(pages).split())
    rows = {k: pattern.search(whole) for k, pattern in ROWS.items()}
    if not all(rows.values()) or not (issued := ISSUED.search(whole)):
        return None

    def money(pattern: re.Pattern[str], group: int = 1) -> Decimal:
        return amount(m.group(group)) if (m := pattern.search(whole)) else Decimal(0)

    lifetime = LIFETIME.search(whole)
    returns = RETURNS.search(whole)
    return Statement(
        name, (m.group(1) if (m := TYPE.search(whole)) else ""), _day(issued.group(1)),
        (_day(m.group(1)) if (m := AS_OF.search(whole)) else None), money(PREMIUM),
        {k: amount(m.group(1)) for k, m in rows.items() if m}, {k: amount(m.group(2)) for k, m in rows.items() if m},
        money(PAID), money(NEEDED), money(LIFETIME, 3), int(lifetime.group(2)) if lifetime else 0,
        tuple(PERCENT.findall(returns.group(1))[:2]) if returns else ())


def _share(part: Decimal, whole: Decimal) -> str:
    return f"{part / whole:.0%}" if whole else "unknown"


def policy_year(s: Statement) -> int:
    """The policy year the statement's date falls in: the first year is 1."""
    on = s.as_of or date.today()
    years = on.year - s.issued.year - ((on.month, on.day) < (s.issued.month, s.issued.day))
    return years + 1


def shares(s: Statement) -> list[str]:
    """What the statement says about the policy's cost, as percentages and multiples of its own figures."""
    now, before = s.current, s.previous
    face = now["death_benefit"] - now["fund"] if s.kind == "B" else now["death_benefit"]
    lines = [f"Type {s.kind or '?'} death benefit, issued {s.issued.isoformat()}: policy year {policy_year(s)}"
             + (f" as of {s.as_of.isoformat()}" if s.as_of else ""),
             f"surrender charge: {_share(now['surrender'], now['fund'])} of the contract fund "
             f"({_share(before['surrender'], before['fund'])} at the previous statement), lost if surrendered now",
             f"cash value: {_share(now['cash'], s.paid)} of the net payments made so far; "
             f"the contract fund is {_share(now['fund'], s.paid)} of them"]
    if face > 0:
        lines.append(f"annual premium: {s.premium / face:.2%} of the insurance amount (the death benefit "
                     + ("less the fund)" if s.kind == "B" else ")"))
    if s.paid:
        lines.append(f"no-lapse guarantee: needs {_share(s.needed, s.paid)} of the payments made so far"
                     + (f"; the one to age {s.lifetime_age} needs {_share(s.lifetime_needed, s.paid)} of them"
                        if s.lifetime_needed else ""))
    if now["fund"]:
        lines.append(f"death benefit: {now['death_benefit'] / now['fund']:.1f}x the contract fund")
    if s.returns:
        lines.append("fund return: " + ", ".join(f"{r}%" for r in s.returns)
                     + " (this year to date, then a year since the contract date)")
    return lines
