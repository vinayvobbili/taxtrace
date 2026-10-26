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

A third is a monthly e-statement of every account a customer holds at the bank ("As on 31-01-26"): a balance summary,
the term deposits (one row each: the account, its opening day, principal, rate, interest accrued, maturity amount and
day), then a page per savings account, its transactions under "Credit", "Debit" and "Balance" between "... on
01-01-26: <opening>" and "Your Closing Balance on 31-01-26: <closing>". A month without transactions prints only the
account's available balance. Each account is a statement of its own; a term deposit's balance is its principal and
the interest accrued on it, as the statement's day.

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
# the e-statement of all of a customer's accounts: dates as dd-mm-yy
AS_ON = re.compile(r"\bAs on (\d{2}-\d{2}-\d{2})\b")
SHORT_DAY = re.compile(r"^(\d{2})-(\d{2})-(\d{2}):?$")
BALANCE_ON = re.compile(rf"\bon (\d{{2}}-\d{{2}}-\d{{2}}):\s*{AMOUNT}")
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


def _long(printed: str) -> str:
    """'31-01-26' as '31-01-2026'."""
    d, m, y = SHORT_DAY.match(printed).groups()
    return f"{d}-{m}-20{y}"


def _last_four(printed: str) -> str:
    """An account number's last four digits, printed whole or masked ('XXXXXXX1234'); '' if it isn't one."""
    digits = re.sub(r"\D", "", printed)
    return digits[-4:] if len(digits) >= 4 and re.fullmatch(r"[\dX]+", printed) else ""


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
    closing: Decimal | None = None  # the balance at the end, when it prints one apart from the rows
    kind: str = ""  # in a statement of several accounts: "savings" or "term deposit"
    operation: str = ""  # how a savings account is held: "SINGLE", "FORMER OR SURVIVOR"
    term: dict | None = None  # a term deposit's opening day, principal, rate, interest accrued, maturity and its day
    balance_page: int = 0  # where the closing balance was read, when no row gives it
    balance_quote: str = ""
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


def is_consolidated(page: str) -> bool:
    """A page of the monthly e-statement of all of a customer's accounts."""
    flat = " ".join(page.split())
    return bool(AS_ON.search(flat)) and "Welcome" in flat


def read_consolidated(name: str, pages: list[str], words: dict[int, list[dict]]) -> list[Statement]:
    """Each account in a statement of all of a customer's accounts, as a statement of its own: the savings accounts
    with their transactions, and the term deposits."""
    flat = " ".join(" ".join(pages).split())
    end = _long(m.group(1)) if (m := AS_ON.search(flat)) else ""
    start = "01" + end[2:]
    currency = "INR" if re.search(r"\bINR\b", flat) else ""
    found: list[Statement] = []
    summary: dict[str, tuple[Decimal, str]] = {}
    available: dict[int, Decimal] = {}  # each savings account's, by its place in `found`
    current: Statement | None = None  # the savings account whose page is being read
    columns: dict[str, float] = {}
    for n in sorted(words):
        rows = _rows(words[n])
        texts = [" ".join(w["text"] for w in r) for r in rows]
        if "FIXED DEPOSITS" in texts:
            found += _deposits(name, n, rows, start, end, currency)
            continue
        described = False  # a line under a transaction continues its description
        for i, (row, text) in enumerate(zip(rows, texts, strict=True)):
            if text.startswith("Transaction Accounts") or text.startswith(("Fixed Deposit", "Total")):
                if amounts := [w["text"] for w in row if MONEY.match(w["text"])]:
                    summary[text.split()[0].lower()] = (money(amounts[-1]), text)
            if text in ("SAVING ACCOUNT", "SAVINGS ACCOUNT") and i + 1 < len(rows) \
                    and (account := _last_four(rows[i + 1][0]["text"])):
                current = Statement(name, account, currency, start, end, kind="savings")
                found.append(current)
                columns, described = {}, False
                continue
            if current is None:
                continue
            if "of Operation" in text:
                current.operation = text.split("Operation", 1)[1].strip()
            elif text.startswith("Available Balance") and (
                    amounts := [w["text"] for w in row if MONEY.match(w["text"])]):
                available[len(found) - 1] = money(amounts[-1])
                current.balance_page, current.balance_quote = n, text
            elif all(c in [w["text"] for w in row] for c in ("Credit", "Debit", "Balance")):
                columns = {w["text"]: w["x0"] for w in row}
            elif columns and (m := BALANCE_ON.search(text)):
                on, balance = _long(m.group(1)), money(m.group(2))
                if "Closing" in text:
                    current.closing, current.end = balance, on
                    current.balance_page, current.balance_quote = n, text
                else:
                    current.opening, current.start = balance, on
                described = False
            elif columns and SHORT_DAY.match(row[0]["text"]):
                current.rows.append(_transaction(row, columns, n, text))
                described = True
            elif described and columns and 40 < row[0]["x0"] < columns["Credit"] - 50 \
                    and not any(MONEY.match(w["text"]) for w in row):
                current.rows[-1].description += " " + text
            else:
                described = False
    for i, s in enumerate(found):
        if s.kind == "savings":
            _savings_checks(s, available.get(i))
    _summary_checks(found, summary)
    return found


def _transaction(row: list[dict], columns: dict[str, float], n: int, text: str) -> Row:
    """A savings account's row: the date, the description, a reference, then amounts right-aligned under "Credit",
    "Debit" and "Balance" (the other column printing 0), so each goes by its right edge."""
    credit = debit = Decimal(0)
    balance = Decimal(0)
    for w in row[1:]:
        if not MONEY.match(w["text"]):
            continue
        if w["x1"] > columns["Balance"]:
            balance = money(w["text"])
        elif w["x1"] > columns["Debit"]:
            debit = money(w["text"])
        else:
            credit = money(w["text"])
    # the description runs up to the cheque or reference number's column ("Ref.No./Chq.No."), a "-" when there's none
    cut = next((x for t, x in columns.items() if ".No" in t), columns["Credit"])
    words = [w["text"] for w in row[1:] if w["x0"] < cut and w["text"] != "-"]
    on = _long(row[0]["text"])
    found = Row(on, debit, credit, balance, " ".join(words), "", n, text)
    found.kind = ("tds" if TDS.search(found.description) and debit else
                  "tds refund" if TDS.search(found.description) and credit else
                  "interest" if INTEREST.search(found.description) and credit else
                  "tax refund" if REFUND.search(found.description) and credit else "")
    return found


def _deposits(name: str, n: int, rows: list[list[dict]], start: str, end: str, currency: str) -> list[Statement]:
    """The term deposits' page: a row each, its account, opening day, principal, holding, rate, lien, interest
    accrued, maturity amount and maturity day."""
    found = []
    for row in rows:
        texts = [w["text"] for w in row]
        days = [i for i, t in enumerate(texts) if SHORT_DAY.match(t)]
        if len(days) < 2 or not days[0] or not (account := _last_four(texts[days[0] - 1])):
            continue
        amounts = [money(t) for t in texts[days[0] + 1:days[1]] if MONEY.match(t)]
        s = Statement(name, account, currency, start, end, kind="term deposit")
        s.balance_page, s.balance_quote = n, " ".join(texts)
        found.append(s)
        if len(amounts) != 5:
            s.questions.append(Question(f"term deposit {account}'s row doesn't read as principal, rate, lien, interest "
                                        "accrued and maturity amount", n, s.balance_quote))
            continue
        principal, rate, _, accrued, maturity = amounts
        s.term = {"opened": _long(texts[days[0]]), "principal": principal, "rate": rate, "accrued": accrued,
                  "maturity": maturity, "matures": _long(texts[days[1]])}
        s.opening = s.closing = principal + accrued
        s.check("the maturity amount is more than the principal and the interest accrued so far",
                maturity >= principal + accrued, n, s.balance_quote)
    return found


def _savings_checks(s: Statement, available: Decimal | None) -> None:
    if s.closing is None and not s.rows:  # a month without transactions prints only the balance
        s.opening = s.closing = available
    if s.closing is None:
        s.questions.append(Question(f"savings account {s.account}: no closing or available balance was read",
                                    s.balance_page or 1, ""))
        return
    if s.rows:
        first = s.rows[0]
        if s.opening is not None:
            s.check(f"the balance on {first.on} follows from the opening balance",
                    abs(s.opening + first.deposit - first.withdrawal - first.balance) < CENT, first.page, first.quote)
        for before, row in zip(s.rows, s.rows[1:], strict=False):
            s.check(f"the balance on {row.on} follows from the one before",
                    abs(before.balance + row.deposit - row.withdrawal - row.balance) < CENT, row.page, row.quote)
        s.check("the closing balance is the last transaction's", s.rows[-1].balance == s.closing, s.balance_page,
                s.balance_quote)
    if available is not None:
        s.check("the available balance is the closing balance", available == s.closing, s.balance_page,
                s.balance_quote)


def _summary_checks(found: list[Statement], summary: dict[str, tuple[Decimal, str]]) -> None:
    """The balance summary's lines: the savings accounts' balances together, the term deposits' (principal, or with
    the interest accrued), and their total."""
    savings = [s for s in found if s.kind == "savings"]
    deposits = [s for s in found if s.kind == "term deposit" and s.term]
    if not found:
        return
    saved = sum((s.closing or Decimal(0) for s in savings), Decimal(0))
    principal = sum((s.term["principal"] for s in deposits), Decimal(0))
    held = sum((s.closing for s in deposits), Decimal(0))
    target = found[0]
    if "transaction" in summary:
        target.check("the savings accounts' balances add up to the balance summary's",
                     summary["transaction"][0] == saved, 1, summary["transaction"][1])
    if "fixed" in summary:
        target.check("the term deposits add up to the balance summary's", summary["fixed"][0] in (principal, held), 1,
                     summary["fixed"][1])
    if "total" in summary:
        target.check("the accounts add up to the balance summary's total",
                     summary["total"][0] in (saved + principal, saved + held), 1, summary["total"][1])
    elif not summary:
        target.questions.append(Question("the balance summary wasn't read", 1, ""))


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
