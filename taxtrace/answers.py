"""Answers to a tax preparer's questions: "Rental income = $1,200/month", typed into the preparer's own document.

A preparer sends questions each year (an organizer, or a Word document of them) and the answers come back typed
under them. An answer that's an amount is a line of its own: what it is, "=" or ":", the amount, and how often
("/month", "per year"). Each is kept with the heading it's under ("Rental property:"), its page and its line exactly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal

from .prior import amount

ANSWER = re.compile(r"^\s*(?P<what>[A-Za-z][A-Za-z0-9 &/'’()-]*?)\s*[=:]\s*\$\s?(?P<amount>\d[\d,]*(?:\.\d{1,2})?)"
                    r"\s*(?:(?:/|per\s+|a\s+)(?P<per>month|mo|year|yr|annum)\b)?", re.IGNORECASE)
HEADING = re.compile(r"^\s*(?P<heading>[A-Za-z][^=?$]{2,60}):\s*$")
PER = {"mo": "month", "yr": "year", "annum": "year"}


@dataclass
class Answer:
    what: str  # "Rental income"
    amount: Decimal
    per: str  # "month", "year", or "" when the answer doesn't say
    section: str  # the heading it's under, "Rental property"
    file: str
    page: int
    quote: str  # its line, exactly as `text.pages` gives it

    @property
    def yearly(self) -> Decimal:
        return self.amount * 12 if self.per == "month" else self.amount


def read(name: str, pages: list[str]) -> list[Answer]:
    """Every answer that's an amount, in order."""
    found = []
    for n, page in enumerate(pages, 1):
        section = ""
        for line in page.splitlines():
            if m := ANSWER.match(line):
                per = (m.group("per") or "").lower()
                found.append(Answer(m.group("what").strip(), amount(m.group("amount")), PER.get(per, per), section,
                                    name, n, line))
            elif m := HEADING.match(line):
                section = m.group("heading").strip()
    return found
