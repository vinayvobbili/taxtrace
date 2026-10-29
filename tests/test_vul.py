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
    assert "no variable universal life statement or in-force illustration found" in err


STATUS = """
          Policy Issue Date                 03/03/2020
          Policy Values Date                03/10/2026
          Current Basic Insurance Amount $250,000.00
          Type B (Increasing) Death Benefit , Guideline Premium Test
                             Policy Status Report
          Current Billed Premium and Payment Frequency $6,000.00paid Annually
          Current Short-Term No-Lapse Guarantee Premium $1,080.00
          Current Limited No-Lapse Guarantee Premium $2,400.00
          Contract Fund $46,000.00
          Cash Value $43,700.00
          Death Benefit $296,000.00
          Total Premium Outlay to Date $46,000.00
          Surrender charges may apply if you make a withdrawal on a policy with
          a Type A (Fixed) death benefit, reduce the Basic Insurance Amount, or surrender the policy.
"""
LEDGER = """
          Next Scheduled Annual Premium $0.00
          Non-Guaranteed Results Based on Hypothetical Annual Gross Returns and Assumed Charges
  6.00% (Net 5.10%) @ and 6.00% (Net 5.10%)@ and 3.00% (Net 2.10%) @ and 3.00% (Net 2.10%)@ and 0.00% (Net -0.90%) @
       Current Charges        Maximum Charges        Current Charges        Maximum Charges     and Maximum Charges
         Annual
         Premium Contract   Cash     Death     Cash     Death     Cash     Death     Cash     Death    Cash    Death
  Year Age Outlay  Fund     Value   Benefit    Value   Benefit    Value   Benefit    Value   Benefit  Value  Benefit
   7*  46    0   47,000   45,000  297,000<   44,000  297,000<   45,000  296,000<   44,000  296,000<  43,000 295,000<
   8   47    0   48,000   47,500  298,000<   46,000  298,000<   45,500  296,000<   44,000  295,000<  41,000 293,000<
   9   48    0   50,000   50,000  300,000<   48,000  299,000<   46,000  296,000<   43,000  294,000<  END‡    END‡
  10   49    0   52,000   52,000  302,000    49,000  300,000    46,500  296,000    END‡     END‡
  17   56    0   81,000   81,000  331,000    66,000  316,000    56,000  306,000
              Total $0
"""


def test_an_illustration_reads_todays_values_the_scenarios_and_each_years_cells():
    ill = vul.read_illustration("illustration.pdf", [STATUS, LEDGER])
    assert ill and ill.kind == "B" and ill.issued == date(2020, 3, 3) and ill.values_date == date(2026, 3, 10)
    assert ill.status["cash"] == Decimal("43700.00") and ill.status["next"] == 0 and ill.status["billed"] == 6000
    assert [(s.gross, s.net, s.charges) for s in ill.scenarios] == [
        ("6.00", "5.10", "current"), ("6.00", "5.10", "maximum"), ("3.00", "2.10", "current"),
        ("3.00", "2.10", "maximum"), ("0.00", "-0.90", "maximum")]
    assert [y.year for y in ill.years] == [7, 8, 9, 10, 17]
    ninth, tenth, last = ill.years[2], ill.years[3], ill.years[4]
    assert ninth.cells[4] is None and tenth.cells[3] is None and 4 not in tenth.cells
    assert last.cells[2] == vul.Cell(Decimal(56000), Decimal(306000), False) and set(last.cells) == {0, 1, 2}
    assert ninth.cells[0].guaranteed and not tenth.cells[0].guaranteed


def test_illustration_shares_give_lapse_years_guarantees_and_growth_without_any_figure():
    lines = vul.illustration_shares(vul.read_illustration("illustration.pdf", [STATUS, LEDGER]))
    assert lines == [
        "in-force illustration: Type B death benefit, issued 2020-03-03, values as of 2026-03-10",
        "illustrated with no more premiums; the premium on file is still billed: ask the insurer to stop billing it",
        "today: cash value 95% of the premiums paid; the contract fund 100%, of which the surrender charge is 5%",
        "death benefit today: 6.8x the cash value",
        "no-lapse guarantee premiums: short-term 18%, limited 40% of the billed premium",
        "surrender charge: 4% of the fund at the end of policy year 7, 1% of the fund at the end of policy year 8, "
        "none from policy year 9 (age 48)",
        "6.00% gross (5.10% net), current charges: in force through age 56; no-lapse guarantee through policy year 9 "
        "(age 48); cash value grows 6.1% a year over the 10 years from policy year 7 (to age 56)",
        "6.00% gross (5.10% net), maximum charges: in force through age 56; no-lapse guarantee through policy year 9 "
        "(age 48); cash value grows 4.1% a year over the 10 years from policy year 7 (to age 56)",
        "3.00% gross (2.10% net), current charges: in force through age 56; no-lapse guarantee through policy year 9 "
        "(age 48); cash value grows 2.2% a year over the 10 years from policy year 7 (to age 56)",
        "3.00% gross (2.10% net), maximum charges: lapses in policy year 10 (age 49); no-lapse guarantee through "
        "policy year 9 (age 48)",
        "0.00% gross (-0.90% net), maximum charges: lapses in policy year 9 (age 48); no-lapse guarantee through "
        "policy year 8 (age 47)"]
    assert not any(f in " ".join(lines) for f in ("6,000", "43,700", "46,000", "81,000", "250,000", "296,000"))


def test_the_command_reads_an_illustration_too(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "_open", lambda doc: [STATUS, LEDGER])
    assert cli.main(["vul", str(tmp_path / "illustration.pdf")]) == 0
    out = capsys.readouterr().out
    assert "lapses in policy year 10 (age 49)" in out and "81,000" not in out


def test_a_statement_is_not_an_illustration():
    assert vul.read_illustration("statement.pdf", [FRONT, RETURNS, LAPSE]) is None
