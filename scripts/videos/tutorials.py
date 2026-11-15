"""The six tutorials, about a minute each, page first. Narration is short and plain; a scene's clip is held as long as
its voice, so every line is said over the screen it describes."""

from __future__ import annotations

from common import Scene, Video
from stories import (
    badges,
    chat_answered_by,
    chat_cloud,
    chat_masked_offer,
    entry_card,
    folders,
    forms_card,
    import_again_card,
    import_card,
    light,
    mcp_card,
    mcp_result_card,
    outline_card,
    redacted_card,
    saved_card,
    todo_and_moves,
    workspace_stats,
)

IMPORT = Video(
    name="taxtrace-01-import",
    subtitle="Step 1: import your documents",
    problem=["A zip from your preparer", "A driver's license inside", "Forms named whatever", "Some of them twice"],
    problem_say=("A preparer's portal hands you a zip. There's a driver's license in it, forms named whatever, and "
                 "some of them twice."),
    problem_cues=("zip", "driver's license", "forms named", "twice"),
    scenes=[
        Scene("Once your documents are imported, this page shows them sorted by tax year, with filed returns in a "
              "folder of their own.", folders, name="documents"),
        Scene("To import, point taxtrace at the folder or the zip. Each file goes to its tax year, last year's filed "
              "return goes to prior-returns, and the driver's license is skipped: it's no tax input, and a copy not "
              "made can't leak.",
              lambda rec, d: light(rec, "2026/2026 W-2", "prior-returns/", "identity document", hold=1.4),
              card=import_card, name="import"),
        Scene("Import the same folder again, and nothing changes. Files already in the workspace are skipped.",
              lambda rec, d: light(rec, "already imported", hold=1.4), card=import_again_card, name="again"),
    ],
)

LAYOUT = Video(
    name="taxtrace-02-see-the-layout",
    subtitle="Step 2: see a document's layout without its values",
    problem=["Help with a form", "Without showing your numbers", "Or your name", "Or your town"],
    problem_say=("Sometimes you want help with a form, but you'd rather not show anyone your numbers, your name, or "
                 "your town."),
    problem_cues=("help with a form", "your numbers", "your name", "your town"),
    scenes=[
        Scene("Every document in your workspace is listed here, tagged with the form it holds. To see inside one "
              "without its values, taxtrace has two views.", badges, name="documents"),
        Scene("The first is the outline: each page's first lines, so you can see which forms a document holds, and "
              "in what order. Names and amounts are already masked.",
              lambda rec, d: light(rec, "Brokerage", "p3:", hold=1.4), card=outline_card, name="outline"),
        Scene("The second is the redacted layout. It keeps the form's shape, and replaces every digit with a pound "
              "sign, and every name, street and town with stars. That is safe to show to whoever is helping you.",
              lambda rec, d: light(rec, "###,###.##", "******* Payroll", hold=1.5), card=redacted_card,
              name="redacted"),
    ],
)

READ = Video(
    name="taxtrace-03-read-the-forms",
    subtitle="Step 3: read your forms and see where each value came from",
    problem=["A number on a form", "Is it the right box?", "Did a digit slip?", "Who checks every one?"],
    problem_say=("A number on a form is only useful if you can trust it. Is it from the right box? Did a digit "
                 "slip? And who has time to check every one by hand?"),
    problem_cues=("A number", "right box", "digit slip", "by hand"),
    scenes=[
        Scene("On the page, each document wears a badge for the form it holds: W-2, 1098 or 1099. Reading them is "
              "one command each.", badges, name="badges"),
        Scene("Here the W-2 and the mortgage statement are read. Every box is found by the words of its label, so a "
              "payroll company's own layout reads too, and each reading says how many of its checks pass.",
              lambda rec, d: light(rec, "p1: 2026 Form W-2", "p1: 2026 Form 1098", hold=1.6),
              card=forms_card, name="read"),
        Scene("Each value is saved with its page, its place on it, and the exact text it was read from. A check "
              "throws out any value whose text isn't on that page, and the form's own arithmetic is checked: box 4 "
              "must be 6.2 percent of box 3.",
              lambda rec, d: light(rec, "box 1 ", "box 4 ", "box 4 is 6.2%", hold=1.5), card=saved_card, name="saved"),
    ],
)

ENTRY = Video(
    name="taxtrace-04-entry-sheet",
    subtitle="Step 4: the entry sheet",
    problem=["Question after question", "In their order, not yours", "Where was that figure?"],
    problem_say=("Typing a return into tax software means answering question after question, in an order you don't "
                 "choose, and wondering where each figure was."),
    problem_cues=("question after question", "an order you don't", "where each figure"),
    scenes=[
        Scene("Start on the page. The to-do list shows what's due, and the moves show what could still lower the "
              "tax.", todo_and_moves, name="page"),
        Scene("The entry sheet lists everything your tax software will ask, in the order it asks. Under each form, "
              "each value shows the document and page it was read from.",
              lambda rec, d: light(rec, "Wages (Form W-2)", "Box 1,", "Box 4,", "Dividends", hold=1.3),
              card=entry_card, name="sheet"),
        Scene("Each row is ready, an estimate, or missing. A missing row names the command that fills it, and "
              "names, Social Security numbers and bank numbers are left for you to type.",
              lambda rec, d: light(rec, "Filing status [missing]", "Give to charity", "Sales on 1099-Bs",
                                   "Estimated tax payments", hold=1.3), card=entry_card, name="status"),
    ],
)

CHAT = Video(
    name="taxtrace-05-ask-the-chat",
    subtitle="Step 5: ask the chat, and see what it was sent",
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

ASSISTANT = Video(
    name="taxtrace-06-ai-assistant",
    subtitle="Step 6: connect your AI assistant",
    problem=["An AI assistant", "Paste it all in?", "Your whole tax folder"],
    problem_say=("Your AI assistant could be a real help with your taxes, but you wouldn't paste your whole tax "
                 "folder into it."),
    problem_cues=("AI assistant", "paste", "whole tax folder"),
    scenes=[
        Scene("Everything on this page is what your AI assistant can see too, but only in masked form. It connects "
              "through M C P, the standard way to plug tools into an assistant.", workspace_stats, name="page"),
        Scene("One command adds taxtrace to Claude Code. The assistant is offered five tools: status, the list of "
              "documents, a document's outline, form checks, and the to-do list. Every one is read-only.",
              lambda rec, d: light(rec, "claude mcp add", "get_status", "get_todo", hold=1.4), card=mcp_card,
              name="connect"),
        Scene("What comes back is counts and masked text. The dates are real, but the wording is masked, and no tool "
              "returns an amount or a name. A locked document is never opened, and the Keychain is never asked.",
              lambda rec, d: light(rec, "get_status", "get_todo", hold=1.6), card=mcp_result_card, name="result"),
    ],
)

TUTORIALS = {v.name: v for v in (IMPORT, LAYOUT, READ, ENTRY, CHAT, ASSISTANT)}
