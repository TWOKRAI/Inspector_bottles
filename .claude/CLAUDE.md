# KnowledgeOS — Project Extensions

Agents: `.claude/agents/`, commands: `.claude/commands/`, modes: `.claude/modes/`.
Project context, vault zones, rules, stack → see root `CLAUDE.md` (single source of truth).

## Modes (read the right one before starting any task)

| Mode | File | When |
|------|------|------|
| **Dev** | `.claude/modes/dev.md` | Code, tests, review, refactoring, migration, CI, deploy, bugs |
| **Knowledge** | `.claude/modes/knowledge.md` | Transcription, curation, synthesis, search, Q&A, translation |
| **Spec** | `.claude/modes/spec.md` | Living product specs in `docs/direction/` |

Mixed task (dev + knowledge) → read both. Unclear → ask the user.

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

Full list in the corresponding mode file. Key commands:

- **Dev:** `/plan`, `/implement`, `/test`, `/review`, `/debug`, `/ship`, `/pipeline`, `/team`
- **Knowledge:** `/transcribe`, `/curate`, `/synthesize`, `/search`, `/research`, `/library`, `/translate`, `/digest`, `/compress`
- **Spec:** `/spec`, `/spec-sync`
