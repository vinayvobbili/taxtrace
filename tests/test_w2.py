"""W-2s drawn at the IRS form's print positions and at a payroll company's, for made-up people. All values invented."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from conftest import printed
from test_k1 import draw

from taxtrace import agi, cli, d400, entry, k1, text, w2

EMPLOYER = "Initech Payroll Services"


def irs_copy(top: float = 0.0, wages: str = "152,400.17") -> list:
    """The positions of the IRS's own form, one copy, starting `top` points down the page."""
    rows = [
        (157, 38.5, "a Employee’s social security number"), (170, 49.0, "XXX-XX-4410"),
        (42, 62.5, "b Employer identification number (EIN)"), (50, 74.0, "88-7654321"),
        (339, 62.5, "1"), (348, 62.5, "Wages, tips, other compensation"), (345, 74.0, wages),
        (461, 62.5, "2"), (471, 62.5, "Federal income tax withheld"), (470, 74.0, "22,310.44"),
        (42, 86.5, "c Employer’s name, address, and ZIP code"), (50, 98.0, EMPLOYER), (50, 108.0, "44 Birch Road"),
        (339, 86.5, "3"), (348, 86.5, "Social security wages"), (345, 98.0, "171,000.00"),
        (461, 86.5, "4"), (471, 86.5, "Social security tax withheld"), (470, 98.0, "10,602.00"),
        (339, 110.5, "5"), (348, 110.5, "Medicare wages and tips"), (345, 122.0, "178,000.00"),
        (461, 110.5, "6"), (471, 110.5, "Medicare tax withheld"), (470, 122.0, "2,581.00"),
        (339, 134.5, "7"), (348, 134.5, "Social security tips"), (461, 134.5, "8"), (471, 134.5, "Allocated tips"),
        (335, 170.5, "11"), (349, 170.5, "Nonqualified plans"),
        (461, 158.5, "10"), (471, 158.5, "Dependent care benefits"),
        (458, 182.5, "12a"), (471, 182.5, "See instructions for box 12"), (458, 190.0, "C"), (475, 194.0, "D"),
        (510, 194.0, "24,500.00"), (458, 197.0, "o"),
        (458, 206.5, "12b"), (458, 214.0, "C"), (475, 218.0, "DD"), (510, 218.0, "19,250.10"),
        (458, 230.5, "12c"), (458, 238.0, "Co"), (458, 254.5, "12d"), (458, 262.0, "C"),
        (42, 182.5, "e Employee’s first name and initial"), (50, 196.0, "Jordan Q Quillfeather"),
        (38, 290.5, "15 State Employer’s state ID number"), (40, 303.0, "CO"), (70, 303.0, "12-3456"),
        (197, 290.5, "16"), (209, 290.5, "State wages, tips, etc."), (205, 303.0, "152,400.17"),
        (284, 290.5, "17"), (296, 290.5, "State income tax"), (295, 303.0, "6,081.00"),
        (363, 290.5, "18"), (375, 290.5, "Local wages, tips, etc."),
        (449, 290.5, "19"), (461, 290.5, "Local income tax"),
        (58, 340.7, "W-2"), (289, 340.7, "2026"), (106, 346.3, "Wage and Tax Statement"),
    ]
    return [(x, y + top, phrase) for x, y, phrase in rows]


def payroll_copy(x: float = 0.0, top: float = 0.0) -> list:
    """A payroll company's substitute: shortened labels, values beside them, no year-row title like the IRS's."""
    rows = [
        (10, 20, "W-2 Wage and Tax Statement 2026"),
        (10, 34, "b EIN"), (60, 34, "77-1234567"), (10, 46, "a SSN"), (60, 46, "XXX-XX-9921"),
        (10, 60, "c Employer’s name"), (10, 70, "Globex Staffing LLC"),
        (10, 90, "1 Wages, Tips, Other Comp."), (120, 90, "60,000.00"),
        (160, 90, "2 Federal Income Tax"), (250, 90, "5,000.00"),
        (10, 110, "3 Social Security Wages"), (120, 110, "60,000.00"),
        (160, 110, "4 Social Security Tax"), (250, 110, "3,720.00"),
        (10, 130, "5 Medicare Wages"), (120, 130, "60,000.00"),
        (160, 130, "6 Medicare Tax"), (250, 130, "870.00"),
        (10, 150, "12a"), (40, 150, "D"), (60, 150, "3,000.00"),
        (10, 170, "16 State Wages"), (120, 170, "60,000.00"), (160, 170, "17 State Income Tax"), (250, 170, "2,400.00"),
    ]
    return [(x + a, top + b, phrase) for a, b, phrase in rows]


def read(path: Path) -> list[w2.W2]:
    pages = text.pages(path)
    return w2.read(path.name, {n: text.words(path, n) for n, p in enumerate(pages, 1) if w2.is_form(p)})


def test_the_irs_forms_boxes_are_read_under_their_labels(tmp_path: Path):
    found = read(draw(tmp_path / "w2.pdf", [irs_copy() + irs_copy(396)]))
    assert len(found) == 1  # two copies on a page are one form
    f = found[0]
    assert {b: str(v.amount) for b, v in f.amounts.items()} == {
        "1": "152400.17", "2": "22310.44", "3": "171000.00", "4": "10602.00", "5": "178000.00", "6": "2581.00",
        "16": "152400.17", "17": "6081.00"}
    assert {c: str(v.amount) for c, v in f.box_12.items()} == {"D": "24500.00", "DD": "19250.10"}
    assert (f.year, f.ein, f.employee, f.state) == (2026, "88-7654321", "4410", "CO")
    assert f.employer == EMPLOYER
    assert f.failed == []
    assert f.questions == []
    assert k1.verify(f, text.words(tmp_path / "w2.pdf", 1)) == []


def test_the_irs_forms_own_page_with_made_up_values():
    """The real form's words, not a drawing of it: see scripts/make-w2-fixture."""
    words = json.loads((Path(__file__).parent / "data" / "w2-irs-words.json").read_text(encoding="utf-8"))
    assert w2.is_form(" ".join(w["text"] for w in words))
    found = w2.read("fw2.pdf", {1: words})
    assert len(found) == 1
    f = found[0]
    assert {b: str(v.amount) for b, v in f.amounts.items()} == {
        "1": "152400.17", "2": "22310.44", "3": "171000.00", "4": "10602.00", "5": "178000.00", "6": "2581.00",
        "16": "152400.17", "17": "6081.00"}
    assert {c: str(v.amount) for c, v in f.box_12.items()} == {"D": "24500.00", "DD": "19250.10"}
    assert (f.year, f.ein, f.employee, f.state, f.employer) == (2026, "88-7654321", "4410", "CO", EMPLOYER)
    assert f.failed == []
    assert f.questions == []
    assert k1.verify(f, words) == []


def test_only_the_last_four_of_the_ssn_are_kept(tmp_path: Path):
    copy = [(x, y, "123-45-4410" if p == "XXX-XX-4410" else p) for x, y, p in irs_copy()]
    f = read(draw(tmp_path / "w2.pdf", [copy]))[0]
    assert f.employee == "4410"
    assert "123-45" not in json.dumps(f.to_json())


def test_a_payroll_companys_shorter_labels_and_values_beside_them(tmp_path: Path):
    f = read(draw(tmp_path / "w2.pdf", [payroll_copy()]))[0]
    assert {b: str(v.amount) for b, v in f.amounts.items()} == {
        "1": "60000.00", "2": "5000.00", "3": "60000.00", "4": "3720.00", "5": "60000.00", "6": "870.00",
        "16": "60000.00", "17": "2400.00"}
    assert {c: str(v.amount) for c, v in f.box_12.items()} == {"D": "3000.00"}
    assert (f.year, f.ein, f.employee) == (2026, "77-1234567", "9921")
    assert f.employer == "Globex Staffing LLC"
    assert f.failed == []


def test_four_copies_on_a_page_are_one_form(tmp_path: Path):
    page = payroll_copy() + payroll_copy(x=300) + payroll_copy(top=380) + payroll_copy(x=300, top=380)
    found = read(draw(tmp_path / "w2.pdf", [page]))
    assert len(found) == 1
    assert found[0].amounts["2"].amount == Decimal("5000.00")
    assert found[0].questions == []


def test_copies_showing_other_wages_are_asked_about(tmp_path: Path):
    page = irs_copy() + irs_copy(396, wages="9,999.99")
    assert "different box 1 wages" in read(draw(tmp_path / "w2.pdf", [page]))[0].questions[0].text


def test_the_same_form_on_two_pages_counts_once(tmp_path: Path):
    first, second = read(draw(tmp_path / "w2.pdf", [irs_copy(), irs_copy()]))
    assert (first.copy_of, second.copy_of) == (None, 1)


def test_a_blank_form_or_its_instructions_arent_a_w2(tmp_path: Path):
    blank = [row for row in irs_copy() if not w2.MONEY.match(row[2])]
    assert read(draw(tmp_path / "blank.pdf", [blank])) == []
    prose = [(40, 40, "Instructions: enter wages, tips, other compensation and federal income tax withheld from W-2")]
    assert read(draw(tmp_path / "prose.pdf", [prose])) == []


def test_arithmetic_that_doesnt_hold_fails_a_check(tmp_path: Path):
    wrong = [(x, y, "1,000.00" if p == "10,602.00" else "10.00" if p == "2,581.00" else p) for x, y, p in irs_copy()]
    failed = {c.what for c in read(draw(tmp_path / "w2.pdf", [wrong]))[0].failed}
    assert failed == {"box 4 is 6.2% of box 3", "box 6 is at least 1.45% of box 5"}


def test_more_tax_than_145_percent_is_the_additional_medicare_tax(tmp_path: Path):
    more = [(x, y, "4,000.00" if p == "2,581.00" else p) for x, y, p in irs_copy()]
    assert read(draw(tmp_path / "w2.pdf", [more]))[0].failed == []


def test_boxes_that_need_more_are_asked_about(tmp_path: Path):
    extras = [*irs_copy(), (470, 170.0, "1,500.00"), (345, 182.0, "2,000.00"), (510, 242.0, "850.00"),
              (475, 242.0, "W"), (205, 320.0, "5,000.00")]
    questions = " ".join(q.text for q in read(draw(tmp_path / "w2.pdf", [extras]))[0].questions)
    assert "box 10" in questions
    assert "box 11" in questions
    assert "code W" in questions
    assert "more than one state" in questions


def test_an_amount_in_box_12_with_no_code_is_asked_about(tmp_path: Path):
    copy = [row for row in irs_copy() if row[2] != "D"]
    f = read(draw(tmp_path / "w2.pdf", [copy]))[0]
    assert "box 12a has an amount with no code" in f.questions[0].text
    assert "D" not in f.box_12


def test_a_missing_year_fails_a_check(tmp_path: Path):
    copy = [row for row in irs_copy() if row[2] != "2026"]
    assert "the tax year is printed" in {c.what for c in read(draw(tmp_path / "w2.pdf", [copy]))[0].failed}


def test_the_command_saves_the_values_and_prints_them_masked(workspace_home, tmp_path: Path, capsys):
    path = draw(tmp_path / "docs" / "2026 W-2 Initech.pdf", [irs_copy() + irs_copy(396)])
    assert cli.main(["w2", str(path)]) == 0
    out = printed(capsys)
    for secret in ("152,400", "22,310", "24,500", "7654321", "4410", "Initech Payroll", "Quillfeather"):
        assert secret not in out
    assert "2026 Form W-2" in out
    saved = json.loads((workspace_home / "forms" / "2026 W-2 Initech.json").read_text())
    assert saved[0]["form"] == "W-2"
    assert saved[0]["amounts"]["1"]["amount"] == "152400.17"
    assert saved[0]["box_12"]["D"]["amount"] == "24500.00"


def test_the_command_says_when_it_finds_none(workspace_home, tmp_path: Path, capsys):
    path = draw(tmp_path / "other.pdf", [[(40, 40, "Not a tax form")]])
    assert cli.main(["w2", str(path)]) == 0
    assert "no W-2s found" in printed(capsys)


def saved_form(tmp_path: Path) -> dict:
    return read(draw(tmp_path / "w2.pdf", [irs_copy()]))[0].to_json()


def test_a_real_w2_replaces_the_pay_stub_everywhere(tmp_path: Path):
    form = saved_form(tmp_path)
    stub = {"form": "paystub", "file": "stub.pdf", "year": 2026, "paid": "2026-10-30", "period_start": "2026-10-16",
            "period_end": "2026-10-31", "taxable_wages": {"current": "1", "year_to_date": "1", "label": "x"}}
    sheet = entry.build(2026, forms=[stub, form], k1s=[], returns=[], today=date(2027, 2, 1))
    wages = next(s for s in sheet.sections if s.title.startswith("Wages"))
    got = {r.what: (r.value, r.status) for r in wages.rows}
    assert got["Box 1, Wages, tips, other compensation"] == ("152,400.17", entry.READY)
    assert got["Box 2, Federal income tax withheld"] == ("22,310.44", entry.READY)
    assert got["Box 12 code D"] == ("24,500.00", entry.READY)
    assert got["Box 17, CO, State income tax"] == ("6,081.00", entry.READY)
    assert EMPLOYER in wages.title
    assert "Form W-2" not in sheet.coming
    federal = agi.build(2026, forms=[stub, form], k1s=[], returns=[])
    assert federal.line("1z").amount == Decimal("152400.17")
    assert federal.line("1z").status == agi.READY
    withheld, status, _ = d400._withheld(2026, [stub, form], [])
    assert (withheld, status) == (Decimal("6081.00"), d400.READY)
