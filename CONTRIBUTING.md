# Contributing

This is a local review candidate; no public contribution destination or maintainer identity is confirmed. Prepare a local patch and its evidence. Do not upload private workspaces, official attachments or credentials.

Read [AGENTS.md](AGENTS.md), [LICENSE_SCOPE.md](LICENSE_SCOPE.md) and [docs/MAINTENANCE.md](docs/MAINTENANCE.md). Preserve the canonical Store transactions, immutable object versions, original tests and failure boundaries. A UI, Git merge or status label must not manufacture verified evidence.

Create a dedicated environment and install the relevant extras:

```console
python -m venv .venv
python -m pip install ".[test,build]"
python -m unittest discover -s tests -p "test_*.py" -v
```

Use the interpreter inside `.venv` in the last two commands. Full historical regression additionally requires the separately obtained authorized fixture set and `.[historical]`; see [fixture instructions](docs/HISTORICAL_FIXTURES.md). A missing fixture or dependency is a limitation, not a pass.

Change only the affected behavior, retain a reproducible failing case and rerun that path. Record actual commands, interpreter/platform, expected and actual output, and remaining unexecuted checks. CI files describe intended automation; only a completed CI run proves execution.

Patch descriptions should explain the user-visible problem, resulting behavior, relevant tests and risks. Use the provided PR template when a repository is eventually selected. Keep reports from human review, independent Agent review, runtime execution and static checks separate.
