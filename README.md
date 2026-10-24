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
2. **Nothing leaves your machine.** Where a language model helps (sorting documents, reading messy
   receipts), it is a local MLX model on your Mac. No tax document goes to a cloud API.
3. **Nothing is decided silently.** A receipt that could be a repair or an improvement, a missing
   1099, a rate choice: each is a question for you, with the evidence next to it.

## Status

Early. What works today:

- `taxtrace redact`: masks a document down to its layout, so a layout can be studied (by a person or
  an AI assistant helping write a parser) without its values, names or places. Every digit becomes `#`,
  and every word the IRS's own publications don't use in lowercase becomes `*`s, so names, streets
  and towns go without anyone listing them.

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

`import` takes a folder or a zip, such as a tax preparer's portal export with one folder per year. It
skips identity documents (driver's licenses, Social Security cards, passports) and anything already
imported, and records every file it places, with its sha256, in `imports.jsonl`.

Your documents and everything derived from them live in a workspace folder, `~/TaxData` or
`$TAXTRACE_HOME`, which taxtrace refuses to place inside a git repository. Names that are also
ordinary words (Will, Grace) go in `<workspace>/redact-terms.txt`, one per line.

A password-protected PDF is read with a password kept in the macOS Keychain, never in a file or on a
command line. One `default` entry covers every return that shares a password; an entry under a file's
name wins for that file. `security` asks for it without echoing:

```bash
security add-generic-password -s taxtrace -a default -w
security add-generic-password -s taxtrace -a "2024 Return.pdf" -w   # just this file
```

## Development

```bash
python -m pytest -q && ruff check .
python scripts/build_vocab.py    # rebuild the redaction vocabulary from IRS publications
```

Every fixture is invented: no real person, place or amount appears in this repository.
