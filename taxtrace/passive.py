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
    source: str = ""  # "k1" or "schedule e"
    current: Decimal | None = None  # this year's net income (positive) or loss (negative); None: not known yet
    carried: Decimal | None = None  # the unallowed loss it brings in; None: the year before's return isn't in hand
    carried_from: int | None = None  # the return whose Worksheet 5 gave it
    final: bool = False  # its K-1 is a final one: a full disposition frees what it carries
    ein: str = ""
    k1_file: str = ""
    k1_page: int | None = None
    worksheet: str = ""  # "1" or "3" on the latest return; "" for a new activity
    left_out: list[str] = field(default_factory=list)  # K-1 boxes with amounts that aren't the activity's


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


def build(year: int, returns: list[dict], k1s: list[dict]) -> Ledger:
    """The ledger for `year` from the saved carryforwards (`prior` JSON) and K-1s (`k1` JSON, federal faces)."""
    ledger = Ledger(year)
    earlier = [r for r in returns if r.get("year") and r["year"] < year and (r.get("activities") or r.get("unallowed"))]
    latest = max(earlier, key=lambda r: r["year"], default=None)
    faces = [f for f in k1s if "form" not in f and f.get("year") == year and f.get("copy_of") is None
             and not f.get("retirement_plan")]
    if latest is None:
        ledger.ask(f"no return before {year} with Form 8582's worksheets has been read: run `taxtrace prior` on last "
                   "year's return, and each activity's carried loss comes from it")
    else:
        ledger.latest = latest["year"]
        if latest["year"] < year - 1:
            ledger.ask(f"the latest return with Form 8582 is {latest['year']}'s: the {latest['year'] + 1} to "
                       f"{year - 1} returns changed what each activity carries, so the losses carried into {year} "
                       f"come from the {year - 1} return's Worksheet 5")
        carried = {u["activity"]: Decimal(u["unallowed"]) for u in latest.get("unallowed", [])}
        names = [a["activity"] for a in latest.get("activities", [])]
        names += [n for n in carried if n not in names]  # a Worksheet 5 row whose Worksheet 3 row wasn't read
        sheet = {a["activity"]: a["worksheet"] for a in latest.get("activities", [])}
        for name in names:
            line = Line(name, worksheet=sheet.get(name, ""), carried_from=latest["year"])
            if latest["year"] == year - 1:
                line.carried = carried.get(name, Decimal(0))
            ledger.lines.append(line)
    taken: set[int] = set()
    for line in ledger.lines:
        scores = sorted(((similar(line.activity, f.get("partnership", "")), i) for i, f in enumerate(faces)
                         if i not in taken), reverse=True)
        if scores and scores[0][0] >= MATCH:
            if len(scores) > 1 and scores[1][0] == scores[0][0]:
                ledger.ask("an activity's name matches two K-1s equally: which is it?", line.activity)
                continue
            taken.add(scores[0][1])
            _from_k1(line, faces[scores[0][1]])
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


def _from_k1(line: Line, face: dict) -> None:
    line.source, line.ein, line.k1_file, line.k1_page = "k1", face.get("ein", ""), face["file"], face["page"]
    line.current, line.left_out = passive_amount(face.get("items", []))
    line.final = bool(face.get("final"))
