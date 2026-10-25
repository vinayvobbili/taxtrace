"""Schedule K-1 faces drawn at the IRS form's own positions, for a made-up partnership. Every value is invented."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest

from taxtrace import cli, k1, text

PARTNERSHIP = "Larkspur Ridge Fund LP"
EIN = "88-1234567"
# (x, top, text): each phrase is drawn in one piece, as the form prints it
FACE = [
    (326, 39, "X"), (336, 40, "Final K-1"), (415, 40, "Amended K-1"),
    (193, 83, "For calendar year 2025, or tax year"),
    (48, 145, "Part I Information About the Partnership"), (319, 49, "Part III Partner's Share of Current Year"),
    (40, 160, "A Partnership's employer identification number"), (146, 169, EIN),
    (40, 184, "B Partnership's name, address, city, state, and ZIP code"), (40, 193, PARTNERSHIP),
    (40, 204, "77 Quarrystone Way, Fernmoor, ZZ 00000"),
    (47, 253, "Part II Information About the Partner"),
    (41, 268, "E Partner's SSN or TIN"), (141, 277, "XXX-XX-4410"),
    (40, 339, "G"), (72, 339, "General partner or LLC"), (181, 338, "X"), (194, 339, "Limited partner or other LLC"),
    (38, 363, "H1"), (59, 362, "X"), (72, 364, "Domestic partner"), (194, 364, "Foreign partner"),
    (40, 400, "I1 What type of entity is this partner?"), (175, 399, "Individual"),
    (40, 412, "I2 If this partner is a retirement plan (IRA/SEP/Keogh/etc.), check here"),
    (41, 424, "J Partner's share of profit, loss, and capital (see instructions):"),
    (110, 434, "Beginning"), (230, 434, "Ending"),
    (57, 448, "Profit"), (130, 445, "4.1200000"), (238, 445, "3.9800000"),
    (57, 460, "Loss"), (130, 457, "4.1200000"), (238, 457, "3.9800000"),
    (57, 472, "Capital"), (130, 469, "4.1200000"), (238, 469, "3.9800000"),
    (38, 508, "K1 Partner's share of liabilities:"), (160, 518, "Beginning"), (251, 518, "Ending"),
    (57, 532, "Nonrecourse"), (190, 529, "1,200"), (280, 529, "1,150"),
    (57, 548, "Qualified nonrecourse"), (57, 556, "financing"), (180, 555, "14,300"), (262, 555, "13,900"),
    (57, 568, "Recourse"),
    (38, 579, "K2 Check this box if item K1 includes liability amounts from lower-tier partnerships"),
    (38, 591, "K3 Check if any of the above liability is subject to guarantees or other"),
    (57, 600, "payment obligations by the partner. See instructions"),
    (41, 616, "L Partner's Capital Account Analysis"),
    (57, 628, "Beginning capital account"), (270, 625, "18,500"),
    (57, 640, "Capital contributed during the year"), (290, 637, "0"),
    (57, 652, "Current year net income (loss)"), (266, 649, "(2,298)"),
    (57, 664, "Other increase (decrease) (attach explanation)"),
    (57, 676, "Withdrawals and distributions"), (280, 673, "900"),
    (57, 688, "Ending capital account"), (270, 685, "15,302"),
    (40, 700, "M Did the partner contribute property with a built-in gain (loss)?"),
    (72, 712, "Yes"), (101, 711, "X"), (115, 712, "No"),
    (40, 724, "N Partner's Share of Net Unrecognized Section 704(c) Gain or (Loss)"),
    (57, 735, "Beginning"), (57, 747, "Ending"),
    # Part III, left column
    (318, 74.5, "1"), (334, 74.5, "Ordinary business income (loss)"), (410, 84.7, "(4,210)"),
    (318, 98.5, "2"), (334, 98.5, "Net rental real estate income (loss)"), (420, 108.7, "1,875"),
    (318, 218.5, "5"), (334, 218.5, "Interest income"), (435, 228.7, "37"),
    (316, 410.5, "9c"), (334, 410.5, "Unrecaptured section 1250 gain"),
    (316, 530.5, "13"), (334, 530.5, "Other deductions"), (316, 540.7, "AE"), (430, 540.7, "112"),
    (316, 603, "22"), (334, 603, "More than one activity for at-risk purposes*"),
    (316, 615, "23"), (334, 615, "More than one activity for passive activity purposes*"),
    # right column
    (453, 74.5, "14"), (471, 74.5, "Self-employment earnings (loss)"),
    (453, 170.5, "16"), (472, 170.5, "Schedule K-3 is attached if"), (472, 180.5, "checked"), (563, 180.3, "4"),
    (453, 350.5, "19"), (471, 350.5, "Distributions"), (452, 362.7, "A"), (550, 362.7, "900"),
    (453, 398.5, "20"), (471, 398.5, "Other information"), (452, 410.7, "A"), (560, 410.7, "37"),
    (452, 422.7, "Z*"), (540, 422.7, "STMT"),
    (453, 506.5, "21"), (471, 506.5, "Foreign taxes paid or accrued"),
    (362, 760, "Cat. No. 11394R"), (452, 760, "Schedule K-1 (Form 1065) 2025"),
]
# statement pages in the two layouts seen: a preparer's (underlined headings, code tables, a 199A grid) and a fund's
SUPPLEMENT = [
    "Schedule K-1 Supplemental Information 2025",
    "Name of Partnership                Partnership EIN",
    f"{PARTNERSHIP}                     {EIN}",
    "            L_i_n_e_ _1_8_ _-_ _O_t_h_e_r_ _I_n_f_o_r_m_a_t_i_o_n_ Statement 101",
    "C_o_d_e_ D_e_s_c_r_i_p_t_i_o_n_                          A_m_o_u_n_t_",
    "C    Meals (general)                                    ______64_",
    "Total                                                   __________64__",
    "         S_e_c_t_i_o_n_ _L_:_ _C_u_r_r_e_n_t_ _Y_e_a_r_ _N_e_t_ _I_n_c_o_m_e_",
    "D_e_s_c_r_i_p_t_i_o_n_                                  A_m_o_u_n_t_",
    "Ordinary business  income (loss)                        (4,210)",
    "Line 13, Code AE -  Portfolio deductions                (112)",
    "         F_o_r_m_ _1_0_6_5_ _S_c_h_e_d_u_l_e_ _K_-_1_ _C_o_d_e_s_",
    "Line 20, Code Z  -  Section 199A information",
    "              [See K-1 instructions, pages 26-27]",
]
STATEMENT_A = [
    "STATEMENT A - QBI Pass-through Entity Reporting",
    "Schedule K-1, Line 20, Code Z",
    "      2025",
    "LINE NUMBER        NO. 1         NO.",
    "Ordinary Business",
    "                   (4,210)",
    "Income (Loss)",
    "Section 179",
    "Other Deductions   1,388",
    "W-2 Wages          2,940",
    "Unadjusted Basis",
    "Immediately After  61,500",
    "Acquisition",
]
FUND_STATEMENT = [
    "LINE 13 - OTHER DEDUCTIONS",
    "AE- DEDUCTIONS-PORTFOLIO INCOME                              $112",
    "LINE 20, CODE Z SECTION 199A INFORMATION",
    "TRADE OR BUSINESS: Real Estate for Development",
    "EIN (IF APPLICABLE): 88-7654321",
    "LINE 20Z SECTION 199A QUALIFIED BUSINESS INCOME              -$4,210",
    "LINE 20Z SECTION 199A W-2 WAGES FROM THE TRADE OR BUSINESS.   $2,940",
    "THE QBI REPORTED ABOVE INCLUDES ITEMS REPORTED ON LINE 1",
    "TRADE OR BUSINESS: Residential Rental Real Estate",
    "LINE 20Z SECTION 199A QUALIFIED BUSINESS INCOME              $35",
    "TAXPAYER HAS ELECTED TO AGGREGATE THE FOLLOWING TRADES OR BUSINESSES",
    "SEC. 1.199A-4",
    "TRADE OR BUSINESS: Real Estate for Development",
    "TOTALS: AGGREGATED GROUP 1",
    "QUALIFIED BUSINESS INCOME                                    -$4,210",
    "W-2 WAGES                                                    $2,940",
    "UBTI INCLUDED ON LINE 1 - QUALIFIED ORG*                     100.00%",
    "Box 19C: PROPERTY DISTRIBUTIONS - OTHER PROPERTY:",
    "FAIR MARKET VALUE OF PROPERTY DISTRIBUTED                    $950",
    "THE PARTNERSHIP'S ADJUSTED BASIS OF PROPERTY DISTRIBUTED     $900",
    "ITEM L, PARTNER'S CAPITAL ACCOUNT ANALYSIS",
    "TAX BASIS",
    "Box 20, CODE AG GROSS RECEIPTS FOR SECTION 448(C)",
    "CURRENT YEAR GROSS PROCEEDS                                  $77",
]
# a third preparer's: each statement titled "SCHEDULE K-1 ..., BOX nn, CODE X", whole dollars printed "1,234."
TITLED_STATEMENT = [
    "SCHEDULE K-1  NONDEDUCTIBLE EXPENSES, BOX 18, CODE C",
    "DESCRIPTION                   PARTNER FILING INSTRUCTIONS        AMOUNT",
    "EXCLUDED MEALS AND            NONDEDUCTIBLE PORTION",
    "ENTERTAINMENT EXPENSES                                             9.",
    "                                                               ---------",
    "TOTAL TO SCHEDULE K-1, BOX 18, CODE C                              9.",
    "                                                               =========",
    "SCHEDULE K-1  BUSINESS INTEREST EXPENSE, BOX 20, CODE N",
    "BUSINESS INTEREST EXPENSE - SEE PARTNERS INSTRUCTIONS",
    "(INCLUDED IN RENTAL REAL ESTATE",
    "INCOME (LOSS))                                                 2,250.",
    "TOTAL TO SCHEDULE K-1, BOX 20, CODE N                          2,250.",
    "SCHEDULE K-1  SECTION 199A INFORMATION, BOX 20, CODE Z",
    "RENT - APARTMENTS",
    "   RENTAL INCOME (LOSS)                                         1,875.",
    "   W-2 WAGES                                                      310.",
    "SCHEDULE K-1  WITHDRAWALS AND DISTRIBUTIONS",
    "CASH DISTRIBUTION                                               48,000.",
]
# a worksheet grid, its amounts a single space after their labels
GRID_STATEMENT = [
    "          Schedule K-1, Box 20, Code Z - Section 199A Information",
    "                        Column A    Column B    Column C",
    "QBI or Qualified PTP items:",
    " Ordinary business income (loss) -12",
    " Net rental real estate income (loss) -4,210",
    " Section 1231 gain (loss)",
    "W-2 wages",
    "Section 199A(g) deduction",
]
SECRETS = ["4,210", "1,875", "18,500", "15,302", "2,298", "14,300", "Larkspur", "Quarrystone", "1234567", "4410"]


def draw(path: Path, pages: list[list]) -> Path:
    """A face is (x, top, phrase) tuples placed on the page; a statement page is lines, in a fixed-width font."""
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=letter)
    for page in pages:
        if page and isinstance(page[0], str):
            c.setFont("Courier", 12)  # 7.2 points a character, the width of a layout text column: gaps survive
            for i, line in enumerate(page):
                c.drawString(20, letter[1] - 40 - 14 * i, line)
        else:
            c.setFont("Helvetica", 7)
            for x, top, phrase in page:
                c.drawString(x, letter[1] - top - 5.2, phrase)  # a 7-point word's top sits 5 points over its baseline
        c.showPage()
    c.save()
    return path


def edited(face: list, **changes: str) -> list:
    """The face with some phrases replaced: {old text: new text}."""
    swap = {old.replace("_", " "): new for old, new in changes.items()}
    return [(x, top, swap.get(phrase, phrase)) for x, top, phrase in face]


@pytest.fixture
def face_pdf(tmp_path: Path) -> Path:
    return draw(tmp_path / "2025 K-1 Larkspur.pdf", [[(40, 40, "Schedule K-1 cover letter")], FACE])


def read(path: Path) -> list[k1.K1]:
    pages = text.pages(path)
    return k1.read(path.name, {n: text.words(path, n) for n, p in enumerate(pages, 1) if k1.is_face(p)}, pages)


def test_every_box_and_code_is_read_by_where_it_sits(face_pdf: Path):
    (found,) = read(face_pdf)
    assert found.page == 2 and found.year == 2025
    assert [(i.box, i.code, i.value.amount, i.statement) for i in found.items] == [
        ("1", "", Decimal(-4210), False), ("2", "", Decimal(1875), False), ("5", "", Decimal(37), False),
        ("13", "AE", Decimal(112), False), ("19", "A", Decimal(900), False), ("20", "A", Decimal(37), False),
        ("20", "Z", None, True),
    ]  # box 9c's "1250" is its label, and "(Form 1065) 2025" is the footer: neither is an amount
    assert found.k3_attached  # box 16's mark, a check mark drawn as ZapfDingbats' "4"
    assert found.more_than_one_activity == {"22": False, "23": False}
    assert found.final and not found.amended
    assert not found.failed
    assert [q.text for q in found.questions] == [
        "a final K-1: was the partnership interest sold or the partnership wound up? Its passive losses carried "
        "over from earlier years may be allowed in full this year.",
        "box 20 code Z: the amount is on the partnership's statement, and no statement page after the face gives it"]
    assert k1.verify(found, text.words(face_pdf, 2)) == []


def test_statement_amounts_in_a_preparers_layout(tmp_path: Path):
    path = draw(tmp_path / "k1.pdf", [FACE, SUPPLEMENT, STATEMENT_A, FACE])
    first, copy = read(path)
    assert [(s.box, s.code, s.description, s.amount, s.page) for s in first.statement] == [
        ("18", "C", "Meals (general)", Decimal(64), 2),  # not the table's total, or the heading's statement number
        ("20", "Z", "Ordinary Business Income (Loss)", Decimal(-4210), 3),  # a label wrapped around its amount
        ("20", "Z", "Other Deductions", Decimal(1388), 3),
        ("20", "Z", "W-2 Wages", Decimal(2940), 3),
        ("20", "Z", "Unadjusted Basis Immediately After Acquisition", Decimal(61500), 3),
    ]  # item L's reconciliation repeats the face's amounts, so its "Line 13, Code AE" row isn't one
    assert first.questions[1:] == []  # box 20 Z is on the statement: only the final K-1 is asked about
    assert copy.statement == [] and copy.copy_of == 1  # the pages after the last face hold no statement
    assert k1.verify(first, text.words(path, 1), text.pages(path)) == []


def test_statement_amounts_in_a_funds_layout(tmp_path: Path):
    (found,) = read(draw(tmp_path / "k1.pdf", [FACE, FUND_STATEMENT]))
    development, rental, group = "Real Estate for Development", "Residential Rental Real Estate", "AGGREGATED GROUP 1"
    assert [(s.box, s.code, s.description, s.amount, s.kind, s.business, s.aggregate)
            for s in found.statement] == [
        ("13", "AE", "DEDUCTIONS-PORTFOLIO INCOME", Decimal(112), "", "", ""),
        # not the EIN, "LINE 1" or a %
        ("20", "Z", "SECTION 199A QUALIFIED BUSINESS INCOME", Decimal(-4210), "qbi", development, ""),
        ("20", "Z", "SECTION 199A W-2 WAGES FROM THE TRADE OR BUSINESS", Decimal(2940), "wages", development, ""),
        ("20", "Z", "SECTION 199A QUALIFIED BUSINESS INCOME", Decimal(35), "qbi", rental, ""),
        # the group's totals repeat its business's amounts: marked, so nothing adds them in twice
        ("20", "Z", "QUALIFIED BUSINESS INCOME", Decimal(-4210), "qbi", "", group),
        ("20", "Z", "W-2 WAGES", Decimal(2940), "wages", "", group),
        ("19", "C", "FAIR MARKET VALUE OF PROPERTY DISTRIBUTED", Decimal(950), "", "", ""),
        ("19", "C", "THE PARTNERSHIP'S ADJUSTED BASIS OF PROPERTY DISTRIBUTED", Decimal(900), "", "", ""),
        ("20", "AG", "CURRENT YEAR GROSS PROCEEDS", Decimal(77), "", "", ""),  # no business: another code's
    ]
    assert found.statement[1].section.startswith("LINE 20Z SECTION 199A QUALIFIED BUSINESS INCOME")
    assert found.statement[4].members == (development,)
    assert [c.what for c in found.checks if "aggregated" in c.what] == [
        "box 20 code Z: an aggregated group's qbi is its businesses' added up",
        "box 20 code Z: an aggregated group's wages is its businesses' added up"]
    assert found.failed == []


def test_statement_amounts_under_titles_that_name_the_box(tmp_path: Path):
    (found,) = read(draw(tmp_path / "k1.pdf", [FACE, TITLED_STATEMENT]))
    assert [(s.box, s.code, s.amount) for s in found.statement] == [
        ("18", "C", Decimal(9)), ("20", "N", Decimal(2250)), ("20", "Z", Decimal(1875)), ("20", "Z", Decimal(310))]
    assert [s.kind for s in found.statement if s.code == "Z"] == ["", "wages"]
    # the totals repeat the items; a distribution under a title naming no box belongs to no box


def test_statement_amounts_a_single_space_after_their_labels(tmp_path: Path):
    (found,) = read(draw(tmp_path / "k1.pdf", [FACE, GRID_STATEMENT]))
    assert [(s.box, s.code, s.description, s.amount) for s in found.statement] == [
        ("20", "Z", "Ordinary business income (loss)", Decimal(-12)),
        ("20", "Z", "Net rental real estate income (loss)", Decimal(-4210))]  # "W-2", "199A(g)": no amounts


def test_an_aggregated_total_that_is_not_its_businesses_fails(tmp_path: Path):
    statement = [line.replace("-$4,210", "-$4,120") if line.startswith("QUALIFIED") else line
                 for line in FUND_STATEMENT]
    (found,) = read(draw(tmp_path / "k1.pdf", [FACE, statement]))
    assert [(c.what, c.quote.split()[:3]) for c in found.failed] == [
        ("box 20 code Z: an aggregated group's qbi is its businesses' added up", ["-4210", "against", "QUALIFIED"])]


def test_parts_one_and_two_are_read_by_their_labels(face_pdf: Path):
    (found,) = read(face_pdf)
    assert (found.ein, found.partnership, found.partner) == (EIN, PARTNERSHIP, "4410")
    assert (found.general_partner, found.domestic, found.entity_type) == (False, True, "Individual")
    assert not found.retirement_plan and not found.lower_tier and not found.guaranteed
    assert found.built_in_gain is False
    assert {k: (v["beginning"].amount, v["ending"].amount) for k, v in found.shares.items()} == {
        "profit": (Decimal("4.12"), Decimal("3.98")), "loss": (Decimal("4.12"), Decimal("3.98")),
        "capital": (Decimal("4.12"), Decimal("3.98"))}
    assert {k: (v["beginning"].amount, v["ending"].amount) for k, v in found.liabilities.items() if v} == {
        "nonrecourse": (Decimal(1200), Decimal(1150)), "qualified_nonrecourse": (Decimal(14300), Decimal(13900))}
    assert {k: v.amount for k, v in found.capital.items()} == {
        "beginning": Decimal(18500), "contributed": Decimal(0), "current_year": Decimal(-2298),
        "withdrawals": Decimal(900), "ending": Decimal(15302)}
    assert found.section_704c == {}


def test_box_numbers_run_into_their_labels_are_split(tmp_path: Path):
    glued = {(453, 74.5, "14"): "14Self-employment earnings (loss)",
             (453, 170.5, "16"): "16Schedule K-3 is attached if"}
    labels = {(471, 74.5, "Self-employment earnings (loss)"), (472, 170.5, "Schedule K-3 is attached if")}
    page = [(x, top, glued.get((x, top, t), t)) for x, top, t in FACE if (x, top, t) not in labels]
    (found,) = read(draw(tmp_path / "k1.pdf", [page]))
    (plain,) = read(draw(tmp_path / "plain.pdf", [FACE]))
    assert [(i.box, i.code, i.value.amount) for i in found.items] == [
        (i.box, i.code, i.value.amount) for i in plain.items]
    assert found.k3_attached and not found.failed


def test_a_partnership_ein_printed_masked_is_still_read(tmp_path: Path):
    (found,) = read(draw(tmp_path / "k1.pdf", [edited(FACE, **{EIN: "XX-XXX4567"})]))
    assert found.ein == "XX-XXX4567"


def test_a_partnership_name_a_blank_line_below_its_label_is_read(tmp_path: Path):
    page = [(x, top + (13 if t in (PARTNERSHIP, "77 Quarrystone Way, Fernmoor, ZZ 00000") else 0), t)
            for x, top, t in FACE]
    (found,) = read(draw(tmp_path / "k1.pdf", [page]))
    assert found.partnership == PARTNERSHIP


def test_a_capital_account_that_does_not_add_up_fails(tmp_path: Path):
    path = draw(tmp_path / "k1.pdf", [edited(FACE, **{"15,302": "15,320"})])
    (found,) = read(path)
    assert [(c.what, c.quote) for c in found.failed] == [
        ("item L: the beginning capital account plus this year's changes is the ending", "15302 against 15,320")]


def test_a_copy_counts_once_and_another_partners_k1_is_its_own(tmp_path: Path):
    spouse = edited(FACE, **{"XXX-XX-4410": "XXX-XX-7302"})
    path = draw(tmp_path / "k1s.pdf", [FACE, FACE, spouse])
    first, copy, other = read(path)
    assert (first.copy_of, copy.copy_of, other.copy_of) == (None, 1, None)
    assert copy.questions == [] and other.partner == "7302"


def test_an_ira_k1_is_marked_and_asks_nothing(tmp_path: Path):
    path = draw(tmp_path / "ira.pdf", [[*edited(FACE, Individual="NOMINEE IRA"), (300, 411, "X")]])
    (found,) = read(path)
    assert found.retirement_plan and found.entity_type == "NOMINEE IRA"
    assert found.questions == []


def test_a_page_that_is_not_a_face_is_skipped(tmp_path: Path):
    words = [{"text": "1", "x0": 318.0, "x1": 322.0, "top": 74.5}]
    assert k1.face("x.pdf", 1, words) is None


def test_cli_writes_the_values_and_prints_none(face_pdf: Path, workspace_home: Path, capsys):
    assert cli.main(["k1", str(face_pdf), "--layout"]) == 0
    out = capsys.readouterr().out
    for secret in SECRETS:
        assert secret not in out
    assert "amounts in 1, 2, 5, 13 AE, 19 A, 20 A, 20 Z (statement); 10 of 10 checks pass, 3 questions" in out
    assert "question: box 16: a Schedule K-3 is attached, and none from this partnership" in out  # none read
    assert "question: box 20 code Z: the amount is on the partnership's statement, and no statement page" in out
    assert "box 1: (#,###) at" in out
    saved = json.loads((workspace_home / "k1" / "2025 K-1 Larkspur.json").read_text())
    assert saved[0]["items"][0] | {"value": None} == {"box": "1", "code": "", "value": None, "statement": False,
                                                      "label": "Ordinary business income (loss)"}
    assert saved[0]["capital"]["ending"]["amount"] == "15302"


def test_cli_failure_names_the_line_and_masks_the_amounts(tmp_path: Path, capsys):
    path = draw(tmp_path / "k1.pdf", [edited(FACE, **{"15,302": "15,320"})])
    assert cli.main(["k1", str(path)]) == 1
    assert ("failed: item L: the beginning capital account plus this year's changes is the ending "
            "(##### against ##,###)") in capsys.readouterr().out


def test_words_by_row_within_a_region(face_pdf: Path, capsys):
    assert cli.main(["words", str(face_pdf), "--page", "2", "--x", "300:", "--top", "70:90", "--rows"]) == 0
    labels, value = capsys.readouterr().out.splitlines()  # the rows of boxes 1 and 14, then box 1's amount
    assert labels.split()[1:3] == ["318:#", "334:Ordinary"] and "453:## 471:Self-employment" in labels
    assert value.split()[1:] == ["410:(#,###)"]


def test_a_name_that_is_not_a_path_is_looked_up_in_the_workspace(workspace_home: Path, capsys):
    draw(workspace_home / "2025" / "k1.pdf", [FACE])
    assert cli.main(["k1", "2025"]) == 0
    assert "k#.pdf p1: 2025 K-1" in capsys.readouterr().out
