"""Carryforwards read from made-up returns in the preparer software's layouts. Every value here is invented."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import make_pdf

from taxtrace import cli, prior, text

NAME = "Marisol T. Vexley & Corwin Vexley"
SCHEDULE_HEAD = [
    "      10/02/21                        2021 Federal Depreciation Schedule                         Page  1",
    f"                                     {NAME}                      ###-##-4410",
    "         No.    Description          Date Acquired Date Sold Cost/Basis  Cur 179  Bonus  Salvage  Basis    Prior"
    "    Method Life Rate Current",
    "        Schedule E - RENTAL PROPERTY",
    "        _________________________________",
    "         Buildings",
    "         _________",
]
SCHEDULE = [
    *SCHEDULE_HEAD,
    "         1     RENTAL PROPERTY       7/22/16          287,450                       287,450   48,903    S/L   MM"
    "   27.5  .03636   10,452",
    "         2     NEW ROOF              3/09/20           12,600                        12,600      267    S/L   MM"
    "   27.5  .03636      458",
    "           Total Buildings                            300,050    0    0    0      300,050   49,170"
    "                     10,910",
    "           Grand Total Depreciation                   300,050    0    0    0      300,050   49,170"
    "                     10,910",
]
AMT_SCHEDULE = [
    "      10/02/21              2021 Federal Alternative Minimum Tax Depreciation Schedule            Page  1",
    *SCHEDULE[1:],
]
FORM_8582_PAGE_2 = [
    f"     Form 8582 (2021) {NAME} ###-##-4410 Page2",
    "     Worksheet 3 'For Form 8582, Lines 3a, 3b, and 3c (see instructions)",
    "             Name of activity  (a)Net income (b)Net loss (c)Unallowed (d)Gain (e)Loss",
    "     RENTAL PROPERTY                        4,812.    9,977.             14,789.",
    "     Worksheet 5 'Allocation of Unallowed Losses(see instructions)",
    "              Name of activity   and line number to (a)Loss (b)Ratio (c)Unallowed loss",
    "     RENTAL PROPERTY              SCH E P1 22      14,789.    0.840006     12,422.",
    "     QUENBY TERRACE LP            SCH E P2 28       2,817.    0.159994      2,366.",
    "     Total. . . . . . . . . . . . . . . . . . . . . . . . . G 17,606. 1.00 14,788.",
]
FORM_8582_PAGE_3 = [
    f"     Form 8582 (2021) {NAME} ###-##-4410 Page 3",
    "     Worksheet 6 'Allowed Losses(see instructions)",
    "              Name of activity   and line number (a)Loss (b)Unallowed loss (c)Allowed loss",
    "     RENTAL PROPERTY              SCH E P1 22      14,789.     12,422.          2,367.",
    "     QUENBY TERRACE LP            SCH E P2 28       2,817.      2,366.            451.",
    "     Total. . . . . . . . . . . . . . . . . . . . . . . . . G 17,606. 14,788. 2,818.",
    "     Worksheet 7 'Activities With Losses Reported on Two or More Forms or Schedules (see instructions)",
    "     Total. . . . . . . . . . . . . . . . . . . . . . . . G 0. 0.00 0. 0.",
]
AMT_8582 = ["Alternative Minimum Tax", *FORM_8582_PAGE_2]
# the older layout: one worksheet a page, and a Depreciation Detail Listing
LISTING = [
    "                                            Depreciation Detail Listing                      2017",
    "   * Item is included in AMT",
    f"     {NAME}                                        ###-##-4410",
    "   No.   Description Date  Cost  Basis Adj  Business %  179  Bonus  Basis  Life Method Rate  Prior  Current"
    "  Accumulated  AMT Current",
    "    1 8813 WILLOWMERE LN    07222016 287,450*    100.00          287,450 27.5 SL    MM  3.636  4,766  10,452"
    "    15,218    10,452",
    "      Totals              287,450                            287,450              4,766    10,452    15,218"
    "    10,452",
]
WORKSHEET_5 = [
    "                                      Worksheet 5",
    "                               Allocation of Unallowed Losses",
    f"     {NAME}                      ###-##-4410",
    "                   Name of activity         (a) Loss  (b) Ratio   (c) Unallowed loss",
    "     1                               E P1 22          11,204    1            9,860",
    "         Total ....................................   11,204    1.00      9,860",
]


@pytest.fixture
def return_2021(tmp_path: Path) -> Path:
    pages = [FORM_8582_PAGE_2, FORM_8582_PAGE_3, AMT_8582, SCHEDULE, AMT_SCHEDULE, SCHEDULE]
    return make_pdf(tmp_path / "prior-returns" / "2021 Vexley Return.pdf", pages)


def read(path: Path) -> prior.Carryforwards:
    return prior.read(path.name, text.pages(path))


def test_amounts_in_the_preparers_styles():
    assert prior.amount("1,234.") == 1234
    assert prior.amount("-1,234.50") == Decimal("-1234.50")
    assert prior.amount("(980)") == -980
    assert prior.amount("287,450*") == 287450
    with pytest.raises(ValueError):
        prior.amount("S/L")


def test_depreciation_schedule(return_2021: Path):
    found = read(return_2021)
    assert found.year == 2021
    roof = found.assets[1]
    assert (roof.description, roof.placed_in_service, roof.cost, roof.basis, roof.prior, roof.current) == (
        "NEW ROOF", "3/09/20", 12600, 12600, 267, 458)
    assert (roof.method, roof.convention, roof.life, roof.activity) == ("S/L", "MM", Decimal("27.5"),
                                                                        "RENTAL PROPERTY")
    assert roof.accumulated == 725
    # the second copy of the schedule (page 6) is the same one, kept once; the AMT copies are skipped
    assert [a.page for a in found.assets] == [4, 4]
    assert found.skipped == [3, 5]
    assert not found.failed, found.failed
    assert any("repeats page 4" in c.what for c in found.checks)
    assert not found.questions


def test_unallowed_passive_losses(return_2021: Path):
    found = read(return_2021)
    rental, partnership = found.unallowed
    assert (rental.activity, rental.form_line, rental.loss, rental.unallowed) == (
        "RENTAL PROPERTY", "SCH E P1 22", 14789, 12422)
    assert (partnership.activity, partnership.ratio, partnership.unallowed) == (
        "QUENBY TERRACE LP", Decimal("0.159994"), 2366)
    assert any("matches Worksheet 5" in c.what and c.ok for c in found.checks)


def test_every_quote_is_on_its_page(return_2021: Path):
    pages = text.pages(return_2021)
    found = prior.read(return_2021.name, pages)
    assert prior.verify(found, pages) == []
    found.unallowed[0].quote = found.unallowed[0].quote.replace("12,422", "12,433")
    assert prior.verify(found, pages) == ["unallowed loss on page 1: its line isn't on that page"]


def test_a_total_that_doesnt_add_up_fails_its_check(tmp_path: Path):
    wrong = [ln.replace("10,910", "10,990") if "Grand Total" in ln else ln for ln in SCHEDULE]
    found = read(make_pdf(tmp_path / "2021 Return.pdf", [wrong]))
    assert [c.what for c in found.failed] == ["the rows' current depreciation adds up to the totals line"]


def test_two_copies_that_disagree_are_a_question(tmp_path: Path):
    other = [ln.replace("48,903", "48,930") for ln in SCHEDULE]
    found = read(make_pdf(tmp_path / "2021 Return.pdf", [SCHEDULE, other]))
    assert [q.text for q in found.questions] == [
        "Asset 1 is on page 1 and again on page 2, with a different prior: which copy is the filed one?"]
    assert [a.page for a in found.assets] == [1, 1, 2, 2]


def test_a_schedule_for_another_year_is_skipped(tmp_path: Path):
    projection = [ln.replace("2021 Federal", "2022 Federal") for ln in SCHEDULE]
    found = read(make_pdf(tmp_path / "2021 Return.pdf", [SCHEDULE, projection]))
    assert (found.other_years, [a.page for a in found.assets], found.questions) == ({2: 2022}, [1, 1], [])
    # a projection whose prior isn't this year's accumulated is a failed check
    assert [c.what for c in found.failed] == [
        "asset 1: next year's schedule (page 2) starts from this year's accumulated depreciation",
        "asset 2: next year's schedule (page 2) starts from this year's accumulated depreciation"]
    rolled = [ln.replace("2021 Federal", "2022 Federal").replace("48,903", "59,355").replace("   267 ", "   725 ")
              for ln in SCHEDULE]
    assert not read(make_pdf(tmp_path / "2021 R.pdf", [SCHEDULE, rolled])).failed


def test_bonus_depreciation_is_a_question(tmp_path: Path):
    bonus = [*SCHEDULE_HEAD,
             "         1     FENCE                 5/01/21            8,000      0   8,000    0          0       0"
             "    S/L   HY   15.0  .00000        0",
             "           Grand Total Depreciation                     8,000      0   8,000    0          0       0"
             "                         0"]
    found = read(make_pdf(tmp_path / "2021 Return.pdf", [bonus]))
    assert [q.text for q in found.questions] == [
        "This asset has a Section 179, bonus, salvage or basis-reduction amount: check what carries forward.",
        "The schedule's totals show Section 179, bonus or salvage amounts: check what carries forward."]


def test_the_older_layout(tmp_path: Path):
    found = read(make_pdf(tmp_path / "2017 Return.pdf", [LISTING, WORKSHEET_5]))
    (house,) = found.assets
    assert (house.description, house.placed_in_service, house.cost, house.prior, house.current, house.method) == (
        "8813 WILLOWMERE LN", "07222016", 287450, 4766, 10452, "SL")
    assert house.accumulated == 15218
    (rental,) = found.unallowed
    assert (rental.activity, rental.form_line, rental.loss, rental.ratio, rental.unallowed) == (
        "1", "E P1 22", 11204, 1, 9860)
    assert not found.failed, found.failed


def test_cli_writes_the_values_and_prints_none(return_2021: Path, workspace_home: Path, capsys):
    assert cli.main(["prior", str(return_2021), "--layout"]) == 0
    out = capsys.readouterr().out
    for secret in ("12,422", "287,450", "Vexley", "Quenby", "10,452"):
        assert secret not in out
    assert "2 assets" in out and "2 activities" in out
    saved = json.loads((workspace_home / "carryforwards" / "2021 Vexley Return.json").read_text())
    assert saved["year"] == 2021
    assert saved["assets"][0]["accumulated"] == "59355"
    assert saved["unallowed"][1]["unallowed"] == "2366"
