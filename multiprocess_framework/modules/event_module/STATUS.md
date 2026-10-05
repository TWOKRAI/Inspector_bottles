# event_module — Статус компонентов

**Статус:** STABLE (carve-out из `multiprocess_prototype/domain/event_bus.py` 2026-06-18, правило framework-first)

Generic typed in-proc pub/sub событий-фактов. Pure Python, 0 Qt, 0 app-зависимостей
(тип события не ограничен). Прототип — тонкий потребитель через re-export-шим
(`domain/event_bus.py`, `domain/protocols/event_bus.py`).

---

## Таблица компонентов

| Компонент | Файл | Статус | Описание |
|-----------|------|--------|----------|
| EventBus | event_bus.py | Готов | Синхронный typed pub/sub: subscribe/publish, RLock, snapshot-под-lock, default logging error-handler |
| ErrorHandler | event_bus.py | Готов | Тип callback'а `(Exception, event) -> None` |
| _Subscription | event_bus.py | Готов | Управление подпиской: unsubscribe (идемпотентный) + context-manager |
| EventBusProtocol | interfaces.py (Protocol) | Готов | Контракт pub/sub для DI и Qt-обёрток |
| Subscription | interfaces.py (Protocol) | Готов | Контракт управления подпиской |
| Subscribers | subscribers.py | Готов (Task 0.3) | Подписчики с владельцем-`IScope`: подписка — запись владельца, счётчики ошибок и отклонённых доставок (EVT-003) |

## Внешние зависимости

- stdlib (itertools, logging, threading, types, typing, weakref).
- `base_manager.interfaces` (`IScope`, `IHandle`) — только `subscribers.py` (EVT-003).

## Потребители

- `multiprocess_prototype/domain/event_bus.py` — re-export `EventBus`, `ErrorHandler` (шим).
- `multiprocess_prototype/domain/protocols/event_bus.py` — re-export `EventBusProtocol`, `Subscription` (шим).
- `multiprocess_prototype/frontend/qt_event_bus.py` — `QtEventBus` оборачивает `EventBus` (Qt-thread-marshal).

## Тесты

- `tests/test_event_bus.py` — контракт на generic-событиях (subscribe/publish, порядок,
  exception-isolation, custom error_handler, unsubscribe ctx/explicit, no-op, тип-точность, no-Qt).
- `tests/test_subscribers_acceptance.py` — слепая приёмка S1–S15 (Task 0.3).
- `tests/test_subscribers.py` — опасности: `add` против `owner.close()`, `_Release` из финализатора под локом.
