---
description: Full development cycle in one command — plan → implement → test → review → ship (with failure-recovery via debugger)
disable-model-invocation: true
---

Automatic full cycle. The Director drives every stage. Explicit failure-recovery loops via `debugger` and escalation to `teamlead`.
Default transport is subagents; `--team` and `--workflow` are selected in §1′.

## Algorithm

> **Stage numbering.** `### N.` headings — reading order; stage IDs **of this file** — `S0…S7`
> (intake+research → plan → contract → RED → GREEN → final → review → integration). The numbering
> is local: stages, roles, handoff chains and gates are described once in the skill
> [`team-protocol`](../skills/team-protocol/SKILL.md) (§1 stages, §2 roles, §3 chains, §4
> escalation, §5 gates), and its S0–S8 are numbered differently — check by stage name, not by number.
> Machine gates are **callable gates** (S2 contract-complete, S3 RED-block, S7 Integration):
> invoked manually from this file, TRUE enforcement (git pre-commit/CI) — Phase 2.

### 0. Intake → Research (S0)

**Intake — first, never skipped.** Restate the owner's task in three blocks and
show it to them **before** research and planning:
- **Goal** — one sentence.
- **Acceptance** — 3–6 verifiable lines: input → expected output, number, file.
- **Out of scope** — what we don't touch.

At most two questions, and only where different readings would produce materially different work;
state everything else as an assumption out loud and move on. **Gate (HUMAN):** the owner confirms
the wording — both the plan and the review's acceptance criteria grow from it, so the cost of error here is maximal.

**Research — choosing the approach with a human in the loop**, after Intake and **before** planning.
> **Skip condition:** the task is clearly trivial (one file, no cross-module effects, < 1 day) →
> research is skipped, `research.md` is not created; STATE.md records "S0 skipped (trivial)".
> Intake is **not** cancelled by this skip condition — it's cheaper than any of the following stages.

Launch the **investigator** agent (Opus, read-only) with the `grill-me` and `brainstorm` skills active:
- Pass the task: $ARGUMENTS
- Investigator researches the task and generates `plans/YYYY-MM-DD_<slug>/research.md`:
  2–4 approaches with trade-offs, a recommended approach, open questions.
- If the `grill-me`/`brainstorm` skills are unavailable — investigator works in free-form mode
  and explicitly marks this in `research.md` ("skills unavailable — free-form analysis").
- **Gate S0 (HUMAN):** the user chooses an approach or confirms the recommended one →
  the pipeline continues to §1. The list of owner gates is in `team-protocol` §1/§5;
  there is deliberately no "human decides N times" counter here: it diverged from the list.

### 1. Planning (S1)

- **A plan for the current branch already exists** (`ls plans/*_<slug>*.md` is non-empty and its `Branch:` field
  matches `git branch --show-current`) → the stage is skipped. Take the first Task X.Y with
  status `[PENDING]` and go to §1′.
- **No plan exists** → run `/dev:plan <task>` and **do not repeat its steps here**: there the manager
  writes the spec with Task X.Y, `reviewer` in `MODE: plan` gives a verdict against the checklist, the owner
  approves it, then a `<type>/<slug>` branch is created, a line in `plans/README.md`, and a commit
  of the plan. Come back here with the approved plan and the branch name.

### 1′. Transport — how the remaining stages are executed

The stages and their gates are the same; the flag only changes **who hands work to whom**. The
selection criterion is the transport table in [`team-protocol`](../skills/team-protocol/SKILL.md) §8; here just
one line per flag.

- **No flag — subagents** (`Agent` + `SendMessage`, every handoff goes through you).
  Works always; read §2 onward as-is. This is the default, no separate confirmation needed.
- **`--team` — a live team.** Two checks, both **before** spawning: (1) the `agent-teams` plugin
  is enabled in `.claude/enabled.yaml` **and** `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is present in
  the composed `.claude/settings.json` — while it's off, `plugin doctor` prints it as the line
  "available (on disk, not enabled)". The flag is read only at **session start**: if you have just enabled it —
  restart, otherwise check (2) will fail on a correctly configured repository;
  (2) the transport is visible in your tool list: you have `ListAgents` and after spawning
  it prints the participants by name, `SendMessage` addresses them by name. The probe is observing your own
  list, not checking the docs and not spawning just to spawn. **`TaskCreate` is not fit for this
  check:** in CC 2.1.222 it is the shared task-list tool, it's absent regardless of the
  engine, and checking against it answers "no" on a correctly configured repository (a live run
  2026-09-05). From the same source, a fact worth knowing in advance: **there is no shared task
  list or `TaskCompleted` event in this build** — the task gate is held by `reviewer`, not a hook. Both "yes" →
  control passes to the `/dev:team` protocol (its §0 — the remaining preconditions, §4 — briefs,
  §5 — tasks and gates); stages §2–§7 are the same, only the handoff transport changes. Any "no" →
  **say out loud which check failed, and continue on subagents** — don't fake a team.
- **`--workflow` — 0-token orchestration by script.** The RED → GREEN → Review stages are driven
  by the deterministic `dev-pipeline` script, not you: branching, fan-out and the budget ceiling are in code,
  not in reasoning. The threshold, invocation, observation and mandatory merge-back are in the section
  "Transport `--workflow`" below; not duplicated here. Launch — **only on the owner's explicit
  word** (opt-in); a flag in the command counts as that word, a guess that "a Workflow would be
  handy here" does not.

### 2. Implementation (Contract-first TDD: interface → red → green → refactor)

**Baseline (before changes).** Once, before the first code change (before 2-INTERFACE / S2 Contract):
`uv run --no-project python scripts/capture_baseline.py` → `.sentrux/baseline.json` (coverage% + optional sentrux snapshot).
This is a precondition for the S7 delta: without a baseline, integrator (§7) works in advisory mode — the S7 gate does not block.

For every Task X.Y from the plan — **the order is mandatory**. Branch by the `Module contract:` field from the spec:

**The brief for every executor (RED, GREEN, REFACTOR) — follows the form
`.claude/plugins/dev/templates/executor-brief.md`:** DESIGN from the lead, FILES (allowed files),
REDS ≤ 10, the first edit within the first 5 calls, TESTS — the task's radius in the foreground. Nothing to fill
DESIGN with → `investigator` first, or a decision from the lead. Observation — `scripts/agent_report.py --live`,
not a dialogue (Д45). The GREEN brief for part N+1 is written from the report/handoff of part N, not from the plan. <!-- lint-language: allow -->

| Module contract | Stage 2 |
|---|---|
| `new-full` / `new-lite` | **2-INTERFACE → 2-RED → 2-GREEN → 2-REFACTOR** |
| `public-api-change` | **2-INTERFACE (amendment) → 2-RED → 2-GREEN → 2-REFACTOR** |
| `impl-only` / `n/a` | **2-RED+GREEN by one developer → 2-REFACTOR** (interface untouched) |

**Chain by size (Д47).** A separate tester for 2-RED — only for `new-*`, `public-api-change` <!-- lint-language: allow -->
and an unclear contract. A review fix, a change to an existing module, wiring (`impl-only` / `n/a`) —
**one developer**: reds in the brief (REDS), the red run before touching `src` pasted into the report,
break-injection is mandatory. With the lead's line-by-line design, a tester → developer pair cost 210–237k per
piece, one developer — 92–105k at the same quality; tests that don't catch a mutation passed both forms —
mutation testing catches them (a reviewer or a separate tester brief for the batch), not a second executor.

**Why this order** (not bureaucracy): without a formal contract-in-code, the test relies on a retelling of the spec — the implementation and the test diverge because everyone interprets the spec their own way. With interface.py in the code, tester and developer share **common ground truth** (Protocol + Pre/Post). Without RED-first, the implementer agent fits tests to broken code — Pocock: "the model writes code with a bug → writes a test confirming this wrong behavior → fits the test to its own broken code. This is an **algorithmic optimization**, not malice." Contract-in-code + RED-first = double structural protection.

**2-INTERFACE — the formal contract FIRST** (only for `new-*` / `public-api-change`).
Launch **developer** (Sonnet) or **teamlead** (Opus, if Senior+) with the `module-contract` skill active:
- Creates `interface.py` (full) or a module docstring (lite) with `Protocol`/`ABC` + DbC: `Pre:`/`Post:`/`Invariants:` for every public function
- Module README: Purpose / Public API / Boundaries / Stability — **without** Usage examples at this step (examples = contract tests from 2-RED, not duplicated)
- No implementation yet — `_impl/` is empty or contains only `raise NotImplementedError`
- Commit: `feat(<scope>): interface for Task X.Y` + `Refs: plans/<slug>.md`. Layer: `interface` (if in commit-layers.txt).
- **callable gate S2 contract-complete** — a deterministic check of contract completeness before 2-RED:
  `uv run --no-project python scripts/s2_gate.py --interface <path/to/interface.py>`.
  `VERDICT: PASS` (exit 0) → every public function (name not starting with `_`) has `Pre:` and `Post:` in the docstring → proceed to 2-RED.
  `VERDICT: BLOCK` (exit 1) → functions without Pre/Post are listed → send developer/teamlead back to complete the contract, **do not** go into 2-RED on a leaky contract.
  A non-standard docstring format (non-ASCII, multi-line Pre/Post) the parser doesn't classify → escalate to the **ai-judge** agent (semantic check). callable gate — invoked manually; enforcement in git pre-commit/CI — Phase 2.

**2-RED — tester writes a failing test from the contract.**
Launch the **tester** agent (Sonnet) in `MODE: red` (pass it through the header of the first lines of the prompt — see `agents/tester.md` → "How the orchestrator passes parameters"):
- **In the shared tree, `run_in_background: false`** (Д45): the RED → GREEN chain is sequential, <!-- lint-language: allow -->
  there is no implementation yet per the step order — a worktree doesn't blind anything, and it costs a +19…28k tax
  of nested `CLAUDE.md` files per agent. Forbidden paths (`_impl/`) — in the brief. `isolation: "worktree"`
  only in Parallel mode (real fan-out, see below and `core/agents/_WORKTREE_PATTERN.md`).
- Pass: the path to `interface.py` (or the module docstring) from 2-INTERFACE + the acceptance criteria from the Task
- Tester reads **only** `interface.py` + Pre/Post in the docstring, **does not read** `_impl/`. If it's an impl-only Task (no 2-INTERFACE) — it reads the existing contract + the spec.
- Tester writes a minimal test for one Pre/Post line (one test = one assertion)
- Tester runs the test and **demonstrates** that it fails:
  - For `new-*`: `NotImplementedError` (from the stub in `_impl/`) or `AttributeError` (if there's no impl yet)
  - For `public-api-change`/`impl-only`: `AssertionError` showing wrong output
  - Not acceptable: `ImportError` / `SyntaxError` (setup is broken, fix the test setup)
- If the test passes → STOP. The test is wrong (it tests current behavior, not the desired one). Rewrite it.
- **callable gate RED-block (S3)** — a deterministic recheck of the RED state:
  `pytest <test> -v 2>&1 | tee /tmp/red_out.txt` → `uv run --no-project python scripts/red_gate.py --report /tmp/red_out.txt`.
  `VERDICT: PASS` → RED confirmed (FAILED + NotImplementedError/AssertionError) → proceed to 2-GREEN.
  `VERDICT: BLOCK` → the test is wrong (all-green) or setup is broken (ImportError/SyntaxError) → rewrite the test.
  (callable gate — invoked manually; enforcement in git pre-commit/CI — Phase 2.)
- After RED, tester commits itself (explicit paths): `test(<scope>): failing test for Task X.Y` +
  `Refs: plans/<slug>.md`. (In Parallel mode the test arrives via merge-back of its worktree.)

**2-GREEN — developer/teamlead writes the minimal implementation.**
- If the level is Senior/Senior+ → launch **teamlead** (Opus)
- If the level is Middle/Middle+ → launch **developer** (Sonnet)
- Pass: the path to `interface.py` + the path to the failing test (the agent **reads both**, doesn't guess the contract)
- The goal — **the minimal code in `_impl/` so the failing test passes and the Pre/Post from the interface are honored**. No over-engineering for future scenarios.
- The agent **does not edit** `interface.py` or the failing test. If the contract turns out to be wrong — that's a signal to redo the spec in the plan + go back to 2-INTERFACE, **not** to fit the test/impl to it.
- Commit: `feat(<scope>): impl for Task X.Y` + `Refs: plans/<slug>.md`. Update the status `[PENDING]` → `[DONE]`.

**2-REFACTOR (optional) — if 2-GREEN left obvious debt.**
- If the implementation is ugly but passes the test → `developer` cleans it up in the same context, tests stay green after every edit.
- The contract (`interface.py`) **is not touched** — that changes the public API, it must go through a `public-api-change` Task.
- Skip if the code is already clean.

### 3. Regression — tester runs the full suite

Launch the **tester** agent (Sonnet) in `MODE: regression` (pass it through the header of the first lines of the prompt):
- Goal: verify that 2b/2c **did not break neighboring code** (not Task acceptance — that's already green from 2a).
- Run: `pytest` the whole module/layer + relevant integration tests.
- **Live-smoke (the S5 gate before S6)** — green pytest ≠ the app starts. One "the app starts and responds" smoke scenario catches a class of bugs invisible to unit tests (an import cycle at startup, a broken entrypoint, a misconfigured env):
  - **CLI / has an entrypoint** → determine the **real** entry point and run it non-destructively (`--version`/`--help`): **first** `[project.scripts]` from `pyproject.toml` — `uv run <console-command> --version`, or `/core:infra:run-proto` (resolves the entrypoint itself from `[project.scripts]`/`make run`/`uv run python -m`); bare `uv run python -m <pkg>` — **only** if the package has `__main__.py` (otherwise it fails with "No module named `<pkg>.__main__`" for projects with a console-scripts entrypoint). Doesn't do real work.
  - **Web / GUI** → bring up the app, Playwright `navigate` + `screenshot` of the main screen (web) or qt-mcp `qt_screenshot` (GUI); check there's no fatal in the startup logs.
  - **Skip** if the project has no entrypoint or it's library-only → `uv run python -c "import <pkg>"` is enough. Note in the status "live-smoke: skipped (library-only)".
  - **Gate:** smoke FAIL → **STOP before step 4**: don't review a broken app — developer/teamlead fixes startup (the same 2-iterations→escalation loop as for a regression FAIL).
- If PASS (suite + live-smoke) → step 4 (review)
- If FAIL:
  - **Iteration 1 (FAIL)**: launch **debugger** (Sonnet) with the failing test and the stack → either debugger fixes it in scope, or it gives a diagnosis → `developer`/`teamlead` applies the fix → tester retries regression
  - **Iteration 2 (repeat FAIL)**: debugger + developer again → tester retry
  - **Iteration 3 (still FAIL)**: **STOP**, escalate to **teamlead** (Opus) — either the spec is inadequate or the architecture needs revisiting

### 4. Review
Launch the **reviewer** agent (Opus, `run_in_background: false` — the verdict is needed before step 5):
- Pass: `git diff main...HEAD` + the plan + acceptance criteria
- **reviewer runs, not reads** — reproduces the claimed tests and quotes the output;
  break-injection on every claimed property (revert the implementation → check the red set).
  A verdict without reproduction is advisory (see `agents/reviewer.md`).
- If APPROVED → step 5 (ship)
- If CHANGES REQUESTED:
  - **Iteration 1**: `developer`/`teamlead` applies the fixes → reviewer re-reviews
  - **Iteration 2** (last): `developer`/`teamlead` gets a final chance → reviewer
  - **Iteration 3**: **STOP**, escalate to **teamlead** (Opus) to revisit the spec or the architecture

**Model diversity (advisory).** Review is more valuable when the reviewer's errors **don't correlate**
with the implementer's errors: the same model weights tend to repeat the author's blind spot
("uncorrelated errors" — an independent reviewer catches what the author structurally cannot see).
The ideal is review by a model of a **different family/version** than the one that wrote the code.
- **Config (once it becomes possible):** `reviewer_model: claude-opus-4-9` in this file or
  `.claude/modes/_stack.md` → the orchestrator brings up reviewer on the specified model in S6.
- **Current status — advisory-only:** Claude Code is tied to the `claude-*` family, cross-vendor
  review is unavailable; for now pick the **most different available** configuration (the newest version
  of Opus / extended thinking for reviewer), even if the implementer used the same one. The
  `reviewer_model:` field records the intent for the future; in practice reviewer stays Opus.

### 7. Integration (S7)

> Runs after §4 Review, before Ship (conceptually: S6 Review → S7 Integration → Ship).
> **callable gate** — invoked manually from this file; TRUE enforcement (git pre-commit/CI) — Phase 2.

Launch the **integrator** agent (Opus, read-only):
- Pass: the list of changed files (`git diff --name-only main...HEAD`) + the path to `.sentrux/baseline.json`.
- Integrator creates `plans/YYYY-MM-DD_<slug>/integration.md` (with a machine-readable JSON block).
- Run the **callable gate**: `uv run --no-project python scripts/integration_gate.py --report plans/.../integration.md`
  - exit 0 (`VERDICT: PASS`) → proceed to §5 Documentation / §6 Ship.
  - exit 1 (`VERDICT: BLOCK`) → **STOP**. Return to `developer`/`teamlead` to remove the cause
    (a new dependency cycle / coverage-drop > 5% / god-node growth > 20%). The loop and its limit —
    `project-rules` §7, the single source for all stages (see `## Rules`).
- **Advisory-skip:** if integrator returned PASS marked "MCP unavailable" (or there is no
  `.sentrux/baseline.json` — Task 1.6 not done) → the pipeline continues, the log records
  "S7 advisory: no MCP data / no baseline — delta unavailable".

### 5. Documentation and diagrams (optional)
If the task touches the architecture:
- Regular documentation (docstrings, README) → **docs-writer** (Haiku)
- ADR / ARCHITECTURE.md / migration guide → **tech-writer** (Sonnet)
- **Diagrams are stale** (modules / dependencies / the public API changed) → `/core:infra:diagrams` (pyreverse + pydeps + optional mermaid) — regenerate from code, don't draw by hand
- **The feature's user-facing behavior changed** → sync the living spec: `/dev:spec:spec-sync` (spec-writer checks `docs/direction/` against the code)

### 6. Ship
Run `/dev:ship`:
- validate → tests → linter
- Show the final diff
- Propose a commit message in Conventional Commits + trailers format
  (`Why:`, `Layer:`, `Refs:` — **mandatory** if a plan file exists for the current branch, + optional `Risk:` / `Reversible:` / `Tested:` / `Rejected:`).
  Full guide: `.claude/COMMIT_GUIDE.md`. Validation: `scripts/validate_commit/validate_commit.py`.
- If every Task in the plan = [DONE] → propose closing the plan (Status: DONE, a separate `docs(plans): закрыть <slug>` commit) <!-- lint-language: allow -->
- Phase gates are **not cancelled** by the transport: the phase is closed → `cto` acceptance (S7); merge into `main` →
  the `cto` merge gate → the owner. Rows — [`team-protocol`](../skills/team-protocol/SKILL.md) §5.
- Ask for permission to push

## Failure-recovery graph

```
                  ┌─ new-* / public-api-change ─→ INTERFACE (Protocol+DbC) ─┐
plan → (developer)│                                                          │
                  └─ impl-only / n/a ───────────────────────────────────────→┴→ tester(RED) → impl(GREEN) → [refactor] → tester(regression)
                                                                                                                       ↓ PASS  ↓ FAIL
                                                                                                                       review  debugger → impl [fix] → tester (retry)
                                                                                                                                       ↓ FAIL (iteration 2)
                                                                                                                                       debugger → impl → tester
                                                                                                                                           ↓ FAIL (iteration 3)
                                                                                                                                           ESCALATE → teamlead (rethink)

review → [APPROVED] → integration (S7) → docs? → ship
review → [CHANGES] → impl → tester(regression) → review (iteration 2)
                ↓ CHANGES (iteration 3)
                ESCALATE → teamlead (rethink spec/architecture)

integration (S7) → integrator → integration_gate.py
                ↓ PASS                    ↓ BLOCK (new cycle / coverage-drop / god-node)
                docs? → ship              developer/teamlead [fix] → integration (retry)
                                                  ↓ BLOCK (iteration 3)
                                                  ESCALATE → teamlead
```

For `impl-only` / `n/a` the `tester(RED) → impl(GREEN)` nodes on the graph are one developer with REDS in the brief (Д47, §2). <!-- lint-language: allow -->

## Rules

- Between stages, show the user a brief status
- **Research (§0) is skipped** for trivial tasks (one file, no cross-module
  effects, < 1 day); **Intake is never skipped** — it's cheaper than any stage after it
- **callable gates (S2 contract-complete, S3 RED-block, S7 Integration)** are invoked manually from this
  file via `scripts/s2_gate.py` / `scripts/red_gate.py` / `scripts/integration_gate.py`;
  TRUE enforcement (git pre-commit/CI) — Phase 2
- **The iteration limit and the escalation ladder are not here.** One source: the `project-rules` skill §7
  (who writes to whom, the `ESCALATION -> <role>` format) and [`team-protocol`](../skills/team-protocol/SKILL.md)
  §4 (the lead is a mailman, not a substitute for the level above). §3/§4/§7 spell out only who does what
  on a given iteration of their own stage
- debugger is invoked automatically on the first FAIL from tester (don't wait for a manual /dev:debug)
- If the task is clearly Senior+ → go straight to teamlead for implementation (not developer)
- If it's an architectural change — reviewer checks that there's an entry in `DECISIONS.md` (or tech-writer was called)
- By default the stages are **sequential**; for a plan with independent Tasks — opt-in **Parallel mode** (see below)

## Token budget (observability, opt-in)

To measure the real cost of the pipeline (an honest "before/after", not an eyeballed estimate),
every stage can log tokens/tool-calls to `data/pipeline-metrics.jsonl`
(append-only, gitignored) via the opt-in Stop-hook `token-budget-meter.sh`.

**Enabling it** (NOT registered by default — it's a tool, not an always-on guard):
add to `.claude/settings.json` under `"hooks"`:
```json
"Stop": [
  { "hooks": [{ "type": "command",
                "command": "${CLAUDE_PLUGIN_ROOT}/hooks/token-budget-meter.sh",
                "timeout": 10 }] }
]
```
and around every stage export `PIPELINE_STAGE=S3` (S0…S7). The record per stage:
`{ts, session_id, stage, tokens_in, tokens_out, tool_calls}`.

**Hard-stop rule.** Set the stage budget via `PIPELINE_STAGE_BUDGET=<tokens>`.
If `tokens_in + tokens_out > budget` — the hook writes a warning to stderr (a Stop-hook cannot
block the event). The orchestrator, upon seeing a breach (a warning or a jsonl record above
the threshold), **MUST stop the stage** before moving to the next one and **escalate to
teamlead** (the stage went over budget → a loop/drift is likely; don't keep burning tokens).
This is the same discipline as smart-zone (see `CLAUDE.md` → Behavioral additions): the budget is a
preemptive gate, not a retrospective one.

## Parallel mode (optional) — fan-out over independent Tasks

> Turn on **only** when the plan contains independent Tasks (the `Dependencies:` field from manager
> is empty, `Files:` don't overlap) and a large plan needs to be sped up. By default
> `/dev:pipeline` is sequential; parallel mode is opt-in, its risks are real.

**Mechanism — native subagent isolation, NOT a session-worktree.**
Fan-out is done via `Agent(isolation: "worktree")` on the **writing** agents (developer,
tester), launched with several Agent calls in one message. The isolation contract,
lifecycle, the difference from `EnterWorktree`/`ExitWorktree`, the base, who commits, merge-back, cleanup,
the writer cap — single source
[`core/agents/_WORKTREE_PATTERN.md`](../../core/agents/_WORKTREE_PATTERN.md); not
repeated here.

**Who is in a worktree, who isn't:**
- **developer + tester** (write files and commit) → each in its own `isolation: "worktree"`.
- **reviewer** (read-only, doesn't commit) → a worktree is NOT needed; reviewers for different Tasks can
  run in parallel without isolation (they only read the committed diff, they don't race each other for files).

**Flow:**
1. **Independence gate.** Take Tasks without `Dependencies:` and with non-overlapping `Files:`.
   Dependent / overlapping by files → sequential (otherwise merge conflicts). `Dependencies:`
   is optional → when it's absent AND files might overlap, **sequential by
   default** (the field's absence ≠ proof of independence).
2. **Pre-flight (base-ref).** Set `worktree.baseRef=head` — otherwise the worktree won't see
   feature-branch commits not yet merged into default, and tests will run against stale code.
   The detail and why pushing to `origin/<feature>` doesn't fix it — _WORKTREE_PATTERN.md (the
   transport table, the Subagents row). Can't set it → **sequential**.
3. **Fan-out.** For every independent Task — developer+tester in `isolation:"worktree"` (the
   2-RED→2-GREEN stages as in §2), with parallel Agent calls. Limit concurrency with the writer cap
   from _WORKTREE_PATTERN.md (see Caps below). ⚠️ Before trusting any test run in a
   worktree — the venv trap and the mandatory prompt line for it are in _WORKTREE_PATTERN.md.
4. **Merge-back → cleanup.** Lifecycle create→work→commit→merge-back→cleanup — see
   _WORKTREE_PATTERN.md.
5. **Review.** After merge-back — reviewer on every Task (§4), can run in parallel (read-only).

**Caps.** The loop cap — one source, the `project-rules` skill §7; not repeated here, and
no second one is introduced. The writer cap for parallel worktrees — also a single source,
_WORKTREE_PATTERN.md; no separate number is kept here. Escalate to **teamlead** on a
merge-back conflict / an orphaned worktree (cleanup commands — in _WORKTREE_PATTERN.md; the loop cap
covers only test-fail / review loops, not worktree failures).

**Hook races (worktrees share a common `.git/hooks`):**
- **qex post-commit reindex** — the hook itself detects a linked worktree and doesn't reindex from it;
  nothing needs to be disabled manually anymore (`_WORKTREE_PATTERN.md` → "Shared .git/hooks").
- **session-log pre-commit hook** stages `docs/sessions/<today>.md` into every commit — that's by
  design, not a race: `docs/sessions/*.md merge=union` in `.gitattributes` resolves the append-only
  journal on merge-back without a conflict.

## Transport `--workflow` — the `dev-pipeline` script

> **Opt-in.** Workflow runs only when the owner said so explicitly (the `--workflow` flag in
> the command counts as saying so). A "suitable-looking" plan by itself is not grounds for it.

**When to use it.** ≥3 independent Tasks from one approved plan: the `Dependencies:` field is empty,
`Files:` don't overlap (the same independence gate as in Parallel mode above). Fewer than three,
dependent, or overlapping by files — subagents; the script's payoff is in the fan-out, and on a single
task it only adds a layer.

**How to invoke it.** **You** read the plan — the script has no filesystem access and receives
the work as a list:

```
Workflow name: dev-pipeline
args: {
  "plan": "plans/YYYY-MM-DD_<slug>.md",
  "tasks": [
    {"id": "3.1", "level": "Middle+", "files": ["src/a.py"], "acceptance": ["...", "..."]},
    {"id": "3.2", "level": "Senior+", "files": ["src/b.py"], "acceptance": ["..."]}
  ]
}
```

Pass `args` as a real JSON value, not a string containing JSON. `level` selects
the GREEN executor (`Senior+` → `teamlead`, otherwise `developer`), `acceptance` goes into the
reviewer's prompt — don't pass criteria and you'll get a "by feel" verdict.

**Observation.** `/workflows` — live progress by stage (RED / GREEN / Review), tokens spent
and pause/stop. The script holds the budget ceiling itself: less than 50k left — the task doesn't
start the next stage, and is logged as dropped. The cost of orchestration is 0 model
tokens: the branching is in code.

**What comes back.** `{plan, results, branches, dropped}`:
- `results[]` — for every Task: `id`, `implementer`, `branches`, `dropped`, and the stage outputs
  (`red.failing_output`, `green.left_open`, `review.verdict` / `findings[{input, observed}]` /
  `injections[{property, predicted_red, observed_red}]`).
- `branches` — **the list of branches for merge-back**, the main return field (see below).
- `dropped` — what fell out and at which stage; an empty array ≠ "everything passed", check the length of
  `results` against the list of Tasks you sent.

**`null` in an agent's output.** `agent()` returns `null` if the user skipped the participant
or it died on a terminal API error after retries. The script turns this into a `dropped` record
and does **not** proceed further on that Task — the stages after it were not executed. Reaction: look at `dropped`,
finish that Task the usual way (§2 on subagents) or restart just it. Silently treating
a skipped Task as done is not allowed.

**Merge-back is mandatory — otherwise there's no work.** Each agent commits in its own worktree and
returns the branch name; the branches are in `branches`. After the script returns:
1. Merge **sequentially, one at a time**: `git merge --no-ff <branch>` — and `git show --stat` on
   every merged commit. Only you merge; a parallel merge of two branches is the source of that exact
   race the isolation existed to prevent.
2. After all branches — regression on the full suite: `/dev:test` (or `uv run pytest -q`). Green
   individual worktrees ≠ a green build after merging.
3. Worktree and branch cleanup — per `_WORKTREE_PATTERN.md` (the same place has the commands for an orphaned
   worktree and for the Windows "directory in use by another process" case).
4. **A merge conflict → escalate to `teamlead`, not a workflow re-run.** A re-run
   doesn't resolve the conflict: it will spawn a second branch with the same divergence.

**Interruption and resumption.** A run is stopped (pause/stop, a crash, a script edit) →
`Workflow({scriptPath, resumeFromRunId})` with the `runId` from the previous run's result: the unchanged
prefix of `agent()` calls is served from cache instantly, the first changed or
new call and everything after it run live. The same script + the same `args` = a 100% cache hit. That's why the
script has no `Date.now()` / `Math.random()` — non-determinism is exactly what breaks resume. Before
explaining an empty result, read `journal.jsonl` in the transcript directory: it records the
actual return value of every agent.

Task (optionally with a transport flag `--team` / `--workflow`; parsing — §1′): $ARGUMENTS
