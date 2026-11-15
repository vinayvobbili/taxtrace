# Carryforwards

## Carryforwards

```bash
taxtrace prior            # every return in <workspace>/prior-returns
taxtrace prior --layout   # also each line a value came from, masked
taxtrace prior --words 23-26,71   # also those pages' masked words, in the same run (one Keychain approval)
```

Next year's return starts from last year's: each asset's depreciation so far, and each passive activity's loss
that couldn't be taken yet. `prior` reads them from the preparer's own printouts: the federal depreciation
schedule (Drake's "Federal Depreciation Schedule", or its "Depreciation Detail Listing", whose land rows carry
forward as cost with no depreciation) and Form 8582's Worksheets 5 and 6. Where the return prints "Next Year's
Depreciation Worksheet", each asset's deduction there is checked against a year rolled forward. The values go to `<workspace>/carryforwards/<return>.json`, each with its page and the exact
line it was read from. The terminal gets counts, failed checks and questions, masked like `redact`'s output.

Nothing is taken on trust:

- Every row is added up against the schedule's totals line, and each asset's depreciation so far against its
  basis.
- On Form 8582, each activity's ratio is checked against its share of the loss, its unallowed loss against
  its ratio of the total, and Worksheet 6 against Worksheet 5.
- Worksheets 1 and 3 list every passive activity, with income as well as loss: its net income, net loss, the
  unallowed loss it brought in, and the overall gain or loss. A row leaves the columns it doesn't use empty, so
  each amount is read by where it sits, under its column's heading. Each row has to come to its overall gain or
  loss, and the rows to the total line.
- A schedule printed twice is kept once, and a second copy that disagrees is a question.
- The alternative minimum tax and book copies are skipped. So is next year's projected schedule, which is
  checked to start from this year's accumulated depreciation.
- A Section 179, bonus or salvage amount, or business use under 100%, is a question for you, not a guess.
- Schedule B (Form 1116) gives the foreign tax carried to next year, per category of income (passive,
  general...) and again for the alternative minimum tax, by the year each tax arose: its columns are the ten
  years before this one, this year and a total. Each column's lines have to combine (line 3 is lines 1 and 2,
  line 8 is lines 3 through 7), the subtotal has to carry from page 1 to page 2, and the total has to add up its
  columns. The AMT copy's page 2 doesn't say it's the AMT copy, so it goes with the nearest page 1. A box
  left unchecked is a question. The terminal shows only the years a carryover arose in.
- The Carryover Worksheet (Drake's "List of items that will carryover to the next tax return") is read row by
  row: state and local taxes paid, the QBI loss, the foreign tax credit (regular and AMT), last year's tax for
  the estimated-tax safe harbor, each spouse's IRA basis. Its foreign tax credit has to equal Schedule B's
  carryover, and its heading has to name the next year. Anything under Passive Activity or At Risk Limitations
  is a question, since no copy seen so far had rows there. `--layout` lists each row's label and which amounts it
  has (regular, AMT, taxpayer, spouse), never the amounts.
- Form 8995 (the simplified QBI deduction) gives each business's qualified business income (line 1, continued
  on its own page past five businesses) and lines 2 to 17. Its arithmetic is checked line by line, its QBI and
  REIT/PTP losses carried on (lines 16 and 17) have to be the Carryover Worksheet's and the next year's lines 3
  and 7.
- Form 1040 gives the lines next year's estimated tax goes by: the adjusted gross income, the total tax, the
  withholding, the estimated payments, the refundable credits, the total payments, the overpayment, what of it
  went to next year, and the estimated tax penalty. Each is found by its number and words of its label, and the
  payments have to add up.
- Returns years apart are checked against each other. An asset's depreciation is rolled forward a full year
  at a time, and has to match the later return's prior depreciation. A miss says how far off it is in years
  of depreciation (0.46 years is a first, partial year left out), with no amounts. A year's foreign tax
  carried to the following year has to be the next year's carryover from the prior year, year by year.

```bash
taxtrace prior --project 2025   # roll the latest schedule forward, for returns not in hand yet
```

`--project` writes `<workspace>/carryforwards/projected-<year>.json`: each asset's depreciation for every
year since the latest return, marked as projected until that year's return arrives to confirm it.
`--layout` also shows each asset's prior and current depreciation in years. That's enough to spot a
missing or partial year without seeing an amount.
