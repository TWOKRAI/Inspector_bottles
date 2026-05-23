# KnowledgeOS — Project Extensions

Agents: `.claude/agents/`, commands: `.claude/commands/`, modes: `.claude/modes/`.
Project context, vault zones, rules, stack → see root `CLAUDE.md` (single source of truth).

## Modes (read the right one before starting any task)

| Mode | File | When |
|------|------|------|
| **Dev** | `.claude/modes/dev.md` | Code, tests, review, refactoring, migration, CI, deploy, bugs |
| **Spec** | `.claude/modes/spec.md` | Living product specs in `docs/direction/` |

Unclear which mode → ask the user.

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
