"""scripts/check_budget_guards.py: no budget file or CSV in git, and a workspace outside the repo. Made-up paths."""

import importlib.util
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("check_budget_guards", ROOT / "scripts" / "check_budget_guards.py")
guards = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guards)


@pytest.mark.parametrize("path", [
    "budget/budget-2027.toml", "TaxData/budget/rules.toml", "budget/statements/2026-11/globex-card.csv",
    "statements/2026-11/export.csv", "actuals/2026-11.json", "ledger.jsonl", "docs/rules.toml", "budget-2027.toml",
    "export.CSV", "docs/umbrella-streaming.csv", "tests/other/globex.csv", "scripts/budget/helper.py",
])
def test_private_files_are_named(path):
    assert guards.private(path)


@pytest.mark.parametrize("path", [
    "taxtrace/budget.py", "docs/budget.md", "tests/test_budget.py", "tests/data/made-up-bank.csv",
    "tests/data/w2-irs-words.json", "taxtrace/static/index.html", "pyproject.toml", "scripts/check",
])
def test_ordinary_files_pass(path):
    assert not guards.private(path)


def git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q")
    (path / "README.md").write_text("made up\n")
    git(path, "add", "README.md")
    return path


def test_a_clean_repo_passes(repo, tmp_path):
    assert guards.problems(repo, {"TAXTRACE_HOME": str(tmp_path / "TaxData")}) == []


def test_a_tracked_budget_file_or_csv_fails_even_when_forced_past_gitignore(repo, tmp_path):
    (repo / "budget").mkdir()
    (repo / "budget" / "budget-2027.toml").write_text("[x]\n")
    (repo / "export.csv").write_text("Date,Description,Amount\n")
    (repo / "tests" / "data").mkdir(parents=True)
    (repo / "tests" / "data" / "made-up.csv").write_text("Date,Description,Amount\n")
    git(repo, "add", "-f", "budget/budget-2027.toml", "export.csv", "tests/data/made-up.csv")
    found = guards.problems(repo, {"TAXTRACE_HOME": str(tmp_path / "TaxData")})
    assert found == ["tracked by git: budget/budget-2027.toml", "tracked by git: export.csv"]


def test_a_workspace_inside_the_repo_fails(repo):
    found = guards.problems(repo, {"TAXTRACE_HOME": str(repo / "TaxData")})
    assert len(found) == 1 and "inside this repo" in found[0]
    assert guards.home_inside(repo, {"TAXTRACE_HOME": str(repo)}) == repo.resolve()


def test_the_default_workspace_is_checked_too(repo, tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: repo)
    assert guards.home_inside(repo, {}) == (repo / "TaxData").resolve()
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert guards.home_inside(repo, {}) is None


def test_main_exits_one_on_a_problem_and_zero_when_clean(repo, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TAXTRACE_HOME", str(tmp_path / "TaxData"))
    assert guards.main(["check_budget_guards.py", str(repo)]) == 0
    assert "ok" in capsys.readouterr().out
    (repo / "ledger.jsonl").write_text("{}\n")
    git(repo, "add", "-f", "ledger.jsonl")
    assert guards.main(["check_budget_guards.py", str(repo)]) == 1
    assert "tracked by git: ledger.jsonl" in capsys.readouterr().out


def test_this_repo_passes():
    assert guards.tracked(ROOT) and [f for f in guards.tracked(ROOT) if guards.private(f)] == []
