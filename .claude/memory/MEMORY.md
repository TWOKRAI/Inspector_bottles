# MEMORY — index

> **Status: empty by design.** Пусто на старте, заполняется автоматически по
> правилам `auto memory` из системного промпта (или вручную через `/core:memory:init`).

## Что это

Project-local memory store — `.claude/memory/`, git-tracked, портативна вместе
с репо. Каждая запись — отдельный `.md` файл с frontmatter (`name`,
`description`, `metadata.type`, опц. `metadata.last-verified: YYYY-MM-DD`).
Этот файл — только индекс (одна строка на запись).

Правила записи/чтения, типы (`user`/`feedback`/`project`/`reference`), capture
rail — `.claude/CLAUDE.md` → «Memory (OVERRIDE)». Механический контроль —
`.claude/plugins/core/scripts/memory_lint.py`.

## Формат строки

```
- [Title in ~50 chars](filename.md) — one-line hook (whole line ≤ 150 chars)
```

Строка целиком — ≤ 150 символов (порог `line-too-long` линта). Например:

```
- [Russian-only user-facing output](feedback_russian.md) — все ответы и docs на русском
- [User is solo dev](user_role.md) — single maintainer, no team conventions
```

## Команды

- `/core:memory:init` — создать первый каркас (только в новом проекте).
- `/core:memory:status` — что сейчас лежит в `.claude/memory/`.
- `/core:memory:search <query>` — найти запись по содержанию.
- `/core:memory:remember [урок]` — захватить урок вручную.

## Секции

### Feedback
_(empty)_

### User
_(empty)_

### Project
_(empty)_

### Reference
_(empty)_

---

> Не путать с `~/.claude/projects/<project>/memory/` (нативный путь Claude
> Code) — мы намеренно переопределяем его на `.claude/memory/` ради
> портативности. Per-project, не входит в seed.
