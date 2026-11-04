"""A year's federal adjusted gross income, Form 1040's income lines from what the other commands saved.

It's what North Carolina's D-400 starts from, and what's asked to sign an e-file next year. Each line is the sum of
what's read so far:

- 1z, wages: the W-2s' box 1, or the latest pay stub projected to December 31. When a year's return is filed and no
  W-2 was read, the filed line stands in, so the other lines can still be compared.
- 2b, taxable interest: the 1099-INTs' boxes 1 and 3, the foreign side's interest and the K-1s' box 5.
- 3b, ordinary dividends: the 1099-DIVs' box 1a and the K-1s' box 6a.
- 7, capital gain: the net of `sales`, sales abroad and the K-1s' boxes 8 and 9a, a net loss held to the year's limit.
- 8, Schedule 1 income: what Form 8582 allowed of the rental and the K-1s (`passive`), and the K-1s' royalties (box 7).
  Before Form 8582 is worked out, it's the rental's net and the K-1s' passive income, with no limit taken.
- 10, adjustments: the IRA contributions `moves` has as done.

A K-1's section 1231 gain (box 10) is in line 8 here, where a preparer may put it on line 7: the two lines can differ by
it, and their sum and line 11 can't. When the year's own return has been filed and read (`prior`), every line is
compared with it: how close the build comes to what the preparer filed.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal
from itertools import combinations

from . import estimates, paystub, qbi
from . import sales as sales_rules
from .passive import passive_amount
from .prior import Check

READY, ESTIMATE, MISSING = "ready", "estimate", "missing"
ZERO = Decimal(0)
SORT = {READY: 0, ESTIMATE: 1, MISSING: 2}
TOLERANCE = Decimal(1)  # a dollar: a return's lines are rounded
EXPLAINS = Decimal(5)  # a few rounded pieces can add up to a few dollars


@dataclass
class Part:
    line: str  # Form 1040's: "2b"
    what: str
    amount: Decimal | None
    status: str
    sources: list[str] = field(default_factory=list)
    pieces: dict[str, Decimal] = field(default_factory=dict)  # what it adds up, by name, for explaining a difference


@dataclass
class Agi:
    year: int
    parts: list[Part] = field(default_factory=list)
    checks: list[Check] = field(default_factory=list)
    explained: list[str] = field(default_factory=list)  # which pieces' absence would make a differing line match
    questions: list[str] = field(default_factory=list)

    def line(self, line: str) -> Part:
        return next(p for p in self.parts if p.line == line)

    @property
    def total(self) -> Decimal | None:
        """Line 11, once every line has an amount."""
        if any(p.amount is None for p in self.parts):
            return None
        return sum((p.amount for p in self.parts if p.line != "10"), ZERO) - self.line("10").amount

    @property
    def status(self) -> str:
        return max((p.status for p in self.parts), key=SORT.__getitem__, default=MISSING)

    def to_json(self) -> dict:
        out = asdict(self)
        out["total"] = None if self.total is None else str(self.total)
        out["status"] = self.status
        return out


def _dollars(value: object) -> Decimal:
    return ZERO if value is None else Decimal(str(value))


def _box(form: dict, box: str) -> Decimal:
    return _dollars((form.get("amounts", {}).get(box) or {}).get("amount"))


def _k1_box(face: dict, box: str) -> Decimal:
    return sum((_dollars(i["value"].get("amount")) for i in face.get("items", []) if i["box"] == box), ZERO)


def _k1_name(face: dict) -> str:
    return face.get("partnership") or face.get("file", "")


def _year_forms(forms: list[dict], year: int, kind: str) -> list[dict]:
    return [f for f in forms if f.get("form") == kind and f.get("year") == year and f.get("copy_of") is None]


def _wages(year: int, forms: list[dict], filed: dict) -> Part:
    w2s = _year_forms(forms, year, "W-2")
    if w2s:
        return Part("1z", "Wages", sum((_box(f, "1") for f in w2s), ZERO), READY, [f.get("file", "") for f in w2s])
    if stub := estimates.latest_stub(forms, year):
        wages = paystub.from_json(stub).projected_wages()
        if wages is not None:
            return Part("1z", "Wages", wages, ESTIMATE, [stub.get("file", "")])
    if "1z" in filed:
        return Part("1z", "Wages", Decimal(filed["1z"]), READY, ["the filed return: no W-2 has been read"])
    return Part("1z", "Wages", None, MISSING, ["`taxtrace paystub`, until the W-2 comes"])


def _interest(year: int, forms: list[dict], faces: list[dict], found: dict | None) -> Part:
    ints = _year_forms(forms, year, "1099-INT")
    total = sum((_box(f, "1") + _box(f, "3") for f in ints), ZERO) + sum((_k1_box(f, "5") for f in faces), ZERO)
    status, sources = READY, [f.get("file", "") for f in ints]
    pieces = {f"the 1099-INT of {f.get('file', '')} p{f.get('page', '')}": _box(f, "1") + _box(f, "3") for f in ints}
    pieces |= {f"K-1 box 5 of {_k1_name(f)}": _k1_box(f, "5") for f in faces}
    if found is None:
        status = MISSING
        sources.append("`taxtrace foreign`")
    else:
        total += _dollars(found.get("interest"))
        if found.get("estimated") or any(a.get("missing") for a in found.get("accounts", [])):
            status = ESTIMATE
        sources.append("the foreign side")
        pieces["the foreign side's interest"] = _dollars(found.get("interest"))
    return Part("2b", "Taxable interest", total if status != MISSING else None, status, sources, pieces)


def _capital(year: int, sales: dict | None, found: dict | None, faces: list[dict], filing: str) -> Part:
    abroad = sum((_dollars(s.get("gain")) for s in (found or {}).get("sales", [])), ZERO)
    from_k1s = sum((_k1_box(f, "8") + _k1_box(f, "9a") for f in faces), ZERO)
    if sales is None:
        return Part("7", "Capital gain or loss", None, MISSING, ["`taxtrace sales`"])
    net = _dollars(sales.get("net")) + abroad + from_k1s
    limit = sales_rules.LOSS_LIMIT.get(filing, sales_rules.LIMIT)
    pieces = {"the stock sales": _dollars(sales.get("net")), "the sale abroad": abroad}
    pieces |= {f"K-1 boxes 8 and 9a of {_k1_name(f)}": _k1_box(f, "8") + _k1_box(f, "9a") for f in faces}
    return Part("7", "Capital gain or loss", max(net, -limit), READY if sales.get("from_forms") else ESTIMATE,
                ["`taxtrace sales`"] + (["the foreign side"] if abroad else []), pieces)


def _schedule_1(rental: dict | None, passive: dict | None, faces: list[dict], agi: Agi, year_over: bool) -> Part:
    royalties = sum((_k1_box(f, "7") for f in faces), ZERO)
    for f in faces:
        if _k1_box(f, "11") or _k1_box(f, "4c"):
            agi.questions.append(f"{f.get('partnership') or f.get('file', '')}: its K-1 has guaranteed payments or "
                                 "other income (box 4c or 11), which isn't counted yet")
    form = (passive or {}).get("form_8582")
    if form:
        allowed = {a.get("name", ""): _dollars(a.get("allowed")) for a in form.get("activities", [])}
        return Part("8", "Schedule 1 income", sum(allowed.values(), ZERO) + royalties,
                    READY if year_over else ESTIMATE, ["Form 8582, as `taxtrace passive` worked it out"],
                    {**allowed, "the K-1s' royalties": royalties})
    if rental is None and not faces:
        return Part("8", "Schedule 1 income", None, MISSING, ["`taxtrace rental`, `taxtrace passive`"])
    total = _dollars((rental or {}).get("income_or_loss")) + royalties
    total += sum((passive_amount(f.get("items", []))[0] for f in faces), ZERO)
    agi.questions.append("Form 8582 isn't worked out yet (`taxtrace passive`), so a passive loss it wouldn't allow is "
                         "counted here")
    return Part("8", "Schedule 1 income", total, ESTIMATE, ["the rental and the K-1s, before Form 8582"])


def build(year: int, *, forms: list[dict], k1s: list[dict], returns: list[dict], filing: str = "",
          rental: dict | None = None, found: dict | None = None, sales: dict | None = None,
          passive: dict | None = None, moves: dict | None = None, year_over: bool = False) -> Agi:
    agi = Agi(year)
    filed = next(((r.get("f1040") or {}).get("lines", {}) for r in returns
                  if r.get("year") == year and r.get("f1040")), {})
    faces = qbi.faces(k1s, year)
    divs = _year_forms(forms, year, "1099-DIV")
    agi.parts = [
        _wages(year, forms, filed),
        _interest(year, forms, faces, found),
        Part("3b", "Ordinary dividends", sum((_box(f, "1a") for f in divs), ZERO)
             + sum((_k1_box(f, "6a") for f in faces), ZERO), READY, [f.get("file", "") for f in divs]),
        _capital(year, sales, found, faces, filing),
        _schedule_1(rental, passive, faces, agi, year_over),
    ]
    done = [m for m in (moves or {}).get("moves", []) if m.get("key") in ("spouse_ira", "own_ira") and m.get("done")]
    agi.parts.append(Part("10", "Adjustments to income", sum((_dollars(m.get("amount")) for m in done), ZERO), READY,
                          ["`taxtrace moves`"] if done else []))
    if filed:
        _rehearse(agi, filed)
    return agi


def _compare(agi: Agi, what: str, mine: Decimal | None, theirs: Decimal) -> None:
    if mine is None:
        agi.checks.append(Check(f"{what}: not built yet", False, 0))
        return
    gap = abs(mine - theirs)
    if gap <= TOLERANCE:
        agi.checks.append(Check(f"{what} is the filed return's", True, 0))
        return
    size = "by under $100" if gap < 100 else "by under $1,000" if gap < 1000 else "by $1,000 or more"
    agi.checks.append(Check(f"{what} is {'higher' if mine > theirs else 'lower'} than the filed return's, {size}",
                            False, 0))


def _explain(agi: Agi, what: str, pieces: dict[str, Decimal], theirs: Decimal) -> None:
    """Which one or two pieces, left out, bring `what` to the filed amount: how far the build's reading of a line and
    the preparer's differ, in names and never amounts."""
    mine = sum(pieces.values(), ZERO)
    if abs(mine - theirs) <= TOLERANCE:
        return
    named = [(k, v) for k, v in pieces.items() if v]
    for size in (1, 2):
        fits = [left for left in combinations(named, size)
                if abs(mine - sum((v for _, v in left), ZERO) - theirs) <= EXPLAINS]
        if fits:
            for left in fits:
                agi.explained.append(f"{what}: leaving out {' and '.join(k for k, _ in left)} would match")
            return
    agi.explained.append(f"{what}: leaving out no one or two of its parts would match")


def _rehearse(agi: Agi, filed: dict) -> None:
    """Each line against the year's filed Form 1040: which way and roughly how far, never an amount."""
    amount = {k: Decimal(v) for k, v in filed.items()}
    seven = amount.get("7", amount.get("7a", ZERO))
    _explain(agi, "line 2b", agi.line("2b").pieces, amount.get("2b", ZERO))
    _explain(agi, "lines 7 and 8 together", {**agi.line("7").pieces, **agi.line("8").pieces},
             seven + amount.get("8", ZERO))
    for line, theirs in (("1z", amount.get("1z", ZERO)), ("2b", amount.get("2b", ZERO)),
                         ("3b", amount.get("3b", ZERO)), ("7", seven), ("8", amount.get("8", ZERO)),
                         ("10", amount.get("10", ZERO))):
        _compare(agi, f"line {line}", agi.line(line).amount, theirs)
    seven_mine, eight_mine = agi.line("7").amount, agi.line("8").amount
    both = None if seven_mine is None or eight_mine is None else seven_mine + eight_mine
    _compare(agi, "lines 7 and 8 together", both, seven + amount.get("8", ZERO))
    eleven = next((amount[k] for k in ("11", "11b", "11a") if k in amount), None)
    if eleven is not None:
        _compare(agi, "line 11", agi.total, eleven)
