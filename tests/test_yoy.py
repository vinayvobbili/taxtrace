"""A year against the one before, for a made-up couple. Every value is invented."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from conftest import printed

from taxtrace import cli, yoy


def w2(year: int, ein: str = "12-3456789", employee: str = "4410", **kw) -> dict:
    return {"form": "W-2", "year": year, "ein": ein, "employee": employee, "employer": "Initech", "file": "w2.pdf",
            "amounts": {"1": {"amount": "150000"}}, **kw}


def div(year: int, tin: str = "98-7654321") -> dict:
    return {"form": "1099-DIV", "year": year, "payer_tin": tin, "file": "globex.pdf", "amounts": {}}


def statuses(found: list[yoy.Document]) -> dict[str, str]:
    return {f"{d.form} {d.name}": d.status for d in found}


def test_a_document_from_last_year_that_hasnt_come_is_listed_first():
    found = yoy.documents([w2(2025), w2(2026), div(2025)], [], 2026)
    assert found[0] == yoy.Document("1099-DIV", "globex.pdf", yoy.MISSING)
    assert statuses(found)["W-2 Initech"] == yoy.HERE


def test_a_payers_new_name_is_still_the_same_payer():
    found = yoy.documents([w2(2025), w2(2026, employer="Initech Holdings")], [], 2026)
    assert [d.status for d in found] == [yoy.HERE]


def test_each_spouses_w2_counts_apart():
    found = yoy.documents([w2(2025), w2(2025, employee="7720"), w2(2026)], [], 2026)
    assert sorted(d.status for d in found) == [yoy.HERE, yoy.MISSING]


def test_a_new_payer_is_listed():
    assert statuses(yoy.documents([div(2026)], [], 2026)) == {"1099-DIV globex.pdf": yoy.NEW}


def test_a_copy_isnt_a_document():
    assert yoy.documents([div(2025), {**div(2026), "copy_of": "other.pdf"}], [], 2026)[0].status == yoy.MISSING


def test_a_final_k1_isnt_expected_and_another_is():
    k1s = [{"year": 2025, "ein": "11-1111111", "partnership": "Umbrella Fund", "final": True},
           {"year": 2025, "ein": "22-2222222", "partnership": "Globex Partners"},
           {"year": 2026, "ein": "33-3333333", "partnership": "Hooli Land"}]
    assert statuses(yoy.documents([], k1s, 2026)) == {"K-1 Umbrella Fund": yoy.ENDED,
                                                      "K-1 Globex Partners": yoy.MISSING, "K-1 Hooli Land": yoy.NEW}


def test_a_foreign_account_needs_its_statements_again():
    then = {"accounts": [{"account": "1111", "country": "Freedonia"}, {"account": "2222", "country": "Freedonia"}]}
    found = yoy.accounts({"accounts": [{"account": "1111"}]}, then)
    assert [d.status for d in found] == [yoy.HERE, yoy.MISSING]
    assert yoy.accounts(None, None) == []


@pytest.mark.parametrize(("now", "then", "words"), [
    (None, 100, "not built yet"), (0, 0, ""), (100, 0, "new this year"), (0, 100, "gone this year"),
    (105, 100, "about the same"), (95, 100, "about the same"), (130, 100, "up 10% to 50%"),
    (70, 100, "down 10% to 50%"), (150, 100, "up more than 50%"), (20, 100, "down more than 50%"),
    (-50, -100, "up more than 50%")])
def test_a_line_moves_in_words(now, then, words):
    assert yoy.movement(None if now is None else Decimal(now), Decimal(then)) == words


def test_lines_find_the_number_a_line_had_and_skip_empty_ones():
    built = [("7", "Capital gain", Decimal(1000)), ("11", "Income", Decimal(100)), ("23", "Other", Decimal(0))]
    moves = yoy.lines(built, {"7a": Decimal(1000), "11b": Decimal(300)})
    assert [(m.line, m.words, m.large) for m in moves] == [("7", "about the same", False),
                                                           ("11", "down more than 50%", True)]


def test_the_command_lists_without_an_amount(workspace_home, capsys):
    for folder, name, data in (
            ("forms", "w2.json", [w2(2025), w2(2026), div(2025)]),
            ("carryforwards", "2025.json", {"year": 2025, "f1040": {"lines": {"11a": "160000", "24": "20000"}}}),
            ("foreign", "2026-confirmed.json", {"filing": "joint"})):
        (workspace_home / folder).mkdir(parents=True, exist_ok=True)
        (workspace_home / folder / name).write_text(json.dumps(data))
    assert cli.main(["yoy", "--year", "2026"]) == 1
    out = printed(capsys)
    assert "not here yet: 1099-DIV" in out
    assert "2026 against 2025" in out
    for secret in ("150000", "150,000", "160,000", "20,000"):
        assert secret not in out
    assert (workspace_home / "yoy" / "2026.txt").exists()


def test_with_no_filed_return_it_still_lists_the_documents(workspace_home, capsys):
    (workspace_home / "forms").mkdir(parents=True)
    (workspace_home / "forms" / "w2.json").write_text(json.dumps([w2(2025), w2(2026)]))
    assert cli.main(["yoy", "--year", "2026"]) == 0
    assert "no filed 2025 return" in printed(capsys)
