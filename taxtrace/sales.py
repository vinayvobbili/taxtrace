"""A year's stock sales: Schedule D's totals, the wash sale windows, and how much more loss the year can use.

Schedule D nets the short-term sales against each other and the long-term ones, with last year's capital loss
carryover on its own side and each fund's capital gain distributions (1099-DIV box 2a) on the long-term side. A net
loss comes off other income up to $3,000 ($1,500 married filing separately), and the rest carries to next year,
keeping its character. So while the year's net is above -$3,000, one more dollar of loss saves tax at your full rate;
past it, the loss only carries on.

A loss doesn't count when the same security, or one substantially identical, is bought 30 days before or after the
sale, in any account: a spouse's too, and a dividend reinvested counts as buying. Bought in a taxable account, the
loss moves to the new shares' basis. Bought in an IRA, it's gone for good (Rev. Rul. 2008-5). A broker reports wash
sales only within one account of the same security, so a purchase elsewhere is yours to catch: the trade histories
of all the accounts are read for it, each a CSV as a broker exports one ("Run Date, Account, Action, Symbol,
Quantity, Amount"). Lines above the header are skipped, and what isn't a purchase or a sale is left out.

Before the year's 1099-Bs exist, what the broker's realized gain and loss page says is kept with `--confirm`:
`realized_short=AMOUNT` and `realized_long=AMOUNT` (negative for a net loss), which stand in for the year's sales
until a 1099-B is read; `distributions=AMOUNT` (the capital gain distributions expected); `carry_short=AMOUNT` and
`carry_long=AMOUNT` (last year's capital loss carryover, as positive amounts, when `prior` didn't read it) and
`loss_SYMBOL_YYYY-MM-DD=yes` (a sale at a loss, for its wash sale window).
"""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from .prior import Question

WINDOW = 30  # days before and after a sale at a loss
LOSS_LIMIT = {"separate": Decimal(1500)}  # a year's net capital loss against other income; $3,000 for other filings
LIMIT = Decimal(3000)
CARRY = re.compile(r"(short|long)[- ]term\s+capital\s+loss", re.IGNORECASE)
HEADERS = {"date": ("run date", "trade date", "date", "transaction date"), "account": ("account", "account name"),
           "action": ("action", "description", "transaction", "type"), "symbol": ("symbol", "ticker"),
           "quantity": ("quantity", "shares"), "amount": ("amount", "amount ($)", "net amount")}
BOUGHT = re.compile(r"\b(bought|buy|purchase|reinvest\w*)\b", re.IGNORECASE)
SOLD = re.compile(r"\b(sold|sell|redemption|redeemed)\b", re.IGNORECASE)
RETIREMENT = re.compile(r"\b(ira|roth|rollover|401\(?k\)?)\b", re.IGNORECASE)
LOSS_KEY = re.compile(r"^loss_([a-z][a-z.]{0,5})_(\d{4}-\d{2}-\d{2})$")
AMOUNT_KEYS = ("realized_short", "realized_long", "distributions", "carry_short", "carry_long")


@dataclass
class Trade:
    day: date
    account: str
    kind: str  # "bought" or "sold"
    symbol: str
    reinvested: bool = False

    @property
    def retirement(self) -> bool:
        return bool(RETIREMENT.search(self.account))


@dataclass
class Window:
    symbol: str
    sold: date
    until: date  # the last day a purchase would make it a wash sale
    open: bool  # still running on the day this was worked out
    bought: list[Trade] = field(default_factory=list)  # purchases inside it, in any account

    @property
    def lost_for_good(self) -> bool:
        return any(t.retirement for t in self.bought)


@dataclass
class Totals:
    year: int
    boxes: dict[str, dict[str, Decimal]] = field(default_factory=dict)  # Form 8949's box: proceeds, basis, wash, gain
    short: Decimal = Decimal(0)
    long: Decimal = Decimal(0)
    distributions: Decimal = Decimal(0)
    carry_short: Decimal = Decimal(0)  # last year's loss, positive
    carry_long: Decimal = Decimal(0)
    net: Decimal = Decimal(0)
    allowed: Decimal = Decimal(0)  # what comes off this year's return: the net, or the limit on a net loss
    carries_on: Decimal = Decimal(0)  # the net loss past the limit, to next year
    room: Decimal = Decimal(0)  # how much more net loss this year can use
    from_forms: bool = False  # 1099-Bs were read; otherwise `realized_*` stand in
    windows: list[Window] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)

    def ask(self, text: str) -> None:
        self.questions.append(Question(text, 0, ""))


def confirmation(spec: str) -> tuple[str, str]:
    """'realized_short=-1,700', 'distributions=800', 'loss_ACME_2026-10-20=yes'."""
    key, sep, value = (s.strip().lower() for s in spec.partition("="))
    usage = ValueError("--confirm takes realized_short=AMOUNT, realized_long=AMOUNT, distributions=AMOUNT, "
                       "carry_short=AMOUNT, carry_long=AMOUNT or loss_SYMBOL_YYYY-MM-DD=yes")
    if not sep:
        raise usage
    if m := LOSS_KEY.match(key):
        try:
            date.fromisoformat(m.group(2))
        except ValueError:
            raise usage from None
        if value == "yes":
            return key, value
        raise usage
    if key not in AMOUNT_KEYS:
        raise usage
    try:
        number = Decimal(value.replace(",", "").replace("$", ""))
    except InvalidOperation:
        raise usage from None
    if not number.is_finite() or (key not in ("realized_short", "realized_long") and number < 0):
        raise usage
    return key, str(number)


def read_trades(content: str) -> list[Trade]:
    """A broker's exported trade history: what's bought and sold, from the line that holds its header on. Empty when
    the file isn't one."""
    lines = content.lstrip("﻿").splitlines()
    start = next((i for i, ln in enumerate(lines) if _columns(next(csv.reader([ln]), []))), None)
    if start is None:
        return []
    rows = csv.reader(io.StringIO("\n".join(lines[start:])))
    columns = _columns(next(rows))
    trades = []
    for row in rows:
        cell = {k: row[i].strip() if i < len(row) else "" for k, i in columns.items()}
        day, action = _day(cell.get("date", "")), cell.get("action", "")
        symbol = cell.get("symbol", "").upper()
        if not day or not symbol:
            continue
        kind = "bought" if BOUGHT.search(action) else "sold" if SOLD.search(action) else ""
        if kind:
            trades.append(Trade(day, cell.get("account", ""), kind, symbol, "reinvest" in action.lower()))
    return trades


def _columns(row: list[str]) -> dict[str, int]:
    """The columns of a trade history's header, or {} when the row isn't one: it needs a day, an action, a symbol."""
    names = [c.strip().lower() for c in row]
    found = {key: next(names.index(a) for a in aliases if a in names) for key, aliases in HEADERS.items()
             if any(a in names for a in aliases)}
    return found if {"date", "action", "symbol"} <= found.keys() else {}


def _day(text: str) -> date | None:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y"):
        try:
            return datetime.strptime(text.split(" as of")[0].strip(), fmt).date()
        except ValueError:
            continue
    return None


def windows(losses: list[tuple[str, date]], trades: list[Trade], today: date) -> list[Window]:
    """Each sale at a loss's window, and the purchases of the same symbol inside it, in any account."""
    found = []
    for symbol, sold in sorted(set(losses), key=lambda s: (s[1], s[0])):
        before, after = sold - timedelta(days=WINDOW), sold + timedelta(days=WINDOW)
        bought = [t for t in trades if t.kind == "bought" and t.symbol == symbol and before <= t.day <= after]
        found.append(Window(symbol, sold, after, today <= after, bought))
    return found


def build(year: int, *, forms: list[dict], returns: list[dict], trades: list[Trade] | None = None,
          confirmed: dict | None = None, filing: str = "", today: date | None = None) -> Totals:
    confirmed, trades = confirmed or {}, trades or []
    out = Totals(year)
    sales = [s for f in forms if f.get("form") == "1099-B" and f.get("year") == year for s in f.get("sales", [])]
    out.from_forms = bool(sales)
    for s in sales:
        box = out.boxes.setdefault(s["box"], {k: Decimal(0) for k in ("proceeds", "basis", "wash", "gain")})
        for k in ("proceeds", "basis", "wash", "gain"):
            box[k] += Decimal(s[k] or 0)
        gain = Decimal(s["gain"]) if s["gain"] is not None else Decimal(s["proceeds"])
        if s["term"] == "short":
            out.short += gain
        else:
            out.long += gain
    if sales and any(k in confirmed for k in ("realized_short", "realized_long")):
        out.ask("a 1099-B has been read, so it's used and the realized_short and realized_long you confirmed aren't")
    if not sales:
        out.short = Decimal(confirmed.get("realized_short", 0))
        out.long = Decimal(confirmed.get("realized_long", 0))
        if "realized_short" not in confirmed and "realized_long" not in confirmed:
            out.ask(f"no {year} 1099-B is read yet (`taxtrace 1099`): until it comes, confirm what the broker's "
                    "realized gain and loss page shows (`--confirm realized_short=AMOUNT realized_long=AMOUNT`)")
    read = sum(Decimal(f["amounts"]["2a"]["amount"]) for f in forms if f.get("form") == "1099-DIV"
               and f.get("year") == year and f.get("copy_of") is None and "2a" in f.get("amounts", {}))
    out.distributions = read if read else Decimal(confirmed.get("distributions", 0))
    if not read and "distributions" not in confirmed:
        out.ask("funds pay capital gain distributions in December, and they count against the year's losses: "
                "`--confirm distributions=AMOUNT` once the funds estimate them")
    _carry(out, year, returns, confirmed)
    short, long = out.short - out.carry_short, out.long + out.distributions - out.carry_long
    out.net = short + long
    limit = LOSS_LIMIT.get(filing, LIMIT)
    out.allowed = max(out.net, -limit)
    out.carries_on = out.allowed - out.net
    out.room = max(Decimal(0), out.net + limit)
    losses = [(s["symbol"], date.fromisoformat(s["sold"])) for s in sales if s["symbol"] and s["gain"] is not None
              and Decimal(s["gain"]) < 0]
    for key in confirmed:
        if m := LOSS_KEY.match(key):
            losses.append((m.group(1).upper(), date.fromisoformat(m.group(2))))
    out.windows = windows(losses, trades, today or date.today())
    if out.windows and not trades:
        out.ask("no trade history has been read, so a purchase inside a wash sale window can't be seen: export each "
                "account's history as a CSV, both of yours, IRAs too (`taxtrace sales --year YEAR FILES`)")
    if sales and any(not s["symbol"] for s in sales):
        out.ask("a sale's symbol isn't printed on the 1099-B, so its wash sale window isn't checked: "
                "`--confirm loss_SYMBOL_YYYY-MM-DD=yes`")
    if any(w.bought for w in out.windows):
        out.ask("a similar fund isn't the same symbol, and may still be substantially identical: two index funds on "
                "different indexes aren't, the same fund's other share class is")
    return out


def _carry(out: Totals, year: int, returns: list[dict], confirmed: dict) -> None:
    rows = [i for r in returns if r.get("year") == year - 1 for i in r.get("carryovers", [])]
    for row in rows:
        if (m := CARRY.search(row["label"])) and "amount" in row["amounts"]:
            setattr(out, f"carry_{m.group(1).lower()}", abs(Decimal(row["amounts"]["amount"])))
    for side in ("short", "long"):
        if f"carry_{side}" in confirmed:
            setattr(out, f"carry_{side}", Decimal(confirmed[f"carry_{side}"]))


def to_json(t: Totals) -> dict:
    return {"year": t.year, "from_forms": t.from_forms,
            "boxes": {b: {k: str(v) for k, v in row.items()} for b, row in sorted(t.boxes.items())},
            "short": str(t.short), "long": str(t.long), "distributions": str(t.distributions),
            "carry_short": str(t.carry_short), "carry_long": str(t.carry_long), "net": str(t.net),
            "allowed": str(t.allowed), "carries_on": str(t.carries_on), "room": str(t.room),
            "windows": [{"symbol": w.symbol, "sold": w.sold.isoformat(), "until": w.until.isoformat(), "open": w.open,
                         "lost_for_good": w.lost_for_good,
                         "bought": [{"day": b.day.isoformat(), "account": b.account, "reinvested": b.reinvested}
                                    for b in w.bought]} for w in t.windows],
            "questions": [q.text for q in t.questions]}
