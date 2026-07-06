---
description: Project long-term memory status — what's in .claude/memory/
---

Покажи текущее состояние проектной памяти.

## Шаги

1. Проверь существование `.claude/memory/`. Если нет — предложи `/core:memory:init`, остановись.
2. Прочитай `.claude/memory/MEMORY.md` (если есть).
3. `ls .claude/memory/*.md` — собери список memory-файлов кроме `MEMORY.md`.
4. Для каждого файла извлеки frontmatter (`name`, `description`, `metadata.type`).
5. Сгруппируй по типу: `user`, `feedback`, `project`, `reference`, `other` (если type не указан).

## Вывод

```
Memory: .claude/memory/
Index:  MEMORY.md (N строк)
Files:  M записей

User:        <count>
Feedback:    <count>
Project:     <count>
Reference:   <count>

Последние 3 изменённые:
- <file> (type) — description
- ...
```

Если индекс `MEMORY.md` рассинхронен с реальными файлами (есть .md без ссылки в индексе, или ссылки на несуществующие файлы) — предупреди и предложи синхронизацию.
