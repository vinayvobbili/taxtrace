"""What every video's scenes share: the made-up household served by `taxtrace ui`, a scene (what is said, and what the
mouse does while it is said), and the timing that keeps a clip as long as its narration.

Everything is made up (Initech, Globex, Umbrella, Boulder, CO): the workspace is built in a temporary folder
(demo.py), TAXTRACE_HOME points at it while the videos are made, and nothing reads ~/TaxData or calls a model.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))  # demo.py, cards.py

import demo  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

WORDS_PER_SECOND = 2.55  # Kokoro's af_heart, a little slower than it speaks, so a clip never ends before its line
LEAD = 0.6  # a beat before the voice has anything to look at
SPEECH_WPS = 3.0  # what af_heart really does: for a card that must not linger
SHOWN_HOME = "~/TaxData"  # what the page says the workspace is called (the real one is a temporary folder)
TAGLINE = "Every number, traced to its page."


def seconds_to_say(text: str) -> float:
    """How long a narration takes, about: the clip is held at least this long."""
    return len(text.split()) / WORDS_PER_SECOND + LEAD


def problem_seconds(say: str, minimum: float = 7.0) -> float:
    """How long the problem card runs: about its narration at the voice's real pace. It is a floor, not a cap: if the
    voice runs longer, the card's last frame holds until it is done."""
    return max(minimum, len(say.split()) / SPEECH_WPS)


def cue_times(say: str, cues: tuple[str, ...] | list[str], lead: float = 0.3) -> list[float]:
    """When each cue phrase of a narration is spoken, about: seconds from its start, `lead` early so a card that
    takes a moment to land is in place as the words are said."""
    return [max(0.0, len(say[:say.index(cue)].split()) / SPEECH_WPS - lead) for cue in cues]


@dataclass
class Demo:
    """A served demo: the page's address, the household it shows, and the browser to record it in."""

    url: str
    home: Path
    run: demo.Run
    browser: object


@dataclass
class Scene:
    """One narrated clip: open the page, say `say`, and do `run(rec, demo)` meanwhile. A scene may set the page up
    first with plain page calls and then `rec.begin()`: the clip starts there, so it opens on the state it needs."""

    say: str
    run: Callable | None = None
    min_seconds: float = 0.0
    name: str = ""


@dataclass
class Video:
    """A video: its title card, the problem it opens on, and the scenes of the walkthrough.

    name: the file stem (`taxtrace-demo`, `taxtrace-01-import`). subtitle: under the title card's logo.
    problem: lines for the animated problem scene, and `problem_say` is its narration; `problem_cues` are the phrases
    of that narration where each line drops in (none: the lines fall at even gaps). max_seconds: the length this
    video must stay under.
    """

    name: str
    subtitle: str
    problem: list[str]
    problem_say: str
    scenes: list[Scene]
    max_seconds: float = 130.0
    problem_cues: tuple[str, ...] = ()


VIEW = {"viewport": {"width": 1536, "height": 864}, "device_scale_factor": 1.25, "color_scheme": "light"}
VIDEO_SIZE = {"width": 1920, "height": 1080}  # the reel's frame; the capture is scaled up to it on saving
assert VIEW["viewport"]["width"] * VIDEO_SIZE["height"] == VIEW["viewport"]["height"] * VIDEO_SIZE["width"]

ASKED = {  # what the pretend models answer: the chat's routing, masking and "what was sent" panel are the real ones
    "carry": ("Several things carry forward from a filed return:\n\n- **Capital losses** past the $3,000 yearly limit "
              "(Schedule D, the capital loss carryover worksheet)\n- **Passive losses** a rental or partnership "
              "couldn't use (Form 8582)\n- **Foreign tax credit** you couldn't use (Form 1116)\n- **Depreciation** "
              "on a rental, which carries on each year (Form 4562)\n\nCheck last year's return for each."),
    "which form": ("Your wages are in **box 1** of your Form W-2. Box 1 is your taxable pay: it leaves out pre-tax "
                   "401(k) deferrals, so it can be lower than the box 3 and box 5 figures.\n\nIt goes on **Form "
                   "1040, line 1a**."),
    "dollars": ("Box 1 is your taxable wages after pre-tax deductions such as 401(k) deferrals. If your last pay "
               "stub's year-to-date taxable wages match it, the two agree.\n\nCheck it against the stub before you "
               "enter it."),
}


def canned_reply(question: str) -> str:
    q = question.lower()
    return next((text for key, text in ASKED.items() if key in q), ASKED["carry"])


@contextmanager
def pretend_models() -> Iterator[None]:
    """The chat answers with a canned reply, streamed a word at a time as a model would, so nothing reaches a model.
    Everything around it is the real chat: what is masked, what was sent, which model is asked."""
    from taxtrace import chat

    def reply(system, messages, settings):
        for word in canned_reply(messages[-1]["content"]).split(" "):
            time.sleep(0.04)  # a model writes as it goes
            yield word + " "

    ready = [{"backend": b, "label": chat.LABELS[b], "model": m, "cloud": b in chat.CLOUD, "ready": ok, "why": why}
             for b, m, ok, why in (("claude", "claude-sonnet-5-5", True, ""),
                                   ("agy", "claude-sonnet-5-5-medium", False,
                                    "the Antigravity CLI (agy) isn't installed"),
                                   ("local", "the local model server", True, ""))]
    saved = dict(chat.RUNNERS), chat.status
    chat.RUNNERS.update(claude=reply, local=reply)
    chat.status = lambda settings=None: ready
    try:
        yield
    finally:
        chat.RUNNERS.clear()
        chat.RUNNERS.update(saved[0])
        chat.status = saved[1]


@contextmanager
def demo_running() -> Iterator[Demo]:
    """The household built in a fresh folder, `taxtrace ui` serving it on a free port, and Chromium ready.

    TAXTRACE_HOME is the temporary folder for the whole block, so nothing can read a real workspace. The page shows
    the workspace as ~/TaxData. The chat answers with canned replies (see pretend_models)."""
    from taxtrace import web

    with tempfile.TemporaryDirectory(prefix="taxtrace-video-") as tmp:
        root = Path(tmp)
        home = (root / "TaxData").resolve()
        with demo.workspace_at(home), pretend_models():
            run = demo.build(home, root / "export")
            shown, sheet = web.overview, web.entry_screen

            def overview() -> dict:
                return {**shown(), "path": SHOWN_HOME}

            def entry_screen(year: int | None = None) -> dict:  # the sheet's file path, as the person's own folder
                data = sheet(year)
                return {**data, "file": data["file"] and data["file"].replace(str(home), SHOWN_HOME)}

            web.overview, web.entry_screen = overview, entry_screen
            server = web.serve(port=0, open_browser=False)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                with sync_playwright() as p:
                    browser = p.chromium.launch()
                    try:
                        yield Demo(url=server.url, home=home, run=run, browser=browser)
                    finally:
                        browser.close()
            finally:
                web.overview, web.entry_screen = shown, sheet
                server.shutdown()
                server.server_close()
