"""An insurance policy's declarations page: what it covers, where, for which term, and its premium.

An insurer's package holds the policy forms (tens of pages of conditions) and, near the front, a declarations page
for each policy: its kind ("Landlord's Rental Dwelling", "Homeowners", "Automobile"), its number and term, the
property it covers, who's billed (a mortgagee pays it from escrow) and the annual premium. Only the declarations
are read, from the page's layout text: a landlord policy's premium is a rental's insurance on Schedule E line 9.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from decimal import Decimal

from .prior import amount

PREMIUM = re.compile(r"(?:Current|Total) Annual Premium:\s*\$?\s*(\d[\d,]*\.\d{2})")
KINDS = (("landlord", re.compile(r"Landlord'?s Rental|Rental Dwelling|Landlord Policy", re.IGNORECASE)),
         ("homeowners", re.compile(r"Homeowners Insurance|Homeowners Policy", re.IGNORECASE)),
         ("auto", re.compile(r"Automobile Insurance|Auto Policy Declarations", re.IGNORECASE)))
DAY = r"\d{2}/\d{2}/\d{4}"
STARTS = re.compile(rf"(?:Policy Term:\s*From|Policy Effective Date:)\s*({DAY})")
ENDS = re.compile(rf"Policy Expiration Date:\s*({DAY})|^\s*({DAY}),\s*\d{{1,2}}:\d\d|\bto\s+({DAY})", re.MULTILINE)
NEW = re.compile(rf"New Policy Effective Date:\s*({DAY})")
NUMBER = re.compile(r"Policy Number:\s*(\S+)")
LOCATED = re.compile(r"(?:is located at|Insured Location|Location of Residence Premises):?\s*$", re.IGNORECASE)
ESCROW = re.compile(r"Bill To:\s*(?:First\s+)?Mortgagee", re.IGNORECASE)


@dataclass
class Policy:
    file: str
    page: int
    kind: str  # "landlord", "homeowners", "auto", or "" when the page doesn't say
    number: str
    premium: Decimal
    quote: str  # the premium's line, exactly as `text.pages` gives it
    starts: str = ""  # the term, as printed
    ends: str = ""
    new_since: str = ""  # "New Policy Effective Date": the first term of a new policy
    location: str = ""  # the property it covers, spaces closed up
    escrow: bool = False  # billed to the mortgagee, who pays it from the borrower's escrow
    insurer: str = ""

    def to_json(self) -> dict:
        return {k: str(v) if isinstance(v, Decimal) else v for k, v in asdict(self).items()}


def is_declarations(page_text: str) -> bool:
    return bool(PREMIUM.search(page_text))


def read(name: str, pages: list[str]) -> list[Policy]:
    """Each policy's declarations among a document's pages; a page repeating one already read counts once."""
    found: list[Policy] = []
    for n, page in enumerate(pages, 1):
        if not (m := PREMIUM.search(page)):
            continue
        line = next(ln for ln in page.splitlines() if m.group(0) in ln)
        policy = Policy(name, n, next((k for k, pattern in KINDS if pattern.search(page)), ""),
                        (num.group(1) if (num := NUMBER.search(page)) else ""), amount(m.group(1)), line)
        if start := STARTS.search(page):
            policy.starts = start.group(1)
            if end := ENDS.search(page, start.end()):
                policy.ends = next(g for g in end.groups() if g)
        if new := NEW.search(page):
            policy.new_since = new.group(1)
        lines = page.splitlines()
        if (at := next((i for i, ln in enumerate(lines) if LOCATED.search(ln)), None)) is not None:
            policy.location = next((" ".join(ln.split()) for ln in lines[at + 1:at + 3] if ln.strip()), "")
        policy.escrow = bool(ESCROW.search(page)) or ("Mortgagee" in page and "Bill To" in page)
        policy.insurer = next((" ".join(ln.split()) for ln in lines if "Insurance Company" in ln), "")
        if not any((p.number, p.premium, p.kind) == (policy.number, policy.premium, policy.kind) for p in found):
            found.append(policy)
    return found
