# Plan: Рефакторинг `process_manager_module` (#13) — Генеральный директор

> **Статус:** implemented (Composer, 2026-04-10) — см. ревью Opus  
> **Дата:** 2026-04-10  
> **Исполнитель:** Cursor Composer v2  
> **Ревью:** Claude Opus 4.6  
> **Ссылки:** [00_overview.md](plans/refactoring/00_overview.md) · [review_modules.md](plans/refactoring/review_modules.md) · [ARCHITECTURE_REFERENCE.md §13–§15](Inspector_prototype/multiprocess_framework/docs/ARCHITECTURE_REFERENCE.md)
> **Milestone:** M1 — после этого модуля фреймворк должен запускать multi-process приложение с graceful shutdown.

---

## Context

`process_manager_module` (#13) — **оркестратор всего фреймворка**. Это «генеральный директор»: он создаёт `SharedResourcesManager`, считывает конфиги, порождает все дочерние процессы, мониторит их состояние, принимает команды (start/stop/restart/status) и гарантирует корректное завершение.

**`ProcessManagerProcess` сам является `ProcessModule`** — у него есть свои workers, router, logger, command_manager. Он живёт в отдельном OS-процессе и общается с другими через те же IPC-механизмы.

Все 12 зависимостей отрефакторены (средняя оценка 8.8/10). Модуль в рабочем состоянии, но содержит **критический архитектурный баг** и несколько проблем, которые не позволяют считать его production-ready.

**Сложность: 4/5** — требуется архитектурное изменение (per-process stop events), расслоение крупного модуля, и хардение shutdown cascade.

---

## 1. Текущее состояние

| Метрика | Значение |
|---------|----------|
| Файлов .py (без tests) | 21 |
| LOC (без tests) | ~2486 |
| Тест-файлов | 10 |
| Тестов (pytest) | TODO (прогнать baseline) |
| Самый большой файл | `runner/process_runner.py` — 447 LOC |

### Файловая структура

```
process_manager_module/
├── __init__.py                     (48)
├── interfaces.py                   (239)
├── launcher/
│   ├── system_launcher.py          (213)   — Фасад (Dict at Boundary)
│   ├── spawner.py                  (203)   — Bootstrap + сигналы
│   └── schema.py                   (21)    — DEFAULT_PROCESS_SCHEMA
├── process/
│   └── process_manager_process.py  (339)   — Оркестратор (ProcessModule)
├── core/
│   ├── process_registry.py         (209)   — Реестр + lifecycle + create
│   ├── process_priority.py         (103)   — Приоритеты ОС
│   └── process_status.py           (103)   — Статусы процессов
├── runner/
│   └── process_runner.py           (447)   — Entry point дочернего процесса ★
├── monitor/
│   └── process_monitor.py          (136)   — Polling state changes
├── adapters/
│   └── schema_adapter.py           (206)   — SchemaBase → (name, dict)
└── platforms/
    ├── __init__.py                  (13)
    └── base.py                     (30)    — StubPlatformAdapter
```

---

## 2. Выявленные проблемы

### CRITICAL

| # | Проблема | Файл:строка | Влияние |
|---|----------|-------------|---------|
| **P1** | **Shared stop_event — остановка одного процесса убивает все** | `process_manager_process.py:307`, `process_registry.py:85,172` | Все дочерние процессы получают один и тот же `stop_event`. Вызов `stop_process("camera")` делает `self._process_registry.stop_event.set()` → **все процессы** получают сигнал остановки. Невозможно остановить/рестартовать один процесс. |
| **P2** | **Нет возможности рестартовать процесс** | `process_manager_process.py` | После `stop_process()` нет `restart_process()`. А из-за P1 даже stop одного невозможен. |

### HIGH

| # | Проблема | Файл:строка | Влияние |
|---|----------|-------------|---------|
| **P3** | **process_runner.py — God Object (447 LOC)** | `runner/process_runner.py` | 10 функций с разной ответственностью: загрузка класса, нормализация памяти, построение SRM из bundle, console redirect, lifecycle, error reporting. Нарушает SRP. |
| **P4** | **_create_process_impl — 97-строчная top-level функция** | `process_registry.py:14-96` | Вынесена из класса «для лимита строк», но это helper на уровне модуля, который принимает 9 аргументов. Логичнее как метод ProcessRegistry или отдельный Builder. |
| **P5** | **ProcessSpawner создаёт инфраструктуру, которую дети не получают** | `spawner.py:77-91` | Создаёт ConfigManager, LoggerManager, ErrorManager — но в bundle передаёт только `queues`, `config`, `custom`. Дочерние процессы создают свои инстансы. Parent ConfigManager/LoggerManager используются только для логирования spawner-а. Избыточно. |
| **P6** | **Shutdown cascade: двойной SRM** | `spawner.py:77-78`, `process_runner.py:134` | ProcessSpawner создаёт свой SRM. ProcessManagerProcess (внутри child process) создаёт **второй** SRM из bundle. Две копии, не связаны. Parent SRM.shutdown() не влияет на child SRM. |

### MEDIUM

| # | Проблема | Файл:строка | Влияние |
|---|----------|-------------|---------|
| **P7** | **ProcessMonitor не проверяет process.is_alive()** | `monitor/process_monitor.py:64` | Мониторит только ProcessStateRegistry (состояние установленное самим процессом). Если процесс крашится без установки состояния — monitor не заметит. |
| **P8** | **Нет DECISIONS.md** | — | Нет документированных ADR для модуля |
| **P9** | **`_ProcessLogger` — дупликация логики** | `runner/process_runner.py:28-51` | Дублирует ObservableMixin._log_info/warning/error с fallback на print. Паттерн оправдан (не всегда есть LoggerManager), но можно упростить. |
| **P10** | **Bundle creation разбросан** | `process_registry.py:59-81`, `runner/process_runner.py:120-210` | Создание bundle (registry) и его распаковка (runner) — тесно связанные части одного контракта, но живут в разных файлах без общей спецификации. |

### LOW

| # | Проблема | Файл:строка | Влияние |
|---|----------|-------------|---------|
| P11 | `main()` в system_launcher.py — пустой пример | `system_launcher.py:204-213` | Мёртвый код |
| P12 | `ProcessPriority` — StubPlatformAdapter всегда False | `platforms/base.py:30` | Приоритеты не работают, но это осознанный TODO |
| P13 | `ISystemLauncher.shutdown()` — алиас для `stop()` | `interfaces.py:58-60` | Два метода для одного действия |

---

## 3. Целевая архитектура

### 3.1 Per-process stop events (решение P1/P2)

**Было:**
```
ProcessRegistry.stop_event (один Event)
    │
    ├─ передаётся в _create_process_impl → Process(args=(..., stop_event, ...))
    ├─ stop_all() → stop_event.set() → все процессы стопаются ✓
    └─ stop_process("camera") → stop_event.set() → ВСЕ процессы стопаются ✗
```

**Стало:**
```
ProcessRegistry._stop_events: Dict[str, Event]
    │
    ├─ create_and_register("camera", ...) → _stop_events["camera"] = Event()
    │   └─ Process(args=(..., _stop_events["camera"], ...))
    │
    ├─ stop_all() → for ev in _stop_events.values(): ev.set() → все стопаются ✓
    ├─ stop_process("camera") → _stop_events["camera"].set() → только camera ✓
    └─ restart_process("camera"):
        1. _stop_events["camera"].set()  → camera стопается
        2. process.join(timeout)
        3. _stop_events["camera"] = Event()  → новый Event
        4. create_and_register("camera", ..., new_event)  → новый процесс
        5. process.start()
```

### 3.2 Расслоение process_runner.py (решение P3)

**Было:** 1 файл, 447 LOC, 10 функций

**Стало:**
```
runner/
├── __init__.py                     — re-export run_process_function
├── process_runner.py               (~150 LOC) — run_process_function (main entry)
├── bundle_builder.py               (~120 LOC) — _build_shared_resources_from_bundle + memory normalization
├── class_loader.py                 (~30 LOC)  — _load_process_class
└── console_redirect.py             (~40 LOC)  — _setup_console_redirect
```

Helpers `_log_exception_via_error_manager`, `_update_process_state`, `_run_lifecycle` остаются в `process_runner.py` (тесно связаны с main function).

### 3.3 ProcessRegistry: Builder pattern (решение P4)

**Было:** `_create_process_impl()` — top-level функция с 9 аргументами

**Стало:** Метод `ProcessRegistry._create_process(name, class_path, config, priority)` — все зависимости берёт из self. Вспомогательная логика создания bundle вынесена в `_build_process_bundle(name, config)`.

### 3.4 Упрощение ProcessSpawner (решение P5/P6)

**Было:** Spawner создаёт SRM + ConfigManager + LoggerManager + ErrorManager

**Стало:** 
- Spawner создаёт **только** SRM (нужен для queues/events) и лёгкий `_ProcessLogger` (для логирования до старта child).
- ConfigManager и ErrorManager убираются из spawner (они нужны только внутри ProcessManagerProcess, который их создаёт сам как ProcessModule).
- LoggerManager spawner-а заменяется на `_ProcessLogger` с fallback на print.

### 3.5 ProcessMonitor + heartbeat (решение P7)

**Было:** Только polling ProcessStateRegistry

**Стало:** Monitor дополнительно проверяет `process.is_alive()` для каждого зарегистрированного процесса. Если процесс мёртв, но state не обновлён — ставит `"crashed"` и логирует.

```python
def _check_process_health(self):
    for process in self.process._process_registry.os_processes:
        if not process.is_alive():
            pd = self.process.shared_resources.get_process_data(process.name)
            current_status = pd.status if pd else None
            if current_status not in ("stopped", "error", "crashed"):
                self._handle_crash(process.name, process.exitcode)
```

### 3.6 restart_process (решение P2)

Новый метод в ProcessManagerProcess:

```python
def restart_process(self, process_name: str) -> bool:
    """Перезапустить процесс: stop → recreate → start."""
    if not self.stop_process(process_name):
        return False
    # Получить конфиг из сохранённого
    config = self._process_configs.get(process_name)
    if not config:
        return False
    process = self.create_process(
        process_name, config["class"], config, config.get("priority", "normal")
    )
    if process:
        process.start()
        self._priority.apply_priority(process)
        return True
    return False
```

Новая команда `process.restart` в builtin commands.

### 3.7 Итоговая структура модуля

```
process_manager_module/
├── __init__.py                         — Public exports
├── interfaces.py                       — ISystemLauncher, IProcessManagerProcess, IProcessRegistry
│
├── launcher/
│   ├── __init__.py
│   ├── system_launcher.py              (~180 LOC) — Фасад, без main()
│   ├── spawner.py                      (~150 LOC) — Упрощённый bootstrap
│   └── schema.py                       (21)       — DEFAULT_PROCESS_SCHEMA
│
├── process/
│   ├── __init__.py
│   └── process_manager_process.py      (~350 LOC) — Оркестратор + restart
│
├── core/
│   ├── __init__.py
│   ├── process_registry.py             (~220 LOC) — Per-process stop events, _build_process_bundle
│   ├── process_priority.py             (103)      — Без изменений
│   └── process_status.py               (103)      — Без изменений
│
├── runner/
│   ├── __init__.py                     — re-export run_process_function
│   ├── process_runner.py               (~150 LOC) — Main entry point
│   ├── bundle_builder.py               (~120 LOC) — SRM from bundle + memory normalization
│   ├── class_loader.py                 (~30 LOC)  — Dynamic class loading
│   └── console_redirect.py             (~40 LOC)  — Console setup
│
├── monitor/
│   ├── __init__.py
│   └── process_monitor.py              (~170 LOC) — Polling + heartbeat
│
├── adapters/
│   └── schema_adapter.py              (206)       — Без изменений
│
├── platforms/
│   ├── __init__.py
│   └── base.py                         (30)       — Без изменений
│
├── docs/
│   ├── README.md
│   └── CONFIG_CONTRACT.md
│
├── DECISIONS.md                        — NEW: ADR для модуля
└── tests/                              — Обновлённые + новые тесты
```

---

## 4. Атомарные шаги

### Шаг 0 — Baseline (read-only)

**Цель:** Зафиксировать текущее состояние.

```bash
cd Inspector_prototype
python -m pytest multiprocess_framework/modules/process_manager_module/tests -v --tb=short
```

Запомнить число тестов, все ли проходят.

```bash
find multiprocess_framework/modules/process_manager_module -name "*.py" ! -path "*/tests/*" ! -path "*/__pycache__/*" -exec wc -l {} + | sort -rn
```

**Ожидание:** Все тесты зелёные. Метрики записаны.

---

### Шаг 1 — Per-process stop events (CRITICAL, решение P1/P2)

**Это самый важный шаг. Без него фреймворк не может управлять отдельными процессами.**

**Файлы:**

1. **ПРАВКА `core/process_registry.py`:**

   - Добавить `self._stop_events: Dict[str, Event] = {}` в `__init__`
   - В `create_and_register()`: создавать индивидуальный `Event()` для каждого процесса:
     ```python
     def create_and_register(self, name, class_path, config, priority):
         process_stop_event = Event()
         self._stop_events[name] = process_stop_event
         process = self._create_process(name, class_path, config, priority, process_stop_event)
         if process:
             self.add_process(process)
         return process
     ```
   - Переместить `_create_process_impl` внутрь класса как `_create_process()`, убрав дублирующиеся параметры (берутся из self):
     ```python
     def _create_process(self, name, class_path, config, priority, stop_event):
         # Весь код _create_process_impl, но self.queue_registry, self.shared_resources и т.д.
     ```
   - В `stop_all()`: итерировать по всем stop_events:
     ```python
     def stop_all(self, timeout=5.0):
         for ev in self._stop_events.values():
             ev.set()
         self._join_all(timeout)
         # ... terminate/kill cascade
     ```
   - Добавить `stop_one(name, timeout=5.0)`:
     ```python
     def stop_one(self, name: str, timeout: float = 5.0) -> bool:
         ev = self._stop_events.get(name)
         process = self.get_process_by_name(name)
         if not ev or not process:
             return False
         ev.set()
         process.join(timeout=timeout)
         if process.is_alive():
             process.terminate()
             process.join(timeout=1.0)
         if process.is_alive():
             process.kill()
         return True
     ```
   - Добавить `remove_process(name)`:
     ```python
     def remove_process(self, name: str) -> None:
         self.os_processes = [p for p in self.os_processes if p.name != name]
         self._stop_events.pop(name, None)
     ```
   - Убрать `self.stop_event` из `__init__` (больше не нужен единый Event). **Но** оставить `_global_stop_event` для обратной совместимости с `stop_all()` (или убрать, если stop_all итерирует по _stop_events).

2. **ПРАВКА `process/process_manager_process.py`:**

   - `stop_process(name)` → использовать `self._process_registry.stop_one(name)`:
     ```python
     def stop_process(self, process_name=None):
         if process_name:
             timeout = self.get_config("stop_process_timeout") or 5.0
             return self._process_registry.stop_one(process_name, timeout)
         self._process_registry.stop_all()
         return True
     ```
   - `_create_components()` → ProcessRegistry больше не принимает единый stop_event. Вместо этого ProcessManagerProcess передаёт свой stop_event отдельно:
     ```python
     self._process_registry = ProcessRegistry(
         logger=self,
         queue_registry=queue_registry,
         config_manager=None,
         shared_resources=self.shared_resources,
     )
     ```
   - Добавить `restart_process(name)`:
     ```python
     def restart_process(self, process_name: str) -> bool:
         config = self._get_saved_process_config(process_name)
         if not config:
             self._log_error(f"No saved config for '{process_name}'")
             return False
         if not self.stop_process(process_name):
             return False
         self._process_registry.remove_process(process_name)
         # Re-register в shared_resources
         if self.shared_resources:
             self.shared_resources.register_process(process_name, config)
         priority = config.get("priority", "normal")
         process = self._process_registry.create_and_register(
             process_name, config["class"], config, priority
         )
         if process:
             process.start()
             self._priority.apply_priority(process)
             self._log_info(f"Process '{process_name}' restarted")
             return True
         return False
     ```
   - Добавить `_process_configs: Dict[str, Dict]` для хранения конфигов при создании (нужны для restart):
     ```python
     def _create_processes_from_config(self, processes_config):
         # ... existing code ...
         for name, proc_config in valid:
             self._process_configs[name] = proc_config  # NEW: save for restart
     ```
   - Добавить команду `process.restart` в `_register_builtin_commands()`.

3. **ПРАВКА `launcher/spawner.py`:**

   - Убрать `self._stop_event` из bundle custom (он передаётся как отдельный аргумент `run_process_function`):
     ```python
     # Было:
     "custom": {"process_config": process_config, "stop_event": self._stop_event}
     # Стало:
     "custom": {"process_config": process_config}
     ```
   - В `stop()`: `self._stop_event.set()` остаётся (это stop_event для ProcessManagerProcess, не для children).

4. **ПРАВКА тестов:**
   - `test_process_registry.py` — обновить для per-process events
   - `test_process_manager_process.py` — обновить `stop_process`, добавить тест `restart_process`
   - Новый тест: `stop_process("A")` не останавливает процесс "B"

**Верификация:**
```bash
python -m pytest multiprocess_framework/modules/process_manager_module/tests -v --tb=short
```

---

### Шаг 2 — Расслоение process_runner.py (решение P3)

**Цель:** Разбить 447-строчный файл на 4 файла с чёткой ответственностью.

**Файлы:**

1. **СОЗДАТЬ `runner/class_loader.py`:**
   - Переместить `_load_process_class()` (строки 58-76) из process_runner.py
   - Переместить `_ProcessLogger` (строки 28-51) — используется и в class_loader, и в runner

2. **СОЗДАТЬ `runner/bundle_builder.py`:**
   - Переместить `_build_shared_resources_from_bundle()` (строки 120-210)
   - Переместить `_normalize_memory_spec()` (строки 79-93)
   - Переместить `_normalize_memory_config()` (строки 96-117)

3. **СОЗДАТЬ `runner/console_redirect.py`:**
   - Переместить `_setup_console_redirect()` (строки 213-248)

4. **ПРАВКА `runner/process_runner.py`:**
   - Оставить:
     - `run_process_function()` (основная функция)
     - `_run_lifecycle()` (тесно связан с main function)
     - `_log_exception_via_error_manager()` (используется в main function)
     - `_update_process_state()` (используется в main function)
   - Импортировать вынесенные функции:
     ```python
     from .class_loader import _load_process_class, _ProcessLogger
     from .bundle_builder import _build_shared_resources_from_bundle
     from .console_redirect import _setup_console_redirect
     ```

5. **ПРАВКА `runner/__init__.py`:**
   - Обновить re-export: `from .process_runner import run_process_function`

6. **ПРАВКА тестов:**
   - `test_process_runner.py` — обновить импорты для тестов перемещённых функций. Тесты для `_normalize_memory_spec`, `_normalize_memory_config`, `_build_shared_resources_from_bundle` → импорт из `bundle_builder`. Тесты `_load_process_class` → импорт из `class_loader`.

**Верификация:**
```bash
python -m pytest multiprocess_framework/modules/process_manager_module/tests/test_process_runner.py -v
```

---

### Шаг 3 — Упрощение ProcessSpawner (решение P5/P6)

**Цель:** Убрать лишнюю инфраструктуру из spawner. Spawner = «простой стартер», а не mini-framework.

**Файлы:**

1. **ПРАВКА `launcher/spawner.py`:**

   - Убрать создание `ConfigManager` (строки 80-81) — не используется дочерними процессами
   - Заменить `LoggerManager` на `_ProcessLogger` из `runner/class_loader.py`:
     ```python
     from ..runner.class_loader import _ProcessLogger
     # В launch_orchestrator():
     self._logger = _ProcessLogger("spawner")
     ```
   - Убрать создание `ErrorManager` (строки 89-90) — spawner может логировать ошибки через _ProcessLogger
   - Убрать `get_logger()`, `get_error_manager()` методы (больше не нужны)
   - Упростить `stop()` — убрать `self._error_manager.shutdown()` (нет error_manager)
   - `_ProcessLogger` уже имеет info/warning/error с fallback на print

   **Итог:** `launch_orchestrator()` сокращается с ~30 до ~15 строк:
   ```python
   def launch_orchestrator(self) -> bool:
       self._platform.setup_multiprocessing()
       self._shared_resources = SharedResourcesManager(manager_name="shared_resources")
       self._shared_resources.initialize()
       self._logger = _ProcessLogger("spawner")

       process_config = {"processes_config": self._processes_config}
       bundle = {
           "queues": {},
           "config": process_config,
           "custom": {"process_config": process_config},
       }
       self._process = Process(
           target=run_process_function,
           args=(PROCESS_MANAGER_CLASS_PATH, "ProcessManager", self._stop_event, bundle),
           name="ProcessManager",
       )
       self._process.start()
       self._setup_signals()
       return True
   ```

2. **ПРАВКА `launcher/system_launcher.py`:**
   - Убрать `_get_logger()` (строки 48-50) — spawner больше не имеет LoggerManager
   - `_log_info()`, `_log_warning()` → всегда print (spawner — это main-process, print нормально):
     ```python
     def _log_info(self, msg): print(f"[SystemLauncher] {msg}")
     def _log_warning(self, msg): print(f"[SystemLauncher] WARNING: {msg}")
     ```
   - Убрать `main()` (строки 204-213) — мёртвый код (P11)

3. **ПРАВКА тестов:**
   - `test_process_spawner.py` — обновить для упрощённого spawner (нет logger/error_manager)
   - `test_system_launcher.py` — обновить для новых _log_info/_log_warning

**Верификация:**
```bash
python -m pytest multiprocess_framework/modules/process_manager_module/tests/test_process_spawner.py -v
python -m pytest multiprocess_framework/modules/process_manager_module/tests/test_system_launcher.py -v
```

---

### Шаг 4 — ProcessMonitor: heartbeat (решение P7)

**Цель:** Monitor обнаруживает crashed-процессы, а не только self-reported state changes.

**Файлы:**

1. **ПРАВКА `monitor/process_monitor.py`:**

   - Добавить `_check_heartbeats()` — проверять `process.is_alive()` для каждого OS-процесса:
     ```python
     def _check_heartbeats(self):
         """Проверить liveness каждого процесса. Обнаружить crashes."""
         if not hasattr(self.process, '_process_registry'):
             return
         for proc in self.process._process_registry.os_processes:
             if not proc.is_alive():
                 exitcode = proc.exitcode
                 prev = self.previous_states.get(proc.name, {})
                 prev_status = prev.get("status", "unknown")
                 if prev_status not in ("stopped", "error", "crashed"):
                     self.process._log_warning(
                         f"Process '{proc.name}' crashed (exitcode={exitcode})"
                     )
                     self._handle_state_change(
                         proc.name, prev,
                         {"status": "crashed", "exitcode": exitcode, "metadata": {}, "custom": {}}
                     )
                     self.previous_states[proc.name] = {"status": "crashed", "exitcode": exitcode, "metadata": {}, "custom": {}}
     ```

   - В `_monitoring_loop()` — вызывать `_check_heartbeats()` после проверки state registry:
     ```python
     # После существующего кода проверки all_states:
     self._check_heartbeats()
     ```

   - Добавить в `get_stats()` поле `"crashed_processes"`:
     ```python
     "crashed_processes": [
         name for name, state in self.previous_states.items()
         if state.get("status") == "crashed"
     ]
     ```

2. **ПРАВКА тестов:**
   - `test_process_monitor.py` — добавить тест: процесс упал (is_alive=False, exitcode=-9) → monitor обнаруживает crash

**Верификация:**
```bash
python -m pytest multiprocess_framework/modules/process_manager_module/tests/test_process_monitor.py -v
```

---

### Шаг 5 — Bundle contract: спецификация (решение P10)

**Цель:** Формализовать контракт bundle (структура dict, который передаётся в child process).

**Файлы:**

1. **СОЗДАТЬ `core/bundle_contract.py`** (~50 LOC):
   ```python
   """
   Bundle Contract — формальная спецификация connection bundle.
   
   Bundle — pickle-safe dict, который передаётся в дочерний процесс через Process(args=...).
   Создаётся в ProcessRegistry._build_process_bundle().
   Распаковывается в runner/bundle_builder._build_shared_resources_from_bundle().
   """
   from typing import TypedDict, Dict, Any, Optional
   
   # Для документации — не для runtime валидации (TypedDict не pickle-safe)
   BUNDLE_KEYS = ("queues", "config", "custom", "routing_map")
   
   def validate_bundle(bundle: Dict[str, Any]) -> bool:
       """Проверить что bundle содержит обязательные ключи."""
       return all(k in bundle for k in ("queues", "config"))
   
   def build_bundle(
       queues: Dict[str, Any],
       config: Dict[str, Any],
       custom: Optional[Dict[str, Any]] = None,
       routing_map: Optional[Dict[str, Dict[str, Any]]] = None,
   ) -> Dict[str, Any]:
       """Единая точка создания bundle."""
       return {
           "queues": queues,
           "config": config,
           "custom": custom or {},
           "routing_map": routing_map or {},
       }
   ```

2. **ПРАВКА `core/process_registry.py`:**
   - Использовать `build_bundle()` вместо inline dict:
     ```python
     from .bundle_contract import build_bundle
     bundle = build_bundle(queues=queues, config=process_config, custom=custom, routing_map=routing_map)
     ```

3. **ПРАВКА `runner/bundle_builder.py`:**
   - Использовать `validate_bundle()` в начале `_build_shared_resources_from_bundle()`:
     ```python
     from ..core.bundle_contract import validate_bundle
     if not validate_bundle(bundle):
         raise ValueError("Invalid bundle: missing required keys")
     ```

4. **ПРАВКА `docs/CONFIG_CONTRACT.md`:**
   - Добавить секцию «Bundle Contract» с описанием структуры, обязательных/опциональных полей

**Верификация:**
```bash
python -m pytest multiprocess_framework/modules/process_manager_module/tests -v
```

---

### Шаг 6 — interfaces.py: обновить контракты

**Цель:** Обновить interfaces для новых методов.

**Файлы:**

1. **ПРАВКА `interfaces.py`:**

   - В `IProcessManagerProcess` добавить:
     ```python
     @abstractmethod
     def restart_process(self, process_name: str) -> bool:
         """Перезапустить процесс: stop → recreate → start."""
         ...
     ```

   - В `IProcessRegistry` добавить:
     ```python
     @abstractmethod
     def stop_one(self, name: str, timeout: float = 5.0) -> bool:
         """Остановить один процесс (per-process stop event)."""
         ...

     @abstractmethod
     def remove_process(self, name: str) -> None:
         """Удалить процесс из реестра (после stop)."""
         ...
     ```

   - Убрать `ISystemLauncher.shutdown()` алиас (P13) — **оставить только `stop()`**. Или наоборот — **оставить оба** для совместимости с BaseManager lifecycle. Решение: оставить оба, это стандартный lifecycle pattern.

2. **ПРАВКА тестов:**
   - `test_interfaces.py` — добавить тесты для новых методов

**Верификация:**
```bash
python -m pytest multiprocess_framework/modules/process_manager_module/tests/test_interfaces.py -v
```

---

### Шаг 7 — Документация: DECISIONS.md + README update

**Цель:** Задокументировать архитектурные решения.

**Файлы:**

1. **СОЗДАТЬ `modules/process_manager_module/DECISIONS.md`:**

   ```markdown
   # process_manager_module — Архитектурные решения (ADR)
   
   ## ADR-PM-001: Per-process stop events (2026-04-10)
   
   **Контекст:** Все дочерние процессы использовали один stop_event. 
   Остановка одного процесса вызывала остановку всех.
   
   **Решение:** Каждый процесс получает индивидуальный Event() при создании.
   ProcessRegistry хранит Dict[str, Event]. stop_all() итерирует по всем.
   stop_one(name) — устанавливает только Event конкретного процесса.
   
   **Следствие:** Возможен restart_process — stop + recreate + start.
   
   ---
   
   ## ADR-PM-002: ProcessSpawner — минималистичный bootstrap (2026-04-10)
   
   **Контекст:** Spawner создавал ConfigManager, LoggerManager, ErrorManager,
   которые не передавались дочерним процессам.
   
   **Решение:** Spawner создаёт только SRM + _ProcessLogger. Полноценная
   инфраструктура создаётся внутри ProcessManagerProcess (как ProcessModule).
   
   **Следствие:** Один SRM, одна инфраструктура, нет дублирования.
   
   ---
   
   ## ADR-PM-003: Bundle Contract (2026-04-10)
   
   **Контекст:** Bundle (pickle-safe dict для дочернего процесса) создавался
   в ProcessRegistry и распаковывался в process_runner — без формального контракта.
   
   **Решение:** core/bundle_contract.py определяет build_bundle() и validate_bundle().
   Единая точка создания гарантирует формат.
   
   **Следствие:** Изменения в bundle требуют правки в одном месте.
   
   ---
   
   ## ADR-PM-004: Heartbeat monitoring (2026-04-10)
   
   **Контекст:** ProcessMonitor полагался только на self-reported state
   через ProcessStateRegistry. Crashed процессы не обнаруживались.
   
   **Решение:** Monitor дополнительно проверяет process.is_alive().
   Если процесс мёртв без обновления state — ставит "crashed".
   
   **Следствие:** Обнаружение сбоев без зависимости от кода дочернего процесса.
   
   ---
   
   ## ADR-PM-005: Расслоение process_runner.py (2026-04-10)
   
   **Контекст:** process_runner.py (447 LOC) содержал 10 функций с разной
   ответственностью: class loading, memory normalization, SRM building,
   console redirect, lifecycle, error reporting.
   
   **Решение:** Split на 4 файла: process_runner.py (main), bundle_builder.py,
   class_loader.py, console_redirect.py. Публичный API (run_process_function)
   не меняется.
   
   **Следствие:** Каждый файл < 150 LOC, чёткая ответственность.
   ```

2. **ПРАВКА `README.md`:**
   - Обновить диаграмму shutdown cascade с per-process stop events
   - Добавить секцию «Restart process»
   - Обновить диаграмму файловой структуры

3. **ПРАВКА `STATUS.md`:**
   - Обновить стадию: Phase 9 — per-process stop events, runner split, monitor heartbeat

4. **ПРАВКА главного `multiprocess_framework/DECISIONS.md`:**
   - Добавить ссылку на `modules/process_manager_module/DECISIONS.md` в раздел «Модульные решения»

**Верификация:**
```bash
# Проверить что все ссылки из DECISIONS.md ведут на существующие файлы
```

---

### Шаг 8 — Финальная верификация + метрики

**Цель:** Прогнать все тесты, зафиксировать метрики «после».

```bash
cd Inspector_prototype

# 1. Тесты модуля
python -m pytest multiprocess_framework/modules/process_manager_module/tests -v --tb=short

# 2. Тесты всего фреймворка (проверить что ничего не сломали)
python scripts/run_framework_tests.py

# 3. Метрики
find multiprocess_framework/modules/process_manager_module -name "*.py" ! -path "*/tests/*" ! -path "*/__pycache__/*" -exec wc -l {} + | sort -rn
```

**Ожидаемые метрики «после»:**

| Метрика | До | После | Δ |
|---------|-----|-------|---|
| Файлов .py (без tests) | 21 | ~25 | +4 (split runner + bundle_contract) |
| LOC (без tests) | ~2486 | ~2400 | −86 (удалён spawner bloat + dead code) |
| Тест-файлов | 10 | ~12 | +2 (bundle_contract, restart) |
| Тестов (pytest) | TODO | TODO | + |
| Max file LOC | 447 | ~220 | −51% (runner split) |

---

## 5. Порядок зависимостей шагов

```
Шаг 0 (baseline)
    ↓
Шаг 1 (per-process stop events) ★ CRITICAL
    ↓
Шаг 2 (split process_runner.py)
    ↓
Шаг 3 (simplify spawner)
    ↓
Шаг 4 (monitor heartbeat)
    ↓
Шаг 5 (bundle contract)
    ↓
Шаг 6 (update interfaces)
    ↓
Шаг 7 (documentation)
    ↓
Шаг 8 (final verification)
```

Шаги 2, 3, 4 можно делать параллельно (независимы друг от друга), но все зависят от Шага 1.

---

## 6. Диаграмма Graceful Shutdown (целевая)

```
SIGINT / SIGTERM (Ctrl+C)
    │
    ▼
ProcessSpawner._signal_handler()           [Main process]
    ├─ _logger.warning("Signal received")
    └─ stop()
         ├─ _stop_event.set()              [ProcessManager's stop_event]
         ├─ process.join(graceful=3s)
         ├─ if alive: terminate → join → kill
         ├─ on_shutdown() callback
         └─ shared_resources.shutdown()
              │
              ▼
         [Inside ProcessManagerProcess]     [ProcessManager OS-process]
         (detects _stop_event.is_set() → run() exits)
              │
              ▼
         ProcessManagerProcess.shutdown()
              ├─ 1. monitor.stop()          [Stop polling thread]
              ├─ 2. registry.stop_all()     [Stop ALL children]
              │       ├─ for name in _stop_events:
              │       │     _stop_events[name].set()   [Per-process!]
              │       ├─ join_all(timeout=5s)
              │       ├─ for alive: terminate → join(1s)
              │       └─ for alive: kill
              ├─ 3. console.shutdown()
              └─ 4. super().shutdown()      [WorkerManager, RouterManager, LoggerManager]
                        │
                        ▼
                   [Inside each child]      [Child OS-process]
                   (detects own stop_event → run() exits)
                        │
                        ▼
                   process_instance.shutdown()
                   ├─ WorkerManager.stop_all()
                   ├─ RouterManager.shutdown()
                   ├─ LoggerManager.flush()
                   └─ exit(0)

RESULT: Все процессы корректно завершены. Нет zombie processes.
         SharedMemory освобождена. Очереди закрыты. Логи сброшены.
```

### Альтернативный сценарий: stop_process("camera")

```
ProcessManagerProcess.stop_process("camera")
    │
    ▼
ProcessRegistry.stop_one("camera")
    ├─ _stop_events["camera"].set()         [Только camera!]
    ├─ camera_process.join(timeout=5s)
    ├─ if alive: terminate → join(1s)
    └─ if alive: kill

Остальные процессы продолжают работать.
```

### Альтернативный сценарий: restart_process("camera")

```
ProcessManagerProcess.restart_process("camera")
    │
    ├─ stop_process("camera")               [Cascade выше]
    ├─ registry.remove_process("camera")    [Убрать из реестра]
    ├─ shared_resources.register_process("camera", config)
    ├─ _stop_events["camera"] = Event()     [Новый Event!]
    ├─ registry.create_and_register("camera", ...)
    ├─ process.start()
    └─ priority.apply_priority(process)

Camera перезапущена. Остальные процессы не затронуты.
```

---

## 7. Риски и митигации

| Риск | Вероятность | Митигация |
|------|-------------|-----------|
| Windows spawn: per-process Event не picklable | Средняя | Event() из multiprocessing **picklable** на Windows. Проверить в Шаге 1. |
| Split runner сломает импорты в prototype | Низкая | `runner/__init__.py` re-exports `run_process_function` — публичный API не меняется |
| Убрать LoggerManager из spawner → потеря логов при старте | Средняя | `_ProcessLogger` с fallback на print покрывает потребности bootstrapping |
| restart_process: race condition при быстром restart | Низкая | join() гарантирует что старый процесс мёртв перед стартом нового |
| Monitor heartbeat: false positive "crashed" | Средняя | Проверять exitcode: если 0 → "stopped", если != 0 → "crashed" |

---

## 8. Что НЕ входит в этот план

- **Platform-specific priorities** (P12) — отдельная задача, не блокирует M1
- **Correlation ID для REQUEST/RESPONSE** — scope router_module
- **Error_module / Statistics_module рефакторинг** — модули #14, #15
- **Prototype M1** — создаётся после этого плана, отдельный документ
- **Auto-restart policy** (если процесс crashed → автоматически рестартовать) — можно добавить позже в Monitor

---

## 9. Оценка текущего состояния

**Оценка до рефакторинга: 6/10**

| Критерий | Оценка | Комментарий |
|----------|--------|-------------|
| **Архитектура** | 5/10 | Критический баг P1 (shared stop_event) делает невозможным управление отдельными процессами. Это фундаментальный дефект оркестратора. |
| **Код** | 7/10 | Читаемый, документированный. Но process_runner.py (447 LOC) — God Object. _create_process_impl — извлечённая функция с 9 аргументами. |
| **Shutdown** | 7/10 | Cascade корректный для ALL-or-NOTHING. Но нет per-process stop (P1) и нет обнаружения crashes (P7). |
| **Тестируемость** | 7/10 | 10 тест-файлов — хорошее покрытие. Но баг P1 не покрыт тестом (нет теста «stop A не останавливает B»). |
| **Документация** | 7/10 | README 558 LOC, interfaces полные. Нет DECISIONS.md. |
| **Инфраструктура spawner** | 5/10 | Создаёт ConfigManager + LoggerManager + ErrorManager, которые не используются дочерними. Два SRM. |

**Ожидаемая оценка после рефакторинга: 9/10**

Решение P1 (per-process stop events) превращает модуль из «запуск-и-убить-всех» в полноценный оркестратор с возможностью управлять каждым процессом индивидуально, рестартовать, мониторить crashes.

---

## 10. Контрольные вопросы для ревью

После каждого шага ревьюер проверяет:

1. Все тесты модуля зелёные?
2. Тесты фреймворка зелёные (`python scripts/run_framework_tests.py`)?
3. `interfaces.py` — контракты соответствуют реализации?
4. Dict at Boundary соблюдён? (Никаких Pydantic/объектов в bundle)
5. Pickle-safe? (Никаких RLock, non-picklable objects в bundle)
6. Shutdown cascade: каждый процесс корректно завершается?
7. Нет circular imports?
