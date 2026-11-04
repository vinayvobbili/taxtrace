"""Form 1040's lines 12e to 24, from adjusted gross income to the total tax, with Form 1116's credit.

Line 12e is the larger of the standard deduction and Schedule A (mortgage interest on the home, state and local taxes up
to the year's cap, charity, medical past 7.5%). Line 13a is the smaller of Form 8995's line 10 and 20% of taxable income
less net capital gain, which is why the simplified form's threshold matters: above it, Form 8995-A applies, and `qbi`
asks. Line 16 follows the Qualified Dividends and Capital Gain Tax Worksheet, using the Tax Table's $50 bands under
$100,000 as the form says. Line 19 is the child tax credit, and line 20 is Form 1116's credit: the smaller of the
foreign taxes available and line 16 times foreign taxable income over line 11 less line 14. Line 23 adds the additional
Medicare tax and the net investment income tax. The alternative minimum tax isn't worked out, and the output says so.

Form 1116 takes income taxed at lower rates out of both sides of its fraction: a foreign gain on line 1a (times 0.4054
at 15%, 0.5405 at 20%, nothing at 0%) and the world's on line 18 (the Worksheet for Line 18). That's required at a
foreign gain of $20,000 or more, or when the income taxed at ordinary rates passes the 24% bracket, and an election
below that: the way with the larger limit is the one taken.

Figures: Rev. Proc. 2024-40 and 2025-32, with the 2025 standard deduction as the One Big Beautiful Bill Act set it.
Only joint and single returns have brackets here; other filing statuses are a question.

A filed year is compared line by line, and each rule is also tested from the filed form's own inputs, so a wrong rule
shows up apart from an income line that differs.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal
from itertools import pairwise

from . import d400, paystub
from .agi import ESTIMATE, MISSING, READY, Agi, difference
from .prior import Check

ZERO = Decimal(0)
BRACKETS = {
    **paystub.BRACKETS,
    (2025, "joint"): (Decimal(31500), ((0, "0.10"), (23850, "0.12"), (96950, "0.22"), (206700, "0.24"),
                                       (394600, "0.32"), (501050, "0.35"), (751600, "0.37"))),
    (2025, "single"): (Decimal(15750), ((0, "0.10"), (11925, "0.12"), (48475, "0.22"), (103350, "0.24"),
                                        (197300, "0.32"), (250525, "0.35"), (626350, "0.37"))),
}
CAPITAL_GAIN_BANDS = {  # the most taxable income taxed at 0% and at 15%
    (2025, "joint"): (Decimal(96700), Decimal(600050)), (2025, "single"): (Decimal(48350), Decimal(533400)),
    (2026, "joint"): (Decimal(98900), Decimal(613700)), (2026, "single"): (Decimal(49450), Decimal(545500)),
}
SALT_CAP = {2025: Decimal(40000), 2026: Decimal(40400)}
CHILD_CREDIT = Decimal(2200)
CHILD_PHASE_OUT = {"joint": Decimal(400000)}  # $200,000 for everyone else
CHILD_PHASE_OUT_OTHER = Decimal(200000)
MEDICARE_OVER = {"joint": Decimal(250000)}  # and the net investment income tax's threshold; $200,000 for single
OVER_OTHER = Decimal(200000)
MEDICARE_RATE, INVESTMENT_RATE = Decimal("0.009"), Decimal("0.038")
INVESTMENT = ("2b", "3b", "7", "8")  # Form 1040's lines of investment income, for the net investment income tax
MEDICAL_FLOOR = Decimal("0.075")
TABLE_UNDER, TABLE_BAND = Decimal(100000), Decimal(50)
RATE_15, RATE_20 = Decimal("0.15"), Decimal("0.20")
QBI_RATE = Decimal("0.20")
GAIN_AT_15, GAIN_AT_20 = Decimal("0.4054"), Decimal("0.5405")  # a foreign gain's share on Form 1116's line 1a
WORLD_AT_25, WORLD_AT_20, WORLD_AT_15 = Decimal("0.3243"), Decimal("0.4595"), Decimal("0.5946")  # taken off line 18
ADJUST_FROM = Decimal(20000)  # a foreign gain from here up has to be adjusted
AMT_NOTE = "the alternative minimum tax isn't worked out: check Form 6251 on the filing site"


@dataclass
class Form:
    year: int
    filing: str = ""
    lines: list[d400.Line] = field(default_factory=list)
    form_1116: dict[str, Decimal] = field(default_factory=dict)
    deduction: str = ""  # "standard" or "itemized"
    room: Decimal = ZERO  # how far Schedule A is over the standard deduction, or under it when negative
    questions: list[str] = field(default_factory=list)

    def amount(self, line: str) -> Decimal | None:
        return next((n.amount for n in self.lines if n.line == line), None)

    def to_json(self) -> dict:
        return asdict(self)


def schedule_a_words(room: Decimal) -> str:
    """Schedule A against the standard deduction, in words: nothing finer than which way and roughly how far."""
    way, gap = ("over", room) if room > 0 else ("under", -room)
    sizes = ((1000, "under $1,000"), (5000, "$1,000 to $5,000"), (10000, "$5,000 to $10,000"))
    size = next((words for top, words in sizes if gap < top), "$10,000 or more")
    return f"Schedule A so far is {way} the standard deduction by {size}"


def whole(value: Decimal) -> Decimal:
    return value.quantize(Decimal(1), ROUND_HALF_UP)


def on_brackets(amount: Decimal, year: int, filing: str) -> Decimal | None:
    """The tax on an amount: the Tax Table's $50 band's middle under $100,000, the computation worksheet above it."""
    table = BRACKETS.get((year, filing))
    if table is None:
        return None
    if amount <= 0:
        return ZERO
    # the table's bands start at $3,000; below that they're narrower, a few dollars' difference at most
    taxed = (amount // TABLE_BAND) * TABLE_BAND + TABLE_BAND / 2 if amount < TABLE_UNDER else amount
    tax = ZERO
    for (low, rate), (high, _) in pairwise((*table[1], (None, None))):
        if taxed <= low:
            break
        tax += ((min(taxed, Decimal(high)) if high is not None else taxed) - low) * Decimal(rate)
    return whole(tax)


def rate_bands(taxable: Decimal, preferred: Decimal, year: int,
               filing: str) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """The Qualified Dividends and Capital Gain Tax Worksheet's split: the income at ordinary rates (its line 5), then
    what's at 0%, 15% and 20% (its lines 9, 17 and 20)."""
    zero_top, fifteen_top = CAPITAL_GAIN_BANDS[(year, filing)]
    taxable = max(ZERO, taxable)
    preferred = max(ZERO, min(preferred, taxable))
    ordinary = taxable - preferred
    at_zero = min(taxable, zero_top) - min(ordinary, min(taxable, zero_top))
    at_fifteen = min(preferred - at_zero, max(ZERO, min(taxable, fifteen_top) - ordinary - at_zero))
    return ordinary, at_zero, at_fifteen, preferred - at_zero - at_fifteen


def with_capital_gains(taxable: Decimal, preferred: Decimal, year: int, filing: str) -> Decimal | None:
    """Line 16 by the worksheet: `preferred` is the qualified dividends and the net capital gain, taxed at 0%, 15% and
    20% on top of the rest of the income."""
    if (year, filing) not in CAPITAL_GAIN_BANDS or (year, filing) not in BRACKETS:
        return None
    ordinary, _, at_fifteen, at_twenty = rate_bands(taxable, preferred, year, filing)
    tax = whole(at_fifteen * RATE_15 + at_twenty * RATE_20) + on_brackets(ordinary, year, filing)
    return min(tax, on_brackets(max(ZERO, taxable), year, filing))


def line_18(income: Decimal, preferred: Decimal, year: int, filing: str, at_25: Decimal = ZERO) -> Decimal:
    """Form 1116's Worksheet for Line 18: the income less the world's gains and qualified dividends, weighted by how
    far under the top rate each was taxed. `at_25` is the part of the gain that's Schedule D's line 19."""
    _, at_zero, at_fifteen, at_twenty = rate_bands(income, preferred, year, filing)
    moved = min(at_25, at_fifteen)
    return max(ZERO, income - (moved * WORLD_AT_25 + at_twenty * WORLD_AT_20 + (at_fifteen - moved) * WORLD_AT_15
                               + at_zero))


def adjusted_gain(gain: Decimal, income: Decimal, preferred: Decimal, year: int, filing: str) -> Decimal:
    """A foreign gain's share on Form 1116's line 1a, nothing of what's taxed at 0%."""
    _, _, at_fifteen, at_twenty = rate_bands(income, preferred, year, filing)
    gain = max(ZERO, gain)
    fifteen = min(gain, at_fifteen)
    return fifteen * GAIN_AT_15 + min(gain - fifteen, at_twenty) * GAIN_AT_20


def must_adjust(foreign_gain: Decimal, ordinary: Decimal, year: int, filing: str) -> bool:
    """Whether the adjustment exception is out of reach: the bar is where the 32% bracket starts."""
    top = next(Decimal(low) for low, rate in BRACKETS[(year, filing)][1] if rate == "0.32")
    return foreign_gain >= ADJUST_FROM or ordinary > top


def child_credit(children: int, agi: Decimal, filing: str) -> Decimal:
    """Schedule 8812's credit before the limit of the tax: $50 off for each $1,000, or part of it, past the line."""
    over = agi - CHILD_PHASE_OUT.get(filing, CHILD_PHASE_OUT_OTHER)
    steps = (over / 1000).to_integral_value(rounding=ROUND_CEILING) if over > 0 else ZERO
    return max(ZERO, CHILD_CREDIT * children - steps * 50)


def foreign_limit(tax: Decimal, foreign_taxable: Decimal, income: Decimal) -> Decimal:
    """Form 1116's line 21: the tax times foreign taxable income over the income the tax was on, at most the whole."""
    if income <= 0 or foreign_taxable <= 0:
        return ZERO
    return whole(tax * min(Decimal(1), foreign_taxable / income))


def _dollars(value: object) -> Decimal:
    return Decimal(str(value)) if value not in (None, "") else ZERO


def _qualified_dividends(forms: list[dict], faces: list[dict], year: int) -> Decimal:
    held = sum((_dollars((f.get("amounts", {}).get("1b") or {}).get("amount")) for f in forms
                if f.get("form") == "1099-DIV" and f.get("year") == year and f.get("copy_of") is None), ZERO)
    return held + sum((_dollars(i["value"].get("amount")) for f in faces for i in f.get("items", [])
                       if i["box"] == "6b"), ZERO)


def _net_long(sales: dict | None, found: dict | None, faces: list[dict]) -> tuple[Decimal, Decimal]:
    """The year's net long-term gain and its short-term net."""
    sold = sales or {}
    abroad = sum((_dollars(s.get("gain")) for s in (found or {}).get("sales", [])), ZERO)
    k1_long = sum((_dollars(i["value"].get("amount")) for f in faces for i in f.get("items", []) if i["box"] == "9a"),
                  ZERO)
    k1_short = sum((_dollars(i["value"].get("amount")) for f in faces for i in f.get("items", []) if i["box"] == "8"),
                   ZERO)
    return (_dollars(sold.get("long")) + _dollars(sold.get("distributions")) - _dollars(sold.get("carry_long"))
            + abroad + k1_long, _dollars(sold.get("short")) - _dollars(sold.get("carry_short")) + k1_short)


def _itemized(year: int, forms: list[dict], rental: dict | None, agi_total: Decimal, confirmed: dict) -> Decimal:
    interest = sum((_dollars((f.get("amounts", {}).get("1") or {}).get("amount"))
                    for f in d400.home_loans(forms, year, rental)), ZERO)
    state = sum((_dollars((f.get("amounts", {}).get("17") or {}).get("amount")) for f in forms
                 if f.get("form") == "W-2" and f.get("year") == year and f.get("copy_of") is None), ZERO)
    salt = min(SALT_CAP.get(year, max(SALT_CAP.values())), state + _dollars(confirmed.get("property_tax")))
    medical = max(ZERO, _dollars(confirmed.get("medical")) - agi_total * MEDICAL_FLOOR)
    return interest + salt + _dollars(confirmed.get("charity")) + medical


def _qbi(qbi: dict | None, before: Decimal, preferred: Decimal) -> Decimal:
    if not qbi:
        return ZERO
    lines = qbi.get("lines", {})
    component = _dollars(lines.get("10"))
    return whole(max(ZERO, min(component, QBI_RATE * max(ZERO, before - preferred))))


def gross_income(agi: Agi, rental: dict | None) -> Decimal:
    """Form 1116's line 3e, income before its deductions: a rental's rents and not its profit, the K-1s' income and not
    their losses, and adjustments or the rates don't come into it."""
    net_rent = _dollars((rental or {}).get("income_or_loss"))
    rents = _dollars((((rental or {}).get("lines") or {}).get("3") or {}).get("amount"))
    others = sum((p.amount for p in agi.parts if p.line not in ("8", "10") and p.amount is not None and p.amount > 0),
                 ZERO)
    schedule_1 = next((p.amount or ZERO for p in agi.parts if p.line == "8"), ZERO)
    return others + rents + max(ZERO, schedule_1 - net_rent)


def _foreign(form: Form, found: dict | None, agi: Agi, deduction: Decimal, tax: Decimal, preferred: Decimal,
             rental: dict | None = None) -> Decimal:
    """Form 1116, passive category, as this return has it: its lines by number; the credit is line 35."""
    if not found:
        return ZERO
    gain = sum((_dollars(s.get("gain")) for s in found.get("sales", [])), ZERO)
    gross = gain + _dollars(found.get("interest"))
    taxes = sum((_dollars((t.get("kept") or {}).get("dollars")) for t in found.get("taxes", [])
                 if t.get("category", "passive") == "passive"), ZERO)
    carried = sum((_dollars(v) for c in found.get("carryovers", []) if c.get("category") == "passive"
                   and not c.get("amt") for v in c.get("years", {}).values()), ZERO)
    if not gross and not taxes and not carried:
        return ZERO
    every = gross_income(agi, rental)
    share = deduction * min(Decimal(1), gross / every) if every > 0 else ZERO
    income = (agi.total or ZERO) - deduction
    year, filing = form.year, form.filing
    plain = (gross, income)
    adjusted = (gross - gain + adjusted_gain(gain, income, preferred, year, filing),
                line_18(income, preferred, year, filing))
    ordinary = rate_bands(income, preferred, year, filing)[0]
    saved = tax < (on_brackets(max(ZERO, income), year, filing) or ZERO) and ordinary > 0
    ways = [adjusted] if saved else [plain]
    if saved and not must_adjust(max(ZERO, gain), ordinary, year, filing):
        ways.append(plain)
    line_1a, line_18_amount = max(ways, key=lambda way: foreign_limit(tax, way[0] - share, way[1]))
    line_7 = whole(line_1a - share)
    limit = foreign_limit(tax, line_7, line_18_amount)
    line_14 = whole(taxes + carried)
    credit = min(line_14, limit, tax)
    form.form_1116 = {"1a": whole(line_1a), "3d": whole(gross), "3e": whole(every), "3g": whole(share), "7": line_7,
                      "9": whole(taxes), "10": whole(carried), "14": line_14, "17": line_7,
                      "18": whole(line_18_amount), "20": tax, "21": limit, "35": credit}
    return credit


def build(year: int, *, agi: Agi, forms: list[dict], k1s: list[dict], filing: str = "", found: dict | None = None,
          sales: dict | None = None, rental: dict | None = None, qbi: dict | None = None,
          confirmed: dict | None = None) -> Form:
    from .qbi import faces as k1_faces

    confirmed = confirmed or {}
    form = Form(year, filing)
    if (year, filing) not in BRACKETS or (year, filing) not in CAPITAL_GAIN_BANDS:
        form.questions.append(f"{year}'s brackets for this filing status aren't in taxtrace yet: joint and single only")
        return form
    federal = agi.total
    if federal is None:
        form.lines.append(d400.Line("11", "Adjusted gross income", None, MISSING, "`taxtrace agi`"))
        form.questions.append("adjusted gross income isn't complete: see `taxtrace agi`")
        return form
    status = agi.status
    faces = k1_faces(k1s, year)
    standard = BRACKETS[(year, filing)][0]
    itemized = _itemized(year, forms, rental, federal, confirmed)
    form.deduction = "itemized" if itemized > standard else "standard"
    form.room = itemized - standard
    deduction = whole(max(itemized, standard))
    if "property_tax" not in confirmed or "charity" not in confirmed:
        form.questions.append("line 12e: the home's property tax and charity aren't confirmed, and Schedule A could "
                              "come out larger (`d400 --confirm property_tax= charity= medical=`)")
    long_net, short_net = _net_long(sales, found, faces)
    qualified = _qualified_dividends(forms, faces, year)
    preferred = qualified + max(ZERO, min(long_net, long_net + short_net))
    before = federal - deduction
    qbi_deduction = _qbi(qbi, before, preferred)
    line_14 = deduction + qbi_deduction
    taxable = max(ZERO, whole(federal) - line_14)
    tax = with_capital_gains(taxable, preferred, year, filing)
    children = int(_dollars(confirmed.get("children")))
    if "children" not in confirmed:
        form.questions.append("line 19: how many children got the child tax credit (`d400 --confirm children=N`)")
    credit_children = min(tax, child_credit(children, federal, filing))
    foreign_credit = _foreign(form, found, agi, deduction, tax, preferred, rental)
    foreign_credit = min(foreign_credit, tax - credit_children)
    line_22 = tax - credit_children - foreign_credit
    other = other_taxes(_medicare_wages(forms, year), sum((p.amount or ZERO for p in agi.parts if p.line in INVESTMENT),
                                                          ZERO), federal, filing)
    if federal > MEDICARE_OVER.get(filing, OVER_OTHER):
        form.questions.append("line 23: over the threshold, so the additional Medicare tax or the net investment "
                              "income tax applies: an estimate until Forms 8959 and 8960 are compared")
    add = form.lines.append
    add(d400.Line("11", "Adjusted gross income", whole(federal), status, "`taxtrace agi`"))
    add(d400.Line("12e", f"{form.deduction.capitalize()} deduction", deduction, status))
    add(d400.Line("13a", "Qualified business income deduction", qbi_deduction, status, "`taxtrace qbi`"))
    add(d400.Line("14", "Lines 12e, 13a and 13b", line_14, status))
    add(d400.Line("15", "Taxable income", taxable, status))
    add(d400.Line("16", "Tax", tax, status, "Qualified Dividends and Capital Gain Tax Worksheet"))
    add(d400.Line("19", "Child tax credit", credit_children, READY if "children" in confirmed else MISSING))
    add(d400.Line("20", "Foreign tax credit (Form 1116)", foreign_credit, ESTIMATE if found else READY,
                  "`taxtrace foreign`"))
    add(d400.Line("22", "Line 18 less line 21", line_22, status))
    add(d400.Line("23", "Other taxes", other, status))
    add(d400.Line("24", "Total tax", line_22 + other, status))
    form.questions.append(AMT_NOTE)
    return form


def _medicare_wages(forms: list[dict], year: int) -> Decimal:
    return sum((_dollars((f.get("amounts", {}).get("5") or {}).get("amount")) for f in forms
                if f.get("form") == "W-2" and f.get("year") == year and f.get("copy_of") is None), ZERO)


def other_taxes(medicare_wages: Decimal, investment: Decimal, income: Decimal, filing: str) -> Decimal:
    """Line 23: Form 8959's tax on wages past the threshold, Form 8960's on investment income past it."""
    over = MEDICARE_OVER.get(filing, OVER_OTHER)
    return whole(max(ZERO, medicare_wages - over) * MEDICARE_RATE
                 + min(max(ZERO, investment), max(ZERO, income - over)) * INVESTMENT_RATE)


def compare(form: Form, filed: dict[str, Decimal], filed_1116: dict[str, Decimal], schedule_d: dict[str, Decimal],
            filing: str, children: int | None, forms: list[dict] | None = None,
            form_4797: dict[str, Decimal] | None = None) -> tuple[list[Check], list[str]]:
    """The built lines against the year's filed return, then each rule from the filed form's own inputs: which way and
    roughly how far, never an amount. A line with nothing on either side tests nothing, and is listed apart."""
    checks, untested = [], []
    for line in form.lines:
        if line.line == "11":
            continue
        theirs = filed.get(line.line, ZERO)
        if line.amount is not None and not line.amount and not theirs:
            untested.append(f"line {line.line}: nothing on either side")
        else:
            checks.append(difference(f"line {line.line}", line.amount, theirs))
    for no, amount in form.form_1116.items():
        if no in filed_1116 or amount:
            if no in ("1a", "3d", "3e", "3g", "7", "9", "14", "18", "21", "35"):
                checks.append(difference(f"Form 1116 line {no}", amount, filed_1116.get(no, ZERO)))
    year = form.year
    if "15" in filed and "16" in filed:
        long_net = schedule_d.get("15", ZERO)
        net = max(ZERO, min(long_net, schedule_d.get("16", ZERO)))
        preferred = filed.get("3a", ZERO) + net
        tax = with_capital_gains(filed["15"], preferred, year, filing)
        checks.append(difference("line 16 worked from the filed taxable income", tax, filed["16"]))
        if "18" in filed_1116 and (year, filing) in CAPITAL_GAIN_BANDS:
            checks.append(difference("Form 1116 line 18 worked from the filed taxable income",
                                     whole(line_18(filed["15"], preferred, year, filing, schedule_d.get("19", ZERO))),
                                     filed_1116["18"]))
        if (form_4797 or {}).get("24") and "1a" in filed_1116 and "3d" in filed_1116:
            gain = form_4797["24"]
            checks.append(difference("Form 1116 line 1a worked from its line 3d and Form 4797's gain",
                                     whole(filed_1116["3d"] - gain + adjusted_gain(gain, filed["15"], preferred, year,
                                                                                   filing)), filed_1116["1a"]))
    if all(k in filed_1116 for k in ("3d", "3e", "3g")) and filed.get("12e") and filed_1116["3e"]:
        ratio = round(filed_1116["3d"] / filed_1116["3e"], 5)
        checks.append(difference("Form 1116 line 3g worked from its lines 3d and 3e and line 12e",
                                 whole(filed["12e"] * ratio), filed_1116["3g"]))
    if "11a" in filed or "11b" in filed or "11" in filed:
        agi = next(filed[k] for k in ("11b", "11a", "11") if k in filed)
        if children is not None and filed.get("19"):
            checks.append(difference("line 19 worked from the filed income and the children",
                                     min(child_credit(children, agi, filing), filed.get("16", ZERO)), filed["19"]))
        if "14" in filed and "15" in filed:
            checks.append(difference("line 15 worked from the filed income and line 14", agi - filed["14"],
                                     filed["15"]))
        if forms is not None and any(f.get("form") == "W-2" and f.get("year") == year for f in forms):
            investment = sum((filed.get(n, ZERO) for n in (*INVESTMENT, "7a")), ZERO)
            checks.append(difference("line 23 worked from the filed income and the W-2s",
                                     other_taxes(_medicare_wages(forms, year), investment, agi, filing),
                                     filed.get("23", ZERO)))
    if (year, filing) in BRACKETS and filed.get("12e") and "itemized" not in form.deduction:
        checks.append(difference("line 12e is the year's standard deduction", BRACKETS[(year, filing)][0],
                                 filed["12e"]))
    if all(k in filed_1116 for k in ("17", "18", "20", "21")):
        checks.append(difference("Form 1116 line 21 worked from its filed lines 17, 18 and 20",
                                 foreign_limit(filed_1116["20"], filed_1116["17"], filed_1116["18"]), filed_1116["21"]))
    return checks, untested


def to_text(form: Form) -> str:
    def row(line: d400.Line) -> str:
        value = f"{line.amount:,.0f}" if line.amount is not None else "?"
        mark = {READY: "", ESTIMATE: " [estimate]", MISSING: " [missing]"}[line.status]
        return f"  {line.line}. {line.what}: {value}{mark}" + (f"  <- {line.source}" if line.source else "")

    out = [f"{form.year} Form 1040, lines 11 to 24", *map(row, form.lines)]
    if form.form_1116:
        out += ["", "Form 1116, passive category"]
        out += [f"  {no}. {amount:,.0f}" for no, amount in form.form_1116.items()]
    if form.questions:
        out += ["", "Still to settle", *(f"  - {q}" for q in form.questions)]
    return "\n".join(out) + "\n"
