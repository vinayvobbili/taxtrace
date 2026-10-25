"""Schedule E from a made-up filed return, answers, a 1098, a landlord policy and a rolled-forward schedule."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from conftest import make_pdf, printed
from test_f1098 import FORM_1098
from test_k1 import draw
from test_office import docx, para

from taxtrace import answers, cli, policy, prior, schedule_e, text

FILED = [
    [
        "SCHEDULE E               Supplemental Income and Loss            OMB No. 1545-0074",
        "Part I Income or Loss From Rental Real Estate and Royalties",
        "1a Physical address of each property (street, city, state, ZIP code)",
        "A 2208 QUENBY MILL ROAD, LARKSPUR, ZZ 99902",
        "1b Type of Property 2 For each rental real estate property listed Fair Rental Days Personal Use Days QJV",
        "A    1      personal use days. Check the QJV box A 365",
        "3 Rents received. . . . . . . . . . . . . . . . . . . . . . 3 13,200.",
        "5 Advertising. . . . . . . . . . . . . . . . . . . . . . . 5",
        "12 Mortgage interest paid to banks, etc. (see instructions). . . . . . 12 7,415.",
        "16 Taxes. . . . . . . . . . . . . . . . . . . . . . . . . . 16 2,310.",
        "18 Depreciation expense or depletion. . . . . . . . . . . . 18 9,350.",
        "19 Other (list) > See Stmt 1        19       1,265.",
        "20 Total expenses. Add lines 5 through 19. . . . . . . . . . 20 20,340.",
    ],
    [
        "Statement 1",
        "Schedule E, Line 19 - 2208 QUENBY MILL ROAD",
        "Other Rental and Royalty Expenses",
        "Association Dues. . . . . . . . . . . . . . . . . . . $ 1,140.",
        "Miscellaneous. . . . . . . . . . . . . . . . . . . . . . 125.",
        "Total $     1,265.",
    ],
]
POLICY = [
    "Brindlewood Mutual Insurance Company",
    "Landlord's Rental Dwelling Declarations                ST 32",
    "Policy Number: 7700412233",
    "Policy Term: From 03/18/2025 to",
    "New Policy Effective Date: 03/18/2025",
    "03/18/2026, 12:01 A.M. Standard Time",
    "Bill To: Mortgagee",
    "The residence premises covered by this policy is located at:",
    "2208 QUENBY MILL RD     LARKSPUR     ZZ   99902",
    "A - Dwelling          $  310,000        $  842.00",
    "Current Annual Premium: $ 918.40",
]
ANSWERS = (para("Did you pay any estimated taxes in 2025?") + para("No") + para("Rental property:")
           + para("What is the rental income and expenses for 2025?") + para("Rental income = $1,150/month")
           + para("Repairs expenses = $640/year") + para("Cleaning expense = $300/year"))
PROJECTED = {"through": 2025, "projected": True, "assets": [{
    "asset": "1", "description": "Residential bldg", "activity": "Rental - 2208 Quenby Mill Road",
    "basis": "257150", "annual": "9350.91", "method": "SL",
    "from": {"file": "2020 Return.pdf", "year": 2020, "page": 40, "quote": "1 Residential bldg", "accumulated": "0"},
    "years": [{"year": 2024, "depreciation": "9350.91", "accumulated": "0", "last": False},
              {"year": 2025, "depreciation": "9350.91", "accumulated": "0", "last": False}]}]}
SECRETS = ["Quenby", "QUENBY", "2208", "13,200", "13800", "1150", "1,150", "918", "6842", "1486", "9350", "7415",
           "Brindlewood", "7700412233"]


def test_a_filed_schedule_e_is_read_with_its_line_19_statement(tmp_path: Path):
    path = make_pdf(tmp_path / "2024 Return.pdf", FILED)
    found = prior.read(path.name, text.pages(path))
    (rental,) = found.rentals
    assert (rental.address, rental.year, rental.kind, rental.fair_rental_days) == (
        "2208 QUENBY MILL ROAD, LARKSPUR, ZZ 99902", 2024, "1", 365)
    assert {n: line.amount for n, line in rental.lines.items()} == {
        3: Decimal(13200), 12: Decimal(7415), 16: Decimal(2310), 18: Decimal(9350), 19: Decimal(1265)}
    assert [(o.what, o.amount) for o in rental.other] == [("Association Dues", Decimal(1140)),
                                                          ("Miscellaneous", Decimal(125))]
    assert [c.what for c in found.checks] == ["Schedule E: lines 5 to 19 add up to line 20",
                                              "Schedule E: line 19's statement adds up to line 19"]
    assert found.failed == []
    assert schedule_e.load(json.loads(json.dumps(found.to_json()))["rentals"][0]) == rental


def test_answers_and_a_landlord_policy_are_read():
    found = answers.read("q.docx", ["\n".join(["Rental property:", "Rental income = $1,150/month",
                                               "Repairs expenses = $640 per year", "Did you have HOA dues? No"])])
    assert [(a.what, a.yearly, a.per, a.section) for a in found] == [
        ("Rental income", Decimal(13800), "month", "Rental property"),
        ("Repairs expenses", Decimal(640), "year", "Rental property")]
    (p,) = policy.read("farmers.pdf", ["\n".join(POLICY)])
    assert (p.kind, p.number, p.premium, p.starts, p.ends, p.new_since, p.escrow) == (
        "landlord", "7700412233", Decimal("918.40"), "03/18/2025", "03/18/2026", "03/18/2025", True)
    assert p.location == "2208 QUENBY MILL RD LARKSPUR ZZ 99902"
    assert schedule_e.same_place(p.location, "2208 Quenby Mill Road")
    assert not schedule_e.same_place(p.location, "2280 Quenby Mill Road")


def test_cli_puts_the_year_together_and_asks_what_the_documents_cant_say(
        tmp_path: Path, workspace_home: Path, capsys):
    assert cli.main(["prior", str(make_pdf(tmp_path / "2024 Return.pdf", FILED))]) == 0
    assert cli.main(["1098", str(draw(tmp_path / "2025 Mortgage 1098.pdf", [FORM_1098]))]) == 0
    docs = tmp_path / "2025"
    docs.mkdir()
    docx(docs / "2025 Tax Questions.docx", ANSWERS)
    make_pdf(docs / "Brindlewood policies.pdf", [["Policy conditions"], POLICY])
    (workspace_home / "carryforwards" / "projected-2025.json").write_text(json.dumps(PROJECTED))
    capsys.readouterr()
    assert cli.main(["rental", str(docs), "--year", "2025"]) == 0
    out = printed(capsys)
    for secret in SECRETS:
        assert secret not in out
    assert "  line 3 rents received: answers, 2025 Tax Questions.docx p1" in out
    assert "  line 9 insurance: policy, *********** policies.pdf p2" in out
    assert "  line 12 mortgage interest paid to banks, etc.: 1098 box 1, 2025 Mortgage 1098.pdf p1" in out
    assert "  line 16 taxes: 1098 box 10, 2025 Mortgage 1098.pdf p1" in out
    assert "  2024: lines 3, 12, 16, 18, 19; line 19: Association Dues, Miscellaneous" in out
    saved = json.loads((workspace_home / "schedule-e" / "2025.json").read_text())
    assert {n: line["amount"] for n, line in saved["lines"].items()} == {
        "3": "13800", "7": "300", "9": "918.40", "12": "6842.17", "14": "640", "16": "1486.20", "18": "9350.91"}
    assert saved["total_expenses"] == "19537.68" and saved["income_or_loss"] == "-5737.68"
    asked = [q["text"].split(":")[0] for q in saved["questions"]]
    assert asked == ["line 2", "line 3 is 12 months at the monthly rent", "line 9", "line 18 is rolled forward from "
                     "the 2020 depreciation schedule", "line 19, other (Association Dues, Miscellaneous)"]

    # what only the person knows, confirmed once, settles its questions on every later run
    assert cli.main(["rental", str(docs), "--year", "2025", "--confirm", "fair_rental_days=365",
                     "--confirm", "personal_use_days=0", "--confirm", "rent_all_year=yes",
                     "--confirm", "earlier_policy=210.15", "--confirm", "dues=1,140"]) == 0
    capsys.readouterr()
    assert cli.main(["rental", str(docs), "--year", "2025"]) == 0
    out = printed(capsys)
    assert "  line 19 other: confirmed by you" in out and "1,140" not in out and "210" not in out
    saved = json.loads((workspace_home / "schedule-e" / "2025.json").read_text())
    assert (saved["fair_rental_days"], saved["personal_use_days"]) == (365, 0)
    assert (saved["lines"]["9"]["amount"], saved["lines"]["19"]["amount"]) == ("1128.55", "1140")
    assert [q["text"].split(":")[0] for q in saved["questions"]] == [
        "line 18 is rolled forward from the 2020 depreciation schedule"]


def test_a_confirmation_must_be_one_the_schedule_takes():
    assert schedule_e.confirmation("rent-all-year=Yes") == ("rent_all_year", True)
    for bad in ("rent_all_year=maybe", "tenant=Quenby", "dues"):
        try:
            schedule_e.confirmation(bad)
        except ValueError:
            continue
        raise AssertionError(bad)
