"""The MCP tools: they describe themselves fully, return the expected shape, and never return a raw value.
Made-up documents only."""

from __future__ import annotations

import asyncio
import json
import re
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from conftest import AMOUNTS, NAMES, PRIOR_RETURN, TAXPAYER, make_pdf
from test_f1098 import FORM_1098, SECRETS
from test_k1 import FACE, draw

from taxtrace import cli, todo, workspace

mcp = pytest.importorskip("taxtrace.mcp_server")
TOOLS = {t.name: t for t in asyncio.run(mcp.server.list_tools())}


def call(name: str, **args):
    """What a client gets back: the JSON text of the tool's result, parsed."""
    result = asyncio.run(mcp.server.call_tool(name, args))
    return json.loads(result.content[0].text)


def test_every_parameter_is_described():
    missing = [f"{name}.{param}" for name, t in TOOLS.items()
               for param, schema in t.input_schema.get("properties", {}).items() if not schema.get("description")]
    assert not missing


def test_every_tool_is_read_only():
    assert {name for name, t in TOOLS.items() if not (t.annotations and t.annotations.read_only_hint)} == set()


def test_allowed_values_match_the_code():
    from typing import get_args
    assert get_args(mcp.Form) == mcp.review.FORMS


@pytest.mark.parametrize("tool, sibling", [
    ("get_status", "list_documents"), ("get_status", "get_todo"), ("list_documents", "get_status"),
    ("list_documents", "get_document_outline"), ("get_document_outline", "get_form_checks"),
    ("get_document_outline", "list_documents"), ("get_form_checks", "get_document_outline"),
    ("get_todo", "list_documents"),
])
def test_overlapping_tools_point_to_each_other(tool, sibling):
    assert sibling in TOOLS[tool].description


VERBS = {"get", "list"}


def test_tool_names_start_with_a_verb():
    assert {name for name in TOOLS if name.split("_")[0] not in VERBS} == set()


# -- a made-up workspace

TODO_LIST = """\
## Estimated tax
- [ ] **{soon}** Pay $4,250.75 to Marlowe Credit Union, account 5527018834
  - the voucher is in the Fernwick folder
  - [ ] ask Pemberton about 1,830.40
- [ ] Mail the $912.00 check to Larkspur Brokerage

## Records
- [x] **{done}** Order the tax software
- [ ] **{late}** Scan the receipts from Pemberton
"""
TODO_AMOUNTS = ["4,250", "4250", "5527018834", "1,830", "912"]
TODO_NAMES = ["Marlowe", "Fernwick", "Pemberton", "Larkspur"]


@pytest.fixture
def workspace_with_documents(workspace_home: Path) -> Path:
    make_pdf(workspace_home / "prior-returns" / f"{TAXPAYER.replace(' ', '_')}_2025_Return.pdf", PRIOR_RETURN)
    draw(workspace_home / "2025" / "Thistledown 1098.pdf", [FORM_1098, FORM_1098])
    draw(workspace_home / "2025" / "Quillfeather K-1.pdf", [FACE])
    on = todo.today()
    (workspace_home / workspace.TODO).write_text(TODO_LIST.format(
        soon=(on + timedelta(days=3)).strftime("%a %-m/%-d"), done=on.strftime("%a %-m/%-d"),
        late=(on - timedelta(days=4)).strftime("%a %-m/%-d")))
    return workspace_home


def test_status_counts_what_is_there(workspace_with_documents):
    status = call("get_status")
    assert status["exists"] and status["documents"] == 3 and status["todo"] is True
    assert status["years"] == ["2025"]
    assert {f["name"]: f["documents"] for f in status["folders"]} == {"2025": 2, "prior-returns": 1}
    assert status["documents_read"] == 0 and status["saved"] == {}


def test_status_without_a_workspace(workspace_home):
    status = call("get_status")
    assert status["exists"] is False and status["documents"] == 0 and "message" in status


def test_listing_gives_ids_and_masks_names(workspace_with_documents):
    rows = call("list_documents")["documents"]
    assert [r["id"] for r in rows] == [1, 2, 3]
    assert {r["kind"] for r in rows} == {"pdf"}
    assert all(name not in json.dumps(rows) for name in [*NAMES, "Thistledown", "Quillfeather"])
    assert call("list_documents", only="read")["count"] == 0 and call("list_documents", only="unread")["count"] == 3


def test_a_document_taxtrace_saved_something_from_is_read(workspace_with_documents):
    assert cli.main(["1098", "2025"]) == 0
    assert [r["name"] for r in call("list_documents", only="read")["documents"]] == ["*********** 1098.pdf"]
    assert call("get_status")["saved"] == {"forms": 1}


def test_outline_lists_pages_by_masked_heading(workspace_with_documents):
    first = next(r for r in call("list_documents")["documents"] if r["folder"] == "prior-returns")
    out = call("get_document_outline", id=first["id"])
    assert out["pages"] == 2 and [p["page"] for p in out["outline"]] == [1, 2]
    assert any("Form 4562" in h for p in out["outline"] for h in p["headings"])
    assert [p["page"] for p in call("get_document_outline", id=first["id"], start=2)["outline"]] == [2]


def test_outline_of_a_locked_document_is_not_opened(workspace_home):
    make_pdf(workspace_home / "2025" / "locked.pdf", PRIOR_RETURN, password="hunter22")
    out = call("get_document_outline", id=1)
    assert out["locked"] is True and "outline" not in out


def test_an_unknown_document_says_what_ids_exist(workspace_with_documents):
    with pytest.raises(mcp.ToolError, match="ids 1 to 3"):
        call("get_document_outline", id=9)


def test_form_checks_report_passes_and_questions(workspace_with_documents):
    out = call("get_form_checks", form="1098")
    assert out["forms_found"] == 2 and out["forms_failing"] == 0
    first, second = out["forms"]
    assert (first["form"], first["year"], first["checks"], first["passed"]) == ("1098", 2025, 3, 3)
    assert first["questions"] and second["copy_of_page"] == 1
    assert call("get_form_checks", form="k1")["forms_found"] == 1
    assert call("get_form_checks", form="1099")["forms_found"] == 0


def test_form_checks_report_a_failure_without_its_value(workspace_home):
    from test_k1 import edited
    draw(workspace_home / "2025" / "bad 1098.pdf", [edited(FORM_1098, **{"171,305.62": "17,130.56"})])
    out = call("get_form_checks", form="1098", id=1)
    assert out["forms_failing"] == 1 and out["forms"][0]["failed"]
    assert "17,130" not in json.dumps(out) and "171,305" not in json.dumps(out)


def test_todo_groups_by_due_date_with_masked_text(workspace_with_documents):
    out = call("get_todo")
    assert out["exists"] and out["counts"] == {"overdue": 1, "week": 1, "undated": 1}
    assert [i["group"] for i in out["items"]] == ["overdue", "week", "undated"]
    soon = out["items"][1]
    assert soon["days_left"] == 3 and soon["due"] == (todo.today() + timedelta(days=3)).isoformat()
    assert soon["text"].startswith("Pay $#,###.## to ******* Credit Union, account ##########")
    assert [i["text"] for i in call("get_todo", days=7)["items"]] != [] and len(call("get_todo", days=7)["items"]) == 2


def test_todo_without_a_list(workspace_home):
    out = call("get_todo")
    assert out["exists"] is False and out["items"] == []


# -- privacy

ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
LABELLED = re.compile(r"(?:form|schedule|line|part|page|worksheet) \d+", re.I)


def test_no_tool_returns_a_value_or_a_name(workspace_with_documents):
    """Every tool's output, over a workspace with amounts, IDs and names in its documents and its to-do list."""
    assert cli.main(["1098", "2025"]) == 0  # so the saved files hold the real values too
    ids = [r["id"] for r in call("list_documents")["documents"]]
    outputs = [call("get_status"), call("list_documents"), call("get_todo"), call("get_todo", days=30),
               *(call("get_document_outline", id=i, limit=200, lines=5) for i in ids),
               *(call("get_form_checks", form=f) for f in ("1098", "1099", "k1"))]
    blob = json.dumps(outputs, ensure_ascii=False)
    assert len(outputs) >= 10
    for secret in [*AMOUNTS, *SECRETS, *TODO_AMOUNTS, *NAMES, *TODO_NAMES, "Thistledown", "Quenby", "hunter22"]:
        assert secret not in blob, secret
    # no digit run longer than a form number or a year survives, once the dates the tools return are set aside
    rest = ISO_DATE.sub("", blob).replace("2025", "").replace("1098", "").replace("1099", "")
    rest = re.sub(r"##/##/\d{4}", "", rest)  # a date in a document: masking keeps its year
    rest = LABELLED.sub("", rest)  # Form 4562, Line 22: numbers masking keeps because they name a form
    long = re.search(r".{0,30}\d{3,}", rest)
    assert not long, long.group(0)
    assert str(workspace.home()) not in blob and "pytest-" not in blob


def test_redact_terms_are_masked_too(workspace_with_documents):
    (workspace_with_documents / workspace.TERMS_FILE).write_text("Estimated\n")
    assert "Estimated" not in json.dumps(call("get_todo"))


def test_the_server_does_not_import_the_chat_or_a_cloud_sdk():
    import subprocess
    code = "import sys, taxtrace.mcp_server; print([m for m in ('anthropic', 'taxtrace.chat') if m in sys.modules])"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=True).stdout
    assert out.strip() == "[]"


# -- the command and the registry entry

def test_mcp_command_says_how_to_install_the_extra(monkeypatch, capsys):
    import taxtrace
    monkeypatch.delitem(sys.modules, "taxtrace.mcp_server", raising=False)
    monkeypatch.delattr(taxtrace, "mcp_server", raising=False)
    for name in [m for m in sys.modules if m == "mcp" or m.startswith("mcp.")] or ["mcp"]:
        monkeypatch.setitem(sys.modules, name, None)
    assert cli.main(["mcp"]) == 1
    assert "pip install 'taxtrace[mcp]'" in capsys.readouterr().err


def test_registry_entry_matches_the_release():
    """The MCP Registry lists the version in server.json and checks the README on PyPI names the server."""
    from taxtrace import __version__

    root = Path(__file__).parent.parent
    entry = json.loads((root / "server.json").read_text())
    assert entry["version"] == entry["packages"][0]["version"] == __version__
    assert len(entry["description"]) <= 100  # the registry refuses a longer one (422)
    assert entry["packages"][0]["environmentVariables"][0]["name"] == "TAXTRACE_HOME"
    assert f"mcp-name: {entry['name']}" in (root / "README.md").read_text()
