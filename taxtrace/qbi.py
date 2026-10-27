"""Form 8995 for a year: the qualified business income deduction, from the K-1s, the rental and last year's return.

Each partnership's qualified business income is its K-1's passive income or loss, as `passive` adds it from the
boxes (1, 2, 3 and 10, less 12): what the preparer's Form 8995 had, rather than the K-1's Section 199A statement
total. The rental's is Schedule E's income or loss (`rental`). A passive loss Form 8582 doesn't allow isn't qualified
business income until a later year allows it: with the year's Form 8582 filed and read, each activity's amount is
what it let through; without it, the amounts are before that limit, and that's a question. Which businesses count
follows last year's filed Form 8995 (`prior`): a partnership it listed (by the EIN's last four digits) that has
income or a loss, and the rental if it listed a Schedule E. One it didn't list is a question, settled with `qbi
--confirm`. Last year's losses carried on (its lines 16 and 17) come in on lines 3 and 7.

Lines 11 to 15 need the year's taxable income, which isn't put together yet, so the deduction is known only when
line 10 is zero. The simplified form is for taxable income before the deduction at or under the year's threshold
(THRESHOLDS); above it Form 8995-A applies, with its wage and property limits, which taxtrace doesn't do yet.

When the year's own return has been filed and read, every line is compared with it: the rehearsal that shows the
build matches what the preparer filed.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .k1 import qbi_kind
from .passive import MATCH, RENTAL, passive_amount, similar
from .prior import CENT, Check, Question

# taxable income before the deduction, at or under which the simplified Form 8995 applies: (married filing jointly,
# everyone else). 2025: Rev. Proc. 2024-40; 2026: Rev. Proc. 2025-32 (married filing separately $201,775)
THRESHOLDS = {2025: (Decimal(394600), Decimal(197300)), 2026: (Decimal(403500), Decimal(201750))}
CHOICES = ("business", "not")
TWENTY = Decimal("0.20")
PASSIVE_INCOME = "its passive income or loss (boxes 1, 2, 3 and 10, less 12)"


@dataclass
class Business:
    name: str  # the partnership's, or "Schedule E: <address>"
    tin: str  # the EIN as its K-1 prints it; "" for the rental
    income: Decimal  # qualified business income or (loss)
    source: str  # "k1" or "schedule e"
    file: str
    # other figures its amount could have been, by what each is: when a filed form disagrees, the one it matches
    others: dict[str, Decimal] = field(default_factory=dict)


@dataclass
class Form:
    year: int
    businesses: list[Business] = field(default_factory=list)
    lines: dict[int, Decimal] = field(default_factory=dict)  # 2 to 10, 16, 17; 15 when it's known
    threshold: Decimal | None = None  # for the filing status, when it's known
    checks: list[Check] = field(default_factory=list)  # against the year's filed form, when there is one
    questions: list[Question] = field(default_factory=list)

    def ask(self, text: str) -> None:
        self.questions.append(Question(text, 0, ""))

    def to_json(self) -> dict:
        return asdict(self)


def confirmation(spec: str) -> tuple[str, str]:
    """'rental=business', or 'k1_1234=not' for the partnership whose EIN ends 1234."""
    key, sep, value = (s.strip().lower() for s in spec.partition("="))
    if not sep or not (key == "rental" or re.fullmatch(r"k1_\d{4}", key)) or value not in CHOICES:
        raise ValueError("--confirm takes rental=business|not, or k1_<the EIN's last four digits>=business|not")
    return key, value


def last_four(tin: str) -> str:
    digits = re.sub(r"\D", "", tin)
    return digits[-4:] if len(digits) >= 4 else ""


def faces(k1s: list[dict], year: int) -> list[dict]:
    """The year's federal K-1 faces, each once, without an IRA's (its items stay in the account)."""
    return [f for f in k1s if "form" not in f and f.get("year") == year and f.get("copy_of") is None
            and not f.get("retirement_plan")]


def allowed(filed: dict) -> dict[str, Decimal]:
    """Each passive activity's income or loss that a filed return's Form 8582 let through, by the worksheet's name for
    it: its overall gain or loss (Worksheets 1 and 3, columns (d) and (e)) less the loss Worksheet 5 carried on."""
    carried = {u["activity"]: abs(Decimal(u["unallowed"])) for u in filed.get("unallowed", [])}
    return {a["activity"]: Decimal(a["gain"]) - abs(Decimal(a["loss"])) + carried.get(a["activity"], Decimal(0))
            for a in filed.get("activities", [])}


def _limited(name: str, limits: dict[str, Decimal], rental: bool = False) -> Decimal | None:
    """The activity's amount after Form 8582, matched by name the way `passive` matches K-1s (the rental by its
    worksheet name's "rental"), or None when no activity matches."""
    if rental:
        found = [v for k, v in limits.items() if RENTAL.search(k)]
        return found[0] if len(found) == 1 else None
    scores = sorted(((similar(name, k), k) for k in limits), reverse=True)
    if scores and scores[0][0] >= MATCH and (len(scores) == 1 or scores[1][0] < scores[0][0]):
        return limits[scores[0][1]]
    return None


def _k1_figures(face: dict) -> dict[str, Decimal]:
    """What a K-1's qualified business income could be, by what each figure is: its Section 199A statement's total
    (without an aggregated group's, whose members are counted) when it has one, the group's, the statement's other
    rows (a statement that lists income parts instead of a total), and its passive income with and without section
    1231 gain."""
    zero = Decimal(0)
    rows = face.get("statement", [])
    out: dict[str, Decimal] = {}
    for label, picked in (("its Section 199A statement's qualified business income",
                           [s for s in rows if not s.get("aggregate") and qbi_kind(s["description"]) == "qbi"]),
                          ("its aggregated group's qualified business income",
                           [s for s in rows if s.get("aggregate") and qbi_kind(s["description"]) == "qbi"]),
                          ("its Section 199A statement's income and deduction rows",
                           [s for s in rows if not s.get("aggregate") and qbi_kind(s["description"]) == ""])):
        if picked:
            out[label] = sum((Decimal(s["amount"]) for s in picked), zero)
    items = face.get("items", [])
    out[PASSIVE_INCOME] = passive_amount(items)[0]
    out[PASSIVE_INCOME + " without section 1231 gain"] = passive_amount([i for i in items if i["box"] != "10"])[0]
    return out


def _net(rental: dict) -> Decimal | None:
    """A filed Schedule E property's rents and royalties less its total expenses (lines 3 and 4 less 20)."""
    lines = rental.get("lines", {})
    if "3" not in lines:
        return None
    total = sum((Decimal(v["amount"]) for k, v in lines.items() if int(k) in range(5, 20)), Decimal(0))
    return sum((Decimal(lines[k]["amount"]) for k in ("3", "4") if k in lines), Decimal(0)) - total


def _twenty(value: Decimal) -> Decimal:
    return (value * TWENTY).quantize(CENT, ROUND_HALF_UP)


def build(year: int, *, k1s: list[dict], rental: dict | None, returns: list[dict], confirmed: dict | None = None,
          filing: str = "") -> Form:
    """The year's Form 8995 from the saved K-1s (`k1`), its Schedule E (`rental`) and the filed returns (`prior`)."""
    confirmed = confirmed or {}
    form = Form(year)
    if year in THRESHOLDS and filing:
        joint, other = THRESHOLDS[year]
        form.threshold = joint if filing == "joint" else other
    last = next((r["qbi"] for r in returns if r.get("year") == year - 1 and r.get("qbi")), None)
    if last is None:
        form.ask(f"the {year - 1} return's Form 8995 isn't read (`taxtrace prior`): its losses carried on (lines 16 "
                 f"and 17) are {year}'s lines 3 and 7, and the businesses it listed say which count this year")
    listed = {last_four(b["tin"]) for b in (last or {}).get("businesses", [])
              if not b["name"].startswith("Schedule E")}
    rental_listed = any(b["name"].startswith("Schedule E") for b in (last or {}).get("businesses", []))
    filed_8582 = next((r for r in returns if r.get("year") == year and r.get("activities")), None)
    limits = allowed(filed_8582) if filed_8582 else {}
    if filed_8582 is None:
        form.ask(f"{year}'s Form 8582 isn't worked out yet: a passive loss it doesn't allow isn't qualified business "
                 "income until a later year allows it, and an earlier loss it frees is, so each business's amount here "
                 "is before that limit")
    reit = Decimal(0)
    for f in faces(k1s, year):
        rows = [s for s in f.get("statement", []) if not s.get("aggregate")]
        name = f.get("partnership", "") or f["file"]
        others = _k1_figures(f)
        income = others.pop(PASSIVE_INCOME)
        if limits:
            if (limited := _limited(name, limits)) is None:
                form.ask(f"{name}: no activity on {year}'s Form 8582 matches it, so its amount is before the passive "
                         "loss limit")
            else:
                income = limited
        four = last_four(f.get("ein", ""))
        choice = confirmed.get(f"k1_{four}", "business" if four in listed and income else "")
        if choice == "business":
            form.businesses.append(Business(name, f.get("ein", ""), income, "k1", f["file"], others))
            reit += sum((Decimal(s["amount"]) for s in rows if qbi_kind(s["description"]) in ("reit", "ptp")),
                        Decimal(0))
        elif choice == "" and income and four not in listed:
            form.ask(f"{name} (EIN ending {four or '?'}): it has qualified business income or loss, and last year's "
                     f"Form 8995 didn't list it: `taxtrace qbi --confirm k1_{four or '<last four>'}=business|not`")
    choice = confirmed.get("rental", "business" if rental_listed else "")
    if rental is None:
        if choice == "business":
            form.ask(f"the rental counts on Form 8995, and its {year} Schedule E isn't put together yet (`taxtrace "
                     "rental`)")
    elif choice == "business":
        income = Decimal(rental["income_or_loss"])
        if limits:
            if (limited := _limited("", limits, rental=True)) is None:
                form.ask(f"the rental: no one activity on {year}'s Form 8582 is it, so its amount is before the "
                         "passive loss limit")
            else:
                income = limited
        others = {f"the filed {year} Schedule E's net": net
                  for r in returns if r.get("year") == year
                  for net in [_net(p) for p in r.get("rentals", [])] if net is not None}
        form.businesses.append(Business(f"Schedule E: {rental.get('address', '')}", "", income, "schedule e",
                                        f"schedule-e/{year}.json", others))
    elif choice == "":
        form.ask("the rental: is it a qualified business on Form 8995 (a trade or business, or the 250-hour safe "
                 "harbor)? `taxtrace qbi --confirm rental=business|not`")
    _lines(form, last, reit)
    filed = next((r["qbi"] for r in returns if r.get("year") == year and r.get("qbi")), None)
    if filed:
        _rehearse(form, filed)
    return form


def _lines(form: Form, last: dict | None, reit: Decimal) -> None:
    carried = {int(k): Decimal(v) for k, v in (last or {}).get("lines", {}).items()}
    zero = Decimal(0)
    n = form.lines
    n[2] = sum((b.income for b in form.businesses), zero)
    n[3] = carried.get(16, zero)
    n[4] = max(zero, n[2] + n[3])
    n[5] = _twenty(n[4])
    n[6] = reit  # the K-1s' REIT dividends and PTP income; 1099-DIV box 5 isn't read yet
    n[7] = carried.get(17, zero)
    n[8] = max(zero, n[6] + n[7])
    n[9] = _twenty(n[8])
    n[10] = n[5] + n[9]
    n[16] = min(zero, n[2] + n[3])
    n[17] = min(zero, n[6] + n[7])
    if n[10] == 0:
        n[15] = zero  # the smaller of line 10 and the income limit
    else:
        form.ask(f"lines 11 to 15: the deduction is the smaller of line 10 and 20% of taxable income less net capital "
                 f"gain, which needs {form.year}'s taxable income")
    if carried.get(6):
        form.ask("last year's Form 8995 had qualified REIT dividends or PTP income (line 6): 1099-DIV box 5 isn't "
                 "read yet")


def _rehearse(form: Form, filed: dict) -> None:
    """Each line against the year's filed Form 8995, and each business by its EIN's last four digits."""
    lines = {int(k): Decimal(v) for k, v in filed.get("lines", {}).items()}
    for n in (2, 3, 4, 5, 10, 15, 16, 17):
        if n in form.lines:
            form.checks.append(Check(f"line {n} is the filed Form 8995's", abs(form.lines[n] - lines.get(n, 0)) <= CENT,
                                     0))
    built = {("rental" if b.source == "schedule e" else last_four(b.tin)): b for b in form.businesses}
    for b in filed.get("businesses", []):
        key = "rental" if b["name"].startswith("Schedule E") else last_four(b["tin"])
        mine = built.pop(key, None)
        what = "the rental" if key == "rental" else f"the business with EIN ending {key}"
        if mine is None:
            form.checks.append(Check(f"{what}, on the filed Form 8995, is built too", False, 0))
        else:
            theirs = Decimal(b["income"])
            ok = abs(mine.income - theirs) <= CENT
            same = [k for k, v in mine.others.items() if abs(v - theirs) <= CENT]
            form.checks.append(Check(f"{what}: its income is the filed Form 8995's"
                                     + ("" if ok or not same else f" (the filed one is {' and '.join(same)})"), ok, 0))
    for key in built:
        form.checks.append(Check(f"the business with EIN ending {key} isn't on the filed Form 8995", False, 0))
