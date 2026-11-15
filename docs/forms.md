# Forms: W-2, 1098, 1099, Schedule E, Form 8995

## Form W-2

`taxtrace w2 "2026 W-2 Initech.pdf"` writes `forms/2026 W-2 Initech.json`: boxes 1 to 8, 10, 11, 12 (each code with its
amount), 16 to 19, the state in box 15, the employer's name and EIN, and the year.

The IRS's form and a payroll company's substitute hold the same boxes in different places, so each box is found by the
words of its label, and its value under or beside that label. Two or four copies on a page, or the same form on another
page, count once. If the copies show different wages, it asks, since that may be a second employer's.

Only the last four digits of the employee's Social Security number are kept. Box 13's checkboxes and box 14 aren't read:
the entry sheet says to type box 13 from the form.

It checks that box 4 is 6.2% of box 3 and box 6 at least 1.45% of box 5, and asks about what needs another form: box 8
(allocated tips), box 10 (Form 2441), box 11, code W in box 12 (Form 8889), a second state's row, and a corrected W-2c.

The entry sheet shows the W-2's boxes in place of the pay stub's estimate, `agi` uses box 1 for wages, and `d400` uses
box 17 for the state tax withheld. Box 10's dependent care benefits follow Form 2441: what's excluded is the smallest of
the benefits, the care expenses, each spouse's earned income and the year's limit, and the rest is wages on line 1e, so
a joint return with no earned income for the spouse excludes nothing (`agi --confirm care_expenses= spouse_earned=`). The tests read the words of the IRS's own page with made-up values printed on it
(`scripts/make-w2-fixture`).

## Form 1098

```bash
taxtrace 1098 2025            # every Form 1098 in <workspace>/2025
taxtrace 1098 2025 --layout   # also each value's text, masked, and where it sits
```

A lender's 1098 is a printed form too. Each box is found by its number and the first words of its label, matched
with the spaces taken out, since a lender's print can split a word ("M ortgage"). Its value is what sits under the
label, from the box's number to the next box's label beside it or below it. The lender's TIN, the borrower's (last
four digits only), the account number and the calendar year are read by their labels. The values go to
`<workspace>/forms/<document>.json`; the terminal gets which boxes hold amounts, the checks and the questions.

- Box 1 has to be there, and has to be under 15% of box 2's principal: more is a misread, not a mortgage.
- Box 10 (other) isn't interest. What the lender prints beside it (often taxes or insurance paid from escrow)
  decides where it goes, so it's a question, as are a refund of interest (box 4), insurance premiums (box 5),
  points (box 6), more than one property (box 9) and a corrected form.
- Box 8's address, or box 7's mark, says which property the interest is for: a rental's goes on Schedule E line 12,
  a home's on Schedule A. A 1098 with neither is a question.

## Forms 1099-DIV and 1099-INT

```bash
taxtrace 1099 2025            # every consolidated 1099 statement in <workspace>/2025
taxtrace 1099 2025 --layout   # also the account and each box's label, with its value masked
taxtrace 1099 2025 --unlock   # also ask the Keychain for locked documents' passwords
```

Brokers' statements are seldom locked, so a locked document is skipped without asking the Keychain unless
`--unlock` is given: the folder's other locked files (a W-2, a return) never prompt.

A broker's consolidated statement prints each form as a column of rows under its title ("1099-DIV Dividends and
Distributions - 2025 ..."), the forms side by side: a box's id, its label, and the amount well right of the label.
A box id printed a little under its label's line is on that row. The year is the title's; the payer's TIN and the
account number are read by their labels. A statement printed twice counts once. The values go to
`<workspace>/forms/<document>.json`; the terminal gets which boxes hold amounts, the checks and the questions.

- The form's own arithmetic is checked: qualified dividends (1b), section 897 ordinary dividends (2e) and section
  199A dividends (5) are each part of the ordinary dividends (1a), and 2b, 2c, 2d and 2f part of the capital gain
  distributions (2a).
- Box 5 is Form 8995 line 6 (`qbi`).
- The boxes that change where an amount goes are questions: foreign tax paid (with box 8's country), a return of
  capital (box 3), tax withheld, liquidation distributions, exempt-interest dividends, and on a 1099-INT the early
  withdrawal penalty, Treasury interest (North Carolina doesn't tax it), tax-exempt interest and bond premium. So is
  a corrected form.

## Schedule E

```bash
taxtrace prior                 # also reads the filed returns' Schedule E: the property, lines 3 to 20, line 19's list
taxtrace 1098 2025
taxtrace rental --year 2025    # reads the answers and policies in <workspace>/2025, writes schedule-e/2025.json
```

`rental` puts one property's Part I together from what's been read, each line with where it came from:

- Rents and expenses from the answers typed into the preparer's questions ("Rental income = $1,200/month",
  "Repairs = $400/year"), under a rental heading. A month's amount is taken twelve times, and that's a question.
- Mortgage interest (line 12) from the 1098 whose box 8 is the property's address, and its box 10, when the lender's
  description says taxes or insurance paid from escrow, on line 16 or 9.
- Insurance (line 9) from the landlord policy's declarations page for the property: its annual premium. A policy new
  this year is a question: an earlier one's premium paid this year counts too.
- Depreciation (line 18) from the latest filed depreciation schedule `prior` saved, rolled forward without opening
  the return again (or `prior --project`'s, when it's newer). Rolled over more than one year, it's a question.

When the year's own return has been filed and read, each line is checked against its Schedule E: a rehearsal that
shows which lines the build and the preparer part on, and whether taxtrace's is more or less, never by how much.

What only you know is settled with `--confirm`, kept in `schedule-e/<year>-confirmed.json` for every later run:
`fair_rental_days=365`, `personal_use_days=0`, `rent_all_year=yes`, `rent=AMOUNT` (the rent every tenant paid in the
year, together, in place of the answers' monthly figure), `earlier_policy=AMOUNT` (a premium paid this year for a
policy before the one read, `0` for none), `dues=AMOUNT` (association dues, line 19), and `cleaning=AMOUNT` and
`repairs=AMOUNT` (the year's receipts added up, lines 7 and 14, a repair a tenant paid out of the rent among them).

A document goes with the property when its address has the same house number and street. A line the latest filed
Schedule E had that this year has nothing for (association dues on line 19) is a question, as are the fair rental
and personal use days. Locked documents are skipped without a Keychain prompt: answers and policies aren't locked.

## Form 8995

```bash
taxtrace qbi --year 2025            # writes qbi/2025.json from what k1, rental and prior saved
taxtrace qbi --year 2025 --layout   # also each K-1's Section 199A statement rows: what each is and its sign
taxtrace qbi --year 2025 --confirm k1_4567=business --confirm rental=not
```

`qbi` puts the simplified Form 8995 together from what's been saved, opening no document:

- Each partnership's qualified business income is its K-1's passive income or loss (boxes 1, 2, 3 and 10, less 12),
  the figure a preparer's Form 8995 carries, rather than the Section 199A statement's own total.
- The rental's is Schedule E's net from `rental`.
- A passive loss Form 8582 doesn't allow isn't qualified business income until a later year allows it. Each
  activity's amount is what the year's Form 8582 let through (its overall gain or loss, less what it carried on):
  the filed one when the year's return is read, otherwise the one `passive` worked out. With neither, the amounts
  are before that limit, and that's a question.
- Which businesses count follows last year's filed Form 8995: a partnership it listed (by its EIN's last four
  digits) that has income or a loss this year, and the rental if it listed a Schedule E. One it didn't list is a
  question for `--confirm k1_<last four>=business|not` (or `rental=`), kept in `qbi/<year>-confirmed.json`.
- Line 6 is the K-1s' REIT dividends and PTP income and the year's 1099-DIVs' section 199A dividends (box 5, from
  `taxtrace 1099`). Last year's losses carried on (lines 16 and 17) come in on lines 3 and 7. Lines 11 to 15 need taxable income, so
  the deduction is known only when line 10 is zero. The threshold for the simplified form follows the filing status
  `foreign --confirm filing=` kept; above it Form 8995-A applies, which taxtrace doesn't do yet.

When the year's own return has been filed and read, every line and business is checked against its Form 8995. A
business whose amount disagrees names the other figure the filed one matches (the Section 199A statement's total,
an aggregated group's, the filed Schedule E's net), so a rehearsal shows where a build and the preparer part ways.
The terminal gets which businesses are income or a loss, the checks and the questions, never an amount.
