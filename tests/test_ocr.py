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


def test_outline_lists_masked_page_headings(prior_return: Path, capsys):
    assert cli.main(["outline", str(prior_return)]) == 0
    out = capsys.readouterr().out
    assert "2 pages" in out
    assert "p1: ****** Q. ************ ###-##-#### | Form 4562 Depreciation and Amortization Report ####\n" in out
    assert "p2: Form 8582 Worksheet 5 - Allocation of Unallowed Losses | Name of activity" in out
    assert "Quillfeather" not in out
