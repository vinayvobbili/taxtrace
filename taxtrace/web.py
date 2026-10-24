"""`taxtrace ui`: a page on this computer, at http://taxtrace.localhost:8766/, showing the workspace and a chat.

It listens on 127.0.0.1 only and answers only requests that carry its own Host name (which stops DNS
rebinding) and, for /api/, the token baked into the page (which stops other pages from calling it).
"""

from __future__ import annotations

import json
import secrets
import socketserver
import sys
import threading
import time
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from urllib.parse import urlparse

from . import __version__, chat, text, workspace

APP_HOST = "taxtrace.localhost"  # browsers and macOS send every *.localhost name to this machine, never the web
PORT = 8766  # jobwatch's is 8765
MAX_BODY = 1_000_000


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
            if not url.path.startswith("/api/"):
                return self._json(HTTPStatus.NOT_FOUND, {"error": "not found"})
            if not secrets.compare_digest(self.headers.get("X-Taxtrace-Token", ""), token):
                return self._json(HTTPStatus.FORBIDDEN, {"error": "missing or wrong token; reload the page"})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    return self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"error": "too large"})
                body = json.loads(self.rfile.read(length) or b"{}") if length else {}
                if method == "GET" and url.path == "/api/status":
                    return self._json(HTTPStatus.OK, {"models": chat.status(settings), "workspace": overview()})
                if method == "POST" and url.path == "/api/chat":
                    messages = chat.clean(body.get("messages"), settings.max_turns)
                    return self._stream(chat.answer(messages, settings))
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
