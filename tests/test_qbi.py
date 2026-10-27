"""Form 8995, from made-up K-1s, a Schedule E and filed returns shaped as `k1`, `rental` and `prior` save them."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import printed

from taxtrace import cli, qbi


def face(partnership: str, ein: str, *items: tuple[str, str], statement: tuple = (), year: int = 2025,
         **flags) -> dict:
    return {"file": "k1.pdf", "page": 2, "year": year, "ein": ein, "partnership": partnership, "partner": "4410",
            "copy_of": None, "retirement_plan": False, "final": False,
            "items": [{"box": b, "code": "", "value": {"amount": a}} for b, a in items],
            "statement": list(statement), **flags}


def row(description: str, amount: str, business: str = "Larkspur Homes", aggregate: bool = False) -> dict:
    return {"section": "Section 199A", "description": description, "amount": amount, "business": business,
            "aggregate": aggregate}


def activity(name: str, gain: str = "0", loss: str = "0") -> dict:
    return {"worksheet": "3", "activity": name, "net_income": gain, "net_loss": loss, "prior_unallowed": "0",
            "gain": gain, "loss": loss, "page": 32, "quote": name}


LARKSPUR = face("Larkspur Ridge Fund, L.P.", "88-1234567", ("1", "-4210"), ("2", "1875"), ("5", "37"),
                ("10", "300"), ("12", "50"),
                statement=(row("SECTION 199A QUALIFIED BUSINESS INCOME", "-2000"),
                           row("SECTION 199A W-2 WAGES FROM THE TRADE OR BUSINESS", "500"),
                           row("QUALIFIED BUSINESS INCOME", "-2000", "", aggregate=True)))
BRINDLEWOOD = face("Brindlewood Homes LLC", "87-7654321", ("2", "640"))
RENTAL = {"address": "4417 Brambleworth Ct", "income_or_loss": "2150"}
RETURN_2024 = {"file": "2024 Return.pdf", "year": 2024, "qbi": {
    "businesses": [{"name": "K1P: LARKSPUR RIDGE FUND LP", "tin": "88-1234567", "income": "-900"},
                   {"name": "Schedule E: 4417 Brambleworth Ct", "tin": "XXX-XX-XXXX", "income": "1800"}],
    "lines": {"2": "900", "3": "-2150", "16": "-1250", "17": "0"}}}


def build(*returns: dict, k1s: list[dict] | None = None, **kwargs) -> qbi.Form:
    return qbi.build(2025, k1s=[LARKSPUR, BRINDLEWOOD] if k1s is None else k1s, rental=RENTAL,
                     returns=[RETURN_2024, *returns], **kwargs)


def test_each_business_is_its_k1s_passive_income_and_last_years_loss_carries_in():
    form = build(filing="joint")
    fund, rental = form.businesses
    assert (fund.income, fund.source, rental.income, rental.source) == (Decimal(-2085), "k1", Decimal(2150),
                                                                         "schedule e")
    assert fund.others["its Section 199A statement's qualified business income"] == Decimal(-2000)
    assert fund.others["its aggregated group's qualified business income"] == Decimal(-2000)
    n = form.lines
    assert (n[2], n[3], n[4], n[5], n[10], n[15], n[16]) == (Decimal(65), Decimal(-1250), 0, 0, 0, 0, Decimal(-1185))
    assert form.threshold == Decimal(394600)
    assert [q.text.split(":")[0] for q in form.questions] == [
        "2025's Form 8582 isn't worked out yet", "Brindlewood Homes LLC (EIN ending 4321)"]


def test_a_confirmed_business_counts_and_one_with_nothing_listed_or_not_is_left_out():
    quiet = face("Larkspur Ridge Fund, L.P.", "88-1234567", ("1", "0"))
    form = build(k1s=[quiet, BRINDLEWOOD], confirmed={"k1_4321": "business", "rental": "not"})
    assert [b.name for b in form.businesses] == ["Brindlewood Homes LLC"]
    assert form.lines[2] == Decimal(640) and form.lines[4] == Decimal(0)  # 640 less last year's 1,250 carried in
    assert not [q for q in form.questions if "Brindlewood" in q.text or "rental" in q.text]


def test_form_8582s_limit_sets_each_activitys_amount():
    filed = {"file": "2025 Return.pdf", "year": 2025,
             "activities": [activity("LARKSPUR RIDGE FUND LP", loss="2085"), activity("RENTAL PROPERTY", "2150")],
             "unallowed": [{"activity": "LARKSPUR RIDGE FUND LP", "unallowed": "1500"}]}
    assert qbi.allowed(filed) == {"LARKSPUR RIDGE FUND LP": Decimal(-585), "RENTAL PROPERTY": Decimal(2150)}
    form = build(filed, k1s=[LARKSPUR])
    assert [b.income for b in form.businesses] == [Decimal(-585), Decimal(2150)]
    assert not [q for q in form.questions if "Form 8582" in q.text]


def test_passives_worked_out_form_8582_sets_each_activitys_amount_when_none_is_filed():
    worked_out = {"activities": [{"name": "LARKSPUR RIDGE FUND LP", "allowed": "-400"},
                                 {"name": "RENTAL PROPERTY", "allowed": "2150"}]}
    form = build(k1s=[LARKSPUR], worked_out=worked_out)
    assert [b.income for b in form.businesses] == [Decimal(-400), Decimal(2150)]
    assert not [q for q in form.questions if "Form 8582" in q.text]


def test_the_rehearsal_names_the_figure_a_filed_form_used():
    filed = {"file": "2025 Return.pdf", "year": 2025, "qbi": {
        "businesses": [{"name": "K1P: LARKSPUR RIDGE FUND LP", "tin": "88-1234567", "income": "-2000"},
                       {"name": "Schedule E: 4417 Brambleworth Ct", "tin": "XXX-XX-XXXX", "income": "2150"}],
        "lines": {"2": "150", "3": "-1250", "4": "0", "5": "0", "10": "0", "15": "0", "16": "-1100", "17": "0"}}}
    form = build(filed, k1s=[LARKSPUR])
    failed = [c.what for c in form.checks if not c.ok]
    assert failed == ["line 2 is the filed Form 8995's", "line 16 is the filed Form 8995's",
                      "the business with EIN ending 4567: its income is the filed Form 8995's (the filed one is its "
                      "Section 199A statement's qualified business income and its aggregated group's qualified "
                      "business income)"]
    assert len(form.checks) == 11


def test_the_years_1099_div_box_5_is_line_6_and_answers_last_years_line_6():
    last = {**RETURN_2024, "qbi": {**RETURN_2024["qbi"], "lines": {**RETURN_2024["qbi"]["lines"], "6": "40"}}}
    assert [q for q in qbi.build(2025, k1s=[], rental=None, returns=[last]).questions if "(line 6)" in q.text]

    def div(amount: str, year: int = 2025, copy_of: int | None = None) -> dict:
        return {"form": "1099-DIV", "year": year, "copy_of": copy_of, "amounts": {"5": {"amount": amount}}}

    forms = [div("64.18"), div("64.18", copy_of=1), div("12.00", year=2024), {"form": "1098", "year": 2025}]
    form = qbi.build(2025, k1s=[], rental=None, returns=[last], forms=forms)
    assert (form.lines[6], form.lines[8], form.lines[9]) == (Decimal("64.18"), Decimal("64.18"), Decimal(13))
    assert not [q for q in form.questions if "(line 6)" in q.text]


def test_confirmation_takes_the_rental_or_an_eins_last_four():
    assert qbi.confirmation("K1_4321 = Business") == ("k1_4321", "business")
    assert qbi.confirmation("rental=not") == ("rental", "not")
    for bad in ("k1_43=business", "rental=maybe", "rental"):
        with pytest.raises(ValueError):
            qbi.confirmation(bad)


def test_cli_prints_no_amounts(workspace_home: Path, capsys):
    for folder, name, data in (("carryforwards", "2024 Return.json", RETURN_2024), ("k1", "k1.json", [LARKSPUR]),
                               ("schedule-e", "2025.json", RENTAL)):
        (workspace_home / folder).mkdir(parents=True, exist_ok=True)
        (workspace_home / folder / name).write_text(json.dumps(data))
    assert cli.main(["qbi", "--year", "2025", "--layout"]) == 0
    out = printed(capsys)
    assert "2025 Form 8995: 2 businesses; lines 2, 3, 4, 5, 6, 7, 8, 9, 10, 15, 16, 17; the threshold needs" in out
    assert ": a loss (k1)" in out and "a loss carried to next year (line 16); no deduction (line 15 is zero)" in out
    assert "(EIN ending 4567):" in out
    assert "    - [qbi] SECTION ###A QUALIFIED BUSINESS INCOME / " in out
    assert "    + [wages] SECTION ###A W-2 WAGES FROM THE TRADE OR BUSINESS / " in out
    assert "    - [qbi, aggregate] QUALIFIED BUSINESS INCOME" in out
    for secret in ("2085", "1250", "1185", "2150", "Larkspur", "Brambleworth"):
        assert secret not in out
    saved = json.loads((workspace_home / "qbi" / "2025.json").read_text())
    assert saved["lines"]["16"] == "-1185"
