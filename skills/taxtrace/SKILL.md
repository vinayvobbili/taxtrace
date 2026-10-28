---
name: taxtrace
description: Look over a person's US tax return preparation from your agent with the taxtrace MCP server. It shows what is in their tax workspace (documents by tax year), which Form 1098, 1099-DIV, 1099-INT and K-1 readings passed their checks, what is still a question, and their money and tax to-do list by due date. Everything comes back masked (digits as #, names as *), so no amount, name or account number reaches you. Use when the user asks what is left to do on their taxes, which documents are in or read, whether their forms read cleanly, or what is due soon.
---

# taxtrace

taxtrace is an open-source tool (MIT, on PyPI) that prepares a US federal and state return from the user's own
documents, on their own computer, with every number traced to the page it came from. It files nothing. Its MCP
server lets you see the state of the user's workspace without seeing their data.

## What you can and can't see

The tools return **masked text only**. A `#` is a digit and a run of `*` a word that could identify someone (a
name, a street, a town); words from the IRS's own publications stay readable, and so do dates, counts and
pass/fail results. You never get an amount, name, ID, account number or the workspace's path.

taxtrace's own reading of the documents (PDFs, OCR, passwords from the Keychain) runs on the user's computer, and
the server only returns what is left after masking. It opens no locked document and never asks the Keychain, so
you can't trigger a password prompt. Don't guess what was masked. If a question needs the real values, say so:
the user can open the page (`taxtrace ui`, at http://taxtrace.localhost:8766/) or ask the model that runs on
their Mac.

## Setup (once)

If the `taxtrace` tools aren't available, set it up:

```
pipx install 'taxtrace[mcp]'      # or: pip install 'taxtrace[mcp]'
claude mcp add taxtrace -s user -e TAXTRACE_HOME=~/TaxData -- taxtrace-mcp
```

`TAXTRACE_HOME` is the workspace folder (default `~/TaxData`), outside any git repository. Without installing
first: `claude mcp add taxtrace -s user -e TAXTRACE_HOME=~/TaxData -- uvx --with 'mcp>=2.2' taxtrace mcp`.

Claude Desktop: add the server to `claude_desktop_config.json` (use the full path of `taxtrace-mcp`, such as
`~/.local/bin/taxtrace-mcp` for pipx, if the app can't find it), then restart the app:

```
{
  "mcpServers": {
    "taxtrace": {
      "command": "taxtrace-mcp",
      "env": { "TAXTRACE_HOME": "/Users/you/TaxData" }
    }
  }
}
```

To use this as a skill in Claude Desktop, zip the folder (`cd skills && python -m zipfile -c taxtrace-skill.zip
taxtrace`) and upload it under Settings, Capabilities, Skills. The MCP server above is what gives it its tools.

## The workflow

1. **Start with `get_status`.** It counts the tax years, folders and documents, how many were read, and whether a
   to-do list exists. A workspace that doesn't exist yet means nothing has been imported (`taxtrace import`).
2. **See the documents.** `list_documents` gives each one an id, with its folder and name masked, and whether
   taxtrace has read it; `only: "unread"` lists what is still to read. Ids change when documents are added, so
   list again after an import.
3. **See what a document holds.** `get_document_outline` lists a document's pages by masked heading, so you can
   tell which forms and worksheets it has. A locked PDF is reported as locked: the user reads it with
   `taxtrace`, which uses a password from their Keychain.
4. **Check the forms.** `get_form_checks` with `1098`, `1099` or `k1` says per form how many checks passed, which
   failed and what questions it leaves (box names and masked quotes). A failed check means a value to look at by
   hand, not that the return is wrong. Pass `id` to read one document; without it every PDF is read, which can
   take a while.
5. **See what is due.** `get_todo` lists the open items soonest first with real due dates and masked wording;
   `days` limits it to the overdue and the next N days. Summarize by group (overdue, today, week, later,
   undated) and say plainly that item wording is masked.

## Rules

- **Read-only.** Every tool only reads. You can't tick a to-do, import a document or file anything; the user does
  that in taxtrace. taxtrace never files a return.
- **Never try to unmask.** Don't ask the user to paste amounts or names to "fill in" the masked text, and don't
  guess a masked word from its length. Tell them what you need to know and where to look.
- **A judgment call is theirs.** An election, a repair or an improvement, which year something belongs to: lay out
  the options and what each needs, and leave the choice to them.
- **Name the rule.** For a tax rule, name the form, line, schedule or IRS publication and the tax year, and say
  what facts it turns on.
