"""The made-up household the videos run on: an invented Initech employee in Boulder, CO, with round figures.

    python scripts/videos/demo.py [FOLDER]      # build the workspace in FOLDER (default: a temporary one)

`build` draws the documents a tax preparer's export would hold (a W-2 and a 1098 with real print positions, so the
real readers read them), imports them with the real `taxtrace import`, reads them with `taxtrace w2` and `1098`, saves
the other forms as the readers would have, and writes `moves` and `entry` with the real commands. Nothing reads
~/TaxData: TAXTRACE_HOME is set to the folder for as long as the build runs. Every name, town and amount is invented.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

YEAR = 2026
TAXPAYER = "Pat Rivera"
EMPLOYER = "Initech Payroll Services"

# (x, top, text) at the print positions the readers look for: a label, and its value just below it.
W2_FACE = [
    (157, 38.5, "a Employee’s social security number"), (170, 49.0, "XXX-XX-4410"),
    (42, 62.5, "b Employer identification number (EIN)"), (50, 74.0, "88-7654321"),
    (339, 62.5, "1"), (348, 62.5, "Wages, tips, other compensation"), (345, 74.0, "120,000.00"),
    (461, 62.5, "2"), (471, 62.5, "Federal income tax withheld"), (470, 74.0, "20,000.00"),
    (42, 86.5, "c Employer’s name, address, and ZIP code"), (50, 98.0, EMPLOYER), (50, 108.0, "1000 Pearl Street"),
    (339, 86.5, "3"), (348, 86.5, "Social security wages"), (345, 98.0, "120,000.00"),
    (461, 86.5, "4"), (471, 86.5, "Social security tax withheld"), (470, 98.0, "7,440.00"),
    (339, 110.5, "5"), (348, 110.5, "Medicare wages and tips"), (345, 122.0, "120,000.00"),
    (461, 110.5, "6"), (471, 110.5, "Medicare tax withheld"), (470, 122.0, "1,740.00"),
    (339, 134.5, "7"), (348, 134.5, "Social security tips"), (461, 134.5, "8"), (471, 134.5, "Allocated tips"),
    (335, 170.5, "11"), (349, 170.5, "Nonqualified plans"),
    (461, 158.5, "10"), (471, 158.5, "Dependent care benefits"),
    (458, 182.5, "12a"), (471, 182.5, "See instructions for box 12"), (458, 190.0, "C"), (458, 197.0, "o"),
    (458, 206.5, "12b"), (458, 214.0, "C"), (458, 230.5, "12c"), (458, 238.0, "Co"), (458, 254.5, "12d"),
    (458, 262.0, "C"),
    (42, 182.5, "e Employee’s first name and initial"), (50, 196.0, TAXPAYER),
    (38, 290.5, "15 State Employer’s state ID number"), (40, 303.0, "CO"), (70, 303.0, "12-3456"),
    (197, 290.5, "16"), (209, 290.5, "State wages, tips, etc."), (205, 303.0, "120,000.00"),
    (284, 290.5, "17"), (296, 290.5, "State income tax"), (295, 303.0, "4,800.00"),
    (363, 290.5, "18"), (375, 290.5, "Local wages, tips, etc."),
    (449, 290.5, "19"), (461, 290.5, "Local income tax"),
    (58, 340.7, "W-2"), (289, 340.7, str(YEAR)), (106, 346.3, "Wage and Tax Statement"),
]
F1098_FACE = [
    (365, 251.6, "CORRECTED (if checked)"),
    (22, 264.8, "RECIPIENT’S/LENDER’S name, street address, city or town"),
    (22, 270.8, "foreign postal code, and telephone no."),
    (35, 282.5, "Globex Bank"), (35, 288.8, "PO Box 100"), (35, 298.3, "Boulder, CO 80301-0000"),
    (456, 274.5, "Form 1098"), (500, 286.5, "Mortgage Interest Statement"),
    (440, 303.0, "For calendar year"), (454, 310.3, str(YEAR)),
    (324, 321.6, "1"), (333, 321.6, "M ortgage interest received from payer(s)/borrower(s)*"), (567, 321.6, "Copy B"),
    (323, 329.2, "$"), (388, 329.2, "9,000.00"), (561, 329.2, "For Payer/"),
    (22, 334.6, "PAYER’S/BORROWER’S name, street address (including apt. no.)"),
    (324, 340.3, "2"), (333, 338.0, "Outstanding mortgage principal"),
    (444, 340.3, "3"), (453, 338.0, "Mortgage origination date"), (564, 338.0, "Borrower"),
    (323, 345.8, "$"), (351, 345.8, "250,000.00"), (456, 347.9, "06/14/2020"), (552, 351.8, "1 and 10 is important"),
    (324, 357.8, "4"), (333, 357.8, "Refund of overpaid interest"),
    (444, 357.8, "5"), (453, 357.8, "Mortgage insurance premiums"),
    (323, 365.9, "$"), (441, 365.9, "$"),
    (323, 375.8, "6"), (332, 375.8, "Points paid on purchase"), (331, 381.8, "of principal residence"),
    (424, 375.8, "7"), (433, 375.8, "If address of property securing"),
    (433, 381.8, "mortgage is the same as PAYER’S/BORROWER’S"), (433, 389.7, "address, the box is checked"),
    (74, 386.6, TAXPAYER), (323, 393.8, "$"),
    (323, 405.8, "8"), (332, 405.8, "Address or description of property securing mortgage"),
    (340, 417.8, "12 Birch Road"), (340, 423.8, "Boulder"), (388, 423.8, "CO 80302"),
    (323, 434.5, "9"), (332, 434.5, "Number of properties securing"),
    (436, 434.5, "10"), (449, 434.5, "Other"),
    (322, 452.1, "11"), (335, 452.1, "Mortgage acquisition date"),
    (436, 452.1, "Account number (see instructions)"), (463, 459.5, "000123456"),
    (323, 470.8, "RECIPIENT’S/LENDER’S TIN"), (454, 470.8, "PAYER’S/BORROWER’S TIN"),
    (343, 477.5, "77-7654321"), (461, 477.5, "XXX-XX-4410"),
    (19, 490.7, "Form 1098 (Rev. 1-2025) (Keep for your records) www.irs.gov/Form1098"),
    (314, 516.7, "Box 2. Shows the outstanding principal on the mortgage as of January 1"),
    (23, 645.4, "Account number. May show an account or other unique number"),
    (23, 662.4, "Box 1. Shows the mortgage interest received by the recipient/lender"),
]
# A broker's statement and a filed return, as plain pages: the importer files them, the videos list them by name.
BROKER_PAGE = [f"Umbrella Brokerage    Consolidated Form 1099    {YEAR}",
               "Form 1099-DIV    Dividends and Distributions", "1a Total ordinary dividends   1,500.00"]
RETURN_PAGE = [f"Form 1040    U.S. Individual Income Tax Return    {YEAR - 1}", "Pat Rivera    Boulder, CO"]
# What `taxtrace 1099` and the pay-stub reader would have saved (the entry sheet reads these).
PAYSTUB = {"form": "paystub", "file": "2026 Initech paystub.pdf", "year": YEAR, "paid": f"{YEAR}-10-30",
           "period_start": f"{YEAR}-10-16", "period_end": f"{YEAR}-10-31",
           "withheld": {"federal": {"current": "800.00", "year_to_date": "16000.00", "label": "FIT Withheld"},
                        "state": {"current": "190.00", "year_to_date": "3800.00", "label": "SIT Withheld (CO)"}},
           "deferred": {"pretax": {"current": "900.00", "year_to_date": "18000.00", "label": "401k"}},
           "salary": {"current": "5000.00", "year_to_date": "100000.00", "label": "Salary"},
           "taxable_wages": {"current": "4000.00", "year_to_date": "96000.00", "label": "Taxable"}}
DIVIDENDS = {"form": "1099-DIV", "file": "2026 Umbrella Brokerage 1099.pdf", "page": 3, "year": YEAR,
             "payer_tin": "12-3456789", "account": "U100",
             "amounts": {"1a": {"amount": "1500.00", "label": "Ordinary dividends", "page": 3}}}

TODO = """\
## Taxes
- [ ] **{soon}** Pay the fourth estimated payment (Q4)
- [ ] **{later}** Ask Initech payroll to confirm box 12 on the W-2
- [ ] **{week}** Gather the receipts for this year's charity gifts
## Money
- [ ] **{today}** Move the year-end cash into the savings account
- [ ] Check the 401(k) contribution against the limit
"""


def draw(path: Path, pages: list[list]) -> Path:
    """A PDF: each page is (x, top, text) tuples placed on it, or lines of plain text in a fixed-width font."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=letter)
    for page in pages:
        if page and isinstance(page[0], str):
            c.setFont("Courier", 12)
            for i, line in enumerate(page):
                c.drawString(20, letter[1] - 40 - 14 * i, line)
        else:
            c.setFont("Helvetica", 7)
            for x, top, phrase in page:
                c.drawString(x, letter[1] - top - 5.2, phrase)
        c.showPage()
    c.save()
    return path


def export_folders(parent: Path) -> list[Path]:
    """What a preparer's portal hands back: a folder per year, with an identity document that is skipped. This year's
    holds last year's signed return as well, which goes to prior-returns."""
    now, before = parent / f"{YEAR} TAX", parent / f"{YEAR - 1} TAX"
    draw(now / f"{YEAR} W-2 Initech.pdf", [W2_FACE])
    draw(now / f"{YEAR} 1098 Globex Bank.pdf", [F1098_FACE])
    draw(now / f"{YEAR} Umbrella Brokerage 1099.pdf", [["Cover letter"], ["Account summary"], BROKER_PAGE])
    draw(now / f"{YEAR - 1} Tax Return Rivera signed.pdf", [RETURN_PAGE])
    draw(now / "Driver License.pdf", [["Driver license front"]])
    draw(before / f"{YEAR - 1} Umbrella Brokerage 1099.pdf", [["Cover letter"], ["Account summary"], BROKER_PAGE])
    draw(before / f"{YEAR - 1} Initech paystub.pdf", [[f"Initech Payroll Services    Earnings statement {YEAR - 1}"]])
    return [now, before]


def write_todo(home: Path, today: date) -> None:
    days = {k: today + timedelta(days=n) for k, n in (("today", 0), ("soon", 2), ("week", 5), ("later", 24))}
    fmt = {k: f"{d:%a} {d.month}/{d.day}" for k, d in days.items()}
    (home / "todo.md").write_text(TODO.format(**fmt), encoding="utf-8")


def save(home: Path, folder: str, name: str, value: object) -> None:
    (home / folder).mkdir(parents=True, exist_ok=True)
    (home / folder / name).write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


@dataclass
class Run:
    """What the real commands printed while the household was built, by command."""

    home: Path
    exports: list[Path]
    said: dict[str, str] = field(default_factory=dict)


@contextlib.contextmanager
def workspace_at(home: Path) -> Iterator[None]:
    """TAXTRACE_HOME is `home` for the block, whatever it was (or wasn't) before."""
    before = os.environ.get("TAXTRACE_HOME")
    os.environ["TAXTRACE_HOME"] = str(home)
    try:
        yield
    finally:
        if before is None:
            os.environ.pop("TAXTRACE_HOME", None)
        else:
            os.environ["TAXTRACE_HOME"] = before


def command(run: Run, *argv: str, key: str = "") -> str:
    """Run `taxtrace ARGV` in this process against the demo workspace; what it printed is kept under `key`, else the
    command's first word (`import`, `w2`, `moves`...)."""
    from taxtrace import cli

    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        code = cli.main(list(argv))
    run.said[key or argv[0]] = out.getvalue()
    if code not in (0, 1):  # 1 is a check that failed, which the output says
        raise RuntimeError(f"taxtrace {' '.join(argv)} exited {code}:\n{out.getvalue()}")
    return out.getvalue()


def build(home: Path, scratch: Path, today: date | None = None) -> Run:
    """The household's workspace in `home` (made if need be), with the preparer's export in `scratch`.

    Call it inside workspace_at(home): the commands read TAXTRACE_HOME."""
    today = today or date.today()
    home.mkdir(parents=True, exist_ok=True)
    run = Run(home, export_folders(scratch))
    sources = [str(p) for p in run.exports]
    command(run, "import", *sources)
    command(run, "import", *sources, key="import again")
    command(run, "outline", str(home / str(YEAR)))
    command(run, "redact", str(home / str(YEAR)))
    command(run, "w2")
    command(run, "1098")
    save(home, "forms", "paystub.json", PAYSTUB)
    save(home, "forms", "2026 Umbrella Brokerage 1099.json", [DIVIDENDS])
    write_todo(home, today)
    command(run, "moves", "--year", str(YEAR))
    command(run, "entry", "--year", str(YEAR))
    return run


def main(argv: list[str] | None = None) -> None:
    folder = Path(argv[0]).expanduser().resolve() if argv else None
    with tempfile.TemporaryDirectory(prefix="taxtrace-demo-") as tmp:
        home = folder or Path(tmp) / "TaxData"
        with workspace_at(home):
            run = build(home, Path(tmp) / "export")
        for name, said in run.said.items():
            print(f"$ taxtrace {name}\n{said}")  # the home folder's name in them is a temporary one
        print(f"workspace: {home}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1:])
