"""A bank's statement of account (an Indian bank's, as its branch prints it): each transaction, read by where it sits.

A foreign account's statement gives what the US return needs from the account: the interest credited in the
calendar year (Schedule B, and the income Form 1116 credits tax against), the highest balance and the balance on
December 31 (Form 8938 and the FBAR), and a tax refund arriving from India's income tax department.

The statement is a table: a date, then the amount under "Withdrawal" or "Deposit", then the balance with "Cr." (or
"Dr."), then a description that can run onto the next lines. An amount belongs to the column it starts in (the header
words' left edges). Interest rows say the period they pay for ("From :01-04-2025 to 30-06-2025"). India's statements
run on its financial year (April to March), so one rarely covers a calendar year: what it covers is kept, and the
foreign side asks for the rest.

The other layout read is a monthly "Account Statement": a row number, the date as "01 Jan 2026", the description
(under a "Description" header, left of the amounts), amounts with Indian commas ("1,23,456.78"), an "Opening Balance"
row and an "Account Summary" of the opening and closing balances. Its quarterly interest row is credited net of the
TDS ("Int:1234.56 and TAX:123.45"): it is read as the two rows other statements print, the interest, then the TDS
withheld from it.

Checks: each balance is the one before plus the deposit or less the withdrawal, and the withdrawals and deposits add
up to the statement's grand totals (or the balances match its account summary). Nothing that names the holders is
kept, and of the account number only its last four digits.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from decimal import Decimal

from .prior import Check, Question, _rows

DAY = re.compile(r"^(\d{2})-(\d{2})-(\d{4})$")  # dd-mm-yyyy
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
MONEY = re.compile(r"^(\d{1,3}(,\d{2,3})+|\d+)\.\d{1,2}$")  # 102410.00, or with Indian commas: 1,02,410.00
AMOUNT = r"(\d{1,3}(?:,\d{2,3})+\.\d{2}|\d+\.\d{2})"
WORD_DAY = r"(\d{1,2} (?:" + "|".join(MONTHS) + r") \d{4})"
PERIOD = re.compile(r"Statement for Period\s*:\s*(\d{2}-\d{2}-\d{4})\s+to\s+(\d{2}-\d{2}-\d{4})"
                    rf"|Account Statement\s*{WORD_DAY}\s*-\s*{WORD_DAY}")
ACCOUNT = re.compile(r"Account No\.?\s*:?\s*(\d+)")
CURRENCY = re.compile(r"Currency\s*:?\s*((?i:indian rupees?)|[A-Z]{3})\b")
SUMMARY = re.compile(rf"Savings Account \(SA\):\s*{AMOUNT}\s+{AMOUNT}")  # its opening, then closing, balance
INTEREST = re.compile(r"From\s*:\s*\d{2}-\d{2}-\d{4}\s+to\s+\d{2}-\d{2}-\d{4}|\bINT(?:EREST)?\b", re.IGNORECASE)
NET_INTEREST = re.compile(rf"\bInt:{AMOUNT}\s+and\s+TAX:{AMOUNT}")
REFUND = re.compile(r"\bREFUND\b", re.IGNORECASE)
TDS = re.compile(r"\bTDS\b", re.IGNORECASE)
FOOTER = re.compile(r"^(Page Total|Grand|Page\s+\S+\s+of|Statement Generated)")
COLUMNS = ("Withdrawal", "Deposit", "Balance")
CENT = Decimal("0.01")
TOTAL_SLACK = Decimal("0.1")  # the grand totals print with one decimal place


def day(printed: str) -> date:
    d, m, y = DAY.match(printed).groups()
    return date(int(y), int(m), int(d))


def money(printed: str) -> Decimal:
    return Decimal(printed.replace(",", ""))


def _numeric(printed: str) -> str:
    """'01 Jan 2026' as '01-01-2026', the dd-mm-yyyy the rest of taxtrace reads."""
    d, m, y = printed.split()
    return f"{int(d):02d}-{MONTHS.index(m) + 1:02d}-{y}"


@dataclass
class Row:
    on: str  # dd-mm-yyyy, as printed (a "01 Jan 2026" rewritten so)
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
    start: str = ""  # the period, dd-mm-yyyy
    end: str = ""
    opening: Decimal | None = None  # the "Opening Balance" row's, when it prints one
    rows: list[Row] = field(default_factory=list)
    totals: tuple[Decimal, Decimal] | None = None  # the grand totals: withdrawals, deposits
    summary: tuple[Decimal, Decimal] | None = None  # the account summary: opening and closing balances
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
    return ("Statement of Account" in flat or "Account Statement" in flat) and all(c in flat for c in COLUMNS)


def read(name: str, pages: list[str], words: dict[int, list[dict]]) -> Statement:
    found = Statement(name)
    flat = " ".join(" ".join(pages).split())
    if m := ACCOUNT.search(flat):
        found.account = m.group(1)[-4:]
    if m := CURRENCY.search(flat):
        found.currency = "INR" if m.group(1).lower().startswith("indian rupee") else m.group(1)
    if m := PERIOD.search(flat):
        start, end, word_start, word_end = m.groups()
        found.start, found.end = (start, end) if start else (_numeric(word_start), _numeric(word_end))
    if m := SUMMARY.search(flat):
        found.summary = (money(m.group(1)), money(m.group(2)))
    for n in sorted(words):
        _page(found, n, words[n])
    _checks(found)
    return found


def _dated(row: list[dict]) -> tuple[str, int] | None:
    """The row's date, dd-mm-yyyy, and how many words it and a row number before it take; None if it has none."""
    texts = [w["text"] for w in row[:4]]
    for i in (0, 1):  # after a row number, or not
        if i and not texts[0].isdigit():
            break
        if len(texts) > i and DAY.match(texts[i]):
            return texts[i], i + 1
        if len(texts) > i + 2 and re.fullmatch(WORD_DAY, " ".join(texts[i:i + 3])):
            return _numeric(" ".join(texts[i:i + 3])), i + 3
    return None


def _page(found: Statement, n: int, words: list[dict]) -> None:
    rows = _rows(words)
    header = next((r for r in rows if all(any(w["text"] == c for w in r) for c in COLUMNS)), None)
    if header is None:
        return
    edges = {c: next(w["x0"] for w in header if w["text"] == c) for c in COLUMNS}
    # where descriptions sit: under "Description", left of the amounts, or after the balance
    described = next((w["x0"] for w in header if w["text"] == "Description" and w["x0"] < edges["Withdrawal"]), None)
    if described is not None:
        span = (described - 10, edges["Withdrawal"])
    else:
        span = (min((w["x0"] for w in header if w["x0"] > edges["Balance"] + 30), default=edges["Balance"] + 50),
                float("inf"))

    def describes(w: dict) -> bool:
        return span[0] <= w["x0"] < span[1]

    dated: list[tuple[float, Row]] = []
    lines: list[tuple[float, str]] = []  # description lines, each to go with the dated row nearest it
    for row in rows[rows.index(header) + 1:]:
        text = " ".join(w["text"] for w in row)
        if FOOTER.match(text) or FOOTER.match(" ".join(w["text"] for w in row if describes(w))):
            if text.startswith("Grand"):
                amounts = [w["text"] for w in row if re.fullmatch(r"\d+(\.\d+)?", w["text"])]
                if len(amounts) >= 2:
                    found.totals = (Decimal(amounts[0]), Decimal(amounts[1]))
            continue
        if "Opening Balance" in text and (amounts := [w["text"] for w in row if MONEY.match(w["text"])]):
            found.opening = money(amounts[-1])
            continue
        if (on := _dated(row)) and row[0]["x0"] < edges["Withdrawal"]:
            printed, taken = on
            out = dep = Decimal(0)
            balance, sign = None, 1
            for w in row[taken:]:
                if describes(w):
                    continue
                if MONEY.match(w["text"]):
                    value = money(w["text"])
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
            dated.append((row[0]["top"], Row(printed, out, dep, sign * balance, "", "", n, text)))
            if own := " ".join(w["text"] for w in row[taken:] if describes(w)):
                lines.append((row[0]["top"], own))
        elif span[0] - 5 <= row[0]["x0"] < span[1]:
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
        found.rows.extend(_net_interest(found, r))
    for r in found.rows:
        r.kind = r.kind or ("tds" if TDS.search(r.description) and r.withdrawal else
                            "tds refund" if TDS.search(r.description) and r.deposit else
                            "interest" if INTEREST.search(r.description) and r.deposit else
                            "tax refund" if REFUND.search(r.description) and r.deposit else "")


def _net_interest(found: Statement, r: Row) -> list[Row]:
    """Interest credited net of its TDS, as the interest and then the TDS withheld; any other row as it is."""
    m = NET_INTEREST.search(r.description)
    if not m or not r.deposit:
        return [r]
    gross, tax = money(m.group(1)), money(m.group(2))
    found.check(f"the interest on {r.on} less its TDS is what was credited", gross - tax == r.deposit, r.page,
                r.quote)
    interest = replace(r, deposit=gross, balance=r.balance + tax, kind="interest")
    return [interest, replace(r, deposit=Decimal(0), withdrawal=tax, kind="tds")] if tax else [interest]


def _checks(found: Statement) -> None:
    if not found.rows:
        found.questions.append(Question("no transactions were read: is this a statement of account?", 1, ""))
        return
    first = found.rows[0]
    if found.opening is not None:
        found.check(f"the balance on {first.on} follows from the opening balance",
                    abs(found.opening + first.deposit - first.withdrawal - first.balance) < CENT, first.page,
                    first.quote)
    for before, row in zip(found.rows, found.rows[1:], strict=False):
        found.check(f"the balance on {row.on} follows from the one before",
                    abs(before.balance + row.deposit - row.withdrawal - row.balance) < CENT, row.page, row.quote)
    if found.totals is not None:
        out = sum((r.withdrawal for r in found.rows), Decimal(0))
        dep = sum((r.deposit for r in found.rows), Decimal(0))
        found.check("withdrawals and deposits add up to the grand totals",
                    abs(out - found.totals[0]) <= TOTAL_SLACK and abs(dep - found.totals[1]) <= TOTAL_SLACK,
                    found.rows[-1].page)
    if found.summary is not None:
        opening, closing = found.summary
        found.check("the opening and closing balances are the account summary's",
                    found.opening == opening and found.rows[-1].balance == closing, found.rows[-1].page)
    if found.currency and found.currency != "INR":
        found.questions.append(Question(f"the account is in {found.currency}, not rupees", 1, ""))
