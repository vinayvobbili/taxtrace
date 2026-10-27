"""Each passive activity's year: what it earned or lost, and the loss it carries in from earlier years.

Form 8582 limits passive losses, and what it doesn't allow carries to the next year activity by activity. So a
year starts from the latest return's worksheets (`prior`: every activity on Worksheets 1 and 3, and the unallowed
loss each carries on, from Worksheet 5), and goes on with this year's K-1s (`k1`). Each activity is matched to its
partnership's K-1 by name, the way the preparer's worksheet spelled it; a K-1 no activity matches is a new one.

Nothing is settled silently: an activity with no K-1 this year (sold, ended, or missing from the folder), a gap
between the latest return and this year (the years between changed what each activity carries), a box whose place
in the activity isn't certain, and the rental, whose year comes from Schedule E, are questions or notes.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from . import f8582
from .prior import Question

# a K-1's passive income (loss): the business, the rental real estate and other rentals, and section 1231 gain
PASSIVE = ("1", "2", "3", "10")
LESS = ("12",)  # section 179, taken against the activity's income
# box 13 codes that aren't the activity's: portfolio deductions, and business interest the partner carries on
NOT_THE_ACTIVITYS = {"AE", "L", "K"}
COMMON = {"LLC", "LP", "L", "P", "INC", "THE", "OF", "AND", "CO", "LTD", "LLLP", "GP", "PARTNERSHIP", "PARTNERS"}
MATCH = 0.5  # share of the shorter name's words the two names have to share
RENTAL = re.compile(r"\bRENTAL\b", re.IGNORECASE)


@dataclass
class Line:
    """One activity's year."""

    activity: str  # as the latest return's worksheet names it, or as its K-1 does for a new one
    source: str = ""  # "k1", "schedule e", or "merged" (into another activity, in an earlier year)
    current: Decimal | None = None  # this year's net income (positive) or loss (negative); None: not known yet
    carried: Decimal | None = None  # the unallowed loss it brings in; None: the year before's return isn't in hand
    carried_from: int | None = None  # the return whose Worksheet 5 gave it
    final: bool = False  # its K-1 is a final one: a full disposition frees what it carries
    ein: str = ""
    k1_file: str = ""
    k1_page: int | None = None
    worksheet: str = ""  # "1" or "3" on the latest return; "" for a new activity
    left_out: list[str] = field(default_factory=list)  # K-1 boxes with amounts that aren't the activity's
    merged_into: str = ""  # the activity whose K-1 it now shares (its year is counted there, once)


@dataclass
class Ledger:
    year: int
    latest: int | None = None  # the latest return before `year` with Form 8582's worksheets
    lines: list[Line] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    def ask(self, text: str, quote: str = "") -> None:
        self.questions.append(Question(text, 0, quote))

    def to_json(self) -> dict:
        def plain(obj):
            if isinstance(obj, Decimal):
                return str(obj)
            if isinstance(obj, dict):
                return {k: plain(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [plain(v) for v in obj]
            return obj

        return plain(asdict(self))


def words(name: str) -> set[str]:
    """A name's distinctive words: "Larkspur Ridge Fund, LLC" is {"LARKSPUR", "RIDGE", "FUND"}."""
    return {w for w in re.findall(r"[A-Z0-9]+", name.upper()) if w not in COMMON}


def similar(a: str, b: str) -> float:
    one, two = words(a), words(b)
    return len(one & two) / min(len(one), len(two)) if one and two else 0.0


def passive_amount(items: list[dict]) -> tuple[Decimal, list[str]]:
    """A K-1's passive income (loss) from its boxes (`k1` JSON items), and the boxes with amounts it leaves out."""
    total, left_out = Decimal(0), []
    for item in items:
        value = item["value"]["amount"]
        if value is None:
            continue
        box, code = item["box"], item["code"]
        if box in PASSIVE:
            total += Decimal(value)
        elif box in LESS:
            total -= abs(Decimal(value))
        else:
            left_out.append(box + (f" {code}" if code else ""))
    return total, left_out


def build(year: int, returns: list[dict], k1s: list[dict], previous: dict | None = None) -> Ledger:
    """The ledger for `year` from the saved carryforwards (`prior` JSON) and K-1s (`k1` JSON, federal faces).

    What each activity carries in comes from last year's return: its Worksheet 5, or, when its copy has no Form 8582
    worksheets, its Carryover Worksheet's Passive Activity section printed empty (nothing carries in). Without
    either, last year's ledger (`previous`, as this function saved it) gives the activities, and its worked-out Form
    8582 what each carries in."""
    ledger = Ledger(year)
    earlier = [r for r in returns if r.get("year") and r["year"] < year and (r.get("activities") or r.get("unallowed"))]
    latest = max(earlier, key=lambda r: r["year"], default=None)
    faces = [f for f in k1s if "form" not in f and f.get("year") == year and f.get("copy_of") is None
             and not f.get("retirement_plan")]
    if previous is not None and previous.get("year") != year - 1:
        previous = None
    if latest is not None and latest["year"] == year - 1:
        previous = None  # last year's own worksheets are better than a ledger built before they were read
    if latest is None and previous is None:
        ledger.ask(f"no return before {year} with Form 8582's worksheets has been read: run `taxtrace prior` on last "
                   "year's return, and each activity's carried loss comes from it")
    if latest is not None:
        ledger.latest = latest["year"]
    if previous is not None:  # every activity still going last year, as last year's ledger has it
        for p in previous.get("lines", []):
            if not p.get("final"):
                ledger.lines.append(Line(p["activity"], worksheet=p.get("worksheet", ""),
                                         merged_into=p.get("merged_into", "")))
    elif latest is not None:
        names = [a["activity"] for a in latest.get("activities", [])]
        names += [u["activity"] for u in latest.get("unallowed", [])
                  if u["activity"] not in names]  # a Worksheet 5 row whose Worksheet 3 row wasn't read
        sheet = {a["activity"]: a["worksheet"] for a in latest.get("activities", [])}
        ledger.lines = [Line(name, worksheet=sheet.get(name, "")) for name in names]
    _carried_in(ledger, latest, previous, returns)
    taken: dict[int, Line] = {}
    for line in ledger.lines:
        if line.merged_into:  # merged in an earlier year: its year is counted with the one it merged into
            line.source = "merged"
            continue
        scores = sorted(((similar(line.activity, f.get("partnership", "")), i) for i, f in enumerate(faces)
                         if i not in taken), reverse=True)
        if scores and scores[0][0] >= MATCH:
            if len(scores) > 1 and scores[1][0] == scores[0][0]:
                ledger.ask("an activity's name matches two K-1s equally: which is it?", line.activity)
                continue
            taken[scores[0][1]] = line
            _from_k1(line, faces[scores[0][1]])
        elif (shared := next((i for i, f in enumerate(faces)
                              if i in taken and similar(line.activity, f.get("partnership", "")) >= MATCH),
                             None)) is not None:
            # two of the latest return's activities, one K-1 now: a fund merged into another
            survivor = taken[shared]
            line.source, line.merged_into = "k1", survivor.activity
            line.ein, line.k1_file, line.k1_page = survivor.ein, survivor.k1_file, survivor.k1_page
            ledger.ask(f"this activity's name matches the same {year} K-1 as another activity's: likely merged into "
                       "it, and a merger isn't a disposition, so the loss it carries goes on with the surviving "
                       "activity instead of being freed", line.activity)
        elif RENTAL.search(line.activity):
            line.source = "schedule e"
        else:
            ledger.ask(f"no {year} K-1 matches this activity: was it sold or did it end (a full disposition frees "
                       "the loss it carries), or is its K-1 missing from the folder?", line.activity)
    for i, f in enumerate(faces):
        if i not in taken:
            line = Line(f.get("partnership", ""))
            _from_k1(line, f)
            ledger.lines.append(line)
    for line in ledger.lines:
        for box in line.left_out:
            if box.startswith("13 ") and box.split()[1] not in NOT_THE_ACTIVITYS:
                ledger.ask(f"box {box}: whether this deduction is part of the passive activity's loss isn't settled "
                           "by its code", line.activity)
    return ledger


def _carried_in(ledger: Ledger, latest: dict | None, previous: dict | None, returns: list[dict]) -> None:
    """Each line's carried loss and the return (or ledger) it comes from, or the question of where it would."""
    year = ledger.year
    if latest is not None and latest["year"] == year - 1:
        carried = {u["activity"]: Decimal(u["unallowed"]) for u in latest.get("unallowed", [])}
        for line in ledger.lines:
            line.carried, line.carried_from = carried.get(line.activity, Decimal(0)), year - 1
        return
    last = next((r for r in returns if r.get("year") == year - 1 and r.get("carryover_sections")), None)
    listed = last is not None and any("under Passive Activity" in q["text"] for q in last.get("questions", []))
    if last is not None and "Passive Activity" in last["carryover_sections"] and not listed:
        for line in ledger.lines:
            line.carried, line.carried_from = Decimal(0), year - 1
        ledger.ask(f"the {year - 1} return's Carryover Worksheet prints its Passive Activity section empty, so no "
                   f"activity carries a loss into {year}: its Form 8582 Worksheet 5 would confirm it")
        return
    form = (previous or {}).get("form_8582")
    if form:
        unallowed = {a["name"]: Decimal(a["unallowed"]) for a in form.get("activities", [])}
        for line in ledger.lines:  # a merged activity's loss went on with the one it merged into
            line.carried, line.carried_from = unallowed.get(line.activity, Decimal(0)), year - 1
        ledger.ask(f"what each activity carries into {year} is taxtrace's own {year - 1} Form 8582, not a filed one: "
                   f"the {year - 1} return's Worksheet 5 would confirm it")
        return
    since = latest["year"] if latest else None
    if since is not None or previous is not None:
        ledger.ask(f"what each activity carries into {year} comes from the {year - 1} return's Form 8582 Worksheet 5"
                   + (f" (the latest read is {since}'s, and the years between changed it)" if since else "")
                   + ", or its Carryover Worksheet: neither is read yet")


def confirmation(spec: str) -> tuple[str, object]:
    """'magi=180000' (Decimal, as a string to keep), or 'lived_apart=yes' (bool)."""
    key, sep, value = (s.strip() for s in spec.partition("="))
    key = key.lower()
    try:
        if sep and key == "magi":
            return key, str(Decimal(value.replace(",", "")))
        if sep and key == "lived_apart" and value.lower() in ("yes", "no"):
            return key, value.lower() == "yes"
    except ArithmeticError:
        pass
    raise ValueError("--confirm takes magi=AMOUNT or lived_apart=yes|no")


def for_8582(ledger: Ledger, rental: Decimal | None) -> tuple[list[f8582.Activity], list[str]]:
    """The ledger's activities as Form 8582 takes them, and the names of those whose year or carried loss isn't
    known yet (the form waits for them). The rental's year is Schedule E's net (`rental`); a merged activity's
    carried loss goes on with the one it merged into; an activity new this year is in Part V, since a partnership
    interest's rental isn't one the partner actively participates in."""
    for line in ledger.lines:
        if line.source == "schedule e":
            line.current = rental
    carried = {line.activity: line.carried for line in ledger.lines}
    for line in ledger.lines:
        if line.merged_into and line.carried is not None and carried.get(line.merged_into) is not None:
            carried[line.merged_into] += line.carried
    missing = [line.activity for line in ledger.lines
               if (line.current is None and not line.merged_into) or line.carried is None]
    if missing:
        return [], missing
    return [f8582.Activity(line.activity, "IV" if line.worksheet == "1" else "V", line.current,
                           carried[line.activity], line.final)
            for line in ledger.lines if not line.merged_into], []


def _from_k1(line: Line, face: dict) -> None:
    line.source, line.ein, line.k1_file, line.k1_page = "k1", face.get("ein", ""), face["file"], face["page"]
    line.current, line.left_out = passive_amount(face.get("items", []))
    line.final = bool(face.get("final"))
