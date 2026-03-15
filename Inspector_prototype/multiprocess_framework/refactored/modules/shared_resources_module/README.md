# shared_resources_module

**Этап:** 8/8 | **Статус:** Production-ready

Pickle-safe «записная книжка» для межпроцессного взаимодействия.
Создаётся в ProcessManager, заполняется через `register_process()`, передаётся напрямую в дочерние процессы через pickle.

---

## Быстрый старт

```python
from shared_resources_module import SharedResourcesManager

# 1. Создать и инициализировать
srm = SharedResourcesManager()
srm.initialize()

# 2. Зарегистрировать процессы (единая точка — ADR-018)
srm.register_process("camera", {
    "queues": {
        "system": {"maxsize": 100},
        "data": {"maxsize": 50},
    },
    "events": ["custom_event"],
})

# 3. Передать в дочерний процесс (pickle-safe)
from multiprocessing import Process

def worker(srm):
    srm.reinitialize_in_child()  # восстановить non-pickle ресурсы
    config = srm.get_process_config("camera")
    q = srm.get_process_data("camera").queues.system
    q.get(timeout=1.0)

p = Process(target=worker, args=(srm,))
p.start()
```

---

## Архитектура

```
SharedResourcesManager (фасад, pickle-safe)
├── ConfigStore          — конфиги всех процессов (dict, статика)
├── ProcessStateRegistry — runtime: ProcessData с Queue/Event ссылками
├── QueueRegistry        — создание и доступ к очередям
├── EventManager         — системные события, reinitialize()
└── MemoryManager        — SharedMemory по именам, owner/consumer
```

### Pickle-safe гарантии

| Компонент | Pickle-safe? | reinitialize нужен? |
|-----------|-------------|---------------------|
| ConfigStore | ✅ (dict) | Нет |
| ProcessStateRegistry | ✅ (Queue/Event нативно) | Нет |
| QueueRegistry | ✅ | Нет |
| EventManager | ⚠️ (internal Queue теряется) | **Да** |
| MemoryManager | ✅ (только имена) | **Да** (открыть по именам) |

---

## API

### SharedResourcesManager

```python
srm.initialize() -> bool
srm.shutdown() -> bool
srm.register_process(name: str, config: dict) -> bool
srm.reinitialize_in_child() -> bool
srm.get_process_data(name: str) -> Optional[ProcessData]
srm.get_process_config(name: str) -> Optional[dict]
srm.get_process_names() -> List[str]

# Properties
srm.config_store       -> ConfigStore
srm.process_state_registry -> ProcessStateRegistry
srm.queue_registry     -> QueueRegistry
srm.event_manager      -> EventManager
srm.memory_manager     -> MemoryManager
```

### Формат config для register_process()

```python
config = {
    "queues": {
        "system": {"maxsize": 100},
        "data": {"maxsize": 50},
    },
    "events": ["custom_event"],       # дополнительные события
    "memory": {                        # опционально
        "names": {
            "frames": (4, (480, 640, 3), "uint8"),
        },
        "coll": 2,
    },
}
```

### ProcessData

```python
pd = srm.get_process_data("camera")
pd.status          # ProcessStatus.RUNNING
pd.queues.system   # multiprocessing.Queue
pd.events.stop     # multiprocessing.Event
pd.metadata        # dict
pd.custom          # dict (только пользовательские runtime-данные)
pd.to_dict()       # ProcessDataDict (без Queue/Event ссылок)
```

### Динамический доступ

```python
# Эквивалентно srm.get_process_data("camera")
pd = srm.camera
pd.queues.system.put(message)
```

---

## Типы

```python
from shared_resources_module import ProcessStatus, EventType, ResourceType

ProcessStatus.INITIALIZING | READY | RUNNING | STOPPING | STOPPED | ERROR
EventType.PROCESS_REGISTERED | PROCESS_STATE_CHANGED | QUEUE_ADDED | ...
ResourceType.QUEUE | EVENT | SHARED_MEMORY
```

---

## Тесты

```bash
pytest Inspector_prototype/multiprocess_framework/refactored/modules/shared_resources_module/tests/ -v
```

50+ тестов: types, config_store, process_data, PSR, SRM, QueueRegistry, EventManager, MemoryManager.

---

## Связь с data_schema_module

Модули не дублируют логику:

- **shared_resources_module** — runtime: ProcessData, Queue, Event, SharedMemory, ConfigStore (dict)
- **data_schema_module** — схемы, валидация, RegisterBase, ProcessDataContainer (использует ProcessData.custom)
- **DataSchemaAdapter** — тонкий мост: `srm.data_manager` → `StorageManager(shared_resources=srm)` из data_schema_module

Валидация конфигов — в config_module через data_schema_module. ConfigStore хранит только dict (Dict at Boundary).

---

## Архитектурные решения

- **ADR-017**: ConfigStore отдельно от ProcessData — разные жизненные циклы
- **ADR-018**: `register_process()` — единая точка, инкапсуляция создания ресурсов
- **ADR-019**: SharedMemory по именам — pickle-safe, owner/consumer паттерн
- **ADR-020**: `reinitialize_in_child()` — явное восстановление non-pickle ресурсов
- **ADR-021**: Прямой pickle SRM вместо ad-hoc bundle dict

Подробнее: `DECISIONS.md` (ADR-017..021), `docs/ARCHITECTURE.md`.
