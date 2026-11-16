"""The videos' stories (scripts/videos): every video fits its length, is filmed in the page and never in a terminal,
tells the problem gently and keeps to invented figures. Nothing here opens a browser or renders a video."""

import importlib.util
import re
import sys
from pathlib import Path

import pytest

pytest.importorskip("playwright")
pytest.importorskip("slidecast")

VIDEOS = Path(__file__).resolve().parents[1] / "scripts" / "videos"
MODULES = ("demo", "common", "cards", "captions", "stories", "tutorials", "posters", "publish")


@pytest.fixture(scope="module")
def stories():
    sys.path.insert(0, str(VIDEOS))
    try:
        loaded = {}
        for name in MODULES:
            spec = importlib.util.spec_from_file_location(name, VIDEOS / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[name] = module
            spec.loader.exec_module(module)
            loaded[name] = module
        yield loaded
    finally:
        sys.path.remove(str(VIDEOS))
        for name in MODULES:
            sys.modules.pop(name, None)


def all_videos(stories):
    return {**stories["stories"].TOUR, **stories["tutorials"].TUTORIALS}


def estimated_length(stories, video) -> float:
    """Title card, problem, tagline, each scene held for its voice, and the closing card."""
    say = stories["common"].seconds_to_say
    scenes = sum(max(s.min_seconds, say(s.say)) + 0.3 for s in video.scenes)
    return 3.0 + stories["common"].problem_seconds(video.problem_say) + say(stories["common"].TAGLINE) + scenes + 4.0


def test_the_capture_has_the_frames_aspect_ratio(stories):
    """Playwright never scales a recording up, so the page is recorded at its own size and scaled on saving."""
    common = stories["common"]
    view, frame = common.VIEW["viewport"], common.VIDEO_SIZE
    assert view["width"] * frame["height"] == view["height"] * frame["width"]


def test_the_tour_and_the_four_tutorials_are_the_ones_the_page_wires(stories):
    page = (VIDEOS.parents[1] / "site" / "index.html").read_text(encoding="utf-8")
    wired = [Path(src).stem for src in re.findall(r' src="([^"]+\.mp4)"', page)]
    assert list(all_videos(stories)) == wired == [
        "taxtrace-demo", "taxtrace-01-import", "taxtrace-02-entry-sheet", "taxtrace-03-todo-and-moves",
        "taxtrace-04-ask-the-chat"]


def test_every_video_fits_its_length(stories):
    for name, video in all_videos(stories).items():
        limit = 130 if name == "taxtrace-demo" else 100
        assert estimated_length(stories, video) <= limit, name
        assert video.max_seconds <= 130


def test_the_tour_is_about_two_minutes_and_a_tutorial_about_one(stories):
    videos = all_videos(stories)
    assert 90 <= estimated_length(stories, videos["taxtrace-demo"]) <= 130
    for name, video in videos.items():
        if name != "taxtrace-demo":
            assert 50 <= estimated_length(stories, video) <= 100, name


def test_every_scene_is_filmed_in_the_page_and_never_in_a_terminal(stories):
    """The videos show the UI, not the CLI: a scene is the page and what the mouse does on it, and no narration or
    code in the story files speaks of a terminal, a command line or a terminal-style card."""
    assert "card" not in stories["common"].Scene.__dataclass_fields__
    assert not hasattr(stories["cards"], "window")
    for name, video in all_videos(stories).items():
        assert len(video.scenes) >= 3 and all(s.run for s in video.scenes), name
        said = " ".join([video.problem_say, *(s.say for s in video.scenes)])
        assert not re.search(r"\b(terminal|command line|command|type taxtrace|run taxtrace)\b", said, re.I), name
    for module in ("stories", "tutorials", "build"):
        source = (VIDEOS / f"{module}.py").read_text(encoding="utf-8")
        assert not re.search(r"window\(|cards\.tint|\"cmd\"|terminal window", source), module


def test_the_problem_is_told_gently_and_each_line_drops_in_as_it_is_reached(stories):
    common, cards = stories["common"], stories["cards"]
    for name, video in all_videos(stories).items():
        assert len(video.problem_cues) == len(video.problem), name
        assert not re.search(r"\b(must|never|always|fail|danger|risk)\b", video.problem_say, re.I), name
        times = common.cue_times(video.problem_say, video.problem_cues)
        assert times == sorted(times) and len(set(times)) == len(times), name
        problem = cards.problem_scene(video.problem, common.problem_seconds(video.problem_say), times)
        assert [float(d) for d in re.findall(r"animation-delay:([\d.]+)s", problem)] == [round(t, 2) for t in times]


def test_narration_is_plain_sentences_a_newcomer_follows(stories):
    for name, video in all_videos(stories).items():
        for scene in video.scenes:
            assert scene.say.endswith("."), (name, scene.say)
            assert 15 <= len(scene.say.split()) <= 60, (name, scene.say)
            assert not re.search(r"\btaxtrace (ui|import|w2|entry|outline|redact)\b|`", scene.say), scene.say


def test_the_tour_shows_what_the_screens_hold(stories):
    said = " ".join(s.say for s in stories["stories"].DEMO.scenes).lower()
    for word in ("to-do list", "tax-saving moves", "import tab", "passport", "tagged with the form", "entry sheet",
                 "ready, an estimate or missing", "document and page", "pound signs", "never leaves your mac"):
        assert word in said, word


def test_the_tagline_and_the_title_card(stories):
    common, cards = stories["common"], stories["cards"]
    assert common.TAGLINE == "Every number, traced to its page."
    title = cards.title_card("Step 1: import your documents")
    assert "Step 1: import your documents" in title and "tax" in title and "background-clip: text" in title


def test_the_problem_scene_drops_each_line_in_and_escapes_it(stories):
    page = stories["cards"].problem_scene(["A <b> line", "Another"], 7.0)
    assert page.count('class="line"') == 2 and "A &lt;b&gt; line" in page


def test_no_real_name_or_figure_is_written_in_the_story_files(stories):
    forbidden = re.compile(r"\b\d{3}-\d{2}-\d{4}\b|/Users/")
    for name in ("demo", "common", "cards", "stories", "tutorials", "build", "publish"):
        text = (VIDEOS / f"{name}.py").read_text(encoding="utf-8")
        assert not forbidden.search(text), name
    houses = (VIDEOS / "demo.py").read_text(encoding="utf-8")
    for invented in ("Initech", "Globex", "Umbrella", "Boulder"):
        assert invented in houses


def test_the_demo_runs_only_against_its_own_temporary_workspace():
    text = (VIDEOS / "common.py").read_text(encoding="utf-8")
    assert "TemporaryDirectory" in text and "workspace_at(home)" in text
    assert "Path.home()" not in text and "expanduser" not in text


def test_publish_puts_each_video_where_the_page_reads_it(stories, tmp_path):
    publish = stories["publish"]
    def placed(name):
        return {k: p.relative_to(tmp_path).as_posix() for k, p in publish.site_files(name, tmp_path).items()}

    assert placed("taxtrace-demo") == {
        "mp4": "site/taxtrace-demo.mp4", "vtt": "site/taxtrace-demo.vtt", "txt": "site/taxtrace-demo.txt",
        "jpg": "site/taxtrace-demo.jpg"}
    assert placed("taxtrace-04-x") == {
        "mp4": "site/tutorials/taxtrace-04-x.mp4", "vtt": "site/tutorials/taxtrace-04-x.vtt",
        "txt": "site/tutorials/taxtrace-04-x.txt", "jpg": "site/tutorials/taxtrace-04-x.jpg"}
    for name in ("taxtrace-02-x", "taxtrace-01-x", "taxtrace-demo", "other"):
        (tmp_path / name).mkdir()
        (tmp_path / name / f"{name}.mp4").write_bytes(b"")
    assert publish.names(tmp_path) == ["taxtrace-demo", "taxtrace-01-x", "taxtrace-02-x"]


def test_every_video_has_a_designed_poster_that_fits_its_screenshot_inside_the_frame(stories, tmp_path):
    posters = stories["posters"]
    names = {p.name.removeprefix("tutorials/") for p in posters.POSTERS}
    assert names == {stories["stories"].DEMO.name, *stories["tutorials"].TUTORIALS}
    # a very tall page (2560x5000) must still be scaled to fit the window area, never cropped or overflowing
    shot = tmp_path / "tall.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n\0\0\0\rIHDR" + (2560).to_bytes(4, "big") + (5000).to_bytes(4, "big"))
    for w, h in ((1280, 720), (1200, 630)):
        page = posters.poster_page(posters.POSTERS[0], shot, w, h)
        width, height = map(int, re.search(r'style="width:(\d+)px;height:(\d+)px"', page).groups())
        assert width <= w and height <= h - 2 * 40 - 26
        assert 'See tax<span class="g">trace</span> work' in page and 'class="play"' in page
        assert "<h1>Import your documents</h1>" in posters.poster_page(posters.POSTERS[1], shot, w, h)
