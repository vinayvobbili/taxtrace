"""`taxtrace budget`: a household's plan for the year against what was spent, from bank and card exports.

Three kinds of file, in the workspace's budget/ folder (never read as documents, never inside a git repo):

- budget-<year>.toml, the plan: spending lines, each in a group and with a monthly budget (a month can override
  it; sub-lines can split a parent), and sinking funds with a monthly transfer, planned spending and a balance.
- rules.toml, payee rules: payee words -> a budget line or a fund, or `exclude` for what isn't spending (transfers,
  card payments, income, investments), with a one-off flag. The longest match wins.
- actuals/<yyyy-mm>.json, a month's transactions as imported (budget_import), with their per-line totals.

The functions here are plain: they take the parsed plan, rules and transactions and return the numbers the CLI and
the page show. Only load_plan, load_rules and load_actuals read files.
"""

from __future__ import annotations

import calendar
import json
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib

# The groups a line belongs to, in the order the page shows them, with their colour there.
GROUPS = {"fixed": ("Fixed bills", "blue"), "essentials": ("Daily essentials", "teal"),
          "family": ("Family", "violet"), "discretionary": ("Discretionary", "orange")}
REFUNDS = ("net", "exclude")  # a refund lowers its line, or is left out like a transfer
NEAR = 80  # percent used that turns a line's bar amber
PLAN_GLOB = "budget-[0-9][0-9][0-9][0-9].toml"
RULES_FILE = "rules.toml"
ACTUALS = "actuals"
MONTH = re.compile(r"(20\d\d)-(0[1-9]|1[0-2])")
ZERO = Decimal(0)
CENT = Decimal("0.01")
# A source's own category or flag that says a row moves money rather than spends it, when no rule matched it.
NOT_SPENDING = {"transfer", "transfers", "income", "paycheck", "payroll", "credit card payment", "card payment",
                "payment", "payments", "interest", "interest income"}


class BudgetError(ValueError):
    pass


def month_key(text: str) -> str:
    """`text` when it's a month such as 2027-03, else BudgetError."""
    if not MONTH.fullmatch(str(text)):
        raise BudgetError(f"{text!r} isn't a month: write it as YYYY-MM, such as 2027-03")
    return str(text)


def amount(value, where: str, signed: bool = False) -> Decimal:
    """A money value from a file: a number, or text such as 1,250.00. Negative only when `signed`."""
    if isinstance(value, bool):
        raise BudgetError(f"{where}: {value!r} isn't an amount")
    try:
        d = Decimal(str(value).replace(",", "").replace("$", "").strip())
    except InvalidOperation:
        raise BudgetError(f"{where}: {value!r} isn't an amount") from None
    if not d.is_finite() or (d < 0 and not signed):
        raise BudgetError(f"{where}: {value!r} isn't an amount")
    return d


def cents(d: Decimal) -> Decimal:
    return d.quantize(CENT)


def norm(text: str) -> str:
    """Lowercase words and digits only, one space apart: what payees and rules are compared on."""
    return " ".join(re.findall(r"[a-z0-9]+", text.lower()))


# -- the plan -----------------------------------------------------------------------------------------------------

@dataclass
class BasisItem:
    """One past payment a budget was worked out from."""
    month: str
    payee: str
    amount: Decimal


@dataclass
class Basis:
    """How a line's (or fund's) budget was set: the method in words, the period it covers, a note, the monthly
    figure it came to and the past payments behind it. Every part is optional."""
    method: str = ""
    period: str = ""
    note: str = ""
    amount_per_month: Decimal | None = None
    items: list[BasisItem] = field(default_factory=list)

    def total(self) -> Decimal:
        return sum((i.amount for i in self.items), ZERO)

    def to_json(self) -> dict:
        months = sorted({i.month for i in self.items})
        return {"method": self.method, "period": self.period, "note": self.note,
                "amount_per_month": _num(self.amount_per_month), "total": _num(self.total()), "months": len(months),
                "items": [{"month": i.month, "payee": i.payee, "amount": _num(i.amount)}
                          for i in sorted(self.items, key=lambda i: (i.month, i.payee.casefold()), reverse=True)]}


@dataclass
class Line:
    name: str
    group: str
    icon: str = ""
    monthly: Decimal | None = None  # None on a parent whose sub-lines carry the budget
    overrides: dict[str, Decimal] = field(default_factory=dict)
    cap: bool = False
    subs: list[Line] = field(default_factory=list)
    parent: str | None = None
    basis: Basis | None = None
    kind: str = ""  # "income" or "cost" on a rental property's line; blank on the household's own
    funded_by: str | None = None  # a property cost that a sinking fund pays for (its name), for the page to say so

    def budget(self, month: str) -> Decimal:
        if month in self.overrides:
            return self.overrides[month]
        if self.monthly is not None:
            return self.monthly
        return sum((s.budget(month) for s in self.subs), ZERO)


@dataclass
class Fund:
    name: str
    icon: str = ""
    monthly: Decimal = ZERO  # the transfer into it each month
    transfers: dict[str, Decimal] = field(default_factory=dict)  # a month's own transfer, over `monthly`
    planned: dict[str, Decimal] = field(default_factory=dict)  # what it's meant to pay, by month
    opening: Decimal = ZERO
    target: Decimal | None = None  # what it should hold; the year's transfers when not given
    cap: bool = False
    basis: Basis | None = None

    def transfer(self, month: str) -> Decimal:
        return self.transfers.get(month, self.monthly)


@dataclass
class Property:
    """A rental property: what comes in (rent) and what goes out (repairs, cleaning, tax, insurance, HOA), each a
    line like the household's, kept apart from the household's own lines, groups and totals."""
    name: str
    icon: str = ""
    income: list[Line] = field(default_factory=list)
    costs: list[Line] = field(default_factory=list)
    basis: Basis | None = None

    def lines(self) -> list[Line]:
        return [*self.income, *self.costs]

    def net(self, month: str) -> Decimal:
        """What it is meant to bring in net in `month`: the income budgeted less the costs budgeted."""
        return (sum((x.budget(month) for x in self.income), ZERO) - sum((x.budget(month) for x in self.costs), ZERO))


@dataclass
class Plan:
    year: int
    lines: list[Line]
    funds: list[Fund] = field(default_factory=list)
    refunds: str = "net"
    near: int = NEAR
    cash: dict[str, Decimal] = field(default_factory=dict)  # reachable cash planned at each month's end (optional)
    properties: list[Property] = field(default_factory=list)

    def months(self) -> list[str]:
        return [f"{self.year}-{m:02d}" for m in range(1, 13)]

    def target(self, fund: Fund) -> Decimal:
        return fund.target if fund.target is not None else sum((fund.transfer(m) for m in self.months()), ZERO)

    def yearly(self, line: Line) -> Decimal:
        return sum((line.budget(m) for m in self.months()), ZERO)

    def find(self, name: str) -> Line | Fund | None:
        """The line, sub-line, property line or fund named `name`, in any case."""
        want = name.strip().casefold()
        for line in self.lines:
            for item in (line, *line.subs):
                if item.name.casefold() == want:
                    return item
        for prop in self.properties:
            for item in prop.lines():
                if item.name.casefold() == want:
                    return item
        return next((f for f in self.funds if f.name.casefold() == want), None)

    def property(self, name: str) -> Property | None:
        want = name.strip().casefold()
        return next((p for p in self.properties if p.name.casefold() == want), None)

    def basis_targets(self) -> list[Line | Fund | Property]:
        """Everything that can carry a basis, in the file's order: lines and their sub-lines, properties and their
        lines, then funds."""
        return [*(i for line in self.lines for i in (line, *line.subs)),
                *(i for p in self.properties for i in (p, *p.lines())), *self.funds]

    def top(self, name: str) -> Line | None:
        """The top-level line that `name` (a line or a sub-line) counts toward."""
        for line in self.lines:
            if name in (line.name, *(s.name for s in line.subs)):
                return line
        return None


def _month_amounts(table, where: str) -> dict[str, Decimal]:
    if table is None:
        return {}
    if not isinstance(table, dict):
        raise BudgetError(f"{where}: write it as a table of months, such as {{ \"2027-01\" = 0 }}")
    return {month_key(k): amount(v, f"{where} {k}") for k, v in table.items()}


def _text(raw: dict, key: str, where: str) -> str:
    value = raw.get(key, "")
    if not isinstance(value, str):
        raise BudgetError(f"{where}: {key} is text, such as {key} = \"...\"")
    return value.strip()


def _basis(raw, where: str) -> Basis | None:
    """A line's or fund's `basis` table: how its budget was set, and the past payments it came from."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise BudgetError(f"{where}: basis is a table: [lines.basis] with method, period, note, amount_per_month and "
                          f"items")
    items = raw.get("items") or []
    if not isinstance(items, list):
        raise BudgetError(f"{where}: basis items is a list of {{ month = \"2026-10\", payee = \"...\", amount = 120 }}")
    out = []
    for n, item in enumerate(items, 1):
        if not isinstance(item, dict) or not str(item.get("payee", "")).strip():
            raise BudgetError(f"{where}: basis item {n} needs a month, a payee and an amount")
        out.append(BasisItem(month_key(str(item.get("month"))), str(item["payee"]).strip(),
                             amount(item.get("amount"), f"{where} basis item {n}", signed=True)))
    return Basis(method=_text(raw, "method", where), period=_text(raw, "period", where), note=_text(raw, "note", where),
                 amount_per_month=amount(raw["amount_per_month"], f"{where} basis amount_per_month")
                 if "amount_per_month" in raw else None, items=out)


def _line(raw: dict, where: str, parent: Line | None = None) -> Line:
    if not isinstance(raw, dict) or not str(raw.get("name", "")).strip():
        raise BudgetError(f"{where}: every line needs a name")
    name = str(raw["name"]).strip()
    group = parent.group if parent else str(raw.get("group", "")).strip().lower()
    if group not in GROUPS:
        raise BudgetError(f"{where} ({name}): group is one of {', '.join(GROUPS)}")
    line = Line(name=name, group=group, icon=str(raw.get("icon", "")), cap=bool(raw.get("cap", False)),
                monthly=amount(raw["monthly"], f"{name} monthly") if "monthly" in raw else None,
                overrides=_month_amounts(raw.get("overrides"), f"{name} overrides"),
                parent=parent.name if parent else None, basis=_basis(raw.get("basis"), name))
    if parent is None:
        line.subs = [_line(s, f"{name} sub-line {i + 1}", line) for i, s in enumerate(raw.get("sub") or [])]
    if line.monthly is None and not line.subs:
        raise BudgetError(f"{name}: give it a monthly budget (monthly = 250), or sub-lines that have one")
    return line


def _property_line(raw: dict, where: str, prop: str, kind: str) -> Line:
    if not isinstance(raw, dict) or not str(raw.get("name", "")).strip():
        raise BudgetError(f"{where}: every {kind} line needs a name")
    name = str(raw["name"]).strip()
    if "monthly" not in raw:
        raise BudgetError(f"{name}: give it a monthly amount (monthly = 1500)")
    funded = str(raw.get("funded_by", "")).strip() or None
    if funded and kind == "income":
        raise BudgetError(f"{name}: funded_by is for costs, not income")
    return Line(name=name, group="property", icon=str(raw.get("icon", "")), cap=bool(raw.get("cap", False)),
                monthly=amount(raw["monthly"], f"{name} monthly"),
                overrides=_month_amounts(raw.get("overrides"), f"{name} overrides"), parent=prop,
                basis=_basis(raw.get("basis"), name), kind=kind, funded_by=funded)


def _property(raw: dict, where: str) -> Property:
    """A `[[properties]]` table: a name, an `income` list (rent) and a `costs` list, each a line with a monthly
    amount, an optional `funded_by` (a sinking fund's name) and an optional basis."""
    if not isinstance(raw, dict) or not str(raw.get("name", "")).strip():
        raise BudgetError(f"{where}: every property needs a name")
    name = str(raw["name"]).strip()
    lists = {}
    for key, kind in (("income", "income"), ("costs", "cost")):
        items = raw.get(key) or []
        if not isinstance(items, list):
            raise BudgetError(f"{name}: {key} is a list of [[properties.{key}]] tables")
        lists[key] = [_property_line(r, f"{name} {key} {i + 1}", name, kind) for i, r in enumerate(items)]
    if not lists["income"] and not lists["costs"]:
        raise BudgetError(f"{name}: give the property income (rent) or costs: [[properties.income]] or "
                          f"[[properties.costs]]")
    return Property(name=name, icon=str(raw.get("icon", "")), income=lists["income"], costs=lists["costs"],
                    basis=_basis(raw.get("basis"), name))


def _fund(raw: dict, where: str) -> Fund:
    if not isinstance(raw, dict) or not str(raw.get("name", "")).strip():
        raise BudgetError(f"{where}: every fund needs a name")
    name = str(raw["name"]).strip()
    return Fund(name=name, icon=str(raw.get("icon", "")), cap=bool(raw.get("cap", False)),
                monthly=amount(raw.get("monthly", 0), f"{name} monthly"),
                transfers=_month_amounts(raw.get("transfers"), f"{name} transfers"),
                planned=_month_amounts(raw.get("planned"), f"{name} planned"),
                opening=amount(raw.get("opening", 0), f"{name} opening", signed=True),
                target=amount(raw["target"], f"{name} target") if "target" in raw else None,
                basis=_basis(raw.get("basis"), name))


def parse_plan(text: str) -> Plan:
    """A budget file's plan. BudgetError says what's wrong with one that doesn't parse or doesn't add up."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as err:
        raise BudgetError(f"the budget file isn't valid TOML: {err}") from None
    year = data.get("year")
    if not isinstance(year, int) or not 2000 <= year <= 2099:
        raise BudgetError("the budget file needs its year: year = 2027")
    refunds = str(data.get("refunds", "net"))
    if refunds not in REFUNDS:
        raise BudgetError(f"refunds is one of {', '.join(REFUNDS)}")
    near = data.get("near", NEAR)
    if not isinstance(near, int) or not 1 <= near <= 100:
        raise BudgetError("near is a percent from 1 to 100")
    plan = Plan(year=year, refunds=refunds, near=near,
                lines=[_line(raw, f"line {i + 1}") for i, raw in enumerate(data.get("lines") or [])],
                funds=[_fund(raw, f"fund {i + 1}") for i, raw in enumerate(data.get("funds") or [])],
                cash={month_key(str(r.get("month"))): amount(r.get("plan"), f"cash {r.get('month')}")
                      for r in data.get("cash") or []},
                properties=[_property(raw, f"property {i + 1}") for i, raw in enumerate(data.get("properties") or [])])
    if not plan.lines:
        raise BudgetError("the budget file has no lines: add [[lines]] tables")
    seen: set[str] = set()
    for name in [n for line in plan.lines for n in (line.name, *(s.name for s in line.subs))] + \
            [f.name for f in plan.funds] + [n for p in plan.properties for n in (p.name, *(x.name for x in p.lines()))]:
        if name.casefold() in seen:
            raise BudgetError(f"{name!r} is named twice: lines, sub-lines, properties and funds each need their own "
                              f"name")
        seen.add(name.casefold())
    funds = {f.name.casefold() for f in plan.funds}
    for prop in plan.properties:
        for x in prop.costs:
            if x.funded_by and x.funded_by.casefold() not in funds:
                raise BudgetError(f"{x.name}: funded_by {x.funded_by!r} isn't a sinking fund in the budget")
    return plan


def plan_path(folder: Path) -> Path | None:
    """The newest year's budget file in `folder`."""
    found = sorted(folder.glob(PLAN_GLOB)) if folder.is_dir() else []
    return found[-1] if found else None


def load_plan(folder: Path) -> Plan | None:
    path = plan_path(folder)
    return parse_plan(path.read_text(encoding="utf-8")) if path else None


# -- payee rules --------------------------------------------------------------------------------------------------

@dataclass(frozen=True)
class Rule:
    words: tuple[str, ...]
    line: str | None  # the line, sub-line or fund's own name; None when excluded
    exclude: bool = False
    one_off: bool = False

    def describe(self) -> str:
        target = "EXCLUDE" if self.exclude else str(self.line)
        return f"{' / '.join(self.words)} -> {target}{' ONE-OFF' if self.one_off else ''}"


def parse_rules(text: str, plan: Plan | None = None) -> list[Rule]:
    """rules.toml's rules, in file order. With the plan, each target is checked and spelt as the plan spells it."""
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as err:
        raise BudgetError(f"the rules file isn't valid TOML: {err}") from None
    rules = []
    for i, raw in enumerate(data.get("rules") or [], 1):
        match = raw.get("match")
        words = tuple(str(w).strip() for w in ([match] if isinstance(match, str) else match or []) if norm(str(w)))
        if not words:
            raise BudgetError(f"rule {i}: match is the payee's words, such as match = \"Globex Grocery\"")
        exclude, line = bool(raw.get("exclude", False)), raw.get("line")
        if not exclude and not line:
            raise BudgetError(f"rule {i} ({words[0]}): give it a line, or exclude = true")
        if line and plan is not None:
            found = plan.find(str(line))
            if found is None:
                raise BudgetError(f"rule {i} ({words[0]}): {line!r} isn't a line or fund in the budget")
            line = found.name
        rules.append(Rule(words=words, line=None if exclude else str(line), exclude=exclude,
                          one_off=bool(raw.get("one_off", False))))
    return rules


def load_rules(folder: Path, plan: Plan | None = None) -> list[Rule]:
    path = folder / RULES_FILE
    return parse_rules(path.read_text(encoding="utf-8"), plan) if path.exists() else []


def parse_rule_text(text: str) -> Rule:
    """A rule written on one line, the way `taxtrace budget rules --add` takes it: "Globex Grocery -> Groceries",
    "Acme Card Payment -> EXCLUDE", "Umbrella County Tax -> EXCLUDE ONE-OFF". Several payees: "A / B -> Line"."""
    if "->" not in text:
        raise BudgetError("write a rule as: payee words -> budget line (or EXCLUDE)")
    left, right = (s.strip() for s in text.split("->", 1))
    words = tuple(w.strip() for w in left.split(" / ") if norm(w))
    tokens = right.split()
    one_off = bool(tokens) and tokens[-1].upper() in ("ONE-OFF", "ONEOFF")
    target = " ".join(tokens[:-1] if one_off else tokens)
    if not words or not target:
        raise BudgetError("write a rule as: payee words -> budget line (or EXCLUDE)")
    exclude = target.upper() == "EXCLUDE"
    return Rule(words=words, line=None if exclude else target, exclude=exclude, one_off=one_off)


def rule_toml(rule: Rule) -> str:
    """The rule as a [[rules]] table to append to rules.toml."""
    match = json.dumps(rule.words[0] if len(rule.words) == 1 else list(rule.words), ensure_ascii=False)
    lines = ["", "[[rules]]", f"match = {match}"]
    lines.append("exclude = true" if rule.exclude else f"line = {json.dumps(rule.line, ensure_ascii=False)}")
    if rule.one_off:
        lines.append("one_off = true")
    return "\n".join(lines) + "\n"


def match_rule(rules: Iterable[Rule], payee: str) -> Rule | None:
    """The rule whose payee words appear, as whole words, in `payee`; the longest wins, then the first written."""
    text, best, best_len = f" {norm(payee)} ", None, 0
    for rule in rules:
        for words in rule.words:
            w = norm(words)
            if len(w) > best_len and f" {w} " in text:
                best, best_len = rule, len(w)
    return best


# -- transactions -------------------------------------------------------------------------------------------------

@dataclass
class Txn:
    day: date
    payee: str
    amount: Decimal  # spending is positive, a refund or credit negative
    account: str = ""
    category: str = ""  # the export's own category, when it has one
    pending: bool = False
    flags: tuple[str, ...] = ()  # the export's own markers: TRANSFER, INCOME, ONE-OFF...
    source: str = ""  # the import it came from
    id: str = ""

    def to_json(self) -> dict:
        return {"id": self.id, "date": self.day.isoformat(), "payee": self.payee, "amount": str(self.amount),
                "account": self.account, "category": self.category, "pending": self.pending,
                "flags": list(self.flags), "source": self.source}

    @classmethod
    def from_json(cls, d: dict) -> Txn:
        return cls(day=date.fromisoformat(d["date"]), payee=d["payee"], amount=Decimal(d["amount"]),
                   account=d.get("account", ""), category=d.get("category", ""), pending=bool(d.get("pending")),
                   flags=tuple(d.get("flags", ())), source=d.get("source", ""), id=d.get("id", ""))


def mask_account(label: str) -> str:
    """An account label without its digits: "Checking 4417" shows as "Checking ••••". Never an account number."""
    return re.sub(r"\d[\d\s-]{2,}\d|\d{3,}", "••••", label).strip()


@dataclass
class Sorted:
    txn: Txn
    line: str | None = None  # the line, sub-line or fund it counts toward
    fund: bool = False
    excluded: str | None = None  # why it isn't spending: "rule", "transfer", "credit", "refund"
    one_off: bool = False
    refund: bool = False
    income: bool = False  # money in, on a rental property's income line (rent): received, never spending

    @property
    def counted(self) -> bool:
        return self.line is not None and self.excluded is None

    @property
    def value(self) -> Decimal:
        """What it adds to its line: the amount, or for rent received its size whichever sign the export gave it."""
        return abs(self.txn.amount) if self.income else self.txn.amount

    @property
    def unmatched(self) -> bool:
        return self.line is None and self.excluded is None


def sort_txn(t: Txn, rules: list[Rule], plan: Plan) -> Sorted:
    """Where one transaction goes: its rule's line or fund, left out (a rule's exclude, or the export calling it a
    transfer, income or a payment), or unmatched. A negative amount on a line is a refund."""
    rule = match_rule(rules, t.payee)
    one_off = "ONE-OFF" in t.flags or bool(rule and rule.one_off)
    if rule and rule.exclude:
        return Sorted(t, excluded="rule", one_off=one_off)
    if rule:
        found = plan.find(rule.line or "")
        if found is not None:
            if getattr(found, "kind", "") == "income":
                return Sorted(t, line=found.name, one_off=one_off, income=True)
            refund = t.amount < 0
            return Sorted(t, line=found.name, fund=isinstance(found, Fund), one_off=one_off, refund=refund,
                          excluded="refund" if refund and plan.refunds == "exclude" else None)
    said = {norm(f) for f in t.flags} | {norm(t.category)}
    if said & NOT_SPENDING:
        return Sorted(t, excluded="transfer", one_off=one_off)
    if t.amount < 0:
        return Sorted(t, excluded="credit", one_off=one_off)
    return Sorted(t, one_off=one_off)


# -- the actuals store --------------------------------------------------------------------------------------------

@dataclass
class Month:
    month: str
    txns: list[Txn]
    trial: bool = False  # a try-out month before the plan's year: shown, never in the year's totals
    sources: dict[str, dict] = field(default_factory=dict)


def actuals_path(folder: Path, month: str) -> Path:
    return folder / ACTUALS / f"{month_key(month)}.json"


def load_actuals(folder: Path) -> dict[str, Month]:
    out = {}
    for path in sorted((folder / ACTUALS).glob("20[0-9][0-9]-[01][0-9].json")) if folder.is_dir() else []:
        d = json.loads(path.read_text(encoding="utf-8"))
        out[path.stem] = Month(month=path.stem, trial=bool(d.get("trial")), sources=d.get("sources", {}),
                               txns=[Txn.from_json(t) for t in d.get("transactions", [])])
    return out


def line_totals(m: Month, plan: Plan, rules: list[Rule]) -> dict[str, str]:
    """A month's spending per line, sub-line and fund, as the rules sort it now."""
    totals: dict[str, Decimal] = {}
    for s in (sort_txn(t, rules, plan) for t in m.txns):
        if s.counted:
            totals[s.line] = totals.get(s.line, ZERO) + s.value
    return {k: str(cents(v)) for k, v in sorted(totals.items())}


def save_month(folder: Path, m: Month, plan: Plan, rules: list[Rule]) -> Path:
    path = actuals_path(folder, m.month)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"month": m.month, "trial": m.trial, "sources": m.sources, "totals": line_totals(m, plan, rules),
            "transactions": [t.to_json() for t in sorted(m.txns, key=lambda t: (t.day, t.payee.lower()))]}
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


# -- status: budget against spent ---------------------------------------------------------------------------------

def days_in(month: str) -> int:
    y, m = map(int, month.split("-"))
    return calendar.monthrange(y, m)[1]


def elapsed(month: str, today: date) -> Decimal:
    """How much of `month` has gone by on `today`: 1 for a past month, 0 for a future one."""
    y, m = map(int, month.split("-"))
    if (y, m) < (today.year, today.month):
        return Decimal(1)
    if (y, m) > (today.year, today.month):
        return ZERO
    return Decimal(today.day) / Decimal(days_in(month))


def view_months(plan: Plan, view: str, today: date, actuals: dict[str, Month] | None = None) -> list[str]:
    """The months a view covers: "ytd" is the plan's year so far, up to the latest month imported when there is
    one (a month not imported yet would read as nothing spent); else the one month asked for."""
    if view != "ytd":
        return [month_key(view)]
    months = [m for m in plan.months() if elapsed(m, today) > 0]
    imported = [m for m in months if actuals and m in actuals and not actuals[m].trial]
    return [m for m in months if m <= imported[-1]] if imported else months


def default_view(plan: Plan, actuals: dict[str, Month], today: date) -> str:
    """Year to date once the plan's year has a month imported, else the latest month imported (a trial month)."""
    if any(not a.trial and a.month in view_months(plan, "ytd", today) for a in actuals.values()):
        return "ytd"
    return max(actuals) if actuals else "ytd"


def _pct(part: Decimal, whole: Decimal) -> float | None:
    return round(float(part / whole * 100), 1) if whole else None


def _num(d: Decimal | None) -> float | None:
    return None if d is None else float(cents(d))


@dataclass
class View:
    plan: Plan
    rules: list[Rule]
    actuals: dict[str, Month]
    view: str
    today: date

    @property
    def months(self) -> list[str]:
        return view_months(self.plan, self.view, self.today, self.actuals)

    def sorted_rows(self) -> list[Sorted]:
        """Every transaction in the view's months. Year to date leaves trial months out."""
        rows = []
        for month in self.months:
            m = self.actuals.get(month)
            if m and not (self.view == "ytd" and m.trial):
                rows += [sort_txn(t, self.rules, self.plan) for t in m.txns]
        return rows


def _line_json(line: Line, v: View, spent: dict[str, Decimal], counts: dict[str, int], span: Decimal,
               months: list[str]) -> dict:
    """A line's numbers, its sub-lines' spending counted in. A parent's `subs` carry the same numbers for their own
    spending, so the page can show a card per sub-line; the parent's totals stay the ones that count."""
    names = (line.name, *(s.name for s in line.subs))
    budget = sum((line.budget(m) for m in months), ZERO)
    expected = sum((line.budget(m) * elapsed(m, v.today) for m in months), ZERO)
    total = sum((spent.get(n, ZERO) for n in names), ZERO)
    pct = _pct(total, budget)
    out = {"name": line.name, "group": line.group, "icon": line.icon, "cap": line.cap,
           "monthly": _num(line.budget(months[-1])), "budget": _num(budget), "yearly": _num(v.plan.yearly(line)),
           "spent": _num(total), "remaining": _num(budget - total), "pct": pct, "pace": _pct(total, expected),
           "avg": _num(total / span) if span else None, "count": sum(counts.get(n, 0) for n in names),
           "over": total > budget, "near": pct is not None and pct >= v.plan.near and total <= budget,
           "basis": line.basis.to_json() if line.basis else None}
    if line.subs:
        subs = [{**_line_json(s, v, spent, counts, span, months), "parent": line.name} for s in line.subs]
        if spent.get(line.name):  # the parent's own payments that no sub-line took
            own = spent[line.name]
            subs.append({"name": "Not split", "parent": line.name, "group": line.group, "icon": line.icon,
                         "cap": False, "monthly": None, "budget": None, "yearly": None, "spent": _num(own),
                         "remaining": None, "pct": None, "pace": None, "avg": _num(own / span) if span else None,
                         "count": counts.get(line.name, 0), "over": False, "near": False, "unsplit": True,
                         "basis": None})
        out["subs"] = subs
    return out


def status(plan: Plan, rules: list[Rule], actuals: dict[str, Month], view: str | None = None,
           today: date | None = None) -> dict:
    """The numbers the page and `taxtrace budget status` show for a month or the year to date: per line its
    budget, spent, remaining, % used, pace against the plan so far and monthly average; the funds' balances; the
    totals by group; and the rows that aren't in a line (pending, refunds, one-offs, left out, unmatched)."""
    today = today or date.today()
    view = view or default_view(plan, actuals, today)
    v = View(plan, rules, actuals, view, today)
    months = v.months
    if not months:  # the year hasn't started: show its first month's plan
        months = [plan.months()[0]]
    span = sum((elapsed(m, today) for m in months), ZERO)
    rows = v.sorted_rows()
    spent: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    for s in rows:
        if s.counted:
            spent[s.line] = spent.get(s.line, ZERO) + s.value
            counts[s.line] = counts.get(s.line, 0) + 1
    lines = [_line_json(line, v, spent, counts, span, months) for line in plan.lines]
    funds = [_fund_json(f, v, spent, counts, months) for f in plan.funds]
    properties = [_property_json(p, v, spent, counts, span, months) for p in plan.properties]
    rental = {x.name for p in plan.properties for x in p.lines()}  # kept out of the household's own counts below

    def bucket(pick) -> dict:
        chosen = [s for s in rows if pick(s)]
        return {"count": len(chosen), "total": _num(sum((s.txn.amount for s in chosen), ZERO))}

    budget = sum((Decimal(str(x["budget"])) for x in lines), ZERO)
    total = sum((Decimal(str(x["spent"])) for x in lines), ZERO)
    expected = sum((line.budget(m) * elapsed(m, today) for line in plan.lines for m in months), ZERO)
    groups = {g: {"label": label, "colour": colour,
                  "budget": _num(sum((Decimal(str(x["budget"])) for x in lines if x["group"] == g), ZERO)),
                  "spent": _num(sum((Decimal(str(x["spent"])) for x in lines if x["group"] == g), ZERO))}
              for g, (label, colour) in GROUPS.items()}
    month_list = [{"month": k, "trial": a.trial, "rows": len(a.txns), "label": month_label(k, a.trial)}
                  for k, a in sorted(actuals.items())]
    trial = view != "ytd" and bool(actuals.get(view) and actuals[view].trial)
    return {
        "year": plan.year, "view": view, "label": view_label(plan, view, months, today, trial), "months": months,
        "elapsed": round(float(span), 2), "trial": trial, "near": plan.near, "refunds": plan.refunds,
        "today": today.isoformat(), "available": month_list,
        "totals": {"budget": _num(budget), "spent": _num(total), "remaining": _num(budget - total),
                   "pct": _pct(total, budget), "pace": _pct(total, expected), "expected": _num(expected),
                   "yearly": _num(sum((plan.yearly(line) for line in plan.lines), ZERO)),
                   "avg": _num(total / span) if span else None,
                   "monthly": _num(sum((line.budget(months[-1]) for line in plan.lines), ZERO)),
                   "over": sum(1 for x in lines if x["over"]), "near": sum(1 for x in lines if x["near"]),
                   "funds_spent": _num(sum((Decimal(str(f["spent"])) for f in funds), ZERO))},
        "groups": groups, "lines": lines, "funds": funds, "properties": properties,
        "cash": _num(plan.cash.get(months[-1])) if plan.cash.get(months[-1]) is not None else None,
        "other": {"pending": bucket(lambda s: s.txn.pending and s.counted and s.line not in rental),
                  "refunds": bucket(lambda s: s.refund and s.line not in rental),
                  "one_off": bucket(lambda s: s.one_off and s.line not in rental),
                  "excluded": bucket(lambda s: s.excluded in ("rule", "transfer", "credit")),
                  "unmatched": {**bucket(lambda s: s.unmatched),
                                "payees": len({norm(s.txn.payee) for s in rows if s.unmatched})}},
        "rows": len(rows),
    }


def _property_json(prop: Property, v: View, spent: dict[str, Decimal], counts: dict[str, int], span: Decimal,
                   months: list[str]) -> dict:
    """A rental property: its income and cost lines (each as a line's numbers, `spent` being what was received on
    an income line) and what it nets, for the months in view and for a month and a year of the plan. Kept apart
    from the household's totals."""
    def one(line: Line) -> dict:
        x = _line_json(line, v, spent, counts, span, months)
        x.update(kind=line.kind, funded_by=line.funded_by, property=prop.name)
        if line.kind == "income":  # a rent short of the plan isn't "over"; nothing about it is an alarm
            x.update(over=False, near=False)
        return x
    income, costs = [one(x) for x in prop.income], [one(x) for x in prop.costs]

    def total(items: list[dict], key: str) -> Decimal:
        return sum((Decimal(str(x[key])) for x in items), ZERO)
    plan_months = v.plan.months()
    return {"name": prop.name, "icon": prop.icon, "basis": prop.basis.to_json() if prop.basis else None,
            "income": income, "costs": costs,
            "totals": {"income_budget": _num(total(income, "budget")), "income_received": _num(total(income, "spent")),
                       "cost_budget": _num(total(costs, "budget")), "cost_spent": _num(total(costs, "spent")),
                       "net_budget": _num(total(income, "budget") - total(costs, "budget")),
                       "net": _num(total(income, "spent") - total(costs, "spent")),
                       "monthly_income": _num(sum((x.budget(months[-1]) for x in prop.income), ZERO)),
                       "monthly_costs": _num(sum((x.budget(months[-1]) for x in prop.costs), ZERO)),
                       "monthly_net": _num(prop.net(months[-1])),
                       "yearly_income": _num(sum((x.budget(m) for x in prop.income for m in plan_months), ZERO)),
                       "yearly_costs": _num(sum((x.budget(m) for x in prop.costs for m in plan_months), ZERO)),
                       "yearly_net": _num(sum((prop.net(m) for m in plan_months), ZERO))}}


def _fund_json(fund: Fund, v: View, spent: dict[str, Decimal], counts: dict[str, int], months: list[str]) -> dict:
    plan = v.plan
    target = plan.target(fund)
    in_year = months[-1] in plan.months()
    balance = None
    if in_year:
        upto = [m for m in plan.months() if m <= months[-1]]
        used = sum((sort_spent(v, fund.name, m) for m in upto), ZERO)
        balance = fund.opening + sum((fund.transfer(m) for m in upto), ZERO) - used
    total = spent.get(fund.name, ZERO)
    return {"name": fund.name, "icon": fund.icon, "cap": fund.cap, "monthly": _num(fund.transfer(months[-1])),
            "transfers": _num(sum((fund.transfer(m) for m in months), ZERO)) if in_year else None,
            "planned": _num(sum((fund.planned.get(m, ZERO) for m in months), ZERO)),
            "yearly": _num(sum((fund.transfer(m) for m in plan.months()), ZERO)),
            "spent": _num(total), "count": counts.get(fund.name, 0), "target": _num(target),
            "balance": _num(balance), "pct": _pct(balance, target) if balance is not None else None,
            "over": balance is not None and balance < 0, "basis": fund.basis.to_json() if fund.basis else None}


def sort_spent(v: View, name: str, month: str) -> Decimal:
    """What `name` (a fund) paid in one month of the plan's year, trial months left out."""
    m = v.actuals.get(month)
    if not m or m.trial:
        return ZERO
    return sum((s.txn.amount for s in (sort_txn(t, v.rules, v.plan) for t in m.txns)
                if s.counted and s.line == name), ZERO)


def month_label(month: str, trial: bool = False) -> str:
    y, m = map(int, month.split("-"))
    return f"{calendar.month_name[m]} {y}{' (trial month)' if trial else ''}"


def view_label(plan: Plan, view: str, months: list[str], today: date, trial: bool) -> str:
    if view != "ytd":
        label = month_label(view, trial)
        part = elapsed(view, today)
        return label if part in (0, 1) else f"{label}, {today.day} of {days_in(view)} days"
    if not view_months(plan, "ytd", today):
        return f"{plan.year}: the year hasn't started"
    first, last = months[0], months[-1]
    return (f"{plan.year} year to date: {calendar.month_abbr[int(first[5:])]}"
            f"{'' if first == last else ' to ' + calendar.month_abbr[int(last[5:])]}")


def payments_total(rows: list[dict], name: str) -> float | None:
    """What `payments` rows add up to, which is the card's Spent figure: the rows that count toward a line (not a
    refund that refunds = "exclude" leaves out), or every row of the "unmatched" and "excluded" buckets."""
    counted = rows if name in ("unmatched", "excluded") else [r for r in rows if not r["excluded"]]
    return _num(sum((Decimal(str(r["amount"])) for r in counted), ZERO))


def payments(plan: Plan, rules: list[Rule], actuals: dict[str, Month], view: str, name: str,
             today: date | None = None) -> list[dict]:
    """The transactions behind one line (its sub-lines too), fund, or the "unmatched" or "excluded" rows, newest
    first, with the account's digits masked."""
    v = View(plan, rules, actuals, view, today or date.today())
    line = plan.find(name)
    names = {name} if line is None else {line.name, *(s.name for s in getattr(line, "subs", []))}

    def wanted(s: Sorted) -> bool:
        if name == "unmatched":
            return s.unmatched
        if name == "excluded":
            return s.excluded is not None
        return s.line in names
    rows = [s for s in v.sorted_rows() if wanted(s)]
    rows.sort(key=lambda s: (s.txn.day, s.txn.payee.lower()), reverse=True)
    return [{"date": s.txn.day.isoformat(), "payee": s.txn.payee, "amount": _num(s.value),
             "line": s.line, "pending": s.txn.pending, "refund": s.refund, "one_off": s.one_off,
             "excluded": s.excluded, "account": mask_account(s.txn.account)} for s in rows]
