"""taxtrace: prepare a US federal + state return from your own documents, every number traced to its source."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, importer, redact, text, workspace


def cmd_redact(args: argparse.Namespace) -> int:
    """Write each document's layout with the values, names and places masked.

    Only the masked file names and counts are printed, never a document's own name or text, so the output is
    safe to show to whoever is helping with the layout.
    """
    docs = _documents(args)
    if not docs:
        print("no readable documents", file=sys.stderr)
        return 1
    out = workspace.outside_git(Path(args.out) if args.out else workspace.home() / workspace.REDACTED)
    out.mkdir(parents=True, exist_ok=True)
    terms = workspace.redact_terms(Path(args.terms) if args.terms else None)
    written = 0
    for i, doc in enumerate(docs, 1):
        name = f"{i:02d}-{redact.redact(doc.stem, terms, bare_years=True).text}.txt"
        try:
            pages = _open(doc)
        except text.Locked as err:
            print(f"{name}: skipped, {err}; store its password with: {workspace.keychain_hint()}")
            continue
        except text.UnsupportedDocument as err:
            print(f"{name}: skipped, {err}")
            continue
        body, kept, masked = [], 0, 0
        for n, page in enumerate(pages, 1):
            r = redact.redact(page, terms)
            body.append(f"=== page {n} ===\n{r.text}")
            kept, masked = kept + r.words_kept, masked + r.words_masked
        (out / name).write_text("\n".join(body) + "\n")
        written += 1
        share = masked / (kept + masked) if kept + masked else 0.0
        print(f"{name}: {len(pages)} pages, {share:.0%} of words masked")
    print(f"wrote {written} of {len(docs)} files to {out}")
    return 0


def _documents(args: argparse.Namespace) -> list[Path]:
    """The documents named on the command line, or with none named, every one in the workspace."""
    return text.documents([Path(p) for p in args.paths] or workspace.sources())


def _open(doc: Path) -> list[str]:
    """A document's pages, trying each password the Keychain holds for it when it's locked."""
    def passwords():
        yield None  # most files aren't locked: the Keychain is asked only when one is
        yield from workspace.pdf_passwords(doc)

    failure = text.Locked("password-protected")
    for password in passwords():
        try:
            return text.pages(doc, password, ocr_cache=workspace.ocr_cache())
        except text.Locked as err:
            failure = err  # the last says best why: no password stored, or none that opened it
    raise failure


def cmd_outline(args: argparse.Namespace) -> int:
    """Each page's first lines, masked: which forms and worksheets a document holds, and in what order."""
    terms = workspace.redact_terms()
    for doc in _documents(args):
        name = redact.redact(doc.name, terms, bare_years=True).text
        try:
            pages = _open(doc)
        except text.UnsupportedDocument as err:
            print(f"{name}: skipped, {err}")
            continue
        print(f"{name}: {len(pages)} pages")
        for n, page in enumerate(pages, 1):
            heads = [redact.redact(h, terms).text for h in text.headings(page, args.lines)]
            print(f"  p{n}: {' | '.join(heads) if heads else '(blank)'}")
    return 0


def cmd_unlock(args: argparse.Namespace) -> int:
    """Say which Keychain entry opens each locked PDF, and what each stored password looks like (never what it is)."""
    docs = _documents(args)
    terms = workspace.redact_terms()
    shown: set[str] = set()
    failed = 0
    for doc in docs:
        name = redact.redact(doc.name, terms, bare_years=True).text
        try:
            text.pages(doc)
            print(f"{name}: not locked")
            continue
        except text.Locked:
            pass
        except text.UnsupportedDocument:
            continue
        entries = workspace.keychain_entries(doc)
        opened = None
        for account, password in entries:
            if account not in shown:
                shown.add(account)
                print(f"  Keychain entry '{redact.redact(account, terms, bare_years=True).text}': "
                      f"{workspace.shape(password)}")
            try:
                text.pages(doc, password)
                opened = account
                break
            except text.Locked:
                continue
        if opened:
            print(f"{name}: opens with '{redact.redact(opened, terms, bare_years=True).text}'")
        else:
            failed += 1
            why = "no Keychain entry" if not entries else "no stored password opens it"
            print(f"{name}: locked, {why}; store one with: {workspace.keychain_hint()}")
    return 1 if failed else 0


def cmd_import(args: argparse.Namespace) -> int:
    """Copy a folder or zip of documents into the workspace: filed returns to prior-returns/, the rest by tax year."""
    home = workspace.outside_git(workspace.home())
    try:
        placed = importer.import_documents(Path(args.source), home, dry_run=args.dry_run)
    except ValueError as err:
        print(err, file=sys.stderr)
        return 1
    for p in placed:
        print(f"{p.dest or '-':<45} {p.source}" + ("" if p.dest else f"  ({p.reason})"))
    copied = [p for p in placed if p.dest]
    verb = "would copy" if args.dry_run else "copied"
    print(f"{verb} {len(copied)} of {len(placed)} files into {home}")
    return 0


def cmd_ui(args: argparse.Namespace) -> int:
    """Open the workspace and a chat in the browser, at http://taxtrace.localhost:8766/."""
    from . import chat, web

    order = tuple(b.strip() for b in args.models.split(",") if b.strip())
    if unknown := [b for b in order if b not in chat.BACKENDS]:
        print(f"unknown model {', '.join(unknown)}: choose from {', '.join(chat.BACKENDS)}", file=sys.stderr)
        return 2
    server = web.serve(args.port, open_browser=not args.no_open, settings=chat.Settings(order=order,
                                                                                        keychain=args.keychain))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


PATHS_HELP = "documents or folders (default: the whole workspace)"


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="taxtrace", description=__doc__)
    ap.add_argument("--version", action="version", version=f"taxtrace {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("redact", help="mask documents down to their layout", description=cmd_redact.__doc__)
    p.add_argument("paths", nargs="*", help=PATHS_HELP)
    p.add_argument("--out", help="folder for the masked text (default: <workspace>/redacted)")
    p.add_argument("--terms", help=f"extra words to mask, one per line (default: <workspace>/{workspace.TERMS_FILE})")
    p.set_defaults(func=cmd_redact)
    p = sub.add_parser("import", help="copy documents into the workspace, sorted by tax year",
                       description=cmd_import.__doc__)
    p.add_argument("source", help="a folder, or a zip such as a tax preparer's portal export")
    p.add_argument("--dry-run", action="store_true", help="show where each file would go, copy nothing")
    p.set_defaults(func=cmd_import)
    p = sub.add_parser("unlock", help="check which stored password opens each locked PDF",
                       description=cmd_unlock.__doc__)
    p.add_argument("paths", nargs="*", help=PATHS_HELP)
    p.set_defaults(func=cmd_unlock)
    p = sub.add_parser("outline", help="list each page's masked heading", description=cmd_outline.__doc__)
    p.add_argument("paths", nargs="*", help=PATHS_HELP)
    p.add_argument("--lines", type=int, default=2, help="lines per page (default: 2)")
    p.set_defaults(func=cmd_outline)
    p = sub.add_parser("ui", help="open the workspace and a chat in the browser", description=cmd_ui.__doc__)
    p.add_argument("--port", type=int, default=8766, help="port on 127.0.0.1 (default: 8766)")
    p.add_argument("--no-open", action="store_true", help="don't open the browser")
    p.add_argument("--models", default="claude,agy,local",
                   help="the chat's models, tried in this order (default: claude,agy,local)")
    p.add_argument("--keychain", default="anthropic",
                   help="Keychain item with the Anthropic API key, if ANTHROPIC_API_KEY isn't set (default: anthropic)")
    p.set_defaults(func=cmd_ui)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except workspace.InsideGitRepo as err:
        print(err, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
