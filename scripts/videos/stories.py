"""The videos' stories: each scene's narration and what the mouse does while it is said.

Short, plain sentences. Every scene is filmed in the real `taxtrace ui` on the made-up household (demo.py): the
Overview (status, to-do list, moves), the Import screen (files chosen with the file picker), the Entry sheet, and the
chat with its "what was sent" panel. Nothing is filmed that the page cannot show: no terminal, no command output.
A scene that needs the page in a state (files already chosen, say) sets it up before `rec.begin()`, so its clip
opens on that state.
"""

from __future__ import annotations

from common import TAGLINE, Demo, Scene, Video  # noqa: F401  (TAGLINE is part of the story, re-exported)

ASK_CLOUD = "I live in Boulder and my employer is Initech. Which form shows my wages for 2026?"
ASK_LOCAL = "My wages were 120,000 dollars. Is box 1 right?"
PICKED = 4  # the files the picker is given (demo.INCOMING)


# -- finding things on the page ---------------------------------------------------------------------------------------

def folder(rec, name: str):
    return rec.page.locator(".folder", has_text=name).first


def result(rec, status: str):
    """The Import screen's card for the first file with that status (recognised, skipped...)."""
    return rec.page.locator(f"#import-results .res[data-status={status}]").first


def section(rec, title: str):
    return rec.page.locator("#entry-sections .sec", has_text=title).first


def hide_fab(rec) -> None:
    """The chat button floats over the page's bottom-right corner: out of the way where the scene isn't about it."""
    rec.page.evaluate("document.getElementById('fab').style.visibility = 'hidden'")


def go(rec, view: str, *, quietly: bool = False) -> None:
    """Open a screen: click its tab, or (before the clip begins) just go there."""
    hide_fab(rec)
    if quietly:
        rec.page.evaluate("view => { location.hash = view === 'home' ? '' : view; }", view)
        rec.page.wait_for_timeout(300)
    else:
        rec.click(f"#tab-{view}", after=0.9)


# -- the Import screen ------------------------------------------------------------------------------------------------

def choose_files(rec, d: Demo, *, quietly: bool = False) -> None:
    """Pick the preparer's files in the file dialog (the dialog itself is the browser's; its answer is set here), and
    wait until the page has said what it makes of each."""
    files = [str(p) for p in d.run.incoming]
    if quietly:
        rec.page.set_input_files("#pick-files", files)
    else:
        with rec.page.expect_file_chooser() as chooser:
            rec.click("#choose-files", after=0.4)
        chooser.value.set_files(files)
    rec.page.wait_for_function(
        f"document.querySelectorAll('#import-results .res').length >= {PICKED}"
        " && !document.querySelector('#import-results .spin')", timeout=20000)
    rec.hold(0.5)


def import_pick(rec, d: Demo) -> None:
    """From the Overview to the Import tab, choose the files: the page reads their names."""
    rec.hold(0.8)
    go(rec, "import")
    rec.point_at("#drop")
    rec.hold(0.5)
    choose_files(rec, d)
    rec.scroll_to("#import-stats")
    rec.point_at("#import-stats .stat.lead")
    rec.hold(0.8)


def import_recognised(rec, d: Demo) -> None:
    """The files are chosen: what the page says of each, and what it skips."""
    go(rec, "import", quietly=True)
    choose_files(rec, d, quietly=True)
    rec.scroll_to("#import-stats")
    rec.begin()
    rec.hold(0.6)
    for status in ("recognised", "skipped"):
        rec.point_at(result(rec, status).locator("dl, .note").first)
        rec.hold(0.9)
    rec.point_at(rec.page.locator("#import-results .res", has_text="Passport").first.locator(".note"))
    rec.hold(0.9)
    rec.point_at(rec.page.locator("#import-results .res", has_text="Return").first.locator("dd").nth(2))
    rec.hold(0.8)


def file_them(rec, d: Demo) -> None:
    """Press the button, wait for Filed, then see the documents by folder on the Overview."""
    go(rec, "import", quietly=True)
    choose_files(rec, d, quietly=True)
    rec.scroll_to("#import-stats")
    rec.begin()
    rec.hold(0.6)
    rec.click("#import-go", after=0.5)
    rec.page.wait_for_function("document.getElementById('import-go').textContent === 'Filed'", timeout=20000)
    rec.hold(0.8)
    rec.point_at("#import-stats .stat.s-ok")
    rec.hold(0.8)
    go(rec, "home")
    folders(rec, d)


def folders(rec, d: Demo) -> None:
    """The documents by folder: the year's folder, its form badges, the filed returns."""
    hide_fab(rec)
    rec.scroll_to("#folders")
    rec.hold(0.6)
    rec.point_at(folder(rec, "2026"))
    rec.hold(0.5)
    rec.point_at(folder(rec, "2026").locator(".form").first)
    rec.hold(0.6)
    rec.point_at(folder(rec, "prior-returns"))
    rec.hold(1.0)


# -- the Entry sheet --------------------------------------------------------------------------------------------------

def entry_open(rec, d: Demo) -> None:
    """From the Overview to the Entry sheet: the counts at its top."""
    rec.hold(0.8)
    go(rec, "entry")
    rec.page.wait_for_selector("#entry-sections .sec")
    rec.hold(0.6)
    for stat in ("lead", "s-est", "s-miss"):
        rec.point_at(f"#entry-stats .stat.{stat}")
        rec.hold(0.8)


def entry_sources(rec, d: Demo) -> None:
    """A section's rows: the value, its status, and the document and page it was read from."""
    go(rec, "entry", quietly=True)
    rec.page.wait_for_selector("#entry-sections .sec")
    rec.begin()
    rec.hold(0.6)
    wages = section(rec, "W-2")
    rec.scroll_to(wages)
    rec.point_at(wages.locator("th", has_text="From"))
    rec.hold(0.6)
    rec.point_at(wages.locator("tbody tr").first.locator(".val"))
    rec.hold(0.8)
    rec.point_at(wages.locator("tbody tr").first.locator(".src"))
    rec.hold(1.0)
    rec.point_at(wages.locator("tbody tr").nth(1).locator(".src"))
    rec.hold(0.8)


def entry_attention(rec, d: Demo) -> None:
    """Only the rows that need the person, and the link from a section to the to-do items about it."""
    go(rec, "entry", quietly=True)
    rec.page.wait_for_selector("#entry-sections .sec")
    rec.begin()
    rec.hold(0.6)
    rec.click("#entry-filter button[data-f=attention]", after=0.8)
    rec.point_at("#entry-sections .sec .cnt.missing")
    rec.hold(0.8)
    link = rec.page.locator("#entry-sections .sec-foot a.todolink[href^='#todo-']").first
    rec.point_at(link)
    rec.hold(0.8)
    rec.click(link, after=1.4)
    rec.hold(0.8)


def entry_coming(rec, d: Demo) -> None:
    """What is still to come, and what the sheet leaves for the person to type."""
    go(rec, "entry", quietly=True)
    rec.page.wait_for_selector("#entry-sections .sec")
    rec.begin()
    rec.hold(0.6)
    rec.scroll_to("#entry-extra")
    rec.point_at("#entry-extra .card h3")
    rec.hold(0.8)
    rec.point_at("#entry-coming li")
    rec.hold(1.0)
    rec.point_at("#entry-how")
    rec.hold(1.0)


# -- the Overview -----------------------------------------------------------------------------------------------------

def overview(rec, d: Demo) -> None:
    """The top of the page: what the workspace holds, the to-do list, the year's moves."""
    hide_fab(rec)
    rec.hold(0.6)
    for tile in (1, 3):
        rec.point_at(f"#hero .stat:nth-child({tile})")
        rec.hold(0.7)
    rec.scroll_to("#todo")
    rec.point_at("#todo .tcard")
    rec.hold(1.0)
    rec.scroll_to("#plan")
    rec.point_at("#plan .stat.lead")
    rec.hold(0.6)
    rec.point_at("#plan-moves .tcard .tag.save")
    rec.hold(0.8)
    rec.point_at("#plan-moves .tcard:nth-child(2) .tag.save")
    rec.hold(0.8)


def status(rec, d: Demo) -> None:
    """The workspace's counts, tile by tile."""
    hide_fab(rec)
    rec.hold(0.8)
    for tile in range(1, 5):
        rec.point_at(f"#hero .stat:nth-child({tile})")
        rec.hold(0.9)


def todo_list(rec, d: Demo) -> None:
    """The to-do list: its counts by due date, a card's details, and one ticked off."""
    hide_fab(rec)
    rec.scroll_to("#todo")
    rec.hold(0.5)
    rec.point_at("#todo-stats .stat >> nth=0")
    rec.hold(0.7)
    rec.point_at("#todo .tcard .tag.due")
    rec.hold(0.8)
    rec.click("#todo .g-today .tcard .chk", after=1.2)
    rec.hold(0.8)


def moves(rec, d: Demo) -> None:
    """The year's moves: what could still come off the tax, then each move with its saving and its deadline."""
    hide_fab(rec)
    rec.scroll_to("#plan")
    rec.hold(0.5)
    rec.point_at("#plan-stats .stat.lead")
    rec.hold(0.8)
    rec.point_at("#plan-moves .tcard .tag.save")
    rec.hold(0.8)
    rec.point_at("#plan-moves .tcard .action")
    rec.hold(1.0)
    rec.point_at("#plan-moves .tcard:nth-child(2) .tag.save")
    rec.hold(1.0)


# -- the chat ---------------------------------------------------------------------------------------------------------

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


# -- the stories ------------------------------------------------------------------------------------------------------

DEMO = Video(
    name="taxtrace-demo",
    subtitle="From a folder of documents to an entry sheet, on your own computer.",
    problem=["A folder of tax PDFs", "Which page said that?", "Is a form missing?", "Who else will see it?"],
    problem_say=("Tax season often starts with a folder of PDFs and a quiet worry. Which page did that number come "
                 "from? Is a form missing? And do you really want to hand all of it to a chatbot?"),
    problem_cues=("folder of PDFs", "Which page", "Is a form", "hand all of it"),
    scenes=[
        Scene("This is taxtrace, running in your browser, on your own Mac. At the top, what your workspace holds, "
              "then your to-do list, and the year's tax-saving moves, ranked by the dollars each one saves.",
              overview, name="overview"),
        Scene("When your preparer sends more documents, open the Import tab and choose the files. taxtrace shows "
              "what it makes of each one: its form, its tax year and its owner. A passport, or a copy you already "
              "have, is skipped.", import_pick, name="import"),
        Scene("One button files the rest. The page then lists your documents by folder, sorted by tax year, each "
              "tagged with the form it holds, and none of them has left your computer.", file_them, name="filed"),
        Scene("Then the entry sheet: everything your tax software will ask, in the order it asks. Each value shows "
              "whether it is ready, an estimate or missing, and the document and page it was read from.",
              entry_sources, name="entry"),
        Scene("Switch to estimates and missing, and only the rows that need you are left. Each section links to the "
              "to-do items that mention it, so nothing waits unnoticed.", entry_attention, name="attention"),
        Scene("Last, the chat, for questions about tax rules and forms. Before anything goes to a cloud model, "
              "digits become pound signs and names and towns become stars, and the page shows exactly what was "
              "sent.", chat_cloud, name="chat"),
        Scene("And a question with an amount in it never leaves your Mac. The model here answers it, and the page "
              "says why.", chat_local, name="chat-local"),
    ],
)

TOUR = {DEMO.name: DEMO}
