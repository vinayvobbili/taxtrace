"""The passive ledger, from made-up saved carryforwards and K-1s shaped as `prior` and `k1` write them."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from taxtrace import cli, passive


def activity(name: str, loss: str = "0", carried: str = "0") -> dict:
    return {"worksheet": "3", "activity": name, "net_income": "0", "net_loss": loss, "prior_unallowed": carried,
            "gain": "0", "loss": loss, "page": 32, "quote": name}


def face(partnership: str, *items: tuple[str, str, str | None], year: int = 2025, **flags) -> dict:
    return {"file": "k1.pdf", "page": 2, "year": year, "ein": "88-1234567", "partnership": partnership,
            "partner": "4410", "copy_of": None, "retirement_plan": False, "final": False,
            "items": [{"box": b, "code": c, "value": {"amount": a}} for b, c, a in items], **flags}


RETURN_2024 = {
    "file": "2024 Return.pdf", "year": 2024,
    "activities": [activity("RENTAL PROPERTY", "4120", "9880"), activity("LARKSPUR RIDGE FUND LP", "1875"),
                   activity("QUENBY TERRACE LP")],
    "unallowed": [{"activity": "RENTAL PROPERTY", "unallowed": "12422"},
                  {"activity": "LARKSPUR RIDGE FUND LP", "unallowed": "1575"}],
}
LARKSPUR = face("Larkspur Ridge Fund, L.P.", ("1", "", "-4210"), ("2", "", "1875"), ("5", "", "37"),
                ("13", "AE", "112"), ("10", "", "300"), ("12", "", "50"))


def test_each_activity_is_matched_to_its_k1_and_carries_its_loss_in():
    ledger = passive.build(2025, [RETURN_2024], [LARKSPUR, face("Brindlewood Homes LLC", ("2", "", "640"))])
    assert ledger.latest == 2024
    by = {line.activity: line for line in ledger.lines}
    fund = by["LARKSPUR RIDGE FUND LP"]
    assert (fund.source, fund.current, fund.carried, fund.carried_from) == ("k1", Decimal(-2085), Decimal(1575), 2024)
    assert fund.left_out == ["5", "13 AE"]  # interest and a portfolio deduction aren't the activity's
    assert (by["RENTAL PROPERTY"].source, by["RENTAL PROPERTY"].carried) == ("schedule e", Decimal(12422))
    assert by["Brindlewood Homes LLC"].worksheet == "" and by["Brindlewood Homes LLC"].current == Decimal(640)
    assert [q.quote for q in ledger.questions] == ["QUENBY TERRACE LP"]  # no 2025 K-1: sold, ended or missing?


def test_a_gap_since_the_latest_return_leaves_the_carried_losses_unknown():
    older = {**RETURN_2024, "year": 2020, "file": "2020 Return.pdf"}
    ledger = passive.build(2025, [older], [LARKSPUR])
    assert all(line.carried is None for line in ledger.lines)
    assert ledger.questions[0].text.startswith("the latest return with Form 8582 is 2020's: the 2021 to 2024")


def test_copies_ira_k1s_and_other_years_are_left_out_and_odd_deductions_asked():
    k1s = [LARKSPUR, {**LARKSPUR, "copy_of": 2}, face("Sablewick IRA Fund", ("1", "", "90"), retirement_plan=True),
           face("Quenby Terrace LP", ("1", "", "10"), year=2024), face("Quenby Terrace LP", ("13", "W", "15"))]
    ledger = passive.build(2025, [RETURN_2024], k1s)
    assert [line.activity for line in ledger.lines if line.source == "k1"] == [
        "LARKSPUR RIDGE FUND LP", "QUENBY TERRACE LP"]
    assert [q.text.split(":")[0] for q in ledger.questions] == ["box 13 W"]


def test_a_fund_merged_into_another_shares_its_k1_and_is_not_freed():
    merged = {**RETURN_2024, "activities": [activity("LARKSPUR RIDGE HOMES FUND LP", "1875", "300"),
                                            activity("LARKSPUR RIDGE FUND LP", "0", "120")], "unallowed": []}
    ledger = passive.build(2025, [merged], [face("Larkspur Ridge Homes Fund, L.P.", ("1", "", "-400"))])
    survivor, merged_away = ledger.lines
    assert (survivor.current, survivor.merged_into) == (Decimal(-400), "")
    assert (merged_away.source, merged_away.current, merged_away.merged_into, merged_away.k1_page) == (
        "k1", None, "LARKSPUR RIDGE HOMES FUND LP", 2)
    assert [q.quote for q in ledger.questions] == ["LARKSPUR RIDGE FUND LP"]
    assert "a merger isn't a disposition" in ledger.questions[0].text


def test_cli_prints_no_amounts(workspace_home: Path, capsys):
    (workspace_home / "carryforwards").mkdir(parents=True)
    (workspace_home / "carryforwards" / "2024 Return.json").write_text(json.dumps(RETURN_2024))
    (workspace_home / "k1").mkdir()
    (workspace_home / "k1" / "k1.json").write_text(json.dumps([{**LARKSPUR, "final": True}]))
    assert cli.main(["passive"]) == 0
    out = capsys.readouterr().out
    assert "2025: 3 passive activities, starting from the 2024 return's Form 8582; 1 questions" in out
    assert ": its K-1 (k#.pdf p2), this year a loss, a loss carried in; a final K-1: a full disposition frees" in out
    for secret in ("1575", "2085", "12422", "Larkspur", "LARKSPUR"):
        assert secret not in out
    saved = json.loads((workspace_home / "passive" / "2025.json").read_text())
    assert saved["lines"][1]["carried"] == "1575"
