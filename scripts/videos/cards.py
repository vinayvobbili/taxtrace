"""The cards around the screen recordings: the title card (also the closing card's base), the animated problem scene,
and the terminal window that shows what a command printed or a file holds. 1920 x 1080 for the first two, the
recorder's 1536 x 864 page for the window. taxtrace's teal look; accent text takes the brand gradient."""

from __future__ import annotations

import html
import re

from slidecast import Theme

THEME = Theme(accent_gradient="linear-gradient(90deg, #5eead4, #93c5fd)", background="#07110e", body_color="#e6f4ef")

ICON = ('<svg viewBox="0 0 32 32" width="150" height="150"><defs><linearGradient id="lg" x1="0" y1="0" x2="1" y2="1">'
        '<stop offset="0" stop-color="#0f766e"/><stop offset="1" stop-color="#15803d"/></linearGradient></defs>'
        '<rect x="1" y="1" width="30" height="30" rx="9" fill="url(#lg)"/>'
        '<path d="M10 6.5h8.5l4.5 4.5v14a1.5 1.5 0 0 1-1.5 1.5h-11.5A1.5 1.5 0 0 1 8.5 25V8A1.5 1.5 0 0 1 10 6.5z" '
        'fill="#fff" fill-opacity=".92"/><path d="M18.5 6.5V11H23" fill="none" stroke="#0f766e" stroke-width="1.4" '
        'stroke-linejoin="round"/><path d="M11.5 15h9M11.5 18.5h5" stroke="#0f766e" stroke-opacity=".45" '
        'stroke-width="1.6" stroke-linecap="round"/><path d="M12 22.5l2.6 2.4 5.4-5.8" fill="none" stroke="#d97706" '
        'stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></svg>')

BASE = """
* { box-sizing: border-box; margin: 0; padding: 0; }
body { width: 1920px; height: 1080px; overflow: hidden; color: #e6f4ef; position: relative;
  font-family: -apple-system, "SF Pro Display", "Helvetica Neue", Arial, sans-serif;
  background: radial-gradient(1500px 900px at 88% -10%, rgba(20,184,166,.34) 0%, transparent 60%),
              radial-gradient(1200px 800px at -10% 110%, rgba(245,158,11,.2) 0%, transparent 55%), #07110e; }
.logo { filter: drop-shadow(0 30px 60px rgba(20,184,166,.4)); }
"""


def _page(css: str, body: str) -> str:
    head = f'<!doctype html><html><head><meta charset="utf-8"><style>{BASE}{css}</style></head>'
    return f"{head}<body>{body}</body></html>"


def title_card(subtitle: str) -> str:
    """The opening card, shown silent for about 3 s, and again at the end under the tagline."""
    css = """
    .card { position: absolute; inset: 0 0 160px; display: flex; flex-direction: column; align-items: center;
      justify-content: center; text-align: center; }
    h1 { font-size: 128px; letter-spacing: -.03em; margin-top: 44px; line-height: 1; }
    p { font-size: 44px; margin-top: 30px; color: #a9c9be; line-height: 1.35; max-width: 1400px; }
    """
    body = (f'<div class="card"><div class="logo">{ICON}</div><h1>tax{THEME.accent("trace")}</h1>'
            f"<p>{html.escape(subtitle)}</p></div>")
    return _page(css, body)


def problem_scene(lines: list[str], seconds: float, delays: list[float] | None = None) -> str:
    """The pain, before the payoff: each line drops in as a card, one after another, and the pile gets heavier.

    `delays` are when each line drops in (seconds), to match the narration; without them the lines fall at even
    gaps over `seconds`. Animated with CSS only (slidecast steps the animations frame by frame); the last frame
    holds for as long as the narration runs."""
    gap = max(0.9, (seconds - 1.5) / max(1, len(lines)))
    delays = delays or [0.4 + i * gap for i in range(len(lines))]
    cards = "".join(
        f'<div class="line" style="animation-delay:{delays[i]:.2f}s;--tilt:{(-1) ** i * (1 + i % 3) * .35:.2f}deg">'
        f"{html.escape(line)}</div>" for i, line in enumerate(lines))
    css = """
    .stack { position: absolute; inset: 0; display: flex; flex-direction: column; align-items: center;
      justify-content: center; gap: 26px; }
    .line { font-size: 54px; font-weight: 650; letter-spacing: -.01em; padding: 26px 56px; border-radius: 24px;
      background: rgba(255,255,255,.06); border: 1px solid rgba(94,234,212,.32); opacity: 0;
      transform: translateY(-60px) rotate(var(--tilt)); animation: drop .7s cubic-bezier(.2,.9,.3,1.2) forwards;
      box-shadow: 0 24px 60px rgba(0,0,0,.35); }
    @keyframes drop { to { opacity: 1; transform: translateY(0) rotate(var(--tilt)); } }
    """
    return _page(css, f'<div class="stack">{cards}</div>')


# -- the terminal window: what a command printed, or a file's lines, recorded like any page ------------------------

WINDOW_CSS = """
* { box-sizing: border-box; margin: 0; padding: 0; }
html { color-scheme: dark; }
body { height: 100vh; overflow: hidden; padding: 36px 48px 48px; color: #d8ece5;
  font: 16px/1.5 -apple-system, "SF Pro Text", "Segoe UI", sans-serif;
  background: radial-gradient(1000px 560px at 6% -12%, rgba(20,184,166,.28), transparent 62%),
    radial-gradient(900px 520px at 100% -8%, rgba(99,102,241,.2), transparent 60%),
    radial-gradient(700px 500px at 60% 110%, rgba(245,158,11,.1), transparent 60%), #07110e; }
.win { max-width: 1380px; max-height: 100%; margin: 0 auto; border-radius: 18px; overflow: hidden;
  display: flex; flex-direction: column; background: rgba(10,22,19,.94);
  border: 1px solid #1d352e; box-shadow: 0 34px 70px -30px rgba(45,212,191,.45), 0 2px 6px rgba(0,0,0,.4);
  animation: rise .6s cubic-bezier(.2,.9,.3,1) both; }
@keyframes rise { from { opacity: 0; transform: translateY(14px); } }
.bar { display: flex; align-items: center; gap: 8px; padding: 12px 16px; background: #14261f;
  border-bottom: 1px solid #1d352e; }
.bar i { width: 12px; height: 12px; border-radius: 50%; background: #fb7185; }
.bar i:nth-child(2) { background: #fbbf24; } .bar i:nth-child(3) { background: #34d399; }
.bar b { margin-left: 10px; font-weight: 650; font-size: 14px; color: #8fb0a6; }
.out { position: relative; flex: 1 1 auto; min-height: 0; overflow: hidden; padding: 18px 24px 22px;
  font: 16.5px/1.62 ui-monospace, "SF Mono", Menlo, monospace; white-space: pre-wrap; overflow-wrap: anywhere; }
.ln { padding: 0 10px; margin: 0 -10px; border-radius: 8px; transition: background .35s, box-shadow .35s; }
.ln.hl { background: rgba(94,234,212,.17); box-shadow: 0 0 0 1px rgba(94,234,212,.4); }
.prompt { color: #5eead4; } .cmd { color: #f2fbf7; font-weight: 650; }
.head { color: #93c5fd; font-weight: 700; margin-top: 10px; }
.dim { color: #7f9b91; } .ok { color: #5eead4; } .est { color: #fbbf24; } .miss { color: #fb7185; }
.mask { color: #c4b5fd; }
.gap { height: 12px; }
"""

STATUS = (("ready", "ok"), ("[estimate]", "est"), ("[missing]", "miss"), ("failed", "miss"), ("pass", "ok"),
          ("already imported", "est"), ("identity document", "est"))


def tint(line: str) -> str:
    """One line of output as HTML: the status words coloured (ready, estimate, missing, failed), masks (#, *) violet."""
    safe = html.escape(line)
    for word, css in STATUS:
        safe = re.sub(rf"(?<![\w-])({re.escape(html.escape(word))})(?!\w)", rf'<span class="{css}">\1</span>', safe,
                      count=1)
    return re.sub(r"([#*]{2,}(?:[#*.,\-]*[#*])?)", r'<span class="mask">\1</span>', safe)


def window(title: str, blocks: list[tuple[str, str]]) -> str:
    """A terminal-like page. `blocks` are (kind, text): "cmd" a prompt line, "out" a command's output (a line each),
    "head" a heading, "gap" a space, "dim" a note. Every line is a `.ln` the recorder can point at."""
    rows = []
    for kind, text in blocks:
        if kind == "gap":
            rows.append('<div class="gap"></div>')
        elif kind == "cmd":
            rows.append('<div class="ln"><span class="prompt">$</span> '
                        f'<span class="cmd">{html.escape(text)}</span></div>')
        elif kind == "head":
            rows.append(f'<div class="ln head">{html.escape(text)}</div>')
        elif kind == "dim":
            rows.append(f'<div class="ln dim">{html.escape(text)}</div>')
        else:
            rows.extend(f'<div class="ln">{tint(line) or "&nbsp;"}</div>' for line in text.splitlines())
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><title>{html.escape(title)}</title>'
            f'<style>{WINDOW_CSS}</style></head><body><div class="win"><div class="bar"><i></i><i></i><i></i>'
            f'<b>{html.escape(title)}</b></div><div class="out">{"".join(rows)}</div></div></body></html>')
