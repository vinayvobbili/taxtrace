"""The browser's Import screen: what a file's name says, the /api/import endpoint and its staging. Made-up files for an
invented taxpayer at Initech in Boulder, CO."""

from __future__ import annotations

import http.client
import io
import json
import threading
import zipfile
from pathlib import Path
from urllib.parse import quote, urlencode

import pytest

from taxtrace import importer, web, workspace

PDF = b"%PDF-1.4 made-up\n"


@pytest.fixture
def server():
    srv = web.serve(0, open_browser=False, token="t0ken")
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


def upload(srv, name, data=PDF, *, dry=False, year=None, token="t0ken", host=None):
    port = srv.server_address[1]
    params = {"name": name, **({"dry": "1"} if dry else {}), **({"year": year} if year else {})}
    query = urlencode(params, quote_via=quote)
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Host": host or f"{web.APP_HOST}:{port}", "X-Taxtrace-Token": token,
               "Content-Type": "application/octet-stream"}
    conn.request("POST", f"/api/import?{query}", body=data, headers=headers)
    r = conn.getresponse()
    return r.status, json.loads(r.read())


def workspace_files(home: Path) -> set[str]:
    if not home.exists():
        return set()
    return {p.relative_to(home).as_posix() for p in home.rglob("*") if p.is_file() and p.name != workspace.MANIFEST}


@pytest.mark.parametrize("name, form", [
    ("Initech W2 2026.pdf", "W-2"), ("w-2_casey.pdf", "W-2"), ("2026/1099-INT Globex Bank.pdf", "1099-INT"),
    ("1099 DIV.pdf", "1099-DIV"), ("brokerage 1099B.pdf", "1099-B"), ("1099.pdf", "1099"),
    ("Acme Mortgage 1098.pdf", "1098"), ("1098-T.pdf", "1098-T"), ("Umbrella Lofts K-1 2026.pdf", "K-1"),
    ("k3-umbrella.pdf", "K-3"), ("Initech paystub Oct.pdf", "Pay stub"), ("Rental Income And Expense.pdf", "Rental"),
    ("Globex statement 2026-03.pdf", "Statement"), ("Form 16 2026.pdf", "India"), ("notes.docx", None),
    ("W2K.pdf", None), ("Form 10990 report.pdf", None)])
def test_form_type_from_the_name(name, form):
    assert importer.form_type(name) == form


def test_owner_is_a_redact_term_in_the_name():
    assert importer.owner("Casey W-2 2026.pdf", ["Dana", "Casey"]) == "Casey"
    assert importer.owner("casey-w2.pdf", ["Casey"]) == "Casey"
    assert importer.owner("Caseyville W-2.pdf", ["Casey"]) == ""  # a whole word only
    assert importer.owner("W-2.pdf", ["Casey"]) == ""
    assert importer.owner("Casey/W-2.pdf", ["Casey"]) == ""  # the file's name, not its folder's


def test_describe_tells_recognised_from_unrecognised_and_skipped():
    terms = ["Casey"]
    ok = importer.describe(importer.Placement("2026 TAX/Casey W-2.pdf", "2026/Casey W-2.pdf", "tax year"), terms)
    assert (ok["status"], ok["form"], ok["year"], ok["owner"]) == ("recognised", "W-2", "2026", "Casey")
    odd = importer.describe(importer.Placement("2026 TAX/Notes.docx", "2026/Notes.docx", "tax year"), terms)
    assert (odd["status"], odd["form"], odd["year"]) == ("unrecognised", None, "2026")
    assert "doesn't say which form" in odd["note"]
    lost = importer.describe(importer.Placement("W-2.pdf", "unsorted/W-2.pdf", "no year in its name"), terms)
    assert (lost["status"], lost["form"], lost["year"]) == ("unrecognised", "W-2", None)
    assert "unsorted/" in lost["note"]
    filed = importer.describe(importer.Placement("2025 Tax Return (signed).pdf",
                                                 "prior-returns/2025 Tax Return (signed).pdf", "filed return"), terms)
    assert (filed["status"], filed["form"], filed["year"]) == ("recognised", "Filed return", "2025")
    skipped = importer.describe(importer.Placement("Casey Driver License.pdf", None, "identity document"), terms)
    assert (skipped["status"], skipped["dest"], skipped["note"]) == ("skipped", None, "identity document")


def test_a_preview_reads_the_name_and_files_nothing(server, workspace_home):
    status, data = upload(server, "Initech W-2 2026.pdf", dry=True)
    assert status == 200
    [row] = data["results"]
    assert (row["status"], row["form"], row["year"], row["dest"], row["filed"]) == (
        "recognised", "W-2", "2026", "2026/Initech W-2 2026.pdf", False)
    assert workspace_files(workspace_home) == set()


def test_uploading_files_them_the_way_the_command_does(server, workspace_home):
    workspace_home.mkdir()
    (workspace_home / workspace.TERMS_FILE).write_text("# names\nCasey\n")
    status, data = upload(server, "2026 TAX/Casey W-2 Initech.pdf", PDF + b"w2")
    [row] = data["results"]
    assert status == 200 and row["filed"] is True and row["owner"] == "Casey" and row["status"] == "recognised"
    assert (workspace_home / "2026" / "Casey W-2 Initech.pdf").read_bytes() == PDF + b"w2"
    manifest = [json.loads(line) for line in (workspace_home / workspace.MANIFEST).read_text().splitlines()]
    assert [m["dest"] for m in manifest] == ["2026/Casey W-2 Initech.pdf"]
    # the same bytes again are skipped, whatever they're called now
    [again] = upload(server, "copy.pdf", PDF + b"w2")[1]["results"]
    assert (again["status"], again["dest"], again["note"]) == ("skipped", None, "already imported")


def test_files_end_up_where_the_cli_puts_them(server, workspace_home):
    for name, want in [("2025 Tax Return (signed).pdf", "prior-returns/2025 Tax Return (signed).pdf"),
                       ("Boulder escrow.pdf", "unsorted/Boulder escrow.pdf"),
                       ("2026/Umbrella K-1.pdf", "2026/Umbrella K-1.pdf")]:
        [row] = upload(server, name, PDF + name.encode())[1]["results"]
        assert row["dest"] == want
    assert row["status"] == "recognised"
    assert workspace_files(workspace_home) == {"prior-returns/2025 Tax Return (signed).pdf",
                                               "unsorted/Boulder escrow.pdf", "2026/Umbrella K-1.pdf"}


def test_identity_documents_and_fake_pdfs_are_skipped_with_a_reason(server, workspace_home):
    [license_] = upload(server, "Casey Driver License 2026.pdf")[1]["results"]
    assert (license_["status"], license_["note"], license_["filed"]) == ("skipped", "identity document", False)
    [fake] = upload(server, "2026/W-2.pdf", b"<html>please log in</html>")[1]["results"]
    assert fake["status"] == "skipped" and "not a PDF" in fake["note"]
    assert workspace_files(workspace_home) == set()


def test_unrecognised_files_are_filed_but_flagged(server, workspace_home):
    [row] = upload(server, "2026 TAX/scribbles.docx", b"notes")[1]["results"]
    assert (row["status"], row["form"], row["dest"], row["filed"]) == (
        "unrecognised", None, "2026/scribbles.docx", True)
    assert (workspace_home / "2026" / "scribbles.docx").exists()


def test_a_year_given_overrides_the_name(server, workspace_home):
    [row] = upload(server, "Initech W-2.pdf", dry=True, year="2025")[1]["results"]
    assert (row["dest"], row["year"], row["status"]) == ("2025/Initech W-2.pdf", "2025", "recognised")
    assert upload(server, "Initech W-2.pdf", year="next")[0] == 400


def test_a_zip_gives_a_result_per_file(server, workspace_home):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Portal 2026/Initech W-2.pdf", PDF + b"a")
        zf.writestr("Portal 2026/Globex 1099-INT.pdf", PDF + b"b")
        zf.writestr("Portal 2026/Casey DL.pdf", PDF + b"c")
    status, data = upload(server, "portal-export.zip", buf.getvalue())
    by = {r["source"]: r for r in data["results"]}
    assert status == 200 and len(by) == 3
    assert by["Portal 2026/Globex 1099-INT.pdf"]["form"] == "1099-INT"
    assert by["Portal 2026/Casey DL.pdf"]["status"] == "skipped"
    assert workspace_files(workspace_home) == {"2026/Initech W-2.pdf", "2026/Globex 1099-INT.pdf"}


@pytest.mark.parametrize("name", ["", "../escape.pdf", "/etc/passwd", "a/../../b.pdf", "a/..", ".."])
def test_unsafe_names_are_refused(server, workspace_home, name):
    status, data = upload(server, name)
    assert status == 400 and "can't be imported" in data["error"]
    assert workspace_files(workspace_home) == set()


def test_the_endpoint_wants_the_token_and_our_own_host(server, workspace_home):
    assert upload(server, "W-2.pdf", token="wrong")[0] == 403
    assert upload(server, "W-2.pdf", host="evil.example:80")[0] == 403
    assert workspace_files(workspace_home) == set()


def test_a_workspace_inside_a_git_repo_is_refused(server, tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setenv("TAXTRACE_HOME", str(repo / "TaxData"))
    status, data = upload(server, "2026/W-2.pdf")
    assert status == 400 and "git repository" in data["error"]


def test_staged_uploads_are_removed(server, workspace_home, tmp_path, monkeypatch):
    staging = tmp_path / "staging"
    staging.mkdir()
    monkeypatch.setattr("tempfile.tempdir", str(staging))
    assert upload(server, "2026/Initech W-2.pdf")[0] == 200
    assert list(staging.iterdir()) == []


def test_the_page_has_the_import_screen_with_stable_ids():
    html = web.page("t0ken").decode()
    for ident in ("tab-import", "view-import", "drop", "choose-files", "choose-folder", "pick-files", "pick-folder",
                  "import-year", "import-go", "import-clear", "import-stats", "import-results"):
        assert f'id="{ident}"' in html
    assert "webkitdirectory" in html and "/api/import" in html
