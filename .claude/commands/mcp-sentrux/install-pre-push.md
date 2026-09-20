---
description: Install the sentrux pre-push hook (blocks push on rule violations/regression)
---

Install a git pre-push hook that runs structural checks before every `git push`:

```bash
bash scripts/install_pre_push_hook.sh
```

Project got `.claude/` via `claude-kit-project init` (not `new`), and `scripts/` is still
empty? The same installer lives in the plugin and finds the hook body there itself:

```bash
bash .claude/plugins/core/templates/scripts/install_pre_push_hook.sh
```

What this gives you (in execution order):
- **injections-record gate** — if the branch changed `tests/**`, its plan must have a filled-in
  `property | predicted red | observed red` line; otherwise the push is blocked.
  Runs first: a cheap check before the structural analysis.
- `sentrux check` — blocks the push if a rule from `.sentrux/rules.toml` is violated.
- `sentrux gate` — blocks the push on a structural regression relative to the baseline.

If sentrux is **not installed** — the structural part is silently skipped (warn-skip, exit 0).
So installing the hook is safe even without the MCP dependency.

The installer resolves the hook path via `git rev-parse --git-path hooks/pre-push` and exits 1
without writing anything when:
- `core.hooksPath` is set (git does not run `.git/hooks` in that case);
- the hook path or its containing directory is a symlink (claude-kit never writes through a link);
- a foreign (unmarked) hook already exists.

`--force` overrides ONLY the foreign-hook case, rebuilding the hook from the project's own
`scripts/hooks/pre-push` — it never bypasses the `core.hooksPath` or symlink refusals.

If sentrux is **installed but no baseline has been recorded yet** — `sentrux gate` will fail the
very first push with `Failed to load baseline`. This is not a broken hook: record the baseline
once (`sentrux gate --save`, see below) right after installing.

**Update the baseline** after a deliberate metrics improvement:

```bash
sentrux gate --save
```

**Emergency bypass** (only in extreme cases, not recommended):

```bash
git push --no-verify
```

Files (paths from the project root; laid down by the skeleton on `claude-kit-project new` / `init`):
- `scripts/install_pre_push_hook.sh` — the installer.
- `scripts/hooks/pre-push` — the body of the structural gate (the installer assembles the final
  `.git/hooks/pre-push` from it and the injections block).

> Paths are deliberately not relative links: this file lives both as the plugin source
> (`.claude/plugins/mcp-sentrux/commands/`) and as the materialized mirror
> (`.claude/commands/mcp-sentrux/`) — their depth to the project root differs, so one
> relative link cannot be correct in both. Delivery of these two files is guarded by
> `tests/e2e/test_consumer_smoke.py`.

After installation the hook works locally (it does not travel with the repository). On a new
machine it needs to be reinstalled.

$ARGUMENTS
