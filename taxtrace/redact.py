"""Mask a tax document's text down to its layout, so it can be shown to someone who mustn't see it.

Every digit becomes `#`, so $12,345.67 reads $##,###.##: the shape of a column stays, the value goes.
Every word that isn't in the vocabulary (words the IRS itself prints in lowercase) becomes `*`s of
the same length, so names, streets, towns, banks and employers go without anyone listing them.
Kept on purpose, because they say what a page is and nothing about whose it is:

- a number right after Form, Schedule, Line, Part, Page or Worksheet (`Form 4562`, `Line 22`), the
  letter-dash forms (`W-2`, `K-1`, `D-400`) and the bare form numbers in FORM_NUMBERS (`1099-INT`);
- a year in a date (`06/15/2019`) or after a word that introduces one (`Tax year 2025`), never a
  bare 1900-2099 that could be a whole-dollar amount.

`terms` are masked first, whatever the vocabulary says: names that are also words (Will, Bill, Grace),
or anything else the person wants gone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from importlib import resources

TOKEN = re.compile(r"(?P<num>\d+)|(?P<word>[A-Za-z]+)")
LABEL_BEFORE = re.compile(r"(?<![A-Za-z])(?:form|schedule|sch|line|ln|part|page|pg|worksheet)\.?\s*$", re.I)
# W-2, K-1, D-400: the letter-dash forms, named without "Form" more often than with it.
LETTER_FORM_BEFORE = re.compile(r"(?<![A-Za-z])[WKD]-$")
FORM_NUMBERS = frozenset({"1040", "1098", "1099", "1116", "4562", "4797", "6251", "8582", "8606", "8938", "8949",
                          "8959", "8960", "8995"})
YEAR = re.compile(r"(?:19|20)\d\d")
# A year is kept only where it can't be an amount: in a date, or after a word that introduces one.
YEAR_BEFORE = re.compile(r"(?:\d[/-]|(?<![A-Za-z])(?:year|yr|for|ending|beginning|calendar|tax)\.?\s*)$", re.I)


@cache
def vocabulary() -> frozenset[str]:
    data = resources.files("taxtrace") / "data"
    words: set[str] = set()
    for name in ("vocab.txt", "vocab_extra.txt"):
        for line in (data / name).read_text().splitlines():
            line = line.strip().lower()
            if line and not line.startswith("#"):
                words.add(line)
    return frozenset(words)


@dataclass
class Redaction:
    text: str
    words_kept: int = 0
    words_masked: int = 0
    numbers_kept: int = 0
    numbers_masked: int = 0

    @property
    def masked_share(self) -> float:
        words = self.words_kept + self.words_masked
        return self.words_masked / words if words else 0.0


def _in_amount(text: str, start: int, end: int) -> bool:
    """True when a run of digits is glued to more digits by a comma or a decimal point, or follows a $."""
    before, after = text[max(0, start - 2):start], text[end:end + 2]
    return bool(re.search(r"[$]$|\d[.,]$", before) or re.match(r"[.,]\d", after))


def mask_terms(text: str, terms: list[str]) -> str:
    """`text` with each of `terms` (whole words, any case) turned into *s, longest first."""
    for term in sorted({t.strip() for t in terms if t.strip()}, key=len, reverse=True):
        pattern = re.compile(r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])", re.I)
        text = pattern.sub(lambda m: re.sub(r"\S", "*", m.group(0)), text)
    return text


def redact(text: str, terms: list[str] | None = None, vocab: frozenset[str] | None = None,
           bare_years: bool = False) -> Redaction:
    """`bare_years` keeps a year standing on its own, for text that holds no amounts: a file name."""
    vocab = vocabulary() if vocab is None else vocab
    text = mask_terms(text, terms or [])
    out = Redaction(text="")

    def swap(m: re.Match) -> str:
        token = m.group(0)
        if m.group("word"):
            if len(token) == 1 or token.lower() in vocab:
                out.words_kept += 1
                return token
            out.words_masked += 1
            return "*" * len(token)
        if _in_amount(text, m.start(), m.end()):
            out.numbers_masked += 1
            return "#" * len(token)
        named = (LABEL_BEFORE.search(text, 0, m.start()) or LETTER_FORM_BEFORE.search(text, 0, m.start())
                 or token in FORM_NUMBERS)
        year = YEAR.fullmatch(token) and (bare_years or YEAR_BEFORE.search(text, 0, m.start()))
        if named or year:
            out.numbers_kept += 1
            return token
        out.numbers_masked += 1
        return "#" * len(token)

    out.text = TOKEN.sub(swap, text)
    return out
