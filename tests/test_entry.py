"""A year's entry sheet from made-up saved forms: invented partnerships, banks, accounts and amounts."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from conftest import printed

from taxtrace import cli, entry

STUB = {"form": "paystub", "file": "initech-stub.pdf", "year": 2026, "paid": "2026-10-30", "period_start": "2026-10-16",
        "period_end": "2026-10-31",
        "withheld": {"federal": {"current": "500.00", "year_to_date": "10000.00", "label": "FIT Withheld"},
                     "state": {"current": "100.00", "year_to_date": "2000.00", "label": "SIT Withheld (CO)"}},
        "deferred": {"pretax": {"current": "200.00", "year_to_date": "4000.00", "label": "401k"}},
        "taxable_wages": {"current": "4000.00", "year_to_date": "80000.00", "label": "Taxable"}}
INT = {"form": "1099-INT", "file": "globex-1099.pdf", "page": 2, "year": 2026, "payer_tin": "12-3456789",
       "account": "A77", "amounts": {"1": {"amount": "41.17", "label": "Interest income", "page": 2},
                                     "3": {"amount": "0.00", "label": "US savings bond interest", "page": 2}}}
DIV = {"form": "1099-DIV", "file": "globex-1099.pdf", "page": 3, "year": 2026, "payer_tin": "12-3456789",
       "account": "A77", "amounts": {"1a": {"amount": "310.25", "label": "Ordinary dividends", "page": 3},
                                     "7": {"amount": "4.40", "label": "Foreign tax paid", "page": 3}}}
LAST_DIV = {**DIV, "year": 2025, "account": "Z11"}
K1 = {"file": "umbrella-k1.pdf", "page": 1, "year": 2026, "ein": "98-7654321", "partnership": "Umbrella Lofts LLC",
      "final": False, "items": [{"box": "2", "code": "", "label": "Net rental real estate income",
                                 "value": {"amount": "-812.00"}},
                                {"box": "20", "code": "Z", "label": "Other", "value": {"amount": None}}],
      "statement": [{"box": "20", "code": "Z", "description": "Qualified business income", "amount": "-812.00",
                     "page": 4},
                    {"box": "20", "code": "Z", "description": "Qualified business income", "amount": "-900.00",
                     "page": 4, "aggregate": "GROUP"}]}
IRA_K1 = {**K1, "file": "ira-k1.pdf", "ein": "11-1111111", "partnership": "Hooli IRA Fund", "retirement_plan": True}
LAST_K1 = {**K1, "year": 2025, "ein": "55-5555555", "partnership": "Massive Dynamic LP"}
LAST_FINAL = {**K1, "year": 2025, "ein": "66-6666666", "partnership": "Soylent Sold LP", "final": True}
NC = {"form": "D-403", "file": "umbrella-nc.pdf", "page": 2, "year": 2026, "partnership": "Umbrella Lofts LLC",
      "lines": {"1": {"amount": "-812.00", "goes": "already in federal adjusted gross income"},
                "2": {"amount": "33.00", "goes": "Form D-400 Schedule S, Part A"}}}
LOAN = {"form": "1098", "file": "acme-1098.pdf", "page": 1, "year": 2026, "lender": "Acme Mortgage",
        "lender_tin": "22-2222222", "account": "L1", "address": "12 Birch Road",
        "amounts": {"1": {"amount": "9000.00", "label": "Mortgage interest", "page": 1},
                    "2": {"amount": "250000.00", "label": "Outstanding mortgage principal", "page": 1}}}
RENTAL_LOAN = {**LOAN, "file": "acme-rental.pdf", "account": "L2", "address": "48 Oak Lane"}
RENTAL = {"address": "48 Oak Lane, Boulder, CO", "year": 2026, "fair_rental_days": 365, "personal_use_days": 0,
          "lines": {"3": {"amount": "24000", "source": "confirmed"}, "18": {"amount": "7000", "source": "projected"}},
          "other": [{"what": "Dues", "amount": "1200", "source": "answers"}], "income_or_loss": "15800",
          "questions": [{"text": "line 9, insurance: last year's return had an amount", "page": 0, "quote": ""}]}
FOUND = {"year": 2026, "estimated": True, "method": "accrued", "reporting": {"form_8938": False},
         "accounts": [{"country": "India", "account": "3301", "missing": ["2026-10-01..2026-12-31"],
                       "files": ["godavari-3301.pdf"], "interest": {"dollars": "120.50"}}],
         "refunds": [], "withheld": [], "sales": [], "taxes": [], "tds": [{"country": "India"}],
         "carryovers": [{"category": "passive", "amt": False, "years": {"2025": "700"}, "file": "2025-return.pdf"},
                        {"category": "passive", "amt": True, "years": {"2024": "50", "2025": "60"},
                         "file": "2025-return.pdf"}],
         "questions": [{"text": "whose is account 2?", "page": 0, "quote": ""}]}
RETURN = {"year": 2025, "f1040": {"lines": {"11a": "150000.00", "11b": "150000.00"}}}
SALES = {"from_forms": False, "boxes": {"A": {"proceeds": "1000", "basis": "1500", "wash": "0", "gain": "-500"}},
         "carry_short": "0", "carry_long": "250", "questions": ["the 10/28 sale's realized amount"]}
MOVES = {"moves": [{"key": "spouse_ira", "name": "Spouse's IRA", "by": "2027-04-15", "amount": "7000", "done": False},
                   {"key": "charity", "name": "Cash gifts", "by": "2026-12-31", "amount": "500", "done": True},
                   {"key": "401k", "name": "Fill the 401(k)", "by": "2026-12-15", "amount": "900", "done": False}]}
PLAN = {"payments": {"2026-09-15": "1500"}, "applied": "0"}


def full(**changes) -> entry.Sheet:
    made = {"forms": [STUB, INT, DIV, LAST_DIV, LOAN, RENTAL_LOAN], "k1s": [K1, IRA_K1, LAST_K1, LAST_FINAL, NC],
            "returns": [RETURN], "filing": "joint", "rental": RENTAL, "found": FOUND, "sales": SALES, "plan": PLAN,
            "moves": MOVES, "passive": None, "form_8995": None, "today": date(2026, 11, 4)}
    return entry.build(2026, **{**made, **changes})


def section(sheet: entry.Sheet, title: str) -> entry.Section:
    return next(s for s in sheet.sections if s.title.startswith(title))


def rows(sheet: entry.Sheet, title: str) -> dict[str, tuple[str, str]]:
    return {r.what: (r.value, r.status) for r in section(sheet, title).rows}


def test_a_pay_stub_stands_in_for_the_w2_as_estimates():
    got = rows(full(), "Wages")
    assert got["Box 1, wages"] == ("96,000.00", entry.ESTIMATE)  # the year to date and 4 semimonthly paychecks left
    assert got["Box 2, federal income tax withheld"] == ("12,000.00", entry.ESTIMATE)
    assert got["Box 17, CO income tax withheld"] == ("2,400.00", entry.ESTIMATE)
    assert got["Box 12 code D, 401(k) deferrals"] == ("4,800.00", entry.ESTIMATE)


def test_no_pay_stub_is_missing_and_says_what_fills_it():
    row = section(full(forms=[]), "Wages").rows[0]
    assert (row.status, row.value) == (entry.MISSING, "")
    assert "taxtrace paystub" in row.source


def test_each_1099_is_its_own_section_without_its_zero_boxes():
    assert rows(full(), "Interest") == {"Box 1, Interest income": ("41.17", entry.READY)}
    div = section(full(), "Dividends")
    assert div.title == "Dividends (1099-DIV), payer 12-3456789, account A77"
    assert "Box 7 goes to the foreign tax credit" in div.notes[0]
    assert "Foreign tax on a 1099-DIV, passive category" in rows(full(), "Foreign tax credit")


def test_last_years_agi_uses_the_2025_forms_line():
    got = rows(full(), "Filing status")
    assert got["2025 adjusted gross income, to sign the e-file"] == ("150,000.00", entry.READY)
    assert got["Filing status"] == ("joint", entry.READY)
    assert rows(full(filing="", returns=[]), "Filing status")["Filing status"] == ("", entry.MISSING)


def test_foreign_interest_is_an_estimate_while_statements_or_rates_are_missing():
    got = rows(full(), "Foreign interest")
    assert got["Interest, India account ending 3301"] == ("120.50", entry.ESTIMATE)
    assert got["Schedule B line 7b: country"] == ("India", entry.READY)
    assert got["Form 8938"] == ("Not due", entry.READY)
    settled = {**FOUND, "estimated": False, "accounts": [{**FOUND["accounts"][0], "missing": []}]}
    assert rows(full(found=settled), "Foreign interest")["Interest, India account ending 3301"][1] == entry.READY


def test_the_credit_shows_each_carryover_and_warns_about_schedule_b():
    sheet = full()
    got = rows(sheet, "Foreign tax credit")
    assert got["Taxes paid or accrued"] == ("accrued", entry.READY)
    assert got["Carryover, passive category, from 2025"] == ("700.00", entry.READY)
    assert got["Carryover (AMT), passive category, from 2024, 2025"] == ("110.00", entry.READY)
    assert got["Foreign tax for the year"] == ("", entry.MISSING)
    notes = " ".join(section(sheet, "Foreign tax credit").notes)
    assert "Schedule B (Form 1116)" in notes
    assert "isn't entered" in notes


def test_a_foreign_sale_goes_on_form_8949_in_dollars():
    sale = {"description": "House abroad", "term": "long", "acquired": "2006-01-02", "sold": "2026-03-04",
            "proceeds": {"dollars": "90000"}, "basis": "20000", "file": "itr.pdf"}
    got = rows(full(found={**FOUND, "sales": [sale]}), "Stock and property")
    assert got["Sale abroad: House abroad, long-term, bought 2006-01-02, sold 2026-03-04: proceeds"][0] == "90,000.00"
    assert got["Sale abroad: House abroad: cost basis"][0] == "20,000.00"


def test_sales_stand_in_until_the_1099_bs_come():
    got = rows(full(), "Stock and property")
    assert got["Form 8949 box A: proceeds"] == ("1,000.00", entry.ESTIMATE)
    assert "Form 8949 box A: wash sale adjustment" not in got  # zero
    assert got["Capital loss carried in, long-term"] == ("250.00", entry.READY)
    final = rows(full(sales={**SALES, "from_forms": True}), "Stock and property")
    assert final["Form 8949 box A: proceeds"][1] == entry.READY


def test_a_sales_run_with_nothing_in_it_is_still_missing():
    got = rows(full(sales={"from_forms": False, "boxes": {}}), "Stock and property")
    assert got["Sales on 1099-Bs"] == ("", entry.MISSING)


def test_no_passive_loss_carried_in_says_none():
    ledger = {"lines": [{"activity": "Umbrella Lofts", "carried": "0"}]}
    assert rows(full(passive=ledger), "Passive")["Losses carried in"] == ("None", entry.READY)
    unknown = {"lines": [{"activity": "Umbrella Lofts", "carried": None}]}
    assert rows(full(passive=unknown), "Passive")["Umbrella Lofts: loss carried in"] == ("", entry.MISSING)


def test_the_rental_is_final_only_after_the_year_ends():
    got = rows(full(), "Rental")
    assert got["Line 3, Rents received"] == ("24,000.00", entry.ESTIMATE)
    assert got["Line 19 statement: Dues"] == ("1,200.00", entry.ESTIMATE)
    assert got["Fair rental days"] == ("365", entry.READY)
    assert got["Personal use days"] == ("0", entry.READY)
    assert rows(full(today=date(2027, 2, 1)), "Rental")["Line 3, Rents received"][1] == entry.READY


def test_a_k1s_boxes_and_statement_rows_without_group_totals_or_an_iras():
    sheet = full()
    got = rows(sheet, "K-1: Umbrella")
    assert got["Box 2, Net rental real estate income"] == ("-812.00", entry.READY)
    assert got["Box 20 code Z, Other"] == ("on the statement", entry.READY)
    assert got["Statement, box 20Z: Qualified business income [qbi]"] == ("-812.00", entry.READY)  # no group's -900
    assert not any("Hooli" in s.title for s in sheet.sections)


def test_only_the_homes_loan_is_a_deduction_and_moves_show_if_theyre_done():
    got = rows(full(), "Deductions")
    assert got["Home loan, Acme Mortgage: box 1, Mortgage interest"] == ("9,000.00", entry.READY)
    assert len([k for k in got if k.startswith("Home loan")]) == 1  # the rental's isn't here, nor the loan's balance
    assert not any("Outstanding" in k for k in got)
    assert got["Spouse's IRA: only if done by 2027-04-15"] == ("7,000.00", entry.ESTIMATE)
    assert got["Cash gifts"] == ("500.00", entry.READY)
    assert not any("401(k)" in k for k in got)


def test_nc_takes_what_federal_income_doesnt_already_hold():
    got = rows(full(), "North Carolina")
    assert list(got) == ["Umbrella Lofts LLC, NC K-1 line 2: Form D-400 Schedule S, Part A"]


def test_payments_say_none_rather_than_nothing():
    assert rows(full(), "Payments")["Estimated tax paid 2026-09-15"] == ("1,500.00", entry.READY)
    assert rows(full(plan={"payments": {}}), "Payments")["Estimated tax payments"] == ("None", entry.READY)
    assert rows(full(plan=None), "Payments")["Estimated tax payments"] == ("", entry.MISSING)


def test_whats_still_to_come_is_last_years_forms_not_yet_here():
    coming = full().coming
    assert coming[0] == "Form W-2"
    assert "K-1: Massive Dynamic LP" in coming
    assert not any("Soylent" in c for c in coming)  # its last K-1 was final
    assert not any("Umbrella" in c for c in coming)  # it's in
    assert "1099-DIV: payer 12-3456789, account Z11" in coming
    assert any("3301: 2026-10-01 to 2026-12-31" in c for c in coming)


def test_a_form_new_this_year_is_on_the_list_only_when_expected_until_its_read():
    expected = ["1098=Initrode Loans", "1099=9-9-9", "K-1=Dunder", "1099=A77"]
    coming = full(expected=expected).coming
    assert "1098: Initrode Loans (you said to expect it)" in coming
    assert "1099: 9-9-9 (you said to expect it)" in coming
    assert "K-1: Dunder (you said to expect it)" in coming
    assert not any("A77 (you said" in c for c in coming)  # that account's 1099 has been read
    read = {**INT, "account": "99-9", "payer_tin": "33-3333333"}
    assert not any("9-9-9" in c for c in full(forms=[read], expected=["1099=999"]).coming)  # dashes don't matter


def test_a_form_expected_of_another_kind_or_year_hasnt_arrived():
    assert any("A77" in c for c in full(expected=["1098=A77"]).coming)  # the account's 1099s aren't a 1098
    assert any("Z11" in c for c in full(forms=[LAST_DIV], expected=["1099=Z11"]).coming)  # last year's copy


def test_expect_takes_a_known_kind_and_words():
    assert entry.expectation("k-1 = Umbrella Lofts") == "K-1=Umbrella Lofts"
    for bad in ("Umbrella", "1098=", "1040=Acme"):
        with pytest.raises(ValueError):
            entry.expectation(bad)


def test_the_sheet_always_says_the_list_isnt_everything():
    assert entry.COMING_NOTE in entry.to_text(entry.build(2026, forms=[{"form": "W-2", "year": 2026}], k1s=[],
                                                          returns=[], today=date(2026, 11, 4))).replace("\n", " ")


def test_a_w2_read_is_no_longer_coming():
    assert "Form W-2" not in full(forms=[{"form": "W-2", "year": 2026}]).coming


def test_every_commands_open_questions_are_gathered():
    questions = full().questions
    assert "rental: line 9, insurance: last year's return had an amount" in questions
    assert "foreign: whose is account 2?" in questions
    assert "sales: the 10/28 sale's realized amount" in questions


def test_nothing_run_yet_is_all_missing_and_never_a_crash():
    sheet = entry.build(2026, forms=[], k1s=[], returns=[], today=date(2026, 11, 4))
    assert sheet.count(entry.READY) == 0
    assert sheet.count(entry.MISSING) >= 8
    text = entry.to_text(sheet)
    assert "[missing]" in text
    assert "nothing for this year so far" in text  # North Carolina


def test_the_text_marks_status_and_sources_and_tells_what_to_type_yourself():
    text = entry.to_text(full())
    assert text.startswith("Entry sheet for 2026: ")
    assert "Box 1, wages: 96,000.00 [estimate]  <- initech-stub.pdf" in text
    assert "Box 1, Interest income: 41.17  <- globex-1099.pdf p2" in text
    assert "Social Security numbers" in text
    assert "## Still to come" in text
    assert "## Questions still open" in text


def save(home: Path, folder: str, name: str, value: object) -> None:
    (home / folder).mkdir(parents=True, exist_ok=True)
    (home / folder / name).write_text(json.dumps(value))


def test_the_command_writes_the_amounts_to_a_file_and_prints_them_masked(workspace_home, capsys):
    save(workspace_home, "forms", "stub.json", STUB)
    save(workspace_home, "forms", "int.json", [INT])
    save(workspace_home, "k1", "umbrella.json", [K1])
    save(workspace_home, "schedule-e", "2026.json", RENTAL)
    save(workspace_home, "foreign", "2026.json", FOUND)
    save(workspace_home, "foreign", "2026-confirmed.json", {"filing": "joint"})
    assert cli.main(["entry", "--year", "2026"]) == 0
    out = printed(capsys)
    text = (workspace_home / "entry" / "2026.txt").read_text()
    assert "41.17" in text
    assert "Umbrella Lofts" in text
    assert json.loads((workspace_home / "entry" / "2026.json").read_text())["year"] == 2026
    for secret in ("41.17", "96,000", "120.50", "Umbrella", "98-7654321", "12-3456789", "Oak Lane"):
        assert secret not in out
    assert "still to come" in out
    assert "Wages (Form W-2): 4 estimates" in out


def test_an_accounts_last_digits_that_look_like_a_year_stay_masked(workspace_home, capsys):
    account = {**FOUND["accounts"][0], "account": "1987"}
    save(workspace_home, "foreign", "2026.json", {**FOUND, "accounts": [account]})
    assert cli.main(["entry", "--year", "2026"]) == 0
    assert "1987" not in printed(capsys)
    assert "Statements, account 1987" in (workspace_home / "entry" / "2026.txt").read_text()


def test_the_command_keeps_what_to_expect_and_prints_it_masked(workspace_home, capsys):
    assert cli.main(["entry", "--year", "2026", "--expect", "1098=Initrode Loans", "--expect", "1099=5678"]) == 0
    first = printed(capsys)
    assert "Initrode" not in first
    assert "5678" not in first
    assert cli.main(["entry", "--year", "2026"]) == 0  # kept for the next run
    printed(capsys)
    assert "1098: Initrode Loans" in (workspace_home / "entry" / "2026.txt").read_text()
    assert cli.main(["entry", "--year", "2026", "--expect", "nonsense"]) == 2


def test_the_command_runs_on_an_empty_workspace(workspace_home, capsys):
    assert cli.main(["entry", "--year", "2026"]) == 0
    assert "missing" in printed(capsys)
