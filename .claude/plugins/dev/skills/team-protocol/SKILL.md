---
name: team-protocol
description: >
  One protocol on three transports — stages S0–S8, roles, handoff chains,
  escalation, gates, sandbox modes and the MCP regulation by operation class.
  Triggers: "team", "pipeline", "handoff", "escalation", "which transport",
  running a phase with more than one agent.
---

# Team protocol — one protocol, three transports

Stages, roles, chains, gates, sandbox and MCP rules are written **here once**;
`/dev:pipeline`, `/dev:team` and Workflow are three ways to execute them (§8),
not three methodologies. Preloaded for `manager` and `cto`. Teammates **do**
inherit `skills:` — observed live 2026-09-05 on CC 2.1.222; still name the chain
in the brief: `Handoff:` is per-task and no preload carries it.

## 1. Stages S0–S8

| # | Stage | Who | Out | Gate |
|---|---|---|---|---|
| S0 | Intake | lead ↔ owner | goal, 3–6 acceptance lines, out-of-scope; ≤ 2 questions | owner confirms the wording |
| S1 | Plan | `manager` (4+ files), else lead | `plans/<date>_<slug>.md` with Task X.Y | frontmatter complete |
| S1′ | Plan review | `reviewer` in `MODE: plan` | checklist verdict | **owner** approves → branch + plan commit |
| S2 | Team assembly | lead | transport §8, sandbox mode §6, briefs, worktrees | clean tree; no second session in it; branch ≠ `main` |
| S3 | Execute by chains | roles on `Handoff` | a commit per Task | §5; 2 iterations → `teamlead` |
| S4 | Injections | lead, never delegated | predicted red set vs the fact | recorded in the plan |
| S5 | Regression + live smoke | `tester` | full suite green, the app starts | FAIL → debugger loop |
| S6 | Integration | `integrator` | dsm-delta, coverage, god nodes | `integration_gate.py` |
| S7 | Phase acceptance | `cto` | ACCEPT / WITH CONDITIONS / BLOCK | three lenses, reproduction |
| S8 | Merge-back and close | lead → `cto` → owner | branches merged, plan DONE, session log, team stopped | push only on the owner's word |

## 2. Roles

| In a company | Here | Does | Never |
|---|---|---|---|
| PM **and** department head | **lead** — the main session | intake, approval, spawn, assign, watch, inject, merge, report | writes code — except the Threshold Rule (1–3 files, < 80 lines, said out loud) |
| Technical director | `cto` | phase acceptance, merge gate, arbitration, ADR-level calls | tasks, code, review by reading; **once per phase, never per task** |
| Project manager / analyst | `manager` | decomposition into Task X.Y with `Level`, `Files`, `Dependencies`, `Handoff`, `Gate` | spawning, git, code — it thinks, the lead executes |

There is no separate dispatcher agent: only the lead may own a team and its task
list, only the lead has the conversation with the owner, and one more Opus hop per
message buys nothing. Full role ↔ agent roster: `.claude/plugins/dev/modes/dev.md`.

## 3. Handoff chains

`Handoff:` in a Task is data, not improvisation — an ordered "who → whom → what".

| Task type | Chain |
|---|---|
| New module / public API | `developer`(INTERFACE) → `tester`(RED) → `developer`\|`teamlead`(GREEN) → `reviewer` |
| Unclear contract | `tester`(RED) → `developer`(GREEN) → `reviewer` |
| impl-only / bugfix / review fix / wiring, design by the lead | `developer`(REDS in the brief: red run before the `src` edit, break-injection) → `reviewer` |
| Mechanical, diff already written | `junior` → `developer`(check, commit) |
| Documentation | `docs-writer`\|`tech-writer` → `reviewer`(express) |
| Regression FAIL | `tester`(FAIL) → `debugger` → `developer` → `tester`(retry); 2 iterations → `teamlead` |
| Cross-module defect | `investigator`(diagnosis) → `teamlead` → `reviewer` |

Chain by size (Д47): with the lead's line-by-line design a `tester` → `developer` pair cost
210–237k per piece, one `developer` writing the reds first 92–105k at the same quality. Tests that
miss a mutation got past both forms — a mutation check (reviewer, or a separate `tester` brief per
batch) finds them, a second writer does not.

Questions go **along the chain only**: the consumer asks the producer by name; anything else
goes up the ladder (§4), never sideways. Writer roles (`developer`, `tester`, `junior`,
`debugger`) do not preload this skill — the brief's `Handoff:` line is their only channel for it.

**The pre-report gate is mechanics, not a review step.** A writer role finishes only on a green
`pre_report_gate.py` (`pre_report_gate = on` in `_stack.md`) — exec bit, contract-lite, ruff and
the configured tests. The reviewer is handed the gate's green output and does **not** re-check
those four classes; their context goes to semantics and injected defects. Fix cycle after a
review: `reviewer -> developer`(batch of ≤ 5 findings)`-> reviewer`(express).

**The brief is a form, not prose — `dev/templates/executor-brief.md`.** Mandatory fields:
DESIGN decided by the lead (which function, which call site, what must not change), FILES as a
numbered list of allowed paths ("need another file → stop and ask"), REDS ≤ 10 predicted red
tests, FIRST EDIT within the first 5 tool calls, TESTS as the task radius in the foreground,
BUDGET (soft / hard), REPORT shape. Cannot fill DESIGN → `investigator` or the lead decides
first; more than ten reds → split by decision. Measured (2026-09-15, Task 2.7): a code map with
free reconnaissance — 207k tokens, 60 calls, **zero files written**; two allowed files — 98k,
25 calls, done. (2026-09-16, Task 4.1): two briefs without a design — 181k / 175k, zero code;
the lead's design in the brief — 167k, 17 reds green. The lead watches the transcript
(`agent_report.py --live`, three stop rules in the form) and does not talk to the agent.

## 4. Escalation

The ladder is `project-rules` §7 unchanged — `junior`/`docs-writer` →
`developer`/`tech-writer` → `teamlead` → `cto` → owner, in the `ESCALATION -> <role>`
format (question / tried / blocked on / files). Two protocol clarifications:

- **The lead is a postman, not a stand-in for the level above.** Its job is that the
  question arrived and the answer came back to whoever asked. It answers by itself
  only on what the owner decides — and then it asks the owner first.
- **A question that outlives the task** (needs the owner, a stand, an access) is a
  line in the "Open questions" section of `docs/sessions/<today>.md`. An unrecorded
  question is a lost question.

In a live team a teammate cannot spawn subagents: it escalates by `SendMessage` to
the role by name if that role is on the team, otherwise to the lead. Keep `teamlead`
on the team whenever you expect escalations.

## 5. Gates

| Gate | Who | Mechanism |
|---|---|---|
| Contract complete (S2) | script | `s2_gate.py`; an unusual docstring → `ai-judge` |
| RED confirmed (S3) | script | `red_gate.py` |
| Mutation probe on the diff (S5) | script | `mutation_gate.py`; survivors are killed by a test or named equivalent — adds to break-injection |
| Task closed (live team) | hook | `TaskCompleted`: ruff + pytest; 2 blocks → pass with a warning |
| Went idle with uncommitted work | hook | `TeammateIdle` in the worktree |
| Task review | `reviewer` | reproduction + break-injection; 2 iterations → `teamlead` |
| Integration (S6) | `integrator` + script | `integration_gate.py`; advisory without a baseline |
| Intake wording (S0) | **owner** | confirms goal / acceptance / out-of-scope before anything is built |
| Plan approved (S1′) | `reviewer` `MODE: plan` → **owner** | the plan checklist |
| Phase acceptance (S7) | `cto` | three lenses |
| Merge into `main` | `cto` → **owner** (push) | merge gate |

`TaskCreated` (reject a task with no `Handoff:`) is **reserved, backlog** — not an active gate.
Owner gates are the rows marked **owner** above; a command may add one of its own (`/dev:pipeline`
§0 has the owner pick the research approach). No count is given here on purpose: a number
restated in another file drifts from the list it counts — read the rows, not a total.

## 6. Sandbox

| Mode | Who is where | When |
|---|---|---|
| **A. One writer** | everyone in the shared tree, writers strictly sequential, readers in parallel | **default** — every sequential chain, RED → GREEN → review included; dependent tasks; ≤ 2 Task. Cheaper: no merge-back, no worktree tax |
| **B. Fan-out** | a worktree per writer, hand-made ones **beside the repo**; creation, base ref, writer cap, who merges — `core/agents/_WORKTREE_PATTERN.md` | two or more writers at once on disjoint `Files:`, when time beats tokens |

**Sequential is not fan-out.** Task 4.1 (2026-09-16) ran five agents strictly one after another,
each in its own worktree: the isolation blinded nothing (RED runs before GREEN exists by order)
and cost the nested-memory tax five times (+19…28k per agent on its first read), two lead
mistakes and the gate log — Д45 revoked "a worktree per writer" for sequential chains.

**A role that issues a verdict reviews a fixed SHA, never the working copy** — `git diff
<base>..<sha>`, `git show <sha>:<path>` — and the lead names that SHA in the brief. Mode A puts
readers and writers in one tree at once, so a reviewer reading files while the lead edits them
will attribute the lead's changes to whatever it just ran. That is not hypothetical: it produced
a false blocker on the Phase 3 gate of this very plan, where `git status` was dirty from the
lead's own command and the reviewer reported it as a test mutating tracked files.

Worktree creation, base ref per transport, who commits, merge-back (only the lead merges, one
branch at a time), cleanup, the venv false-green trap, and shared `.git/hooks` all live in one
place — `core/agents/_WORKTREE_PATTERN.md`; read it there, do not restate it.

**One agent = one task** (in mode B: one worktree). Do not keep a warm agent alive across tasks to save its startup context. Measured 2026-09-10 on four implementers: a single task drives an agent to a peak context of **287–371k**, with 96–99 % of its calls already above the ~100k degradation line; a second task would start there, not at zero. The billed quantity is context × number of calls (125 M cache-read tokens across those four), so a long agent is not cheaper — each of its steps costs more than the last. Subagent prompt caching is 5-minute, so an agent idle while the lead merges is not warm either. Re-entry is made cheap by the plan and by role memory (`memory:` in the agent's frontmatter), not by keeping the agent alive.

**Cap and cleanup.** ≤ 3 concurrent writers (see `core/agents/_WORKTREE_PATTERN.md`); the lead removes every worktree **and its branch** at the wave's merge point — the engine only cleans a worktree that stayed unchanged, so any agent that commits leaves one behind. Clean before the next wave starts, never "later".

**Two writers never sit on the same file in one wave.** Build the map from the tasks' `Files:` before spawning, not from their titles: on 2026-09-10 a by-topic split put two agents on one `check_injections.py` in the first wave that used the rule.

## 7. MCP regulation by operation class

| Class | Examples | Who | Where | Rule |
|---|---|---|---|---|
| **R** read / search | `qex:search_code`, `sentrux:dsm/health/scan/rescan`, `serena:find_*`, `codegraph:explore` | all | any tree | `scan`/`rescan` are computation, not state: `integrator`, `investigator` and the `sentrux-*` commands run them normally — one at a time, cache in `.sentrux/cache/` |
| **D** documentation | `context7:query-docs` | all | — | external libraries only; never stdlib or the core stack |
| **M** mutating edits | `serena:rename_symbol`, `replace_symbol_body`, `ast-grep:rewrite` | writer roles only | own worktree, or mode A | read-only roles are denied these by `disallowedTools` |
| **I** state, not computation | `qex:index_codebase`, `sentrux:session_start/session_end` (baseline), graphify build | **lead only** | **main tree only** | one at a time; the qex post-commit hook has no `git-common-dir` guard before Task 6.5, so in fan-out the lead disables it by hand (`/mcp-qex:install-reindex-hook` → "Worktree / lock race") |
| **X** external drivers | `playwright:*`, `qt-mcp:*`, `github:*` | `tester` / `reviewer` / `cto`, per task | shared tree | one application instance per session; GUI tests are never parallel |

- Fallback is mandatory: a server disabled in `enabled.yaml` → take the `Grep`/`Read`
  path your own role prompt names (`project-rules` §3).
- Ollama is one local embedding server — the lead caps concurrent qex searchers at 3.
- Grant notation is `mcp__server__tool` only; the colon form in `tools:` is dead.

## 8. Transport binding

| Transport | Gives | Does not give | Take it when |
|---|---|---|---|
| **Subagents** (`Agent` + `SendMessage`) | an agent that lives in the session and continues with its context; background by default; native `isolation: worktree` | agents do not see each other — every handoff passes through the lead | ≤ 2 Task, or dependent tasks; the default, works today |
| **Live team** (Agent Teams) | shared task list with dependencies, messaging by name, hook gates | experimental: does not survive `/resume`, one team per session, a teammate spawns no subagents, no shared task list on CC 2.1.222 (hence no `TaskCompleted` gate), permissions are shared | 3–8 Task where the consumer of a result must ask its producer (`tester` ↔ `developer`) |
| **Workflow** (JS script) | 0-token orchestration, output schemas, a budget ceiling, `resumeFromRunId` | no dialogue between agents | ≥ 3 independent **same-shaped** Task; only on the owner's explicit word |

Measured once on one workload, by session transcripts: subagents **1.0×**, live
team **1.2×**, workflow **2.0×**; the live team is slowest by wall clock and still
cheaper than the workflow. Transport and fan-out are confounded — each ran in its own
default shape, and the live-team run used **neither peer messaging nor hook gates**, so
its number is a floor, not the price of the full mode. Caveats: `agent-teams` README.

The thresholds do not overlap — choose by the count and the shape of the Task list,
not by taste. A live-team phase is one session, so a handoff note between phases is
mandatory.
