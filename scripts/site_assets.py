"""Render the landing page's pictures from made-up data: site/og.jpg and the placeholder video posters.

    python scripts/site_assets.py [SITE_DIR]

Writes og.jpg (1200x630, the link preview), taxtrace-demo.jpg and tutorials/taxtrace-NN-*.jpg (1280x720). Every
name, employer, town and amount in them is invented. A poster stands in until its video is published: replace the
video, and the poster can be replaced by a frame of it. Needs playwright (pip install playwright).
"""

import sys
from html import escape
from pathlib import Path

PAGE = """<!doctype html><meta charset="utf-8"><style>
* {{ box-sizing: border-box; }}
body {{ margin: 0; width: {w}px; height: {h}px; overflow: hidden; color: #e6f4ef; display: flex; align-items: center;
  gap: 48px; padding: 0 {pad}px; font: 16px/1.4 -apple-system, "SF Pro Text", "Segoe UI", sans-serif;
  background: radial-gradient(700px 420px at 4% -10%, rgba(20,184,166,.34), transparent 62%),
    radial-gradient(640px 420px at 104% 0%, rgba(245,158,11,.22), transparent 60%), #07110e; }}
.l {{ flex: 1.05; }} .r {{ flex: 1.25; }}
.chip {{ display: inline-block; padding: 5px 14px; border-radius: 999px; font-size: {chip}px; font-weight: 700;
  color: #fff; background: linear-gradient(135deg, #0f766e, #15803d); margin-bottom: 18px; }}
h1 {{ margin: 0; font-size: {big}px; line-height: 1.04; letter-spacing: -.035em; font-weight: 850; text-wrap: balance;
  background: linear-gradient(90deg, #5eead4, #93c5fd); -webkit-background-clip: text; color: transparent; }}
p {{ margin: 16px 0 0; font-size: {sub}px; color: #8fb0a6; text-wrap: pretty; }}
.panel {{ border-radius: 20px; padding: 22px 24px; background: rgba(14,28,24,.92); border: 1px solid #1d352e;
  box-shadow: 0 30px 60px -30px rgba(45,212,191,.45); font: 600 {mono}px/1.95 ui-monospace, Menlo, monospace; }}
.row {{ display: flex; justify-content: space-between; gap: 18px; border-top: 1px solid #1d352e; }}
.row:first-child {{ border-top: 0; }}
.k {{ color: #8fb0a6; }} .ok {{ color: #5eead4; }} .est {{ color: #fbbf24; }} .miss {{ color: #fb7185; }}
</style><div class="l"><span class="chip">{chip_text}</span><h1>{title}</h1><p>{sub_text}</p></div>
<div class="r"><div class="panel">{rows}</div></div>"""

ROWS = {
    "demo": [("Wages, Initech", "100,000", "ok:ready"), ("Rental, Umbrella Property", "24,000", "ok:ready"),
             ("Interest, Globex Bank", "1,200", "est:estimate"), ("1099-DIV", "&mdash;", "miss:missing")],
    "import": [("2026/ W-2 Initech.pdf", "", "ok:sorted"), ("2026/ K-1 Globex Partners.pdf", "", "ok:sorted"),
               ("prior-returns/ 2025 Return.pdf", "", "ok:sorted"), ("Driver license.jpg", "", "est:skipped")],
    "entry": [("Wages (W-2, Initech)", "100,000", "ok:ready"), ("Dividends (Globex Brokerage)", "800", "ok:ready"),
              ("Estimated tax paid", "10,000", "est:estimate"), ("Rental expenses", "", "miss:missing")],
    "plan": [("Send the Q4 estimated payment", "", "est:due soon"), ("Fill the 401(k)", "saves 350", "ok:move 1"),
             ("Give to charity in cash", "saves 240", "ok:move 2"), ("Move the year-end cash", "", "ok:done")],
    "chat": [("You", "Is the Umbrella bill a repair?", ""),
             ("Sent to the cloud", "Is the ******** bill a repair?", "est:masked"),
             ("Question with an amount", "", "ok:stays on your Mac")],
}

POSTERS = {
    "taxtrace-demo": ("demo", "Demo", "Documents in, entry sheet out", "Every number traced to its page."),
    "tutorials/taxtrace-01-import": ("import", "Step 1", "Import", "Sort a preparer's export by tax year."),
    "tutorials/taxtrace-02-entry-sheet": ("entry", "Step 2", "Get the entry sheet", "Ready, estimate or missing."),
    "tutorials/taxtrace-03-todo-and-moves": ("plan", "Step 3", "Plan the year", "The to-do list and the moves."),
    "tutorials/taxtrace-04-ask-the-chat": ("chat", "Step 4", "Ask in the chat", "Cloud models see only masked text."),
}


def rows_html(key: str) -> str:
    out = []
    for label, value, tag in ROWS[key]:
        cls, _, word = tag.partition(":")
        tag_html = f'<span class="{cls}">{escape(word)}</span>' if word else ""
        out.append(f'<div class="row"><span class="k">{label}</span><span>{value} {tag_html}</span></div>')
    return "".join(out)


def page(w: int, h: int, key: str, chip_text: str, title: str, sub_text: str, big: int, sub: int, mono: int) -> str:
    return PAGE.format(w=w, h=h, pad=64 if w > 1200 else 56, chip=15, big=big, sub=sub, mono=mono, chip_text=chip_text,
                       title=title, sub_text=sub_text, rows=rows_html(key))


def render(site: Path) -> list[Path]:
    from playwright.sync_api import sync_playwright

    jobs = [("og", 1200, 630, "demo", "Free and open source", "Every number on your return, traced to its page",
             "Reads your tax documents on your own computer. Nothing is guessed.", 52, 20, 15)]
    jobs += [(name, 1280, 720, key, chip, title, sub, 60, 22, 17) for name, (key, chip, title, sub) in POSTERS.items()]
    written = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for name, w, h, key, chip, title, sub, big, subpx, mono in jobs:
            path = site / f"{name}.jpg"
            path.parent.mkdir(parents=True, exist_ok=True)
            tab = browser.new_page(viewport={"width": w, "height": h})
            tab.set_content(page(w, h, key, chip, title, sub, big, subpx, mono))
            tab.screenshot(path=str(path), type="jpeg", quality=88)
            tab.close()
            written.append(path)
        browser.close()
    return written


if __name__ == "__main__":
    for path in render(Path(sys.argv[1] if len(sys.argv) > 1 else "site")):
        print(path)
