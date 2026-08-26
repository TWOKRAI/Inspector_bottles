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

## Standing rules injected into every project agent prompt

Appended verbatim to all 12 files in `.claude/agents/dev/` (no shared-include mechanism exists —
each file is standalone, so the block is duplicated; keep them in sync by editing all twelve).

1. **Check qex freshness before using it.** `get_indexing_status` first, compare `last_indexed`
   with today. The index here is deliberately stale and does not say so. Stale → qex is a hint,
   `Grep` is truth; counts come from grep only. **Announce the index age before any review verdict
   and ask whether to refresh.** Pass the age as a number into subagent prompts.
2. **Honesty is the rewarded outcome, not a failure.** Don't invent a plausible explanation, don't
   stay silent about unfinished or shaky work, don't pass a green run off as proof when the test is
   known to be weak. Every final report carries a non-empty "what I left open and what I know is
   unreliable in my own work". Questions that outlive the task go to
   [`docs/claude/OPEN_QUESTIONS.md`](../docs/claude/OPEN_QUESTIONS.md).

Both added 2026-08-26 at the owner's request. The second one has a measured origin: in Ф5 of
`observation-port` an agent handed back its own hazard test as unreliable ("it only goes red when
the race window is widened artificially"), which stopped a false guarantee from being counted —
while a confident "М5 cannot pass" in the same phase survived until it was checked by hand.

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

Full list in the corresponding mode file. Key commands (46 total in 7 namespaces):

- **Dev:** `/dev:plan`, `/dev:implement`, `/dev:test`, `/dev:review`, `/dev:debug`, `/dev:ship`, `/dev:pipeline`, `/dev:adr`, `/dev:plan-status`
  (bare `/plan` and `/review` are Claude Code built-ins — plan mode and PR review; the
  global agent-launching copies moved to `/ko:plan` and `/ko:review` on 2026-08-05)
- **Spec:** `/spec`, `/spec-sync`
- **Quality:** `/sentrux-health`, `/sentrux-dsm`, `/sentrux-gaps`, `/qex-status`, `/code-stats`, `/test-ratio`, `/doctor`, `/lint-agents`, `/lint-settings`
- **Analysis:** `/channel-map`, `/message-contracts`, `/todo-inventory`, `/graph-slice`
- **Memory:** `/memory:init`, `/memory:search`, `/memory:status`
- **Infra:** `/validate`, `/fw-test`, `/cold-start`, `/run-proto`, `/clean-cache`, `/diagrams`
- **Team:** `/team`, `/hire`, `/handoff`, `/docs`, `/wrap-up`
