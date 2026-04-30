# Dev Mode — Команда разработки

Загружается при задачах: написать код, реализовать фичу, исправить баг, рефакторинг, миграция, тесты, ревью, документация к коду.

## Pipeline

```
spec-writer → manager → developer/teamlead → tester → (debugger on FAIL) → reviewer → ship
```

Скилл `/pipeline` прогоняет цепочку целиком с failure-recovery через debugger.

## Состав команды (`.claude/agents/company/`)

| Агент | Модель | Skill | Когда вызывать |
|-------|--------|-------|----------------|
| **spec-writer** | Sonnet 4.6 | `/spec`, `/spec-sync` | Живое продуктовое ТЗ в `docs/direction/` — с точки зрения пользователя |
| **manager** | Sonnet 4.6 | `/plan` | Декомпозиция этапа → Task X.Y с уровнями сложности. НЕ пишет код |
| **developer** | Sonnet 4.6 | `/implement` | Типовая реализация Task по ТЗ (Middle/Middle+). Код + smoke-test + коммит |
| **teamlead** | Opus 4.6 | Agent tool | Senior+: архитектура, рефакторинг, интеграция. Эскалация 3-й итерации ревью/отладки |
| **tester** | Sonnet 4.6 | `/test` | Pytest по acceptance criteria из ТЗ. НЕ меняет логику |
| **debugger** | Sonnet 4.6 | `/debug` | Воспроизведение → гипотезы → root cause. Чинит в scope или выдаёт диагноз |
| **reviewer** | Opus 4.6 | `/review` | Full review (10+ файлов, архитектура, безопасность). Max 2 итерации — далее эскалация в teamlead. НЕ пишет код |
| **docs-writer** | Haiku 4.5 | `/docs` | Простая док: docstrings, README модуля, STATUS.md |
| **tech-writer** | Sonnet 4.6 | Agent tool | Сложная док: DECISIONS.md (ADR), ARCHITECTURE.md, MIGRATION_*.md, RFC-*.md |

## Граничные правила

- **developer vs teamlead** — teamlead для архитектуры/рефакторинга (Opus); developer для типовой реализации (Sonnet). Если не уверен — developer
- **reviewer vs teamlead** — reviewer только читает и указывает; teamlead пишет код (express review ≤3 файлов или Senior+ implementation)
- **docs-writer vs tech-writer** — ADR / ARCHITECTURE / MIGRATION / RFC → tech-writer; всё остальное → docs-writer
- **3 итерации — стоп** — reviewer не даёт апрув → teamlead эскалация; debugger не нашёл root cause за 3 гипотезы → teamlead эскалация
- **Параллельное делегирование** — при независимых подзадачах вызывай агентов в одном сообщении (несколько Agent tool calls), не последовательно

## Типовые сценарии

```
Задача средней сложности         →  /pipeline
Новая фича — отдельными шагами   →  /plan  →  /implement  →  /test  →  /review  →  /ship
Архитектурное решение / рефактор →  teamlead через Agent tool (без skill-обёртки)
Падающий тест / регрессия        →  /debug
ADR / migration guide            →  tech-writer через Agent tool
Живое ТЗ для apps/*              →  /spec  → пользователь редактирует → /spec-sync
Быстрая проверка диффа           →  /ship  (тесты + линтер + diff review)
Состав команды                   →  /team
```

## Правила координации

Координатор (Opus) НЕ пишет код сам, если задача делегируется. Роли:
- Opus — читает ТЗ пользователя, планирует стратегию, делегирует, проверяет результат агентов
- Sonnet-агенты — heavy lifting в своих контекстных окнах (developer, tester, manager, debugger)
- Opus-агенты — критические решения (reviewer, teamlead)

Исключение: если задача тривиальная (<30 строк, один файл) — координатор может сделать сам без делегирования.

## Plans hierarchy

Plans хранятся по scope — не смешивать:
- `workspace/plans/` — cross-cutting (roadmap, фазы, миграции между apps)
- `apps/{app}/plans/` — per-app
- `projects/{slug}/plans/` — per-project

Manager при `/plan` выбирает правильное место по контексту задачи.
