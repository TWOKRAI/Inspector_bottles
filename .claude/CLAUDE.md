# KnowledgeOS — Project Extensions

Agents: `.claude/agents/`, commands: `.claude/commands/`, modes: `.claude/modes/`.
Project context, vault zones, rules, stack → see root `CLAUDE.md` (single source of truth).

## Modes (read the right one before starting any task)

| Mode | File | When |
|------|------|------|
| **Dev** | `.claude/modes/dev.md` | Code, tests, review, refactoring, migration, CI, deploy, bugs |
| **Spec** | `.claude/modes/spec.md` | Living product specs in `docs/direction/` |

Unclear which mode → ask the user.

## Test authorship — three roles, three defect classes (STRICT)

A test written by the code's author proves agreement with the author's own model, not
with reality. Green therefore never means correct on its own. Established 2026-07-26,
Ф0.3 of `observability-unified-routing`: 12 green tests + a passing "red-without-fix"
check all pinned a **wrong model** — the ceiling bounded the deque, while memory actually
grew in in-flight batches. The reviewer found it by **running** the scenario, not reading.

| Role | Writes | Guards against |
|------|--------|----------------|
| **Independent agent** (`tester`) | tests from the acceptance criteria, **without seeing the implementation** | the author's wrong model |
| **Author** (`developer` / `teamlead`) | tests for internal hazards — races, reentrancy, ordering, lock discipline | regressions in the subtle places only the author can see |
| **Reviewer** (`reviewer`) | **reproduces by running**, quoting real output; does not review by reading the diff alone | both — plus the defects that are invisible in a diff (`except: pass`, a counter that means "handed over" not "written") |

Rules:
- **Break-injection is the proof, and it is mandatory.** Not once per commit — once per
  claimed property. Revert each guarantee separately (throwaway pytest plugin or a scripted
  textual patch) and record which tests died. State the expected set BEFORE running; a
  mismatch is a finding either way. A test that stays green under its own break does not
  exist. A test that **hangs** instead of failing is worse than absent — it hides the
  regression behind a timeout, so any test that can block must run the call in a daemon
  thread with a join deadline.
- **Author writes hazard tests for the mechanism.** Most of the value arrives while writing
  the docstring — "what can break in *this* mechanism, given how it is built" — not from the
  run. Author's tests are additional, never a replacement.
- **Independent `tester` — ALWAYS, on every task. No "selectively".** (Owner's decision,
  2026-08-13, replacing the earlier carve-out for "internal mechanism work". The carve-out
  was doing exactly what the rule below warned about: decaying into "never". Measured on
  Task 2.1 of `telemetry-stage6`, where the skip had already been declared and the tester
  was then run anyway: it found two stale README claims the author had missed, and
  injecting against *its* suite exposed a wrong causal explanation the author had written
  into the ADR, the plan and three docstrings.)
  - It runs **before** the author writes tests where the order allows, gets the acceptance
    criteria only, and is explicitly forbidden the diff, the implementation files, and the
    author's tests — name the forbidden paths in the prompt, a generic "don't peek" leaks.
  - Its green run is **not** the result. Break-inject against *its* file too: a suite that
    stays green under the break is the thing you were trying to prevent, and the tester
    cannot check this itself — it never saw what to break.
  - Its wrong model is a finding, not noise: when it pins a contract the code does not
    have, decide which one is right and write down why.
- **A review verdict without a reproduction is advisory only.** Findings must carry
  input → observed output. Reviewers work **synchronously** — no background offload,
  no long waits; on a hang, skip that check and say so, but always issue the verdict.
  Since Claude Code 2.1.212 subagents are **background by default**, so synchronous is
  no longer what you get by omission — pass `run_in_background: false` explicitly for
  `reviewer` and `tester`. See "Subagents are background by default" below.
- A test that derives its expected value from the code under test agrees with any answer,
  including "nothing". Write the literal, and check the constant separately.
- **A spy on an implementation API name guards the name, not the property.** Assert the
  observable effect — cost, bytes written, calls at the OS boundary — or the guarantee
  evaporates the moment someone swaps an equivalent call. Found by the phase review:
  a test spying on `Path.rglob` stayed green when the walk was rewritten with `os.walk`
  while the guarantee it protected was gone.
- **There is no legitimate skip of the independent tester** since 2026-08-13. If one is
  ever forced (agent unavailable, task is pure docs), say so in the plan AND the commit with
  the reason — and treat the task as unverified until it is run.
- **A fake-harness test proves the harness.** Where a command surface is tested against
  fakes, add one test that wires the real objects — otherwise renaming a production
  attribute leaves every test green.
- **Never write "impossible", "guaranteed" or "cannot" in code, docs or a plan without a
  reproduction next to it.** A confident wrong explanation outlives a bug: the bug gets
  found by its symptom, the explanation gets believed. The phase review caught two —
  a comment claiming a per-channel sum survives channel teardown (it does not) and a
  docstring calling a filesystem lock a structural guarantee (on POSIX the file would
  have been deleted).

**Measured over Ф0 of `observability-unified-routing` (2026-07-27), which is why the rules
are weighted this way.** Independent tester, 5 runs: 3 real findings, 1 wrong model imposed
as a contract, 1 void run (launched in parallel with the implementation). Break-injection in
task 0.7 alone exposed **three defective tests of the author's own** — a vacuous one (green
with the guard fully removed), a flaky one, and one that hung the suite instead of failing.
The reviewer role delivered only once it was run synchronously against a narrow scope — and
then it returned two blockers with reproductions.

## Task launch convention (owner's decision, 2026-08-13 — do NOT ask before each task)

The owner does not want a "how should I run this one?" round per task. This is the standing
answer; follow it and only speak up when deviating.

| Stage | Who | Notes |
|---|---|---|
| 1. Independent acceptance tests | `tester`, **once per mechanism, before the implementation** | synchronous, from acceptance criteria only. Runs in a **git worktree at the pre-implementation commit** — blindness is enforced by the tree, not by prose (see below). Its tests are expected RED; they are the spec handed to stage 2. |
| 2. Implementation | `developer` (Middle) / `teamlead` (Senior+) | per the threshold rule in the global CLAUDE.md. I keep the spec, the acceptance and the measurements. |
| 3. Break-injection | me, never delegated | against **both** test sets — the author's and the tester's. Predictions written before the run. |
| 4. Live stand | me | numbers, not adjectives; `backend_ctl` over reading source. |
| 5. Review | `reviewer`, **after every task** | synchronous (`run_in_background: false`), findings must carry input → observed output. |
| 6. Live defect that is not obvious | `investigator` | instead of digging in the main context. |

**Stage 1 refined 2026-08-20 (owner's decision), and it is NOT a carve-out.** The tester still runs on
every mechanism — what is banned is running it TWICE on the same one. Measured on Ф1 of
`observation-port`: Task 1.2 and Task 1.3 both commissioned an independent tester over the same
subtree mechanism. The first (before/with the implementation) found real defects; the second cost
**479k tokens and 16 minutes to find zero** — it re-accepted what a tester and a reviewer had already
accepted. A second acceptance pass over an already-tested mechanism is now **my injection matrix plus
`reviewer`**, never a second tester. The tester's own value comes from arriving BEFORE the code:
on Task 1.4 the same role, run first, returned 6 red tests that became the implementer's spec.

**Blindness is enforced by the worktree, not by the prompt (same decision).** Both testers that day
confessed leaks — one ran a wide `grep` across the tests directory and pulled in forbidden files, the
other imported the forbidden `alert_rules` through `python -c` and printed the rule table. Both
disclosed honestly, both swear they did not use it, and **neither claim is checkable**. Naming
forbidden paths in prose stays (it is still the instruction), but the tester now works in a
`git worktree` at the commit before the implementation lands: there is nothing to leak, and its tests
are red by construction. Carry the file back into the main tree afterwards.

Solo (no subagent for stage 2) stays legitimate only for genuinely trivial work — 1–3 files,
under ~80 lines, no new mechanism — and **must be said out loud** in the task write-up. It is
not the default. Stages 1, 3 and 5 have no solo variant.

The owner's multi-select on 2026-08-13 picked the full roster *and* "tester only, rest solo";
the two are incompatible, and this table is how it was resolved — full roster as the default,
solo as the named exception. Say so if the owner meant the opposite.

## Subagents are background by default (Claude Code 2.1.212+, STRICT)

Upgraded 2026-08-05, 2.1.152 → 2.1.222. Three defaults changed underneath the rules above,
and each one fails **silently** — nothing errors, the guarantee just stops holding.

| New default | What it breaks here | What to do |
|---|---|---|
| Subagents run in the **background** unless told otherwise | "Reviewers work synchronously" becomes a wish; the verdict arrives after the turn that needed it | Pass `run_in_background: false` for `reviewer`, `tester`, and any live-run check |
| A finished background agent **commits, pushes, and opens a draft PR** on its own — it no longer asks | Commits without `Why:`/`Layer:` trailers, pushes not gated by `/dev:ship`, plan checkboxes out of sync | Say so in the agent's prompt: diagnose and report only, never commit or push. `reviewer` and `investigator` do not write code — that already covers them; `developer`/`teamlead` need it said |
| Nested subagents up to **depth 3** (was 1) | Director → Manager → Developer now really nests, so the 2-iteration failure-recovery limit can be spent three levels down without surfacing | Escalation still surfaces to the top on the 3rd iteration — state the limit in the spec handed down, not only at the top level |

Also gone: the `/agents` wizard (2.1.200) and `ultraplan` (2.1.222). Permission mode
"Default" is now called "Manual". `/review` is a fast single-pass PR review; `/code-review`
is the multi-agent one and it **runs in the background** since 2.1.218 — for a verdict this
project's rules will accept, drive `reviewer` directly instead.

## ponytail — when the laziness ladder applies

The `ponytail` skill (`.claude/plugins/ponytail/`) is installed **skills-only**: no
SessionStart hook, so it never injects itself. Its own description says "use on ANY coding
task", which in this repo would mean always-on with random timing — the boundary below
replaces that. Deliberate: the measured win (JetBrains, 80 paired tasks) is −15% code /
−10% cost on greenfield feature work, and this repo is mostly mechanism work on 27 existing
modules, where the ladder's top rungs rarely fire.

Run the ladder (`Skill: ponytail`) before writing, when the task is:
- new code from scratch, a new module, a new widget, a new plugin;
- adding a dependency, or picking between a library and stdlib/platform;
- a request that smells speculative — "make it configurable/pluggable/generic for later".

Skip it for: framework mechanism work (IPC, routing, locks, seqlock, observability layers),
debugging, refactors that keep behaviour, docs, plans, ADRs.

On demand regardless of the above: `ponytail-review` (diff), `ponytail-audit` (whole repo),
`ponytail-debt` (harvest `ponytail:` comments).

**Precedence — project rules win, without exception.** ponytail says "trivial one-liners
need no test", "ONE runnable check, no frameworks", "fewest files possible", "code first,
at most three short lines". Where that meets the rules above it loses: break-injection per
claimed property, the three test-authorship roles, `README.md` + `STATUS.md` + `tests/` per
module, `Why:`/`Layer:` trailers. ponytail governs **what gets built**, never what gets
proven or documented.

## Standing rules — one skill, not twelve copies (since 2026-09-02)

The standing rules (qex freshness, honesty over plausibility) plus MCP availability, commit
trailers, subagent scope, language discipline and the escalation ladder live in ONE file:
`.claude/plugins/dev/skills/project-rules/SKILL.md`, materialized to `.claude/skills/project-rules/`.
Every agent in `.claude/agents/dev/` lists `project-rules` in its `skills:` frontmatter (preloads the
text into its context) and ends with a four-line pointer for the case preload does not happen.
Change a rule in the skill, never in an agent.

History: before 2026-09-02 the block was pasted verbatim into all 12 agents (~60 lines each, ~650
lines of duplication), and the plugin sources in `.claude/plugins/dev/agents/` had silently fallen
60 lines behind the materialized copies — a `claude-kit sync` would have erased the rules from every
agent. Sources and materialized copies are identical again; keep them so (edit the source, copy to
the mirror, or run the materializer).

1. **qex freshness** — `get_indexing_status` first; announce the index age before a verdict; pass
   the age as a number into subagent prompts; counts come from grep.
2. **Honesty is the rewarded outcome** — every final report carries a non-empty "what I left open
   and what I know is unreliable in my own work"; questions that outlive the task go to
   [`docs/claude/OPEN_QUESTIONS.md`](../docs/claude/OPEN_QUESTIONS.md).

Language of agent files: English end to end. Commands, guides and reports: Russian.

## Team mode — agents that live in the session (`/dev:team`, since 2026-09-02)

Agent Teams is enabled: `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` in the `env` of `.claude/settings.json`
(source: `.claude/plugins/core/settings.partial.json`). The lead — this session, Opus at `high` by
project settings — is the PM: intake → Task X.Y → the minimal roster as teammates → tasks with
dependencies → monitor → break-injection → review → merge. There is no PM agent: the lead has the
conversation history, an agent would not. Protocol: `.claude/commands/dev/team.md`. Owner's guide
(Russian): [`docs/claude/AGENT_TEAMS_GUIDE.md`](../docs/claude/AGENT_TEAMS_GUIDE.md). Brief template
with per-model prompting notes: `.claude/plugins/dev/templates/team-brief.md`.

Roles → models (all 14): `cto` = Fable (verdicts only: phase acceptance, merge gate, arbitration,
answers to escalations from Opus roles — once per phase, never per task); `teamlead` / `reviewer` /
`investigator` / `manager` / `integrator` / `ai-judge` = Opus; `developer` / `tester` / `debugger` /
`tech-writer` / `spec-writer` = Sonnet; `junior` / `docs-writer` = Haiku. `junior` never commits. No role exists without a task: spawn the minimal roster.

**Escalation ladder (owner's decision 2026-09-02, `project-rules` §7).** A question goes one level up,
never sideways, never into a guess: `junior`/`docs-writer` → `developer`/`tech-writer` →
`teamlead` → `cto` → the owner (through the lead, recorded in `OPEN_QUESTIONS.md`). `debugger` may
route through `investigator` for the diagnosis. In a team the asker messages the higher role by name;
outside a team it ends its report with `ESCALATION -> <role>` (question / tried / blocked on / files)
and the lead spawns that role. The lead relays; it does not answer in place of the higher role.

What does NOT change in team mode: tester once per mechanism BEFORE the code, in a worktree at the
pre-implementation commit; break-injection by the lead, never delegated; reviewer synchronous after
every task; Fable only at phase acceptance / merge gate / arbitration / escalation.

Hooks as gates (fail-open after two blocks on the same task or agent; `TEAM_GATES=off` disables):
`TaskCompleted` runs ruff on changed `.py` and pytest on changed test files — titles *starting*
with `[RED]`, `[docs]` or `[skip-gate]` skip it (a prefix only, so a task about the RED path is still judged); `TeammateIdle` blocks idling with uncommitted work inside
a linked worktree and only warns in the shared tree; `SubagentStart` / `SubagentStop` append to
`data/team-journal.jsonl`. Scripts: `.claude/plugins/dev/hooks/`.

Git in team mode: one worktree per writer (`.claude/worktrees/team-<task>`), at most three writers
at once, readers in the shared tree; only the lead merges; stage explicit paths; `git show --stat`
after every commit; `docs/sessions/*.md` merges by union (`.gitattributes`). No per-worktree venv:
the main `.venv` with `PYTHONPATH=$PWD` from the worktree root — the package is not an editable
install, and `uv sync` would fetch CPU torch instead of the CUDA wheel.

Engine limits (2.1.222): teammates do not survive `/resume`; one team per session; teammates cannot
spawn teams or background subagents; split panes are unavailable in Windows Terminal / VS Code —
in-process only (↑/↓ + Enter opens a teammate, Esc back, x stops, Ctrl+T task list). Each teammate
is a full session: ~25k tokens of context before its first tool call.

## Language policy (STRICT)

**All user-facing output MUST be in Russian. No exceptions.**

| What | Language | Why |
|------|----------|-----|
| Chat responses to user | **Russian** | User is Russian-speaking |
| Code comments | **Russian** | Readability for the user |
| Documentation (README, STATUS, descriptions) | **Russian** | User reads these |
| Plans (workspace/plans/, apps/*/plans/, projects/*/plans/) | **Russian** | User reviews and edits plans |
| Wiki articles | **Russian** | Target audience is Russian |
| Technical terms (pipeline, frontmatter, RAG, etc.) | English as-is | Standard terminology |
| CLAUDE.md, agent prompts, memory, settings.json | English | Token efficiency, system-only files |

- `preferredLanguage: ru` in settings.json reinforces this
- Internal reasoning can be in any language — only output matters

## Commands — quick reference

Full list in the corresponding mode file. Key commands (76 command files in 14 namespaces, counted 2026-09-02):

- **Dev:** `/dev:plan`, `/dev:implement`, `/dev:test`, `/dev:review`, `/dev:debug`, `/dev:ship`, `/dev:pipeline`, `/dev:team`, `/dev:adr`, `/dev:plan-status`
  (bare `/plan` and `/review` are Claude Code built-ins — plan mode and PR review; the
  global agent-launching copies moved to `/ko:plan` and `/ko:review` on 2026-08-05)
- **Spec:** `/spec`, `/spec-sync`
- **Quality:** `/sentrux-health`, `/sentrux-dsm`, `/sentrux-gaps`, `/qex-status`, `/code-stats`, `/test-ratio`, `/doctor`, `/lint-agents`, `/lint-settings`
- **Analysis:** `/channel-map`, `/message-contracts`, `/todo-inventory`, `/graph-slice`
- **Memory:** `/memory:init`, `/memory:search`, `/memory:status`
- **Infra:** `/validate`, `/fw-test`, `/cold-start`, `/run-proto`, `/clean-cache`, `/diagrams`
- **Team:** `/team`, `/hire`, `/handoff`, `/docs`, `/wrap-up`

## MCP routing (orchestrator + subagents)

Available MCP servers — composed from `enabled.yaml` (a disabled plugin is absent; the list is the source of truth for subagents too):

- `qex` — semantic / fuzzy code search; docs: `.claude/plugins/mcp-qex/README.md`
- `sentrux` — architecture metrics, DSM, cycles, health-gate; docs: `.claude/plugins/mcp-sentrux/README.md`
- `context7` — up-to-date docs for external libraries; docs: `.claude/plugins/mcp-context7/README.md`
- `github-mcp` — GitHub state: PR / Issues / Actions; docs: `.claude/plugins/mcp-github/README.md`
- `qt-mcp` — runtime inspection for PyQt5/PySide6 GUI apps; docs: `.claude/plugins/mcp-qt/README.md`
- `backend-ctl` — live backend control via `backend_ctl` driver (requires `BACKEND_CTL=1`); docs: `.claude/plugins/mcp-backend-ctl/README.md`
- `sentry` — error-monitoring MCP (marketplace consume plugin, needs Sentry auth via `/mcp`; no local `.claude/plugins/` docs)

Before first using an MCP tool — `Read` its README (`.claude/plugins/<id>/README.md`): setup, usage, rules.

Not in `.mcp.json` → fallback to `Grep`/`Read`, don't hand the task to a subagent "for nothing". One server
answered → don't re-check another on the same data.

## Behavioral additions (Karpathy + Pocock gap-fill)

Gaps the default system prompt covers weakly. Apply on non-trivial tasks.

- **Think before coding.** State assumptions; multiple readings of the request → list them, don't
  pick silently; simpler approach exists → say so; unclear → stop and ask, don't guess.
- **Goal-driven execution.** Multi-step work → state a brief plan `1. step → verify: check`.
  Reframe imperatives into verifiable goals ("fix bug" → repro test → green). Weak criteria
  ("make it work") cause drift.
- **Smart-zone discipline.** Quality degrades past ~100k tokens (Pocock "dumb zone") — watch the
  budget proactively, not after the fact. Full protocol (task/phase boundary triggers, `/clear`
  vs `/compact`) → `project-rules` §8. Don't pad context: 20 files read when 3 matter costs
  reasoning, not just tokens — use `qex:search_code` / targeted `Grep` instead.

## Token discipline (baseline & tool output)

Lossless habits that shrink baseline + per-command cost (never trade reasoning quality for
tokens — that's what `caveman` is for, trigger-based, user-facing only).

- MCP tool-search is default-on (schemas load on demand) — don't force `ENABLE_TOOL_SEARCH=true`
  behind a proxy/Vertex; tune via `ENABLE_TOOL_SEARCH=auto:N` in `settings.json` → `env` if needed.
- Prefer CLI (`gh`/`git`/`sentrux`/`qex` via `Bash`) over MCP for one-off ops; disable unused
  servers in `enabled.yaml`. Audit the baseline with `/context` or skill **context-budget**.
- Lean tool output at the source — hooks can't rewrite it after the fact: `pytest -q --tb=short`,
  `ruff check -q`, pipe large logs through `grep -E 'ERROR|FAIL'`. Exception: debugger/tester need
  full output.
- Unavoidable `/compact` → focus `modified files + test commands + plan path`; at a real boundary
  prefer `/clear` + handoff (see Smart-zone discipline).

## Project layout — where to write and where to read

| What | Path | Written by |
|-----|------|-------|
| Main package | `src/<package>/` | developer |
| **Module contract** | `src/<package>/<module>/{README.md,interface.py,_impl/}` (full) or `<module>.py` (lite) + `tests/contract/test_<module>.py` | developer (skill `module-contract`) |
| Tests | `tests/` | tester |
| Scripts / commit validator | `scripts/`, `scripts/validate_commit/` | developer / seed (autocopy) |
| Commit guide | `.claude/COMMIT_GUIDE.md` | seed (autocopy) |
| Session logs | `docs/sessions/YYYY-MM-DD.md` | `/core:team:wrap-up`, pre-commit-session-log hook |
| Task plans | `plans/YYYY-MM-DD_<slug>.md` (single) or `.../plan.md`+`phase-N.md` (multi-phase) | `/dev:plan` (Manager) |
| Long-term memory | `.claude/memory/MEMORY.md` + `*.md` | agent (auto-memory rules) |
| Layer enum | `.claude/commit-layers.txt` | project (manual) |
| Commands/Agents/Skills | `.claude/{commands,agents,skills}/…` (materialized, gitignored) | `plugin sync` from `plugins/<id>/…` |
| Hooks | composed in `.claude/settings.json` | `plugin sync` from `plugin.json.hooks` |
| Living spec | `docs/direction/` | `/dev:spec:spec`, `/dev:spec:spec-sync` |
| Data (gitignored) | `data/` | runtime |

**Thread:** `/dev:plan` → plan + branch → `/dev:implement Task X.Y` → commit with a `Refs: plans/<slug>.md`
trailer → `/dev:ship` checks `--grep="Refs:"` and closes the plan → `/core:team:wrap-up` writes
`docs/sessions/<today>.md`. A new session restores context: branch → plan → commits' `Refs:`
→ latest `docs/sessions/` → `.claude/memory/`.

## Memory (OVERRIDE)

**Canonical path:** `.claude/memory/` (project-local, git-tracked; `autoMemoryDirectory` in
`.claude/settings.local.json`, fixed by `plugin doctor --fix`). Index `- [Title](file.md) — hook`;
an entry is a separate `.md` with frontmatter `name`/`description`/`metadata.type` ∈
`user`/`feedback`/`project`/`reference`. Lint: `.claude/plugins/core/scripts/memory_lint.py`.
Commands: `/core:memory:status`, `:search <query>`, `:remember [lesson]`, `:init` (new project).
Per-project — not shipped in the seed.

**Subagent memory** (CC ≥2.1.59) adds to, does not replace: agent frontmatter `memory: <scope>` →
CC injects the role's `MEMORY.md` into the system prompt + Read/Write/Edit. `project` (default for
dev-write agents, see `memory:` in their frontmatter) → `.claude/agent-memory/<name>/`, under git;
`local` → `.claude/agent-memory-local/<name>/`, gitignored; `user` → `~/.claude/agent-memory/<name>/`,
machine-local. Isolated per role (reviewer — review patterns, tester — flaky tests); cross-role
rules stay in `.claude/memory/`.

**Capture rail — when to write.** WHEN: the fix took more than one attempt; a recurring trap;
the user gave a rule/correction; a non-trivial decision outside code/git/plan. FORBID: what
code/git/plan/`CLAUDE.md` already store; one-off details; "might come in handy". Before writing —
`grep` on individual keywords (not the whole phrase); a near-match → UPDATE, not a duplicate.
Manual trigger — `/core:memory:remember` at a verified transition (red→green, decision made).
