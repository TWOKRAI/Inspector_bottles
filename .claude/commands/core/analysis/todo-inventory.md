---
description: Inventory of TODO/FIXME/HACK with git blame (author, age)
---

Run a tech-debt inventory:

```bash
uv run --no-project python scripts/todo_inventory/todo_inventory.py
```

What it collects: `TODO/FIXME/HACK/XXX/BUG/NOTE` (tags configurable), attributed to the author and the line's last-change date via `git blame`.

Config: [scripts/todo_inventory/todo_inventory.toml](../../scripts/todo_inventory/todo_inventory.toml). Details in [README.md](../../scripts/todo_inventory/README.md).

Useful options:
- `uv run --no-project python scripts/todo_inventory/todo_inventory.py --no-blame` — fast scan without git (no authors/age).
- `uv run --no-project python scripts/todo_inventory/todo_inventory.py --group-by author` — who left the most.
- `uv run --no-project python scripts/todo_inventory/todo_inventory.py --sort-by age --limit 20` — top 20 oldest.
- `uv run --no-project python scripts/todo_inventory/todo_inventory.py --format json` — for CI/notifications.

**When to use:**
- Before a tech-debt cleanup sprint: what's there, who left it, how old it is.
- Finding HACK/XXX older than N days — critical markers for review.
- Summary by author — who to route "their own" TODOs back to.

**Notes:**
- `git blame` is slow with a large number of hits — use `--no-blame` for a fast scan.
- The script may find TODOs in its own [todo_inventory.py](../../scripts/todo_inventory/todo_inventory.py) — this is not a bug, add `scripts/todo_inventory/*` to `exclude.path_patterns` in your own config.

$ARGUMENTS
