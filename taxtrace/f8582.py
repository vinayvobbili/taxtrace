"""Form 8582, the passive activity loss limit, worked out for a year (the form as revised for 2024: Parts I to VII).

Each activity goes in Part IV (rental real estate with active participation) or Part V (every other passive
activity) with this year's net income or loss and the unallowed loss it brings in. Line 3 adds them all: zero or
more, and every loss is allowed. A loss, and Part II's special allowance (up to $25,000 for rental real estate with
active participation, phased out between $100,000 and $150,000 of modified adjusted gross income) lets part of the
rental's loss through; the rest of line 3's loss is unallowed and spread over the activities with an overall loss
by their share of the losses (Part VII), to carry to next year. An activity disposed of in full at an overall loss
isn't on the form: its losses, carried ones too, are allowed in full.

An older return's worksheets (Worksheets 1 and 3, 4, 5 and 6 before 2024) hold the same numbers, so `rehearse`
works a filed return's form out again from its own Worksheets 1 and 3 and checks it against its Worksheet 5.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .prior import Check, Question

ZERO = Decimal(0)
DOLLAR = Decimal(1)
# Part II: the special allowance and where its phase-out ends, for a joint return (and single); married filing
# separately and living apart all year, half; living together any time in the year, none
ALLOWANCE = {"joint": (Decimal(25000), Decimal(150000)), "separate": (Decimal(12500), Decimal(75000))}
NEAR = Decimal(2)  # a filed worksheet's whole dollars against ratios worked out exactly


@dataclass
class Activity:
    name: str
    part: str  # "IV": rental real estate with active participation; "V": every other passive activity
    current: Decimal  # this year's net income (positive) or loss (negative)
    carried: Decimal = ZERO  # the unallowed loss it brings in from earlier years, as a positive amount
    final: bool = False  # disposed of in full this year
    special: Decimal = ZERO  # its share of Part II's special allowance (Part VI)
    unallowed: Decimal = ZERO  # what carries on to next year (Part VII)
    outside: bool = False  # a full disposition at an overall loss: allowed in full, not on the form

    @property
    def overall(self) -> Decimal:
        """Its overall gain (positive) or loss (negative): columns (d) and (e)."""
        return self.current - self.carried

    @property
    def allowed(self) -> Decimal:
        """What reaches the return from it this year: its income less the losses the form lets through."""
        return self.overall + self.unallowed


@dataclass
class Form:
    year: int
    activities: list[Activity] = field(default_factory=list)
    lines: dict[str, Decimal] = field(default_factory=dict)  # "1a" to "3", "4" to "9", "10", "11"
    questions: list[Question] = field(default_factory=list)

    def ask(self, text: str, quote: str = "") -> None:
        self.questions.append(Question(text, 0, quote))

    def to_json(self) -> dict:
        out = asdict(self)
        for a, row in zip(self.activities, out["activities"], strict=True):
            row["allowed"] = a.allowed
        return out


def compute(year: int, activities: list[Activity], *, magi: Decimal | None = None, filing: str = "",
            lived_apart: bool | None = None) -> Form:
    """The year's Form 8582 for these activities; each one's `special` and `unallowed` are set in place."""
    form = Form(year, activities)
    n = form.lines
    for a in activities:
        a.special = a.unallowed = ZERO
        a.outside = a.final and a.overall < 0
    on = [a for a in activities if not a.outside]
    for part, first in (("IV", "1"), ("V", "2")):
        mine = [a for a in on if a.part == part]
        n[first + "a"] = sum((a.current for a in mine if a.current > 0), ZERO)
        n[first + "b"] = sum((a.current for a in mine if a.current < 0), ZERO)
        n[first + "c"] = -sum((a.carried for a in mine), ZERO)
        n[first + "d"] = n[first + "a"] + n[first + "b"] + n[first + "c"]
    n["3"] = n["1d"] + n["2d"]
    n["9"] = ZERO
    if n["3"] < 0 and n["1d"] < 0:
        _special(form, magi, filing, lived_apart)
    n["10"] = n["1a"] + n["2a"]
    n["11"] = n["9"] + n["10"]
    if n["3"] >= 0:
        return form
    if n["9"]:  # Part VI: the special allowance shared by the rental activities with an overall loss
        losers = [a for a in on if a.part == "IV" and a.overall < 0]
        _share(losers, [-a.overall for a in losers], n["9"], "special")
    losers = [a for a in on if a.overall < 0]
    losses = [-a.overall - a.special for a in losers]  # Part VII column (a): Part VI's (d) for the rental ones
    _share(losers, losses, -n["3"] - n["9"], "unallowed")
    return form


def _special(form: Form, magi: Decimal | None, filing: str, lived_apart: bool | None) -> None:
    """Part II, lines 4 to 9."""
    n = form.lines
    n["4"] = min(-n["1d"], -n["3"])
    if filing == "separate" and not lived_apart:
        if lived_apart is None:
            form.ask("married filing separately: the special allowance is only for a spouse who lived apart all "
                     "year (`--confirm lived_apart=yes|no`)")
        return
    cap, top = ALLOWANCE["separate" if filing == "separate" else "joint"]
    n["5"] = top
    if magi is None:
        form.ask(f"Part II: the special allowance for the rental's loss needs {form.year}'s modified adjusted gross "
                 f"income (`--confirm magi=AMOUNT`); without it none is taken")
        return
    n["6"] = max(magi, ZERO)
    n["7"] = max(n["5"] - n["6"], ZERO)
    n["8"] = min(n["7"] / 2, cap)
    n["9"] = min(n["4"], n["8"])


def _share(activities: list[Activity], losses: list[Decimal], total: Decimal, into: str) -> None:
    """Spread `total` over the activities by their share of `losses`, in whole dollars, the last one taking what
    rounding leaves so the shares add up to it."""
    whole = sum(losses, ZERO)
    left = total
    for i, (a, loss) in enumerate(zip(activities, losses, strict=True)):
        share = left if i == len(activities) - 1 else (total * loss / whole).quantize(DOLLAR, ROUND_HALF_UP)
        setattr(a, into, share)
        left -= share


def from_filed(filed: dict) -> list[Activity]:
    """A filed return's activities, from its Worksheets 1 and 3 as `prior` saved them."""
    return [Activity(a["activity"], "IV" if a["worksheet"] == "1" else "V",
                     Decimal(a["net_income"]) - abs(Decimal(a["net_loss"])), abs(Decimal(a["prior_unallowed"])))
            for a in filed.get("activities", [])]


def rehearse(filed: dict, *, magi: Decimal | None = None, filing: str = "") -> tuple[Form, list[Check]]:
    """A filed return's Form 8582 worked out again from its Worksheets 1 and 3, against its Worksheet 5."""
    form = compute(filed["year"], from_filed(filed), magi=magi, filing=filing)
    theirs = {u["activity"]: abs(Decimal(u["unallowed"])) for u in filed.get("unallowed", [])}
    checks = []
    for a in form.activities:
        checks.append(Check(f"{filed['year']}: an activity's unallowed loss is Worksheet 5's",
                            abs(a.unallowed - theirs.pop(a.name, ZERO)) <= NEAR, 0, a.name))
    for name in theirs:
        checks.append(Check(f"{filed['year']}: a Worksheet 5 activity is on Worksheets 1 and 3", False, 0, name))
    return form, checks
