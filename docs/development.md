# Development

## Development

```bash
git config core.hooksPath .githooks   # once: every push first runs scripts/check
scripts/check                         # budget guards, then ruff + pytest on Python 3.10 and 3.13, as CI does
python scripts/build_vocab.py         # rebuild the redaction vocabulary from IRS publications
```

Set `PRE_PUSH_AUDIT` to a command that scans a repository for personal data and exits non-zero on a
finding, and `scripts/check` runs it too, with the repository's path appended.

Every fixture is invented: no real person, place or amount appears in this repository. The workspace's
`budget/` folder is never read as documents, and git and the package builds exclude budget, rules, ledger and
CSV files (a CSV is allowed in `tests/data/` alone); `scripts/check_budget_guards.py` fails when one is tracked
or when `TAXTRACE_HOME` points inside the repository.
