"""Carryforwards read from made-up returns in the preparer software's layouts. Every value here is invented."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import make_pdf, printed

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
    "     Total. . . . . . . . . . . . . . G     4,812.    9,977.",
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
# the listing as the later returns print it: dashed dates, a land row with no method, and next year's worksheet
LISTING_2025 = [
    "                                            Depreciation Detail Listing                      2025",
    "   * Item is included in AMT",
    f"     {NAME}                                        ###-##-4410",
    "   No.   Description Date  Cost  Basis Adj  Business %  179  Bonus  Basis  Life Method Rate  Prior  Current"
    "  Accumulated  AMT Current",
    "    1 8813 WILLOWMERE LN    07-14-2017 268,400*    100.00          268,400 27.5 SL    MM  3.636  72,786   9,759"
    "    82,545     9,759",
    "    2 LAND                  07-14-2017  45,000     100.00                0      N/A",
    "      Totals              313,400                            268,400             72,786     9,759    82,545"
    "     9,759",
    "      Land Amount          45,000",
]
NEXT_YEAR = [
    "                          Next Year's Depreciation Worksheet",
    "                                                    2025",
    f"     {NAME}                                        ###-##-4410",
    "   Form Multi-Form Description            Date        Basis   Method       Life   Deduction",
    "   E    1 8813 WILLOWMERE LN              07-14-2017  268,400 SL     MM    27.5       9,759",
    "        TOTAL                                                                          9,759",
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


def test_the_later_listing_with_land_and_next_years_worksheet(tmp_path: Path):
    found = read(make_pdf(tmp_path / "2025 Return.pdf", [LISTING_2025, NEXT_YEAR]))
    house, land = found.assets
    assert (house.placed_in_service, house.in_service().isoformat(), house.basis, house.prior, house.current) == (
        "07-14-2017", "2017-07-14", 268400, 72786, 9759)
    assert (land.description, land.cost, land.basis, land.accumulated, land.method) == ("LAND", 45000, 0, 0, "N/A")
    assert not found.failed, found.failed
    assert not found.questions
    assert [c.what for c in found.checks if "next year" in c.what] == [
        "asset 1: next year's depreciation worksheet (page 2) takes a full year at its rate, or what's left of its "
        "basis", "next year's depreciation worksheet's rows add up to its total"]
    off = [ln.replace("9,759", "9,795") for ln in NEXT_YEAR]
    assert len(read(make_pdf(tmp_path / "2025 R.pdf", [LISTING_2025, off])).failed) == 1  # the rows still add up
    # land numbered like its building, as some preparers do, doesn't stand in for the building
    shared = [ln.replace("    2 LAND", "    1 LAND") for ln in LISTING_2025]
    assert not read(make_pdf(tmp_path / "2025 L.pdf", [shared, NEXT_YEAR])).failed
    # a row that's neither depreciated nor land is still asked about
    odd = [ln.replace("0      N/A", "1,200  N/A") for ln in LISTING_2025]
    assert any("can't split" in q.text for q in read(make_pdf(tmp_path / "2025 S.pdf", [odd])).questions)


def test_cli_writes_the_values_and_prints_none(return_2021: Path, workspace_home: Path, capsys):
    assert cli.main(["prior", str(return_2021), "--layout"]) == 0
    out = printed(capsys)
    for secret in ("12,422", "287,450", "Vexley", "Quenby", "10,452"):
        assert secret not in out
    assert "2 assets" in out and "2 activities" in out
    assert "prior 4.68 years, current 1.00 years" in out  # 48,903 and 10,452 at 10,452 a year
    saved = json.loads((workspace_home / "carryforwards" / "2021 Vexley Return.json").read_text())
    assert saved["year"] == 2021
    assert saved["assets"][0]["accumulated"] == "59355"
    assert saved["unallowed"][1]["unallowed"] == "2366"


def test_cli_prints_the_words_of_other_pages_in_the_same_run(return_2021: Path, workspace_home: Path, capsys,
                                                            monkeypatch):
    opened = []
    real = cli._unlocked
    monkeypatch.setattr(cli, "_unlocked", lambda doc, keychain=True: opened.append(doc) or real(doc, keychain))
    assert cli.main(["prior", str(return_2021), "--words", "1,9"]) == 0  # a page past the end is left out
    out = printed(capsys)
    assert len(opened) == 1  # one opening: a locked return asks the Keychain once
    assert [ln for ln in out.splitlines() if ln.startswith("==")] == ["== 2021 ****** Return.pdf page 1"]
    assert "Worksheet" in out and "Vexley" not in out and "12,422" not in out


def test_a_full_year_at_the_rate_and_the_last_year(return_2021: Path):
    house, roof = read(return_2021).assets
    assert (house.rate, house.annual, roof.annual) == (Decimal("0.03636"), 10452, 458)
    assert house.in_service().isoformat() == "2016-07-22"
    years = prior.roll(house, 2021, 2023)
    assert [(y.year, y.depreciation, y.accumulated) for y in years] == [(2022, 10452, 69807), (2023, 10452, 80259)]
    house.prior = house.basis - house.current - 100  # 100 left of the basis at the end of 2021
    (final,) = prior.roll(house, 2021, 2022)
    assert (final.depreciation, final.last) == (100, True)


# the 2021 schedule as it should follow the 2017 listing: 15,218 through 2017, then 10,452 a year for 2018-2020
FOLLOWS_2017 = [ln.replace("48,903", "46,574").replace("49,170", "46,841") for ln in SCHEDULE]


def test_returns_years_apart_are_checked_against_each_other(tmp_path: Path):
    listing = read(make_pdf(tmp_path / "2017 Return.pdf", [LISTING]))
    assert listing.assets[0].rate == Decimal("0.03636")
    later = read(make_pdf(tmp_path / "2021 Return.pdf", [FOLLOWS_2017]))
    (check,) = prior.link([later, listing])
    assert check.ok and "2017's depreciation rolled forward is 2021's prior" in check.what
    (check,) = prior.link([listing, read(make_pdf(tmp_path / "2021 Other.pdf", [SCHEDULE]))])
    assert not check.ok


def test_cli_projects_the_missing_years(tmp_path: Path, workspace_home: Path, capsys):
    folder = tmp_path / "returns"
    make_pdf(folder / "2017 Return.pdf", [LISTING])
    make_pdf(folder / "2021 Return.pdf", [FOLLOWS_2017])
    assert cli.main(["prior", str(folder), "--project", "2025"]) == 0
    out = printed(capsys)
    assert "across returns: 1 of 1 checks pass" in out
    assert "projected 2 assets from the 2021 return through 2025" in out and "10,452" not in out
    saved = json.loads((workspace_home / "carryforwards" / "projected-2025.json").read_text())
    house = saved["assets"][0]
    assert (house["from"]["year"], house["annual"], house["placed_in_service"]) == (2021, "10452", "2016-07-22")
    assert [y["year"] for y in house["years"]] == [2022, 2023, 2024, 2025]
    assert house["years"][-1]["accumulated"] == str(46574 + 10452 + 4 * 10452)
    assert cli.main(["prior", str(folder), "--project", "2017"]) == 1


# Form 8582's page 2 as Drake prints it: (x, top, text), each column's amounts right under its heading
ACTIVITIES = [
    (37, 51, "Form 8582 (2020) Page 2"),
    (37, 75, "Worksheet 1 'For Form 8582, Lines 1a, 1b, and 1c (see instructions)"),
    (224, 100, "(a)Net income"), (304, 100, "(b)Net loss"), (372, 100, "(c)Unallowed"),
    (452, 104, "(d)Gain"), (526, 104, "(e)Loss"),
    (37, 174, "Total. Enter on Form 8582, lines 1a, 1b,"), (37, 182, "and 1c. G"),  # nothing on it: no total
    (37, 291, "Worksheet 3 'For Form 8582, Lines 3a, 3b, and 3c (see instructions)"),
    (226, 316, "(a)Net income"), (304, 316, "(b)Net loss"), (372, 316, "(c)Unallowed"),
    (452, 320, "(d)Gain"), (526, 320, "(e)Loss"), (238, 324, "(line 3a)"), (310, 324, "(line 3b)"),
    (38, 335, "RENTAL PROPERTY"), (322, 335, "4,120."), (394, 335, "9,880."), (530, 335, "14,000."),
    (38, 346, "Larkspur Ridge Fund LP"), (322, 346, "1,875."), (536, 346, "1,875."),
    (38, 357, "Quarrystone Homes LLC"), (274, 357, "350."), (490, 357, "350."),
    (37, 390, "Total.Enter on Form 8582, lines 3a, 3b,"),
    (37, 398, "and 3c. G"), (274, 398, "350."), (322, 398, "5,995."), (394, 398, "9,880."),  # (a) to (c) only
]


def test_every_passive_activity_by_the_column_each_amount_sits_in(tmp_path: Path):
    from test_k1 import draw

    path = draw(tmp_path / "2020 Return.pdf", [ACTIVITIES])
    pages = text.pages(path)
    found = prior.read(path.name, pages, {1: text.words(path, 1)})
    assert [(a.worksheet, a.activity, a.net_income, a.net_loss, a.prior_unallowed, a.gain, a.loss)
            for a in found.activities] == [
        ("3", "RENTAL PROPERTY", 0, Decimal(4120), Decimal(9880), 0, Decimal(14000)),
        ("3", "Larkspur Ridge Fund LP", 0, Decimal(1875), 0, 0, Decimal(1875)),
        ("3", "Quarrystone Homes LLC", Decimal(350), 0, 0, Decimal(350), 0)]  # income: no loss carried
    assert found.failed == [] and len(found.checks) == 6  # each row, and the total's (a) to (c)
    assert prior.verify(found, pages) == []
    wrong = [(x, top, "5,959." if phrase == "5,995." else phrase) for x, top, phrase in ACTIVITIES]
    path = draw(tmp_path / "wrong.pdf", [wrong])
    assert [c.what for c in prior.read(path.name, text.pages(path), {1: text.words(path, 1)}).failed] == [
        "Worksheet 3: the rows' column (b) adds up to the total"]


def test_cli_reads_the_activities(tmp_path: Path, workspace_home: Path, capsys):
    from test_k1 import draw

    assert cli.main(["prior", str(draw(tmp_path / "2020 Return.pdf", [ACTIVITIES])), "--layout"]) == 0
    out = printed(capsys)
    assert "3 passive activities on Worksheets 1 and 3; 6 of 6 checks pass" in out
    assert "p1 Worksheet 3 activity, columns a, d: *********** Homes *** ###. ###." in out and "350" not in out
    saved = json.loads((workspace_home / "carryforwards" / "2020 Return.json").read_text())
    assert saved["activities"][1]["net_loss"] == "1875"
