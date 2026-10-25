"""Word documents and Excel workbooks, built from their XML by hand for a made-up landlord. Every value is invented."""

from __future__ import annotations

import zipfile
from pathlib import Path

import pytest

from taxtrace import cli, text

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
S = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
R = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def para(*runs: str) -> str:
    runs_xml = "".join("<w:r><w:tab/></w:r>" if r == "\t" else f"<w:r><w:t>{r}</w:t></w:r>" for r in runs)
    return f"<w:p>{runs_xml}</w:p>"


def docx(path: Path, body: str) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("word/document.xml", f"<w:document {W}><w:body>{body}</w:body></w:document>")
    return path


def xlsx(path: Path, sheets: dict[str, str], shared: list[str]) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/workbook.xml", f"<workbook {S} {R}><sheets>" + "".join(
            f'<sheet name="{name}" sheetId="{n}" r:id="rId{n}"/>' for n, name in enumerate(sheets, 1))
            + "</sheets></workbook>")
        links = "".join(f'<Relationship Id="rId{n}" Target="worksheets/sheet{n}.xml"/>'
                        for n in range(1, len(sheets) + 1))
        z.writestr("xl/_rels/workbook.xml.rels",
                   f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{links}'
                   "</Relationships>")
        z.writestr("xl/sharedStrings.xml", f"<sst {S}>" + "".join(f"<si><t>{s}</t></si>" for s in shared) + "</sst>")
        for n, rows in enumerate(sheets.values(), 1):
            z.writestr(f"xl/worksheets/sheet{n}.xml", f"<worksheet {S}><sheetData>{rows}</sheetData></worksheet>")
    return path


def test_a_word_document_reads_as_paragraphs_and_table_rows(tmp_path: Path):
    path = docx(tmp_path / "2025 Tax Questions.docx", para("Did you have rental income?") + (
        "<w:tbl><w:tr><w:tc>" + para("Rent received") + "</w:tc><w:tc>" + para("14,400") + "</w:tc></w:tr></w:tbl>")
        + "<w:sdt><w:sdtContent>" + para("Answer:", "\t", "Yes, Quenby Mill Road") + "</w:sdtContent></w:sdt>")
    assert text.pages(path) == ["Did you have rental income?\nRent received | 14,400\nAnswer:\tYes, Quenby Mill Road"]


def test_a_workbook_reads_one_sheet_a_page_with_its_cells_in_their_columns(tmp_path: Path):
    rows = ('<row r="1"><c r="A1" t="s"><v>0</v></c><c r="C1" t="s"><v>1</v></c></row>'
            '<row r="2"><c r="A2" t="inlineStr"><is><t>January</t></is></c><c r="C2"><v>1200</v></c></row>'
            '<row r="3"><c r="B3"/></row>')
    path = xlsx(tmp_path / "rents.xlsx", {"2025 rents": rows, "Notes": '<row r="1"><c t="s"><v>2</v></c></row>'},
                ["Month", "Rent", "Paid by Brindlewood tenant"])
    assert text.pages(path) == ["[2025 rents]\nMonth |  | Rent\nJanuary |  | 1200",
                                "[Notes]\nPaid by Brindlewood tenant"]


def test_a_locked_or_damaged_office_file_is_unsupported(tmp_path: Path):
    path = tmp_path / "locked.xlsx"
    path.write_bytes(b"\xd0\xcf\x11\xe0 an encrypted container, not a zip")
    with pytest.raises(text.UnsupportedDocument, match="password-protected"):
        text.pages(path)


def test_redact_masks_office_files_too(tmp_path: Path, workspace_home: Path, capsys):
    path = docx(tmp_path / "Brambleworth questions.docx", para("Rent received from Quenby tenant 14,400"))
    assert cli.main(["redact", str(path), "--out", str(tmp_path / "out")]) == 0
    (masked,) = (tmp_path / "out").glob("*.txt")
    assert masked.read_text().strip().endswith("Rent received from ****** tenant ##,###")
    assert "Brambleworth" not in capsys.readouterr().out
