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
- **Independent `tester` — selectively, not always.** Call it when the contract is
  observable from outside: config fields, counters, public API, command surface. Skip it for
  internal mechanism work: not seeing the code, it invents a model and pins it as the
  contract. When called, it goes **before** the author writes tests and gets the acceptance
  criteria only, never the diff.
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
- **Skipping the independent tester must be declared out loud** ("tester skipped: internal
  mechanism, <reason>") in the plan or the commit. Unstated, "selectively" decays into
  "never".
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
