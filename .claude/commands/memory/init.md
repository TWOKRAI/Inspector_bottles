---
description: Инициализация .claude/memory/ для нового проекта — skeleton MEMORY.md
---

Однократная инициализация структуры долговременной памяти. Запускать **один раз** на новый проект, созданный через `claude-kit new` (или вручную).

## Идемпотентность

Если `.claude/memory/MEMORY.md` уже существует — **ничего не делай**, сообщи "memory already initialized" и покажи `/memory:status`.

## Шаги

1. Создай папку `.claude/memory/` если её нет.
2. Создай `.claude/memory/MEMORY.md` — **скопируй содержимое из bundled
   seed-template** (single source of truth). Не вписывай skeleton руками,
   чтобы не дрифтить от canonical-версии.
   - Предпочтительно: запусти `claude-kit init <target> --mode empty`
     (он использует `read_memory_skeleton()` под капотом).
   - Альтернатива: скопируй файл целиком из bundled seed —
     `cp <claude-kit>/src/claude_kit/template/memory/MEMORY.md .claude/memory/MEMORY.md`
     (точный путь можно найти через `python -c "from claude_kit.core.composition.skeleton import read_memory_skeleton; print(read_memory_skeleton())"`).
3. Если в `.claude/memory/` лежит только `.gitkeep` — удали его (теперь папка не пустая).
4. Подскажи следующий шаг:
   - `/memory:status` — посмотреть состояние.
   - Первые записи добавятся **автоматически** по правилам "auto memory" из системного промпта: каждая запись — отдельный `.md` файл с frontmatter, плюс строка в индексе `MEMORY.md` в формате `- [Title](file.md) — hook`.

## Не делать

- Не копировать чужие memory-записи из других проектов.
- Не создавать примеры записей — пусть память наполняется органически.
