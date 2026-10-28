from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

import pytest
from conftest import PRIOR_RETURN, make_pdf

from taxtrace import cli, text


def make_scan(path: Path, lines: list[str]) -> Path:
    """A PDF whose page is a picture of text, the way a scanner makes one: no text layer."""
    from PIL import Image, ImageDraw, ImageFont
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    img = Image.new("RGB", (1700, 2200), "white")
    draw = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=56)
    for i, line in enumerate(lines):
        draw.text((120, 150 + 110 * i), line, fill="black", font=font)
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=letter)
    c.drawImage(ImageReader(img), 0, 0, *letter)
    c.showPage()
    c.save()
    return path


def test_needs_ocr_when_any_page_has_no_text():
    assert text.needs_ocr(["Form 1040 U.S. Individual Income Tax Return", ""])
    assert not text.needs_ocr(["Form 1040 U.S. Individual Income Tax Return"])


def test_headings_are_the_first_non_blank_lines():
    assert text.headings("\n\n  Form 8582  \n Passive    Activity \n more", 2) == ["Form 8582", "Passive Activity"]


def test_a_cached_ocr_copy_is_used_without_running_ocr(tmp_path: Path, monkeypatch):
    scan = make_pdf(tmp_path / "scan.pdf", [[]])  # a page with nothing on it
    cache = tmp_path / "ocr-cache"
    cache.mkdir()
    digest = hashlib.sha256(scan.read_bytes()).hexdigest()
    make_pdf(cache / f"{digest}.pdf", PRIOR_RETURN)
    monkeypatch.setattr(shutil, "which", lambda name: pytest.fail("ocrmypdf ran despite the cache"))
    assert "Form 4562" in text.pages(scan, ocr_cache=cache)[0]


def test_without_ocrmypdf_a_scan_says_how_to_read_it(tmp_path: Path, monkeypatch):
    scan = make_pdf(tmp_path / "scan.pdf", [[]])
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(text.UnsupportedDocument, match="brew install ocrmypdf"):
        text.pages(scan, ocr_cache=tmp_path / "ocr-cache")
    assert text.pages(scan) == [""]  # no cache given: the text layer, empty as it is


def test_without_ocrmypdf_a_typed_document_with_a_blank_page_still_reads(tmp_path: Path, monkeypatch):
    mixed = make_pdf(tmp_path / "policy.pdf", [["Policy conditions"], PRIOR_RETURN[0]])
    monkeypatch.setattr(shutil, "which", lambda name: None)
    found = text.pages(mixed, ocr_cache=tmp_path / "ocr-cache")
    assert len(found) == 2 and "Form 4562" in found[1]


@pytest.mark.skipif(shutil.which("ocrmypdf") is None, reason="ocrmypdf isn't installed")
def test_a_scan_is_read_through_ocr_once(tmp_path: Path):
    scan = make_scan(tmp_path / "scan.pdf", ["Form 8582 Passive Activity Loss Limitations", "Worksheet 5"])
    cache = tmp_path / "ocr-cache"
    first = text.pages(scan, ocr_cache=cache)
    assert "8582" in first[0] and "Passive Activity" in first[0]
    [kept] = list(cache.iterdir())
    assert kept.name == hashlib.sha256(scan.read_bytes()).hexdigest() + ".pdf"
    assert text.pages(scan, ocr_cache=cache) == first  # the same text every time after


def test_a_picture_is_read_only_through_ocr(tmp_path: Path, monkeypatch):
    from PIL import Image

    picture = tmp_path / "statement.jpeg"
    Image.new("RGB", (600, 800), "white").save(picture)
    with pytest.raises(text.UnsupportedDocument, match="read only through OCR"):
        text.pages(picture)  # no cache given
    cache = tmp_path / "ocr-cache"
    cache.mkdir()
    make_pdf(cache / f"{hashlib.sha256(picture.read_bytes()).hexdigest()}.pdf", PRIOR_RETURN)
    monkeypatch.setattr(shutil, "which", lambda name: pytest.fail("ocrmypdf ran despite the cache"))
    assert "Form 4562" in text.pages(picture, ocr_cache=cache)[0]
    assert text.layer(picture, cache).parent == cache and text.layer(cache / "x.pdf", None).name == "x.pdf"
    assert picture in text.documents([tmp_path])


@pytest.mark.skipif(shutil.which("ocrmypdf") is None, reason="ocrmypdf isn't installed")
def test_a_photo_of_a_page_reads(tmp_path: Path):
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGB", (1200, 1600), "white")
    ImageDraw.Draw(img).text((80, 120), "Statement for Period : 01-04-2026 to 30-09-2026", fill="black",
                             font=ImageFont.load_default(size=40))
    picture = tmp_path / "photo.jpeg"
    img.save(picture)  # no resolution saved, as a phone's chat app sends it
    assert "Statement for Period" in text.pages(picture, ocr_cache=tmp_path / "ocr-cache")[0]


def test_outline_lists_masked_page_headings(prior_return: Path, capsys):
    assert cli.main(["outline", str(prior_return)]) == 0
    out = capsys.readouterr().out
    assert "2 pages" in out
    assert "p1: ****** Q. ************ ###-##-#### | Form 4562 Depreciation and Amortization Report ####\n" in out
    assert "p2: Form 8582 Worksheet 5 - Allocation of Unallowed Losses | Name of activity" in out
    assert "Quillfeather" not in out


def test_outline_can_list_only_the_pages_naming_a_form(prior_return: Path, capsys):
    assert cli.main(["outline", str(prior_return), "--match", "8582|1116"]) == 0
    out = capsys.readouterr().out
    assert "2 pages" in out and "  p2: Form 8582" in out and "  p1:" not in out
    with pytest.raises(SystemExit):
        cli.main(["outline", "--match", "(8582"])


def test_show_opens_one_workspace_file_in_chrome_at_a_page(workspace_home: Path, capsys, monkeypatch):
    for year in ("2024", "2025"):
        make_pdf(workspace_home / "prior-returns" / f"{year} Quillfeather Client Copy.pdf", PRIOR_RETURN)
    ran = []
    monkeypatch.setattr(cli.subprocess, "run", lambda cmd, check: ran.append(cmd))
    assert cli.main(["show", "prior-returns/2025*Client*", "--page", "19"]) == 0
    [cmd] = ran
    assert cmd[:3] == ["open", "-a", "Google Chrome"]
    assert cmd[3].startswith("file:///") and cmd[3].endswith("/2025%20Quillfeather%20Client%20Copy.pdf#page=19")
    out = capsys.readouterr()
    assert "at page 19" in out.out and "Quillfeather" not in out.out
    assert cli.main(["show", "prior-returns/*Client*"]) == 2 and len(ran) == 1
    assert "matches 2 files" in capsys.readouterr().err


def test_list_prints_masked_names_by_folder_without_opening(workspace_home: Path, capsys, monkeypatch):
    make_pdf(workspace_home / "2025" / "Quillfeather 2025 W2.pdf", PRIOR_RETURN)
    monkeypatch.setattr(cli, "_open", lambda doc: pytest.fail("list opened a document"))
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "2025/************ 2025 W#.pdf\n" in out and "Quillfeather" not in out
