"""The FBAR (FinCEN Form 114) each spouse files: their foreign accounts, item by item, from the year's foreign side.

Each spouse whose accounts together passed $10,000 at any time in the year files their own FBAR, of the accounts
in their name: an account held with the other spouse is on both, one held with anyone else (a parent) is theirs in
full. Per account the form asks the bank's name and mailing address, the account's type and number, and its maximum
value: the highest balance, at the Treasury's December 31 rate, rounded up to the next whole dollar. An account
held alone goes in Part II, one held with anyone else in Part III, with how many own it.

What's read here is `taxtrace foreign`'s saved year, the statements' mode of operation ("SINGLE", "FORMER OR
SURVIVOR") for whether an account is held jointly, and what was confirmed: each bank's name and address
(bank_<the statements' file name's first word>), and whether an account is held jointly where no statement says
(joint_<last four digits>). The account numbers stay out: the person types them in from a statement.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from decimal import ROUND_CEILING, Decimal

from .prior import Question

FILERS = {"self": "fbar", "spouse": "fbar_spouse"}  # whose FBAR, and its key in the foreign side's `reporting`
# a mode of operation that names more than one holder
JOINT = re.compile(r"SURVIVOR|JOINT|ANYONE|EITHER", re.I)


@dataclass
class Item:
    account: str  # the last four digits
    bank: str  # the bank's name, once confirmed
    address: str
    type: str  # FinCEN's type of account: "Bank"
    currency: str
    maximum: int | None  # the highest balance in dollars, rounded up; None until it's known
    joint: bool | None  # held with anyone else: Part III; alone: Part II; None until a statement or confirmation says
    part: str  # "II" or "III", "" while `joint` isn't known
    estimate: bool  # the year isn't covered yet, or its December 31 rate isn't out


@dataclass
class Fbar:
    year: int
    filers: dict[str, list[Item]] = field(default_factory=dict)  # "self", "spouse": their FBAR's accounts
    due: dict[str, bool | None] = field(default_factory=dict)
    questions: list[Question] = field(default_factory=list)

    def to_json(self) -> dict:
        return asdict(self)


def _issuer(files: list[str]) -> str:
    """The first word of a statement's file name ('sbi' of 'sbi-1234-2026-01.pdf'), which names its bank."""
    m = re.match(r"[a-z]+", files[0].lower()) if files else None
    return m.group(0) if m else ""


def build(year: int, found: dict, statements: list[dict], confirmed: dict) -> Fbar:
    """The year's FBAR items from the foreign side `found` (`taxtrace foreign`'s saved year)."""
    fbar = Fbar(year)
    modes = {s.get("account"): s.get("operation", "") for s in sorted(statements, key=lambda s: s.get("end", ""))
             if s.get("operation")}  # each account's latest
    for n, a in enumerate(found.get("accounts", []), 1):
        filers = {"self": ["self"], "spouse": ["spouse"], "joint": ["self", "spouse"]}.get(a.get("holder", ""), [])
        if not filers:
            fbar.questions.append(Question(f"account {n}: whose it is isn't confirmed (`taxtrace foreign --confirm "
                                           "account_<last four>=self|spouse|joint`)", 0, ""))
            continue
        bank = confirmed.get(f"bank_{_issuer(a.get('files', []))}", "")
        if not bank:
            fbar.questions.append(Question(f"account {n}: its bank's name and mailing address (`taxtrace foreign "
                                           "--confirm bank_<the statements' file name's first word>=<name>; "
                                           "<address>`)", 0, ""))
        name, _, address = bank.partition("; ")
        joint = True if a.get("holder") == "joint" else None
        if joint is None and (mode := modes.get(a.get("account"))):
            joint = bool(JOINT.search(mode))
        if joint is None and (said := confirmed.get(f"joint_{a.get('account', '')}")):
            joint = said == "yes"
        if joint is None:
            fbar.questions.append(Question(f"account {n}: is it held with anyone else? No statement says "
                                           "(`taxtrace foreign --confirm joint_<last four>=yes|no`)", 0, ""))
        high = a.get("highest")
        maximum = int(Decimal(high["dollars"]).to_integral_value(ROUND_CEILING)) if high else None
        item = Item(a.get("account", ""), name, address, "Bank", a.get("currency", ""), maximum, joint,
                    {True: "III", False: "II"}.get(joint, ""),
                    bool(a.get("missing")) or bool(found.get("estimated")) or maximum is None)
        for whose in filers:
            fbar.filers.setdefault(whose, []).append(item)
    fbar.due = {whose: found.get("reporting", {}).get(key) for whose, key in FILERS.items() if whose in fbar.filers}
    return fbar


def checklist(fbar: Fbar) -> str:
    """The FBAR items as the BSA e-filing form asks them, one filer after the other: for the person to type in."""
    lines = [f"FBAR (FinCEN Form 114) for {fbar.year}: each filer's own form, at bsaefiling.fincen.gov", ""]
    for whose, items in fbar.filers.items():
        due = {True: "due", False: "not due", None: "not settled yet"}[fbar.due.get(whose)]
        lines.append(f"{'Your' if whose == 'self' else 'Your spouse’s'} FBAR ({due}): {len(items)} account(s)")
        for item in items:
            value = f"${item.maximum:,}" if item.maximum is not None else "?"
            lines += [f"  Part {item.part or '?'}, account ending {item.account}: {item.type}, {item.currency}",
                      f"    maximum value {value}" + (" (an estimate so far)" if item.estimate else ""),
                      f"    bank: {item.bank or '?'}; {item.address or '?'}",
                      "    account number: type it in from a statement"
                      + ("; Part III also asks how many own it and the principal joint owner" if item.joint else "")]
        lines.append("")
    if fbar.questions:
        lines += ["Still to settle:", *(f"  {q.text}" for q in fbar.questions)]
    return "\n".join(lines).rstrip() + "\n"
