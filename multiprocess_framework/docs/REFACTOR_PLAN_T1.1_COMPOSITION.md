# Рефакторинг process_module + process_manager_module

## Context

`process_module` (6,757 LOC, 206 тестов) и `process_manager_module` (5,716 LOC, ~120 тестов) — ядро фреймворка. Оба модуля зрелые и рабочие, но содержат архитектурные запахи, которые лучше исправить пока система молодая:

1. **Псевдокомпозиция (Friend anti-pattern)** — `ProcessManagers` и `ProcessLifecycle` напрямую мутируют атрибуты `ProcessModule` (`self.process.worker_manager = ...`)
2. **Command boilerplate** — 6+ идентичных `if isinstance(data, dict): kwargs.update(data)` блоков
3. **Hardcoded SHM** — размер фрейма 480×640×3 зашит в оркестратор
4. **Приватные методы как public API** — `_get_status()`, `_broadcast_full_status()`
5. **IProcessCommunication не Protocol** — нет structural typing
6. **Дублирование pause/resume** — 2×30 строк с идентичной логикой
7. **Defensive hasattr** — ненужные проверки в shutdown

**Цель:** Решить все 7 проблем одним рефакторингом, сохранив 100% backward compat для прототипа v2 и всех тестов.

---

## Изменения правил и паттернов

### Правило 1: ProcessModule владеет своим lifecycle (инверсия оркестрации)

**Было:** `ProcessLifecycle` — оркестратор. `ProcessModule.initialize()` просто делегирует в `self._lifecycle.initialize()`.

**Стало:** `ProcessModule` — оркестратор. `ProcessLifecycle` — набор helper-функций (init_configuration, init_queues, shutdown).

**Почему:** Класс должен владеть своим жизненным циклом. Сейчас `ProcessModule` — "пустая оболочка", а реальная логика в composition-объекте. Когда `ProcessManagerProcess` переопределяет `initialize()`, приходится понимать 3 уровня индирекции: PM.initialize → lifecycle.initialize → process._init_configuration → lifecycle._init_configuration. После рефакторинга — 1 уровень: PM.initialize → super().initialize (который сам всё оркестрирует).

### Правило 2: Return-based composition — «Создай и верни, не трогай хоста»

**Было:** Composition-объекты пишут в атрибуты хоста: `self.process.worker_manager = WorkerManager(...)`.

**Стало:** Composition-объекты возвращают результат, хост сам присваивает: `bundle = create_all(); self.worker_manager = bundle.worker`.

**Почему:** SRP. `ProcessManagers` умеет **создавать** менеджеры. **Назначать** атрибуты — ответственность `ProcessModule`. Если переименовать `self.worker_manager` → `self._wm` — сейчас сломается `ProcessManagers`, хотя это внутренняя деталь `ProcessModule`.

### Правило 3: Публичный API = публичное имя

**Было:** Методы с `_` prefix вызываются снаружи: `self._status._get_status(process)`.

**Стало:** Если метод вызывается извне класса — он public: `self._status.get_status_for_process(process)`.

### Правило 4: IProcessCommunication → Protocol

**Было:** Обычный класс (ни ABC, ни Protocol).

**Стало:** `@runtime_checkable class IProcessCommunication(Protocol)` — structural typing, isinstance-проверки, mypy validation.

---

## Оценка изменений

| # | Изменение | Польза архитектуры | Польза maintenance | Риск | Усилие | Итого |
|---|-----------|:--:|:--:|:--:|:--:|:--:|
| **T1-T4** | **Псевдокомпозиция → ManagersBundle + orchestrator** | **9/10** | **8/10** | **6/10** | **8/10** | **★★★★★** |
| | _Убирает Friend anti-pattern из ядра. ProcessModule контролирует свои атрибуты. Будущий рефакторинг менеджеров (добавление/удаление) безопасен — меняешь только ManagersBundle и _apply_managers_bundle, а не 3 класса одновременно. Тестируемость: create_all() можно тестировать изолированно без ProcessModule._ | | | | | |
| **T5** | **Command boilerplate → _merge_cmd_args** | **3/10** | **7/10** | **1/10** | **2/10** | **★★★☆☆** |
| | _DRY: -60 строк повторяющегося кода. Каждый новый _cmd_* метод будет 3-4 строки вместо 8-10. Снижает вероятность забыть `if isinstance(data, dict)` при добавлении новой команды._ | | | | | |
| **T6** | **pause/resume → _send_worker_command** | **4/10** | **6/10** | **1/10** | **1/10** | **★★★☆☆** |
| | _DRY: -30 строк. Будущие команды (reset, reload) — одна строка вместо 30. Единая точка логирования и обработки ошибок для worker-команд._ | | | | | |
| **T7** | **SHM hardcode → config** | **6/10** | **5/10** | **1/10** | **1/10** | **★★★★☆** |
| | _Устраняет хардкод 480×640×3 из оркестратора. Любое разрешение камеры без правки фреймворка. Баг-превенция: при смене камеры не нужно помнить что надо менять код PM._ | | | | | |
| **T8** | **Private → Public (2 метода)** | **5/10** | **4/10** | **1/10** | **1/10** | **★★★☆☆** |
| | _Честный API: имя отражает реальность. IDE/mypy перестанут предупреждать о доступе к приватным членам. Документация не врёт._ | | | | | |
| **T9** | **IProcessCommunication → Protocol** | **5/10** | **3/10** | **1/10** | **1/10** | **★★★☆☆** |
| | _Structural typing: isinstance-проверки работают, mypy ловит несоответствие. Консистентность с ISharedResources (уже Protocol-стиль)._ | | | | | |
| **T10** | **hasattr cleanup** | **2/10** | **2/10** | **1/10** | **1/10** | **★★☆☆☆** |
| | _Косметика. Убирает ложную защиту — атрибуты всегда есть. Код читается чище._ | | | | | |

### Суммарная оценка

| Метрика | До | После | Дельта |
|---------|:--:|:-----:|:------:|
| Архитектурная чистота | 6.5/10 | **8.5/10** | +2.0 |
| Maintainability | 7/10 | **8.5/10** | +1.5 |
| Тестируемость компонентов | 7/10 | **9/10** | +2.0 |
| LOC (PM process file) | 917 | **~800** | -117 |
| Дублирование кода | ~90 строк | **0** | -90 |
| Публичный API честность | 80% | **100%** | +20% |

**Ключевой выигрыш T1-T4:** Сейчас чтобы добавить новый менеджер — нужно менять 3 файла (ProcessManagers, ProcessModule, ProcessLifecycle). После — только 2: добавить поле в ManagersBundle и строку в `_apply_managers_bundle`. ProcessManagers.create_all() масштабируется линейно.

---

## Принцип: «Read — don't write»

Ключевое правило рефакторинга: **композиционные объекты ЧИТАЮТ из хоста, но НЕ ПИШУТ в его атрибуты**. Запись — ответственность хоста (ProcessModule).

```
До:  ProcessManagers → self.process.worker_manager = WorkerManager(...)  ← мутация
После: ProcessManagers → return ManagersBundle(worker=WorkerManager(...))  ← возврат
       ProcessModule → self.worker_manager = bundle.worker  ← хост сам пишет
```

---

## Задачи

### Task 1 — ManagersBundle dataclass
**Файл:** `process_module/types/types.py`
**Действие:** Добавить dataclass `ManagersBundle` — контейнер для всех менеджеров, создаваемых `ProcessManagers`.

```python
@dataclass
class ManagersBundle:
    """Результат ProcessManagers.create_all() — контейнер менеджеров."""
    worker: Any
    logger: Any
    router: Any
    command: Any
    stats: Any
    console: Any
    error: Any | None = None
    config_manager: Any | None = None
    console_enabled: bool = False
```

---

### Task 2 — ProcessManagers: return вместо мутации
**Файл:** `process_module/managers/process_managers.py`

**Изменения:**
1. Метод `initialize()` → `create_all() -> ManagersBundle`
2. Каждый `_create_*()` возвращает созданный менеджер (не пишет в self.process.*)
3. Новый метод `register_all(bundle, process)` — регистрация в ObservableMixin
4. Новый метод `attach_adapters(bundle, process)` — создание и привязка адаптеров
5. Удалить `register_manager()` и `get_manager()` (делегация больше не нужна)
6. `_connect_event_manager()` — оставить, но вызывать из ProcessModule

**Контракт `create_all()`:** Читает из self.process (name, shared_resources, config_handler, config_manager, queue_registry), создаёт менеджеры в правильном порядке (worker → logger → error → router → stats → command → console), возвращает ManagersBundle. **Ноль записей в self.process**.

---

### Task 3 — ProcessLifecycle: return вместо мутации
**Файл:** `process_module/lifecycle/process_lifecycle.py`

**Изменения:**
1. `_init_configuration()` → `init_configuration() -> tuple[ConfigHandler, ConfigManager, dict]`
   - Больше НЕ пишет в self.process.config_handler/config_manager/config
   - Возвращает тройку (config_handler, config_manager, config)
2. `_init_queues()` → `init_queues() -> tuple[dict, QueueRegistry | None, MemoryManager | None]`
   - Больше НЕ пишет в self.process.queues/queue_registry/memory_manager
   - Возвращает тройку
3. `initialize()` — **УДАЛИТЬ**. Оркестрация переезжает в ProcessModule.initialize()
4. `_register_commands_with_router()` → `register_commands_with_router()` (public)
   - Оставить как есть (читает из process, не пишет атрибуты)
5. `shutdown()` — оставить (teardown mutation допустим)

---

### Task 4 — ProcessModule.initialize(): orchestrator
**Файл:** `process_module/core/process_module.py`

**Изменения:**
1. `initialize()` — полная inline-оркестрация (вместо делегации в lifecycle):
   ```python
   def initialize(self) -> bool:
       try:
           self._init_configuration()
           self._init_queues()
           self._init_managers()
           self._init_communication()
           self._register_process_state()
           self._init_custom_managers()
           self._init_application_threads()
           self._lifecycle.register_commands_with_router()
           self._init_system_threads()
           self.update_process_state(status=ProcessStatus.READY.value)
           # logger context
           logger = self.get_manager("logger")
           if logger and hasattr(logger, "push_context"):
               logger.push_context(proc_name=self.name)
           self.is_initialized = True
           self._log_info(f"Process '{self.name}' initialized successfully")
           return True
       except Exception as e:
           self._log_error(f"Failed to initialize process '{self.name}': {e}")
           return False
   ```

2. `_init_configuration()` — вызывает lifecycle.init_configuration(), сам присваивает:
   ```python
   def _init_configuration(self):
       ch, cm, cfg = self._lifecycle.init_configuration()
       self.config_handler, self.config_manager, self.config = ch, cm, cfg
   ```

3. `_init_queues()` — аналогично:
   ```python
   def _init_queues(self):
       q, qr, mm = self._lifecycle.init_queues()
       self.queues, self.queue_registry, self.memory_manager = q, qr, mm
   ```

4. `_init_managers()` — вызывает create_all(), распаковывает bundle:
   ```python
   def _init_managers(self):
       bundle = self._process_managers.create_all()
       self._apply_managers_bundle(bundle)
   ```

5. Новый метод `_apply_managers_bundle(bundle)`:
   ```python
   def _apply_managers_bundle(self, bundle: ManagersBundle):
       self.worker_manager = bundle.worker
       self.logger_manager = bundle.logger
       self.error_manager = bundle.error
       self.router_manager = bundle.router
       self.stats_manager = bundle.stats
       self.command_manager = bundle.command
       self.console_manager = bundle.console
       self._process_managers.register_all(bundle, self)
       self._process_managers.attach_adapters(bundle, self)
       self._process_managers.connect_event_manager(self)
   ```

6. `_init_state_proxy()` — вызывается из initialize() в конце (как раньше)

**Совместимость тестов:** Методы `_init_configuration()`, `_init_queues()`, `_init_managers()` сохраняют имена → тестовые моки (`process._init_configuration = Mock()`) продолжают работать.

**Совместимость прототипа v2:**
- `GenericProcessApp._init_custom_managers()` — переопределяет хук, работает как раньше
- `GuiProcess(ProcessModule)` — наследует, тесты мокают те же методы
- `ProcessManagerProcessApp(ProcessManagerProcess)` — наследует PM, PM.initialize() вызывает super()

---

### Task 5 — Command boilerplate: _merge_cmd_args helper
**Файл:** `process_manager_module/process/process_manager_process.py`

**Изменения:**
1. Добавить module-level helper:
   ```python
   def _merge_cmd_args(data: dict | None, kwargs: dict) -> dict:
       """Унифицировать вызов из Dispatcher(data_dict) и прямой(kwargs)."""
       if isinstance(data, dict):
           kwargs.update(data)
       return kwargs
   ```

2. Упростить 6 методов `_cmd_process_start/stop/pause/resume/restart/status` — убрать дублирование:
   ```python
   def _cmd_process_start(self, data=None, **kwargs) -> dict:
       args = _merge_cmd_args(data, kwargs)
       if not (pn := args.get("process_name")):
           return {"error": "process_name required"}
       return {"success": self.start_process(pn), "process_name": pn}
   ```

3. Аналогично упростить `_cmd_topology_apply`, `_cmd_topology_diff`

**Экономия:** ~60 строк.

---

### Task 6 — _send_worker_command helper
**Файл:** `process_manager_module/process/process_manager_process.py`

**Изменения:**
1. Новый метод `_send_worker_command(process_name, command) -> bool` — объединяет логику pause/resume
2. `pause_process()` и `resume_process()` делегируют в helper

**Экономия:** ~30 строк.

---

### Task 7 — SHM hardcode fix
**Файл:** `process_manager_module/process/process_manager_process.py`

**Изменения в `_cmd_wire_setup()`:**
```python
# До:
mm.create_memory_dict(owner, {shm_name: (1, (480, 640, 3), "uint8")}, buffer_slots)

# После:
frame_shape = tuple(shm_config.get("frame_shape", (480, 640, 3)))
dtype = shm_config.get("dtype", "uint8")
mm.create_memory_dict(owner, {shm_name: (1, frame_shape, dtype)}, buffer_slots)
```

---

### Task 8 — Private → Public
**Файлы:**
- `process_manager_module/core/process_status.py`: `_get_status()` → `get_status_for_process()`
- `process_manager_module/monitor/process_monitor.py`: `_broadcast_full_status()` → `broadcast_full_status()`

**Обновить все вызовы:**
- `process_manager_process.py:905` — `self._status._get_status(...)` → `self._status.get_status_for_process(...)`
- `process_manager_process.py:238` — `self._process_monitor._broadcast_full_status()` → `self._process_monitor.broadcast_full_status()`
- `process_monitor.py:209` — внутренний вызов `self._broadcast_full_status()` → `self.broadcast_full_status()`
- `process_monitor.py:462` — `self.process._status.get_all_status()` — уже public, ОК
- `process_status.py:49` — внутренний вызов `self._get_status(...)` → `self.get_status_for_process(...)`

---

### Task 9 — IProcessCommunication → Protocol
**Файл:** `process_module/interfaces.py`

```python
# До:
class IProcessCommunication:

# После:
from typing import Protocol, runtime_checkable

@runtime_checkable
class IProcessCommunication(Protocol):
```

---

### Task 10 — hasattr cleanup в PM shutdown
**Файл:** `process_manager_module/process/process_manager_process.py`

```python
# До:
if hasattr(self, "_process_monitor"):
    self._process_monitor.stop()
if hasattr(self, "_process_registry"):

# После:
self._process_monitor.stop()
...
self._process_registry.stop_all(...)
```

Эти атрибуты создаются в `_create_components()` → `__init__()` — они **всегда** существуют.

---

### Task 11 — Обновить тесты
**Файлы:**
- `process_module/tests/test_process_lifecycle.py` — обновить если нужно (моки на _init_* сохранены → должно работать)
- `process_manager_module/tests/test_process_status.py` — обновить вызовы `_get_status`
- Запустить `python scripts/run_framework_tests.py`

---

### Task 12 — Обновить прототип v2
**Файлы в `multiprocess_prototype/`:**
- `frontend/tests/test_gui_process.py` — проверить что моки на _init_* всё ещё работают
- Остальное не должно сломаться (хуки _init_custom_managers сохранены)

---

### Task 13 — Обновить документацию
**Файлы:**
- `process_module/DECISIONS.md` — ADR-PM-009: Return-based composition (ManagersBundle)
- `process_manager_module/DECISIONS.md` — ADR-PMM-008: Command args helper, public API rename
- `process_module/STATUS.md` — обновить версию

---

## Порядок выполнения

```
1. Task 1  — ManagersBundle dataclass (types.py)
2. Task 2  — ProcessManagers refactor (return-based)
3. Task 3  — ProcessLifecycle refactor (return-based)
4. Task 4  — ProcessModule orchestrator
5. Task 9  — IProcessCommunication Protocol
6. Task 8  — Private → Public (status + monitor)
7. Task 10 — hasattr cleanup
8. Task 5  — Command boilerplate helper
9. Task 6  — pause/resume helper
10. Task 7 — SHM hardcode fix
11. Task 11 — Tests
12. Task 12 — Prototype v2 check
13. Task 13 — Documentation
```

Tasks 1–4 — ядро (псевдокомпозиция). Tasks 5–10 — cleanup PM. Tasks 11–13 — верификация.

---

## Затронутые файлы

| Файл | Изменение |
|------|-----------|
| `multiprocess_framework/modules/process_module/types/types.py` | + ManagersBundle |
| `multiprocess_framework/modules/process_module/managers/process_managers.py` | create_all() → return bundle |
| `multiprocess_framework/modules/process_module/lifecycle/process_lifecycle.py` | return-based, remove initialize() |
| `multiprocess_framework/modules/process_module/core/process_module.py` | orchestrator, _apply_managers_bundle |
| `multiprocess_framework/modules/process_module/interfaces.py` | IProcessCommunication → Protocol |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` | 5 improvements |
| `multiprocess_framework/modules/process_manager_module/core/process_status.py` | _get_status → public |
| `multiprocess_framework/modules/process_manager_module/monitor/process_monitor.py` | _broadcast_full_status → public |
| `multiprocess_framework/modules/process_module/DECISIONS.md` | + ADR-PM-009 |
| `multiprocess_framework/modules/process_manager_module/DECISIONS.md` | + ADR-PMM-008 |

---

## Верификация

1. `python scripts/run_framework_tests.py` — все тесты фреймворка (206 + 120)
2. `python -m pytest multiprocess_prototype/ -x` — тесты прототипа v2
3. `python scripts/validate.py` — структурная валидация
4. `python multiprocess_prototype/run.py` — smoke-test запуска

---

## Риски

| Риск | Митигация |
|------|-----------|
| Тесты мокают `_init_configuration` | Сохраняем имена методов на ProcessModule |
| GenericProcessApp._init_custom_managers | Хук остаётся, сигнатура не меняется |
| GuiProcess наследует ProcessModule | initialize() → super() chain сохранена |
| ProcessManagerProcessApp | PM.initialize() вызывает super(), chain сохранён |
