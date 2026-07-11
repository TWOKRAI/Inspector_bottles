---
name: zoom-out
description: Tell the agent to zoom out and give broader context or a higher-level perspective. Use when you're unfamiliar with a section of code or need to understand how it fits into the bigger picture.
disable-model-invocation: true
---

I don't know this area of code well. Go up a layer of abstraction. Give me a map of all the relevant modules and callers, using the project's domain glossary vocabulary.

Используй доступные инструменты в порядке предпочтения:
- если **graphify** подключён → `graphify:query_graph` для overview "что с чем связано" (hubs, god-nodes одной квери);
- если **sentrux** подключён → `sentrux:dsm` для матрицы зависимостей;
- если **codegraph** подключён → `codegraph_explore` для иерархии модулей + cross-cutting (перечисли модули/файлы в query);
- всегда → `qex:search_code` для семантической карты по теме;
- если MCP не подключены → `Glob` + `Read` README модулей.

Карту представь в терминах domain glossary из `CLAUDE.md` / `.claude/modes/_stack.md` — не file paths, а понятия предметной области.
