# Team brief — transport wrapper for one teammate, in English

The fields of the brief itself — DESIGN, FILES, REDS, FIRST EDIT, TESTS, OUT OF SCOPE, TRAPS,
BUDGET, COMMIT, REPORT — and the per-model notes are the executor form
`dev/templates/executor-brief.md`; fill it first, then wrap it in the blocks below. The wrapper
adds only what the live team has and a subagent does not: named peers and a worktree of its own.

Why a wrapper at all: on this project the measured misses of Sonnet-class implementers were
misses of *scope*, not of code quality — the model executes literally and does not generalize an
instruction from one item to the rest. Half of the result is in the brief.

```
<role>
You are `<agent-type>` on team `<team>` for plan `<plans/<slug>/plan.md>`, Task <X.Y>.
Lead: the main session. Peers you may message by name — only the roles on this Task's
`Handoff:` chain: <name — role, produces your input>, <name — role, consumes your output>.
</role>

<task>
<the executor form, filled: TASK / DESIGN / FILES / REDS / FIRST EDIT / TESTS / OUT OF SCOPE /
 TRAPS / HANDOFF IN / BUDGET / COMMIT>
</task>

<working_rules>
- Protocol: `team-protocol` is preloaded for you; if it is not in your context, read
  `.claude/skills/team-protocol/SKILL.md`. Peers you may ask are only those on your
  `Handoff:` chain.
- Worktree (writers only): you work in `<path beside the repo>` on branch `<branch>`. First
  command there: `env -u VIRTUAL_ENV uv sync --extra dev`; every later command as
  `env -u VIRTUAL_ENV uv run …`; run the worktree preflight and paste its output before any
  test claim. (readers: you work in the shared tree and change no files)
- The `DESIGN: … / FILES: … / starting edits` message goes to the lead by name; do not wait
  for an answer.
- Cannot finish (a decision you may not make, spec contradicts the code, two failed
  iterations)? Escalate ONE level up, never sideways — `ESCALATION -> <role>` to that role by
  name, or to the lead if the role is not on the team. Do not wait idle for an answer you can
  work around.
</working_rules>

<report>
<the REPORT block of the executor form>
</report>
```

Append the per-model line from the executor form for the teammate's tier.
