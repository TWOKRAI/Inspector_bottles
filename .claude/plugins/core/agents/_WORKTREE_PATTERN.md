# Agent worktree isolation — pattern doc

**Single source of worktree rules for all three transports** — subagents (`Agent` +
`SendMessage`), the live team (`/dev:team`), and Workflow. `team-protocol` §6, `/dev:pipeline`,
`/dev:team`, and the `agent-teams` README each point here instead of restating the mechanics;
read the rule here, not a paraphrase there.

Native Claude Code feature (frontmatter `isolation: "worktree"`). **Not** enabled by default in this seed because:

1. It changes how agents touch the file tree (each isolated agent works in a temporary `git worktree`).
2. Existing `/dev:pipeline` runs agents sequentially — there's no race condition to solve right now.
3. Worktree cleanup adds disk churn and one more failure mode (orphaned worktrees).

But the moment you start running **parallel agents** on the same project (manager dispatches two implementers, or developer + tester run concurrently), you need it. This file documents the pattern so future-you knows how.

## Default: the shared tree — a worktree only for a real fan-out (Д45)

A **sequential** chain — `tester`(RED) → `developer`(GREEN) → `reviewer`, a follow-up part
briefed from the previous part's handoff, one writer at a time — runs in the **shared tree**
(`team-protocol` §6 mode A). A worktree is for a **fan-out**: two or more writers at once on
disjoint `Files:`. Measured 2026-09-16 (Task 4.1, five agents, strictly sequential, each in its
own `isolation: "worktree"`): the isolation bought nothing — the RED test was blinded by order,
not by the tree — and cost:

- **the nested-memory tax, five times over:** the FIRST read of any path under
  `.claude/worktrees/agent-<id>/` injects three `CLAUDE.md` attachments (the main tree's
  `.claude/CLAUDE.md` plus both worktree copies), **+19…28k tokens in one call**; a worktree
  agent's real working budget is ~25k below the ceiling. Budget it that way;
- two lead errors that only a worktree makes possible (`git checkout <file>` wiping an agent's
  uncommitted edits; a false-red preflight from the inherited `VIRTUAL_ENV`, see below);
- the pre-report gate's log dying with the worktree (Task 2.7).

**Where a worktree may live.** Agent-tool worktrees (`isolation: "worktree"`) are placed by the
harness under `.claude/worktrees/` — the `worktree` settings object (`baseRef`, `sparsePaths`,
`symlinkDirectories`) has no location key, so the tax above cannot be dodged by layout, only
shrunk (smaller `CLAUDE.md`). Worktrees you create by hand (the live team, a script) go **beside
the repo**, never under it: `git worktree add ../<repo>--team-<task> -b <type>/<slug>-<task>`.
Same file, same commit, read from a sibling worktree — **+3 410** tokens, zero attachments; from
`.claude/worktrees/` — **+17 123** with three. The team gates judge "this project" by the main
repository's `git-common-dir`, so a sibling worktree stays gated.

## When to enable on an agent

Add `isolation: "worktree"` to an agent's frontmatter when **all** of:

- The agent **writes** files (Read-only agents like `investigator` don't need it)
- The agent **will** run **concurrently** with another file-writing agent on the same repo
  (a real fan-out — not "might", not a sequential chain that merely could be parallel)
- The agent's task is **self-contained** within one logical scope (one task, one branch)

Bad fit: `manager` (orchestrator, doesn't write code itself), `docs-writer` running solo (no concurrency), `debugger` (often needs full repo state, not isolated copy).

Good fit: `developer` (writes a lot, often parallel candidates), `tester` (writes tests for the same diff developer is producing).

## How to enable

Edit the agent's frontmatter (e.g. `plugins/dev/agents/developer.md`):

```yaml
---
name: developer
description: ...
model: sonnet
tools: Read, Write, Edit, Glob, Grep, Bash, mcp__qex__search_code
isolation: worktree                # ← add this
---
```

Claude Code does the rest: when the agent is spawned, it creates a `git worktree` in a temp dir, the agent operates there, and on completion the result is either merged back or the worktree is discarded.

## Native `isolation: worktree` vs `EnterWorktree`/`ExitWorktree` vs manual `git worktree add`

Three ways to get a worktree; pick by who is doing the work, not by habit. `isolation: worktree`
is documented (Agents docs, linked below); `EnterWorktree`/`ExitWorktree` and
`worktree.baseRef` are real tools present on the session but **not** covered by that page —
noted here so this doc stays the one place that names all three.

**Native `isolation: "worktree"`** (Agent tool param, also used by Workflow script steps) — use
when an **orchestrator spawns an agent** (developer, tester) and the whole create → work →
merge-back → cleanup lifecycle should be handled by the engine, not by hand. This is what
`/dev:pipeline` parallel mode uses (a sequential RED → GREEN chain stays in the shared tree). **Prefer this
over `EnterWorktree`/`ExitWorktree` whenever you are spawning an agent** — the engine handles
merge-back and cleanup for you; `EnterWorktree`/`ExitWorktree` do not.

**`EnterWorktree` / `ExitWorktree`** — switch the **whole calling session** into one worktree
(session = one worktree, no parallelism) and back. This is an escape hatch for isolating a
single task's own session — a solo agent that wants a scratch copy without touching the shared
tree — not a fan-out mechanism. `ExitWorktree action:"remove"` refuses to delete a worktree that
has uncommitted files or unmerged commits unless `discard_changes: true`; commit or merge first.

**Manual `git worktree add`** — use when a worktree is needed **outside an agent's lifecycle**:
the live team (the lead has no `isolation` param to hand a teammate — see the transport table
below), a human poking at a scratch checkout, a non-agent script, the smoke test below, or any
case that needs control over the base ref beyond what the project-wide `baseRef` setting gives
you (e.g. a worktree pinned to a specific old commit instead of HEAD/`origin/<default>`).

## Transport table — creation, base, commit, merge-back, cleanup, test-visibility

| Transport | How the worktree is created | Base ref | Who commits | Merge-back | Cleanup | How to verify tests see your code |
|---|---|---|---|---|---|---|
| **Subagents** (`Agent`, Task tool) | `Agent(isolation: "worktree")` — engine-managed | `worktree.baseRef` project setting (seed default: `head` — see below) | the isolated agent itself, inside its worktree | the orchestrator, by hand, one branch at a time. **If you rewrite the agent's commit while integrating** (conflict resolution, dedup, amend), delete its worktree and branch in the same step — otherwise the branch is a trap that reintroduces what you removed. Verify with `git cherry HEAD <branch>`: `-` means the patch is already in HEAD, `+` means it is not | **the engine cleans ONLY a worktree that stayed unchanged** — any agent that commits leaves its worktree AND its branch behind. The orchestrator removes both at the wave's merge point (`git worktree remove` + `git branch -D` + `git worktree prune`). Measured 2026-09-10: 11 orphans from earlier phases, 1.6 GB, because this row used to claim cleanup was automatic | **before trusting any test run:** `env -u VIRTUAL_ENV uv sync --extra dev` inside the worktree (`--extra dev` if the project keeps its test deps in `[project.optional-dependencies]`), then `env -u VIRTUAL_ENV uv run python scripts/worktree_preflight.py` — it prints the path of **both** your package and your test runner; BOTH MUST resolve inside the worktree (see "venv false-green trap" below) |
| **Live team** (`/dev:team`) | the **lead**, by hand, **beside the repo**: `git worktree add ../<repo>--team-<task> -b <type>/<slug>-<task>` off local HEAD (under `.claude/worktrees/` it pays the nested-memory tax — see "Default: the shared tree") | local HEAD at creation time — the `baseRef` setting does not reach this path (it is not native `isolation`); verify with `git rev-parse HEAD` in the teammate's report | the teammate (`developer`/`teamlead`/`tester`/`junior`) that owns that worktree | the **lead only**, one branch at a time, `git show --stat` on each merged commit | the lead: `git worktree remove` after merge; an orphaned worktree is an escalation, not a silent delete | same check, run by the teammate inside its own worktree, printed in its report before it claims a test result |
| **Workflow** (JS script) | a script step sets `isolation: "worktree"` — engine-managed, same mechanism as subagents | `worktree.baseRef` project setting, same as subagents | the step's agent | engine-managed | engine-managed | the script step must itself include the `uv sync` + import-path check as an explicit step (0-token orchestration means nothing checks this for you) — do not assume a Workflow agent remembers a rule from this doc that was never in its prompt |

**Only the lead merges, one branch at a time.** This is the one rule that holds regardless of
transport: whoever creates worktrees for other writers (the live-team lead; an orchestrator
running subagent fan-out) is also the only one who merges them back. Two branches merging
concurrently into the same tree is how a worktree pattern turns into a race condition the whole
mechanism exists to avoid.

**Writer cap: ≤ 3 concurrent writers, of them ≤ 1–2 "tooling-heavy" (`teamlead`, 40+ tool-uses
per task).** More writers do not go faster — past this cap you trade speed for session-limit
hits and commit races. This cap is the same number across `team-protocol` §6 (Mode B fan-out),
`/dev:pipeline` parallel mode, and `/dev:team`; do not restate a different number in any of
those — link here instead.

## What changes for the agent

- The agent's CWD is the worktree, not the original repo
- Other agents' in-flight changes are invisible until they finish
- Tool calls that depend on cwd (qex, sentrux, codegraph index in `.codegraph/`) need to be re-thought — they may re-index the worktree, which is wasteful

## What you need to handle manually

- **Local indexes per worktree:** qex/codegraph each maintain `~/.qex/<hash>` or `.codegraph/codegraph.db`. In a worktree they may re-index from scratch. Acceptable for short tasks, expensive for long ones. Mitigation: have the orchestrator pre-warm the index in the main tree, or accept the overhead.
- **`.env` / secrets:** if your agent needs `.env`, it's in the worktree only if `.env` is **tracked** (it shouldn't be). Either copy via a setup step or pass via env vars.
- **uv / venv / `VIRTUAL_ENV` / `uv run pytest` (false-green / false-red trap) — read this before trusting any test run in a worktree:** *(the env-var name is spelled out here on purpose: on 2026-09-10 three agents hit this within one hour and none of them found this section, because they grepped for `VIRTUAL_ENV` and the heading said only "uv / venv")*
  a fresh worktree starts without `.venv/` and without a dev-extra install. `uv run <anything>`
  can silently fall back to the **main tree's** `.venv` (`which pytest` resolves outside your
  worktree) and then execute the **main tree's** `src/`, not yours.

  > **Paste this line into every prompt that spawns a writer into a worktree:** "In your
  > worktree, run `env -u VIRTUAL_ENV uv sync --extra dev` once before any test command
  > (`--extra dev` if this project declares its test deps as an extra rather than a
  > dependency-group), run every later command as `env -u VIRTUAL_ENV uv run …`, then verify
  > with `env -u VIRTUAL_ENV uv run python scripts/worktree_preflight.py` (or
  > `… python -c \"import <your top-level package> as m, pytest; print(m.__file__);
  > print(pytest.__file__)\"`) — BOTH printed paths MUST resolve inside your worktree. If
  > either does not, your test run is not evidence of anything; fix the venv before
  > reporting a result either way."

  **`VIRTUAL_ENV` is inherited from the main checkout** (confirmed 2026-09-16, Task 4.1): with it
  set, `uv run` inside the worktree resolves the package and `pytest` from the MAIN tree's
  `.venv`, and the preflight goes red for a working tree — a false red blamed on the agent. The
  `env -u VIRTUAL_ENV` prefix on every command is the fix; `UV_PROJECT_ENVIRONMENT` sharing is
  not.

  **Check the runner, not only the package** — this is the half that was missing until
  2026-09-10, and it is the half that matters. `uv sync` installs the project itself
  editable, so the package import resolves inside the worktree and the check goes green
  **while `pytest` still resolves to the main tree's `.venv` and executes the main tree's
  `src/`**. A verification that passes for a reason unrelated to the property it claims to
  check is the exact failure this document exists to prevent.

  The symptom is two-sided, confirmed both ways on this project: on 2026-06-22 the stale-venv
  fallback gave **false-green** (tests looked like they passed, ran against old code); in
  Task 6.8 it gave **false-red** (a working implementation reported the same 5 pre-existing
  failures as before the fix — re-running the suite against a correctly synced worktree venv
  then showed 7/7 with zero code
  changes). Do **not** share a venv via `UV_PROJECT_ENVIRONMENT`. This mitigation lived only in
  `.claude/memory/` after the first incident and still did not reach the prompt for the second —
  it belongs in the prompt template (see the transport table's last column and the quoted line
  above), not only in memory.

- **Never `git checkout <file>` to undo a break-injection in an agent's tree** (2026-09-16):
  it restores the file to HEAD and wipes the agent's uncommitted edits together with the
  injection — recovered that day only because the diff was still in the transcript. Undo an
  injection with the inverse edit; if the agent's work arrived uncommitted, commit it FIRST,
  then inject.
- **Lint caches (`ruff check` false-green) — verify any lint claim with `--no-cache`:**
  `ruff check` reads `.ruff_cache`, and an entry cached **before** new files appeared keeps
  reporting "All checks passed" for a tree that is actually red. In the Task 6.7 team run this
  cost two wrong adjudications in a row: the lead used a cached `ruff check` to declare a
  developer's report of new `I001` errors a fabrication, then did the same to the tester — and
  was wrong both times; the mechanism the developer had described immediately was real.

  > **Rule:** when you contradict an agent's report about lint, re-run with `--no-cache` first.
  > Refuting a correct report costs more than the original error — the reporter is trained to
  > doubt a true observation, and the real defect stays in the tree.

- **Stale bytecode (`__pycache__`) — clean it before any mutation/injection pass:**
  a source edit of the **same byte length** (swapping two characters, flipping a comparison)
  can leave `.pyc` mtime/size unchanged, so Python reuses the stale bytecode and runs the code
  you thought you reverted. Injection results then look plausible and mean nothing. Clear
  `__pycache__` and set `PYTHONDONTWRITEBYTECODE=1` for the whole pass, and take a clean
  baseline both before and after — do not "repair" contaminated numbers by subtracting a basis.

## Fan-out lifecycle (parallel `/dev:pipeline`)

In parallel mode `/dev:pipeline` fans out **per independent Task** — one `isolation: "worktree"`
agent (developer/tester) per Task, several Agent calls in one message. Read-only agents
(reviewer) run un-isolated and may run concurrently: they only read committed diffs, so they
don't race on files. The orchestration policy (independence gate, caps, which agents commit)
lives in the `/dev:pipeline` "Parallel mode" section; this section is the per-agent mechanism.

Lifecycle per isolated agent: **create → work → commit → merge-back → cleanup.**

- **Base ref:** `worktree.baseRef` accepts `fresh` (default) — branches from
  `origin/<default-branch>` for a clean tree — or `head` — branches from your current local HEAD,
  so unpushed commits and feature-branch state are present. Applies to `--worktree`,
  `EnterWorktree`, **and agent isolation** alike. The seed sets `"worktree": {"baseRef": "head"}`
  in `core/settings.partial.json` project-wide, because a worktree that only sees
  `origin/<default-branch>` misses feature commits not yet merged into default and tests run
  against stale code. Pushing the feature branch to `origin/<feature>` does **not** fix this
  (`fresh` still bases off `origin/<default>`, not your branch). If the composed `settings.json`
  doesn't carry this key (stale compose, local override) — fall back to sequential.
- **Commit before cleanup:** `ExitWorktree action:"remove"` refuses to delete a worktree that
  has uncommitted files or unmerged commits unless `discard_changes: true`. Merge/commit first.
- **Shared `.git/hooks`:** every worktree of a repo shares the parent `.git/hooks`. A commit
  inside any worktree used to fire the same post-commit qex reindex in every worktree (lock
  race on `~/.qex` + fragmented indexes); the guard now lives in the core dispatcher
  `hooks/git/post-commit.sh` — parts never run from a linked worktree. The same session-log
  pre-commit hook still stages `docs/sessions/<today>.md` into each commit — this is by design,
  not a race: `docs/sessions/*.md merge=union` in `.gitattributes` resolves the append-only file
  on merge-back without a conflict.
- **venv (false-green / false-red):** see "What you need to handle manually" above — the most
  confirmed fan-out footgun on this project, confirmed in both directions.
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
