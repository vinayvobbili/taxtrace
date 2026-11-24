"""Fail if the household budget's private files could reach the repo.

    python scripts/check_budget_guards.py [ROOT]

Exits 1 when git tracks a budget folder, a ledger, a rules or budget plan file or a CSV (a CSV is allowed in
tests/data/ alone), or when TAXTRACE_HOME (else ~/TaxData) resolves inside the repo. scripts/check runs it before
the tests, which unset TAXTRACE_HOME, so a shell pointed at the repo is caught before anything is audited.
"""

import fnmatch
import os
import subprocess
import sys
from pathlib import Path, PurePosixPath

PRIVATE_FOLDERS = {"budget", "statements", "actuals"}
PRIVATE_FILES = ("ledger.jsonl", "rules.toml", "budget-*.toml")
MADE_UP_CSVS = PurePosixPath("tests/data")


def private(path: str) -> bool:
    """Whether a tracked file (a path from the repo's root) is one the budget keeps out of git."""
    p = PurePosixPath(path)
    if PRIVATE_FOLDERS & set(p.parts[:-1]):
        return True
    if any(fnmatch.fnmatch(p.name, pattern) for pattern in PRIVATE_FILES):
        return True
    return p.suffix.lower() == ".csv" and MADE_UP_CSVS not in p.parents


def tracked(root: Path) -> list[str]:
    out = subprocess.run(["git", "-C", str(root), "ls-files", "-z"], capture_output=True, text=True, check=True)
    return [f for f in out.stdout.split("\0") if f]


def home_inside(root: Path, env: dict[str, str] | None = None) -> Path | None:
    """The workspace folder when it sits inside the repo at `root`, else None."""
    env = os.environ if env is None else env
    home = Path(env.get("TAXTRACE_HOME") or Path.home() / "TaxData").expanduser().resolve()
    return home if home.is_relative_to(root.resolve()) else None


def problems(root: Path, env: dict[str, str] | None = None) -> list[str]:
    found = [f"tracked by git: {f}" for f in tracked(root) if private(f)]
    if (home := home_inside(root, env)) is not None:
        found.append(f"the workspace ({home}) is inside this repo; set TAXTRACE_HOME to a folder outside it")
    return found


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent
    found = problems(root)
    for line in found:
        print(line)
    print(f"budget guards: {len(found)} problems" if found else "budget guards: ok")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
