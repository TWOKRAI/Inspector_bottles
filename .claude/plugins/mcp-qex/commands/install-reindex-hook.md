---
description: Install the qex post-commit reindex hook (auto-reindexes qex after each commit; no-ops when Ollama/qex is down)
---

The qex reindex is a **PART** (`hooks/git/post-commit.d/qex-reindex.sh`) run by the
core post-commit dispatcher (`.claude/plugins/core/hooks/git/post-commit.sh`), not a
standalone `.git/hooks/post-commit` file of its own — so semantic search
(`mcp__qex__search_code`) doesn't fall behind the current state of the code and agents
don't degrade to `Grep`.

The dispatcher (and the part alongside it) is installed for you by `claude-kit-project
new`, `claude-kit-project init --apply` and `claude-kit-claude plugin upgrade --apply` —
there is normally nothing to run here manually. If it's missing (e.g. after a manual
bootstrap or a partial checkout), heal it with:

```bash
claude-kit-claude plugin doctor . --fix
```

**Check that the dispatcher is in place:**

```bash
test -f "$(git rev-parse --git-path hooks/post-commit)" && echo OK || echo MISSING
```

`MISSING` — run `claude-kit-claude plugin doctor . --fix`, then re-check.

**Verify it actually runs** (the dispatcher captures every part's output into one log,
regardless of exit code):

```bash
git commit --allow-empty -m "test post-commit dispatcher"
tail -5 .claude/logs/post-commit.log
```

You should see a line from the qex part: `ok: reindexed`, or a `skip: ...` line
explaining why it didn't (qex not found, Ollama down, or mcp-qex not enabled in
`.mcp.json`) — never a hard failure that blocks the commit.

What this gives you:

- After every commit, qex runs an **incremental** reindex (Merkle-diff, usually
  < 5 seconds) as one part of the dispatcher's run — doesn't block the commit.
- Semantic search stays fresh without a manual `/mcp-qex:qex-reindex`.
- `/core:quality:doctor` and the core `mcp-health-check.sh` SessionStart hook report how
  many commits the index is behind HEAD (`idx: qex-reindex=<N>`), read from the sha file
  the part writes after each successful run.

**Binary path** — if qex isn't on `PATH` or under `~/.cargo/bin/qex` /
`~/.local/bin/qex`, set `QEX_BIN` in the environment, or edit the `QEX_BIN` resolution at
the top of `.claude/plugins/mcp-qex/hooks/git/post-commit.d/qex-reindex.sh`.

**Disabling it** — delete the part locally (the dispatcher just skips a missing file):

```bash
rm .claude/plugins/mcp-qex/hooks/git/post-commit.d/qex-reindex.sh
```

Or disable the `mcp-qex` plugin entirely (`claude-kit-claude plugin disable mcp-qex .`) —
the part's own enabled-check (`grep '"qex"' .mcp.json`) also skips cleanly in that case,
so leaving the file in place after disabling the plugin is harmless too.

Files:

- [../hooks/git/post-commit.d/qex-reindex.sh](../hooks/git/post-commit.d/qex-reindex.sh) —
  the part itself, run by the core dispatcher.

$ARGUMENTS
