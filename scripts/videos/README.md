# Rebuild the videos

The two-minute tour (`site/taxtrace-demo.mp4`) and the four tutorials (`site/tutorials/taxtrace-0N-*.mp4`) are screen
recordings of the real `taxtrace ui` on a made-up household (an invented Initech employee in Boulder, CO, with round
figures; Globex Bank, Umbrella Brokerage): nothing reads your own `~/TaxData`, reaches the internet or calls a model.
Every scene is filmed in the page, with a visible cursor, a ripple on every click and nothing cut off at the frame's
edges. Never in a terminal: a step the page has no screen for is dropped, not faked.

## What the videos show

| Video | Screen it films |
|---|---|
| `taxtrace-demo` (2 min) | Overview (status, to-do list, moves), Import (files chosen with the file picker, then filed), Entry sheet (values, statuses, sources; the to-do links), the chat and its "what was sent" panel |
| `taxtrace-01-import` | Import: choose files, what the page recognises (form, year, owner), what it skips, filing them, the folders on the Overview |
| `taxtrace-02-entry-sheet` | Entry sheet: the counts, each value with its document and page, estimates and missing, what is still to come |
| `taxtrace-03-todo-and-moves` | Overview: the status tiles, the to-do list (one item ticked off), the year's moves |
| `taxtrace-04-ask-the-chat` | The chat: what a cloud model is sent (digits as pound signs, names as stars), who answers, an amount staying on the Mac |

The first set had six tutorials. Three have no screen in the page and were dropped or merged: a document's layout
(`outline` and `redact`: the masking is shown in the chat's "what was sent" panel), the form readings box by box (each
value's document and page is on the Entry sheet), and the MCP tools (a Claude Code connection, not a screen).

```
source .venv/bin/activate            # taxtrace's environment: uv pip install -e ".[dev,mcp,video]" playwright
python -m playwright install chromium
scripts/videos/make-videos --dry     # a screenshot after each action, to check framing (cheap, no video)
scripts/videos/make-videos           # record and render every video (Kokoro narration; needs Apple Silicon)
scripts/videos/make-videos taxtrace-demo taxtrace-04-ask-the-chat    # just those
python scripts/videos/publish.py     # re-encode them into site/, with captions, narration, posters and og.jpg
python scripts/videos/demo.py        # just the household: print what the real commands say about it
```

Output goes to `scripts/videos/out/NAME/` (git ignores it): `clips/`, `NAME.mp4`, its poster, `NAME.vtt` and `NAME.txt`.
Music: `slidecast compose -o scripts/videos/out` writes the bed and stings that `build.py` reads by default; without
them the videos have the voice only.

| File | What it holds |
|---|---|
| `demo.py` | The household: documents drawn with real print positions, imported, read and summed up by the real commands, and a second batch for the Import screen's file picker |
| `stories.py` | The tour, every scene's narration and mouse actions (`Scene`), and the page helpers |
| `tutorials.py` | The four tutorials |
| `cards.py` | The title card (silent 3 s, and the closing card) and the animated problem scene |
| `common.py` | `Scene` and `Video`, the narration timing, the served page, the pretend models |
| `build.py` | Records the scenes, assembles the reel, renders it, writes its captions and narration |
| `captions.py` | `NAME.vtt` from the narration and the rendered segments' lengths, and `NAME.txt`, the narration as paragraphs; run alone it captions videos already rendered, with no re-render |
| `publish.py` | Copies the finished files into `site/`: H.264 with the moov atom first, the posters and the link preview (made by `posters.py`) |
| `posters.py` | Designed thumbnails (`site/*.jpg`, `og.jpg`): the whole screen from the real UI, a title and a play button; `python scripts/videos/posters.py` regenerates them alone |

The story follows slidecast's shape: a silent title card, a gentle problem, the tagline "Every number, traced to its
page." at the turn, the walkthrough, and the title card again. Each clip is held as long as its narration. slidecast's
`Recorder` moves the cursor and fails a scene when a sticky or fixed element is sliced by the frame's edge.

What is real and what is pretend: the workspace and its documents are built with the real `import`, `w2`, `1098`,
`moves` and `entry` commands (the setup, never filmed); the page is the real `taxtrace ui`, with the real import,
entry sheet, masking, routing and "what was sent" panel. The file dialog is the browser's, so the recording chooses the
files in it by script, the way a person would pick them (a drop can't be scripted, so it isn't filmed). A scene that
needs the page in a state (files already chosen) sets it up and calls `rec.begin()`: the clip starts there. The
models' answers are canned (nothing calls a model), and the page shows the workspace as `~/TaxData`. The 2025 and 2026
tax years, the to-do dates and the moves follow the day the videos are made.

The page's "Read the narration" and the README's lead-in repeat the tour's narration (`site/taxtrace-demo.txt`); a test
checks they match. Keep figures invented: never a real name, employer, town or amount.
