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

## Subscribers — подписчики с владельцем (EVT-003)

```python
from multiprocess_framework.modules.event_module import Subscribers

pub = Subscribers("frames")
h = pub.add(on_frame, owner=scope)    # запись scope, kind="subscription", путь "<scope>/frames#<n>"
pub.emit(frame)                       # -> число доставок без исключения
```

- Закрытие `scope` или `h.close()` снимает подписку; подписчик и издатель не держат друг друга.
- `emit` — снимок под локом, вызовы вне лока, порядок `add`. Подписка, добавленная в ходе
  рассылки, в неё не попадает; снятая — в её остаток не попадает.
- Доставка в закрытого или собранного владельца не идёт и считается (`emits_after_close`).
  Счётчик уходит владельцу (`IScope.note_emits_after_close`) и попадает в отчёт `root.close()`.
- `errors` (первые 20), `error_count` — исключения подписчиков; рассылка идёт дальше.
- **Окно чужого потока:** после возврата `close()` владельца подписчик может получить ещё
  одну рассылку, начатую другим потоком раньше. В одном потоке окна нет.

## Изоляция

- **0 Qt-зависимостей** (pure Python). Qt-thread-safety — обёртка приложения (например,
  `QtEventBus` маршалит publish на main thread), не часть этого модуля.
- Зависимость: `base_manager.interfaces` (`IScope`, `IHandle`) — только для `Subscribers`.
- **0 app-зависимостей**: тип события generic (`TypeVar E` без bound) — модуль не импортирует
  доменные события приложения.

## Состав

| Файл | Что |
|------|-----|
| `event_bus.py` | `EventBus`, `_Subscription`, `ErrorHandler` |
| `interfaces.py` | `EventBusProtocol`, `Subscription` (контракты для DI/обёрток) |
| `subscribers.py` | `Subscribers` — подписчики с владельцем-областью (EVT-003) |
| `tests/test_event_bus.py` | контракт-тесты на generic-событиях |
| `tests/test_subscribers*.py` | приёмка `Subscribers` (S1–S15) и опасности (гонки, финализатор под локом) |
