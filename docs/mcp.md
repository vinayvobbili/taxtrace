# MCP server and agent skill

## MCP server and agent skill

`taxtrace-mcp` lets Claude Code, Claude Desktop or any MCP client (MCP, the Model Context Protocol, is the standard way an AI assistant calls tools) look at your workspace: what's in it, what
each document is, which forms read cleanly, and what's on your to-do list. It returns **masked text only**.

```bash
pipx install 'taxtrace[mcp]'      # or: pip install 'taxtrace[mcp]'
claude mcp add taxtrace -s user -e TAXTRACE_HOME=~/TaxData -- taxtrace-mcp
```

Without installing first, [uv](https://docs.astral.sh/uv/) can fetch and run it: `claude mcp add taxtrace -s user -e
TAXTRACE_HOME=~/TaxData -- uvx --with 'mcp>=2.2' taxtrace mcp`. `taxtrace mcp` runs the same server as
`taxtrace-mcp`. For Claude Desktop, add this to `claude_desktop_config.json` (use the full path of `taxtrace-mcp`
if `which taxtrace-mcp` isn't on the app's `PATH`, such as `~/.local/bin/taxtrace-mcp` for pipx):

```json
{
  "mcpServers": {
    "taxtrace": {
      "command": "taxtrace-mcp",
      "env": { "TAXTRACE_HOME": "/Users/you/TaxData" }
    }
  }
}
```

| Tool | What it gives |
| --- | --- |
| `get_status` | Counts: tax years, folders, documents, how many were read, what was saved from them, whether a to-do list exists |
| `list_documents` | Each document's id, folder and name (masked), kind, and whether it was read; filter to read or unread |
| `get_document_outline` | A document's pages by masked heading: which forms it holds, in order (a locked PDF is reported, not opened) |
| `get_form_checks` | Per Form 1098, 1099-DIV or 1099-INT, or K-1: checks passed of total, the ones that failed, the questions left |
| `get_todo` | `todo.md` by due date: section, date, days left, group, and masked text, notes and sub-tasks |

Every tool is read-only. The masking is the one the chat uses for a cloud model and `taxtrace redact` writes:
digits become `#`, words outside the IRS's own vocabulary become `*`s, and names in `redact-terms.txt` go first.
No tool returns an amount, name, ID, account number or the workspace's path; dates, counts and pass/fail results
stay. A locked document is never opened and the Keychain is never asked, so a client can't cause a prompt or reach
a password. taxtrace reads your documents on your machine, as it always does; the client only gets what is left
after masking. A test builds a workspace full of made-up amounts and names and checks that none of them appear in
any tool's output.

[skills/taxtrace/SKILL.md](https://github.com/vinayvobbili/taxtrace/blob/main/skills/taxtrace/SKILL.md) is an agent skill that tells an assistant when and how to use
these tools, and that it only ever sees masked text. Copy the folder into `~/.claude/skills/`, or zip it to upload
to Claude Desktop (Settings, Capabilities, Skills): `cd skills && python -m zipfile -c taxtrace-skill.zip taxtrace`.
It's listed in the [MCP Registry](https://registry.modelcontextprotocol.io) as `io.github.vinayvobbili/taxtrace`
once released.
