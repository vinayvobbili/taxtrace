# Install, workspace and documents

## Install

```bash
pip install -e ".[dev,mcp]"
```

`taxtrace[chat]` adds the chat's Claude SDK and `taxtrace[mcp]` an [MCP server](https://github.com/vinayvobbili/taxtrace/blob/main/docs/mcp.md#mcp-server-and-agent-skill). The
chat's model on your own computer is whatever OpenAI-compatible server answers at `http://127.0.0.1:8010/v1`
(`vllm-mlx serve <model> --port 8010`, `mlx_lm.server`, LM Studio; `LOCAL_LLM_URL` points elsewhere on the same
computer). taxtrace never loads a model itself, so one server can hold a single copy for every program, and it
refuses a server on another machine, since that model sees your values unmasked.

## Use

```bash
taxtrace import ~/Downloads/portal-export.zip  # filed returns to prior-returns/, the rest by tax year
taxtrace redact ~/TaxData/prior-returns        # writes ~/TaxData/redacted/*.txt
```

A path that isn't one from where you are is looked up in the workspace: `taxtrace k1 2025` reads
`<workspace>/2025`.

`taxtrace outline <files>` lists each page's masked heading: which forms a document holds, in order (`--match
'1116|4562'` lists only the pages naming them). The heading skips scanner and barcode noise (lines of `#`, `*` and
punctuation), and the outline ends with the pages that repeat earlier ones (`p5-p8 repeat p1-p4`, allowing small OCR
differences). A scanned page that reads as garbage (a sheet fed upside down) is read again turned 180 degrees and kept
if that reads better, in `outline`, `redact` and every other command; the outline marks it (`p8 (rotated)`).
`taxtrace words <pdf> --page 2 --rows` shows a page's words, masked,
with where each one sits (`--x 300:450` and `--top 70:240` narrow it to a region): the geometry of a printed form, for
writing a reader of it. `--marks` adds the drawn shapes, so a checkbox ticked with a drawn mark shows. `--page
19-20,69`, `--page all` and several files take one run, so files that share a Keychain entry cost one approval.
`taxtrace show 'prior-returns/2025*' --page 19` opens a document in Chrome at a page, for you to read yourself.
A scanned PDF (pictures of pages, no text) is read through [ocrmypdf](https://ocrmypdf.readthedocs.io)
on your machine (`brew install ocrmypdf`), once: the searchable copy is kept under the original's sha256
in `<workspace>/ocr-cache`, so the text values are quoted from never shifts. A picture (.jpg, .png: a
phone's photo or screenshot of a statement, as one arrives in a chat) goes the same way. A chat app shrinks
what it sends, though, and a blurred table's rows may not read: `bank` then saves nothing for that account,
and a PDF from the bank (or the picture sent as a document, uncompressed) is the better copy.

`import` takes a folder or a zip, such as a tax preparer's portal export with one folder per year. It
skips identity documents (driver's licenses, Social Security cards, passports) and anything already
imported, and records every file it places, with its sha256, in `imports.jsonl`.

Your documents and everything derived from them live in a workspace folder, `~/TaxData` or
`$TAXTRACE_HOME`, which taxtrace refuses to place inside a git repository. Names that are also
ordinary words (Will, Grace) go in `<workspace>/redact-terms.txt`, one per line.

A password-protected PDF is read with a password kept in the macOS Keychain, never in a file or on a
command line. One `default` entry covers every return that shares a password; an entry under a file's
name wins for that file, and one under the name before its first `-` covers a bank's monthly statements
(`quillbank` for `quillbank-4410-2026-01.pdf`, `quillbank-4410-2026-02.pdf`, ...). `security` asks for it
without echoing, and `-T ""` trusts no app, so macOS asks you (Allow / Deny) each time anything reads it,
taxtrace included:

```bash
security add-generic-password -s taxtrace -a default -T "" -w
security add-generic-password -s taxtrace -a "2024 Return.pdf" -T "" -w   # just this file
security add-generic-password -s taxtrace -a quillbank -T "" -w           # quillbank-*.pdf
```

Click **Allow**, not **Always Allow**: that would add the reader to the trusted list and end the prompts.

That prompt only takes the typed password. To approve each read with Apple Watch or Touch ID instead:

```bash
taxtrace keychain setup                              # the default entry and the chat's key
taxtrace keychain setup --account "2024 Return.pdf"  # and a file's own entry
```

`setup` builds a small helper (`taxtrace/macos/keychain_gate.swift`, compiled with the Xcode command line tools)
and moves each entry over to it. macOS asks for the entry the old way one last time, and the secret is never
retyped or shown. From then on the entry trusts only the helper, and the helper releases it only after macOS's
own approval: Apple Watch, Touch ID, or the password where neither is set up. Every read is still yours to allow.
Only the entries `setup` moved go through the helper; any other is read the classic way, with its one prompt. If
you deny the classic prompt during `setup`, it says so and leaves that entry as it was: run `setup` again.
Once the helper is built, store a new password with `taxtrace keychain store <name>` (a file's name, its issuer's
such as `quillbank`, or `default`): `security` asks for it unechoed, then the helper moves it over the way `setup`
does, with one classic prompt. An entry stored with a bare `security add-generic-password -T <helper>` stays
`security`'s: macOS adds its own prompt to every read the helper makes, on top of Apple Watch or Touch ID.
taxtrace reads each entry at most once per command, so a folder of returns sharing the `default` password
costs one prompt. `taxtrace unlock` says which entry opens each locked file, and how each stored password
is shaped (`aaaa99999`), never what it is. A password pdfminer turns down is tried once more with qpdf
(`brew install qpdf`), which gets it on stdin and decrypts a copy into a temporary folder for the read: when qpdf
turns it down too, the stored password is wrong, not the reader.

Another tool can read an entry `setup` moved, such as an API key it shares with the chat, without the entry
trusting that tool too:

```bash
taxtrace keychain read anthropic --for jobwatch   # the secret on stdout, once approved
```

The prompt names the item and the tool. The secret goes to the program that runs the command, never to a
terminal, and an entry `setup` didn't move isn't read this way.

A tool that reads the key unattended (a background service after a restart) has nobody there to approve, and the
approval times out. For a key that guards little, such as one with a spend limit, `taxtrace keychain release
anthropic` moves it back for good: one approval, then `security` saves it again (the secret on its stdin, never
in a command line) and it reads without any prompt, taxtrace's chat included. The document passwords can't be
released.

When a read asks for the password instead of Apple Watch or Touch ID (a Watch out of range, asleep or locked
falls back to it), `taxtrace keychain check` says which ways macOS offers right now and why not, and
`check --try` shows one Watch / Touch ID prompt and prints what came back. Neither rebuilds the helper or touches
an entry.

Besides PDFs and text files (.txt, .csv), Word documents (.docx: one line per paragraph and per table row) and
Excel workbooks (.xlsx: a page per sheet, one line per row) are read, with Python's own zip and XML modules. A
password-protected Office file isn't read: save an unprotected copy into the workspace.

`redact`, `outline` and `unlock` with no paths read the whole workspace, leaving out what taxtrace wrote
there itself (`redacted/`, `ocr-cache/`).
