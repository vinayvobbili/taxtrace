"""The repo keeps the budget's private files out twice: .gitignore for git, and excludes for the sdist and wheel.
Checked with made-up paths, against the real .gitignore and pyproject.toml."""

import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PRIVATE = [
    "budget/budget-2027.toml", "TaxData/budget/rules.toml", "budget/statements/2026-11/globex-card.csv",
    "statements/2026-11/export.csv", "actuals/2026-11.json", "ledger.jsonl", "rules.toml", "docs/rules.toml",
    "budget-2027.toml", "sheet-map.toml", "docs/sheet-map.toml", "sheet-exports/tracker.csv", "export.csv",
    "docs/umbrella-streaming.csv", "tests/other/globex.csv", "taxtrace/x/y.csv",
]
KEPT = ["tests/data/made-up-bank.csv", "taxtrace/budget.py", "docs/budget.md", "tests/test_budget.py"]


def ignored(path: str) -> bool:
    """Whether git would ignore `path` (it needn't exist) in this repo."""
    r = subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-q", "--no-index", path])
    return r.returncode == 0


@pytest.mark.parametrize("path", PRIVATE)
def test_gitignore_covers_a_private_budget_file(path):
    assert ignored(path)


@pytest.mark.parametrize("path", KEPT)
def test_gitignore_leaves_the_code_and_made_up_test_data(path):
    assert not ignored(path)


@pytest.fixture(scope="module")
def project(tmp_path_factory) -> Path:
    """A small project with the real pyproject.toml (and no .gitignore, so only its excludes can keep files out),
    holding a package with made-up budget files in it and beside it."""
    root = tmp_path_factory.mktemp("project")
    (root / "pyproject.toml").write_text((ROOT / "pyproject.toml").read_text())
    (root / "README.md").write_text("made up\n")
    (root / "LICENSE").write_text("made up\n")
    files = [*PRIVATE, "taxtrace/__init__.py", "taxtrace/cli.py", "tests/data/made-up-bank.csv"]
    for rel in files:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('__version__ = "0.0.0"\n' if rel.endswith(".py") else "made up\n")
    return root


def test_the_sdist_leaves_out_every_private_budget_file(project, tmp_path):
    builder = pytest.importorskip("hatchling.builders.sdist").SdistBuilder(str(project))
    built = Path(next(builder.build(directory=str(tmp_path), versions=["standard"])))
    with tarfile.open(built) as tar:
        names = [n.split("/", 1)[1] for n in tar.getnames() if "/" in n]
    assert "taxtrace/cli.py" in names and "taxtrace/__init__.py" in names
    assert [n for n in names if n in PRIVATE or n.endswith(".csv")] == []


def test_without_its_excludes_the_build_would_ship_them(project, tmp_path):
    """The control: the same project with the exclude lines removed does ship them, so the two tests around this
    one can fail."""
    bare = tmp_path / "bare"
    bare.mkdir()
    for path in project.rglob("*"):
        if path.is_file():
            target = bare / path.relative_to(project)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(path.read_text())
    pyproject = bare / "pyproject.toml"
    pyproject.write_text("".join(ln for ln in pyproject.read_text().splitlines(keepends=True)
                                 if not ln.startswith("exclude = ")))
    builder = pytest.importorskip("hatchling.builders.wheel").WheelBuilder(str(bare))
    built = Path(next(builder.build(directory=str(tmp_path / "out"), versions=["standard"])))
    with zipfile.ZipFile(built) as wheel:
        assert "taxtrace/x/y.csv" in wheel.namelist()


def test_the_wheel_leaves_out_every_private_budget_file(project, tmp_path):
    builder = pytest.importorskip("hatchling.builders.wheel").WheelBuilder(str(project))
    built = Path(next(builder.build(directory=str(tmp_path), versions=["standard"])))
    with zipfile.ZipFile(built) as wheel:
        names = wheel.namelist()
    assert "taxtrace/cli.py" in names and "taxtrace/__init__.py" in names
    assert [n for n in names if n in PRIVATE or n.endswith(".csv")] == []
