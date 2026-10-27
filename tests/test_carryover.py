from __future__ import annotations

from pathlib import Path

from conftest import printed
from test_f1116b import AMT_1, AMT_2, REGULAR_1, REGULAR_2, read
from test_f8995 import FORM_8995  # its line 16 is the worksheet's QBI loss carryover
from test_k1 import draw

from taxtrace import cli

# Drake's Carryover Worksheet by position, with a letter of the "Client Copy" watermark among the rows
WORKSHEET = [
    (245, 25, "Carryover Worksheet"),
    (154, 37, "List of items that will carryover to the 2026 tax return"),
    (486, 49, "2025"),
    (47, 98.6, "Itemized Deductions"), (504, 98.6, "Carryover Amount"),
    (54, 110.5, "Contributions subject to 60% of AGI limitations ................"),
    (54, 182.5, "State/local taxes paid in 2025 to 2026 to the Schedule A ......"), (546, 182.5, "1,480"),
    (47, 218.6, "Expenses"),
    (363, 225.4, "y"),
    (54, 256.2, "Disallowed investment interest expense"), (324, 256.2, "AM T"), (450, 256.2, "Reg. Tax"),
    (47, 302.6, "Losses"),
    (54, 374.5, "QBI loss carryover ................................"), (540, 374.5, "12,345"),
    (47, 398.6, "Credits"),
    (54, 434.5, "Foreign Tax credit......................"), (324, 434.5, "AMT"), (409, 434.5, "12"),
    (450, 434.5, "Reg. Tax"), (546, 434.5, "3,815"),
    (47, 470.6, "Other"),
    (54, 482.5, "Preparer Fee........................................"), (557, 482.5, "450"),
    (54, 508.2, "Estimated Tax Payment 1"), (392, 508.2, "Estimated Tax Payment 3"),
    (54, 530.5, "Federal tax liability for 2025 calculation ........"), (540, 530.5, "31,906"),
    (54, 554.5, "IRA basis.............."), (310, 554.5, "Taxpayer"), (409, 554.5, "7,000"), (454, 554.5, "Spouse"),
    (546, 554.5, "6,500"),
    (47, 662.6, "Passive Activity"),
    (47, 698.6, "At Risk Limitations"),
    (40, 761.8, "WK_CARRY.LD"),
]


def test_each_row_and_whose_amount_it_is(tmp_path: Path):
    found = read(draw(tmp_path / "2025 Return.pdf", [WORKSHEET, FORM_8995]))
    assert [(i.section, i.label, i.amounts) for i in found.carryovers] == [
        ("Itemized Deductions", "State/local taxes paid in 2025 to 2026 to the Schedule A", {"amount": 1480}),
        ("Losses", "QBI loss carryover", {"amount": 12345}),
        ("Credits", "Foreign Tax credit", {"amt": 12, "regular": 3815}),
        ("Other", "Preparer Fee", {"amount": 450}),
        ("Other", "Federal tax liability for 2025 calculation", {"amount": 31906}),
        ("Other", "IRA basis", {"taxpayer": 7000, "spouse": 6500})]
    assert not found.questions
    # no Schedule B in this return, yet a foreign tax credit carried: that's a failed check, not a silent pass
    assert [c.what for c in found.failed] == [
        "the Carryover Worksheet's foreign tax credit (regular tax) is Schedule B (Form 1116)'s carryover to the "
        "following year",
        "the Carryover Worksheet's foreign tax credit (AMT) is Schedule B (Form 1116)'s carryover to the following "
        "year"]


def test_the_credit_ties_to_schedule_b(tmp_path: Path):
    found = read(draw(tmp_path / "2025 Return.pdf", [REGULAR_1, REGULAR_2, AMT_2, AMT_1, WORKSHEET, FORM_8995]))
    assert found.failed == [], found.failed
    # the year, the credit's regular and AMT amounts, the QBI loss
    assert sum(c.what.startswith("the Carryover Worksheet") for c in found.checks) == 4
    off = [(x, top, "3,851" if phrase == "3,815" else phrase) for x, top, phrase in WORKSHEET]
    found = read(draw(tmp_path / "2025 Off.pdf", [REGULAR_1, REGULAR_2, AMT_2, AMT_1, off, FORM_8995]))
    assert [c.what for c in found.failed] == [
        "the Carryover Worksheet's foreign tax credit (regular tax) is Schedule B (Form 1116)'s carryover to the "
        "following year"]
    found = read(draw(tmp_path / "2025 No 8995.pdf", [REGULAR_1, REGULAR_2, AMT_2, AMT_1, WORKSHEET]))
    assert [c.what for c in found.failed] == ["the Carryover Worksheet's QBI loss carryover is Form 8995's line 16"]


def test_another_year_and_a_passive_row_are_caught(tmp_path: Path):
    found = read(draw(tmp_path / "2024 Return.pdf", [WORKSHEET]))
    assert "the Carryover Worksheet carries to 2025" in [c.what for c in found.failed]
    passive = [*WORKSHEET, (54, 674.5, "RENTAL - ELM COURT ......"), (546, 674.5, "2,210")]
    found = read(draw(tmp_path / "2025 Return.pdf", [passive]))
    assert [q.text for q in found.questions] == [
        "The Carryover Worksheet lists something under Passive Activity: read it by hand."]
    assert all(i.section != "Passive Activity" for i in found.carryovers)


def test_every_section_is_kept_empty_ones_too(tmp_path: Path):
    found = read(draw(tmp_path / "2025 Return.pdf", [WORKSHEET]))
    assert {"Passive Activity", "At Risk Limitations"} <= set(found.carryover_sections)
    assert len(found.carryover_sections) == len(set(found.carryover_sections))


def test_cli_shows_the_labels_never_the_amounts(tmp_path: Path, workspace_home: Path, capsys):
    path = draw(tmp_path / "2025 Return.pdf", [REGULAR_1, REGULAR_2, AMT_2, AMT_1, WORKSHEET, FORM_8995])
    assert cli.main(["prior", str(path), "--layout"]) == 0
    out = printed(capsys)
    assert "Carryover Worksheet p[5]: 6 items" in out
    assert "carryover, Credits: Foreign Tax credit (amt, regular)" in out
    assert "IRA basis (taxpayer, spouse)" in out
    assert not any(a in out for a in ("12,345", "31,906", "7,000", "6,500"))
    assert '"label": "QBI loss carryover"' in (workspace_home / "carryforwards" / "2025 Return.json").read_text()
