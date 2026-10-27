"""Exchange rates and the foreign side in dollars, from made-up rates and the made-up ITR in test_itr."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import make_pdf, printed
from test_certificate import CERTIFICATE
from test_itr import RETURN, SECRETS
from test_k1 import draw
from test_statement import ALL_ACCOUNTS, MONTHLY, PAGE, SUMMARY, statement_page
from test_statement import SECRETS as STATEMENT_SECRETS
from test_tds import FORM_16A

from taxtrace import cli, foreign, fx

FRED_CSV = "observation_date,DEXINUS\n2006-05-17,45.1000\n2006-05-18,45.2000\n2006-05-19,\n" \
           "2014-04-01,60.0000\n2015-03-31,62.0000\n2025-02-07,87.4000\n2025-02-10,87.5000\n2025-02-11,87.6000\n" \
           "2025-12-31,90.2000\n"
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
    assert foreign.confirmation("improvement_dates=Average") == ("improvement_dates", "average")
    assert foreign.confirmation("account_4410=Joint") == ("account_4410", "joint")
    assert foreign.confirmation("tds_20260331=Taken") == ("tds_20260331", "taken")
    for bad in ("owner=cousin", "improvement_dates=15/09/2014", "rate=88", "account_4410=other", "account_44=self",
                "tds_2026-03-31=taken", "tds_20260331=maybe"):
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
    # dates not known: the financial year's mean rate stands, and the question is settled
    assert cli.main(["foreign", "--year", "2025", "--confirm", "improvement_dates=average"]) == 0
    saved = json.loads((workspace_home / "foreign" / "2025.json").read_text())
    assert saved["questions"] == [] and saved["sales"][0]["improvements"][0]["dollars"] == "3934.43"


def test_bank_statements_give_the_interest_the_refund_and_whether_to_report(tmp_path: Path, workspace_home: Path,
                                                                           capsys, monkeypatch):
    monkeypatch.setattr(fx, "_get", fake_get([]))
    assert cli.main(["itr", str(make_pdf(tmp_path / "itr2.pdf", RETURN))]) == 0
    # India's refund of 4,97,420 arrives with 14,920 of interest on it
    swap = {"4970.00": "512340.00", "108192.00": "615562.00", "108110.80": "615480.80", "5782.0": "513152.0"}
    later = [(x, top, swap.get(phrase, phrase)) for x, top, phrase in PAGE]
    assert cli.main(["bank", str(draw(tmp_path / "later.pdf", [later]))]) == 0
    capsys.readouterr()
    assert cli.main(["foreign", "--year", "2025"]) == 0
    saved = json.loads((workspace_home / "foreign" / "2025.json").read_text())
    (account,) = saved["accounts"]
    assert (account["covered"], account["missing"]) == (["2025-04-01..2025-12-31"], ["2025-01-01..2025-03-31"])
    assert (account["interest"]["amount"], account["interest"]["dollars"]) == ("812.00", "9.33")  # at 87.011
    (refund,) = saved["refunds"]
    assert (refund["arrived"], refund["interest"]["amount"], refund["interest"]["dollars"]) == (
        "2025-12-02", "14920.00", "171.47")
    assert saved["interest"] == "180.80"
    assert [(t["kept"]["what"], t["kept"]["dollars"]) for t in saved["taxes"]][1:] == [("TDS on interest", "0.90")]
    # without January to March, the highest balance isn't known yet, nor how the return files
    assert saved["reporting"] == {"fbar": None, "form_8938": None}
    asked = [q["text"] for q in saved["questions"]]
    assert any(t.startswith("account 1: its statements don't cover 2025-01-01 to 2025-03-31") for t in asked)
    assert any(t.startswith("how you file") for t in asked)

    earlier = statement_page("01-04-2024 to 31-03-2025", [
        ("11-02-2025", "", "3880000.00", "3980000.00", "RTGS IN HOUSE SALE"),
        ("20-03-2025", "3877000.00", "", "103000.00", "SWIFT OUT OWN ACCOUNT"),
    ])
    assert cli.main(["bank", str(draw(tmp_path / "earlier.pdf", [earlier]))]) == 0
    capsys.readouterr()
    assert cli.main(["foreign", "--year", "2025", "--confirm", "filing=joint"]) == 0
    # each spouse's FBAR is of the accounts in their name: until it's known whose this one is, neither is settled
    assert "  your FBAR: not settled yet\n  Form 8938: not due\n" in printed(capsys)
    assert cli.main(["foreign", "--year", "2025", "--confirm", "account_9876=spouse"]) == 0
    out = printed(capsys)
    for secret in [*STATEMENT_SECRETS, "3980000", "615480"]:
        assert secret not in out
    assert ("  account 1: India, ending #### in INR, your spouse's, covers 2025-01-01 to 2025-12-31; interest at IRS "
            "yearly") in out
    assert "  India's refund: arrived 2025-12-02, with interest on it (Schedule B) at IRS yearly" in out
    assert "  your FBAR: not due\n  your spouse's FBAR: due\n  Form 8938: not due\n" in out
    assert "  confirmed: filing, account ####\n" in out
    saved = json.loads((workspace_home / "foreign" / "2025.json").read_text())
    (account,) = saved["accounts"]
    assert account["missing"] == [] and account["holder"] == "spouse"
    assert saved["reporting"] == {"fbar": False, "fbar_spouse": True, "form_8938": False}
    # the sale's price, at the Treasury's December 31 rate (89.411); December 31's is the last row's
    assert (account["highest"]["amount"], account["highest"]["dollars"]) == ("3980000.00", "44513.54")
    assert (account["december_31"]["amount"], account["december_31"]["dollars"]) == ("615480.80", "6883.73")
    assert not any(q["text"].startswith(("account", "how you file")) for q in saved["questions"])


def test_a_year_still_going_is_estimated_at_the_latest_days_rate(tmp_path: Path, workspace_home: Path, monkeypatch):
    monkeypatch.setattr(fx, "_get", fake_get([]))
    assert cli.main(["bank", str(draw(tmp_path / "monthly.pdf", [MONTHLY, SUMMARY]))]) == 0
    statements = [s for f in sorted((workspace_home / "forms").glob("bank-*.json")) for s in json.loads(f.read_text())]
    csv = FRED_CSV + "2026-03-31,85.0000\n2026-10-23,88.1000\n"
    rates = fx.Rates("INR", tmp_path / "fx", get=lambda url: csv if "fred" in url else fake_get([])(url))
    found = foreign.build(2026, itrs=[], rates=rates, statements=statements, today=date(2026, 10, 25))
    (account,) = found.accounts
    assert found.estimated and account.interest.rate.day == "2026-10-23"  # no IRS 2026 average yet
    assert (account.interest.amount, account.interest.dollars) == (Decimal("1234.56"), Decimal("14.01"))
    assert (account.highest.amount, account.highest.dollars) == (Decimal("127410.00"), Decimal("1446.20"))
    assert [(t.kept.what, t.kept.dollars) for t in found.taxes] == [("TDS on interest", Decimal("1.45"))]  # at 85
    # once the year is over, its own rates are asked for
    found = foreign.build(2026, itrs=[], rates=rates, statements=statements, today=date(2027, 2, 1))
    assert not found.estimated and any("no 2026 rate" in q.text for q in found.questions)


def test_each_account_of_a_statement_of_every_account_has_its_balance(tmp_path: Path, workspace_home: Path,
                                                                     monkeypatch):
    monkeypatch.setattr(fx, "_get", fake_get([]))
    assert cli.main(["bank", str(draw(tmp_path / "godavari.pdf", ALL_ACCOUNTS))]) == 0
    statements = [s for f in sorted((workspace_home / "forms").glob("bank-*.json")) for s in json.loads(f.read_text())]
    csv = FRED_CSV + "2026-10-23,88.1000\n"
    rates = fx.Rates("INR", tmp_path / "fx", get=lambda url: csv if "fred" in url else fake_get([])(url))
    found = foreign.build(2026, itrs=[], rates=rates, statements=statements, today=date(2026, 10, 25))
    accounts = {a.account: a for a in found.accounts}
    deposit, savings, quiet = accounts["3301"], accounts["5520"], accounts["7781"]
    assert (deposit.kind, savings.kind) == ("term deposit", "savings")
    assert deposit.highest.amount == Decimal("157546.30")  # its principal and the interest accrued on it
    assert (savings.highest.amount, savings.interest.amount) == (Decimal("52379.65"), Decimal("379.65"))
    assert quiet.highest.amount == Decimal("0.00") and quiet.covered == ["2026-03-01..2026-03-31"]
    # interest added to a deposit is the year's: one opened in the year from its principal, the other needs December's
    assert accounts["3302"].interest.amount == Decimal("1706.85") and deposit.interest is None
    assert any(q.text.startswith("account 1: a term deposit without a statement from before 2026") for q in
               found.questions)


def three_months(tmp_path: Path, home: Path) -> tuple[list[dict], fx.Rates]:
    """Statements of every account for December, February and March: the 1,50,000 deposit worth 1,55,000, then
    1,58,000, then 1,57,546.30 after March 31's TDS."""

    def month(as_on: str, start: str, accrued: str) -> list:
        swap = {"As on 31-03-26": f"As on {as_on}", "7546.30": accrued}
        return [[(x, top, swap.get(p, p).replace("31-03-26", as_on).replace("01-03-26", start)) for x, top, p in page]
                for page in ALL_ACCOUNTS]

    for name, pages in [("december", month("31-12-25", "01-12-25", "5000.00")),
                        ("february", month("28-02-26", "01-02-26", "8000.00")), ("march", ALL_ACCOUNTS)]:
        assert cli.main(["bank", str(draw(tmp_path / f"gramin-{name}.pdf", pages))]) == 0
    statements = [s for f in sorted((home / "forms").glob("bank-*.json")) for s in json.loads(f.read_text())]
    csv = FRED_CSV + "2026-03-31,85.0000\n2026-10-23,88.1000\n"
    return statements, fx.Rates("INR", tmp_path / "fx", get=lambda url: csv if "fred" in url else fake_get([])(url))


def test_a_term_deposits_interest_is_what_its_value_grew_by_and_a_fall_is_asked_about(tmp_path: Path,
                                                                                    workspace_home: Path, monkeypatch):
    monkeypatch.setattr(fx, "_get", fake_get([]))
    statements, rates = three_months(tmp_path, workspace_home)
    found = foreign.build(2026, itrs=[], rates=rates, statements=statements, today=date(2026, 10, 25))
    (deposit,) = [a for a in found.accounts if a.account == "3301"]
    assert deposit.interest.amount == Decimal("2546.30")  # 1,57,546.30 on March 31 less 1,55,000 on December 31
    assert any(q.text.startswith("account 1: the term deposit's value fell on 2026-03-31: was TDS taken") for q in
               found.questions)


def test_the_interest_certificates_tax_is_the_fall_on_march_31_and_interest_too(tmp_path: Path,
                                                                                 workspace_home: Path, monkeypatch):
    monkeypatch.setattr(fx, "_get", fake_get([]))
    statements, rates = three_months(tmp_path, workspace_home)
    assert cli.main(["bank", str(draw(tmp_path / "gramin-certificate.pdf", [CERTIFICATE]))]) == 0
    certificates = [json.loads((workspace_home / "forms" / "certificate-3301-20260331.json").read_text())]
    found = foreign.build(2026, itrs=[], rates=rates, statements=statements, certificates=certificates,
                          today=date(2026, 10, 25))
    (deposit,) = [a for a in found.accounts if a.account == "3301"]
    assert deposit.interest.amount == Decimal("3646.30")  # what the value grew by, and the 1,100 taken from it
    (tds,) = found.taxes
    assert (tds.kept.what, tds.kept.amount, tds.kept.rate.day, tds.category) == (
        "TDS on interest", Decimal("1100.00"), "2026-03-31", "passive")
    # the other deposit's overhead, charged and not taken, is asked about and isn't a tax yet
    assert [q.text[:90] for q in found.questions if "fell" in q.text or "certificate" in q.text] == [
        "account 2: the interest certificate for the year ended 2026-03-31 shows overhead tax on it"]

    # more tax than a fall of 453.70 and a quarter's interest can explain: some was taken on another day
    certificates[0]["deposits"][0]["tax"] = "5000.00"
    found = foreign.build(2026, itrs=[], rates=rates, statements=statements, certificates=certificates,
                          today=date(2026, 10, 25))
    assert not found.taxes
    asked = [q.text for q in found.questions if "fell" in q.text or "tax for the year" in q.text]
    assert len(asked) == 1 and asked[0].startswith("account 1: the interest certificate's tax for the year ended "
                                                   "2026-03-31 isn't what the term deposit's value fell by")


def test_the_quarters_tds_certificate_counts_what_no_statement_shows_once(tmp_path: Path, workspace_home: Path,
                                                                          monkeypatch):
    monkeypatch.setattr(fx, "_get", fake_get([]))
    statements, rates = three_months(tmp_path, workspace_home)
    assert cli.main(["bank", str(draw(tmp_path / "gramin-certificate.pdf", [CERTIFICATE])),
                     str(draw(tmp_path / "gramintds-q4.pdf", [FORM_16A]))]) == 0
    forms = workspace_home / "forms"
    certificates = [json.loads((forms / "certificate-3301-20260331.json").read_text())]
    quarter = json.loads((forms / "tds-gramintds-q4.json").read_text())
    confirmed = {"bank_gramin": "Godavari Grameena Bank; Main Road, Vennelapadu"}

    def build(deducted: str, confirmed: dict = confirmed) -> foreign.Foreign:
        return foreign.build(2026, itrs=[], rates=rates, statements=statements, certificates=certificates,
                             quarters=[{**quarter, "deducted": deducted}], confirmed=confirmed,
                             today=date(2026, 10, 25))

    found = build("1100.00")  # the interest certificate's 1,100 on March 31: nothing more
    assert len(found.taxes) == 1 and not found.withheld
    assert found.reconciled == ["India's TDS certificate for 2026-01-01 to 2026-03-31 matches the TDS found"]

    found = build("1500.00")  # 400 more than found: asked about, not counted, till Form 26AS says where it came from
    assert len(found.taxes) == 1 and not found.withheld
    (asked,) = [q.text for q in found.questions if "more tax" in q.text]
    assert "--confirm tds_20260331=taken" in asked and "interest credited in" not in asked
    assert len(build("1500.00", {**confirmed, "tds_20260331": "not"}).taxes) == 1
    early = {**quarter, "deducted": "1500.00", "payments": [{**quarter["payments"][0], "on": "02-07-2025"}]}
    late = foreign.build(2026, itrs=[], rates=rates, statements=statements, certificates=certificates,
                         quarters=[early], confirmed=confirmed, today=date(2026, 10, 25))
    assert any("interest credited in 2025, but tax counts in the year it was taken when Form 1116 claims taxes paid"
               in q.text for q in late.questions)

    # Form 26AS says the 400 was taken in the quarter from a term deposit: a tax, and interest the value never showed
    found = build("1500.00", {**confirmed, "tds_20260331": "taken"})
    assert [(t.kept.amount, t.on, t.file) for t in found.taxes][1:] == [
        (Decimal("400.00"), "2026-03-31", "gramintds-q4.pdf")]
    (extra,) = found.withheld
    assert (extra.amount, extra.rate.source) == (Decimal("400.00"), "FRED DEXINUS")  # a daily rate till 2026 ends
    assert found.estimated

    assert any("shows less tax" in q.text for q in build("900.00").questions)
    assert any("its bank isn't confirmed" in q.text for q in build("1100.00", {}).questions)
