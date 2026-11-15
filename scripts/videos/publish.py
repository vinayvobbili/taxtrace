"""Copy the rendered videos into site/: the mp4 (re-encoded small), its captions and narration, and its poster.

    python scripts/videos/publish.py [--out DIR] [--captions-only]

For the tour: site/taxtrace-demo.{mp4,vtt,txt,jpg} and the link preview site/og.jpg (1200x630). For each
tutorial: site/tutorials/NAME.{mp4,vtt,txt,jpg}. A poster is a frame from the first scene on the page (after
the title card, the problem and the tagline), 1280x720. `--captions-only` copies only
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

import captions  # noqa: E402

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


def first_scene_at(work: Path) -> float:
    """Where the first scene starts in the video: after the title card, the problem and the tagline."""
    return sum(captions.seconds_of(work / f"s{i:03d}.mkv") for i in (1, 2, 3))


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def encode(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-v", "error", "-y", "-i", str(src), *ENCODE, str(dest)])


def frame(video: Path, dest: Path, at: float, size: str, pad: str = "") -> None:
    """One frame as a JPEG scaled to `size`; `pad` (ffmpeg's pad, e.g. "1200:630:40:0:#ffffff") fills out the rest."""
    vf = ",".join(f for f in (f"scale={size}", f"pad={pad}" if pad else "") if f)
    run(["ffmpeg", "-v", "error", "-y", "-ss", f"{at:.2f}", "-i", str(video), "-frames:v", "1", "-vf", vf,
         "-q:v", "3", str(dest)])


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
        at = first_scene_at(where / "work") + 1.6  # the page has scrolled back to its top by then
        frame(dest["mp4"], dest["jpg"], at, "1280:720")
        if name == TOUR:  # 16:9 into 1.91:1 without cutting anything off: the page's own pale tint fills the sides
            frame(dest["mp4"], ROOT / "site" / "og.jpg", at, "1120:630", pad="1200:630:40:0:#eef5f3")
        print(f"published {name}: {dest['mp4'].stat().st_size / 1e6:.1f} MB")


if __name__ == "__main__":
    main()
