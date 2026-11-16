"""Copy the rendered videos into site/: the mp4 (re-encoded small), its captions and narration, and its poster.

    python scripts/videos/publish.py [--out DIR] [--captions-only]

For the tour: site/taxtrace-demo.{mp4,vtt,txt,jpg} and the link preview site/og.jpg (1200x630). For each
tutorial: site/tutorials/NAME.{mp4,vtt,txt,jpg}. A poster is a designed thumbnail (posters.py: the whole screen
in the real UI, a title and a play button), 1280x720, never a video frame. `--captions-only` copies only
the .vtt and .txt files, for after a caption or narration edit that didn't change the voice.

The mp4 is H.264 with the moov atom first (so a browser plays it while it downloads) and a bitrate that keeps each
video in the megabytes: git keeps every version of it.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import posters  # noqa: E402

ROOT = HERE.parent.parent
OUT = HERE / "out"
TOUR = "taxtrace-demo"
ENCODE = ["-c:v", "libx264", "-preset", "slow", "-crf", "28", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
          "-movflags", "+faststart"]


def names(out: Path) -> list[str]:
    """Rendered videos, the tour first, then the tutorials in order (taxtrace-01-..., taxtrace-02-...)."""
    done = [p.name for p in sorted(out.glob("taxtrace-*")) if (p / f"{p.name}.mp4").exists()]
    return sorted(done, key=lambda n: (n != TOUR, n))


def site_files(name: str, root: Path = ROOT) -> dict[str, Path]:
    """Where a video's files go on the site: mp4, vtt, txt, jpg."""
    folder = root / "site" if name == TOUR else root / "site" / "tutorials"
    return {ext: folder / f"{name}.{ext}" for ext in ("mp4", "vtt", "txt", "jpg")}


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def encode(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), *ENCODE, str(dest)])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--captions-only", action="store_true", help="copy only the captions and narration")
    args = ap.parse_args(argv)
    for name in names(args.out):
        where = args.out / name
        dest = site_files(name)
        for ext in ("vtt", "txt"):
            if (where / f"{name}.{ext}").exists():
                shutil.copyfile(where / f"{name}.{ext}", dest[ext])
        if args.captions_only:
            print(f"published {name}'s captions")
            continue
        encode(where / f"{name}.mp4", dest["mp4"])
        print(f"published {name}: {dest['mp4'].stat().st_size / 1e6:.1f} MB")
    if not args.captions_only:
        for path in posters.write_all(ROOT / "site"):  # designed thumbnails, not video frames
            print(f"poster {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
