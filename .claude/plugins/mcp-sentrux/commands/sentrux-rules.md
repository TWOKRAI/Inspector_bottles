---
description: Check architectural invariants from .sentrux/rules.toml
---

Run the `.sentrux/rules.toml` rule check:

1. Check whether `.sentrux/rules.toml` exists at the project root. If not — tell the user the file needs to be created (see https://github.com/sentrux/sentrux and [`.claude/plugins/mcp-sentrux/rules.template.toml`](../../.claude/plugins/mcp-sentrux/rules.template.toml) if present), and show the minimal generic template:

```toml
[constraints]
max_cycles   = 0
no_god_files = true

# Paths in [[boundaries]] are LITERAL directory prefixes: `*` stands for a file name
# and does NOT expand a directory segment ("src/*/domain" matches nothing). Use the
# full path src/<pkg>/<layer> with no trailing slash. Keys: from/to/reason
# (there is NO `forbidden` key — sentrux silently ignores unknown keys).
[[boundaries]]
from   = "src/your_package/domain"
to     = "src/your_package/adapters"
reason = "domain must not depend on adapters (DIP)"
```

> This is a generic example. Fit the paths to the real architecture (see `.claude/modes/_stack.md` → "Layers") or take a ready-made archetype from `.claude/plugins/mcp-sentrux/templates/` (`.sentrux/rules.toml` is usually already deployed by `claude-kit new`).

2. If the file exists — call `mcp__sentrux__check_rules` with `path` = the absolute path to the project root.

Show the user:
- Which rules passed ✅, which failed ❌.
- For each failure — the specific files/imports violating the rule.
- A hint on how to fix it (extract to a shared layer, invert the dependency, apply DI).

$ARGUMENTS
