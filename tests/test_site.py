"""The landing page (site/index.html) says what the README and the code say, and ships what it links."""

import re
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
PAGE = (SITE / "index.html").read_text(encoding="utf-8")
README = (ROOT / "README.md").read_text(encoding="utf-8")
CLI = (ROOT / "taxtrace" / "cli.py").read_text(encoding="utf-8")


def jpeg_size(path: Path) -> tuple[int, int]:
    data = path.read_bytes()
    assert data[:2] == b"\xff\xd8", path
    i = 2
    while i < len(data):
        marker, length = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
        if marker in (0xC0, 0xC1, 0xC2):
            height, width = struct.unpack(">HH", data[i + 5:i + 9])
            return width, height
        i += 2 + length
    raise AssertionError(f"no size in {path}")


def test_page_is_self_contained():
    assert not re.search(r"<script[^>]+src=", PAGE)
    for asset in re.findall(r'(?:src|href|poster)="([\w./-]+\.(?:svg|png|jpg))"', PAGE):
        assert (SITE / asset).is_file(), asset


def test_external_links_open_in_a_new_tab():
    anchors = re.findall(r"<a\b[^>]*>", PAGE)
    external = [a for a in anchors if 'href="http' in a]
    assert external
    for a in external:
        assert 'target="_blank"' in a and 'rel="noopener"' in a, a


def test_title_description_and_link_preview():
    title = "taxtrace | Every number on your return, traced to its page"
    desc = ("Free and open source. Reads your tax documents on your own computer and builds an entry sheet where "
            "every number carries the page and the exact text it came from. Nothing is guessed.")
    assert f"<title>{title}</title>" in PAGE
    assert f'<meta name="description" content="{desc}">' in PAGE
    assert f'<meta property="og:description" content="{desc}">' in PAGE
    assert f'<meta property="og:title" content="{title}">' in PAGE
    for tag in ('property="og:type" content="website"', 'name="twitter:card" content="summary_large_image"',
                'property="og:url" content="https://vinayvobbili.github.io/taxtrace/"',
                'property="og:image" content="https://vinayvobbili.github.io/taxtrace/og.jpg"',
                'property="og:image:width" content="1200"', 'property="og:image:height" content="630"'):
        assert f"<meta {tag}>" in PAGE, tag
    assert '<link rel="icon" href="icon.svg" type="image/svg+xml">' in PAGE
    assert jpeg_size(SITE / "og.jpg") == (1200, 630)


def test_install_box_is_uv_first_with_one_row_per_step_on_each_system():
    uv = PAGE.split('<div class="uv" id="install" tabindex="-1">')[1].split('<p class="sub">')[0]
    assert PAGE.count('class="uv"') == 1 and PAGE.count('id="install"') == 1  # one install box, in the hero
    assert PAGE.index('class="uv"') < PAGE.index('<div class="tiles">')
    assert PAGE.count("<code>uv tool install taxtrace</code>") == 2  # its two systems, nowhere else
    assert PAGE.count("pipx install taxtrace") == 1
    assert "scroll-margin-top: 90px" in re.search(r"\.uv \{.*?\}", PAGE, re.S).group(0)  # lands under the sticky bar
    assert 'document.getElementById("install")' in PAGE
    assert uv.count('<div class="uvpanel"') == 2
    assert "<code>curl -LsSf https://astral.sh/uv/install.sh | sh</code>" in uv
    assert '<code>powershell -c "irm https://astral.sh/uv/install.ps1 | iex"</code>' in uv
    assert uv.count("<code>uv tool install taxtrace</code>") == 2 and uv.count("<code>taxtrace ui</code>") == 2
    labels = re.findall(r'<span class="or">(?:<a [^>]*>)?([^<]+)(?:</a>)?</span>', uv)
    assert labels == ["Install uv", "Then", "Then run"] * 2
    # every command has a Copy button, in the same columns on every row
    assert uv.count("<code>") == 6 and uv.count('<button type="button" aria-live="polite">Copy</button>') == 6
    assert "grid-template-columns: 5.2em minmax(0, 1fr) 4.6em" in PAGE
    seg = re.search(r'<div class="seg" role="group" aria-label="Your system" hidden>(.*?)</div>', uv, re.S).group(1)
    assert re.findall(r'data-os="(\w+)" aria-pressed="(\w+)">([^<]+)</button>', seg) == [
        ("unix", "true", "Mac / Linux"), ("win", "false", "Windows")]
    assert '<p class="sub pipx">Already have Python? <code id="cmd">pipx install taxtrace</code>' in PAGE
    assert "taxtrace ui" in README and '"ui"' in CLI


def test_the_closing_section_is_a_call_to_action_that_links_back_up_not_a_second_install_card():
    closing = PAGE.split('<section class="again" id="get-started">')[1].split("</section>")[0]
    assert "<h2>Ready to trace your return?</h2>" in closing
    assert re.findall(r'<a class="(btn(?: primary)?)" href="([^"]+)">([^<]+)</a>', closing) == [
        ("btn primary", "#install", "Install taxtrace"), ("btn", "#demo", "Watch the demo")]
    assert "uvrow" not in closing and "<code>" not in closing and "$" not in closing
    assert PAGE.index('class="uv"') < PAGE.index('id="get-started"') < PAGE.index("<h2>Read more</h2>")
    # every in-page link lands on one element, and no id is used twice
    ids = re.findall(r'\sid="([^"]+)"', PAGE)
    assert len(ids) == len(set(ids)), sorted(i for i in set(ids) if ids.count(i) > 1)
    for anchor in re.findall(r'href="#([\w-]+)"', PAGE):
        assert anchor in ids, anchor
    assert re.search(r"section\[id\][^{]*\{[^}]*scroll-margin-top: 70px", PAGE)  # #demo lands under the sticky bar
    # the copy buttons and the tabs are wired once, to the one card
    assert PAGE.count('querySelectorAll(".uvrow button, .pipx button")') == 1


def test_in_a_browser_the_closing_buttons_land_under_the_sticky_header_and_the_one_card_works():
    import importlib.util
    pytest = __import__("pytest")
    pytest.importorskip("playwright.sync_api")
    spec = importlib.util.spec_from_file_location("site_shots", ROOT / "scripts" / "site_shots.py")
    shots = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shots)
    try:
        report = shots.anchors_report(SITE, widths=(390,))
    except Exception as e:  # no browser installed here
        pytest.skip(str(e))
    for key, row in report.items():
        assert row["cards"] == 1 and row["win_tab"] and row["aligned"], key
        assert row["copied"] == "uv tool install taxtrace", key
        for target, got in row["lands"].items():
            assert got["below_header"] and got["on_screen"], (key, target)


def test_no_claude_desktop_one_click_line_until_a_release_ships_an_mcpb():
    # no taxtrace release has an .mcpb asset and scripts/build-mcpb doesn't exist here; add the line with the asset
    assert not (ROOT / "scripts" / "build-mcpb").exists()
    assert "one click" not in PAGE and ".mcpb" not in PAGE


def test_gear_popover_has_theme_and_width_with_icons_and_remembers_them():
    header = PAGE.split("<header>")[1].split("</header>")[0]
    gear = re.search(r'<button class="gear"[^>]*>', header).group(0)
    assert 'aria-label="Display settings"' in gear and 'aria-expanded="false"' in gear
    pop = header.split('id="pop"')[1]
    buttons = re.findall(r'<button data-v="(\w+)" aria-pressed="(\w+)"><svg class="ic" viewBox="0 0 24 24" '
                         r'aria-hidden="true">.*?</svg>(\w+)</button>', pop)
    assert buttons == [("system", "true", "System"), ("light", "false", "Light"), ("dark", "false", "Dark"),
                       ("standard", "true", "Standard"), ("wide", "false", "Wide"), ("full", "false", "Full")]
    for want in ('"tt-theme"', '"tt-width"', "root.dataset.width", "root.dataset.theme", '"Escape"',
                 'closest(".settings")', "prefers-reduced-motion", "localStorage"):
        assert want in PAGE, want
    for width in ("wide", "full"):
        assert f':root[data-width="{width}"] .wrap' in PAGE
    assert ':root[data-theme="dark"]' in PAGE and "prefers-color-scheme: dark" in PAGE


def test_headings_and_paragraphs_balance_their_lines():
    assert "h1, h2, h3, summary { text-wrap: balance; }" in PAGE
    assert "p, li { text-wrap: pretty; }" in PAGE
    assert re.search(r"\.sub \{[^}]*text-wrap: balance;", PAGE)


def test_stat_tiles_link_to_sections_and_private_tile_is_worded_as_asked():
    tiles = re.findall(r'<a class="tile" href="#(\w+)"', PAGE)
    assert len(tiles) == 4
    for anchor in tiles:
        assert f'id="{anchor}"' in PAGE, anchor
    assert '<a class="tile" href="#private"><b>Private</b><span>your data stays on your computer</span></a>' in PAGE


def test_demo_video_and_every_step_video_are_wired_but_guarded():
    videos = re.findall(r"<video\b[^>]*>.*?</video>", PAGE)
    assert len(videos) == 5  # the demo and four steps
    assert PAGE.count('class="step"') == 4
    for video in videos:
        poster, src = re.search(r'poster="([^"]+)" src="([^"]+)"', video).groups()
        assert 'controls preload="none" playsinline' in video and "autoplay" not in video
        assert (SITE / poster).is_file() and jpeg_size(SITE / poster) == (1280, 720), poster
        assert src.endswith(".mp4") and poster.removesuffix(".jpg") == src.removesuffix(".mp4")
        assert re.search(r'aria-label="Video: [^"]+"', video), video
        vtt = src.removesuffix(".mp4") + ".vtt"
        assert f'<track kind="captions" srclang="en" label="English" src="{vtt}">' in video
    # videos come later: a missing file leaves the poster, a "coming soon" note and no controls, not a broken player
    script = PAGE.split("// videos are added after the page")[1].split("// comments")[0]
    assert 'method: "HEAD"' in script and 'removeAttribute("controls")' in script
    assert 'classList.add("soon")' in script and "Video coming soon" in PAGE


def test_demo_narration_is_in_a_details():
    demo = PAGE.split("<h2>See it work</h2>")[1].split("</section>")[0]
    assert '<details class="narration">' in demo and "<summary>Read the narration</summary>" in demo
    assert "Demo data: the people, employers and amounts shown are invented." in demo


def test_private_section_names_the_cloud_exception_the_code_has():
    private = PAGE.split('<div class="private" id="private">')[1].split("</section>")[0]
    assert "Your documents never leave your computer." in private
    exception = re.search(r'<li class="except">(.*?)</li>', private, re.S).group(1)
    for fact in ("optional chat", "Claude's API", "Google's Antigravity", "masked text only",
                 "taxtrace ui --models local"):
        assert fact in exception, fact
    # the same facts, in the code
    chat = (ROOT / "taxtrace" / "chat.py").read_text(encoding="utf-8")
    assert 'BACKENDS = ("claude", "agy", "local")' in chat
    assert "Claude and agy only ever see masked text" in chat
    assert '"--models", default="claude,agy,local"' in CLI
    assert "No accounts, no usage data." in private and "Federal Reserve" in private
    assert "FRED" in (ROOT / "taxtrace" / "fx.py").read_text(encoding="utf-8")


def test_how_it_works_commands_exist():
    for command in ("import", "outline", "redact", "w2", "1099", "k1", "1098", "entry", "ui"):
        assert f'"{command}"' in CLI, command
    assert (ROOT / "taxtrace" / "mcp_server.py").is_file()
    assert "taxtrace-mcp" in (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def test_read_more_links_point_at_this_project():
    links = PAGE.split("<h2>Read more</h2>")[1].split("</section>")[0]
    names = re.findall(r"<a [^>]*>(.*?)</a>", links)
    assert names == ["The README", "The entry sheet", "The chat", "Use it from Claude (MCP)", "GitHub", "PyPI",
                     "MCP Registry entry"]
    for doc in re.findall(r"taxtrace/blob/main/docs/([\w.-]+)(?:#([\w-]+))?\"", links):
        text = (ROOT / "docs" / doc[0]).read_text(encoding="utf-8")
        assert not doc[1] or re.search(rf"(?mi)^#+ {re.escape(doc[1].replace('-', ' '))}\b", text), doc
    assert '"name": "io.github.vinayvobbili/taxtrace"' in (ROOT / "server.json").read_text(encoding="utf-8")
    assert "io.github.vinayvobbili%2Ftaxtrace/versions/latest" in links


def test_join_in_has_giscus_comments_and_a_coffee_card_without_a_price():
    join = PAGE.split('id="join"')[1].split("</section>")[0]
    for href in ("https://github.com/vinayvobbili/taxtrace", "https://github.com/vinayvobbili/taxtrace/issues",
                 "https://ko-fi.com/vinayvobbili"):
        assert f'href="{href}"' in join
    assert "$" not in join
    assert 'id="comments"' in join
    script = PAGE.split("// comments (giscus")[1].split("// the uv commands")[0]
    assert 'src = "https://giscus.app/client.js"' in script and "IntersectionObserver" in script
    for want in ('repo: "vinayvobbili/vinayvobbili.github.io"', '"repo-id": "R_kgDOSZD6Ig"',
                 'category: "Announcements"', '"category-id": "DIC_kwDOSZD6Is4C-p2b"',
                 'mapping: "specific"', 'term: "taxtrace"', 'strict: "0"', 'loading: "lazy"'):
        assert want in script, want
    assert "setConfig" in script  # follows the System / Light / Dark switch


def test_the_problem_is_plain_old_way_lines_not_cards_and_the_overview_follows():
    pain = re.findall(r"<p>(.*?)</p>", PAGE.split('<div class="pain">')[1].split("</div>")[0])
    assert pain == ["Forty PDFs from six places.", "Numbers retyped, never checked.", "Carryovers buried on page 71."]
    assert sum(map(len, pain)) < 95  # fits one row at 900px
    label = re.search(r'<p class="pain-label">(.*?)The old way</p>', PAGE, re.S)
    assert label and '<svg class="ic"' in label.group(1) and 'aria-hidden="true"' in label.group(1)
    assert PAGE.index("The old way</p>") < PAGE.index('<div class="pain">')
    css = re.search(r"\.pain p \{.*?\}", PAGE, re.S).group(0)
    assert not any(word in css for word in ("var(--panel)", "border", "box-shadow"))  # lines, not cards
    assert "@media (min-width: 900px) { .pain { flex-direction: row;" in PAGE and "white-space: nowrap" in PAGE
    assert "--pain-x: #be123c" in PAGE and "--pain-x: #fb7185" in PAGE
    assert PAGE.index('<div class="pain">') < PAGE.index("<h2>What taxtrace does for you</h2>")
    assert "<h2>What it does</h2>" not in PAGE
    assert "sends nothing home" not in PAGE + README


def test_the_name_is_tax_in_the_text_color_and_trace_in_the_gradient_read_as_one_word():
    hero = PAGE.split('<div class="hero">')[1].split('<div class="cta">')[0]
    assert '<h1 aria-label="taxtrace">tax<span class="grad">trace</span></h1>' in hero
    assert '<span aria-label="taxtrace" role="img">tax<b>trace</b></span>' in PAGE
    assert '<h1 class="grad">' not in PAGE and "<b>taxtrace</b>" not in PAGE
    # "tax" takes the page's text color (never a literal white); "trace" the --name-grad of each theme
    assert "color: var(--text)" in re.search(r"\.brand \{.*?\}", PAGE, re.S).group(0)
    assert re.search(r"\.brand b, \.grad \{ background: var\(--name-grad\)", PAGE)
    assert not re.search(r"\.hero h1\s*\{[^}]*color:\s*#(?:fff|ffffff)", PAGE, re.I)
    import importlib.util
    spec = importlib.util.spec_from_file_location("site_shots", ROOT / "scripts" / "site_shots.py")
    shots = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shots)

    def rgb(h):
        return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))

    for theme, block in (("light", PAGE.split(":root {")[1].split("}")[0]),
                         ("dark", PAGE.split(':root[data-theme="dark"] {')[1].split("}")[0])):
        bg = rgb(re.search(r"--bg: (#\w{6})", block).group(1))
        stops = re.findall(r"#[0-9a-f]{6}", re.search(r"--name-grad: ([^;]+);", block).group(1))
        assert len(stops) == 2
        for stop in stops:  # both ends of the gradient read against the page background (WCAG AA)
            assert shots.contrast(rgb(stop), bg) >= 4.5, (theme, stop)


def test_the_strip_checker_computes_wcag_contrast():
    import importlib.util
    spec = importlib.util.spec_from_file_location("site_shots", ROOT / "scripts" / "site_shots.py")
    shots = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(shots)
    assert round(shots.contrast((0, 0, 0), (255, 255, 255)), 1) == 21.0
    assert shots.contrast((119, 119, 119), (119, 119, 119)) == 1.0


def test_the_page_and_its_pictures_use_only_invented_names():
    text = PAGE + (ROOT / "scripts" / "videos" / "posters.py").read_text(encoding="utf-8")
    assert not re.search(r"\b\d{3}-\d{2}-\d{4}\b", text)  # no Social Security number
    for invented in ("Initech", "Globex", "Umbrella"):
        assert invented in text
