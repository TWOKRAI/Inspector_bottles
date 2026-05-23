# Agent worktree isolation — pattern doc

Native Claude Code feature (frontmatter `isolation: "worktree"`). **Not** enabled by default in this seed because:

1. It changes how agents touch the file tree (each isolated agent works in a temporary `git worktree`).
2. Existing `/pipeline` runs agents sequentially — there's no race condition to solve right now.
3. Worktree cleanup adds disk churn and one more failure mode (orphaned worktrees).

But the moment you start running **parallel agents** on the same project (manager dispatches two implementers, or developer + tester run concurrently), you need it. This file documents the pattern so future-you knows how.

## When to enable on an agent

Add `isolation: "worktree"` to an agent's frontmatter when **all** of:

- The agent **writes** files (Read-only agents like `investigator` don't need it)
- The agent might run **concurrently** with another file-writing agent on the same repo
- The agent's task is **self-contained** within one logical scope (one task, one branch)

Bad fit: `manager` (orchestrator, doesn't write code itself), `docs-writer` running solo (no concurrency), `debugger` (often needs full repo state, not isolated copy).

Good fit: `developer` (writes a lot, often parallel candidates), `tester` (writes tests for the same diff developer is producing).

## How to enable

Edit the agent's frontmatter (e.g. `agents/company/developer.md`):

```yaml
---
name: developer
description: ...
model: claude-sonnet-4-6
tools: Read, Write, Edit, Glob, Grep, Bash, mcp:qex:search_code
isolation: worktree                # ← add this
---
```

Claude Code does the rest: when the agent is spawned, it creates a `git worktree` in a temp dir, the agent operates there, and on completion the result is either merged back or the worktree is discarded.

## What changes for the agent

- The agent's CWD is the worktree, not the original repo
- Other agents' in-flight changes are invisible until they finish
- Tool calls that depend on cwd (qex, sentrux, codegraph index in `.codegraph/`) need to be re-thought — they may re-index the worktree, which is wasteful

## What you need to handle manually

- **Local indexes per worktree:** qex/codegraph each maintain `~/.qex/<hash>` or `.codegraph/codegraph.db`. In a worktree they may re-index from scratch. Acceptable for short tasks, expensive for long ones. Mitigation: have the orchestrator pre-warm the index in the main tree, or accept the overhead.
- **`.env` / secrets:** if your agent needs `.env`, it's in the worktree only if `.env` is **tracked** (it shouldn't be). Either copy via a setup step or pass via env vars.
- **uv / venv:** a worktree starts without `.venv/`. The agent needs to `uv sync` again, or share a venv via `UV_PROJECT_ENVIRONMENT` env var.

## Smoke test before committing to this pattern

```bash
# In a sacrificial branch
git worktree add ../seed-worktree-test HEAD
cd ../seed-worktree-test
# Run a quick task that touches files + tests
make gate
cd -
git worktree remove ../seed-worktree-test
```

If `make gate` works in the worktree without the agent layer involved, the project tolerates worktree isolation. If not, the project has hidden global state that needs fixing before adding `isolation: worktree`.

## When to revisit

Add `isolation: worktree` to one agent (probably `developer`) when you actually start running parallel `/pipeline` instances. Don't add it speculatively — sequential `/pipeline` runs work fine without it, and the cost of getting orphaned worktrees is real.

## Sources

- Claude Code Agents docs: <https://code.claude.com/docs/en/agents>
- Claude Code Worktrees Guide: <https://www.claudedirectory.org/blog/claude-code-worktrees-guide>
- Git worktree manual: `git help worktree`
