"""A bank's statement of account (an Indian bank's, as its branch prints it): each transaction, read by where it sits.

A foreign account's statement gives what the US return needs from the account: the interest credited in the
calendar year (Schedule B, and the income Form 1116 credits tax against), the highest balance and the balance on
December 31 (Form 8938 and the FBAR), and a tax refund arriving from India's income tax department.

The statement is a table: a date, then the amount under "Withdrawal" or "Deposit", then the balance with "Cr." (or
"Dr."), then a description that can run onto the next lines. An amount belongs to the column it starts in (the header
words' left edges). Interest rows say the period they pay for ("From :01-04-2025 to 30-06-2025"). India's statements
run on its financial year (April to March), so one rarely covers a calendar year: what it covers is kept, and the
foreign side asks for the rest.

Checks: each balance is the one before plus the deposit or less the withdrawal, and the withdrawals and deposits add
up to the statement's grand totals. Nothing that names the holders is kept, and of the account number only its last
four digits.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal

from .prior import Check, Question, _rows

DAY = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")  # dd-mm-yyyy
MONEY = re.compile(r"^\d+\.\d{1,2}$")
PERIOD = re.compile(r"Statement for Period\s*:\s*(\d{2}-\d{2}-\d{4})\s+to\s+(\d{2}-\d{2}-\d{4})")
ACCOUNT = re.compile(r"Statement of Account No\s*:\s*(\d+)")
CURRENCY = re.compile(r"Acct Currency\s*:\s*([A-Z]{3})")
INTEREST = re.compile(r"From\s*:\s*\d{2}-\d{2}-\d{4}\s+to\s+\d{2}-\d{2}-\d{4}|\bINT(?:EREST)?\b", re.IGNORECASE)
REFUND = re.compile(r"\bREFUND\b", re.IGNORECASE)
TDS = re.compile(r"\bTDS\b", re.IGNORECASE)
FOOTER = re.compile(r"^(Page Total|Grand|Page\s+\S+\s+of)")
COLUMNS = ("Withdrawal", "Deposit", "Balance")
CENT = Decimal("0.01")
TOTAL_SLACK = Decimal("0.1")  # the grand totals print with one decimal place


def day(printed: str) -> date:
    d, m, y = DAY.match(printed).groups()
    return date(int(y), int(m), int(d))


@dataclass
class Row:
    on: str  # dd-mm-yyyy, as printed
    withdrawal: Decimal
    deposit: Decimal
    balance: Decimal  # negative when printed "Dr."
    description: str
    kind: str  # "interest", "tax refund", "tds" (withheld on interest), "tds refund" or ""
    page: int
    quote: str


@dataclass
class Statement:
    file: str
    account: str = ""  # the last four digits
    currency: str = ""
    start: str = ""  # the period, dd-mm-yyyy as printed
    end: str = ""
    rows: list[Row] = field(default_factory=list)
    totals: tuple[Decimal, Decimal] | None = None  # the grand totals: withdrawals, deposits
    checks: list[Check] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    @property
    def failed(self) -> list[Check]:
        return [c for c in self.checks if not c.ok]

    def check(self, what: str, ok: bool, page: int, quote: str = "") -> None:
        self.checks.append(Check(what, ok, page, quote))

    def to_json(self) -> dict:
        return {"form": "BANK", **asdict(self)}


def is_statement(page: str) -> bool:
    flat = " ".join(page.split())
    return "Statement of Account" in flat and all(c in flat for c in COLUMNS)


def read(name: str, pages: list[str], words: dict[int, list[dict]]) -> Statement:
    found = Statement(name)
    flat = " ".join(" ".join(pages).split())
    if m := ACCOUNT.search(flat):
        found.account = m.group(1)[-4:]
    if m := CURRENCY.search(flat):
        found.currency = m.group(1)
    if m := PERIOD.search(flat):
        found.start, found.end = m.groups()
    for n in sorted(words):
        _page(found, n, words[n])
    _checks(found)
    return found


def _page(found: Statement, n: int, words: list[dict]) -> None:
    rows = _rows(words)
    header = next((r for r in rows if all(any(w["text"] == c for w in r) for c in COLUMNS)), None)
    if header is None:
        return
    edges = {c: next(w["x0"] for w in header if w["text"] == c) for c in COLUMNS}
    after = min((w["x0"] for w in header if w["x0"] > edges["Balance"] + 30), default=edges["Balance"] + 50)
    dated: list[tuple[float, Row]] = []
    lines: list[tuple[float, str]] = []  # description lines, each to go with the dated row nearest it
    for row in rows[rows.index(header) + 1:]:
        text = " ".join(w["text"] for w in row)
        if FOOTER.match(text) or FOOTER.match(" ".join(w["text"] for w in row if w["x0"] >= after)):
            if text.startswith("Grand"):
                amounts = [w["text"] for w in row if re.fullmatch(r"\d+(\.\d+)?", w["text"])]
                if len(amounts) >= 2:
                    found.totals = (Decimal(amounts[0]), Decimal(amounts[1]))
            continue
        if DAY.match(row[0]["text"]) and row[0]["x0"] < edges["Withdrawal"]:
            out = dep = Decimal(0)
            balance, sign = None, 1
            for w in row[1:]:
                if MONEY.match(w["text"]):
                    value = Decimal(w["text"])
                    if w["x0"] >= edges["Balance"]:
                        balance = value
                    elif w["x0"] >= edges["Deposit"]:
                        dep = value
                    else:
                        out = value
                elif w["text"] in ("Dr.", "Dr"):
                    sign = -1
            if balance is None:
                continue
            dated.append((row[0]["top"], Row(row[0]["text"], out, dep, sign * balance, "", "", n, text)))
            if own := " ".join(w["text"] for w in row if w["x0"] >= after):
                lines.append((row[0]["top"], own))
        elif row[0]["x0"] >= after - 5:
            lines.append((row[0]["top"], text))
    # A description of several lines is centred on its row, so its first line sits above the row's date: each line
    # goes with the dated row nearest it, in order from the top.
    parts: dict[int, list[str]] = {}
    for top, line in lines:
        if dated:
            nearest = min(range(len(dated)), key=lambda i: (abs(dated[i][0] - top), -i))
            parts.setdefault(nearest, []).append(line)
    for i, (_, r) in enumerate(dated):
        r.description = " ".join(parts.get(i, []))
        found.rows.append(r)
    for r in found.rows:
        r.kind = ("tds" if TDS.search(r.description) and r.withdrawal else
                  "tds refund" if TDS.search(r.description) and r.deposit else
                  "interest" if INTEREST.search(r.description) and r.deposit else
                  "tax refund" if REFUND.search(r.description) and r.deposit else "")


def _checks(found: Statement) -> None:
    if not found.rows:
        found.questions.append(Question("no transactions were read: is this a statement of account?", 1, ""))
        return
    for before, row in zip(found.rows, found.rows[1:], strict=False):
        found.check(f"the balance on {row.on} follows from the one before",
                    abs(before.balance + row.deposit - row.withdrawal - row.balance) < CENT, row.page, row.quote)
    if found.totals is not None:
        out = sum((r.withdrawal for r in found.rows), Decimal(0))
        dep = sum((r.deposit for r in found.rows), Decimal(0))
        found.check("withdrawals and deposits add up to the grand totals",
                    abs(out - found.totals[0]) <= TOTAL_SLACK and abs(dep - found.totals[1]) <= TOTAL_SLACK,
                    found.rows[-1].page)
    if found.currency and found.currency != "INR":
        found.questions.append(Question(f"the account is in {found.currency}, not rupees", 1, ""))
