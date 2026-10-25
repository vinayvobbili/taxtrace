"""D-403 NC K-1s drawn at the form's own positions, for the made-up partnership in test_k1. Every value is invented."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from conftest import printed
from test_k1 import FACE, PARTNERSHIP, draw, edited

from taxtrace import cli, k1, nck1, text

NC_FORM = [
    (36, 38, "NC K-1 (25)"), (228, 38, "2025 Partner's Share of"), (36, 52, "(D-403)"),
    (177, 50, "N.C. Income, Adjustments, and Credits"),
    (58, 186, "Partnership's Federal Employer ID Number"), (267, 186, "Partnership's Name, Address, and Zip Code"),
    (54, 193, "881234567"), (262, 193, PARTNERSHIP),
    (58, 222, "Is the partnership a Taxed Partnership?"), (137, 241, "X"), (81, 245, "Yes"), (120, 245, "No"),
    (58, 307, "Partner's Identifying Number"), (54, 313, "300624410"),
    (58, 342, "Was the partner a N.C. resident on the last day of the"), (58, 349, "partnership's taxable year?"),
    (94, 361, "X"), (73, 366.6, "Yes"), (112, 366.6, "No"),
    (310, 385, "X"), (58, 391.4, "Is the partner a beneficial owner of a disregarded entity?"),  # under its answers
    (253, 389.4, "Yes"), (292, 389.4, "No"),
    (38, 461, "A. All Partners"), (53, 473, "Partner's Pro Rata Share of the Following Items:"), (307, 473, "Amount"),
    (391, 473, "Individuals Filing Form D-400 Enter Amount on:"),
    (313, 493, "-2298"), (40, 499.4, "1. Income (Loss)"),
    (327, 505, "450"), (40, 510.2, "2. Additions to Income (Loss)"), (433, 510.2, "Form D-400 Schedule S, Part A"),
    (320, 517, "1200"), (40, 522.2, "3. Deductions from Income (Loss)"),
    (341, 529, "0"), (40, 534.2, "4. Tax Credits"),
    (40, 546.2, "5. Tax Withheld from Compensation Paid for Services"), (341, 553, "0"),
    (52, 555.8, "Performed in N.C."), (416, 555.8, "Form D-400, Line 20 (N.C. residents only)"),
    (38, 567, "B. Nonresident Partners Only"), (307, 581, "Amount"),
    (342, 601, "0"), (40, 607.4, "6. Line 1 Attributable to North Carolina"),
    (342, 625, "0"), (40, 631.4, "7. Line 2 Attributable to North Carolina"),
    (342, 649, "0"), (40, 654.2, "8. Line 3 Attributable to North Carolina"),
    (342, 661, "0"), (40, 665, "9. Net Tax Paid by the Partnership"),
    (38, 676, "C. Taxed Partnerships Only"), (307, 688, "Amount"),
    (342, 709, "0"), (36, 715.4, "10. Loss Attributable to North Carolina"),
    (342, 733, "0"), (36, 738.2, "11. Income Attributable to North Carolina"),
]
SECRETS = ["2298", "1200", "1234567", "300624410", "Larkspur"]


def read(path: Path) -> list[nck1.NCK1]:
    pages = text.pages(path)
    return nck1.read(path.name, {n: text.words(path, n) for n, p in enumerate(pages, 1) if nck1.is_form(p)})


def test_every_line_goes_to_the_label_under_its_amount(tmp_path: Path):
    path = draw(tmp_path / "nc.pdf", [NC_FORM, NC_FORM])
    first, copy = read(path)
    assert (first.year, first.ein, first.partnership, first.partner) == (2025, "88-1234567", PARTNERSHIP, "4410")
    assert {n: v.amount for n, v in first.lines.items()} == {
        1: Decimal(-2298), 2: Decimal(450), 3: Decimal(1200), **{n: Decimal(0) for n in range(4, 12)}}
    # line 5's label takes two rows, and its amount sits above the second
    assert abs(first.lines[5].top - 553) < 1
    assert (first.resident, first.taxed_partnership, first.disregarded_entity) == (True, False, False)
    assert first.failed == []
    assert [q.text.split(":")[0] for q in first.questions] == ["lines 2 and 3"]
    assert copy.copy_of == 1 and copy.questions == []
    assert k1.verify(first, text.words(path, 1)) == []


def test_nonresident_lines_on_a_residents_k1_fail(tmp_path: Path):
    (found,) = read(draw(tmp_path / "nc.pdf", [[(x, top, "75" if (x, top) == (342, 601) else phrase)
                                                for x, top, phrase in NC_FORM]]))
    assert [(c.what, c.quote) for c in found.failed] == [
        ("lines 6 to 9 are for nonresident partners only, and the form says this K-1 isn't one", "75")]


def test_line_one_is_checked_against_the_federal_k1(tmp_path: Path):
    (nc,) = read(draw(tmp_path / "nc.pdf", [NC_FORM]))
    federal = [(i.box, i.value.amount) for i in k1.face("f.pdf", 1, text.words(draw(tmp_path / "f.pdf", [FACE]), 1))
               .items if i.value.amount is not None]
    nck1.tie(nc, federal)  # boxes 1, 2 and 5; box 13's deduction and box 19's distribution aren't income
    assert [c.what for c in nc.checks if c.what.startswith("line 1")] == [
        "line 1 is the federal K-1's Part III lines 1 to 11 added up"] and nc.failed == []
    nck1.tie(nc, [*federal, ("9a", Decimal(80))])
    assert nc.failed[-1].quote == "-2218 against -2298"


def test_cli_ties_an_nc_k1_to_a_federal_one_read_on_an_earlier_run(tmp_path: Path, workspace_home: Path, capsys):
    federal, state = draw(tmp_path / "2025 K-1 Larkspur.pdf", [FACE]), draw(tmp_path / "2025 NC K-1.pdf", [NC_FORM])
    assert cli.main(["k1", str(federal)]) == 0
    capsys.readouterr()
    assert cli.main(["k1", str(state), "--layout"]) == 0
    out = printed(capsys)
    for secret in SECRETS:
        assert secret not in out
    assert ("NC K-1 (D-403) from ##-#######, amounts on lines 1, 2, 3; 3 of 3 checks pass, 1 questions; "
            "resident yes, taxed partnership no, disregarded entity no") in out
    assert "line 1: -#### at" in out
    saved = json.loads((workspace_home / "k1" / "2025 NC K-1.json").read_text())
    assert saved[0]["form"] == "D-403" and saved[0]["partner"] == "4410"
    assert saved[0]["lines"]["2"] | {"top": 0, "x0": 0} == {
        "amount": "450", "page": 1, "top": 0, "x0": 0, "quote": "450", "label": "Additions to income (loss)",
        "goes": "Form D-400 Schedule S, Part A"}


def test_cli_asks_for_the_federal_k1_when_none_has_been_read(tmp_path: Path, workspace_home: Path, capsys):
    other = edited(NC_FORM, **{"881234567": "880000001"})
    assert cli.main(["k1", str(draw(tmp_path / "nc.pdf", [other]))]) == 0
    assert "question: no federal K-1 from this partnership for this partner has been read" in capsys.readouterr().out
