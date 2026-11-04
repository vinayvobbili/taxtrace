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
FILED_STANDS_IN = "the filed return: no W-2 has been read"
CARE_LIMIT = {2025: Decimal(5000), 2026: Decimal(7500)}  # dependent care benefits a joint return can exclude
CARE_KEYS = ("care_expenses", "spouse_earned")


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
    untested: list[str] = field(default_factory=list)  # lines of a filed return that nothing here could test
    details: list[str] = field(default_factory=list)  # the filed Schedules D and 1, part by part, in words
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


def _taxable_care(w2s: list[dict], filing: str, year: int, confirmed: dict, agi: Agi) -> tuple[Decimal, bool]:
    """Form 2441's Part III: the dependent care benefits in box 10 that are taxed, line 1e, and whether that's certain.

    What's excluded is the smallest of the benefits, the care expenses, each spouse's earned income and the year's
    limit, so a joint return with no earned income on the spouse's side excludes nothing. A second employee's W-2 gives
    the spouse's; otherwise `spouse_earned` does, for a job with no W-2 read yet.
    """
    benefits = sum((_box(f, "10") for f in w2s), ZERO)
    if not benefits:
        return ZERO, True
    earned: dict[str, Decimal] = {}
    for f in w2s:
        earned[f.get("employee", "")] = earned.get(f.get("employee", ""), ZERO) + _box(f, "1")
    amounts = sorted(earned.values(), reverse=True)
    limit = CARE_LIMIT.get(year, max(CARE_LIMIT.values())) / (2 if filing == "separate" else 1)
    caps = [benefits, amounts[0], limit]
    if filing in ("joint", "separate"):
        spouse = Decimal(confirmed["spouse_earned"]) if "spouse_earned" in confirmed else \
            (amounts[1] if len(amounts) > 1 else ZERO)
        caps.append(spouse)
    if "care_expenses" in confirmed:
        return benefits - min(*caps, Decimal(confirmed["care_expenses"])), True
    if min(caps) == 0:  # no earned income on one side: nothing is excluded, whatever the expenses
        if "spouse_earned" not in confirmed:
            agi.questions.append("box 10: with no earned income shown for your spouse, all the dependent care benefits "
                                 "are taxed; if your spouse worked, was a full-time student or disabled, "
                                 "`--confirm spouse_earned=AMOUNT`")
        return benefits, True
    agi.questions.append("box 10: how much you paid for care this year decides how much of it is taxed "
                         "(`--confirm care_expenses=AMOUNT`)")
    return benefits - min(caps), False


def _wages(year: int, forms: list[dict], filed: dict, filing: str, confirmed: dict, agi: Agi) -> Part:
    w2s = _year_forms(forms, year, "W-2")
    if w2s:
        wages = sum((_box(f, "1") for f in w2s), ZERO)
        care, certain = _taxable_care(w2s, filing, year, confirmed, agi)
        return Part("1z", "Wages", wages + care, READY if certain else ESTIMATE, [f.get("file", "") for f in w2s],
                    {"box 1": wages, "taxable dependent care": care} if care else {})
    if stub := estimates.latest_stub(forms, year):
        wages = paystub.from_json(stub).projected_wages()
        if wages is not None:
            return Part("1z", "Wages", wages, ESTIMATE, [stub.get("file", "")])
    if "1z" in filed:
        return Part("1z", "Wages", Decimal(filed["1z"]), READY, [FILED_STANDS_IN])
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
          passive: dict | None = None, moves: dict | None = None, year_over: bool = False,
          confirmed: dict | None = None) -> Agi:
    agi = Agi(year)
    filed = next(((r.get("f1040") or {}).get("lines", {}) for r in returns
                  if r.get("year") == year and r.get("f1040")), {})
    faces = qbi.faces(k1s, year)
    divs = _year_forms(forms, year, "1099-DIV")
    agi.parts = [
        _wages(year, forms, filed, filing, confirmed or {}, agi),
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
        _schedule_d_details(agi, filed_lines(returns, year, "schedule_d"), sales, faces, found)
        _sale_abroad_details(agi, filed_lines(returns, year, "form_4797"), found)
        _schedule_1_details(agi, filed_lines(returns, year, "schedule_1"))
        _schedule_e_details(agi, filed_lines(returns, year, "schedule_e"), faces)
    return agi


def filed_lines(returns: list[dict], year: int, form: str) -> dict[str, Decimal]:
    """A filed form's lines for the year, from whichever of the year's returns holds it; a signing packet may not."""
    lines = next(((r.get(form) or {}).get("lines", {}) for r in returns if r.get("year") == year and r.get(form)), {})
    return {k: Decimal(v) for k, v in lines.items()}


def difference(what: str, mine: Decimal | None, theirs: Decimal) -> Check:
    """How a built amount compares with a filed one: which way and roughly how far, never an amount."""
    if mine is None:
        return Check(f"{what}: not built yet", False, 0)
    gap = abs(mine - theirs)
    if gap <= TOLERANCE:
        return Check(f"{what} is the filed return's", True, 0)
    size = "by under $100" if gap < 100 else "by under $1,000" if gap < 1000 else "by $1,000 or more"
    return Check(f"{what} is {'higher' if mine > theirs else 'lower'} than the filed return's, {size}", False, 0)


def _compare(agi: Agi, what: str, mine: Decimal | None, theirs: Decimal) -> None:
    agi.checks.append(difference(what, mine, theirs))


def _detail(agi: Agi, what: str, mine: Decimal, theirs: Decimal) -> None:
    """One part of a line against the filed schedule's. Nothing on either side says nothing."""
    if mine or theirs:
        agi.details.append(difference(what, mine, theirs).what)


def _schedule_d_details(agi: Agi, d: dict[str, Decimal], sales: dict | None, faces: list[dict],
                        found: dict | None) -> None:
    """Line 7's parts against Schedule D's, to show which part a difference comes from."""
    if not d:
        return

    def filed(*lines: str) -> Decimal:
        return sum((d.get(n, ZERO) for n in lines), ZERO)

    sold = sales or {}
    _detail(agi, "Schedule D, short-term sales (lines 1a to 3)", _dollars(sold.get("short")),
            filed("1a", "1b", "2", "3"))
    _detail(agi, "Schedule D, long-term sales (lines 8a to 10)", _dollars(sold.get("long")),
            filed("8a", "8b", "9", "10"))
    _detail(agi, "Schedule D, the K-1s' gains (lines 5 and 12)",
            sum((_k1_box(f, "8") + _k1_box(f, "9a") for f in faces), ZERO), filed("5", "12"))
    _detail(agi, "Schedule D, capital gain distributions (line 13)", _dollars(sold.get("distributions")), filed("13"))
    _detail(agi, "Schedule D, loss carryovers (lines 6 and 14)",
            -_dollars(sold.get("carry_short")) - _dollars(sold.get("carry_long")), filed("6", "14"))
    abroad = sum((_dollars(s.get("gain")) for s in (found or {}).get("sales", [])), ZERO)
    _detail(agi, "Schedule D, the sale abroad against Form 4797's gains (lines 4 and 11)", abroad, filed("4", "11"))


def _sale_abroad_details(agi: Agi, form: dict[str, Decimal], found: dict | None) -> None:
    """The sale abroad against Form 4797's Part III, where a depreciable property's sale is reported."""
    sales = (found or {}).get("sales", [])
    if not form or not sales:
        return
    price = sum((_dollars((s.get("proceeds") or {}).get("dollars")) for s in sales), ZERO)
    _detail(agi, "Form 4797, the sale abroad's price (line 20)", price, form.get("20", ZERO))
    _detail(agi, "Form 4797, the sale abroad's cost and selling expenses (line 21)",
            sum((_dollars(s.get("basis")) for s in sales), ZERO), form.get("21", ZERO))
    _detail(agi, "Form 4797, depreciation (line 22)", ZERO, form.get("22", ZERO))
    _detail(agi, "Form 4797, the sale abroad's gain (line 24)", sum((_dollars(s.get("gain")) for s in sales), ZERO),
            form.get("24", ZERO))


def _schedule_e_details(agi: Agi, form: dict[str, Decimal], faces: list[dict]) -> None:
    """Line 8's own parts against Schedule E's: the rental (line 26) and the K-1s (line 32). An activity on Form 8582
    counts as a K-1's when its first word is a K-1 partnership's: everything else there is the rental."""
    if not form:
        return
    first = {_k1_name(f).split()[0].casefold() for f in faces if _k1_name(f).split()}
    pieces = agi.line("8").pieces
    theirs = sum((v for k, v in pieces.items() if k == "the K-1s' royalties"
                  or (k.split() and k.split()[0].casefold() in first)), ZERO)
    _detail(agi, "Schedule E, the K-1s (line 32)", theirs, form.get("32", ZERO))
    _detail(agi, "Schedule E, the rental (line 26)", (agi.line("8").amount or ZERO) - theirs, form.get("26", ZERO))
    _explain(agi, "Schedule E line 32", {k: v for k, v in pieces.items() if k == "the K-1s' royalties"
                                         or (k.split() and k.split()[0].casefold() in first)}, form.get("32", ZERO))


def _schedule_1_details(agi: Agi, one: dict[str, Decimal]) -> None:
    """Line 8's parts against Schedule 1's."""
    if not one:
        return
    _detail(agi, "Schedule 1, the rental and the K-1s (line 5)", agi.line("8").amount or ZERO, one.get("5", ZERO))
    for line, what in (("1", "state refunds"), ("4", "Form 4797's other gains"), ("9", "other income")):
        _detail(agi, f"Schedule 1, {what} (line {line})", ZERO, one.get(line, ZERO))


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
        part = agi.line(line)
        if FILED_STANDS_IN in part.sources:  # the filed line itself: a match would prove nothing
            agi.untested.append(f"line {line}: no W-2 has been read, so the filed line stands in")
        elif part.amount == 0 and theirs == 0:  # nothing on either side
            agi.untested.append(f"line {line}: nothing on either side")
        else:
            _compare(agi, f"line {line}", part.amount, theirs)
    seven_mine, eight_mine = agi.line("7").amount, agi.line("8").amount
    both = None if seven_mine is None or eight_mine is None else seven_mine + eight_mine
    _compare(agi, "lines 7 and 8 together", both, seven + amount.get("8", ZERO))
    eleven = next((amount[k] for k in ("11", "11b", "11a") if k in amount), None)
    if eleven is not None:
        _compare(agi, "line 11", agi.total, eleven)
