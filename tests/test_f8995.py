from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from conftest import make_pdf, printed

from taxtrace import cli, f8995, prior, text

# Drake's Form 8995: line 2's amount on the row under its label, losses in spaced parentheses
FORM_8995 = [  # under 80 characters a line: it's drawn on a portrait page too (`test_k1.draw`)
    "Form 8995  Qualified Business Income Deduction          OMB No. 1545-2294",
    "           Simplified Computation                       2025",
    "Name(s) shown on return                 Your taxpayer identification number",
    "Jordan B Quillfeather & Pat Quillfeather          ***-**-4410",
    "1 (a) Trade, business, or aggregation name  (b) TIN  (c) Qualified income",
    "i   Schedule E: 8813 WILLOWMERE LN, ZENTONVILLE  XXX-XX-6789      4,210",
    "ii  K1P: LARKSPUR RIDGE FUND LP              p12-3456789         64",
    "iii K1P: QUARRYSTONE HOMES LLC               23-4567890     (1,870)",
    "iv  K1P: ELM COURT AT HARBOR LLC             34-5678901        (55)",
    "2   Total qualified business income or (loss). Combine lines 1i",
    "    through 1v, column (c) ..............................  2      2,349",
    "3   Qualified business net (loss) carryforward from the prior",
    "    year ................................................  3   ( 14,694 )",
    "4   Total qualified business income. Combine lines 2 and 3 ...  4    0",
    "5   Qualified business income component. Line 4 by 20% .......  5    0",
    "6   Qualified REIT dividends and PTP income or (loss) ........  6    0",
    "7   Qualified REIT dividends and PTP (loss) carryforward .....  7   (  )",
    "8   Total qualified REIT dividends and PTP income ............  8    0",
    "9   REIT and PTP component. Multiply line 8 by 20% (0.20) ....  9    0",
    "10  QBI deduction before the income limitation ..............  10    0",
    "11  Taxable income before qualified business income deduction  11  187,400",
    "12  Net capital gain, increased by any qualified dividends ...  12   21,350",
    "13  Subtract line 12 from line 11. If zero or less, enter -0-  13  166,050",
    "14  Income limitation. Multiply line 13 by 20% (0.20) ........  14   33,210",
    "15  Qualified business income deduction ......................  15    0",
    "16  Total qualified business (loss) carryforward .............  16  ( 12,345 )",
    "17  Total qualified REIT dividends and PTP (loss) carryforward  17   ( 0 )",
    "Line 11 Enter your taxable income figured before any QBI deduction:",
    "    Form 1040 or 1040-SR, line 11a, ................ 210,150",
    "    minus Form 1040 or 1040-SR, line 12e, .......... 22,750",
]
CONTINUED = [
    "8995 QBI Deduction, Line 1, Continued                       2025",
    "Name(s) as shown on return                          Tax ID Number",
    "(a)Trade, business, or aggregation name  (b)TIN  (c)Qualified income",
    "K1P: BRAMBLE FLATS LLC                    45-6789012       (40)",
]


def read(path: Path) -> prior.Carryforwards:
    return prior.read(path.name, text.pages(path))


def test_each_business_and_every_line(tmp_path: Path):
    found = read(make_pdf(tmp_path / "2025 Return.pdf", [FORM_8995]))
    filed = found.qbi
    assert [(b.name, b.tin, b.income) for b in filed.businesses] == [
        ("Schedule E: 8813 WILLOWMERE LN, ZENTONVILLE", "XXX-XX-6789", 4210),  # the SSN printed masked
        ("K1P: LARKSPUR RIDGE FUND LP", "12-3456789", 64),  # a watermark letter glued to the number is left off
        ("K1P: QUARRYSTONE HOMES LLC", "23-4567890", -1870),
        ("K1P: ELM COURT AT HARBOR LLC", "34-5678901", -55)]
    assert (filed.line(2), filed.line(3), filed.line(16), filed.line(7), filed.line(14)) == (
        2349, -14694, -12345, 0, 33210)
    assert sorted(filed.lines) == list(range(2, 18))
    assert found.failed == [], found.failed
    assert sum(c.what.startswith("Form 8995") for c in found.checks) == 11


def test_a_continued_page_and_a_sum_that_misses(tmp_path: Path):
    more = [ln.replace("2,349", "2,309").replace("( 12,345 )", "( 12,385 )") for ln in FORM_8995]
    found = read(make_pdf(tmp_path / "2025 Return.pdf", [more, CONTINUED]))
    assert found.qbi.pages == [1, 2] and found.qbi.businesses[-1].income == -40
    assert found.failed == []
    off = [ln.replace("33,210", "33,201") for ln in FORM_8995]
    assert [c.what for c in read(make_pdf(tmp_path / "2025 Off.pdf", [off])).failed] == [
        "Form 8995: line 14 is 20% of line 13"]


def test_last_years_carryforward_is_this_years_line_3(tmp_path: Path):
    later = read(make_pdf(tmp_path / "2025 Return.pdf", [FORM_8995]))
    # 2024: the businesses lost 5,694 on top of 9,000 carried in, and 14,694 carried on
    earlier_page = [ln.replace("2025", "2024").replace("( 14,694 )", "( 9,000 )")
                    .replace("( 12,345 )", "( 14,694 )").replace("2,349", "(5,694)") for ln in FORM_8995]
    earlier = read(make_pdf(tmp_path / "2024 Return.pdf", [earlier_page]))
    assert earlier.qbi.line(16) == -14694
    assert [(c.what, c.ok) for c in f8995.link(earlier.qbi, 2024, later.qbi, 2025)] == [
        ("Form 8995: 2024's line 16 is 2025's line 3", True), ("Form 8995: 2024's line 17 is 2025's line 7", True)]
    assert any(c.what == "Form 8995: 2024's line 16 is 2025's line 3" for c in prior.link([later, earlier]))
    assert f8995.link(earlier.qbi, 2023, later.qbi, 2025) == []


def test_no_form_8995_is_none():
    assert f8995.read(["Form 8995-A Qualified Business Income Deduction"]) == (None, [])
    assert f8995.is_page("8995 QBI Deduction, Line 1, Continued 2025")
    assert f8995.is_page("8995 QBI Deduction, Line 1, Schedule 2024")  # whatever the word after "Line 1,"
    assert Decimal(0) == f8995.Filed().line(16)


def test_cli_says_what_it_read_never_the_amounts(tmp_path: Path, workspace_home: Path, capsys):
    assert cli.main(["prior", str(make_pdf(tmp_path / "2025 Return.pdf", [FORM_8995])), "--layout"]) == 0
    out = printed(capsys)
    assert "Form 8995 p[1]: 4 businesses, a loss carried on" in out
    assert "Form 8995 business, loss:" in out and "lines read: 2, 3, 4" in out
    assert not any(a in out for a in ("12,345", "14,694", "1,870", "33,210"))
