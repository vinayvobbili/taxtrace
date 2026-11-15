"""The videos' stories: each scene's narration and what the mouse does while it is said.

Short, plain sentences. The page (`taxtrace ui`) comes first; a command's own output shows in a terminal window only
where the page has nothing to show (reading a form, the entry sheet, the layout). The windows hold what the real
commands printed on the made-up household (demo.py): nothing in them is typed in by hand but the command line.
"""

from __future__ import annotations

import asyncio
import json
import re
from concurrent.futures import ThreadPoolExecutor

import cards
from common import TAGLINE, Demo, Scene, Video  # noqa: F401  (TAGLINE is part of the story, re-exported)

ASK_CLOUD = "I live in Boulder and my employer is Initech. Which form shows my wages for 2026?"
ASK_LOCAL = "My wages were 120,000 dollars. Is box 1 right?"
IMPORT_COMMAND = "taxtrace import '~/Downloads/2026 TAX' '~/Downloads/2025 TAX'"


# -- finding things on the page ---------------------------------------------------------------------------------------

def folder(rec, name: str):
    return rec.page.locator(".folder", has_text=name).first


def line(rec, text: str):
    """A line of a terminal window by what it says."""
    return rec.page.locator(".ln", has_text=text).first


def light(rec, *texts: str, hold: float = 1.0, point: bool = True) -> None:
    """Point at each line in turn and give it a glow, one at a time."""
    for text in texts:
        target = line(rec, text)
        rec.page.evaluate("() => document.querySelectorAll('.ln.hl').forEach(l => l.classList.remove('hl'))")
        target.evaluate("l => l.classList.add('hl')")
        if point:
            rec.scroll_to(target, margin=140)
            rec.point_at(target, where=(0.5, 0.5))
        rec.hold(hold)


def wait_for_answer(rec) -> None:
    """The chat has finished writing its reply (the button reads Send again)."""
    rec.page.wait_for_function("document.getElementById('send').textContent === 'Send'", timeout=20000)
    rec.hold(0.8)


def ask(rec, question: str) -> None:
    rec.click("#input", after=0.3)
    rec.type("#input", question, delay=0.03, after=0.5)
    rec.click("#send", after=0.4)
    wait_for_answer(rec)


def open_chat(rec) -> None:
    rec.click("#fab", after=0.9)


def show_sent(rec) -> None:
    rec.click("details.sent summary", after=1.4)


# -- the page ---------------------------------------------------------------------------------------------------------

def overview(rec, d: Demo) -> None:
    """The top of the page: what the workspace holds, the to-do list, the year's moves."""
    rec.hold(0.8)
    rec.point_at(".stat.lead")
    rec.hold(0.4)
    rec.scroll_to("#todo")
    rec.point_at("#todo .tcard")
    rec.hold(1.0)
    rec.scroll_to("#plan")
    rec.point_at("#plan .stat.lead")
    rec.hold(0.6)
    rec.point_at("#plan-moves .tcard")
    rec.hold(1.0)


def todo_and_moves(rec, d: Demo) -> None:
    rec.hold(0.6)
    rec.scroll_to("#todo")
    rec.point_at("#todo .tcard")
    rec.hold(1.4)
    rec.scroll_to("#plan")
    rec.point_at("#plan-moves .tcard")
    rec.hold(1.4)


def folders(rec, d: Demo) -> None:
    """The documents by folder: the year's folder, its form badges, the filed returns."""
    rec.scroll_to("#folders")
    rec.hold(0.6)
    rec.point_at(folder(rec, "2026"))
    rec.hold(0.5)
    rec.point_at(folder(rec, "2026").locator(".form").first)
    rec.hold(0.6)
    rec.point_at(folder(rec, "prior-returns"))
    rec.hold(1.0)


def badges(rec, d: Demo) -> None:
    rec.scroll_to("#folders")
    rec.hold(0.5)
    for form in ("W-2", "1098", "1099"):
        rec.point_at(rec.page.locator(".form", has_text=form).first)
        rec.hold(0.7)


def workspace_stats(rec, d: Demo) -> None:
    rec.hold(0.8)
    rec.point_at(".stat.lead")
    rec.hold(0.5)
    rec.scroll_to("#folders")
    rec.point_at(folder(rec, "2026"))
    rec.hold(1.0)


def chat_cloud(rec, d: Demo) -> None:
    """Ask a question with nothing private in it: Claude answers, and the page shows what it was sent."""
    open_chat(rec)
    ask(rec, ASK_CLOUD)
    show_sent(rec)


def chat_answered_by(rec, d: Demo) -> None:
    """Who answers, in order, and which of them see masked text."""
    rec.page.evaluate("document.getElementById('fab').style.visibility = 'hidden'")  # it would sit over the notes
    rec.scroll_to("#models")
    rec.point_at("#models li >> nth=0")
    rec.hold(0.8)
    rec.point_at(".pill.mine")
    rec.hold(1.0)


def chat_local(rec, d: Demo) -> None:
    """A question with an amount in it: the model on this Mac answers, and the page says why."""
    open_chat(rec)
    rec.click("#clear", after=0.6)
    ask(rec, ASK_LOCAL)
    rec.point_at(".pill.warn")
    rec.hold(1.0)
    rec.point_at(".offer button")
    rec.hold(0.8)


def chat_masked_offer(rec, d: Demo) -> None:
    """The offer: ask Claude too, with the amount masked, and look at what it was sent."""
    chat_local(rec, d)
    rec.click(".offer button", after=0.4)
    wait_for_answer(rec)
    show_sent(rec)


# -- the terminal windows ---------------------------------------------------------------------------------------------

def shown(d: Demo, text: str) -> str:
    """Command output as it would read in the person's own folder: the temporary home is ~/TaxData."""
    for home in {str(d.home), str(d.home.resolve()), "/private" + str(d.home.resolve())}:
        text = text.replace(home, "~/TaxData")
    return re.sub(r"\S*taxtrace-video-\S*?/export/", "", text)


def import_card(d: Demo) -> str:
    return cards.window("terminal", [("cmd", IMPORT_COMMAND), ("out", shown(d, d.run.said["import"]))])


def import_again_card(d: Demo) -> str:
    return cards.window("terminal", [("cmd", IMPORT_COMMAND), ("out", shown(d, d.run.said["import again"]))])


def outline_card(d: Demo) -> str:
    out = shown(d, d.run.said["outline"])
    return cards.window("terminal", [("cmd", "taxtrace outline ~/TaxData/2026"), ("out", out)])


def redacted_card(d: Demo) -> str:
    """The W-2's masked layout, the page's own lines, blank ones left out."""
    name = next(p for p in sorted((d.home / "redacted").glob("*W-2*.txt")))
    rows = [ln.rstrip() for ln in name.read_text(encoding="utf-8").splitlines()[1:] if ln.strip()]
    return cards.window("redacted/" + name.name, [("out", "\n".join(rows))])


def saved_blocks(d: Demo) -> list[tuple[str, str]]:
    """What the W-2's reading saved: each box's value with its page, its place on it and its quote, and the checks."""
    saved = json.loads(next((d.home / "forms").glob("*W-2*.json")).read_text(encoding="utf-8"))[0]
    rows = [f"box {box:<3} {v['amount']:>12}   page {v['page']}, at {v['top']}, {v['x0']}   read from \"{v['quote']}\""
            for box, v in saved["amounts"].items()]
    checks = [f"pass  {c['what']}" + (f"  ({c['quote']})" if c["quote"] else "") if c["ok"] else f"FAILED  {c['what']}"
              for c in saved["checks"]]
    return [("head", "forms/2026 W-2 Initech.json: each value, and where it was read"), ("out", "\n".join(rows)),
            ("gap", ""), ("head", "and the form's own checks"), ("out", "\n".join(checks))]


def w2_card(d: Demo) -> str:
    return cards.window("terminal", [("cmd", "taxtrace w2"), ("out", shown(d, d.run.said["w2"])), ("gap", ""),
                                     *saved_blocks(d)])


def forms_card(d: Demo) -> str:
    return cards.window("terminal", [("cmd", "taxtrace w2"), ("out", shown(d, d.run.said["w2"])), ("gap", ""),
                                     ("cmd", "taxtrace 1098"), ("out", shown(d, d.run.said["1098"]))])


def saved_card(d: Demo) -> str:
    return cards.window("forms/2026 W-2 Initech.json", saved_blocks(d))


def entry_card(d: Demo) -> str:
    """The command's masked summary, then the sheet itself (up to where the state's section would start)."""
    sheet = (d.home / "entry" / "2026.txt").read_text(encoding="utf-8")
    sheet = sheet.split("## North Carolina")[0].rstrip()
    return cards.window("entry/2026.txt", [("cmd", "taxtrace entry --year 2026"), ("out", d.run.said["entry"]),
                                           ("gap", ""), ("head", "entry/2026.txt"), ("out", sheet)])


def mcp_card(d: Demo) -> str:
    from taxtrace import mcp_server

    with ThreadPoolExecutor(1) as pool:  # the recorder's own event loop is running on this thread
        tools = pool.submit(asyncio.run, mcp_server.server.list_tools()).result()
    rows = [f"{t.name:<22} {'read-only' if t.annotations and t.annotations.read_only_hint else 'changes things'}"
            for t in tools]
    return cards.window("terminal", [
        ("cmd", "claude mcp add taxtrace -s user -e TAXTRACE_HOME=~/TaxData -- taxtrace-mcp"), ("gap", ""),
        ("head", "What the assistant is offered"), ("out", "\n".join(rows))])


def mcp_result_card(d: Demo) -> str:
    from taxtrace import review

    status = json.dumps(review.status(), indent=2)
    todo = review.todo_list(None)
    items = [f"{i['due'] or 'no date':<11} {i['group']:<8} {i['text']}" for i in todo["items"]]
    return cards.window("what the assistant gets back", [
        ("head", "get_status"), ("out", status), ("gap", ""), ("head", "get_todo"), ("out", "\n".join(items))])


# -- the stories ------------------------------------------------------------------------------------------------------

DEMO = Video(
    name="taxtrace-demo",
    subtitle="From a folder of documents to an entry sheet, on your own computer.",
    problem=["A folder of tax PDFs", "Which page said that?", "Is a form missing?", "Who else will see it?"],
    problem_say=("Tax season often starts with a folder of PDFs and a quiet worry. Which page did that number come "
                 "from? Is a form missing? And do you really want to hand all of it to a chatbot?"),
    problem_cues=("folder of PDFs", "Which page", "Is a form", "hand all of it"),
    scenes=[
        Scene("This is taxtrace, running in your browser, on your own Mac. At the top, your to-do list, and the "
              "year's tax-saving moves, ranked by the dollars each one saves.", overview, name="overview"),
        Scene("Further down are your documents, in a plain folder on your disk, sorted by tax year. Each one is "
              "tagged with the form it holds, and none of them has left your computer.", folders, name="documents"),
        Scene("Behind the page, taxtrace reads each form box by box. Here is the W-2 from Initech: eight values "
              "read, and all five checks pass, including that box 4 is 6.2 percent of box 3. Every value keeps the "
              "page, and the exact text, it came from.",
              lambda rec, d: light(rec, "p1: 2026 Form W-2", "5 of 5 checks", hold=1.6), card=w2_card, name="w2"),
        Scene("From those readings, taxtrace writes an entry sheet: everything your tax software will ask, in the "
              "order it asks. Each row is ready, an estimate, or missing, and a missing row names the command that "
              "fills it.",
              lambda rec, d: light(rec, "Box 1,", "Box 4,", "Sales on 1099-Bs", "Give to charity", hold=1.2),
              card=entry_card, name="entry"),
        Scene("Last, the chat, for questions about tax rules and forms. Before anything goes to a cloud model, "
              "digits become pound signs and names and towns become stars, and the page shows exactly what was "
              "sent.", chat_cloud, name="chat"),
        Scene("And a question with an amount in it never leaves your Mac. The model here answers it, and the page "
              "says why.", chat_local, name="chat-local"),
    ],
)

TOUR = {DEMO.name: DEMO}
