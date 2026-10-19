"""taxtrace: prepare a US federal + state return from your own documents, every number traced to its source."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, redact, text, workspace


def cmd_redact(args: argparse.Namespace) -> int:
    """Write each document's layout with the values, names and places masked.

    Only the masked file names and counts are printed, never a document's own name or text, so the output is
    safe to show to whoever is helping with the layout.
    """
    docs = text.documents([Path(p) for p in args.paths])
    if not docs:
        print("no readable documents", file=sys.stderr)
        return 1
    out = workspace.outside_git(Path(args.out) if args.out else workspace.home() / "redacted")
    out.mkdir(parents=True, exist_ok=True)
    terms = workspace.redact_terms(Path(args.terms) if args.terms else None)
    for i, doc in enumerate(docs, 1):
        name = f"{i:02d}-{redact.redact(doc.stem, terms, bare_years=True).text}.txt"
        try:
            pages = text.pages(doc)
        except text.UnsupportedDocument as err:
            print(f"{name}: skipped, {err}")
            continue
        body, kept, masked = [], 0, 0
        for n, page in enumerate(pages, 1):
            r = redact.redact(page, terms)
            body.append(f"=== page {n} ===\n{r.text}")
            kept, masked = kept + r.words_kept, masked + r.words_masked
        (out / name).write_text("\n".join(body) + "\n")
        share = masked / (kept + masked) if kept + masked else 0.0
        print(f"{name}: {len(pages)} pages, {share:.0%} of words masked")
    print(f"wrote {len(docs)} files to {out}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="taxtrace", description=__doc__)
    ap.add_argument("--version", action="version", version=f"taxtrace {__version__}")
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("redact", help="mask documents down to their layout", description=cmd_redact.__doc__)
    p.add_argument("paths", nargs="+", help="documents or folders")
    p.add_argument("--out", help="folder for the masked text (default: <workspace>/redacted)")
    p.add_argument("--terms", help=f"extra words to mask, one per line (default: <workspace>/{workspace.TERMS_FILE})")
    p.set_defaults(func=cmd_redact)
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
