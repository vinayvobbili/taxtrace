"""Forms 1098 drawn at a lender's print positions, for a made-up lender and property. Every value is invented."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from conftest import printed
from test_k1 import FACE, draw, edited

from taxtrace import cli, f1098, k1, text

LENDER = "Thistledown Home Lending"
PROPERTY = ["2208 Quenby Mill Road", "Larkspur", "ZZ 99902"]
# (x, top, text): each phrase is drawn in one piece; a box's number is apart from its label, as the lender prints it
FORM_1098 = [
    (365, 251.6, "CORRECTED (if checked)"),
    (22, 264.8, "RECIPIENT’S/LENDER’S name, street address, city or town"),
    (22, 270.8, "foreign postal code, and telephone no."),
    (35, 282.5, LENDER), (35, 288.8, "PO Box 4417"), (35, 298.3, "Fernmoor, ZZ 99901-0000"),
    (456, 274.5, "Form 1098"), (500, 286.5, "Mortgage Interest Statement"),
    (440, 303.0, "For calendar year"), (454, 310.3, "2025"),
    (324, 321.6, "1"), (333, 321.6, "M ortgage interest received from payer(s)/borrower(s)*"), (567, 321.6, "Copy B"),
    (323, 329.2, "$"), (388, 329.2, "6,842.17"), (561, 329.2, "For Payer/"),
    (22, 334.6, "PAYER’S/BORROWER’S name, street address (including apt. no.)"),
    (324, 340.3, "2"), (333, 338.0, "Outstanding mortgage principal"),
    (444, 340.3, "3"), (453, 338.0, "Mortgage origination date"), (564, 338.0, "Borrower"),
    (323, 345.8, "$"), (351, 345.8, "171,305.62"), (456, 347.9, "06/14/2017"), (552, 351.8, "1 and 10 is important"),
    (324, 357.8, "4"), (333, 357.8, "Refund of overpaid interest"),
    (444, 357.8, "5"), (453, 357.8, "Mortgage insurance premiums"),
    (323, 365.9, "$"), (441, 365.9, "$"),
    (323, 375.8, "6"), (332, 375.8, "Points paid on purchase"), (331, 381.8, "of principal residence"),
    (424, 375.8, "7"), (433, 375.8, "If address of property securing"),
    (433, 381.8, "mortgage is the same as PAYER’S/BORROWER’S"), (433, 389.7, "address, the box is checked"),
    (74, 386.6, "Jordan Q. Quillfeather"), (323, 393.8, "$"),
    (323, 405.8, "8"), (332, 405.8, "Address or description of property securing mortgage"),
    (340, 417.8, PROPERTY[0]), (340, 423.8, PROPERTY[1]), (388, 423.8, PROPERTY[2]),
    (323, 434.5, "9"), (332, 434.5, "Number of properties securing"),
    (436, 434.5, "10"), (449, 434.5, "Other"), (448, 441.5, "$1,486.20COUNTYTAX"),
    (322, 452.1, "11"), (335, 452.1, "Mortgage acquisition date"),
    (436, 452.1, "Account number (see instructions)"), (463, 459.5, "0048213377"),
    (323, 470.8, "RECIPIENT’S/LENDER’S TIN"), (454, 470.8, "PAYER’S/BORROWER’S TIN"),
    (343, 477.5, "88-7654321"), (461, 477.5, "XXX-XX-4410"),
    (19, 490.7, "Form 1098 (Rev. 1-2025) (Keep for your records) www.irs.gov/Form1098"),
    (314, 516.7, "Box 2. Shows the outstanding principal on the mortgage as of January 1"),
    (23, 645.4, "Account number. May show an account or other unique number"),
    (23, 662.4, "Box 1. Shows the mortgage interest received by the recipient/lender"),
]
SECRETS = ["6,842", "6842", "171,305", "1,486", "0048213377", "7654321", "4410", "Thistledown", "Quenby", "2208"]


def read(path: Path) -> list[f1098.F1098]:
    pages = text.pages(path)
    return f1098.read(path.name, {n: text.words(path, n) for n, p in enumerate(pages, 1) if f1098.is_form(p)})


def test_each_box_is_read_under_its_label(tmp_path: Path):
    path = draw(tmp_path / "1098.pdf", [FORM_1098, FORM_1098])
    first, copy = read(path)
    assert {box: v.amount for box, v in first.amounts.items()} == {
        "1": Decimal("6842.17"), "2": Decimal("171305.62"), "10": Decimal("1486.20")}
    assert (first.year, first.lender, first.lender_tin, first.payer, first.account) == (
        2025, LENDER, "88-7654321", "4410", "0048213377")
    assert (first.origination, first.acquisition, first.address, first.properties) == (
        "06/14/2017", "", " ".join(PROPERTY), None)
    assert (first.other, first.corrected, first.same_address) == ("COUNTYTAX", False, False)
    assert first.failed == [] and len(first.checks) == 3
    assert [q.text.split(" (")[0] for q in first.questions] == ["box 10"]
    assert copy.copy_of == 1 and copy.questions == []
    assert k1.verify(first, text.words(path, 1)) == []


def test_a_corrected_form_with_a_refund_and_no_property_asks(tmp_path: Path):
    marked = [(355, 251.6, "X"), *[(x, top, phrase) for x, top, phrase in FORM_1098 if phrase not in PROPERTY],
              (351, 365.9, "212.00")]
    (found,) = read(draw(tmp_path / "1098.pdf", [marked]))
    assert found.corrected and found.amount("4") == Decimal("212.00") and found.address == ""
    assert [q.text.split(":")[0] for q in found.questions] == [
        "a corrected 1098", "which property the mortgage is on", "box 4", "box 10 (other)"]


def test_interest_out_of_line_with_the_principal_fails(tmp_path: Path):
    (found,) = read(draw(tmp_path / "1098.pdf", [edited(FORM_1098, **{"171,305.62": "17,130.56"})]))
    assert [(c.what, c.quote) for c in found.failed] == [
        ("box 1 is under 15% of box 2's principal", "6,842.17 against 17,130.56")]


def test_other_forms_are_not_read_as_a_1098(tmp_path: Path):
    path = draw(tmp_path / "k1.pdf", [FACE])
    assert not f1098.is_form(text.pages(path)[0])
    assert f1098.form("k1.pdf", 1, text.words(path, 1)) is None


def test_cli_prints_no_amounts_or_names(tmp_path: Path, workspace_home: Path, capsys):
    path = draw(tmp_path / "2025 Mortgage 1098.pdf", [FORM_1098])
    assert cli.main(["1098", str(path), "--layout"]) == 0
    out = printed(capsys)
    for secret in SECRETS:
        assert secret not in out
    assert "2025 Form 1098 from ##-#######, amounts in boxes 1, 2, 10; 3 of 3 checks pass, 1 questions" in out
    assert "box 1: #,###.## at" in out
    saved = json.loads((workspace_home / "forms" / "2025 Mortgage 1098.json").read_text())
    assert saved[0]["form"] == "1098" and saved[0]["amounts"]["1"]["amount"] == "6842.17"
    assert saved[0]["amounts"]["10"]["label"] == "Other" and saved[0]["address"] == " ".join(PROPERTY)
