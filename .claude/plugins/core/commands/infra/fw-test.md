---
description: Run the project's tests (pytest or make test)
---

Run the project's tests.

## Priority

1. **If there's a `Makefile` with a `test` target:**
   ```bash
   make test
   ```

2. **Else if there's a `pyproject.toml` / `pytest.ini` / `tests/`:**
   ```bash
   uv run pytest -q
   ```

3. **If the project has its own test runner** (given in `.claude/modes/_stack.md` → "Test runner"):
   follow that instruction.

## After the run

Show the result:
- How many passed / failed / skipped.
- If there's a FAIL — print a short list (test names + first error line).
- Suggest `/dev:debug` to diagnose failing tests.

## Hints

- Windows: use `py -3` or `python3` if `python` points to 2.x.
- If pytest isn't installed — `uv add --group dev pytest pytest-cov`.

$ARGUMENTS
