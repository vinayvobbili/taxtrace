"""The budget's files live in the workspace but are never documents: nothing lists, reads or sends them.
Made-up files, merchants and amounts only."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import make_pdf, printed

from taxtrace import chat, cli, review, web, workspace

BUDGET_FILES = {
    "umbrella-streaming-export.csv": "Date,Description,Amount\n2026-11-03,INITECH FUEL 0042,-88.20\n",
    "statements/2026-11/globex-card.csv": "Date,Payee,Debit,Credit\n2026-11-09,GLOBEX GROCERY,245.00,\n",
    "statements/2026-11/notes.txt": "VANDELAY PHARMACY 129.99\n",
    "budget-2027.toml": '[categories.groceries]\nmonthly = 410\n',
    "rules.toml": '[[rule]]\nmatch = "VANDELAY PHARMACY"\ncategory = "Health"\n',
    "ledger.jsonl": '{"description": "UMBRELLA STREAMING", "amount": "-12.75"}\n',
    "actuals/2026-11.json": '{"groceries": {"spent": "64.10"}}',
    "sheet-map.toml": '[[sources]]\nfile = "sheet-exports/wonka-tracker.csv"\nkind = "month-grid"\n',
    "sheet-exports/wonka-tracker.csv": "Month,Kramerica Pet Fund budget\n2026-11,$317.55\n",
}
SECRETS = ["umbrella-streaming", "globex-card", "INITECH FUEL", "GLOBEX GROCERY", "VANDELAY", "UMBRELLA STREAMING",
           "88.20", "245.00", "129.99", "12.75", "64.10", "ledger", "rules.toml", "sheet-map", "wonka-tracker",
           "Kramerica", "317.55"]
OWN_DOCUMENT = "2025/Thistledown 1098.pdf"


@pytest.fixture
def budget_workspace(workspace_home: Path) -> Path:
    """A workspace with one real document beside a budget folder full of made-up exports."""
    make_pdf(workspace_home / OWN_DOCUMENT, [["Form 1098 Mortgage Interest Statement 2025"]])
    for rel, content in BUDGET_FILES.items():
        path = workspace_home / workspace.BUDGET / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return workspace_home


def test_the_budget_folder_is_one_of_taxtraces_own():
    assert workspace.BUDGET == "budget" and workspace.BUDGET in workspace.DERIVED


def test_sources_leave_the_budget_folder_out(budget_workspace):
    assert [p.name for p in workspace.sources()] == ["2025"]


def test_the_budget_folder_alone_is_no_source(workspace_home):
    (workspace_home / workspace.BUDGET).mkdir(parents=True)
    (workspace_home / workspace.BUDGET / "export.csv").write_text("Date,Description,Amount\n")
    assert workspace.sources() == []


def test_the_cli_list_never_names_a_budget_file(budget_workspace, capsys):
    assert cli.main(["list"]) == 0
    out = printed(capsys)
    assert "2025/" in out
    assert not [s for s in SECRETS if s in out]


def test_the_chat_never_lists_or_sends_a_budget_file(budget_workspace):
    for masked in (False, True):
        listed = chat.inventory([], masked=masked)
        assert not [s for s in SECRETS if s in listed]
    assert "Thistledown" in chat.inventory([], masked=False)


def test_the_page_and_the_review_never_hold_a_budget_file(budget_workspace):
    assert [d.name for d in review.documents()] == ["Thistledown 1098.pdf"]
    blob = json.dumps(web.overview())
    assert "Thistledown" in blob and not [s for s in SECRETS if s in blob]


def test_no_mcp_tool_returns_a_budget_file(budget_workspace):
    from test_mcp_tools import call

    outputs = [call(name) for name in ("get_status", "list_documents", "get_todo", "get_moves", "get_jobchange",
                                       "get_sales")]
    assert call("list_documents")["count"] == 1 and call("get_status")["documents"] == 1
    outputs += [call("get_document_outline", id=1), call("get_form_checks", form="1098", id=1),
                call("get_form_checks", form="1099"), call("get_form_checks", form="k1")]
    with pytest.raises(Exception, match="no document"):
        call("get_document_outline", id=2)
    blob = json.dumps(outputs)
    assert not [s for s in SECRETS if s in blob]
