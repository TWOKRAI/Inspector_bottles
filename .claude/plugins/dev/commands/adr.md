---
description: Create a new ADR (Architectural Decision Record) in docs/decisions/
---

# /dev:adr — создание ADR через tech-writer

Запускает tech-writer-агента для создания структурированного ADR
(Architectural Decision Record) на основе текущей задачи или контекста сессии.

## Когда использовать `/dev:adr` (этот командой создаётся глобальный, cross-module ADR)

- Принято **архитектурное решение** (выбор фреймворка, паттерна, инструмента, схемы хранения)
- Решение **влияет на код в нескольких местах** или на будущие решения
- Хочется зафиксировать **why** + **alternatives considered** + **consequences**, чтобы через год не возвращаться к тому же спору
- Затрагивает **2+ модуля** или общий стек (cross-module)

НЕ нужно ADR для:
- Тривиальных правок (rename, format, bugfix без обсуждения альтернатив)
- Решений уровня одного файла, очевидных из кода

## Глобальный (`/dev:adr`) vs per-module (`DECISIONS.md`) — куда писать

| Решение | Уровень | Где живёт | Формат |
|---------|---------|-----------|--------|
| Затрагивает 2+ модуля или общий стек | Global | `docs/decisions/NNNN-<slug>.md` (создаёт `/dev:adr`) | `ADR-NNNN` |
| Внутри одного модуля (выбор паттерна, threading-модели, API shape) | Per-module | `<module>/DECISIONS.md` (создаёт агент из `.claude/plugins/core/templates/DECISIONS.template.md`) | `ADR-{CODE}-NNN` |

Per-module ADR агрегируются в `docs/PROJECT_CONTEXT.md` через
`scripts/aggregate_context` (slash-command `/core:quality:sync-context`). Глобальные ADR
живут отдельно и не индексируются этим скриптом — у них своя нумерация.

Если сомневаешься — начни с **per-module DECISIONS.md**. Поднять на глобальный
уровень всегда можно ссылкой из global ADR на module ADR.

## Как работает

1. Команда определяет следующий номер ADR (по `docs/decisions/NNNN-*.md`).
2. Берёт `.claude/plugins/core/templates/ADR.template.md`, подставляет `{{NUMBER}}`, `{{TITLE}}`, `{{DATE}}`, `{{AUTHORS}}`.
3. Передаёт tech-writer-агенту контекст текущей задачи + созданный скелет.
4. tech-writer заполняет секции **Context**, **Decision**, **Alternatives considered**, **Consequences** на основе истории сессии и переданных аргументов.
5. Сохраняет в `docs/decisions/NNNN-<slug>.md`, статус по умолчанию `PROPOSED`.

## Аргументы

- `$ARGUMENTS` — короткий заголовок ADR (kebab-case или текст). Пример: `/dev:adr embedded-vector-store-vs-qdrant`.

## Workflow рекомендация

```
1. Обсудили решение в сессии → tech-writer уже имеет контекст.
2. /dev:adr <title>            # создаст PROPOSED ADR
3. Прочитать ADR, отредактировать руками если нужно.
4. Сменить status на ACCEPTED после согласования.
5. В коде/CLAUDE.md/STACK.md добавить ссылку на ADR номер,
   где правило проявляется.
```

## Связанные команды

- `/dev:spec:spec` — продуктовое ТЗ (что делает приложение для пользователя), отдельная сущность от ADR
- `/dev:plan` — план задачи, может ссылаться на ADR в секции "Решения (decisions log)"
- `tech-writer` (Agent tool) — пишет ADR без обёртки, если хочешь больше контроля

## Шаблон

См. `.claude/plugins/core/templates/ADR.template.md` — структура:
**Context → Decision → Alternatives → Consequences → Implementation pointers → Revisit when**.
