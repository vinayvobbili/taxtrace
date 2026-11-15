# Rebuild the videos

The two-minute tour (`site/taxtrace-demo.mp4`) and the six tutorials (`site/tutorials/taxtrace-0N-*.mp4`) are screen
recordings of the real `taxtrace ui` on a made-up household (an invented Initech employee in Boulder, CO, with round
figures; Globex Bank, Umbrella Brokerage): nothing reads your own `~/TaxData`, reaches the internet or calls a model.
Every video opens on the page, with a visible cursor, a ripple on every click and nothing cut off at the frame's edges.
Where the page has nothing to show (reading a form, the entry sheet, a document's layout, the MCP tools) the cursor
moves over a terminal window that holds what the real command printed on that household.

```
source .venv/bin/activate            # taxtrace's environment: uv pip install -e ".[dev,mcp,video]" playwright
python -m playwright install chromium
scripts/videos/make-videos --dry     # a screenshot after each action, to check framing (cheap, no video)
scripts/videos/make-videos           # record and render every video (Kokoro narration; needs Apple Silicon)
scripts/videos/make-videos taxtrace-demo taxtrace-05-ask-the-chat    # just those
python scripts/videos/publish.py     # re-encode them into site/, with captions, narration, posters and og.jpg
python scripts/videos/demo.py        # just the household: print what the real commands say about it
```

Output goes to `scripts/videos/out/NAME/` (git ignores it): `clips/`, `NAME.mp4`, its poster, `NAME.vtt` and `NAME.txt`.
Music: `slidecast compose -o scripts/videos/out` writes the bed and stings that `build.py` reads by default; without
them the videos have the voice only.

| File | What it holds |
|---|---|
| `demo.py` | The household: documents drawn with real print positions, imported, read and summed up by the real commands |
| `stories.py` | The tour, every scene's narration and mouse actions (`Scene`), the page helpers and the terminal windows |
| `tutorials.py` | The six tutorials |
| `cards.py` | The title card (silent 3 s, and the closing card), the animated problem scene, the terminal window |
| `common.py` | `Scene` and `Video`, the narration timing, the served page, the pretend models |
| `build.py` | Records the scenes, assembles the reel, renders it, writes its captions and narration |
| `captions.py` | `NAME.vtt` from the narration and the rendered segments' lengths, and `NAME.txt`, the narration as paragraphs; run alone it captions videos already rendered, with no re-render |
| `publish.py` | Copies the finished files into `site/`: H.264 with the moov atom first, a poster frame, the link preview |

The story follows slidecast's shape: a silent title card, a gentle problem, the tagline "Every number, traced to its
page." at the turn, the walkthrough, and the title card again. Each clip is held as long as its narration. slidecast's
`Recorder` moves the cursor and fails a scene when a sticky or fixed element is sliced by the frame's edge.

What is real and what is pretend: the workspace, the documents, `import`, `w2`, `1098`, `moves` and `entry` are the
real commands; the page is the real `taxtrace ui`, with the real masking, routing and "what was sent" panel. The
models' answers are canned (nothing calls a model), and the page shows the workspace as `~/TaxData`. The 2025 and 2026
tax years, the to-do dates and the moves follow the day the videos are made.

The page's "Read the narration" and the README's lead-in repeat the tour's narration (`site/taxtrace-demo.txt`); a test
checks they match. Keep figures invented: never a real name, employer, town or amount.
