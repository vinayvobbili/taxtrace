"""MCP server exposing taxtrace to an AI assistant: the workspace, its documents and its to-do list, masked.

Every tool is read-only and returns masked text only (see review.py): digits are #, words that could identify
someone are *s. A client that is a cloud model never sees an amount, name, ID or account number, and taxtrace's own
reading of the documents runs on this computer.
"""

from __future__ import annotations

from typing import Annotated, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__, review, workspace

server = MCPServer(
    "taxtrace",
    instructions=(
        "Reads a person's tax workspace (their own documents, folder by folder, kept on their computer) and gives "
        "back only MASKED text: # stands for a digit and a run of * for a word that could identify someone (a name, "
        "a street, a town). No tool returns an amount, name, ID or account number; never guess what was masked, and "
        "tell the person to open the page (taxtrace ui) or ask the local model for the real values. "
        "get_status counts the tax years, folders and documents, and how many were read; list_documents names "
        "each document (masked) with an id; get_document_outline lists a document's pages by masked heading, which "
        "forms it holds; get_form_checks says which Form 1098, 1099-DIV, 1099-INT and K-1 readings passed their "
        "checks (every value traced to its page) and which failed or raised a question; get_todo lists the person's "
        "money and tax to-dos by due date (the dates are real, the wording masked). "
        "taxtrace never files anything and these tools change nothing."
    ),
    version=__version__,
    website_url="https://github.com/vinayvobbili/taxtrace",
)

READ = ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)

Form = Literal["1098", "1099", "k1"]
Only = Literal["all", "read", "unread"]

DocId = Annotated[int, Field(ge=1, description=(
    "The document's id from list_documents (its place in the workspace, from 1). Ids change when documents are "
    "added or removed, so list again after an import."))]


def _call(fn, *args, **kwargs):
    """Run a review function; a ToolError, so the model reads what to fix instead of a bare failure."""
    try:
        return fn(*args, **kwargs)
    except (review.ReviewError, workspace.InsideGitRepo) as e:
        raise ToolError(str(e)) from None


@server.tool(annotations=READ)
def get_status() -> dict:
    """What the person's workspace holds, as counts: tax years (folders named for one), each folder's number of
    documents, how many documents taxtrace has read, how many files it saved per kind of reading, and whether a
    to-do list exists. Names are masked. Start here; for the documents themselves use list_documents, for the
    to-dos use get_todo."""
    return _call(review.status)


@server.tool(annotations=READ)
def list_documents(
    only: Annotated[Only, Field(description=(
        "all (default), read (taxtrace has saved something from it) or unread (nothing saved yet: the ones still "
        "to read)."))] = "all",
) -> dict:
    """The workspace's documents, each with an id, its folder and file name (masked), its kind (pdf, csv, ...) and
    whether it was read. Nothing is opened, so no password is asked for. The id is what get_document_outline and
    get_form_checks take. For counts only use get_status."""
    rows = [r for r in _call(review.listing) if only == "all" or r["read"] == (only == "read")]
    return {"count": len(rows), "documents": rows}


@server.tool(annotations=READ)
def get_document_outline(
    id: DocId,
    start: Annotated[int, Field(ge=1, description="The first page to list (default 1).")] = 1,
    limit: Annotated[int, Field(ge=1, le=review.MAX_PAGES, description=(
        "How many pages to list from start (default 40, at most 200)."))] = 40,
    lines: Annotated[int, Field(ge=1, le=5, description=(
        "How many of each page's first lines to show, masked (default 2: on a tax form they name the form)."))] = 2,
) -> dict:
    """A document's pages, each with its first lines masked: which forms and worksheets it holds, and in what
    order. A password-protected document is reported as locked, not opened (taxtrace's own commands read it with
    a password from the Keychain). To see how the forms in it checked out use get_form_checks; to find the id,
    list_documents."""
    return _call(review.outline, id, start, limit, lines)


@server.tool(annotations=READ)
def get_form_checks(
    form: Annotated[Form, Field(description=(
        "Which form to read: 1098 (mortgage interest), 1099 (the 1099-DIVs and 1099-INTs on a broker's "
        "statement) or k1 (the federal Schedule K-1 face)."))],
    id: Annotated[int | None, Field(ge=1, description=(
        "Only this document (its id from list_documents). Omit to read every PDF in the workspace, which "
        "can take a while."))] = None,
) -> dict:
    """Read the forms of one kind in the workspace's PDFs and report how their checks came out, never a value: per
    form its document id, page, tax year, how many checks passed of how many, the ones that failed and the
    questions it leaves the person (box names and masked quotes). Every value taxtrace reads is traced to its page
    and rejected if its text isn't there, so a failed check means a value to look at by hand. Locked documents
    are skipped and counted. For a document's other pages use get_document_outline."""
    return _call(review.checks, form, id)


@server.tool(annotations=READ)
def get_todo(
    days: Annotated[int | None, Field(ge=0, le=366, description=(
        "Only the overdue items and those due within this many days from today. Omit for every open item, "
        "soonest first, undated last."))] = None,
) -> dict:
    """The person's open money and tax to-dos from todo.md in their workspace, soonest first: section, due date,
    days left, group (overdue, today, week, later, undated), and the text, notes and sub-tasks masked (the dates
    are real; the wording is masked, so ask the person what an item says if it matters). Nothing is changed:
    the person ticks items on the taxtrace page. For the documents use list_documents."""
    return _call(review.todo_list, days)


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
