"""Exchange rates and the foreign side in dollars, from made-up rates and the made-up ITR in test_itr."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import make_pdf, printed
from test_itr import RETURN, SECRETS

from taxtrace import cli, foreign, fx

FRED_CSV = "observation_date,DEXINUS\n2006-05-17,45.1000\n2006-05-18,45.2000\n2006-05-19,\n" \
           "2014-04-01,60.0000\n2015-03-31,62.0000\n2025-02-07,87.4000\n2025-02-10,87.5000\n2025-02-11,87.6000\n"
IRS_HTML = """<table><thead><tr><th scope="col">Country</th><th scope="col">Currency</th><th>2025</th>
<th>2024</th></tr></thead><tbody><tr><td><strong>India</strong></td><td>Rupee</td><td>87.011</td><td>83.512</td></tr>
<tr><td>Iceland</td><td>Krona</td><td>137.2</td><td>138.0</td></tr></tbody></table>"""
TREASURY_JSON = json.dumps({"data": [{"record_date": "2025-12-31", "country_currency_desc": "India-Rupee",
                                      "exchange_rate": "89.411"}]})


def fake_get(fetched: list[str]):
    def get(url: str) -> str:
        fetched.append(url)
        if "fred" in url:
            return FRED_CSV
        if "irs.gov" in url:
            return IRS_HTML
        return TREASURY_JSON
    return get


def test_each_rate_comes_from_its_source_once(tmp_path: Path):
    fetched: list[str] = []
    rates = fx.Rates("INR", tmp_path / "fx", get=fake_get(fetched))
    assert rates.daily(date(2025, 2, 11)).rate == Decimal("87.6000")
    weekend = rates.daily(date(2006, 5, 20))  # a Saturday after a day with no rate: the last day that had one
    assert (weekend.rate, weekend.day, weekend.source) == (Decimal("45.2000"), "2006-05-18", "FRED DEXINUS")
    assert rates.yearly(2025).rate == Decimal("87.011") and rates.yearly(2024).rate == Decimal("83.512")
    assert rates.year_end(2025).rate == Decimal("89.411")
    assert rates.average(date(2014, 4, 1), date(2015, 3, 31)).rate == Decimal("61.0000")
    assert len(fetched) == 3
    again = fx.Rates("INR", tmp_path / "fx", get=lambda url: pytest.fail(f"fetched {url} again"))
    assert again.daily(date(2025, 2, 10)).rate == Decimal("87.5000") and again.yearly(2025).rate == Decimal("87.011")
    assert again.year_end(2025).rate == Decimal("89.411")
    with pytest.raises(fx.NoRate):
        again.daily(date(1999, 1, 1))


def test_a_confirmation_must_be_one_the_foreign_side_takes():
    assert foreign.confirmation("owner=Spouse") == ("owner", "spouse")
    assert foreign.confirmation("improvement-dates=2014-09-15, 2015-01-02") == (
        "improvement_dates", "2014-09-15,2015-01-02")
    for bad in ("owner=cousin", "improvement_dates=15/09/2014", "rate=88"):
        with pytest.raises(ValueError):
            foreign.confirmation(bad)


def test_cli_puts_the_sale_and_indias_tax_in_dollars(tmp_path: Path, workspace_home: Path, capsys, monkeypatch):
    monkeypatch.setattr(fx, "_get", fake_get([]))
    assert cli.main(["itr", str(make_pdf(tmp_path / "itr2.pdf", RETURN))]) == 0
    capsys.readouterr()
    assert cli.main(["foreign", "--year", "2025"]) == 0
    out = printed(capsys)
    for secret in SECRETS:
        assert secret not in out
    assert "  Form 8949: House, India, long-term, from ***#.pdf; a gain in dollars" in out
    assert "  Form 1116: India, passive category, tax kept at FRED DEXINUS of" in out
    saved = json.loads((workspace_home / "foreign" / "2025.json").read_text())
    (sale,) = saved["sales"]
    # 48,50,000 / 87.6 on 11 Feb 2025; 9,80,000 / 45.2 on 18 May 2006; 2,40,000 / 61 (FY 2014-15's mean)
    assert (sale["proceeds"]["dollars"], sale["cost"]["dollars"], sale["improvements"][0]["dollars"]) == (
        "55365.30", "21681.42", "3934.43")
    assert (sale["basis"], sale["gain"]) == ("25615.85", "29749.45")
    assert saved["taxes"][0]["kept"]["dollars"] == "5394.75"  # 4,72,580 at the sale day's 87.6
    assert [q["text"].split(":")[1].strip()[:20] for q in saved["questions"]] == [
        "the date each improv", "who owned the proper"]

    assert cli.main(["foreign", "--year", "2025", "--confirm", "owner=spouse",
                     "--confirm", "improvement_dates=2014-04-01"]) == 0
    saved = json.loads((workspace_home / "foreign" / "2025.json").read_text())
    assert saved["questions"] == [] and saved["sales"][0]["improvements"][0]["dollars"] == "4000.00"
    assert cli.main(["foreign", "--year", "2025"]) == 0  # kept for later runs
    assert "confirmed: owner, improvement dates" in capsys.readouterr().out
