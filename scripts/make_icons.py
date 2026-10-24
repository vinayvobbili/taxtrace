"""The app's PNG icons, rendered from the SVGs in taxtrace/static (the page's manifest lists them).

    python scripts/make_icons.py          # after changing icon-app.svg or icon-maskable.svg

Chrome installs the page as an app from the manifest's PNGs (macOS's dock and app switcher, Windows' taskbar);
Safari's "Add to Dock" and iOS read apple-touch-icon.png. Needs rsvg-convert (`brew install librsvg`).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

STATIC = Path(__file__).resolve().parent.parent / "taxtrace" / "static"
# (source, size, output)
ICONS = [
    ("icon-app.svg", 192, "icon-192.png"),
    ("icon-app.svg", 512, "icon-512.png"),
    ("icon-maskable.svg", 512, "icon-maskable-512.png"),
    ("icon-maskable.svg", 180, "apple-touch-icon.png"),  # iOS rounds the corners itself
]


def main() -> int:
    exe = shutil.which("rsvg-convert")
    if not exe:
        print("needs rsvg-convert: brew install librsvg", file=sys.stderr)
        return 1
    for src, size, name in ICONS:
        subprocess.run([exe, "-w", str(size), "-h", str(size), "-o", str(STATIC / name), str(STATIC / src)], check=True)
        print(f"{name}: {size}x{size} from {src}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
