---
description: Run the project's entry point — via pyproject [project.scripts], make run, or python -m <package>
---

Run the project's main entry point. Determine it by priority:

## Steps

1. **If `pyproject.toml` has `[project.scripts]`** — pick the first entry and run via uv:
   ```bash
   uv run <script-name> $ARGUMENTS
   ```

2. **Else if there's a `Makefile` with a `run` target**:
   ```bash
   make run ARGS="$ARGUMENTS"
   ```

3. **Else if there's a `src/<package>/__main__.py`** (or `<package>/__main__.py`):
   ```bash
   uv run python -m <package> $ARGUMENTS
   ```

4. **Else if there's a `src/<package>/cli.py` or `app.py` or `main.py`**:
   ```bash
   uv run python -m <package>.<module> $ARGUMENTS
   ```

5. **If nothing is found** — ask the user for the entry-point path and suggest adding `[project.scripts]` to `pyproject.toml`.

## Hints

- If it fails with `ModuleNotFoundError` — run `uv sync` (or `make install`).
- If it fails with a UI/GUI error — check that the corresponding optional group is installed: `uv sync --group <ui-group>` (see `pyproject.toml` → `[dependency-groups]`).
- If the process crashes — ask whether to run `/dev:debug` for diagnosis.

## Smoke mode (live-smoke for `/dev:pipeline` S5)

When you need **not** a full run but just a check that "the app starts" (the S5
live-smoke gate before review) — add a non-destructive flag to the steps above so
the entrypoint comes up and exits right away, without doing real work:
```bash
uv run python -m <package> --version   # or --help
```
The goal is to catch an import cycle at startup, a broken entrypoint, a
misconfigured env. If the entrypoint has no `--version`/`--help` — `uv run python -c "import <package>"` is enough.
A failure at this step = STOP before S6 (see `/dev:pipeline` → step 3 Live-smoke).

## Project-specific override

If `.claude/modes/_stack.md` has an "Entry point" section — follow it instead of the algorithm above.

$ARGUMENTS
