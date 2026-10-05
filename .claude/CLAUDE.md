# KnowledgeOS — Project Extensions

Lead file: the main session and the built-in `general-purpose` read it. Agents: `.claude/agents/`, commands: `.claude/commands/`, modes: `.claude/modes/`.
Project context, rules, stack → see root `CLAUDE.md`. Measurements, pilots, history → `docs/claude/LEAD_RULES.md`.

## For any agent without project-rules

Covers the lead too: the main session does not load `project-rules`.
- Every final report has a non-empty "What I left open / unreliable" section; questions that outlive the task go to `docs/claude/OPEN_QUESTIONS.md`.
- Escalate one level up, never sideways, never a guess: junior/docs-writer → developer/tech-writer → teamlead → cto → owner.
- Search with `git grep` or `rg` scoped to paths; never `grep -r` from the repo root (worktrees hold full checkouts).
- One tree, one writer. Stage explicit paths, never `git add -A`; after a commit run `git show --stat HEAD`.
- In a worktree: the main `.venv` + `PYTHONPATH=<worktree root>`; never `uv sync`, never `uv run` without `--no-sync`.
- Never commit or push unless the brief says so.
- Answers to the owner are in Russian.

## Modes (read the right one before starting any task)

| Mode | File | When |
|------|------|------|
| **Dev** | `.claude/modes/dev.md` | Code, tests, review, refactoring, migration, CI, deploy, bugs |
| **Spec** | `.claude/modes/spec.md` | Living product specs in `docs/direction/` |

Unclear which mode → ask the user.

## Test authorship — three roles, three defect classes (STRICT)

Green never means correct on its own. Full text: `docs/claude/LEAD_RULES.md` → «Test authorship».
- Three roles: blind `tester` (acceptance criteria) / author (hazard tests: races, reentrancy, ordering) / `reviewer` (reproduces by running).
- Break-injection on every claimed property: revert each guarantee separately; state the expected failing set BEFORE the run and name it again AFTER the last test is written; a mismatch is a finding.
- A test that can block runs the call in a daemon thread with a join deadline.
- Independent `tester`: every task, once per mechanism, before the code; acceptance only, forbidden paths named; break-inject its file too; its wrong model is a finding.
- No legitimate tester skip: a forced one goes into the plan AND the commit; the task stays unverified.
- A review verdict without a reproduction (input → observed output) is advisory only. Reviewers: no long waits; on a hang skip that check, say so, always issue the verdict.
- Expected values are literals, never derived from the code under test.
- Assert the observable effect, not a spy on an API name.
- A fake-harness suite needs one test that wires the real objects.
- Never write "impossible", "guaranteed" or "cannot" without a reproduction next to it.

## Task launch convention (owner's decision, 2026-08-13 — do NOT ask before each task)

The owner does not want a "how should I run this one?" round per task. This is the standing
answer; follow it and only speak up when deviating.

| Stage | Who | Notes |
|---|---|---|
| 0. Spec review | `reviewer`, **synchronous, once on the Task text** (DESIGN / FILES / REDS), via `MODE: plan` on one Task file (`reviewer.md`) | before the tester: the tester's acceptance lines must be final. Verdict `APPROVED` / `CHANGES REQUESTED` with a list. Not run for solo-trivial work. |
| 1. Independent acceptance tests | `tester`, **once per mechanism, before the implementation** | synchronous, from acceptance criteria only. Runs in a **git worktree at the pre-implementation commit** — blindness is enforced by the tree, not by prose. Its tests are expected RED; they are the spec handed to stage 2. |
| 2. Implementation | `developer` (Middle) / `teamlead` (Senior+) | per the threshold rule in the global CLAUDE.md. I keep the spec, the acceptance and the measurements. |
| 3. Break-injection | me, never delegated | against **both** test sets — the author's and the tester's. Predictions written before the run. |
| 4. Live stand | me | numbers, not adjectives; `backend_ctl` over reading source. |
| 5. Review | `reviewer`, **after every task** | synchronous (`run_in_background: false`), findings must carry input → observed output. |
| 6. Live defect that is not obvious | `investigator` | instead of digging in the main context. |

- Never run the tester twice on one mechanism: a second acceptance pass = my injection matrix plus `reviewer`.
- Name the forbidden paths in the tester prompt too; carry its file back into the main tree afterwards.
- Solo (no subagent for stage 2) only for trivial work — 1–3 files, under ~80 lines, no new mechanism — and it must be said out loud. Stages 1, 3 and 5 have no solo variant.

Refinements and history: `docs/claude/LEAD_RULES.md` → «Task launch convention».

## Subagents are background by default (Claude Code 2.1.212+, STRICT)

Three Claude Code defaults changed underneath the rules above, and each one fails **silently** —
nothing errors, the guarantee just stops holding.

| New default | What it breaks here | What to do |
|---|---|---|
| Subagents run in the **background** unless told otherwise | "Reviewers work synchronously" becomes a wish; the verdict arrives after the turn that needed it | Pass `run_in_background: false` for `reviewer`, `tester`, and any live-run check |
| A finished background agent **commits, pushes, and opens a draft PR** on its own — it no longer asks | Commits without `Why:`/`Layer:` trailers, pushes not gated by `/dev:ship`, plan checkboxes out of sync | Say so in the agent's prompt: diagnose and report only, never commit or push. `reviewer` and `investigator` do not write code — that already covers them; `developer`/`teamlead` need it said |
| Nested subagents up to **depth 3** (was 1) | Director → Manager → Developer now really nests, so the 2-iteration failure-recovery limit can be spent three levels down without surfacing | Escalation still surfaces to the top on the 3rd iteration — state the limit in the spec handed down, not only at the top level |

Roles → models (all 14): `cto` = Fable; `teamlead` / `reviewer` / `investigator` / `manager` / `integrator` / `ai-judge` = Opus; `developer` / `tester` / `debugger` / `tech-writer` / `spec-writer` = Sonnet; `junior` / `docs-writer` = Haiku.

`/review` is a fast single-pass PR review; `/code-review` is the multi-agent one and **runs in
the background** — for a verdict this project's rules will accept, drive `reviewer` directly instead.

## ponytail — when the laziness ladder applies

Run `Skill: ponytail` before new code, a new dependency or a speculative "make it generic" ask; skip it for mechanism work, debugging, behaviour-keeping refactors, docs, plans. Project rules always win over ponytail. On demand: `ponytail-review`, `ponytail-audit`, `ponytail-debt`. Boundary: `docs/claude/LEAD_RULES.md` → «ponytail».

## Standing rules — one skill, not twelve copies (since 2026-09-02)

Subagent rules live in `project-rules`; change a rule in the skill, never in an agent. Edit the source in `.claude/plugins/<id>/`, then copy it to the mirror byte for byte.
`claude-kit upgrade --apply` preserves only `.claude/CLAUDE.md`, `modes/_stack.md`, `settings.local.json`, `commit-layers.txt`; `project-rules`, `team-protocol`, `cto.md` in `.claude/plugins/` get overwritten — `diff` before an upgrade. History: `docs/claude/LEAD_RULES.md` → «Standing rules».

## Team mode — agents that live in the session (`/dev:team`, since 2026-09-02)

Protocol: `.claude/commands/dev/team.md`. Fable (`cto`) — only phase acceptance / merge gate / arbitration / escalation, never per task.
Only the lead merges; one worktree per writer, at most three writers at once. No role without a task: spawn the minimal roster.
Escalation: the asker messages the higher role by name; outside a team it ends with `ESCALATION -> <role>` (question / tried / blocked on / files) and the lead spawns that role; the lead relays, never answers in place of the higher role.
Engine limits: re-check them after a Claude Code upgrade.
Roles, hooks, git, engine limits: `docs/claude/LEAD_RULES.md` → «Team mode».

## Persistent agents across a track — re-summon, don't respawn (pilot «Компания v2», 2026-10-02)

- Address = agentId, never the name; keep an `agentId` table in the handoff.
- Developer: one per track; review fixes go to the author before its handoff; set the handoff threshold (~150k) after the review nits close.
- Re-summon for review fixes and round 2 (≤ 10 calls); a whole next subtask on the same agent is provisional.
- Reviewer round 2: re-summon the round-1 reviewer by agentId.
- Tester and round-1 reviewer stay fresh relative to the code.
- No standing "expert" agent: write `docs/maps/<subsystem>.md`. Anyone re-summoned after a spec change gets the spec SHA and an order to re-read the section.
- The live stand stays mandatory before merge.

Measurements: `docs/claude/LEAD_RULES.md` → «Persistent agents».

## Language policy (STRICT)

**All user-facing output MUST be in Russian. No exceptions.**

| What | Language | Why |
|------|----------|-----|
| Chat responses to user | **Russian** | User is Russian-speaking |
| Code comments | **Russian** | Readability for the user |
| Documentation (README, STATUS, descriptions) | **Russian** | User reads these |
| Reports, handoffs, session logs | **Russian** | User reads these |
| Plans (workspace/plans/, apps/*/plans/, projects/*/plans/) | **Russian** | User reviews and edits plans |
| Wiki articles | **Russian** | Target audience is Russian |
| Technical terms (pipeline, frontmatter, RAG, etc.) | English as-is | Standard terminology |
| `.claude/` files: CLAUDE.md, agent prompts, skills, commands, memory, settings.json | English | Token efficiency, model-read files (owner 2026-10-05: everything a model reads is English) (root `CLAUDE.md` is Russian: the owner reads it) |

- the native `language` key in `.claude/settings.json` reinforces this (`project-rules` §6)
- Internal reasoning can be in any language — only output matters
- Explanations to the owner and between roles follow STE-80: `.claude/skills/project-rules/ste-80.md`.

## Commands — quick reference

Full list in the corresponding mode file. Key commands (recount: `find .claude/commands -name '*.md' | wc -l`):

- **Dev:** `/dev:plan`, `/dev:implement`, `/dev:test`, `/dev:review`, `/dev:debug`, `/dev:ship`, `/dev:pipeline`, `/dev:team`, `/dev:adr`, `/dev:plan-status`
  (bare `/plan` and `/review` are Claude Code built-ins — plan mode and PR review)
- **Spec:** `/spec`, `/spec-sync`
- **Quality:** `/sentrux-health`, `/sentrux-dsm`, `/sentrux-gaps`, `/qex-status`, `/code-stats`, `/test-ratio`, `/arch-review`, `/doctor`, `/lint-agents`, `/lint-settings` (owner)
- **Analysis:** `/channel-map`, `/message-contracts`, `/todo-inventory`, `/graph-slice`
- **Memory:** `/memory:init` (owner), `/memory:search`, `/memory:status`
- **Infra:** `/validate`, `/fw-test`, `/cold-start`, `/run-proto`, `/clean-cache` (owner), `/diagrams`
- **Team:** `/team`, `/hire`, `/handoff`, `/docs`, `/wrap-up`

## MCP routing (orchestrator + subagents)

Servers per role: `docs/claude/LEAD_RULES.md` → «MCP routing». Before first use `Read` `.claude/plugins/<id>/README.md`; a server absent from `.mcp.json` → `Grep`/`Read`; one server answered → don't re-check another.
Debug and test the backend through `backend_ctl` (`BACKEND_CTL=1`; the same router messages as the GUI); `qt-mcp` only to test the GUI itself; no ad-hoc psutil.
Servers with docs: `docs/claude/LEAD_RULES.md` → «MCP routing».

## Behavioral additions (Karpathy + Pocock gap-fill)

- Think before coding: state assumptions; several readings → list them, never pick silently; unclear → ask.
- Goal-driven: multi-step work gets a plan `1. step → verify: check`.
- Smart-zone: quality degrades past ~100k tokens; watch the budget early. Boundary protocol: `.claude/skills/project-rules/session-boundaries.md`.

## Token discipline (baseline & tool output)

Never trade reasoning quality for tokens. Lean output at the source (`pytest -q --tb=short`, `ruff check -q`); debugger/tester get full output; read the 3 files that matter, not 20 (qex / targeted `Grep`); don't force `ENABLE_TOOL_SEARCH=true` (behind a proxy/Vertex); CLI over MCP for one-off ops; disable unused servers in `enabled.yaml`, audit with `/context`. Unavoidable `/compact` → focus files + tests + plan path; at a boundary prefer `/clear` + handoff. Details: `docs/claude/LEAD_RULES.md` → «Token discipline».

## Project layout — where to write and where to read

| What | Path |
|-----|------|
| Code | root `CLAUDE.md` → «Ключевые пути» |
| Commit guide | `.claude/COMMIT_GUIDE.md` |
| Plans / session logs | `plans/`, `docs/sessions/YYYY-MM-DD.md` (`/core:team:wrap-up`) |
| Open questions | `docs/claude/OPEN_QUESTIONS.md` |
| Commands/Agents/Skills | edit `.claude/plugins/<id>/…`, then copy to `.claude/{commands,agents,skills}/` |

Thread: `/dev:plan` → `/dev:implement Task X.Y` → commit with `Refs:` → `/dev:ship` → `/core:team:wrap-up`. Full table: `docs/claude/LEAD_RULES.md` → «Project layout».

## Memory (OVERRIDE)

Canon: `docs/claude/memory/` (git, both machines); the local auto-memory folder is a cache refreshed from it by `diff`. Cross-role rules stay in `docs/claude/memory/`.
Format and subagent memory: `docs/claude/LEAD_RULES.md` → «Memory».

**Capture rail — when to write.** WHEN: the fix took more than one attempt; a recurring trap;
the user gave a rule/correction; a non-trivial decision outside code/git/plan. FORBID: what
code/git/plan/`CLAUDE.md` already store; one-off details; "might come in handy". Before writing —
`grep` on individual keywords (not the whole phrase); a near-match → UPDATE, not a duplicate.
Manual trigger — `/core:memory:remember` at a verified transition (red→green, decision made).
