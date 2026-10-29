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


# An in-force illustration: the insurer's projection of the policy from today, under a few hypothetical returns
# and current or maximum charges, year by year. Its Policy Status Report gives today's values; its ledger gives,
# for each policy year, the premium outlay, the contract fund, then each scenario's cash value and death benefit
# ("<" while the no-lapse guarantee holds, "END" in the year the policy lapses).

SLASHED = r"(\d{2}/\d{2}/\d{4})"
STATUS = {"billed": rf"Current Billed Premium.*?{MONEY}", "short": rf"Short-Term No-Lapse Guarantee Premium\s*{MONEY}",
          "limited": rf"Limited No-Lapse Guarantee Premium\s*{MONEY}", "fund": rf"Contract Fund\s*{MONEY}",
          "cash": rf"Cash Value\s*{MONEY}", "death_benefit": rf"Death Benefit\s*{MONEY}",
          "paid": rf"Total Premium Outlay to Date\s*{MONEY}", "face": rf"Current Basic Insurance Amount\s*{MONEY}",
          "next": rf"Next Scheduled Annual Premium\s*{MONEY}"}
ILLUSTRATED_TYPE = re.compile(r"Type ([AB]) \([^)]*\) Death Benefit")  # not the glossary's "a Type A (Fixed) death"
LEDGER_HEAD = re.compile(r"Year\s+Age\s+Outlay")
RATE = re.compile(r"(-?\d+\.\d+)%\s*\(Net\s*(-?\d+\.\d+)%\)")
CHARGES = re.compile(r"\b(Current|Maximum) Charges")
LEDGER_ROW = re.compile(r"\s*(\d+)\*?\s+(\d+)\s+(\d[\d,]*)\s+(\d[\d,]*)\s+(.+?)\s*")
CELL = re.compile(r"\d[\d,]*<?|END‡?")


@dataclass
class Scenario:
    gross: str  # the hypothetical gross return, as printed
    net: str  # after the policy's asset charges and fund expenses
    charges: str  # "current" or "maximum"


@dataclass
class Cell:
    cash: Decimal
    death_benefit: Decimal
    guaranteed: bool  # the no-lapse guarantee holds for the whole year


@dataclass
class Year:
    year: int  # the policy year: the first is 1
    age: int
    outlay: Decimal
    fund: Decimal  # the contract fund at the year's end, under the first scenario
    cells: dict[int, Cell | None]  # by scenario; None in the year it lapses


@dataclass
class Illustration:
    file: str
    kind: str
    issued: date | None
    values_date: date | None  # the day the illustrated values start from
    status: dict[str, Decimal]  # STATUS' values
    scenarios: list[Scenario]
    years: list[Year]


def _slashed(pattern: str, whole: str) -> date | None:
    m = re.search(rf"{pattern}\s*{SLASHED}", whole)
    return datetime.strptime(m.group(1), "%m/%d/%Y").date() if m else None


def _ledger(pages: list[str]) -> tuple[list[Scenario], list[Year]]:
    """The scenarios named over the ledger, and its rows: each row's cash values and death benefits paired off to the
    scenarios still in force, in order (a lapsed scenario's columns are left blank after its END year)."""
    scenarios: list[Scenario] = []
    years: list[Year] = []
    ended: set[int] = set()
    for page in pages:
        head = LEDGER_HEAD.search(page)
        if not head:
            continue
        if not scenarios:
            top = page[:head.start()]
            scenarios = [Scenario(g, n, c.lower())
                         for (g, n), c in zip(RATE.findall(top), CHARGES.findall(top), strict=False)]
        for line in page[head.end():].splitlines():
            m = LEDGER_ROW.fullmatch(line)
            tokens = m.group(5).split() if m else []
            if not tokens or len(tokens) % 2 or not all(CELL.fullmatch(t) for t in tokens):
                continue
            alive = [i for i in range(len(scenarios)) if i not in ended]
            cells: dict[int, Cell | None] = {}
            for i, (cash, death) in zip(alive, zip(tokens[::2], tokens[1::2], strict=True), strict=False):
                if cash.startswith("END"):
                    cells[i] = None
                    ended.add(i)
                else:
                    cells[i] = Cell(amount(cash), amount(death.rstrip("<")), death.endswith("<"))
            years.append(Year(int(m.group(1)), int(m.group(2)), amount(m.group(3)), amount(m.group(4)), cells))
    return scenarios, years


def read_illustration(name: str, pages: list[str]) -> Illustration | None:
    """The in-force illustration among a document's pages, or None when it isn't one."""
    whole = " ".join(" ".join(pages).split())
    if "Policy Status Report" not in whole or "Next Scheduled Annual Premium" not in whole:
        return None
    scenarios, years = _ledger(pages)
    if not scenarios or not years:
        return None
    status = {k: amount(m.group(1)) if (m := re.search(p, whole)) else Decimal(0) for k, p in STATUS.items()}
    return Illustration(name, (m.group(1) if (m := ILLUSTRATED_TYPE.search(whole)) else ""),
                        _slashed("Policy Issue Date", whole), _slashed("Policy Values Date", whole), status,
                        scenarios, years)


def _growth(start: Decimal, end: Decimal, years: int) -> str:
    return f"{float(end / start) ** (1 / years) - 1:.1%}" if start > 0 and end > 0 else "none"


def illustration_shares(ill: Illustration) -> list[str]:
    """What the illustration says the policy does from here, as shares, growth rates and years, never its figures."""
    s, first = ill.status, ill.years[0]
    lines = [f"in-force illustration: Type {ill.kind or '?'} death benefit"
             + (f", issued {ill.issued.isoformat()}" if ill.issued else "")
             + (f", values as of {ill.values_date.isoformat()}" if ill.values_date else "")]
    if not any(y.outlay for y in ill.years) and not s["next"]:
        lines.append("illustrated with no more premiums"
                     + ("; the premium on file is still billed: ask the insurer to stop billing it" if s["billed"]
                        else ""))
    elif s["billed"]:
        lines.append(f"illustrated premiums: {s['next'] / s['billed']:.0%} of the billed premium a year")
    if s["paid"]:
        lines.append(f"today: cash value {_share(s['cash'], s['paid'])} of the premiums paid; the contract fund "
                     f"{_share(s['fund'], s['paid'])}, of which the surrender charge is "
                     f"{_share(s['fund'] - s['cash'], s['fund'])}")
    if s["cash"] and s["death_benefit"]:
        lines.append(f"death benefit today: {s['death_benefit'] / s['cash']:.1f}x the cash value")
    if s["billed"] and (s["short"] or s["limited"]):
        lines.append(f"no-lapse guarantee premiums: short-term {_share(s['short'], s['billed'])}, limited "
                     f"{_share(s['limited'], s['billed'])} of the billed premium")
    charged = [y for y in ill.years if (c := y.cells.get(0)) and y.fund > c.cash]
    free = next((y for y in ill.years if (c := y.cells.get(0)) and y.fund <= c.cash), None)
    lines.append("surrender charge: " + "".join(f"{_share(y.fund - y.cells[0].cash, y.fund)} of the fund at the end "
                                                f"of policy year {y.year}, " for y in charged)
                 + (f"none from policy year {free.year} (age {free.age})" if free else "past the illustration"))
    for i, sc in enumerate(ill.scenarios):
        held = [y for y in ill.years if (c := y.cells.get(i)) and c.guaranteed]
        lapse = next((y for y in ill.years if i in y.cells and y.cells[i] is None), None)
        last = [y for y in ill.years if y.cells.get(i)]
        parts = [(f"lapses in policy year {lapse.year} (age {lapse.age})" if lapse
                  else f"in force through age {last[-1].age}" if last else "not illustrated"),
                 f"no-lapse guarantee through policy year {held[-1].year} (age {held[-1].age})" if held
                 else "no no-lapse guarantee"]
        start = first.cells.get(i)
        for n in (10, 20):
            later = next((y for y in ill.years if y.year == first.year + n and y.cells.get(i)), None)
            if start and later:
                parts.append(f"cash value grows {_growth(start.cash, later.cells[i].cash, n)} a year over the "
                             f"{n} years from policy year {first.year} (to age {later.age})")
        lines.append(f"{sc.gross}% gross ({sc.net}% net), {sc.charges} charges: " + "; ".join(parts))
    return lines
