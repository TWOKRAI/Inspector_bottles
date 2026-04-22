# events — системные события

## Назначение

Подмодуль управления системными событиями для межпроцессного взаимодействия. Pickle-safe (ADR-020): `_event_queue`, `_subscribers`, `_new_event_event` исключаются из pickle; пересоздаются через `reinitialize()` в дочернем процессе.

## Импорты

```python
from shared_resources_module.events import EventManager, EventType
# или
from shared_resources_module.events.core import EventManager
```

## Точки входа

| Класс/метод | Описание |
|-------------|----------|
| EventManager | `initialize()` | Инициализация |
| EventManager | `shutdown()` | Завершение работы |
| EventManager | `reinitialize()` | Пересоздать Queue/Event после unpickle |
| EventManager | `emit_event(event_type, process_name?, **kwargs)` | Отправить событие |
| EventManager | `subscribe(event_type, callback)` | Подписаться |
| EventManager | `unsubscribe(event_type, callback)` | Отписаться |
| EventManager | `wait_for_event(event_type?, timeout)` | Ожидать событие |

## Зависимости

- **Зависит от:** `base_manager`, `shared_resources_module.core.interfaces`, `shared_resources_module.types`, `shared_resources_module.mixins`
- **Используется в:** `SharedResourcesManager`, `ProcessManagerProcess`

## Структура модуля

```
events/
├── __init__.py           # EventManager, EventType
├── interfaces.py         # Re-export IEventManager
├── core/
│   ├── __init__.py
│   └── manager.py        # EventManager
├── README.md
└── STATUS.md
```
