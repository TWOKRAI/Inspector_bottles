# shared_resources_module — Архитектура

## Компонентная диаграмма

```mermaid
graph TD
    subgraph SRM_facade ["SharedResourcesManager (фасад, pickle-safe)"]
        CS["ConfigStore<br/>Dict[str, dict]<br/>конфиги всех процессов"]
        PSR["ProcessStateRegistry<br/>Dict[str, ProcessData]<br/>runtime-состояние"]
        QR["QueueRegistry<br/>создание + доступ к Queue<br/>через PSR"]
        EM["EventManager<br/>системные события<br/>reinitialize()"]
        MM["MemoryManager<br/>SharedMemory по именам<br/>owner vs consumer"]
    end

    subgraph PD ["ProcessData (в PSR)"]
        PDQ["queues: QueuesProxy<br/>system, data, broadcast..."]
        PDE["events: EventsProxy<br/>stop, pause..."]
        PDS["status: ProcessStatus"]
        PDM["metadata: dict"]
        PDC["custom: dict (runtime only)"]
    end

    PSR --> PD
    QR -->|"создает Queue,<br/>регистрирует в PSR"| PSR
    MM -->|"хранит shm.name строки<br/>в ProcessData.custom"| PSR
    EM -->|"emit через PSR<br/>при изменениях"| PSR
```

## Поток данных: регистрация процессов

```mermaid
sequenceDiagram
    participant App as main.py
    participant SL as SystemLauncher
    participant PMM as ProcessManagerProcess
    participant SRM as SharedResourcesManager
    participant P1 as ChildProcess_1

    App->>SL: add_process("camera", config_dict)
    SL->>PMM: spawn ProcessManager

    PMM->>SRM: srm = SharedResourcesManager()
    PMM->>SRM: srm.initialize()
    PMM->>SRM: srm.register_process("camera", config_dict)

    Note over SRM: 1. config_store.store("camera", config)<br/>2. PSR.register_process("camera")<br/>3. queue_registry.create_and_register_queues()<br/>4. Создать stop/pause Event<br/>5. memory_manager (если config["memory"])

    PMM->>P1: Process(target=run_fn, args=(srm,))

    Note over P1: pickle SRM → unpickle<br/>Queue/Event ссылки сохранены!
    P1->>P1: srm.reinitialize_in_child()
    P1->>P1: ProcessModule(shared_resources=srm)
```

## Pickle/Unpickle диаграмма

```mermaid
graph LR
    subgraph main ["ProcessManager (главный процесс)"]
        SRM1["SRM<br/>ConfigStore: dict ✅<br/>PSR: ProcessData + Queue/Event ✅<br/>EventManager: _event_queue ❌<br/>MemoryManager: shm names ✅"]
    end

    SRM1 -->|"pickle"| Wire["bytes через pipe"]
    Wire -->|"unpickle"| SRM2

    subgraph child ["Child Process"]
        SRM2["SRM (unpickled)<br/>ConfigStore: ✅<br/>PSR + Queue/Event: ✅<br/>EventManager: _event_queue = None<br/>MemoryManager: handles = {}"]
        SRM3["After reinitialize_in_child()<br/>EventManager: new local Queue ✅<br/>MemoryManager: opened shm handles ✅"]
        SRM2 -->|"reinitialize_in_child()"| SRM3
    end
```

## Разделение ответственностей

| Компонент | Ответственность | Pickle-safe? | reinitialize? |
|-----------|----------------|-------------|---------------|
| **ConfigStore** | Конфиги всех процессов | ✅ (dict) | Нет |
| **ProcessStateRegistry** | Runtime: статус, Queue/Event | ✅ (нативно) | Нет |
| **QueueRegistry** | Создание Queue, доступ через PSR | ✅ | Нет |
| **EventManager** | Системные события, подписки | ⚠️ | **Да** |
| **MemoryManager** | SharedMemory: owner/consumer | ✅ (имена) | **Да** |

## Многопроцессорная безопасность

1. **Нет разделяемого мутабельного состояния** — каждый процесс имеет свою копию SRM
2. **Queue** — единственный канал общения (OS pipes, thread/process safe)
3. **Event** — синхронизация через shared semaphore (process safe)
4. **SharedMemory** — каждый процесс открывает свой handle по имени
5. **Нет Lock/Manager** — не нужны, нет shared mutable state

## Файловая структура

```
shared_resources_module/
├── __init__.py                      # Чистый экспорт
├── interfaces.py                    # Реэкспорт из core/interfaces.py
├── types/
│   ├── __init__.py
│   └── types.py                     # ProcessStatus, ResourceType, EventType, TypedDict
├── core/
│   ├── interfaces.py                # ISharedResourcesManager, IConfigStore, ...
│   └── shared_resources_manager.py  # SRM (фасад)
├── state/
│   ├── process_data.py              # ProcessData (runtime: status + queues + events)
│   └── process_state_registry.py    # PSR: Dict[str, ProcessData]
├── config/
│   └── config_store.py              # ConfigStore: Dict[str, dict]
├── events/
│   ├── core/manager.py              # EventManager: emit, subscribe, reinitialize()
│   ├── interfaces.py
│   └── README.md
├── queues/
│   ├── core/manager.py              # QueueRegistry: create + access через PSR
│   ├── interfaces.py
│   └── README.md
├── memory/
│   ├── core/manager.py              # MemoryManager: shm.name, owner/consumer
│   ├── format/buffer.py              # pack/unpack изображений
│   ├── platform/shm.py               # create_shm_block, close_shm
│   ├── validation/access.py         # validate_memory_access
│   └── docs/FORMATS.md
├── adapters/
│   └── data_schema_adapter.py       # Мост к data_schema_module.StorageManager
├── registry/
│   └── data_schema_adapter.py       # Обратная совместимость → adapters/
├── mixins/
│   └── stats_mixin.py               # ManagerStatsMixin
├── tests/                           # 50+ тестов
└── docs/
    └── ARCHITECTURE.md              # Этот файл
```

## Связь с data_schema_module

**shared_resources_module** и **data_schema_module** — разные ответственности:

| shared_resources_module | data_schema_module |
|-------------------------|-------------------|
| Runtime: ProcessData, Queue, Event, SharedMemory | Схемы: RegisterBase, валидация, merge_with_defaults |
| ConfigStore — хранит dict (без валидации) | SchemaRegistry — валидирует по схемам |
| TypedDict для Dict at Boundary | Pydantic модели, field_meta |
| DataSchemaAdapter — тонкий мост | StorageManager, ProcessDataContainer — используют ProcessData.custom |

**Нет дублирования логики:**
- ConfigStore хранит только dict — валидация конфигов (если нужна) — в config_module через data_schema_module
- ProcessData — runtime-контейнер; ProcessDataContainer (data_schema) расширяет его через custom["component_dnas"]
- DataSchemaAdapter делегирует в data_schema_module.StorageManager — не содержит схемной логики
