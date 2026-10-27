# taxtrace

**Prepare a US federal and state return from your own documents, on your own machine, with every
number traced to the page it came from.**

taxtrace does not file anything. It reads a folder of your documents (W-2s, 1099s, 1098s, property
manager statements, receipts, foreign bank statements, last year's return) and produces an entry sheet
you type into consumer tax software, an FBAR account list, and a list of questions for you: anything
it couldn't settle from the documents alone.

If taxtrace helps with your return, a ⭐ on GitHub is how I know: taxtrace sends nothing home, so stars are the
only count of who uses it. If it saved you a preparer's fee, a [$1 coffee](https://ko-fi.com/vinayvobbili) says so
too.

Three rules hold everywhere:

1. **Nothing is guessed.** Every value carries the file, the page and the exact text it was read from,
   and a deterministic check rejects any value whose quote isn't on that page.
2. **Your documents never leave your machine.** Where a language model reads them (sorting documents,
   reading messy receipts), it is a local MLX model on your Mac. The chat can use a cloud model, which
   only ever sees masked text (see [Chat](#chat)).
3. **Nothing is decided silently.** A receipt that could be a repair or an improvement, a missing
   1099, a rate choice: each is a question for you, with the evidence next to it.

## Status

Early. What works today:

- `taxtrace redact`: masks a document down to its layout, so a layout can be studied (by a person or
  an AI assistant helping write a parser) without its values, names or places. Every digit becomes `#`,
  and every word the IRS's own publications don't use in lowercase becomes `*`s, so names, streets
  and towns go without anyone listing them.
- `taxtrace import`, `outline` and `unlock`: sort a preparer's export into the workspace, list the forms
  in each document, and check passwords kept in the Keychain.
- `taxtrace prior`: reads a filed return's carryforwards (see [Carryforwards](#carryforwards)).
- `taxtrace k1`: reads each Schedule K-1 (Form 1065) face, every box and code, its statements, the Schedule
  K-3, and North Carolina's D-403 NC K-1 (see [K-1s](#k-1s)).
- `taxtrace passive`: each passive activity's year and the loss it carries in (see
  [Passive activities](#passive-activities)).
- `taxtrace 1098`: reads each Form 1098 mortgage interest statement (see [Form 1098](#form-1098)).
- `taxtrace 1099`: reads the 1099-DIVs and 1099-INTs on brokers' consolidated 1099 statements (see
  [Forms 1099-DIV and 1099-INT](#forms-1099-div-and-1099-int)).
- `taxtrace rental`: puts the rental's Schedule E together, line by line (see [Schedule E](#schedule-e)).
- `taxtrace qbi`: Form 8995, the qualified business income deduction (see [Form 8995](#form-8995)).
- `taxtrace itr`: reads India's income tax return (ITR-2): a property sale, the interest, the tax India kept (see
  [India's return](#indias-return)).
- `taxtrace bank`: reads a foreign bank's statement of account: interest, a tax refund, balances (see
  [Bank statements](#bank-statements)).
- `taxtrace ui`: the workspace in the browser, with a chat (see [Chat](#chat)).

Planned, in order: the foreign side (interest at Treasury rates, foreign tax
credit, FBAR, Form 8938 check), the entry sheet, and a year-over-year check.

## Install

```bash
pip install -e ".[dev]"
```

## Use

```bash
taxtrace import ~/Downloads/portal-export.zip  # filed returns to prior-returns/, the rest by tax year
taxtrace redact ~/TaxData/prior-returns        # writes ~/TaxData/redacted/*.txt
```

A path that isn't one from where you are is looked up in the workspace: `taxtrace k1 2025` reads
`<workspace>/2025`.

`taxtrace outline <files>` lists each page's masked heading: which forms a document holds, in order (`--match
'1116|4562'` lists only the pages naming them). `taxtrace words <pdf> --page 2 --rows` shows a page's words, masked,
with where each one sits (`--x 300:450` and `--top 70:240` narrow it to a region): the geometry of a printed form, for
writing a reader of it. `--marks` adds the drawn shapes, so a checkbox ticked with a drawn mark shows. `--page
19-20,69`, `--page all` and several files take one run, so files that share a Keychain entry cost one approval.
`taxtrace show 'prior-returns/2025*' --page 19` opens a document in Chrome at a page, for you to read yourself.
A scanned PDF (pictures of pages, no text) is read through [ocrmypdf](https://ocrmypdf.readthedocs.io)
on your machine (`brew install ocrmypdf`), once: the searchable copy is kept under the original's sha256
in `<workspace>/ocr-cache`, so the text values are quoted from never shifts.

`import` takes a folder or a zip, such as a tax preparer's portal export with one folder per year. It
skips identity documents (driver's licenses, Social Security cards, passports) and anything already
imported, and records every file it places, with its sha256, in `imports.jsonl`.

Your documents and everything derived from them live in a workspace folder, `~/TaxData` or
`$TAXTRACE_HOME`, which taxtrace refuses to place inside a git repository. Names that are also
ordinary words (Will, Grace) go in `<workspace>/redact-terms.txt`, one per line.

A password-protected PDF is read with a password kept in the macOS Keychain, never in a file or on a
command line. One `default` entry covers every return that shares a password; an entry under a file's
name wins for that file, and one under the name before its first `-` covers a bank's monthly statements
(`quillbank` for `quillbank-4410-2026-01.pdf`, `quillbank-4410-2026-02.pdf`, ...). `security` asks for it
without echoing, and `-T ""` trusts no app, so macOS asks you (Allow / Deny) each time anything reads it,
taxtrace included:

```bash
security add-generic-password -s taxtrace -a default -T "" -w
security add-generic-password -s taxtrace -a "2024 Return.pdf" -T "" -w   # just this file
security add-generic-password -s taxtrace -a quillbank -T "" -w           # quillbank-*.pdf
```

Click **Allow**, not **Always Allow**: that would add the reader to the trusted list and end the prompts.

That prompt only takes the typed password. To approve each read with Apple Watch or Touch ID instead:

```bash
taxtrace keychain setup                              # the default entry and the chat's key
taxtrace keychain setup --account "2024 Return.pdf"  # and a file's own entry
```

`setup` builds a small helper (`taxtrace/macos/keychain_gate.swift`, compiled with the Xcode command line tools)
and moves each entry over to it. macOS asks for the entry the old way one last time, and the secret is never
retyped or shown. From then on the entry trusts only the helper, and the helper releases it only after macOS's
own approval: Apple Watch, Touch ID, or the password where neither is set up. Every read is still yours to allow.
Only the entries `setup` moved go through the helper; any other is read the classic way, with its one prompt. If
you deny the classic prompt during `setup`, it says so and leaves that entry as it was: run `setup` again.
Once the helper is built, store a new password with `taxtrace keychain store <name>` (a file's name, its issuer's
such as `quillbank`, or `default`): `security` asks for it unechoed, then the helper moves it over the way `setup`
does, with one classic prompt. An entry stored with a bare `security add-generic-password -T <helper>` stays
`security`'s: macOS adds its own prompt to every read the helper makes, on top of Apple Watch or Touch ID.
taxtrace reads each entry at most once per command, so a folder of returns sharing the `default` password
costs one prompt. `taxtrace unlock` says which entry opens each locked file, and how each stored password
is shaped (`aaaa99999`), never what it is. A password pdfminer turns down is tried once more with qpdf
(`brew install qpdf`), which gets it on stdin and decrypts a copy into a temporary folder for the read: when qpdf
turns it down too, the stored password is wrong, not the reader.

Another tool can read an entry `setup` moved, such as an API key it shares with the chat, without the entry
trusting that tool too:

```bash
taxtrace keychain read anthropic --for jobwatch   # the secret on stdout, once approved
```

The prompt names the item and the tool. The secret goes to the program that runs the command, never to a
terminal, and an entry `setup` didn't move isn't read this way.

When a read asks for the password instead of Apple Watch or Touch ID (a Watch out of range, asleep or locked
falls back to it), `taxtrace keychain check` says which ways macOS offers right now and why not, and
`check --try` shows one Watch / Touch ID prompt and prints what came back. Neither rebuilds the helper or touches
an entry.

Besides PDFs and text files (.txt, .csv), Word documents (.docx: one line per paragraph and per table row) and
Excel workbooks (.xlsx: a page per sheet, one line per row) are read, with Python's own zip and XML modules. A
password-protected Office file isn't read: save an unprotected copy into the workspace.

`redact`, `outline` and `unlock` with no paths read the whole workspace, leaving out what taxtrace wrote
there itself (`redacted/`, `ocr-cache/`).

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

## K-1s

```bash
taxtrace k1 2025            # every K-1 face in <workspace>/2025
taxtrace k1 2025 --layout   # also each value's text, masked, and where it sits
```

A K-1's face is a printed form: each amount sits in its box under the box's number, with its code beside it, so
read in order an amount lands next to whatever label is beside it on the page. `k1` reads by position instead. It
finds Part III's two columns by their first boxes and gives each amount to the nearest box number above it in its
column. Parts I and II are read by their labels: the EIN, the partnership, the partner (last four digits of the
TIN), each check mark, profit, loss and capital shares, liabilities, and the capital account. The values go to
`<workspace>/k1/<document>.json`, each with its page, position and exact text. The terminal gets the boxes and
codes that hold amounts, with failed checks and questions, never an amount or a name.

- Item L's capital account has to add up: beginning, plus contributions, this year's income and other changes,
  less withdrawals, is the ending balance. Each share has to be between 0% and 100%, and each amount in a box
  with codes has to have one.
- A face printed twice for the same partner counts once. The same amounts for another partner, such as a spouse,
  are that partner's own K-1.
- An IRA's K-1 (item I2 checked) is marked as one: its income stays in the account, off the return.
- An amount the face sends to the partnership's statement ("STMT", "See statement") is read from the statement
  pages after the face. A "Line 20, Code Z" or "Box 19C" reference, or a code in a box's table, ties each amount
  line under it to its box and code, with its description; a label wrapped around its amount (Statement A's
  199A grid) is put back together. Totals and item L's reconciliation, which repeat amounts given elsewhere, are
  left out. A statement amount the pages don't give is a question.
- Each Section 199A amount is marked with its kind (qualified business income, W-2 wages, UBIA, REIT dividends,
  PTP income) and the trade or business it's for. An aggregated group's totals are kept but marked as the group's,
  so they're never added in a second time, and each one has to be its businesses' amounts added up.
- A final K-1, or more than one activity (boxes 22, 23), is a question.

North Carolina's partner K-1 (Form D-403 NC K-1) is read the same way, by where things sit. Each of its eleven
lines has its amount just above the line's label, and the partnership's FEIN, the partner's number (only its last
four digits are kept) and the three Yes/No answers are read by their labels. It goes to the same folder, with where
the D-400 takes each line.

- Line 1 has to be the same partnership's federal K-1, Part III lines 1 to 11 added up, as the form says. The
  federal K-1 can be read in the same run or an earlier one; if none has been read, that's a question.
- Lines 6 to 9 are for nonresident partners and 10 and 11 for taxed partnerships: an amount there on a K-1 whose
  answers say it isn't one fails.
- Additions and deductions (lines 2, 3) and credits (line 4) are a question: the form doesn't say which Schedule S
  or D-400TC line each belongs on.

A Schedule K-3 (the partner's international items) is read for Form 1116: box E's marks for which parts apply,
and every amount in Part II (gross income and deductions by source and category), each with its line, its
country row and country code, and its column, from (a) U.S. source through the foreign categories to the total.
Part III's foreign taxes are noted.

- Each row's columns have to add up to its total, and each total line to the lines its label names ("combine
  lines 1 through 23", "subtract line 54 from line 24").
- Part II's interest, dividends, gains and section 1231 lines have to match the same partnership's K-1 boxes, and
  a K-1 whose box 16 says a K-3 is attached has to have one read, now or on an earlier run.
- The terminal says whether any of Part II is foreign source and in which categories. Foreign taxes are a question
  for now: their table isn't read yet.

## Passive activities

```bash
taxtrace passive            # the latest year of the K-1s read
taxtrace passive --year 2025
```

Form 8582 limits passive losses, and what it doesn't allow carries to the next year activity by activity. `passive`
starts from the latest return's worksheets as `prior` saved them (every activity on Worksheets 1 and 3, and what
each carries on from Worksheet 5) and goes on with this year's K-1s as `k1` saved them. It opens no document. Each
activity is matched to its partnership's K-1 by the words of its name, and its year is the K-1's boxes 1, 2, 3
and 10, less box 12. Interest, dividends and portfolio deductions aren't the activity's. A K-1 no activity matches
is a new activity. The ledger goes to `<workspace>/passive/<year>.json`; the terminal gets each activity's
masked name, where its year comes from and whether it's income or a loss, never an amount.

- An activity with no K-1 this year is a question: sold, ended, or missing from the folder? A full disposition (a
  final K-1) frees the loss it carries.
- What each activity carries in comes from last year's Worksheet 5. When last year's copy has none, its Carryover
  Worksheet's Passive Activity section printed empty means nothing carries in; failing that, last year's ledger
  (activities sold last year dropped) and the Form 8582 `passive` worked out for it. Each is a note to confirm
  against the filed Worksheet 5, and with none of them what each carries in is left unknown.
- A return whose Worksheet 5 carries losses on, followed by a return whose Carryover Worksheet lists none, is a
  question: the next year's passive income allowed them all, or they were left off and lost to every later year.
- The rental's year comes from Schedule E (`rental`), and a box 13 deduction whose code doesn't settle whether it's
  the activity's is a question.

With every activity's year and carried loss known, `passive` works the year's Form 8582 out and saves it with the
ledger:

- Each activity goes in Part IV (rental real estate with active participation: the latest return's Worksheet 1) or
  Part V (every other one, a partnership's new activity too). Line 3 adds them up; zero or more, and every loss is
  allowed.
- Part II's special allowance (up to $25,000, phased out between $100,000 and $150,000 of modified adjusted gross
  income) needs `--confirm magi=AMOUNT`; married filing separately also needs `lived_apart=yes|no`. It goes to the
  Part IV activities first (Part VI).
- The rest of line 3's loss is unallowed, shared by the activities with an overall loss in proportion to their losses
  (Part VII), and carries to next year. An activity disposed of in full at an overall loss is off the form: its
  losses, carried ones too, are allowed in full.
- Every filed return whose worksheets were read is worked out again from its own Worksheets 1 and 3 and checked
  against its Worksheet 5: the same arithmetic, rehearsed on the preparer's numbers.

The terminal says what each activity's loss does (allowed, part carried on, off the form), never how much.

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
```

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

## Chat

```bash
pip install -e ".[chat,local]"   # Claude's SDK, and the model that runs on your Mac
taxtrace ui                      # opens http://taxtrace.localhost:8766/
```

The page lists your workspace by folder and has a chat for tax rules, forms and what a document is for.
It answers with the first model in `--models` (default `claude,agy,local`) that can, and moves on to the
next when one can't (no key, quota used up, not installed):

- `claude`: Anthropic's API, with `ANTHROPIC_API_KEY` or a Keychain item holding the key (`--keychain`,
  default `anthropic`).
- `agy`: Google's [Antigravity CLI](https://antigravity.google/docs/cli), on its subscription, run in an
  empty folder.
- `local`: an MLX model on your Mac.

Claude and agy only ever see masked text. Every message, and the list of your documents, goes through the
same masking as `taxtrace redact` first: digits become `#`, and words outside the IRS's own vocabulary
become `*`s. A question with an amount in it, or a name from `redact-terms.txt`, isn't sent to them at all:
the model on your Mac answers it, and the page says why. Under each question a cloud model answered, the
page shows exactly what it was sent. The chat reads only the document list and what you type: it can't open
a document, change a file or file anything.

### Always on (macOS)

An installed app (the page added to your Dock from the browser) only works while the server is running.
To start it at login and restart it if it stops:

```bash
taxtrace service install     # same --port, --models and --keychain as `ui`
taxtrace service status      # running or not, the address, the log
taxtrace service uninstall
```

Run `install` from the shell where `TAXTRACE_HOME` is set: a login item doesn't read your shell profile,
so install writes that workspace path, and a `PATH` that finds `agy` and Homebrew's `ocrmypdf`, into
`~/Library/LaunchAgents/io.github.taxtrace.ui.plist`. No key or password goes in it; Claude's key is still
read from the Keychain. The log is `~/Library/Logs/taxtrace-ui.log`.

To install the page as an app, open http://taxtrace.localhost:8766/ in Chrome and click the install icon at
the right of the address bar (or ⋮ → Cast, save and share → Install page as app). It gets its own window and
Dock icon. `python scripts/make_icons.py` rebuilds the app's PNG icons after an SVG changes.

## Development

```bash
git config core.hooksPath .githooks   # once: every push first runs scripts/check
scripts/check                         # ruff + pytest on Python 3.10 and 3.13, as CI does
python scripts/build_vocab.py         # rebuild the redaction vocabulary from IRS publications
```

Set `PRE_PUSH_AUDIT` to a command that scans a repository for personal data and exits non-zero on a
finding, and `scripts/check` runs it too, with the repository's path appended.

Every fixture is invented: no real person, place or amount appears in this repository.
