# Process Manager Module (Refactored)

Модуль управления процессами. ProcessManagerProcess — оркестратор с композицией ProcessRegistry + ProcessPriority + ProcessStatus. Dict at Boundary: SystemLauncher принимает только (name, proc_dict); конвертация в app через process(); нормализация через merge_with_defaults(DEFAULT_PROCESS_SCHEMA).

**Логирование:** SystemLauncher и ProcessSpawner используют LoggerManager (из logger_module). Ошибки в ProcessRegistry направляются в логирование вместо `except: pass`.

---

## Содержание

1. [Структура папок и файлов](#структура-папок-и-файлов)
2. [Архитектура модуля](#архитектура-модуля)
3. [Схема связей компонентов](#схема-связей-компонентов)
4. [Описание классов и методов](#описание-классов-и-методов)
5. [Поток запуска системы](#поток-запуска-системы)
6. [Использование](#использование)

---

## Структура папок и файлов

```
process_manager_module/
├── __init__.py                    # ProcessManagerProcess, SystemLauncher, ProcessSpawner
│
├── core/                          # Ядро управления процессами
│   ├── __init__.py                # ProcessRegistry, ProcessPriority, ProcessStatus
│   ├── process_registry.py        # ProcessRegistry (registry + lifecycle + create_and_register)
│   ├── process_priority.py        # ProcessPriority
│   └── process_status.py          # ProcessStatus
│
├── process/                       # Процесс-оркестратор
│   ├── __init__.py                # ProcessManagerProcess
│   └── process_manager_process.py # ProcessManagerProcess (ProcessModule + композиция)
│
├── runner/                        # Запуск процессов ОС
│   ├── __init__.py                # run_process_function
│   └── process_runner.py          # run_process_function (top-level для pickle/spawn)
│
├── launcher/                      # Точка входа
│   ├── __init__.py                # SystemLauncher, ProcessSpawner, DEFAULT_PROCESS_SCHEMA
│   ├── schema.py                  # DEFAULT_PROCESS_SCHEMA (default_schema для нормализации)
│   ├── system_launcher.py         # SystemLauncher (фасад, Dict at Boundary)
│   └── spawner.py                 # ProcessSpawner (launch_orchestrator)
│
├── monitor/                       # Мониторинг состояний процессов
│   ├── __init__.py                # ProcessMonitor
│   └── process_monitor.py         # ProcessMonitor
│
├── platforms/                     # Платформо-зависимые адаптеры
│   ├── __init__.py                # get_platform_adapter, StubPlatformAdapter
│   └── base.py                    # StubPlatformAdapter
│
├── tests/                         # Тесты модуля
│   ├── test_system_launcher.py    # SystemLauncher
│   ├── test_process_registry.py   # ProcessRegistry
│   ├── test_process_priority.py   # ProcessPriority
│   ├── test_process_status.py    # ProcessStatus
│   └── test_process_spawner.py    # ProcessSpawner
│
└── README.md                      # Документация (этот файл)
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
| `launch_orchestrator()` | SharedResourcesManager, ConfigManager, LoggerManager, Process(), process.start(), setup_signals. |
| `stop(timeout=3.0)` | stop_event.set(), terminate, join, kill, shared_resources.shutdown(). |
| `wait()` | process.join(). |
| `is_running()` | process.is_alive(). |
| `get_process()` | Process ОС. |
| `get_shared_resources()` | SharedResourcesManager. |
| `get_logger()` | LoggerManager (создаётся в launch_orchestrator). |

---

### 3. `core/process_registry.py` — ProcessRegistry

**Роль:** Реестр + lifecycle + создание. Объединяет registry, start/stop, create_and_register.

| Метод | Описание |
|-------|----------|
| `__init__(stop_event, logger, queue_registry, config_manager, shared_resources)` | Зависимости через конструктор. |
| `add_process(process)` | Добавить Process в os_processes. |
| `get_process_by_name(name)` | Найти процесс по имени. |
| `create_and_register(name, class_path, config, priority)` | Создать Process ОС (helper _create_process_impl), добавить в реестр. |
| `start_all()` | Запуск всех процессов. |
| `stop_all(timeout=3.0)` | stop_event.set(), join, terminate, kill. |

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
| `stop_process(process_name=None)` | _registry.stop_all() или terminate одного. |
| `get_process_status(process_name=None)` | _status + расширенный через shared_resources. |
| `get_all_processes_status()` | _status.get_all_status(). |

---

### 7. `runner/process_runner.py` — run_process_function

**Роль:** Top-level функция (pickle/spawn). Создаёт объекты внутри целевого процесса.

| Параметр | Описание |
|----------|----------|
| `class_path` | Путь к классу процесса. |
| `process_name` | Имя процесса. |
| `stop_event` | multiprocessing.Event. |
| `shared_resources_or_bundle` | SharedResourcesManager или dict (queues, config, custom, routing_map). |

---

### 8. `monitor/process_monitor.py` — ProcessMonitor

**Роль:** Отслеживание ProcessStateRegistry, broadcast при изменении статуса.

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
   → SharedResourcesManager, ConfigManager, LoggerManager
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
4. При stop_event или shutdown:
   → process_monitor.stop()
   → _registry.stop_all()
   → console_manager.close_all()
   → super().shutdown()
```

---

## Использование

### Dict at Boundary (рекомендуется)

```python
from multiprocess_framework.refactored.modules.process_manager_module import SystemLauncher
from multiprocess_framework.refactored.modules.data_schema_module import build_process_with_workers
from multiprocess_prototype.processes.process_1 import Process1Config
from multiprocess_prototype.processes.process_1.worker_1 import Worker1Config
from multiprocess_prototype.processes.process_2 import Process2Config
from multiprocess_prototype.processes.process_2.worker_2 import Worker2_1Config, Worker2_2Config

launcher = SystemLauncher()

launcher.add_process(*build_process_with_workers(Process1Config(), Worker1Config()))
launcher.add_process(*build_process_with_workers(
    Process2Config(),
    Worker2_1Config(),
    Worker2_2Config(),
))

launcher.run()
launcher.shutdown()
```

### Через ProcessSpawner напрямую

```python
from multiprocess_framework.refactored.modules.process_manager_module import ProcessSpawner

spawner = ProcessSpawner(processes_config={"process_1": {...}})
spawner.launch_orchestrator()
spawner.wait()
spawner.stop()
```

---

## Тесты

Тесты находятся в `tests/` и покрывают SystemLauncher, ProcessRegistry, ProcessPriority, ProcessStatus, ProcessSpawner.

**Запуск из корня Inspector_prototype:**

```bash
python -m pytest multiprocess_framework/refactored/modules/process_manager_module/tests/ -v
```

**Интеграционные тесты** (SystemLauncher + ProcessSpawner):

```bash
python -m pytest multiprocess_framework/tests/integration/test_launcher_integration.py multiprocess_framework/tests/integration/test_main_launcher.py -v
```

---

## Зависимости модуля

- `process_module` — ProcessModule
- `shared_resources_module` — SharedResourcesManager
- `config_module` — ConfigManager
- `logger_module` — LoggerManager
- `console_module` — ConsoleManager
- `worker_module` — ThreadConfig, ThreadPriority
- `data_schema_module` — merge_with_defaults (нормализация proc_dict), process/build_process_with_workers (в app-слое)
