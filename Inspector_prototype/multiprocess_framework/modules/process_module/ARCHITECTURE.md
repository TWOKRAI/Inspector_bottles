# Архитектура ProcessModule (Refactored)

**Документация**: Фаза 9, Этап 8/8 (Завершённый рефакторинг)

---

## 1. Концепция и история

### Было (до рефакторинга)

- **565 строк** в `process_module.py` с множеством ответственностей
- **Циклическая зависимость** с `shared_resources_module`
- **Прямые импорты** из 7+ модулей
- **Нет** `interfaces.py`, `types/`, `adapters/`
- **Связанность: 2/10** — высокая тесная связь между компонентами

### Стало (после рефакторинга)

- **Модульная архитектура** с чёткой ответственностью
- **Разрыв циклической зависимости** через `ISharedResources` protocol
- **Dependency Injection** вместо прямых импортов
- **Полный набор контрактов**: `interfaces.py`, `types/`, `adapters/`
- **Связанность: 7/10** — значительное улучшение

---

## 2. Архитектурные решения (ADR)

### ADR-001: Разрыв циклической зависимости через Protocol

**Проблема:**
```
process_module → shared_resources_module (импортирует QueueRegistry, MemoryManager)
                          ↓
                    import ProcessData, ProcessStateRegistry
                    (хранят физические ресурсы — Queue, Event)
```

**Решение:** Использовать Protocol для DI:

```python
# process_module/interfaces.py
class ISharedResources(Protocol):
    """Что process_module ожидает от shared_resources."""
    
    @property
    def queue_registry(self) -> Any: ...
    
    @property
    def memory_manager(self) -> Any: ...
    
    @property
    def event_manager(self) -> Any: ...
    
    def get_process_data(self, name: str) -> Optional[Dict]: ...
    def register_process_state(self, name: str, state: dict) -> bool: ...
    def update_process_state(self, name: str, **kwargs) -> bool: ...
```

**Результат:**
```
                    process_module
                          ↓
                    (ISharedResources protocol)
                          ↓
           shared_resources_module ← однонаправленно
```

**Файлы, затронутые:**
- `process_module/interfaces.py` — определена `ISharedResources`
- `process_module/core/process_module.py` — принимает через конструктор
- `shared_resources_module/core/shared_resources_manager.py` — реализует контракт
- `process_module/state/process_data.py` — алиасы для совместимости

### ADR-002: ProcessData/ProcessStateRegistry переносятся в shared_resources_module

**Причина:** `ProcessData` и `ProcessStateRegistry` хранят **физические ресурсы** (Queue, Event):
- Они жизненно важны для всех процессов
- `shared_resources_module` — правильное место для shared ресурсов
- Это устраняет циклическую зависимость

**Новое расположение:**
```
shared_resources_module/
├── state/
│   ├── __init__.py
│   ├── process_data.py              ← (перенесено из process_module)
│   └── process_state_registry.py    ← (перенесено из process_module)
└── ...

process_module/state/
├── process_data.py                  # Алиас → shared_resources_module/state/
```

`ProcessStateRegistry` импортируется только из `shared_resources_module` (локальный shim-файл в `process_module/state/` удалён, ADR-165).

**Импорты до рефакторинга:**
```python
# process_module внутри себя
from .state.process_data import ProcessData
from .state.process_state_registry import ProcessStateRegistry
```

**Импорты после рефакторинга:**
```python
# shared_resources_module
from .state.process_data import ProcessData
from .state.process_state_registry import ProcessStateRegistry

# process_module — только ProcessData (алиас); ProcessStateRegistry — из SRM
from .state import ProcessData
from ..shared_resources_module.state import ProcessStateRegistry
```

### ADR-003: Dict at Boundary

Все данные на границе процессов передаются как обычные `dict`:

```python
# Конфигурация (граница)
config_dict = {
    "name": "process_1",
    "workers": {"worker_1": {...}},
    "modules": {...},
}

# Внутри процесса (типизированное)
config: ProcessConfigDict = config_dict
# или через Pydantic/TypedDict при необходимости
```

**Типы на границе:**
- `ProcessConfigDict` — конфигурация процесса
- `ProcessStatsDict` — статистика процесса
- `ProcessMetadataDict` — метаданные процесса

### ADR-004: ProcessStatus enum вместо строк

**Было:**
```python
self.status = "running"  # Строка — ошибки в ввода
```

**Стало:**
```python
from process_module.types import ProcessStatus

self.status = ProcessStatus.RUNNING
# или значение
self.status_str = ProcessStatus.RUNNING.value  # → "running"
```

**Преимущества:**
- ✅ Типобезопасность
- ✅ IDE автодополнение
- ✅ Документация через интеллектуальное меню

---

## 3. Структура модуля

### 3.1 Иерархия файлов

```
process_module/
│
├── __init__.py                      # Публичный API
│
├── interfaces.py                    # Публичные контракты
│   ├── IProcessModule (ABC)        # Основной интерфейс процесса
│   ├── ISharedResources (Protocol) # DI-контракт для shared_resources
│   └── IProcessCommunication (Protocol) # Контракт коммуникации
│
├── types/
│   ├── __init__.py
│   └── types.py                    # Enum и TypedDict
│       ├── ProcessStatus (Enum)
│       ├── ManagerType (Enum)
│       ├── QueueType (Enum)
│       ├── ProcessConfigDict (TypedDict)
│       ├── ProcessStatsDict (TypedDict)
│       └── ProcessMetadataDict (TypedDict)
│
├── core/
│   ├── __init__.py
│   └── process_module.py           # ProcessModule (главный класс)
│       ├── __init__(name, config, shared_resources)
│       ├── initialize() → bool
│       ├── shutdown() → bool
│       ├── run() → None
│       ├── stop() → None
│       ├── should_stop() → bool
│       ├── send_message(target, msg) → bool
│       ├── broadcast_message(msg) → bool
│       └── receive_message(timeout) → Dict|None
│
├── lifecycle/
│   ├── __init__.py
│   └── process_lifecycle.py        # ProcessLifecycle
│       ├── create(config) → ProcessModule
│       ├── initialize() → bool
│       ├── shutdown() → bool
│       └── update_status(new_status) → bool
│
├── managers/
│   ├── __init__.py
│   └── process_managers.py         # ProcessManagers
│       ├── initialize(shared_resources) → dict
│       └── get_manager(manager_type) → Manager
│
├── communication/
│   ├── __init__.py
│   └── process_communication.py    # ProcessCommunication
│       ├── send_message(target, msg)
│       ├── broadcast_message(msg)
│       ├── receive_message(timeout)
│       └── Алиасы: send/receive/broadcast_message
│
├── config/
│   ├── __init__.py
│   └── process_config_handler.py   # ProcessConfigHandler
│       ├── get_config() → ProcessConfigDict
│       ├── update_config(dict) → bool
│       └── validate_config(dict) → bool
│
├── state/
│   ├── __init__.py
│   ├── process_state.py            # ProcessState (обёртка)
│   └── process_data.py             # Алиас → shared_resources_module
│
├── threads/
│   ├── __init__.py
│   └── system_threads.py           # SystemThreads
│       ├── create_thread(name, func)
│       └── stop_all_threads()
│
├── adapters/
│   ├── __init__.py
│   ├── process_adapter.py          # ProcessAdapter(BaseAdapter)
│   │   ├── get_status() → ProcessStatus
│   │   ├── get_stats() → ProcessStatsDict
│   │   ├── send_command(cmd) → bool
│   │   └── stop() → bool
│   └── schema_adapter.py           # SchemaAdapter(ISchemaAdapter)
│       ├── adapt(schema_class) → ProcessConfigDict
│       └── adapt_instance(obj) → ProcessConfigDict
│
├── tests/
│   ├── __init__.py
│   ├── test_types.py               # 12 тестов
│   ├── test_process_lifecycle.py   # 13 тестов
│   ├── test_process_communication.py # 14 тестов
│   ├── test_process_config.py      # 10 тестов
│   └── test_process_module.py      # Интеграционные тесты
│
├── README.md                       # Документация пользователя
├── STATUS.md                       # Карточка здоровья
├── ARCHITECTURE.md                 # Этот файл
│
└── docs/                           # Архивная документация
    ├── README.md                   (дублирует корневой README)
    ├── ARCHITECTURE.md             (дублирует корневой ARCHITECTURE)
    ├── COMMUNICATION.md            (специализированная документация)
    ├── STATUS.md                   (дублирует корневой STATUS)
    └── COMPLETION_PLAN.md          (план выполнения)
```

### 3.2 Классы и их ответственность

#### ProcessModule (core/process_module.py)

```python
class ProcessModule(BaseManager, ObservableMixin):
    """Основной класс процесса."""
    
    def __init__(
        self,
        name: str,
        config: Optional[ProcessConfigDict] = None,
        shared_resources: Optional[ISharedResources] = None,
    ):
        # Параметры
        self.name = name
        self._config = config or {}
        self.shared_resources = shared_resources
        
        # Компоненты (инициализируются в initialize())
        self.worker_manager: Optional[WorkerManager] = None
        self.router_manager: Optional[RouterManager] = None
        self.logger_manager: Optional[LoggerManager] = None
        
        # Ресурсы из shared_resources (через DI)
        self.queue_registry = getattr(shared_resources, 'queue_registry', None)
        self.memory_manager = getattr(shared_resources, 'memory_manager', None)
        
        # Состояние
        self._is_initialized = False
        self._should_stop = False
```

**Ответственность:**
1. ✅ Жизненный цикл (initialize/shutdown/run/stop)
2. ✅ Координация компонентов (менеджеры, воркеры)
3. ✅ IPC (отправка/получение сообщений)
4. ✅ Мониторинг (статус, статистика)

#### ProcessLifecycle (lifecycle/process_lifecycle.py)

```python
class ProcessLifecycle:
    """Управление этапами жизненного цикла."""
    
    def initialize(self) -> bool:
        # Инициализация менеджеров
        # Инициализация конфигурации
        # Запуск системных потоков
        # Обновление статуса → READY
    
    def shutdown(self) -> bool:
        # Остановка всех воркеров
        # Очистка ресурсов
        # Закрытие очередей
        # Обновление статуса → STOPPED
```

#### ProcessManagers (managers/process_managers.py)

```python
class ProcessManagers:
    """Инициализация менеджеров процесса."""
    
    @staticmethod
    def initialize(shared_resources: ISharedResources) -> dict:
        # Создание WorkerManager
        # Создание RouterManager
        # Создание LoggerManager
        # Возврат словаря менеджеров
```

#### ProcessCommunication (communication/process_communication.py)

```python
class ProcessCommunication:
    """Межпроцессная коммуникация."""
    
    def send_message(self, target: str, message: Dict) -> bool:
        # Отправить сообщение через router_manager
    
    def broadcast_message(self, message: Dict) -> bool:
        # Трансляция всем процессам
    
    def receive_message(self, timeout: float) -> Optional[Dict]:
        # Получить сообщение из очереди
```

---

## 4. Граф зависимостей

### До рефакторинга

```
process_module
    ├──→ shared_resources_module (прямой импорт QueueRegistry)
    │        ├──→ process_module (ЦИКЛИЧЕСКАЯ!)
    │        └──→ data_schema_module
    ├──→ worker_module
    ├──→ router_module
    ├──→ logger_module
    ├──→ command_module
    ├──→ dispatch_module
    └──→ base_manager
```

**Проблема**: Циклическая зависимость process_module ↔ shared_resources_module

### После рефакторинга

```
process_module
    ├──→ (ISharedResources protocol)
    │        ↓
    │   shared_resources_module ← только для DI
    │        ├──→ data_schema_module
    │        └──→ registers_module
    ├──→ worker_module
    ├──→ router_module
    ├──→ logger_module
    ├──→ command_module
    ├──→ dispatch_module
    └──→ base_manager
```

**Решение**: Однонаправленный граф без циклов

### Полная иерархия (система)

```
process_manager_module
    ├──→ process_module (ProcessModule)
    │        ├──→ worker_module (WorkerManager)
    │        ├──→ router_module (RouterManager)
    │        └──→ logger_module (LoggerManager)
    │
    └──→ shared_resources_module
         ├──→ process_module (ISharedResources)
         └──→ ProcessData + ProcessStateRegistry
```

---

## 5. Жизненный цикл процесса

### Диаграмма состояний

```
[NOT_INITIALIZED]
        ↓
   initialize()
        ↓
[INITIALIZING] ← ProcessLifecycle.initialize()
        ↓
[READY] ← ждёт run()
        ↓
    run()
        ↓
[RUNNING] ← основной цикл while not should_stop()
        ↓
 should_stop() == True
        ↓
[STOPPING] ← начало остановки
        ↓
   shutdown()
        ↓
[STOPPED] ← ProcessLifecycle.shutdown()
        ↓
    конец
```

### Переходы

| Из | В | Метод | Условие |
|----|---|-------|---------|
| NOT_INITIALIZED | INITIALIZING | `initialize()` | Явный вызов |
| INITIALIZING | READY | `ProcessLifecycle.initialize()` успешно | ✅ return True |
| INITIALIZING | ERROR | `ProcessLifecycle.initialize()` ошибка | ❌ return False |
| READY | RUNNING | `run()` | Вход в цикл |
| RUNNING | STOPPING | `should_stop() == True` | Внешний сигнал |
| STOPPING | STOPPED | `shutdown()` завершена | ✅ return True |
| STOPPING | ERROR | `shutdown()` ошибка | ❌ return False |

---

## 6. Интеграция с другими модулями

### worker_module

```python
# ProcessModule создаёт WorkerManager
self.worker_manager = WorkerManager(
    name=self.name,
    shared_resources=self.shared_resources,
)

# Пользователь может создавать воркеры
config = ThreadConfig(priority=ThreadPriority.NORMAL)
self.worker_manager.create_worker("worker_1", func, config, auto_start=True)
```

### router_module

```python
# ProcessModule использует RouterManager для IPC
self.router_manager.send({
    "channel": "external",
    "target_process": "process_2",
    "command": "execute",
    "data": {...},
})
```

### logger_module

```python
# ProcessModule логирует через LoggerManager
self.log_info("Процесс запущен")
self.log_error("Ошибка в работе")
# или приватные методы
self._log_info("Debug информация")
```

### shared_resources_module

```python
# Через Protocol (DI)
self.queue_registry = getattr(self.shared_resources, 'queue_registry', None)
self.memory_manager = getattr(self.shared_resources, 'memory_manager', None)

# Получить данные процесса
process_data = self.shared_resources.get_process_data(self.name)
```

---

## 7. Dict at Boundary

### Конфигурация на границе

```
[Главный процесс]
       ↓
    dict конфиг
       ↓
[ProcessModule.__init__(config: ProcessConfigDict)]
       ↓
   [Внутри процесса]
   ├── Pydantic модели (если нужно)
   ├── TypedDict (для типизации)
   └── Обычные dict (для работы)
```

### Типы на границе

```python
from typing import TypedDict, Dict, Any, Optional, List

class ProcessConfigDict(TypedDict, total=False):
    """Конфигурация процесса (на границе)."""
    name: str
    process: Dict[str, Any]      # Параметры процесса
    managers: Dict[str, Any]     # Конфиг менеджеров
    modules: Dict[str, Any]      # Подмодули
    workers: Dict[str, Any]      # Конфиг воркеров
    custom: Dict[str, Any]       # Пользовательские параметры

class ProcessStatsDict(TypedDict, total=False):
    """Статистика процесса (на границе)."""
    name: str
    running: bool
    queues: Dict[str, Any]       # Информация об очередях
    workers: Dict[str, Any]      # Информация о воркерах
    memory: Optional[Dict[str, Any]]

class ProcessMetadataDict(TypedDict, total=False):
    """Метаданные процесса (на границе)."""
    name: str
    status: str                   # "running", "stopped", etc.
    uptime: float
    worker_count: int
    error_count: int
```

---

## 8. Безопасность типов

### Типизация в interfaces.py

```python
from typing import Protocol, Optional, Dict, Any, List

class IProcessModule(ABC):
    """Публичный контракт процесса."""
    
    @abstractmethod
    def initialize(self) -> bool: ...
    
    @abstractmethod
    def send_message(self, target: str, message: Dict[str, Any]) -> bool: ...

class ISharedResources(Protocol):
    """Контракт shared_resources для DI."""
    
    @property
    def queue_registry(self) -> Any: ...
    
    def get_process_data(self, name: str) -> Optional[Dict]: ...

class IProcessCommunication(Protocol):
    """Контракт коммуникации."""
    
    def send_message(self, target: str, message: Dict[str, Any]) -> bool: ...
    def receive_message(self, timeout: float) -> Optional[Dict]: ...
    def broadcast_message(self, message: Dict[str, Any]) -> bool: ...
```

### Использование типизации

```python
def create_process(
    name: str,
    config: ProcessConfigDict,
    shared_resources: Optional[ISharedResources] = None,
) -> IProcessModule:
    """Создать процесс с типизацией."""
    process = ProcessModule(name, config, shared_resources)
    return process  # Type: IProcessModule
```

---

## 9. Тестирование и примеры

### Unit-тесты (49 тестов)

```
tests/
├── test_types.py (12)              ✓ Enum, TypedDict, pickle
├── test_process_lifecycle.py (13)  ✓ initialize/shutdown/run/stop
├── test_process_communication.py (14) ✓ send/receive/broadcast
└── test_process_config.py (10)     ✓ get/update config
```

### Интеграционные примеры

```python
# Простой процесс
class MyProcess(ProcessModule):
    def run(self):
        while not self.should_stop():
            self.log_info("Работаю...")
            time.sleep(1)

# Процесс с воркерами
class ProcessWithWorkers(ProcessModule):
    def initialize(self) -> bool:
        config = ThreadConfig(priority=ThreadPriority.NORMAL)
        self.worker_manager.create_worker(
            "worker_1",
            lambda stop, pause: self.worker_func(stop, pause),
            config,
            auto_start=True,
        )
        return True

# Процесс с коммуникацией
class Producer(ProcessModule):
    def run(self):
        for i in range(10):
            self.send_message("Consumer", {"data": i})

class Consumer(ProcessModule):
    def run(self):
        while not self.should_stop():
            msg = self.receive_message(timeout=2.0)
            if msg:
                self.log_info(f"Получено: {msg['data']}")
```

---

## 10. Производительность и оптимизация

### Оптимизация инициализации

- ✅ Lazy инициализация менеджеров в `initialize()`
- ✅ Кэширование очередей и регистров
- ✅ Минимальный overhead при создании

### Оптимизация коммуникации

- ✅ Асинхронная отправка через RouterManager
- ✅ Batch обработка сообщений в очередях
- ✅ Потокобезопасность гарантирована

### Мониторинг

- ✅ Статистика в памяти (не персистентна)
- ✅ Получение метрик через `get_stats()`
- ✅ Встроенные счётчики упреждающих событий

---

## 11. История рефакторинга (Фазы 1-8)

| Фаза | Название | Результат |
|------|----------|-----------|
| 1 | Types | ProcessStatus, ProcessConfigDict (TypedDict) |
| 2 | Interfaces | IProcessModule, ISharedResources (Protocol), IProcessCommunication |
| 3 | State refactor | ProcessData/ProcessStateRegistry перенесены в shared_resources_module |
| 4 | Core refactor | DI вместо прямых импортов, ProcessStatus enum |
| 5 | Managers + Lifecycle + Config | Убрана циклическая зависимость, lazy imports |
| 6 | Adapters | ProcessAdapter(BaseAdapter), SchemaAdapter |
| 7 | Cleanup | __init__.py, pickle-тесты, интеграция |
| 8 | Tests | 49 unit-тестов (все проходят ✓) |

---

## 12. Дополнительные ссылки

- **README.md** — пользовательская документация с примерами
- **STATUS.md** — карточка здоровья, оценки, чеклист
- **interfaces.py** — публичные контракты (основной источник истины)
- **types/types.py** — перечисления и TypedDict
- **tests/** — unit-тесты (примеры использования API)
- **Plan** — полный план рефакторинга `process_module_refactoring_40da2b2c.plan.md`
