# Commands

Early. What works today:

- `taxtrace redact`: masks a document down to its layout, so a layout can be studied (by a person or
  an AI assistant helping write a parser) without its values, names or places. Every digit becomes `#`,
  and every word the IRS's own publications don't use in lowercase becomes `*`s, so names, streets
  and towns go without anyone listing them.
- `taxtrace import`, `outline` and `unlock`: sort a preparer's export into the workspace, list the forms
  in each document, and check passwords kept in the Keychain.
- `taxtrace prior`: reads a filed return's carryforwards (see [Carryforwards](https://github.com/vinayvobbili/taxtrace/blob/main/docs/carryforwards.md#carryforwards)).
- `taxtrace k1`: reads each Schedule K-1 (Form 1065) face, every box and code, its statements, the Schedule
  K-3, and North Carolina's D-403 NC K-1 (see [K-1s](https://github.com/vinayvobbili/taxtrace/blob/main/docs/k1.md#k-1s)).
- `taxtrace passive`: each passive activity's year and the loss it carries in (see
  [Passive activities](https://github.com/vinayvobbili/taxtrace/blob/main/docs/passive.md#passive-activities)).
- `taxtrace 1098`: reads each Form 1098 mortgage interest statement (see [Form 1098](https://github.com/vinayvobbili/taxtrace/blob/main/docs/forms.md#form-1098)).
- `taxtrace 1099`: reads the 1099-DIVs, 1099-INTs and 1099-Bs on brokers' consolidated 1099 statements (see
  [Forms 1099-DIV and 1099-INT](https://github.com/vinayvobbili/taxtrace/blob/main/docs/forms.md#forms-1099-div-and-1099-int) and [Stock sales](https://github.com/vinayvobbili/taxtrace/blob/main/docs/planning.md#stock-sales)).
- `taxtrace rental`: puts the rental's Schedule E together, line by line (see [Schedule E](https://github.com/vinayvobbili/taxtrace/blob/main/docs/forms.md#schedule-e)).
- `taxtrace qbi`: Form 8995, the qualified business income deduction (see [Form 8995](https://github.com/vinayvobbili/taxtrace/blob/main/docs/forms.md#form-8995)).
- `taxtrace paystub`: reads a pay stub's income tax withheld, and projects the year's (see
  [Estimated tax](https://github.com/vinayvobbili/taxtrace/blob/main/docs/planning.md#estimated-tax)).
- `taxtrace estimates`: the year's withholding and estimated payments against the safe harbor, quarter by quarter
  (see [Estimated tax](https://github.com/vinayvobbili/taxtrace/blob/main/docs/planning.md#estimated-tax)).
- `taxtrace ira`: each spouse's IRA deduction and the Roth IRA's limit at the year's projected income (see
  [IRAs](https://github.com/vinayvobbili/taxtrace/blob/main/docs/planning.md#iras)).
- `taxtrace jobchange`: the year as the pay stub projects it, against leaving one job and starting another (see
  [A change of job](https://github.com/vinayvobbili/taxtrace/blob/main/docs/planning.md#a-change-of-job)).
- `taxtrace sales`: the year's stock sales for Schedule D, the wash-sale windows, and the room left for losses (see
  [Stock sales](https://github.com/vinayvobbili/taxtrace/blob/main/docs/planning.md#stock-sales)).
- `taxtrace moves`: the year's tax-saving moves, ranked by the dollars each saves, with deadlines (see
  [The year's moves](https://github.com/vinayvobbili/taxtrace/blob/main/docs/planning.md#the-years-moves)).
- `taxtrace itr`: reads India's income tax return (ITR-2): a property sale, the interest, the tax India kept (see
  [India's return](https://github.com/vinayvobbili/taxtrace/blob/main/docs/foreign.md#indias-return)).
- `taxtrace bank`: reads a foreign bank's statement of account: interest, a tax refund, balances (see
  [Bank statements](https://github.com/vinayvobbili/taxtrace/blob/main/docs/foreign.md#bank-statements)).
- `taxtrace entry`: the year's entry sheet, to type into a filing site (see [Entry sheet](https://github.com/vinayvobbili/taxtrace/blob/main/docs/return.md#entry-sheet)).
- `taxtrace ui`: the workspace in the browser, with an Import screen (drop files in, filed as `import` files them), the entry sheet as a table and a chat (see [Chat](https://github.com/vinayvobbili/taxtrace/blob/main/docs/chat.md#chat)).

- `taxtrace agi`: the year's federal adjusted gross income, against the filed return when there is one (see
  [Adjusted gross income](https://github.com/vinayvobbili/taxtrace/blob/main/docs/return.md#adjusted-gross-income)).
- `taxtrace d400`: North Carolina's Form D-400 with Schedules S and A (see [Form D-400](https://github.com/vinayvobbili/taxtrace/blob/main/docs/return.md#form-d-400)).
- `taxtrace w2`: reads Form W-2s into the entry sheet, `agi` and `d400` (see [Form W-2](https://github.com/vinayvobbili/taxtrace/blob/main/docs/forms.md#form-w-2)).
- `taxtrace tax`: Form 1040's lines 12e to 24 with Form 1116's credit (see [Total tax](https://github.com/vinayvobbili/taxtrace/blob/main/docs/return.md#total-tax)).
- `taxtrace yoy`: a year against the one before (see [Year over year](https://github.com/vinayvobbili/taxtrace/blob/main/docs/return.md#year-over-year)).
