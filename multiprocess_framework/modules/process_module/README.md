# Process Module — Управление процессами в фреймворке

**Status:** ✅ Production Ready (49/49 tests passing, Refactoring Phase 8/8 Complete)

Модуль `process_module` отвечает за **создание, инициализацию, управление и мониторинг процессов** в многопроцессном фреймворке. Это центральный компонент, который координирует работу конфигурации, коммуникации, менеджеров и воркеров (через `worker_module`).

**Эталонные примеры конфигурации (plain dict):** [`docs/examples/process_config_canonical_examples.py`](docs/examples/process_config_canonical_examples.py). Поведение `ProcessConfigHandler` — в [`tests/test_process_config.py`](tests/test_process_config.py).

**Конфигурация в коде процесса:** после `initialize()` читайте параметры через **`IProcessModule.get_config` / `update_config`** или **`self.config_handler`** — это единая точка (фасад), без прямого разбора `bundle` или `SharedResourcesManager` в прикладной логике. Общая картина «schema→dict и ветки доставки»: [../../docs/CONFIG_GUIDE.md](../../docs/CONFIG_GUIDE.md).

---

## Быстрый старт

### Импорты

```python
from multiprocess_framework.modules.process_module import (
    ProcessModule,
    ProcessStatus,
    ProcessConfigDict,
)
```

### Создание простого процесса

```python
import time
from multiprocess_framework.modules.process_module import ProcessModule

class MyProcess(ProcessModule):
    def initialize(self) -> bool:
        """Инициализация процесса."""
        self.log_info("Инициализация MyProcess...")
        self.is_initialized = True
        return True

    def shutdown(self) -> bool:
        """Завершение работы процесса."""
        self.log_info("Завершение MyProcess...")
        self.is_initialized = False
        return True

    def run(self):
        """Основной цикл процесса."""
        counter = 0
        while not self.should_stop():
            counter += 1
            self.log_info(f"Итерация {counter}")
            time.sleep(1)

# Использование
process = MyProcess("my_process")
try:
    process.initialize()
    process.run()
finally:
    process.shutdown()
```

### Процесс с воркерами

```python
from multiprocess_framework.modules.worker_module import (
    ThreadConfig,
    ThreadPriority,
    ExecutionMode,
)

class WorkerProcess(ProcessModule):
    def initialize(self) -> bool:
        """Инициализация процесса с воркерами."""
        self.log_info("Инициализирую воркеры...")

        # Получить менеджер воркеров (автоматически создан ProcessModule)
        manager = self.worker_manager

        # Создать воркер обработки данных
        def data_worker(stop_event, pause_event):
            while not stop_event.is_set():
                if pause_event.is_set():
                    time.sleep(0.05)
                    continue
                self.log_info("Обработка данных...")
                time.sleep(1)

        config = ThreadConfig(
            priority=ThreadPriority.NORMAL,
            execution_mode=ExecutionMode.LOOP,
        )
        manager.create_worker("data_processor", data_worker, config, auto_start=True)

        self.is_initialized = True
        return True

    def run(self):
        """Основной цикл с мониторингом воркеров."""
        while not self.should_stop():
            status = self.worker_manager.get_all_workers_status()
            self.log_info(f"Статус воркеров: {status}")
            time.sleep(5)
```

---

## Архитектура модуля

```
process_module/
├── __init__.py                  # Публичный API
├── interfaces.py                # IProcessModule, ISharedResources, IProcessCommunication
├── types/
│   ├── __init__.py
│   └── types.py                 # ProcessStatus, ManagerType, QueueType, TypedDict
├── core/
│   ├── __init__.py
│   └── process_module.py        # ProcessModule (главный класс)
├── lifecycle/
│   ├── __init__.py
│   └── process_lifecycle.py     # Жизненный цикл: initialize/shutdown
├── managers/
│   ├── __init__.py
│   ├── process_managers.py      # Инициализация менеджеров
│   ├── observability_wiring.py  # Сшивка плоскостей: hub, стор, tap'ы, документы, отбор широких записей
│   ├── observability_flight.py  # Flight recorder: дамп кольца записей процесса по вызову (ADR-PM-037)
│   ├── observability_reload.py  # Пересборка конфига из слоёв + readback + вердикт
│   └── observability_ttl.py     # Авто-возврат рантайм-правок по истечении срока
├── communication/
│   ├── __init__.py
│   └── process_communication.py # IPC через router_module
├── config/
│   ├── __init__.py
│   └── process_config_handler.py # Парсинг конфигурации
├── state/
│   ├── __init__.py
│   └── process_state.py         # Делегирует в shared_resources_module
├── threads/
│   ├── __init__.py
│   └── system_threads.py        # Управление системными потоками
├── adapters/
│   ├── __init__.py
│   ├── process_adapter.py       # ProcessAdapter(BaseAdapter)
│   └── schema_adapter.py        # SchemaAdapter для конфигов
├── tests/                       # Unit-тесты (49 тестов)
├── README.md                    # Этот файл
├── STATUS.md                    # Карточка здоровья
└── ARCHITECTURE.md              # Детальное описание дизайна
```

---

## Ключевые концепции

### 1. Жизненный цикл процесса

```
initialize()
    ↓
[INITIALIZING] → инициализация менеджеров, воркеров, конфига
    ↓
[READY]
    ↓
run()
    ↓
[RUNNING] ← основной цикл процесса
    ↓
stop() / should_stop() → возврат True
    ↓
[STOPPING] → остановка воркеров
    ↓
shutdown()
    ↓
[STOPPED]
```

### 2. Компоненты ProcessModule

| Компонент | Класс | Назначение |
|-----------|-------|-----------|
| **Менеджер воркеров** | `WorkerManager` | Создание, управление и мониторинг потоков |
| **Маршрутизатор** | `RouterManager` | Межпроцессная коммуникация через каналы |
| **Конфиг-обработчик** | `ProcessConfigHandler` | Парсинг и валидация конфигурации |
| **Коммуникация** | `ProcessCommunication` | Отправка/получение сообщений |
| **Логгер** | `LoggerManager` | Логирование с категоризацией |

### 3. Опциональная конфигурация менеджеров (managers)

Через `proc_dict["managers"]` можно включить дополнительные возможности (все опциональны, обратная совместимость сохранена):

| Ключ | Назначение | Условие |
|------|------------|---------|
| `managers.logger` | Полный dict-конфиг LoggerManager (channels, scopes, modules) | При наличии `channels` |
| `managers.error` | ErrorManager (errors.log, critical.log, warnings.log) | При непустом dict |
| `managers.router.duplicate_messages_to_logger` | Дублирование сообщений в LoggerManager для отладки | При `True` |

Без `managers` в конфиге процессы работают как раньше (только LoggerManager, StatsManager, RouterManager по умолчанию).

### 4. Разрыв циклической зависимости (Рефакторинг)

**Проблема была:** `process_module` ↔ `shared_resources_module` (циклическая зависимость)

**Решение:** Используется `ISharedResources` (Protocol) для Dependency Injection:

```python
class ProcessModule(BaseManager, ObservableMixin):
    def __init__(
        self,
        name: str,
        config: Optional[dict] = None,
        shared_resources: Optional[ISharedResources] = None,
    ):
        self.shared_resources = shared_resources
        # Получаем через protocol, а не прямой импорт
        self.queue_registry = getattr(shared_resources, 'queue_registry', None)
        self.memory_manager = getattr(shared_resources, 'memory_manager', None)
```

Это обеспечивает **однонаправленный** граф зависимостей.

### 5. Dict at Boundary

Все данные, пересекающие границу процессов, передаются как обычные `dict`:

```python
# Конфигурация процесса (границ процесса)
config_dict = {
    "name": "process_1",
    "workers": {
        "worker_1": {
            "class": "my_module.Worker1",
            "thread": {"priority": "NORMAL"},
        }
    }
}

# Внутри процесса: типизированные объекты
process = ProcessModule("process_1", config=config_dict)
```

### 6. IPC через RouterManager

```python
# Отправить сообщение другому процессу
self.send_message(
    target="process_2",
    message={
        "command": "execute",
        "data": {"task": "compute", "value": 42},
    }
)

# Трансляция всем (broadcast)
self.broadcast_message({
    "event": "status_changed",
    "status": "running",
})
```

---

## ProcessModule API

### Жизненный цикл

```python
# Инициализация
success = process.initialize()  # → bool

# Основной цикл
process.run()  # Блокирует до stop()

# Остановка
process.stop()  # Сигнал к остановке

# Завершение
success = process.shutdown()  # → bool

# Проверка
is_stopping = process.should_stop()  # → bool
```

### Коммуникация

```python
# Отправить сообщение
process.send_message("target_process", {"command": "execute"})

# Трансляция
process.broadcast_message({"event": "ready"})

# Получить сообщение
msg = process.receive_message(timeout=1.0)
```

### Конфигурация

```python
# Получить текущую конфигурацию
config = process.get_config()  # → ProcessConfigDict

# Обновить конфигурацию
process.update_config({
    "workers": {"worker_2": {...}}
})
```

### Статистика

```python
# Получить статистику
stats = process.get_stats()  # → ProcessStatsDict
# {
#     "name": "process_1",
#     "running": True,
#     "queues": {...},
#     "workers": {...},
# }

# Получить статус
status = process.get_status()  # → ProcessStatus enum
```

### Воркеры

```python
# Получить менеджер воркеров
manager = process.worker_manager

# Создать воркер
manager.create_worker("worker_1", func, config, auto_start=True)

# Получить статус всех воркеров
all_status = manager.get_all_workers_status()
```

---

## Зависимости

- **Зависит от:**
  - `base_manager` (BaseManager)
  - `worker_module` (WorkerManager)
  - `router_module` (RouterManager)
  - `logger_module` (LoggerManager)
  - `shared_resources_module` (QueueRegistry, MemoryManager)
  - `data_schema_module` (SchemaAdapter)

- **Используется в:**
  - `process_manager_module` (оркестрация процессов)
  - `process_1`, `process_2` (прототип)

---

## Примеры

### Пример 1: Простой процесс с логированием

```python
class SimpleProcess(ProcessModule):
    def initialize(self) -> bool:
        self.counter = 0
        return True

    def run(self):
        while not self.should_stop():
            self.counter += 1
            if self.counter % 10 == 0:
                self.log_info(f"Counter: {self.counter}")
            time.sleep(0.1)

    def shutdown(self) -> bool:
        self.log_info(f"Final counter: {self.counter}")
        return True

# Запуск
process = SimpleProcess("simple")
process.initialize()
process.run()
process.shutdown()
```

### Пример 2: Процесс с коммуникацией

```python
class Producer(ProcessModule):
    def run(self):
        for i in range(10):
            self.send_message(
                "consumer",
                {"data": i}
            )
            time.sleep(1)

class Consumer(ProcessModule):
    def run(self):
        while not self.should_stop():
            msg = self.receive_message(timeout=2.0)
            if msg:
                data = msg.get("data")
                self.log_info(f"Получено: {data}")
```

### Пример 3: Процесс с воркерами и конфигом

```python
config = {
    "process": {"name": "data_processor"},
    "workers": {
        "fetcher": {
            "class": "myapp.DataFetcher",
            "thread": {
                "priority": "NORMAL",
                "execution_mode": "loop",
            }
        },
        "processor": {
            "class": "myapp.DataProcessor",
            "thread": {
                "priority": "NORMAL",
                "restart_on_failure": True,
            }
        }
    }
}

process = ProcessModule("data_processor", config=config)
process.initialize()
process.run()
process.shutdown()
```

---

## Тестирование

Модуль включает полный набор unit-тестов (49 тестов):

```bash
# Запустить все тесты process_module
pytest multiprocess_framework/modules/process_module/tests/ -v

# Запустить конкретный тест
pytest ...tests/test_process_lifecycle.py::test_initialize -v

# С покрытием
pytest ...tests/ --cov=process_module --cov-report=html
```

**Тестовое покрытие:**
- `test_types.py` (12 тестов) — Enum, TypedDict, сериализация
- `test_process_lifecycle.py` (13 тестов) — initialize/shutdown/run/stop
- `test_process_communication.py` (14 тестов) — send/receive/broadcast
- `test_process_config.py` (10 тестов) — конфигурация, обновление

---

## Стандарты и соглашения

### Потокобезопасность

Все публичные методы потокобезопасны благодаря `RouterManager`, `WorkerManager` и `LoggerManager`:

```python
# Безопасно вызывать из разных потоков
process.send_message(...)
process.log_info(...)
process.worker_manager.create_worker(...)
```

### Абстракции и интерфейсы

Внешние модули должны зависеть только от `interfaces.py`:

```python
from process_module.interfaces import IProcessModule

def manage_process(process: IProcessModule):
    process.initialize()
    process.run()
    process.shutdown()
```

### Обработка ошибок

```python
try:
    process.initialize()
    process.run()
except Exception as e:
    process.log_error(f"Ошибка процесса: {e}")
finally:
    process.shutdown()
```

---

## Структура репозитория

```mermaid
graph TD
    SharedRes["shared_resources_module"]
    Process["process_module"]
    ProcManager["process_manager_module"]
    Worker["worker_module"]
    Router["router_module"]
    Logger["logger_module"]

    Process -->|"ISharedResources<br/>protocol"| SharedRes
    Process -->|"WorkerManager"| Worker
    Process -->|"RouterManager"| Router
    Process -->|"LoggerManager"| Logger
    ProcManager -->|"ProcessModule"| Process
    ProcManager -->|"SharedResourcesManager"| SharedRes
```

---

## Наблюдаемость процесса: три файла обвязки

> Сверено **2026-08-10**, коммит `b04a0c12`. Плоскость целиком —
> [`docs/observability/`](../../docs/observability/CONNECTORS.md); здесь только то, что делает
> **этот** модуль.

Процесс не просто «имеет логгер»: он **сшивает четыре плоскости, держит слои конфигурации и умеет
отвечать, что действует сейчас**. За это отвечают три файла в `managers/` плюс три схемы в
`configs/` (`observability_config.py`, `observability_layers.py`, `observability_audit.py`).

| Файл | Что делает | Когда зовётся |
|---|---|---|
| `observability_wiring.py` | сшивает `ObservabilityHub`, `ObservabilityStore` + store-tap'ы на **оба** менеджера (`logger` и `error`), forward-tap'ы живого хвоста (keyed по subscriber), плоскость документов (`wire_document_sink`), отбор широких записей (`wire_event_selector` → `WideEventSelector`, ADR-PM-036) и политику истории (`resolve_history_policy`) | **один раз** на `initialize()` (`ProcessModule._wire_observability_hub`); ручки отбора широких записей после этого перенастраиваются пересборкой (`apply_event_selector`) |
| `observability_flight.py` | flight recorder: политика дампа (`FlightRecorder`), сшивка `wire_flight_recorder`, пересборка `apply_flight_recorder`, readback `flight_plane_report`. Кольцо берёт у логгера (`read_sink_tail`), путь — дорогой файлов журнала (`log_paths.process_log_directory`); своего кольца и своей дороги записи не заводит (ADR-PM-037) | сшивка — **один раз** на `initialize()`; ручки после этого перенастраиваются пересборкой; сам дамп — по вызову `ctx.flight_dump` |
| `observability_reload.py` | **единственное** место, где секция раскладывается (`expand_observability`) и применяется (`apply_observability_layers`): пересборка из слоёв L0→L3, readback из живых менеджеров, трёхзначный вердикт | и файловый watcher, и IPC-команда `config.reload` |
| `observability_ttl.py` | авто-возврат правок L3 по истечении срока; исполняет такт heartbeat, а не свой таймер | каждый heartbeat процесса |

**Что из этого следует практически:**

* **`observability.documents` и `observability.history` на лету не действуют.** Слои их принимают,
  но сшивка идёт только на `initialize()` — новое значение вступит в силу со следующего старта
  процесса. В `observability_reload.py` этих имён нет вовсе.
* **Пересборка — из источников, а не дельта поверх живого.** Дельта не умеет выразить «ключ удалён
  из слоя → вернись к нижнему», а с четырьмя слоями «вернуть как было» — основная операция.
* **`log_directory` приходит из машинного контекста** (`resolve_base_log_dir`: явный аргумент →
  `MULTIPROCESS_LOG_DIR` → `INSPECTOR_LOG_DIR` → `logs`) и переопределяется только явным ключом
  слоя. Иначе частичный reload уводил бы файлы логов в чужой каталог (живая находка 2026-07-22).
* **Срок правки исполняется не везде.** Процесс без heartbeat подметальщика не имеет; команда
  обязана ответить `ttl_enforced: false`, а не делать вид, что срок принят.
* **Порядок останова — часть контракта** (`lifecycle/process_lifecycle.py`):
  `console → command → router → error → stats → статус и итоговая INFO → logger последним`.
  Отказ гашения логгера не проглатывается — о нём говорит `emergency_log`.

---

## `telemetry.publish.default_enabled`: белый список одним полем (ADR-PM-039)

Секция `telemetry.publish` (`TelemetryPublishConfig`, `configs/telemetry_publish_config.py`) —
publisher-gate: какие метрики процесс считает и публикует в дерево StateStore и как часто (см.
также «Уровни плагина» ниже). До этой ручки «выключить» означало перечислить ВЕСЬ каталог метрик
поимённо — каталог per-process (5-8+ имён) и растёт молча на каждом `declare_metric`, поэтому
перечисление протухало без единого голоса.

`default_enabled: bool = True` отвечает на вопрос «что делать с метрикой, для которой в `metrics`
нет правила»:

| `default_enabled` | Поведение неперечисленной метрики |
|---|---|
| `True` (дефолт, обратная совместимость) | ВКЛЮЧЕНА с `default_interval_sec` — конфиг только сужает/переопределяет |
| `False` | ВЫКЛЮЧЕНА — секция становится белым списком; включают только явные `metrics.<имя>.enabled: true` |

**Обратная совместимость трёхзначна, а не двузначна.** Секции `telemetry` нет вовсе →
`_build_telemetry_gate()` возвращает `None` (гейта нет, легаси-путь: публикуется всё без
рейт-лимита). `telemetry.publish.default_enabled: false` → гейт ЕСТЬ и активно молчит на весь
каталог. Эти состояния выглядят похоже на первый взгляд, но физически противоположны: `_loop`
передаёт в `build_worker_telemetry` `allowed_metrics=None` («всё разрешено») в первом случае и
`allowed_metrics=set()` («ничего не разрешено») во втором.

**Слияние с рецептом.** Глобальный `telemetry.publish` (`system.yaml`) и per-process
`blueprint.processes[].telemetry` конкретного рецепта сливаются `deep_merge`'ом
(`BlueprintAssembler._resolve_telemetry`,
`multiprocess_prototype/backend/assembly/assembler.py:206-226`) — рецепт, переопределяющий только
`metrics`, НЕ стирает глобальный `default_enabled`, если сам его не задаёт.

Флип push-публикации уровней на опрос (РТ-2, `plans/telemetry-stage6.md`) — отдельный шаг:
эта ручка делает флип ВЫРАЗИМЫМ одним полем, но сама его не включает.

**Рантайм-правка в режиме `replace` (по умолчанию) СНИМАЕТ флип, если тело правки не повторяет
`default_enabled`.** `telemetry.reconfigure`/расширенный `config.reload` без `telemetry_mode:
merge` пересобирают `publish` ЦЕЛИКОМ из присланного тела; отсутствующий в теле `default_enabled`
берёт схемный дефолт (`true`), а не текущее значение живого гейта. Чтобы точечная правка (включить
одну метрику, поправить интервал) пережила флип — присылайте `telemetry_mode: merge`, либо
повторяйте `default_enabled: false` в каждой `replace`-правке. Голоса об этом нет: ответ команды
не отражает смену `default_enabled` (находка ревью Б1, закреплено
`test_telemetry_default_enabled_hazards.py::TestReplaceModeDropsDefaultEnabledSilently`).

---

## Уровни плагина: объявить и отдать (Task 3.5, ADR-PM-038)

> Сверено **2026-08-16** живым стендом `frontend/run.py` (webcam_sketch, 7 процессов + ПМ).
> Раздел отражает **вторую редакцию** ADR-PM-038 (Р3.5-11…Р3.5-15): владение стережётся при
> публикации, весь тик едет одним merge, две частоты разведены по именам.

Плагину доступны две дороги для «сколько СЕЙЧАС», и они **разные плоскости**:

| Дорога | Разъём | Куда едет | Что даёт |
|---|---|---|---|
| **Уровень** дерева состояния | `ctx.declare_metric(имя)` + `ctx.publish_metric(имя, значение)` | `processes.<процесс>.state.<имя>` сборщиком телеметрийного тика | одно текущее число, publisher-gate, опрос `introspect.telemetry → levels` |
| **Агрегат** плоскости stats | `ctx.gauge(имя, значение)` (и остальная четвёрка) | `StatsManager` → окно → стор | агрегат за окно + история |

Имена соседние намеренно и означают РАЗНОЕ: `record_metric` — счётчик за окно, `publish_metric` —
текущее значение в дерево. Путать их — тот же класс, на котором фаза уже обжигалась; развилка
названа в [ADR-PM-038](DECISIONS.md).

**Правило первое: уровень публикует фреймворк.** Прямой `state_proxy.merge` из плагина в
`processes.<p>.state` едет **мимо** publisher-гейта, мимо сборщика тика и мимо опроса. Доказано
измерением: гейт `camera_0` закрыт на `fps` (readback `enabled=false`, `gate_active=true`), за
41.1 с чисто-тиковые `latency_ms` и `shm.boundary_crossings` дали **0** дельт, а `state.fps` —
**35**, потому что его писал плагин напрямую.

**Правило второе: публикуй в СВОЁ имя.** Хранилище ключуется парой `(имя, публикатор)`, и
сборщик берёт лист, только если объявленный владелец имени равен публикатору (Р3.5-11). Пара, а не
имя: при ключе-имени сосед, опечатавшийся в имени, ЗАТИРАЛ ячейку владельца — подменить чужое число
он не мог, а уничтожить его мог (воспроизведено 2026-08-17). Публикация в чужое имя не поедет ни push'ем, ни опросом, ни при
каком состоянии гейта, и об этом будет сказано WARNING'ом один раз — с именем, публикатором и
владельцем. Раньше отбор проверял лишь «такое имя кто-нибудь объявлял», и спор двух писателей за
один лист разрешал транспорт: на продовом правиле троттла `processes.**.state.fps: 0.05` оба merge
тика попадали в одно окно 15.6-мс сетки Windows, и плагинный `fps` вырезался **всегда** — без
`rejection_reason`, то есть невидимо даже для отправителя.

**Весь тик — один `proxy.merge`** (Р3.5-12): воркеры + агрегат + `shm` + уровни плагинов в одном
payload под `processes.<name>`. Три отдельных merge были той самой парой записей, которую
арбитрировал троттл; заодно 3 IPC-сообщения на тик → 1.

**Уровень мёртвого владельца исчезает в момент смерти** (Р3.5-14): `PluginLevels.retract(owner)`
зовёт фреймворк в `ProcessModulePlugin._do_shutdown`, ПОСЛЕ пользовательского `shutdown` (плагин
вправе отдать последнее значение в нём самом). TTL и штампов свежести нет.

### Реестр НЕмигрированных писателей

Мигрирован **один** плагин — `Plugins/sources/capture` (уровни `capture_fps`, `frame_count`,
`drops`); объём выбран владельцем (Р3.5-5): механизм судится на одном настоящем потребителе, а не
на семи сразу. Остальные семь прямых писателей в `processes.<p>.state*` на HEAD 2026-08-16 —
здесь, с причиной у каждого; список сверен с фактом 2026-08-16 после второй редакции — ни один из
семи не тронут. Реестр обязан переживать задачу: без него «почему у этих гейт не работает»
пришлось бы выяснять грепом заново.

**Имя `capture_fps`, а не `fps`** (Р3.5-13): это ДВЕ разные физические величины. `fps` фреймворка —
`max(effective_hz)` по running-воркерам, то есть частота ЦИКЛА; `capture_fps` — сколько кадров в
секунду реально прочитано с камеры. Пока они ехали под одним именем, лист осциллировал бы даже при
идеальной доставке. Следствие названо: в исторической колонке `fps` у `camera_0` есть ступенька —
до 2026-08-16 измеренная частота захвата (~12.5), после частота цикла (~21.4). Миграции данных нет
намеренно; `capture_fps` персистится сам, JSON-колонкой `extra` стока телеметрии.

| Писатель | Путь | Почему не мигрирован |
|---|---|---|
| `Plugins/processing/color_mask` | `…state` (`processed_count`, `avg_latency_ms`) | **кандидат №1**: два настоящих уровня. Не тронут только объёмом задачи; `status` в том же merge — фронт |
| `Services/ml_inference` | `…state` (`last_latency_ms`, `inference_fps`, …) | уровни есть, но в том же merge едут `loaded_model` / `last_label` / `active_providers` — **не уровни, а факты и фронты**; миграция требует разделить merge, это своя задача |
| `Plugins/utility/pilot_widgets` | `…state` (`tick_count`, `tick_value` + весь регистр) | публикует **весь регистр** ради отладки пути GUI←worker; уровни здесь не цель |
| `Plugins/processing/word_layout` | `…state.word_layout` | **прогресс раскладки**, а не измерение: `word`, `next_letter`, `slots_filled` меняются событием |
| `Plugins/sources/camera_service` | `…state.cam.actual` | **actual-параметры камеры** — константы на срок сессии, меняются командой |
| `Services/control_panel` | `…state.control_panel` | блоб из ~50 контролов; **не телеметрия вовсе** |
| `Services/phone_gateway` | `…state.phone` | слово/seq (фронты) + base64-миниатюра; уровнем не является ничего |

Отдельно, **вне** этого namespace и потому вне задачи: `Plugins/calibration/camera_robot`
(`calibration.state.*`) и `Plugins/hub/device_hub` (путь из конфига).

### Границы, которые задача НЕ закрывает

* `uptime` / `status` / `pid` пишет **ProcessManager** о ЧУЖОМ процессе из своего `first_seen`.
  Опрос процесса их отдать не может по построению — это граница, а не долг (ADR-PM-038).
  `uptime` при этом крупнейший источник дельт: 83 из 158 на `camera_0` за окно замера.
* `state.pid` мёртв: `None` у всех семи процессов живьём, писателя нет (seed `bootstrap.py`).
  Задача его не оживляет и не удаляет.

---

## Версия и совместимость

- **Версия**: 2.0.0 (Refactored, Phase 8/8)
- **Python**: 3.8+
- **Зависит от**: `base_manager`, `worker_module`, `router_module`
- **Обратная совместимость**: ✅ Да (старые процессы используют ProcessModule как раньше)

---

## Ссылки

- **ARCHITECTURE.md** — детальное описание дизайна (500+ строк, диаграммы)
- **REFACTORING_ASSESSMENT.md** — честная оценка рефакторинга (до/после, выводы)
- **STATUS.md** — карточка здоровья модуля, итоговые оценки, чеклист
- **interfaces.py** — публичные контракты (IProcessModule, ISharedResources, IProcessCommunication)
- **types/types.py** — типы и перечисления (ProcessStatus, ProcessConfigDict, и т.д.)
- **Plan** — `process_module_refactoring_40da2b2c.plan.md`
