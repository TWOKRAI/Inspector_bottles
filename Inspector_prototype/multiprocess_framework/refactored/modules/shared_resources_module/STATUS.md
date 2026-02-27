# Статус SharedResourcesModule (Refactored)

## ✅ Рефакторинг завершен

### Основные компоненты
- ✅ `core/shared_resources_manager.py` - SharedResourcesManager (BaseManager + ObservableMixin)
- ✅ `events/event_manager.py` - EventManager (BaseManager + ObservableMixin)
- ✅ `queues/queue_registry.py` - QueueRegistry (BaseManager + ObservableMixin)
- ✅ `memory/memory_manager.py` - MemoryManager (BaseManager + ObservableMixin)
- ✅ `registry/data_schema_adapter.py` - Адаптер для data_schema модуля
- ✅ `core/interfaces.py` - Интерфейсы для всех компонентов

### Функциональность
- ✅ Все методы из оригинального QueueManager перенесены в QueueRegistry
- ✅ Все методы из оригинального ImageMemoryManager перенесены в MemoryManager
- ✅ Все методы из оригинального EventManager перенесены в EventManager
- ✅ Поддержка записи и чтения изображений в разделенную память
- ✅ Поддержка поиска свободных индексов памяти
- ✅ Поддержка освобождения памяти
- ✅ Интеграция с ProcessStateRegistry и ProcessData
- ✅ Интеграция с RouterManager для событий

### Тесты
- ✅ `test_shared_resources_manager.py` - тесты для SharedResourcesManager
- ✅ `test_queue_registry.py` - тесты для QueueRegistry
- ✅ `test_event_manager.py` - тесты для EventManager
- ✅ `test_memory_manager.py` - тесты для MemoryManager

### Документация
- ✅ `README.md` - основная документация с примерами
- ✅ `docs/ARCHITECTURE.md` - архитектура модуля
- ✅ Все компоненты имеют docstrings

## Архитектура

### Компоненты
```
SharedResourcesManager (архив, BaseManager + ObservableMixin)
├── ProcessStateRegistry (из Process_module)
│   └── ProcessData (данные процессов через data_schema)
├── EventManager (BaseManager + ObservableMixin)
│   └── Интеграция с RouterManager
├── QueueRegistry (BaseManager + ObservableMixin)
│   └── Интеграция с ProcessStateRegistry
└── MemoryManager (BaseManager + ObservableMixin)
    └── Использует ProcessData.custom через data_schema
```

### Принципы
- ✅ БЕЗ Manager() и Lock() для кросс-платформенной совместимости
- ✅ Легковесность: SharedResourcesManager - легковесный контейнер
- ✅ data_schema: Единая точка работы с данными через адаптер
- ✅ Модульность: Каждый компонент - отдельный модуль
- ✅ Единообразие: Все менеджеры наследуются от BaseManager + ObservableMixin

## Использование

```python
from multiprocess_framework.refactored.modules.shared_resources_module import (
    SharedResourcesManager,
    QueueRegistry,
    MemoryManager,
    EventManager,
    EventType
)

# Создание менеджера общих ресурсов
shared_resources = SharedResourcesManager(
    manager_name="SharedResources",
    router_manager=router_manager  # опционально
)
shared_resources.initialize()

# Регистрация процесса
shared_resources.register_process_state("MyProcess", initial_state={"status": "ready"})

# Работа с очередями
queue_registry = QueueRegistry(
    process_state_registry=shared_resources.process_state_registry
)
queue_registry.initialize()

queue_config = {
    "system": {"maxsize": 100},
    "data": {"maxsize": 50}
}
queues = queue_registry.create_and_register_queues("MyProcess", queue_config)

# Работа с памятью
memory_manager = MemoryManager(
    process_state_registry=shared_resources.process_state_registry
)
memory_manager.initialize()

memory_config = {
    "camera_feed": (100, (480, 640, 3), np.uint8)
}
memory_manager.create_memory_dict("MyProcess", memory_config, coll=5)

# Работа с событиями
event_manager = shared_resources.event_manager
event_manager.subscribe(EventType.PROCESS_STATE_CHANGED, callback)

# Завершение
memory_manager.shutdown()
queue_registry.shutdown()
shared_resources.shutdown()
```

## Преимущества новой архитектуры

- ✅ Единообразие со всеми менеджерами системы (BaseManager + ObservableMixin)
- ✅ Автоматическое логирование через ObservableMixin
- ✅ Стандартный жизненный цикл (initialize/shutdown)
- ✅ Модульная структура (core/, events/, queues/, memory/, registry/)
- ✅ Интеграция с ProcessStateRegistry и ProcessData
- ✅ Использование data_schema для работы с данными через адаптер
- ✅ Полное покрытие тестами
- ✅ Четкие интерфейсы для всех компонентов

## Миграция из старого модуля

Старый модуль: `multiprocess_framework.modules.Shared_resources_module`
Новый модуль: `multiprocess_framework.refactored.modules.shared_resources_module`

### Изменения в API

1. **QueueManager → QueueRegistry**
   - Старый: `QueueManager(process_state_registry)`
   - Новый: `QueueRegistry(process_state_registry=process_state_registry)`
   - Добавлены методы: `initialize()`, `shutdown()`, `get_stats()`

2. **ImageMemoryManager → MemoryManager**
   - Старый: `ImageMemoryManager(process_state_registry)`
   - Новый: `MemoryManager(process_state_registry=process_state_registry)`
   - Добавлены методы: `initialize()`, `shutdown()`, `get_stats()`

3. **EventManager**
   - API остался прежним, но теперь наследуется от BaseManager + ObservableMixin
   - Добавлены методы: `initialize()`, `shutdown()`, `get_stats()`

4. **SharedResourcesManager**
   - API остался прежним, но теперь наследуется от BaseManager + ObservableMixin
   - Добавлены методы: `initialize()`, `shutdown()`, `get_stats()`

## Статус: ✅ Готов к использованию

Все компоненты рефакторены, протестированы и готовы к использованию.
