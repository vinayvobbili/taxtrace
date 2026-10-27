"""Form 8582 worked out from made-up activities, and rehearsed against a made-up filed return's worksheets."""

from __future__ import annotations

from decimal import Decimal

from taxtrace import f8582
from taxtrace.f8582 import Activity


def acts() -> list[Activity]:
    return [Activity("RENTAL PROPERTY", "IV", Decimal(-9000), Decimal(3000)),
            Activity("LARKSPUR RIDGE FUND LP", "V", Decimal(-4000), Decimal(1000)),
            Activity("QUENBY TERRACE LP", "V", Decimal(2500), Decimal(500))]


def test_income_covers_every_loss_and_nothing_carries_on():
    form = f8582.compute(2026, [Activity("A", "V", Decimal(5000)), Activity("B", "V", Decimal(-3000), Decimal(1000))])
    assert form.lines["3"] == Decimal(1000)
    assert [a.unallowed for a in form.activities] == [0, 0]
    assert [a.allowed for a in form.activities] == [Decimal(5000), Decimal(-4000)]


def test_without_the_special_allowance_line_3s_loss_is_shared_by_the_losses():
    form = f8582.compute(2026, acts(), magi=Decimal(240000), filing="joint")
    n = form.lines
    assert (n["1d"], n["2d"], n["3"], n["4"], n["8"], n["9"], n["10"], n["11"]) == (
        Decimal(-12000), Decimal(-3000), Decimal(-15000), Decimal(12000), 0, 0, Decimal(2500), Decimal(2500))
    rental, fund, quenby = form.activities
    assert (rental.unallowed, fund.unallowed, quenby.unallowed) == (Decimal(10588), Decimal(4412), 0)  # 12 : 5
    assert sum(a.allowed for a in form.activities) == n["10"] - n["11"]  # income less the losses allowed
    assert not form.questions


def test_the_special_allowance_goes_to_the_rental_first():
    form = f8582.compute(2026, acts(), magi=Decimal(130000), filing="joint")
    assert (form.lines["7"], form.lines["8"], form.lines["9"]) == (Decimal(20000), Decimal(10000), Decimal(10000))
    rental, fund, _ = form.activities
    assert rental.special == Decimal(10000)
    # line C: 15,000 less 10,000; shared by the rental's 2,000 left and the fund's 5,000
    assert (rental.unallowed, fund.unallowed) == (Decimal(1429), Decimal(3571))


def test_no_magi_or_a_separate_return_together_takes_no_allowance_and_asks():
    form = f8582.compute(2026, acts(), filing="joint")
    assert form.lines["9"] == 0 and "modified adjusted gross income" in form.questions[0].text
    form = f8582.compute(2026, acts(), magi=Decimal(50000), filing="separate")
    assert form.lines["9"] == 0 and "lived apart" in form.questions[0].text
    form = f8582.compute(2026, acts(), magi=Decimal(50000), filing="separate", lived_apart=True)
    assert form.lines["8"] == Decimal(12500)


def test_a_full_disposition_at_a_loss_is_off_the_form_and_at_a_gain_frees_its_own_loss():
    sold = Activity("SOLD LP", "V", Decimal(-2000), Decimal(6000), final=True)
    gain = Activity("GAIN LP", "V", Decimal(9000), Decimal(6000), final=True)
    other = Activity("OTHER LP", "V", Decimal(-1000))
    form = f8582.compute(2026, [sold, gain, other])
    assert sold.outside and sold.allowed == Decimal(-8000)
    assert not gain.outside and form.lines["3"] == Decimal(2000)
    assert other.allowed == Decimal(-1000)


def test_the_rehearsal_checks_a_filed_worksheet_5():
    filed = {"year": 2020, "activities": [
        {"worksheet": "3", "activity": "RENTAL PROPERTY", "net_income": "0", "net_loss": "4120",
         "prior_unallowed": "9880"},
        {"worksheet": "3", "activity": "LARKSPUR RIDGE FUND LP", "net_income": "0", "net_loss": "1875",
         "prior_unallowed": "0"},
        {"worksheet": "3", "activity": "QUENBY TERRACE LP", "net_income": "1878", "net_loss": "0",
         "prior_unallowed": "0"}],
        "unallowed": [{"activity": "RENTAL PROPERTY", "unallowed": "12344"},
                      {"activity": "LARKSPUR RIDGE FUND LP", "unallowed": "1700"},
                      {"activity": "BRINDLEWOOD HOMES LLC", "unallowed": "50"}]}
    _, checks = f8582.rehearse(filed)
    assert [(c.ok, c.quote) for c in checks] == [(True, "RENTAL PROPERTY"), (False, "LARKSPUR RIDGE FUND LP"),
                                                 (True, "QUENBY TERRACE LP"), (False, "BRINDLEWOOD HOMES LLC")]
