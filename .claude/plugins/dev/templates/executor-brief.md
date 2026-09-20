# Executor brief — the form the lead fills before spawning a writer

**One brief = one decision = one agent.** The lead fills every field below before the
`Agent` call (subagent), the teammate spawn (`/dev:team`, wrapped by
`agent-teams/templates/team-brief.md`) or the Workflow step. A field the lead cannot fill
is a finding about the task, not about the form — see "When you cannot fill DESIGN".
Transport wrappers add their own lines (peers, worktree path); they never restate these.

Checked before the spawn by dev/hooks/lint-brief.sh (DESIGN >= 3 lines, FILES <= brief_max_files,
REDS <= 10 or n/a, REPORT present); 'BRIEF-OVERRIDE: <reason>' lets a justified exception through.

**Why these fields** (Task 4.1, 2026-09-16, five runs measured from subagent transcripts —
Д45): two briefs without a design burned 181k / 175k tokens and shipped zero code; the brief
that carried the lead's design and six files finished at 167k with 17 reds green. One task,
one model, the same day: a code map with free reconnaissance — 207k, 60 calls, nothing
written; two allowed files — 98k, 25 calls, done. The lead's reply to a running agent cost
5.5k and changed nothing. Peak context ≈ start + worktree tax + 30k + 4k per red test, so
ten reds is the cap that keeps a run under the soft budget.

```
TASK: <X.Y> — <one sentence>                 PLAN: <plans/…/phase-N.md>
ROLE: <developer | teamlead | tester | junior | debugger>
  (a separate tester RED run only for a new module or an unclear contract; a review fix, a change
   to an existing module or wiring is one developer with REDS below — Д47)
CHAIN: <who produced your input> -> you -> <who consumes your output>

DESIGN (decided by the lead — you type it, you do not derive it):
  <3–6 sentences: which function / class, which call site, what must NOT change,
   which existing helper to reuse. Name symbols and line ranges, not topics.>

FILES (complete list — nothing else; need another file -> stop and ask the lead):
  1. <path> — <what changes there>
  2. <path> — <…>

REDS (predicted red tests, <= 10, `path::test_name`; "n/a — <why>" for docs / config):
  - tests/<…>::test_<…>

ACCEPTANCE: numbers the lead will check by running <command>

FIRST EDIT: within your first 5 tool calls. Do not re-derive DESIGN; do not open files
  outside FILES. Before your first edit under src/, send ONE message upward (<= 300 tokens,
  do not wait for an answer):  DESIGN: <3 lines> / FILES: <list> / starting edits

TESTS: <exact pytest command for the task radius>

TEST RULES: foreground, `timeout: 300000`, never in the background, never the full suite
  (the lead runs it at the merge point); tests/e2e only when the task is about e2e. In a
  worktree: `env -u VIRTUAL_ENV uv sync --extra dev` once, then `env -u VIRTUAL_ENV uv run …`;
  paste the preflight output before any test claim.

OUT OF SCOPE: <what not to touch, what not to "improve">
TRAPS: <1–3 lines from memory, the plan, or the previous agent's handoff>
HANDOFF IN: <docs/handoffs/<file>.md + SHA when continuing an unfinished run; else "none">

BUDGET: the hook's "Context checkpoint" message (start + 100k, repeated every +50k) is a
  decision, not a stop: commit what already works; a clear remainder under ~30 tool calls →
  finish the task (no handoff); more left or going in circles → write
  docs/handoffs/<YYYY-MM-DD>_task-<X.Y>-<role>.md (done / left / next step / files / SHA —
  enough to resume within ~5 calls) and report. Judge by calls left, not by the share of the task. Below it, no handoff file. A hard budget exists only if the lead set one — then
  only git add|commit|status|diff|log|show, the handoff file and the report tool remain.

COMMIT: commit — Why:/Refs: trailers (Why: on ONE line), stage explicit paths; a task file
  may override with "do not commit".
  Never push, never a PR, never `git add -A`.

REPORT (final message, <= 25 lines): FIRST LINE 'STATUS: DONE | DONE_WITH_CONCERNS | NEEDS_CONTEXT | BLOCKED';
  outcome; every acceptance number from the command that produced it; files touched;
  "What I interpreted rather than followed"; "What I left open / unreliable" (non-empty).
  Put the FULL report (command outputs, reasoning) in
  docs/reviews/<YYYY-MM-DD>_task-<X.Y>-<role>.md and name that path - the lead's context
  is the most expensive one.
```

`python3 scripts/plans_ledger.py brief <id>` prints this form filled from `tasks/<id>.md` plus
the standing blocks (FIRST EDIT, TEST RULES, BUDGET, COMMIT, REPORT) and the per-model line for
ROLE — edit the task file, not the brief.

## When you cannot fill DESIGN

Then this is a design task, not a writing task. Send `investigator` (read-only; returns the
call sites and a recommendation) or decide it yourself from the code — only then brief a
writer. A writer briefed without DESIGN spends its whole budget deriving it and ships nothing.

## When REDS exceeds ten

Split by decision, not by file, so that each part ends green on its own (the pre-report gate
blocks a writing role with red tests; a "RED only" brief goes to `tester`). The GREEN brief
for part N+1 is written from part N's report or handoff, never from the plan alone.

## While the agent runs — watch, do not talk (Д45)

`uv run --no-project python scripts/agent_report.py --live` (this repo; elsewhere read the tail of the agent's
transcript) prints context, tool calls, edits in `src|tests`, commits, last tool, idle seconds
and a verdict per agent. Three rules, no conversation:

- **zero edits in FILES at start + 40k** → stop; rewrite the brief with a real DESIGN;
- **no transcript line for 300 s** → stop; the run waits on something it cannot see
  (a backgrounded test, a permission prompt);
- **above the soft budget** → the agent decides (Д48): it commits, then finishes or hands off;
  wait, and brief a fresh agent only from its handoff. Measured on 93 transcripts (fresh-context
  check): a handoff breaks even after 15–80 remaining calls (most likely 25–50; median tail past the
  mark is 30), so a forced cut-off gains nothing in the median case. Savings barely move with the
  threshold but change ~3× with how fast the fresh agent resumes — the handoff's quality is the lever.

A task that genuinely needs more context gets it from the lead, not from the agent: write
`.claude/logs/agents/<agent_id>.budget` (`soft=250000`, or `hard=160000` to cap a runaway) —
the hook reads it on the agent's next tool call.

## Per-model line — append one to the brief

- **Sonnet** (`developer`, `tester`, `debugger`, `tech-writer`): literal and precise — name
  every call site and every file; task, intent and constraints up front in one message. For
  finding-type work: "report every issue, including uncertain and low-severity ones".
- **Opus** (`teamlead`, `reviewer`, `investigator`, `manager`): drop "double-check" lines — it
  over-verifies when told to; constrain scope, cap delegation ("no subagents for work you can
  finish in a handful of calls"), ask for concise output explicitly.
- **Haiku** (`junior`, `docs-writer`): numbered steps, exact anchors and file lists, one
  verification command, a fixed report shape; anything unwritten comes back as a question.
- **Fable** (`cto`): say which progress text you want between tool calls; "first privately list
  what you need next, then request everything independent in one response"; it finishes long
  tasks unattended — never ask it to wait for permission on work already requested.
