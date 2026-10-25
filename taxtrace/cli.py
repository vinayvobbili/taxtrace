"""taxtrace: prepare a US federal + state return from your own documents, every number traced to its source."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal
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
    """The documents named on the command line, or with none named, every one in the workspace.

    A name that isn't a path from here is looked up in the workspace: `2025` is <workspace>/2025.
    """
    home = workspace.home()
    paths = [path if path.exists() or not (home / path).exists() else home / path for path in map(Path, args.paths)]
    return text.documents(paths or workspace.sources())


def _open(doc: Path) -> list[str]:
    """A document's pages, trying each password the Keychain holds for it when it's locked."""
    return _unlocked(doc)[0]


def _unlocked(doc: Path, keychain: bool = True) -> tuple[list[str], str | None]:
    """A document's pages and the password that opened them (None: not locked). With `keychain` off, a locked
    document is skipped (raises `text.Locked`) without asking for its stored password."""
    def passwords():
        yield None  # most files aren't locked: the Keychain is asked only when one is
        if keychain:
            yield from workspace.pdf_passwords(doc)

    failure = text.Locked("password-protected")
    for password in passwords():
        try:
            return text.pages(doc, password, ocr_cache=workspace.ocr_cache()), password
        except text.Locked as err:
            failure = err  # the last says best why: no password stored, or none that opened it
    from . import gate

    if {(workspace.KEYCHAIN_SERVICE, a) for a in (doc.name, workspace.KEYCHAIN_DEFAULT)} & gate.refused:
        raise text.Locked(f"{failure}; the Keychain read wasn't approved (Apple Watch, Touch ID or password)")
    raise failure


def cmd_list(args: argparse.Namespace) -> int:
    """The documents' names, masked, by folder: what's there to read, without opening anything (no Keychain ask)."""
    terms = workspace.redact_terms()
    home = workspace.home()
    for doc in _documents(args):
        try:
            where = doc.parent.relative_to(home).as_posix()
        except ValueError:
            where = ""
        name = redact.redact(doc.name, terms, bare_years=True).text
        print(f"{where + '/' if where and where != '.' else ''}{name}")
    return 0


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


def cmd_words(args: argparse.Namespace) -> int:
    """A page's words with their positions, masked: the geometry of a printed form, without its values or names."""
    terms = workspace.redact_terms()
    doc = Path(args.path)
    try:
        _, password = _unlocked(doc)
    except text.UnsupportedDocument as err:
        print(f"{redact.redact(doc.name, terms, bare_years=True).text}: {err}", file=sys.stderr)
        return 1
    found = sorted((w for w in text.words(doc, args.page, password)
                    if _within(w["x0"], args.x) and _within(w["top"], args.top)), key=lambda w: (w["top"], w["x0"]))
    if not args.rows:
        for w in found:
            print(f"{w['top']:7.1f} {w['x0']:6.1f}-{w['x1']:<6.1f} {redact.redact(w['text'], terms).text}")
        return 0
    rows: list[list[dict]] = []
    for w in found:  # a row: words whose tops are within 2 points of the row's first
        if rows and w["top"] - rows[-1][0]["top"] <= 2:
            rows[-1].append(w)
        else:
            rows.append([w])
    for row in rows:
        print(f"{row[0]['top']:7.1f} " + " ".join(f"{w['x0']:.0f}:{redact.redact(w['text'], terms).text}"
                                                for w in sorted(row, key=lambda w: w["x0"])))
    return 0


def _range(spec: str) -> tuple[float, float]:
    """'300:450' as (300, 450); either end may be left out ('300:' is from 300 on)."""
    low, _, high = spec.partition(":")
    return float(low or "-inf"), float(high or "inf")


def _within(value: float, bounds: tuple[float, float] | None) -> bool:
    return bounds is None or bounds[0] <= value <= bounds[1]


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
        opened, tried = None, False
        for account, password in workspace.keychain_entries(doc):
            tried = True
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
            why = "no stored password opens it" if tried else "no Keychain entry"
            print(f"{name}: locked, {why}; store one with: {workspace.keychain_hint()}")
    return 1 if failed else 0


def cmd_import(args: argparse.Namespace) -> int:
    """Copy folders, zips or single files of documents into the workspace: filed returns to prior-returns/, the rest
    by tax year. File names are printed masked, since a name can carry a person's or a partnership's."""
    home = workspace.outside_git(workspace.home())
    terms = workspace.redact_terms()
    if missing := [Path(s).name for s in args.sources if not Path(s).exists()]:
        for name in missing:
            print(f"{redact.redact(name, terms, bare_years=True).text}: no such file or folder", file=sys.stderr)
        return 1
    placed: list[importer.Placement] = []
    for source in args.sources:
        placed += importer.import_documents(Path(source), home, dry_run=args.dry_run,
                                            year=str(args.year) if args.year else None)
    for p in placed:
        dest, source = (redact.redact(s, terms, bare_years=True).text if s else "-" for s in (p.dest, p.source))
        print(f"{dest:<45} {source}" + ("" if p.dest else f"  ({p.reason})"))
    copied = [p for p in placed if p.dest]
    verb = "would copy" if args.dry_run else "copied"
    print(f"{verb} {len(copied)} of {len(placed)} files into {home}")
    return 0


def cmd_prior(args: argparse.Namespace) -> int:
    """Read each filed return's carryforwards (depreciation, unallowed passive losses) into <workspace>/carryforwards.

    The values go only to that file. What's printed is masked: counts, the checks that failed, the questions, and
    with --layout each line a value was read from, so a layout can be checked without its numbers.
    """
    from . import prior

    home = workspace.outside_git(workspace.home())
    paths = [Path(p) for p in args.paths] or [home / importer.PRIOR_RETURNS]
    terms = workspace.redact_terms()

    def masked(line: str) -> str:
        return redact.redact(line, terms).text.strip()

    out = home / workspace.CARRYFORWARDS
    failed = 0
    returns: list[prior.Carryforwards] = []
    for doc in text.documents(paths):
        name = redact.redact(doc.name, terms, bare_years=True).text
        try:
            pages, password = _unlocked(doc)
        except text.UnsupportedDocument as err:
            print(f"{name}: skipped, {err}")
            continue
        words = {n: text.words(doc, n, password) for n, page in enumerate(pages, 1) if prior.has_activities(page)} \
            if doc.suffix.lower() in text.PDF_SUFFIXES else {}
        found = prior.read(doc.name, pages, words)
        if not (found.assets or found.unallowed or found.activities or found.rentals):
            print(f"{name}: no depreciation schedule or Form 8582 worksheets")
            continue
        problems = prior.verify(found, pages)
        returns.append(found)
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{doc.stem}.json").write_text(json.dumps(found.to_json(), indent=2) + "\n")
        bad = found.failed
        failed += bool(bad or problems)
        asset_pages = sorted({a.page for a in found.assets})
        loss_pages = sorted({u.page for u in found.unallowed})
        print(f"{name}: tax year {found.year or '?'}, {len(found.assets)} assets (p{asset_pages}), "
              f"{len(found.unallowed)} activities with unallowed losses (p{loss_pages}), "
              f"{len(found.activities)} passive activities on Worksheets 1 and 3; "
              f"{len(found.checks) - len(bad)} of {len(found.checks)} checks pass, {len(found.questions)} questions"
              + (f"; AMT and book copies skipped (p{found.skipped})" if found.skipped else "")
              + "".join(f"; p{n} is the {y} schedule, skipped" for n, y in found.other_years.items())
              + "".join(f"; Schedule E p{r.lines[3].page if 3 in r.lines else '?'}: lines "
                        f"{', '.join(map(str, sorted(r.lines))) or 'none'}" + (f", line 19's {len(r.other)} items"
                                                                              if r.other else "")
                        for r in found.rentals))
        for c in bad:
            print(f"  failed, p{c.page}: {masked(c.what)}")
        for p in problems:
            print(f"  failed: {p}")
        for q in found.questions:
            print(f"  question, p{q.page}: {masked(q.text)}" + (f"\n    {masked(q.quote)}" if q.quote else ""))
        if args.layout:
            for a in found.assets:
                # in years of depreciation: shows a first partial year or a gap, with no amount
                years = (f", prior {a.prior / a.annual:.2f} years, current {a.current / a.annual:.2f} years"
                         if a.annual else "")
                print(f"  p{a.page} asset {a.number}, {a.method} {a.convention} {masked(str(a.life))}{years}: "
                      f"{masked(a.quote)}")
            for u in found.unallowed:
                print(f"  p{u.page} unallowed loss: {masked(u.quote)}")
            for v in found.activities:
                used = ", ".join(c for c, x in zip("abcde", (v.net_income, v.net_loss, v.prior_unallowed, v.gain,
                                                             v.loss), strict=True) if x)
                print(f"  p{v.page} Worksheet {v.worksheet} activity, columns {used or 'none'}: {masked(v.quote)}")
    if links := prior.link(returns):
        bad = [c for c in links if not c.ok]
        failed += bool(bad)
        print(f"across returns: {len(links) - len(bad)} of {len(links)} checks pass")
        for c in bad:  # built from years, an asset number and a ratio, never a document's text or amounts
            print(f"  failed: {c.what}")
    if args.project:
        earlier = [r for r in returns if r.year and r.year < args.project and r.assets]
        if not earlier:
            print(f"no return before {args.project} with a depreciation schedule to roll forward", file=sys.stderr)
            return 1
        latest = max(earlier, key=lambda r: r.year)
        rows = prior.project(latest, args.project)
        target = out / f"projected-{args.project}.json"
        target.write_text(json.dumps({"through": args.project, "projected": True, "assets": rows}, indent=2) + "\n")
        ending = sum(any(y["last"] for y in r["years"]) for r in rows)
        print(f"projected {len(rows)} assets from the {latest.year} return through {args.project}: {target.name}"
              + (f"; {ending} reach the end of their recovery period, check the final year" if ending else "")
              + f". Confirm against the {args.project - 1} return when it arrives.")
    print(f"wrote to {out}" if out.exists() else "nothing to write")
    return 1 if failed else 0


def _saved(out: Path, read_now: set[str]) -> list[dict]:
    """What earlier runs of `k1` wrote for the documents this one didn't read (by their file names' stems)."""
    rows: list[dict] = []
    for path in sorted(out.glob("*.json")) if out.is_dir() else []:
        if path.stem not in read_now:
            rows += json.loads(path.read_text())
    return rows


def cmd_k1(args: argparse.Namespace) -> int:
    """Read every Schedule K-1 (Form 1065) face into <workspace>/k1: each box and code, and Parts I and II.

    North Carolina's D-403 NC K-1s and the Schedule K-3s are read too. Each NC K-1's line 1 is checked against the
    same partnership's federal K-1, and each K-1 that says a K-3 is attached has to have one, read now or on an
    earlier run. The values go only to that folder. What's printed is masked: which boxes, codes and lines have
    amounts, the checks that failed and the questions, and with --layout each value's text and where it sits.
    """
    from . import k1, k3, nck1

    home = workspace.outside_git(workspace.home())
    terms = workspace.redact_terms()

    def masked(line: str) -> str:
        return redact.redact(line, terms).text.strip()

    def report(head: str, bad: list, problems: list[str], questions: list, extra: tuple[str, ...] = ()) -> int:
        # checks and questions name boxes and lines only, never the document's text: that's in the quotes
        print(head)
        for line in extra:
            print(f"  {line}")
        for c in bad:
            print(f"  failed: {c.what}" + (f" ({masked(c.quote)})" if c.quote else ""))
        for p in problems:
            print(f"  failed: {masked(p)}")
        for q in questions:
            print(f"  question: {q.text}" + (f" ({masked(q.quote)})" if q.quote else ""))
        return bool(bad or problems)

    out = home / workspace.K1
    read_now = []  # (masked name, path, page texts, words by page, federal K-1s, NC K-1s, K-3s)
    for doc in _documents(args):
        name = redact.redact(doc.name, terms, bare_years=True).text
        try:
            pages, password = _unlocked(doc)
        except text.UnsupportedDocument as err:
            print(f"{name}: skipped, {err}")
            continue
        faces = [n for n, page in enumerate(pages, 1) if k1.is_face(page)]
        forms = [n for n, page in enumerate(pages, 1) if nck1.is_form(page)]
        schedules = [n for n, page in enumerate(pages, 1) if k3.is_page(page) and n not in faces]
        if not (faces or forms or schedules) or doc.suffix.lower() not in text.PDF_SUFFIXES:
            continue
        words = {n: text.words(doc, n, password) for n in sorted({*faces, *forms, *schedules})}
        read_now.append((name, doc, pages, words,
                         k1.read(doc.name, {n: words[n] for n in faces}, pages) if faces else [],
                         nck1.read(doc.name, {n: words[n] for n in forms}) if forms else [],
                         k3.read(doc.name, {n: words[n] for n in schedules}, pages) if schedules else []))
    saved = _saved(out, {doc.stem for _, doc, *_ in read_now})
    federal = {(f.ein, f.partner): [(i.box, i.value.amount) for i in f.items if i.value.amount is not None]
               for *_, found, _, _ in read_now for f in found if f.copy_of is None and not f.retirement_plan}
    for row in saved:
        if "form" not in row and row.get("copy_of") is None and not row.get("retirement_plan"):
            federal.setdefault((row["ein"], row["partner"]), [
                (i["box"], Decimal(i["value"]["amount"])) for i in row["items"] if i["value"]["amount"] is not None])
    attached = {(s.ein, s.partner) for *_, threes in read_now for s in threes} | {
        (row["ein"], row["partner"]) for row in saved if row.get("form") == "K-3"}
    for *_, found, ncs, threes in read_now:
        for s in threes:
            if amounts := federal.get((s.ein, s.partner)):
                k3.tie(s, amounts)
            else:
                s.ask("no federal K-1 from this partnership for this partner has been read: run `taxtrace k1` on it "
                      "too, and Part II's interest, dividends and gains are checked against its boxes")
        for f in found:
            if f.k3_attached and f.copy_of is None and not f.retirement_plan and (f.ein, f.partner) not in attached:
                f.ask("box 16: a Schedule K-3 is attached, and none from this partnership for this partner has been "
                      "read: run `taxtrace k1` on it too")
        for nc in ncs:
            if nc.copy_of is not None:
                continue
            if amounts := federal.get((nc.ein, nc.partner)):
                nck1.tie(nc, amounts)
            else:
                nc.ask("no federal K-1 from this partnership for this partner has been read: run `taxtrace k1` "
                       "on it too, and line 1 is checked against it")
    failed = 0
    for name, _, pages, words, found, ncs, threes in read_now:
        for f in found:
            boxes = ", ".join(i.box + (f" {i.code}" if i.code else "") + (" (statement)" if i.statement else "")
                              for i in f.items)
            extra: tuple[str, ...] = ()
            if f.statement:
                counts: dict[str, int] = {}
                for s in f.statement:
                    key = s.box + (f" {s.code}" if s.code else "")
                    counts[key] = counts.get(key, 0) + 1
                totals = sum(bool(s.aggregate) for s in f.statement)
                extra = ("statement amounts: " + ", ".join(f"{k} ×{n}" if n > 1 else k for k, n in counts.items())
                         + (f"; {totals} of them an aggregated group's totals, which repeat its businesses' amounts"
                            if totals else ""),)
            failed += report(
                f"{name} p{f.page}: {f.year or '?'} K-1 from {masked(f.ein) or 'no EIN found'}, "
                f"amounts in {boxes or 'no boxes'}; {len(f.checks) - len(f.failed)} of {len(f.checks)} checks pass, "
                f"{len(f.questions)} questions"
                + ("; a retirement plan's (I2): nothing on it goes on the return" if f.retirement_plan else "")
                + (f"; a second copy of p{f.copy_of}'s, counted once" if f.copy_of else "")
                + ("; final K-1" if f.final else "") + ("; amended" if f.amended else "")
                + ("; Schedule K-3 attached" if f.k3_attached else ""),
                f.failed, k1.verify(f, words[f.page], pages), f.questions, extra)
            if args.layout:
                print(f"  partnership {masked(f.partnership)}; entity {masked(f.entity_type)}; "
                      f"general partner {f.general_partner}, domestic {f.domestic}, publicly traded "
                      f"{f.publicly_traded}, lower-tier {f.lower_tier}, guarantees {f.guaranteed}, "
                      f"built-in gain {f.built_in_gain}")
                for part, rows in (("J", f.shares), ("K1", f.liabilities)):
                    for key, cols in rows.items():
                        print(f"  {part} {key}: " + ", ".join(f"{col} {masked(v.quote)}" for col, v in cols.items()))
                for part, cols in (("L", f.capital), ("N", f.section_704c)):
                    for key, v in cols.items():
                        print(f"  {part} {key}: {masked(v.quote)} at {v.top}, {v.x0}")
                for i in f.items:
                    print(f"  box {i.box}{' ' + i.code if i.code else ''}: {masked(i.value.quote)} at "
                          f"{i.value.top}, {i.value.x0}")
                for s in f.statement:
                    whose = (f" [{s.kind or 'other'} of {masked(s.aggregate)}, the total of "
                             f"{', '.join(masked(m) for m in s.members) or 'no business named'}]" if s.aggregate
                             else f" [{s.kind or 'other'} of {masked(s.business)}]" if s.business else "")
                    print(f"  p{s.page} statement {s.box}{' ' + s.code if s.code else ''} "
                          f"{masked(s.description)!r}{whose}: {masked(s.quote)}")
        for nc in ncs:
            answers = {"resident": nc.resident, "taxed partnership": nc.taxed_partnership,
                       "disregarded entity": nc.disregarded_entity}
            failed += report(
                f"{name} p{nc.page}: {nc.year or '?'} NC K-1 (D-403) from {masked(nc.ein) or 'no FEIN found'}, "
                f"amounts on lines {', '.join(str(n) for n, v in sorted(nc.lines.items()) if v.amount) or 'none'}; "
                f"{len(nc.checks) - len(nc.failed)} of {len(nc.checks)} checks pass, {len(nc.questions)} questions; "
                + ", ".join(f"{k} {'?' if v is None else 'yes' if v else 'no'}" for k, v in answers.items())
                + (f"; a second copy of p{nc.copy_of}'s, counted once" if nc.copy_of else ""),
                nc.failed, k1.verify(nc, words[nc.page]), nc.questions)
            if args.layout:
                print(f"  partnership {masked(nc.partnership)}")
                for n, v in sorted(nc.lines.items()):
                    print(f"  line {n}: {masked(v.quote)} at {v.top}, {v.x0}")
        for s in threes:
            lines = sorted({c.line for c in s.cells})
            foreign = s.foreign_columns()
            failed += report(
                f"{name} p{s.page}: {s.year or '?'} Schedule K-3 from {masked(s.ein) or 'no EIN found'}, parts that "
                f"apply {', '.join(p for p, yes in s.parts.items() if yes) or 'none marked'}; Part II amounts on lines "
                f"{', '.join(map(str, lines)) or 'none'}; {len(s.checks) - len(s.failed)} of {len(s.checks)} checks "
                f"pass, {len(s.questions)} questions",
                s.failed, k3.verify(s, words), s.questions,
                ("foreign source: " + (f"amounts in columns {', '.join(f'({c})' for c in sorted(foreign))}"
                                       if foreign else "none, all of Part II is U.S. source")
                 + f"; foreign taxes: {len(s.foreign_taxes) or 'none'}",))
            if args.layout:
                for c in s.cells:
                    print(f"  p{c.value.page} line {c.line}{' ' + c.row if c.row else ''}"
                          f"{' ' + masked(c.country) if c.country else ''} ({c.column}): {masked(c.value.quote)} at "
                          f"{c.value.top}, {c.value.x0}")
    written: dict[str, list[dict]] = {}  # each document's forms, by its file name's stem
    for _, doc, _, _, found, ncs, threes in read_now:
        if rows := [f.to_json() for f in [*found, *ncs, *threes]]:
            written[doc.stem] = rows
    for stem, rows in written.items():
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{stem}.json").write_text(json.dumps(rows, indent=2) + "\n")
    print(f"wrote to {out}" if written else "no K-1s found")
    return 1 if failed else 0


def cmd_1098(args: argparse.Namespace) -> int:
    """Read every Form 1098 (Mortgage Interest Statement) into <workspace>/forms: each box, the lender and the year.

    The values go only to that folder. What's printed is masked: which boxes have amounts, the checks that failed
    and the questions (box 10's other amount, a refund of interest, which property), and with --layout each value's
    text and where it sits.
    """
    from . import f1098, k1

    home = workspace.outside_git(workspace.home())
    terms = workspace.redact_terms()

    def masked(line: str) -> str:
        return redact.redact(line, terms).text.strip()

    out, written, failed = home / workspace.FORMS, 0, 0
    for doc in _documents(args):
        name = redact.redact(doc.name, terms, bare_years=True).text
        try:
            pages, password = _unlocked(doc)
        except text.UnsupportedDocument as err:
            print(f"{name}: skipped, {err}")
            continue
        forms = [n for n, page in enumerate(pages, 1) if f1098.is_form(page)]
        if not forms or doc.suffix.lower() not in text.PDF_SUFFIXES:
            continue
        words = {n: text.words(doc, n, password) for n in forms}
        found = f1098.read(doc.name, words)
        for f in found:
            problems = k1.verify(f, words[f.page])
            failed += bool(f.failed or problems)
            print(f"{name} p{f.page}: {f.year or '?'} Form 1098 from {masked(f.lender_tin) or 'no lender TIN found'}"
                  f", amounts in boxes {', '.join(f.amounts) or 'none'}; {len(f.checks) - len(f.failed)} of "
                  f"{len(f.checks)} checks pass, {len(f.questions)} questions"
                  + ("; corrected" if f.corrected else "")
                  + (f"; a second copy of p{f.copy_of}'s, counted once" if f.copy_of else ""))
            print(f"  property: {masked(f.address) if f.address else 'none in box 8'}"
                  + ("; box 7: the borrower's own address" if f.same_address else ""))
            for c in f.failed:
                print(f"  failed: {c.what}" + (f" ({masked(c.quote)})" if c.quote else ""))
            for p in problems:
                print(f"  failed: {masked(p)}")
            for q in f.questions:
                print(f"  question: {q.text}" + (f" ({masked(q.quote)})" if q.quote else ""))
            if args.layout:
                print(f"  lender {masked(f.lender)}; account {masked(f.account)}; borrower's TIN ending "
                      f"{masked(f.payer) or '?'}; origination {masked(f.origination) or 'none'}, acquisition "
                      f"{masked(f.acquisition) or 'none'}; properties {f.properties or 'not printed'}")
                for box, v in f.amounts.items():
                    print(f"  box {box}: {masked(v.quote)} at {v.top}, {v.x0}")
        if found:
            out.mkdir(parents=True, exist_ok=True)
            (out / f"{doc.stem}.json").write_text(json.dumps([f.to_json() for f in found], indent=2) + "\n")
            written += 1
    print(f"wrote to {out}" if written else "no 1098s found")
    return 1 if failed else 0


def cmd_itr(args: argparse.Namespace) -> int:
    """Read India's income tax returns (ITR-2) into <workspace>/forms: a sale of property in India, the interest
    India saw, and the tax India kept after the refund, for Form 8949 and Form 1116.

    The values go only to that folder, as itr-<assessment year>.json. What's printed is masked: which rows were
    found, the checks that failed and the questions.
    """
    from . import itr

    home = workspace.outside_git(workspace.home())
    terms = workspace.redact_terms()

    def masked(line: str) -> str:
        return redact.redact(line, terms).text.strip()

    out, written, failed = home / workspace.FORMS, 0, 0
    for doc in _documents(args):
        name = redact.redact(doc.name, terms, bare_years=True).text
        try:
            pages, _ = _unlocked(doc)
        except text.UnsupportedDocument as err:
            print(f"{name}: skipped, {err}")
            continue
        if not itr.is_return(pages):
            continue
        found = itr.read(doc.name, pages)
        failed += bool(found.failed)
        fy = found.financial_year
        print(f"{name}: {found.version or 'ITR'} for assessment year {found.year or '?'}"
              + (f" (India's year {fy[0]:%m/%Y} to {fy[1]:%m/%Y})" if fy else "")
              + f", {found.status or 'residential status not found'}, filed {masked(found.filed) or '?'}; "
              f"{len(found.checks) - len(found.failed)} of {len(found.checks)} checks pass, "
              f"{len(found.questions)} questions")
        print(f"  tax rows: {', '.join(k.replace('_', ' ') for k in found.tax) or 'none'}")
        print(f"  interest rows: {', '.join(found.interest) or 'none'}")
        for sale in found.sales:
            print(f"  sale: {sale.term}-term, acquired {masked(sale.acquired)}, sold {masked(sale.sold)}; rows: "
                  f"{', '.join(k.replace('_', ' ') for k in sale.amounts)}; {len(sale.improvements)} improvements"
                  + ("; an exemption" if sale.exemption and sale.exemption.amount else "")
                  + ("; gain found" if sale.gain else "; no gain row"))
        for c in found.failed:
            print(f"  failed: {c.what}" + (f" ({masked(c.quote)})" if c.quote else ""))
        for q in found.questions:
            print(f"  question: {q.text}" + (f" ({masked(q.quote)})" if q.quote else ""))
        out.mkdir(parents=True, exist_ok=True)
        # a list, like every file in forms/, which `rental` reads all of and picks its forms from by "form"
        (out / f"itr-{found.year or doc.stem}.json").write_text(json.dumps([found.to_json()], indent=2,
                                                                           default=str) + "\n")
        written += 1
    print(f"wrote to {out}" if written else "no Indian returns found")
    return 1 if failed else 0


def cmd_bank(args: argparse.Namespace) -> int:
    """Read foreign banks' statements of account into <workspace>/forms: each transaction, which rows are interest,
    a tax refund or TDS, for Schedule B, Form 1116, Form 8938 and the FBAR.

    The values go only to that folder, as bank-<last four digits>-<period start>.json. What's printed is masked: the
    period, how many rows of each kind, the checks that failed and the questions.
    """
    from . import statement

    home = workspace.outside_git(workspace.home())
    terms = workspace.redact_terms()

    def masked(line: str) -> str:
        return redact.redact(line, terms).text.strip()

    out, written, failed = home / workspace.FORMS, 0, 0
    for doc in _documents(args):
        name = redact.redact(doc.name, terms, bare_years=True).text
        if doc.suffix.lower() not in text.PDF_SUFFIXES:
            continue
        try:
            pages, password = _unlocked(doc)
        except text.UnsupportedDocument as err:
            print(f"{name}: skipped, {err}")
            continue
        tables = [n for n, page in enumerate(pages, 1) if statement.is_statement(page)]
        if not tables:
            continue
        found = statement.read(doc.name, pages, {n: text.words(doc, n, password) for n in tables})
        failed += bool(found.failed)
        kinds = {k: sum(r.kind == k for r in found.rows) for k in ("interest", "tax refund", "tds", "tds refund")}
        print(f"{name}: account ending {masked(found.account) or '?'} in {found.currency or '?'}, "
              f"{found.start or '?'} to {found.end or '?'}; {len(found.rows)} rows ("
              + ", ".join(f"{v} {k}" for k, v in kinds.items()) + f"); {len(found.checks) - len(found.failed)} of "
              f"{len(found.checks)} checks pass")
        if args.rows:
            for r in found.rows:
                print(f"  {r.on} {'deposit' if r.deposit else 'withdrawal'} {r.kind or '-'}: {masked(r.description)}")
        for c in found.failed:
            print(f"  failed: {c.what}" + (f" ({masked(c.quote)})" if c.quote else ""))
        for q in found.questions:
            print(f"  question: {q.text}")
        out.mkdir(parents=True, exist_ok=True)
        start = "".join(reversed(found.start.split("-"))) if found.start else doc.stem
        (out / f"bank-{found.account or 'x'}-{start}.json").write_text(
            json.dumps([found.to_json()], indent=2, default=str) + "\n")
        written += 1
    print(f"wrote to {out}" if written else "no statements of account found")
    return 1 if failed else 0


def cmd_rental(args: argparse.Namespace) -> int:
    """Put the rental's Schedule E (Part I) for a year together into <workspace>/schedule-e/<year>.json.

    It reads the answers to the preparer's questions and the insurance declarations among the documents given
    (default: <workspace>/<year>), skipping locked ones without asking the Keychain, and takes what `1098`, `prior`
    and `prior --project` saved: the property's 1098, the latest filed Schedule E and the depreciation rolled
    forward. What's printed is masked: where each line comes from, the checks and the questions.
    """
    from . import answers, policy, schedule_e

    home = workspace.outside_git(workspace.home())
    terms = workspace.redact_terms()

    def masked(line: str) -> str:
        return redact.redact(line, terms).text.strip()

    year = args.year
    docs = text.documents([Path(p) if Path(p).exists() else home / p for p in args.paths] or [home / str(year)])
    found_answers, policies = [], []
    for doc in docs:
        try:
            pages, _ = _unlocked(doc, keychain=False)
        except text.UnsupportedDocument:
            continue  # a locked K-1 or statement: neither answers nor declarations are kept locked
        found_answers += answers.read(doc.name, pages)
        if doc.suffix.lower() in text.PDF_SUFFIXES:
            policies += policy.read(doc.name, pages)
    filed = []
    for path in sorted((home / workspace.CARRYFORWARDS).glob("*.json")):
        row = json.loads(path.read_text())
        if isinstance(row, dict) and (row.get("year") or year) < year:
            filed += [schedule_e.load(r) for r in row.get("rentals", [])]
    last = max(filed, key=lambda r: r.year or 0, default=None)
    forms = [f for path in sorted((home / workspace.FORMS).glob("*.json"))
             for rows in [json.loads(path.read_text())] for f in (rows if isinstance(rows, list) else [rows])]
    projected_path = home / workspace.CARRYFORWARDS / f"projected-{year}.json"
    projected = json.loads(projected_path.read_text()) if projected_path.exists() else None
    out = home / workspace.SCHEDULE_E
    kept = out / f"{year}-confirmed.json"  # what was confirmed on earlier runs stays confirmed
    confirmed = json.loads(kept.read_text()) if kept.exists() else {}
    try:
        confirmed |= dict(map(schedule_e.confirmation, args.confirm))
    except ValueError as err:
        print(err, file=sys.stderr)
        return 2
    if args.confirm:
        out.mkdir(parents=True, exist_ok=True)
        kept.write_text(json.dumps(confirmed, indent=2) + "\n")
    rental = schedule_e.build(year, last=last, answers=found_answers, forms=forms, policies=policies,
                              projected=projected, confirmed=confirmed)
    print(f"{year} Schedule E for {masked(rental.address) or 'an unknown property'}"
          + (f", against {last.year}'s filed return" if last else "") + ":")
    for n, line in sorted(rental.lines.items()):
        print(f"  line {n} {schedule_e.LINES[n].lower()}: " + ("confirmed by you" if line.source == "confirmed" else
              f"{line.source}, {redact.redact(line.file, terms, bare_years=True).text} p{line.page}"))
    if confirmed:
        print("  confirmed: " + ", ".join(k.replace("_", " ") + (f" {'yes' if v else 'no'}" if isinstance(v, bool)
                                                                 else "") for k, v in confirmed.items()))
    if last:
        print(f"  {last.year}: lines {', '.join(map(str, sorted(last.lines)))}"
              + (f"; line 19: {', '.join(masked(o.what) for o in last.other)}" if last.other else ""))
    for c in rental.failed:
        print(f"  failed: {c.what}" + (f" ({masked(c.quote)})" if c.quote else ""))
    for q in rental.questions:
        print(f"  question: {q.text}" + (f" ({masked(q.quote)})" if q.quote else ""))
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{year}.json").write_text(json.dumps(rental.to_json(), indent=2) + "\n")
    print(f"wrote to {out / f'{year}.json'}")
    return 1 if rental.failed else 0


def cmd_foreign(args: argparse.Namespace) -> int:
    """Put a year's foreign side together in dollars into <workspace>/foreign/<year>.json: a property sold abroad
    (Form 8949) and the tax kept there (Form 1116), from India's returns that `itr` saved.

    Each amount is converted at its own day's rate (FRED's noon buying rate), fetched once into <workspace>/fx: the
    price at the sale's, the cost at the purchase's. What's printed is masked: what each amount is and the rate's
    source, the questions, and whether the dollar result is a gain or a loss.
    """
    from . import foreign, fx

    home = workspace.outside_git(workspace.home())
    terms = workspace.redact_terms()

    def masked(line: str) -> str:
        return redact.redact(line, terms).text.strip()

    year = args.year
    itrs = [f for path in sorted((home / workspace.FORMS).glob("itr-*.json"))
            for rows in [json.loads(path.read_text())] for f in (rows if isinstance(rows, list) else [rows])]
    out = home / workspace.FOREIGN
    kept = out / f"{year}-confirmed.json"  # what was confirmed on earlier runs stays confirmed
    confirmed = json.loads(kept.read_text()) if kept.exists() else {}
    try:
        confirmed |= dict(map(foreign.confirmation, args.confirm))
    except ValueError as err:
        print(err, file=sys.stderr)
        return 2
    if args.confirm:
        out.mkdir(parents=True, exist_ok=True)
        kept.write_text(json.dumps(confirmed, indent=2) + "\n")
    found = foreign.build(year, itrs=itrs, rates=fx.Rates("INR", home / workspace.FX), confirmed=confirmed)
    print(f"{year} foreign side: {len(found.sales)} sale(s), {len(found.taxes)} foreign tax(es)"
          + ("" if itrs else "; no Indian return read yet (`taxtrace itr`)"))
    for sale in found.sales:
        source = redact.redact(sale.file, terms, bare_years=True).text
        print(f"  Form 8949: {sale.description}, {sale.term}-term, from {source}; a "
              f"{'gain' if sale.gain >= 0 else 'loss'} in dollars")
        for c in [sale.proceeds, sale.cost, *sale.improvements, *([sale.expenses] if sale.expenses else [])]:
            print(f"    {masked(c.what)}: p{c.page}, at {c.rate.source} of {masked(c.rate.day)}")
    for t in found.taxes:
        print(f"  Form 1116: {t.country}, {t.category} category, {t.kept.what} at {t.kept.rate.source} of "
              f"{masked(t.kept.rate.day)}")
    if confirmed:
        print("  confirmed: " + ", ".join(k.replace("_", " ") for k in confirmed))
    for q in found.questions:
        print(f"  question: {q.text}")
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{year}.json").write_text(json.dumps(found.to_json(), indent=2, default=str) + "\n")
    print(f"wrote to {out / f'{year}.json'}")
    return 0


def cmd_passive(args: argparse.Namespace) -> int:
    """Each passive activity's year into <workspace>/passive/<year>.json, from what `prior` and `k1` saved.

    Each activity on the latest return's Form 8582 worksheets is matched to this year's K-1 from its partnership:
    this year's passive income or loss, and the loss it carries in. No document is opened. What's printed is masked:
    each activity's name, where its year comes from, whether it's income or a loss, and the questions.
    """
    from . import passive

    home = workspace.outside_git(workspace.home())
    terms = workspace.redact_terms()

    def masked(line: str) -> str:
        return redact.redact(line, terms).text.strip()

    def saved(folder: str) -> list:
        return [json.loads(p.read_text()) for p in sorted((home / folder).glob("*.json"))] \
            if (home / folder).is_dir() else []

    returns = [r for r in saved(workspace.CARRYFORWARDS) if "file" in r]  # not a projection
    k1s = [row for rows in saved(workspace.K1) for row in rows]
    year = args.year or max((f["year"] for f in k1s if "form" not in f and f.get("year")), default=None)
    if year is None:
        print("no K-1 has been read yet: run `taxtrace k1` first", file=sys.stderr)
        return 1
    ledger = passive.build(year, returns, k1s)
    out = home / workspace.PASSIVE
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{year}.json").write_text(json.dumps(ledger.to_json(), indent=2) + "\n")
    print(f"{year}: {len(ledger.lines)} passive activities"
          + (f", starting from the {ledger.latest} return's Form 8582" if ledger.latest else "")
          + f"; {len(ledger.questions)} questions")
    for line in ledger.lines:
        source = {"k1": f"its K-1 ({masked(line.k1_file)} p{line.k1_page})",
                  "schedule e": "Schedule E (not read yet)"}.get(line.source, "no source this year")
        current = (f"counted with {masked(line.merged_into)}" if line.merged_into else
                   "not known yet" if line.current is None else "income" if line.current > 0 else
                   "a loss" if line.current < 0 else "nothing")
        carried = (f"what it carries in comes from the {year - 1} return" if line.carried is None else
                   "a loss carried in" if line.carried else "no loss carried in")
        print(f"  {masked(line.activity) or 'an unnamed activity'}"
              + (f" (Worksheet {line.worksheet})" if line.worksheet else " (new)")
              + f": {source}, this year {current}, {carried}"
              + ("; a final K-1: a full disposition frees what it carries" if line.final else ""))
    for q in ledger.questions:
        print(f"  question: {q.text}" + (f" ({masked(q.quote)})" if q.quote else ""))
    print(f"wrote to {out / f'{year}.json'}")
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


def cmd_service(args: argparse.Namespace) -> int:
    """Keep `taxtrace ui` running: start it at login, restart it if it stops (macOS)."""
    from . import service

    try:
        if args.action == "install":
            url = service.install(args.port, args.models, args.keychain)
            print(f"taxtrace ui now starts when you log in and restarts if it stops: {url}\n"
                  f"Workspace: {workspace.home()}. Log: {service.log_path()}. "
                  "Undo with `taxtrace service uninstall`.")
        elif args.action == "uninstall":
            print("Removed: taxtrace ui no longer starts at login." if service.uninstall() else "Not installed.")
        else:
            s = service.status()
            if not s["installed"]:
                print("Not installed. `taxtrace service install` starts taxtrace ui at login.")
            else:
                state = f"running (pid {s['pid']})" if s["running"] else "installed, not running: see the log"
                print(f"{state}\n{s['url'] or ''}\nLog: {s['log']}")
    except (service.ServiceError, workspace.InsideGitRepo) as err:
        print(f"taxtrace: {err}", file=sys.stderr)
        return 1
    return 0


def cmd_keychain(args: argparse.Namespace) -> int:
    """Approve Keychain reads with Apple Watch or Touch ID instead of typing the login password (macOS)."""
    from . import chat, gate

    if args.action == "status":  # asks the Keychain for attributes only: no prompt, no secret
        built = "built, current" if gate.current() else "built, out of date: run setup" if gate.ready() else "not built"
        print(f"helper: {built}")
        accounts = [workspace.KEYCHAIN_DEFAULT, *args.account, *gate.adopted_accounts(workspace.KEYCHAIN_SERVICE)]
        entries = [(workspace.KEYCHAIN_SERVICE, account) for account in dict.fromkeys(accounts)]
        entries.append((args.keychain, ""))
        for service, account in entries:
            # a file's own entry is named for the file, so masked like any file name
            name = account if account == workspace.KEYCHAIN_DEFAULT else redact.redact(
                account, workspace.redact_terms(), bare_years=True).text
            shown = f"{service}/{name}" if account else service
            if not chat.keychain_has(service):
                state = "no such entry"
            elif gate.adopted(service, account):
                state = "Apple Watch or Touch ID"
            else:
                state = "the classic prompt (password, then Allow): run setup to move it"
            leftover = "; a backup copy is left over, setup clears it" if chat.keychain_has(
                f"{service}.taxtrace-backup") else ""
            print(f"  {shown}: {state}{leftover}")
        return 0
    try:
        rebuilt = gate.build()
    except gate.GateError as err:
        print(f"taxtrace: {err}", file=sys.stderr)
        return 1
    print(f"Built {gate.helper_path()}" if rebuilt else f"Already built: {gate.helper_path()}")
    entries = [(workspace.KEYCHAIN_SERVICE, account) for account in [workspace.KEYCHAIN_DEFAULT, *args.account]]
    if chat.keychain_has(args.keychain):
        entries.append((args.keychain, ""))  # the chat's key, whatever account it was stored under
    print("Moving each entry over to the helper: macOS asks for it the old way one last time (password, then Allow).")
    failed = 0
    for service, account in entries:
        shown = f"{service}/{account}" if account else service
        try:
            moved = gate.adopt(service, account)
        except gate.GateError as err:
            failed += 1
            print(f"  {shown}: {err}")
            continue
        print(f"  {shown}: {'now asks for Apple Watch or Touch ID' if moved else 'no such entry, skipped'}")
    print("Restart the service so the chat reads its key the new way: taxtrace service install")
    return 1 if failed else 0


PATHS_HELP ="documents or folders (default: the whole workspace)"


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
    p.add_argument("sources", nargs="+", metavar="source",
                   help="a folder, a zip such as a tax preparer's portal export, or a single file")
    p.add_argument("--year", type=int, help="the tax year of every file that isn't a filed return "
                                            "(default: read from its folder's name, else its own)")
    p.add_argument("--dry-run", action="store_true", help="show where each file would go, copy nothing")
    p.set_defaults(func=cmd_import)
    p = sub.add_parser("unlock", help="check which stored password opens each locked PDF",
                       description=cmd_unlock.__doc__)
    p.add_argument("paths", nargs="*", help=PATHS_HELP)
    p.set_defaults(func=cmd_unlock)
    p = sub.add_parser("list", help="the documents' names, masked, without opening them", description=cmd_list.__doc__)
    p.add_argument("paths", nargs="*", help=PATHS_HELP)
    p.set_defaults(func=cmd_list)
    p = sub.add_parser("outline", help="list each page's masked heading", description=cmd_outline.__doc__)
    p.add_argument("paths", nargs="*", help=PATHS_HELP)
    p.add_argument("--lines", type=int, default=2, help="lines per page (default: 2)")
    p.set_defaults(func=cmd_outline)
    p = sub.add_parser("words", help="a page's masked words with their positions", description=cmd_words.__doc__)
    p.add_argument("path", help="a PDF")
    p.add_argument("--page", type=int, default=1, help="page number (default: 1)")
    p.add_argument("--x", type=_range, metavar="MIN:MAX", help="only words starting in this range of points")
    p.add_argument("--top", type=_range, metavar="MIN:MAX", help="only words this far down the page, in points")
    p.add_argument("--rows", action="store_true", help="one line per row: each word as x:text")
    p.set_defaults(func=cmd_words)
    p = sub.add_parser("prior", help="read filed returns' carryforwards: depreciation, unallowed passive losses",
                       description=cmd_prior.__doc__)
    p.add_argument("paths", nargs="*", help="returns or folders (default: <workspace>/prior-returns)")
    p.add_argument("--layout", action="store_true", help="also print each line a value came from, masked")
    p.add_argument("--project", type=int, metavar="YEAR",
                   help="roll the latest return's depreciation forward through YEAR, for returns not in hand yet")
    p.set_defaults(func=cmd_prior)
    p = sub.add_parser("k1", help="read Schedule K-1 (Form 1065) faces: every box and code, Parts I and II",
                       description=cmd_k1.__doc__)
    p.add_argument("paths", nargs="*", help=PATHS_HELP)
    p.add_argument("--layout", action="store_true", help="also print each value's text and place, masked")
    p.set_defaults(func=cmd_k1)
    p = sub.add_parser("1098", help="read Form 1098 mortgage interest statements: each box, the lender and the year",
                       description=cmd_1098.__doc__)
    p.add_argument("paths", nargs="*", help=PATHS_HELP)
    p.add_argument("--layout", action="store_true", help="also print each value's text and place, masked")
    p.set_defaults(func=cmd_1098)
    p = sub.add_parser("itr", help="read India's income tax returns: a property sale, interest, the tax India kept",
                       description=cmd_itr.__doc__)
    p.add_argument("paths", nargs="*", help=PATHS_HELP)
    p.set_defaults(func=cmd_itr)
    p = sub.add_parser("bank", help="read foreign banks' statements of account: interest, refunds, balances",
                       description=cmd_bank.__doc__)
    p.add_argument("paths", nargs="*", help=PATHS_HELP)
    p.add_argument("--rows", action="store_true", help="also print each row's date, kind and description, masked")
    p.set_defaults(func=cmd_bank)
    p = sub.add_parser("rental", help="put a year's Schedule E for the rental together, line by line",
                       description=cmd_rental.__doc__)
    p.add_argument("paths", nargs="*", help="documents or folders with the answers and policies "
                                            "(default: <workspace>/<year>)")
    p.add_argument("--year", type=int, required=True, help="the tax year")
    p.add_argument("--confirm", action="append", default=[], metavar="KEY=VALUE",
                   help="settle a question only you can answer, kept for later runs: fair_rental_days=365, "
                        "personal_use_days=0, rent_all_year=yes, earlier_policy=AMOUNT (0: none), dues=AMOUNT")
    p.set_defaults(func=cmd_rental)
    p = sub.add_parser("foreign", help="a year's foreign side in dollars: a property sold abroad, the tax kept there",
                       description=cmd_foreign.__doc__)
    p.add_argument("--year", type=int, required=True, help="the tax year")
    p.add_argument("--confirm", action="append", default=[], metavar="KEY=VALUE",
                   help="settle a question only you can answer, kept for later runs: owner=self|spouse|joint|other, "
                        "improvement_dates=YYYY-MM-DD,..., use=investment|personal|rental")
    p.set_defaults(func=cmd_foreign)
    p = sub.add_parser("passive", help="each passive activity's year, from the saved returns and K-1s",
                       description=cmd_passive.__doc__)
    p.add_argument("--year", type=int, help="the tax year (default: the latest year of the K-1s read)")
    p.set_defaults(func=cmd_passive)
    p = sub.add_parser("keychain", help="approve Keychain reads with Apple Watch or Touch ID (macOS)",
                       description=cmd_keychain.__doc__)
    p.add_argument("action", choices=["setup", "status"],
                   help="setup: build the helper and move entries over; status: how each entry is read now")
    p.add_argument("--keychain", default="anthropic", help="the chat's API key item to include (default: anthropic)")
    p.add_argument("--account", action="append", default=[], metavar="FILE NAME",
                   help="also move a file's own entry (repeatable); the default entry is always moved")
    p.set_defaults(func=cmd_keychain)
    p = sub.add_parser("ui", help="open the workspace and a chat in the browser", description=cmd_ui.__doc__)
    p.add_argument("--port", type=int, default=8766, help="port on 127.0.0.1 (default: 8766)")
    p.add_argument("--no-open", action="store_true", help="don't open the browser")
    p.add_argument("--models", default="claude,agy,local",
                   help="the chat's models, tried in this order (default: claude,agy,local)")
    p.add_argument("--keychain", default="anthropic",
                   help="Keychain item with the Anthropic API key, if ANTHROPIC_API_KEY isn't set (default: anthropic)")
    p.set_defaults(func=cmd_ui)
    p = sub.add_parser("service", help="keep `taxtrace ui` running: start it at login, restart it if it stops "
                                       "(macOS)", description=cmd_service.__doc__)
    p.add_argument("action", choices=["install", "uninstall", "status"])
    p.add_argument("--port", type=int, default=8766, help="install: port on 127.0.0.1 (default: 8766)")
    p.add_argument("--models", default="claude,agy,local", help="install: the chat's models, as for `ui`")
    p.add_argument("--keychain", default="anthropic", help="install: Keychain item with the Anthropic API key")
    p.set_defaults(func=cmd_service)
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
