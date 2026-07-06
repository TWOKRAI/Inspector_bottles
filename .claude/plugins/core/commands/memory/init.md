---
description: Initialize .claude/memory/ for a new project — skeleton MEMORY.md
---

Однократная инициализация структуры долговременной памяти. Запускать **один раз** на новый проект, созданный через `claude-kit-project new` (или вручную).

## Идемпотентность

Если `.claude/memory/MEMORY.md` уже существует — **ничего не делай**, сообщи "memory already initialized" и покажи `/core:memory:status`.

## Шаги

1. Создай папку `.claude/memory/` если её нет.
2. Создай `.claude/memory/MEMORY.md` — **скопируй содержимое из bundled
   seed-template** (single source of truth). Не вписывай skeleton руками,
   чтобы не дрифтить от canonical-версии.
   - Новый проект через `claude-kit-project new` уже получает `.claude/memory/MEMORY.md`
     автоматически (bootstrap материализует skeleton из плагина) — этот шаг нужен
     только для ручного bootstrap или существующего проекта без `.claude/memory/`.
   - Скопируй файл целиком из канонического плагинного skeleton:
     `cp <claude-kit>/src/claude_kit_claude/template/plugins/core/memory/MEMORY.md .claude/memory/MEMORY.md`
     (канонический плагинный путь; старый путь монолита `claude_kit` — deprecated).
3. Если в `.claude/memory/` лежит только `.gitkeep` — удали его (теперь папка не пустая).
4. Подскажи следующий шаг:
   - `/core:memory:status` — посмотреть состояние.
   - Первые записи добавятся **автоматически** по правилам "auto memory" из системного промпта: каждая запись — отдельный `.md` файл с frontmatter, плюс строка в индексе `MEMORY.md` в формате `- [Title](file.md) — hook`.

## Не делать

- Не копировать чужие memory-записи из других проектов.
- Не создавать примеры записей — пусть память наполняется органически.
