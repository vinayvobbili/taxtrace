"""Screenshot a static site (a folder with index.html) at 1440px and 375px, with the settings popover open.

    python scripts/site_shots.py SITE_DIR OUT_DIR [PREFIX]
    python scripts/site_shots.py --strip SITE_DIR      # the problem strip at 390/800/900/1000, light and dark
    python scripts/site_shots.py --anchors SITE_DIR    # install card, closing buttons, tabs, Copy at 390/900/1440

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


def luminance(rgb: tuple[float, ...]) -> float:
    lin = [(c / 255 / 12.92) if c / 255 <= 0.04045 else ((c / 255 + 0.055) / 1.055) ** 2.4 for c in rgb[:3]]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: tuple[float, ...], b: tuple[float, ...]) -> float:
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


# the problem strip: rows of lines, widows, overflow, and each line's and the ✕ marker's color and the page background
STRIP = """() => {
  const rgb = s => s.match(/[\\d.]+/g).slice(0, 3).map(Number);
  const lines = [...document.querySelectorAll(".pain p")];
  const mark = getComputedStyle(lines[0], "::before").color;
  return {rows: new Set(lines.map(p => Math.round(p.getBoundingClientRect().top))).size,
          overflow: document.documentElement.scrollWidth - innerWidth,
          bg: rgb(getComputedStyle(document.body).backgroundColor),
          text: rgb(getComputedStyle(lines[0]).color),
          label: rgb(getComputedStyle(document.querySelector(".pain-label")).color), mark: rgb(mark)};
}"""


def strip_report(site: Path, widths=(390, 800, 900, 1000)) -> dict[str, dict]:
    """The problem strip at each width, in light and dark, each in an iframe of that width (a window resize doesn't
    change the viewport): rows (1 at 900px and up, 3 below), overflow, widows and the contrast ratios (4.5 or more)."""
    from playwright.sync_api import sync_playwright

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
    report = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for width in widths:
                for scheme in ("light", "dark"):
                    page = browser.new_page(viewport={"width": width, "height": 900}, color_scheme=scheme)
                    page.goto(url)
                    page.wait_for_timeout(1000)
                    got = page.evaluate(STRIP)
                    ratios = {k: round(contrast(got[k], got["bg"]), 2) for k in ("text", "label", "mark")}
                    report[f"{width} {scheme}"] = {"rows": got["rows"], "overflow": got["overflow"],
                                                   "widows": page.evaluate(WIDOWS), "contrast": ratios}
                    page.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    return report


def anchors_report(site: Path, widths=(390, 900, 1440)) -> dict[str, dict]:
    """At each width, in light and dark: the install cards on the page (1), where each closing button lands (its
    target's top must sit at or below the sticky header, and be on screen), the OS tab switch and a Copy click."""
    from playwright.sync_api import sync_playwright

    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
    report = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for width in widths:
                for scheme in ("light", "dark"):
                    ctx = browser.new_context(viewport={"width": width, "height": 900}, color_scheme=scheme,
                                              permissions=["clipboard-read", "clipboard-write"])
                    page = ctx.new_page()
                    page.goto(url)
                    page.wait_for_timeout(800)
                    row = {"cards": page.locator(".uv").count(), "lands": {}}
                    header = page.evaluate('document.querySelector("header").getBoundingClientRect().bottom')
                    for hrefs in ("#install", "#demo"):
                        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                        page.wait_for_timeout(300)
                        page.click(f'#get-started a[href="{hrefs}"]')
                        page.wait_for_timeout(3000)  # the smooth scroll from the page's end
                        top = page.evaluate(f'document.querySelector("{hrefs}").getBoundingClientRect().top')
                        row["lands"][hrefs] = {"top": round(top), "below_header": top >= header - 1,
                                               "on_screen": top < 900}
                    page.click('.uv .seg button[data-os="win"]')
                    row["win_tab"] = page.locator('.uvpanel[data-os="win"]').is_visible() and \
                        not page.locator('.uvpanel[data-os="unix"]').is_visible()
                    page.click('.uv .seg button[data-os="unix"]')
                    button = page.locator('.uvpanel[data-os="unix"] .uvrow button').nth(1)
                    button.click()
                    row["copied"] = page.evaluate("navigator.clipboard.readText()")
                    row["aligned"] = len({round(b.bounding_box()["x"]) for b in
                                          page.locator('.uvpanel[data-os="unix"] .uvrow button').all()}) == 1
                    report[f"{width} {scheme}"] = row
                    ctx.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    return report


if __name__ == "__main__":
    if sys.argv[1] == "--anchors":
        for key, row in anchors_report(Path(sys.argv[2])).items():
            print(key, row)
        sys.exit()
    if sys.argv[1] == "--strip":
        for key, row in strip_report(Path(sys.argv[2])).items():
            print(key, row)
        sys.exit()
    site, out = Path(sys.argv[1]), Path(sys.argv[2])
    print(shoot(site, out, sys.argv[3] if len(sys.argv) > 3 else "site"))
