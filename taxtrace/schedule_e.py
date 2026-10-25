"""Schedule E, Part I: a rental property's year, from a filed return's Schedule E and this year's documents.

A filed return's Schedule E (a preparer's print, read as layout text) gives the lines to compare against: the
property's address, its type and fair rental days, lines 3 to 20, and line 19's statement of other expenses. `prior`
reads it with the rest of a return's carryforwards.

`build` puts this year's together from what taxtrace has read. Rents and expenses come from the answers to the
preparer's questions (`answers`), the mortgage interest from the property's 1098 (and what its box 10 says the
lender paid from escrow), insurance from its landlord policy's declarations (`policy`), and depreciation from the
depreciation schedule rolled forward (`prior --project`). A document is matched to the property by its address: the
house number and the street's first word. Each line keeps where it came from. A line the filed return had that this
year has nothing for, or what only a person knows (how many months were rented), is a question.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import Decimal

from .answers import Answer
from .policy import Policy
from .prior import CENT, Check, Question, amount

LINES = {
    3: "Rents received", 4: "Royalties received", 5: "Advertising", 6: "Auto and travel",
    7: "Cleaning and maintenance", 8: "Commissions", 9: "Insurance", 10: "Legal and other professional fees",
    11: "Management fees", 12: "Mortgage interest paid to banks, etc.", 13: "Other interest", 14: "Repairs",
    15: "Supplies", 16: "Taxes", 17: "Utilities", 18: "Depreciation expense or depletion", 19: "Other",
    20: "Total expenses",
}
EXPENSES = range(5, 20)
LINE = re.compile(r"^\s*(?P<no>\d{1,2})\s+(?P<label>[A-Z].*?)[\s.]*\s(?P=no)\s+(?P<amount>-?[\d,]*\d\.?)\s*$")
PART_I = "Income or Loss From Rental Real Estate"
ROW_A = re.compile(r"^\s*A\s+(?P<type>\d)\b.*\bA\s+(?P<fair>\d{1,3})(?:\s+(?P<personal>\d{1,3}))?\s*$")
STATEMENT = re.compile(r"Schedule E,\s*Line 19\b")
ITEM = re.compile(r"^\s*(?P<what>[A-Za-z][^.$]*?)[\s.]*\$?\s*(?P<amount>-?[\d,]*\d\.?)\s*$")
PLACE = re.compile(r"\b(\d{2,6})\s*([A-Za-z]+)")
RENT = re.compile(r"\brent", re.IGNORECASE)  # "Rental income", not "Current Annual Premium"
# an answer's words, for the line it goes on: the first that matches wins
WORDS = ((7, ("clean", "maintenance", "lawn", "landscap", "pest")), (14, ("repair",)), (5, ("advertis",)),
         (6, ("auto", "travel", "mileage")), (8, ("commission",)), (9, ("insurance",)),
         (10, ("legal", "professional", "accounting")), (11, ("management", "manager")),
         (12, ("mortgage interest",)), (13, ("interest",)), (15, ("supplies",)), (16, ("tax",)),
         (17, ("utilit", "water", "electric", "sewer", "trash")), (19, ("hoa", "association", "dues")))
ESCROWED = ((16, ("TAX",)), (9, ("INS", "HAZARD")))  # box 10's words, for what the lender paid from escrow


@dataclass
class Line:
    line: int
    amount: Decimal
    source: str  # "filed return", "1098 box 1", "answers", "policy", "projected depreciation"
    file: str
    page: int
    quote: str
    what: str = ""  # an item's own description: line 19's, or an answer's


@dataclass
class Rental:
    address: str
    year: int | None = None
    kind: str = ""  # line 1b's type of property, "1": single family
    fair_rental_days: int | None = None
    personal_use_days: int | None = None
    lines: dict[int, Line] = field(default_factory=dict)
    other: list[Line] = field(default_factory=list)  # line 19's statement
    checks: list[Check] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    def check(self, what: str, ok: bool, page: int = 0, quote: str = "") -> None:
        self.checks.append(Check(what, ok, page, quote))

    def ask(self, question: str, page: int = 0, quote: str = "") -> None:
        self.questions.append(Question(question, page, quote))

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def amount(self, line: int) -> Decimal:
        return self.lines[line].amount if line in self.lines else Decimal(0)

    @property
    def expenses(self) -> Decimal:
        return sum((self.amount(n) for n in EXPENSES), Decimal(0))

    def to_json(self) -> dict:
        def plain(obj):
            if isinstance(obj, Decimal):
                return str(obj)
            if isinstance(obj, dict):
                return {str(k): plain(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [plain(v) for v in obj]
            return obj

        out = plain(asdict(self))
        out["total_expenses"] = str(self.expenses)
        out["income_or_loss"] = str(self.amount(3) + self.amount(4) - self.expenses)
        return out


def filed(name: str, pages: list[str], year: int | None) -> list[Rental]:
    """Property A of each filed Schedule E among a return's pages, with its line 19 statement."""
    found: list[Rental] = []
    for n, page in enumerate(pages, 1):
        if PART_I not in page or "Rents received" not in page:
            continue
        lines = page.splitlines()
        at = next((i for i, ln in enumerate(lines) if "Physical address of each property" in ln), None)
        address = next((ln.strip()[1:].strip() for ln in lines[at + 1:at + 3] if re.match(r"^\s*A\s+\S", ln)), "") \
            if at is not None else ""
        rental = Rental(address=address, year=year)
        for ln in lines:
            if (row := ROW_A.match(ln)) and rental.kind == "":
                rental.kind, rental.fair_rental_days = row.group("type"), int(row.group("fair"))
                rental.personal_use_days = int(row.group("personal")) if row.group("personal") else None
            elif (m := LINE.match(ln)) and int(m.group("no")) in LINES and \
                    m.group("label").startswith(LINES[int(m.group("no"))].split()[0]):
                rental.lines[int(m.group("no"))] = Line(int(m.group("no")), amount(m.group("amount")),
                                                        "filed return", name, n, ln)
        if 20 in rental.lines:
            total = rental.lines.pop(20)
            rental.check("lines 5 to 19 add up to line 20", abs(rental.expenses - total.amount) <= CENT, n,
                         f"{rental.expenses} against {total.quote.strip()}")
        found.append(rental)
    if found:
        _statement(name, found[0], pages)
    return found


def load(row: dict) -> Rental:
    """A Rental as `to_json` saved it."""
    def line(d: dict) -> Line:
        return Line(**{**d, "amount": Decimal(d["amount"])})

    return Rental(row["address"], row.get("year"), row.get("kind", ""), row.get("fair_rental_days"),
                  row.get("personal_use_days"), {int(n): line(d) for n, d in row.get("lines", {}).items()},
                  [line(d) for d in row.get("other", [])], [Check(**c) for c in row.get("checks", [])],
                  [Question(**q) for q in row.get("questions", [])])


def _statement(name: str, rental: Rental, pages: list[str]) -> None:
    for n, page in enumerate(pages, 1):
        lines = page.splitlines()
        if (at := next((i for i, ln in enumerate(lines) if STATEMENT.search(ln)), None)) is None:
            continue
        for ln in lines[at + 1:]:
            if ln.strip().lower().startswith("total"):
                total = sum((o.amount for o in rental.other), Decimal(0))
                rental.check("line 19's statement adds up to line 19", abs(total - rental.amount(19)) <= CENT, n,
                             f"{total} against {ln.strip()}")
                return
            if m := ITEM.match(ln):
                rental.other.append(Line(19, amount(m.group("amount")), "filed return", name, n, ln,
                                         m.group("what").strip()))


def same_place(a: str, b: str) -> bool:
    """Whether two addresses are the same property: the same house number and street, as far as both are printed."""
    ka, kb = PLACE.search(a), PLACE.search(b)
    if not (ka and kb) or ka.group(1) != kb.group(1):
        return False
    wa, wb = ka.group(2).lower(), kb.group(2).lower()
    return wa.startswith(wb) or wb.startswith(wa)  # "MAPLEWOODDRIVE" is "Maplewood" printed without its space


def _line(answer: Answer) -> int | None:
    what = answer.what.lower()
    if RENT.search(what) and not any(w in what for w in ("expense", "cost", "paid")):
        return 3
    return next((n for n, words in WORDS if any(w in what for w in words)), None)


def build(year: int, *, last: Rental | None, answers: list[Answer], forms: list[dict], policies: list[Policy],
          projected: dict | None, address: str = "") -> Rental:
    """This year's Schedule E for one property, from what's been read; `last` is the latest filed one."""
    place = address or (last.address if last else "")
    rental = Rental(address=place, year=year)
    if not place:
        rental.ask("which property: no filed Schedule E has been read (`taxtrace prior`) to give its address")
    if last:
        rental.kind = last.kind
        rental.ask(f"line 2: {last.year}'s return had {last.fair_rental_days or 'no'} fair rental days and "
                   f"{last.personal_use_days or 'no'} personal use days: the same for {year}?")
    for a in answers:
        if not (RENT.search(a.section) or RENT.search(a.what)):
            continue
        if (n := _line(a)) is None:
            rental.ask(f"an answer under {a.section or 'no heading'} that isn't a Schedule E line by its words: "
                       "which line is it?", a.page, a.quote)
            continue
        if n in rental.lines:  # two answers for one line (repairs, and more repairs) add up
            rental.lines[n].amount += a.yearly
        else:
            rental.lines[n] = Line(n, a.yearly, "answers", a.file, a.page, a.quote, a.what)
        if n == 3 and a.per == "month":
            rental.ask(f"line 3 is 12 months at the monthly rent: if the property was empty for a while or the rent "
                       f"changed in {year}, the rent actually received", a.page, a.quote)
        elif a.per == "":
            rental.ask(f"line {n}: the answer doesn't say whether it's a year's or a month's: taken as the year's",
                       a.page, a.quote)
    _mortgage(rental, year, forms)
    _insurance(rental, year, policies)
    _depreciation(rental, year, projected)
    if last:
        for n, old in last.lines.items():
            if n in EXPENSES and old.amount and n not in rental.lines:
                what = f" ({', '.join(o.what for o in last.other)})" if n == 19 and last.other else ""
                rental.ask(f"line {n}, {LINES[n].lower()}{what}: {last.year}'s return had an amount, and nothing for "
                           f"{year} has been found")
    return rental


def _mortgage(rental: Rental, year: int, forms: list[dict]) -> None:
    mine = [f for f in forms if f.get("form") == "1098" and f.get("copy_of") is None and f.get("year") == year
            and same_place(f.get("address", ""), rental.address)]
    if not mine:
        rental.ask(f"line 12: no {year} Form 1098 with this property's address has been read (`taxtrace 1098`)")
        return
    if 12 in rental.lines:
        rental.ask("line 12: an answer gives mortgage interest too; the 1098's is taken", quote=rental.lines[12].quote)
    interest = [(f, f["amounts"]["1"]) for f in mine if "1" in f["amounts"]]
    if interest:
        f, v = interest[0]
        rental.lines[12] = Line(12, sum((Decimal(v["amount"]) for _, v in interest), Decimal(0)), "1098 box 1",
                                f["file"], v["page"], v["quote"])
    for f in mine:
        if "10" not in f["amounts"]:
            continue
        v, words = f["amounts"]["10"], f.get("other", "").upper()
        n = next((n for n, keys in ESCROWED if any(k in words for k in keys)), None)
        if n is None:
            rental.ask("box 10 of the property's 1098: its description doesn't say taxes or insurance: which is it?",
                       v["page"], f.get("other", ""))
        elif n in rental.lines:
            rental.ask(f"line {n}: the 1098's box 10 and an answer both give it; the 1098's is taken",
                       v["page"], rental.lines[n].quote)
            rental.lines[n] = Line(n, Decimal(v["amount"]), "1098 box 10", f["file"], v["page"], v["quote"])
        else:
            rental.lines[n] = Line(n, Decimal(v["amount"]), "1098 box 10", f["file"], v["page"], v["quote"])


def _insurance(rental: Rental, year: int, policies: list[Policy]) -> None:
    mine = [p for p in policies if p.kind == "landlord" and same_place(p.location, rental.address)]
    if not mine:
        if 9 not in rental.lines:
            rental.ask("line 9: no landlord policy's declarations with this property's address have been read")
        return
    if 9 in rental.lines and rental.lines[9].source == "1098 box 10":
        rental.ask("line 9: the 1098's box 10 already has the insurance paid from escrow, so the policy's premium "
                   "isn't added again", mine[0].page, mine[0].quote)
        return
    p = mine[0]
    rental.lines[9] = Line(9, p.premium, "policy", p.file, p.page, p.quote)
    if p.new_since.endswith(str(year)):
        rental.ask(f"line 9: a new policy from {p.new_since}: if another policy covered the property earlier in "
                   f"{year}, what was paid for it in {year} is an expense too", p.page)


def _depreciation(rental: Rental, year: int, projected: dict | None) -> None:
    if not projected:
        rental.ask(f"line 18: no depreciation rolled forward to {year} (`taxtrace prior --project {year}`)")
        return
    assets = projected.get("assets", [])
    mine = [a for a in assets if same_place(a.get("activity", ""), rental.address)] or \
        (assets if len({a.get("activity") for a in assets}) == 1 else [])
    rows = [(a, y) for a in mine for y in a.get("years", []) if y["year"] == year]
    if not rows:
        rental.ask(f"line 18: no asset of this property's has a {year} year in the rolled-forward schedule")
        return
    a, _ = rows[0]
    rental.lines[18] = Line(18, sum((Decimal(y["depreciation"]) for _, y in rows), Decimal(0)),
                            "projected depreciation", a["from"]["file"], a["from"]["page"], a["from"]["quote"])
    rental.ask(f"line 18 is rolled forward from the {a['from']['year']} depreciation schedule: check it against the "
               f"{year - 1} return's when it arrives")
    if any(y.get("last") for _, y in rows):
        rental.ask(f"line 18: an asset's basis runs out in {year}, so its last year is smaller")
