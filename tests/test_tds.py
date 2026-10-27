"""A made-up bank's quarterly TDS certificates: Form 16A for January to March 2026, Form 131 for April to June."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import printed
from test_k1 import draw, edited

from taxtrace import cli, tds, text

FORM_16A = [
    (255, 75, "FORM NO. 16A"), (267, 95, "[See rule 31(1)(b)]"),
    (154, 115, "Certificate under section 203 of the Income-tax Act, 1961 for tax deducted at source"),
    (23, 137, "Certificate No. QWERTYU"), (440, 137, "Last updated on 12-Jun-2026"),
    (102, 157, "Name and address of the Deductor"), (379, 157, "Name and address of the Deductee"),
    (39, 171, "GODAVARI GRAMEENA BANK"), (320, 171, "KANAKADURGA PEDDIREDDI"),
    (39, 181, "MAIN ROAD, VENNELAPADU"), (320, 181, "4 TEMPLE STREET, VENNELAPADU"),
    (77, 247, "PAN of the Deductor"), (446, 247, "PAN of the Deductee"), (88, 267, "AAACG1234K"),
    (458, 267, "ABCPK1234C"),
    (460, 306, "From"), (534, 306, "To"), (448, 324, "01-Jan-2026"), (516, 324, "31-Mar-2026"),
    (260, 347, "Summary of payment"),
    (49, 374, "Sl. No."), (124, 374, "Amount paid/ credited"), (259, 374, "Nature of payment**"),
    (58, 399, "1"), (197, 399, "1520.40"), (286, 399, "194A"), (400, 399, "4417000123"), (505, 399, "31-03-2026"),
    (58, 414, "2"), (197, 414, "7546.30"), (286, 414, "194A"), (400, 414, "4417000124"), (505, 414, "31-03-2026"),
    (42, 429, "Total (Rs.)"), (197, 429, "9066.70"),
    (198, 522, "Summary of tax deducted at source in respect of deductee"),
    (75, 557, "Quarter"), (84, 589, "Q4"), (204, 589, "QRSTUVWX"), (406, 589, "1100.00"), (546, 589, "1100.00"),
    (83, 603, "I. DETAILS OF TAX DEDUCTED AND DEPOSITED IN THE CENTRAL GOVERNMENT ACCOUNT THROUGH BOOK ADJUSTMENT"),
    (27, 684, "Total (Rs.)"),
    (99, 698, "II. DETAILS OF TAX DEDUCTED AND DEPOSITED IN THE CENTRAL GOVERNMENT ACCOUNT THROUGH CHALLAN"),
    (34, 742, "Sl. No."),
    (43, 779, "1"), (174, 779, "0.00"), (241, 779, "-"), (327, 779, "07-04-2026"), (440, 779, "-"), (528, 779, "F"),
    (43, 794, "2"), (162, 794, "1100.00"), (228, 794, "0510308"), (327, 794, "07-04-2026"), (432, 794, "20431"),
    (528, 794, "F"),
    (27, 809, "Total (Rs.)"), (162, 809, "1100.00"),
]

FORM_131 = [
    (257, 80, "FORM NO. 131"),
    (23, 150, "Certificate No.: QWE123456789012"), (367, 150, "Last updated on: 14/Jul/2026"),
    (262, 168, "PART A: Details of the deductor"), (63, 182, "Name"), (263, 182, "GODAVARI GRAMEENA BANK"),
    (63, 208, "Address"), (263, 208, "MAIN ROAD, VENNELAPADU"),
    (63, 336, "Tax year"), (263, 332, "2026-27"),
    (331, 357, "From"), (492, 357, "To"), (63, 363, "Quarter of tax year"), (318, 368, "01/Apr/2026"),
    (476, 368, "30/Jun/2026"),
    (63, 403, "Name"), (263, 403, "KANAKADURGA PEDDIREDDI"), (263, 459, "ABCPK1234C"),
    (283, 481, "PART B"), (260, 499, "Summary of payment"),
    (44, 547, "1"), (118, 547, "1072"), (246, 547, "₹845.20"), (405, 547, "30/Jun/2026"),
    (37, 565, "Total"), (246, 565, "₹845.20"),
    (199, 583, "Summary of tax deducted at source in respect of deductee"),
    (50, 636, "Q1"), (170, 636, "123456789012345"), (365, 636, "₹84.52"), (417, 636, "10.0000"), (550, 636, "₹84.52"),
    (46, 654, "Total"), (365, 654, "₹84.52"), (550, 654, "₹84.52"),
    (52, 672, "I. DETAILS OF TAX DEDUCTED AND DEPOSITED IN THE CENTRAL GOVERNMENT ACCOUNT THROUGH BOOK ADJUSTMENT"),
    (44, 738, "–"), (107, 738, "–"), (37, 753, "Total"), (124, 753, "₹0.00"),
    (72, 769, "II. DETAILS OF TAX DEDUCTED AND DEPOSITED IN THE CENTRAL GOVERNMENT ACCOUNT THROUGH CHALLAN"),
]
FORM_131_CHALLANS = [
    (44, 91, "1"), (125, 91, "₹84.52"), (189, 91, "0510308"), (290, 91, "07/Jul/2026"), (406, 91, "20517"),
    (514, 91, "Final"),
    (37, 106, "Total"), (125, 106, "₹84.52"),
]


def read(path: Path) -> tds.Certificate:
    pages = text.pages(path)
    assert tds.is_certificate(pages[0])
    return tds.read(path.name, pages, {n: text.words(path, n, None) for n in range(1, len(pages) + 1)})


def test_form_16a_gives_the_quarter_its_payments_tax_and_challans(tmp_path: Path):
    found = read(draw(tmp_path / "tds.pdf", [FORM_16A]))
    assert (found.number, found.deductor, found.start, found.end, found.quarter) == (
        "16A", "GODAVARI GRAMEENA BANK", "01-01-2026", "31-03-2026", "Q4")
    assert (str(found.deducted), str(found.deposited)) == ("1100.00", "1100.00")
    assert [(p.on, str(p.amount)) for p in found.payments] == [("31-03-2026", "1520.40"), ("31-03-2026", "7546.30")]
    assert [(c.on, str(c.amount)) for c in found.challans] == [("07-04-2026", "1100.00")]  # the empty one is left out
    assert [c.ok for c in found.checks] == [True, True, True] and not found.questions


def placed(face: list) -> list[dict]:
    """A face's words as `text.words` gives them, without drawing it: reportlab's Helvetica has no ₹."""
    return [{"text": word, "x0": x + 24 * i, "top": top}
            for x, top, phrase in face for i, word in enumerate(phrase.split())]


def test_form_131_reads_rupee_signs_and_challans_on_the_next_page():
    faces = [FORM_131, FORM_131_CHALLANS]
    pages = [" ".join(phrase for _, _, phrase in sorted(face, key=lambda w: (w[1], w[0]))) for face in faces]
    assert tds.is_certificate(pages[0])
    found = tds.read("tds.pdf", pages, {n: placed(face) for n, face in enumerate(faces, 1)})
    assert (found.number, found.deductor, found.start, found.end, found.quarter) == (
        "131", "GODAVARI GRAMEENA BANK", "01-04-2026", "30-06-2026", "Q1")
    assert (str(found.deducted), [str(p.amount) for p in found.payments]) == ("84.52", ["845.20"])
    assert [(c.on, str(c.amount)) for c in found.challans] == [("07-07-2026", "84.52")]
    assert [c.ok for c in found.checks] == [True, True, True]


def test_payments_off_their_total_fail(tmp_path: Path):
    found = read(draw(tmp_path / "tds.pdf", [edited(FORM_16A, **{"1520.40": "1520.50"})]))
    assert [c.what for c in found.failed] == ["the payments add up to their total"]


def test_cli_saves_the_certificate_without_the_customer(tmp_path: Path, workspace_home: Path, capsys):
    assert cli.main(["bank", str(draw(tmp_path / "gramin-tds-q4.pdf", [FORM_16A]))]) == 0
    out = printed(capsys)
    assert "TDS certificate (Form 16A), Q4 of India's year, 01-01-2026 to 31-03-2026; 2 payments, 1 challans" in out
    for secret in ["KANAKADURGA", "ABCPK1234C", "1100.00"]:
        assert secret not in out
    saved = (workspace_home / "forms" / "tds-gramin-tds-q4.json").read_text()
    assert json.loads(saved)["deducted"] == "1100.00"
    for secret in ["KANAKADURGA", "PEDDIREDDI", "ABCPK1234C", "TEMPLE"]:
        assert secret not in saved
