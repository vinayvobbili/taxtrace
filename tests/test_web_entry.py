"""The browser's Entry sheet screen: /api/entry and its links to the to-do list. Made-up saved forms for an invented
Initech employee in Boulder, CO."""

from __future__ import annotations

import http.client
import json
import threading
from pathlib import Path

import pytest
from test_entry import FOUND, INT, K1, RENTAL, STUB, save

from taxtrace import cli, entry, todo, web, workspace


@pytest.fixture
def server():
    srv = web.serve(0, open_browser=False, token="t0ken")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def get(srv, path, token="t0ken"):
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    conn.request("GET", path, headers={"Host": f"{web.APP_HOST}:{port}", "X-Taxtrace-Token": token})
    r = conn.getresponse()
    return r.status, json.loads(r.read())


@pytest.fixture
def saved(workspace_home: Path) -> Path:
    save(workspace_home, "forms", "stub.json", STUB)
    save(workspace_home, "forms", "int.json", [INT])
    save(workspace_home, "k1", "umbrella.json", [K1])
    save(workspace_home, "schedule-e", "2026.json", RENTAL)
    save(workspace_home, "foreign", "2026.json", FOUND)
    save(workspace_home, "foreign", "2026-confirmed.json", {"filing": "joint"})
    return workspace_home


def section(data: dict, title: str) -> dict:
    return next(s for s in data["sections"] if s["title"].startswith(title))


def test_the_sheet_is_what_the_command_builds(server, saved):
    status, data = get(server, "/api/entry?year=2026")
    assert status == 200 and data["year"] == 2026
    sheet = cli.entry_sheet(saved, 2026)
    assert [s["title"] for s in data["sections"]] == [s.title for s in sheet.sections]
    assert data["sections"][0]["rows"] == sheet.to_json()["sections"][0]["rows"]
    assert data["counts"] == {"ready": sheet.count(entry.READY), "estimate": sheet.count(entry.ESTIMATE),
                              "missing": sheet.count(entry.MISSING)}
    assert data["questions"] == sheet.questions and data["yourself"] == entry.YOURSELF


def test_rows_carry_values_status_and_the_document_they_came_from(server, saved):
    data = get(server, "/api/entry?year=2026")[1]
    interest = {r["what"]: r for r in section(data, "Interest")["rows"]}["Box 1, Interest income"]
    assert (interest["value"], interest["status"], interest["source"]) == ("41.17", "ready", "globex-1099.pdf p2")
    wages = {r["what"]: r for r in section(data, "Wages")["rows"]}["Box 1, wages"]
    assert wages["status"] == "estimate" and wages["source"] == "initech-stub.pdf"
    assert section(data, "Wages")["counts"]["estimate"] >= 1


def test_what_is_missing_says_which_command_fills_it(server, saved):
    data = get(server, "/api/entry?year=2026")[1]
    missing = [r for s in data["sections"] for r in s["rows"] if r["status"] == "missing"]
    assert missing and all(r["value"] == "" and "`taxtrace" in r["source"] for r in missing)
    assert data["counts"]["missing"] == len(missing)


def test_a_workspace_with_nothing_saved_is_all_missing_and_the_year_is_this_one(server, workspace_home):
    status, data = get(server, "/api/entry")
    assert status == 200 and data["year"] == web.date.today().year
    assert data["counts"]["ready"] == 0 and data["counts"]["missing"] > 0
    assert data["file"] is None and data["years"] == [data["year"]]


def test_years_come_from_folders_and_saved_forms_and_the_latest_is_the_default(server, saved):
    (saved / "2024").mkdir()
    data = get(server, "/api/entry")[1]
    assert data["years"] == [2024, 2026] and data["year"] == 2026
    assert get(server, "/api/entry?year=2024")[1]["year"] == 2024


def test_the_file_the_command_wrote_is_named(server, saved, capsys):
    assert get(server, "/api/entry?year=2026")[1]["file"] is None
    assert cli.main(["entry", "--year", "2026"]) == 0
    assert get(server, "/api/entry?year=2026")[1]["file"] == str(saved / "entry" / "2026.txt")


def test_forms_you_said_to_expect_are_still_to_come(server, saved):
    save(saved, "entry", "2026-expected.json", ["1098=Initrode Loans"])
    coming = [c["text"] for c in get(server, "/api/entry?year=2026")[1]["coming"]]
    assert "1098: Initrode Loans (you said to expect it)" in coming
    assert "Form W-2" in coming  # only a pay stub so far


def test_nothing_is_written_by_looking(server, saved):
    before = {p for p in saved.rglob("*") if p.is_file()}
    get(server, "/api/entry?year=2026")
    assert {p for p in saved.rglob("*") if p.is_file()} == before


LIST = """\
## Taxes
- [ ] **Fri 12/4/2026** Ask Initech payroll when the W-2 will arrive
- [ ] **Mon 1/4/2027** Chase the Umbrella K-1
- [ ] Clean the garage
"""


def test_sections_link_to_the_to_do_items_that_mention_them(server, saved, monkeypatch):
    (saved / workspace.TODO).write_text(LIST)
    data = get(server, "/api/entry?year=2026")[1]
    line = {i.text.split()[-1]: i.line for i in todo.parse(LIST, todo.today())}  # by its last word
    wages = section(data, "Wages")  # an estimate, from the pay stub, until the W-2 comes
    assert [t["line"] for t in wages["todo"]] == [line["arrive"]]
    assert wages["todo"][0]["title"].startswith("Ask Initech payroll")
    coming = {c["text"]: c["todo"] for c in data["coming"]}
    assert [t["line"] for t in coming["Form W-2"]] == [line["arrive"]]
    linked = {t["line"] for s in data["sections"] for t in s["todo"]}
    assert line["garage"] not in linked
    assert line["K-1"] not in linked  # the Umbrella K-1 is read: nothing left to do on its section
    assert data["open_todo"] == 3


def test_a_section_with_nothing_left_has_no_to_do_links(server, saved):
    (saved / workspace.TODO).write_text(LIST)
    data = get(server, "/api/entry?year=2026")[1]
    ready_only = [s for s in data["sections"] if s["rows"] and s["counts"]["missing"] == s["counts"]["estimate"] == 0]
    assert ready_only and all(s["todo"] == [] for s in ready_only)


@pytest.mark.parametrize("path", ["/api/entry?year=next", "/api/entry?year=1999", "/api/entry?year=20267"])
def test_a_bad_year_is_400(server, saved, path):
    assert get(server, path)[0] == 400


def test_the_endpoint_wants_the_token(server, saved):
    assert get(server, "/api/entry", token="wrong")[0] == 403


def test_the_page_has_the_entry_screen_with_stable_ids():
    html = web.page("t0ken").decode()
    for ident in ("tab-entry", "view-entry", "entry-year", "entry-filter", "entry-stats", "entry-sections",
                  "entry-extra", "entry-todo"):
        assert f'id="{ident}"' in html
    assert "/api/entry" in html


def test_the_entry_sheet_never_hands_a_null_to_replace_children():
    """`replaceChildren(card, null)` writes the word "null" on the page: a missing card must be an empty list."""
    html = web.page("t0ken").decode()
    render = html.split("function renderEntry")[1].split("let entryData")[0]
    assert "Questions still open" in render
    assert ": null)" not in render
