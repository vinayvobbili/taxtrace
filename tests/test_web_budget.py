"""The browser's Budget tab: /api/budget, its payments, the made-up household behind "Demo data", and the page's
own parts. Made-up plans and payees only (Initech, Globex, Umbrella)."""

from __future__ import annotations

import http.client
import json
import shutil
import threading
from datetime import date
from pathlib import Path

import pytest
from test_budget import PIPE, PLAN, RULES

from taxtrace import budget_import, web, workspace


@pytest.fixture
def server():
    srv = web.serve(0, open_browser=False, token="t0ken")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def get(srv, path, token="t0ken", host=None):
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path, headers={"Host": host or f"{web.APP_HOST}:{port}", "X-Taxtrace-Token": token})
    r = conn.getresponse()
    return r.status, json.loads(r.read())


@pytest.fixture
def imported(workspace_home: Path, tmp_path: Path, monkeypatch) -> Path:
    """A workspace with the made-up plan and rules, and March 2031 imported from the pipe fixture."""
    monkeypatch.setenv(budget_import.PRIVATE_ENV, str(tmp_path / "private"))
    folder = workspace_home / workspace.BUDGET
    folder.mkdir(parents=True)
    (folder / "budget-2031.toml").write_text(PLAN, encoding="utf-8")
    (folder / "rules.toml").write_text(RULES, encoding="utf-8")
    from taxtrace import budget

    plan = budget.load_plan(folder)
    budget_import.import_file(PIPE, "2031-03", folder, plan, budget.load_rules(folder, plan))
    return folder


def test_demo_mode_shows_the_made_up_household(server, workspace_home):
    status, d = get(server, "/api/budget?demo=1")
    assert status == 200 and d["source"] == "demo" and d["folder"] is None
    assert len(d["lines"]) == 13 and set(d["groups"]) == {"fixed", "essentials", "family", "discretionary"}
    assert d["view"] == "ytd" and d["year"] == date.today().year and d["funds"]
    assert d["totals"]["spent"] > 0 and d["lines"][0]["icon"]


def test_demo_payments_load_for_a_line(server, workspace_home):
    status, d = get(server, "/api/budget/payments?demo=1&line=Groceries")
    assert status == 200 and d["payments"] and all(p["line"] == "Groceries" for p in d["payments"])
    assert {"date", "payee", "amount", "pending", "refund", "account"} <= set(d["payments"][0])


def test_without_a_plan_the_tab_says_where_it_would_be(server, workspace_home):
    status, d = get(server, "/api/budget")
    assert status == 200 and d == {"source": "none", "folder": str(workspace_home / "budget"), "exists": False}


def test_the_workspaces_budget_is_read_and_nothing_is_written(server, imported):
    before = {p: p.read_bytes() for p in imported.rglob("*") if p.is_file()}
    status, d = get(server, "/api/budget?view=2031-03")
    assert status == 200 and d["source"] == "workspace" and d["view"] == "2031-03"
    assert {x["name"]: x["spent"] for x in d["lines"] if x["spent"]} == {
        "Groceries": 88.2, "Fuel and transit": 64.1, "Health": 54.3, "Shopping": 105.0, "Dining out": 74.05,
        "Fun": 12.75}
    assert d["other"]["unmatched"]["count"] == 1
    assert {p: p.read_bytes() for p in imported.rglob("*") if p.is_file()} == before


def test_payments_never_carry_an_account_number(server, imported):
    status, d = get(server, "/api/budget/payments?view=2031-03&line=Health")
    assert status == 200 and [p["account"] for p in d["payments"]] == ["Checking ••••"]
    body = json.dumps(get(server, "/api/budget/payments?view=2031-03&line=excluded")[1])
    assert "4417" not in body


@pytest.mark.parametrize("path", ["/api/budget?view=March", "/api/budget/payments?view=2031-13&line=Health"])
def test_a_bad_view_is_400(server, imported, path):
    assert get(server, path)[0] == 400


def test_a_broken_budget_file_is_a_400_that_says_why(server, imported):
    (imported / "budget-2031.toml").write_text("year = [")
    status, d = get(server, "/api/budget")
    assert status == 400 and "valid TOML" in d["error"]


def test_the_budget_wants_the_token_and_our_own_host(server, imported):
    assert get(server, "/api/budget?demo=1", token="wrong")[0] == 403
    assert get(server, "/api/budget?demo=1", host="evil.example:80")[0] == 403


def test_a_trial_month_is_offered_but_not_in_the_year(server, imported):
    shutil.copy(imported / "actuals" / "2031-03.json", imported / "actuals" / "2030-11.json")
    data = json.loads((imported / "actuals" / "2030-11.json").read_text())
    data.update(month="2030-11", trial=True)
    (imported / "actuals" / "2030-11.json").write_text(json.dumps(data))
    d = get(server, "/api/budget?view=2030-11")[1]
    assert d["trial"] and "trial month" in d["label"]
    assert [m["trial"] for m in d["available"]] == [True, False]


def test_the_page_has_the_budget_tab_after_the_entry_sheet():
    html = web.page("t0ken").decode()
    tabs = html.split('id="tabs"')[1].split("</nav>")[0]
    assert [t for t in ("Overview", "Import", "Entry sheet", "Budget") if t in tabs] == \
        ["Overview", "Import", "Entry sheet", "Budget"]
    assert tabs.index("tab-entry") < tabs.index("tab-budget")
    for ident in ("tab-budget", "view-budget", "budget-span", "budget-month", "budget-demo", "budget-stats",
                  "budget-body", "budget-demo-note"):
        assert f'id="{ident}"' in html
    assert "/api/budget" in html and '"budget"' in html.split("const VIEWS")[1].split(";")[0]


def test_the_page_keeps_its_theme_and_width_settings_and_the_group_colours():
    html = web.page("t0ken").decode()
    assert "taxtrace-theme" in html and "taxtrace-width" in html and 'data-w="wide"' in html
    for group in ("fixed", "essentials", "family", "discretionary"):
        assert f"--b-{group}:" in html and f".grp-{group}" in html
    assert "prefers-reduced-motion" in html


def test_every_screen_shares_the_polish_the_active_tab_and_hover_lift():
    css = web.page("t0ken").decode().split("<style>")[1].split("</style>")[0]
    assert '.tabs a[aria-current="page"]::after' in css
    for card in (".stat:hover", ".folder:hover", ".tcard:hover", ".sec:hover", ".res:hover", ".entry-extra .card:hover",
                 ".bcard:hover"):
        assert card in css, card


def test_the_page_loads_nothing_from_the_network():
    html = web.page("t0ken").decode()
    assert "<script src" not in html and "https://" not in html.split("<style>")[1].split("</style>")[0]
