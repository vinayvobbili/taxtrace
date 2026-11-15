# Planning: estimated tax, IRAs, a job change, stock sales, moves

## Estimated tax

```bash
taxtrace prior                                   # reads last year's Form 1040 and Carryover Worksheet
taxtrace paystub 2026/payslip.pdf                # the latest pay stub: the year's withholding, projected
taxtrace estimates --year 2026 --confirm paid_2026-09-15=2500
```

A pay stub's header row gives the pay period and the payment date, and its taxes table each tax's amount this
paycheck and the year to date ("FIT Withheld", "SIT Withheld (NC)"). The year's withholding is the year to date's
plus this paycheck's for each one left: the pay period's length says how often you're paid, and each later
paycheck is paid as long after its period ends as this one was, so a December period paid in January counts next
year. A bonus or a new W-4 changes that, so it's a question.

`taxtrace paystub --rate 47` says what each paycheck left would take home at a 47% pre-tax 401(k) deferral: this
paycheck's net pay, less the deferral's change, plus the federal withholding it moves (the percentage method: the
year's brackets past the standard deduction, on the paycheck's taxable wages times the paychecks in a year) and the
state's at its flat rate, until the year's limit stops the deferrals. The terminal gets each paycheck's take-home as
a share of this one's and the cents of take-home a deferred dollar costs; the amounts go to the file, and `--show`
prints them in your own terminal only.

No underpayment penalty is due when the year's payments reach the smaller of 90% of the year's own tax and 100%
of last year's (110% when last year's adjusted gross income was over $150,000, $75,000 married filing separately).
Last year's tax is the Carryover Worksheet's federal tax liability, or Form 1040's line 24 less line 32.

A quarter of it is due by each of April 15, June 15, September 15 and January 15, and each quarter is checked on
its own. An estimated payment counts on the day it's made, so a January payment can't make up an earlier quarter.
Withholding counts as paid evenly through the year, however late, so more withholding before December 31 makes up
every quarter, and `estimates` says how much would. Last year's overpayment applied to this year counts in April.

What only you know is kept in `estimates/<year>-confirmed.json`: `withheld=AMOUNT` (the year's federal tax
withheld in all, in place of the pay stub's projection, when there's more than one job or a 1099 withholds too), `paid_YYYY-MM-DD=AMOUNT` (each estimated payment)
and `tax=AMOUNT` (the year's own tax, once it's worked out). The terminal says which quarters are met or short;
the amounts are in `estimates/<year>.json`.

## IRAs

```bash
taxtrace ira --year 2026                       # from the latest pay stub and last year's Form 1040
taxtrace ira --year 2026 --confirm other=9000  # the year's income besides the wages, once it's known
```

A married couple filing jointly can each put the year's limit into an IRA, a spouse without pay on the other's
pay. How much of it is deductible phases out with income: over a lower range for a spouse covered by a 401(k), a
higher one for a spouse who isn't but is married to one who is. A Roth IRA has its own range. `ira` projects the
year's income from the pay stub's federal taxable wages to December 31, as they are and with the 401(k)'s room
filled (which lowers it), plus last year's interest, dividends and Schedule 1 income, and gives each spouse's
deduction and the Roth IRA's limit in both cases. The income itself is masked.

## A change of job

```bash
taxtrace jobchange --year 2026 --confirm leave=2026-12-11 --confirm start=2026-12-14 --confirm new_salary=196,000
taxtrace jobchange --year 2026 --confirm loan=12,000 --confirm loan_repaid=no   # what's kept stays for the next run
```

Two employers in a year change four things, and neither payroll knows about the other. The 401(k)'s limit is one
limit across both plans. Social Security stops at the wage base at each employer, so the new one withholds again, and
what's past the base comes back as a credit on Schedule 3 line 11. A 401(k) loan comes due on leaving: what's unpaid
is taxed, with 10% more under age 59½, unless it's repaid or the same amount is rolled over by October 15 of the next
year. And a bonus, a sign-on or a paid-out vacation is withheld at a flat 22%, whatever your bracket.

`jobchange` puts the year as it stands beside the year with the change, from the latest pay stub and last year's
other income. The cases are rough on purpose, without capital gain rates or credits: they're for comparing, and the
difference is what to read. Leaving after December 31 changes nothing on the year's return, and it says so. The
terminal gets the paychecks left and what changes, with the amounts masked.

## Stock sales

```bash
taxtrace 1099 2026                                   # reads the 1099-B on a consolidated statement too
taxtrace sales --year 2026 trades.csv                # Schedule D's totals, and any purchases in the wash-sale windows
taxtrace sales --year 2026 --confirm realized_short=-1,700   # before the 1099-B comes, from the broker's realized page
taxtrace sales --year 2026 trades.csv --confirm loss_ACME_2026-10-20=yes   # a loss to watch the window of
```

The 1099-B's sales are read under their headings (short-term or long-term, the Form 8949 box) and columns. Each one's
printed gain is checked against its proceeds and basis, and a wash sale's disallowed loss is added back. `sales` nets
the two sides with the capital gain distributions and last year's carryovers, then applies the $3,000 limit against
other income ($1,500 married filing separately): what's past it carries on, and what's under it is the room left for
more losses.

A sold loss comes undone if the same thing is bought within 30 days either side, in any account, a spouse's too. A
dividend reinvested counts. A purchase in an IRA loses the loss for good, since nothing adds it to the IRA's basis.
Give `sales` a broker's trade history (CSV) and it lists what falls inside each window, without printing symbols,
amounts or accounts to the terminal.

## The year's moves

```bash
taxtrace moves --year 2026 --confirm plan_cap=20 --confirm rental_tax=3,000 --confirm charity=500
taxtrace moves --year 2026 --confirm done_401k=yes   # kept, and shown last
```

`moves` ranks what's still open by the dollars each takes off the year's tax at your own brackets, with its deadline:
filling the 401(k) up to what the plan's percentage cap can reach in the paychecks left, stock losses up to the room
`sales` found, the rental's property tax paid by December 31 when no escrow pays it, the IRAs `ira` finds deductible,
and cash gifts to charity without itemizing (federal only, and only for giving you'd do anyway). Moves are stacked in
a fixed order, each from the income the ones before it left, so two moves in one bracket aren't counted at a rate
neither gets. `jobchange`'s findings join the list: Social Security coming back, and what an unpaid loan would cost.

The terminal gets the ranking with the amounts masked. `taxtrace ui` shows the amounts, with the job change and stock
sales beside them, in its Moves section.
