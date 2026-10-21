# Worker Module — Управление потоками в фреймворке

**Status:** ✅ Production Ready (49/49 tests passing)

Модуль `worker_module` отвечает за **создание, управление и мониторинг потоков** (threads) внутри каждого процесса. Это централизованный менеджер, который гарантирует потокобезопасность, единый жизненный цикл и мониторинг всех воркеров.

---

## Быстрый старт

### Импорты

```python
from multiprocess_framework.modules.worker_module import (
    WorkerManager,
    ThreadConfig,
    ThreadPriority,
    WorkerType,
    ExecutionMode,
)
```

### Создание и запуск воркера

```python
import time

# 1. Создать менеджер (обычно делает ProcessModule)
manager = WorkerManager("my_process")
manager.initialize()

# 2. Определить функцию воркера
def my_worker(stop_event, pause_event):
    """Цикличный воркер, обрабатывает events."""
    while not stop_event.is_set():
        if pause_event.is_set():
            time.sleep(0.05)
            continue
        print("Обработка данных...")
        time.sleep(1.0)

# 3. Создать и запустить воркер
config = ThreadConfig(
    priority=ThreadPriority.NORMAL,
    worker_type=WorkerType.APPLICATION,
    execution_mode=ExecutionMode.LOOP,
)
manager.create_worker("worker_1", my_worker, config, auto_start=True)

# 4. Мониторить статус
status = manager.get_worker_status("worker_1")
print(f"Статус: {status['status'].value}")  # → "running"

# 5. Остановить
manager.stop_worker("worker_1", timeout=5.0)
manager.shutdown()
```

### Одноразовая задача (TASK режим)

```python
def init_task(stop_event, pause_event):
    """Одноразовая инициализирующая задача."""
    print("Инициализация базы данных...")
    # выполняется один раз и завершается

config = ThreadConfig(
    execution_mode=ExecutionMode.TASK,  # ← Важно!
    worker_type=WorkerType.SYSTEM,
)
manager.create_worker("init", init_task, config, auto_start=True)

# Статус будет COMPLETED, а не STOPPED
status = manager.get_worker_status("init")
assert status['status'].value == "completed"
```

---

## Архитектура модуля

```
worker_module/
├── types/
│   ├── __init__.py
│   └── types.py              # WorkerStatus, ThreadPriority, WorkerType, ExecutionMode, WorkerInfo
├── interfaces.py             # IWorkerManager, IWorkerLifecycle, IWorkerRegistry
├── core/
│   ├── __init__.py
│   ├── thread_config.py      # ThreadConfig + Dict at Boundary
│   └── worker_manager.py     # WorkerManager (главный менеджер)
├── lifecycle/
│   ├── __init__.py
│   └── worker_lifecycle.py   # Жизненный цикл: create/start/stop/restart
├── registry/
│   ├── __init__.py
│   └── worker_registry.py    # Потокобезопасный реестр воркеров
├── adapters/
│   ├── __init__.py
│   ├── worker_adapter.py     # WorkerAdapter для процессного кода
│   └── schema_adapter.py     # Интеграция со SchemaBase конфигами
├── tests/                    # Unit-тесты (49 тестов)
├── README.md                 # Этот файл
├── STATUS.md                 # Карточка здоровья
└── ARCHITECTURE.md           # Детальное описание дизайна
```

---

## Ключевые концепции

### 1. Два типа воркеров

| Тип | Назначение | Примеры | Создание |
|-----|-----------|---------|---------|
| **SYSTEM** | Внутренние процессы фреймворка | `message_processor`, будущие `health_check` | Автоматически при инициализации |
| **APPLICATION** | Пользовательские задачи | `worker_1`, `data_processor`, `sensor_reader` | Из конфига или программно |

```python
# Системный воркер
config = ThreadConfig(worker_type=WorkerType.SYSTEM)

# Пользовательский воркер (по умолчанию)
config = ThreadConfig(worker_type=WorkerType.APPLICATION)
```

### 2. Два режима выполнения

| Режим | Поведение | Статус при завершении | Примеры |
|-------|-----------|----------------------|---------|
| **LOOP** | `run()` в бесконечном цикле, слушает `stop_event` | `STOPPED` | Постоянные: опрос, очереди |
| **TASK** | `run()` выполняется один раз и завершается | `COMPLETED` | Разовые: инициализация, миграция |

```python
# Циклический режим (по умолчанию)
config = ThreadConfig(execution_mode=ExecutionMode.LOOP)

# Режим одноразовой задачи
config = ThreadConfig(execution_mode=ExecutionMode.TASK)
```

### 3. Жизненный цикл воркера

```
create_worker()
    ↓
start_worker() [или auto_start=True]
    ↓
[RUNNING] ← pause_worker() / resume_worker()
    ↓
stop_worker() / автоперезапуск при ошибке
    ↓
[STOPPED] или [COMPLETED] или [ERROR]
```

### 4. Приоритеты и poll interval

Приоритет влияет на интервал опроса для `stop_event` и `pause_event`:

| Приоритет | Poll Interval | Применение |
|-----------|--------------|-----------|
| **SYSTEM** | 0.001s (1ms) | Критичные системные потоки |
| **REALTIME** | 0.01s (10ms) | Требует низкой задержки |
| **NORMAL** | 0.1s (100ms) | Стандартные воркеры |
| **BATCH** | 1.0s | Фоновая пакетная обработка |
| **BACKGROUND** | 5.0s | Низкоприоритетные задачи |

```python
config = ThreadConfig(priority=ThreadPriority.REALTIME)
```

---

## KeyedExecutor — исполнитель с порядком по ключу (Task 1.9a, ADR-WRK-005)

**Stability:** lite. Контракт — протокол `OrderedExecutor` (`interfaces.py`), реализация —
`keyed_executor.KeyedExecutor`. Клиенты (`CommandManager`, ProcessManager) знают только протокол.

**Purpose.** Операции, которые ждут другой процесс, не должны занимать приёмный поток. Исполнитель берёт их на
свои потоки и сохраняет порядок там, где он важен: операции с пересекающимися ключами идут строго в порядке подачи,
с непересекающимися — параллельно. `key=None` — «все ключи».

**Public API.**

| Член | Контракт |
|---|---|
| `KeyedExecutor(name, *, worker_manager, max_pending=64, serial=False, max_workers=4, should_reject=None, log=None)` | Создаёт `max_workers` (при `serial=True` — 1) постоянных SYSTEM-воркеров `keyed-<name>-<i>` через `worker_manager.create_worker(auto_start=True)`. Имя занято → `ValueError`. Отдельного `start()` нет. |
| `submit(action, key, reply, *, inline_if_idle=False) -> bool` | **Pre:** не закрыт и `should_reject()` не `True`, иначе `reply(system_stopping)` на вызывающем потоке, `False`. **Post:** `reply` ровно раз — результат / `{"success": False, "error": "<тип>: <текст>"}` / `system_stopping` / `executor_busy`. `True` — в очереди; `False` — `reply` уже вызван. Никогда не блокирует. |
| `request_stop()` | Закрыть приём, снять очередь (каждой — `system_stopping`). Идемпотентен. |
| `join_until(deadline) -> bool` | Ждать текущие операции и выход рабочих до `time.monotonic()`-срока; `False` + WARNING с именами операций. |
| `shutdown(deadline) -> bool` | `request_stop(); return join_until(deadline)`. |

Правила:
- `max_pending` считает только **ждущие** операции; исполняемые не считаются. На потолке — `executor_busy`,
  один WARNING на эпизод (эпизод кончается, когда очередь опустела).
- `inline_if_idle=True`: ключ не пересекается ни с исполняемыми, ни с ждущими → `action` и `reply` на вызывающем
  потоке, `False`. Решение и захват ключа — под одним локом.
- Повторный вход (`submit` из `action` этого исполнителя): ключ ⊆ ключа текущей операции (при `serial=True` — любой)
  → на месте, как часть родителя; иначе обычная постановка. `action` не вправе ждать `reply` вложенной.
- `should_reject` зовётся в `submit` и свободными рабочими на каждом пробуждении (раз в 0,1 с) при непустой очереди —
  и когда ничего не исполнимо (ждущие за занятым ключом снимаются, не дожидаясь его); вне лока, без защёлки;
  исключение → `True`. При `serial=True` единственный рабочий занят операцией — очередь снимется после неё.
- `stop_event` воркера (`stop_all_workers`) → `request_stop()` всего исполнителя: очередь получает отказ, а не тишину.
- `BaseException` в `action` (`SystemExit`, `KeyboardInterrupt`): `reply` ровно раз (`"<тип>: <текст>"`), исключение
  идёт дальше, рабочий выходит и закрывает исполнитель — очередь получает `system_stopping`.
- После `shutdown` имя исполнителя остаётся занятым в этом `WorkerManager` (STOPPED-воркеры остаются в реестре):
  новый исполнитель на живом менеджере — с новым именем.
- Лок исполнителя не держится поверх `action`, `reply` и `should_reject`. Логи — через `logger_module.get_std_logger`
  (без LoggerManager — stdlib-логгер `multiprocess_framework.worker_module.keyed_executor.<name>`) или переданный `log`.

**Usage.**

```python
from multiprocess_framework.modules.worker_module.keyed_executor import KeyedExecutor

ex = KeyedExecutor("pm_ops", worker_manager=wm, max_workers=8)
ex.submit(lambda: start("cam1"), frozenset({"cam1"}), reply)   # параллельно с cam2
ex.submit(lambda: start("cam2"), frozenset({"cam2"}), reply)
ex.submit(lambda: apply_topology(), None, reply)               # после обеих, до всех следующих
ex.shutdown(time.monotonic() + 2.0)                            # очередь → system_stopping
```

**Boundaries.** Не знает про команды, роутер и PM; особенности PM (ожидание готовности, `still_relevant`) живут
внутри `action`. Зависит от `WorkerManager`, `ThreadConfig`. Тесты: `tests/test_keyed_executor_acceptance.py`
(слепые R1–R12b), `tests/test_keyed_executor_hazards.py` (H1a, H1b, H2, H5, H7 + контракт).

---

## ExecutorManager — именованные исполнители процесса (Task 1.9m, ADR-WRK-006)

**Stability:** lite. Контракт — протоколы `IExecutorRegistry` / `IExecutorManager` (`interfaces.py`), реализация —
`executor_manager.ExecutorManager(BaseManager, ObservableMixin)`. Экспорта из `worker_module/__init__.py` нет
(как у `KeyedExecutor`): `from ...worker_module.executor_manager import ExecutorManager, ExecutorSpec`.

**Purpose.** Один сотрудник процесса, который создаёт `KeyedExecutor` из конфига или по вызову кода, принимает готовые
объекты `OrderedExecutor` по имени, отдаёт их `CommandManager` (`register_command(executor="io")`), владеет созданными и
показывает их в интроспекции. Не только ProcessManager: любой процесс на фреймворке получает такого же помощника.

**Как подключить.**
- *Из конфига процесса* — ключ `executors` в `proc_dict["config"]` (в `ProcessLaunchConfig` — поле `executors`; пустое
  значение из `proc_dict` снимается). `ProcessModule` вызывает `load_config` при сборке менеджеров, до любой регистрации
  команд. На запись — своя попытка: неверная запись даёт одну строку ERROR и пропускается, соседние создаются.
  Схема записи `ExecutorSpec`: `kind="keyed"`, `serial=False`, `max_workers=4` (≥ 1), `max_pending=64` (≥ 1);
  лишний ключ — отказ записи (`extra="forbid"`), а не тихий исполнитель с умолчаниями.
- *Из кода* — `create(name, spec=None, *, should_reject=None)` (`should_reject` — код, в конфиг не кладётся) или
  `register(name, executor)` для готового объекта (адаптеры-политики). Менеджер процесса лежит в
  `process.executor_manager` (слот `executors` в `ManagersBundle`; `None`, если bundle собран вручную).

```python
# конфиг процесса (ProcessLaunchConfig.executors / proc_dict["config"]["executors"])
executors = {"io": {"kind": "keyed", "max_workers": 8, "max_pending": 32}}

# из кода: после super().initialize(), до регистрации команд, которые назовут исполнитель
ex = self.executor_manager.create("lifecycle", {"serial": True}, should_reject=self._stopping)
self.executor_manager.register("submit-adapter", my_adapter)       # владелец остаётся у вызывающего
self.command_manager.register_command("camera.start", handler, executor="io", key_from="camera")
```

**Public API.**

| Член | Контракт |
|---|---|
| `get(name) -> OrderedExecutor \| None` | Объект по имени; не бросает. Это весь `IExecutorRegistry`. |
| `create(name, spec=None, *, should_reject=None)` | Имя занято → `ValueError`; неверный `spec` → `ValueError` (`<loc>: <msg>` через `; `, без входных значений); после закрытия → `RuntimeError` (допустим `ScopeClosedError`). На любом провале имя не остаётся занятым. Одна строка INFO на созданный. |
| `register(name, executor)` | Нет вызываемого `submit` → `TypeError`; имя занято → `ValueError`. Только маршрутизация по имени. |
| `load_config(section) -> list[str]` | Имена созданных. `None` / `{}` → `[]`, ни строки лога; не `Mapping` → одна строка ERROR, `[]`. |
| `names()` / `is_executor_thread(name)` | Все имена в порядке появления / текущий поток — рабочий **созданного** `name` (точное имя потока; для зарегистрированного и неизвестного — `False`). |
| `describe()` | Снимок для интроспекции (ниже). |

Имя — по правилу имени записи `Scope`: непустая `str`, без `/`, без суффикса ` (self)`.

**Владение и остановка.**
- *Созданные* менеджер отдаёт своей области (`scope.own(..., kind="executor")`); в `ProcessModule` это область
  `executor_manager-scope` внутри сегмента `work`, запись `executors` стоит сразу после `plugins`. Исполнители
  закрываются общим сроком области: сначала `request_stop` (очередь получает `system_stopping`), затем `join_until`.
  Закрытие со своего рабочего потока ждать не станет: WARNING и `False` сразу. Без области (менеджер вне `ProcessModule`)
  созданные лежат в `_unowned` и закрываются в `shutdown()` менеджера общим сроком 2,0 с.
- *Зарегистрированные* менеджер не закрывает (ни `request_stop`, ни `join_until`, даже если объект `Stoppable`): владелец
  остаётся у регистрирующего. `register` после закрытия менеджера принимается; `create` — нет.
- Процесс без исполнителей платит ноль: ни потоков, ни строк лога (объект менеджера, пустая область и одна запись в `work`).

**Интроспекция.** Команда `introspect.executors` (процесс отвечает за себя; через backend_ctl —
`send_command(<процесс>, "introspect.executors")`) возвращает `ExecutorManager.describe()`:
`{"executors": {<имя>: {...}}, "unavailable": ["pending_depth", "running_keys"]}`. Созданный: `kind`, `source`
(`config` / `code`), `serial`, `max_workers`, `max_pending`, `owned` (принят областью), `workers`
(`{<имя воркера>: {"is_alive", "status"}}`; снятый воркер — `"absent"`). Зарегистрированный: `kind="registered"`,
`source="code"`, `type`. Глубины очереди и ключей в работе нет: у `KeyedExecutor` нет публичного чтения, ядро не правилось
(`docs/claude/OPEN_QUESTIONS.md`).

**Boundaries.** `worker_module` о `command_module` не знает: `CommandManager` видит только `IExecutorRegistry` под
`TYPE_CHECKING`. Рабочие исполнителя — SYSTEM-воркеры, `worker.stop/remove/...` по IPC отвечают `protected`. Тесты:
`tests/test_executor_manager_acceptance.py`, `tests/test_executor_manager_hazards.py`; проводка процесса —
`process_module/tests/test_process_executors_acceptance.py`.

---

## ThreadConfig — Конфигурация потока

### Основные параметры

```python
config = ThreadConfig(
    priority=ThreadPriority.NORMAL,        # приоритет
    restart_on_failure=False,              # перезапускать при ошибке?
    max_restarts=3,                        # макс. перезапусков
    dependencies=["worker_0"],             # должен запуститься после
    worker_type=WorkerType.APPLICATION,    # SYSTEM или APPLICATION
    execution_mode=ExecutionMode.LOOP,     # LOOP или TASK
)
```

### Dict at Boundary (для конфигов)

```python
# Сериализация (в конфиге процесса)
config_dict = config.to_dict()
# → {
#     "priority": "NORMAL",
#     "restart_on_failure": False,
#     "max_restarts": 3,
#     "dependencies": ["worker_0"],
#     "worker_type": "application",
#     "execution_mode": "loop",
# }

# Десериализация (при создании воркера)
config = ThreadConfig.from_dict(config_dict)
```

---

## WorkerManager API

### Создание и управление

```python
# Создать воркер (не запускать)
manager.create_worker("worker_1", my_func, config, auto_start=False)

# Запустить/остановить
manager.start_worker("worker_1")
manager.stop_worker("worker_1", timeout=5.0)

# Перезагрузить
manager.restart_worker("worker_1", timeout=5.0)

# Пауза/возобновление (для LOOP режима)
manager.pause_worker("worker_1")
manager.resume_worker("worker_1")

# Групповые операции
manager.start_all_workers()
manager.stop_all_workers()
```

### Мониторинг и статистика

```python
# Получить статус одного воркера
status = manager.get_worker_status("worker_1")
# → {
#     'status': WorkerStatus.RUNNING,
#     'uptime': 123.45,
#     'successful_runs': 1000,
#     'failed_runs': 2,
#     'restart_count': 0,
# }

# Получить все воркеры и их статусы
all_status = manager.get_all_workers_status()

# Метрики производительности
metrics = manager.get_worker_metrics("worker_1")
# → {
#     'status': 'running',
#     'uptime': 123.45,
#     'poll_interval': 0.1,
#     'last_error': None,
#     'has_been_started': True,
#     'last_run_duration': 0.0050,
#     'total_runtime': 120.30,
# }

# Проверить, запущен ли
is_running = manager.is_worker_running("worker_1")

# Общая статистика
stats = manager.get_stats()
# → {
#     'total_workers': 2,
#     'running': 1,
#     'stopped': 1,
#     'failed_runs': 2,
# }
```

### Фильтрация и выборка

```python
# Получить список всех воркеров
all_names = manager.list_workers()

# Только системные воркеры
system_workers = manager.list_system_workers()

# Только прикладные воркеры
app_workers = manager.list_application_workers()

# Отфильтровать по типу
system_names = manager.list_workers(worker_type=WorkerType.SYSTEM)
```

---

## Обработка ошибок и автоперезапуск

### Автоматический перезапуск

```python
config = ThreadConfig(
    restart_on_failure=True,  # включить автоперезапуск
    max_restarts=3,          # макс 3 попытки
)
manager.create_worker("resilient_worker", my_func, config, auto_start=True)

# Если my_func бросит исключение, воркер автоматически перезагрузится
# После 3 неудачных попыток остановится с статусом ERROR
```

### Мониторинг ошибок

```python
status = manager.get_worker_status("resilient_worker")
print(f"Ошибок: {status['failed_runs']}")
print(f"Перезапусков: {status['restart_count']}")
print(f"Последняя ошибка: {status['last_error']}")
```

---

## Интеграция с ProcessModule

WorkerManager автоматически создаётся и управляется `ProcessModule`:

```python
from multiprocess_framework.modules.process_module import ProcessModule

process = ProcessModule("my_process")
process.initialize()

# WorkerManager уже создан и инициализирован
manager = process.worker_manager
# или через адаптер:
worker_adapter = process.worker_adapter

manager.create_worker("worker_1", my_func, config, auto_start=True)
```

### Чтение конфигов из SchemaBase

```python
# В конфиге процесса
workers_config = {
    "worker_1": {
        "class": "my_module.Worker1",
        "config": {"interval": 1.0},
        "thread": {
            "priority": "NORMAL",
            "execution_mode": "loop",
            "restart_on_failure": False,
            "max_restarts": 3,
        },
    },
}

# ProcessModule автоматически прочитает "thread" секцию
# и создаст ThreadConfig.from_dict(thread_dict)
```

---

## Межпоточное общение (локальный канал)

Воркеры внутри процесса могут общаться через **локальный канал** на базе `queue.Queue`:

```python
# worker_1 отправляет сообщение worker_2
self.process.router_manager.send({
    "channel": f"{self.process.name}_local",
    "target_worker": "worker_2",
    "command": "process_data",
    "data": {"result": 42},
})

# worker_2 получает через handler или receive()
def on_message(msg):
    if msg["target_worker"] == "worker_2":
        print(f"Получено: {msg['data']}")

self.process.router_manager.register_message_handler(on_message)
```

---

## Примеры использования

### Пример 1: Постоянная обработка данных

```python
class DataProcessor:
    def __init__(self, interval=1.0):
        self.interval = interval

    def run(self, stop_event, pause_event):
        while not stop_event.is_set():
            if pause_event.is_set():
                time.sleep(0.05)
                continue
            self.process_batch()
            time.sleep(self.interval)

    def process_batch(self):
        print("Обработка партии данных...")

# Создание
processor = DataProcessor(interval=1.0)
config = ThreadConfig(
    priority=ThreadPriority.NORMAL,
    execution_mode=ExecutionMode.LOOP,
)
manager.create_worker("processor", processor.run, config, auto_start=True)
```

### Пример 2: Инициализирующая задача

```python
def initialize_database(stop_event, pause_event):
    """Запускается один раз при старте процесса."""
    print("Инициализация БД...")
    create_tables()
    load_initial_data()
    print("БД инициализирована!")

config = ThreadConfig(
    execution_mode=ExecutionMode.TASK,
    worker_type=WorkerType.SYSTEM,
)
manager.create_worker("db_init", initialize_database, config, auto_start=True)

# Статус будет COMPLETED после выполнения
```

### Пример 3: Отказоустойчивый воркер с перезапуском

```python
def resilient_worker(stop_event, pause_event):
    while not stop_event.is_set():
        try:
            data = fetch_from_api()
            process(data)
        except APIError as e:
            logger.error(f"API ошибка: {e}")
            raise  # Триггер для автоперезапуска

config = ThreadConfig(
    priority=ThreadPriority.NORMAL,
    restart_on_failure=True,
    max_restarts=5,
)
manager.create_worker("api_fetcher", resilient_worker, config, auto_start=True)
```

---

## Тестирование

Модуль включает полный набор unit-тестов (49 тестов):

```bash
# Запустить все тесты worker_module
pytest multiprocess_framework/modules/worker_module/tests/ -v

# Запустить конкретный тест
pytest ...tests/test_worker_lifecycle.py::test_task_execution -v

# С покрытием
pytest ...tests/ --cov=worker_module --cov-report=html
```

**Тестовое покрытие:**
- `test_types.py` — перечисления и TypedDict
- `test_thread_config.py` — конфигурация, to_dict/from_dict
- `test_worker_registry.py` — потокобезопасный реестр
- `test_worker_lifecycle.py` — жизненный цикл, LOOP/TASK режимы
- `test_worker_manager.py` — весь API менеджера
- `test_worker_adapter.py` — адаптер для процесса

---

## Стандарты и соглашения

### Потокобезопасность

WorkerRegistry использует `threading.Lock` для защиты всех операций:

```python
def register(self, ...):
    with self._lock:
        self._workers[name] = worker_info
```

Все публичные методы WorkerManager потокобезопасны благодаря этому.

### Абстракции и интерфейсы

Внешние модули должны зависеть только от `interfaces.py`:

```python
from worker_module.interfaces import IWorkerManager

def my_function(manager: IWorkerManager):
    # Безопасно для мокирования и подмены реализации
    status = manager.get_worker_status("worker_1")
```

### Dict at Boundary

Конфигурация передаётся через границу процессов как обычный `dict`:

```python
# На границе: только dict
thread_config_dict = {"priority": "NORMAL", "execution_mode": "loop"}

# Внутри процесса: Pydantic/TypedDict
thread_config = ThreadConfig.from_dict(thread_config_dict)
```

---

## Знаемые ограничения и ТВДЧ

1. **Нет приоритизации OS-уровня** — приоритеты управляют только poll intervals, не влияют на OS scheduler
2. **Локальный канал — только queue.Queue** — синхронный, подходит для внутри-процессного общения
3. **Метрики хранятся в памяти** — нет персистентности между запусками процесса
4. **Graceful shutdown** — таймаут 5 сек. для остановки может быть недостаточным для сложных воркеров

Подробнее см. `ARCHITECTURE.md`.

---

## Ссылки

- **ARCHITECTURE.md** — детальное описание дизайна и диаграммы
- **STATUS.md** — карточка здоровья модуля
- **interfaces.py** — публичные контракты
- **Plan** — `C:\Users\INNOTECH\.cursor\plans\worker_module_refactoring_679af54d.plan.md`
