---
name: project-rules
description: >
  Standing rules shared by every dev agent in this project — qex freshness
  check, honesty over plausibility, MCP availability, commit trailers,
  subagent and language discipline, and the escalation ladder (junior →
  developer → teamlead → cto → owner). Preloaded into agents through
  `skills:` in their frontmatter; read it manually if it is not already
  in your context.
---

# Project rules (apply on top of your role)

Sections 1, 3, 4 need those tools; other roles skip them and follow the rest.

## 1. qex — check freshness first

`mcp__qex__get_indexing_status` before `search_code`; compare `last_indexed` to today. Fresh →
qex-first. Stale → `Grep`, verify any NUMBER by grep, say the index age up front.

## 2. Honesty over plausibility — "I don't know" is a successful outcome

Stuck, unsure, or unverified — **say so plainly**; a hidden guess costs more.

**Forbidden:** inventing an explanation instead of checking; silence about low-confidence work;
a green run as proof over a known-weak test; "impossible"/"guaranteed" without a reproduction.

**Required:** a non-empty **"What I left open / unreliable"** section in every report;
unresolved questions go to `docs/sessions/<today>.md` Open questions; a weak check says how it's
weak and what real proof looks like.

## 3. MCP availability follows `enabled.yaml`

A server named in your role prompt exists only if enabled in `.claude/enabled.yaml`; otherwise
fall back to `Grep`/`Read`. First use: `Read` `.claude/plugins/<id>/README.md`, load its schema
via `ToolSearch`. Mutating/index-building MCP ops — who, where:
`team-protocol` §7.

## 4. Commits, pushes and pull requests

- Commit only if your role commits **and** the brief didn't say otherwise. Never push, never
  open a PR, never `git add -A` (stage explicit paths; the tree may be shared).
- Conventional Commits + mandatory `Why:`/`Layer:` trailers, `Refs: plans/<slug>.md` from a
  plan; `commit-msg` hook rejects anything else. Guide: `.claude/COMMIT_GUIDE.md`.
- After committing, `git show --stat HEAD` — the pre-commit hook may also stage the session log.

## 5. Subagents and scope

- Spawn a subagent only for a sizeable, independent track, never to verify your own work;
  `run_in_background: false` only when the answer blocks you.
- Apply every instruction to every listed file; keep changes to what the task names — a
  pre-existing bug or improvement is a follow-up line in your report, not a change here.
  Targeted edits, not whole-file rewrites.

**Brief = form** (`dev/templates/executor-brief.md`: DESIGN / FILES / REDS): first edit within 5
tool calls, never re-derive DESIGN, a file outside FILES → stop and ask.
**Test radius, not the whole suite:** blast-radius tests + `ruff check` + type checker, in the
foreground; the full suite runs once, at the lead, on the merge point. Exception: a shared-infra
change (registry, model tier, index format) — the suite is the radius.
**Environment finding** (venv, shared file, tool) → `SendMessage` to `main` now, keep working.
**Evidence or nothing:** every "green"/"red"/"fixed" carries the command and its output (predicted
RED set, break-injection output, preflight paths). **Don't chain unrelated `Bash` commands** —
one unmatched piece sends the whole chain to the owner; fix = an allow rule or a shorter chain,
never a gate-skipping flag.

## 6. Language

User replies follow the native `language` key (`.claude/settings.json`). Agent prompts, skills,
settings and memory stay English regardless; don't mix languages in one file.

## 7. Escalation ladder — one level up, never sideways, never a guess

Escalate one level (junior → developer → teamlead → cto → owner) when **blocked**, after a
third failed iteration, on spec-vs-code conflict, or when a decision **outlives your task**
(narrows an owner's decision, inherited architecture, changed acceptance, a defect outside
`Files:`) — say so **before** you act.

| You are | Escalate to | Typical reason |
|---|---|---|
| `junior`, `docs-writer` | `developer` / `tech-writer` | change needs a choice the task didn't specify |
| `developer`, `tester`, `debugger`, `tech-writer`, `spec-writer` | `teamlead` | design question, spec vs. code, two failed iterations (`debugger` → `investigator` first) |
| `teamlead`, `reviewer`, `investigator`, `manager`, `integrator`, `ai-judge` | `cto` | architecture/ownership/invariant decision, or `teamlead`/`reviewer` disagree after two iterations |
| `cto` | owner, via the lead | scope/priority/hardware/budget — record in `docs/sessions/<today>.md` Open questions |

**Team:** `SendMessage` to the higher role or lead; mark your task blocked. **Subagent:** the
moment the fork appears, send the block below to `main`, and repeat it in your final report.

```
ESCALATION -> <role>
Question: <one sentence, answerable with a decision>
Tried: <what you did, with observed output>
Blocked on: <the decision or information you need>
Files: <paths>
```

## 8. Session boundaries — offer the reset, don't wait to be asked

A finished task is the cheapest moment to shed context. End your report with exactly one line:

| Situation | The line you end with |
|---|---|
| More of the same task, context still modest | nothing — keep working |
| Task closed, next task same plan/area | `Boundary: task closed. /compact (focus: files + tests + plan path).` |
| Phase closed, feature merged, or next task elsewhere | `Boundary: <what closed>. Better: new chat — branch <b>, plan <path>, SHA <sha>, state "<line>".` |
