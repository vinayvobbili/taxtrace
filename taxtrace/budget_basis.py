"""`taxtrace budget basis`: how a line's, sub-line's or fund's budget was set, kept in the budget file.

A `basis` is an optional table under a line, a sub-line or a fund: the method in words (an average of the last
months, a quote, a round-up, a decision), the period it covers, a note, the monthly figure it came to, and the
past payments it came from. The Budget tab's info icon shows it; without one the icon says none is recorded yet.

    [[lines]]
    name = "Groceries"
    monthly = 400
      [lines.basis]
      method = "average of the last three months, rounded up"
      period = "2030-08 to 2030-10"
      amount_per_month = 380
      items = [
        { month = "2030-10", payee = "Globex Grocery", amount = 371.20 },
      ]

The file is edited as text, so its comments and layout stay as they are.
"""

from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path

from . import budget, budget_import
from .budget import Basis, BasisItem, BudgetError

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

HEADER = re.compile(r"^\s*\[\[?[^\[\]]+\]\]?\s*(#.*)?$")
NAME = re.compile(r"^\s*name\s*=\s*(\"[^\"]*\"|'[^']*')\s*(#.*)?$")
BASIS_TABLE = {"lines": "lines.basis", "lines.sub": "lines.sub.basis", "funds": "funds.basis"}


def _table(line: str) -> str:
    """The dotted name in a table header line: "  [[lines.sub]]  # note" is "lines.sub"."""
    return line.split("#", 1)[0].strip().strip("[]").strip()


def _headers(lines: list[str]) -> list[int]:
    return [i for i, line in enumerate(lines) if HEADER.match(line)]


def _locate(lines: list[str], name: str) -> tuple[int, int, str]:
    """Where the line, sub-line or fund called `name` sits in the file: its header's index, where its own block
    ends and its kind of table."""
    heads = _headers(lines)
    want = name.strip().casefold()
    for n, start in enumerate(heads):
        table = _table(lines[start])
        end = heads[n + 1] if n + 1 < len(heads) else len(lines)
        if table not in BASIS_TABLE:
            continue
        for line in lines[start + 1:end]:
            found = NAME.match(line)
            if found and tomllib.loads(f"v = {found.group(1)}")["v"].strip().casefold() == want:
                return start, end, table
    raise BudgetError(f"{name!r} isn't a line, sub-line or fund in the budget file")


def _text(value: str) -> str:
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ") + '"'


def _number(d: Decimal) -> str:
    return f"{d:f}"


def block(table: str, indent: str, basis: Basis) -> list[str]:
    """A basis table as the lines to put in the file."""
    out = [f"{indent}[{table}]"]
    for key in ("method", "period", "note"):
        if getattr(basis, key):
            out.append(f"{indent}{key} = {_text(getattr(basis, key))}")
    if basis.amount_per_month is not None:
        out.append(f"{indent}amount_per_month = {_number(basis.amount_per_month)}")
    if basis.items:
        out.append(f"{indent}items = [")
        out += [f"{indent}  {{ month = {_text(i.month)}, payee = {_text(i.payee)}, amount = {_number(i.amount)} }},"
                for i in basis.items]
        out.append(f"{indent}]")
    return out


def items_from(path: Path) -> list[BasisItem]:
    """The payments in a pipe-separated or CSV transactions file (the importer's own readers) as basis items:
    month, payee and amount. The account is left behind."""
    rows = budget_import.parse(budget_import.read_text(path)).rows
    items = [BasisItem(f"{t.day:%Y-%m}", t.payee, t.amount) for t in rows if t.amount]
    if not items:
        raise BudgetError(f"{path}: no payments found: expected date | account | payee | category | amount | flags")
    return sorted(items, key=lambda i: (i.month, i.payee.casefold()), reverse=True)


def set_basis(folder: Path, name: str, *, method: str | None = None, period: str | None = None,
              note: str | None = None, amount_per_month: str | None = None, items: list[BasisItem] | None = None,
              clear: bool = False) -> Basis | None:
    """Record how `name`'s budget was set, in the newest budget file in `folder`: what's given replaces what was
    there, the rest stays. `clear` removes the basis. The file is checked before it's written. Returns the new basis."""
    path = budget.plan_path(folder)
    if path is None:
        raise BudgetError(f"no budget-<year>.toml in {folder}")
    lines = path.read_text(encoding="utf-8").split("\n")
    start, end, table = _locate(lines, name)
    target = budget.parse_plan("\n".join(lines)).find(name)
    old = target.basis or Basis()
    new = None if clear else Basis(
        method=old.method if method is None else method.strip(),
        period=old.period if period is None else period.strip(),
        note=old.note if note is None else note.strip(),
        amount_per_month=old.amount_per_month if amount_per_month is None
        else budget.amount(amount_per_month, "--amount-per-month"),
        items=old.items if items is None else items)
    basis_table = BASIS_TABLE[table]
    while end < len(lines) and HEADER.match(lines[end]) and _table(lines[end]).startswith(basis_table):
        stop = next((i for i in _headers(lines) if i > end), len(lines))
        del lines[end:stop]  # the old basis: its table and any sub-tables
    if new is not None:
        at = end
        while at > start + 1 and not lines[at - 1].strip():
            at -= 1
        indent = re.match(r"\s*", lines[start]).group()
        lines[at:at] = block(basis_table, indent, new)
    text = "\n".join(lines)
    budget.parse_plan(text)  # a broken edit is never written
    path.write_text(text, encoding="utf-8")
    return new


def describe(name: str, basis: Basis | None, monthly: Decimal | None = None) -> list[str]:
    """What a basis says, for the terminal: no account digits, only what the file holds."""
    if basis is None:
        return [f"{name}: no basis recorded yet. Add one with: taxtrace budget basis \"{name}\" --method \"...\" "
                f"--period \"...\" --items-from <file>"]
    out = [name + (f" (budget {monthly:,.0f} a month)" if monthly is not None else "")]
    for label, value in (("method", basis.method), ("period", basis.period), ("note", basis.note)):
        if value:
            out.append(f"  {label}: {value}")
    if basis.amount_per_month is not None:
        out.append(f"  per month: {basis.amount_per_month:,.2f}")
    if basis.items:
        out.append(f"  {len(basis.items)} past payments, {basis.total():,.2f} in all:")
        out += [f"    {i.month}  {i.payee}  {i.amount:,.2f}"
                for i in sorted(basis.items, key=lambda i: (i.month, i.payee.casefold()), reverse=True)]
    return out
