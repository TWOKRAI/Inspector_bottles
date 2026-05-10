# Phase 12.5 — TopologyBridge Runtime (Полный мост GUI ↔ Runtime)

## Контекст

Phase 12 закрыта — мост работает для **field_set**, **action** и **lifecycle** (start/stop/restart).
Но мост **не умеет**:
1. **Создавать/удалять процессы** в runtime (hot_add / hot_remove)
2. **Управлять wire'ами** (connect / disconnect потоков данных через SHM)
3. **Вычислять diff** между текущей и желаемой topology (гранулярные изменения)
4. Lifecycle-команды **захардкожены** в ProcessesPresenter, недоступны другим табам

v1 всё это умел (~1500 LOC в converters + topology_bridge + wire_data_bridge), но архитектурно это был монолит. v2 Phase 12.5 делает **то же, но модульно** — каждый блок независим, тестируем, подключаем через DI.

**Результат Phase 12.5:** любой таб (Pipeline, Recipes, Processes, Settings) сможет:
- Добавить/удалить процесс в runtime → `bridge.hot_add_process()`
- Подключить/отключить wire → `bridge.connect_wire()`
- Применить новую topology целиком → `bridge.apply_topology_diff(old, new)`
- И всё это undoable через ActionBus

---

## Архитектура: 3 новых модуля + расширение 2 существующих

```
bridge/                              ← пакет, уже существует
├── command_catalog.py               ← существующий (Phase 12)
├── command_sender.py                ← существующий (Phase 12)
├── command_validator.py             ← существующий (Phase 12)
├── topology_bridge.py               ← РАСШИРЯЕТСЯ (Phase 12.5)
├── diff_engine.py                   ← НОВЫЙ — вычисление diff между topology
├── wire_protocol.py                 ← НОВЫЙ — wire data classes + command builders
├── system_commands.py               ← НОВЫЙ — каталог system-level IPC-команд
└── tests/
    ├── test_diff_engine.py          ← НОВЫЙ
    ├── test_wire_protocol.py        ← НОВЫЙ
    ├── test_system_commands.py      ← НОВЫЙ
    ├── test_topology_bridge_v2.py   ← НОВЫЙ (расширения Phase 12.5)
    └── ... (существующие тесты Phase 12 — не трогаем)
```

### Принцип: каждый модуль решает одну задачу

```
TopologyDiffEngine (pure Python)     — ЧТО изменилось? (old→new topology)
     ↓ TopologyDiff
WireProtocol (pure Python)           — КАК описать wire? (data classes)
     ↓ WireConfig, WireCommand
SystemCommands (pure Python)         — КАКУЮ IPC-команду отправить? (command builders)
     ↓ dict (IPC message)
TopologyBridge (orchestrator)        — КООРДИНАЦИЯ: diff → commands → sender
     ↓ CommandSender
IPC → Runtime                        — процессы получают команды
```

Зависимости **однонаправленные**, циклов нет. Каждый блок тестируем изолированно.

---

## Подзадачи

### Task 12.4 — TopologyDiffEngine (pure Python diff)
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Чистая Python-функция: (old_topology, new_topology) → TopologyDiff

**Files:**
- CREATE: `frontend/bridge/diff_engine.py`
- CREATE: `frontend/bridge/tests/test_diff_engine.py`

**Почему отдельный модуль:**
- Pure Python, без Qt, без IPC — тестируется мгновенно
- Используется в TopologyBridge, TopologyMutationHandler, Pipeline Editor, Recipes
- v1 аналог: `converters.py` (~400 LOC) — 4 отдельных diff-функции, тесно связанных с конкретными Pydantic-схемами. v2 работает с generic topology dict.

**Интерфейс:**

```python
@dataclass(frozen=True)
class ProcessDiff:
    """Изменения одного процесса."""
    process_name: str
    kind: Literal["added", "removed", "modified"]
    old_config: dict[str, Any] | None  # None для added
    new_config: dict[str, Any] | None  # None для removed
    changed_fields: list[str]          # только для modified

@dataclass(frozen=True)
class WireDiff:
    """Изменения одного wire."""
    wire_key: str
    kind: Literal["added", "removed", "modified"]
    old_config: dict[str, Any] | None
    new_config: dict[str, Any] | None

@dataclass(frozen=True)
class TopologyDiff:
    """Полный diff между двумя topology."""
    processes: list[ProcessDiff]
    wires: list[WireDiff]

    @property
    def has_changes(self) -> bool: ...

    @property
    def added_processes(self) -> list[ProcessDiff]: ...

    @property
    def removed_processes(self) -> list[ProcessDiff]: ...

    @property
    def modified_processes(self) -> list[ProcessDiff]: ...

    @property
    def added_wires(self) -> list[WireDiff]: ...

    @property
    def removed_wires(self) -> list[WireDiff]: ...

    def summary(self) -> str:
        """Человекочитаемая сводка для логов/дебага."""
        ...

def compute_diff(old: dict, new: dict) -> TopologyDiff:
    """Вычислить diff между двумя topology dict.

    Сравнивает:
    - processes[] по process_name (ключ идентификации)
    - wires[] по wire_key или (source, target) tuple
    - Внутри каждого процесса — plugin configs (field-level diff)
    """
```

**Алгоритм diff (из v1, упрощённый):**
1. Построить dict по process_name: `{name: config}` для old и new
2. added = keys в new, но не в old
3. removed = keys в old, но не в new
4. modified = keys в обоих, но config отличается
5. Для modified — вычислить changed_fields (какие поля config изменились)
6. Аналогично для wires по wire_key

**Acceptance criteria:**
- [ ] compute_diff() корректно вычисляет added/removed/modified для процессов
- [ ] compute_diff() корректно вычисляет added/removed/modified для wires
- [ ] TopologyDiff.summary() — человекочитаемая сводка
- [ ] has_changes / added_processes / removed_processes — удобные property
- [ ] Pure Python, 0 зависимостей (кроме dataclasses, typing)
- [ ] Тесты: 12+ (пустой diff, add process, remove process, modify config, add wire, remove wire, mixed, summary)
**LOC:** ~150

---

### Task 12.5 — WireProtocol + SystemCommands
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Data classes для wire-конфигурации + builders для system-level IPC-команд

**Files:**
- CREATE: `frontend/bridge/wire_protocol.py`
- CREATE: `frontend/bridge/system_commands.py`
- CREATE: `frontend/bridge/tests/test_wire_protocol.py`
- CREATE: `frontend/bridge/tests/test_system_commands.py`

**Почему 2 отдельных модуля:**
- `wire_protocol.py` — **что такое wire** (данные, валидация, defaults)
- `system_commands.py` — **какие IPC-команды отправить** (command builders, format)
- Разделение: данные ≠ транспорт

#### wire_protocol.py

```python
@dataclass(frozen=True)
class ShmConfig:
    """Конфигурация shared memory для wire."""
    shm_name: str = ""            # авто-генерация если пусто
    buffer_slots: int = 4
    owner_process: str = ""       # авто = source_process
    strategy: str = "direct"      # "direct" | "via_pm"

@dataclass(frozen=True)
class WireConfig:
    """Конфигурация одного wire (соединения между процессами)."""
    wire_key: str
    source: str                   # "process.plugin.port"
    target: str                   # "process.plugin.port"
    transport: str = "router"     # "router" | "direct"
    shm_config: ShmConfig = field(default_factory=ShmConfig)

    @property
    def source_process(self) -> str:
        """Имя процесса-источника (до первой точки)."""
        return self.source.split(".")[0]

    @property
    def target_process(self) -> str:
        """Имя процесса-получателя (до первой точки)."""
        return self.target.split(".")[0]

    def with_defaults(self) -> WireConfig:
        """Заполнить авто-значения (shm_name, owner_process)."""
        ...

    @classmethod
    def from_topology_entry(cls, key: str, entry: dict) -> WireConfig:
        """Создать из записи topology dict."""
        ...

    def to_topology_entry(self) -> dict:
        """Конвертировать обратно в topology dict формат."""
        ...

def validate_wire(wire: WireConfig) -> tuple[bool, str | None]:
    """Валидировать wire config.

    Проверки:
    - source != target (нет self-loop)
    - source_process != target_process (разные процессы)
    - source и target — валидный формат (process.plugin.port)
    - buffer_slots >= 2
    """
```

#### system_commands.py

```python
"""Каталог system-level IPC-команд.

Каждая функция: typed args → dict (IPC message payload).
Чистый Python, без побочных эффектов. Легко тестировать,
легко читать в дебагере (print(build_hot_add(...))).
"""

# --- Process lifecycle ---

def build_process_start(process_name: str) -> dict:
    """Команда запуска процесса."""
    return {"cmd": "process.start", "process_name": process_name}

def build_process_stop(process_name: str) -> dict:
    """Команда остановки процесса."""
    return {"cmd": "process.stop", "process_name": process_name}

def build_process_restart(process_name: str) -> dict:
    """Команда перезапуска процесса."""
    return {"cmd": "process.restart", "process_name": process_name}

# --- Hot add/remove ---

def build_hot_add_process(
    process_name: str,
    plugin_name: str,
    plugin_config: dict | None = None,
    *,
    auto_start: bool = True,
) -> dict:
    """Команда горячего добавления процесса.

    ProcessManager создаёт GenericProcess с указанным плагином и стартует.
    """
    return {
        "cmd": "process.hot_add",
        "process_name": process_name,
        "plugin_name": plugin_name,
        "plugin_config": plugin_config or {},
        "auto_start": auto_start,
    }

def build_hot_remove_process(process_name: str, *, graceful: bool = True) -> dict:
    """Команда горячего удаления процесса.

    graceful=True: stop → дождаться завершения → удалить.
    graceful=False: kill → удалить.
    """
    return {
        "cmd": "process.hot_remove",
        "process_name": process_name,
        "graceful": graceful,
    }

# --- Wire management ---

def build_wire_setup(wire: "WireConfig") -> dict:
    """Команда создания wire (SHM-канал между процессами).

    Отправляется в ProcessManager, который:
    1. Создаёт SHM-регион
    2. Отправляет wire.configure source + target процессам
    """
    w = wire.with_defaults()
    return {
        "cmd": "wire.setup",
        "wire_key": w.wire_key,
        "source": w.source,
        "target": w.target,
        "source_process": w.source_process,
        "target_process": w.target_process,
        "transport": w.transport,
        "shm_config": {
            "shm_name": w.shm_config.shm_name,
            "buffer_slots": w.shm_config.buffer_slots,
            "owner_process": w.shm_config.owner_process,
            "strategy": w.shm_config.strategy,
        },
    }

def build_wire_teardown(wire_key: str, source_process: str, target_process: str) -> dict:
    """Команда удаления wire."""
    return {
        "cmd": "wire.teardown",
        "wire_key": wire_key,
        "source_process": source_process,
        "target_process": target_process,
    }

# --- Реестр всех system-команд (для документации и валидации) ---

SYSTEM_COMMANDS: dict[str, str] = {
    "process.start": "Запуск существующего процесса",
    "process.stop": "Остановка процесса",
    "process.restart": "Перезапуск процесса",
    "process.hot_add": "Горячее добавление нового процесса",
    "process.hot_remove": "Горячее удаление процесса",
    "wire.setup": "Создание SHM-канала между процессами",
    "wire.teardown": "Удаление SHM-канала",
}
```

**Acceptance criteria:**
- [ ] WireConfig.from_topology_entry() / to_topology_entry() — round-trip без потерь
- [ ] WireConfig.with_defaults() — авто-заполнение shm_name и owner_process
- [ ] validate_wire() — все проверки (self-loop, формат, buffer_slots)
- [ ] Все build_* функции возвращают корректные dict (проверить ключи/значения)
- [ ] SYSTEM_COMMANDS — полный реестр для инспекции
- [ ] Pure Python, 0 зависимостей
- [ ] Тесты: 15+ (wire_protocol: 8+, system_commands: 7+)
**LOC:** ~250 (wire_protocol ~130, system_commands ~120)

---

### Task 12.6 — TopologyBridge Runtime Extensions
**Level:** Senior (Opus/TeamLead)
**Assignee:** teamlead
**Goal:** Расширить TopologyBridge до полноценного runtime-моста

**Files:**
- MODIFY: `frontend/bridge/topology_bridge.py` — 6 новых методов
- MODIFY: `frontend/bridge/__init__.py` — реэкспорт новых модулей
- CREATE: `frontend/bridge/tests/test_topology_bridge_v2.py`

**Почему в существующий TopologyBridge (не новый класс):**
- TopologyBridge — **единая точка входа** для GUI → Runtime. Другие табы уже используют его через `ctx.topology_bridge()`. Новый класс = новый accessor в AppContext = фрагментация API.
- Новые методы **аналогичны существующим** (hot_add ≈ start_process, connect_wire ≈ on_field_set) — тот же паттерн: validate → build command → send.

**Новый Protocol (расширение IBridgeCommandSender):**

```python
@runtime_checkable
class IBridgeSystemSender(Protocol):
    """Расширение для system-level команд (ProcessManager)."""
    def send_system_command(self, command: dict[str, Any]) -> None: ...
```

Реализация в CommandSender: `send_system_command()` отправляет в ProcessManager (единый целевой процесс для system ops).

**Новые методы TopologyBridge:**

```python
class TopologyBridge:
    # ... существующие методы (Phase 12) ...

    # === Phase 12.5: Hot Process Management ===

    def hot_add_process(
        self,
        process_name: str,
        plugin_name: str,
        plugin_config: dict[str, Any] | None = None,
        *,
        auto_start: bool = True,
    ) -> bool:
        """Добавить новый процесс в runtime (горячее подключение).

        1. Проверяет что процесс ещё не существует в topology
        2. Строит IPC-команду через system_commands.build_hot_add_process()
        3. Отправляет в ProcessManager через sender.send_system_command()

        Returns: True если команда отправлена, False если валидация не прошла.
        """

    def hot_remove_process(
        self,
        process_name: str,
        *,
        graceful: bool = True,
    ) -> bool:
        """Удалить процесс из runtime (горячее отключение).

        1. Проверяет что процесс существует в topology
        2. Автоматически отключает все wire'ы процесса
        3. Отправляет hot_remove в ProcessManager

        Returns: True если команда отправлена.
        """

    # === Phase 12.5: Wire Management ===

    def connect_wire(
        self,
        wire_key: str,
        source: str,       # "process.plugin.port"
        target: str,        # "process.plugin.port"
        *,
        transport: str = "router",
        shm_config: dict[str, Any] | None = None,
    ) -> bool:
        """Создать wire (SHM-канал) между процессами.

        1. Создаёт WireConfig из аргументов
        2. Валидирует через wire_protocol.validate_wire()
        3. Строит IPC-команду через system_commands.build_wire_setup()
        4. Отправляет в ProcessManager

        Returns: True если валидно и отправлено.
        """

    def disconnect_wire(self, wire_key: str) -> bool:
        """Удалить wire по ключу.

        1. Находит wire в topology по wire_key
        2. Строит IPC-команду через system_commands.build_wire_teardown()
        3. Отправляет в ProcessManager

        Returns: True если wire найден и команда отправлена.
        """

    # === Phase 12.5: Topology Diff Apply ===

    def apply_topology_diff(
        self,
        old_topology: dict[str, Any],
        new_topology: dict[str, Any],
    ) -> TopologyApplyResult:
        """Применить минимальный diff к runtime.

        Порядок операций (из v1, критичен!):
        1. Удалить wire'ы удалённых процессов
        2. Остановить удалённые процессы
        3. Создать новые процессы
        4. Создать новые wire'ы
        5. Обновить конфиги изменённых процессов (через on_field_set)

        Guard: _applying flag предотвращает вложенные вызовы.

        Returns: TopologyApplyResult с деталями (что применено, что упало).
        """

    # === Phase 12.5: Inspection (для дебага) ===

    def get_capabilities(self) -> dict[str, bool]:
        """Какие возможности доступны.

        Для дебага и UI — показать что bridge умеет.
        Пример: {"field_set": True, "hot_add": True, "wire": True, "diff_apply": True}
        """
```

**TopologyApplyResult (для отладки):**

```python
@dataclass
class TopologyApplyResult:
    """Результат apply_topology_diff — подробный отчёт для логов."""
    processes_added: list[str]
    processes_removed: list[str]
    wires_added: list[str]
    wires_removed: list[str]
    configs_updated: list[str]
    errors: list[str]

    @property
    def ok(self) -> bool:
        return len(self.errors) == 0

    def summary(self) -> str:
        """Человекочитаемая сводка."""
        parts = []
        if self.processes_added:
            parts.append(f"+{len(self.processes_added)} процессов")
        if self.processes_removed:
            parts.append(f"-{len(self.processes_removed)} процессов")
        if self.wires_added:
            parts.append(f"+{len(self.wires_added)} wire'ов")
        if self.wires_removed:
            parts.append(f"-{len(self.wires_removed)} wire'ов")
        if self.configs_updated:
            parts.append(f"~{len(self.configs_updated)} конфигов")
        if self.errors:
            parts.append(f"⚠ {len(self.errors)} ошибок")
        return ", ".join(parts) or "нет изменений"
```

**Интеграция с CommandSender:**

```python
# Добавить в CommandSender:
def send_system_command(self, command: dict[str, Any]) -> None:
    """Отправить system-level команду в ProcessManager.

    Используется для: process.hot_add, process.hot_remove,
    wire.setup, wire.teardown.
    """
    target = "ProcessManager"
    msg = {
        "type": "command",
        "command": "process.command",
        "data_type": "process.command",
        "sender": self._process.name,
        "targets": [target],
        "data": command,
    }
    self._process.send_message(target, msg)
```

**Guard pattern (из v1):**
```python
class TopologyBridge:
    def __init__(self, ...):
        ...
        self._applying = False  # guard для apply_topology_diff

    def apply_topology_diff(self, old, new) -> TopologyApplyResult:
        if self._applying:
            logger.warning("apply_topology_diff: вложенный вызов — пропускаем")
            return TopologyApplyResult(...)

        self._applying = True
        try:
            diff = compute_diff(old, new)
            ...
        finally:
            self._applying = False
```

**Acceptance criteria:**
- [ ] hot_add_process() — валидация + IPC + логирование
- [ ] hot_remove_process() — каскадное отключение wire'ов + IPC
- [ ] connect_wire() — валидация WireConfig + IPC
- [ ] disconnect_wire() — поиск wire по ключу + IPC
- [ ] apply_topology_diff() — diff → 5-этапный apply (порядок из v1!)
- [ ] TopologyApplyResult — подробный отчёт с summary()
- [ ] Guard _applying предотвращает вложенные вызовы
- [ ] send_system_command() в CommandSender
- [ ] Все существующие тесты Phase 12 проходят (регрессия)
- [ ] Тесты: 20+ (hot_add, hot_remove, connect_wire, disconnect_wire, apply_diff happy path, apply_diff partial failure, guard, cascading disconnect)
**LOC:** ~250 (bridge extensions ~180, sender ~20, result ~50)

---

### Task 12.7 — WireStatusMonitor
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Мониторинг статусов wire'ов после setup — знать что wire реально работает

**Почему это нужно:**
v1 имел `WireDataBridge` (~200 LOC) с полным жизненным циклом wire-статусов. Без мониторинга bridge отправляет `wire.setup` и **не знает** — создался ли SHM, потекли ли данные, или всё зависло. Это production-критичная штука.

**Files:**
- CREATE: `frontend/bridge/wire_monitor.py`
- CREATE: `frontend/bridge/tests/test_wire_monitor.py`

**Интерфейс:**

```python
from enum import Enum

class WireStatus(Enum):
    """Жизненный цикл wire (из v1 WireDataBridge, адаптирован)."""
    NOT_CONFIGURED = "not_configured"  # wire в topology, но setup не отправлен
    PENDING = "pending"                # wire.setup отправлен, ожидаем подтверждения
    IDLE = "idle"                      # SHM создан, middleware подключен, данных нет
    ACTIVE = "active"                  # данные передаются
    BROKEN = "broken"                  # ошибка: SHM или процесс недоступен


@dataclass
class WireMetrics:
    """Метрики одного wire."""
    fps: float = 0.0
    latency_ms: float = 0.0
    buffer_fill: float = 0.0         # 0.0–1.0, заполненность ring buffer
    last_update: float = 0.0         # timestamp последнего обновления


class WireStatusMonitor:
    """Мониторинг статусов и метрик wire'ов.

    Отдельный модуль конструктора — подключается к TopologyBridge через DI.
    Pure Python логика + опциональный QTimer для polling.

    Жизненный цикл wire:
      NOT_CONFIGURED → (bridge.connect_wire) → PENDING → (runtime ответ) → IDLE/ACTIVE
                                                  ↓ (timeout)
                                                BROKEN
    """

    def __init__(
        self,
        sender: IBridgeCommandSender,
        *,
        pending_timeout_sec: float = 10.0,
        poll_interval_ms: int = 2000,
    ) -> None: ...

    # --- Lifecycle callbacks (вызывает TopologyBridge) ---

    def on_wire_setup_sent(self, wire_key: str) -> None:
        """Отметить wire как PENDING. Вызывается из bridge.connect_wire()."""

    def on_wire_teardown_sent(self, wire_key: str) -> None:
        """Удалить wire из мониторинга. Вызывается из bridge.disconnect_wire()."""

    # --- Runtime ответы (вызывается из state_multiplexer) ---

    def on_status_received(self, wire_key: str, status: str) -> None:
        """Обновить статус wire из runtime ответа."""

    def on_metrics_received(self, wire_key: str, metrics: dict) -> None:
        """Обновить метрики wire из runtime ответа."""

    # --- Инспекция (для UI и дебага) ---

    def get_status(self, wire_key: str) -> WireStatus:
        """Текущий статус wire."""

    def get_all_statuses(self) -> dict[str, WireStatus]:
        """Все wire'ы и их статусы."""

    def get_metrics(self, wire_key: str) -> WireMetrics | None:
        """Метрики wire (fps, latency, buffer_fill)."""

    def get_broken_wires(self) -> list[str]:
        """Список wire'ов в состоянии BROKEN (для алертов в UI)."""

    def summary(self) -> str:
        """Сводка: '3 active, 1 pending, 0 broken'."""

    # --- Polling (опциональный, через QTimer) ---

    def start_polling(self) -> None:
        """Запустить периодический опрос wire.status из runtime.

        QTimer создаётся лениво (как в CommandSender).
        Отправляет wire.status запрос через sender.
        """

    def stop_polling(self) -> None:
        """Остановить polling."""

    # --- Timeout detection ---

    def check_timeouts(self) -> list[str]:
        """Проверить PENDING wire'ы на timeout → перевести в BROKEN.

        Вызывается из polling tick или вручную.
        Returns: список wire_key, перешедших в BROKEN.
        """
```

**Интеграция с TopologyBridge (в Task 12.6):**

```python
class TopologyBridge:
    def __init__(self, ..., wire_monitor: WireStatusMonitor | None = None):
        self._wire_monitor = wire_monitor

    def connect_wire(self, wire_key, source, target, **kw) -> bool:
        # ... существующая логика ...
        if ok and self._wire_monitor:
            self._wire_monitor.on_wire_setup_sent(wire_key)
        return ok

    def disconnect_wire(self, wire_key) -> bool:
        # ... существующая логика ...
        if ok and self._wire_monitor:
            self._wire_monitor.on_wire_teardown_sent(wire_key)
        return ok
```

**Интеграция со state_multiplexer (в app.py):**

```python
def _state_multiplexer(msg_dict: dict) -> None:
    _original_state_cb(msg_dict)
    data_type = msg_dict.get("data_type")

    if data_type == "state_delta":
        # ... существующая логика Phase 12 ...
        pass

    elif data_type == "wire_status" and wire_monitor:
        wire_key = msg_dict.get("wire_key", "")
        status = msg_dict.get("status", "")
        wire_monitor.on_status_received(wire_key, status)

    elif data_type == "wire_metrics" and wire_monitor:
        wire_key = msg_dict.get("wire_key", "")
        wire_monitor.on_metrics_received(wire_key, msg_dict.get("data", {}))
```

**Acceptance criteria:**
- [ ] WireStatus enum с 5 состояниями (NOT_CONFIGURED, PENDING, IDLE, ACTIVE, BROKEN)
- [ ] on_wire_setup_sent() → статус PENDING с timestamp
- [ ] on_status_received() → обновление статуса
- [ ] on_metrics_received() → обновление WireMetrics
- [ ] check_timeouts() → PENDING > 10сек → BROKEN
- [ ] get_broken_wires() — для алертов в UI
- [ ] summary() — "3 active, 1 pending, 0 broken"
- [ ] Polling через QTimer (ленивая инициализация, как в CommandSender)
- [ ] Pure Python логика (QTimer — опциональный)
- [ ] Тесты: 10+ (lifecycle, timeout, metrics, summary)
**LOC:** ~150 (monitor ~120, tests ~130)

---

## Порядок реализации

```
Wave 1 (параллельно, нет зависимостей):
  ├── Task 12.4  TopologyDiffEngine              (Middle+, ~150 LOC)
  ├── Task 12.5  WireProtocol + SystemCommands    (Middle+, ~250 LOC)
  └── Task 12.7  WireStatusMonitor               (Middle+, ~150 LOC)

Wave 2 (зависит от Wave 1):
  └── Task 12.6  TopologyBridge Runtime           (Senior, ~270 LOC)
```

**Итого:** ~820 LOC кода + ~510 LOC тестов ≈ 1330 LOC

---

## Что Phase 12.5 даёт Phase 13

| Task Phase 13 | Без Phase 12.5 | С Phase 12.5 |
|---------------|---------------|--------------|
| **13.1a** TopologyMutationHandler | Full snapshot swap через TopologyHolder | `bridge.apply_topology_diff(old, new)` — гранулярно |
| **13.4** Порты + wire creation | GUI-only (runtime не знает) | `bridge.connect_wire(src, tgt)` → end-to-end + мониторинг |
| **13.6** Enhanced Presenter | Собирает lifecycle логику сам | `bridge.hot_add_process()`, `bridge.connect_wire()` |
| **13.10** Live sync | Пишется с нуля (~80 LOC) | **УДАЛЯЕТСЯ** — уже в bridge |
| **Pipeline statusbar** | Нет данных о wire health | `wire_monitor.summary()` → "3 active, 0 broken" |

### Изменения в Phase 13 после Phase 12.5

1. **Task 13.10 удаляется** — hot_add/hot_remove уже в TopologyBridge
2. **Task 13.1a упрощается** — TopologyMutationHandler вызывает `bridge.apply_topology_diff()` вместо raw `topology_holder.set_topology()`
3. **Task 13.4 становится end-to-end** — wire creation в GUI → SHM в runtime + мониторинг статуса
4. **Task 13.6 упрощается** — presenter делегирует bridge, не собирает логику сам
5. **Pipeline Tab statusbar** — может показать wire health через `wire_monitor.get_all_statuses()`

---

## Итоговая архитектура bridge/ после Phase 12.5

```
bridge/
├── command_catalog.py        Phase 12  — plugin commands (field_set, action)
├── command_validator.py      Phase 12  — pre-flight validation
├── command_sender.py         Phase 12  — IPC transport + debounce + send_system_command
├── topology_bridge.py        Phase 12  — orchestrator (field_set, lifecycle)
│                             +12.5     — hot_add/remove, connect/disconnect wire, apply_diff
├── diff_engine.py            Phase 12.5 — ЧТО изменилось (old → new topology)
├── wire_protocol.py          Phase 12.5 — КАК описать wire (data classes, validation)
├── system_commands.py        Phase 12.5 — КАКУЮ IPC-команду послать (builders)
├── wire_monitor.py           Phase 12.5 — wire РАБОТАЕТ? (status lifecycle, metrics, polling)
└── tests/
    ├── test_command_catalog.py       Phase 12 — 25 тестов
    ├── test_command_sender.py        Phase 12 — 13 тестов
    ├── test_command_validator.py     Phase 12 — 11 тестов
    ├── test_topology_bridge.py       Phase 12 — 21 тест
    ├── test_topology_bridge_v2.py    Phase 12.5 — 20+ тестов
    ├── test_diff_engine.py           Phase 12.5 — 12+ тестов
    ├── test_wire_protocol.py         Phase 12.5 — 8+ тестов
    ├── test_system_commands.py       Phase 12.5 — 7+ тестов
    └── test_wire_monitor.py          Phase 12.5 — 10+ тестов
```

**8 модулей, каждый — один файл, одна задача.** Зависимости однонаправленные:

```
TopologyBridge (orchestrator)
  ├── uses → CommandCatalog (plugin commands)
  ├── uses → CommandValidator (validation)
  ├── uses → CommandSender (transport)
  ├── uses → DiffEngine (topology diff)
  ├── uses → SystemCommands (IPC builders)
  ├── uses → WireProtocol (wire data)
  └── uses → WireMonitor (wire health)
```

Каждый модуль тестируется **изолированно**, без моков на соседей.

---

## Новые файлы (8)

| Файл | LOC | Назначение |
|------|-----|------------|
| `bridge/diff_engine.py` | ~150 | TopologyDiffEngine — pure Python diff |
| `bridge/wire_protocol.py` | ~130 | WireConfig, ShmConfig, validate_wire |
| `bridge/system_commands.py` | ~120 | build_hot_add, build_wire_setup, SYSTEM_COMMANDS |
| `bridge/wire_monitor.py` | ~120 | WireStatusMonitor — lifecycle, metrics, polling |
| `bridge/tests/test_diff_engine.py` | ~150 | 12+ тестов diff |
| `bridge/tests/test_wire_protocol.py` | ~100 | 8+ тестов wire |
| `bridge/tests/test_system_commands.py` | ~80 | 7+ тестов builders |
| `bridge/tests/test_wire_monitor.py` | ~130 | 10+ тестов monitor |

## Модифицируемые файлы (3)

| Файл | Изменение |
|------|-----------|
| `bridge/topology_bridge.py` | +7 методов (hot_add, hot_remove, connect_wire, disconnect_wire, apply_topology_diff, get_capabilities) + wire_monitor DI |
| `bridge/command_sender.py` | +1 метод (send_system_command) |
| `bridge/__init__.py` | реэкспорт новых модулей |

---

## Ключевые решения

1. **4 модуля, а не 1 монолит** — diff_engine, wire_protocol, system_commands, wire_monitor тестируются отдельно, используются отдельно
2. **TopologyBridge = orchestrator** — не знает как вычислять diff, не знает формат wire, не мониторит — он координирует
3. **system_commands = builders без side-effects** — `build_hot_add()` возвращает dict, не отправляет. Удобно для тестов, дебага, логирования (`print(build_hot_add(...))`)
4. **TopologyApplyResult** — не просто bool, а детальный отчёт. Для дебага: `result.summary()` → "+2 процессов, +3 wire'ов, ⚠ 1 ошибок"
5. **WireStatusMonitor** — полный жизненный цикл wire (NOT_CONFIGURED → PENDING → IDLE → ACTIVE / BROKEN). Паритет с v1 WireDataBridge, но модульный
6. **Guard _applying** — из v1, предотвращает рекурсию (topology_changed callback → apply → topology_changed → ...)
7. **Порядок apply из v1** — remove wires → remove processes → add processes → add wires → update configs. Порядок критичен: нельзя удалить процесс пока его wire'ы активны
8. **send_system_command** в CommandSender, а не прямой send_message — единый транспорт, единый формат сообщений, единый лог

---

## Сравнение v1 vs v2 после Phase 12.5

| Критерий | v1 | v2 после 12.5 | Кто лучше |
|----------|:--:|:--:|:---------:|
| Полнота функциональности (bridge) | ★★★★★ | ★★★★★ | **Паритет** |
| Архитектурная чистота | ★★★☆☆ | ★★★★★ | **v2** |
| Автоматизация (catalog, resolve) | ★★☆☆☆ | ★★★★★ | **v2** |
| Debounce/coalescing | ★★☆☆☆ | ★★★★★ | **v2** |
| Реактивность (state → GUI) | ★★☆☆☆ | ★★★★★ | **v2** |
| Topology lifecycle (hot_add/remove) | ★★★★★ | ★★★★★ | **Паритет** |
| Wire management + monitoring | ★★★★☆ | ★★★★★ | **v2** (модульнее) |
| Тестируемость | ★★☆☆☆ | ★★★★★ | **v2** |
| Расширяемость (новый плагин) | ★★☆☆☆ | ★★★★★ | **v2** |
| Отладка (inspect, logging) | ★★★☆☆ | ★★★★★ | **v2** |

---

## Верификация

1. **Unit тесты (без Qt):** diff_engine, wire_protocol, system_commands, wire_monitor — мгновенные
2. **Unit тесты (без Qt):** TopologyBridge extensions с mock sender — проверить порядок вызовов
3. **Регрессия:** все 82 теста Phase 12 проходят
4. **Smoke-test:** topology_bridge.apply_topology_diff(old, new) → result.summary()
5. **Smoke-test:** wire_monitor.summary() → "3 active, 1 pending, 0 broken"
6. **Команда:** `python -m pytest multiprocess_prototype/frontend/bridge/tests/ -v`
