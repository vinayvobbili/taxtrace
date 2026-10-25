"""India's ITR-2 from a made-up non-resident's return: a house sold, interest, TDS settled with a refund."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from conftest import make_pdf, printed

from taxtrace import cli, itr, text

HEADER = [
    "Acknowledgement Number : 482019357700416                  Date of Filing : 14-Aug-2025*",
    "INDIAN INCOME TAX RETURN",
    "FORM [For Individuals and HUFs not having income from profits and gains of business or profession]"
    " Assessment Year",
    "ITR-2 (Please see Rule 12 of the Income-tax Rules, 1962) 2025-26",
    "PART A-GENERAL",
    "(A1) First Name  Tarunika   (A3) Last Name  Pemmaraju   (A4) PAN  QWERT4821K",
    "(e) Residential Status in India                 Non Resident during the previous year",
]
CAPITAL_GAINS = [
    "SCHEDULE CG CAPITAL GAINS",
    "A(I) Short-term Capital Gains (STCG) (Sub-items 4 and 5 are not applicable for residents) A",
    "B(I) Long-term capital gain (LTCG) (Sub-items 3, 4, 5 & 6 are not applicable for residents) B",
    "From sale of land or building or both (fill up details separately for each property from",
    "Date of Purchase/Acquisition       Date of Sale/Transfer",
    "18/05/2006                         11/02/2025",
    "a i Full value of consideration received/receivable ai 48,50,000",
    "ii Value of property as per stamp valuation authority aii 47,20,000",
    "iii of Capital Gains [in case (aii) does not exceed 1.10 times (ai), take this aiii 48,50,000",
    "i Cost of acquisition without indexation bi 9,80,000",
    "1   2,40,000 2014-15   0",
    "Total   2,40,000   0",
    "biii Expenditure wholly and exclusively in connection with transfer biii 0",
    "c Balance (aiii - biv) 1c 36,30,000",
    "Total   B1d   0",
    "e Long-term Capital Gains on immovable property (1c - 1d) B1e 36,30,000",
]
OTHER_SOURCES = [
    "SCHEDULE OS INCOME FROM OTHER SOURCES",
    "B Interest, Gross (bi + bii + biii + biv + bv + bvi + bvii + bviii + bix) 1b 18,240",
    "bi From Savings Bank bi 16,900",
]
TAX = [
    "Part B - TTI Computation of tax liability on total income",
    "d Tax Payable on Total Income (2a + 2b -2c) 2d 4,53,750",
    "Gross tax liability (7 + 7iv + 8) 9 4,72,580",
    "Net tax liability (12-13d) (enter zero if negative) 14 4,72,580",
    "e Total Interest and Fee Payable (15a+15b+15c+15d) 15e 0",
    "Aggregate liability (14+15e) 16 4,72,580",
    "a Advance Tax (from column 5 of 18A) 17a 0",
    "b TDS (total of column 5 of 18B and column 9 of 18C) 17b 9,70,000",
    "c TCS (total of column 5(i) of 18D) 17c 0",
    "d Self Assessment Tax (from column 5 of 18A) 17d 0",
    "e Total Taxes Paid (17a+17b+17c+17d) 17e 9,70,000",
    "Amount payable (Enter if 16 is greater than 17e, else enter 0) 18 0",
    "Refund (If 17e is greater than 16) (Refund, if any, will be directly credited into the bank account) 19 4,97,420",
    "SCHEDULE TDS2 - 194C DETAILS OF TAX DEDUCTED AT SOURCE (TDS) ON INCOME",
    "1 Self  HYDK04417E  9,70,000  9,70,000  Capital Gains",
    "Total   9,70,000",
    "SCHEDULE TCS - DETAILS OF TAX COLLECTED AT SOURCE",
]
RETURN = [HEADER, CAPITAL_GAINS, OTHER_SOURCES, TAX]
SECRETS = ["48,50,000", "47,20,000", "9,80,000", "2,40,000", "36,30,000", "18,240", "16,900", "4,72,580",
           "9,70,000", "4,97,420", "Tarunika", "Pemmaraju", "QWERT4821K", "482019357700416", "HYDK04417E", "18/05",
           "11/02"]


def test_a_non_residents_return_gives_the_sale_the_interest_and_what_india_kept(tmp_path: Path):
    path = make_pdf(tmp_path / "itr2.pdf", RETURN)
    pages = text.pages(path)
    assert itr.is_return(pages)
    found = itr.read(path.name, pages)
    assert (found.version, found.year, found.filed, found.status) == ("ITR-2", "2025-26", "14-Aug-2025", "Non Resident")
    assert [str(d) for d in found.financial_year] == ["2024-04-01", "2025-03-31"]
    (sale,) = found.sales
    assert (sale.term, sale.acquired, sale.sold, str(sale.sold_on)) == ("long", "18/05/2006", "11/02/2025",
                                                                       "2025-02-11")
    assert {k: v.amount for k, v in sale.amounts.items()} == {
        "consideration": 4850000, "stamp_value": 4720000, "adopted": 4850000, "cost": 980000,
        "transfer_expenses": 0, "balance": 3630000}
    assert [(i.amount.amount, i.year) for i in sale.improvements] == [(240000, "2014-15")]
    assert (sale.exemption.amount, sale.gain.amount) == (0, 3630000)
    assert {k: v.amount for k, v in found.interest.items()} == {"interest": 18240, "savings": 16900}
    assert found.kept == Decimal(472580) == found.tax["aggregate"].amount
    assert found.failed == [] and len(found.checks) == 6
    assert [q.text.split(":")[0] for q in found.questions] == ["sale 1", "sale 1"]  # improvements' dates, ownership
    assert not any(c in json.dumps([q.text for q in found.questions]) for c in ("2006", "2025"))


def test_a_refund_rounded_to_ten_rupees_still_adds_up():
    rounded = [line.replace("4,97,420", "4,97,416") for line in TAX]
    found = itr.read("itr2.pdf", ["\n".join(HEADER), "\n".join(rounded)])
    assert found.failed == []
    found = itr.read("itr2.pdf", ["\n".join(HEADER), "\n".join(line.replace("4,97,420", "4,96,420") for line in TAX)])
    assert [c.what for c in found.failed] == ["the refund is the taxes paid less the aggregate liability"]


def test_cli_saves_the_return_and_prints_it_masked(tmp_path: Path, workspace_home: Path, capsys):
    path = make_pdf(tmp_path / "ITR2 Tarunika.pdf", RETURN)
    assert cli.main(["itr", str(path)]) == 0
    out = printed(capsys)
    for secret in SECRETS:
        assert secret not in out
    assert "ITR-2 for assessment year 2025-26 (India's year 04/2024 to 03/2025), Non Resident" in out
    assert "  sale: long-term, acquired ##/##/2006, sold ##/##/2025; rows: consideration, stamp value" in out
    (saved,) = json.loads((workspace_home / "forms" / "itr-2025-26.json").read_text())
    assert (saved["form"], saved["version"], saved["kept"], saved["sales"][0]["gain"]["amount"]) == (
        "ITR", "ITR-2", "472580", "3630000")
    assert "QWERT4821K" not in json.dumps(saved) and "482019357700416" not in json.dumps(saved)
