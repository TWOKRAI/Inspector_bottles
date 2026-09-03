---
name: project-rules
description: Standing rules shared by every dev agent in this repository — qex freshness check, honesty over plausibility, MCP availability, commit trailers, subagent and language discipline, and the escalation ladder (junior → developer → teamlead → cto → owner). Preloaded into agents through `skills:` in their frontmatter; Read it manually if it is not already in your context.
---

# Project rules (apply on top of your role)

These rules used to be pasted verbatim into all twelve agent files; they now live here only.
Source of truth: `.claude/plugins/dev/skills/project-rules/SKILL.md`, materialized to
`.claude/skills/project-rules/`. Edit the plugin source, then re-materialize — there are no
per-agent copies to keep in sync anymore.

## 1. qex — check index freshness BEFORE using it

`mcp__qex__get_indexing_status` is the **first step of any qex use**, before the first
`search_code`. Compare `last_indexed` with today's date.

The index does not announce its age: with `indexed: true` and `vector_search_available` the
results look healthy and answer confidently — with old data. (Until 2026-08-27 the index was
weeks stale by owner's decision; it is now rebuilt and cheap to refresh, ~7 min incremental —
but only the date tells you which state you are in.)

- Fresh (days) → the usual "qex-first" rule applies: search before modifying a symbol.
- Stale (weeks) → qex is a hint "where to look"; the truth is `Grep`/`rg` and reading the file.
  Re-check line numbers from the results instead of copying them. Any NUMBER ("how many
  callers", an inventory) is counted by grep only — a stale hit does not count.
- **Announce the index age before a review or a verdict and ask whether to refresh**, in one
  line: "index from <date>, N days old; refresh?" A verdict built on a stale index without
  that line is not accepted.
- When you launch a subagent, **pass the index age as a number in its prompt**. It does not
  know the age and will trust the results; "check it yourself" is weaker than a date.
- Semantic queries to `search_code` work best in English with code-like vocabulary; exact
  Russian terms still hit through BM25, abstract Russian paraphrase misses.

## 2. Honesty is the rewarded outcome — "I don't know" beats plausible

If you are stuck, do not know something, could not verify it, or doubt your own result —
**say so plainly**. That is a successful outcome of the task, not a failure.

It is also cheaper for you: a hidden guess does not disappear, it comes back as a review
finding, a re-run, a second iteration, sometimes a redo of the whole task. Naming a doubt
costs one sentence; hiding it costs the work twice, the second time with someone else's time
and with less trust in the rest of your report. Measured on phase Ф5 of `observation-port`,
both sides on the same day: the agent that handed in its own hazard test as unreliable
redid nothing — the caveat was simply recorded; the agent that confidently declared "this
test cannot pass" instead of "I do not understand what it wants" earned a whole extra
iteration, because the claim had to be checked by hand and turned out half true.

**Forbidden:**
- inventing a plausible explanation instead of checking ("most likely because…");
- staying silent about work that is unfinished or done without confidence;
- presenting a green run as proof when you know the test is weak;
- writing "impossible", "guaranteed", "cannot" without a reproduction next to it.

**Required:**
- a non-empty section **"What I left open and what I know is unreliable in my own work"** in
  every final report;
- if a question outlives your task (needs access, an owner's decision, the live stand, another
  agent) — record it in `docs/claude/OPEN_QUESTIONS.md` in the format given at the top of that
  file. A recorded question gets picked up; an unspoken one does not;
- if your own check is weak — say in what way, and what would count as real proof.

Handing in your own test as unreliable is the right move. A false guard is more expensive
than a missing one, because people rely on it.

## 3. MCP availability follows `enabled.yaml`

A server named in your role prompt is usable only when its plugin is enabled in
`.claude/enabled.yaml`; disabled servers are simply absent — take the `Grep`/`Read` fallback
your role lists. Before the first use of any MCP tool, `Read` its plugin README
(`.claude/plugins/<id>/README.md`) for setup, usage and rules. Tool schemas are deferred: load
them with `ToolSearch` before calling.

## 4. Commits, pushes and pull requests

- Commit only if your role says you commit **and** the lead's brief did not say otherwise.
  Never push, never open a pull request, never `git add -A` — stage the explicit paths you
  changed. A second session or teammate may have uncommitted work in the same tree, and
  `-A` sweeps it into your commit under your message.
- Message format: Conventional Commits plus the mandatory trailers `Why:` and `Layer:`, and
  `Refs: plans/<slug>.md` when the task comes from a plan. The `commit-msg` hook rejects
  anything else. Full guide: `docs/claude/COMMIT_GUIDE.md`; `Layer:` values in
  `.claude/modes/_stack.md`.
- After every commit run `git show --stat HEAD` and check that the diff matches the message.
  The pre-commit hook stages the session log, so a commit can carry more than you staged.

## 5. Subagents and scope

- Spawn a subagent only for a sizeable, genuinely independent track (a wide multi-file sweep).
  Do not delegate work you can finish in a handful of tool calls, and do not use subagents to
  verify or double-check your own work. Pass `run_in_background: false` when you need the
  answer before continuing.
- Apply every instruction to every listed file, not only the first one. Keep changes to what
  the task names; a pre-existing bug or an improvement you notice is a follow-up line in your
  report, not a change in this task.
- Prefer targeted edits over whole-file rewrites: same result, fewer tokens, smaller diff.

## 6. Language

Agent prompts, skills, settings and memory files are English. Everything the owner reads is
Russian: chat output, code comments and docstrings, README/STATUS/DECISIONS, plans, guides.
Technical terms stay in English inside Russian text. Do not mix languages inside one file.

## 7. Escalation ladder — a question goes one level up, never sideways, never into a guess

When you cannot finish — a decision you are not allowed to make, an ambiguity whose two
readings give different work, a third failed iteration, a contradiction between the spec and
the code — the task ends neither with a guess nor with silence. It goes one level up, exactly
as in a company: a junior asks a developer, a developer asks the teamlead, the teamlead asks
the technical director, the director asks the owner.

| You are | You escalate to | Typical reason |
|---|---|---|
| `junior`, `docs-writer` | `developer` / `tech-writer` | the change needs a choice the task did not write down |
| `developer`, `tester`, `debugger`, `tech-writer`, `spec-writer` | `teamlead` | design question, spec contradicts the code, two failed iterations; `debugger` may go to `investigator` first for the diagnosis |
| `teamlead`, `reviewer`, `investigator`, `manager`, `integrator`, `ai-judge` | `cto` | architecture, ownership or invariant decision; `teamlead` and `reviewer` still disagree after two iterations; an ADR-level choice |
| `cto` | the owner, through the lead | scope, priority, hardware, budget — anything only the owner decides; also recorded in `docs/claude/OPEN_QUESTIONS.md` |

How to escalate:
- **In a team** — `SendMessage` to the higher role by name if it is on the team; otherwise the
  same text to the lead, who spawns that role. Mark your task blocked; do not go idle silently.
- **As a subagent** — end your report with the block below; the lead spawns the higher role.
- One level at a time: a junior never writes to the cto. The answer comes back the same way.
  The higher level answers the question within its scope; it does not take over the task
  unless it says so explicitly.

```
ESCALATION -> <role>
Question: <one sentence, answerable with a decision>
Tried: <what you did, with observed output>
Blocked on: <the decision or information you need>
Files: <paths>
```

Why this shape: a question with "tried" and "observed output" is answered in one reply; a bare
"it does not work" costs the higher level a re-investigation, and a silent guess costs a
review iteration.
