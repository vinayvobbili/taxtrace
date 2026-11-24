"""`taxtrace ui`: a page on this computer, at http://taxtrace.localhost:8766/, showing the workspace and a chat.

It listens on 127.0.0.1 only and answers only requests that carry its own Host name (which stops DNS
rebinding) and, for /api/, the token baked into the page (which stops other pages from calling it). Documents
picked on the Import screen are uploaded to this server alone, and filed the way `taxtrace import` files them.
"""

from __future__ import annotations

import json
import re
import secrets
import socketserver
import sys
import tempfile
import threading
import time
import webbrowser
from datetime import date
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path, PurePosixPath
from urllib.parse import parse_qs, urlparse

from . import __version__, budget, budget_demo, chat, cli, entry, importer, text, todo, workspace

APP_HOST = "taxtrace.localhost"  # browsers and macOS send every *.localhost name to this machine, never the web
PORT = 8766  # jobwatch's is 8765
MAX_BODY = 1_000_000
MAX_UPLOAD = 200_000_000  # one document (or a portal's zip) sent to /api/import, from this computer to this server
# What the page links to besides itself, for the tab and for installing it as an app (see scripts/make_icons.py)
STATIC = {"icon.svg": "image/svg+xml", "icon-192.png": "image/png", "icon-512.png": "image/png",
          "icon-maskable-512.png": "image/png", "apple-touch-icon.png": "image/png",
          "manifest.webmanifest": "application/manifest+json"}


def page(token: str) -> bytes:
    html = resources.files("taxtrace").joinpath("static/index.html").read_text(encoding="utf-8")
    return html.replace("__TAXTRACE_TOKEN__", token).replace("__TAXTRACE_VERSION__", __version__).encode()


def overview() -> dict:
    """The workspace's folders and the documents in each, for the page (on this computer only)."""
    root = workspace.home()
    folders = []
    for source in workspace.sources():
        docs = text.documents([source])
        if source.is_dir():
            folders.append({"name": source.name, "documents": [str(d.relative_to(source)) for d in docs]})
        elif docs:
            folders.append({"name": "", "documents": [source.name]})
    return {"path": str(root), "exists": root.is_dir(), "folders": folders,
            "documents": sum(len(f["documents"]) for f in folders)}


def plans() -> dict:
    """The latest year's moves, with its job change and stock sales, as those commands last saved them."""
    root = workspace.home()
    saved = {folder: {p.stem: p for p in (root / folder).glob("*.json") if p.stem.isdigit()}
             for folder in (workspace.MOVES, workspace.JOBCHANGE, workspace.SALES)}
    year = max((y for paths in saved.values() for y in paths), default=None)
    return {"year": int(year) if year else None,
            **{folder: json.loads(paths[year].read_text()) if year in paths else None
               for folder, paths in saved.items()}}


STOP_WORDS = {"form", "forms", "year", "last", "entry", "what", "adjusted", "gross", "income", "status", "filing",
              "check", "checks", "other", "about", "their", "which", "where", "ending", "payer", "account", "accounts"}
FORM_ROOTS = re.compile(r"\b(?:W-?2|1099|1098|K-?[13]|8949|8938|8582|8995|1116|FBAR|D-?40[03]|Schedule [A-E])\b", re.I)


def _keywords(text_: str) -> set[str]:
    """What a to-do item would have to mention to be about a section or an item of the sheet: its forms (1099-INT
    and 1099-DIV both give 1099) and its names and topics (Initech, Umbrella, wages), without the filler words."""
    forms = {re.sub(r"[-\s]", "", m).lower() for m in FORM_ROOTS.findall(text_)}
    return forms | {w for w in re.findall(r"[A-Za-z]{5,}", text_.lower()) if w not in STOP_WORDS}


def _mentions(item: dict, words: set[str]) -> bool:
    hay = " ".join([item["text"], *item["notes"]]).lower()
    squeezed = re.sub(r"[-\s]", "", hay)  # "W-2" and "w2" are the same form
    return any(w in (squeezed if w[0].isdigit() or len(w) < 5 else hay) for w in words)


def entry_years(home: Path) -> list[int]:
    """The tax years with documents or saved results in the workspace."""
    years = {int(p.name) for p in home.glob("[0-9][0-9][0-9][0-9]") if p.is_dir()}
    for folder in (workspace.ENTRY, workspace.SALES, workspace.MOVES, workspace.SCHEDULE_E, workspace.ESTIMATES):
        years |= {int(p.stem) for p in (home / folder).glob("[0-9][0-9][0-9][0-9].json")}
    years |= {int(r["year"]) for r in [*cli._forms(home), *cli._k1s(home)] if str(r.get("year", "")).isdigit()}
    return sorted(years)


def entry_screen(year: int | None = None) -> dict:
    """A year's entry sheet for the page: `taxtrace entry`'s rows with their values, from what the other commands
    saved (nothing is read from a document or written here), each section with the to-do items that mention it."""
    home = workspace.home()
    years = entry_years(home)
    year = year or (years[-1] if years else date.today().year)
    kept = home / workspace.ENTRY / f"{year}-expected.json"
    sheet = cli.entry_sheet(home, year, json.loads(kept.read_text()) if kept.exists() else [])
    on = todo.today()
    items = todo.to_json(todo.load(on) or [], on)

    def related(label: str) -> list[dict]:
        words = _keywords(label)
        return [{"line": i["line"], "title": i["title"], "group": i["group"]} for i in items if _mentions(i, words)]

    out = sheet.to_json()
    for section, data in zip(sheet.sections, out["sections"], strict=True):
        data["counts"] = {s: section.count(s) for s in (entry.READY, entry.ESTIMATE, entry.MISSING)}
        data["todo"] = related(section.title) if section.count(entry.MISSING) or section.count(entry.ESTIMATE) else []
    out["coming"] = [{"text": c, "todo": related(c)} for c in sheet.coming]
    file = home / workspace.ENTRY / f"{year}.txt"
    return {**out, "years": sorted({*years, year}), "counts": {s: sheet.count(s) for s in
            (entry.READY, entry.ESTIMATE, entry.MISSING)}, "yourself": entry.YOURSELF, "coming_note": entry.COMING_NOTE,
            "file": str(file) if file.exists() else None, "open_todo": len(items)}


def _budget(demo: bool, today: date | None = None):
    """The plan, rules and months the Budget tab shows: the workspace's budget folder, or the made-up household."""
    if demo:
        return budget_demo.demo(today)
    folder = workspace.home() / workspace.BUDGET
    plan = budget.load_plan(folder)
    if plan is None:
        return None
    return plan, budget.load_rules(folder, plan), budget.load_actuals(folder)


def budget_view(asked: str) -> str | None:
    """A view the page asked for: "ytd", a month, or nothing (the default)."""
    if asked and asked != "ytd":
        budget.month_key(asked)
    return asked or None


def budget_screen(view: str | None = None, demo: bool = False, today: date | None = None) -> dict:
    """The Budget tab: each line's budget against what was spent, for a month or the year to date, from
    <workspace>/budget/ (nothing is written by looking), or the made-up household's with `demo`."""
    folder = workspace.home() / workspace.BUDGET
    found = _budget(demo, today)
    if found is None:
        return {"source": "none", "folder": str(folder), "exists": folder.is_dir()}
    data = budget.status(*found, view, today)
    return {**data, "source": "demo" if demo else "workspace", "folder": None if demo else str(folder)}


def budget_payments(view: str | None, name: str, demo: bool = False, today: date | None = None) -> dict:
    """The transactions behind one line, sub-line or fund (or the unmatched or left-out rows), for the page's
    "Payments behind this number", with their count and the total that the card's Spent figure shows."""
    found = _budget(demo, today)
    if found is None:
        return {"payments": [], "count": 0, "total": 0}
    view = view or budget.default_view(found[0], found[2], today or date.today())
    rows = budget.payments(*found, view, name, today)
    return {"payments": rows, "count": len(rows), "total": budget.payments_total(rows, name)}


def upload_name(name: str) -> PurePosixPath:
    """A dropped file's name as the browser gives it ("2025 TAX/W-2.pdf" for one inside a folder), made safe to
    stage: relative, no `..`, no empty parts."""
    path = PurePosixPath(name.replace("\\", "/"))
    if not path.parts or path.is_absolute() or any(p in ("", ".", "..") for p in path.parts) or len(path.parts) > 12:
        raise ValueError("that file name can't be imported")
    return path


def import_upload(name: str, data: bytes, dry_run: bool = False, year: str | None = None) -> list[dict]:
    """File one uploaded document (or zip, or a file from a dropped folder) the way `taxtrace import` does, and say
    what taxtrace made of each file it holds. `dry_run` only reports. The upload is staged in a temporary folder that
    is removed afterwards, and goes nowhere else."""
    if year and not re.fullmatch(r"20\d\d", year):
        raise ValueError("the tax year is four digits, such as 2026")
    rel = upload_name(name)
    home = workspace.outside_git(workspace.home())
    with tempfile.TemporaryDirectory(prefix="taxtrace-upload-") as tmp:
        staged = Path(tmp, *rel.parts)
        staged.parent.mkdir(parents=True, exist_ok=True)
        staged.write_bytes(data)
        # a folder's own name leads its files' names, as it does for `taxtrace import <folder>`
        placed = importer.import_documents(Path(tmp, rel.parts[0]), home, dry_run=dry_run, year=year)
    terms = workspace.redact_terms()
    return [{**importer.describe(p, terms), "filed": bool(p.dest) and not dry_run} for p in placed]


def make_handler(settings: chat.Settings, token: str, port_ref: list[int]):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):  # quiet: the terminal shows only errors
            pass

        def _send(self, status: int, body: bytes, ctype: str):
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data):
            self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8")

        def _host_ok(self) -> bool:
            return self.headers.get("Host", "") in {f"{h}:{port_ref[0]}" for h in ("127.0.0.1", "localhost", APP_HOST)}

        def _stream(self, pieces):
            """The reply as it's written, one JSON object per line: {"note"} and {"answering"} as they happen,
            {"text"} pieces, then {"done", "stats"} or {"error"}."""
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.close_connection = True

            def line(obj):
                self.wfile.write(json.dumps(obj, ensure_ascii=False).encode() + b"\n")
                self.wfile.flush()
            start, stats = time.monotonic(), {}
            try:
                for piece in pieces:
                    if isinstance(piece, dict):
                        if "stats" in piece:
                            stats.update(piece["stats"])
                        else:
                            line(piece)
                    else:
                        line({"text": piece})
                line({"done": True, "stats": {**stats, "seconds": round(time.monotonic() - start, 1)}})
            except (BrokenPipeError, ConnectionResetError):
                pass  # the page stopped the reply or went away
            except Exception as e:
                print(f"taxtrace ui: chat: {type(e).__name__}: {e}", file=sys.stderr)
                try:
                    line({"error": str(e) if isinstance(e, chat.Unavailable) else f"{type(e).__name__}: {e}"})
                except OSError:
                    pass
            finally:
                if hasattr(pieces, "close"):
                    pieces.close()

        def _handle(self, method: str):
            if not self._host_ok():
                return self._json(HTTPStatus.FORBIDDEN, {"error": "unexpected Host"})
            url = urlparse(self.path)
            if method == "GET" and url.path in ("/", "/index.html"):
                return self._send(HTTPStatus.OK, page(token), "text/html; charset=utf-8")
            name = "icon.svg" if url.path == "/favicon.ico" else url.path.lstrip("/")
            if method == "GET" and name in STATIC:  # icons and the manifest: the browser asks without the token
                body = resources.files("taxtrace").joinpath(f"static/{name}").read_bytes()
                return self._send(HTTPStatus.OK, body, STATIC[name])
            if not url.path.startswith("/api/"):
                return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            if not secrets.compare_digest(self.headers.get("X-Taxtrace-Token", ""), token):
                return self._json(HTTPStatus.FORBIDDEN, {"error": "missing or wrong token; reload the page"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                upload = method == "POST" and url.path == "/api/import"
                if length > (MAX_UPLOAD if upload else MAX_BODY):
                    self.close_connection = True  # its body is left unread
                    return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "too large"})
                if upload:  # one file's bytes, named in the query; the reply says what became of each file in it
                    query = parse_qs(url.query)
                    results = import_upload((query.get("name") or [""])[0], self.rfile.read(length),
                                            dry_run=(query.get("dry") or [""])[0] == "1",
                                            year=(query.get("year") or [""])[0] or None)
                    return self._json(HTTPStatus.OK, {"results": results})
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                if method == "GET" and url.path == "/api/status":
                    return self._json(HTTPStatus.OK, {"models": chat.status(settings), "workspace": overview()})
                if method == "GET" and url.path == "/api/todo":
                    on = todo.today()
                    items = todo.load(on)
                    return self._json(HTTPStatus.OK, {"items": todo.to_json(items or [], on),
                                                      "path": str(todo.path()), "exists": items is not None})
                if method == "GET" and url.path == "/api/moves":
                    return self._json(HTTPStatus.OK, plans())
                if method == "GET" and url.path == "/api/entry":
                    asked = (parse_qs(url.query).get("year") or [""])[0]
                    if asked and not re.fullmatch(r"20\d\d", asked):
                        raise ValueError("the tax year is four digits, such as 2026")
                    return self._json(HTTPStatus.OK, entry_screen(int(asked) if asked else None))
                if method == "GET" and url.path in ("/api/budget", "/api/budget/payments"):
                    query = parse_qs(url.query)
                    view = budget_view((query.get("view") or [""])[0])
                    demo = (query.get("demo") or [""])[0] == "1"
                    if url.path == "/api/budget":
                        return self._json(HTTPStatus.OK, budget_screen(view, demo))
                    return self._json(HTTPStatus.OK, budget_payments(view, (query.get("line") or [""])[0], demo))
                if method == "POST" and url.path == "/api/todo/done":
                    line, expect = int(body.get("line", 0)), str(body.get("text", ""))
                    try:
                        todo.mark_done(todo.path(), line, expect)
                    except FileNotFoundError:
                        return self._json(HTTPStatus.CONFLICT, {"error": "todo.md is gone. Reload the page."})
                    except ValueError as e:  # the line changed since the page loaded
                        return self._json(HTTPStatus.CONFLICT, {"error": str(e)})
                    return self._json(HTTPStatus.OK, {"ok": True})
                if method == "POST" and url.path == "/api/chat":
                    messages = chat.clean(body.get("messages"), settings.max_turns)
                    return self._stream(chat.answer(messages, settings, masked=body.get("masked") is True))
                return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            except (ValueError, workspace.InsideGitRepo) as e:
                return self._json(HTTPStatus.BAD_REQUEST, {"error": str(e)})

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

    return Handler


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # HTTPServer looks up the host's full DNS name here, which can take seconds; it isn't needed.
        socketserver.TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


def serve(port: int = PORT, open_browser: bool = True, settings: chat.Settings | None = None,
          token: str | None = None) -> ThreadingHTTPServer:
    """Start the server (port 0 picks a free one); call serve_forever() on the result. Its `url` is the page's."""
    token = token or secrets.token_urlsafe(24)
    port_ref = [port]
    server = _Server(("127.0.0.1", port), make_handler(settings or chat.Settings(), token, port_ref))
    port_ref[0] = server.server_address[1]
    server.url = f"http://{APP_HOST}:{port_ref[0]}/"
    print(f"taxtrace is running at {server.url}  (workspace: {workspace.home()}). Press Ctrl+C to stop.",
          file=sys.stderr)
    if open_browser:
        threading.Timer(0.3, webbrowser.open, (server.url,)).start()
    return server
