"""Ask about your return in plain words, on the page `taxtrace ui` serves.

Three models, tried in order until one answers:

- claude: Anthropic's API (pip install 'taxtrace[chat]'), with ANTHROPIC_API_KEY or a macOS Keychain item
  holding the key.
- agy: Google's Antigravity CLI, on its subscription's quota.
- local: a model on this Mac, behind any OpenAI-compatible server at http://127.0.0.1:8010/v1 (LOCAL_LLM_URL
  points elsewhere on this computer): vllm-mlx, mlx_lm.server, LM Studio. One server holds the one copy of the
  model and queues every program's requests, so taxtrace never loads a model itself.

Claude and agy only ever see masked text. Before anything is sent to them, the instructions, the workspace
listing and every message of the conversation go through the same masking `taxtrace redact` uses: digits
become #, and names, streets and towns become runs of *. A question that holds one of your values (an amount,
or a word from redact-terms.txt) isn't sent to them at all: the local model answers it, and the page says why.

The chat reads only what it's given and has no tools: it can't open a document, change a file or file anything.
"""

from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

from . import redact, text, workspace

BACKENDS = ("claude", "agy", "local")  # the default order: the strongest model first, this Mac's last
LABELS = {"claude": "Claude", "agy": "Antigravity (agy)", "local": "On this Mac"}
CLOUD = {"claude", "agy"}
KEYCHAIN = "anthropic"  # the Keychain item (its service name) holding the Anthropic API key
LOCAL_URL = "http://127.0.0.1:8010/v1"  # the local model server, unless LOCAL_LLM_URL names another
LOOPBACK = {"127.0.0.1", "localhost", "::1"}  # the local model gets unmasked data, so its server must be here
# Where agy's installer and Homebrew put it: a launchd service's PATH has neither.
AGY_PLACES = ("~/.local/bin/agy", "/opt/homebrew/bin/agy", "/usr/local/bin/agy")
MAX_MESSAGE = 8000
MAX_LISTED = 200  # documents named in the instructions; the rest are counted

SYSTEM = """You are the assistant inside taxtrace, a tool that prepares the user's US federal and state income \
tax return from their own documents, on their own computer. Help them understand tax rules and forms, what each \
of their documents is for, and what to check or ask before they enter the return.

Rules:
- For a tax rule, name the form, line, schedule or IRS publication it comes from and the tax year it applies \
to. If the answer turns on facts you don't have, say which.
- Facts about the user come only from the data below and their messages. Never invent amounts, documents or \
circumstances.
- A judgment call (an election, a repair or an improvement, which year something belongs to) is the user's: \
lay out the options and what each needs, and leave the choice to them.
- You can't open documents, change files or file anything. Say so if asked.
- Earlier answers in the conversation may have come from a much smaller model on the user's computer, not \
from you. If one of them is wrong, say what's wrong and why, without calling it your own.
- {masking}
- Be concise and concrete: short paragraphs or bullets.

Today is {today}.

{context}"""

MASKED = ("Everything below and in the user's messages has been masked on their computer before reaching you: # "
          "stands for a digit and a run of * for a word that could identify someone (a name, a street, a town). "
          "Work with what's left, and never guess what was masked. If a question needs the real values, say "
          "that the model on their Mac can answer it.")
UNMASKED = "The data below is the user's own and unmasked: it never leaves their computer."


class Unavailable(RuntimeError):
    """A model can't answer here (not installed, no key, quota used up): the next one in the order is tried."""


@dataclass
class Settings:
    order: tuple[str, ...] = BACKENDS
    keychain: str = KEYCHAIN
    claude_model: str = "claude-sonnet-5-5"  # quick, conversational replies
    agy_model: str = "claude-sonnet-5-5-medium"  # `agy models` lists the ids
    local_url: str = ""  # "": LOCAL_LLM_URL, or LOCAL_URL. The server picks the model.
    max_tokens: int = 1500
    max_turns: int = 24  # the most recent messages sent with each question
    agy_timeout: float = 180.0
    local_timeout: float = 900.0  # a question can wait in the server's line behind other programs

    def model(self, backend: str) -> str:
        return {"claude": self.claude_model, "agy": self.agy_model, "local": "the local model server"}[backend]

    def server(self) -> str:
        return (self.local_url or os.environ.get("LOCAL_LLM_URL") or LOCAL_URL).rstrip("/")


def clean(messages, turns: int = Settings.max_turns) -> list[dict]:
    """The conversation from the page, its last `turns` messages: alternating user and assistant turns, ending
    with the user's."""
    if not isinstance(messages, list) or not messages:
        raise ValueError("send messages: [{role, content}, ...]")
    out: list[dict] = []
    for m in messages[-turns:]:
        if not (isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)):
            raise ValueError("each message needs a role (user or assistant) and text content")
        body = m["content"].strip()[:MAX_MESSAGE]
        if not body:
            continue
        if out and out[-1]["role"] == m["role"]:
            out[-1]["content"] += "\n\n" + body
        else:
            out.append({"role": m["role"], "content": body})
    while out and out[0]["role"] != "user":
        out.pop(0)
    if not out or out[-1]["role"] != "user":
        raise ValueError("the last message must be the user's")
    return out


def mask(body: str, terms: list[str]) -> str:
    """What a cloud model is sent in place of `body`. A year on its own is kept: in a question it's a tax year."""
    return redact.redact(body, terms, bare_years=True).text


def private_reason(question: str, terms: list[str]) -> str:
    """Why `question` stays on this Mac (it holds an amount or a configured name), or "" when masking it loses
    nothing of yours."""
    if redact.redact(question, terms, bare_years=True).numbers_masked:
        return "Your question has an amount or account number in it, so the model on this Mac answers it."
    if redact.mask_terms(question, terms) != question:
        return "Your question names someone from redact-terms.txt, so the model on this Mac answers it."
    return ""


def inventory(terms: list[str], masked: bool) -> str:
    """The workspace's documents, folder by folder: masked for a cloud model, as they are for the local one.
    Names only: nothing is opened, so no password is asked for."""
    root = workspace.home()
    docs = text.documents(workspace.sources())
    if not docs:
        return "## The user's documents\nNone in the workspace yet (taxtrace import adds them)."
    lines = [f"## The user's documents ({len(docs)}, by folder)"]
    for doc in docs[:MAX_LISTED]:
        rel = str(doc.relative_to(root)) if doc.is_relative_to(root) else doc.name
        lines.append("- " + (redact.redact(rel, terms, bare_years=True).text if masked else rel))
    if len(docs) > MAX_LISTED:
        lines.append(f"- …and {len(docs) - MAX_LISTED} more")
    return "\n".join(lines)


def system_prompt(context: str, masked: bool, today: date | None = None) -> str:
    return SYSTEM.format(masking=MASKED if masked else UNMASKED, today=(today or date.today()).isoformat(),
                         context=context.strip())


def answer(messages: list[dict], settings: Settings | None = None, masked: bool = False) -> Iterator[str | dict]:
    """The reply in pieces as it's written, from the first model in the order that can answer. Dicts along the
    way: {"note"} when a model is skipped and why, {"answering"} once one starts (which, its model, and for a cloud
    model the masked question it was sent), and {"stats"} at the end.

    A question holding the user's values goes to the model on this Mac, with {"offer"}: the question as a cloud
    model would get it. The local model is far smaller, so the page offers to ask again with `masked`: the
    question then goes down the whole order, its values masked like everything else a cloud model is sent."""
    settings = settings or Settings()
    terms = workspace.redact_terms()
    question = messages[-1]["content"]
    why_local = "" if masked else private_reason(question, terms)
    order = ("local",) if why_local else tuple(b for b in settings.order if b in RUNNERS)
    if why_local:
        yield {"note": why_local}
        if any(b in CLOUD for b in settings.order):
            yield {"offer": mask(question, terms)}
    skipped: list[str] = []
    for backend in order:
        cloud = backend in CLOUD
        sent = [{"role": m["role"], "content": mask(m["content"], terms)} for m in messages] if cloud else messages
        system = system_prompt(inventory(terms, masked=cloud), masked=cloud)  # the user's data in it: the list
        try:
            pieces = RUNNERS[backend](system, sent, settings)
            first = next(pieces, "")
        except Exception as e:  # nothing written yet, so the next model can still take the whole question
            why = str(e) if isinstance(e, Unavailable) else f"{type(e).__name__}: {e}"
            skipped.append(f"{LABELS[backend]}: {why}.")
            yield {"note": f"{LABELS[backend]} couldn't answer: {why}"}
            continue
        yield {"answering": {"backend": backend, "label": LABELS[backend], "model": settings.model(backend),
                             "local": not cloud, **({"sent": sent[-1]["content"]} if cloud else {})}}
        if first:
            yield first
        yield from pieces
        return
    raise Unavailable("no model could answer. " + " ".join(skipped))


# -- the models

def api_key(item: str) -> str:
    """The Anthropic API key: ANTHROPIC_API_KEY, or the Keychain item `item`. Kept in this process only."""
    if key := os.environ.get("ANTHROPIC_API_KEY"):
        return key
    if sys.platform != "darwin" or not item:
        raise Unavailable("set ANTHROPIC_API_KEY before taxtrace ui")
    from . import gate

    if gate.adopted(item, ""):  # Apple Watch or Touch ID approves the read
        key = gate.read(item, "", "read the Anthropic API key for the taxtrace chat") or ""
    else:
        r = subprocess.run(["security", "find-generic-password", "-s", item, "-w"], capture_output=True, text=True)
        key = "" if r.returncode else r.stdout
    if not key.strip():
        raise Unavailable(f"no API key in the Keychain item {item!r}, or its read wasn't approved: add one with "
                          f"security add-generic-password -s {item} -a \"$USER\" -w")
    os.environ["ANTHROPIC_API_KEY"] = key.strip()
    return os.environ["ANTHROPIC_API_KEY"]


def _claude(system: str, messages: list[dict], settings: Settings) -> Iterator[str | dict]:
    try:
        import anthropic
    except ImportError:
        raise Unavailable("needs: pip install 'taxtrace[chat]'") from None
    client = anthropic.Anthropic(api_key=api_key(settings.keychain))
    return _claude_pieces(client.messages.stream(model=settings.claude_model, max_tokens=settings.max_tokens,
                                                 system=system, messages=messages))


def _claude_pieces(manager) -> Iterator[str | dict]:
    with manager as stream:  # the request goes out here: a bad key or an overload fails before any text
        yield from stream.text_stream
        usage = stream.get_final_message().usage
        yield {"stats": {"input_tokens": usage.input_tokens, "output_tokens": usage.output_tokens}}


def find_agy() -> str | None:
    if found := shutil.which("agy"):
        return found
    for place in AGY_PLACES:
        p = Path(place).expanduser()
        if p.is_file() and os.access(p, os.X_OK):
            return str(p)
    return None


def transcript(system: str, messages: list[dict]) -> str:
    """One prompt for a model that takes no system prompt or turns: the instructions, then the conversation."""
    turns = "\n\n".join(f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}" for m in messages)
    return f"{system}\n\n---\n\n{turns}\n\nAssistant:"


def _agy(system: str, messages: list[dict], settings: Settings) -> Iterator[str | dict]:
    exe = find_agy()
    if not exe:
        raise Unavailable("the Antigravity CLI (agy) isn't installed")
    args = [exe, "-p", transcript(system, messages), "--output-format", "json", "--model", settings.agy_model,
            "--sandbox", "--disable-slash-commands", "--print-timeout", f"{max(int(settings.agy_timeout) - 10, 10)}s"]
    with tempfile.TemporaryDirectory(prefix="agy-") as empty:  # nothing of the user's for it to read
        try:
            done = subprocess.run(args, cwd=empty, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                  timeout=settings.agy_timeout)
        except subprocess.TimeoutExpired:
            raise Unavailable(f"no answer within {settings.agy_timeout:g}s") from None
        except OSError as e:
            raise Unavailable(f"couldn't start: {e}") from e
    try:
        reply = json.loads(done.stdout or "")
    except ValueError:
        reply = None
    if done.returncode or not isinstance(reply, dict) or reply.get("status") != "SUCCESS":
        detail = (done.stderr or done.stdout or "no output").strip()[:300]
        raise Unavailable(f"exit {done.returncode}: {detail}")
    used = reply.get("usage") or {}
    return iter([str(reply.get("response") or "").strip(),
                 {"stats": {"input_tokens": int(used.get("input_tokens") or 0),
                            "output_tokens": int(used.get("output_tokens") or 0)}}])


def local_problem(url: str) -> str:
    """Why `url` can't be the local model's server, or "". It gets the user's values unmasked, so it must be on
    this computer."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return f"the local model server's address {url!r} isn't a URL"
    if parts.hostname not in LOOPBACK:
        return f"the local model server must be on this computer (127.0.0.1 or localhost), not {parts.hostname}"
    return ""


def local_answering(url: str) -> bool:
    """Whether a server answers at `url` (its model list, which never loads a model)."""
    try:
        with urllib.request.urlopen(f"{url}/models", timeout=2) as reply:
            return reply.status == 200
    except (OSError, ValueError):
        return False


def _server_says(e: urllib.error.HTTPError) -> str:
    try:
        body = json.loads(e.read() or b"{}")
    except ValueError:
        body = {}
    error = body.get("error") if isinstance(body, dict) else None
    message = error.get("message") if isinstance(error, dict) else error or (body.get("detail") if body else "")
    return str(message or e.reason).strip()[:300]


def _local(system: str, messages: list[dict], settings: Settings) -> Iterator[str | dict]:
    """The local model server, streamed. It names the model itself; the request only turns thinking off, which a
    template without that switch ignores."""
    url = settings.server()
    if problem := local_problem(url):
        raise Unavailable(problem)
    body = {"model": "local", "messages": [{"role": "system", "content": system}, *messages],
            "max_tokens": settings.max_tokens, "stream": True, "stream_options": {"include_usage": True},
            "chat_template_kwargs": {"enable_thinking": False}}
    request = urllib.request.Request(f"{url}/chat/completions", json.dumps(body).encode(),
                                     {"Content-Type": "application/json"})
    began = time.monotonic()
    try:
        reply = urllib.request.urlopen(request, timeout=settings.local_timeout)
    except urllib.error.HTTPError as e:
        raise Unavailable(f"the local model server answered {e.code}: {_server_says(e)}") from None
    except (OSError, ValueError) as e:
        why = getattr(e, "reason", e)
        raise Unavailable(f"no local model server at {url} ({why}); start one there, or set LOCAL_LLM_URL") from None
    return _local_pieces(reply, began)


def _local_pieces(reply, began: float) -> Iterator[str | dict]:
    """Text from the server's events (`data: {...}` lines) as it comes, then the token counts."""
    used: dict = {}
    with reply:
        for raw in reply:
            line = raw.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if data == "[DONE]":
                break
            chunk = json.loads(data)
            if chunk.get("error"):
                raise Unavailable(f"the local model server stopped: {chunk['error']}")
            used = chunk.get("usage") or used
            for choice in chunk.get("choices") or ():
                if piece := (choice.get("delta") or {}).get("content"):
                    yield piece
    output = int(used.get("completion_tokens") or 0)
    seconds = time.monotonic() - began
    yield {"stats": {"input_tokens": int(used.get("prompt_tokens") or 0), "output_tokens": output,
                     **({"tokens_per_sec": round(output / seconds, 1)} if output and seconds > 0 else {})}}


RUNNERS: dict[str, Callable[[str, list[dict], Settings], Iterator[str | dict]]] = {
    "claude": _claude, "agy": _agy, "local": _local}


def status(settings: Settings | None = None) -> list[dict]:
    """Each model in the order, whether it looks ready and why not. Only looks: no key is read and no model is
    asked anything (the local server is asked only for its model list)."""
    settings = settings or Settings()
    out = []
    for backend in settings.order:
        why = ""
        if backend == "claude":
            if importlib_missing("anthropic"):
                why = "needs: pip install 'taxtrace[chat]'"
            elif not os.environ.get("ANTHROPIC_API_KEY") and not keychain_has(settings.keychain):
                why = f"no ANTHROPIC_API_KEY, and no Keychain item {settings.keychain!r}"
        elif backend == "agy":
            why = "" if find_agy() else "the Antigravity CLI (agy) isn't installed"
        elif backend == "local":
            url = settings.server()
            why = local_problem(url) or ("" if local_answering(url) else f"no local model server answers at {url}")
        out.append({"backend": backend, "label": LABELS[backend], "model": settings.model(backend),
                    "cloud": backend in CLOUD, "ready": not why, "why": why})
    return out


def importlib_missing(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is None
    except (ImportError, ValueError):
        return True


def keychain_has(item: str) -> bool:
    """Whether the Keychain holds `item`, asked without -w: its attributes only, so macOS doesn't prompt."""
    if sys.platform != "darwin" or not item:
        return False
    return subprocess.run(["security", "find-generic-password", "-s", item], capture_output=True).returncode == 0
