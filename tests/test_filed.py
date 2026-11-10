"""Schedule 1, Schedule D and the D-400 as filed, from a made-up return printed the way a preparer's software prints
them: a draft watermark's stray letters on some rows, and the D-400's amounts on the row above each label."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from conftest import make_pdf, printed

from taxtrace import agi, cli, d400, f1040, filed, prior, text

SCHEDULE_1 = [
    "SCHEDULE 1        Additional Income and Adjustments to Income    OMB No. 1545-0074",
    "(Form 1040)                                                      2025",
    "Part I Additional Income",
    " 1 Taxable refunds, credits, or offsets of state and local income taxes ......... 1  210",
    " 4 Other gains or (losses). Check if any from Form(s): 4797 4684 y............... 4  90",
    " 5 Rental real estate, royalties, partnerships, S corporations, etc. Attach Schedule E ....... 5  (1,300)",
    " 8 Other income:                   o",
    " a Net operating loss ................................. 8a ( )",
    " z Other income. List type and amount:",
    "                                                       8z  500",
    " 9 Total other income. Add lines 8a through 8z .................. 9  500",
    "10 Combine lines 1 through 7 and 9. This is your additional income. Enter here and on Form 1040,",
    "   1040-SR, or 1040-NR, line 8 ........................................ 10  (500)",
]
SCHEDULE_1_PAGE_2 = [
    "Schedule 1 (Form 1040) 2025                                            Page 2",
    "20 IRA deduction ................................... 20  7,000",
    "26 Add lines 11 through 23 and 25. These are your adjustments to income. Enter here and on Form",
    "   1040, 1040-SR, or 1040-NR, line 10 ................. 26  7,000",
]
SCHEDULE_D = [
    "SCHEDULE D                 Capital Gains and Losses              OMB No. 1545-0074",
    "(Form 1040)                                                      2025",
    "  Part I Short-Term Capital Gains and Losses",
    " 1a Totals for all short-term transactions reported on",
    "    leave this line blank and go to line 1b .........",
    " 1b Totals for all transactions reported on Form(s) 8949",
    "    with Box A or Box G checked .............. 900    1,000                   (100)",
    "  6 Short-term capital loss carryover. Enter the amount, if any, from line 8 of your Capital Loss",
    "    Carryover Worksheet in the instructions ................................... 6 ( )",
    "  7 Net short-term capital gain or (loss). Combine lines 1a through 6 in column (h). If you have any",
    "    long-term gains or losses, go to Part II below. Otherwise, go to Part III on page 2 ......... 7 (100)",
    "  Part II Long-Term Capital Gains and Losses",
    " 8b Totals for all transactions reported on Form(s) 8949",
    "    with Box D or Box J checked .............. 700    50                   650",
    " 11 Gain from Form 4797, Part I; long-term gain from Forms 2439 and 6252; and long-term gain or (loss)",
    "    from Forms 4684, 6781, and 8824 ...................................... 11 12,000",
    " 13 Capital gain distributions. See the instructions ............................... 13 2,450",
    " 14 Long-term capital loss carryover. Enter the amount, if any, from line 13 of your Capital Loss",
    "    Carryover Worksheet in the instructions ................................... 14 ( )",
    " 15 Net long-term capital gain or (loss). Combine lines 8a through 14 in column (h). Then, go to Part III",
    "    on page 2 ................................................... 15   15,100",
]
SCHEDULE_D_PAGE_2 = [
    "Schedule D (Form 1040) 2025 Jordan Q Quillfeather XXX-XX-4410 Page 2",
    "  Part III Summary",
    " 16 Combine lines 7 and 15 and enter the result ............................. 16 15,000",
    " 19 If you are required to complete the Unrecaptured Section 1250 Gain Worksheet (see",
    "    instructions), enter the amount, if any, from line 18 of that worksheet ............... 19 8",
]
WORKSHEET = ["Schedule D Tax Worksheet", " 16 Enter the amount from line 16 .......... 16 99,999"]
D400 = [
    "D-400 2025 Page 2 (25)",
    "Last Name (First 10 Characters)    Your Social Security Number",
    "211,000",
    " 6. Federal Adjusted Gross Income      6.",
    "0",
    " 7. Additions to Federal Adjusted Gross Income      7.",
    "211,000",
    " 8. Add Lines 6 and 7      8.",
    "120",
    " 9. Deductions From Federal Adjusted Gross Income      9.",
    "10. Child Deduction",
    "2",
    "  a. Enter the number of qualifying children for whom you were allowed a federal child tax credit  10a.",
    "0",
    "  b. Enter the amount of the child deduction      10b.",
    "Y",
    "11. N.C. Standard Deduction      11.",
    "N",
    "11. N.C. Itemized Deduction      11.",
    "25,500",
    "11. Deduction amount      11.",
    "25,620",
    "12. a. Add Lines 9, 10b, and 11      12a.",
    "y",
    "185,380",
    "  b. Subtract Line 12a from Line 8      12b.",
    "1.0000",
    "13. Part-year Residents and Nonresidents Taxable Percentage      13.",
    "p  185,380",
    "14. N.C. Taxable Income      14.",
    "7,879",
    "15. N.C. Income Tax      15.",
    "0",
    "16. Tax Credits  o      16.",
    "7,879",
    "17. Subtract Line 16 from Line 15      17.",
    "0",
    "18. Consumer Use Tax      18.",
    "C  Y",
    "You certify that no Consumer Use Tax is due",
    "7,879",
    "19. Add Lines 17 and 18      19.",
    "North Carolina Income Tax Withheld",
    "t",
    "8,000",
    "20a. Your tax withheld      20a.",
    "n",
    "0",
    "20b. Spouse's tax withheld      20b.",
    "Other Tax Payments e",
    "0",
    "21a. 2025 estimated tax i      21a.",
    "8,000",
    "23. Add Lines 20a through 22      23.",
    "0",
    "24. Previous Refunds      24.",
    "8,000",
    "25. Subtract Line 24 from Line 23      25.",
    "26a. Tax Due      26a.",
    "121",
    "28. Overpayment      28.",
]
FILED_1040 = f1040.Filed(lines={"7a": Decimal(15000), "8": Decimal(-500), "10": Decimal(7000), "11a": Decimal(211000)},
                         pages=[1])
PAGES = [SCHEDULE_1, SCHEDULE_1_PAGE_2, SCHEDULE_D, SCHEDULE_D_PAGE_2, WORKSHEET, D400]


SCHEDULE_E = [
    "Supplemental Income and Loss",
    " 23a Total of all amounts reported on line 3 for all rental properties ........ 23a 24,000",
    " 24 Income. Add positive amounts shown on line 21. Do not include any losses ............ 24 1,700",
    " 25 Losses. Add royalty losses from line 21 and rental real estate losses from line 22. here... 25",
    " 26 Total rental real estate and royalty income or (loss). Combine lines 24 and 25. Enter the result",
    "    here. If Parts II, III, IV, and line 40 on page 2 do not apply to you, ........ 26 1,700",
]
SCHEDULE_E_PAGE_2 = [
    "Schedule E (Form 1040) 2025 Attachment Sequence No. 13 Page2",
    " 30 Add columns (h) and (k) of line 29a...... ............................ 30 40",
    " 31 Add columns (g), (i), and (j) of line 29b .t............................... 31 ( 3,040 )",
    " 32 Total partnership and S corporation income or (loss). Combine lines 30 and 31 ....... 32 (3,000)",
    " 41 Total income or (loss). Combine lines 26, 32, 37, 39, and 40. Enter the result here and on Schedule",
    "    1 (Form 1040), line 5 ..................................... 41 (1,300)",
]
FORM_4797 = [
    "4797  Sales of Business Property  OMB No. 1545-0184",
    " 6 Gain, if any, from line 32, from other than casualty or theft ............................ 6 12,000",
    " 7 Combine lines 2 through 6. Enter the gain or (loss) here and on the appropriate line ........... 7 12,000",
]
FORM_4797_PAGE_2 = [
    "Form 4797 (2025) Jordan Q Quillfeather XXX-XX-4410 Page2",
    " 20 Gross sales price (Note: See line 1a before completing.) 20 100,000",
    " 21 Cost or other basis plus expense of sale........ 21 88,000",
    " 22 Depreciation (or depletion) allowed or allowable.... 22",
    " 23 Adjusted basis. Subtract line 22 from line 21...... 23 88,000",
    " 24 Total gain. Subtract line 23 from line 20 ........ 24 12,000",
    " 32 other than casualty or theft on Form 4797, line 6.................................. 32 12,000",
]
PAGES = [*PAGES, SCHEDULE_E, SCHEDULE_E_PAGE_2, FORM_4797, FORM_4797_PAGE_2]


def read(tmp_path: Path, pages: list[list[str]] = PAGES, name: str = "2025 return.pdf") -> filed.Forms:
    path = make_pdf(tmp_path / name, pages)
    return filed.read(text.pages(path), FILED_1040)


def test_schedule_1_is_read_by_its_line_numbers(tmp_path: Path):
    one = read(tmp_path).schedule_1
    assert one.pages == [1, 2]
    assert {k: str(v) for k, v in one.lines.items()} == {
        "1": "210", "4": "90", "5": "-1300", "8a": "0", "8z": "500", "9": "500", "10": "-500", "20": "7000",
        "26": "7000"}


def test_schedule_d_reads_the_gain_column_of_its_sales_rows(tmp_path: Path):
    capital = read(tmp_path).schedule_d
    assert capital.pages == [3, 4]  # the Schedule D Tax Worksheet's page isn't the schedule
    assert {k: str(v) for k, v in capital.lines.items()} == {
        "1b": "-100", "6": "0", "7": "-100", "8b": "650", "11": "12000", "13": "2450", "14": "0", "15": "15100",
        "16": "15000", "19": "8"}


def test_the_d400s_amounts_are_on_the_row_above_each_label(tmp_path: Path):
    state = read(tmp_path).d400
    assert state.line("6") == Decimal(211000)
    assert state.line("10a") == Decimal(2)
    assert state.line("11") == Decimal(25500)  # the rows with only a Y or N above them don't count
    assert state.line("14") == Decimal(185380)  # sharing its row with a watermark's letter
    assert state.line("20a") == Decimal(8000)
    assert state.line("28") == Decimal(121)
    assert "26a" not in state.lines  # the row above is another label
    assert "18" in state.lines
    assert state.line("18") == 0


def test_an_official_print_with_each_amount_on_its_labels_row(tmp_path: Path):
    page = ["D-400 2025 Page 2", " 6. Federal Adjusted Gross Income   6.   211,000",
            "14. N.C. Taxable Income   14.   185,380", "15. N.C. Income Tax   15.   7,879"]
    assert read(tmp_path, [page]).d400.lines == {"6": Decimal(211000), "14": Decimal(185380), "15": Decimal(7879)}


def test_schedule_e_and_form_4797_read_their_totals(tmp_path: Path):
    forms = read(tmp_path)
    assert {k: str(v) for k, v in forms.schedule_e.lines.items()} == {
        "23a": "24000", "24": "1700", "26": "1700", "30": "40", "31": "-3040", "32": "-3000", "41": "-1300"}
    assert {k: str(v) for k, v in forms.form_4797.lines.items()} == {
        "6": "12000", "7": "12000", "20": "100000", "21": "88000", "23": "88000", "24": "12000", "32": "12000"}


def test_every_form_adds_up_and_agrees_with_the_others(tmp_path: Path):
    checks = read(tmp_path).checks
    assert [c.what for c in checks if not c.ok] == []
    assert len(checks) == 25


def test_a_misread_line_fails_a_check(tmp_path: Path):
    wrong = [row.replace("15   15,100", "15   15,900") for row in SCHEDULE_D]
    checks = read(tmp_path, [wrong, SCHEDULE_D_PAGE_2]).checks
    assert {c.what for c in checks if not c.ok} == {"Schedule D: line 15 adds up lines 8a through 14",
                                                    "Schedule D: line 16 is lines 7 and 15"}


def test_a_return_without_the_forms_has_none(tmp_path: Path):
    assert read(tmp_path, [["Form 8879, an e-file signature"]]) == filed.Forms()


def test_prior_saves_them(tmp_path: Path):
    path = make_pdf(tmp_path / "2025 return.pdf", PAGES)
    found = prior.read(path.name, text.pages(path)).to_json()
    assert found["schedule_d"]["lines"]["13"] == "2450"
    assert found["schedule_1"]["lines"]["5"] == "-1300"
    assert found["d400"]["lines"]["14"] == "185380"


RETURN = {"year": 2025, "f1040": {"lines": {"1z": "190000", "7a": "15000", "8": "-500", "10": "7000", "11a": "211000"}},
          "schedule_1": {"lines": {"1": "210", "4": "90", "5": "-1300", "9": "500"}},
          "schedule_d": {"lines": {"1b": "-100", "8b": "650", "11": "12000", "13": "2450"}},
          "d400": {"lines": {"6": "211000", "15": "7879"}}}
PACKET = {"year": 2025, "f1040": None, "d400": None}
SALES = {"from_forms": True, "net": "3000", "short": "-100", "long": "650", "distributions": "2450",
         "carry_short": "0", "carry_long": "0"}


def test_the_rehearsal_says_which_part_of_a_line_differs_without_an_amount():
    built = agi.build(2025, forms=[], k1s=[], returns=[PACKET, RETURN], filing="joint", sales=SALES,
                      rental={"income_or_loss": "-1300"})
    details = "\n".join(built.details)
    assert "short-term sales (lines 1a to 3) is the filed return's" in details
    assert "long-term sales (lines 8a to 10) is the filed return's" in details
    assert "capital gain distributions (line 13) is the filed return's" in details
    assert "gains (lines 4 and 11) is lower than the filed return's, by $1,000 or more" in details
    assert "the rental and the K-1s (line 5) is the filed return's" in details
    assert "state refunds (line 1) is lower than the filed return's, by under $1,000" in details
    assert "other income (line 9) is lower" in details
    assert "loss carryovers" not in details  # nothing on either side
    for amount in ("12000", "12,000", "2450", "1300"):
        assert amount not in details


def test_the_sale_abroad_and_schedule_e_are_compared_part_by_part():
    found = {"interest": "0", "sales": [{"gain": "15000", "proceeds": {"dollars": "100000"}, "basis": "85000"}]}
    returned = {**RETURN, "form_4797": {"lines": {"20": "100000", "21": "88000", "24": "12000"}},
                "schedule_e": {"lines": {"26": "1700", "32": "-3000"}}}
    face = {"file": "umbrella.pdf", "page": 1, "year": 2025, "partnership": "Umbrella Lofts LLC", "items": []}
    passive = {"form_8582": {"activities": [{"name": "48 Oak Lane", "allowed": "1700"},
                                            {"name": "Umbrella Lofts", "allowed": "-2000"}]}}
    built = agi.build(2025, forms=[], k1s=[face], returns=[returned], filing="joint", sales=SALES, found=found,
                      passive=passive)
    details = "\n".join(built.details)
    assert "the sale abroad's price (line 20) is the filed return's" in details
    assert "cost and selling expenses (line 21) is lower than the filed return's, by $1,000 or more" in details
    assert "the sale abroad's gain (line 24) is higher than the filed return's, by $1,000 or more" in details
    assert "the K-1s (line 32) is higher than the filed return's, by $1,000 or more" in details
    assert "the rental (line 26) is the filed return's" in details


def test_the_d400s_rate_is_tested_from_the_filed_taxable_income():
    form = d400.Form(2025)
    checks, _ = d400.compare(form, {"14": Decimal(185380), "15": Decimal(7879)})
    assert [c.what for c in checks] == ["line 15 worked from the filed line 14 is the filed return's"]
    checks, _ = d400.compare(form, {"14": Decimal(185380), "15": Decimal(6000)})
    assert not checks[0].ok


def test_a_k1_the_filed_schedule_e_doesnt_hold_is_named():
    returned = {**RETURN, "schedule_e": {"lines": {"26": "0", "32": "-3000"}}}
    faces = [{"file": f"{n}.pdf", "page": 1, "year": 2025, "partnership": f"{n} LLC", "items": []}
             for n in ("Umbrella", "Globex", "Initech")]
    passive = {"form_8582": {"activities": [{"name": "Umbrella LLC", "allowed": "-3000"},
                                            {"name": "Globex LLC", "allowed": "900"},
                                            {"name": "Initech LLC", "allowed": "400"}]}}
    built = agi.build(2025, forms=[], k1s=faces, returns=[returned], filing="joint", sales=SALES, passive=passive)
    assert "Schedule E line 32: leaving out Globex LLC and Initech LLC would match" in built.explained


def test_lines_that_cant_test_anything_arent_counted():
    form = d400.Form(2025, lines=[d400.Line("20", "Withheld", Decimal(100)), d400.Line("21b", "Extension", Decimal(0))])
    filed_d400 = {"20a": Decimal(8000), "21b": Decimal(900)}
    assert d400.compare(form, filed_d400, has_w2=False) == (
        [], ["line 20: no W-2 has been read", "line 21b: an amount you confirm, not given for 2025"])
    checks, untested = d400.compare(form, filed_d400, confirmed={"extension": "0"})
    assert (len(checks), untested) == (2, [])


def test_a_form_the_return_doesnt_hold_adds_no_detail():
    built = agi.build(2025, forms=[], k1s=[], returns=[{"year": 2025, "f1040": RETURN["f1040"]}], filing="joint")
    assert built.details == []


def test_the_d400_is_compared_line_by_line():
    form = d400.Form(2025, lines=[d400.Line("6", "AGI", Decimal(211000)), d400.Line("7", "Additions", Decimal(0)),
                                  d400.Line("15", "Tax", Decimal(7000)), d400.Line("20", "Withheld", Decimal(8000)),
                                  d400.Line("23", "Paid", None, d400.MISSING)])
    checks, untested = d400.compare(form, {"6": Decimal(211000), "15": Decimal(7879), "20a": Decimal(5000),
                                           "20b": Decimal(3000), "23": Decimal(8000)})
    assert [c.what for c in checks if c.ok] == ["line 6 is the filed return's", "line 20 is the filed return's"]
    assert [c.what for c in checks if not c.ok] == ["line 15 is lower than the filed return's, by under $1,000",
                                                    "line 23: not built yet"]
    assert untested == ["line 7: nothing on either side"]


def test_the_command_compares_with_the_filed_d400_and_masks_it(workspace_home, capsys):
    saved = workspace_home / "carryforwards"
    saved.mkdir(parents=True, exist_ok=True)
    (saved / "2025 return.json").write_text(json.dumps(RETURN))
    assert cli.main(["d400", "--year", "2025", "--confirm", "children=2"]) in (0, 1)
    out = printed(capsys)
    assert "211000" not in out
    assert "211,000" not in out
