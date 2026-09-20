# agent-teams — a live team of agents (experimental, default-off)

A wrapper over the native Claude Code Agent Teams engine: teammates are not
one-off workers but full sessions that live until the phase's work is done,
pull tasks from a shared list, message each other by name, and are stopped by
gates, not by promises.

**The plugin itself carries no role.** It only provides the
`CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS` environment variable and two gate hooks
(`TaskCompleted`, `TeammateIdle`); the full roster (`developer`, `tester`,
`reviewer`, `cto`, …) lives in the `dev` plugin and works the same whether
this plugin is enabled or not.

Off by default. To enable it — **restart the session**: the environment
variable is only picked up at start. To turn it back off —
`plugin disable agent-teams .`, no traces left.

> **Tool trap.** `claude-kit-claude plugin enable agent-teams .` works, but it
> rewrites `.claude/enabled.yaml` from serialization: it wipes all comments in
> the file (including the description of its own schema) and flips it to
> CRLF. Until this is fixed, enable it by hand instead — add `agent-teams:` /
> `enabled: true` under `plugins:` — and call
> `claude-kit-claude plugin sync .`: it rebuilds `settings.json` and
> `.mcp.json` without touching `enabled.yaml`.

## Three mechanisms — which one when

The full table (what it gives, what it doesn't, the exact switch-over
threshold) — [`team-protocol` §8](../dev/skills/team-protocol/SKILL.md).

- **Subagents** — the default: a worker reports to the lead, backgrounded by
  default, they don't see each other.
- **Live team** (this plugin) — teammates see a shared task list and message
  each other by name; instead of hoping "the teammate will manage" — hooks.
- **Workflow** — a deterministic script for many same-shaped tasks, only on
  the owner's explicit word. The ready-made script is `dev-pipeline`
  (RED → GREEN → Review over independent Tasks); how to call it, what it
  returns, and the mandatory merge-back —
  [`../dev/commands/pipeline.md`](../dev/commands/pipeline.md) → "Transport
  `--workflow`".

## Roles and models

The full roster (14 roles) and the model per role — the "Team composition"
table in [`dev.md`](../dev/modes/dev.md). Model versions deliberately don't
go there: tiers (Opus / Sonnet / Haiku / Fable) don't go stale, versions do.

## How to launch

`/dev:team <phase|task>` runs the protocol from preconditions to merge-back.
The same protocol is available as `/dev:pipeline --team` — same stages,
different transport. Full text —
[`../dev/commands/team.md`](../dev/commands/team.md); here — the stages in
brief:

| Stage | What happens |
|---|---|
| 0 Preconditions | plugin and env flag enabled, tree clean, no second session in it |
| 1 Intake | goal + 3–6 acceptance lines + out of scope, ≤ 2 questions |
| 2 Decomposition | Task X.Y; overlapping `Files:` → chain, otherwise parallel |
| 3 Roster | only roles with a task — see the roster above |
| 4 Spawn and briefs | a worktree per writer from local HEAD, **beside the repo** (`../<repo>--team-<task>`); brief per the template below |
| 5 Tasks | `Handoff:`/`Gate:` from the plan — verbatim into the task's description and title |
| 6 Watch | see below |
| 7 Injections | lead only, never delegated |
| 8 Review and escalation | `reviewer` after every task; ladder — [`project-rules` §7](../dev/skills/project-rules/SKILL.md) |
| 9 Merge-back | the lead merges one branch at a time, `git show --stat` on each |

The teammate's brief — per the
[`templates/team-brief.md`](templates/team-brief.md) template: in English,
with a separate note per model tier.

## Watch

- `/tasks` — everything running in the session, with each teammate's
  transcript.
- `/usage` — token attribution by subagent and skill.
- `claude agents` (or `/agents`) — background sessions outside this one.
- `data/agent-journal.jsonl` — an append-only journal of starts and finishes,
  see the table below.

## Hooks and journal

| Hook | Blocks when | Safety valve |
|---|---|---|
| `TaskCompleted` → `hooks/team-task-completed-gate.sh` | a changed `.py` is red on `ruff check`, or a changed test file is red | 2 blocks on the same task → the third passes with a warning; a title prefixed `[RED]`/`[docs]`/`[skip-gate]` — skip; `TEAM_GATES=off` — turns it off; hook timeout (150 s) — also fail-open |
| `TeammateIdle` → `hooks/team-teammate-idle-gate.sh` | going idle with an uncommitted change **inside the teammate's own linked worktree**; in the shared tree — only a warning to the lead | same limit: 2 blocks → the third passes; `TEAM_GATES=off`; timeout (15 s) — fail-open |
| `SubagentStart`/`SubagentStop` → the `observability` plugin's journal (default-on, works for ordinary subagents too, not only the team) | never | a JSON line in `data/agent-journal.jsonl` (in `.gitignore`): time, event, agent type/id, `cwd`, last 300 characters of the final message |

## Git discipline in the team

Worktree creation, base ref, writer cap, who commits, merge-back, cleanup,
the venv trap, and what proves the tests see your code — single source of
truth [`core/agents/_WORKTREE_PATTERN.md`](../core/agents/_WORKTREE_PATTERN.md)
(the "Live team" row in the transport table), not repeated here. Two rules
specific to this plugin, not about worktrees as such:

- Reader roles — in the shared tree, don't change files.
- Stage explicit paths, never `git add -A` — the shared tree may hold
  someone else's uncommitted edit.

## Cost and engine limits

- Every teammate is a full session. **Measured from transcripts** (20 spawns
  across three transports on a freshly generated project): **48.6k…62.9k
  tokens** are read before the first line of work, median **≈56k** (for
  live-team teammates — 53.5k / 61.2k / 62.9k). This includes the harness
  system prompt with tool schemas, three `CLAUDE.md` files, memory, and the
  brief; the agent's own file and its preload skills are a small share. On a
  mature project the number is higher, not lower. Four teammates —
  **≈220k tokens at the start**, before any work.
- Doesn't survive `/resume`; one team per session; the lead cannot be
  replaced.
- A teammate doesn't spawn subagents and doesn't go into background work —
  only synchronous calls; escalation — `SendMessage` along the `Handoff:`
  chain.
- Split panes aren't available in Windows Terminal and VS Code — in-process
  mode only.

### Cost — measured

The same benchmark (three independent utilities, 2 files and three
acceptance lines each) run with all three transports on one fixture from a
shared tag. Measured from session transcripts (`usage` per message, deduped
by `message.id`), not from `/usage`: that is a daily aggregate across all
local sessions, and three runs on the same day are indistinguishable in it.

| Transport | Total | Lead | Agents | n agents | Duration |
|---|---|---|---|---|---|
| Subagents (`/dev:pipeline`) | **$7.68** | 4.66 | 3.02 | 5 | 37m 07s |
| Live team (`/dev:team`) | **$9.08** | 5.74 | 3.34 | 3 | 64m 52s |
| Workflow (`--workflow`) | **$15.25** | 6.89 | 8.36 | 12 | 46m 05s |

- `$` — **API list-price equivalent**, not a bill: a subscription spends
  plan limits instead. The number serves as a comparable scale; the ratio
  carries the meaning.
- Stable conclusion: **subagents < team < workflow**, `--workflow` costs
  roughly **twice** as much as subagents. The order holds under any
  reasonable weighting of the output and after subtracting the
  measurement's own overhead.
- **The "Lead" row's ratios cannot be compared** — they're contaminated
  differently by the measurer's own questions (separable in one run, not in
  another, absent in the third).
- The live team is the **slowest** by wall clock and still cheaper than
  workflow: the transport is interactive by design, the owner stays in the
  loop.
- **The "live team" row does not measure everything you pay for.** In that
  run, teammates **never messaged each other** and **hook gates never
  fired**: the lead ran the roles sequentially, and CC 2.1.222 has no shared
  task list, so there's no `TaskCompleted` event either. So $9.08 is the
  price of **sequential named subagents woken by message**, not of full team
  mode. What teammate messaging and the gates cost — **not measured**; take
  the row as a lower bound.
- Scope of validity: **one run per transport**, one workload, one machine.
  Layout and transport are confounded by construction (workflow ran 12
  agents against 5 and 3), so the table answers "how much does the transport
  cost **in its normal layout**", not "how much does an agent cost".
- The workflow row measures `dev-pipeline` **in the revision that actually
  ran**; the script's RED prompt was fixed after the measurement (it
  prescribed "one property per test" — exactly what reviewers rejected tests
  for in all three runs). The prompt fix doesn't affect the cost, it does
  affect the RED stage's quality, and that wasn't re-measured.

## First trial run

One small task, one mechanism. Roster: `tester` + `developer` + `reviewer`,
no `cto`. The goal is to verify the wiring, not to ship a feature:

1. the tester got a `[RED]` task and asked the developer about the interface
   by name;
2. `TaskCompleted` blocked the developer's red test and released it after
   the fix;
3. `data/agent-journal.jsonl` got start and finish lines for both;
4. merge-back left no stray junk in the commit.

If even one of the four didn't happen — that's a finding, not a reason to
fix it on the spot.

## What a live run has verified, and what it hasn't

Run on 2026-09-05, CC 2.1.222, roster `tester` + `developer`, a throwaway
task. Observations as facts, not impressions:

- **Works:** spawning teammates, addressing by name, `SendMessage` in both
  directions (the tester asked the developer about the interface, got a
  contract, and wrote tests from it without peeking into the developer's
  files), `ListAgents` on the lead, the `SubagentStart`/`SubagentStop`
  journal. An incoming message **wakes** a stopped teammate — in the journal
  that's a second `SubagentStart` with the same `agent_id`.
- **A teammate inherits `skills:`** — both skills arrived as full blocks
  before its first tool call. The earlier note that it "doesn't inherit" was
  wrong.
- **`ListAgents` exists only for the lead** — a teammate doesn't have it; it
  learns its addressee from the brief, and only from there.
- **Not a single live `TaskCompleted`/`TeammateIdle` event occurred, and in
  this build none can:** CC 2.1.222 has no shared task list, so there's
  nothing to generate the event. Both gate hooks are verified only by tests
  on a synthetic git repository. Until that changes, the task gate is held
  by `reviewer`, not the hook.
