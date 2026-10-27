"""Carryforwards from a filed return: the depreciation schedule, Form 8582's unallowed passive losses, and the
foreign tax carried over on Schedule B (Form 1116) (read by `f1116b`).

Next year's return starts from these: each asset's depreciation so far, and each activity's loss that couldn't be
taken yet. They're read from the preparer software's own printouts (Drake's two layouts so far: the "Federal
Depreciation Schedule" and the "Depreciation Detail Listing", whose land rows carry no depreciation, and Form 8582's
Worksheets 5 and 6), never from a model. "Next Year's Depreciation Worksheet", where printed, is checked against a
year's depreciation rolled forward.

Every value keeps its page and the exact line it came from, and `verify` checks each line is still on its page.
Whatever doesn't add up (a row against the totals line, a ratio against the losses) is a failed check, and
whatever can't be settled from the page alone (a bonus or Section 179 amount, business use under 100%) is a
question: neither is ever papered over. Alternative minimum tax and book copies of the same schedules are skipped.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from itertools import pairwise

from . import text

DATE = r"\d{1,2}/\d{1,2}/\d{2,4}|\d{1,2}-\d{1,2}-\d{2,4}|\d{8}"
ROW = re.compile(rf"^\s*(?P<no>\d+)\s+(?P<desc>\S.*?)\s+(?P<acquired>{DATE})(?:\s+(?P<sold>{DATE}))?\s+(?P<rest>.+)$")
METHOD = re.compile(r"^(?:S/L|SL|\d{3}DB|DB|MACRS|ADS|AMORT)$")
CONVENTION = re.compile(r"^[A-Z]{2}$")  # MM, HY, MQ
NUMBER = re.compile(r"^-?\(?\$?(?:\d{1,3}(?:,\d{3})+|\d+)?(?:\.\d*)?\)?\*?$")
PERCENT = re.compile(r"^\d{1,3}\.\d\d$")  # business use, "100.00"
WORKSHEET = re.compile(r"^\s*Worksheet\s+(\d)\b")
# the three amounts that end a Worksheet 5 or 6 row; what comes before is the activity and its form and line
FIGURE = r"-?[\d,]*\d\.?\d*"
THREE = re.compile(rf"^\s*(?P<head>\S.*?)\s+(?P<a>{FIGURE})\s+(?P<b>{FIGURE})\s+(?P<c>{FIGURE})\s*$")
SKIP = re.compile(r"MIN TAX PURPOSES|Alternative Minimum Tax|Book Depreciation", re.IGNORECASE)
YEAR = re.compile(r"(?<!\d)((?:19|20)\d\d)(?!\d)")
CENT = Decimal("1")  # amounts are whole dollars: a sum may be off by a dollar per row from rounding
RATIO = Decimal("0.0005")
COLUMNS = ("cost", "basis", "prior", "current")  # the amounts two copies of a schedule could disagree on


def amount(token: str) -> Decimal:
    """'1,234.' or '(1,234)' or '-1,234.00' or '318,400*' as a number; a minus or parentheses make it negative."""
    negative = token.startswith("-") or token.startswith("(")
    digits = token.strip("-()$*").rstrip(".").replace(",", "")
    try:
        value = Decimal(digits or "0")
    except InvalidOperation:
        raise ValueError(f"not an amount: {token!r}") from None
    return -value if negative else value


def printed_date(printed: str) -> date | None:
    """A date in any of the layouts' spellings ("7/22/16", "07-22-2016", "07222016")."""
    for fmt in ("%m/%d/%y", "%m/%d/%Y", "%m-%d-%Y", "%m-%d-%y", "%m%d%Y"):
        try:
            return datetime.strptime(printed, fmt).date()
        except ValueError:
            continue
    return None


def _number(token: str) -> bool:
    return bool(NUMBER.match(token)) and any(c.isdigit() for c in token)


def _rate(token: str) -> Decimal:
    """A depreciation rate as a fraction: the schedule prints ".03636", the older listing "3.636" (percent)."""
    value = amount(token)
    return value / 100 if value > 1 else value


@dataclass
class Asset:
    number: str
    description: str
    activity: str  # the schedule's section ("RENTAL PROPERTY"), when the layout has one
    placed_in_service: str
    cost: Decimal
    basis: Decimal  # depreciable basis
    prior: Decimal  # depreciation taken before this year
    current: Decimal  # this year's
    method: str
    convention: str
    life: Decimal
    rate: Decimal  # of the basis, a full year's share ("0.03636")
    page: int
    quote: str

    @property
    def accumulated(self) -> Decimal:
        """Depreciation taken through this year: next year's prior depreciation."""
        return self.prior + self.current

    @property
    def annual(self) -> Decimal:
        """A full year's depreciation at this rate, in whole dollars as the preparer rounds it."""
        return (self.basis * self.rate).quantize(CENT, ROUND_HALF_UP)

    def in_service(self) -> date | None:
        return printed_date(self.placed_in_service)

    def key(self) -> tuple:
        return (self.number, self.description, self.placed_in_service, self.cost, self.basis, self.prior,
                self.current)


@dataclass
class Unallowed:
    """One activity's row on Form 8582 Worksheet 5: its loss, its share, and what couldn't be taken this year."""

    activity: str
    form_line: str  # where the loss is reported ("SCH E P1 22")
    loss: Decimal
    ratio: Decimal
    unallowed: Decimal  # carried to next year's Worksheet 1 or 3, column (c)
    page: int
    quote: str


@dataclass
class Activity:
    """One activity's row on Form 8582 Worksheet 1 (rental real estate with active participation) or Worksheet 3
    (every other passive activity): this year's net income or loss, the unallowed loss it brought in from earlier
    years, and the overall gain or loss. Every passive activity is here, not only those with a loss carried on."""

    worksheet: str  # "1" or "3"
    activity: str
    net_income: Decimal  # (a)
    net_loss: Decimal  # (b)
    prior_unallowed: Decimal  # (c): the year before's Worksheet 5 unallowed loss
    gain: Decimal  # (d)
    loss: Decimal  # (e)
    page: int
    quote: str  # the row's words, in order


@dataclass
class Check:
    what: str
    ok: bool
    page: int
    quote: str = ""  # the document's own text the check is about, kept apart so `what` holds none


@dataclass
class Question:
    text: str
    page: int
    quote: str


@dataclass
class Carryforwards:
    file: str
    year: int | None
    assets: list[Asset] = field(default_factory=list)
    unallowed: list[Unallowed] = field(default_factory=list)
    activities: list[Activity] = field(default_factory=list)  # Worksheets 1 and 3, read by position
    checks: list[Check] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    skipped: list[int] = field(default_factory=list)  # AMT and book copies
    other_years: dict[int, int] = field(default_factory=dict)  # page: the year of a schedule for another year
    rentals: list = field(default_factory=list)  # the filed Schedule E's properties (`schedule_e.Rental`)
    foreign_tax: list = field(default_factory=list)  # Schedule B (Form 1116) by category (`f1116b.Schedule`)
    carryovers: list = field(default_factory=list)  # the Carryover Worksheet's rows (`carryover.Item`)
    carryover_sections: list[str] = field(default_factory=list)  # every section it prints, empty ones too
    qbi: object | None = None  # the filed Form 8995 (`f8995.Filed`)

    def check(self, what: str, ok: bool, page: int) -> None:
        self.checks.append(Check(what, ok, page))

    def ask(self, question: str, page: int, quote: str) -> None:
        self.questions.append(Question(question, page, quote))

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def to_json(self) -> dict:
        def plain(obj):
            if isinstance(obj, Decimal):
                return str(obj)
            if isinstance(obj, dict):
                return {k: plain(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [plain(v) for v in obj]
            return obj

        out = plain(asdict(self))
        for row, asset in zip(out["assets"], self.assets, strict=True):
            row["accumulated"] = str(asset.accumulated)
        return out


def has_activities(page: str) -> bool:
    """Whether a page has Form 8582's Worksheet 1 or 3, whose rows are read by position (`text.words`)."""
    return bool(re.search(r"^\s*Worksheet\s+[13]\b", page, re.MULTILINE))


def needs_words(page: str) -> bool:
    """Whether `read` wants a page's words (`text.words`): Form 8582's Worksheets 1 and 3, Schedule B (Form 1116)
    and the Carryover Worksheet, whose amounts are placed by the column they sit in."""
    from . import carryover, f1116b

    return has_activities(page) or f1116b.is_page(page) or carryover.is_page(page)


def read(name: str, pages: list[str], words: dict[int, list[dict]] | None = None) -> Carryforwards:
    """The carryforwards in one return's pages. `name` is the file name, which usually gives the tax year.

    With the words of the pages `needs_words` picks (`text.words`, by page number), Worksheets 1 and 3 are read
    too (every passive activity's year, by the columns each amount sits in), and Schedule B (Form 1116): the foreign
    tax carried to next year, by the year it arose.
    """
    found = Carryforwards(file=name, year=_year(name, pages))
    schedules: list[list[Asset]] = []
    group: list[Asset] = []
    next_year: list[tuple[int, str]] = []
    for n, page in enumerate(pages, 1):
        heads = " ".join(text.headings(page, 3))
        if SKIP.search(heads):
            if "Depreciation" in heads or "8582" in page or WORKSHEET.search(page):
                found.skipped.append(n)
            continue
        if "Federal Depreciation Schedule" in heads or "Depreciation Detail Listing" in heads:
            shown = YEAR.search(re.sub(DATE, "", heads))  # the schedule's own year, past the date it was printed
            if shown and found.year and int(shown.group(1)) != found.year:
                found.other_years[n] = int(shown.group(1))  # a projection for the next year, or last year's copy
                if found.other_years[n] == found.year + 1:
                    next_year.append((n, page))
                continue
        if "Federal Depreciation Schedule" in heads:
            group = _schedule(found, n, page, group, schedules)
        elif "Depreciation Detail Listing" in heads:
            group = _listing(found, n, page, group, schedules)
        if any(WORKSHEET.match(line) for line in page.splitlines()):
            _worksheets(found, n, page)
        if words and n in words:
            _activities(found, n, words[n])
    if group:  # rows after the last totals line
        schedules.append(group)
        found.check("depreciation rows end with a totals line", False, group[-1].page)
    _keep_one_copy(found, schedules)
    _against_projection(found, next_year)
    if found.year:
        for n, page in enumerate(pages, 1):
            if "Next Year's Depreciation Worksheet" in " ".join(text.headings(page, 3)):
                _next_year(found, n, page)
    from . import schedule_e  # it builds on this module's checks and amounts

    found.rentals = schedule_e.filed(name, pages, found.year)
    for rental in found.rentals:
        for c in rental.checks:
            found.check(f"Schedule E: {c.what}", c.ok, c.page)
    from . import f1116b

    found.foreign_tax, checks, questions = f1116b.read(found.year, pages, words or {})
    found.checks += checks
    found.questions += questions
    from . import f8995

    found.qbi, checks = f8995.read(pages)
    found.checks += checks
    _carryovers(found, pages, words or {})
    if found.year is None and (found.assets or found.unallowed):
        found.ask("Which tax year is this return? Its file name doesn't say.", 1, "")
    return found


def _carryovers(found: Carryforwards, pages: list[str], words: dict[int, list[dict]]) -> None:
    """The Carryover Worksheet's rows, checked for the year they carry to and against Schedule B (Form 1116)."""
    from . import carryover

    for n, page in enumerate(pages, 1):
        if n not in words or not carryover.is_page(page):
            continue
        items, questions = carryover.read(n, words[n])
        found.carryovers += items
        found.carryover_sections += carryover.sections(words[n])
        found.questions += questions
        if found.year:
            found.check(f"the Carryover Worksheet carries to {found.year + 1}",
                        carryover.to_year(page) == found.year + 1, n)
        credit = next((i for i in items if i.label.lower().startswith("foreign tax credit")), None)
        if found.foreign_tax or credit:
            for amt, key in ((False, "regular"), (True, "amt")):
                carried = sum((sum(s.following.values(), Decimal(0)) for s in found.foreign_tax if s.amt == amt),
                              Decimal(0))
                shown = (credit.amounts.get(key, Decimal(0)) + (credit.amounts.get("amount", Decimal(0)) if not amt
                                                                 else Decimal(0))) if credit else Decimal(0)
                found.check(f"the Carryover Worksheet's foreign tax credit ({'AMT' if amt else 'regular tax'}) is "
                            "Schedule B (Form 1116)'s carryover to the following year",
                            abs(carried - shown) <= CENT, n)
        for label, line in (("qbi loss carryover", 16), ("qualified reit and ptp loss carryover", 17)):
            row = next((i for i in items if i.label.lower().startswith(label)), None)
            on_form = found.qbi.line(line) if found.qbi else Decimal(0)
            if row or on_form:  # the worksheet prints the loss without its sign
                shown = abs(row.amounts.get("amount", Decimal(0))) if row else Decimal(0)
                found.check(f"the Carryover Worksheet's {label.replace('qbi', 'QBI').replace('reit', 'REIT')} is "
                            f"Form 8995's line {line}", abs(shown - abs(on_form)) <= CENT, n)


def _against_projection(found: Carryforwards, pages: list[tuple[int, str]]) -> None:
    """The preparer's own schedule for next year: its prior depreciation should be this year's accumulated."""
    projected = Carryforwards(file=found.file, year=None)
    schedules: list[list[Asset]] = []
    for n, page in pages:
        reader = _schedule if "Federal Depreciation Schedule" in page else _listing
        schedules.append(reader(projected, n, page, [], schedules))
    by_key = {a.key()[:3]: a for group in schedules for a in group}
    for asset in found.assets:
        if (then := by_key.get(asset.key()[:3])) is not None:
            found.check(f"asset {asset.number}: next year's schedule (page {then.page}) starts from this year's "
                        "accumulated depreciation", abs(then.prior - asset.accumulated) <= CENT, then.page)
            (next_year,) = roll(asset, found.year, found.year + 1)
            found.check(f"asset {asset.number}: next year's schedule (page {then.page}) takes a full year at its "
                        "rate", abs(then.current - next_year.depreciation) <= CENT, then.page)


def _year(name: str, pages: list[str]) -> int | None:
    m = YEAR.search(name)
    return int(m.group(1)) if m else None


def _keep_one_copy(found: Carryforwards, schedules: list[list[Asset]]) -> None:
    """A return can print the same schedule twice (with the forms, and again with the statements): keep the first."""
    kept: list[list[Asset]] = []
    for group in schedules:
        same = next((k for k in kept if [a.key() for a in k] == [a.key() for a in group]), None)
        if same is not None:
            found.check(f"the schedule on page {group[0].page} repeats page {same[0].page}", True, group[0].page)
            continue
        earlier = {a.key()[:3]: a for k in kept for a in k}
        for asset in group:
            if (first := earlier.get(asset.key()[:3])) is None:
                continue
            if not (differ := [c for c in COLUMNS if getattr(first, c) != getattr(asset, c)]):
                continue
            found.ask(f"Asset {asset.number} is on page {first.page} and again on page {asset.page}, with a different "
                      f"{', '.join(differ)}: which copy is the filed one?", asset.page, asset.quote)
        kept.append(group)
    found.assets = [a for k in kept for a in k]


def _schedule(found: Carryforwards, n: int, page: str, group: list[Asset],
              schedules: list[list[Asset]]) -> list[Asset]:
    """Drake's Federal Depreciation Schedule: cost, any bonus/179/salvage columns, basis, prior, method, life, rate,
    current. Sections ("Schedule E - RENTAL PROPERTY") name the activity."""
    activity = ""
    for line in page.splitlines():
        if m := re.match(r"^\s*Schedule\s+\S+\s+-\s+(\S.*?)\s*$", line):
            activity = m.group(1)
            continue
        if re.match(r"^\s*Grand Total Depreciation\b", line):
            _totals(found, n, line, group, middle=True)
            schedules.append(group)
            group = []
            continue
        if not (m := ROW.match(line)):
            continue
        tokens = m.group("rest").split()
        at = next((i for i, t in enumerate(tokens) if METHOD.match(t)), None)
        if at is None:
            found.ask("A depreciation row with no method this reader knows: read it by hand.", n, line)
            continue
        amounts, after = tokens[:at], tokens[at + 1:]
        convention = after.pop(0) if after and CONVENTION.match(after[0]) else ""
        if len(after) < 3 or len(amounts) < 2 or not all(_number(t) for t in amounts + after[:3]):
            found.ask("A depreciation row this reader can't split into its columns: read it by hand.", n, line)
            continue
        life, current = after[0], after[2]
        cost, basis = amount(amounts[0]), amount(amounts[-2] if len(amounts) >= 3 else amounts[-1])
        prior = amount(amounts[-1]) if len(amounts) >= 3 else Decimal(0)
        if len(amounts) == 2:
            found.ask("A depreciation row with two amounts before the method, read as cost and basis with no prior "
                      "depreciation (placed in service this year?): is that right?", n, line)
        if len(amounts) > 3 and any(amount(t) for t in amounts[1:-2]):
            found.ask("This asset has a Section 179, bonus, salvage or basis-reduction amount: check what carries "
                      "forward.", n, line)
        asset = Asset(m.group("no"), m.group("desc"), activity, m.group("acquired"), cost, basis, prior,
                      amount(current), tokens[at], convention, amount(life), _rate(after[1]), n, line)
        _asset_checks(found, asset)
        if m.group("sold"):
            found.ask("This asset was sold or disposed of: nothing of it carries forward, but the sale belongs on "
                      "that year's Form 4797.", n, line)
        group.append(asset)
    return group


def _listing(found: Carryforwards, n: int, page: str, group: list[Asset],
             schedules: list[list[Asset]]) -> list[Asset]:
    """Drake's older Depreciation Detail Listing: cost, business %, basis, life, method, convention, rate, then
    prior, current and accumulated depreciation (and the AMT current, which isn't kept)."""
    for line in page.splitlines():
        if re.match(r"^\s*Totals\b", line):
            nums = [amount(t) for t in line.split()[1:] if _number(t)]
            cost, basis, after = (nums[0], nums[1], nums[2:]) if len(nums) >= 2 else (None, None, [])
            split = _prior_current(after)
            if cost is None or split is None:
                found.check("the listing's totals line splits into its columns", False, n)
            else:
                _compare(found, n, group, cost, basis, *split[:2])
            schedules.append(group)
            group = []
            continue
        if not (m := ROW.match(line)):
            continue
        tokens = m.group("rest").split()
        at = next((i for i, t in enumerate(tokens) if METHOD.match(t)), None)
        if at is None and (land := _land(m, tokens, n, line)):
            group.append(land)
            continue
        if at is None or at < 3:
            found.ask("A depreciation row this reader can't split into its columns: read it by hand.", n, line)
            continue
        before, after = tokens[:at], tokens[at + 1:]
        convention = after.pop(0) if after and CONVENTION.match(after[0]) else ""
        nums = after[1:]  # after the rate
        split = _prior_current([amount(t) for t in nums]) if all(_number(t) for t in nums) else None
        if split is None or not all(_number(t) for t in before):
            found.ask("A depreciation row this reader can't split into its columns: read it by hand.", n, line)
            continue
        cost, basis, life = before[0], before[-2], before[-1]
        middle = before[1:-2]
        use = [t for t in middle if PERCENT.match(t)]
        if use and amount(use[0]) != 100:
            found.ask("This asset is used for business less than 100% of the time: check the basis that carries "
                      "forward.", n, line)
        if any(amount(t) for t in middle if not PERCENT.match(t)):
            found.ask("This asset has a basis adjustment, Section 179 or bonus amount: check what carries forward.",
                      n, line)
        prior, current, accumulated = split
        asset = Asset(m.group("no"), m.group("desc"), "", m.group("acquired"), amount(cost), amount(basis), prior,
                      current, tokens[at], convention, amount(life), _rate(after[0]), n, line)
        found.check(f"asset {asset.number}: prior plus current is the accumulated depreciation",
                    abs(asset.accumulated - accumulated) <= CENT, n)
        _asset_checks(found, asset)
        group.append(asset)
    return group


def _land(m: re.Match, tokens: list[str], n: int, line: str) -> Asset | None:
    """A row that isn't depreciated (land): a cost, then nothing but the business use and zeros, and no method
    ("N/A" or blank). Its cost is in the listing's totals; it carries forward as basis, never as depreciation."""
    amounts = [t for t in tokens if _number(t)]
    others = [t for t in tokens if not _number(t)]
    if not amounts or len(others) > 1 or any(amount(t) for t in amounts[1:] if not PERCENT.match(t)):
        return None
    return Asset(m.group("no"), m.group("desc"), "", m.group("acquired"), amount(amounts[0]), Decimal(0), Decimal(0),
                 Decimal(0), others[0] if others else "", "", Decimal(0), Decimal(0), n, line)


def _next_year(found: Carryforwards, n: int, page: str) -> None:
    """The preparer's Next Year's Depreciation Worksheet: each asset's deduction next year (form, asset number,
    description, date, basis, method, convention, life, deduction), which should be a full year at its rate, or what
    is left of its basis."""
    # land can share its building's number and date: only depreciated assets are on this worksheet
    by_asset = {(a.number, a.in_service()): a for a in found.assets if a.annual}
    total, seen = None, Decimal(0)
    for line in page.splitlines():
        if re.match(r"^\s*TOTAL\b", line):
            nums = [amount(t) for t in line.split()[1:] if _number(t)]
            total = nums[-1] if nums else None
            continue
        if not (m := re.match(rf"^\s*[A-Z]\s+(?P<no>\d+)\s+(?P<desc>\S.*?)\s+(?P<on>{DATE})\s+(?P<rest>.+)$", line)):
            continue
        tokens = m.group("rest").split()
        if not (tokens and _number(tokens[-1]) and any(METHOD.match(t) for t in tokens)):
            continue
        deduction = amount(tokens[-1])
        seen += deduction
        if (asset := by_asset.get((m.group("no"), printed_date(m.group("on"))))) is None:
            found.ask("Next year's depreciation worksheet has an asset that isn't on this year's listing: read it by "
                      "hand.", n, line)
            continue
        (then,) = roll(asset, found.year, found.year + 1)
        found.check(f"asset {asset.number}: next year's depreciation worksheet (page {n}) takes a full year at its "
                    "rate, or what's left of its basis", abs(then.depreciation - deduction) <= CENT, n)
    if total is not None:
        found.check("next year's depreciation worksheet's rows add up to its total", abs(seen - total) <= CENT, n)


def _prior_current(nums: list[Decimal]) -> tuple[Decimal, Decimal, Decimal] | None:
    """(prior, current, accumulated) from the listing's last columns: prior, current, accumulated, AMT current.

    Prior is blank the year an asset is placed in service, so three amounts are either prior, current and
    accumulated (no AMT column) or current, accumulated and AMT: the sum tells which.
    """
    if len(nums) == 4:
        return nums[0], nums[1], nums[2]
    if len(nums) == 3:
        if abs(nums[0] + nums[1] - nums[2]) <= CENT:
            return nums[0], nums[1], nums[2]
        if nums[0] == nums[1]:
            return Decimal(0), nums[0], nums[1]
    if len(nums) == 2 and nums[0] == nums[1]:
        return Decimal(0), nums[0], nums[1]
    return None


def _asset_checks(found: Carryforwards, asset: Asset) -> None:
    found.check(f"asset {asset.number}: depreciation so far is no more than its basis",
                asset.accumulated <= asset.basis + CENT, asset.page)
    found.check(f"asset {asset.number}: basis is no more than its cost", asset.basis <= asset.cost + CENT,
                asset.page)


def _totals(found: Carryforwards, n: int, line: str, group: list[Asset], middle: bool) -> None:
    nums = [amount(t) for t in line.split() if _number(t)]
    if len(nums) < 4:
        found.check("the schedule's totals line splits into its columns", False, n)
        return
    cost, basis, prior, current = nums[0], nums[-3], nums[-2], nums[-1]
    if middle and any(nums[1:-3]):
        found.ask("The schedule's totals show Section 179, bonus or salvage amounts: check what carries forward.",
                  n, line)
    _compare(found, n, group, cost, basis, prior, current)


def _compare(found: Carryforwards, n: int, group: list[Asset], cost, basis, prior, current) -> None:
    slack = CENT * max(len(group), 1)
    for what, total, column in (("cost", cost, "cost"), ("basis", basis, "basis"),
                                ("prior depreciation", prior, "prior"), ("current depreciation", current, "current")):
        rows = sum((getattr(a, column) for a in group), Decimal(0))
        found.check(f"the rows' {what} adds up to the totals line", abs(rows - total) <= slack, n)


def _worksheets(found: Carryforwards, n: int, page: str) -> None:
    """Form 8582 Worksheet 5 (each activity's unallowed loss) and Worksheet 6 (the same, checked against it)."""
    sheet = None
    rows: dict[str, list[tuple[str, str, Decimal, Decimal, Decimal, str]]] = {"5": [], "6": []}
    for line in page.splitlines():
        if m := WORKSHEET.match(line):
            sheet = m.group(1)
            continue
        if sheet not in rows:
            continue
        m = THREE.match(line)
        if not m:
            continue
        head = m.group("head")
        if re.match(r"^\s*Total\b", head):
            _worksheet_total(found, n, sheet, rows[sheet], [amount(m.group(k)) for k in "abc"], line)
            sheet = None
            continue
        parts = re.split(r"\s{2,}", head.strip())
        activity, form_line = parts[0], " ".join(parts[1:])
        rows[sheet].append((activity, form_line, amount(m.group("a")), amount(m.group("b")), amount(m.group("c")),
                            line))
    if rows.get(sheet):
        found.check(f"Worksheet {sheet} ends with its total line", False, n)
    for activity, form_line, loss, ratio, unallowed, line in rows["5"]:
        found.unallowed.append(Unallowed(activity, form_line, abs(loss), ratio, abs(unallowed), n, line))
    for activity, _, loss, unallowed, allowed, _line in rows["6"]:
        found.check(f"Worksheet 6, {activity}: loss less unallowed is the allowed loss",
                    abs(abs(loss) - abs(unallowed) - abs(allowed)) <= CENT, n)
        five = [u for u in found.unallowed if u.activity == activity]
        if abs(unallowed):
            found.check(f"Worksheet 6, {activity}: the unallowed loss matches Worksheet 5",
                        len(five) == 1 and abs(five[0].unallowed - abs(unallowed)) <= CENT, n)


def _rows(words: list[dict], slack: float = 2.0) -> list[list[dict]]:
    """Words grouped into the rows they sit on, top to bottom, each row left to right."""
    rows: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(w["top"] - rows[-1][0]["top"]) <= slack:
            rows[-1].append(w)
        else:
            rows.append([w])
    return [sorted(row, key=lambda w: w["x0"]) for row in rows]


def _activities(found: Carryforwards, n: int, words: list[dict]) -> None:
    """Worksheets 1 and 3 on one page: each row's amounts go to the column whose heading starts left of its end."""
    rows = _rows(words)
    starts = [i for i, row in enumerate(rows) if any(
        w["text"] == "Worksheet" and nxt["text"].isdigit() for w, nxt in pairwise(row))]
    for k, start in enumerate(starts):
        sheet = next(nxt["text"] for w, nxt in pairwise(rows[start]) if w["text"] == "Worksheet")
        if sheet not in ("1", "3"):
            continue
        section = rows[start + 1:starts[k + 1] if k + 1 < len(starts) else len(rows)]
        heads: dict[str, dict] = {}
        for w in (w for r in section for w in r):
            if m := re.match(r"^\(([a-e])\)", w["text"]):
                heads.setdefault(m.group(1), w)
        if set(heads) != set("abcde"):
            found.check(f"Worksheet {sheet}: its five columns' headings are on the page", False, n)
            continue
        left, below = heads["a"]["x0"], max(h["top"] for h in heads.values())
        columns = sorted(heads.items(), key=lambda t: t[1]["x0"])
        total = next((r for r in section if r[0]["text"].startswith("Total")), None)
        totals: dict[str, Decimal] = {}
        sums = dict.fromkeys("abcde", Decimal(0))
        for r in section:
            if r[0]["top"] <= below + 4 or not any(_number(w["text"]) and w["x1"] > left for w in r):
                continue
            got = dict.fromkeys("abcde", Decimal(0))
            for w in r:
                if _number(w["text"]) and w["x1"] > left:
                    column = next((c for c, h in reversed(columns) if h["x0"] < w["x1"] - 2), "a")
                    got[column] += abs(amount(w["text"]))
            if total is not None and total[0]["top"] - 1 <= r[0]["top"] <= total[0]["top"] + 12:
                totals = got  # the totals line, or the row under its label that holds its amounts
                continue
            name = " ".join(w["text"] for w in r if w["x1"] <= left)
            found.activities.append(Activity(sheet, name, got["a"], got["b"], got["c"], got["d"], got["e"], n,
                                             " ".join(w["text"] for w in r)))
            found.check(f"Worksheet {sheet}, {name}: net income less net loss and prior years' unallowed loss is "
                        "the overall gain or loss",
                        abs(got["a"] - got["b"] - got["c"] - (got["d"] - got["e"])) <= CENT, n)
            for c in sums:
                sums[c] += got[c]
        if not totals:
            if any(sums.values()):
                found.check(f"Worksheet {sheet} ends with its total line", False, n)
            continue
        for c, value in totals.items():  # the form's total line takes (a) to (c); some printouts add (d) and (e)
            if (value or sums[c]) and (c in "abc" or totals["d"] or totals["e"]):
                found.check(f"Worksheet {sheet}: the rows' column ({c}) adds up to the total",
                            abs(sums[c] - value) <= CENT, n)


def _worksheet_total(found: Carryforwards, n: int, sheet: str, rows: list, total: list[Decimal], line: str) -> None:
    if sheet == "6":
        for i, what in enumerate(("loss", "unallowed loss", "allowed loss")):
            rows_sum = sum((abs(r[2 + i]) for r in rows), Decimal(0))
            found.check(f"Worksheet 6: the rows' {what} adds up to the total", abs(rows_sum - abs(total[i])) <= CENT, n)
        return
    loss_total, ratio_total, unallowed_total = abs(total[0]), total[1], abs(total[2])
    loss_sum = sum((abs(r[2]) for r in rows), Decimal(0))
    found.check("Worksheet 5: the rows' loss adds up to the total", abs(loss_sum - loss_total) <= CENT, n)
    found.check("Worksheet 5: the rows' unallowed loss adds up to the total",
                abs(sum((abs(r[4]) for r in rows), Decimal(0)) - unallowed_total) <= CENT * max(len(rows), 1), n)
    found.check("Worksheet 5: the ratios add up to 1", abs(sum((r[3] for r in rows), Decimal(0)) - 1) <= RATIO * 10
                and abs(ratio_total - 1) <= RATIO * 10, n)
    for activity, _, loss, ratio, unallowed, _line in rows:
        share = abs(loss) / loss_total if loss_total else Decimal(0)
        found.check(f"Worksheet 5, {activity}: the ratio is its share of the loss", abs(share - ratio) <= RATIO, n)
        found.check(f"Worksheet 5, {activity}: the unallowed loss is its ratio of the total",
                    abs(ratio * unallowed_total - abs(unallowed)) <= CENT, n)


@dataclass
class Year:
    year: int
    depreciation: Decimal
    accumulated: Decimal  # through this year
    last: bool = False  # the basis runs out this year: the table's final-year amount applies, check it


def roll(asset: Asset, start: int, through: int) -> list[Year]:
    """The asset's depreciation for each year after `start` (the year of its return) through `through`.

    Straight-line property takes the same full-year share every year after the first, until the basis is used up:
    what next year's schedule will show, so a missing year's return can be filled in, and checked once it arrives.
    """
    years, accumulated = [], asset.accumulated
    for year in range(start + 1, through + 1):
        take = min(asset.annual, max(asset.basis - accumulated, Decimal(0)))
        accumulated += take
        years.append(Year(year, take, accumulated, last=take < asset.annual))
    return years


def link(returns: list[Carryforwards]) -> list[Check]:
    """Each return's depreciation checked against an earlier one's, rolled forward over the years in between, and
    its foreign tax carryover against the year before's."""
    from . import f1116b

    checks = []
    taxed = sorted((r for r in returns if r.year and r.foreign_tax), key=lambda r: r.year)
    for earlier, later in pairwise(taxed):
        checks += f1116b.link(earlier.foreign_tax, earlier.year, later.foreign_tax, later.year)
    from . import f8995

    filed = sorted((r for r in returns if r.year and r.qbi), key=lambda r: r.year)
    for earlier, later in pairwise(filed):
        checks += f8995.link(earlier.qbi, earlier.year, later.qbi, later.year)
    dated = sorted((r for r in returns if r.year and r.assets), key=lambda r: r.year)
    for earlier, later in pairwise(dated):
        by_asset = {(a.in_service(), a.cost): a for a in earlier.assets if a.in_service()}
        for asset in later.assets:
            if (first := by_asset.get((asset.in_service(), asset.cost))) is None:
                continue
            years = roll(first, earlier.year, later.year - 1)
            expected = years[-1].accumulated if years else first.accumulated
            ok = abs(expected - asset.prior) <= CENT * max(len(years), 1)
            checks.append(Check(f"asset {asset.number}: {earlier.year}'s depreciation rolled forward is "
                                f"{later.year}'s prior depreciation" + ("" if ok else _gap(first, asset, expected)),
                                ok, asset.page))
    return checks


def _gap(earlier: Asset, later: Asset, expected: Decimal) -> str:
    """Why a roll-forward missed, in words that carry no amount: the gap in years of depreciation, what changed."""
    years = (later.prior - expected) / earlier.annual if earlier.annual else Decimal(0)
    changed = [what for what, a, b in (("basis", earlier.basis, later.basis), ("rate", earlier.rate, later.rate),
                                        ("cost", earlier.cost, later.cost)) if a != b]
    return (f" (later's prior is {years:+.2f} years of depreciation from the roll-forward"
            + (f"; the {' and '.join(changed)} changed between the returns" if changed else "") + ")")


def project(found: Carryforwards, through: int) -> list[dict]:
    """Every asset's depreciation rolled from `found`'s year through `through`, for a year whose return is missing."""
    if found.year is None:
        raise ValueError("the return's tax year isn't known, so there is nothing to roll from")
    rows = []
    for asset in found.assets:
        years = roll(asset, found.year, through)
        rows.append({"asset": asset.number, "description": asset.description, "activity": asset.activity,
                     "placed_in_service": str(asset.in_service() or asset.placed_in_service),
                     "basis": str(asset.basis), "annual": str(asset.annual), "method": asset.method,
                     "from": {"file": found.file, "year": found.year, "page": asset.page, "quote": asset.quote,
                              "accumulated": str(asset.accumulated)},
                     "years": [{"year": y.year, "depreciation": str(y.depreciation),
                                "accumulated": str(y.accumulated), "last": y.last} for y in years]})
    return rows


def verify(found: Carryforwards, pages: list[str]) -> list[str]:
    """Every value's quote, checked against its page as the document reads now: the problems, if any."""
    problems = []
    for kind, rows in (("asset", found.assets), ("unallowed loss", found.unallowed)):
        for row in rows:
            if not (1 <= row.page <= len(pages)) or row.quote not in pages[row.page - 1].splitlines():
                problems.append(f"{kind} on page {row.page}: its line isn't on that page")
    for row in found.activities:  # read by position: its words, in the order the page's line has them
        if not (1 <= row.page <= len(pages)) or row.quote not in (
                " ".join(line.split()) for line in pages[row.page - 1].splitlines()):
            problems.append(f"passive activity on page {row.page}: its row isn't on that page")
    return problems
