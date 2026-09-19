---
description: Turn ON the qex post-commit auto-reindex (OFF by default — the index is rebuilt only by /mcp-qex:qex-reindex; no-ops when Ollama/qex is down)
---

The qex reindex is a **PART** (`hooks/git/post-commit.d/qex-reindex.sh`) run by the core
post-commit dispatcher (`.claude/plugins/core/hooks/git/post-commit.sh`). The dispatcher and
the part are installed by `claude-kit-project new`, `init --apply` and `plugin upgrade --apply`.

**Since 1.2.x the part is OFF by default.** A commit never starts an embedder run on its own
(on a large project with an 8b embedder that is tens of minutes of GPU/CPU); the index is
updated only when you run `/mcp-qex:qex-reindex` (incremental) or `/mcp-qex:qex-rebuild`.

**Turn auto-reindex on** — one key in the ```ini block of `.claude/modes/_stack.md`:

```ini
qex_auto_reindex = on     # off (default): only by /mcp-qex:qex-reindex
```

Precedence: env `QEX_AUTO_REINDEX=on|off` (one-off runs, tests) → the key → off.

**Verify** (the dispatcher captures every part's output into one log):

```bash
git commit --allow-empty -m "test post-commit dispatcher"
tail -5 .claude/logs/post-commit.log
```

With the key off you see `skip: auto-reindex off (qex_auto_reindex=off; run /mcp-qex:qex-reindex)`;
with it on — `ok: reindexed`, or a `skip: ...` naming why not (qex not found, Ollama down,
mcp-qex not enabled in `.mcp.json`). Never a hard failure that blocks the commit.

**If the dispatcher itself is missing** (manual bootstrap, partial checkout):

```bash
test -f "$(git rev-parse --git-path hooks/post-commit)" && echo OK || echo MISSING
claude-kit-claude plugin doctor . --fix
```

What auto mode gives you when on: after every commit in the main tree an **incremental**
reindex (Merkle-diff; seconds on a small repo, minutes to hours on a large one) as one part
of the dispatcher's run, never blocking the commit; `/core:quality:doctor` and the core
`mcp-health-check.sh` SessionStart hook report how many commits the index is behind HEAD
(`idx: qex-reindex=<N>`).

**Binary path** — if qex isn't on `PATH` or under `~/.cargo/bin/qex` / `~/.local/bin/qex`,
set `QEX_BIN` in the environment.

Files:

- [../hooks/git/post-commit.d/qex-reindex.sh](../hooks/git/post-commit.d/qex-reindex.sh) —
  the part itself, run by the core dispatcher.

$ARGUMENTS
