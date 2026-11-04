"""A year against the one before, the way a preparer looks before signing: what's missing, and what moved.

Documents: every W-2, 1098, 1099 and K-1 from last year should come again, so each one with no match this year is
listed, unless its K-1 said it was the final one. Matching goes by the payer's tax ID, and by the employee on a W-2,
since a name can be printed differently from one year to the next. A foreign account last year should have its
statements this year.

Lines: Form 1040's lines from `agi` and `tax` against last year's filed return, in words: about the same under 10%,
then up or down by 10% to 50% or by more, or new or gone. It never prints an amount; `yoy/<year>.txt` holds them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from decimal import Decimal

from .qbi import faces

ZERO = Decimal(0)
HERE, MISSING, ENDED, NEW = "here", "not here yet", "ended", "new this year"
DOCUMENTS = ("W-2", "1098", "1099-B", "1099-DIV", "1099-G", "1099-INT", "1099-MISC", "1099-NEC", "1099-R")
ABOUT_THE_SAME, LARGE = Decimal("0.10"), Decimal("0.50")
GONE, APPEARED = "gone this year", "new this year"
ALIASES = {"7": ("7", "7a"), "11": ("11", "11a", "11b")}  # the numbers these lines have had on the form


@dataclass
class Document:
    form: str
    name: str
    status: str


@dataclass
class Move:
    line: str
    what: str
    now: Decimal | None
    then: Decimal
    words: str

    @property
    def large(self) -> bool:
        return "more than" in self.words or self.words in (GONE, APPEARED)


@dataclass
class Check:
    year: int
    documents: list[Document] = field(default_factory=list)
    lines: list[Move] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)

    @property
    def missing(self) -> list[Document]:
        return [d for d in self.documents if d.status == MISSING]


def movement(now: Decimal | None, then: Decimal) -> str:
    """How far a line moved, in words; "" when it's nothing in both years."""
    if now is None:
        return "not built yet"
    if not now and not then:
        return ""
    if not then:
        return APPEARED
    if not now:
        return GONE
    change = (now - then) / abs(then)
    if abs(change) < ABOUT_THE_SAME:
        return "about the same"
    return f"{'up' if change > 0 else 'down'} {'more than 50%' if abs(change) >= LARGE else '10% to 50%'}"


def _key(row: dict) -> tuple:
    if row["form"] == "W-2":
        return row["form"], row.get("ein") or row.get("file"), row.get("employee")
    return row["form"], row.get("payer_tin") or row.get("lender_tin") or row.get("file")


def _forms(forms: list[dict], year: int) -> dict[tuple, dict]:
    return {_key(f): f for f in forms
            if f.get("form") in DOCUMENTS and f.get("year") == year and f.get("copy_of") is None}


def _name(row: dict) -> str:
    return row.get("employer") or row.get("lender") or row.get("payer") or row.get("partnership") or row.get("file", "")


def documents(forms: list[dict], k1s: list[dict], year: int) -> list[Document]:
    """Last year's documents against this year's, then what's new."""
    then, now = _forms(forms, year - 1), _forms(forms, year)
    found = [Document(key[0], _name(row), HERE if key in now else MISSING) for key, row in then.items()]
    found += [Document(key[0], _name(row), NEW) for key, row in now.items() if key not in then]
    k1_then = {f.get("ein") or f.get("file"): f for f in faces(k1s, year - 1)}
    k1_now = {f.get("ein") or f.get("file"): f for f in faces(k1s, year)}
    for key, row in k1_then.items():
        status = HERE if key in k1_now else ENDED if row.get("final") else MISSING
        found.append(Document("K-1", _name(row), status))
    found += [Document("K-1", _name(row), NEW) for key, row in k1_now.items() if key not in k1_then]
    return sorted(found, key=lambda d: (d.status != MISSING, d.form, d.name))


def accounts(found_now: dict | None, found_then: dict | None) -> list[Document]:
    """Each foreign account of last year against this year's statements."""
    then = {a.get("account"): a for a in (found_then or {}).get("accounts", [])}
    now = {a.get("account") for a in (found_now or {}).get("accounts", [])}
    return [Document("foreign account", f"{a.get('country', '')} account", HERE if key in now else MISSING)
            for key, a in then.items()]


def _filed(filed: dict[str, Decimal], line: str) -> Decimal:
    return next((filed[n] for n in ALIASES.get(line, (line,)) if n in filed), ZERO)


def lines(built: list[tuple[str, str, Decimal | None]], filed: dict[str, Decimal]) -> list[Move]:
    """Form 1040's built lines, (line, what, amount), against the filed return's."""
    moves = [Move(line, what, now, then := _filed(filed, line), movement(now, then)) for line, what, now in built]
    return [m for m in moves if m.words]


def build(year: int, *, forms: list[dict], k1s: list[dict], built: list[tuple[str, str, Decimal | None]],
          filed: dict[str, Decimal], found_now: dict | None = None, found_then: dict | None = None) -> Check:
    return Check(year, documents(forms, k1s, year) + accounts(found_now, found_then), lines(built, filed))


def to_text(check: Check) -> str:
    out = [f"{check.year} against {check.year - 1}", "", "Documents"]
    out += [f"  {d.status}: {d.form}, {d.name}" for d in check.documents]
    out += ["", "Form 1040's lines"]
    for m in check.lines:
        now = "?" if m.now is None else f"{m.now:,.0f}"
        out.append(f"  {m.line}. {m.what}: {now} against {m.then:,.0f}: {m.words}")
    return "\n".join(out) + "\n"
