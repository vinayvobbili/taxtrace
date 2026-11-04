"""A year's entry sheet: everything the return asks for, section by section, for typing into a filing site.

taxtrace files nothing. This puts what the other commands saved in the order a return's interview asks for it, each
value with the document it came from and how far it can be trusted:

- ready: read off a final form, or worked out from them.
- estimate: it can still change, because the year isn't over, a statement is missing, or a pay stub stands in for the
  W-2.
- missing: nothing has been read for it yet; the row says which command fills it.

The sheet can be built at any time and only gets more complete. Run it again as documents come in, after the commands
that read them. "Still to come" compares the forms read for the year with last year's: a K-1 or 1099 that came last
year and hasn't yet this year, without a final K-1 to say it's over. What the person types themselves (names, Social
Security numbers, birth dates, IP PINs, bank numbers) never appears.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal

from . import estimates, paystub, qbi, schedule_e

READY, ESTIMATE, MISSING = "ready", "estimate", "missing"
YOURSELF = ("Type these yourself, they aren't on this sheet: names, Social Security numbers, birth dates, this year's "
            "IP PINs and your bank's numbers.")
SCHEDULE_B_1116 = ("A carryover needs Schedule B (Form 1116): check that the filing site takes it before relying on "
                   "e-filing. If it can't, the return can still be mailed.")
COMING_NOTE = ("This list holds only what came last year and what `--expect` added, so anything new this year isn't on "
               "it unless you add it. Before filing, check your forms against every account and investment you held.")
EXPECTS = {"1098": ("1098",), "1099": ("1099-INT", "1099-DIV", "1099-B"), "K-1": (), "W-2": ("W-2",)}
IDENTIFIERS = ("lender", "lender_tin", "payer_tin", "account", "partnership", "ein", "file")


@dataclass
class Row:
    what: str
    value: str = ""
    status: str = READY
    source: str = ""


@dataclass
class Section:
    title: str
    rows: list[Row] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def add(self, what: str, value: object = "", status: str = READY, source: str = "") -> None:
        self.rows.append(Row(what, money(value), status, source))

    def count(self, status: str) -> int:
        return sum(r.status == status for r in self.rows)


@dataclass
class Sheet:
    year: int
    sections: list[Section] = field(default_factory=list)
    coming: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)

    def count(self, status: str) -> int:
        return sum(s.count(status) for s in self.sections)

    def to_json(self) -> dict:
        return asdict(self)


def expectation(spec: str) -> str:
    """'1098=Acme Mortgage', '1099=5678', 'K-1=Umbrella': a form to wait for, by words of its payer, account or file."""
    kind, sep, words = (s.strip() for s in spec.partition("="))
    if not sep or not words or kind.upper() not in EXPECTS:
        raise ValueError(f"--expect takes KIND=WORDS, with KIND one of {', '.join(EXPECTS)}: words of the form's "
                         "payer, lender, partnership, account or file name")
    return f"{kind.upper()}={words}"


def _plain(text: str) -> str:
    return text.lower().replace("-", "").replace(" ", "")


def _arrived(spec: str, year: int, forms: list[dict], k1s: list[dict]) -> bool:
    """Whether a form of the kind expected has been read for the year, with the words in one of its identifiers."""
    kind, _, words = spec.partition("=")
    rows = qbi.faces(k1s, year) if kind == "K-1" else [f for f in forms if f.get("form") in EXPECTS[kind]
                                                       and f.get("year") == year]
    return any(_plain(words) in _plain(str(f.get(key) or "")) for f in rows for key in IDENTIFIERS)


def money(value: object) -> str:
    """A Decimal, or a string that is one, as "1,234.50"; anything else as it is."""
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
    return str(value)


def _dollars(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _where(saved: dict, page: object = None) -> str:
    file, page = saved.get("file", ""), page if page is not None else saved.get("page")
    return f"{file} p{page}" if file and page else file


def build(year: int, *, forms: list[dict], k1s: list[dict], returns: list[dict], filing: str = "",
          rental: dict | None = None, found: dict | None = None, sales: dict | None = None,
          passive: dict | None = None, form_8995: dict | None = None, plan: dict | None = None,
          moves: dict | None = None, today: date | None = None, expected: list[str] | None = None,
          nc: dict | None = None, federal: dict | None = None) -> Sheet:
    """The year's sheet from what the other commands saved: `forms` and `k1s` hold every year's, the rest are the
    year's own (`rental`, `foreign`, `sales`, `passive`, `qbi`, `estimates`, `moves`, `d400` and `agi`), None when not
    run yet. `expected` is the forms the person said to wait for (`expectation`), new this year or otherwise."""
    today = today or date.today()
    sheet = Sheet(year)
    done = today.year > year
    sheet.sections.append(_personal(year, filing, returns))
    sheet.sections += _w2s(forms, year) or [_wages(year, forms)]
    sheet.sections += _information(forms, year, "1099-INT", "Interest")
    sheet.sections += _information(forms, year, "1099-DIV", "Dividends")
    sheet.sections.append(_sales(sales, found))
    sheet.sections.append(_foreign_interest(found))
    sheet.sections.append(_foreign_tax(found, forms, year))
    sheet.sections.append(_rental(rental, done))
    sheet.sections += _k1s(k1s, year)
    sheet.sections.append(_passive(passive))
    sheet.sections.append(_qbi(form_8995))
    sheet.sections.append(_deductions(forms, year, rental, moves))
    sheet.sections.append(_payments(plan))
    sheet.sections.append(_north_carolina(k1s, year, nc))
    sheet.sections.append(_checks(federal, nc))
    sheet.coming = _coming(year, forms, k1s, found)
    sheet.coming += [f"{spec.replace('=', ': ', 1)} (you said to expect it)" for spec in expected or []
                     if not _arrived(spec, year, forms, k1s)]
    sheet.questions = _questions(rental=rental, foreign=found, sales=sales, passive=passive, qbi=form_8995)
    return sheet


def _personal(year: int, filing: str, returns: list[dict]) -> Section:
    s = Section("Filing status and last year", notes=[YOURSELF])
    s.add("Filing status", filing, READY if filing else MISSING,
          "" if filing else "`taxtrace foreign --confirm filing=`")
    lines = next(((r.get("f1040") or {}).get("lines", {}) for r in returns
                  if r.get("year") == year - 1 and r.get("f1040")), {})
    agi = next((lines[k] for k in ("11", "11b", "11a") if k in lines), None)
    if agi is None:
        s.add(f"{year - 1} adjusted gross income, to sign the e-file", "", MISSING, "`taxtrace prior`")
    else:
        s.add(f"{year - 1} adjusted gross income, to sign the e-file", _dollars(agi), READY,
              f"the filed {year - 1} Form 1040")
    return s


def _w2s(forms: list[dict], year: int) -> list[Section]:
    """One section per W-2, its boxes as printed."""
    out = []
    for f in _year_forms(forms, year, "W-2"):
        s = Section(f"Wages (Form W-2), {f.get('employer') or '?'}, EIN {f.get('ein') or '?'}")
        for box, value in f.get("amounts", {}).items():
            state = f"{f.get('state')}, " if box in ("16", "17") and f.get("state") else ""
            s.add(f"Box {box}, {state}{value.get('label', '')}", _dollars(value.get("amount")), READY,
                  _where(f, value.get("page")))
        for code, value in f.get("box_12", {}).items():
            s.add(f"Box 12 code {code}", _dollars(value.get("amount")), READY, _where(f, value.get("page")))
        s.notes.append("Box 13's checkboxes aren't read: type them from the form.")
        out.append(s)
    return out


def _wages(year: int, forms: list[dict]) -> Section:
    s = Section("Wages (Form W-2)")
    stub = estimates.latest_stub(forms, year)
    if stub is None:
        s.add("Box 1, wages", "", MISSING, "`taxtrace paystub`, until the W-2 comes")
        return s
    read = paystub.from_json(stub)
    file = stub.get("file", "")
    s.notes.append("Projected from the latest pay stub to December 31: the W-2 replaces every figure here.")
    if (wages := read.projected_wages()) is not None:
        s.add("Box 1, wages", wages, ESTIMATE, file)
    if (federal := read.projected()) is not None:
        s.add("Box 2, federal income tax withheld", federal, ESTIMATE, file)
    if (state := read.projected("state")) is not None:
        s.add(f"Box 17, {read.state or 'state'} income tax withheld", state, ESTIMATE, file)
    left = read.paychecks_left()
    for kind, code in (("pretax", "D"), ("roth", "AA")):
        if d := read.deferred.get(kind):
            s.add(f"Box 12 code {code}, 401(k) deferrals", d.year_to_date + d.current * left, ESTIMATE, file)
    return s


def _year_forms(forms: list[dict], year: int, kind: str) -> list[dict]:
    return [f for f in forms if f.get("form") == kind and f.get("year") == year and f.get("copy_of") is None]


def _information(forms: list[dict], year: int, kind: str, name: str) -> list[Section]:
    """One section per 1099, its boxes as printed."""
    out = []
    for f in _year_forms(forms, year, kind):
        s = Section(f"{name} ({kind}), payer {f.get('payer_tin') or '?'}, account {f.get('account') or '?'}")
        for box, value in f.get("amounts", {}).items():
            amount = _dollars(value.get("amount"))
            if amount:
                s.add(f"Box {box}, {value.get('label', '')}".rstrip(", "), amount, READY, _where(f, value.get("page")))
        for box, words in f.get("words", {}).items():
            s.add(f"Box {box}", words, READY, _where(f))
        if f.get("corrected"):
            s.notes.append("This is a corrected form.")
        if kind == "1099-DIV" and "7" in f.get("amounts", {}):
            s.notes.append("Box 7 goes to the foreign tax credit as well, in the passive category.")
        out.append(s)
    return out


def _sales(sales: dict | None, found: dict | None) -> Section:
    s = Section("Stock and property sales (Form 8949, Schedule D)")
    if sales is None or not (sales.get("from_forms") or sales.get("boxes")):
        s.add("Sales on 1099-Bs", "", MISSING, "`taxtrace 1099`, then `taxtrace sales`")
    if sales is not None:
        status = READY if sales.get("from_forms") else ESTIMATE
        source = "the 1099-Bs" if sales.get("from_forms") else "what's confirmed, until the 1099-Bs come"
        for box, row in sales.get("boxes", {}).items():
            for key, label in (("proceeds", "proceeds"), ("basis", "cost basis"), ("wash", "wash sale adjustment")):
                if key in row and (key != "wash" or _dollars(row[key])):
                    s.add(f"Form 8949 box {box}: {label}", _dollars(row[key]), status, source)
        for key, label in (("carry_short", "short-term"), ("carry_long", "long-term")):
            if _dollars(sales.get(key)):
                s.add(f"Capital loss carried in, {label}", _dollars(sales[key]), READY, "last year's return")
    for sale in (found or {}).get("sales", []):
        file = sale.get("file", "")
        s.add(f"Sale abroad: {sale.get('description', '')}, {sale.get('term', '')}-term, bought "
              f"{sale.get('acquired', '')}, sold {sale.get('sold', '')}: proceeds",
              _dollars(sale["proceeds"]["dollars"]), READY, file)
        s.add(f"Sale abroad: {sale.get('description', '')}: cost basis", _dollars(sale["basis"]), READY, file)
    return s


def _foreign_interest(found: dict | None) -> Section:
    s = Section("Foreign interest and accounts (Schedule B, Form 8938)")
    if found is None:
        s.add("Foreign interest", "", MISSING, "`taxtrace foreign`")
        return s
    estimated = found.get("estimated")
    for a in found.get("accounts", []):
        if interest := a.get("interest"):
            status = ESTIMATE if estimated or a.get("missing") else READY
            s.add(f"Interest, {a.get('country', '')} account ending {a.get('account', '')}",
                  _dollars(interest["dollars"]), status, ", ".join(a.get("files", [])[:1]))
    for r in found.get("refunds", []):
        if r.get("interest"):
            s.add(f"Interest on {r.get('country', '')}'s tax refund", _dollars(r["interest"]["dollars"]), READY,
                  r.get("file", ""))
    for c in found.get("withheld", []):
        s.add(c.get("what", "Interest taken as tax"), _dollars(c["dollars"]), READY, "")
    if found.get("accounts"):
        s.add("Schedule B line 7a: a foreign account in the year", "Yes", READY, "")
        s.add("Schedule B line 7b: country", ", ".join(sorted({a.get("country", "") for a in found["accounts"]})),
              READY, "")
    reporting = found.get("reporting", {})
    if "form_8938" in reporting:
        due = {True: "Due", False: "Not due"}.get(reporting["form_8938"], "")
        s.add("Form 8938", due or "Not settled yet", READY if due else ESTIMATE, "")
    if estimated:
        s.notes.append("The year's exchange rates aren't out: these are at the latest day's rate.")
    return s


def _foreign_tax(found: dict | None, forms: list[dict], year: int) -> Section:
    s = Section("Foreign tax credit (Form 1116)")
    if found is None:
        s.add("Foreign tax", "", MISSING, "`taxtrace foreign`")
        return s
    s.add("Taxes paid or accrued", found.get("method", "paid"), READY, "")
    estimated = found.get("estimated")
    for t in found.get("taxes", []):
        s.add(f"{t.get('country', '')}, {t.get('category', '')} category", _dollars(t["kept"]["dollars"]),
              ESTIMATE if estimated else READY, t.get("file", ""))
    if not found.get("taxes"):
        s.add("Foreign tax for the year", "", MISSING, "`taxtrace itr`, then `taxtrace foreign`")
    for c in found.get("carryovers", []):
        total = sum((Decimal(str(v)) for v in c.get("years", {}).values()), Decimal(0))
        years = ", ".join(sorted(str(y) for y in c.get("years", {})))
        s.add(f"Carryover{' (AMT)' if c.get('amt') else ''}, {c.get('category', '')} category, from {years}", total,
              READY, c.get("file", ""))
    if found.get("carryovers"):
        s.notes.append(SCHEDULE_B_1116)
    if found.get("method") == "accrued" and found.get("tds"):
        s.notes.append("Taxes accrued: the year's withholding abroad isn't entered, the foreign return's tax is.")
    for f in _year_forms(forms, year, "1099-DIV"):
        if tax := _dollars((f.get("amounts", {}).get("7") or {}).get("amount")):
            s.add("Foreign tax on a 1099-DIV, passive category", tax, READY, _where(f))
    return s


def _rental(rental: dict | None, year_over: bool) -> Section:
    s = Section("Rental (Schedule E)")
    if rental is None:
        s.add("The rental", "", MISSING, "`taxtrace rental`")
        return s
    status = READY if year_over else ESTIMATE
    if not year_over:
        s.notes.append("The year isn't over: rent and expenses can still change.")
    s.add("Property", rental.get("address", ""), READY, "")
    for key, label in (("fair_rental_days", "Fair rental days"), ("personal_use_days", "Personal use days")):
        if rental.get(key) is not None:
            s.add(label, rental[key], READY, "")
    for n, line in sorted(rental.get("lines", {}).items(), key=lambda kv: int(kv[0])):
        label = schedule_e.LINES.get(int(n), "")
        s.add(f"Line {n}, {label}", _dollars(line["amount"]), status, line.get("source", ""))
    for line in rental.get("other", []):
        s.add(f"Line 19 statement: {line.get('what', '')}", _dollars(line["amount"]), status, line.get("source", ""))
    if "income_or_loss" in rental:
        s.add("Check: income or loss the site should show", _dollars(rental["income_or_loss"]), status, "")
    return s


def _k1s(k1s: list[dict], year: int) -> list[Section]:
    """One section per federal K-1: the face's boxes and its statements' rows, a group's totals left out because
    its members' rows are there. An IRA's K-1 isn't entered: its items stay in the account."""
    out = []
    for f in qbi.faces(k1s, year):
        s = Section(f"K-1: {f.get('partnership') or f.get('file', '')}, EIN {f.get('ein') or '?'}")
        if f.get("final"):
            s.add("Final K-1", "Yes", READY, _where(f))
        if f.get("publicly_traded"):
            s.add("Publicly traded partnership", "Yes", READY, _where(f))
        for item in f.get("items", []):
            value = _dollars(item["value"].get("amount"))
            what = f"Box {item['box']}{' code ' + item['code'] if item.get('code') else ''}, {item.get('label', '')}"
            s.add(what.rstrip(", "), value if value is not None else "on the statement", READY, _where(f))
        for row in f.get("statement", []):
            if row.get("aggregate"):
                continue
            kind = f" [{k}]" if (k := qbi.qbi_kind(row["description"])) else ""
            business = f" / {row['business']}" if row.get("business") else ""
            s.add(f"Statement, box {row.get('box', '')}{row.get('code', '')}: {row['description']}{business}{kind}",
                  _dollars(row["amount"]), READY, _where(f, row.get("page")))
        if f.get("k3_attached"):
            s.notes.append("A K-3 is attached (box 16): `taxtrace k1` reads it for foreign tax.")
        out.append(s)
    return out


def _passive(ledger: dict | None) -> Section:
    s = Section("Passive losses carried in (Form 8582)")
    if ledger is None:
        s.add("Losses carried in", "", MISSING, "`taxtrace passive`")
        return s
    s.notes.append("The site works out Form 8582 itself from these and the year's K-1s and rental.")
    for line in ledger.get("lines", []):
        carried = _dollars(line.get("carried"))
        if carried is None:
            s.add(f"{line.get('activity', '')}: loss carried in", "", MISSING, "last year's return")
        elif carried:
            s.add(f"{line.get('activity', '')}: loss carried in", carried, READY,
                  f"the {line.get('carried_from')} return" if line.get("carried_from") else "")
    if not s.rows:
        s.add("Losses carried in", "None", READY, "")
    return s


def _qbi(form: dict | None) -> Section:
    s = Section("Qualified business income (Form 8995)")
    if form is None:
        s.add("Each business's income", "", MISSING, "`taxtrace qbi`")
        return s
    s.notes.append("The site works out the deduction: compare its Form 8995 with these.")
    for b in form.get("businesses", []):
        s.add(f"{b.get('name', '')}", _dollars(b["income"]), READY, b.get("source", ""))
    lines = form.get("lines", {})
    for n, label in (("3", "Loss carried in from last year"), ("7", "REIT and PTP loss carried in from last year"),
                     ("6", "REIT dividends and PTP income")):
        if value := _dollars(lines.get(n)):
            s.add(f"Line {n}, {label}", value, READY, "")
    return s


def _deductions(forms: list[dict], year: int, rental: dict | None, moves: dict | None) -> Section:
    s = Section("Deductions and adjustments")
    s.notes.append("The site compares itemizing with the standard deduction: enter what's here either way.")
    address = (rental or {}).get("address", "")
    for f in _year_forms(forms, year, "1098"):
        if address and schedule_e.same_place(f.get("address", ""), address):
            continue  # the rental's: on Schedule E
        for box, value in f.get("amounts", {}).items():
            if box != "2" and (amount := _dollars(value.get("amount"))):
                s.add(f"Home loan, {f.get('lender') or '?'}: box {box}, {value.get('label', '')}", amount, READY,
                      _where(f, value.get("page")))
    for m in (moves or {}).get("moves", []):
        if m.get("key") not in ("spouse_ira", "own_ira", "charity"):
            continue
        if m.get("done"):
            s.add(m.get("name", ""), _dollars(m["amount"]), READY, "`taxtrace moves`")
        else:
            s.add(f"{m.get('name', '')}: only if done by {m.get('by', '')}", _dollars(m["amount"]), ESTIMATE,
                  "`taxtrace moves`")
    return s


def _payments(plan: dict | None) -> Section:
    s = Section("Payments")
    if plan is None:
        s.add("Estimated tax payments", "", MISSING, "`taxtrace estimates`")
        return s
    for day, amount in sorted(plan.get("payments", {}).items()):
        s.add(f"Estimated tax paid {day}", _dollars(amount), READY, "")
    if not plan.get("payments"):
        s.add("Estimated tax payments", "None", READY, "")
    if applied := _dollars(plan.get("applied")):
        s.add("Last year's overpayment applied", applied, READY, "the filed return")
    return s


def _checks(federal: dict | None, nc: dict | None) -> Section:
    """What the site's own forms should come to: a wrong entry shows here, before anything is filed."""
    s = Section("Checks: what the site should come to")
    if federal is None or federal.get("total") is None:
        s.add("Federal adjusted gross income", "", MISSING, "`taxtrace agi`")
    else:
        s.add("Federal adjusted gross income", _dollars(federal["total"]), federal.get("status", ESTIMATE),
              "`taxtrace agi`")
    for line in (nc or {}).get("lines", []):
        if line.get("line") in ("14", "15", "26a", "28") and line.get("amount") is not None:
            s.add(f"D-400 line {line['line']}, {line.get('what', '')}", _dollars(line["amount"]),
                  line.get("status", ESTIMATE), "`taxtrace d400`")
    return s


def _north_carolina(k1s: list[dict], year: int, nc: dict | None = None) -> Section:
    s = Section("North Carolina (D-400)")
    s.notes.append("Most of the state return follows the federal one; these are what it takes besides.")
    wanted = {"10a": "D-400 line 10a, qualifying children", "16": "D-400 line 16, tax credits",
              "18": "D-400 line 18, consumer use tax", "21a": "D-400 line 21a, estimated tax paid"}
    for line in (nc or {}).get("lines", []):
        if line.get("line") in wanted:
            s.add(wanted[line["line"]], _dollars(line.get("amount")), line.get("status", READY), line.get("source", ""))
    for line in (nc or {}).get("schedule_a", []):
        if line.get("status") == MISSING:
            s.add(f"Schedule A line {line.get('line')}, {line.get('what', '')}", "", MISSING, line.get("source", ""))
    for f in k1s:
        if f.get("form") != "D-403" or f.get("year") != year or f.get("copy_of") is not None:
            continue
        for n, line in sorted(f.get("lines", {}).items(), key=lambda kv: int(kv[0])):
            if int(n) != 1 and (amount := _dollars(line.get("amount"))):
                s.add(f"{f.get('partnership') or f.get('file', '')}, NC K-1 line {n}: {line.get('goes', '')}", amount,
                      READY, _where(f))
    return s


def _coming(year: int, forms: list[dict], k1s: list[dict], found: dict | None) -> list[str]:
    """What the year still waits for: the W-2, and each form that came last year and hasn't yet this year."""
    coming = [] if any(f.get("form") == "W-2" and f.get("year") == year for f in forms) else ["Form W-2"]
    have = {f.get("ein") for f in qbi.faces(k1s, year)}
    for f in qbi.faces(k1s, year - 1):
        if f.get("ein") not in have and not f.get("final"):
            coming.append(f"K-1: {f.get('partnership') or f.get('file', '')}")
    for kind in ("1099-INT", "1099-DIV", "1099-B"):
        now = {(f.get("payer_tin"), f.get("account")) for f in _year_forms(forms, year, kind)}
        last = {(f.get("payer_tin"), f.get("account")) for f in _year_forms(forms, year - 1, kind)}
        coming += [f"{kind}: payer {tin or '?'}, account {account or '?'}" for tin, account in sorted(
            last - now, key=lambda pair: (pair[0] or "", pair[1] or ""))]
    now = {(f.get("lender_tin"), f.get("account")) for f in _year_forms(forms, year, "1098")}
    for f in _year_forms(forms, year - 1, "1098"):
        if (f.get("lender_tin"), f.get("account")) not in now:
            coming.append(f"1098: {f.get('lender') or f.get('lender_tin') or '?'}")
    for a in (found or {}).get("accounts", []):
        if a.get("missing"):
            # never "ending <digits>" here: redaction keeps a year after that word, and last digits can look like one
            coming.append(f"Statements, account {a.get('account', '?')}: "
                          + ", ".join(m.replace("..", " to ") for m in a["missing"]))
    return coming


def _questions(**saved: dict | None) -> list[str]:
    """Every question the other commands left open, with the command that asked it."""
    out = []
    for command, row in saved.items():
        for q in (row or {}).get("questions", []):
            out.append(f"{command}: {q['text'] if isinstance(q, dict) else q}")
    return out


def to_text(sheet: Sheet) -> str:
    """The sheet as a file to read beside the filing site."""
    lines = [f"Entry sheet for {sheet.year}: {sheet.count(READY)} ready, {sheet.count(ESTIMATE)} estimates, "
             f"{sheet.count(MISSING)} missing", ""]
    marks = {READY: "", ESTIMATE: " [estimate]", MISSING: " [missing]"}
    for section in sheet.sections:
        lines.append(f"## {section.title}")
        lines += [f"  ({note})" for note in section.notes]
        for r in section.rows:
            value = f": {r.value}" if r.value else ""
            source = f"  <- {r.source}" if r.source else ""
            lines.append(f"  {r.what}{value}{marks[r.status]}{source}")
        if not section.rows:
            lines.append("  nothing for this year so far")
        lines.append("")
    lines += ["## Still to come", f"  ({COMING_NOTE})", *(f"  {c}" for c in sheet.coming), ""]
    if sheet.questions:
        lines += ["## Questions still open", *(f"  {q}" for q in sheet.questions), ""]
    return "\n".join(lines).rstrip() + "\n"
