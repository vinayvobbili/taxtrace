from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from taxtrace import cli, importer

PDF = b"%PDF-1.4 made-up\n"
# Shaped like a preparer portal's export: one folder per year, a subfolder for the filed return.
PORTAL = {
    "My Documents_2023 Taxes/Sample W2 2023.pdf": PDF + b"w2-2023",
    "My Documents_2023 Taxes/Rental Income And Expense.pdf": PDF + b"rental-2023",
    "My Documents_2023 Taxes/2020 1040 Tax Return (5-15-21)": PDF + b"return-2020",
    "My Documents_2023 Taxes/Sample DL 2023.pdf": PDF + b"license",
    "My Documents_2023 Taxes/Kid SSN.pdf": PDF + b"ssn-card",
    "My Documents_2023 Taxes_Preparer Docs/2023 Tax Return Documents (SAMPLE)-signed.pdf": PDF + b"return-2023",
    "My Documents_2024 Taxes/Rental Income And Expense.pdf": PDF + b"rental-2024",
    "My Documents_2024 Taxes/Sample DrivingLicense-Front.pdf": PDF + b"license-2",
    "My Documents_2024 Taxes/Notes.docx": b"notes",
    "My Documents_2024 Taxes/Copy of W2.pdf": PDF + b"w2-2023",  # the 2023 W-2 again
    "Loose/escrow.pdf": PDF + b"escrow",
    "Loose/.DS_Store": b"junk",
}


@pytest.fixture
def portal_zip(tmp_path: Path) -> Path:
    path = tmp_path / "Archive_20990101.zip"
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in PORTAL.items():
            zf.writestr(name, data)
    return path


def files(home: Path) -> set[str]:
    return {p.relative_to(home).as_posix() for p in home.rglob("*") if p.is_file() and p.name != importer.MANIFEST}


def test_sorts_by_year_returns_apart_and_skips_identity_documents(portal_zip: Path, workspace_home: Path):
    placed = importer.import_documents(portal_zip, workspace_home)
    assert files(workspace_home) == {
        "2023/Sample W2 2023.pdf",
        "2023/Rental Income And Expense.pdf",
        "prior-returns/2020 1040 Tax Return (5-15-21).pdf",  # nameless PDF given its suffix
        "prior-returns/2023 Tax Return Documents (SAMPLE)-signed.pdf",
        "2024/Rental Income And Expense.pdf",
        "2024/Notes.docx",
        "unsorted/escrow.pdf",
    }
    reasons = {p.source.rsplit("/", 1)[1]: p.reason for p in placed if p.dest is None}
    assert reasons == {"Sample DL 2023.pdf": "identity document", "Kid SSN.pdf": "identity document",
                       "Sample DrivingLicense-Front.pdf": "identity document", "Copy of W2.pdf": "already imported",
                       ".DS_Store": "system file"}
    w2 = PORTAL["My Documents_2023 Taxes/Sample W2 2023.pdf"]
    assert (workspace_home / "2023/Sample W2 2023.pdf").read_bytes() == w2


def test_importing_twice_changes_nothing(portal_zip: Path, workspace_home: Path):
    importer.import_documents(portal_zip, workspace_home)
    manifest = (workspace_home / importer.MANIFEST).read_text()
    again = importer.import_documents(portal_zip, workspace_home)
    assert not [p for p in again if p.dest]
    assert (workspace_home / importer.MANIFEST).read_text() == manifest
    entries = [json.loads(line) for line in manifest.splitlines()]
    assert len(entries) == 7 and all(len(e["sha256"]) == 64 and e["from"] == portal_zip.name for e in entries)


def test_same_name_different_content_is_kept_beside(tmp_path: Path, workspace_home: Path):
    src = tmp_path / "folder" / "2025 Taxes"
    src.mkdir(parents=True)
    (src / "statement.pdf").write_bytes(PDF + b"one")
    (workspace_home / "2025").mkdir(parents=True)
    (workspace_home / "2025" / "statement.pdf").write_bytes(PDF + b"other")
    [placed] = importer.import_documents(tmp_path / "folder", workspace_home)
    assert placed.dest == "2025/statement (2).pdf"


@pytest.mark.parametrize("dry_run", [False, True])
def test_two_different_files_of_one_name_in_one_import(tmp_path: Path, workspace_home: Path, dry_run: bool):
    for sub, body in (("2025 Taxes", b"one"), ("2025 Taxes_review", b"two")):
        (tmp_path / "folder" / sub).mkdir(parents=True)
        (tmp_path / "folder" / sub / "questions.docx").write_bytes(body)
    placed = importer.import_documents(tmp_path / "folder", workspace_home, dry_run=dry_run)
    assert [p.dest for p in placed] == ["2025/questions.docx", "2025/questions (2).docx"]


def test_a_file_already_in_place_is_left_alone(tmp_path: Path, workspace_home: Path):
    src = tmp_path / "folder" / "2025 Taxes"
    src.mkdir(parents=True)
    (src / "w2.pdf").write_bytes(PDF)
    (workspace_home / "2025").mkdir(parents=True)
    (workspace_home / "2025" / "w2.pdf").write_bytes(PDF)
    [placed] = importer.import_documents(tmp_path / "folder", workspace_home)
    assert placed.dest is None and placed.reason == "already in the workspace"


def test_a_folder_named_for_a_year_sorts_its_files_there(tmp_path: Path, workspace_home: Path):
    src = tmp_path / "2025 TAX"
    src.mkdir()
    (src / "message.png").write_bytes(b"png")
    [placed] = importer.import_documents(src, workspace_home)
    assert placed.dest == "2025/message.png" and placed.source == "2025 TAX/message.png"


def test_a_zip_named_for_its_export_day_does_not_set_the_year(tmp_path: Path, workspace_home: Path):
    path = tmp_path / "Archive_20990101.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("loose.pdf", PDF)
    [placed] = importer.import_documents(path, workspace_home)
    assert placed.dest == "unsorted/loose.pdf"


def test_cli_dry_run_copies_nothing(portal_zip: Path, workspace_home: Path, capsys):
    assert cli.main(["import", str(portal_zip), "--dry-run"]) == 0
    assert "would copy 7 of 12 files" in capsys.readouterr().out
    assert not workspace_home.exists() or not files(workspace_home)


def test_cli_rejects_a_plain_file(tmp_path: Path, capsys):
    not_zip = tmp_path / "x.pdf"
    not_zip.write_bytes(PDF)
    assert cli.main(["import", str(not_zip)]) == 1
    assert "not a folder or a zip" in capsys.readouterr().err
