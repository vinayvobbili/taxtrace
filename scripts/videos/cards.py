"""The cards around the screen recordings: the title card (also the closing card's base) and the animated problem
scene, 1920 x 1080. taxtrace's teal look; accent text takes the brand gradient."""

from __future__ import annotations

import html

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
