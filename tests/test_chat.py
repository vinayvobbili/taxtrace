from __future__ import annotations

import http.client
import json
import subprocess
import threading
from pathlib import Path

import pytest

from taxtrace import chat, web, workspace


@pytest.fixture
def docs(workspace_home: Path) -> Path:
    for rel in ("2024/W-2 Quillfeather.pdf", "prior-returns/2023 Return.pdf", "redacted/01-x.txt"):
        (workspace_home / rel).parent.mkdir(parents=True, exist_ok=True)
        (workspace_home / rel).write_bytes(b"%PDF-1.4 made up")
    (workspace_home / workspace.TERMS_FILE).write_text("Jordan\n")
    return workspace_home


@pytest.fixture
def runners(monkeypatch):
    """Fake models: each records what it was sent; `fail` names the ones that can't answer."""
    calls: dict[str, tuple[str, list[dict]]] = {}
    fail: set[str] = set()

    def runner(name):
        def run(system, messages, settings):
            if name in fail:
                raise chat.Unavailable(f"{name} is down")
            calls[name] = (system, messages)
            return iter([f"answer from {name}", {"stats": {"output_tokens": 3}}])
        return run
    monkeypatch.setattr(chat, "RUNNERS", {b: runner(b) for b in chat.BACKENDS})
    return calls, fail


def ask(question: str, history: list[dict] | None = None) -> list:
    return list(chat.answer(chat.clean([*(history or []), {"role": "user", "content": question}])))


def test_a_question_without_values_goes_to_claude_masked(docs, runners):
    calls, _ = runners
    out = ask("What does Quillfeather report on Schedule E line 3 for 2024?")
    assert list(calls) == ["claude"]
    system, sent = calls["claude"]
    assert sent[-1]["content"] == "What does ************ report on Schedule E line 3 for 2024?"
    assert "Quillfeather" not in system and "2024/W-2 ************.pdf" in system  # the document list too
    assert "You are the assistant inside taxtrace" in system and "masked on their computer" in system
    answering = next(p["answering"] for p in out if isinstance(p, dict) and "answering" in p)
    assert answering["backend"] == "claude" and answering["sent"] == sent[-1]["content"]
    assert "answer from claude" in out


def test_each_model_in_turn_until_one_answers(docs, runners):
    calls, fail = runners
    fail.update({"claude"})
    out = ask("When is an FBAR due?")
    assert list(calls) == ["agy"]
    assert {"note": "Claude couldn't answer: claude is down"} in out
    fail.update({"agy", "local"})
    with pytest.raises(chat.Unavailable, match="no model could answer"):
        ask("When is an FBAR due?")


def test_a_question_with_an_amount_or_a_listed_name_stays_on_this_mac_unmasked(docs, runners):
    calls, _ = runners
    out = ask("Is $12,480 of interest from my savings account taxable?")
    assert list(calls) == ["local"]
    system, sent = calls["local"]
    assert sent[-1]["content"].startswith("Is $12,480") and "W-2 Quillfeather.pdf" in system
    assert "never leaves their computer" in system
    assert out[0]["note"].startswith("Your question has an amount")
    assert out[1] == {"offer": "Is $##,### of interest from my savings account taxable?"}
    calls.clear()
    out = list(chat.answer(chat.clean([{"role": "user", "content": "Is $12,480 of interest taxable?"}]), masked=True))
    assert list(calls) == ["claude"] and calls["claude"][1][-1]["content"] == "Is $##,### of interest taxable?"
    assert not any(isinstance(p, dict) and "offer" in p for p in out)
    calls.clear()
    out = ask("Did jordan sign the return?")
    assert list(calls) == ["local"] and "redact-terms.txt" in out[0]["note"]


def test_a_local_answer_is_masked_before_a_later_question_goes_to_the_cloud(docs, runners):
    calls, _ = runners
    history = [{"role": "user", "content": "What was my 2023 interest of $1,234.56 for?"},
               {"role": "assistant", "content": "The $1,234.56 came from Brambleworth Savings."}]
    ask("And which form reports interest?", history)
    sent = calls["claude"][1]
    assert all("1,234" not in m["content"] and "Brambleworth" not in m["content"] for m in sent)


def test_the_document_list_never_holds_what_taxtrace_derived(docs):
    listed = chat.inventory([], masked=False)
    assert "2024/W-2 Quillfeather.pdf" in listed and "redacted" not in listed


def test_clean_keeps_alternating_turns_ending_with_the_user():
    msgs = chat.clean([{"role": "assistant", "content": "hi"}, {"role": "user", "content": "a"},
                       {"role": "user", "content": "b"}])
    assert msgs == [{"role": "user", "content": "a\n\nb"}]
    with pytest.raises(ValueError):
        chat.clean([{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}])


def test_agy_gets_one_prompt_in_an_empty_folder(monkeypatch):
    seen = {}

    def run(args, cwd, **kw):
        seen.update(prompt=args[args.index("-p") + 1], cwd=cwd, files=list(Path(cwd).iterdir()))
        reply = {"status": "SUCCESS", "response": " Form 8938. ", "usage": {"input_tokens": 9, "output_tokens": 2}}
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(reply), stderr="")
    monkeypatch.setattr(chat, "find_agy", lambda: "/bin/agy")
    monkeypatch.setattr(chat.subprocess, "run", run)
    pieces = list(chat._agy("Rules.", [{"role": "user", "content": "Which form?"}], chat.Settings()))
    assert pieces[0] == "Form 8938." and pieces[1]["stats"]["output_tokens"] == 2
    assert seen["prompt"] == "Rules.\n\n---\n\nUser: Which form?\n\nAssistant:" and seen["files"] == []


def test_agy_quota_is_a_reason_to_try_the_next_model(monkeypatch):
    monkeypatch.setattr(chat, "find_agy", lambda: "/bin/agy")
    monkeypatch.setattr(chat.subprocess, "run", lambda args, **kw: subprocess.CompletedProcess(
        args, 1, stdout="", stderr="quota exhausted"))
    with pytest.raises(chat.Unavailable, match="quota exhausted"):
        chat._agy("Rules.", [{"role": "user", "content": "Which form?"}], chat.Settings())


@pytest.fixture
def server(docs, runners):
    srv = web.serve(0, open_browser=False, token="t0ken")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def request(srv, method, path, body=None, host=None, token="t0ken"):
    port = srv.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Host": host or f"{web.APP_HOST}:{port}", "X-Taxtrace-Token": token, "Content-Type": "application/json"}
    conn.request(method, path, body=json.dumps(body) if body is not None else None, headers=headers)
    r = conn.getresponse()
    return r.status, r.read().decode()


def test_the_page_answers_its_own_name_only_and_the_api_wants_the_token(server):
    port = server.server_address[1]
    assert server.url == f"http://taxtrace.localhost:{port}/"
    status, html = request(server, "GET", "/")
    assert status == 200 and "t0ken" in html and "__TAXTRACE_TOKEN__" not in html
    assert request(server, "GET", "/", host=f"other.localhost:{port}")[0] == 403
    status, icon = request(server, "GET", "/icon.svg", token="")
    assert status == 200 and icon.startswith("<svg")
    assert request(server, "GET", "/api/status", token="wrong")[0] == 403


def test_status_lists_the_models_in_order_and_the_workspace(server):
    status, body = request(server, "GET", "/api/status")
    data = json.loads(body)
    assert status == 200
    assert [m["backend"] for m in data["models"]] == ["claude", "agy", "local"]
    assert {f["name"]: f["documents"] for f in data["workspace"]["folders"]} == {
        "2024": ["W-2 Quillfeather.pdf"], "prior-returns": ["2023 Return.pdf"]}


def test_the_chat_streams_one_json_object_per_line(server):
    status, body = request(server, "POST", "/api/chat", {"messages": [{"role": "user", "content": "Due date?"}]})
    events = [json.loads(line) for line in body.splitlines()]
    assert status == 200 and events[0]["answering"]["backend"] == "claude"
    assert {"text": "answer from claude"} in events and events[-1]["done"] and events[-1]["stats"]["output_tokens"] == 3
    assert request(server, "POST", "/api/chat", {"messages": []})[0] == 400
