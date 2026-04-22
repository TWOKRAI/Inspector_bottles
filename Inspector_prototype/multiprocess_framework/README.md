# Multiprocess Framework — Professional Multiprocessing System for Python

**Расположение:** корень пакета `Inspector_prototype/multiprocess_framework/` (ранее часть материалов жила в подпапке `refactored/` — объединено с этим README и `__init__.py`).

**Version:** 2.0 (Refactored, Phase 8/8 Complete)  
**Status:** ✅ Production Ready  
**Python:** 3.9+ (рекомендуется 3.11+)  
**License:** MIT

---

## Start Here

1. **Новичок?** [docs/QUICK_START.md](./docs/QUICK_START.md) → этот README → [DOCUMENTATION_INDEX.md](./DOCUMENTATION_INDEX.md) → выбери путь.
2. **AI-агент?** [docs/FRAMEWORK_OVERVIEW.md](./docs/FRAMEWORK_OVERVIEW.md) (разделы 1–7) → [docs/ROUTING_GLOSSARY.md](./docs/ROUTING_GLOSSARY.md) → [docs/CONFIG_GUIDE.md](./docs/CONFIG_GUIDE.md).
3. **Разработчик?** [docs/QUICK_START.md](./docs/QUICK_START.md) → [docs/FRAMEWORK_OVERVIEW.md](./docs/FRAMEWORK_OVERVIEW.md) → `modules/*/README.md`.
4. **Маршрутизация сообщений и регистров?** [docs/ROUTING_GLOSSARY.md](./docs/ROUTING_GLOSSARY.md) (процесс vs канал Router, `connection_map`, `FieldRouting`).

---

## What is This?

**Multiprocess Framework** is a **comprehensive architectural system** for building reliable, scalable, multithreaded and multiprocessing applications in Python.

Instead of:
```python
# ❌ Raw multiprocessing (painful)
q_in = Queue()
q_out = Queue()
q_log = Queue()
q_err = Queue()
p = Process(target=worker, args=(q_in, q_out, q_log, q_err, ...))
# ... what protocol? how to structure? how to log? when to stop?
```

You get:
```python
# ✅ Multiprocess Framework (structured)
launcher = SystemLauncher(processes=[
    ("processor", {"class_path": "MyApp.ProcessorProcess"}),
    ("logger", {"class_path": "MyApp.LoggerProcess"}),
])
launcher.run()  # blocks until Ctrl+C, graceful shutdown
```

---

## Core Features

✅ **19 packages under `modules/`** (полный каталог: [docs/ARCHITECTURE_MODULE_CATALOG.md](./docs/ARCHITECTURE_MODULE_CATALOG.md))  
✅ **Unified messaging protocol** (Message with 9 types)  
✅ **Type-safe data structures** (Pydantic v2 + SchemaBase)  
✅ **Centralized logging & error handling** (through ObservableMixin)  
✅ **Graceful shutdown** (signal handling, timeout cascades)  
✅ **Thread-safe worker management** (WorkerManager)  
✅ **Dict at Boundary** (process-safe serialization)  
✅ **Request-Response pattern** (correlation_id)  
✅ **Observable/Proxy pattern** (transparent logging)  
✅ **Channel routing** (Router, Logger, Error managers)  
✅ **Database access via messages** (sql_module, channel `database`)

---

## Architecture at a Glance

```
Application (Your Code)
    ↓
ProcessModule (base class for each process)
    ├─ RouterManager (send/receive messages via channels)
    ├─ CommandManager (dispatch commands)
    ├─ WorkerManager (manage threads safely)
    ├─ LoggerManager (centralized logging through channels)
    ├─ ConfigManager (runtime config: get/set, subscriptions, env-fallback)
    ├─ ErrorManager (error handling through channels)
    └─ SQLManager (optional, in DatabaseProcess — access via channel `database`)
    ↓
ProcessManagerProcess (orchestrator)
    ├─ ProcessRegistry (track all processes)
    ├─ ProcessMonitor (monitor state & health)
    └─ SharedResourcesManager (ConfigStore for cross-process sync)
    ↓
SystemLauncher (entry point)
    └─ Fork/spawn, signal handling, graceful shutdown
```

**16 Modules Organized in 5 Layers:**

| Layer | Modules | Purpose |
|-------|---------|---------|
| **Foundation** | base_manager, data_schema_module, message_module | Core abstractions, type safety |
| **Infrastructure** | logger_module, error_module, config_module, console_module, shared_resources_module, **sql_module** | Services, utilities, database access |
| **Communication** | router_module, dispatch_module, command_module | Inter-process messaging |
| **Process** | worker_module, process_module | Process & thread management |
| **Orchestration** | process_manager_module | System startup & lifecycle |

---

## Quick Start

### 1. Create a Process

```python
from multiprocess_framework.modules.process_module import ProcessModule
from multiprocess_framework.modules.worker_module import (
    ThreadConfig, ExecutionMode
)
import time

class CameraProcess(ProcessModule):
    def initialize(self) -> bool:
        self.log_info("Camera starting")
        
        # Create a worker thread
        def capture_frames(stop_event, pause_event):
            frame_count = 0
            while not stop_event.is_set():
                if pause_event.is_set():
                    time.sleep(0.05)
                    continue
                
                frame_count += 1
                self.log_info(f"Captured frame {frame_count}")
                
                # Send to detector
                msg = self.msg.command(
                    targets=["detector"],
                    command="detect",
                    args={"frame_id": frame_count},
                )
                self.router.send(msg)
                
                time.sleep(0.033)  # ~30 FPS
        
        self.create_worker(
            "capture",
            capture_frames,
            ThreadConfig(execution_mode=ExecutionMode.LOOP),
            auto_start=True,
        )
        return True
    
    def shutdown(self) -> bool:
        self.log_info("Camera shutting down")
        return True
```

### 2. Create Another Process

```python
class DetectorProcess(ProcessModule):
    def initialize(self) -> bool:
        self.log_info("Detector starting")
        
        # Register command handler
        self.command_manager.register_command(
            "detect",
            self._detect_handler
        )
        return True
    
    def _detect_handler(self, msg_data):
        frame_id = msg_data.get("frame_id")
        self.log_info(f"Detecting in frame {frame_id}")
        
        # Send results somewhere
        msg = self.msg.command(
            targets=["display"],
            command="show",
            args={"objects": 5},
        )
        self.router.send(msg)
        return {"status": "done"}
    
    def shutdown(self) -> bool:
        self.log_info("Detector shutting down")
        return True
```

### 3. Launch

```python
from multiprocess_framework.modules.process_manager_module import SystemLauncher

if __name__ == "__main__":
    launcher = SystemLauncher(
        processes=[
            ("camera", {
                "class_path": "myapp.CameraProcess",
                "config": {"fps": 30},
            }),
            ("detector", {
                "class_path": "myapp.DetectorProcess",
                "config": {"model": "yolo.pt"},
            }),
            ("display", {
                "class_path": "myapp.DisplayProcess",
                "config": {},
            }),
        ],
        console_enabled=True,
    )
    
    launcher.run()  # blocks until Ctrl+C
```

**That's it!** Your system:
- Creates 3 processes (camera, detector, display)
- Communicates through typed messages
- Logs everything to console/files
- Handles errors gracefully
- Shuts down cleanly on Ctrl+C

---

## Key Concepts

### 1. Message Protocol (Dict at Boundary)

Processes communicate through typed messages:

```python
# 9 message types
msg = adapter.command(targets=["detector"], command="detect", args={...})
msg = adapter.log("error", "Failed to initialize")
msg = adapter.request(targets=["service"], request_type="status", timeout=5)
msg = adapter.response(targets=["requester"], request_id=req_id, result={...})
msg = adapter.event("frame_ready", event_data={...})
msg = adapter.broadcast(content=data, exclude=["self"])
msg = adapter.system(targets=[...], action="pause")
msg = adapter.data(targets=[...], data_type="frame", data=blob)

# Convert to dict at process boundary
raw = msg.to_dict()  # ← send through queue
# Restore in other process
msg = Message.from_dict(raw)
```

### 2. Observable Logging (Transparent Integration)

All managers automatically log through a unified interface:

```python
class MyManager(BaseManager, ObservableMixin):
    def __init__(self, name, logger=None):
        BaseManager.__init__(self, name)
        ObservableMixin.__init__(
            self,
            managers={'logger': logger} if logger else {},
        )
    
    def do_work(self):
        self._log_debug("debug info")     # → LoggerManager.debug()
        self._log_info("processing")      # → LoggerManager.info()
        self._record_metric("ops", 1)     # → StatsManager.record()
        try:
            risky_operation()
        except Exception as e:
            self._track_error(e)          # → ErrorManager.log_exception()
```

### 3. Graceful Shutdown

Processes are cleaned up properly:

```
Ctrl+C / SIGTERM
    ↓
ProcessRegistry.stop_all(timeout=5s)
    ├─ Set stop_event for each process
    ├─ Wait for graceful exit (up to 5s)
    ├─ If hanging: SIGTERM
    ├─ If still hanging: SIGKILL
    └─ Guarantee: all dead in 5s
    ↓
Flush logs, close connections
    ↓
Exit code 0
```

### 4. Database Access via Router (sql_module)

БД доступна как **отдельный канал** в роутере. Процесс `DatabaseProcess` регистрирует команды `db.query`, `db.execute`, `db.insert` в CommandManager. Сообщения с этими командами маршрутизируются в процесс с БД через очередь (channel).

```
Процесс A (GUI, Processor, …)                DatabaseProcess
    │                                              │
    │  msg = {"command": "db.query",              │
    │         "args": {"sql": "SELECT * FROM t"},  │
    │         "targets": ["database"]}             │
    │                                              │
    ├── router.send(msg) ──────────────────────────────► QueueChannel (system)
    │                                              │
    │                                    Router.receive() → message_dispatcher
    │                                    → command_manager.handle_command(msg)
    │                                    → sql_manager.execute_command(msg)
    │                                    → {"status": "success", "data": [...]}
    │                                              │
    │  ◄──────────────────────────── response (если request-response) ──────┤
```

**Использование из любого процесса:**

```python
# Отправить запрос к БД (MessageAdapter.command → args)
msg = self.msg.command(
    targets=["database"],
    command="db.query",
    args={"sql": "SELECT * FROM users", "params": {}},
)
self.router.send(msg)

# db.insert
msg = self.msg.command(
    targets=["database"],
    command="db.insert",
    args={"table": "events", "data": {"type": "frame_ready", "ts": time.time()}},
)
self.router.send_async(msg, priority="normal")
```

**Формат сообщения (Dict at Boundary):** `command` — ключ маршрутизации, `args`/`data` — параметры для SQLManager.execute_command. ProcessLifecycle регистрирует команды в message_dispatcher, поэтому сообщения с `command="db.query"` автоматически попадают в handler → sql_manager.execute_command.

**Request-response (когда нужен результат):** Для `db.query` с ожиданием ответа используйте `request()` вместо `command()`:

```python
# Отправитель — ждёт результат
req = self.msg.request(
    targets=["database"],
    request_type="db.query",
    query={"sql": "SELECT * FROM users", "params": {}},
    timeout=5.0,
)
correlation_id = req.id
self.router.send(req.to_dict())

# В callback или цикле receive: искать msg с request_id == correlation_id
def on_message(msg):
    if msg.get("request_id") == correlation_id:
        result = msg.get("result")  # {"status": "success", "data": [...]}
```

DatabaseProcess при обработке REQUEST должен вызвать `sql_manager.execute_command` и отправить `response(targets=[sender], request_id=req.id, result=result)`.

**Подключение DatabaseProcess:** Добавить в `main.py`:

```python
from multiprocess_prototype.configs import DatabaseConfig
launcher.add_process(*process(DatabaseConfig()))
```

См. [sql_module/README.md](./modules/sql_module/README.md) и [router_module/README.md](./modules/router_module/README.md).

---

### 5. Type-Safe Data Structures

Define your process's data schema:

```python
from data_schema_module import SchemaBase, FieldMeta, FieldRouting
from typing import Annotated

class DetectorConfig(SchemaBase):
    confidence: Annotated[float, FieldMeta(
        "Detection confidence",
        min=0.0, max=1.0,
        unit="%",
    )] = 0.5
    
    max_objects: Annotated[int, FieldMeta(
        "Max objects per frame",
        min=1, max=1000,
    )] = 100

# Automatic validation
config = DetectorConfig()
config.update_field("confidence", 0.8)  # ✓ OK
config.update_field("confidence", 1.5)  # ✗ Error
```

---

## Documentation

| Document | Purpose | Read Time |
|----------|---------|-----------|
| **[DOCUMENTATION_INDEX.md](./DOCUMENTATION_INDEX.md)** | Navigation & quick links | 5 min |
| **[docs/FRAMEWORK_OVERVIEW.md](./docs/FRAMEWORK_OVERVIEW.md)** | Complete overview | 45 min |
| **[docs/ARCHITECTURE_REFERENCE.md](./docs/ARCHITECTURE_REFERENCE.md)** | Diagrams & tables | 30 min |
| **[docs/ROUTING_GLOSSARY.md](./docs/ROUTING_GLOSSARY.md)** | Routing & registers glossary | 5 min |
| **[DECISIONS.md](./DECISIONS.md)** | Architectural decisions (ADRs) | 20 min |
| **[MODULES_STATUS.md](./MODULES_STATUS.md)** | Module status & scores | 2 min |

**Each module also has:**
- `README.md` — module documentation
- `STATUS.md` — refactoring status & scores
- `interfaces.py` — public contract
- `tests/` — usage examples

---

## Design Patterns Used

✅ Factory Pattern (MessageFactory)  
✅ Strategy Pattern (4 dispatch strategies)  
✅ Adapter Pattern (everywhere)  
✅ Observer Pattern (ObservableMixin)  
✅ Template Method Pattern (ProcessModule)  
✅ Proxy Pattern (logging proxies)  
✅ Dependency Injection (explicit dependencies)  

---

## Performance

| Operation | Complexity | Notes |
|-----------|-----------|-------|
| Send message | O(1) | AsyncSender buffering |
| Dispatch command | O(1) | Dict lookup (EXACT_MATCH) |
| Create process | O(n) | Depends on memory |
| Graceful shutdown | O(timeout) | 5-10 seconds typical |
| Logging batch | O(batch_size) | Amortized O(1) |

---

## When to Use

### ✅ Ideal For

- **Video processing** (camera → detector → tracker → UI)
- **IoT applications** (sensors → processing → storage)
- **Microservices** (lightweight service architecture on one machine)
- **Monitoring systems** (multi-source data collection)

### ❌ Not For

- Simple scripts (use raw `multiprocessing`)
- Distributed systems (use Docker + Kubernetes)
- Async-only code (use `asyncio` instead)

---

## Testing

Модули в `modules/` используют **плоские импорты** (`from data_schema_module import …`).
Путь `multiprocess_framework/modules` должен быть на `sys.path` — это задаёт локальный
[`modules/pytest.ini`](./modules/pytest.ini) (`pythonpath = .`), поэтому **рабочий каталог
при запуске pytest — `multiprocess_framework/modules`**.

**Лог-файлы:** относительные пути в `LoggerManager` больше не привязаны к этому каталогу исходников.
По умолчанию используется каталог из **`MULTIPROCESS_LOG_DIR`** / **`INSPECTOR_LOG_DIR`**, иначе подкаталог в системном temp
(см. `logger_module/core/log_paths.py`, **ADR-111**). В pytest под `modules/` **`conftest.py`** выставляет
`MULTIPROCESS_LOG_DIR` в изолированный temp. Для приложения пути задают через **`ManagersConfig.from_log_dir(...)`**
(абсолютные пути после нормализации) или явное **`log_directory`** в `LoggerManagerConfig`.

### Рекомендуемый запуск (из `Inspector_prototype`)

```bash
python scripts/run_framework_tests.py
```

Опции pytest передаются в конец:

```bash
python scripts/run_framework_tests.py process_module/tests -q --maxfail=1
```

### Вручную: сменить каталог на `modules`

```bash
cd multiprocess_framework/modules
python -m pytest
```

Тот же эффект, что и у скрипта выше: подхватывается `pytest.ini` и список `testpaths`
(все `*/tests` перечисленных пакетов).

### Вручную: остаться в `Inspector_prototype` (bash)

```bash
cd Inspector_prototype
PYTHONPATH=multiprocess_framework/modules python -m pytest -c multiprocess_framework/modules/pytest.ini multiprocess_framework/modules
```

На **Windows (PowerShell)**:

```powershell
cd Inspector_prototype
$env:PYTHONPATH = "multiprocess_framework/modules"
python -m pytest -c multiprocess_framework/modules/pytest.ini multiprocess_framework/modules
```

Без `PYTHONPATH` и без `cwd` в `modules` команда `pytest multiprocess_framework/...` из корня
`Inspector_prototype` обычно падает с `ModuleNotFoundError: No module named 'data_schema_module'`.

### Coverage (пример)

Из каталога `modules` (после `cd multiprocess_framework/modules`):

```bash
python -m pytest --cov=. --cov-report=html
```

Либо с явным `PYTHONPATH` из `Inspector_prototype` (bash):

```bash
PYTHONPATH=multiprocess_framework/modules python -m pytest -c multiprocess_framework/modules/pytest.ini multiprocess_framework/modules --cov=multiprocess_framework/modules --cov-report=html
```

### Прочее

- **Статическая проверка структуры** (импорты, `interfaces.py`, без `sys.path.insert` в production):
  `python scripts/validate.py` из `Inspector_prototype`.
- **Тесты приложения-прототипа** задаются в `Inspector_prototype/pyproject.toml` (`testpaths`:
  `multiprocess_prototype/tests` и др.) — это отдельный набор от unit-тестов модулей фреймворка.
- **Известные ограничения:** [PROBLEMS.md](PROBLEMS.md); интеграционные сценарии:
  [tests/integration/TEST_ISSUES.md](./tests/integration/TEST_ISSUES.md).

---

## Principles

1. **Explicit is Better than Implicit** — No hidden globals, all dependencies passed explicitly
2. **Separation of Concerns** — Each module handles one responsibility
3. **Graceful Everything** — Graceful initialization, shutdown, degradation, error handling
4. **Type Safety** — Pydantic + Protocol for type hints
5. **Modularity** — 15 independent modules, can be extended/replaced
6. **Dict at Boundary** — Process-safe serialization

---

## Project Structure

```
Inspector_prototype/multiprocess_framework/
├── README.md                      # ← Start here
├── DOCUMENTATION_INDEX.md         # Navigation guide
├── DECISIONS.md                   # 21 architectural decisions (ADRs)
├── MODULES_STATUS.md               # Module status & scores
│
├── docs/                           # Detailed documentation
│   ├── FRAMEWORK_OVERVIEW.md      # Complete overview
│   ├── ROUTING_GLOSSARY.md        # Routing terms (process vs Router channel)
│   ├── ARCHITECTURE_REFERENCE.md  # Diagrams & tables
│   ├── ARCHITECTURE_MODULE_CATALOG.md
│   ├── FRONTEND_COMMAND_LAUNCHER_ROADMAP.md
│   └── MODULE_README_TEMPLATE.md
│
├── modules/                       # Core packages (см. также channel_routing, statistics)
│   ├── base_manager/
│   ├── channel_routing_module/
│   ├── data_schema_module/
│   ├── message_module/
│   ├── logger_module/
│   ├── error_module/
│   ├── config_module/
│   ├── router_module/
│   ├── dispatch_module/
│   ├── command_module/
│   ├── worker_module/
│   ├── process_module/
│   ├── process_manager_module/
│   ├── console_module/
│   ├── shared_resources_module/
│   ├── registers_module/
│   ├── frontend_module/
│   ├── sql_module/                # Database access via SQLAlchemy 2.0
│   └── statistics_module/
│
└── (пример приложения)             # Inspector_prototype/multiprocess_prototype/main.py
```

---

## Contributing

When adding new features:

1. Define interface in `interfaces.py` (Protocol or ABC)
2. Implement in module
3. Write tests in `tests/`
4. Update module `README.md`
5. Запустить тесты модуля и полный прогон фреймворка: `python scripts/run_framework_tests.py` (из `Inspector_prototype`)
6. Update `DECISIONS.md` if architectural
7. Update `DOCUMENTATION_INDEX.md` if structure changed

---

## License

MIT

---

## Changelog

### v2.0 (Phase 8/8 Complete) — March 2026
- ✅ All 16 modules complete and production-ready
- ✅ Comprehensive documentation (5000+ lines)
- ✅ 21 architectural decisions documented
- ✅ Full test coverage (100+ unit tests)
- ✅ Graceful shutdown with signal handling
- ✅ Error recovery with error_module
- ✅ CommandManager with 6 built-in commands
- ✅ sql_module — database access via Router, typed commands (db.query, db.execute, db.insert)

---

## Support

For questions or issues:

1. Check `DOCUMENTATION_INDEX.md` for navigation
2. Read `docs/FRAMEWORK_OVERVIEW.md` for the concept
3. Look at `docs/ARCHITECTURE_REFERENCE.md` for specifics
4. Check module `README.md` files
5. Review `tests/` for usage examples

---

**Built with ❤️ for reliable multiprocessing in Python**

Last Updated: March 18, 2026

---

## Приложение: краткий русскоязычный обзор (архив корневого README)

Многопроцессный фреймворк для распределённых приложений с PyQt/PySide GUI. Детальные описания классов и файлов — в `modules/<имя_модуля>/README.md` и в разделах выше.

### Архитектура (кратко)

```
SystemLauncher
    └── ProcessManager (главный процесс)
        ├── SharedResourcesManager (общие ресурсы)
        └── Процессы приложения (ProcessModule)
            ├── WorkerManager (потоки)
            ├── RouterManager (маршрутизация)
            ├── LoggerManager (логирование)
            └── CommandManager (команды)
```

- **Многопроцессность:** компоненты изолируются процессами.
- **Централизованное управление:** оркестрация через process_manager_module.
- **Общие ресурсы:** SharedResourcesManager и очереди.
- **Декларативность:** схемы и конфиги через data_schema_module (`process()` для сборки dict процессов).

Импорты в коде предпочтительно из явных путей:

`from multiprocess_framework.modules.<module_name> import ...`

Корневой пакет `import multiprocess_framework` также реэкспортирует часть символов (см. `__init__.py`), но для ясности зависимостей лучше импортировать из `modules`.
