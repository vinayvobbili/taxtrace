# Foreign side: India's return, bank statements, FBAR, Form 1116

## India's return

```bash
taxtrace itr 2025    # writes forms/itr-<assessment year>.json
```

A US person who sells property in India files India's ITR-2 as a non-resident: the buyer withholds TDS at
registration and the return settles it, often with a refund. `itr` reads the printed return row by row (amounts in
Indian grouping, 12,34,567):

- Schedule CG, each property: the purchase and sale dates, the consideration received, the stamp value, the cost,
  the improvements (with the financial year of each), transfer expenses, exemptions and the gain.
- Schedule OS: the interest, and how much of it is savings-account interest.
- Part B-TTI: the tax, the aggregate liability, the taxes paid (advance tax, TDS, TCS, self-assessment) and the
  refund. What India kept, the taxes paid less the refund, is what Form 1116 can credit.

India's year runs April to March (assessment year 2025-26 is April 2024 to March 2025), so a sale's own date says
which US year it belongs to. The checks: the taxes paid add up, the refund is the taxes paid less the aggregate
liability (to the nearest ten rupees, as India rounds it), the aggregate is the net liability plus interest and
fees, the TDS schedules match Part B-TTI, each sale's balance and gain add up, and the sale falls in the return's
year. Questions: an improvement's date (only its financial year is printed, and each converts to dollars at its own
day's rate), a stamp value above the price received (the US return uses the price), and whether the person owned the
whole property. Nothing that names the person is kept: no PAN, acknowledgement number or address.

## Bank statements

```bash
taxtrace bank 2025           # writes forms/bank-<last four digits>-<period start>.json
taxtrace bank --rows 2025    # also each row's date, kind and description, masked
```

An Indian branch's statement of account is a table: the date, the amount under Withdrawal or Deposit, the balance
("Cr." or "Dr."), then a description that can run onto several lines. `bank` places each word by where it sits: an
amount belongs to the column whose heading it starts under, and a description line goes with the dated row nearest
it (a description of several lines is centred on its row). Each row gets a kind: interest (its description names the
period it pays for), a tax refund, TDS withheld on interest, or a TDS refund. These give Schedule B and Form 1116 the
interest, Form 8938 and the FBAR the balances, and a cross-check that India's refund arrived.

A bank's monthly "Account Statement" is read too: a row number, dates as `05 Jan 2026`, the description left of the
amounts, Indian commas (`1,23,456.78`), an Opening Balance row and an Account Summary. Its quarterly interest is
credited net of TDS (`Int:1234.56 and TAX:123.45`), and is read as two rows, the interest and then the TDS withheld.

When only a blurred picture of a statement has arrived (a chat app shrinks what it sends past what OCR reads), type
it into a .csv next to it, each row as printed. Its balances are checked one by one like a printed statement's, and
a mistyped one isn't saved:

```text
account,000123459876
currency,INR
period,01-04-2026,27-10-2026
opening,"1,02,410.00"
date,withdrawal,deposit,balance,description
05-05-2026,,25000.00,127410.00,Cash Deposit
30-06-2026,,1234.56,128644.56,Int.Pd From:01-04-2026 to 30-06-2026
30-06-2026,123.45,,128521.11,TDS on interest
```

So is a bank's monthly e-statement of every account the customer holds there ("As on 31-01-26"): a balance summary,
the term deposits, and a page per savings account with the month's transactions (dates as `31-01-26`, amounts
right-aligned under Credit, Debit and Balance) between its opening and closing balance lines. Each account is saved as
a statement of its own, with how it's held (single, "former or survivor"). A term deposit's balance is its principal
and the interest accrued on it, and the foreign side takes its interest for the year as what that value grew by:
interest added to a cumulative deposit is income in the year it's added, though none is paid out, and a renewal
carries it into the new principal. A value that falls (TDS taken from the interest at India's year end) is asked
about. The checks: each account's balances follow from its opening balance, its closing balance is its available
balance, and the accounts add up to the balance summary.

The bank's interest certificate on its deposits ("for the financial year ended 31st March 2026") goes through `bank`
too: per account, the balance on March 31, the interest paid and accrued, and the total tax deducted, checked against
its TOTAL row. It gives what a term deposit's statements don't: the TDS taken from its interest on March 31. The
foreign side takes it as tax withheld that day (Form 1116) and as interest the value never showed, but only when it
fits the fall in the deposit's value that day (at most the fall plus a quarter's interest). Tax taken earlier in
India's year belongs to an earlier US year, so a certificate that doesn't fit is asked about, never counted whole.

India's quarterly TDS certificate (Form 16A until March 2026, Form 131 from April 2026) goes through `bank` as well:
the quarter, the bank, each payment of interest, the tax deducted and the challans that paid it to the government,
checked against their totals. India's quarters fall inside calendar quarters, so the foreign side compares each 2026
quarter's tax with the TDS it found for that bank (the statements' TDS rows and the interest certificate's): a match is
noted, and tax left over is asked about, never counted on its own: it was taken where no statement shows it. Form
26AS gives each deduction's day and account. Tax on interest credited in an earlier year (a certificate can list such
credits) still counts in the year it was taken when Form 1116 claims taxes paid, its usual box. `foreign --confirm
tds_<the quarter's last day, YYYYMMDD>=taken` then counts it once, as tax withheld on the quarter's last day and as
interest the deposit's value never showed, and `=not` leaves it out. Less tax than was found is asked about too. The
bank is matched by the name the certificate prints, from `foreign --confirm bank_<the statements' file name's first
word>=<name>; <address>`.

`taxtrace fbar --year 2026` turns the foreign side into each spouse's FBAR (FinCEN Form 114), item by item:
`<workspace>/foreign/fbar-2026.txt` is a checklist to type into the BSA e-filing form. Each account is in Part II
(held alone) or Part III (held with anyone else: its statement's mode of operation says, or `foreign --confirm
joint_<last four>=yes|no`). Its maximum value is the highest balance at the Treasury's December 31 rate, rounded up to
the dollar, and marked an estimate until the year is covered. The bank comes from `foreign --confirm
bank_<the statements' file name's first word>=<name>; <address>`. Account numbers stay out of it: they're typed in
from a statement.

The checks: each balance is the one before plus the deposit or less the withdrawal, and the rows add up to the
statement's grand totals (or, on a monthly statement, its opening and closing balances are the summary's, and its
net interest is the interest less the TDS). A statement runs on India's year (April to March), so a calendar year usually needs two.
Of the account number only its last four digits are kept, and nothing that names the holders.

## Foreign side

```bash
taxtrace foreign --year 2025                        # writes foreign/2025.json
taxtrace foreign --year 2025 --confirm owner=spouse
```

`foreign` puts a property sold abroad on Form 8949 in dollars, each amount at its own day's rate: the price at the
sale's, the cost at the purchase's, an improvement at the day it was paid. A currency that fell against the dollar
leaves a dollar gain far smaller than the gain taxed abroad (or a loss, which on a personal home isn't deductible).
The tax the other country kept, the taxes paid less the refund, goes to Form 1116 as passive category, at the rate
of the day it was withheld (a refund is translated at the rate the tax was).

Form 1116 claims taxes either paid or accrued, the box under its Part II, and last year's return shows which:
`foreign --confirm method=paid|accrued`. Accrued, once chosen, binds every later year. Paid counts each tax in the
year it was withheld, at that day's rate. Accrued counts India's tax for its year (April to March) in the US year that
year ends in, as its return for that year finally kept it, at the IRS's average rate for the US year (section 986(a)):
2026 claims the return for April 2025 to March 2026 (assessment year 2026-27). The TDS withheld during the US year is
then kept apart (`tds` in the output), since that return credits it, and the TDS from April on belongs to next year's
Form 1116.

Foreign tax the limit kept from being credited carries forward ten years. `foreign` takes it from last year's return
as `prior` read it: its Schedule B (Form 1116) line 8, per category and for the alternative minimum tax, by the year
each tax arose, is this year's Form 1116 line 10 (`carryovers` in the output). Without last year's return read, that's
a question (`--confirm carryover=none` when nothing carries). A tax in its tenth year is flagged: what this year can't
credit of it expires.

The rates are public and fetched once into `<workspace>/fx`, each kept with its source:

- a day's rate: the Federal Reserve's noon buying rate (FRED, `DEXINUS` for the rupee), or the last business day's
  before a weekend or holiday;
- a year's average, for interest: the IRS's yearly average currency exchange rates;
- December 31, for Form 8938 and the FBAR: the Treasury's Reporting Rates of Exchange.

What only you know is settled with `--confirm`, kept in `foreign/<year>-confirmed.json`: `owner=self|spouse|joint|other`
(on a joint return either spouse's sale counts in full), `improvement_dates=YYYY-MM-DD,...` (until then an
improvement is at its financial year's mean rate; `average` keeps that rate when the dates aren't known),
`use=investment|personal|rental` (asked when the dollar result is a loss), `filing=joint|single|separate|head`
(for Form 8938's thresholds) and `account_<last four digits>=self|spouse|joint` (whose an account is). Each spouse
files their own FBAR, of the accounts in their name, so the FBAR is tested per person; an account held with someone
outside the return (a parent) is yours in full. Form 8938 on a joint return takes both spouses' accounts together.

With the bank statements `bank` saved, `foreign` also gives each account's year:

- the interest credited in the calendar year, at the IRS's yearly average (Schedule B; passive income on Form 1116),
  and the TDS withheld on it at each day's rate (a tax Form 1116 credits);
- the highest balance and the balance on December 31, at the Treasury's December 31 rate, and from all accounts
  together whether the FBAR (over $10,000 at any time) and Form 8938 (by filing status, for someone living in the US)
  are due. A home held directly isn't a Form 8938 asset; the account its price was paid into is;
- India's refund found among the deposits: what arrived beyond it is India's interest on the refund, Schedule B
  income in the year it arrived.

India's statements run April to March, so a calendar year needs two. Until both are read, the days not covered are
asked for, and the FBAR and Form 8938 stay unsettled unless what's covered already crosses a threshold. While the
year is still going, its average and December 31 rates don't exist yet: the latest day's rate stands in for both,
and the FBAR and Form 8938 answers say they're estimates.
