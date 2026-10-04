# Team brief template — one per teammate, in English, under ~60 lines

Why a template: on this project the measured misses of Sonnet-class implementers were misses
of *scope*, not of code quality — the model executes literally and does not generalize an
instruction from one item to the rest. Half of the result is in the brief. The tags below
follow the prompt-engineering guidance for current Claude models: role, then task, then
context, then rules, then the report shape; examples in `<example>` tags when the output
shape matters.

```
<role>
You are `<agent-type>` on team `<team>` for plan `<plans/<slug>/plan.md>`, Task <X.Y>.
Lead: the main session. Peers you may message by name: <name — role>, <name — role>.
</role>

<task>
Goal (one sentence): ...
Files you may change (complete list; nothing else): ...
Steps, in order: 1. ... 2. ... 3. ...
Acceptance (each line checkable, with the command that checks it):
- [ ] ...
Out of scope (do not touch, do not "improve"): ...
</task>

<context>
Why this task exists / what breaks without it: ...
Known traps from memory or the plan: <e.g. "the RED test is at <path>; make it pass, never edit it">
qex index date: <YYYY-MM-DD> (<N> days old). Counts come from Grep, not from qex.
</context>

<working_rules>
- Worktree: you work in `<path>` on branch `<branch>`; run tests from there with
  `PYTHONPATH=$PWD` so imports resolve to your tree, not the main checkout.
  (readers: you work in the shared tree and change no files)
- Commits: <"commit on your branch — Why:/Layer:/Refs: trailers, stage explicit paths"
  | "do not commit; report the paths">. Never push, never open a PR, never `git add -A`.
- A writer in a worktree stages explicit paths, runs `ruff` itself and writes the commit message to a file;
  the lead commits (the protect-branch hook reads main).
- Apply every instruction to every listed file, not only the first one.
- If the task is ambiguous, implement the reading its wording and the surrounding code most
  directly support, state that assumption in your report, and do not build for the others.
- A pre-existing bug or an improvement you notice: a follow-up line in your report, not a fix.
- Ask a peer by name when its output is your input (the RED test path, an interface).
- Cannot finish (a decision you may not make, spec contradicts the code, two failed
  iterations)? Escalate ONE level up, never sideways: junior/docs-writer -> developer/tech-writer
  -> teamlead -> cto -> owner. Send `ESCALATION -> <role>` with question / tried / blocked on /
  files to that role by name, or to the lead if the role is not on the team. Do not wait idle
  for an answer you can work around.
</working_rules>

<report>
Mark the task complete only after the acceptance commands ran; paste their last lines.
Final message: outcome first, then files, then the non-empty section
"What I left open and what I know is unreliable in my own work".
</report>
```

## Per-model notes

The per-model lines live in one place: `executor-brief.md` → "Per-model line" (re-baselined 2026-10-02 for the current
generation). Append the line for the teammate's tier to this brief.

## Re-summon message (SendMessage by agentId)

Send, in this order: the spec SHA and what changed since the agent last read it; what is done and what is left, taken from
the worktree including uncommitted work; the next task; `re-read <section>` when the spec changed. Measured on 1b.2d: a
teamlead resumed after a 429 without loss when this list was explicit.
