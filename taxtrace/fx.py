"""Exchange rates for turning another country's amounts into dollars, each from the source the IRS points to.

- A day's rate (a property bought or sold, a tax withheld): the Federal Reserve's noon buying rate in New York, from
  FRED (series DEXINUS for the rupee, in rupees per dollar). A day with no rate (a weekend, a holiday) takes the
  last business day's before it.
- A year's average (interest and other income that came in through the year): the IRS's yearly average currency
  exchange rates table.
- A year's last day (an account's value on Form 8938 and the FBAR): the Treasury's Reporting Rates of Exchange as of
  December 31.

All three are public: no account, no key, and nothing about the person is sent. Each is fetched once and kept in
<workspace>/fx, and every rate keeps where it came from, so a converted amount can be checked.
"""

from __future__ import annotations

import csv
import io
import json
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

FRED = "https://fred.stlouisfed.org/graph/fredgraph.csv?id={series}"
IRS = "https://www.irs.gov/individuals/international-taxpayers/yearly-average-currency-exchange-rates"
TREASURY = ("https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v1/accounting/od/rates_of_exchange"
            "?fields=record_date,country_currency_desc,exchange_rate&filter=country_currency_desc:eq:{currency},"
            "record_date:eq:{day}")
SERIES = {"INR": "DEXINUS"}  # FRED's daily series, units per dollar
COUNTRY = {"INR": ("India", "Rupee", "India-Rupee")}  # the IRS table's country and currency, the Treasury's name
LOOKBACK = 10  # days: a rate this long before the asked day is still that day's (a long holiday weekend)
CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.IGNORECASE | re.DOTALL)
ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.IGNORECASE | re.DOTALL)
TAG = re.compile(r"<[^>]+>")


class NoRate(LookupError):
    pass


@dataclass
class Rate:
    rate: Decimal  # units of the currency per dollar
    day: str  # the rate's own date or year, which may be before the day asked about
    source: str

    def dollars(self, amount: Decimal) -> Decimal:
        return (amount / self.rate).quantize(Decimal("0.01"))


def _get(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": "taxtrace (exchange rates)"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode("utf-8", errors="replace")


class Rates:
    """Rates for one currency, fetched once into `cache` (a folder) and read from there after."""

    def __init__(self, currency: str, cache: Path, get: Callable[[str], str] | None = None):
        if currency not in SERIES:
            raise NoRate(f"no rate source for {currency}")
        self.currency, self.cache, self._fetch = currency, cache, get
        self._daily: dict[date, Decimal] | None = None

    def get(self, url: str) -> str:
        return (self._fetch or _get)(url)

    def _file(self, name: str) -> Path:
        self.cache.mkdir(parents=True, exist_ok=True)
        return self.cache / name

    def daily(self, day: date) -> Rate:
        """The noon buying rate on `day`, or on the last business day before it."""
        series = SERIES[self.currency]
        path = self._file(f"{series}.csv")
        if self._daily is None:
            if not path.exists() or not _covers(path, day):
                path.write_text(self.get(FRED.format(series=series)))
            self._daily = parse_fred(path.read_text())
        for back in range(LOOKBACK + 1):
            if (rate := self._daily.get(day - timedelta(days=back))) is not None:
                return Rate(rate, str(day - timedelta(days=back)), f"FRED {series}")
        raise NoRate(f"no {series} rate within {LOOKBACK} days before {day}")

    def average(self, start: date, end: date) -> Rate:
        """The mean of the daily rates from `start` to `end`: for an amount known only by its period."""
        self.daily(end)
        found = [r for d, r in self._daily.items() if start <= d <= end]
        if not found:
            raise NoRate(f"no {SERIES[self.currency]} rates from {start} to {end}")
        mean = (sum(found, Decimal(0)) / len(found)).quantize(Decimal("0.0001"))
        return Rate(mean, f"{start} to {end}", f"FRED {SERIES[self.currency]}, mean of {len(found)} days")

    def yearly(self, year: int) -> Rate:
        """The IRS's yearly average rate."""
        path = self._file("irs-yearly.json")
        table = json.loads(path.read_text()) if path.exists() else {}
        key = f"{self.currency} {year}"
        if key not in table:
            country, currency, _ = COUNTRY[self.currency]
            table.update({f"{self.currency} {y}": str(r) for y, r in parse_irs(self.get(IRS), country,
                                                                                currency).items()})
            path.write_text(json.dumps(table, indent=2, sort_keys=True) + "\n")
        if key not in table:
            raise NoRate(f"the IRS table has no {year} rate for {self.currency}")
        return Rate(Decimal(table[key]), str(year), "IRS yearly average currency exchange rates")

    def year_end(self, year: int) -> Rate:
        """The Treasury's reporting rate as of December 31."""
        path = self._file("treasury.json")
        table = json.loads(path.read_text()) if path.exists() else {}
        day, key = f"{year}-12-31", f"{self.currency} {year}-12-31"
        if key not in table:
            rows = json.loads(self.get(TREASURY.format(currency=COUNTRY[self.currency][2], day=day)))["data"]
            if not rows:
                raise NoRate(f"the Treasury has no {day} rate for {self.currency}")
            table[key] = rows[0]["exchange_rate"]
            path.write_text(json.dumps(table, indent=2, sort_keys=True) + "\n")
        return Rate(Decimal(table[key]), day, "Treasury Reporting Rates of Exchange")


def _covers(path: Path, day: date) -> bool:
    """Whether a saved FRED file reaches `day` (it's refetched when asked about a later day)."""
    last = path.read_text().rstrip().rsplit("\n", 1)[-1].split(",", 1)[0]
    try:
        return date.fromisoformat(last) >= day
    except ValueError:
        return False


def parse_fred(body: str) -> dict[date, Decimal]:
    rates = {}
    for row in csv.reader(io.StringIO(body)):
        if len(row) == 2 and re.fullmatch(r"\d{4}-\d{2}-\d{2}", row[0]) and re.fullmatch(r"\d+(\.\d+)?", row[1]):
            rates[date.fromisoformat(row[0])] = Decimal(row[1])
    return rates


def parse_irs(html: str, country: str, currency: str) -> dict[int, Decimal]:
    """The IRS table's rates for one country by year: its header row names the years, newest first."""
    years: list[int] = []
    for row in ROW.findall(html):
        cells = [" ".join(TAG.sub(" ", c).split()) for c in CELL.findall(row)]
        if len(cells) > 2 and all(re.fullmatch(r"\d{4}", c) for c in cells[2:]):
            years = [int(c) for c in cells[2:]]
        elif years and len(cells) > 2 and cells[0] == country and cells[1] == currency:
            return {y: Decimal(c) for y, c in zip(years, cells[2:], strict=False) if re.fullmatch(r"\d+\.\d+", c)}
    return {}
