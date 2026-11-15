# The return: entry sheet, AGI, tax, year over year, North Carolina, to-dos

## Entry sheet

`taxtrace entry --year 2026` writes `entry/2026.txt`: everything the return asks for, in the order a return's interview
asks it, from what the other commands saved. Each value shows the document it came from and how far to trust it:

- **ready**: read off a final form, or worked out from them.
- **estimate**: it can still change. The year isn't over, a statement is missing, or a pay stub stands in for the W-2.
- **missing**: nothing has been read for it yet; the row names the command that fills it.

The sheet can be built at any time and only gets more complete, so run it again as documents come in, after the commands
that read them. It also lists what's still to come, by comparing the year's forms with last year's (a K-1 or 1099 that
came last year and hasn't yet, unless that K-1 was marked final), and gathers every question the other commands left open.

That comparison can't know about anything new this year, like a new brokerage account or partnership. Add those with
`--expect 1099=5678` or `--expect "1098=Acme Mortgage"` (words of the form's payer, lender, partnership, account or file
name; K-1 and W-2 work too), and each stays on the list until its form is read. Before filing, check your forms against
every account and investment you held: an empty list doesn't mean you have everything.

Names, Social Security numbers, birth dates, IP PINs and bank numbers never appear: you type those yourself. An IRA's K-1
isn't entered, since its items stay in the account. If Form 1116 has a carryover, check that your filing site takes
Schedule B (Form 1116) before relying on e-filing: not every one does.

The terminal gets each section's counts, masked. The amounts are only in the file.

## Adjusted gross income

`taxtrace agi --year 2026` adds up Form 1040's income lines from what the other commands saved: wages (1z), taxable
interest (2b), dividends (3b), capital gain (7), Schedule 1 income (8) and adjustments (10), each marked ready, estimate
or missing. It's what the state return starts from, and the sheet's check on what your filing site should come to.

For a year whose own return was filed and read with `prior`, each line is compared with it, which way and roughly how
far ("line 7 is higher than the filed return's, by $1,000 or more"), never an amount. It exits 1 when a line differs. A
K-1's section 1231 gain is on line 8 here where a preparer may use line 7, so "lines 7 and 8 together" and line 11 are the
ones that have to agree. When they don't, it says whether leaving out one or two parts (a K-1, the stock sales) would make
them match, by name only. A line nothing could test isn't counted as a match: wages taken from the filed return because no
W-2 was read, or a line with nothing on either side. The comparison stops at adjusted gross income, so a full match says
nothing about total tax, the foreign tax credit or the state return: see [Total tax](#total-tax) and
[Form D-400](#form-d-400).

## Total tax

`taxtrace tax --year 2026` writes `tax/2026.txt`: Form 1040's lines 11 to 24 and Form 1116's passive category, for a joint
or single return.

- Line 12e is the larger of the standard deduction and Schedule A (the home's mortgage interest, state and local taxes up
  to the year's cap, charity, and medical past 7.5%). It prints how far Schedule A is, in words.
- Line 13a comes from `qbi`. Line 16 follows the Qualified Dividends and Capital Gain Tax Worksheet, with the Tax Table's
  $50 bands under $100,000.
- Line 19 is the child tax credit, using `d400 --confirm children=N`. Line 23 adds the additional Medicare tax and the net
  investment income tax, as estimates until Forms 8959 and 8960 are compared.
- Line 20 is Form 1116's credit. Lines 3d and 3e count gross income, so a rental's rents and not its profit. Income taxed
  at lower rates comes out of line 18 through the Worksheet for Line 18, and a foreign gain is adjusted on line 1a. Below
  the adjustment exception's limits that's an election, and the way with the larger limit is the one taken.

The alternative minimum tax isn't worked out, and the output says so. For a filed year, `tax` compares each line and also
works each rule from the filed form's own inputs (lines 15, 16, 19 and 23, and Form 1116's 1a, 3g, 18 and 21), so a wrong
rule shows up apart from an income line that differs. Each comparison says which way and roughly how far, never an amount.

## Year over year

`taxtrace yoy --year 2026` writes `yoy/2026.txt`, the look a preparer takes before signing:

- Every W-2, 1098, 1099 and K-1 from last year that hasn't come this year, matched by tax ID so a payer's new name doesn't
  count as missing, and within a payer by account, employee or partner, so one account's form can't answer for another's.
  A K-1 marked final isn't expected again. Foreign accounts need their statements again too.
- How far each Form 1040 line moved from last year's filed return, in words: about the same under 10%, up or down 10% to
  50%, up or down more than 50%, new or gone.

It exits 1 while a document is missing, and it prints no amounts; the sheet holds them.

## Form D-400

`taxtrace d400 --year 2026` writes `d400/2026.txt`: North Carolina's Form D-400 with Schedules S and A, for a full-year
resident, following the state's D-400 and D-401 instructions:

- Additions and deductions from the NC K-1s, and interest on US obligations (a fund's share with `--confirm us_interest=`).
- The child deduction from the state's table (`--confirm children=N`).
- The larger of the standard deduction and Schedule A, whose home mortgage interest and property tax stop at $20,000
  together (`--confirm property_tax= charity= medical=`). It says when Schedule A could still win.
- The tax at the year's flat rate, the tax withheld, and estimated payments (`--confirm estimated=`).

`taxtrace prior` also reads a filed return's Schedules 1, D and E, Form 4797 and D-400, checking each form's arithmetic
and each against the others. `agi` then compares line 7 and line 8 part by part (the sales, the distributions, a sale on
Form 4797, the rental, the K-1s), and `d400` compares line by line and tests its rate from the filed taxable income. All
of it says which way and roughly how far, never an amount. Lines that can't test anything are listed apart, not counted.

North Carolina has no credit for tax paid to another country, so nothing from Form 1116 comes here. The state starts from
an older federal law, so the additions it asks for can differ from what you'd expect: check its instructions for the year.
Schedule PN (nonresidents and part-year residents) isn't covered. The 2026 standard deduction and child table are
2025's until the state's 2026 instructions come out.

## To do

```bash
taxtrace todo            # open items by due date, undated last
taxtrace todo --due      # overdue, plus what's due in the next 7 days
taxtrace todo --due 14   # ... the next 14 days
```

The list is `todo.md` at the root of the workspace, written by hand (taxtrace never reads it as a tax document).
The page shows it above the documents, in groups (overdue, today, this week, later, no date), and a card's checkbox
marks it done. A long item shows as its first sentence, without asides in parentheses, and the whole text opens below
it, so write the next step first.

```markdown
## Estimated tax
Any line that isn't an item, like this one, is ignored.
- [ ] **Thu 1/14/2027** Pay the fourth-quarter estimate, from `estimates`
  - the amount is in estimates/2026.json
  - [ ] check the account balance
- [ ] **Wed 10/28, time TBD** Call the plan administrator about the **rollover**
- [x] Order the tax software
```

An item is `- [ ] text` (open) or `- [x] text` (done) under a `## Section`. A leading bold date is its due date, with
a year (`**Fri 1/15/2027**`) or without (`**Wed 10/28**`, the date from 2 months back to 10 months ahead); undated
items are fine. Indented `  - text` lines are notes and indented `  - [ ] text` lines sub-tasks. Marking an item done
changes that line's `[ ]` to `[x]` and nothing else, and refuses if the line was edited since the page loaded.
