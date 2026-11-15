"""scripts/videos/demo.py: the made-up household the videos run on, built with the real commands in a temporary
workspace. Every name, town and amount in it is invented."""

import importlib.util
import json
import re
import sys
from datetime import date
from pathlib import Path

import pytest

from taxtrace import workspace

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "videos" / "demo.py"


@pytest.fixture(scope="module")
def demo():
    spec = importlib.util.spec_from_file_location("video_demo_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # a dataclass looks its module up
    spec.loader.exec_module(module)
    yield module
    sys.modules.pop(spec.name, None)


@pytest.fixture
def household(demo, tmp_path: Path):
    home = tmp_path / "TaxData"
    with demo.workspace_at(home):
        run = demo.build(home, tmp_path / "export", today=date(2026, 11, 15))
    return run


def test_the_build_works_in_its_own_folder_and_gives_the_workspace_back(demo, tmp_path: Path, monkeypatch):
    monkeypatch.delenv("TAXTRACE_HOME", raising=False)
    here = workspace.home()
    with demo.workspace_at(tmp_path / "TaxData"):
        assert workspace.home() == tmp_path / "TaxData"
    assert workspace.home() == here


def test_the_preparers_export_is_sorted_by_year_and_the_drivers_license_is_skipped(household):
    first, again = household.said["import"], household.said["import again"]
    assert "copied 6 of 7 files" in first
    assert "Driver License.pdf  (identity document)" in first
    assert re.search(r"^prior-returns/", first, re.M)
    assert "copied 0 of 7 files" in again and again.count("already imported") == 6
    assert sorted(p.name for p in (household.home / "2026").iterdir()) == [
        "2026 1098 Globex Bank.pdf", "2026 Umbrella Brokerage 1099.pdf", "2026 W-2 Initech.pdf"]
    assert (household.home / "2025").is_dir() and (household.home / "prior-returns").is_dir()


def test_the_w2_is_read_with_its_checks_and_every_value_keeps_its_page_and_quote(household):
    assert "amounts in boxes 1, 2, 3, 4, 5, 6, 16, 17" in household.said["w2"]
    assert "5 of 5 checks pass" in household.said["w2"]
    saved = json.loads(next((household.home / "forms").glob("*W-2*.json")).read_text())[0]
    assert saved["employer"] == "Initech Payroll Services" and saved["state"] == "CO"
    assert saved["amounts"]["1"]["amount"] == "120000.00" and saved["amounts"]["1"]["quote"] == "120,000.00"
    assert saved["amounts"]["4"]["page"] == 1
    assert [c["what"] for c in saved["checks"] if c["ok"]][3] == "box 4 is 6.2% of box 3"


def test_the_mortgage_statement_is_read_and_the_other_forms_are_saved(household):
    assert "3 of 3 checks pass" in household.said["1098"]
    assert (household.home / "forms" / "paystub.json").is_file()
    assert json.loads((household.home / "forms" / "2026 Umbrella Brokerage 1099.json").read_text())[0]["year"] == 2026


def test_the_entry_sheet_and_the_moves_are_the_real_commands_output(household):
    sheet = (household.home / "entry" / "2026.txt").read_text()
    assert "Box 1, Wages, tips, other compensation: 120,000.00  <- 2026 W-2 Initech.pdf p1" in sheet
    assert "Box 1a, Ordinary dividends: 1,500.00" in sheet and "9,000.00" in sheet
    assert "[missing]" in sheet and "[estimate]" in sheet
    plan = json.loads((household.home / "moves" / "2026.json").read_text())
    assert [m["key"] for m in plan["moves"]] == ["401k", "charity"]


def test_the_to_do_list_is_dated_from_the_day_it_is_built(household):
    todo = (household.home / "todo.md").read_text()
    assert "**Sun 11/15** Move the year-end cash" in todo and "**Tue 11/17**" in todo
    assert re.findall(r"^## (\w+)", todo, re.M) == ["Taxes", "Money"]


def test_what_the_commands_print_never_holds_an_amount_or_a_name(household):
    for said in household.said.values():
        for secret in ("120,000", "20,000", "9,000", "Initech Payroll", "Globex", "Rivera"):
            assert secret not in said, secret
