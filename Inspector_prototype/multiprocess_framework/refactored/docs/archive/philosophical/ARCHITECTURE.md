# Архитектура Multiprocess Framework (Refactored)

## Философия архитектуры

Система построена по **двум взаимодополняющим концепциям**:

### 1. Аналогия с живым организмом

Система функционирует как живой организм, где каждый компонент имеет четкую роль:

- **Process Manager** - Мозг (создает и управляет всеми процессами)
- **Process Module** - Организм, отделы головного мозга, каждый процесс (базовый процесс) 
- **Router Manager** - Нервная система ⭐ (связывает все компоненты) и нейроны 
- **Message Module** - Транспорт (кровь/сигналы)
- **Каналы managerRouter** - Нервы (связи к органам)
- **Менеджеры** - Органы (Worker - мышцы, Logger - память, и т.п.)
- **Workers** - Потоки (циклическая логика) 
- **Shared Resources** - Архив (хранилище)
- **Data Schema** - ДНК (параметры и конфиги)

### 2. "Тройца создания циклов" (психоанализ Фрейда)

В основе системы лежат **три главных класса**, образующих "Тройцу создания циклов":

1. **ProcessManagerCore** (Сверхэго) - управляет всеми процессами системы
2. **ProcessModule** (Эго) - базовый процесс, выполняет работу
3. **WorkerManager** (Ид) - управляет потоками внутри процесса

Эти три класса являются **основой всей системы**, все остальные менеджеры работают внутри них.

**Почему "Тройца"?**

Как в психоанализе Фрейда:
- **Сверхэго (ProcessManagerCore)** - высший уровень контроля, управляет всей системой
- **Эго (ProcessModule)** - средний уровень, выполняет работу, балансирует между требованиями имеет свою уникальность работы в
- **Ид (WorkerManager)** - низший уровень, управляет потоками выполнения, инстинктивная работа

Все три класса **наследуются от BaseManager** и используют **ObservableMixin** для единообразия.

---

## 🎯 Соответствие концепций

```
Живой организм          │  Тройца создания циклов
────────────────────────┼─────────────────────────────
Мозг (Process Manager)  │  Сверхэго (ProcessManagerCore)
Организм, отделы головного мозга (Process)      │  Эго (ProcessModule)
Мышцы (Workers)         │  Ид (WorkerManager)
Нервная система (Router)│  Коммуникация (RouterManager)
Архив (Shared Resources)│  Хранилище (ProcessData)
ДНК (Data Schema)       │  Конфигурация (ProcessData.config)
```

---

## 🏗️ Тройца создания циклов - Детальное описание

### 1. ProcessManager (Сверхэго) - Управление системой

**Роль:** Высший уровень управления, контролирует все процессы системы.Он такой же процесс на основе process_module и он всегда будет работать и он уже создает процессы и потом контроллирует все процессы и наводит коммуникации через созданные воркером менеджером потоки. 

**Аналогия:** Мозг организма - принимает решения, управляет всеми процессами.

**Ответственность:**
- Создание и управление процессами ОС
- Мониторинг состояния всех процессов
- Координация между процессами
- Управление жизненным циклом системы
- Регистрация воркеров и очередей

**Наследование:** `BaseManager + ObservableMixin`

**Компоненты:**
- `ProcessLifecycle` - жизненный цикл процессов ОС
- `ProcessPriority` - управление приоритетами процессов
- `ProcessStatus` - мониторинг статусов процессов

**Пример:**
```python
from multiprocess_framework.refactored.modules.process_manager_module import ProcessManagerCore

# ProcessManagerCore создает и управляет процессами
process_manager = ProcessManagerCore(
    manager_name="ProcessManager",
    shared_resources=shared_resources,
    queue_registry=queue_registry,
    config_manager=config_manager,
    console_manager=console_manager,
    platform_adapter=platform_adapter
)

process_manager.initialize()
process_manager.create_process("VisionProcess", "module.VisionProcess", config)
process_manager.start_process("VisionProcess")
```

---

### 2. ProcessModule (Эго) - Базовый процесс

**Роль:** Средний уровень, выполняет основную работу процесса.

**Аналогия:** Организм - выполняет работу, координирует органы (менеджеры).

**Ответственность:**
- Жизненный цикл процесса (initialize/shutdown)
- Управление менеджерами процесса (logger, command, router)
- Межпроцессная коммуникация через RouterManager
- Координация работы воркеров через WorkerManager
- Управление состоянием через ProcessStateRegistry
- Работа с конфигурацией через ConfigManager + ProcessData

**Наследование:** `BaseManager + ObservableMixin`

**Компоненты:**
- `ProcessLifecycle` - жизненный цикл процесса
- `ProcessManagers` - управление менеджерами
- `SystemThreads` - системные потоки (через WorkerManager)
- `ProcessState` - управление состоянием
- `ProcessCommunication` - коммуникация (через RouterManager)
- `ProcessConfigHandler` - обработка конфигурации

**Пример:**
```python
from multiprocess_framework.refactored.modules.process_module import ProcessModule

class VisionProcess(ProcessModule):
    def initialize(self) -> bool:
        # Инициализация процесса
        return True
    
    def run(self):
        # Основной цикл процесса
        while not self.should_stop():
            self.process_vision_data()
            time.sleep(0.1)
```

---

### 3. WorkerManager (Ид) - Управление потоками

**Роль:** Низший уровень, управляет потоками выполнения внутри процесса.

**Аналогия:** Мышцы организма - выполняют работу, циклические действия.

**Ответственность:**
- Создание и управление потоками-воркерами
- Приоритеты выполнения (SYSTEM, REALTIME, NORMAL, BATCH, BACKGROUND)
- Зависимости между воркерами
- Метрики производительности
- Автоматический перезапуск при ошибках

**Наследование:** `BaseManager + ObservableMixin`

**Компоненты:**
- `WorkerRegistry` - реестр воркеров
- `WorkerLifecycle` - жизненный цикл воркеров

**Пример:**
```python
from multiprocess_framework.refactored.modules.worker_module import (
    WorkerManager, ThreadConfig, ThreadPriority
)

# WorkerManager управляет потоками внутри процесса
worker_manager = WorkerManager("VisionProcess")
worker_manager.initialize()

def vision_worker(stop_event, pause_event):
    while not stop_event.is_set():
        process_frame()
        time.sleep(0.01)

config = ThreadConfig(priority=ThreadPriority.REALTIME)
worker_manager.create_worker("vision_processor", vision_worker, config, auto_start=True)
```

---

## Взаимосвязь трех классов

### Иерархическая структура

```
ProcessManagerCore (Сверхэго) - Мозг системы
    │
    ├── Создает и управляет ──┐
    │                          │
    └── ProcessModule (Эго)    │  Организм процесса
        │                       │
        ├── Использует ─────────┘
        │
        └── WorkerManager (Ид)  Мышцы процесса
            │
            └── Управляет потоками внутри процесса
```

### Иерархия управления

1. **ProcessManagerCore** (Сверхэго) создает **ProcessModule** (процессы ОС)
2. **ProcessModule** (Эго) использует **WorkerManager** (потоки внутри процесса)
3. **WorkerManager** (Ид) управляет потоками выполнения

### ProcessManagerProcess - Особый случай

**ProcessManagerProcess** - это ProcessModule (Эго), который управляет другими процессами:

```
ProcessManagerProcess (Эго)
    │
    ├── Наследуется от ProcessModule
    │
    ├── Использует ProcessManagerCore (Сверхэго) для управления
    │
    └── Имеет WorkerManager (Ид) для мониторинга:
        │
        ├── state_monitor - отслеживает состояния процессов
        ├── priority_command_processor - обрабатывает команды
        ├── normal_command_processor - обычные команды
        └── batch_processor - batch операции
```

**Важно:** ProcessManagerProcess сам является процессом (Эго), но использует ProcessManagerCore (Сверхэго) для управления другими процессами.

### Жизненный цикл системы

```
1. ProcessManagerCore.initialize()
   └── Настройка платформы
   └── Инициализация компонентов

2. ProcessManagerCore.create_process()
   └── Создание ProcessData в SharedResources
   └── Регистрация очередей через QueueRegistry
   └── Создание процесса ОС через Process()

3. ProcessManagerCore.start_process()
   └── Запуск процесса ОС
   └── ProcessModule.initialize() (в дочернем процессе)
       └── ProcessLifecycle.initialize()
       └── ProcessManagers.initialize()
           └── WorkerManager.initialize()
           └── LoggerManager.initialize()
           └── CommandManager.initialize()
           └── RouterManager.initialize()
       └── SystemThreads.initialize()
           └── WorkerManager.create_worker("message_processor", ...)
       └── ProcessState.register()

4. ProcessModule.run()
   └── WorkerManager.start_all_workers()
   └── Основной цикл процесса

5. ProcessManagerCore.stop_process()
   └── ProcessModule.shutdown()
       └── WorkerManager.shutdown()
       └── Остановка всех воркеров
   └── Завершение процесса ОС
```

---

## Единая база - BaseManager

Все три главных класса наследуются от **BaseManager**, что обеспечивает:

### ✅ Единообразие

- Стандартный жизненный цикл (initialize/shutdown)
- Единый интерфейс для всех менеджеров
- ObservableMixin для логирования и мониторинга

### ✅ Архитектурная чистота

```
BaseManager (универсальная база)
    ├── ProcessManager (Сверхэго)
    ├── ProcessModule (Эго)
    └── WorkerManager (Ид)
```

Все три класса - это менеджеры с единым интерфейсом!

---

## Остальные менеджеры и компоненты

Все остальные менеджеры работают **внутри** ProcessModule:

```
ProcessModule (Эго)
    │
    ├── Менеджеры (органы организма):
    │   ├── WorkerManager (Ид) - потоки (мышцы)
    │   ├── LoggerManager - логирование (память)
    │   ├── CommandManager - команды (исполнительная система)
    │   └── RouterManager - маршрутизация (нервная система)
    │
    ├── Компоненты взаимодействия:
    │   ├── ProcessState - состояние (через ProcessStateRegistry)
    │   ├── ProcessCommunication - коммуникация (через RouterManager)
    │   └── ProcessConfigHandler - конфигурация (через ConfigManager + ProcessData)
    │
    └── Взаимодействие с SharedResources:
        ├── ConfigManager - конфигурация (через ProcessData.config)
        ├── QueueRegistry - реестр очередей
        ├── ProcessStateRegistry - состояния процессов
        ├── EventManager - события системы
        └── MemoryManager - разделенная память
```

Все менеджеры также наследуются от BaseManager для единообразия.

---

## Shared Resources Module - Архив системы

**Роль:** Легковесный контейнер (архив) для передачи между процессами.

**Аналогия:** Архив организма - хранит данные всех процессов.

**Ответственность:**
- Хранение ProcessData всех процессов
- Управление очередями процессов
- Управление разделенной памятью
- Распространение событий системы
- Интеграция с data_schema для работы с данными компонентов

**Наследование:** `BaseManager + ObservableMixin`

**Компоненты:**
- `SharedResourcesManager` - главный менеджер (архив)
- `ProcessStateRegistry` - реестр состояний процессов (из Process_module)
- `EventManager` - менеджер событий
- `QueueRegistry` - реестр очередей
- `MemoryManager` - менеджер разделенной памяти
- `DataSchemaAdapter` - адаптер для data_schema модуля

**Интерфейсы:**
- `ISharedResourcesManager` - главный менеджер
- `IQueueRegistry` - реестр очередей
- `IEventManager` - менеджер событий
- `IMemoryManager` - менеджер памяти
- `IProcessStateRegistry` - реестр процессов

**Пример:**
```python
from multiprocess_framework.refactored.modules.shared_resources_module import (
    SharedResourcesManager,
    QueueRegistry,
    MemoryManager,
    EventManager,
    EventType
)

# Создание менеджера общих ресурсов
shared_resources = SharedResourcesManager()
shared_resources.initialize()

# Регистрация процесса
shared_resources.register_process_state("VisionProcess")

# Работа с очередями
queue_registry = QueueRegistry(
    process_state_registry=shared_resources.process_state_registry
)
queue_registry.initialize()
queue_registry.create_and_register_queues("VisionProcess", {
    "system": {"maxsize": 100},
    "data": {"maxsize": 50}
})

# Работа с памятью
memory_manager = MemoryManager(
    process_state_registry=shared_resources.process_state_registry
)
memory_manager.initialize()

# Работа с событиями
shared_resources.event_manager.subscribe(
    EventType.PROCESS_STATE_CHANGED,
    lambda event: print(f"Process {event['process_name']} changed")
)
```

**Взаимодействие:**
- ProcessModule использует SharedResourcesManager для доступа к данным других процессов
- ProcessManagerCore создает SharedResourcesManager и передает его в процессы
- Все менеджеры работают с ProcessStateRegistry как единственным источником истины

**Детальная документация:** [`modules/shared_resources_module/README.md`](modules/shared_resources_module/README.md)

---

## Data Schema Module - ДНК системы

**Роль:** Универсальная система работы с данными на основе Pydantic v2.

**Аналогия:** ДНК организма - параметры и конфигурация компонентов.

**Ответственность:**
- Создание схем из Pydantic моделей
- Валидация данных через Pydantic v2
- Конвертация между форматами (JSON, YAML, dict, Pydantic model)
- Работа с дефолтными значениями
- Автоматическая синхронизация с ProcessData
- Версионирование схем
- ДНК компонентов (опционально)

**Наследование:** Независимый модуль (не наследуется от BaseManager)

**Компоненты:**
- `StorageManager` - менеджер хранения данных
- `SchemaRegistry` - реестр схем
- `ModelFactory` - фабрика моделей
- `VersionManager` - менеджер версий
- `DataConverter` - конвертер данных
- `DataValidator` - валидатор данных

**Интерфейсы:**
- `IStorageManager` - менеджер хранения
- `ISchemaRegistry` - реестр схем
- `IVersionManager` - менеджер версий
- `IDataConverter` - конвертер данных
- `IDataValidator` - валидатор данных

**Пример:**
```python
from multiprocess_framework.refactored.modules.data_schema_module import (
    StorageManager,
    SchemaRegistry,
    register_schema
)
from pydantic import BaseModel

# Создание схемы
class MyComponentConfig(BaseModel):
    name: str
    enabled: bool = True

@register_schema("MyComponent")
class MyComponentSchema(MyComponentConfig):
    pass

# Работа с данными
storage = StorageManager(shared_resources=shared_resources)
storage.save_manager_data(
    process_name="MyProcess",
    manager_type="MyComponent",
    manager_name="instance1",
    data={"name": "test", "enabled": True}
)
```

**Взаимодействие:**
- SharedResourcesManager использует DataSchemaAdapter для доступа к data_schema
- ProcessData хранит данные компонентов через StorageManager
- Все менеджеры могут использовать data_schema для работы с конфигурацией

**Детальная документация:** [`modules/data_schema_module/README.md`](modules/data_schema_module/README.md)

---

### Ответственность компонентов

| Компонент | Ответственность | Через что работает |
|-----------|----------------|-------------------|
| **Threads** | Управление потоками | WorkerManager (Ид) |
| **State** | Управление состоянием | ProcessStateRegistry |
| **Communication** | Межпроцессная коммуникация | RouterManager |
| **Config** | Конфигурация процесса | ConfigManager + ProcessData (data_schema) |
| **Queues** | Очереди процессов | QueueRegistry (из SharedResources) |
| **Events** | События системы | EventManager (из SharedResources) |
| **Memory** | Разделенная память | MemoryManager (из SharedResources) |
| **Data Schema** | Данные компонентов | StorageManager (из DataSchema) |

---

## Преимущества архитектуры

### 1. Единообразие ✅

Все менеджеры наследуются от BaseManager:
- Стандартный жизненный цикл
- Единый интерфейс
- ObservableMixin для логирования

### 2. Четкая иерархия ✅ 

```
ProcessManagerCore (система) - Сверхэго (Мозг) 
    │
    └── ProcessModule (процесс) - Эго (Организм, отделы головного мозга) 
        │
        ├── WorkerManager (потоки) - Ид (Мышцы)
        │   └── Воркеры (выполнение)
        │
        ├── RouterManager - Нервная система
        ├── LoggerManager - Память
        ├── CommandManager - Исполнительная система
        └── ... (другие менеджеры)
```

### 3. Модульность ✅

Каждый класс имеет четкую ответственность:
- **ProcessManagerCore** (Сверхэго) - управление процессами системы
- **ProcessModule** (Эго) - работа процесса, координация менеджеров
- **WorkerManager** (Ид) - управление потоками внутри процесса

### 4. Разделение ответственности ✅

Каждый компонент работает через свой менеджер:
- **Threads** → через WorkerManager (Ид)
- **State** → через ProcessStateRegistry
- **Communication** → через RouterManager
- **Config** → через ConfigManager + ProcessData (data_schema)

### 5. Расширяемость ✅

Легко добавлять новые менеджеры:
- Все наследуются от BaseManager
- Используют ObservableMixin
- Стандартный жизненный цикл (initialize/shutdown)
- Могут иметь адаптеры для упрощения использования

---

## Пример полного цикла

```python
# 1. Создание ProcessManagerCore (Сверхэго)
from multiprocess_framework.refactored.modules.process_manager_module import ProcessManagerCore

# Создаем зависимости
from multiprocess_framework.modules.Shared_resources_module import SharedResourcesManager
from multiprocess_framework.modules.Config_module import ConfigManager
from multiprocess_framework.modules.Shared_resources_module.queue_registry import QueueRegistry
from multiprocess_framework.modules.Console_module import ConsoleManager
from multiprocess_framework.modules.Process_manager_module.platforms import get_platform_adapter

shared_resources = SharedResourcesManager()
config_manager = ConfigManager()
queue_registry = QueueRegistry(process_state_registry=shared_resources.process_state_registry)
console_manager = ConsoleManager()
platform_adapter = get_platform_adapter()

# Создаем ProcessManagerCore
process_manager = ProcessManagerCore(
    manager_name="ProcessManager",
    shared_resources=shared_resources,
    queue_registry=queue_registry,
    config_manager=config_manager,
    console_manager=console_manager,
    platform_adapter=platform_adapter
)
process_manager.initialize()

# 2. Создание ProcessModule (Эго)
from multiprocess_framework.refactored.modules.process_module import ProcessModule

class VisionProcess(ProcessModule):
    def initialize(self) -> bool:
        # Инициализация процесса
        return super().initialize()
    
    def _init_application_threads(self):
        # Создание воркеров через WorkerManager (Ид)
        from multiprocess_framework.refactored.modules.worker_module import (
            ThreadConfig, ThreadPriority
        )
        
        def vision_worker(stop_event, pause_event):
            while not stop_event.is_set():
                if pause_event.is_set():
                    time.sleep(0.1)
                    continue
                self.process_frame()
                time.sleep(0.01)
        
        config = ThreadConfig(priority=ThreadPriority.REALTIME)
        self.worker_manager.create_worker("vision", vision_worker, config, auto_start=True)
    
    def run(self):
        # Основной цикл процесса
        while not self.should_stop():
            time.sleep(0.1)

# 3. ProcessManagerCore создает процесс
process_manager.create_process(
    name="VisionProcess",
    class_path="VisionProcess",
    config={},
    priority="normal"
)

# 4. Запуск системы
process_manager.start_process("VisionProcess")

# 5. Мониторинг
status = process_manager.get_process_status("VisionProcess")
print(f"Process status: {status}")

# 6. Завершение
process_manager.stop_process("VisionProcess")
process_manager.shutdown()
```

## Тестирование Тройцы

Все три класса покрыты тестами:

### Юнит-тесты
- `test_worker_manager.py` - тесты для WorkerManager
- `test_process_module.py` - тесты для ProcessModule
- `test_process_manager_core.py` - тесты для ProcessManagerCore (будут добавлены)

### Интеграционные тесты
- `test_triada_integration.py` - тесты взаимодействия всех трех классов

Запуск тестов:
```bash
# Юнит-тесты
pytest src/multiprocess_framework/refactored/modules/worker_module/tests/ -v
pytest src/multiprocess_framework/refactored/modules/process_module/tests/ -v

# Интеграционные тесты
pytest src/multiprocess_framework/refactored/tests/test_triada_integration.py -v
```

---

## Выводы

### "Тройца создания циклов" - основа системы

**Тройца создания циклов** - это основа всей системы:

1. **ProcessManagerCore** (Сверхэго) - управляет системой (Мозг)
2. **ProcessModule** (Эго) - выполняет работу (Организм)
3. **WorkerManager** (Ид) - управляет потоками (Мышцы)

Все три наследуются от **BaseManager** для единообразия и используют **ObservableMixin** для логирования и мониторинга.

### Взаимодействие компонентов

Каждый компонент работает через свой менеджер:
- **Threads** → WorkerManager (Ид)
- **State** → ProcessStateRegistry (из SharedResources)
- **Communication** → RouterManager
- **Config** → ConfigManager + ProcessData (data_schema)
- **Queues** → QueueRegistry (из SharedResources)
- **Events** → EventManager (из SharedResources)
- **Memory** → MemoryManager (из SharedResources)
- **Data Schema** → StorageManager (из DataSchema)

### Преимущества архитектуры

Это обеспечивает:
- ✅ Единообразие архитектуры - все менеджеры наследуются от BaseManager
- ✅ Четкую иерархию управления - Сверхэго → Эго → Ид
- ✅ Модульность и расширяемость - легко добавлять новые компоненты
- ✅ Простоту понимания и поддержки - четкая ответственность каждого компонента
- ✅ Гибкость взаимодействия - компоненты работают через специализированные менеджеры

---

## 📚 Дополнительная документация

### Главная документация фреймворка

- **docs/ARCHITECTURE_COMPLETE.md** - полная архитектура с детальным описанием
- **docs/ARCHITECTURE_DIAGRAMS.md** - визуальные диаграммы и потоки данных
- **docs/ARCHITECTURE_INDEX.md** - индекс всей документации
- **docs/COMPLETENESS.md** - план доработки модулей
- **docs/API.md** - API документация
- **docs/MODULE_STRUCTURE.md** - стандарт структуры модулей

### Документация модулей

Каждый модуль имеет свою внутреннюю документацию:

- **base_manager/docs/** - документация BaseManager модуля
- **process_module/docs/** - документация ProcessModule (включая коммуникацию через RouterManager)
- **worker_module/docs/** - документация WorkerModule
- **process_manager_module/docs/** - документация ProcessManagerModule
- **shared_resources_module/** - документация SharedResourcesModule
  - `README.md` - основная документация
  - `docs/USAGE_EXAMPLES.md` - примеры использования
  - `EVALUATION.md` - оценка модуля
  - `core/interfaces.py` - интерфейсы модуля
- **data_schema_module/** - документация DataSchemaModule
  - `README.md` - основная документация
  - `MIGRATION.md` - руководство по миграции
  - `EVALUATION.md` - оценка модуля
  - `docs/` - детальная документация (USER_GUIDE, STRUCTURE, и др.)
- **message_module/** - документация MessageModule

### Коммуникация через RouterManager

**Важно:** Вся коммуникация между процессами, менеджерами и потоками идет через **RouterManager**, который использует **Dispatch модуль** для интеллектуальной маршрутизации сообщений.

См. `modules/process_module/docs/COMMUNICATION.md` для деталей.
