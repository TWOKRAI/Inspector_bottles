---
description: Инициализация .claude/memory/ для нового проекта — skeleton MEMORY.md
---

Однократная инициализация структуры долговременной памяти. Запускать **один раз** на новый проект, созданный через `claude-kit new` (или вручную).

## Идемпотентность

Если `.claude/memory/MEMORY.md` уже существует — **ничего не делай**, сообщи "memory already initialized" и покажи `/memory:status`.

## Шаги

1. Создай папку `.claude/memory/` если её нет.
2. Создай `.claude/memory/MEMORY.md` со скелетом:
   ```markdown
   # MEMORY — index

   > Project-local memory store. Lives under `.claude/memory/`, tracked in git.
   > Each file is one memory; this file is just an index to them.
   > See `.claude/CLAUDE.md` → "Memory (OVERRIDE)" for write/read rules.

   ## Feedback
   _(empty)_

   ## User
   _(empty)_

   ## Project
   _(empty)_

   ## Reference
   _(empty)_
   ```
3. Если в `.claude/memory/` лежит только `.gitkeep` — удали его (теперь папка не пустая).
4. Подскажи следующий шаг:
   - `/memory:status` — посмотреть состояние.
   - Первые записи добавятся **автоматически** по правилам "auto memory" из системного промпта: каждая запись — отдельный `.md` файл с frontmatter, плюс строка в индексе `MEMORY.md` в формате `- [Title](file.md) — hook`.

## Не делать

- Не копировать чужие memory-записи из других проектов.
- Не создавать примеры записей — пусть память наполняется органически.
