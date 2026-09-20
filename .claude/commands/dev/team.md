---
description: Live agent team for one plan phase — PM intake, Task X.Y, teammates that persist in the session and talk to each other, hooks as gates, the lead as the only merger
disable-model-invocation: true
---

Start a **live team** on a plan phase or on one task: agents are created once, live until
the end of the session, pick up tasks from a shared list, message each other by name and
hand results back to you. You are the lead, in the PM role: you frame, assign, watch, inject
(faults) and consolidate. You don't write code by hand.

Mechanism — Agent Teams, plugin `agent-teams` (default-off). Full breakdown, hotkeys,
cost and traps — `.claude/plugins/agent-teams/README.md`. Entry from `/dev:pipeline --team` —
lands here too: different transport, same stages and gates.

## 0. Preconditions — 30 seconds, don't skip

1. Plugin `agent-teams` is enabled in `.claude/enabled.yaml` **and** the variable
   `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` is in the composed `.claude/settings.json`
   (`claude-kit-claude plugin doctor .` will show the mismatch). If not — enable it
   and restart the session: the environment variable is only picked up
   at startup. Enable it by **editing `enabled.yaml` by hand** + `plugin sync .` —
   `plugin enable` strips the file's comments (trap documented in the plugin's README).
2. Transport is available — one check, and it's in `/dev:pipeline` §1′ (`commands/pipeline.md`):
   `ListAgents` exists for you and prints participants by name, `SendMessage` addresses them. **Not
   `TaskCreate`:** it belongs to the shared task list, which doesn't exist in CC 2.1.222, and gives a
   false "no" (live run 2026-09-05). Teammates spawn in-process; this version has no separate
   commands to create and destroy the team — don't expect them, don't call them. Check fails —
   say so plainly and work on subagents; don't fake a team.
3. `git status` — no one else's uncommitted changes; `ListAgents` — no second session in this
   worktree. Branch — `<type>/<slug>`, not `main`.
4. Is Ollama alive (qex)? If not — agents fall back to `Grep`. Either way, name the index's
   age as a number in briefs: "index from such-and-such date, N days".

5. Say the price out loud: every participant is a full session, measured at ≈56k tokens of
   context before the first line of code (three `CLAUDE.md` + `MEMORY.md`) plus the work itself.
   Four participants — 100k at the start.

## 1. Intake — the PM role

Retell the owner's task in three blocks and show it to them **before** decomposition:
- **Goal** — one sentence.
- **Acceptance** — 3–6 checkable lines: input → expected output, a number, a file.
- **Out of scope** — what we don't touch.

At most two questions, and only where different readings produce materially different work.
Everything else — name it an assumption and move on.

## 2. Decomposition

- Task X.Y format from the global `CLAUDE.md`: Level, Assignee, Goal, Files, Steps, Acceptance,
  Out of scope.
- Four files or more, or an architectural change — `manager` writes the spec; otherwise you
  write it yourself.
- **Independence gate:** `Files:` don't overlap → tasks run in parallel; they overlap → chain
  via `Dependencies:`. A missing field doesn't prove independence.
- Level → executor: Senior+ → `teamlead`; Middle → `developer`; mechanical work with a
  ready-made diff → `junior`.

## 3. Roster — minimal

Role ↔ agent ↔ model — registry `.claude/plugins/dev/modes/dev.md`; who the lead, `cto` and
`manager` are and what they don't do — skill [`team-protocol`](../skills/team-protocol/SKILL.md) §2;
executor by task level — §2 above. Here, only what gets decided when assembling the team:

- Always: you (lead/PM) and `reviewer` — synchronously after every task.
- `tester` — **once per mechanism, before implementation**, in a worktree on a pre-impl commit.
- `debugger` — on a FAIL from the tester. `cto` — phase acceptance, merge gate, `teamlead` ↔
  `reviewer` dispute; **not** per task.
- `teamlead` — when you expect escalations (why exactly — `team-protocol` §4).

Don't spawn "just in case": an idle participant costs the same as a busy one.

## 4. Spawn and briefs

1. Spawn participants one at a time. Each gets a brief: the transport wrapper
   `.claude/plugins/agent-teams/templates/team-brief.md` (role, peers, worktree) + the fields of
   `.claude/plugins/dev/templates/executor-brief.md` (DESIGN from the lead, FILES, REDS ≤ 10, first
   edit within the first 5 calls, TESTS radius, BUDGET, REPORT; also notes per model).
   In English. Nothing to fill DESIGN with → `investigator` first, or a lead decision.
2. **Writers** (`developer`, `teamlead`, `tester`, `junior`) — each gets their own worktree from
   the current HEAD, **next to the repo, not under it**:
   `git worktree add ../<repo>--team-<task> -b <type>/<slug>-<task>` (under `.claude/worktrees/`
   the first read costs +19…28k in nested `CLAUDE.md` tax — Д45). Two or more writers at <!-- lint-language: allow -->
   once — otherwise a shared tree (`team-protocol` §6, mode A).
   Creation/base/venv trap/how to check tests see your code — single source of truth
   `core/agents/_WORKTREE_PATTERN.md` (the "Live team" row in the transport table); the
   participant prints that check's result in their report before claiming a test result.
3. Readers (`reviewer`, `cto`, `investigator`) — in the shared tree, don't change files.
4. Writer cap — single source, `core/agents/_WORKTREE_PATTERN.md`; we don't keep our own number
   here.

## 5. Tasks

- **CC 2.1.222 has no shared task list** (`TaskCreate` and `Ctrl+T` don't exist — live run
  2026-09-05), and with it no `TaskCompleted` event: the task gate is held by `reviewer`, not a
  hook. Until they exist, everything below is about the **brief**: the participant gets the task
  and its prefix as text.
- `TaskCreate` for every Task X.Y; `Dependencies:` from the spec → task dependency.
- Spec fields carry over verbatim, not paraphrased: a `Handoff:` line from the plan goes
  into the task description as-is (the participant uses it to know who to ask and who to
  hand off to), `Gate:` — into the title prefix (`[RED]` / `[docs]` / `[skip-gate]`).
- The tester's task title starts with `[RED]`: the `TaskCompleted` hook doesn't run pytest on
  it (a red set is the spec, not a defect). `[docs]` / `[skip-gate]` — same for documentation and
  for when the gate would block someone else's file.
- Assign explicitly. Self-claiming saves you a turn but breaks the "tester before code" order.

## 6. Observation — what to watch and where to click

| What | How |
|---|---|
| Task list and who took what | `Ctrl+T` — **no list in 2.1.222** — check the roster with `ListAgents` |
| A participant's transcript, message them | `↑`/`↓` to select → `Enter`; `Esc` back; `x` to stop |
| Everything running in the session | `/tasks` |
| Log of every agent's starts and finishes | `data/agent-journal.jsonl` (hooks `SubagentStart/Stop`, plugin `observability`) |
| Gates | `TaskCompleted` → ruff + pytest on changed tests; `TeammateIdle` → nothing uncommitted in the worktree. Two blocks in a row → skip with a warning (two-iteration cap). Turn off: `TEAM_GATES=off` |

While work is delegated, you don't write code. Exception — something trivial (under 30 lines, one
file), and say so out loud.

## 7. Injections — you only

After every mechanism: predict the set → revert each guarantee one at a time → the fact.
Against both test sets, the author's and the tester's. Not delegated. Record it, if the project
keeps an injection log (format and path — per project convention).

## 8. Review and escalation — questions go up a level, like in a company

- `reviewer` after every task, synchronously (`run_in_background: false` if via Agent);
  a finding is an input → observable output.
- Two iterations per loop; on the third — one level up. One chain for everyone, recorded once in
  skill `project-rules` §7 (not duplicated here), agents know it.
- In the team, a participant writes to the level above by name (`SendMessage`), if that role is
  in the team; otherwise — to you, in the same text, and you spawn the needed role. Message
  format is fixed:
  `ESCALATION -> <role>` / Question / Tried / Blocked on / Files. One level at a time: a junior
  doesn't write to the tech director.
- Your job on escalation is not to answer in place of the role above, but to make sure the
  question got through and the answer came back to whoever asked. You answer yourself only
  what the owner decides (and then you ask the owner first). A question that outlives the task
  (needs access, an owner decision, a live rig) — record it in the session log
  (`docs/sessions/<today>.md` → Open questions), not only in chat.
- `cto` — at phase acceptance (three lenses), at the merge gate, and on questions from
  `teamlead`/`reviewer`. Not on lower-level tasks.

## 9. Merge-back and shutdown

1. **You** merge worktree branches: one at a time, `git show --stat` on every commit — the diff
   must match the message. Merge-back and cleanup, including an orphaned worktree — escalate,
   don't silently delete — single source `core/agents/_WORKTREE_PATTERN.md`.
2. Ask participants to stop and wait for them. The team lives until the end of the session;
   `/resume` won't bring it back.
3. Report to the owner: what's done, what's open, what's unreliable in your own work. Memory —
   via `/core:memory:remember`, if the WHEN-gate fired.

Task or phase: $ARGUMENTS
