---
description: Show the current development team — agents, models, roles
---

Покажи текущий состав агентов проекта (автообнаружение).

## Шаги

1. Прочитай содержимое `.claude/plugins/*/agents/` (агенты раскиданы по плагинам: `core`, `dev`, `knowledge`).
2. Для каждого `*.md` файла извлеки frontmatter: `name`, `model`, `description`.
3. Сгруппируй по подпапке (или по флаг-полю в frontmatter, если есть).
4. Выведи таблицу:

```
## Agents

| Категория | Агент | Модель | Когда вызывать (description) |
|-----------|-------|--------|------------------------------|
| dev       | manager     | sonnet | Декомпозиция задачи, написание ТЗ |
| dev       | developer   | sonnet | Реализация по ТЗ |
| dev       | reviewer    | opus   | Код-ревью PR |
| dev       | tester      | sonnet | Тесты по acceptance criteria |
| ...       | ...         | ...    | ... |
```

5. В конце — общая сводка:
   ```
   Всего: N агентов (по категориям: dev=K, knowledge=M, ...)
   ```

## Правила вывода

- Если frontmatter сломан — пометь агент `[malformed]` и продолжай.
- Если в подпапке только `_template.md` или `README.md` — пропусти, не считай агентом.
- Не выдумывай агентов, которых нет на диске.

## Workflow подсказки

Если есть стандартные `manager`, `developer`, `tester`, `reviewer` — подскажи стандартный pipeline:
```
/dev:plan → /dev:implement → /dev:test → [FAIL → /dev:debug] → /dev:review → /core:team:docs → /dev:ship
```

Нанять нового агента: `/core:team:hire <role>` (создаст по шаблону `.claude/plugins/core/agents/_template.md`).
