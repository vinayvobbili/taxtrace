"""Made-up documents only. Every person, place and amount here is invented."""

from __future__ import annotations

from pathlib import Path

import pytest

# A CPA-software-style depreciation report and passive-loss worksheet for a fictional taxpayer.
TAXPAYER = "Jordan Q. Quillfeather"
ADDRESS = "4417 Brambleworth Ct, Zentonville, NC 27999"
PRIOR_RETURN = [
    [
        f"{TAXPAYER}                                         ###-##-6021",
        "Form 4562 Depreciation and Amortization Report          2025",
        f"Activity: Rental - {ADDRESS}",
        "Asset  Description        Date in service   Cost/Basis   Land      Method  Life  Prior      Current",
        "1      Residential bldg   06/15/2019        318,400.00   61,250.00 SL      27.5  57,322.00  9,350.91",
        "2      Roof replacement   04/02/2023         14,880.00             SL      27.5     946.09    541.09",
        "Line 22 Total depreciation                                                            9,892.00",
    ],
    [
        "Form 8582 Worksheet 5 - Allocation of Unallowed Losses",
        "Name of activity       Form or schedule   Loss        Ratio     Unallowed loss",
        "Rental - Brambleworth  Schedule E          -6,418.00   1.000000   -23,906.00",
        "Prior year unallowed losses carried forward                       -17,488.00",
        "Prepared by Halvorsen & Pettigrew CPAs, PTIN P04417783",
    ],
]
AMOUNTS = ["318,400.00", "61,250.00", "57,322.00", "9,350.91", "14,880.00", "946.09", "541.09", "9,892.00",
           "6,418.00", "23,906.00", "17,488.00", "6021", "27999", "4417", "04417783"]
NAMES = ["Jordan", "Quillfeather", "Brambleworth", "Zentonville", "Halvorsen", "Pettigrew"]


def make_pdf(path: Path, pages: list[list[str]], password: str | None = None) -> Path:
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.pdfencrypt import StandardEncryption
    from reportlab.pdfgen import canvas

    path.parent.mkdir(parents=True, exist_ok=True)
    encrypt = StandardEncryption(password, canPrint=1) if password else None
    c = canvas.Canvas(str(path), pagesize=landscape(letter), encrypt=encrypt)
    for page in pages:
        c.setFont("Courier", 8)
        for i, line in enumerate(page):
            c.drawString(36, 560 - 14 * i, line)
        c.showPage()
    c.save()
    return path


@pytest.fixture
def prior_return(tmp_path: Path) -> Path:
    return make_pdf(tmp_path / "docs" / f"{TAXPAYER.replace(' ', '_')}_2025_Return.pdf", PRIOR_RETURN)


@pytest.fixture(autouse=True)
def workspace_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Never the real ~/TaxData."""
    home = tmp_path / "TaxData"
    monkeypatch.setenv("TAXTRACE_HOME", str(home))
    return home


@pytest.fixture(autouse=True)
def no_real_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Never the real Keychain approval helper: a test reaching it would ask the person for their Apple Watch."""
    from taxtrace import gate

    helper = tmp_path / "gate" / "keychain-gate"
    monkeypatch.setattr(gate, "helper_path", lambda: helper)
    return helper
