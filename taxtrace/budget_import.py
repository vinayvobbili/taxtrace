"""Reading a month's transactions into the budget: a bank or card's CSV export, or a pipe-separated list.

A CSV's columns are found by their names, never by who issued it: a date, a description (or payee, merchant,
name), and an amount, or separate debit and credit columns; a status column marks pending rows and a category or
type column is kept. Whether spending is negative or positive is read off the rows (most rows are spending), or
given with `sign`.

Pipe-separated transactions are one per line: `date | account | payee | category | amount | flags`, spending
positive and refunds or credits negative, flags such as PENDING, TRANSFER, INCOME or ONE-OFF. Lines that aren't
rows (headings, notes, totals) are counted as skipped.

The raw file is copied to a folder on this computer only (statements/<yyyy-mm>/ in the private folder, never the
synced workspace, never a git repo); what's kept in the workspace is the month's rows and their totals.
"""

from __future__ import annotations

import csv
import hashlib
import io
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import budget, workspace
from .budget import BudgetError, Month, Txn

PRIVATE_ENV = "TAXTRACE_BUDGET_PRIVATE"

# Column names, most specific first; each is matched against the whole header, lowercased.
COLUMNS = {
    "date": [r"(transaction|trans\.?) date", r"date", r"(posted|posting|post) date", r".*\bdate\b.*"],
    "payee": [r"description", r"payee", r"merchant( name)?", r"name", r"details", r".*(description|payee|merchant).*",
              r"memo"],
    "amount": [r"amount", r"amount \(\w+\)", r".*\bamount\b.*"],
    "debit": [r"debit( amount)?", r"withdrawals?( amount)?", r"money out", r"outflow", r"charges?"],
    "credit": [r"credit( amount)?", r"deposits?( amount)?", r"money in", r"inflow", r"payments?"],
    "status": [r"status", r"state", r"pending"],
    "category": [r"category", r"type", r"transaction type"],
    "account": [r"account( name)?", r"card( name)?", r"account type"],
}
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%b %d, %Y", "%d %b %Y", "%B %d, %Y", "%Y/%m/%d")
SIGNS = ("spend-negative", "spend-positive")


def private_home(env: dict[str, str] | None = None) -> Path:
    """Where raw statements and pastes are kept: on this computer, outside the synced workspace and every repo."""
    env = os.environ if env is None else env
    if env.get(PRIVATE_ENV):
        return Path(env[PRIVATE_ENV]).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "budget-private"
    return Path(env.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "budget-private"


def check_private(folder: Path, home: Path) -> Path:
    """`folder`, after making sure it's outside every git repo and outside the workspace (which may be synced, and
    whose other folders are read as documents)."""
    folder = workspace.outside_git(folder)
    if folder.is_relative_to(home.expanduser().resolve()):
        raise BudgetError(f"{folder} is inside the workspace ({home}); raw statements stay in a folder on this "
                          f"computer only: set {PRIVATE_ENV} to one outside it")
    return folder


def parse_date(text: str) -> date | None:
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(text: str) -> Decimal | None:
    """$1,234.56, -12.75, (12.75) and 12.75- as amounts; blank or anything else as None."""
    t = text.strip().replace("−", "-").replace("$", "").replace(",", "").replace(" ", "")
    if not t:
        return None
    negative = (t.startswith("(") and t.endswith(")")) or t.endswith("-")
    t = t.strip("()").rstrip("-")
    try:
        d = Decimal(t)
    except InvalidOperation:
        return None
    return -d if negative else d


@dataclass
class Parsed:
    kind: str  # "csv" or "pipe"
    rows: list[Txn]
    skipped: int = 0
    columns: dict[str, str] = field(default_factory=dict)  # role -> the CSV header it was read from
    flipped: bool = False  # spending was negative in the file


def _pick(headers: list[str], role: str, taken: set[int]) -> int | None:
    low = [h.strip().lower() for h in headers]
    for pattern in COLUMNS[role]:
        for i, h in enumerate(low):
            if i not in taken and h and re.fullmatch(pattern, h):
                return i
    return None


def _find_header(rows: list[list[str]]) -> tuple[int, dict[str, int]]:
    for n, row in enumerate(rows[:25]):
        taken: set[int] = set()
        cols: dict[str, int] = {}
        for role in ("date", "debit", "credit", "amount", "payee", "status", "category", "account"):
            i = _pick(row, role, taken)
            if i is not None:
                cols[role] = i
                taken.add(i)
        if "debit" in cols and "credit" in cols:
            cols.pop("amount", None)  # two columns say it better than one that may be either
        else:
            cols.pop("debit", None)
            cols.pop("credit", None)
        if "date" in cols and "payee" in cols and ("amount" in cols or "debit" in cols):
            return n, cols
    raise BudgetError("no header row with a date, a description and an amount (or debit and credit) columns: "
                      "this doesn't look like a transactions export")


def parse_csv(text: str, sign: str | None = None) -> Parsed:
    if sign is not None and sign not in SIGNS:
        raise BudgetError(f"sign is one of {', '.join(SIGNS)}")
    rows = list(csv.reader(io.StringIO(text)))
    start, cols = _find_header(rows)
    headers = rows[start]
    out, skipped, raw_amounts = [], 0, []
    for row in rows[start + 1:]:
        if not any(c.strip() for c in row):
            continue

        def cell(role: str, row: list[str] = row) -> str:
            i = cols.get(role)
            return row[i] if i is not None and i < len(row) else ""
        day = parse_date(cell("date"))
        if "amount" in cols:
            value = parse_amount(cell("amount"))
        else:
            debit, credit = parse_amount(cell("debit")), parse_amount(cell("credit"))
            value = None if debit is None and credit is None else abs(debit or 0) - abs(credit or 0)
        payee = cell("payee").strip()
        if day is None or value is None or not payee:
            skipped += 1
            continue
        status = cell("status").strip().lower()
        pending = "pending" in status or payee.lower().startswith("pending ")
        out.append(Txn(day=day, payee=payee, amount=value, account=cell("account").strip(),
                       category=cell("category").strip(), pending=pending))
        raw_amounts.append(value)
    flipped = False
    if "amount" in cols:
        # Most rows of an export are spending: when most amounts are negative, spending is negative here.
        flipped = sign == "spend-negative" or (sign is None and sum(a < 0 for a in raw_amounts) > len(raw_amounts) / 2)
        if flipped:
            for t in out:
                t.amount = -t.amount
    return Parsed("csv", out, skipped, {role: headers[i] for role, i in cols.items()}, flipped)


def parse_pipe(text: str) -> Parsed:
    out, skipped = [], 0
    for line in text.splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split("|")]
        day = parse_date(parts[0]) if len(parts) >= 5 else None
        value = parse_amount(parts[4]) if day else None
        if day is None or value is None or not parts[2]:
            skipped += 1
            continue
        flags = tuple(f.strip().upper() for f in re.split(r"[,;]", parts[5]) if f.strip()) if len(parts) > 5 else ()
        flags = tuple(f for f in flags if re.fullmatch(r"[A-Z][A-Z -]*", f))
        account = "" if parts[1].lower() in ("", "unknown", "-") else parts[1]
        out.append(Txn(day=day, payee=parts[2], amount=value, account=account, category=parts[3],
                       pending="PENDING" in flags, flags=tuple(f for f in flags if f != "PENDING")))
    return Parsed("pipe", out, skipped)


def is_pipe(text: str) -> bool:
    """Whether a file is pipe-separated transactions: some line has five or more fields and starts with a date."""
    return any(len(p := line.split("|")) >= 5 and parse_date(p[0]) for line in text.splitlines()[:400])


def parse(text: str, sign: str | None = None) -> Parsed:
    return parse_pipe(text) if is_pipe(text) else parse_csv(text, sign)


def read_text(path: Path) -> str:
    data = path.read_bytes()
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("latin-1")


def stamp(rows: list[Txn], source: str) -> None:
    """Give each row its source and an id from what it says (date, payee, amount, account), numbered when the same
    row appears twice (two coffees on one day), so importing the same rows again finds them."""
    seen: dict[str, int] = {}
    for t in rows:
        key = "|".join([t.day.isoformat(), budget.norm(t.payee), str(budget.cents(t.amount)), budget.norm(t.account)])
        seen[key] = seen.get(key, 0) + 1
        t.id = hashlib.sha256(f"{key}|{seen[key]}".encode()).hexdigest()[:16]
        t.source = source


@dataclass
class Report:
    kind: str
    month: str
    parsed: int = 0  # rows read in the file
    skipped: int = 0  # lines that weren't rows
    other_months: int = 0
    added: int = 0
    unchanged: int = 0  # already there from this source's last import
    gone: int = 0  # in this source's last import, not in this one (a pending row that changed when it posted)
    duplicates: int = 0  # already there from another source
    pending: int = 0
    refunds: int = 0
    excluded: int = 0
    one_off: int = 0
    unmatched: int = 0
    unmatched_payees: int = 0
    trial: bool = False
    path: Path | None = None
    kept: Path | None = None
    columns: dict[str, str] = field(default_factory=dict)

    def lines(self) -> list[str]:
        out = [f"{self.month}{' (trial month)' if self.trial else ''}: {self.parsed} rows read ({self.kind}), "
               f"{self.skipped} lines skipped" + (f", {self.other_months} from other months left out"
                                                  if self.other_months else "")]
        out.append(f"  {self.added} new, {self.unchanged} already imported"
                   + (f", {self.gone} gone since the last import" if self.gone else "")
                   + (f", {self.duplicates} already there from another file" if self.duplicates else ""))
        out.append(f"  {self.pending} pending, {self.refunds} refunds, {self.excluded} left out as transfers or "
                   f"income, {self.one_off} one-off")
        out.append(f"  {self.unmatched} rows from {self.unmatched_payees} payees match no rule"
                   + (": see `taxtrace budget rules --unmatched`" if self.unmatched else ""))
        return out


def import_file(path: Path, month: str, folder: Path, plan: budget.Plan, rules: list[budget.Rule],
                source: str | None = None, trial: bool = False, sign: str | None = None,
                keep_to: Path | None = None) -> Report:
    """Read one export into `month`'s actuals in the budget `folder`. Importing a file again replaces what that
    source gave before (so a pending row that posted is counted once); a row another source already gave is left
    out as a duplicate. With `keep_to`, the raw file is copied to statements/<month>/ there."""
    month = budget.month_key(month)
    parsed = parse(read_text(path), sign)
    label = source or path.stem
    stamp(parsed.rows, label)
    report = Report(kind=parsed.kind, month=month, parsed=len(parsed.rows), skipped=parsed.skipped,
                    columns=parsed.columns)
    rows = [t for t in parsed.rows if t.day.strftime("%Y-%m") == month]
    report.other_months = len(parsed.rows) - len(rows)
    current = budget.load_actuals(folder).get(month) or Month(month=month, txns=[])
    before = {t.id for t in current.txns if t.source == label}
    others = [t for t in current.txns if t.source != label]
    other_ids = {t.id for t in others}
    fresh = []
    for t in rows:
        if t.id in other_ids:
            report.duplicates += 1
        else:
            fresh.append(t)
    report.unchanged = sum(t.id in before for t in fresh)
    report.added = len(fresh) - report.unchanged
    report.gone = len(before - {t.id for t in fresh})
    current.txns = others + fresh
    current.trial = current.trial or trial
    report.trial = current.trial
    current.sources[label] = {"file": path.name, "kind": parsed.kind, "rows": len(fresh),
                              "imported": datetime.now().isoformat(timespec="seconds")}
    for s in (budget.sort_txn(t, rules, plan) for t in fresh):
        report.pending += s.txn.pending
        report.refunds += s.refund
        report.excluded += s.excluded in ("rule", "transfer", "credit")
        report.one_off += s.one_off
        report.unmatched += s.unmatched
    report.unmatched_payees = len({budget.norm(t.payee) for t in fresh
                                   if budget.sort_txn(t, rules, plan).unmatched})
    report.path = budget.save_month(folder, current, plan, rules)
    if keep_to is not None:
        report.kept = keep_statement(path, month, keep_to)
    return report


def keep_statement(path: Path, month: str, private: Path) -> Path:
    """Copy the raw file to <private>/statements/<month>/, unless it's already in the private folder."""
    path = path.expanduser().resolve()
    private = private.expanduser().resolve()
    if path.is_relative_to(private):
        return path
    dest = private / workspace.STATEMENTS / month / path.name
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    return dest


def refresh(folder: Path, plan: budget.Plan, rules: list[budget.Rule]) -> int:
    """Rewrite every month's totals with the rules as they are now (after a rule is added). Returns the months."""
    months = budget.load_actuals(folder)
    for m in months.values():
        budget.save_month(folder, m, plan, rules)
    return len(months)


def unmatched_payees(folder: Path, plan: budget.Plan, rules: list[budget.Rule],
                     month: str | None = None) -> list[tuple[str, int]]:
    """Payees no rule matches, with how many rows each has, most rows first: to write rules for. No amounts."""
    counts: dict[str, int] = {}
    names: dict[str, str] = {}
    for m in budget.load_actuals(folder).values():
        if month and m.month != month:
            continue
        for t in m.txns:
            if budget.sort_txn(t, rules, plan).unmatched:
                key = budget.norm(t.payee)
                counts[key] = counts.get(key, 0) + 1
                names.setdefault(key, t.payee)
    return sorted(((names[k], n) for k, n in counts.items()), key=lambda x: (-x[1], x[0].lower()))
