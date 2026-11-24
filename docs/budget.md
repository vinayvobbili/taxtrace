# Budget

`taxtrace budget` keeps a household budget against what your bank and card exports say was spent, and the page's
**Budget** tab shows it. It's separate from the return: nothing here is read as a tax document, and nothing is sent
anywhere.

## The files

Everything lives in the workspace's `budget/` folder (`~/TaxData/budget`, or under `$TAXTRACE_HOME`). taxtrace
never reads that folder as documents: the chat, the MCP tools and `taxtrace list` don't see it. Like the rest of the
workspace, it is refused inside a git repository.

- `budget-<year>.toml`, the plan: spending lines in four groups (fixed bills, daily essentials, family,
  discretionary), each with a monthly budget; a month can override it, and sub-lines can split a parent. Sinking
  funds have a monthly transfer, what they're planned to pay, an opening balance and an optional target.
- `rules.toml`, the payee rules: payee words to a line, a sub-line or a fund, or `exclude = true` for what isn't
  spending (card payments, transfers between your accounts, income, investments). `one_off = true` marks a one-off.
- `actuals/<yyyy-mm>.json`, written by `import`: a month's transactions and their per-line totals.

Raw exports are copied to a folder on this computer only, never the workspace (which you may sync):
`~/Library/Application Support/budget-private/statements/<yyyy-mm>/` on macOS, or `$TAXTRACE_BUDGET_PRIVATE`.
taxtrace refuses that folder inside the workspace or a git repository.

A plan, made up:

```toml
year = 2031
refunds = "net"   # a refund lowers its line; "exclude" leaves refunds out
near = 80         # percent used that turns a bar amber

[[lines]]
name = "Groceries"
group = "essentials"
icon = "🛒"
monthly = 480

[[lines]]
name = "Dining out"
group = "discretionary"
icon = "🍽️"
monthly = 280
cap = true

[[lines]]
name = "Utilities"
group = "fixed"
icon = "💡"
  [[lines.sub]]
  name = "Power"
  monthly = 120
  overrides = { "2031-01" = 165 }
  [[lines.sub]]
  name = "Water"
  monthly = 55

[[funds]]
name = "Travel"
icon = "✈️"
monthly = 260
opening = 520
planned = { "2031-07" = 1350 }
```

And its rules:

```toml
[[rules]]
match = ["Globex Grocery", "Soylent Market"]
line = "Groceries"

[[rules]]
match = "Initech Power"
line = "Power"

[[rules]]
match = ["Card Payment", "Initech Payroll"]
exclude = true

[[rules]]
match = "Umbrella County Tax"
exclude = true
one_off = true
```

Words match whole words in the payee, in any case, and the longest match wins: "Globex Grocery" beats "Globex".
A row no rule matches, which the export marks as a transfer, income or a payment, is left out; any other is
"unmatched", counted on its own until you write a rule for it.

## Commands

```
taxtrace budget init                                  # a made-up household in budget/sample/ to try
taxtrace budget status --dir ~/TaxData/budget/sample  # ...and what it looks like
taxtrace budget import march.csv --month 2031-03      # a month's bank or card export
taxtrace budget rules --unmatched                     # payees no rule matches yet
taxtrace budget rules --add "Globex Outlet -> Shopping"
taxtrace budget status                                # the year to date, line by line
taxtrace budget status --month 2031-03                # one month
```

- `import` reads a CSV by its column names, never by who issued it: a date, a description (or payee, merchant,
  name), and an amount or separate debit and credit columns; a status column marks pending rows. Whether spending
  is negative is read off the rows, or given with `--sign spend-negative|spend-positive`. It also reads
  pipe-separated transactions, one per line: `date | account | payee | category | amount | flags`, spending
  positive, flags such as PENDING, TRANSFER, INCOME or ONE-OFF. It prints counts only: rows read, lines skipped,
  new and already imported, pending, refunds, left out, unmatched.
- Importing the same file again changes nothing: it replaces what that file gave before, so a pending row that
  has since posted is counted once. The same rows from another file are skipped as duplicates.
- `--trial` marks a try-out month before the plan's year: it shows on its own and never in the year's totals.
- `status` prints each line's budget, spent, remaining, share used and pace (spending against the plan for the
  days gone by: 100% is on plan), with the monthly average for the year to date, then the funds' balances and the
  rows outside the lines.

## The Budget tab

`taxtrace ui`, then **Budget**. Year to date by default (once the plan's year has a month imported; until then, the
latest month), or any imported month.

- Tiles: the budget so far (and per month and per year), spent (with the monthly average), what's left, pace
  against the plan, and how many lines are over.
- "Where our money goes": spending by group as one bar, with the groups' colours: blue fixed bills, teal daily
  essentials, violet family, orange discretionary.
- A card per line, over-budget lines first: its icon, budget, spent, left, share used, a bar and a ring (green
  left, amber spent, red when over), and "Show payments", which loads that line's rows from this computer. Account
  numbers are never shown: an account's digits become ••••.
- A line with sub-lines is a heading, not a card: a full-width header with its icon, group, total budget, spent and
  left, a thin bar and the year's figure, and under it one card per sub-line, the same card as any other line in
  the group's colour, over-budget ones first, each with its own payments. Payments that match the parent but no
  sub-line get a "Not split" card (only when there are some). The tiles, the group bar and the over count use the
  parent's totals, so nothing counts twice.
- Sinking funds: each balance against its target.
- Not in the lines: pending, refunds, one-offs, what was left out and what matched no rule.
- **Demo data** shows a made-up household instead of yours, to try the screen or take a picture of it.

## Not yet

- Pasting a page of transactions copied from a website (`taxtrace budget paste`) waits for a sample of that page.
- OFX and QFX files, splitting one receipt across two lines, and paying an overspent line from a fund.
