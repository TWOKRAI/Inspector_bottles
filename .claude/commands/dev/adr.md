---
description: Создать новый ADR (Architectural Decision Record) в docs/claude/DECISIONS/
---

# /adr — создание ADR через tech-writer

Запускает tech-writer-агента для создания структурированного ADR
(Architectural Decision Record) на основе текущей задачи или контекста сессии.

## Когда использовать

- Принято **архитектурное решение** (выбор фреймворка, паттерна, инструмента, схемы хранения)
- Решение **влияет на код в нескольких местах** или на будущие решения
- Хочется зафиксировать **why** + **alternatives considered** + **consequences**, чтобы через год не возвращаться к тому же спору

НЕ нужно ADR для:
- Тривиальных правок (rename, format, bugfix без обсуждения альтернатив)
- Решений уровня одного файла, очевидных из кода

## Как работает

1. Команда определяет следующий номер ADR (по `docs/claude/DECISIONS/NNNN-*.md`).
2. Берёт `.claude/templates/ADR.template.md`, подставляет `{{NUMBER}}`, `{{TITLE}}`, `{{DATE}}`, `{{AUTHORS}}`.
3. Передаёт tech-writer-агенту контекст текущей задачи + созданный скелет.
4. tech-writer заполняет секции **Context**, **Decision**, **Alternatives considered**, **Consequences** на основе истории сессии и переданных аргументов.
5. Сохраняет в `docs/claude/DECISIONS/NNNN-<slug>.md`, статус по умолчанию `PROPOSED`.

## Аргументы

- `$ARGUMENTS` — короткий заголовок ADR (kebab-case или текст). Пример: `/adr embedded-vector-store-vs-qdrant`.

## Workflow рекомендация

```
1. Обсудили решение в сессии → tech-writer уже имеет контекст.
2. /adr <title>            # создаст PROPOSED ADR
3. Прочитать ADR, отредактировать руками если нужно.
4. Сменить status на ACCEPTED после согласования.
5. В коде/CLAUDE.md/STACK.md добавить ссылку на ADR номер,
   где правило проявляется.
```

## Связанные команды

- `/spec` — продуктовое ТЗ (что делает приложение для пользователя), отдельная сущность от ADR
- `/plan` — план задачи, может ссылаться на ADR в секции "Решения (decisions log)"
- `tech-writer` (Agent tool) — пишет ADR без обёртки, если хочешь больше контроля

## Шаблон

См. `.claude/templates/ADR.template.md` — структура:
**Context → Decision → Alternatives → Consequences → Implementation pointers → Revisit when**.
