"""Form 1040's lines 12e to 24 and Form 1116's credit, for a made-up couple. Every value is invented."""

from __future__ import annotations

import json
from decimal import Decimal

from conftest import make_pdf, printed

from taxtrace import agi, cli, f1040, filed, tax, text

W2 = {"form": "W-2", "file": "w2.pdf", "year": 2026, "employee": "4410",
      "amounts": {"1": {"amount": "150000"}, "5": {"amount": "170000"}, "17": {"amount": "6000"}}}
DIV = {"form": "1099-DIV", "file": "globex.pdf", "year": 2026,
       "amounts": {"1a": {"amount": "3000"}, "1b": {"amount": "2000"}}}
SALES = {"from_forms": True, "net": "1000", "short": "0", "long": "1000", "distributions": "0"}


def federal(*forms: dict, found: dict | None = None) -> agi.Agi:
    return agi.build(2026, forms=list(forms), k1s=[], returns=[], filing="joint", sales=SALES,
                     rental={"income_or_loss": "0"}, found={} if found is None else found)


def build(*forms: dict, found: dict | None = None, **kw) -> tax.Form:
    confirmed = kw.pop("confirmed", {"children": "2", "property_tax": "0", "charity": "0"})
    return tax.build(2026, agi=federal(*forms, found=found), forms=list(forms), k1s=[], filing="joint", sales=SALES,
                     found=found, confirmed=confirmed, **kw)


def test_brackets_use_the_tables_band_under_100000_and_the_worksheet_above():
    assert tax.on_brackets(Decimal(50000), 2026, "joint") == Decimal(5507)  # on 50,025: 2,480 + 12% of 25,225
    assert tax.on_brackets(Decimal(150000), 2026, "joint") == Decimal(22424)  # 11,600 + 22% of 49,200
    assert tax.on_brackets(Decimal(0), 2026, "joint") == 0
    assert tax.on_brackets(Decimal(1000), 2026, "head") is None


def test_capital_gains_sit_on_top_of_the_other_income():
    assert tax.with_capital_gains(Decimal(50000), Decimal(10000), 2026, "joint") == tax.on_brackets(
        Decimal(40000), 2026, "joint")  # all of it inside the 0% band
    all_at_15 = tax.with_capital_gains(Decimal(200000), Decimal(20000), 2026, "joint")
    assert all_at_15 == tax.on_brackets(Decimal(180000), 2026, "joint") + 3000
    split = tax.with_capital_gains(Decimal(108900), Decimal(20000), 2026, "joint")
    assert split == tax.on_brackets(Decimal(88900), 2026, "joint") + 1500  # 10,000 at 0%, 10,000 at 15%
    assert tax.with_capital_gains(Decimal(700000), Decimal(200000), 2026, "joint") == tax.on_brackets(
        Decimal(500000), 2026, "joint") + tax.whole(Decimal(113700) * tax.RATE_15 + Decimal(86300) * tax.RATE_20)


def test_preferred_income_never_costs_more_than_the_brackets():
    assert tax.with_capital_gains(Decimal(30000), Decimal(90000), 2026, "joint") == 0


def test_the_child_credit_phases_out_by_each_thousand_or_part():
    assert tax.child_credit(2, Decimal(400000), "joint") == Decimal(4400)
    assert tax.child_credit(2, Decimal(400001), "joint") == Decimal(4350)
    assert tax.child_credit(2, Decimal(490000), "joint") == 0
    assert tax.child_credit(1, Decimal(201000), "single") == Decimal(2150)


def test_the_lines_from_income_to_total_tax():
    form = build(W2, DIV)
    assert form.deduction == "standard"
    assert form.amount("12e") == Decimal(32200)
    assert form.amount("15") == Decimal(121800)  # 154,000 less 32,200 (wages, dividends, gains; no W-2 box 10)
    expected = tax.with_capital_gains(Decimal(121800), Decimal(3000), 2026, "joint")
    assert form.amount("16") == expected
    assert form.amount("19") == Decimal(4400)
    assert form.amount("24") == expected - 4400


def test_schedule_a_wins_when_it_is_larger():
    home = {"form": "1098", "file": "acme.pdf", "year": 2026, "address": "12 Birch Road",
            "amounts": {"1": {"amount": "30000"}}}
    form = build(W2, DIV, home, confirmed={"children": "2", "property_tax": "4000", "charity": "500"})
    assert form.deduction == "itemized"
    assert form.amount("12e") == Decimal(40500)  # 30,000 + 6,000 + 4,000 + 500


def test_how_far_schedule_a_is_comes_in_words():
    assert tax.schedule_a_words(Decimal(-7000)).endswith("is under the standard deduction by $5,000 to $10,000")
    assert tax.schedule_a_words(Decimal(500)) == "Schedule A so far is over the standard deduction by under $1,000"
    assert tax.schedule_a_words(Decimal(-20000)).endswith("by $10,000 or more")
    assert build(W2, DIV).room == Decimal(6000) - Decimal(32200)


def test_the_salt_cap_holds():
    assert tax._itemized(2026, [W2], None, Decimal(100000), {"property_tax": "90000"}) == Decimal(40400)


def test_form_1116_credit_is_the_smaller_of_the_taxes_and_the_limit():
    found = {"sales": [], "interest": "10000", "carryovers": [],
             "taxes": [{"category": "passive", "kept": {"dollars": "900"}}]}
    form = build(W2, DIV, found=found)
    assert form.form_1116["9"] == Decimal(900)
    assert form.amount("20") == Decimal(900)
    capped = {**found, "taxes": [{"category": "passive", "kept": {"dollars": "90000"}}]}
    limited = build(W2, DIV, found=capped)
    assert limited.amount("20") == limited.form_1116["21"]
    assert limited.amount("20") < Decimal(90000)


def test_form_1116_carries_in_the_regular_carryover_and_not_the_amts():
    found = {"sales": [], "interest": "10000", "taxes": [],
             "carryovers": [{"category": "passive", "amt": True, "years": {"2024": "500"}},
                            {"category": "passive", "amt": False, "years": {"2024": "300"}}]}
    assert build(W2, DIV, found=found).form_1116["10"] == Decimal(300)


def test_a_funds_foreign_tax_counts_on_form_1116_and_asks_for_its_income():
    fund = {**DIV, "amounts": {**DIV["amounts"], "7": {"amount": "40"}}}
    found = {"sales": [], "interest": "10000", "carryovers": [], "taxes": []}
    form = build(W2, fund, found=found)
    assert form.form_1116["9"] == Decimal(40)
    assert any("1099-DIV box 7" in q for q in form.questions)


def test_a_filed_tax_abroad_shows_as_a_rate_and_never_an_amount():
    found = {"taxes": [{"kept": {"amount": "434000", "rate": {"rate": "86.8000"}}}]}
    note = tax.tax_abroad_note(found, {"dated_tax": Decimal(5000)})
    assert note == ("Form 1116 Part II, the tax abroad: the filed amount works out to 86.80 to the dollar; "
                    "taxtrace used 86.80")
    assert tax.tax_abroad_note(found, {}) is None
    assert tax.tax_abroad_note(None, {"dated_tax": Decimal(5000)}) is None


def test_no_foreign_side_is_no_credit():
    assert build(W2, DIV).amount("20") == 0


def test_over_the_threshold_adds_the_other_taxes():
    wages = {**W2, "amounts": {"1": {"amount": "300000"}, "5": {"amount": "300000"}}}
    form = build(wages, DIV)
    assert form.amount("23") == tax.whole(Decimal(50000) * tax.MEDICARE_RATE + Decimal(4000) * tax.INVESTMENT_RATE)
    assert any("Forms 8959 and 8960" in q for q in form.questions)


def test_under_it_there_are_none():
    assert build(W2, DIV).amount("23") == 0


def test_it_says_what_it_doesnt_work_out():
    assert tax.AMT_NOTE in build(W2, DIV).questions


def test_another_filing_status_is_a_question():
    form = tax.build(2026, agi=federal(W2), forms=[W2], k1s=[], filing="head")
    assert form.lines == []
    assert "joint and single only" in form.questions[0]


def test_an_incomplete_income_is_a_question():
    built = agi.build(2026, forms=[], k1s=[], returns=[], filing="joint")
    form = tax.build(2026, agi=built, forms=[], k1s=[], filing="joint")
    assert "isn't complete" in form.questions[0]


FILED = {"11b": Decimal(155000), "3a": Decimal(2000), "12e": Decimal(32200), "14": Decimal(32200),
         "15": Decimal(122800), "19": Decimal(4400)}
FILED["16"] = tax.with_capital_gains(FILED["15"], Decimal(3000), 2026, "joint")
SCHEDULE_D = {"15": Decimal(1000), "16": Decimal(1000)}


def test_each_rule_is_tested_from_the_filed_forms_own_inputs():
    form = tax.Form(2026, "joint", deduction="standard")
    world = tax.whole(tax.line_18(FILED["15"], Decimal(3000), 2026, "joint"))
    checks, _ = tax.compare(form, FILED, {"17": world / 10, "18": world, "20": Decimal(20000), "21": Decimal(2000)},
                            SCHEDULE_D, "joint", 2, [W2])
    assert [c.what for c in checks if not c.ok] == []
    assert {c.what.split(" is ")[0] for c in checks} == {
        "line 16 worked from the filed taxable income", "line 19 worked from the filed income and the children",
        "line 15 worked from the filed income and line 14", "line 12e",
        "line 23 worked from the filed income and the W-2s",
        "Form 1116 line 18 worked from the filed taxable income",
        "Form 1116 line 21 worked from its filed lines 17, 18 and 20"}


def test_line_18_takes_out_the_gains_by_how_far_under_the_top_rate_they_were_taxed():
    assert tax.line_18(Decimal(200000), Decimal(20000), 2026, "joint") == Decimal(200000) - Decimal("11892")
    assert tax.line_18(Decimal(200000), Decimal(20000), 2026, "joint", Decimal(1000)) == (
        Decimal(200000) - (Decimal("324.3") + Decimal(19000) * tax.WORLD_AT_15))
    assert tax.line_18(Decimal(108900), Decimal(20000), 2026, "joint") == (
        Decimal(108900) - (Decimal(10000) + Decimal(10000) * tax.WORLD_AT_15))
    assert tax.line_18(Decimal(0), Decimal(0), 2026, "joint") == 0


def test_a_foreign_gain_is_cut_by_its_rate_and_nothing_at_zero():
    assert tax.adjusted_gain(Decimal(10000), Decimal(200000), Decimal(20000), 2026, "joint") == Decimal(4054)
    assert tax.adjusted_gain(Decimal(10000), Decimal(50000), Decimal(20000), 2026, "joint") == 0
    assert tax.adjusted_gain(Decimal(-500), Decimal(200000), Decimal(20000), 2026, "joint") == 0


def test_the_adjustment_is_required_from_20000_or_past_the_24_percent_bracket():
    assert not tax.must_adjust(Decimal(19999), Decimal(100000), 2026, "joint")
    assert tax.must_adjust(Decimal(20000), Decimal(100000), 2026, "joint")
    assert not tax.must_adjust(Decimal(0), Decimal(403550), 2026, "joint")
    assert tax.must_adjust(Decimal(0), Decimal(403551), 2026, "joint")


TAXED = [{"category": "passive", "kept": {"dollars": "90000"}}]


def test_line_3e_counts_a_rentals_rents_not_its_profit():
    rental = {"income_or_loss": "-2000", "lines": {"3": {"amount": "24000"}}}
    income = agi.build(2026, forms=[W2, DIV], k1s=[], returns=[], filing="joint", sales=SALES, rental=rental, found={})
    assert tax.gross_income(income, rental) == Decimal(150000 + 3000 + 1000 + 24000)


def test_line_3g_and_line_1a_are_tested_from_the_filed_form():
    form = tax.Form(2026, "joint", deduction="standard")
    worked = tax.adjusted_gain(Decimal(10000), FILED["15"], Decimal(13000), 2026, "joint")
    lines = {"3d": Decimal(11000), "3e": Decimal(220000), "3g": Decimal(1610), "1a": Decimal(1000) + worked}
    checks, _ = tax.compare(form, FILED, lines, {**SCHEDULE_D, "15": Decimal(11000), "16": Decimal(11000)}, "joint", 2,
                            form_4797={"24": Decimal(10000)})
    found = {c.what.split(" is ")[0]: c.ok for c in checks}
    assert found["Form 1116 line 3g worked from its lines 3d and 3e and line 12e"]
    assert found["Form 1116 line 1a worked from its line 3d and Form 4797's gain"]


def test_with_no_foreign_gain_the_worksheet_gives_the_larger_limit():
    form = build(W2, DIV, found={"sales": [], "interest": "10000", "carryovers": [], "taxes": TAXED})
    assert form.form_1116["18"] < form.amount("15")
    assert form.form_1116["1a"] == Decimal(10000)


def test_a_large_foreign_gain_has_to_be_adjusted():
    found = {"sales": [{"gain": "30000"}], "interest": "0", "carryovers": [], "taxes": TAXED}
    gained = {**SALES, "net": "0", "long": "0"}
    form = tax.build(2026, agi=agi.build(2026, forms=[W2, DIV], k1s=[], returns=[], filing="joint", sales=gained,
                                         rental={"income_or_loss": "0"}, found=found),
                     forms=[W2, DIV], k1s=[], filing="joint", sales=gained, found=found, confirmed={"children": "2"})
    assert form.form_1116["1a"] == tax.whole(Decimal(30000) * tax.GAIN_AT_15)
    assert form.form_1116["18"] < form.amount("15")


def test_a_small_foreign_gain_takes_whichever_way_has_the_larger_limit():
    found = {"sales": [{"gain": "5000"}], "interest": "0", "carryovers": [], "taxes": TAXED}
    gained = {**SALES, "net": "0", "long": "0"}
    form = tax.build(2026, agi=agi.build(2026, forms=[W2, DIV], k1s=[], returns=[], filing="joint", sales=gained,
                                         rental={"income_or_loss": "0"}, found=found),
                     forms=[W2, DIV], k1s=[], filing="joint", sales=gained, found=found, confirmed={"children": "2"})
    tax_16 = form.amount("16")
    share = form.form_1116["3g"]
    plain = tax.foreign_limit(tax_16, Decimal(5000) - share, form.amount("15"))
    assert form.form_1116["21"] >= plain
    assert form.form_1116["1a"] == Decimal(5000)  # the election: left unadjusted, the limit comes out larger


def test_a_wrong_filed_tax_shows_which_way_without_an_amount():
    form = tax.Form(2026, "joint", deduction="standard")
    checks, _ = tax.compare(form, {**FILED, "16": FILED["16"] + 5000}, {}, SCHEDULE_D, "joint", 2)
    failed = next(c for c in checks if not c.ok)
    assert failed.what == ("line 16 worked from the filed taxable income is lower than the filed return's, "
                           "by $1,000 or more")


def test_lines_with_nothing_on_either_side_arent_counted():
    form = build(W2, DIV)
    checks, untested = tax.compare(form, dict(FILED), {}, SCHEDULE_D, "joint", 2)
    assert "line 23: nothing on either side" in untested
    assert all("line 23" not in c.what for c in checks)


def test_form_1040s_tax_lines_and_qualified_dividends_are_read(tmp_path):
    page = ["Filing Status   X Married filing jointly",
            "z   Add lines 1a through 1h ......................................  1z   204,310",
            "9   Add lines 1z, 2b, 3b, 4b, 5b, 6b, 7a, and 8. This is your total income ....  9   211,875",
            "e Taxable dependent care benefits from Form 2441, line 26 ............  1e  4,000",
            "if required.   3a Qualified dividends ..... 3a 1,902 b Ordinary dividends ........ 3b 2,486"]
    two = ["Form 1040 (2025)   Jordan Q. Quillfeather   XXX-XX-4410    Page 2",
           "e Standard deduction or itemized deductions (from Schedule A) ................. 12e 31,500",
           "13a Qualified business income deduction from Form 8995 or Form 8995-A ............... 13a 0",
           "14 Add lines 12e, 13a, and 13b ................................... 14 31,500",
           "15 Subtract line 14 from line 11b. This is your taxable income .... 15 180,375",
           "16 Tax (see instructions). Check if any from Form(s) ...... 16 30,000",
           "19 Child tax credit or credit for other dependents from Schedule 8812 ................. 19 4,400",
           "20 Amount from Schedule 3, line 8 ................................. 20 1,100"]
    found, _ = f1040.read(text.pages(make_pdf(tmp_path / "1040.pdf", [page, two])))
    assert {k: found.lines[k] for k in ("1e", "3a", "12e", "14", "15", "16", "19", "20")} == {
        "1e": Decimal(4000), "3a": Decimal(1902), "12e": Decimal(31500), "14": Decimal(31500),
        "15": Decimal(180375), "16": Decimal(30000), "19": Decimal(4400), "20": Decimal(1100)}


F1116_P1 = ["Foreign Tax Credit",
            "Use a separate Form 1116 for each category of income listed below.",
            "d Gross foreign source income (see instructions) ... 30 20,000",
            "e Gross income from all sources (see instructions) ... 250,000 250,000 250,000",
            "g Multiply line 3c by line 3f .............. 39 2,000",
            "A 12 14",
            "B 03-15-2025    1,500    1,500",
            "7 Subtract line 6 from line 1a. Enter the result here and on line 15, page 2.............. 7 18,000",
            "8 Add lines A through C, column (u). Enter the total here and on line 9, page 2 ................ 8 1,500"]
F1116_P2 = ["Form 1116 (2025)     Page2",
            "accrued for the category of income checked above Part I .......... 9 1,500",
            "11 Add lines 9 and 10 .............................. 11 1,500",
            "14 Combine lines 11, 12, and 13. This is the total amount of foreign taxes available .... 14 1,500",
            "income checked above Part I. See instructions ................ y15 18,000",
            "line 19.) .................................... 17 18,000",
            "the deduction for your exemption ........................ 18 180,000",
            "line 1z. Estates and trusts: See instructions ............................... 20 30,000",
            "21 Multiply line 20 by line 19 ............... 21 3,000",
            "33 Enter the smaller of line 20 or line 32 .................................... 33 1,500",
            "line 1; Form 1041, Schedule G, line 2a; or Form 990-T, Part III, line 1a ..................... 35 1,500"]
F1116_AMT = ["FOR ALT MIN TAX PURPOSES ONLY", "Foreign Tax Credit", "Use a separate Form 1116 for each category",
             "the deduction for your exemption ........................ 18 99,999"]


def test_form_1116_is_read_and_its_amt_copy_isnt(tmp_path):
    forms = filed.read(text.pages(make_pdf(tmp_path / "1116.pdf", [F1116_AMT, F1116_P1, F1116_P2])))
    assert forms.form_1116.pages == [2, 3]
    assert forms.form_1116.line("18") == Decimal(180000)
    assert forms.form_1116.line("35") == Decimal(1500)
    assert [c.what for c in forms.checks if not c.ok] == []


def test_a_date_row_on_page_1_isnt_a_line_and_a_stray_letter_doesnt_hide_one(tmp_path):
    forms = filed.read(text.pages(make_pdf(tmp_path / "1116.pdf", [F1116_P1, F1116_P2])))
    assert forms.form_1116.line("12") == 0  # "A 12 14" in Part II: a month and a day
    assert forms.form_1116.line("15") == Decimal(18000)  # printed as "y15 18,000"
    assert forms.form_1116.line("3e") == Decimal(250000)  # in each column
    assert forms.form_1116.line("3d") == Decimal(20000)  # its number garbled in the print, as line 3g's
    assert forms.form_1116.line("3g") == Decimal(2000)
    assert forms.form_1116.line("dated_tax") == Decimal(1500)


def test_the_command_compares_and_masks(workspace_home, capsys):
    saved = workspace_home / "carryforwards"
    saved.mkdir(parents=True, exist_ok=True)
    (workspace_home / "foreign").mkdir(parents=True, exist_ok=True)
    (workspace_home / "foreign" / "2025-confirmed.json").write_text(json.dumps({"filing": "joint"}))
    (saved / "2025.json").write_text(json.dumps({"year": 2025, "f1040": {"lines": {
        "1z": "120000", "11a": "120000", "12e": "31500", "14": "31500", "15": "88500", "16": "10123"}}}))
    (workspace_home / "forms").mkdir(parents=True, exist_ok=True)
    (workspace_home / "forms" / "w2.json").write_text(json.dumps([{**W2, "year": 2025, "amounts": {
        "1": {"amount": "120000"}}}]))
    assert cli.main(["tax", "--year", "2025"]) in (0, 1)
    out = printed(capsys)
    assert "against the filed 2025 return" in out
    for secret in ("120000", "120,000", "88,500", "88500", "10123"):
        assert secret not in out
    assert (workspace_home / "tax" / "2025.txt").exists()
