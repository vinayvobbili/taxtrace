"""Designed thumbnails for the videos: site/taxtrace-demo.jpg, site/tutorials/taxtrace-NN-*.jpg and the link preview
site/og.jpg, made from the real `taxtrace ui` on the made-up household (Initech, Globex, Umbrella; Boulder, CO).

    python scripts/videos/posters.py [--site DIR] [--shots DIR]

Each poster is 1280x720 (og.jpg is 1200x630): a title and a play button on the left, and on the right the whole
screen the video is about, the full page (never a cropped frame) in a browser window that is scaled to fit, so
nothing is cut off at any edge. Nothing reads ~/TaxData or calls a model. `--shots DIR` also keeps the plain
screenshots. publish.py calls `write_all` after it copies the videos.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from html import escape
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

ROOT = HERE.parent.parent
SHOT_WIDTH = 1900  # the page (in its Full width setting) is laid out this wide, then the whole of it is scaled to fit


@dataclass(frozen=True)
class Poster:
    """name: the file stem under site/ (tutorials live in tutorials/). view: the screen shown (home, import, entry,
    chat). label: the small line over the title. title/length: what the thumbnail says."""

    name: str
    view: str
    label: str
    title: str
    length: str


POSTERS = [
    Poster("taxtrace-demo", "entry", "Demo", "See taxtrace work", "2 min"),
    Poster("tutorials/taxtrace-01-import", "import", "Step 1", "Import your documents", "1 min"),
    Poster("tutorials/taxtrace-02-entry-sheet", "entry", "Step 2", "The entry sheet", "1 min"),
    Poster("tutorials/taxtrace-03-todo-and-moves", "home", "Step 3", "The to-do list and moves", "1 min"),
    Poster("tutorials/taxtrace-04-ask-the-chat", "chat", "Step 4", "Ask the chat", "1 min"),
]

CSS = """
* { box-sizing: border-box; }
body { margin: 0; width: %(w)dpx; height: %(h)dpx; overflow: hidden; display: flex; align-items: center; gap: %(gap)dpx;
  padding: %(pad)dpx; color: #e6f4ef; font: 16px/1.3 -apple-system, "SF Pro Display", "Segoe UI", sans-serif;
  background: radial-gradient(720px 440px at 2%% -8%%, rgba(20,184,166,.40), transparent 62%%),
    radial-gradient(620px 420px at 104%% 104%%, rgba(245,158,11,.26), transparent 60%%), #07110e; }
.l { flex: 0 0 %(left)dpx; display: flex; flex-direction: column; align-items: flex-start; }
.chip { padding: 6px 16px; border-radius: 999px; font-size: %(chip)dpx; font-weight: 750; color: #fff;
  background: linear-gradient(135deg, #0f766e, #15803d); margin-bottom: %(gap_s)dpx; }
h1 { margin: 0; font-size: %(big)dpx; line-height: 1.04; letter-spacing: -.035em; font-weight: 850; text-wrap: balance;
  background: linear-gradient(90deg, #5eead4, #93c5fd); -webkit-background-clip: text; color: transparent;
  padding-bottom: .06em; }
h1.name { background: none; color: #e6f4ef; }
h1 .g { background: linear-gradient(90deg, #5eead4, #93c5fd); -webkit-background-clip: text; color: transparent; }
.tag { margin: %(gap_s)dpx 0 %(gap)dpx; font-size: %(sub)dpx; color: #8fb0a6; }
.play { display: flex; align-items: center; gap: 16px; font-size: %(sub)dpx; font-weight: 700; color: #ccfbf1; }
.play i { width: %(btn)dpx; height: %(btn)dpx; border-radius: 50%%; display: grid; place-items: center;
  background: linear-gradient(135deg, #2dd4bf, #16a34a); box-shadow: 0 0 0 8px rgba(45,212,191,.16),
  0 14px 40px rgba(45,212,191,.5); }
.play i::after { content: ""; margin-left: 7%%; border-style: solid; border-width: %(tri)dpx 0 %(tri)dpx %(tri2)dpx;
  border-color: transparent transparent transparent #052e2a; }
.win { flex: 1; height: 100%%; display: flex; align-items: center; justify-content: center; min-width: 0; }
.frame { border-radius: 14px; overflow: hidden; background: #eef5f3; border: 1px solid #2a4a42;
  box-shadow: 0 30px 70px -20px rgba(45,212,191,.5), 0 0 0 6px rgba(45,212,191,.08); display: flex;
  flex-direction: column; max-width: 100%%; max-height: 100%%; }
.bar { height: %(bar)dpx; flex: none; background: #14231f; display: flex; align-items: center; gap: 7px;
  padding: 0 14px; } .bar b { width: 10px; height: 10px; border-radius: 50%%; background: #3b5a52; }
.bar b:nth-child(1) { background: #fb7185; } .bar b:nth-child(2) { background: #fbbf24; }
.bar b:nth-child(3) { background: #4ade80; }
.frame img { display: block; width: 100%%; height: auto; min-height: 0; object-fit: contain; }
"""


def poster_page(p: Poster, shot: Path, w: int, h: int) -> str:
    """The thumbnail as one page: the screenshot is embedded as a file URL and sized to fit the window area."""
    og = w == 1200
    pad = 44 if og else 52
    left = 330 if og else 360
    gap = 40 if og else 48
    bar = 26
    area_w = w - 2 * pad - left - gap
    area_h = h - 2 * pad
    with_bar = area_h - bar
    img_w, img_h = image_size(shot)
    scale = min(area_w / img_w, with_bar / img_h)
    css = CSS % dict(w=w, h=h, pad=pad, gap=gap, gap_s=14, left=left, chip=15, big=42 if og else 48,
                     sub=17 if og else 19, btn=60 if og else 68, tri=11 if og else 13, tri2=18 if og else 21, bar=bar)
    title = escape(p.title)
    # a title that names taxtrace shows the wordmark: "tax" in the text color, "trace" in the gradient
    wordmark = 'tax<span class="g">trace</span>'
    h1 = (f'<h1 class="name">{title.replace("taxtrace", wordmark)}</h1>'
          if "taxtrace" in title else f"<h1>{title}</h1>")
    return (f'<!doctype html><meta charset="utf-8"><style>{css}</style>'
            f'<div class="l"><span class="chip">{escape(p.label)}</span>{h1}'
            f'<div class="tag">Every number, traced to its page.</div>'
            f'<div class="play"><i></i><span>Watch, {escape(p.length)}</span></div></div>'
            f'<div class="win"><div class="frame"><div class="bar"><b></b><b></b><b></b></div>'
            f'<img src="{shot.as_uri()}" style="width:{img_w * scale:.0f}px;height:{img_h * scale:.0f}px"></div></div>')


def image_size(path: Path) -> tuple[int, int]:
    """Width and height of a PNG, from its header."""
    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n", path
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def shoot(d, view: str, dest: Path) -> Path:
    """The whole of one screen of the served demo as a PNG, laid out SHOT_WIDTH wide (device scale 2 for sharpness)."""
    import stories

    page = d.browser.new_page(viewport={"width": SHOT_WIDTH, "height": 800}, device_scale_factor=2,
                              color_scheme="light")
    try:
        page.goto(d.url)
        page.wait_for_selector("#tab-entry")
        page.evaluate("document.documentElement.dataset.width = 'full'")
        page.evaluate("document.getElementById('fab').style.visibility = 'hidden'")
        if view == "chat":
            page.evaluate("document.getElementById('fab').style.visibility = 'visible'")
            page.click("#fab")
            page.fill("#input", stories.ASK_CLOUD)
            page.click("#send")
            page.wait_for_function("document.getElementById('send').textContent === 'Send'", timeout=20000)
            page.click("details.sent summary")
        elif view == "import":
            page.click("#tab-import")
            page.set_input_files("#pick-files", [str(p) for p in d.run.incoming])
            page.wait_for_function(
                f"document.querySelectorAll('#import-results .res').length >= {stories.PICKED}"
                " && !document.querySelector('#import-results .spin')", timeout=20000)
        elif view == "entry":
            page.click("#tab-entry")
            page.wait_for_selector("#entry-sections .sec")
        page.wait_for_timeout(700)
        dest.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(dest), full_page=True)
    finally:
        page.close()
    return dest


def write_all(site: Path = ROOT / "site", shots: Path | None = None) -> list[Path]:
    """Shoot each screen once and compose every poster (and og.jpg) into `site`."""
    import tempfile

    from common import demo_running

    written = []
    with tempfile.TemporaryDirectory(prefix="taxtrace-poster-") as tmp, demo_running() as d:
        keep = shots or Path(tmp)
        views = {}
        for p in POSTERS:
            if p.view not in views:
                views[p.view] = shoot(d, p.view, keep / f"{p.view}.png")
        for p in POSTERS:
            sizes = [(site / f"{p.name}.jpg", 1280, 720)]
            if p.name == "taxtrace-demo":
                sizes.append((site / "og.jpg", 1200, 630))
            for path, w, h in sizes:
                page = d.browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
                html = keep / "poster.html"
                html.write_text(poster_page(p, views[p.view], w, h), encoding="utf-8")
                page.goto(html.as_uri())
                page.wait_for_timeout(200)
                path.parent.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(path), type="jpeg", quality=90)
                page.close()
                written.append(path)
    return written


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--site", type=Path, default=ROOT / "site")
    ap.add_argument("--shots", type=Path, help="also keep the plain screenshots here")
    args = ap.parse_args(argv)
    for path in write_all(args.site, args.shots):
        print(path)


if __name__ == "__main__":
    main()
