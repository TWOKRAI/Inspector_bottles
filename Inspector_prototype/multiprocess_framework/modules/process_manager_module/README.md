# Process Manager Module (Refactored)

**Этап: 8/8** — Модуль управления процессами.

ProcessManagerProcess — оркестратор с композицией ProcessRegistry + ProcessPriority + ProcessStatus + ProcessMonitor. Dict at Boundary: SystemLauncher принимает только (name, proc_dict); конвертация в app через process(); нормализация через merge_with_defaults(DEFAULT_PROCESS_SCHEMA).

**Новое в этапе 8:**
- `interfaces.py` — публичные контракты `ISystemLauncher`, `IProcessManagerProcess`, `IProcessRegistry`
- Graceful shutdown без `sys.exit()` в signal handler
- Интеграция `error_module` — `ErrorManager` в spawner, `log_exception` при ошибках
- CommandManager — 6 встроенных команд (`process.list/start/stop/status`, `system.shutdown/stats`)
- Чистый `process_runner.py` — вспомогательные функции, `_ProcessLogger`, нет отладочных print-ов

---

## Содержание

1. [Структура папок и файлов](#структура-папок-и-файлов)
2. [Архитектура модуля](#архитектура-модуля)
3. [Публичные контракты (interfaces.py)](#публичные-контракты)
4. [Схема связей компонентов](#схема-связей-компонентов)
5. [Описание классов и методов](#описание-классов-и-методов)
6. [Поток запуска системы](#поток-запуска-системы)
7. [Обработка ошибок](#обработка-ошибок)
8. [Graceful Shutdown](#graceful-shutdown)
9. [CommandManager — встроенные команды](#commandmanager--встроенные-команды)
10. [Использование](#использование)

---

## Структура папок и файлов

```
process_manager_module/
├── __init__.py                         # Все публичные экспорты
├── interfaces.py                       # ISystemLauncher, IProcessManagerProcess, IProcessRegistry
│
├── core/                               # Ядро управления процессами
│   ├── __init__.py                     # ProcessRegistry, ProcessPriority, ProcessStatus
│   ├── process_registry.py             # ProcessRegistry (registry + lifecycle + create_and_register)
│   ├── process_priority.py             # ProcessPriority
│   └── process_status.py               # ProcessStatus
│
├── process/                            # Процесс-оркестратор
│   ├── __init__.py                     # ProcessManagerProcess
│   └── process_manager_process.py      # ProcessManagerProcess (ProcessModule + композиция)
│
├── runner/                             # Запуск процессов ОС
│   ├── __init__.py                     # run_process_function
│   └── process_runner.py               # run_process_function + вспомогательные функции
│
├── launcher/                           # Точка входа
│   ├── __init__.py                     # SystemLauncher, ProcessSpawner
│   ├── schema.py                       # DEFAULT_PROCESS_SCHEMA
│   ├── system_launcher.py              # SystemLauncher (фасад, Dict at Boundary)
│   └── spawner.py                      # ProcessSpawner (launch_orchestrator + ErrorManager)
│
├── monitor/                            # Мониторинг состояний процессов
│   ├── __init__.py                     # ProcessMonitor
│   └── process_monitor.py              # ProcessMonitor
│
├── adapters/                           # Адаптеры
│   ├── __init__.py
│   └── schema_adapter.py               # ProcessSchemaAdapter
│
├── platforms/                          # Платформо-зависимые адаптеры
│   ├── __init__.py                     # get_platform_adapter
│   └── base.py                         # StubPlatformAdapter
│
├── tests/                              # Тесты модуля (8 файлов)
│   ├── test_system_launcher.py         # SystemLauncher
│   ├── test_process_registry.py        # ProcessRegistry
│   ├── test_process_priority.py        # ProcessPriority
│   ├── test_process_status.py          # ProcessStatus
│   ├── test_process_spawner.py         # ProcessSpawner + signal handling
│   ├── test_process_manager_process.py # ProcessManagerProcess (новый)
│   ├── test_process_runner.py          # run_process_function (новый)
│   ├── test_process_monitor.py         # ProcessMonitor (новый)
│   ├── test_schema_adapter.py          # ProcessSchemaAdapter (новый)
│   └── test_interfaces.py              # Соответствие контрактам (новый)
│
├── docs/
│   └── README.md                       # Детальная документация
└── README.md                           # Документация (этот файл)
```

---

## Публичные контракты

Файл: `interfaces.py`

```python
from process_manager_module.interfaces import (
    ISystemLauncher,
    IProcessManagerProcess,
    IProcessRegistry,
)
```

### ISystemLauncher

```python
launcher.add_process(name: str, proc_dict: Dict) -> ISystemLauncher  # цепочка
launcher.run() -> None          # блокирующий запуск + ожидание
launcher.start() -> None        # неблокирующий запуск
launcher.stop() -> None         # graceful shutdown
launcher.shutdown() -> None     # алиас для stop()
launcher.wait() -> None         # ожидание завершения
launcher.get_status() -> Dict   # spawner_running, process, registered_processes
launcher.get_stats() -> Dict    # spawner, shared_resources
```

### IProcessManagerProcess

```python
pmp.create_process(name, class_path, config, priority) -> Process
pmp.start_process(process_name) -> bool
pmp.stop_process(process_name=None) -> bool   # один: свой stop_event; None — все
pmp.restart_process(process_name) -> bool    # stop → recreate → start (нужен сохранённый конфиг)
pmp.get_process_status(process_name) -> Dict
pmp.get_all_processes_status() -> Dict[str, Dict]
```

### IProcessRegistry

```python
registry.add_process(process) -> None
registry.get_process_by_name(name) -> Optional[Process]
registry.create_and_register(name, class_path, config, priority) -> Optional[Process]
registry.start_all() -> None
registry.stop_all(timeout: float) -> None  # все per-process stop_event
registry.stop_one(name, timeout=5.0) -> bool
registry.remove_process(name) -> None
```

---

## Архитектура модуля

### Dict at Boundary + default_schema

- **SystemLauncher** принимает только `add_process(name, proc_dict)`
- **Конвертация** в app: `process(Process1Config(), Worker1Config())` из data_schema_module
- **Нормализация**: `merge_with_defaults(proc_dict, DEFAULT_PROCESS_SCHEMA)` — consumer определяет ожидаемый формат, недостающие ключи (class, queues, priority, workers) заполняются
- Конфиги (Process1Config, Worker1Config) — RegisterBase в app; фреймворк работает только с dict

### Иерархия

```
ProcessModule (из process_module)
        │
        └── ProcessManagerProcess
                    │
                    ├── ProcessRegistry (registry + lifecycle + create)
                    ├── ProcessPriority
                    ├── ProcessStatus
                    └── ProcessMonitor
```

### Поток данных

```
SystemLauncher
    │
    └── ProcessSpawner.launch_orchestrator()
            │
            └── Process (ОС) → run_process_function
                                    │
                                    └── ProcessManagerProcess
                                            │
                                            ├── ProcessRegistry
                                            ├── ProcessPriority
                                            ├── ProcessStatus
                                            └── ProcessMonitor
```

---

## Схема связей компонентов

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         SystemLauncher (launcher/)                           │
│  Фасад. add_process(name, proc_dict) — Dict at Boundary                         │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │ использует
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    ProcessSpawner (launcher/spawner.py)                       │
│  launch_orchestrator(): SharedResourcesManager, ConfigManager, Process(),   │
│  process.start(), сигналы. stop(), wait().                                   │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │ target=run_process_function
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              run_process_function (runner/process_runner.py)                 │
│  Top-level (pickle/spawn). SharedResourcesManager из bundle,                 │
│  process.initialize(), process.run().                                        │
└─────────────────────────────────────┬─────────────────────────────────────┘
                                      │ создаёт экземпляр
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│              ProcessManagerProcess (process/)                                │
│  ProcessModule. Композиция: ProcessRegistry + ProcessPriority + ProcessStatus + ProcessMonitor │
└──────────────┬────────────────────────────────────────────┬────────────────┘
               │ содержит                                     │ содержит
               ▼                                             ▼
┌──────────────────────────────┐              ┌──────────────────────────────────┐
│   ProcessRegistry (core/)    │              │   ProcessMonitor (monitor/)       │
│   add, get, start_all,       │              │   Отслеживает ProcessStateRegistry│
│   stop_all, create_and_register │           │   broadcast при изменении статуса │
└──────┬───────┬───────────────┘              └──────────────────────────────────┘
       │       │
       ▼       ▼
┌──────────┐ ┌──────────┐
│Process   │ │Process   │
│Priority  │ │Status    │
└──────────┘ └──────────┘
```

---

## Описание классов и методов

### 1. `launcher/system_launcher.py` — SystemLauncher

**SystemLauncher** — фасад запуска. Dict at Boundary: принимает только (name, proc_dict).

| Метод | Описание |
|-------|----------|
| `__init__(config=None)` | config — опционально (dict). |
| `add_process(name, proc_dict)` | Добавить процесс. proc_dict нормализуется через merge_with_defaults(DEFAULT_PROCESS_SCHEMA). |
| `run()` | ProcessSpawner.launch_orchestrator() + wait(). Ctrl+C → stop. |
| `start()` | Только launch_orchestrator(). |
| `stop()` | ProcessSpawner.stop(). |
| `wait()` | ProcessSpawner.wait(). |
| `shutdown()` | Алиас для stop(). |
| `get_status()` | Статус spawner и Process. |
| `get_stats()` | Статистика системы. |

**Конвертация в app:** `launcher.add_process(*process(Process1Config(), Worker1Config()))` — из data_schema_module.

**DEFAULT_PROCESS_SCHEMA** (launcher/schema.py) — эталонная структура proc_dict. merge_with_defaults гарантирует наличие class, queues, priority, workers.

---

### 2. `launcher/spawner.py` — ProcessSpawner

**Роль:** Создание инфраструктуры + Process ОС + старт + сигналы.

| Метод | Описание |
|-------|----------|
| `__init__(processes_config, platform_adapter)` | Конфигурация процессов. |
| `launch_orchestrator()` | SharedResourcesManager, `_ProcessLogger`, Process(ProcessManager), process.start(), setup_signals. |
| `stop(timeout=3.0)` | stop_event (оркестратора).set(), terminate, join, kill, shared_resources.shutdown(). |
| `wait()` | process.join(). |
| `is_running()` | process.is_alive(). |
| `get_process()` | Process ОС. |
| `get_shared_resources()` | SharedResourcesManager. |

---

### 3. `core/process_registry.py` — ProcessRegistry

**Роль:** Реестр + lifecycle + создание. Объединяет registry, start/stop, create_and_register.

| Метод | Описание |
|-------|----------|
| `__init__(logger, queue_registry, config_manager, shared_resources)` | Без общего stop_event у детей. |
| `add_process(process)` | Добавить Process в os_processes. |
| `get_process_by_name(name)` | Найти процесс по имени. |
| `create_and_register(name, class_path, config, priority)` | Свой `Event` на процесс, `run_process_function`, add. |
| `start_all()` | Запуск всех процессов. |
| `stop_all(timeout=3.0)` | Все `_stop_events.set()`, join, terminate, kill. |
| `stop_one(name, timeout)` | Только событие и join/terminate/kill для имени. |
| `remove_process(name)` | Убрать из `os_processes` и `_stop_events`. |

---

### 4. `core/process_priority.py` — ProcessPriority

**Роль:** Управление приоритетами через платформенный адаптер.

| Метод | Описание |
|-------|----------|
| `register_priority(process_name, priority)` | Сохранить приоритет. |
| `apply_priority(process, delay=0.1)` | Применить к процессу. |
| `get_priority(process_name, default)` | Получить приоритет. |

---

### 5. `core/process_status.py` — ProcessStatus

**Роль:** Мониторинг статуса (alive, pid, exitcode).

| Метод | Описание |
|-------|----------|
| `get_process_status(process_name)` | Статус одного процесса. |
| `get_all_status()` | Словарь {name: status}. |
| `get_stats()` | total, alive, dead, alive_percent. |

---

### 6. `process/process_manager_process.py` — ProcessManagerProcess

**Наследование:** ProcessModule  
**Роль:** Оркестратор. Композиция: ProcessRegistry + ProcessPriority + ProcessStatus + ProcessMonitor.

| Метод | Описание |
|-------|----------|
| `__init__(name, shared_resources, config)` | ConfigManager, QueueRegistry, ConsoleManager, ProcessRegistry, ProcessPriority, ProcessStatus, ProcessMonitor. |
| `initialize()` | ProcessModule.initialize(), _create_processes_from_config(), process_monitor.start(). |
| `shutdown()` | process_monitor.stop(), registry.stop_all(), console_manager.close_all(), ProcessModule.shutdown(). |
| `create_process(name, class_path, config, priority)` | _registry.create_and_register + _priority.register. |
| `start_process(process_name=None)` | _registry.start_all() или один процесс + _priority.apply. |
| `stop_process(process_name=None)` | `stop_all` или `stop_one` (per-process event). |
| `restart_process(process_name)` | stop → `remove_process` → `create_and_register` → start. |
| `get_process_status(process_name=None)` | _status + расширенный через shared_resources. |
| `get_all_processes_status()` | _status.get_all_status(). |

---

### 7. `runner/` — run_process_function + helpers

**Файлы:** `process_runner.py` (entry + lifecycle), `class_loader.py`, `bundle_builder.py`.

**Роль:** Top-level функция (pickle/spawn). Создаёт объекты внутри целевого процесса.

| Параметр | Описание |
|----------|----------|
| `class_path` | Путь к классу процесса. |
| `process_name` | Имя процесса. |
| `stop_event` | multiprocessing.Event. |
| `shared_resources_or_bundle` | SharedResourcesManager или dict (queues, config, custom, routing_map). |

---

### 8. `monitor/process_monitor.py` — ProcessMonitor

**Роль:** ProcessStateRegistry + `process.is_alive()` (liveness), broadcast при изменении статуса.

| Метод | Описание |
|-------|----------|
| `start()` | Воркер state_monitor с _monitoring_loop. |
| `stop()` | Остановка мониторинга. |

---

### 9. `platforms/base.py` — StubPlatformAdapter

**Роль:** setup_multiprocessing (spawn, freeze_support). apply_priority — заглушка.

---

## Поток запуска системы

```
1. SystemLauncher().add_process(Process1Config(), workers=[Worker1Config()]).run()
2. ProcessSpawner(processes_config).launch_orchestrator()
   → SharedResourcesManager, лёгкий лог spawner
   → Process(target=run_process_function, args=(ProcessManagerProcess, ...))
   → process.start()
   → setup_signals, wait()
3. В дочернем процессе: run_process_function
   → SharedResourcesManager из bundle
   → ProcessManagerProcess(name, shared_resources, config)
   → process_instance.initialize()
     → _create_processes_from_config(processes_config)
       → Фаза 1: create_and_register_queues для всех
       → Фаза 2: _registry.create_and_register + start + _priority.apply для каждого
     → process_monitor.start()
   → process_instance.run()
4. При stop_event оркестратора или shutdown:
   → process_monitor.stop()
   → _registry.stop_all() (все per-child stop_event)
   → console_manager.close_all()
   → super().shutdown()
```

---

## Обработка ошибок

### Bootstrap

`ProcessSpawner` не создаёт `ErrorManager` / `LoggerManager` фреймворка: только SRM и `_ProcessLogger` (print-fallback). Полная инфраструктура — в `ProcessManagerProcess`.

### Ошибки в ProcessManagerProcess

```python
# initialize() обёрнут в try/except
# При критической ошибке:
#   1. error_manager.log_exception(exc, context)
#   2. shutdown() — graceful завершение

# Ошибки в run_process_function:
#   1. log_exception_via_error_manager()
#   2. _update_process_state(srm, name, "error")
```

### Ошибки в run_process_function

- Ошибка загрузки класса → возврат без запуска
- Ошибка `initialize()` → `process_state = "error"`, возврат
- Необработанное исключение → `process_state = "error"`, traceback

---

## Graceful Shutdown

### Настройка timeout-ов

```python
launcher = SystemLauncher(
    stop_timeout=10.0,          # время ожидания после terminate
    on_shutdown=my_callback,    # callback при завершении
)
```

### Каскад завершения

```
SIGINT/SIGTERM
    → ProcessSpawner._signal_handler()
        → stop()  # БЕЗ sys.exit() — wait() вернётся естественно
            → stop_event.set()
            → process.join(graceful_timeout=3s)
            → process.terminate()  # если не завершился
            → process.join(stop_timeout)
            → process.kill()       # если всё ещё жив
            → on_shutdown()        # app-level callback
            → SharedResourcesManager.shutdown()

ProcessManagerProcess.shutdown():
    → ProcessMonitor.stop()
    → ProcessRegistry.stop_all(shutdown_timeout)
        → для каждого дочернего: свой stop_event.set()
        → join(timeout) для каждого процесса
        → terminate → join(1s) → kill
    → ConsoleManager.shutdown()  # только если console_enabled
    → super().shutdown()         # WorkerManager, RouterManager
```

### Настройка timeout-а в ProcessManagerProcess

```python
# В конфиге процесса:
config = {
    "shutdown_timeout": 10.0,      # timeout для ProcessRegistry.stop_all
    "stop_process_timeout": 5.0,   # timeout для stop_process()
    "console_enabled": False,      # создавать ли ConsoleManager
}
```

---

## CommandManager — встроенные команды

`ProcessManagerProcess` регистрирует встроенные команды при инициализации:

| Команда | Аргументы | Описание |
|---------|-----------|----------|
| `process.list` | — | Список всех процессов и статусов |
| `process.start` | `process_name` | Запустить именованный процесс |
| `process.stop` | `process_name` | Остановить именованный процесс |
| `process.restart` | `process_name` | Перезапустить процесс |
| `process.status` | `process_name` | Статус именованного процесса |
| `system.shutdown` | — | Завершить систему (stop_event.set()) |
| `system.stats` | — | Статистика: monitor + processes |

Все команды помечены тегом `"system"`.

---

## Использование

### Dict at Boundary (рекомендуется)

```python
from multiprocess_framework.modules.process_manager_module import SystemLauncher
from multiprocess_framework.modules.data_schema_module import process
from multiprocess_prototype.backend.configs import (
    CameraConfig,
    DatabaseConfig,
    GuiConfig,
    ProcessorConfig,
    RendererConfig,
    RobotConfig,
)
from multiprocess_prototype.persistence import get_camera_type

launcher = SystemLauncher(stop_timeout=5.0)
camera_type = get_camera_type()

launcher.add_process(*process(CameraConfig(camera_type=camera_type)))
launcher.add_process(*process(ProcessorConfig()))
launcher.add_process(*process(RendererConfig()))
launcher.add_process(*process(RobotConfig()))
launcher.add_process(*process(DatabaseConfig()))
launcher.add_process(*process(GuiConfig(camera_type=camera_type)))

launcher.run()
```

### Через ProcessSpawner напрямую

```python
from multiprocess_framework.modules.process_manager_module import ProcessSpawner

spawner = ProcessSpawner(processes_config={"process_1": {...}})
spawner.launch_orchestrator()
spawner.wait()
spawner.stop()
```

---

## Тесты

Тесты находятся в `tests/` (8 файлов, этап 7/8):

| Файл | Что тестирует |
|------|---------------|
| `test_system_launcher.py` | SystemLauncher: add_process, get_status, get_stats, stop_timeout, on_shutdown |
| `test_process_spawner.py` | ProcessSpawner: init, stop, signal_handler (без sys.exit), on_shutdown callback |
| `test_process_registry.py` | ProcessRegistry: add, get, start_all, stop_all каскад |
| `test_process_manager_process.py` | ProcessManagerProcess: shutdown порядок, stop_process graceful, команды |
| `test_process_runner.py` | run_process_function: bundle mode, ошибки, _update_process_state |
| `test_process_monitor.py` | ProcessMonitor: start/stop, state detection, broadcast |
| `test_schema_adapter.py` | ProcessSchemaAdapter: adapt, adapt_instance, flatten, build_process_entry |
| `test_interfaces.py` | Соответствие контрактам: SystemLauncher → ISystemLauncher |

**Запуск из корня Inspector_prototype:**

```bash
python -m pytest multiprocess_framework/modules/process_manager_module/tests/ -v
```

**Интеграционные тесты** (SystemLauncher + ProcessSpawner):

```bash
python -m pytest multiprocess_framework/tests/integration/test_launcher_integration.py multiprocess_framework/tests/integration/test_main_launcher.py -v
```

---

## Зависимости модуля

- `process_module` — ProcessModule
- `shared_resources_module` — SharedResourcesManager, QueueRegistry
- `config_module` — ConfigManager
- `logger_module` — LoggerManager
- `error_module` — ErrorManager (новое в этапе 8)
- `console_module` — ConsoleManager
- `worker_module` — ThreadConfig, ThreadPriority
- `command_module` — CommandManager (новое в этапе 8)
- `data_schema_module` — merge_with_defaults (нормализация proc_dict)
