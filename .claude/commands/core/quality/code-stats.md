---
description: Count files/lines/characters per a TOML config (scripts/code_stats/)
---

Run the code stats counter:

```bash
uv run --no-project python scripts/code_stats/code_stats.py
```

> The script is installed automatically via `claude-kit new` (from `.claude/plugins/lang-python/templates/scripts/code_stats/`). If it's not in the project — copy it from the seed or use `tokei .` directly.

Useful invocation options:

- **Specific folder:** `uv run --no-project python scripts/code_stats/code_stats.py --root src/<package>`
- **JSON for parsing:** `uv run --no-project python scripts/code_stats/code_stats.py --format json`
- **Top-N directories:** `uv run --no-project python scripts/code_stats/code_stats.py --group-by directory --limit 20`
- **Custom config:** `uv run --no-project python scripts/code_stats/code_stats.py --config <path>`

Default config: [scripts/code_stats/code_stats.toml](../../scripts/code_stats/code_stats.toml) — extensions, exclusions (`__pycache__`, `.git`, `.venv`, etc.), comment/docstring/blank-line counting flags, output format.

Report details and columns: [scripts/code_stats/README.md](../../scripts/code_stats/README.md).

**When to use:**
- "How many lines of code are in module X?"
- "Which folder weighs the most in code?" (`--group-by directory`)
- A project-size snapshot before refactoring.

**Do NOT use** for architectural coupling analysis — for that, `mcp__sentrux__dsm` / `/mcp-sentrux:sentrux-health`.

$ARGUMENTS
