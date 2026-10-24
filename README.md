# taxtrace

**Prepare a US federal and state return from your own documents, on your own machine, with every
number traced to the page it came from.**

taxtrace does not file anything. It reads a folder of your documents (W-2s, 1099s, 1098s, property
manager statements, receipts, foreign bank statements, last year's return) and produces an entry sheet
you type into consumer tax software, an FBAR account list, and a list of questions for you: anything
it couldn't settle from the documents alone.

Three rules hold everywhere:

1. **Nothing is guessed.** Every value carries the file, the page and the exact text it was read from,
   and a deterministic check rejects any value whose quote isn't on that page.
2. **Your documents never leave your machine.** Where a language model reads them (sorting documents,
   reading messy receipts), it is a local MLX model on your Mac. The chat can use a cloud model, which
   only ever sees masked text (see [Chat](#chat)).
3. **Nothing is decided silently.** A receipt that could be a repair or an improvement, a missing
   1099, a rate choice: each is a question for you, with the evidence next to it.

## Status

Early. What works today:

- `taxtrace redact`: masks a document down to its layout, so a layout can be studied (by a person or
  an AI assistant helping write a parser) without its values, names or places. Every digit becomes `#`,
  and every word the IRS's own publications don't use in lowercase becomes `*`s, so names, streets
  and towns go without anyone listing them.
- `taxtrace import`, `outline` and `unlock`: sort a preparer's export into the workspace, list the forms
  in each document, and check passwords kept in the Keychain.
- `taxtrace ui`: the workspace in the browser, with a chat (see [Chat](#chat)).

Planned, in order: reading a prior-year return's carryforwards (depreciation schedule, Form 8582
passive-loss carryovers), Schedule E, the foreign side (interest at Treasury rates, foreign tax
credit, FBAR, Form 8938 check), the entry sheet, and a year-over-year check.

## Install

```bash
pip install -e ".[dev]"
```

## Use

```bash
taxtrace import ~/Downloads/portal-export.zip  # filed returns to prior-returns/, the rest by tax year
taxtrace redact ~/TaxData/prior-returns        # writes ~/TaxData/redacted/*.txt
```

`taxtrace outline <files>` lists each page's masked heading: which forms a document holds, in order.
A scanned PDF (pictures of pages, no text) is read through [ocrmypdf](https://ocrmypdf.readthedocs.io)
on your machine (`brew install ocrmypdf`), once: the searchable copy is kept under the original's sha256
in `<workspace>/ocr-cache`, so the text values are quoted from never shifts.

`import` takes a folder or a zip, such as a tax preparer's portal export with one folder per year. It
skips identity documents (driver's licenses, Social Security cards, passports) and anything already
imported, and records every file it places, with its sha256, in `imports.jsonl`.

Your documents and everything derived from them live in a workspace folder, `~/TaxData` or
`$TAXTRACE_HOME`, which taxtrace refuses to place inside a git repository. Names that are also
ordinary words (Will, Grace) go in `<workspace>/redact-terms.txt`, one per line.

A password-protected PDF is read with a password kept in the macOS Keychain, never in a file or on a
command line. One `default` entry covers every return that shares a password; an entry under a file's
name wins for that file. `security` asks for it without echoing, and `-T ""` trusts no app, so macOS
asks you (Allow / Deny) each time anything reads it, taxtrace included:

```bash
security add-generic-password -s taxtrace -a default -T "" -w
security add-generic-password -s taxtrace -a "2024 Return.pdf" -T "" -w   # just this file
```

Click **Allow**, not **Always Allow**: that would add the reader to the trusted list and end the prompts.
taxtrace reads each entry at most once per command, so a folder of returns sharing the `default` password
costs one prompt. `taxtrace unlock` says which entry opens each locked file, and how each stored password
is shaped (`aaaa99999`), never what it is.

`redact`, `outline` and `unlock` with no paths read the whole workspace, leaving out what taxtrace wrote
there itself (`redacted/`, `ocr-cache/`).

## Chat

```bash
pip install -e ".[chat,local]"   # Claude's SDK, and the model that runs on your Mac
taxtrace ui                      # opens http://taxtrace.localhost:8766/
```

The page lists your workspace by folder and has a chat for tax rules, forms and what a document is for.
It answers with the first model in `--models` (default `claude,agy,local`) that can, and moves on to the
next when one can't (no key, quota used up, not installed):

- `claude`: Anthropic's API, with `ANTHROPIC_API_KEY` or a Keychain item holding the key (`--keychain`,
  default `anthropic`).
- `agy`: Google's [Antigravity CLI](https://antigravity.google/docs/cli), on its subscription, run in an
  empty folder.
- `local`: an MLX model on your Mac.

Claude and agy only ever see masked text. Every message, and the list of your documents, goes through the
same masking as `taxtrace redact` first: digits become `#`, and words outside the IRS's own vocabulary
become `*`s. A question with an amount in it, or a name from `redact-terms.txt`, isn't sent to them at all:
the model on your Mac answers it, and the page says why. Under each question a cloud model answered, the
page shows exactly what it was sent. The chat reads only the document list and what you type: it can't open
a document, change a file or file anything.

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

## Development

```bash
git config core.hooksPath .githooks   # once: every push first runs scripts/check
scripts/check                         # ruff + pytest on Python 3.10 and 3.13, as CI does
python scripts/build_vocab.py         # rebuild the redaction vocabulary from IRS publications
```

Set `PRE_PUSH_AUDIT` to a command that scans a repository for personal data and exits non-zero on a
finding, and `scripts/check` runs it too, with the repository's path appended.

Every fixture is invented: no real person, place or amount appears in this repository.
