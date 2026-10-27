from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from conftest import printed
from test_k1 import draw

from taxtrace import cli, f1116b, prior, text

# Schedule B (Form 1116) as Drake prints it, by position: each column's heading, and its amounts right under it
HEADS_1 = {"i": 182, "ii": 241, "iii": 300, "iv": 359, "v": 419, "vi": 478, "vii": 537}
HEADS_2 = {"viii": 179, "ix": 240, "x": 300, "xi": 359, "xii": 418, "xiii": 476, "xiv": 535}
# each line's label, and the row under it its amounts sit on
LABELS = {1: (182, "Foreign tax carryover from the prior tax year", "columns of line 8 of the prior year"),
          2: (215, "Adjustments to line 1 (enter description):", "a Carryback adjustment"),
          3: (305, "Adjusted foreign tax carryover from", "prior tax year (combine 1 and 2)"),
          4: (323, "Foreign tax carryover used in current", "tax year (enter as negative)"),
          5: (340, "Foreign tax carryover expired unused", "in current tax year (negative)"),
          6: (364, "Foreign tax carryover generated in", "current tax year"),
          7: (380, "Actual or estimated amount of line 6", "to be carried back (negative)"),
          8: (404, "Foreign tax carryover to the following", "tax year. Combine lines 3 through 7.")}


def schedule(page: int, cells: dict[int, dict[str, str]], amt: bool = False, box: str | None = "c") -> list:
    heads = HEADS_1 if page == 1 else HEADS_2
    top = 158 if page == 1 else 40
    face = [(30, 27, "SCHEDULE B  Foreign Tax Carryover Reconciliation Schedule") if page == 1 else
            (30, 27, "Schedule B (Form 1116) (Rev. 12-2022)  Jordan Quillfeather"),
            (540, 30, "Page 2" if page == 2 else "OMB No. 1545-0121")]
    if page == 1:
        face += [(112, 64, "For 1116 AMT" if amt else "Department of the Treasury"),
                 (36, 115, "a"), (55, 115, "Reserved for future use"), (171, 115, "c"),
                 (190, 115, "Passive category income"), (284, 115, "e"), (300, 115, "Section 951A income"),
                 (36, 124, "b"), (55, 124, "Foreign branch category income"), (171, 124, "d"),
                 (190, 124, "General category income"), (285, 124, "f")]
        if box:
            face.append((182, 113 if box == "c" else 122, "X"))
        face.append((556, 168, "(add columns (i) through (vi))"))
    face += [(x, top, f"({roman})") for roman, x in heads.items()]
    for n, (label_top, label, more) in LABELS.items():
        face += [(32, label_top, str(n)), (47, label_top, label), (47, label_top + 8, more)]
        for roman, value in cells.get(n, {}).items():
            face.append((heads[roman] + 15, label_top + 8, value))
    if page == 1:
        face.append((182, 412, "-0-"))
    face.append((30, 425, "For Paperwork Reduction Act Notice, see the separate instructions."))
    face.append((470, 425, "Schedule B (Form 1116) (Rev. 12-2022)"))
    return face


# 2025: 90 of 2017's tax and 1,250 of 2024's came in, 400 of 2024's was used, 2,875 arose in 2025
REGULAR_1 = schedule(1, {1: {"iii": "90", "vii": "90"}, 3: {"iii": "90", "vii": "90"}, 8: {"iii": "90", "vii": "90"}})
REGULAR_2 = schedule(2, {1: {"viii": "90", "xii": "1,250", "xiv": "1,340"},
                         3: {"viii": "90", "xii": "1,250", "xiv": "1,340"},
                         4: {"xii": "-400", "xiv": "-400"},
                         6: {"xiii": "2,875", "xiv": "2,875"},
                         8: {"viii": "90", "xii": "850", "xiii": "2,875", "xiv": "3,815"}})
AMT_1 = schedule(1, {}, amt=True)
AMT_2 = schedule(2, {6: {"xiii": "12", "xiv": "12"}, 8: {"xiii": "12", "xiv": "12"}})


def read(path: Path) -> prior.Carryforwards:
    pages = text.pages(path)
    return prior.read(path.name, pages, {n: text.words(path, n) for n, p in enumerate(pages, 1)
                                         if prior.needs_words(p)})


def test_each_category_by_the_year_its_tax_arose(tmp_path: Path):
    # the order Drake printed one year: the AMT copy's page 2 before its own page 1
    found = read(draw(tmp_path / "2025 Return.pdf", [REGULAR_1, REGULAR_2, AMT_2, AMT_1]))
    regular, amt = found.foreign_tax
    assert (regular.category, regular.amt, regular.pages, amt.category, amt.amt, amt.pages) == (
        "passive", False, [1, 2], "passive", True, [4, 3])
    assert regular.lines[1] == {2017: 90, 2024: 1250}
    assert regular.lines[4] == {2024: -400}
    assert regular.following == {2017: 90, 2024: 850, 2025: 2875}
    assert regular.totals[8] == 3815
    assert amt.following == {2025: 12}
    assert found.failed == [], found.failed
    assert not found.questions
    assert len(found.checks) > 10


def test_sums_that_dont_add_up_fail(tmp_path: Path):
    off = [(x, top, "3,851" if phrase == "3,815" else phrase) for x, top, phrase in REGULAR_2]
    found = read(draw(tmp_path / "2025 Return.pdf", [REGULAR_1, off]))
    assert [c.what for c in found.failed] == [
        "Schedule B (Form 1116), passive, column (xiv): line 8 is lines 3 through 7 combined",
        "Schedule B (Form 1116), passive, line 8: the total (xiv) adds up its columns"]
    ten =schedule(1, {1: {"i": "40", "vii": "40"}, 3: {"i": "40", "vii": "40"}, 8: {"i": "40", "vii": "40"}})
    found = read(draw(tmp_path / "2025 Other.pdf", [ten]))
    assert "Schedule B (Form 1116), passive: the tenth preceding year's carryover expires, not carried on" in [
        c.what for c in found.failed]


def test_an_unchecked_category_and_a_lone_page_2_are_asked(tmp_path: Path):
    found = read(draw(tmp_path / "2025 Return.pdf", [schedule(1, {}, box=None), REGULAR_2, AMT_2]))
    assert [q.text for q in found.questions] == [
        "Schedule B (Form 1116) has a page 2 without its page 1: read it by hand.",
        "Schedule B (Form 1116): which category of income is this? No box is checked."]
    assert found.foreign_tax[0].category == ""
    general = read(draw(tmp_path / "2025 G.pdf", [schedule(1, {}, box="d")]))
    assert general.foreign_tax[0].category == "general"


def test_a_years_carryover_is_the_next_years_carryover_in(tmp_path: Path):
    # 2024: 90 of 2017's tax went on, and 1,250 arose in 2024
    earlier = read(draw(tmp_path / "2024 Return.pdf", [
        schedule(1, {1: {"iv": "90", "vii": "90"}, 3: {"iv": "90", "vii": "90"}, 8: {"iv": "90", "vii": "90"}}),
        schedule(2, {1: {"viii": "90", "xiv": "90"}, 3: {"viii": "90", "xiv": "90"},
                     6: {"xiii": "1,250", "xiv": "1,250"}, 8: {"viii": "90", "xiii": "1,250", "xiv": "1,340"}}),
        AMT_1, schedule(2, {})]))
    assert earlier.failed == [] and earlier.foreign_tax[0].following == {2017: 90, 2024: 1250}
    later = read(draw(tmp_path / "2025 Return.pdf", [REGULAR_1, REGULAR_2, AMT_1, AMT_2]))
    assert [(c.what, c.ok) for c in prior.link([later, earlier])] == [
        ("Schedule B (Form 1116), passive: 2024's carryover to the following year is 2025's carryover from the prior "
         "year", True),
        ("Schedule B (Form 1116), passive AMT: 2024's carryover to the following year is 2025's carryover from the "
         "prior year", True)]
    gap = read(draw(tmp_path / "2023 Return.pdf", [REGULAR_1, REGULAR_2]))
    assert f1116b.link(gap.foreign_tax, 2023, later.foreign_tax, 2025) == []  # a missing year: nothing to compare
    lost = read(draw(tmp_path / "2025 Lost.pdf", [REGULAR_1, schedule(2, {})]))
    assert [c.ok for c in prior.link([lost, earlier])] == [False]


def test_cli_prints_the_years_never_the_amounts(tmp_path: Path, workspace_home: Path, capsys):
    path = draw(tmp_path / "2025 Return.pdf", [REGULAR_1, REGULAR_2, AMT_2, AMT_1])
    assert cli.main(["prior", str(path), "--layout"]) == 0
    out = printed(capsys)
    assert "Schedule B (Form 1116), passive p[1, 2]: carryover to 2026 from 2017, 2024, 2025" in out
    assert "Schedule B (Form 1116), passive AMT p[4, 3]: carryover to 2026 from 2025" in out
    assert "line 8 from 2017, 2024, 2025" in out
    assert not any(a in out for a in ("2,875", "3,815", "1,250", "850"))
    saved = (workspace_home / "carryforwards" / "2025 Return.json").read_text()
    assert '"2025": "2875"' in saved


def test_is_page_needs_the_heading():
    assert f1116b.is_page("SCHEDULE B  Foreign Tax Carryover Reconciliation Schedule\n(Form 1116)")
    assert f1116b.is_page("Schedule B (Form 1116) (Rev. 12-2022)   Page 2")
    assert not f1116b.is_page("Schedule B (Form 1040) Interest and Ordinary Dividends")
    assert Decimal(0) == sum(f1116b.Schedule("passive", False, {}, {}).following.values())
