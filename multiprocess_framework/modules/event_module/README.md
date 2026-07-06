# event_module — generic typed in-proc pub/sub

Синхронная типизированная шина событий-фактов (pure Python). Диспетчеризация по
`type(event)`: подписчик на тип A получает только события типа A. Шина **не знает** о
конкретных типах событий приложения — переиспользуется любым проектом.

## Зачем

Это «событийная» ось конструктора (отдельная от команд/undo и от реактивного состояния):
- **EventBus** — «что произошло» (факты): `TopologyReplaced`, `PluginConfigChanged` и т.п.
- НЕ путать с `dispatch_module` (key→handler команды) и `state_store_module` (реактивное состояние).

Вынесен из `multiprocess_prototype/domain/event_bus.py` (carve-out 2026-06-18, правило
framework-first): прототип стал тонким потребителем через re-export, контракт `UndoRedoController`
здесь ни при чём — это независимая ось pub/sub.

## Публичный API

```python
from multiprocess_framework.modules.event_module import EventBus, EventBusProtocol, Subscription

bus = EventBus()                                  # опц. error_handler=(exc, event)->None
sub = bus.subscribe(MyEvent, handler)             # handler: (MyEvent) -> None
bus.publish(MyEvent(...))                          # синхронно всем подписчикам типа
sub.unsubscribe()                                 # или: with bus.subscribe(...) as sub: ...
```

- `subscribe(event_type, handler) -> Subscription` — порядок вызова = порядок регистрации.
- `publish(event)` — snapshot подписчиков под RLock, вызов без lock; исключение в одном
  handler не прерывает остальных (логируется или идёт в `error_handler`).
- `Subscription` — `unsubscribe()` (идемпотентный) + context-manager (`__exit__` отписывает).

## Изоляция

- **0 Qt-зависимостей** (pure Python). Qt-thread-safety — обёртка приложения (например,
  `QtEventBus` маршалит publish на main thread), не часть этого модуля.
- **0 app-зависимостей**: тип события generic (`TypeVar E` без bound) — модуль не импортирует
  доменные события приложения.

## Состав

| Файл | Что |
|------|-----|
| `event_bus.py` | `EventBus`, `_Subscription`, `ErrorHandler` |
| `interfaces.py` | `EventBusProtocol`, `Subscription` (контракты для DI/обёрток) |
| `tests/test_event_bus.py` | контракт-тесты на generic-событиях |
