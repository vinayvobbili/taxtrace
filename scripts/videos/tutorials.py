"""The four tutorials, about a minute each, every scene filmed in the page. Narration is short and plain; a scene's clip
is held as long as its voice, so every line is said over the screen it describes.

Dropped from the first set, because the page has no screen for them: the document's layout (outline and redact), the
form readings box by box and the MCP tools. What those showed that the page can show lives on in the steps below:
each entry-sheet value names its document and page, and the chat's "what was sent" panel shows the masking."""

from __future__ import annotations

from common import Scene, Video
from stories import (
    chat_answered_by,
    chat_cloud,
    chat_masked_offer,
    entry_attention,
    entry_coming,
    entry_open,
    entry_sources,
    file_them,
    import_pick,
    import_recognised,
    moves,
    status,
    todo_list,
)

IMPORT = Video(
    name="taxtrace-01-import",
    subtitle="Step 1: import your documents",
    problem=["A pile of files from your preparer", "A passport inside", "Forms named whatever", "Some of them twice"],
    problem_say=("A preparer's portal hands you a pile of files. There's a passport in it, forms named whatever, "
                 "and some of them twice."),
    problem_cues=("pile of files", "passport", "forms named", "twice"),
    scenes=[
        Scene("Open the Import tab and choose the files your preparer sent. They go to taxtrace on your own "
              "computer, and nowhere else. Nothing is filed yet: the page only reads what each file is called.",
              import_pick, name="pick"),
        Scene("For each file, taxtrace shows its form, its tax year and its owner, and where it will go. A filed "
              "return goes to prior-returns. A passport is skipped, and so is a copy you already have.",
              import_recognised, name="recognised"),
        Scene("Press the button, and the rest are filed. Back on the Overview, they sit in their year's folder, "
              "each tagged with its form, and the older return is with the filed returns.", file_them, name="filed"),
    ],
)

ENTRY = Video(
    name="taxtrace-02-entry-sheet",
    subtitle="Step 2: the entry sheet, and where each value came from",
    problem=["Question after question", "In their order, not yours", "Where was that figure?"],
    problem_say=("Typing a return into tax software means answering question after question, in an order you don't "
                 "choose, and wondering where each figure was."),
    problem_cues=("question after question", "an order you don't", "where each figure"),
    scenes=[
        Scene("Open the Entry sheet tab. At the top: how many values are ready to type, how many are estimates "
              "that can still change, and how many are missing because nothing has been read for them yet.",
              entry_open, name="top"),
        Scene("Each section is a form. Every value comes from a document that was read box by box, and sits beside "
              "the document and page it was read from, so you can check it against the page before you type it.",
              entry_sources, name="sources"),
        Scene("To see only what needs you, choose estimates and missing. A section's link takes you to the to-do "
              "items that mention it, so each gap has a next step.", entry_attention, name="attention"),
        Scene("Below the sections are the forms still to come, and the questions still open. Names, Social "
              "Security numbers and bank numbers are left for you to type.", entry_coming, name="coming"),
    ],
)

PLAN = Video(
    name="taxtrace-03-todo-and-moves",
    subtitle="Step 3: the to-do list and the year's moves",
    problem=["Dates in your head", "Tasks in three places", "A saving you could miss"],
    problem_say=("Tax dates live in your head, tasks live in three different places, and a saving you could still "
                 "make is easy to miss."),
    problem_cues=("Tax dates", "three different places", "saving"),
    scenes=[
        Scene("The Overview is where taxtrace opens. At the top: how many documents the workspace holds, which tax "
              "years, how many filed returns it can carry forward from, and how many chat models are ready.",
              status, name="status"),
        Scene("Below, your to-do list, grouped by when each item is due. It is a plain file in your workspace, and "
              "ticking an item here marks it done in that file.", todo_list, name="todo"),
        Scene("Then the year's moves, ranked by what each saves. Each one says what to do, how much, and by when. "
              "The first tile is what could still come off the tax.", moves, name="moves"),
    ],
)

CHAT = Video(
    name="taxtrace-04-ask-the-chat",
    subtitle="Step 4: ask the chat, and see what it was sent",
    problem=["A question about a form", "A folder full of private details", "A chatbot in the cloud"],
    problem_say=("You have a question about a form, but your documents are full of details you'd rather keep "
                 "private, and the chatbot is in the cloud."),
    problem_cues=("question about a form", "details", "chatbot"),
    scenes=[
        Scene("Click the chat button and ask about a rule or a form. Under the answer, open what Claude was sent: "
              "digits became pound signs, and names and towns became stars.", chat_cloud, name="ask"),
        Scene("The page also shows who answers, in order: Claude, then Antigravity, then a model on your Mac. Cloud "
              "models are marked masked, and the one on your Mac is not, because it never leaves the machine.",
              chat_answered_by, name="who"),
        Scene("Ask something with an amount in it, and the question stays on your Mac. The model here answers it, "
              "and the page says why. Or ask Claude as well, with the amount masked, and see exactly what it gets.",
              chat_masked_offer, name="amount"),
    ],
)

TUTORIALS = {v.name: v for v in (IMPORT, ENTRY, PLAN, CHAT)}
