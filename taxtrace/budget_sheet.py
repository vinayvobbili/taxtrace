"""`taxtrace budget check`: a spreadsheet's copy of the budget against the budget file, read-only.

A household may keep its budget twice: in the budget file here and in a spreadsheet that people open and edit.
This reads CSV exports of the spreadsheet's tabs, with a map file (sheet-map.toml, in the budget folder) that says
which column or row holds which budget line, and lists every figure on which the two disagree. It never writes to
either side and never calls the spreadsheet: you export the tabs again when you want a fresh look.

    tolerance = 0.50                       # optional: differences up to this much are the same figure

    [[sources]]
    file = "sheet-exports/tracker.csv"     # relative to the map's folder
    kind = "month-grid"                    # one row per month, one column per figure
    month_column = "Month"                 # the header of the column that names the month (2031-03, Mar 2031...)
    months = "2031-01..2031-12"            # optional: the months to compare (default: the plan's year)
    total_row = "2031 total"               # optional: the row of yearly totals, compared with the plan's years
    total = "Spending lines budget total"  # optional: the column holding all the spending lines' total
    watch = ["budget", "CAP"]              # optional: a column ending in one of these words that is not in the
                                           # map below is reported as only in the Sheet
    ignore = ["Variance (actual - budget)"]  # optional: columns that watch should pass over (not lines)
      [sources.lines]                      # budget line, sub-line or property line -> its monthly budget column
      "Groceries" = "Groceries budget"
      [sources.transfers]                  # sinking fund -> its monthly transfer column
      "Travel" = "Travel fund transfer"
      [sources.planned]                    # sinking fund -> what it is planned to pay, by month
      "Travel" = "Travel fund spent plan"

    [[sources]]
    file = "sheet-exports/detail.csv"
    kind = "year-table"                    # one row per line, with a yearly and/or a monthly figure
    name_column = "Sub-line"
    annual_column = "Annual budget"        # compared with the plan's year
    monthly_column = "Monthly budget"      # compared with the plan's usual monthly figure
      [sources.lines]                      # budget line -> the row's name
      "Power" = "Power"

A column or row is found by its words alone (case, emoji and punctuation are ignored). A tab's export may hold
several tables: the header row is the first one that has the month column (or the name column).
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from . import budget
from .budget import ZERO, BudgetError, Fund, Line, Plan

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

MAP_FILE = "sheet-map.toml"
TOLERANCE = Decimal("0.50")
KINDS = ("month-grid", "year-table")
ASPECTS = {"lines": "budget", "transfers": "transfer", "planned": "planned"}
REFRESH = ("Export each tab of the Sheet as CSV (File > Download > Comma-separated values) over the files in "
           "budget/sheet-exports/, then run `taxtrace budget check`.")


class SheetError(BudgetError):
    """The map or an export can't be read: the message names the file and the column or row."""


class SheetMissing(SheetError):
    """There is no map, or an export it names isn't there: the check has nothing to compare."""


@dataclass
class Source:
    file: str
    kind: str
    lines: dict[str, str] = field(default_factory=dict)  # plan name -> the sheet's column header or row name
    transfers: dict[str, str] = field(default_factory=dict)
    planned: dict[str, str] = field(default_factory=dict)
    month_column: str = ""
    months: tuple[str, ...] = ()
    total_row: str = ""
    total: str = ""
    watch: tuple[str, ...] = ()
    ignore: tuple[str, ...] = ()
    name_column: str = ""
    annual_column: str = ""
    monthly_column: str = ""

    def targets(self) -> list[tuple[str, str, str]]:
        """(aspect, plan name, the sheet's column or row) for everything this source maps."""
        return [(aspect, name, label) for table, aspect in ASPECTS.items()
                for name, label in getattr(self, table).items()]


@dataclass
class SheetMap:
    sources: list[Source]
    tolerance: Decimal = TOLERANCE
    folder: Path = Path(".")

    def path(self, source: Source) -> Path:
        return self.folder / source.file


@dataclass
class Diff:
    line: str
    period: str  # a month, "year" or "each month" (a monthly figure)
    sheet: Decimal | None
    taxtrace: Decimal | None
    file: str = ""

    @property
    def difference(self) -> Decimal | None:
        return None if self.sheet is None or self.taxtrace is None else self.sheet - self.taxtrace

    def to_json(self) -> dict:
        return {"line": self.line, "period": self.period, "sheet": budget._num(self.sheet),
                "taxtrace": budget._num(self.taxtrace), "difference": budget._num(self.difference), "file": self.file}


@dataclass
class Result:
    lines: int = 0  # distinct lines, funds and totals compared
    values: int = 0  # figures compared
    diffs: list[Diff] = field(default_factory=list)
    only_sheet: list[str] = field(default_factory=list)  # in the map or the export, not in the budget file
    only_taxtrace: list[str] = field(default_factory=list)  # in the budget file, not in the map
    files: list[str] = field(default_factory=list)
    exported: datetime | None = None  # the oldest of the exports' modified times

    @property
    def count(self) -> int:
        return len(self.diffs) + len(self.only_sheet) + len(self.only_taxtrace)

    @property
    def in_sync(self) -> bool:
        return self.count == 0

    def to_json(self) -> dict:
        return {"state": "in_sync" if self.in_sync else "differs", "count": self.count, "lines": self.lines,
                "values": self.values, "diffs": [d.to_json() for d in self.diffs], "only_sheet": self.only_sheet,
                "only_taxtrace": self.only_taxtrace, "files": self.files,
                "exported": self.exported.date().isoformat() if self.exported else None, "refresh": REFRESH}


# -- reading ------------------------------------------------------------------------------------------------------

def _text(raw: dict, key: str, where: str, required: bool = False) -> str:
    value = raw.get(key, "")
    if not isinstance(value, str) or (required and not value.strip()):
        raise SheetError(f"{where}: {key} is text, such as {key} = \"...\"")
    return value.strip()


def _names(raw: dict, key: str, where: str) -> dict[str, str]:
    table = raw.get(key) or {}
    if not isinstance(table, dict) or not all(isinstance(v, str) and v.strip() for v in table.values()):
        raise SheetError(f"{where}: [sources.{key}] maps each budget name to the sheet's column or row, such as "
                         f"\"Groceries\" = \"Groceries budget\"")
    return {str(k).strip(): v.strip() for k, v in table.items()}


def _words(raw: dict, key: str, where: str) -> tuple[str, ...]:
    words = raw.get(key) or []
    if not isinstance(words, list) or not all(isinstance(w, str) and w.strip() for w in words):
        raise SheetError(f"{where}: {key} is a list of words, such as {key} = [\"budget\", \"CAP\"]")
    return tuple(w.strip() for w in words)


def _months(text: str, where: str) -> tuple[str, ...]:
    first, _, last = text.partition("..")
    try:
        lo, hi = budget.month_key(first.strip()), budget.month_key((last or first).strip())
    except BudgetError:
        raise SheetError(f"{where}: months is a range such as months = \"2031-01..2031-12\"") from None
    out, y, m = [], int(lo[:4]), int(lo[5:])
    while f"{y}-{m:02d}" <= hi:
        out.append(f"{y}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    if not out:
        raise SheetError(f"{where}: months {text!r} ends before it starts")
    return tuple(out)


def parse_map(text: str, folder: Path) -> SheetMap:
    """sheet-map.toml's sources. SheetError says what is wrong with a map that doesn't parse or doesn't add up."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as err:
        raise SheetError(f"{MAP_FILE} isn't valid TOML: {err}") from None
    try:
        tolerance = budget.amount(data["tolerance"], f"{MAP_FILE} tolerance") if "tolerance" in data else TOLERANCE
    except BudgetError:
        raise SheetError(f"{MAP_FILE}: tolerance is an amount, such as tolerance = 0.50") from None
    sources = []
    for i, raw in enumerate(data.get("sources") or [], 1):
        where = f"{MAP_FILE} source {i}"
        if not isinstance(raw, dict):
            raise SheetError(f"{where}: write each source as a [[sources]] table")
        file, kind = _text(raw, "file", where, True), _text(raw, "kind", where, True)
        if kind not in KINDS:
            raise SheetError(f"{where} ({file}): kind is one of {', '.join(KINDS)}")
        src = Source(file=file, kind=kind, lines=_names(raw, "lines", where), transfers=_names(raw, "transfers", where),
                     planned=_names(raw, "planned", where))
        if kind == "month-grid":
            src.month_column = _text(raw, "month_column", where, True)
            src.total_row, src.total = _text(raw, "total_row", where), _text(raw, "total", where)
            src.watch, src.ignore = (_words(raw, key, f"{where} ({file})") for key in ("watch", "ignore"))
            if "months" in raw:
                src.months = _months(_text(raw, "months", where), f"{where} ({file})")
        else:
            src.name_column = _text(raw, "name_column", where, True)
            src.annual_column = _text(raw, "annual_column", where)
            src.monthly_column = _text(raw, "monthly_column", where)
            if not (src.annual_column or src.monthly_column):
                raise SheetError(f"{where} ({file}): give an annual_column or a monthly_column to compare")
        if not (src.targets() or src.total):
            raise SheetError(f"{where} ({file}): map at least one line, [sources.lines]")
        sources.append(src)
    if not sources:
        raise SheetError(f"{MAP_FILE} has no sources: add a [[sources]] table for each tab's CSV export")
    return SheetMap(sources=sources, tolerance=tolerance, folder=folder)


def load_map(folder: Path, path: Path | None = None) -> SheetMap:
    path = path or folder / MAP_FILE
    if not path.is_file():
        raise SheetMissing(f"no {path.name} in {path.parent}: it says which column of the Sheet's CSV export holds "
                           f"which budget line (see docs/budget.md, \"Checking a spreadsheet's copy\")")
    return parse_map(path.read_text(encoding="utf-8"), path.parent)


def read_table(path: Path) -> list[list[str]]:
    if not path.is_file():
        raise SheetMissing(f"{path.name} isn't in {path.parent}. {REFRESH}")
    try:
        with path.open(newline="", encoding="utf-8-sig") as f:
            return [[c.strip() for c in row] for row in csv.reader(f)]
    except (UnicodeDecodeError, csv.Error) as err:
        raise SheetError(f"{path.name} isn't a CSV file: {err}") from None


def sheet_month(text: str) -> str | None:
    """A month cell as 2031-03: 2031-03, 2031-03-01, 3/1/2031, Mar 2031 or March 2031; None for anything else."""
    text = text.strip()
    if (m := re.fullmatch(r"(20\d\d)-(0[1-9]|1[0-2])(?:-\d\d)?", text)):
        return f"{m[1]}-{m[2]}"
    if (m := re.fullmatch(r"(1[0-2]|0?[1-9])/(?:\d{1,2}/)?(20\d\d)", text)):
        return f"{m[2]}-{int(m[1]):02d}"
    for fmt in ("%b %Y", "%B %Y"):
        try:
            return datetime.strptime(text, fmt).strftime("%Y-%m")
        except ValueError:
            continue
    return None


def sheet_amount(cell: str, where: str) -> Decimal:
    """A cell's figure: $1,250, -$40, (40) or 12.5; a blank cell is no budget, so zero."""
    text = cell.strip()
    if not text:
        return ZERO
    negative = text.startswith("(") and text.endswith(")")
    try:
        value = budget.amount(text.strip("()") if negative else text, where, signed=True)
    except BudgetError:
        raise SheetError(f"{where}: {cell!r} isn't an amount") from None
    return -value if negative else value


# -- the budget file's side ---------------------------------------------------------------------------------------

def usual_monthly(item: Line | Fund) -> Decimal:
    """The figure a line or fund is budgeted at in an ordinary month, before any month's own override."""
    if isinstance(item, Fund):
        return item.monthly
    return item.monthly if item.monthly is not None else sum((usual_monthly(s) for s in item.subs), ZERO)


def _plan_value(plan: Plan, item: Line | Fund | None, aspect: str, month: str | None) -> Decimal:
    """What the budget file says: a month's figure, or the year's with no month."""
    if aspect == "total":
        return sum((_plan_value(plan, x, "budget", month) for x in plan.lines), ZERO)
    months = [month] if month else plan.months()
    if aspect == "budget":
        return sum((item.budget(m) for m in months), ZERO)
    if aspect == "transfer":
        return sum((item.transfer(m) for m in months), ZERO)
    return sum((item.planned.get(m, ZERO) for m in months), ZERO)


def _resolve(plan: Plan, aspect: str, name: str, where: str) -> Line | Fund | None:
    """The line or fund `name` as the budget file has it, None if it has none; SheetError when it is the wrong kind."""
    item = plan.find(name)
    if item is None:
        return None
    if aspect == "budget" and isinstance(item, Fund):
        raise SheetError(f"{where}: {item.name!r} is a sinking fund: map it under [sources.transfers] or "
                         f"[sources.planned]")
    if aspect != "budget" and not isinstance(item, Fund):
        raise SheetError(f"{where}: {item.name!r} is a budget line, not a sinking fund: map it under [sources.lines]")
    return item


# -- comparing ----------------------------------------------------------------------------------------------------

def _column(header: list[str], label: str, where: str) -> int:
    found = [i for i, cell in enumerate(header) if budget.norm(cell) == budget.norm(label)]
    if not found:
        raise SheetError(f"{where}: no column headed {label!r}")
    if len(found) > 1:
        raise SheetError(f"{where}: {len(found)} columns are headed {label!r}; make the headers differ")
    return found[0]


def _header_row(rows: list[list[str]], label: str, where: str) -> int:
    for i, row in enumerate(rows):
        if any(budget.norm(cell) == budget.norm(label) for cell in row):
            return i
    raise SheetError(f"{where}: no row has a column headed {label!r}")


def _cell(row: list[str], col: int) -> str:
    return row[col] if col < len(row) else ""


def _shown(item, aspect: str, name: str) -> str:
    base = item.name if item is not None else name
    return {"budget": base, "transfer": f"{base} (transfer)", "planned": f"{base} (planned)",
            "total": "Spending lines (total)"}[aspect]


class _Compare:
    def __init__(self, plan: Plan, tolerance: Decimal):
        self.plan, self.tolerance, self.result = plan, tolerance, Result()
        self.covered: set[tuple[str, str]] = set()
        self.names: set[str] = set()

    def figure(self, shown: str, period: str, sheet: Decimal, plan_value: Decimal, file: str) -> None:
        self.names.add(shown)
        self.result.values += 1
        if abs(sheet - plan_value) > self.tolerance:
            self.result.diffs.append(Diff(shown, period, sheet, plan_value, file))

    def grid(self, src: Source, rows: list[list[str]]) -> None:
        where = src.file
        head = _header_row(rows, src.month_column, where)
        header = rows[head]
        month_col = _column(header, src.month_column, where)
        wanted = src.months or tuple(self.plan.months())
        by_month: dict[str, list[str]] = {}
        totals: list[str] | None = None
        for row in rows[head + 1:]:
            cell = _cell(row, month_col)
            month = sheet_month(cell)
            if month in wanted:
                if month in by_month:
                    raise SheetError(f"{where}: two rows for {month}")
                by_month[month] = row
            elif src.total_row and budget.norm(cell) == budget.norm(src.total_row) and totals is None:
                totals = row
        for month in wanted:
            if month not in by_month:
                raise SheetError(f"{where}: no row for {month} under the {src.month_column!r} column")
        mapped = set()
        entries = src.targets()
        if src.total:
            entries.append(("total", "", src.total))
        for aspect, name, label in entries:
            col = _column(header, label, f"{where}, {_shown(None, aspect, name)}")
            mapped.add(col)
            item = None if aspect == "total" else _resolve(self.plan, aspect, name, f"{where}, column {label!r}")
            if aspect != "total" and item is None:
                self.result.only_sheet.append(f"{name} (column {label!r} in {where})")
                continue
            shown = _shown(item, aspect, name)
            self.covered.add((item.name if item else "", aspect))
            for month in wanted:
                value = sheet_amount(_cell(by_month[month], col), f"{where}, {label!r} for {month}")
                self.figure(shown, month, value, _plan_value(self.plan, item, aspect, month), where)
            if totals is not None and wanted == tuple(self.plan.months()):
                value = sheet_amount(_cell(totals, col), f"{where}, {label!r} in the {src.total_row!r} row")
                self.figure(shown, "year", value, _plan_value(self.plan, item, aspect, None), where)
        skipped = {budget.norm(w) for w in src.ignore}
        for col, cell in enumerate(header):
            if (col not in mapped and cell and budget.norm(cell) not in skipped
                    and any(f" {budget.norm(cell)}".endswith(f" {budget.norm(w)}") for w in src.watch)):
                self.result.only_sheet.append(f"{cell} (column in {where}, not in the map)")

    def table(self, src: Source, rows: list[list[str]]) -> None:
        where = src.file
        head = _header_row(rows, src.name_column, where)
        header = rows[head]
        name_col = _column(header, src.name_column, where)
        annual = _column(header, src.annual_column, where) if src.annual_column else None
        monthly = _column(header, src.monthly_column, where) if src.monthly_column else None
        for aspect, name, label in src.targets():
            row = next((r for r in rows[head + 1:] if budget.norm(_cell(r, name_col)) == budget.norm(label)), None)
            if row is None:
                raise SheetError(f"{where}: no row named {label!r} under the {src.name_column!r} column")
            item = _resolve(self.plan, aspect, name, f"{where}, row {label!r}")
            if item is None:
                self.result.only_sheet.append(f"{name} (row {label!r} in {where})")
                continue
            shown = _shown(item, aspect, name)
            self.covered.add((item.name, aspect))
            if annual is not None:
                value = sheet_amount(_cell(row, annual), f"{where}, {label!r} in {src.annual_column!r}")
                self.figure(shown, "year", value, _plan_value(self.plan, item, aspect, None), where)
            if monthly is not None and aspect != "planned":
                value = sheet_amount(_cell(row, monthly), f"{where}, {label!r} in {src.monthly_column!r}")
                self.figure(shown, "each month", value, usual_monthly(item), where)

    def missing(self) -> list[str]:
        """What the budget file has that no source maps: lines (or all of a parent's sub-lines), property lines,
        and each fund's transfer and, when it plans any, its planned spending."""
        out = []
        for line in self.plan.lines:
            if (line.name, "budget") in self.covered:
                continue
            for item in line.subs or [line]:
                if (item.name, "budget") not in self.covered:
                    out.append(item.name)
        out += [x.name for p in self.plan.properties for x in p.lines() if (x.name, "budget") not in self.covered]
        for fund in self.plan.funds:
            if (fund.name, "transfer") not in self.covered:
                out.append(f"{fund.name} (transfer)")
            if any(fund.planned.values()) and (fund.name, "planned") not in self.covered:
                out.append(f"{fund.name} (planned)")
        return out


def check_tables(plan: Plan, sheet_map: SheetMap, tables: dict[str, list[list[str]]]) -> Result:
    """Compare the budget file's `plan` with the exports' rows (by each source's file name) as the map reads them."""
    cmp = _Compare(plan, sheet_map.tolerance)
    for src in sheet_map.sources:
        (cmp.grid if src.kind == "month-grid" else cmp.table)(src, tables[src.file])
        if src.file not in cmp.result.files:
            cmp.result.files.append(src.file)
    cmp.result.only_taxtrace = cmp.missing()
    cmp.result.lines = len(cmp.names)
    return cmp.result


def run(folder: Path, plan: Plan, map_path: Path | None = None, sheets: tuple[Path, ...] = (),
        tolerance: Decimal | None = None) -> Result:
    """Read the map and the exports and compare them with the plan. `sheets` stands in for the map's files of the
    same name; one that matches none is an error. Nothing is written."""
    sheet_map = load_map(folder, map_path)
    if tolerance is not None:
        sheet_map.tolerance = tolerance
    paths = {src.file: sheet_map.path(src) for src in sheet_map.sources}
    for given in sheets:
        match = [file for file in paths if Path(file).name == given.name]
        if not match:
            raise SheetError(f"{given.name} isn't one of the files in {MAP_FILE}: {', '.join(sorted(paths))}")
        for file in match:
            paths[file] = given
    tables = {file: read_table(path) for file, path in paths.items()}
    result = check_tables(plan, sheet_map, tables)
    result.exported = min(datetime.fromtimestamp(p.stat().st_mtime) for p in paths.values())
    return result


def summary(folder: Path, plan: Plan | None = None) -> dict:
    """The check as the page and `status` show it: in sync, differs, or unavailable (no map or export yet, or one
    that can't be read), with the reason. Never raises."""
    try:
        plan = plan or budget.load_plan(folder)
        if plan is None:
            return {"state": "unavailable", "reason": "no budget file", "refresh": REFRESH}
        return run(folder, plan).to_json()
    except SheetMissing as err:
        return {"state": "unavailable", "reason": str(err), "refresh": REFRESH}
    except (SheetError, BudgetError, OSError) as err:
        return {"state": "unavailable", "reason": f"the check can't read its files: {err}", "refresh": REFRESH}


def count_text(n: int) -> str:
    return f"{n} difference{'' if n == 1 else 's'}"


def lines(result: Result) -> list[str]:
    """What `taxtrace budget check` prints: the counts first, then every difference. Amounts only."""
    when = f", exported {result.exported:%Y-%m-%d %H:%M}" if result.exported else ""
    out = [f"Sheet check against the budget file ({', '.join(result.files)}{when})",
           f"  {result.lines} lines compared, {result.values} figures; "
           + ("they agree" if result.in_sync else count_text(result.count))]

    def money(v: Decimal | None) -> str:
        return "—" if v is None else f"{v:,.2f}"
    if result.only_sheet:
        out.append("  only in the Sheet:")
        out += [f"    {x}" for x in result.only_sheet]
    if result.only_taxtrace:
        out.append("  only in taxtrace:")
        out += [f"    {x}" for x in result.only_taxtrace]
    if result.diffs:
        out.append(f"  {'line':<34}{'period':<12}{'sheet':>12}{'taxtrace':>12}{'difference':>12}")
        out += [f"  {d.line[:33]:<34}{d.period:<12}{money(d.sheet):>12}{money(d.taxtrace):>12}"
                f"{money(d.difference):>12}" for d in result.diffs]
    return out
