"""The browser's Budget tab: /api/budget, its payments, the made-up household behind "Demo data", and the page's
own parts. Made-up plans and payees only (Initech, Globex, Umbrella)."""

from __future__ import annotations

import http.client
import json
import math
import shutil
import subprocess
import threading
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from test_budget import PIPE, PLAN, RULES

from taxtrace import budget, budget_import, web, workspace


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


GROUPED_PLAN = """\
year = 2031
[[lines]]
name = "Initech Utilities"
group = "fixed"
icon = "💡"
  [[lines.sub]]
  name = "Power"
  icon = "⚡"
  monthly = 120
  [[lines.sub]]
  name = "Water"
  monthly = 55
  [[lines.sub]]
  name = "Internet"
  monthly = 70
  cap = true

[[lines]]
name = "Globex Groceries"
group = "essentials"
monthly = 400
"""
GROUPED_RULES = """\
[[rules]]
match = "Initech Power"
line = "Power"

[[rules]]
match = "Initech Water"
line = "Water"

[[rules]]
match = "Initech Broadband"
line = "Internet"

[[rules]]
match = "Initech Utilities Fee"
line = "Initech Utilities"

[[rules]]
match = "Globex Grocery"
line = "Globex Groceries"
"""
GROUPED_MARCH = """\
2031-03-02 | Checking | Initech Power Co | Utilities | 150.00 |
2031-03-03 | Checking | Initech Water Works | Utilities | 20.00 |
2031-03-04 | Checking | Initech Broadband | Utilities | 69.00 |
2031-03-05 | Checking | Initech Utilities Fee | Utilities | 15.00 |
2031-03-06 | Checking | Globex Grocery | Groceries | 100.00 |
"""


@pytest.fixture
def grouped(workspace_home: Path, tmp_path: Path, monkeypatch) -> Path:
    """A workspace whose Initech Utilities line is split into three sub-lines, March 2031 imported."""
    from taxtrace import budget

    monkeypatch.setenv(budget_import.PRIVATE_ENV, str(tmp_path / "private"))
    folder = workspace_home / workspace.BUDGET
    folder.mkdir(parents=True)
    (folder / "budget-2031.toml").write_text(GROUPED_PLAN, encoding="utf-8")
    (folder / "rules.toml").write_text(GROUPED_RULES, encoding="utf-8")
    plan = budget.load_plan(folder)
    march = tmp_path / "march.txt"
    march.write_text(GROUPED_MARCH, encoding="utf-8")
    budget_import.import_file(march, "2031-03", folder, plan, budget.load_rules(folder, plan))
    return folder


def test_a_parent_line_carries_a_full_set_of_numbers_for_each_sub_line(server, grouped):
    d = get(server, "/api/budget?view=2031-03")[1]
    parent = next(x for x in d["lines"] if x["name"] == "Initech Utilities")
    subs = {s["name"]: s for s in parent["subs"]}
    assert list(subs) == ["Power", "Water", "Internet", "Not split"]
    line_keys = set(d["lines"][1]) - {"subs"}
    assert line_keys <= set(subs["Power"]) and {"parent", "icon"} <= set(subs["Power"])
    power, water, internet, rest = subs.values()
    assert (power["budget"], power["spent"], power["remaining"], power["over"]) == (120, 150, -30, True)
    assert power["parent"] == parent["name"]
    assert (water["spent"], water["over"], water["near"], water["group"]) == (20, False, False, "fixed")
    assert (internet["pct"], internet["near"], internet["over"], internet["cap"]) == (98.6, True, False, True)
    assert (rest["spent"], rest["budget"], rest["over"], rest["count"], rest["unsplit"]) == (15, None, False, 1, True)


def test_a_sub_lines_payments_are_its_own(server, grouped):
    rows = get(server, "/api/budget/payments?view=2031-03&line=Power")[1]["payments"]
    assert [(p["payee"], p["line"]) for p in rows] == [("Initech Power Co", "Power")]
    assert len(get(server, "/api/budget/payments?view=2031-03&line=Initech+Utilities")[1]["payments"]) == 4


def test_the_totals_come_from_the_parent_so_nothing_counts_twice(server, grouped):
    d = get(server, "/api/budget?view=2031-03")[1]
    t = d["totals"]
    assert [x["name"] for x in d["lines"]] == ["Initech Utilities", "Globex Groceries"]
    assert (t["budget"], t["spent"], t["remaining"], t["over"], t["near"]) == (645, 354, 291, 1, 0)
    assert d["groups"]["fixed"]["spent"] == 254 and d["groups"]["fixed"]["budget"] == 245
    assert d["groups"]["essentials"]["spent"] == 100
    parent = d["lines"][0]
    assert sum(s["spent"] for s in parent["subs"]) == parent["spent"] == 254


def test_a_parent_whose_payments_are_all_split_has_no_not_split_card(server, grouped):
    rules = GROUPED_RULES.replace('line = "Initech Utilities"', 'line = "Water"')
    (grouped / "rules.toml").write_text(rules, encoding="utf-8")
    parent = get(server, "/api/budget?view=2031-03")[1]["lines"][0]
    assert [s["name"] for s in parent["subs"]] == ["Power", "Water", "Internet"]


def test_the_page_draws_a_header_and_one_card_per_sub_line_not_a_list():
    html = web.page("t0ken").decode()
    js = html.split("function lineCard")[1].split("function fundCard")[0]
    assert "function groupHead" in js and "bghead" in js and "bgroup" in js
    assert "s => lineCard(s," in js  # each sub-line gets the same card as a line
    assert 'class: "subs"' not in html and "h(\"ul\"" not in js
    css = html.split("<style>")[1].split("</style>")[0]
    assert ".bghead" in css and ".bgroup" in css
    assert ".blines { display: grid; grid-template-columns: repeat(auto-fill" in css
    assert '"blist"' in html.split("function renderBudget")[1]
    # the over-budget lines still come first, the tiles and the group bar still read the parent totals
    assert "urgency(a) - urgency(b)" in js and "urgency(x) * 10" in html.split("function renderBudget")[1]
    render = html.split("function renderBudget")[1].split("async function loadBudget")[0]
    assert "t.over" in render and "d.groups[g].spent" in render


def _finite(value) -> bool:
    """Every number anywhere in a JSON value is a finite one (the page would print NaN or Infinity for any other)."""
    if isinstance(value, float):
        return math.isfinite(value)
    if isinstance(value, dict):
        return all(_finite(v) for v in value.values())
    if isinstance(value, list):
        return all(_finite(v) for v in value)
    return True


EDGE_PLAN = """\
year = 2031
[[lines]]
name = "Initech Nothing"
group = "fixed"
monthly = 0

[[lines]]
name = "Initech Utilities"
group = "fixed"
  [[lines.sub]]
  name = "Power"
  monthly = 0
  [[lines.sub]]
  name = "Water"
  monthly = 55

[[funds]]
name = "Initech Rainy Day"
monthly = 0
"""


@pytest.mark.parametrize("view", [None, "ytd", "2031-03", "2030-11", "2031-12"])
@pytest.mark.parametrize("today", [date(2030, 11, 24), date(2031, 1, 1), date(2031, 3, 15), date(2032, 2, 1)])
def test_no_view_of_an_empty_or_zero_budget_has_a_number_that_is_not_one(view, today):
    """Empty actuals, a zero budget, a sub-line with nothing, the year before it starts and the year after it ends."""
    plan = budget.parse_plan(EDGE_PLAN)
    s = budget.status(plan, [], {}, view, today)
    assert _finite(s) and s["rows"] == 0
    assert all(x["pct"] is None and x["pace"] is None for x in s["lines"] if x["budget"] == 0)
    assert s["lines"][1]["subs"][0]["pct"] is None  # the zero-budget sub-line has no share to show


def test_spending_on_a_zero_budget_line_is_over_with_no_share(workspace_home):
    plan = budget.parse_plan(EDGE_PLAN)
    rules = budget.parse_rules('[[rules]]\nmatch = "Initech Power"\nline = "Power"\n', plan)
    month = budget.Month("2031-03", [budget.Txn(date(2031, 3, 4), "Initech Power Co", Decimal("9.50"))])
    s = budget.status(plan, rules, {"2031-03": month}, "2031-03", date(2031, 3, 31))
    power = s["lines"][1]["subs"][0]
    assert (power["spent"], power["budget"], power["pct"], power["pace"], power["over"]) == (9.5, 0, None, None, True)
    assert _finite(s)


FORMATTERS = ("// -- number formatters", "// -- end of the number formatters")


@pytest.mark.skipif(shutil.which("node") is None, reason="node isn't installed")
def test_the_pages_number_formatters_print_a_dash_for_what_isnt_a_number():
    html = web.page("t0ken").decode()
    code = html.split(FORMATTERS[0])[1].split("\n", 1)[1].split(FORMATTERS[1])[0]
    probe = ("const out = [money(undefined), money(NaN), money(Infinity), money(null), money(''), money(-1234.4), "
             "cents(undefined), cents(NaN), cents(12.5), pctText(undefined), pctText(NaN), pctText(Infinity), "
             "pctText(0), pctText(98.6), ratio(5, 0), ratio(0, 0), ratio(null, 10), ratio(NaN, 10), ratio(50, 200), "
             "ratio(500, 200), ratio(undefined, undefined)]; console.log(JSON.stringify(out));")
    run = subprocess.run(["node", "-e", code + probe], capture_output=True, text=True, check=True)
    assert json.loads(run.stdout) == ["—", "—", "—", "—", "—", "−$1,234", "—", "—", "$12.50", "—", "—", "—", "0%",
                                      "99%", 1, 0, None, None, 0.25, 1, None]


def test_the_page_says_when_nothing_is_imported_for_the_period():
    html = web.page("t0ken").decode()
    assert "No actuals imported for this period yet" in html.split("function renderBudget")[1]


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
