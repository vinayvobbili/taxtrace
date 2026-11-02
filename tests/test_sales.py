"""A broker's 1099-B and trade histories, laid out the way brokers print them, for a made-up broker and account. Every
value and name is invented."""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from conftest import printed
from test_k1 import draw, edited

from taxtrace import cli, f1099b, sales, text

HEADER = [
    (49, 295.0, "Activity"), (77, 295.0, "Type"), (127, 295.0, "Quantity"), (160, 295.0, "Sold"),
    (196, 295.0, "Date"), (215, 295.0, "Acquired"), (253, 295.0, "Date"), (272, 295.0, "Sold"), (290, 295.0, "or"),
    (316, 295.0, "Proceeds"), (410, 295.0, "Cost"), (428, 295.0, "or"), (438, 295.0, "Other"),
    (487, 295.0, "Unadjusted"), (556, 295.0, "Accrued"), (605, 295.0, "Wash"), (628, 295.0, "Sale"),
    (666, 295.0, "Federal"), (717, 295.0, "Loss"), (736, 295.0, "Not"),
    (408, 304.2, "Basis"), (490, 304.2, "Gain/Loss"), (558, 304.2, "Market"), (616, 304.2, "Loss"),
    (658, 304.2, "Income"), (689, 304.2, "Tax"), (719, 304.2, "Allowed"),
]
PAGE = [
    (40, 150.0, "Payer's TIN 47-1029384"),
    (40, 228.2, "1099-B Proceeds From Broker and Barter Exchange Transactions - 2026 - Statement for Recipient"),
    (40, 245.0, "Short-Term Transactions for Which Basis is Reported to the IRS; Report on Form 8949, Part I, "
                "with Box A checked."),
    *HEADER,
    (40, 320.0, "GLOBEX CORP Symbol: GBX"),
    (49, 332.0, "Sale"), (127, 332.0, "10.000"), (196, 332.0, "01/05/2026"), (253, 332.0, "10/20/2026"),
    (330, 332.0, "900.00"), (415, 332.0, "1,300.00"), (495, 332.0, "(400.00)"), (565, 332.0, "0.00"),
    (615, 332.0, "0.00"), (670, 332.0, "0.00"), (725, 332.0, "0.00"),
    (40, 350.0, "Long-Term Transactions for Which Basis is Reported to the IRS; Report on Form 8949, Part II, "
                "with Box D checked."),
    *[(x, top + 75, t) for x, top, t in HEADER],
    (40, 395.0, "INITECH FUND (INTFX)"),
    (49, 407.0, "Sale"), (127, 407.0, "20.000"), (196, 407.0, "03/04/2019"), (253, 407.0, "10/20/2026"),
    (330, 407.0, "2,000.00"), (415, 407.0, "1,500.00"), (495, 407.0, "500.00"), (565, 407.0, "0.00"),
    (615, 407.0, "120.00"), (670, 407.0, "0.00"), (725, 407.0, "0.00"),
    (40, 425.0, "UMBRELLA CORP Symbol: UMB"),
    (49, 437.0, "Sale"), (127, 437.0, "5.000"), (196, 437.0, "03/04/2018"), (253, 437.0, "11/03/2026"),
    (330, 437.0, "700.00"), (415, 437.0, "1,700.00"), (495, 437.0, "(1,000.00)"), (565, 437.0, "0.00"),
    (615, 437.0, "0.00"), (670, 437.0, "0.00"), (725, 437.0, "0.00"),
]
NOT_THE_FORM = [(40, 100.0, "Instructions for recipient: report proceeds from broker exchange transactions on "
                            "Form 1099-B")]
TODAY = date(2026, 11, 3)


def read(path: Path) -> f1099b.F1099B | None:
    pages = text.pages(path)
    return f1099b.read(path.name, {n: text.words(path, n) for n, p in enumerate(pages, 1) if f1099b.is_form(p)})


def test_each_sale_is_read_under_its_heading_and_columns(tmp_path: Path):
    form = read(draw(tmp_path / "1099.pdf", [NOT_THE_FORM, PAGE]))
    assert form.year == 2026 and form.payer_tin == "47-1029384" and form.failed == []
    short, fund, stock = form.sales
    assert (short.term, short.box, short.symbol) == ("short", "A", "GBX")
    assert (short.proceeds, short.basis, short.gain) == (900, 1300, -400)
    assert short.sold == date(2026, 10, 20) and short.acquired == date(2026, 1, 5)
    assert (fund.term, fund.box, fund.symbol) == ("long", "D", "INTFX")
    assert (fund.wash, fund.gain) == (120, 620)  # the disallowed loss adds back to what the printed 500 was
    assert (stock.symbol, stock.gain) == ("UMB", -1000)
    assert any("wash sale" in q.text for q in form.questions)


def test_a_printed_gain_that_doesnt_add_up_fails(tmp_path: Path):
    form = read(draw(tmp_path / "1099.pdf", [edited(PAGE, **{"(400.00)": "(900.00)"})]))
    assert [c.what for c in form.failed] == ["each sale's printed gain or loss is its proceeds less its basis"]


def test_a_statement_without_sales_has_no_form(tmp_path: Path):
    assert read(draw(tmp_path / "1099.pdf", [NOT_THE_FORM])) is None


HISTORY = """Brokerage

Run Date,Account,Action,Symbol,Description,Quantity,Amount ($)
10/20/2026,Joint Taxable,YOU SOLD GLOBEX CORP,GBX,GLOBEX CORP,-10,900
11/10/2026,Rollover IRA,YOU BOUGHT GLOBEX CORP,GBX,GLOBEX CORP,4,400
10/10/2026,Joint Taxable,REINVESTMENT UMBRELLA CORP,UMB,UMBRELLA CORP,1,100
09/01/2026,Joint Taxable,YOU BOUGHT UMBRELLA CORP,UMB,UMBRELLA CORP,1,100
10/30/2026,Joint Taxable,DIVIDEND RECEIVED,INTFX,INITECH FUND,,50
,,Footnote text,,,,
"""


def test_a_trade_history_keeps_purchases_and_sales_from_its_header_on():
    trades = sales.read_trades(HISTORY)
    assert [(t.kind, t.symbol) for t in trades] == [("sold", "GBX"), ("bought", "GBX"), ("bought", "UMB"),
                                                    ("bought", "UMB")]
    assert trades[1].retirement and not trades[0].retirement and trades[2].reinvested
    assert sales.read_trades("Date,Amount\n01/01/2026,5\n") == []


def test_a_purchase_in_an_ira_inside_the_window_loses_the_loss_for_good():
    found = sales.windows([("GBX", date(2026, 10, 20)), ("UMB", date(2026, 11, 3))], sales.read_trades(HISTORY), TODAY)
    gbx, umb = found
    assert gbx.until == date(2026, 11, 19) and gbx.open and gbx.lost_for_good and len(gbx.bought) == 1
    # 10/10 is inside 30 days before the sale, and a dividend reinvested counts; 9/01 is outside
    assert [t.day for t in umb.bought] == [date(2026, 10, 10)] and not umb.lost_for_good
    closed = sales.windows([("GBX", date(2026, 1, 2))], [], TODAY)[0]
    assert not closed.open and not closed.bought


@pytest.fixture
def forms(tmp_path: Path) -> list[dict]:
    return [read(draw(tmp_path / "1099.pdf", [PAGE])).to_json()]


def test_schedule_d_nets_both_sides_with_the_carryover_and_distributions(forms: list[dict]):
    last = {"year": 2025, "carryovers": [{"label": "Long-term capital loss", "amounts": {"amount": "-200"}}]}
    dist = {"form": "1099-DIV", "year": 2026, "amounts": {"2a": {"amount": "150"}}}
    t = sales.build(2026, forms=[*forms, dist], returns=[last], today=TODAY)
    assert (t.short, t.long, t.distributions, t.carry_long) == (-400, -380, 150, 200)
    assert t.boxes["A"]["gain"] == -400 and t.boxes["D"]["wash"] == 120
    assert t.net == -400 + (-380 + 150 - 200) and t.allowed == t.net and t.carries_on == 0
    assert t.room == 3000 + t.net


def test_a_net_loss_past_the_limit_carries_on_and_leaves_no_room():
    t = sales.build(2026, forms=[], returns=[], today=TODAY,
                    confirmed={"realized_short": "-5000", "distributions": "0"})
    assert (t.net, t.allowed, t.carries_on, t.room) == (-5000, -3000, 2000, 0)
    separate = sales.build(2026, forms=[], returns=[], filing="separate", confirmed={"realized_long": "-5000"})
    assert separate.allowed == -1500


def test_until_the_1099b_comes_the_realized_amounts_stand_in(forms: list[dict]):
    t = sales.build(2026, forms=[], returns=[], today=TODAY,
                    confirmed={"realized_short": "-1000", "realized_long": "200"})
    assert not t.from_forms and t.net == -800 and t.room == 2200
    asked = sales.build(2026, forms=[], returns=[], today=TODAY)
    assert any("no 2026 1099-B" in q.text for q in asked.questions)
    both = sales.build(2026, forms=forms, returns=[], today=TODAY, confirmed={"realized_short": "-1"})
    assert both.from_forms and both.short == -400 and any("aren't" in q.text for q in both.questions)


def test_confirmed_losses_get_their_windows():
    t = sales.build(2026, forms=[], returns=[], today=TODAY, confirmed={"loss_gbx_2026-10-20": "yes"},
                    trades=sales.read_trades(HISTORY))
    assert [(w.symbol, w.until) for w in t.windows] == [("GBX", date(2026, 11, 19))] and t.windows[0].lost_for_good


@pytest.mark.parametrize("spec", ["realized_short=lots", "distributions=-5", "loss_gbx_2026-13-45=yes",
                                  "loss_gbx_2026-10-20=no", "unknown=1", "nothing"])
def test_a_confirmation_that_isnt_one_is_refused(spec: str):
    with pytest.raises(ValueError, match="--confirm takes"):
        sales.confirmation(spec)


def test_a_loss_can_be_confirmed_negative():
    assert sales.confirmation("realized_short=-1,700") == ("realized_short", "-1700")
    assert Decimal(sales.confirmation("carry_long=800")[1]) == 800


def test_cli_reads_the_1099b_and_prints_no_amounts_or_symbols(tmp_path: Path, workspace_home: Path, capsys):
    path = draw(tmp_path / "1099 Marlowe.pdf", [PAGE])
    assert cli.main(["1099", str(path)]) == 0
    out = printed(capsys)
    assert "Form 1099-B: 3 sales, 1 short-term and 2 long-term" in out and "Boxes A, D" in out
    history = tmp_path / "history.csv"
    history.write_text(HISTORY)
    assert cli.main(["sales", "--year", "2026", str(history), "--confirm", "loss_gbx_2026-10-20=yes"]) == 0
    out = printed(capsys)
    for secret in ("1,300", "2,000", "GBX", "INTFX", "UMB", "Globex", "1029384"):
        assert secret not in out
    assert "window runs to Nov 19, 2026" in out and "bought inside it in a retirement account" in out
    saved = json.loads((workspace_home / "sales" / "2026.json").read_text())
    assert saved["from_forms"] and Decimal(saved["short"]) == -400
    assert cli.main(["sales", "--year", "2026", "--confirm", "nothing"]) == 2
