# Passive activities

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
