"""The to-do list: reading todo.md, due dates, ticking an item, the page's endpoints and `taxtrace todo`.
Made-up items only."""

from __future__ import annotations

import http.client
import json
import threading
from datetime import date
from pathlib import Path

import pytest

from taxtrace import cli, todo, web, workspace

TODAY = date(2026, 10, 28)
LIST = """\
# Money

## Estimated tax
Intro lines like this one are ignored.
- [ ] **Tue 10/27** Pay the **Q3** estimate, see `estimates`
  - the amount is in estimates/2026.json
  - [ ] check the Fernwick account balance
  - [x] find the voucher
- [ ] **Wed 10/28, time TBD** Call Marlowe Credit Union about the rollover
- [ ] **Mon 11/2** Move savings to the Larkspur brokerage
- [x] **Mon 10/5** Order the tax software
- [ ] **Fri 1/15/2027** Pay the fourth-quarter estimate

## Records
- [ ] Scan the Pemberton receipts
- [ ] **Sat 12/12** Sort the folder
"""


@pytest.fixture
def listed(workspace_home: Path) -> Path:
    workspace_home.mkdir(parents=True)
    file = workspace_home / workspace.TODO
    file.write_text(LIST)
    return file


def test_parse_reads_open_items_with_their_notes_and_subtasks():
    items = todo.parse(LIST, TODAY)
    assert [i.text for i in items] == [
        "Pay the **Q3** estimate, see `estimates`", "Call Marlowe Credit Union about the rollover",
        "Move savings to the Larkspur brokerage", "Pay the fourth-quarter estimate", "Scan the Pemberton receipts",
        "Sort the folder"]
    first = items[0]
    assert (first.section, first.line, first.due) == ("Estimated tax", 5, date(2026, 10, 27))
    assert first.notes == ["the amount is in estimates/2026.json"]
    assert first.subtasks == [{"text": "check the Fernwick account balance", "done": False},
                              {"text": "find the voucher", "done": True}]
    assert first.raw == "- [ ] **Tue 10/27** Pay the **Q3** estimate, see `estimates`"
    assert items[1].due == TODAY and items[1].time == "time TBD"
    assert items[4].due is None and items[4].section == "Records"


def test_only_the_leading_bold_date_counts():
    items = todo.parse("## A\n- [ ] Follow up Sat 10/31 about the form\n- [ ] Sent Wed 10/28 **Fri 11/6** on\n", TODAY)
    assert [i.due for i in items] == [None, None]


def test_a_month_and_day_take_the_date_within_two_months_back_to_ten_ahead():
    assert todo.infer(1, 15, None, date(2026, 12, 20)) == date(2027, 1, 15)
    assert todo.infer(12, 20, None, date(2027, 1, 10)) == date(2026, 12, 20)
    assert todo.infer(8, 30, None, TODAY) == date(2026, 8, 30)  # inside two months back
    assert todo.infer(9, 31, None, TODAY) is None
    assert todo.infer(2, 29, None, date(2026, 12, 1)) is None  # none of the nearby years has one
    assert todo.infer(1, 15, 2027, TODAY) == date(2027, 1, 15)


def test_a_january_item_in_a_december_list_is_next_year_and_later_not_overdue():
    on = date(2026, 12, 28)
    (item,) = todo.parse("## Tax\n- [ ] **Fri 1/15** Pay the estimate\n", on)
    assert item.due == date(2027, 1, 15) and todo.group(item, on) == "later"
    (item,) = todo.parse("## Tax\n- [ ] **Tue 12/22** Pay the estimate\n", on)
    assert todo.group(item, on) == "overdue"


def test_groups_and_order():
    items = todo.parse(LIST, TODAY)
    assert [todo.group(i, TODAY) for i in items] == ["overdue", "today", "week", "later", "undated", "later"]
    assert [i.text for i in todo.ordered(items)][-1] == "Scan the Pemberton receipts"
    assert [i.line for i in todo.due_within(items, TODAY, 7)] == [5, 9, 10]
    assert [i.line for i in todo.due_within(items, TODAY, 0)] == [5, 9]


def test_mark_done_changes_that_one_line_only(listed: Path):
    items = todo.parse(listed.read_text(), TODAY)
    target = items[2]
    todo.mark_done(listed, target.line, target.raw)
    before, after = LIST.splitlines(), listed.read_text().splitlines()
    assert [n for n, (a, b) in enumerate(zip(before, after, strict=True), 1) if a != b] == [target.line]
    assert after[target.line - 1] == "- [x] **Mon 11/2** Move savings to the Larkspur brokerage"


def test_mark_done_keeps_crlf_and_a_missing_final_newline(tmp_path: Path):
    file = tmp_path / "todo.md"
    file.write_bytes(b"## A\r\n- [ ] one\r\n- [ ] two")
    todo.mark_done(file, 2, "- [ ] one")
    todo.mark_done(file, 3, "- [ ] two")
    assert file.read_bytes() == b"## A\r\n- [x] one\r\n- [x] two"


def test_mark_done_refuses_when_the_line_changed(listed: Path):
    expect = "- [ ] **Mon 11/2** Move savings to the Larkspur brokerage"
    text = listed.read_text()
    listed.write_text(text.replace("Larkspur", "Larkspur Trust"))
    for line, wanted in [(11, expect), (999, expect), (0, expect), (8, "- [x] **Mon 10/5** Order the tax software")]:
        with pytest.raises(ValueError, match=r"nothing written|that line is gone"):
            todo.mark_done(listed, line, wanted)
    assert listed.read_text() == text.replace("Larkspur", "Larkspur Trust")


@pytest.fixture
def server():
    srv = web.serve(0, open_browser=False, token="t0ken")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def request(srv, method, path, body=None, token="t0ken"):
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Host": f"{web.APP_HOST}:{port}", "X-Taxtrace-Token": token, "Content-Type": "application/json"}
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    r = conn.getresponse()
    return r.status, json.loads(r.read())


def test_the_page_has_a_to_do_section_above_the_documents():
    html = web.page("t0ken").decode()
    assert 0 < html.index('id="todo"') < html.index("Documents by folder")


def test_api_todo_without_a_file_says_so(server, workspace_home):
    status, data = request(server, "GET", "/api/todo")
    assert status == 200 and data["items"] == [] and data["exists"] is False
    assert data["path"] == str(workspace_home / "todo.md")


def test_api_todo_lists_items_and_wants_the_token(server, listed):
    assert request(server, "GET", "/api/todo", token="wrong")[0] == 403
    status, data = request(server, "GET", "/api/todo")
    assert status == 200 and data["exists"] and data["path"] == str(listed)
    assert len(data["items"]) == 6
    assert {"line", "raw", "section", "text", "due", "group", "notes", "subtasks"} <= set(data["items"][0])
    assert all(i["group"] in todo.GROUPS for i in data["items"])


def test_api_todo_done_ticks_the_line_and_a_changed_line_is_409(server, listed):
    expect = "- [ ] **Fri 1/15/2027** Pay the fourth-quarter estimate"
    line = LIST.splitlines().index(expect) + 1
    assert request(server, "POST", "/api/todo/done", {"line": line, "text": expect}, token="wrong")[0] == 403
    assert request(server, "POST", "/api/todo/done", {"line": line, "text": expect + " now"})[0] == 409
    assert listed.read_text() == LIST
    assert request(server, "POST", "/api/todo/done", {"line": line, "text": expect}) == (200, {"ok": True})
    assert listed.read_text() == LIST.replace(expect, expect.replace("[ ]", "[x]"))
    assert request(server, "POST", "/api/todo/done", {"line": line, "text": expect})[0] == 409  # already done
    assert request(server, "POST", "/api/todo/done", {"line": "x"})[0] == 400


def test_api_todo_done_without_a_file_is_409(server):
    assert request(server, "POST", "/api/todo/done", {"line": 1, "text": "- [ ] x"})[0] == 409


def test_todo_is_never_read_as_a_document(listed):
    assert workspace.TODO in workspace.DERIVED
    assert all(d.name != workspace.TODO for d in workspace.sources())


def test_the_command_lists_open_items_by_due_date(listed, capsys, monkeypatch):
    monkeypatch.setattr(todo, "today", lambda: TODAY)
    assert cli.main(["todo"]) == 0
    out = capsys.readouterr().out.splitlines()
    assert len(out) == 6 and "Pay the **Q3** estimate" in out[0] and "[Estimated tax]" in out[0]
    assert "Scan the Pemberton receipts" in out[-1] and out[-1].startswith("no date")
    assert cli.main(["todo", "--due"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 3
    assert cli.main(["todo", "--due", "0"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 2
    assert cli.main(["todo", "--due", "60"]) == 0
    assert len(capsys.readouterr().out.splitlines()) == 4


def test_the_command_without_a_file_says_where_to_make_one(workspace_home, capsys):
    assert cli.main(["todo"]) == 1
    assert "todo.md" in capsys.readouterr().err
