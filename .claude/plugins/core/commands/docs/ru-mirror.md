---
description: Generate a single Russian catalog of this project's factory (agents, commands, skills, modes) into docs/ru/. For a Russian-speaking owner — regenerable, so a manual translator is never needed.
---

<!-- lint-language: allow -->
<!-- This command intentionally contains Cyrillic: it specifies Russian OUTPUT
     (section headers, target filename). Whitelisted for lint_language (Task 2.3). -->

Generate `docs/ru/КАТАЛОГ.md` — one Russian-language catalog of every agent, command,
skill and mode available in this project. Goal: a Russian-speaking owner reads what the
"factory" does without opening the English prompt files.

## Source of truth

The prompt files (English) are the source of truth. This catalog is a **derived,
regenerable Russian summary** — never hand-edit it; re-run this command instead.

## Where to scan (auto-detect)

1. **Deployed project:** if `.claude/plugins/` exists →
   `.claude/plugins/*/{agents,commands,skills,modes}/**/*.md`.
2. **Seed repo (dogfooding):** else if `src/claude_kit_claude/template/plugins/` exists →
   scan that tree, plus root docs
   `src/claude_kit_claude/template/{CLAUDE,COMMIT_GUIDE,STACK,BOOTSTRAP}.md`.

## How to generate

- Prefer delegating to **Haiku** subagents (e.g. `docs-writer`, or one agent per plugin)
  — these are summaries, not logic, so the cheapest capable tier fits.
- Per file, write **1-3 Russian lines**: what it does + when it triggers.
  - **Agents:** include `model:` + role; when to call it.
  - **Commands:** slash name `/<plugin>:<subdir>:<name>` + one-line purpose.
  - **Skills:** purpose + auto-invoke trigger (from frontmatter `description`).
  - **Modes:** when to read this mode.
- Keep identifiers, slash names, paths, model IDs, tool names, flags **AS-IS** (English);
  Russian prose only.
- Group by plugin; within each plugin by type: `### Агенты` / `### Команды` /
  `### Skills` / `### Modes` (omit empty groups).

## Output

Overwrite `docs/ru/КАТАЛОГ.md` **entirely** (idempotent). Header must note: it is
generated, the regeneration command (`/core:docs:ru-mirror`), and that the English
originals under `plugins/` are the source of truth. Footer: a coverage line (how many
items catalogued).

## Verify coverage

After writing, glob the authoritative set again and confirm **every**
agent/command/skill/mode file appears in the catalog. Report any missing, then add them.

$ARGUMENTS
