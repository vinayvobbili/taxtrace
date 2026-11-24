"""An invented household's budget: what `taxtrace budget init` writes to a sample folder, and the page's
"Demo data" switch. Every payee, line and amount here is made up (Initech, Globex, Umbrella and friends)."""

from __future__ import annotations

import random
from datetime import date
from decimal import Decimal
from pathlib import Path

from . import budget
from .budget import Month, Txn

SAMPLE_PLAN = """\
# A made-up household's budget for {year}: the shape of the file, to copy to budget/budget-{year}.toml and make
# your own. Amounts are per month. Groups: fixed, essentials, family, discretionary.
year = {year}
refunds = "net"   # "net": a refund lowers its line; "exclude": refunds are left out, like transfers
near = 80         # percent used that turns a line's bar amber

[[lines]]
name = "Housing"
group = "fixed"
icon = "🏠"
monthly = 3300

[[lines]]
name = "Car payment"
group = "fixed"
icon = "🚗"
monthly = 410

[[lines]]
name = "Utilities"
group = "fixed"
icon = "💡"
  [lines.basis]
  method = "the three sub-lines' bases added up"
  note = "Water and broadband are fixed bills; power moves with the seasons."
  [[lines.sub]]
  name = "Power"
  monthly = 120
  overrides = {{ "{year}-01" = 165, "{year}-07" = 155 }}
    [lines.sub.basis]
    method = "average of the last four bills, rounded up to the next 5"
    period = "{last}-09 to {last}-12"
    amount_per_month = 120
    note = "January and July run higher, so the plan overrides them."
    items = [
      {{ month = "{last}-12", payee = "Initech Power Co", amount = 131.40 }},
      {{ month = "{last}-11", payee = "Initech Power Co", amount = 109.85 }},
      {{ month = "{last}-10", payee = "Initech Power Co", amount = 112.30 }},
      {{ month = "{last}-09", payee = "Initech Power Co", amount = 122.15 }},
    ]
  [[lines.sub]]
  name = "Water"
  monthly = 55
  [[lines.sub]]
  name = "Broadband"
  monthly = 45

[[lines]]
name = "Health"
group = "fixed"
icon = "🩺"
monthly = 90

[[lines]]
name = "Phone plan"
group = "fixed"
icon = "📱"
monthly = 75

[[lines]]
name = "Groceries"
group = "essentials"
icon = "🛒"
monthly = 480
  [lines.basis]
  method = "average of the last three months, rounded up to the next 10"
  period = "{last}-10 to {last}-12"
  amount_per_month = 470
  items = [
    {{ month = "{last}-12", payee = "Globex Grocery", amount = 402.10 }},
    {{ month = "{last}-12", payee = "Soylent Market", amount = 71.60 }},
    {{ month = "{last}-11", payee = "Globex Grocery", amount = 388.45 }},
    {{ month = "{last}-11", payee = "Soylent Market", amount = 64.20 }},
    {{ month = "{last}-10", payee = "Globex Grocery", amount = 395.00 }},
    {{ month = "{last}-10", payee = "Soylent Market", amount = 80.35 }},
  ]

[[lines]]
name = "Fuel and transit"
group = "essentials"
icon = "⛽"
monthly = 135

[[lines]]
name = "Household supplies"
group = "essentials"
icon = "🧴"
monthly = 85

[[lines]]
name = "Kids' classes"
group = "family"
icon = "🎨"
monthly = 320

[[lines]]
name = "Pet care"
group = "family"
icon = "🐾"
monthly = 60

[[lines]]
name = "Dining out"
group = "discretionary"
icon = "🍽️"
monthly = 280
cap = true

[[lines]]
name = "Shopping"
group = "discretionary"
icon = "🛍️"
monthly = 330
cap = true

[[lines]]
name = "Streaming and fun"
group = "discretionary"
icon = "🎬"
  [[lines.sub]]
  name = "Umbrella Streaming"
  monthly = 18
  [[lines.sub]]
  name = "Globex Music"
  monthly = 11
  [[lines.sub]]
  name = "Games and outings"
  monthly = 66

[[funds]]
name = "Travel"
icon = "✈️"
monthly = 260
opening = 520
planned = {{ "{year}-07" = 1350, "{year}-12" = 980 }}
cap = true
  [funds.basis]
  method = "set by decision: the two trips planned for the year, spread over twelve months"
  period = "{last}"
  note = "The summer trip and the winter trip, from what the same trips cost last year."
  items = [
    {{ month = "{last}-12", payee = "Monarch Air", amount = 980.00 }},
    {{ month = "{last}-07", payee = "Monarch Air", amount = 1290.00 }},
  ]

# A rental property: its rent and costs sit apart from the household's lines, groups and totals. A cost that a sinking
# fund pays for says so with funded_by. Rent deposits are routed to the income line by a payee rule.
[[properties]]
name = "Initech Row 12"
icon = "🏘️"
  [[properties.income]]
  name = "Rent"
  icon = "💵"
  monthly = 1500
    [properties.income.basis]
    method = "the lease: rent in the signed lease, due on the first"
    period = "{last}-09 to {last}-12"
    items = [
      {{ month = "{last}-12", payee = "Initech Tenant", amount = 1500.00 }},
      {{ month = "{last}-11", payee = "Initech Tenant", amount = 1500.00 }},
    ]
  [[properties.costs]]
  name = "HOA"
  icon = "🏢"
  monthly = 90
    [properties.costs.basis]
    method = "the association's notice"
    note = "Dues are billed monthly."
  [[properties.costs]]
  name = "Property tax"
  icon = "🏛️"
  monthly = 180
  funded_by = "Rental reserve"
  [[properties.costs]]
  name = "Building policy"
  icon = "🛡️"
  monthly = 55
  funded_by = "Rental reserve"
  [[properties.costs]]
  name = "Repairs"
  icon = "🔧"
  monthly = 100
    [properties.costs.basis]
    method = "proposed: about one plumber visit every second month"
    period = "{last}"
    items = [
      {{ month = "{last}-10", payee = "Acme Plumbing", amount = 210.00 }},
      {{ month = "{last}-04", payee = "Acme Plumbing", amount = 165.00 }},
    ]
  [[properties.costs]]
  name = "Cleaning"
  icon = "🧹"
  monthly = 50

[[funds]]
name = "Rental reserve"
icon = "🏘️"
monthly = 235

[[funds]]
name = "Gifts"
icon = "🎁"
monthly = 85
planned = {{ "{year}-12" = 640 }}

[[funds]]
name = "Car repairs"
icon = "🔧"
monthly = 70
opening = 310
planned = {{ "{year}-08" = 420 }}
"""

SAMPLE_RULES = """\
# Payee rules for the made-up household: payee words -> a budget line, a sub-line or a fund. Words match whole
# words in the payee, in any case; the longest match wins. exclude = true leaves a row out (transfers, card
# payments, income, investments); one_off = true marks a row that isn't part of the usual month.
[[rules]]
match = "Initech Mortgage"
line = "Housing"

[[rules]]
match = "Vandelay Motors"
line = "Car payment"

[[rules]]
match = "Initech Power"
line = "Power"

[[rules]]
match = "Globex Water"
line = "Water"

[[rules]]
match = "Umbrella Broadband"
line = "Broadband"

[[rules]]
match = ["Vandelay Pharmacy", "Acme Clinic"]
line = "Health"

[[rules]]
match = "Kramerica Mobile"
line = "Phone plan"

[[rules]]
match = ["Globex Grocery", "Soylent Market"]
line = "Groceries"

[[rules]]
match = ["Initech Fuel", "Monarch Transit"]
line = "Fuel and transit"

[[rules]]
match = "Acme Hardware"
line = "Household supplies"

[[rules]]
match = ["Bluth Dance Studio", "Wonka Art Club"]
line = "Kids' classes"

[[rules]]
match = "Monarch Pet Care"
line = "Pet care"

[[rules]]
match = ["Soylent Diner", "Wonka Treats", "Bluth Banana Stand"]
line = "Dining out"

[[rules]]
match = ["Globex Outlet", "Kramerica Books"]
line = "Shopping"

[[rules]]
match = "Umbrella Streaming"
line = "Umbrella Streaming"

[[rules]]
match = "Globex Music"
line = "Globex Music"

[[rules]]
match = "Initech Arcade"
line = "Games and outings"

[[rules]]
match = "Monarch Air"
line = "Travel"

[[rules]]
match = "Acme Auto Repair"
line = "Car repairs"

[[rules]]
match = "Initech Tenant"
line = "Rent"

[[rules]]
match = "Initech HOA"
line = "HOA"

[[rules]]
match = "Initech Property Tax"
line = "Property tax"

[[rules]]
match = "Globex Landlord Cover"
line = "Building policy"

[[rules]]
match = "Acme Plumbing"
line = "Repairs"

[[rules]]
match = "Wonka Cleaners"
line = "Cleaning"

[[rules]]
match = ["Card Payment", "Transfer To Savings", "Initech Payroll"]
exclude = true

[[rules]]
match = "Umbrella County Tax"
exclude = true
one_off = true
"""

# One month's spending, the shape each made-up month takes: (payee, typical amount, how many a month).
MONTH_SHAPE = [
    ("Initech Mortgage", "3300.00", 1), ("Vandelay Motors", "410.00", 1), ("Initech Power", "118.40", 1),
    ("Globex Water", "52.30", 1), ("Umbrella Broadband", "45.00", 1), ("Vandelay Pharmacy", "21.75", 2),
    ("Acme Clinic", "38.50", 1), ("Kramerica Mobile", "74.10", 1), ("Globex Grocery", "88.20", 4),
    ("Soylent Market", "37.25", 2), ("Initech Fuel", "54.30", 2), ("Monarch Transit", "12.75", 2),
    ("Acme Hardware", "29.40", 2), ("Bluth Dance Studio", "245.00", 1), ("Wonka Art Club", "64.10", 1),
    ("Monarch Pet Care", "48.60", 1), ("Soylent Diner", "42.80", 3), ("Wonka Treats", "18.40", 3),
    ("Bluth Banana Stand", "9.50", 2), ("Globex Outlet", "129.99", 1), ("Kramerica Books", "24.60", 2),
    ("Umbrella Streaming", "17.99", 1), ("Globex Music", "10.99", 1), ("Initech Arcade", "31.50", 1),
    ("Initech HOA", "90.00", 1), ("Initech Property Tax", "180.00", 1), ("Globex Landlord Cover", "55.00", 1),
    ("Wonka Cleaners", "50.00", 1),
]
# Money in or moved: the rent deposit is routed to the property's Rent line by a rule; the rest isn't spending.
LEFT_OUT = [("Card Payment Thank You", "-1180.00", ("TRANSFER",)), ("Initech Payroll", "-4350.00", ("INCOME",)),
            ("Initech Tenant", "-1500.00", ("INCOME",))]
FIXED_BILLS = ("Initech Mortgage", "Vandelay Motors", "Initech HOA", "Initech Property", "Globex Landlord",
               "Wonka Cleaners")  # the same amount every month
ODD = [("Initech Kiosk", "57.80")]  # a payee no rule knows, for the unmatched count
ACCOUNTS = ["Checking ••••", "Initech Rewards card", "Globex Cash card"]


def sample_month(month: str, seed: int = 0, upto: int | None = None) -> list[Txn]:
    """A made-up month's transactions: the shape above with each amount moved a little, a refund, a pending
    row near the end, the transfers to leave out and one payee no rule knows. `upto` stops at that day."""
    rng = random.Random(f"{month}-{seed}")
    year, mon = map(int, month.split("-"))
    days = budget.days_in(month)
    last = min(days, upto) if upto else days
    rows = []
    for payee, typical, times in MONTH_SHAPE:
        for n in range(times):
            fixed = times == 1 and payee.startswith(FIXED_BILLS)
            value = Decimal(typical) if fixed else (Decimal(typical) * Decimal(rng.uniform(.72, 1.3))).quantize(
                budget.CENT)
            day = 1 + (n * days // max(times, 1) + rng.randrange(0, max(days // max(times, 1), 1))) % days
            rows.append(Txn(day=date(year, mon, day), payee=payee, amount=value, account=rng.choice(ACCOUNTS)))
    rows.append(Txn(day=date(year, mon, min(20, days)), payee="Globex Outlet", amount=Decimal("-24.99"),
                    account=ACCOUNTS[1]))
    if mon in (7, 12):
        rows.append(Txn(day=date(year, mon, 9), payee="Monarch Air", amount=Decimal(rng.randrange(380, 640)),
                        account=ACCOUNTS[1]))
    if mon == 3:
        rows.append(Txn(day=date(year, mon, 14), payee="Acme Auto Repair", amount=Decimal("186.40"),
                        account=ACCOUNTS[0]))
        rows.append(Txn(day=date(year, mon, 6), payee="Acme Plumbing", amount=Decimal("140.00"), account=ACCOUNTS[0]))
    for payee, value, flags in LEFT_OUT:
        rows.append(Txn(day=date(year, mon, 15), payee=payee, amount=Decimal(value), account=ACCOUNTS[0],
                        flags=flags))
    for payee, value in ODD:
        rows.append(Txn(day=date(year, mon, 11), payee=payee, amount=Decimal(value), account=ACCOUNTS[2]))
    rows = [t for t in rows if t.day.day <= last]
    if upto and rows:
        latest = max(rows, key=lambda t: t.day)
        latest.pending = True
    from .budget_import import stamp

    stamp(rows, "demo")
    return rows


def sample_pipe(month: str) -> str:
    """The made-up month as pipe-separated transactions, the format `taxtrace budget import` reads."""
    lines = [f"Made-up transactions for {month}: date | account | payee | category | amount | flags", ""]
    for t in sorted(sample_month(month), key=lambda t: (t.day, t.payee)):
        flags = ", ".join((*(["PENDING"] if t.pending else []), *t.flags))
        lines.append(f"{t.day.isoformat()} | {t.account} | {t.payee} |  | {t.amount} | {flags}".rstrip(" |"))
    return "\n".join(lines) + "\n"


def sample_plan(year: int) -> str:
    """The made-up plan for `year`; its basis items are last year's invented bills."""
    return SAMPLE_PLAN.format(year=year, last=year - 1)


def demo(today: date | None = None) -> tuple[budget.Plan, list[budget.Rule], dict[str, Month]]:
    """The made-up household's plan for this year, its rules, and its months up to today (today's in part)."""
    today = today or date.today()
    plan = budget.parse_plan(sample_plan(today.year))
    rules = budget.parse_rules(SAMPLE_RULES, plan)
    months = {}
    for m in range(1, today.month + 1):
        key = f"{today.year}-{m:02d}"
        months[key] = Month(month=key, txns=sample_month(key, upto=today.day if m == today.month else None))
    return plan, rules, months


def write_sample(folder: Path, year: int, force: bool = False) -> list[Path]:
    """`taxtrace budget init`: the made-up plan, rules and one month of transactions, into `folder`."""
    files = {folder / f"budget-{year}.toml": sample_plan(year), folder / budget.RULES_FILE: SAMPLE_RULES,
             folder / f"sample-transactions-{year}-01.txt": sample_pipe(f"{year}-01")}
    if not force and (existing := [p for p in files if p.exists()]):
        raise budget.BudgetError(f"{existing[0]} is already there: pass --force to write over the sample")
    folder.mkdir(parents=True, exist_ok=True)
    for path, text in files.items():
        path.write_text(text, encoding="utf-8")
    return list(files)
