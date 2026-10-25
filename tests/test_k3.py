"""Schedule K-3s drawn at the form's positions (narrowed to fit the page), for test_k1's made-up partnership."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from test_k1 import EIN, FACE, draw

from taxtrace import cli, k3, text

FIRST = [
    (38, 38, "Schedule K-3"), (150, 38, "Partner's Share of Income, Deductions,"), (38, 50, "(Form 1065)"),
    (160, 50, "Credits, etc.—International"), (100, 70, "For calendar year 2025, or tax year beginning"),
    (60, 90, "Information About the Partnership"), (300, 90, "Information About the Partner"),
    (46, 100, EIN), (300, 100, "XXX-XX-4410"),
    (536, 212, "Yes"), (560, 212, "No"),
    (65, 225, "1 Does Part I apply?"), (563, 224, "X"),
    (65, 237, "2 Does Part II apply?"), (541, 236, "X"),
    (65, 249, "3 Does Part III apply?"), (563, 248, "X"),
]
HEAD = [(40, 20, "Schedule K-3 (Form 1065) 2025 Page 2"), (40, 30, "Name of partnership EIN Name of partner SSN")]
FOOT = [(440, 760, "Schedule K-3 (Form 1065) 2025")]
PART_TWO = [
    *HEAD,
    (40, 150, "Part II Foreign Tax Credit Limitation"), (40, 170, "Section 1—Gross Income"),
    (97, 194, "Description"), (200, 194, "(a) U.S."), (250, 194, "(b) Branch"), (300, 194, "(c) Passive"),
    (350, 194, "(d) General"), (400, 194, "(e) Other"), (450, 190, "(f) Partner"), (520, 194, "(g) Total"),
    (43, 220, "6 Interest income"),
    (60, 229, "US"), (48, 231.5, "A"), (225, 229, "30"), (545, 229, "30"),
    (60, 241, "CA"), (48, 243.5, "B"), (325, 241, "7"), (545, 241, "7"),  # foreign source, passive category
    (43, 260, "24 Total gross income (combine lines 1"), (58, 268, "through 23)"),
    (225, 268, "30"), (325, 268, "7"), (545, 268, "37"),
    (40, 290, "Section 2—Deductions"),
    (43, 300, "25 Expenses allocable to sales income"), (225, 300, "12"), (545, 300, "12"),
    (43, 315, "54 Total deductions (combine lines 25"), (58, 323, "through 53)"), (225, 323, "12"), (545, 323, "12"),
    (43, 340, "55 Net income (loss) (subtract line 54"), (58, 348, "from line 24)"),
    (225, 348, "18"), (325, 348, "7"), (545, 348, "25"),
    *FOOT,
]
TAXES = [
    *HEAD,
    (40, 60, "Part III Other Information for Preparation of Form 1116 or 1118"), (40, 75, "Section 4—Foreign Taxes"),
    (58, 100, "1 Direct (section 901 or 903) foreign taxes:"), (48, 120, "A"), (300, 120, "15"),
    *FOOT,
]


def read(path: Path) -> list[k3.K3]:
    pages = text.pages(path)
    return k3.read(path.name, {n: text.words(path, n) for n, p in enumerate(pages, 1) if k3.is_page(p)}, pages)


def test_part_two_by_line_row_country_and_column(tmp_path: Path):
    path = draw(tmp_path / "k3.pdf", [FIRST, PART_TWO])
    (found,) = read(path)
    assert (found.page, found.year, found.ein, found.partner) == (1, 2025, EIN, "4410")
    assert found.parts == {"I": False, "II": True, "III": False}
    assert [(c.line, c.row, c.country, c.column, c.value.amount) for c in found.cells[:4]] == [
        (6, "A", "US", "a", Decimal(30)), (6, "A", "US", "g", Decimal(30)),
        (6, "B", "CA", "c", Decimal(7)), (6, "B", "CA", "g", Decimal(7))]
    assert found.amount(24, "g", "") == Decimal(37) and found.amount(55, "c", "") == Decimal(7)
    assert found.foreign_columns() == {"c"}
    assert {c.what for c in found.checks} >= {
        "Part II line 6 row B: its columns add up to its total (g)",
        "Part II line 24, column (g): lines 1 through 23 added up",
        "Part II line 55, column (a): line 24 less line 54"}
    assert found.failed == [] and found.questions == []
    assert k3.verify(found, {n: text.words(path, n) for n in (1, 2)}) == []


def test_a_row_or_total_that_does_not_add_up_fails(tmp_path: Path):
    wrong = [(x, top, "9" if (x, top) == (545, 241) else phrase) for x, top, phrase in PART_TWO]
    (found,) = read(draw(tmp_path / "k3.pdf", [FIRST, wrong]))
    assert [(c.what, c.quote) for c in found.failed] == [
        ("Part II line 6 row B: its columns add up to its total (g)", "7 against 9"),
        ("Part II line 24, column (g): lines 1 through 23 added up", "39 against 37")]


def test_part_two_is_tied_to_the_k1s_boxes(tmp_path: Path):
    (found,) = read(draw(tmp_path / "k3.pdf", [FIRST, PART_TWO]))
    k3.tie(found, [("5", Decimal(37)), ("1", Decimal(-4210))])
    assert [(c.what, c.ok) for c in found.checks if "K-1" in c.what] == [
        ("Part II line 6: its total (g) is the K-1's box 5", True)]  # its countries' rows added up
    k3.tie(found, [("5", Decimal(40))])
    assert found.failed[-1].quote == "37 against 40"


def test_foreign_taxes_are_a_question(tmp_path: Path):
    (found,) = read(draw(tmp_path / "k3.pdf", [FIRST, PART_TWO, TAXES]))
    assert [v.amount for v in found.foreign_taxes] == [Decimal(15)]  # not the "901 or 903" in its label
    assert [q.text.split(":")[0] for q in found.questions] == ["Part III, Section 4 has foreign taxes"]


def test_cli_reads_a_k3_with_its_k1(tmp_path: Path, workspace_home: Path, capsys):
    federal, schedule = draw(tmp_path / "2025 K-1.pdf", [FACE]), draw(tmp_path / "2025 K-3.pdf", [FIRST, PART_TWO])
    assert cli.main(["k1", str(federal), str(schedule), "--layout"]) == 0
    out = capsys.readouterr().out
    assert "box 16: a Schedule K-3 is attached" not in out  # it's read in the same run
    assert ("Schedule K-3 from ##-#######, parts that apply II; Part II amounts on lines 6, 24, 25, 54, 55; "
            "15 of 15 checks pass, 0 questions") in out  # 6 rows, 8 totals' columns, and box 5
    assert "foreign source: amounts in columns (c); foreign taxes: none" in out
    assert "p2 line 6 B CA (c): # at" in out
    assert json.loads((workspace_home / "k1" / "2025 K-3.json").read_text())[0]["form"] == "K-3"
