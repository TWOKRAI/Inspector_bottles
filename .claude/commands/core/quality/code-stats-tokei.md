---
description: Precise LOC count via tokei (shares the TOML with /core:quality:code-stats)
---

Run the tokei wrapper:

```bash
uv run --no-project python scripts/code_stats/code_stats_tokei.py
```

Notes:
- Uses the SAME config [scripts/code_stats/code_stats.toml](../../scripts/code_stats/code_stats.toml) — extensions, exclusions, output format.
- Requires the `tokei` binary (`brew install tokei` / `cargo install tokei`). If not installed — the script prints a hint and exits 3.
- Grouping is always by language (not by directory) — a tokei quirk.
- LOC from tokei is **more precise** than the stdlib variant: real tokenizers recognize comments and string literals across all languages.

Useful options:
- `uv run --no-project python scripts/code_stats/code_stats_tokei.py --root src/<package>`
- `uv run --no-project python scripts/code_stats/code_stats_tokei.py --format json`

**When to use tokei vs stdlib:**
- tokei — precise numbers, faster on large repos, needs the binary.
- `/core:quality:code-stats` (stdlib) — no dependencies, can group by directories.

> `scripts/code_stats/` is installed automatically via `claude-kit new`. Without it, `tokei .` works directly from anywhere in the project (but without the shared TOML config).

$ARGUMENTS
