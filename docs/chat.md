# Chat and the browser page

## Chat

```bash
pip install -e ".[chat,local]"   # Claude's SDK, and the model that runs on your Mac
taxtrace ui                      # opens http://taxtrace.localhost:8766/
```

The page lists your workspace by folder, brings documents in (see [Import](#import)) and has a chat for tax rules, forms and what a document is for.
It answers with the first model in `--models` (default `claude,agy,local`) that can, and moves on to the
next when one can't (no key, quota used up, not installed):

- `claude`: Anthropic's API, with `ANTHROPIC_API_KEY` or a Keychain item holding the key (`--keychain`,
  default `anthropic`).
- `agy`: Google's [Antigravity CLI](https://antigravity.google/docs/cli), on its subscription, run in an
  empty folder.
- `local`: an AI model running on your Mac (MLX is Apple's software for that), served on this computer only.

Claude and agy only ever see masked text. Every message, and the list of your documents, goes through the
same masking as `taxtrace redact` first: digits become `#`, and words outside the IRS's own vocabulary
become `*`s. A question with an amount in it, or a name from `redact-terms.txt`, isn't sent to them at all:
the model on your Mac answers it, and the page says why. Under each question a cloud model answered, the
page shows exactly what it was sent. The chat reads only the document list and what you type: it can't open
a document, change a file or file anything.

## Screens

The page has a tab for each screen, in the header (and at `#import` and so on in the address): **Overview** (the
workspace by folder, the to-do list, the year's moves and the chat), **Import** and **Entry sheet**. Standard, Wide
and Full set how much of a wide monitor the page uses, and the ◐ button picks light, dark or the computer's setting;
both are kept in the browser.

### Import

Pick files, pick a folder, or drop files, folders or a preparer's zip on the box. The page uploads each one to the
server on your computer (`/api/import`, with the page's token: nothing goes anywhere else) and shows what taxtrace
makes of it, a card per file:

- **Recognised**: the form (W-2, 1099-INT, K-1, 1098, a filed return...), the tax year and where it goes.
- **Check it**: it would be filed, but its name doesn't say which form it is, or has no year, so it waits in
  `unsorted/`. Choosing the tax year above the cards (the folder's name or the file's own gives it otherwise) moves
  everything that isn't a filed return into that year.
- **Skipped**: nothing copied, and the card says why: an identity document, a copy already imported (same bytes), a web
  page saved as .pdf.

Nothing is filed until you press **File them**. It files exactly as `taxtrace import` does, with the same folders, the
same skips and a line in `imports.jsonl` for each file. The form and the year come from the file's name and the folder
it sat in (nothing is opened); the owner is a name from `redact-terms.txt` found in the file's name. An upload is
staged in a temporary folder for the moment it takes, and the workspace stays outside any git repository.

### Entry sheet

The year's `taxtrace entry` sheet as tables, one card per section (the wages on a W-2, a 1099's boxes, a K-1, the
rental, deductions, payments and the checks the filing site should come to). Each row has its value, a status and the
document it came from:

- **Ready**: read off a final form, or worked out from them.
- **Estimate**: it can still change (the year isn't over, a statement is missing, or a pay stub stands in for the W-2).
- **Missing**: nothing has been read for it yet; the row names the command that fills it.

The numbers on top count each status and the forms still to come (what came last year and hasn't yet, and what
`--expect` added); the year picker covers every year with documents or saved results, and *Estimates and missing*
hides the rows that are ready. Under a section that isn't finished, and under each form still to come, the page
links the items of your `todo.md` that mention it (by its form or its names: Initech, 1099, wages), and opens the
to-do list at that item; with none, it links to the list. Questions the other commands left open and what you type
yourself (names, Social Security numbers, bank numbers) are never on it.

The screen only reads what the other commands saved: it opens no document and writes no file. Run
`taxtrace entry --year 2026` after documents are read to write the sheet to `<workspace>/entry/2026.txt`, and `--expect`
to add a form to wait for; the page shows the same sheet. It shows the amounts, on this computer only, as `moves` does.

### Always on (macOS)

An installed app (the page added to your Dock from the browser) only works while the server is running.
To start it at login and restart it if it stops:

```bash
taxtrace service install     # same --port, --models and --keychain as `ui`
taxtrace service status      # running or not, the address, the log
taxtrace service uninstall
```

Run `install` from the shell where `TAXTRACE_HOME` is set: a login item doesn't read your shell profile,
so install writes that workspace path, and a `PATH` that finds `agy` and Homebrew's `ocrmypdf`, into
`~/Library/LaunchAgents/io.github.taxtrace.ui.plist`. No key or password goes in it; Claude's key is still
read from the Keychain. The log is `~/Library/Logs/taxtrace-ui.log`.

To install the page as an app, open http://taxtrace.localhost:8766/ in Chrome and click the install icon at
the right of the address bar (or ⋮ → Cast, save and share → Install page as app). It gets its own window and
Dock icon. `python scripts/make_icons.py` rebuilds the app's PNG icons after an SVG changes.
