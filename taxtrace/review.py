"""The workspace as an AI assistant may see it: masked, never raw. What the MCP server (`taxtrace mcp`) returns.

Nothing here returns a value, name, ID or account number from a document or from todo.md. Every piece of free text
(a file name, a page heading, a check's quote, a to-do item) goes through the masking the cloud chat uses and
`taxtrace redact` writes: digits become #, words outside the IRS's vocabulary become *s, and the names in
redact-terms.txt go first. What stays unmasked is what masking itself keeps: dates, and counts and pass/fail results
taxtrace computed. The workspace's own path is left out: it names the person.

A locked document is reported as locked, never opened: no tool here asks the Keychain for a password, so an assistant
can't cause an approval prompt, and the document's password stays where it is.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from . import redact, text, todo, workspace

FORMS = ("1098", "1099", "k1")
YEAR_FOLDER = re.compile(r"(?:19|20)\d\d")
# derived folders whose saved files say which documents were read, and under what name (a prefix before the stem)
READ_IN = (workspace.FORMS, workspace.K1, workspace.CARRYFORWARDS)
# every folder taxtrace saves readings and results in, counted by status
SAVED = (workspace.FORMS, workspace.K1, workspace.CARRYFORWARDS, workspace.PASSIVE, workspace.SCHEDULE_E,
         workspace.FOREIGN, workspace.QBI, workspace.ESTIMATES, workspace.IRA)
READ_PREFIXES = ("itr-", "bank-", "tds-")
MAX_PAGES = 200


class ReviewError(ValueError):
    """Something the assistant should be told in words: no such document, nothing to read."""


def masker() -> Callable[..., str]:
    """`mask(line, names=False)`: the line with its values, names and places masked. `names=True` keeps a bare year,
    for a file name or a folder."""
    terms = workspace.redact_terms()

    def mask(line: str, names: bool = False) -> str:
        return redact.redact(line, terms, bare_years=names).text.strip()

    return mask


def documents() -> list[Path]:
    """The workspace's documents in a stable order: a document's id is its place here, from 1."""
    workspace.outside_git(workspace.home())
    return text.documents(workspace.sources())


def _read_stems() -> set[str]:
    """The file stems of everything taxtrace has saved from a document: the documents that were read."""
    stems: set[str] = set()
    for folder in READ_IN:
        for saved in (workspace.home() / folder).glob("*.json"):
            stem = saved.stem
            stems.add(stem)
            stems.update(stem[len(p):] for p in READ_PREFIXES if stem.startswith(p))
    return stems


def listing() -> list[dict]:
    """Each document: its id, its folder and name masked, its kind, and whether taxtrace has read it."""
    home, mask, read = workspace.home(), masker(), _read_stems()
    rows = []
    for n, doc in enumerate(documents(), 1):
        try:
            where = doc.parent.relative_to(home).as_posix()
        except ValueError:
            where = ""
        rows.append({"id": n, "folder": "" if where == "." else mask(where, names=True),
                     "name": mask(doc.name, names=True), "kind": doc.suffix.lower().lstrip("."),
                     "read": doc.stem in read})
    return rows


def status() -> dict:
    """What the workspace holds, by counts: tax years, folders, documents, and what has been read from them."""
    home, mask = workspace.home(), masker()
    if not home.is_dir():
        return {"exists": False, "years": [], "folders": [], "documents": 0, "read": {}, "todo": False,
                "message": "No workspace yet: `taxtrace import` creates it, or point TAXTRACE_HOME at one."}
    workspace.outside_git(home)
    folders = []
    for source in workspace.sources():
        docs = text.documents([source])
        if docs:
            name = mask(source.name, names=True) if source.is_dir() else ""
            folders.append({"name": name, "documents": len(docs)})
    read = {folder: n for folder in SAVED if (n := sum(1 for _ in (home / folder).glob("*.json")))}
    years = sorted(s.name for s in workspace.sources() if s.is_dir() and YEAR_FOLDER.fullmatch(s.name))
    rows = listing()
    return {"exists": True, "years": years, "folders": folders, "documents": len(rows),
            "documents_read": sum(r["read"] for r in rows), "saved": read,
            "todo": (home / workspace.TODO).is_file()}


def _document(doc_id: int) -> Path:
    docs = documents()
    if not 1 <= doc_id <= len(docs):
        raise ReviewError(f"no document {doc_id}: list_documents gives ids 1 to {len(docs)}"
                          if docs else "the workspace has no documents")
    return docs[doc_id - 1]


def _pages(doc: Path) -> tuple[list[str], str | None]:
    """A document's pages and password, without asking the Keychain: a locked document raises `text.Locked`."""
    from . import cli

    return cli._unlocked(doc, keychain=False)


def outline(doc_id: int, start: int = 1, limit: int = 40, lines: int = 2) -> dict:
    """A document's pages, each with its first `lines` lines masked: which forms it holds, in order."""
    doc, mask = _document(doc_id), masker()
    try:
        pages, _ = _pages(doc)
    except text.UnsupportedDocument as err:  # a locked one too: Locked is one of these
        return {"id": doc_id, "name": mask(doc.name, names=True), "skipped": mask(str(err)),
                "locked": isinstance(err, text.Locked)}
    shown = range(max(start, 1), min(start + max(min(limit, MAX_PAGES), 1), len(pages) + 1))
    return {"id": doc_id, "name": mask(doc.name, names=True), "pages": len(pages),
            "outline": [{"page": n, "headings": [mask(h) for h in text.headings(pages[n - 1], lines)]}
                        for n in shown]}


def _forms(form: str, doc: Path, pages: list[str], password: str | None, mask: Callable[..., str]) -> list[dict]:
    """The forms of one kind on a document's pages, each as its checks' results: the pass count, and what failed
    or is still a question for the person, masked."""
    from . import f1098, f1099, k1

    found: list[tuple[str, int, int | None, object, list[str]]] = []  # (form, page, year, form object, problems)
    if form == "1098":
        pages_ = [n for n, page in enumerate(pages, 1) if f1098.is_form(page)]
        words = {n: text.words(doc, n, password) for n in pages_}
        found = [("1098", f.page, f.year, f, k1.verify(f, words[f.page])) for f in f1098.read(doc.name, words)]
    elif form == "1099":
        pages_ = [n for n, page in enumerate(pages, 1) if f1099.is_form(page)]
        words = {n: text.words(doc, n, password) for n in pages_}
        found = [(f.form, f.page, f.year, f, k1.verify(f, words[f.page])) for f in f1099.read(doc.name, words)]
    else:
        pages_ = [n for n, page in enumerate(pages, 1) if k1.is_face(page)]
        words = {n: text.words(doc, n, password) for n in pages_}
        found = [("K-1", f.page, f.year, f, k1.verify(f, words[f.page], pages))
                 for f in k1.read(doc.name, words, pages)]
    rows = []
    for name, page, year, f, problems in found:
        failed = [mask(c.what + (f" ({c.quote})" if c.quote else "")) for c in f.failed] + [mask(p) for p in problems]
        rows.append({"form": name, "page": page, "year": year, "checks": len(f.checks),
                     "passed": len(f.checks) - len(f.failed), "failed": failed,
                     "questions": [mask(q.text + (f" ({q.quote})" if q.quote else "")) for q in f.questions],
                     "copy_of_page": f.copy_of, "ok": not failed})
    return rows


def checks(form: str, doc_id: int | None = None) -> dict:
    """Read each document's forms of one kind and report how their checks came out, never the values."""
    if form not in FORMS:
        raise ReviewError(f"form is one of {', '.join(FORMS)}")
    mask = masker()
    docs = documents() if doc_id is None else [_document(doc_id)]
    ids = {doc: n for n, doc in enumerate(documents(), 1)}
    out, skipped, locked = [], 0, 0
    for doc in docs:
        if doc.suffix.lower() not in text.PDF_SUFFIXES:
            continue
        try:
            pages, password = _pages(doc)
        except text.UnsupportedDocument as err:
            skipped += 1
            locked += isinstance(err, text.Locked)
            continue
        for row in _forms(form, doc, pages, password, mask):
            out.append({"id": ids[doc], "name": mask(doc.name, names=True), **row})
    return {"form": form, "forms_found": len(out), "forms_failing": sum(not r["ok"] for r in out),
            "documents_skipped": skipped, "documents_locked": locked, "forms": out}


def todo_list(days: int | None = None) -> dict:
    """The open to-do items by due date with their text masked; with `days`, only the overdue and those due soon."""
    mask = masker()
    workspace.outside_git(workspace.home())
    on = todo.today()
    items = todo.load(on)
    if items is None:
        return {"exists": False, "today": on.isoformat(), "counts": {}, "items": [],
                "message": f"No {workspace.TODO} in the workspace."}
    shown = todo.ordered(items) if days is None else todo.due_within(items, on, days)
    rows = [{"section": mask(i.section), "text": mask(i.text), "due": i.due.isoformat() if i.due else None,
             "days_left": (i.due - on).days if i.due else None, "group": todo.group(i, on),
             "time": mask(i.time), "notes": [mask(n) for n in i.notes],
             "subtasks": [{"text": mask(s["text"]), "done": s["done"]} for s in i.subtasks]} for i in shown]
    return {"exists": True, "today": on.isoformat(),
            "counts": {g: n for g in todo.GROUPS if (n := sum(r["group"] == g for r in rows))}, "items": rows}
