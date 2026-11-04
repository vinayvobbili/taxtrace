"""North Carolina's Form D-400 for a year, with its Schedule S and Schedule A, for a full-year resident.

It starts from federal adjusted gross income (`agi`), as North Carolina does, and follows the form's lines, per the
Department of Revenue's D-400 and D-401 instructions for 2025:

- Schedule S, Part A (line 7): what the NC K-1s add (their lines 2 and 10), and anything confirmed.
- Schedule S, Part B (line 9): what the NC K-1s deduct (lines 3 and 11), interest on US obligations (1099-INT box 3,
  and a fund's share confirmed with `us_interest`), and anything confirmed.
- Line 10: the child deduction, from the state's table by filing status and federal income.
- Line 11: the larger of the state's standard deduction and Schedule A: home mortgage interest and real estate
  property taxes together up to $20,000, gifts to charity, and medical costs past 7.5% of federal income.
- Line 15: a flat rate on line 14 (4.25% in 2025, 3.99% in 2026).
- Lines 20 and 21: state tax withheld (the W-2s' box 17 or the pay stub's projection, and NC K-1 line 5), and
  estimated payments confirmed.

North Carolina has no credit for tax paid to another country, so nothing from Form 1116 comes here. Amounts are whole
dollars, as the form asks. The standard deduction and child table for 2026 are 2025's: the state's 2026 instructions
aren't out, so check them when they are. Nonresidents and part-year residents (Schedule PN) aren't covered.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from . import estimates, paystub, schedule_e
from .agi import ESTIMATE, MISSING, READY, Agi, difference
from .prior import Check

ZERO = Decimal(0)
RATE = {2025: Decimal("0.0425"), 2026: Decimal("0.0399")}
STANDARD = {"joint": Decimal(25500), "single": Decimal(12750), "separate": Decimal(12750), "head": Decimal(19125)}
HOME_LIMIT = Decimal(20000)
MEDICAL_FLOOR = Decimal("0.075")
# the deduction per child, $3,000 down to $0 in $500 steps, at federal income up to each of these
CHILD_STEPS = {"joint": (40000, 60000, 80000, 100000, 120000, 140000),
               "head": (30000, 45000, 60000, 75000, 90000, 105000),
               "single": (20000, 30000, 40000, 50000, 60000, 70000),
               "separate": (20000, 30000, 40000, 50000, 60000, 70000)}
AMOUNTS = ("additions", "deductions", "us_interest", "property_tax", "charity", "medical", "credits", "use_tax",
           "estimated", "extension")
TOLERANCE = Decimal(1)
INPUTS = {"16": "credits", "18": "use_tax", "21a": "estimated", "21b": "extension"}  # lines only `--confirm` fills
PAID = ("20", "23", "26a", "28")  # what the tax withheld decides


@dataclass
class Line:
    line: str
    what: str
    amount: Decimal | None
    status: str = READY
    source: str = ""


@dataclass
class Form:
    year: int
    lines: list[Line] = field(default_factory=list)
    schedule_s: list[Line] = field(default_factory=list)
    schedule_a: list[Line] = field(default_factory=list)
    deduction: str = ""  # "standard" or "itemized": line 11's circle
    questions: list[str] = field(default_factory=list)

    def amount(self, line: str) -> Decimal | None:
        return next((n.amount for n in self.lines if n.line == line), None)

    def to_json(self) -> dict:
        return asdict(self)


def confirmation(spec: str) -> tuple[str, str]:
    """'children=2', 'property_tax=3,200', 'charity=500', 'use_tax=0'."""
    key, sep, value = (s.strip().lower() for s in spec.partition("="))
    usage = ValueError(f"--confirm takes children=N or AMOUNT for one of {', '.join(AMOUNTS)}")
    if not sep or (key != "children" and key not in AMOUNTS):
        raise usage
    try:
        number = Decimal(value.replace(",", "").lstrip("$"))
    except InvalidOperation:
        raise usage from None
    if not number.is_finite() or number < 0 or (key == "children" and number != number.to_integral_value()):
        raise usage
    return key, str(number)


def whole(value: Decimal) -> Decimal:
    return value.quantize(Decimal(1), ROUND_HALF_UP)


def child_deduction(filing: str, income: Decimal, children: int) -> Decimal:
    """Line 10b: the state's amount per child at this income, for each child."""
    for n, top in enumerate(CHILD_STEPS[filing]):
        if income <= top:
            return Decimal(3000 - 500 * n) * children
    return ZERO


def home_loans(forms: list[dict], year: int, rental: dict | None) -> list[dict]:
    """The year's 1098s other than the rental's, which go on Schedule E."""
    address = (rental or {}).get("address", "")
    return [f for f in forms if f.get("form") == "1098" and f.get("year") == year and f.get("copy_of") is None
            and not (address and schedule_e.same_place(f.get("address", ""), address))]


def _dollars(value: object) -> Decimal:
    return ZERO if value is None else Decimal(str(value))


def _nc_k1s(k1s: list[dict], year: int) -> list[dict]:
    return [f for f in k1s if f.get("form") == "D-403" and f.get("year") == year and f.get("copy_of") is None]


def _sum_lines(rows: list[dict], *numbers: str) -> Decimal:
    return sum((_dollars((f.get("lines", {}).get(n) or {}).get("amount")) for f in rows for n in numbers), ZERO)


def _withheld(year: int, forms: list[dict], rows: list[dict]) -> tuple[Decimal | None, str, str]:
    from_k1s = _sum_lines(rows, "5")
    w2s = [f for f in forms if f.get("form") == "W-2" and f.get("year") == year and f.get("copy_of") is None]
    if w2s:
        total = sum((_dollars((f.get("amounts", {}).get("17") or {}).get("amount")) for f in w2s), ZERO)
        return total + from_k1s, READY, "the W-2s"
    stub = estimates.latest_stub(forms, year)
    if stub and (state := paystub.from_json(stub).projected("state")) is not None:
        return state + from_k1s, ESTIMATE, "the latest pay stub, projected to December 31"
    if rows:
        return from_k1s, ESTIMATE, "the NC K-1s, no W-2 or pay stub read"
    return None, MISSING, "`taxtrace paystub`"


def build(year: int, *, agi: Agi, forms: list[dict], k1s: list[dict], filing: str = "", rental: dict | None = None,
          confirmed: dict | None = None) -> Form:
    confirmed = confirmed or {}
    form = Form(year)
    if year not in RATE:
        form.questions.append(f"North Carolina's rate for {year} isn't in taxtrace yet")
        return form
    if filing not in STANDARD:
        form.questions.append("how you file (`taxtrace foreign --confirm filing=joint|single|separate|head`)")
        return form
    rows = _nc_k1s(k1s, year)

    def amount(key: str) -> Decimal:
        return Decimal(confirmed.get(key, 0))

    federal, status = agi.total, agi.status
    if federal is None:
        form.lines.append(Line("6", "Federal adjusted gross income", None, MISSING, "`taxtrace agi`"))
        form.questions.append("federal adjusted gross income isn't complete: see `taxtrace agi`")
        return form
    source = f"`taxtrace agi`, {status}"

    additions = _part_a(form, rows, amount)
    line_9 = _part_b(form, rows, forms, year, amount, "us_interest" in confirmed)
    line_6, line_7 = whole(federal), whole(additions)
    line_8 = line_6 + line_7
    if "children" not in confirmed:
        form.questions.append("line 10a: how many children got the federal child tax credit (`--confirm children=N`)")
    children = int(Decimal(confirmed.get("children", 0)))
    line_10b = child_deduction(filing, federal, children)
    line_11, form.deduction = _deduction(form, year, forms, rental, federal, filing, amount)
    line_11 = whole(line_11)
    line_12a = whole(line_9) + line_10b + line_11
    line_12b = line_8 - line_12a
    line_15 = max(ZERO, whole(line_12b * RATE[year]))
    credits = whole(amount("credits"))
    line_17 = max(ZERO, line_15 - credits)
    if "use_tax" not in confirmed:
        form.questions.append("line 18: consumer use tax on purchases where no sales tax was charged, or certify none "
                              "(`--confirm use_tax=AMOUNT`)")
    line_19 = line_17 + whole(amount("use_tax"))
    withheld, withheld_status, withheld_from = _withheld(year, forms, rows)
    line_20 = whole(withheld) if withheld is not None else None
    estimated, extension = whole(amount("estimated")), whole(amount("extension"))
    line_23 = None if line_20 is None else line_20 + estimated + extension

    def add(line: str, what: str, value: Decimal | None, line_status: str = status, src: str = "") -> None:
        form.lines.append(Line(line, what, value, line_status, src))

    add("6", "Federal adjusted gross income", line_6, status, source)
    add("7", "Additions (Schedule S, Part A)", line_7)
    add("8", "Lines 6 and 7", line_8)
    add("9", "Deductions (Schedule S, Part B)", whole(line_9))
    add("10a", "Qualifying children", Decimal(children), READY if "children" in confirmed else MISSING)
    add("10b", "Child deduction", line_10b)
    add("11", f"N.C. {form.deduction} deduction", line_11)
    add("12a", "Lines 9, 10b and 11", line_12a)
    add("12b", "Line 8 less line 12a", line_12b)
    add("14", "North Carolina taxable income", line_12b)
    add("15", f"North Carolina income tax at {RATE[year] * 100:.2f}%", line_15)
    add("16", "Tax credits (D-400TC)", credits, READY, "confirmed" if "credits" in confirmed else "")
    add("17", "Line 15 less line 16", line_17)
    add("18", "Consumer use tax", whole(amount("use_tax")), READY if "use_tax" in confirmed else MISSING)
    add("19", "Lines 17 and 18", line_19)
    add("20", "North Carolina tax withheld (20a and 20b)", line_20, withheld_status, withheld_from)
    add("21a", "Estimated tax paid", estimated, READY, "confirmed" if "estimated" in confirmed else "")
    add("21b", "Paid with an extension", extension, READY, "confirmed" if "extension" in confirmed else "")
    if line_23 is None:
        add("23", "Total payments", None, MISSING)
        return form
    worst = MISSING if withheld_status == MISSING else ESTIMATE if ESTIMATE in (status, withheld_status) else status
    add("23", "Total payments", line_23, withheld_status)
    if line_23 < line_19:
        add("26a", "Tax due", line_19 - line_23, worst)
    else:
        add("28", "Overpayment", line_23 - line_19, worst)
    return form


def _part_a(form: Form, rows: list[dict], amount) -> Decimal:
    """Part A: its total."""
    from_k1s = _sum_lines(rows, "2", "10")
    if from_k1s:
        form.schedule_s.append(Line("A", "From the NC K-1s (their lines 2 and 10): put each on its Part A line",
                                    whole(from_k1s), READY, "the NC K-1s"))
    if amount("additions"):
        form.schedule_s.append(Line("A", "Confirmed by you", whole(amount("additions")), READY, "confirmed"))
    return from_k1s + amount("additions")


def _part_b(form: Form, rows: list[dict], forms: list[dict], year: int, amount, fund_share_known: bool) -> Decimal:
    """Part B: its total."""
    from_k1s = _sum_lines(rows, "3", "11")
    bonds = sum((_dollars((f.get("amounts", {}).get("3") or {}).get("amount")) for f in forms
                 if f.get("form") == "1099-INT" and f.get("year") == year and f.get("copy_of") is None), ZERO)
    us_interest = bonds + amount("us_interest")
    if from_k1s:
        form.schedule_s.append(Line("B", "From the NC K-1s (their lines 3 and 11): put each on its Part B line",
                                    whole(from_k1s), READY, "the NC K-1s"))
    if us_interest:
        form.schedule_s.append(Line("B18", "Interest on US obligations", whole(us_interest), READY, "1099-INT box 3"))
    if amount("deductions"):
        form.schedule_s.append(Line("B", "Confirmed by you", whole(amount("deductions")), READY, "confirmed"))
    if not fund_share_known and any(f.get("form") == "1099-DIV" and f.get("year") == year for f in forms):
        form.questions.append("Schedule S line 18: a fund's dividends paid from US Treasury interest are deductible "
                              "here; the fund's year-end letter gives its share (`--confirm us_interest=AMOUNT`)")
    return from_k1s + us_interest + amount("deductions")


def _deduction(form: Form, year: int, forms: list[dict], rental: dict | None, federal: Decimal, filing: str,
               amount) -> tuple[Decimal, str]:
    """Line 11: Schedule A's lines, then the larger of it and the standard deduction."""
    loans = home_loans(forms, year, rental)
    interest = sum((_dollars((f.get("amounts", {}).get("1") or {}).get("amount")) for f in loans), ZERO)
    tax, charity = amount("property_tax"), amount("charity")
    home = min(interest + tax, HOME_LIMIT)
    medical = max(ZERO, amount("medical") - federal * MEDICAL_FLOOR)
    total = home + charity + medical
    add = form.schedule_a.append
    add(Line("1", "Home mortgage interest", whole(interest), READY if loans else MISSING,
             "the 1098s" if loans else "`taxtrace 1098`, when the home's 1098 comes"))
    add(Line("2", "Real estate property taxes", whole(tax), READY if tax else MISSING,
             "confirmed" if tax else "`--confirm property_tax=AMOUNT`"))
    add(Line("5", "Lines 1 and 2, up to $20,000", whole(home)))
    add(Line("6", "Charitable contributions", whole(charity), READY, "confirmed" if charity else ""))
    add(Line("7d", "Medical and dental past 7.5% of federal income", whole(medical), READY,
             "confirmed" if amount("medical") else ""))
    add(Line("10", "Total itemized deductions", whole(total)))
    standard = STANDARD[filing]
    if total > standard:
        return total, "itemized"
    if not loans or not tax:
        form.questions.append("line 11: the standard deduction is used, because the home's mortgage interest or "
                              "property tax isn't in yet: Schedule A may come out larger once they are")
    return standard, "standard"


def compare(form: Form, filed: dict[str, Decimal], *, confirmed: dict | None = None,
            has_w2: bool = True) -> tuple[list[Check], list[str]]:
    """Each built line against the year's filed D-400: which way and roughly how far, never an amount. A line that
    can't test anything is listed apart and not counted either way: nothing on either side, an amount only you can
    confirm that wasn't given for this year, or the payments while no W-2 has been read."""
    confirmed = confirmed or {}
    checks, untested = [], []
    unpaid = any(filed.get(n) and INPUTS[n] not in confirmed for n in ("21a", "21b"))  # payments the build wasn't given
    for line in form.lines:
        theirs = filed.get("20a", ZERO) + filed.get("20b", ZERO) if line.line == "20" else filed.get(line.line, ZERO)
        if line.amount is not None and not line.amount and not theirs:
            untested.append(f"line {line.line}: nothing on either side")
        elif line.line in INPUTS and INPUTS[line.line] not in confirmed:
            untested.append(f"line {line.line}: an amount you confirm, not given for {form.year}")
        elif line.line in PAID and line.line != "20" and unpaid:
            untested.append(f"line {line.line}: depends on a payment you confirm, not given for {form.year}")
        elif line.line in PAID and not has_w2:
            untested.append(f"line {line.line}: no W-2 has been read")
        else:
            checks.append(difference(f"line {line.line}", line.amount, theirs))
    if "14" in filed and "15" in filed and form.year in RATE:  # the rule alone, whatever the income above it
        checks.append(difference("line 15 worked from the filed line 14", whole(filed["14"] * RATE[form.year]),
                                 filed["15"]))
    return checks, untested


def to_text(form: Form) -> str:
    """The form's lines, to compare with what the filing site's state return shows."""
    def row(line: Line) -> str:
        value = f"{line.amount:,.0f}" if line.amount is not None else "?"
        mark = {READY: "", ESTIMATE: " [estimate]", MISSING: " [missing]"}[line.status]
        return f"  {line.line}. {line.what}: {value}{mark}" + (f"  <- {line.source}" if line.source else "")

    lines = [f"North Carolina D-400 for {form.year}", ""]
    lines += [row(n) for n in form.lines]
    if form.schedule_s:
        lines += ["", "Schedule S", *(row(n) for n in form.schedule_s)]
    if form.schedule_a:
        lines += ["", f"Schedule A (line 11 uses the {form.deduction} deduction)", *(row(n) for n in form.schedule_a)]
    if form.questions:
        lines += ["", "Still to settle:", *(f"  {q}" for q in form.questions)]
    return "\n".join(lines).rstrip() + "\n"
