---
description: Показать текущий состав команды разработки — агенты, модели, роли
---

Покажи текущий состав агентов проекта (автообнаружение).

## Шаги

1. Прочитай содержимое `.claude/agents/` (и всех подпапок, если есть, например `company/`, `university/`, `domain/`).
2. Для каждого `*.md` файла извлеки frontmatter: `name`, `model`, `description`.
3. Сгруппируй по подпапке (или по флаг-полю в frontmatter, если есть).
4. Выведи таблицу:

```
## Agents

| Категория | Агент | Модель | Когда вызывать (description) |
|-----------|-------|--------|------------------------------|
| company   | manager     | opus   | Декомпозиция задачи, написание ТЗ |
| company   | developer   | sonnet | Реализация по ТЗ |
| company   | reviewer    | opus   | Код-ревью PR |
| company   | tester      | sonnet | Тесты по acceptance criteria |
| ...       | ...         | ...    | ... |
```

5. В конце — общая сводка:
   ```
   Всего: N агентов (по категориям: company=K, university=M, ...)
   ```

## Правила вывода

- Если frontmatter сломан — пометь агент `[malformed]` и продолжай.
- Если в подпапке только `_template.md` или `README.md` — пропусти, не считай агентом.
- Не выдумывай агентов, которых нет на диске.

## Workflow подсказки

Если есть стандартные `manager`, `developer`, `tester`, `reviewer` — подскажи стандартный pipeline:
```
/plan → /implement → /test → [FAIL → /debug] → /review → /docs → /ship
```

Нанять нового агента: `/hire <role>` (создаст по шаблону `.claude/agents/_template.md`).
