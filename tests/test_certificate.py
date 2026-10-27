"""A made-up bank's interest certificate on the made-up accounts of test_statement's statement of every account."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import printed
from test_k1 import draw, edited

from taxtrace import certificate, cli, text

CERTIFICATE = [
    (28, 53, "Date : 05/04/2026 10:12 AM"),
    (228, 74, "TO WHOM IT MAY CONCERN"),
    (28, 101, "This is to certify that the following amount of interest has been paid by us on the deposits in the "
              "name of"),
    (28, 110, "Ms. Lalitha Vemulapati (CUSTOMER NO :CIF00004417) for the financial year ended 31st March 2026."),
    (23, 141, "ACCOUNT"), (87, 141, "BR."), (121, 141, "A/C"), (154, 141, "BALANCE AS ON"), (248, 141, "INTEREST"),
    (330, 141, "INTEREST"), (410, 141, "TOTAL TAX"), (483, 141, "OVERHEAD TAX"), (557, 141, "FORM-"),
    (25, 151, "NUMBER"), (81, 151, "CODE"), (116, 151, "TYPE"), (159, 151, "31.MAR.2026"), (259, 151, "PAID"),
    (331, 151, "ACCRUAL"), (410, 151, "DEDUCTED"), (492, 151, "DEDUCTED"), (559, 151, "15G/H"),
    (18, 181, "40912343301"), (81, 181, "04417"), (122, 181, "TD"), (165, 181, "157546.30"), (252, 181, "0.00"),
    (332, 181, "7546.30"), (416, 181, "1100.00"), (498, 181, "0.00"), (563, 181, "NO"),
    (18, 211, "40912343302"), (81, 211, "04417"), (122, 211, "TD"), (165, 211, "101706.85"), (252, 211, "0.00"),
    (332, 211, "1706.85"), (416, 211, "0.00"), (498, 211, "170.69"), (563, 211, "NO"),
    (18, 241, "30887125520"), (81, 241, "04417"), (122, 241, "SB"), (165, 241, "52361.95"), (252, 241, "1520.40"),
    (332, 241, "0.00"), (416, 241, "0.00"), (498, 241, "0.00"), (563, 241, "NO"),
    (30, 271, "TOTAL"), (250, 271, "1520.40"), (332, 271, "9253.15"), (416, 271, "1100.00"), (498, 271, "170.69"),
    (32, 393, "NOTE : *INTEREST ACCRUED IS FOR THE PERIOD 01/04/2025 TO 31/03/2026."),
    (72, 409, "**TOTAL TAX DEDUCTED IS AMOUNT INCLUSIVE OF CESS AND SURCHARGE."),
    (468, 653, "BRANCH MANAGER"),
]


def read(path: Path) -> certificate.Certificate:
    pages = text.pages(path)
    assert certificate.is_certificate(pages[0])
    return certificate.read(path.name, pages, {1: text.words(path, 1, None)})


def test_each_accounts_interest_and_tax_and_the_rows_add_up(tmp_path: Path):
    found = read(draw(tmp_path / "certificate.pdf", [CERTIFICATE]))
    assert (found.year_ended, found.second_tax_label) == ("31-03-2026", "OVERHEAD TAX DEDUCTED")
    assert [(d.account, d.type, str(d.balance), str(d.paid), str(d.accrued), str(d.tax), str(d.second_tax))
            for d in found.deposits] == [
        ("3301", "TD", "157546.30", "0.00", "7546.30", "1100.00", "0.00"),
        ("3302", "TD", "101706.85", "0.00", "1706.85", "0.00", "170.69"),
        ("5520", "SB", "52361.95", "1520.40", "0.00", "0.00", "0.00")]
    assert [c.ok for c in found.checks] == [True] and not found.questions


def test_rows_off_the_total_fail(tmp_path: Path):
    found = read(draw(tmp_path / "certificate.pdf", [edited(CERTIFICATE, **{"7546.30": "7546.40"})]))
    assert [c.what for c in found.failed] == [
        "the rows add up to the TOTAL row (interest paid, accrued and both tax columns)"]


def test_cli_saves_the_certificate_and_prints_it_masked(tmp_path: Path, workspace_home: Path, capsys):
    assert cli.main(["bank", str(draw(tmp_path / "Godavari Vemulapati.pdf", [CERTIFICATE]))]) == 0
    out = printed(capsys)
    for secret in ["Lalitha", "Vemulapati", "CIF00004417", "3301", "1100.00", "157546.30"]:
        assert secret not in out
    assert "interest certificate for the financial year ended 31-03-2026; 3 accounts; 1 of 1 checks pass" in out
    assert "account ending #### (**): tax deducted" in out
    assert "account ending #### (**): no tax deducted, some under OVERHEAD TAX DEDUCTED" in out
    saved = workspace_home / "forms" / "certificate-3301-20260331.json"
    found = json.loads(saved.read_text())
    assert [d["tax"] for d in found["deposits"]] == ["1100.00", "0.00", "0.00"] and "Lalitha" not in saved.read_text()
