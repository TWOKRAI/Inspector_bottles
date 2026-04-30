# queues — реестр очередей

## Назначение

Подмодуль создания и доступа к multiprocessing.Queue для межпроцессного взаимодействия. PSR (ProcessStateRegistry) — единственный source of truth (ADR-018). Pickle-safe: Queue нативно pickle-able.

## Импорты

```python
from shared_resources_module.queues import QueueRegistry
# или
from shared_resources_module.queues.core import QueueRegistry
```

## Точки входа

| Класс/метод | Описание |
|-------------|----------|
| QueueRegistry | `initialize()` | Инициализация |
| QueueRegistry | `shutdown()` | Завершение работы |
| QueueRegistry | `create_queues(queue_config)` | Создать Queue по конфигу |
| QueueRegistry | `register_process_queues(process_name, queues)` | Зарегистрировать в PSR |
| QueueRegistry | `create_and_register_queues(process_name, queue_config)` | Создать и зарегистрировать |
| QueueRegistry | `get_queue(process_name, queue_type)` | Получить очередь |
| QueueRegistry | `send_to_queue(...)` | Отправить сообщение |
| QueueRegistry | `receive_from_queue(...)` | Получить сообщение |
| QueueRegistry | `broadcast_message(...)` | Разослать всем |
| QueueRegistry | `clear_queue(queue, keep_elements)` | Очистить очередь |

## Зависимости

- **Зависит от:** `base_manager`, `shared_resources_module.core.interfaces`, `shared_resources_module.mixins`
- **Используется в:** `SharedResourcesManager`, `ProcessManagerProcess`

## Структура модуля

```
queues/
├── __init__.py           # QueueRegistry
├── interfaces.py         # Re-export IQueueRegistry
├── core/
│   ├── __init__.py
│   └── manager.py        # QueueRegistry
├── README.md
└── STATUS.md
```
