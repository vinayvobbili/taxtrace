"""Form 1040's lines the next year's estimated tax goes by, from a made-up return printed the way a preparer's
software prints the 2025 form: page 2 opens by repeating the adjusted gross income (line 11b)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from conftest import make_pdf

from taxtrace import f1040, prior, text

PAGE_1 = [
    "Your first name and middle initial      Last name           Your social security number",
    "Jordan Q.                               Quillfeather        XXX-XX-4410",
    "Form 1040   Department of the Treasury-Internal Revenue Service",
    "U.S. Individual Income Tax Return 2025",
    "Filing Status   X Married filing jointly",
    "1a  Total amount from Form(s) W-2, box 1 ..........................  1a   204,310",
    "z   Add lines 1a through 1h ......................................  1z   204,310",
    "2a  Tax-exempt interest ....  2a  15     b  Taxable interest ........  2b   41",
    "3a  Qualified dividends ....  3a  1,902  b  Ordinary dividends ......  3b   2,486",
    "7a  Capital gain or (loss). Attach Schedule D if required ............  7a   1,317",
    "8   Additional income from Schedule 1, line 10 .......................  8    3,721",
    "9   Add lines 1z, 2b, 3b, 4b, 5b, 6b, 7a, and 8. This is your total income ....  9   211,875",
    "10  Adjustments to income from Schedule 1, line 26 ...................  10   0",
    "11a Subtract line 10 from line 9. This is your adjusted gross income ......  11a  211,875",
]
PAGE_2 = [
    "Form 1040 (2025)   Jordan Q. Quillfeather   XXX-XX-4410    Page 2",
    "Tax and  11b Amount from line 11a (adjusted gross income) ...........  11b  211,875",
    "24  Add lines 22 and 23. This is your total tax ....................  24   31,906",
    "a Form(s) W-2 ...................................  25a  33,120",
    "d Add lines 25a through 25c ..............................  25d  33,120",
    "26  2025 estimated tax payments and amount applied from 2024 return ....  26",
    "32  Add lines 27a, 28, 29, 30, and 31. These are your total other payments and refundable credits  32  0",
    "33  Add lines 25d, 26, and 32. These are your total payments ........  33   33,120",
    "Refund 34 If line 33 is more than line 24, subtract line 24. This is the amount you overpaid  34  1,214",
    "35a Amount of line 34 you want refunded to you ..........  35a  914",
    "Direct deposit?  b Routing number  0 5 3 1 0 0 3 2 4",
    "36  Amount of line 34 you want applied to your 2026 estimated tax ....  36   300",
    "38  Estimated tax penalty (see instructions) ..........  38",
]
WORKSHEET = ["Form 1040   Explanation Worksheet (This page is not filed with the return.)",
             "11. QBI amount carried to Form 8995 ..........  11  4,410"]
SCHEDULE_3 = ["Schedule 3 (Form 1040) 2025   Jordan Q. Quillfeather   Page 2",
              "11  Excess social security and tier 1 RRTA tax withheld ......  11  410",
              "15  Add lines 9 through 12 and 14. Enter here and on Form 1040, line 31 ....  15  410"]


def test_each_line_is_read_by_its_number_and_label(tmp_path: Path):
    path = make_pdf(tmp_path / "2025 Return.pdf", [PAGE_1, PAGE_2, SCHEDULE_3, WORKSHEET])
    filed, checks = f1040.read(text.pages(path))
    assert filed.pages == [1, 2]  # a schedule's page 2 and the preparer's worksheet aren't the form
    assert filed.lines == {"1z": 204310, "2b": 41, "3b": 2486, "7a": 1317, "8": 3721, "9": 211875, "10": 0,
                           "11a": 211875, "11b": 211875, "24": 31906, "25d": 33120, "32": 0, "33": 33120,
                           "34": 1214, "36": 300}
    assert filed.agi == Decimal(211875) and filed.line("26") == 0
    assert [c.what for c in checks if not c.ok] == [] and len(checks) == 6


def test_a_sum_that_doesnt_add_up_fails_and_prior_saves_the_lines(tmp_path: Path):
    off = [row.replace("1,214", "1,241") for row in PAGE_2]
    path = make_pdf(tmp_path / "2025 Return.pdf", [PAGE_1, off])
    found = prior.read(path.name, text.pages(path))
    assert [c.what for c in found.failed] == ["Form 1040: line 34 is line 33 less line 24, zero at least"]
    assert found.to_json()["f1040"]["lines"]["24"] == "31906"


def test_a_return_without_the_form_has_none(tmp_path: Path):
    path = make_pdf(tmp_path / "2025 Return.pdf", [WORKSHEET])
    assert f1040.read(text.pages(path)) == (None, [])
