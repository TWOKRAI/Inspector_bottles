# Agent worktree isolation — pattern doc

Native Claude Code feature (frontmatter `isolation: "worktree"`). **Not** enabled by default in this seed because:

1. It changes how agents touch the file tree (each isolated agent works in a temporary `git worktree`).
2. Existing `/dev:pipeline` runs agents sequentially — there's no race condition to solve right now.
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
model: claude-sonnet-5
tools: Read, Write, Edit, Glob, Grep, Bash, mcp__qex__search_code
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
- **uv / venv (false-green trap):** a worktree starts without `.venv/`. A file-writing agent must run `uv sync` **inside the worktree** and invoke that worktree's own `.venv` python. Do **not** share a venv via `UV_PROJECT_ENVIRONMENT` (and beware `uv run` falling back to the main venv): the shared venv's editable install points at the main `src/`, so the worktree's tests run against stale code and pass falsely. Verify with `python -c "import <module>; print(<module>.__file__)"` resolving inside the worktree.

## Fan-out lifecycle (parallel `/dev:pipeline`)

In parallel mode `/dev:pipeline` fans out **per independent Task** — one `isolation: "worktree"`
agent (developer/tester) per Task, several Agent calls in one message. Read-only agents
(reviewer) run un-isolated and may run concurrently: they only read committed diffs, so they
don't race on files. The orchestration policy (independence gate, caps, which agents commit)
lives in the `/dev:pipeline` "Parallel mode" section; this section is the per-agent mechanism.

Lifecycle per isolated agent: **create → work → commit → merge-back → cleanup.**

- **Base ref:** by default (`worktree.baseRef = fresh`) a native worktree branches from
  `origin/<default-branch>`. Set `worktree.baseRef = head` so it branches from local HEAD (your
  feature branch with all WIP) — otherwise the worktree misses feature commits not yet merged
  into the default branch and tests run against stale code. Pushing the feature branch to
  `origin/<feature>` does **not** fix this (`fresh` bases off `origin/<default>`, not your
  branch); if you can't set `baseRef=head`, fall back to sequential.
- **Commit before cleanup:** `ExitWorktree action:"remove"` refuses to delete a worktree that
  has uncommitted files or unmerged commits unless `discard_changes: true`. Merge/commit first.
- **Shared `.git/hooks`:** every worktree of a repo shares the parent `.git/hooks`. So a commit
  inside any worktree fires the same post-commit qex reindex (→ `~/.qex` lock race; reindex
  from the main worktree only — see `/mcp-qex:install-reindex-hook`) and the same session-log
  pre-commit hook stages `docs/sessions/<today>.md` into each commit (→ merge-back conflict on
  that append-only file; resolve with a union merge).
- **venv (false-green):** each isolated writer must `uv sync` in its own worktree and use that
  worktree's `.venv` python — a shared venv makes tests pass against stale main `src/` (see
  "uv / venv (false-green trap)" above). This is the most-confirmed fan-out footgun.
- **Failed merge-back / orphaned worktree:** clean up deterministically before escalating —
  `git worktree remove -f -f <path>` (double `-f` for a locked dir), then `git branch -D
  worktree-agent-*`, then `git worktree prune`. Escalate to teamlead only if cleanup itself fails.
- **Windows cleanup:** if a worktree dir is held by a process (editor, file index), `git
  worktree remove` can fail — close handles, then `git worktree prune` to clear stale entries.

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

Add `isolation: worktree` to one agent (probably `developer`) when you actually start running parallel `/dev:pipeline` instances. Don't add it speculatively — sequential `/dev:pipeline` runs work fine without it, and the cost of getting orphaned worktrees is real.

## Sources

- Claude Code Agents docs: <https://code.claude.com/docs/en/agents>
- Claude Code Worktrees Guide: <https://www.claudedirectory.org/blog/claude-code-worktrees-guide>
- Git worktree manual: `git help worktree`
