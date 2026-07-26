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
- Non-trivial task → call `tester` **before** the author writes tests. The tester gets the
  acceptance criteria and the public contract, never the diff.
- Author's tests are additional, never a replacement.
- A review verdict without a reproduction is advisory only. Findings must carry
  input → observed output.
- "Red without the fix" is mandatory but insufficient: it proves the test covers the
  change, not that the change is right.

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
