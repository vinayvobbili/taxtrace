# Development

## Development

```bash
git config core.hooksPath .githooks   # once: every push first runs scripts/check
scripts/check                         # budget guards, then ruff + pytest on Python 3.13 (CI runs 3.11 and 3.13)
python scripts/build_vocab.py         # rebuild the redaction vocabulary from IRS publications
```

Set `PRE_PUSH_AUDIT` to a command that scans a repository for personal data and exits non-zero on a
finding, and `scripts/check` runs it too, with the repository's path appended.

Every fixture is invented: no real person, place or amount appears in this repository. The workspace's
`budget/` folder is never read as documents, and git and the package builds exclude budget, rules, ledger and
CSV files (a CSV is allowed in `tests/data/` alone); `scripts/check_budget_guards.py` fails when one is tracked
or when `TAXTRACE_HOME` points inside the repository.

The budget's code (`budget.py`, `budget_import.py`, `budget_demo.py`) names no bank, card or aggregator: exports
are read by their column names. Its tests use invented companies only (Initech, Globex, Umbrella, Vandelay and the
like); `tests/test_budget.py` fails when a fixture's payee isn't one of them, and the made-up household in
`budget_demo.py` is what `taxtrace budget init` writes and what the page's Demo data shows. Raw exports are copied
to `$TAXTRACE_BUDGET_PRIVATE` (default `~/Library/Application Support/budget-private` on macOS), which taxtrace
refuses inside the workspace or a git repository; the tests point it at a temporary folder.
