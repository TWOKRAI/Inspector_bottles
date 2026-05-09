# Plan: Phase 12.5 -- TopologyBridge Runtime

**Date:** 2026-05-09
**Status:** DRAFT

## Обзор

Расширить bridge-пакет до полноценного runtime-моста: горячее добавление/удаление процессов, управление wire'ами (SHM-каналами), diff-based apply topology. После Phase 12.5 любой таб (Pipeline, Recipes, Processes, Settings) сможет управлять runtime через единый bridge API, а Phase 13 (Pipeline Editor) получит готовые примитивы `bridge.hot_add_process()`, `bridge.connect_wire()`, `bridge.apply_topology_diff()`.

**Итого:** ~820 LOC кода + ~510 LOC тестов. 4 новых файла, 4 файла тестов, 3 модифицируемых файла.

---

## Важные выводы из анализа текущего кода

1. **Формат topology YAML:** `processes` -- список dict с ключом `process_name`, `wires` -- список dict с `source`/`target` (формат `process.plugin.port`), **`wire_key` отсутствует** -- его нужно генерировать из `(source, target)` tuple.

2. **Lifecycle-команды** сейчас отправляются напрямую в целевой процесс через `send_command(process_name, "process.start")`. System-level команды (hot_add/hot_remove, wire.setup/teardown) должны идти **в ProcessManager** -- это новый target, новый метод `send_system_command()`.

3. **`_process_exists()`** в TopologyBridge итерирует `topology["processes"]` по `process_name` -- новые методы будут использовать ту же логику.

4. **Protocol-паттерн** уже отработан: `IBridgeCommandSender`, `IBridgeCommandCatalog`, `IBridgeCommandValidator` -- новый `IBridgeSystemSender` дополняет, не ломает.

5. **Тесты bridge** -- pure Python, без Qt, через dataclass-моки. Стиль сохраняем.

6. **DI через extras:** `ctx.extras["topology_bridge"]` -- новые модули (wire_monitor) тоже через extras.

---

## Порядок реализации

### Wave 1 (параллельно, нет зависимостей между задачами)

- Task 12.4: TopologyDiffEngine [PENDING]
- Task 12.5: WireProtocol + SystemCommands [PENDING]
- Task 12.7: WireStatusMonitor [PENDING]

### Wave 2 (зависит от всех задач Wave 1)

- Task 12.6: TopologyBridge Runtime Extensions [PENDING]

---

## Подзадачи

### Task 12.4 -- TopologyDiffEngine

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Pure Python модуль для вычисления diff между двумя topology dict -- (old, new) -> TopologyDiff с гранулярными изменениями по процессам и wire'ам.

**Context:** TopologyBridge.apply_topology_diff() будет вызывать compute_diff() чтобы определить минимальный набор IPC-команд. Без этого модуля bridge может только заменить topology целиком (snapshot swap через TopologyHolder), что неэффективно и не поддерживает частичные обновления.

**Files:**
- `multiprocess_prototype_2/frontend/bridge/diff_engine.py` -- создать
- `multiprocess_prototype_2/frontend/bridge/tests/test_diff_engine.py` -- создать

**Steps:**

1. Создать `diff_engine.py` с тремя frozen dataclass:
   - `ProcessDiff(process_name, kind: Literal["added","removed","modified"], old_config, new_config, changed_fields)` -- как в спеке
   - `WireDiff(wire_key, kind: Literal["added","removed","modified"], old_config, new_config)` -- `wire_key` = `f"{source}|{target}"` (генерация, т.к. в topology YAML нет явного wire_key)
   - `TopologyDiff(processes: list[ProcessDiff], wires: list[WireDiff])` с property: `has_changes`, `added_processes`, `removed_processes`, `modified_processes`, `added_wires`, `removed_wires`, `summary()`

2. Реализовать `compute_diff(old: dict, new: dict) -> TopologyDiff`:
   - Извлечь `old["processes"]` и `new["processes"]` (оба -- списки dict). Построить словари `{process_name: config_dict}` для каждого.
   - added = process_name в new, но не в old
   - removed = process_name в old, но не в new
   - modified = process_name в обоих, но config отличается. Для modified вычислить `changed_fields` -- ключи верхнего уровня dict, значения которых не равны.
   - Аналогично для `old["wires"]` и `new["wires"]`. Ключ идентификации: tuple `(source, target)`, wire_key = `f"{source}|{target}"`. Для modified wires -- сравнить все поля кроме source/target.

3. Добавить `_build_process_index(processes: list[dict]) -> dict[str, dict]` -- вспомогательная функция для индексации по process_name.

4. Добавить `_build_wire_index(wires: list[dict]) -> dict[str, dict]` -- индексация по `f"{source}|{target}"`.

5. Реализовать `summary()`: формат `"+2 процессов, -1 процессов, ~3 процессов, +1 wire'ов"`.

6. Создать тесты в `test_diff_engine.py`:
   - `test_empty_diff` -- оба пустые -> has_changes=False
   - `test_identical_topologies` -- одинаковые -> has_changes=False
   - `test_process_added` -- новый процесс в new
   - `test_process_removed` -- процесс удален из new
   - `test_process_modified` -- config изменен (changed_fields корректны)
   - `test_process_mixed` -- added + removed + modified одновременно
   - `test_wire_added` -- новый wire
   - `test_wire_removed` -- wire удален
   - `test_wire_modified` -- wire с другим description/transport
   - `test_summary_format` -- summary() возвращает строку
   - `test_convenience_properties` -- added_processes, removed_processes и т.п.
   - `test_missing_sections` -- topology без "processes" или "wires" ключей -> пустой diff

**Acceptance criteria:**
- [ ] compute_diff() корректно вычисляет added/removed/modified для процессов
- [ ] compute_diff() корректно вычисляет added/removed/modified для wires (wire_key = `f"{source}|{target}"`)
- [ ] TopologyDiff.summary() -- человекочитаемая сводка
- [ ] has_changes / added_processes / removed_processes / modified_processes -- property работают
- [ ] Pure Python, 0 зависимостей (только stdlib: dataclasses, typing)
- [ ] 12+ тестов, все зеленые: `python -m pytest multiprocess_prototype_2/frontend/bridge/tests/test_diff_engine.py -v`
- [ ] Обрабатывает edge cases: пустой dict, отсутствие ключей "processes"/"wires"

**Out of scope:**
- Рекурсивный deep-diff внутри plugin configs (только верхний уровень ключей)
- Порядок применения команд (это ответственность TopologyBridge.apply_topology_diff)
- Diff для metadata (name, description topology)

**Edge cases:**
- topology без ключа "processes" или "wires" -> трактовать как пустой список
- Два процесса с одинаковым process_name но разным порядком в списке -> корректный diff
- Wire с одинаковыми source/target но разными дополнительными полями -> kind="modified"

**Dependencies:** нет

---

### Task 12.5 -- WireProtocol + SystemCommands

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Data classes для wire-конфигурации (WireConfig, ShmConfig, validate_wire) + builders для system-level IPC-команд (build_hot_add_process, build_wire_setup и т.д.)

**Context:** TopologyBridge.connect_wire() будет создавать WireConfig, валидировать через validate_wire(), строить IPC-команду через build_wire_setup() и отправлять. Два отдельных файла: wire_protocol.py (данные) и system_commands.py (транспорт).

**Files:**
- `multiprocess_prototype_2/frontend/bridge/wire_protocol.py` -- создать
- `multiprocess_prototype_2/frontend/bridge/system_commands.py` -- создать
- `multiprocess_prototype_2/frontend/bridge/tests/test_wire_protocol.py` -- создать
- `multiprocess_prototype_2/frontend/bridge/tests/test_system_commands.py` -- создать

**Steps:**

1. Создать `wire_protocol.py`:
   - `ShmConfig(shm_name: str = "", buffer_slots: int = 4, owner_process: str = "", strategy: str = "direct")` -- frozen dataclass.
   - `WireConfig(wire_key: str, source: str, target: str, transport: str = "router", shm_config: ShmConfig = field(default_factory=ShmConfig))` -- frozen dataclass.
   - Property: `source_process` (source.split(".")[0]), `target_process` (target.split(".")[0]).
   - Метод `with_defaults() -> WireConfig`: если shm_name пуст -> `f"shm_{source_process}_{target_process}"`, если owner_process пуст -> source_process. Возвращает новый WireConfig (frozen).
   - Classmethod `from_topology_entry(key: str, entry: dict) -> WireConfig`: создать из записи topology wires. Маппинг: `entry["source"]` -> source, `entry["target"]` -> target, wire_key = key (или генерация из source|target).
   - Метод `to_topology_entry() -> dict`: обратная конвертация.
   - Функция `validate_wire(wire: WireConfig) -> tuple[bool, str | None]`:
     - source != target (нет self-loop)
     - source_process != target_process (разные процессы)
     - source и target содержат минимум 2 точки (формат process.plugin.port)
     - buffer_slots >= 2

2. Создать `system_commands.py`:
   - `build_process_start(process_name) -> dict` -- `{"cmd": "process.start", "process_name": process_name}`
   - `build_process_stop(process_name) -> dict`
   - `build_process_restart(process_name) -> dict`
   - `build_hot_add_process(process_name, plugin_name, plugin_config=None, *, auto_start=True) -> dict`
   - `build_hot_remove_process(process_name, *, graceful=True) -> dict`
   - `build_wire_setup(wire: WireConfig) -> dict` -- вызывает wire.with_defaults(), формирует полный dict с shm_config вложенным
   - `build_wire_teardown(wire_key, source_process, target_process) -> dict`
   - `SYSTEM_COMMANDS: dict[str, str]` -- реестр всех system-команд для документации

3. Создать `test_wire_protocol.py` (8+ тестов):
   - `test_source_target_process_properties` -- корректное извлечение имени процесса
   - `test_with_defaults_fills_shm_name` -- авто-генерация shm_name
   - `test_with_defaults_fills_owner` -- авто-генерация owner_process
   - `test_from_topology_entry_roundtrip` -- from_topology_entry -> to_topology_entry без потерь
   - `test_validate_self_loop` -- source == target -> (False, ...)
   - `test_validate_same_process` -- source_process == target_process -> (False, ...)
   - `test_validate_bad_format` -- source без точек -> (False, ...)
   - `test_validate_small_buffer` -- buffer_slots < 2 -> (False, ...)
   - `test_validate_happy_path` -- корректный wire -> (True, None)

4. Создать `test_system_commands.py` (7+ тестов):
   - `test_build_process_start` -- проверить ключи и значения dict
   - `test_build_hot_add_process` -- проверить все поля включая plugin_config
   - `test_build_hot_add_defaults` -- plugin_config=None -> {}
   - `test_build_hot_remove_graceful` -- graceful=True
   - `test_build_wire_setup` -- проверить вложенный shm_config
   - `test_build_wire_teardown` -- проверить ключи
   - `test_system_commands_registry` -- SYSTEM_COMMANDS содержит все 7 команд

**Acceptance criteria:**
- [ ] WireConfig.from_topology_entry() / to_topology_entry() -- round-trip без потерь
- [ ] WireConfig.with_defaults() -- авто-заполнение shm_name (`f"shm_{source_process}_{target_process}"`) и owner_process
- [ ] validate_wire() -- все 4 проверки (self-loop, same process, формат, buffer_slots)
- [ ] Все build_* функции возвращают корректные dict с ожидаемыми ключами
- [ ] SYSTEM_COMMANDS -- полный реестр (7 записей)
- [ ] Pure Python, 0 зависимостей
- [ ] 15+ тестов, все зеленые

**Out of scope:**
- Pydantic-валидация wire (используем простой validate_wire)
- Команды для router-уровня (только process и wire уровни)
- Обработка ошибок IPC (это ответственность CommandSender/TopologyBridge)

**Edge cases:**
- WireConfig с source = "proc.plugin" (2 компонента вместо 3) -- validate_wire вернет ошибку
- build_wire_setup с пустым wire_key -- with_defaults() генерирует shm_name, но wire_key остается пустым (валидация не здесь)

**Dependencies:** нет

---

### Task 12.7 -- WireStatusMonitor

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Модуль мониторинга статусов wire'ов с жизненным циклом NOT_CONFIGURED -> PENDING -> IDLE/ACTIVE/BROKEN, timeout-детекцией и метриками (fps, latency, buffer_fill).

**Context:** Без мониторинга bridge отправляет wire.setup и не знает работает ли wire. WireStatusMonitor отслеживает состояние каждого wire, обнаруживает timeout'ы (PENDING > 10 сек -> BROKEN), собирает метрики. Подключается к TopologyBridge через DI (опциональный), к state_multiplexer для получения runtime-ответов.

**Files:**
- `multiprocess_prototype_2/frontend/bridge/wire_monitor.py` -- создать
- `multiprocess_prototype_2/frontend/bridge/tests/test_wire_monitor.py` -- создать

**Steps:**

1. Создать `wire_monitor.py`:
   - `WireStatus(Enum)`: NOT_CONFIGURED, PENDING, IDLE, ACTIVE, BROKEN
   - `WireMetrics` dataclass: fps, latency_ms, buffer_fill (0.0-1.0), last_update (timestamp)
   - `WireStatusMonitor` класс:
     - `__init__(self, *, pending_timeout_sec: float = 10.0, poll_interval_ms: int = 2000)` -- **без sender в __init__**, sender нужен только для polling, передается опционально. Это важно: pure Python логика не зависит от IPC.
     - Внутреннее состояние: `_statuses: dict[str, WireStatus]`, `_metrics: dict[str, WireMetrics]`, `_pending_since: dict[str, float]` (timestamp когда wire стал PENDING)

2. Реализовать lifecycle callbacks:
   - `on_wire_setup_sent(wire_key: str) -> None`: установить статус PENDING, записать timestamp в `_pending_since[wire_key]`
   - `on_wire_teardown_sent(wire_key: str) -> None`: удалить wire из всех внутренних dict

3. Реализовать runtime-ответы:
   - `on_status_received(wire_key: str, status: str) -> None`: обновить WireStatus по строке, удалить из _pending_since если был PENDING
   - `on_metrics_received(wire_key: str, metrics: dict) -> None`: обновить WireMetrics (fps, latency_ms, buffer_fill из dict, last_update = time.time())

4. Реализовать инспекцию:
   - `get_status(wire_key) -> WireStatus`: текущий статус (NOT_CONFIGURED если не найден)
   - `get_all_statuses() -> dict[str, WireStatus]`: копия всех статусов
   - `get_metrics(wire_key) -> WireMetrics | None`: метрики или None
   - `get_broken_wires() -> list[str]`: список wire_key со статусом BROKEN
   - `summary() -> str`: формат `"3 active, 1 pending, 0 broken"` (подсчет по каждому статусу)

5. Реализовать timeout detection:
   - `check_timeouts() -> list[str]`: проверить все PENDING wire'ы. Если `time.time() - _pending_since[key] > pending_timeout_sec` -> перевести в BROKEN, вернуть список переведенных.

6. Реализовать polling (опциональный, QTimer):
   - `start_polling(sender: IBridgeCommandSender) -> None`: ленивое создание QTimer (как в CommandSender -- try/except ImportError), при каждом тике вызывать check_timeouts() + отправлять wire.status запрос через sender. Сохранить sender как `_poll_sender`.
   - `stop_polling() -> None`: остановить QTimer.

7. Создать `test_wire_monitor.py` (10+ тестов):
   - `test_initial_status_not_configured` -- get_status для неизвестного wire
   - `test_on_wire_setup_sent_sets_pending` -- статус PENDING
   - `test_on_status_received_updates` -- PENDING -> ACTIVE
   - `test_on_wire_teardown_removes` -- wire удален из мониторинга
   - `test_on_metrics_received` -- WireMetrics обновлены
   - `test_check_timeouts_pending_to_broken` -- PENDING > timeout -> BROKEN (мокнуть time.time)
   - `test_check_timeouts_no_timeout` -- PENDING < timeout -> остается PENDING
   - `test_get_broken_wires` -- фильтрация по BROKEN
   - `test_get_all_statuses_copy` -- возвращает копию
   - `test_summary_format` -- "1 active, 1 pending, 0 broken"
   - `test_lifecycle_full_cycle` -- setup -> status -> metrics -> teardown

**Acceptance criteria:**
- [ ] WireStatus enum с 5 состояниями
- [ ] on_wire_setup_sent() -> статус PENDING с timestamp
- [ ] on_status_received() -> обновление статуса
- [ ] on_metrics_received() -> обновление WireMetrics
- [ ] check_timeouts() -> PENDING > 10 сек -> BROKEN
- [ ] get_broken_wires() -- для алертов в UI
- [ ] summary() -- "3 active, 1 pending, 0 broken"
- [ ] Pure Python логика (QTimer -- опциональный, за try/except ImportError)
- [ ] 10+ тестов, все зеленые

**Out of scope:**
- Qt signals для уведомления UI о смене статуса (это Phase 13/14)
- Автоматический reconnect broken wire'ов
- Персистенция метрик (только in-memory)

**Edge cases:**
- on_status_received для неизвестного wire_key -- создать запись (wire мог быть создан вне bridge)
- on_wire_teardown_sent для несуществующего wire -- silent ignore
- check_timeouts когда нет PENDING wire'ов -- return []

**Dependencies:** нет

---

### Task 12.6 -- TopologyBridge Runtime Extensions

**Level:** Senior (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Расширить существующий TopologyBridge 6 новыми методами (hot_add, hot_remove, connect_wire, disconnect_wire, apply_topology_diff, get_capabilities) + добавить send_system_command в CommandSender + интегрировать WireStatusMonitor.

**Context:** Это интеграционная задача -- собирает все модули Wave 1 (diff_engine, wire_protocol, system_commands, wire_monitor) в единый оркестратор. TopologyBridge -- единая точка входа для GUI -> Runtime, другие табы уже используют его через `ctx.topology_bridge()`. Критично: порядок операций в apply_topology_diff (из v1) и guard _applying.

**Files:**
- `multiprocess_prototype_2/frontend/bridge/topology_bridge.py` -- модифицировать (+7 методов, +wire_monitor DI, +_applying guard)
- `multiprocess_prototype_2/frontend/bridge/command_sender.py` -- модифицировать (+send_system_command)
- `multiprocess_prototype_2/frontend/bridge/__init__.py` -- модифицировать (реэкспорт новых модулей)
- `multiprocess_prototype_2/frontend/bridge/tests/test_topology_bridge_v2.py` -- создать

**Steps:**

1. **Расширить IBridgeCommandSender** в `topology_bridge.py`:
   - Добавить новый Protocol `IBridgeSystemSender(Protocol)` с методом `send_system_command(self, command: dict[str, Any]) -> None`.
   - Или расширить существующий IBridgeCommandSender -- добавить `send_system_command` (предпочтительнее, т.к. CommandSender один).

2. **Добавить send_system_command в CommandSender** (`command_sender.py`):
   - Новый метод `send_system_command(self, command: dict[str, Any]) -> None`:
     ```python
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
   - Target жестко "ProcessManager" -- единый адресат для system-level операций.

3. **Расширить __init__ TopologyBridge**:
   - Добавить опциональный параметр `wire_monitor: WireStatusMonitor | None = None`.
   - Добавить `self._applying: bool = False` -- guard для apply_topology_diff.
   - Добавить `self._wire_monitor = wire_monitor`.

4. **Реализовать hot_add_process()**:
   - Проверить что процесс НЕ существует в topology (через `_process_exists()`).
   - Построить IPC-команду: `system_commands.build_hot_add_process(process_name, plugin_name, plugin_config, auto_start=auto_start)`.
   - Отправить через `self._sender.send_system_command(command)`.
   - Вернуть True если отправлено, False если процесс уже существует.

5. **Реализовать hot_remove_process()**:
   - Проверить что процесс существует в topology.
   - Найти все wire'ы, связанные с этим процессом (source_process == name или target_process == name). Использовать `_find_process_wires(process_name)` -- новый helper.
   - Отключить все найденные wire'ы (каскад): для каждого wire вызвать `disconnect_wire(wire_key)`.
   - Построить IPC-команду: `system_commands.build_hot_remove_process(process_name, graceful=graceful)`.
   - Отправить через sender.

6. **Реализовать connect_wire()**:
   - Создать WireConfig из аргументов: `WireConfig(wire_key=wire_key, source=source, target=target, transport=transport, shm_config=ShmConfig(**shm_config) if shm_config else ShmConfig())`.
   - Валидировать: `validate_wire(wire_config)`. При ошибке -- log warning, return False.
   - Построить IPC: `system_commands.build_wire_setup(wire_config)`.
   - Отправить через sender.
   - Уведомить wire_monitor: `self._wire_monitor.on_wire_setup_sent(wire_key)` если monitor есть.
   - Return True.

7. **Реализовать disconnect_wire()**:
   - Найти wire в topology по wire_key. Новый helper `_find_wire(wire_key)` ищет wire в `topology["wires"]` по ключу `f"{source}|{target}"`.
   - Если не найден -- log warning, return False.
   - Построить IPC: `system_commands.build_wire_teardown(wire_key, source_process, target_process)`.
   - Отправить через sender.
   - Уведомить wire_monitor: `self._wire_monitor.on_wire_teardown_sent(wire_key)`.
   - Return True.

8. **Реализовать apply_topology_diff()**:
   - Guard: если `self._applying` == True -- log warning, return пустой TopologyApplyResult.
   - `self._applying = True`, try/finally `self._applying = False`.
   - Вычислить diff: `compute_diff(old_topology, new_topology)`.
   - Если `not diff.has_changes` -- return пустой result.
   - Порядок операций (КРИТИЧНО, из v1):
     1. Удалить wire'ы удалённых процессов -- `disconnect_wire()` для wire'ов где source/target -- удаляемый процесс
     2. Удалить wire'ы из diff.removed_wires -- `disconnect_wire()`
     3. Остановить удалённые процессы -- `hot_remove_process()` (без cascade, wire'ы уже отключены в шаге 1)
     4. Создать новые процессы -- `hot_add_process()` для diff.added_processes
     5. Создать новые wire'ы -- `connect_wire()` для diff.added_wires
     6. Обновить конфиги -- `on_field_set()` для каждого changed_field в diff.modified_processes
   - Собирать результаты в TopologyApplyResult.
   - Ловить исключения per-step, записывать в result.errors, продолжать.

9. **Реализовать get_capabilities()**:
   - Вернуть `{"field_set": True, "hot_add": True, "wire": True, "diff_apply": True}`.

10. **Создать TopologyApplyResult** dataclass в `topology_bridge.py`:
    - Поля: processes_added, processes_removed, wires_added, wires_removed, configs_updated, errors (все list[str]).
    - Property `ok` -> len(errors) == 0.
    - Метод `summary()` -- человекочитаемая сводка.

11. **Добавить helper-методы**:
    - `_find_process_wires(process_name: str) -> list[dict]` -- найти все wire'ы из topology, где source или target начинается с process_name.
    - `_find_wire(wire_key: str) -> dict | None` -- найти wire в topology по wire_key (`f"{source}|{target}"`).

12. **Обновить `__init__.py`** -- добавить реэкспорт:
    - `from .diff_engine import TopologyDiff, ProcessDiff, WireDiff, compute_diff`
    - `from .wire_protocol import WireConfig, ShmConfig, validate_wire`
    - `from .system_commands import SYSTEM_COMMANDS` (+ все build_ функции)
    - `from .wire_monitor import WireStatusMonitor, WireStatus, WireMetrics`
    - Обновить `__all__`.

13. **Создать тесты** `test_topology_bridge_v2.py` (20+ тестов):
    - Группа hot_add: happy path, process already exists, отправлен system_command
    - Группа hot_remove: happy path, process not found, cascade wire disconnect
    - Группа connect_wire: happy path, validation fail (self-loop), wire_monitor notified
    - Группа disconnect_wire: happy path, wire not found, wire_monitor notified
    - Группа apply_diff: happy path (add+remove), empty diff, partial failure (error collected), порядок операций (remove wires before processes), guard _applying
    - Группа get_capabilities: возвращает полный dict
    - Группа TopologyApplyResult: ok property, summary format

    Моки: расширить существующие MockSender, MockCatalog, MockValidator из test_topology_bridge.py (можно импортировать или скопировать). Добавить MockSender.send_system_command с записью вызовов.

**Acceptance criteria:**
- [ ] hot_add_process() -- валидация (процесс не существует) + send_system_command + логирование
- [ ] hot_remove_process() -- каскадное отключение wire'ов + send_system_command
- [ ] connect_wire() -- валидация WireConfig + send_system_command + wire_monitor notify
- [ ] disconnect_wire() -- поиск wire по ключу + send_system_command + wire_monitor notify
- [ ] apply_topology_diff() -- compute_diff -> 5-этапный apply (порядок: disconnect wires -> remove processes -> add processes -> add wires -> update configs)
- [ ] TopologyApplyResult -- подробный отчёт с summary()
- [ ] Guard _applying предотвращает вложенные вызовы
- [ ] send_system_command() добавлен в CommandSender (target="ProcessManager")
- [ ] IBridgeCommandSender расширен send_system_command
- [ ] __init__.py реэкспортирует все новые модули
- [ ] Все 82 существующих теста Phase 12 проходят (регрессия): `python -m pytest multiprocess_prototype_2/frontend/bridge/tests/ -v`
- [ ] 20+ новых тестов в test_topology_bridge_v2.py
- [ ] WireStatusMonitor подключен через DI (опциональный)

**Out of scope:**
- Интеграция wire_monitor в state_multiplexer (app.py) -- отдельная задача Phase 13/14
- Интеграция wire_monitor в AppContext (ctx.extras["wire_monitor"]) -- отдельная задача
- Автоматический rebuild CommandCatalog после hot_add (каталог обновляется через on_topology_changed)
- UI-индикация результатов apply_topology_diff (Phase 13)

**Edge cases:**
- apply_topology_diff с old_topology == new_topology -> пустой result (ok=True, нет операций)
- hot_remove_process для процесса без wire'ов -> только remove, без cascade
- connect_wire с невалидным source format -> validation fail, return False
- apply_topology_diff: один процесс не удалился (ошибка), но остальные операции продолжаются
- Вложенный вызов apply_topology_diff (через callback) -> guard блокирует, log warning

**Dependencies:** Task 12.4, Task 12.5, Task 12.7

---

## Риски и решения

| Риск | Вероятность | Решение |
|------|-------------|---------|
| `send_system_command` target "ProcessManager" -- ProcessManager может не обрабатывать новые команды (hot_add, wire.setup) | Высокая | Phase 12.5 строит **GUI-сторону** моста. Runtime-сторона (ProcessManager handler) -- отдельная задача. Сейчас GUI отправляет команды, runtime их обработает когда будет готов. |
| wire_key из `f"{source}\|{target}"` может конфликтовать | Низкая | source+target уникальны для wire в topology. Если два wire между одними процессами но разными портами -- ключ разный (`proc.plugin1.port\|proc2.plugin2.port`). |
| Порядок операций в apply_topology_diff критичен | Средняя | Порядок жестко захардкожен (из v1), протестирован отдельно. Guard _applying предотвращает рекурсию. |
| Регрессия Phase 12 тестов | Низкая | Все новые методы -- дополнения к TopologyBridge, существующие методы не меняются. IBridgeCommandSender расширяется (не ломает Protocol, т.к. runtime_checkable проверяет наличие методов). **Внимание:** добавление send_system_command в IBridgeCommandSender может сломать моки в тестах -- решение: добавить метод-заглушку в MockSender. |
| WireStatusMonitor polling без Qt | Низкая | QTimer за try/except ImportError -- в тестах polling не работает, pure Python логика тестируется отдельно. |
