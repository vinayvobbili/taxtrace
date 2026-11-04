"""Federal adjusted gross income and North Carolina's D-400, from made-up saved forms and invented amounts."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import printed

from taxtrace import agi, cli, d400, entry

W2 = {"form": "W-2", "file": "initech-w2.pdf", "year": 2026, "amounts": {"1": {"amount": "150000"},
                                                                         "17": {"amount": "6000"}}}
INT = {"form": "1099-INT", "file": "globex.pdf", "year": 2026,
       "amounts": {"1": {"amount": "100"}, "3": {"amount": "50"}}}
DIV = {"form": "1099-DIV", "file": "globex.pdf", "year": 2026, "amounts": {"1a": {"amount": "300"}}}
FACE = {"file": "umbrella-k1.pdf", "page": 1, "year": 2026, "ein": "98-7654321", "partnership": "Umbrella Lofts LLC",
        "items": [{"box": "2", "code": "", "value": {"amount": "-500"}},
                  {"box": "5", "code": "", "value": {"amount": "20"}},
                  {"box": "6a", "code": "", "value": {"amount": "30"}},
                  {"box": "7", "code": "", "value": {"amount": "40"}},
                  {"box": "9a", "code": "", "value": {"amount": "60"}}]}
NC_K1 = {"form": "D-403", "file": "umbrella-nc.pdf", "page": 2, "year": 2026, "partnership": "Umbrella Lofts LLC",
         "lines": {"1": {"amount": "-500"}, "2": {"amount": "200"}, "3": {"amount": "80"}, "5": {"amount": "15"}}}
RENTAL = {"address": "48 Oak Lane", "income_or_loss": "1000"}
FOUND = {"interest": "70", "accounts": [], "estimated": False,
         "sales": [{"gain": "5000", "proceeds": {"dollars": "9000"}, "basis": "4000"}]}
SALES = {"from_forms": True, "net": "-1000"}
HOME = {"form": "1098", "file": "acme.pdf", "year": 2026, "address": "12 Birch Road",
        "amounts": {"1": {"amount": "16000"}}}
RENTAL_LOAN = {**HOME, "file": "acme2.pdf", "address": "48 Oak Lane", "amounts": {"1": {"amount": "7000"}}}
MOVES = {"moves": [{"key": "spouse_ira", "amount": "7000", "done": True},
                   {"key": "own_ira", "amount": "900", "done": False}]}


def federal(**changes) -> agi.Agi:
    made = {"forms": [W2, INT, DIV], "k1s": [FACE], "returns": [], "filing": "joint", "rental": RENTAL, "found": FOUND,
            "sales": SALES, "moves": MOVES, "passive": {"form_8582": {"activities": [{"allowed": "800"}]}},
            "year_over": True}
    return agi.build(2026, **{**made, **changes})


def test_each_income_line_adds_what_goes_on_it():
    found = federal()
    assert found.line("1z").amount == 150000
    assert found.line("2b").amount == 100 + 50 + 20 + 70  # 1099-INT boxes 1 and 3, K-1 box 5, the foreign side
    assert found.line("3b").amount == 300 + 30
    assert found.line("7").amount == -1000 + 5000 + 60  # the sales, a sale abroad, K-1 box 9a
    assert found.line("8").amount == 800 + 40  # what Form 8582 allowed, and royalties
    assert found.line("10").amount == 7000  # a contribution not done yet isn't taken
    assert found.total == 150000 + 240 + 330 + 4060 + 840 - 7000
    assert found.status == agi.READY


def test_a_net_capital_loss_is_held_to_the_years_limit():
    loss = {**SALES, "net": "-9000"}
    assert federal(sales=loss, found={**FOUND, "sales": []}, k1s=[]).line("7").amount == -3000
    assert federal(sales=loss, found={**FOUND, "sales": []}, k1s=[], filing="separate").line("7").amount == -1500


def test_before_form_8582_line_8_is_an_estimate_and_says_so():
    found = federal(passive=None)
    assert found.line("8").amount == Decimal(1000) - 500 + 40
    assert found.line("8").status == agi.ESTIMATE
    assert any("Form 8582 isn't worked out" in q for q in found.questions)


def test_a_pay_stub_makes_it_an_estimate_and_nothing_read_makes_it_incomplete():
    stub = {"form": "paystub", "file": "stub.pdf", "year": 2026, "paid": "2026-10-30", "period_start": "2026-10-16",
            "period_end": "2026-10-31", "taxable_wages": {"current": "4000", "year_to_date": "80000", "label": "x"}}
    found = federal(forms=[stub, INT, DIV])
    assert found.line("1z").amount == 96000
    assert found.status == agi.ESTIMATE
    empty = agi.build(2026, forms=[], k1s=[], returns=[])
    assert empty.total is None
    assert empty.status == agi.MISSING


def test_a_k1s_other_income_is_asked_about():
    other = {**FACE, "items": [*FACE["items"], {"box": "11", "code": "C", "value": {"amount": "9"}}]}
    assert any("box 4c or 11" in q for q in federal(k1s=[other]).questions)


def test_a_filed_year_is_compared_line_by_line_without_amounts():
    built = federal(forms=[INT, DIV], moves=None)  # no W-2: the filed line stands in
    filed = {"1z": "150000", "2b": "240", "3b": "400", "7": "4060", "8": "2000", "10": "0", "11": "156700"}
    found = federal(forms=[INT, DIV], moves=None, returns=[{"year": 2026, "f1040": {"lines": filed}}])
    assert built.line("1z").amount is None
    checks = {c.what: c.ok for c in found.checks}
    assert checks["line 1z is the filed return's"]
    assert checks["line 2b is the filed return's"]
    assert checks["line 3b is lower than the filed return's, by under $100"] is False
    assert checks["line 8 is lower than the filed return's, by $1,000 or more"] is False
    assert not checks["line 11 is lower than the filed return's, by $1,000 or more"]
    assert all(not any(a in c.what for a in ("150000", "2000", "4060")) for c in found.checks)


def test_a_1231_gain_on_another_line_shows_in_the_two_lines_together():
    filed = {"1z": "150000", "2b": "240", "3b": "330", "7a": "4900", "8": "0", "11": "155470"}
    found = federal(moves=None, returns=[{"year": 2026, "f1040": {"lines": filed}}])
    checks = {c.what: c.ok for c in found.checks}
    assert checks["lines 7 and 8 together is the filed return's"]
    assert checks["line 11 is the filed return's"]
    assert not checks["line 7 is lower than the filed return's, by under $1,000"]


def test_a_difference_names_the_part_that_explains_it_without_amounts():
    activities = [{"name": "Umbrella Lofts", "allowed": "300"}, {"name": "Hooli Towers", "allowed": "4400"}]
    filed = {"1z": "150000", "2b": "240", "3b": "330", "7": "4060", "8": "340", "11": "155000"}
    found = federal(moves=None, k1s=[FACE], passive={"form_8582": {"activities": activities}},
                    returns=[{"year": 2026, "f1040": {"lines": filed}}])
    assert found.explained == ["lines 7 and 8 together: leaving out Hooli Towers would match"]
    filed = {**filed, "8": "1"}
    found = federal(moves=None, k1s=[FACE], passive={"form_8582": {"activities": activities}},
                    returns=[{"year": 2026, "f1040": {"lines": filed}}])
    assert found.explained == ["lines 7 and 8 together: leaving out no one or two of its parts would match"]


def form(**changes) -> d400.Form:
    made = {"agi": federal(), "forms": [W2, INT, DIV, HOME, RENTAL_LOAN], "k1s": [FACE, NC_K1], "filing": "joint",
            "rental": RENTAL, "confirmed": {"children": "2", "use_tax": "12"}}
    return d400.build(2026, **{**made, **changes})


def lines(found: d400.Form) -> dict[str, Decimal | None]:
    return {n.line: n.amount for n in found.lines}


def test_the_form_follows_its_lines_for_a_standard_deduction():
    found = lines(form())
    assert found["6"] == 148470  # 150000 + 240 + 330 + 4060 + 840 - 7000
    assert found["7"] == 200
    assert found["8"] == 148670
    assert found["9"] == 80 + 50  # NC K-1 line 3, and 1099-INT box 3
    assert found["10a"] == 2
    assert found["10b"] == 0  # over $140,000 filing jointly
    assert found["11"] == 25500
    assert found["12a"] == 130 + 25500
    assert found["12b"] == 148670 - 25630
    assert found["14"] == found["12b"]
    assert found["15"] == 4909  # 123,040 at 3.99% = 4,909.30
    assert found["17"] == 4909
    assert found["18"] == 12
    assert found["19"] == 4921
    assert found["20"] == 6000 + 15  # the W-2's box 17, and NC K-1 line 5
    assert found["23"] == 6015
    assert found["28"] == 6015 - 4921
    assert "26a" not in found


def test_2025_has_its_own_rate():
    made = form(agi=agi.build(2025, forms=[], k1s=[], returns=[]))
    assert made.lines[0].status == d400.MISSING
    filed = {"1z": "100000", "2b": "0", "3b": "0", "7": "0", "8": "0", "10": "0", "11": "100000"}
    year = agi.build(2025, forms=[], k1s=[], returns=[{"year": 2025, "f1040": {"lines": filed}}],
                     found={"interest": "0"}, sales={"net": "0"}, rental={"income_or_loss": "0"})
    assert lines(d400.build(2025, agi=year, forms=[], k1s=[], filing="joint"))["15"] == 3166  # 74,500 at 4.25%


def test_tax_due_when_payments_fall_short():
    short = {**W2, "amounts": {"1": {"amount": "150000"}, "17": {"amount": "100"}}}
    found = lines(form(forms=[short, INT, DIV], k1s=[FACE], confirmed={"estimated": "200"}))
    assert found["21a"] == 200
    assert found["26a"] > 0
    assert "28" not in found


@pytest.mark.parametrize(("income", "children", "filing", "expected"), [
    (40000, 2, "joint", 6000), (40001, 2, "joint", 5000), (140000, 1, "joint", 500), (140001, 1, "joint", 0),
    (105000, 2, "head", 1000), (105001, 2, "head", 0), (20000, 1, "single", 3000), (70001, 3, "separate", 0)])
def test_the_child_deduction_table(income, children, filing, expected):
    assert d400.child_deduction(filing, Decimal(income), children) == expected


def test_a_low_income_gets_the_child_deduction():
    wages = {**W2, "amounts": {"1": {"amount": "70000"}, "17": {"amount": "2000"}}}
    low = federal(forms=[wages], k1s=[], rental={"income_or_loss": "0"}, found={"interest": "0"},
                  sales={"net": "0", "from_forms": True}, passive=None, moves=None)
    assert lines(form(agi=low, forms=[wages], k1s=[]))["10b"] == 4000  # $2,000 each from $60,000 to $80,000


def test_itemizing_wins_when_its_larger_and_home_costs_stop_at_the_limit():
    found = form(confirmed={"children": "2", "property_tax": "6000", "charity": "7000", "medical": "12000"})
    assert found.deduction == "itemized"
    schedule = {n.line: n.amount for n in found.schedule_a}
    assert schedule["1"] == 16000  # the home's 1098 only, not the rental's
    assert schedule["5"] == 20000  # 22,000 stops at the limit
    assert schedule["7d"] == 865  # 12,000 less 7.5% of 148,470 (11,135.25)
    assert schedule["10"] == 20000 + 7000 + 865
    assert lines(found)["11"] == 27865


def test_the_standard_deduction_says_when_schedule_a_could_still_win():
    found = form(forms=[W2, INT, DIV])
    assert found.deduction == "standard"
    assert any("Schedule A may come out larger" in q for q in found.questions)
    rows = {n.line: n.status for n in found.schedule_a}
    assert (rows["1"], rows["2"]) == (d400.MISSING, d400.MISSING)
    done = form(confirmed={"children": "2", "use_tax": "0", "property_tax": "1000", "us_interest": "0"})
    assert done.deduction == "standard"
    assert not any("Schedule A may" in q for q in done.questions)


def test_a_funds_treasury_share_is_asked_until_confirmed():
    assert any("Schedule S line 18" in q for q in form().questions)
    answered = form(confirmed={"children": "2", "us_interest": "75"})
    assert not any("Schedule S line 18" in q for q in answered.questions)
    assert lines(answered)["9"] == 80 + 50 + 75


def test_questions_for_what_only_you_know():
    found = form(confirmed={})
    text = " ".join(found.questions)
    assert "line 10a" in text
    assert "line 18" in text
    statuses = {n.line: n.status for n in found.lines}
    assert (statuses["10a"], statuses["18"]) == (d400.MISSING, d400.MISSING)


def test_no_filing_status_or_rate_stops_with_a_question():
    assert "how you file" in form(filing="").questions[0]
    year = agi.build(2030, forms=[], k1s=[], returns=[])
    assert "rate for 2030" in d400.build(2030, agi=year, forms=[], k1s=[], filing="joint").questions[0]


@pytest.mark.parametrize("bad", ["children", "children=1.5", "nonsense=3", "charity=abc", "charity=-5", "use_tax=NaN"])
def test_a_confirmation_that_isnt_one_is_refused(bad):
    with pytest.raises(ValueError):
        d400.confirmation(bad)


def test_a_confirmation_takes_money_as_its_written():
    assert d400.confirmation("Property_Tax = $3,200.50") == ("property_tax", "3200.50")
    assert d400.confirmation("children=2") == ("children", "2")


def test_the_text_shows_each_line_and_schedule():
    text = d400.to_text(form())
    assert "15. North Carolina income tax at 3.99%: 4,909" in text
    assert "Schedule S" in text
    assert "Schedule A (line 11 uses the standard deduction)" in text
    assert "Still to settle:" in text


def save(home: Path, folder: str, name: str, value: object) -> None:
    (home / folder).mkdir(parents=True, exist_ok=True)
    (home / folder / name).write_text(json.dumps(value))


def workspace(home: Path) -> None:
    save(home, "forms", "all.json", [W2, INT, DIV, HOME])
    save(home, "k1", "umbrella.json", [FACE, NC_K1])
    save(home, "schedule-e", "2026.json", RENTAL)
    save(home, "foreign", "2026.json", FOUND)
    save(home, "foreign", "2026-confirmed.json", {"filing": "joint"})
    save(home, "sales", "2026.json", SALES)


def test_the_commands_write_the_amounts_to_files_and_print_them_masked(workspace_home, capsys):
    workspace(workspace_home)
    assert cli.main(["agi", "--year", "2026"]) == 0
    assert cli.main(["d400", "--year", "2026", "--confirm", "children=2"]) == 0
    out = printed(capsys)
    for secret in ("150,000", "150000", "148", "Umbrella", "Oak Lane", "4,909"):
        assert secret not in out
    assert "the standard deduction on line 11" in out
    assert "North Carolina income tax" in (workspace_home / "d400" / "2026.txt").read_text()
    assert json.loads((workspace_home / "d400" / "2026-confirmed.json").read_text()) == {"children": "2"}
    assert cli.main(["d400", "--year", "2026"]) == 0  # the confirmation is kept
    capsys.readouterr()
    assert "10a. Qualifying children: 2" in (workspace_home / "d400" / "2026.txt").read_text()
    assert cli.main(["d400", "--year", "2026", "--confirm", "nonsense"]) == 2


def test_agi_exits_1_when_a_filed_year_differs(workspace_home, capsys):
    workspace(workspace_home)
    save(workspace_home, "carryforwards", "2026.json", {"year": 2026, "f1040": {"lines": {"1z": "1", "11": "1"}}})
    assert cli.main(["agi", "--year", "2026"]) == 1
    assert "differs: line 1z is higher" in printed(capsys)


def test_the_entry_sheet_shows_what_the_site_should_come_to(workspace_home, capsys):
    workspace(workspace_home)
    assert cli.main(["agi", "--year", "2026"]) == 0
    assert cli.main(["d400", "--year", "2026"]) == 0
    assert cli.main(["entry", "--year", "2026"]) == 0
    capsys.readouterr()
    text = (workspace_home / "entry" / "2026.txt").read_text()
    assert "Federal adjusted gross income: " in text
    assert "D-400 line 15, North Carolina income tax" in text
    assert "D-400 line 10a, qualifying children" in text
    sheet = entry.build(2026, forms=[], k1s=[], returns=[])
    assert sheet.sections[-1].rows[0].status == entry.MISSING
