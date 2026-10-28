"""A variable universal life statement read as shares of its own figures, from made-up pages laid out like an
insurer's year-to-date statement."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from taxtrace import cli, vul

FRONT = """
          Death Benefit Type Type B (Increasing) Annual Billed Premium $ 6,000.00
          Activity From                     Contract Date    March 3, 2020
          Base Policy Death Benefit          $ 240,000.00           $ 246,000.00
          Contract Fund                       $ 40,000.00           $ 46,000.00
          Surrender Charge                   - $ 4,000.00           - $ 2,300.00
          Cash Value                          $ 36,000.00           $ 43,700.00
"""
RETURNS = """
         Contract Fund Rate of Return
          Since               Period Beginning   Period Ending    Rate of Return
                                                                         4.5%
          Beginning of the Current Year                        Average Return for Period
                                                                        8.2%
          Contract Date       March 3, 2020 June 30, 2026 Annualized Return
"""
LAPSE = """
         As of June 30, 2026:
         The accumulated net payments needed for a No-Lapse Guarantee were $ 4,600.00. Your
         accumulated net payments of $ 46,000.00 were sufficient to provide you with a No-Lapse Guarantee.
         The accumulated net payments needed for a No-Lapse Guarantee that extends beyond the first 10 policy years
         to age 80 were $ 23,000.00.
"""


def test_the_statement_reads_both_dates_values_and_the_guarantees():
    s = vul.read("statement.pdf", [FRONT, RETURNS, LAPSE])
    assert s and s.kind == "B" and s.issued == date(2020, 3, 3) and s.as_of == date(2026, 6, 30)
    assert s.premium == Decimal("6000.00") and s.current["fund"] == Decimal("46000.00")
    assert s.previous["surrender"] == Decimal("4000.00") and s.current["cash"] == Decimal("43700.00")
    assert (s.paid, s.needed, s.lifetime_needed, s.lifetime_age) == (Decimal(46000), Decimal(4600), Decimal(23000), 80)
    assert s.returns == ("4.5", "8.2") and vul.policy_year(s) == 7


def test_shares_say_how_the_figures_compare_without_any_of_them():
    lines = vul.shares(vul.read("statement.pdf", [FRONT, RETURNS, LAPSE]))
    assert lines == [
        "Type B death benefit, issued 2020-03-03: policy year 7 as of 2026-06-30",
        "surrender charge: 5% of the contract fund (10% at the previous statement), lost if surrendered now",
        "cash value: 95% of the net payments made so far; the contract fund is 100% of them",
        "annual premium: 3.00% of the insurance amount (the death benefit less the fund)",
        "no-lapse guarantee: needs 10% of the payments made so far; the one to age 80 needs 50% of them",
        "death benefit: 5.3x the contract fund",
        "fund return: 4.5%, 8.2% (this year to date, then a year since the contract date)"]
    assert not any(figure in " ".join(lines) for figure in ("6,000", "46,000", "246,000", "2,300", "23,000"))


def test_other_documents_are_not_statements():
    assert vul.read("declarations.pdf", ["Total Annual Premium: $1,204.00"]) is None


def test_the_command_prints_the_shares_and_names_what_it_could_not_read(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_open", lambda doc: [FRONT, RETURNS, LAPSE] if doc.name == "a.pdf" else ["nothing"])
    assert cli.main(["vul", str(tmp_path / "a.pdf"), str(tmp_path / "b.pdf")]) == 1
    out, err = capsys.readouterr()
    assert "surrender charge: 5% of the contract fund" in out and "46,000" not in out
    assert "no variable universal life statement found" in err
