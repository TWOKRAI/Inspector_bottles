# {{MODULE_NAME}} — Context

Per-module knowledge для агентов и людей. Создаётся в корне модуля
(`<package>/<module>/CONTEXT.md`). Все разделы **опциональные** — оставь
только то, что нетривиально и полезно знать перед правкой кода.

Aggregator (`scripts/aggregate_context`) собирает CONTEXT.md из всех
модулей в `docs/PROJECT_CONTEXT.md`.

---

## Purpose

Что и зачем делает модуль. 1-3 фразы. Что-то такое, что нельзя получить
быстрым взглядом на `__init__.py` / `interface.py`.

_Пример: «Координирует маршрутизацию запросов между API и worker pool.
Управляет backpressure через bounded queue. Точка входа — `dispatch()`.»_

## Key decisions

Ссылки на ADR (этого модуля или глобальные), которые формируют его дизайн.
Если ADR нет — короткая фраза-якорь.

- `ADR-{{CODE}}-001` — выбор threading-модели (см. `DECISIONS.md`)
- `ADR-007` (глобальный) — единая схема message contracts
- _или просто:_ «Использует state machine вместо callbacks из-за reentrancy»

## Gotchas

Footguns, неочевидные грабли, surprising behavior. **Это самая ценная
секция** для агента. Перечисляй то, что не следует из кода и что можно
случайно сломать.

- Не вызывать из main thread — блокирует event loop UI.
- `register()` идемпотентен только при одинаковом `(name, version)`.
  С разной version — будет тихий conflict.
- При `close()` не отменяет уже принятые задачи, только не принимает новые.

## Glossary

Local terms — слова, которые в этом модуле значат не то же самое, что
в проекте/индустрии в целом.

- **Token** — opaque worker id (НЕ JWT, НЕ access token).
- **Snapshot** — копия очереди без удаления элементов (не git snapshot).

## Open questions

То, что осознанно не решено. Когда агент видит эти вопросы — он знает,
что трогать без согласования с автором не стоит.

- [ ] Backpressure стратегия при failover между регионами — пока NO-OP.
- [ ] Метрики latency: percentile или mean? Сейчас mean.

## Migration notes

Важные миграции, на которые код или данные были перевезены. Помогает
понять артефакты («почему здесь legacy `_old_dispatch()` ещё живёт»).

- 2026-03-15 — мигрировали с `multiprocessing.Queue` на `asyncio.Queue`.
  `_old_dispatch()` оставлен для обратной совместимости до v3.0.
- 2026-05-01 — переименовали `submit()` → `enqueue()`. Старое имя удалено.

---

**Stability:** этот файл — рукописный, aggregator его НЕ перезаписывает.
Обновляй при значимых изменениях модуля. Aggregator только собирает в
сводный индекс — текст вне маркеров в `docs/PROJECT_CONTEXT.md` тоже не
трогает.
