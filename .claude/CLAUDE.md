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

- **Dev:** `/plan`, `/implement`, `/test`, `/review`, `/debug`, `/ship`, `/pipeline`, `/adr`, `/plan-status`
- **Spec:** `/spec`, `/spec-sync`
- **Quality:** `/sentrux-health`, `/sentrux-dsm`, `/sentrux-gaps`, `/qex-status`, `/code-stats`, `/test-ratio`, `/doctor`, `/lint-agents`, `/lint-settings`
- **Analysis:** `/channel-map`, `/message-contracts`, `/todo-inventory`
- **Memory:** `/memory:init`, `/memory:search`, `/memory:status`
- **Infra:** `/validate`, `/fw-test`, `/cold-start`, `/run-proto`, `/clean-cache`, `/diagrams`
- **Team:** `/team`, `/hire`, `/handoff`, `/docs`, `/wrap-up`
