"""A made-up Indian bank's statement of account: an invented branch, holder, account and amounts."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from conftest import printed
from test_k1 import draw

from taxtrace import cli, statement, text

HEAD = [
    (30, 40, "Kesavapuram Co-operative Bank, Tirumalagiri Branch"),
    (30, 54, "Account Holder : Mrudula Kanchibhotla"),
    (30, 68, "Statement of Account No : 000123459876"),
    (30, 82, "Acct Currency : INR"),
    (30, 96, "Statement for Period : 01-04-2025 to 31-03-2026"),
    (30, 120, "Date"), (84, 120, "Withdrawal"), (146, 120, "Deposit"), (208, 120, "Balance"),
    (270,120, "Particulars"),
]
ROWS = [
    (30, 140, "15-05-2025"), (84, 140, "590.00"), (208, 140, "102410.00"), (248,140, "Cr."),
    (270,140, "SMS CHARGES FY:2025-2026"),
    (30, 160, "30-06-2025"), (146, 160, "812.00"), (208, 160, "103222.00"), (248,160, "Cr."),
    (270,160, "Int.Pd From :01-04-2025 to 30-06-2025"),
    # a description of two lines, centred on its row: one line above the date, one below
    (270,174, "NEFT IN::CMS9988/ITD"),
    (30, 180, "02-12-2025"), (146, 180, "4970.00"), (208, 180, "108192.00"), (248,180, "Cr."),
    (270,186, "REFUND 2025-26 TAX"),
    (30, 206, "31-12-2025"), (84, 206, "81.20"), (208, 206, "108110.80"), (248,206, "Cr."),
    (270,206, "TDS ON INTEREST"),
    (30, 226, "Grand Total"), (84, 226, "671.2"), (146, 226, "5782.0"),
    (30, 236, "Printed on 05-04-2026"), (270,236, "Page 1 of 1"),
]
PAGE = HEAD + ROWS


def statement_page(period: str, rows: list[tuple[str, str, str, str, str]]) -> list:
    """A statement for `period` ("01-04-2024 to 31-03-2025") of one-line rows: (date, withdrawal, deposit, balance,
    description), an empty withdrawal or deposit left blank."""
    head = [(x, top, f"Statement for Period : {period}" if phrase.startswith("Statement for") else phrase)
            for x, top, phrase in HEAD]
    words = []
    for i, (on, out, dep, balance, description) in enumerate(rows):
        top = 140 + 20 * i
        words += [(30, top, on), (84, top, out), (146, top, dep), (208, top, balance), (248, top, "Cr."),
                  (270, top, description)]
    return head + [w for w in words if w[2]]


# The monthly layout: a row number, "05 Jan 2026" dates, the description left of the amounts, Indian commas, an
# opening balance row, interest credited net of its TDS, and the account summary on the next page.
MONTHLY = [
    (30, 40, "Account Statement"), (30, 55, "01 Jan 2026 - 31 Mar 2026"),
    (30, 80, "Sarayu Peddibhotla"), (300, 80, "Account No. 4471209935"),
    (300, 95, "Account Type NRO Savings A/c"), (300, 110, "Currency Indian Rupee"),
    (200, 180, "Savings Account Transactions"),
    (30, 200, "#"), (60, 200, "Date"), (110, 200, "Description"), (260, 200, "Chq/Ref. No."),
    (330, 200, "Withdrawal (Dr.)"), (410, 200, "Deposit (Cr.)"), (480, 200, "Balance"),
    (30, 215, "-"), (60, 215, "-"), (110, 215, "Opening Balance"), (495, 215, "1,02,410.00"),
    (30, 230, "1"), (60, 230, "05 Jan 2026"), (110, 230, "NEFT IN RAMAPURAM"), (260, 230, "REF-1"),
    (425, 230, "25,000.00"), (495, 230, "1,27,410.00"),
    (110, 238, "TRADERS CO"),  # the description's second line, under its row
    (30, 252, "2"), (60, 252, "12 Feb 2026"), (110, 252, "UPI 77.50 GROCER"), (260, 252, "UPI-77"),
    (345, 252, "4,410.00"), (495, 252, "1,23,000.00"),
    (30, 266, "3"), (60, 266, "31 Mar 2026"), (110, 266, "Int:1234.56 and TAX:123.45.-2026"),
    (425, 266, "1,111.11"), (495, 266, "1,24,111.11"),
    (30, 700, "Statement Generated on 02 Apr 2026, 10:15"), (480, 700, "Page 1 of 2"),
]
SUMMARY = [
    (30, 40, "Account No.4471209935"), (200, 90, "Account Summary"),
    (40, 110, "Account Opening Balance Closing Balance"),
    (40, 125, "Savings Account (SA):"), (300, 125, "1,02,410.00"), (420, 125, "1,24,111.11"),
]


def test_a_monthly_statement_with_net_interest_reads_as_interest_then_tds(tmp_path: Path):
    found = read(draw(tmp_path / "ramapuram-9935-2026-01.pdf", [MONTHLY, SUMMARY]))
    assert (found.account, found.currency, found.start, found.end) == ("9935", "INR", "01-01-2026", "31-03-2026")
    assert (str(found.opening), found.summary) == ("102410.00", (Decimal("102410.00"), Decimal("124111.11")))
    assert [(r.on, str(r.withdrawal), str(r.deposit), str(r.balance), r.kind) for r in found.rows] == [
        ("05-01-2026", "0", "25000.00", "127410.00", ""),
        ("12-02-2026", "4410.00", "0", "123000.00", ""),
        ("31-03-2026", "0", "1234.56", "124234.56", "interest"),  # the interest before its TDS
        ("31-03-2026", "123.45", "0", "124111.11", "tds"),
    ]
    assert found.rows[0].description == "NEFT IN RAMAPURAM REF-1 TRADERS CO"
    assert found.failed == [] and len(found.checks) == 6 and found.questions == []


def test_a_monthly_statement_off_its_summary_or_its_net_interest_fails(tmp_path: Path):
    swap = {"1,24,111.11": "1,24,111.10", "1,111.11": "1,111.10", "Currency Indian Rupee": "Currency INDIAN RUPEE"}
    page = [(x, top, swap.get(p, p)) for x, top, p in MONTHLY]
    found = read(draw(tmp_path / "statement.pdf", [page, SUMMARY]))
    assert found.currency == "INR"
    assert [c.what for c in found.failed] == ["the interest on 31-03-2026 less its TDS is what was credited",
                                              "the balance on 31-03-2026 follows from the one before",
                                              "the opening and closing balances are the account summary's"]


SECRETS = ["Mrudula", "Kanchibhotla", "000123459876", "9876", "102410.00", "4970.00", "108110.80", "9988"]


def read(path: Path) -> statement.Statement:
    pages = text.pages(path)
    assert statement.is_statement(pages[0])
    return statement.read(path.name, pages, {1: text.words(path, 1, None)})


def test_each_row_its_column_its_kind_and_its_whole_description(tmp_path: Path):
    found = read(draw(tmp_path / "statement.pdf", [PAGE]))
    assert (found.account, found.currency, found.start, found.end) == ("9876", "INR", "01-04-2025", "31-03-2026")
    assert [(r.on, str(r.withdrawal), str(r.deposit), str(r.balance), r.kind) for r in found.rows] == [
        ("15-05-2025", "590.00", "0", "102410.00", ""),
        ("30-06-2025", "0", "812.00", "103222.00", "interest"),
        ("02-12-2025", "0", "4970.00", "108192.00", "tax refund"),
        ("31-12-2025", "81.20", "0", "108110.80", "tds"),  # TDS on interest is withheld, not interest
    ]
    assert found.rows[2].description == "NEFT IN::CMS9988/ITD REFUND 2025-26 TAX"
    assert "Page" not in found.rows[-1].description
    assert found.failed == [] and len(found.checks) == 4 and found.questions == []


def test_a_balance_that_doesnt_follow_fails(tmp_path: Path):
    page = [(x, top, "108191.00" if phrase == "108192.00" else phrase) for x, top, phrase in PAGE]
    found = read(draw(tmp_path / "statement.pdf", [page]))
    assert [c.what for c in found.failed] == ["the balance on 02-12-2025 follows from the one before",
                                              "the balance on 31-12-2025 follows from the one before"]


def test_cli_saves_the_statement_and_prints_it_masked(tmp_path: Path, workspace_home: Path, capsys):
    path = draw(tmp_path / "Statement Kanchibhotla.pdf", [PAGE])
    assert cli.main(["bank", "--rows", str(path)]) == 0
    out = printed(capsys)
    for secret in SECRETS:
        assert secret not in out
    assert ("account ending #### in INR, 01-04-2025 to 31-03-2026; 4 rows (1 interest, 1 tax refund, 1 tds, "
            "0 tds refund); 4 of 4 checks pass") in out
    assert "  02-12-2025 deposit tax refund: " in out
    (saved,) = json.loads((workspace_home / "forms" / "bank-9876-20250401.json").read_text())
    assert (saved["form"], saved["account"], len(saved["rows"])) == ("BANK", "9876", 4)
    assert "000123459876" not in json.dumps(saved) and "Account Holder" not in json.dumps(saved)
