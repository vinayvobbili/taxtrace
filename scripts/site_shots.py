"""Screenshot a static site (a folder with index.html) at 1440px and 375px, with the settings popover open.

    python scripts/site_shots.py SITE_DIR OUT_DIR [PREFIX]

Writes PREFIX-{1440,375}-hero.png, -full.png and -full-dark.png (the whole page, light and dark), -popover.png and
-tile.png (when a .tile exists),
and prints, at each width, the horizontal overflow (0 means none) and the headings and paragraphs whose last line is a
single word (a widow). Needs playwright (pip install playwright).
"""

import functools
import http.server
import sys
import threading
from pathlib import Path

WIDTHS = {1440: 900, 375: 800}

# the last line of each block's text, by laying out one range per word and counting the words on the bottom row
WIDOWS = """() => {
  const out = [];
  for (const el of document.querySelectorAll("h1, h2, h3, p, li")) {
    if (el.offsetParent === null) continue;
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    const rows = [];
    for (let n; (n = walker.nextNode());) {
      for (const m of n.data.matchAll(/\\S+/g)) {
        const r = document.createRange();
        r.setStart(n, m.index); r.setEnd(n, m.index + m[0].length);
        const box = r.getClientRects()[0];
        if (box) rows.push(Math.round(box.top / 4));
      }
    }
    if (rows.length < 4) continue;
    const last = rows[rows.length - 1];
    const alone = rows.filter(t => t === last).length === 1 && rows.some(t => t !== last);
    if (alone) out.push(el.textContent.trim().slice(0, 60));
  }
  return out;
}"""


def shoot(site: Path, out: Path, prefix: str = "site") -> dict[str, dict]:
    from playwright.sync_api import sync_playwright

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(Quiet, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
    out.mkdir(parents=True, exist_ok=True)
    report = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for width, height in WIDTHS.items():
                page = browser.new_page(viewport={"width": width, "height": height})
                page.goto(url)
                page.wait_for_timeout(1000)  # let the rise-in animations finish
                page.screenshot(path=str(out / f"{prefix}-{width}-hero.png"))
                report[str(width)] = {
                    "overflow": page.evaluate("document.documentElement.scrollWidth - innerWidth"),
                    "widows": page.evaluate(WIDOWS),
                }
                page.screenshot(path=str(out / f"{prefix}-{width}-full.png"), full_page=True)
                page.emulate_media(color_scheme="dark")
                page.wait_for_timeout(300)
                page.screenshot(path=str(out / f"{prefix}-{width}-full-dark.png"), full_page=True)
                page.emulate_media(color_scheme="light")
                if page.locator(".tile").count():
                    page.locator(".tiles").first.screenshot(path=str(out / f"{prefix}-{width}-tile.png"))
                page.click("#gear")
                page.wait_for_timeout(400)
                page.screenshot(path=str(out / f"{prefix}-{width}-popover.png"))
                page.keyboard.press("Escape")
                assert page.get_attribute("#gear", "aria-expanded") == "false"
                page.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    return report


if __name__ == "__main__":
    site, out = Path(sys.argv[1]), Path(sys.argv[2])
    print(shoot(site, out, sys.argv[3] if len(sys.argv) > 3 else "site"))
