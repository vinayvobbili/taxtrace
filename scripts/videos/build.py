"""Record and render taxtrace's videos: the two-minute tour and the four tutorials.

    python scripts/videos/build.py --dry                  # screenshots of every scene: check framing, cheaply
    python scripts/videos/build.py [NAME ...] [--out DIR] # record and render (default: every video)
    python scripts/videos/build.py --clips-only           # record the clips, render nothing

Each scene is a screen recording of the real `taxtrace ui` on a made-up household: a cursor glides to each target,
clicks ripple, and nothing may be cut off at the frame's edges (slidecast's framing check fails the scene). The story,
in slidecast's shape: a silent title card, the problem, the tagline at the turn, the walkthrough, and the title card
again. Writes OUT/NAME/ (clips, the video, its poster, its captions NAME.vtt and its narration NAME.txt). See
scripts/videos/README.md.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

import captions
import cards
from common import TAGLINE, Demo, Scene, Video, cue_times, demo_running, problem_seconds, seconds_to_say
from slidecast import MLXKokoroTTS, Music, Reel, Sting
from slidecast.recorder import Recorder

OUT = Path(__file__).resolve().parent / "out"
PHONETIC = {r"\btaxtrace\b": "tax trace", r"\bW-2s?\b": "W two", r"\b1098s?\b": "ten ninety-eight",
            r"\b1099s?\b": "ten ninety-nine", r"\bK-1s?\b": "K one", r"\b401\(k\)": "four oh one K",
            r"\bMCP\b": "M C P", r"\bPDFs?\b": "P D Fs", r"\bAPI\b": "A P I", r"\bIRS\b": "I R S"}
TITLE_SECONDS = 3.0
PROBLEM_SECONDS = 7.0


def record_scene(d: Demo, scene: Scene, clip: Path | None, shots: Path | None) -> None:
    """Record one scene to `clip` (or, with `shots`, only screenshot it). The clip lasts as long as its narration."""
    with Recorder.open(d.browser, d.url, clip, shots=shots, pace=1.0) as rec:
        if scene.run:
            scene.run(rec, d)
        rec.hold_until(max(scene.min_seconds, seconds_to_say(scene.say)))


def record(video: Video, work: Path, dry: bool) -> list[Path | None]:
    """Record every scene of the video; returns the clips (None for a dry run, which writes screenshots)."""
    clips: list[Path | None] = [None] * len(video.scenes)
    with demo_running() as d:
        for i, scene in enumerate(video.scenes, 1):
            name = f"{i:02d}-{scene.name or 'scene'}"
            print(f"  {video.name}: scene {name}", flush=True)
            if dry:
                record_scene(d, scene, None, work / "dry" / video.name / name)
            else:
                clips[i - 1] = work / video.name / "clips" / f"{name}.mp4"
                record_scene(d, scene, clips[i - 1], None)
    return clips


def assemble(video: Video, clips: list[Path], work: Path, music: Path | None) -> Path:
    """The reel: title card, problem, tagline, the clips with their narration, and the title card again."""
    where = work / video.name
    tts = MLXKokoroTTS(voice="af_heart", phonetic=PHONETIC)
    options = {}
    if music:
        options = {"music": Music(str(music / "music_bed.wav"), volume=0.3, fade_in=1.0, fade_out=3.0, duck=True,
                                  duck_db=16),
                   "intro": Sting(str(music / "intro_sting.wav"), volume=0.75),
                   "outro": Sting(str(music / "outro_sting.wav"), volume=0.7)}
    reel = Reel(width=1920, height=1080, fps=25, tts=tts, lead_in=0, loudness=-16, theme=cards.THEME, **options)
    reel.title_card(cards.title_card(video.subtitle), seconds=TITLE_SECONDS)
    seconds = problem_seconds(video.problem_say, PROBLEM_SECONDS)
    delays = cue_times(video.problem_say, video.problem_cues) if video.problem_cues else None
    reel.problem(cards.problem_scene(video.problem, seconds, delays), video.problem_say, seconds=seconds)
    reel.tagline(TAGLINE)
    for scene, clip in zip(video.scenes, clips, strict=True):
        reel.add_clip(clip, scene.say, tail_pad=0.3)
    out = where / f"{video.name}.mp4"
    reel.render(out, make_poster=True, workdir=where / "work", youtube=False)
    captions.write_for(video, TAGLINE, where)
    return out


def main(argv: list[str] | None = None) -> None:
    from stories import TOUR
    from tutorials import TUTORIALS

    videos = {**TOUR, **TUTORIALS}
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("names", nargs="*", help=f"which videos (default all): {', '.join(videos)}")
    ap.add_argument("--out", type=Path, default=OUT, help="where to write (git ignores the default)")
    ap.add_argument("--dry", action="store_true", help="screenshot each scene instead of recording and rendering")
    ap.add_argument("--clips-only", action="store_true", help="record the clips but don't render the videos")
    ap.add_argument("--music", type=Path, default=OUT, metavar="DIR",
                    help="the folder with music_bed.wav, intro_sting.wav, outro_sting.wav (default: out/; `slidecast "
                         "compose -o scripts/videos/out` writes them)")
    args = ap.parse_args(argv)
    names = args.names or list(videos)
    if unknown := [n for n in names if n not in videos]:
        sys.exit(f"no such video: {', '.join(unknown)}")
    work = args.out.expanduser().resolve()
    music = args.music if all((args.music / f).is_file() for f in ("music_bed.wav", "intro_sting.wav",
                                                                    "outro_sting.wav")) else None
    for name in names:
        video = videos[name]
        if not args.dry:
            shutil.rmtree(work / name / "clips", ignore_errors=True)
        clips = record(video, work, args.dry)
        if args.dry or args.clips_only:
            continue
        print(f"Wrote {assemble(video, clips, work, music)}")


if __name__ == "__main__":
    main()
