---
description: Test-to-code volume ratio per module (LOC-based)
---

Run the test-ratio count:

```bash
uv run --no-project python scripts/test_ratio/test_ratio.py
```

> The script is installed automatically via `claude-kit new` (from `.claude/plugins/lang-python/templates/scripts/test_ratio/`).

What it counts: for each module in `scan.module_roots` (configurable in TOML; sensible defaults: `src/`, or specific subpackages like `src/<package>/auth`, `src/<package>/api`) — LOC of files in `tests/` (or matching `test_*.py`/`*_test.py`/`conftest.py`) ÷ LOC of the rest of the production code.

Config: [scripts/test_ratio/test_ratio.toml](../../scripts/test_ratio/test_ratio.toml). Details in [README.md](../../scripts/test_ratio/README.md).

**Health markers:**
- `ok` — ratio ≥ `warn_threshold` (default 0.3)
- `!` — tests exist but are thin
- `x` — no tests

Useful options:
- `uv run --no-project python scripts/test_ratio/test_ratio.py --sort-by ratio --limit 10` — the weakest 10.
- `uv run --no-project python scripts/test_ratio/test_ratio.py --format json` — for CI/trends.

**When to use:**
- Complement to `/mcp-sentrux:sentrux-gaps`: sentrux shows "tests exist/don't exist", `test_ratio` shows **how much**.
- Before refactoring a large module: assess the risk.

**Limitation:** LOC ≠ coverage. For real coverage — `pytest --cov`.

$ARGUMENTS
