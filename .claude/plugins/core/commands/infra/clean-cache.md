---
description: Clean Python caches (__pycache__, .pytest_cache, *.pyc, .coverage) — dry-run by default
---

Show which Python caches and tool artifacts sit in the project:

```bash
uv run --no-project python scripts/clean_cache/clean_cache.py
```

**Runs in dry-run by default** — only shows what *would* be deleted. Actual deletion — the `--apply` flag.

> The script is installed automatically via `claude-kit new` (from `.claude/plugins/lang-python/templates/scripts/clean_cache/`).

What it typically cleans (patterns are configurable): `__pycache__/`, `.pytest_cache/`, `.mypy_cache/`, `.ruff_cache/`, `.tox/`, `htmlcov/`, `*.egg-info/`, `*.pyc`, `*.pyo`, `*.pyd`, `.coverage`, `coverage.xml`.

Does not touch: `.git`, `.venv`, `venv`, `env`, `node_modules`, `.qex`, `.sentrux`.

Useful options (if `scripts/clean_cache/` is installed):
- `--apply` — actual deletion.
- `--root src/<package>` — only a subdirectory.
- `--format json` — machine-readable report for agents.
- `--apply --quiet` — for CI (exit 0/1/2, no output).
- `--min-size 1000000 --limit 20` — only heavy targets, top 20.

**Exit codes (if scripts/clean_cache/ is installed):**
- `0` — success (including "nothing to delete").
- `1` — with `--apply`, some paths failed to delete.
- `2` — slow-rail refusal (root = `/` or `$HOME`), invalid TOML, no such `--root`. Nothing was deleted.

**When to use:**
- Before a commit / build artifact — guarantee a clean workspace.
- After a refactor that renamed/removed modules — `*.pyc` from old names breaks imports.
- Free up space — a repo with a long test history can accumulate 10-50 MB easily.

$ARGUMENTS
