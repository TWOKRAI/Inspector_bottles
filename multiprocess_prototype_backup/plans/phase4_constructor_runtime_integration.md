# План: Фаза 4 — Apply + Runtime интеграция конструктора

**Дата:** 2026-05-04
**Статус:** DONE

## Обзор

Превращаем визуальную конфигурацию wires из конструктора (Фазы 1-3) в работающую runtime-систему. Пользователь нажимает Apply — TopologyBridge конвертирует WireDefinition в IPC-команды, ProcessManager аллоцирует SHM, регистрирует routes в RouterManager и подключает FrameShmMiddleware. WireDataBridge мониторит runtime-статусы wires и отображает их на канвасе (цвет: active/broken/idle).

**Ключевой принцип:** максимум переиспользования готовых компонентов (FrameShmMiddleware, MemoryManager, RouterManager.register_route, TopologyManager). Минимум изменений в фреймворке — только новые команды в CommandManager ProcessManagerProcess.

## Порядок выполнения

### Фаза 4.1: Конвертер wires → команды (converters.py)
- Task 4.1: extract_wire_commands [DONE]

### Фаза 4.2: TopologyBridge — SECTION_WIRES apply
- Task 4.2: _apply_wires в TopologyBridge [DONE] (зависит от 4.1)

### Фаза 4.3: ProcessManager — команда wires.apply
- Task 4.3: wires.apply команда в ProcessManagerProcess [DONE] (зависит от 4.1)

### Фаза 4.4: WireDataBridge — мониторинг runtime-статусов
- Task 4.4: WireDataBridge [DONE]

### Фаза 4.5: Runtime feedback на канвасе
- Task 4.5: визуальные статусы wires [DONE] (зависит от 4.4)

### Фаза 4.6: Тесты
- Task 4.6: unit-тесты + integration [DONE] (зависит от 4.1-4.5)

---

## Задачи

### Task 4.1 — extract_wire_commands: конвертер WireDefinition -> runtime-команды

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Реализовать функции diff_wire_configs() и extract_wire_commands() для конвертации секции wires SystemTopology в список runtime-команд для ProcessManager.

**Контекст:** Существующий паттерн в `converters.py`: diff_process_configs() вычисляет diff (added/removed/modified), extract_process_commands() генерирует IPC-команды. Нужно реализовать точно такой же паттерн для wires. Команды должны быть атомарными: каждый wire — отдельная команда. Порядок: сначала teardown removed wires, потом setup added wires, потом reconfigure modified.

**Файлы:**
- `multiprocess_prototype/registers/system_topology/converters.py` — добавить функции diff_wire_configs() и extract_wire_commands()

**Steps:**
1. Добавить функцию `diff_wire_configs(current: Optional[dict], desired: dict) -> dict`:
   - Вход: два SystemTopology dict (или None для первого запуска)
   - Извлечь `wires` из обоих dict'ов
   - Вычислить: wires_added (list[str]), wires_removed (list[str]), wires_modified (list[str])
   - wires_modified: сравнить source, target, transport, shm_config у одинаковых ключей
   - Вернуть dict с has_changes: bool

2. Добавить функцию `extract_wire_commands(current: Optional[dict], desired: dict) -> List[Dict[str, Any]]`:
   - Вызывать diff_wire_configs() для получения diff
   - Генерировать команды в порядке:
     a. `wire.teardown` для каждого wires_removed — `{"cmd": "wire.teardown", "wire_key": "...", "source": "proc.plugin.port", "target": "proc.plugin.port"}`
     b. `wire.setup` для каждого wires_added — `{"cmd": "wire.setup", "wire_key": "...", "source": "proc.plugin.port", "target": "proc.plugin.port", "transport": "router", "shm_config": {...}}`
     c. `wire.teardown` + `wire.setup` для каждого wires_modified (пересоздание)
   - Из wire source/target адреса (формат "process.plugin.port") извлекать process_name для SHM owner и route registration

3. Добавить оба экспорта в `__all__`

**Формат команды wire.setup:**
```python
{
    "cmd": "wire.setup",
    "wire_key": "wire_abc123",
    "source": "camera_0.capture.frame",       # process.plugin.port
    "target": "processor_0.color_mask.frame",  # process.plugin.port
    "source_process": "camera_0",              # извлечённое имя процесса-отправителя
    "target_process": "processor_0",           # извлечённое имя процесса-получателя
    "transport": "router",
    "shm_config": {
        "shm_name": "wire_abc123_shm",
        "buffer_slots": 4,
        "owner_process": "camera_0",
        "strategy": "direct"
    }
}
```

**Формат команды wire.teardown:**
```python
{
    "cmd": "wire.teardown",
    "wire_key": "wire_abc123",
    "source_process": "camera_0",
    "target_process": "processor_0",
    "shm_config": {  # из current state — для cleanup SHM
        "shm_name": "wire_abc123_shm",
        ...
    }
}
```

**Acceptance criteria:**
- [ ] diff_wire_configs() корректно определяет added/removed/modified
- [ ] extract_wire_commands() генерирует команды в правильном порядке (teardown before setup)
- [ ] Авто-заполнение shm_config.shm_name если пустое (wire_key + "_shm")
- [ ] Авто-заполнение shm_config.owner_process если пустое (source process)
- [ ] Работает с current=None (первый запуск)
- [ ] Dict at Boundary: вход и выход — чистые dict'ы

**Out of scope:** Отправка команд в ProcessManager (это Task 4.2). Работа с MemoryManager/RouterManager (это Task 4.3).

**Edge cases:**
- Wire с одинаковым source/target но разным shm_config → modified
- Wire с пустым shm_config → авто-генерация defaults
- Wire с transport="direct" → пропуск SHM аллокации (будущее, пока генерировать warning)

---

### Task 4.2 — _apply_wires в TopologyBridge

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Добавить обработку SECTION_WIRES в TopologyBridge.apply() — новый транспорт D (IPC Commands для wire management).

**Контекст:** TopologyBridge.apply() уже поддерживает 4 секции (processes, sources, pipeline, displays). Паттерн одинаковый: extract_*_commands → send через command_handler. Для wires нужен точно такой же подход. Важен порядок: wires применяются ПОСЛЕ processes (процессы должны существовать).

**Файлы:**
- `multiprocess_prototype/frontend/bridges/topology_bridge.py` — добавить _apply_wires(), интеграцию в apply()
- `multiprocess_prototype/registers/system_topology/schemas.py` — SECTION_WIRES уже определён (проверить импорт)

**Steps:**
1. Добавить импорт `SECTION_WIRES` и `extract_wire_commands` в topology_bridge.py (extract_wire_commands из Task 4.1)

2. Добавить метод `_apply_wires(self, data: dict) -> bool`:
   - Аналогичен `_apply_processes()` — использует command_handler для отправки команд
   - Вызывает `extract_wire_commands(self._current, data)` для получения списка команд
   - Каждую команду отправляет через `self._cmd.send("process.command", data=cmd)`
   - Логирует каждую команду
   - Возвращает False если хотя бы одна команда не отправлена

3. В методе `apply()` добавить вызов `_apply_wires(data)`:
   - ПОСЛЕ `_apply_processes()` (строка 174) и `_apply_sources()` (строка 178)
   - ПЕРЕД `_apply_displays()` (строка 185)
   - Условие: `if section is None or section == SECTION_WIRES:`
   - Guard: если command_handler is None — skip (как в _apply_processes)

4. В `load_from_backend()` добавить инициализацию wires из бэкенда (пустой dict если нет данных):
   - `data["wires"] = {}` — wires пока загружаются только из blueprint, не из runtime state

**Acceptance criteria:**
- [ ] `apply(SECTION_WIRES)` корректно отправляет wire.setup / wire.teardown команды
- [ ] `apply(None)` включает wires после processes/sources, до displays
- [ ] Обратная совместимость: если wires пустые — ничего не происходит
- [ ] Guard: при отсутствии command_handler — пропуск с debug-логом
- [ ] `_current` state обновляется после apply (diff работает при повторном вызове)

**Out of scope:** Мониторинг статусов (Task 4.4). Обработка response от ProcessManager (Task 4.4).

**Dependencies:** Task 4.1

---

### Task 4.3 — wires.apply команда в ProcessManagerProcess

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** Реализовать обработчики команд wire.setup и wire.teardown в ProcessManagerProcess для runtime-настройки SHM-каналов, routes и FrameShmMiddleware.

**Контекст:** Это самая архитектурно-значимая задача фазы. ProcessManagerProcess уже имеет command infrastructure (CommandManager с register_command). Обработчик получает dict-команду и должен:
1. Аллоцировать SHM через MemoryManager.create_memory_dict()
2. Зарегистрировать route в RouterManager через send_message в целевой процесс
3. Подключить FrameShmMiddleware в source/target процессах

**ВАЖНО о текущей архитектуре:**
- FrameShmMiddleware сейчас hardcoded в процессах (CameraProcess, ProcessorProcess) при initialize()
- MemoryManager.create_memory_dict() вызывается ProcessManager'ом для SHM owner
- RouterManager.add_send_middleware/add_receive_middleware — для каждого процесса свой RouterManager
- ProcessManager НЕ имеет доступа к RouterManager дочерних процессов напрямую
- Вывод: setup FrameShmMiddleware в дочернем процессе нужно делать через IPC-команду в этот процесс

**Стратегия реализации (двухэтапная):**
- Этап A: ProcessManager обрабатывает wire.setup — аллоцирует SHM, отправляет IPC-команды в дочерние процессы
- Этап B: Дочерний процесс (ProcessModule) обрабатывает wire.configure — регистрирует FrameShmMiddleware и route

**Файлы:**
- `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py` — register wire.setup/wire.teardown команды
- `multiprocess_framework/modules/process_module/process_module.py` — register wire.configure/wire.deconfigure команды (в базовом ProcessModule, чтобы все дочерние процессы наследовали)

**Steps:**

**Этап A — ProcessManagerProcess (wire.setup / wire.teardown):**

1. В `_register_base_commands()` (строка ~196) добавить два обработчика:
   ```
   "wire.setup": (self._cmd_wire_setup, "Настроить wire-канал (SHM + routes)"),
   "wire.teardown": (self._cmd_wire_teardown, "Разобрать wire-канал"),
   ```

2. Реализовать `_cmd_wire_setup(self, data=None, **kwargs)`:
   - Извлечь из data: wire_key, source_process, target_process, shm_config, transport
   - **SHM аллокация:** если transport == "router" и shm_config непуст:
     - shm_name = shm_config["shm_name"]
     - buffer_slots = shm_config.get("buffer_slots", 4)
     - owner = shm_config.get("owner_process", source_process)
     - Вызвать `self.memory_manager.create_memory_dict(owner, {shm_name: (1, (480, 640, 3), "uint8")}, buffer_slots)`
     - Размеры кадра (480, 640, 3) — defaults, в будущем будут из wire config
   - **IPC в source process:** отправить команду wire.configure через Router/send_message:
     ```
     {"command": "wire.configure", "data": {
         "wire_key": wire_key, "role": "sender",
         "shm_name": shm_name, "owner": owner,
         "buffer_slots": buffer_slots
     }}
     ```
     Целевой процесс: source_process
   - **IPC в target process:** аналогично с role="receiver"
   - Вернуть `{"success": True, "wire_key": wire_key}`

3. Реализовать `_cmd_wire_teardown(self, data=None, **kwargs)`:
   - Извлечь wire_key, source_process, target_process, shm_config
   - **IPC в source/target:** отправить wire.deconfigure
   - **SHM cleanup:** если есть shm_config — пометить SHM для cleanup (не unlink сразу — может быть в использовании)
   - Вернуть `{"success": True, "wire_key": wire_key}`

**Этап B — ProcessModule (wire.configure / wire.deconfigure):**

4. В `ProcessModule` (базовый класс всех процессов) добавить:
   - Dict `_wire_middlewares: dict[str, tuple[FrameShmMiddleware, str]]` — маппинг wire_key → (middleware, role)
   - Обработчик команды "wire.configure" в command_manager:
     - Извлечь role, shm_name, owner, wire_key
     - Создать FrameShmMiddleware(self.memory_manager, owner=owner, slot=shm_name)
     - Если role == "sender": router_manager.add_send_middleware(mw.on_send)
     - Если role == "receiver": router_manager.add_receive_middleware(mw.on_receive)
     - Сохранить в _wire_middlewares[wire_key] = (mw, role)
   - Обработчик "wire.deconfigure":
     - Извлечь wire_key
     - Достать (mw, role) из _wire_middlewares
     - Удалить middleware из router_manager (нужен метод remove_*_middleware — см. Edge cases)
     - Удалить из _wire_middlewares

5. Проверить наличие `remove_send_middleware` / `remove_receive_middleware` в RouterManager:
   - Если нет — добавить (минимально: удаление из списка по identity)
   - Файл: `multiprocess_framework/modules/router_module/core/router_manager.py`

**Acceptance criteria:**
- [ ] wire.setup создаёт SHM через MemoryManager
- [ ] wire.setup отправляет wire.configure в source и target процессы
- [ ] wire.configure в ProcessModule создаёт и регистрирует FrameShmMiddleware
- [ ] wire.teardown отправляет wire.deconfigure и cleanup SHM
- [ ] wire.deconfigure удаляет middleware из RouterManager
- [ ] Dict at Boundary: все команды — dict'ы
- [ ] Обратная совместимость: ProcessModule без wire.configure команды не ломается
- [ ] Hardcoded FrameShmMiddleware в CameraProcess/ProcessorProcess продолжает работать

**Out of scope:**
- Замена hardcoded FrameShmMiddleware в CameraProcess/ProcessorProcess (это рефакторинг после MVP)
- Динамические размеры кадра (пока используем defaults)
- Горячая замена middleware (wire.modify — пока через teardown + setup)

**Edge cases:**
- wire.setup для процесса который ещё не запущен → сохранить pending wires, применить при start
- Дублирующийся wire_key → перезаписать (idempotent)
- RouterManager.remove_*_middleware не существует → нужно добавить (Step 5)
- MemoryManager.create_memory_dict с уже существующим shm_name → должен быть safe (idempotent)
- target process ещё не подключился к SHM → reinitialize_handles() при первом receive

**Dependencies:** Task 4.1 (формат команд)

---

### Task 4.4 — WireDataBridge: мониторинг runtime-статусов

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать WireDataBridge — компонент, мониторящий runtime-статусы wire-соединений (active/broken/idle) и предоставляющий их в GUI.

**Контекст:** По аналогии с ProcessDataBridge (мониторинг процессов), WireDataBridge будет периодически запрашивать статусы у ProcessManager и обновлять UI. Статус wire определяется по наличию SHM-аллокации + активности middleware. GUI подписывается на изменения через Qt-сигнал.

**Файлы:**
- `multiprocess_prototype/frontend/bridges/wire_data_bridge.py` — новый файл
- `multiprocess_prototype/frontend/bridges/__init__.py` — добавить экспорт

**Steps:**

1. Определить enum `WireStatus`:
   ```python
   class WireStatus(str, Enum):
       IDLE = "idle"           # Wire сконфигурирован, но данные не передаются
       ACTIVE = "active"       # Данные передаются (SHM пишется/читается)
       BROKEN = "broken"       # Ошибка: SHM недоступна или процесс упал
       PENDING = "pending"     # wire.setup отправлен, ответ не получен
       NOT_APPLIED = "not_applied"  # Wire существует только в конфигурации
   ```

2. Создать класс `WireDataBridge(QObject)`:
   - `__init__(self, command_handler, topology_editor, parent=None)`
   - Dict `_wire_statuses: dict[str, WireStatus]` — текущие статусы
   - Qt Signal `statuses_changed = Signal(dict)` — emit при изменении статусов

3. Механизм мониторинга (QTimer-based polling):
   - QTimer с интервалом 2000ms (конфигурируемый)
   - При тике: отправить `wire.status` команду через command_handler
   - Обработать response: обновить _wire_statuses
   - Emit statuses_changed если есть изменения

4. Команда `wire.status` в ProcessManagerProcess (минимальная):
   - Зарегистрировать в _register_base_commands
   - Возвращает dict: `{wire_key: {"status": "active/idle/broken", "last_transfer_ts": ...}}`
   - Определение статуса: SHM существует + middleware зарегистрирован → idle/active; нет SHM → not_applied; процесс упал → broken

5. Метод `start_monitoring()` / `stop_monitoring()` — управление QTimer

6. Метод `get_status(wire_key: str) -> WireStatus` — текущий статус wire

7. Метод `on_apply_started(wire_keys: list[str])` — пометить wires как PENDING

8. Метод `on_apply_completed(results: dict)` — обновить статусы из результатов apply

**Acceptance criteria:**
- [ ] WireDataBridge периодически опрашивает ProcessManager
- [ ] Статусы обновляются при получении response
- [ ] Qt Signal statuses_changed эмитится при изменениях
- [ ] start/stop monitoring работают корректно
- [ ] Graceful degradation: при отсутствии command_handler — все wires NOT_APPLIED

**Out of scope:** Детальные метрики (fps, latency, buffer fill) — это Фаза 6. Визуальное отображение — Task 4.5.

**Edge cases:**
- ProcessManager не отвечает (timeout) → статус BROKEN для всех wires
- Wire удалён из конфигурации между тиками polling → удалить из _wire_statuses
- Множественные wires с одним SHM (fan-out) → каждый wire имеет свой статус

**Dependencies:** Task 4.3 (wire.status команда)

---

### Task 4.5 — Runtime feedback: цвет wires на канвасе по статусу

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Визуализировать runtime-статусы wire-соединений на NodeGraphQt канвасе через цвет pipes.

**Контекст:** NodeGraphQt pipe items — это QPainterPath объекты на QGraphicsScene. Их цвет можно менять через `pipe.color` или стили. WireDataBridge (Task 4.4) предоставляет dict {wire_key: WireStatus}. Нужно при изменении статусов обновлять цвета pipes на канвасе.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/canvas/plugin_graph_adapter.py` — добавить метод update_wire_colors() и подключение к WireDataBridge
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/widget.py` — инициализация WireDataBridge, Apply кнопка, подключение сигналов

**Steps:**

1. Определить цветовую схему статусов (константы в plugin_graph_adapter.py):
   ```python
   WIRE_STATUS_COLORS = {
       WireStatus.NOT_APPLIED: (128, 128, 128),  # Серый — не применён
       WireStatus.PENDING: (255, 200, 0),         # Жёлтый — ожидание
       WireStatus.IDLE: (100, 180, 255),           # Голубой — готов, нет данных
       WireStatus.ACTIVE: (50, 220, 80),           # Зелёный — активный
       WireStatus.BROKEN: (230, 60, 60),           # Красный — ошибка
   }
   ```

2. В PluginGraphAdapter добавить метод `update_wire_colors(statuses: dict[str, WireStatus])`:
   - Для каждого wire_key найти соответствующий pipe на канвасе:
     - Из _addr_wire_map найти (source_addr, target_addr) по wire_key (обратный lookup)
     - Найти pipe item в сцене по портам (через GraphBuilder или прямой обход scene.items())
   - Установить цвет pipe в соответствии со статусом
   - Альтернатива: сохранить маппинг wire_key → pipe item при build (в GraphBuilder)

3. В PluginGraphAdapter добавить `_edge_items: dict[str, Any]` — маппинг wire_key → pipe QGraphicsItem:
   - Заполняется в load_scene() после build()
   - Обновляется при connect/disconnect

4. В GraphBuilder.build() возвращать дополнительно маппинг wire_key → pipe item:
   - После создания edge (connect портов) сохранять ссылку на pipe item
   - NodeGraphQt: pipe = viewer.get_pipe() или итерация по scene.items() после connect

5. В ConstructorTabWidget:
   - Создать WireDataBridge в __init__ (если command_handler не None)
   - Подключить WireDataBridge.statuses_changed → adapter.update_wire_colors
   - Добавить кнопку "Apply" в toolbar:
     - При клике: вызвать TopologyBridge.apply(SECTION_WIRES)
     - Пометить wires как PENDING в WireDataBridge
     - Запустить мониторинг
   - При load_scene() — сбросить цвета wires

**Acceptance criteria:**
- [ ] Wires на канвасе меняют цвет в зависимости от runtime-статуса
- [ ] Кнопка Apply отправляет wire-конфигурацию через TopologyBridge
- [ ] PENDING → ACTIVE/IDLE переход визуально заметен
- [ ] При rebuild канваса (load_scene) цвета сбрасываются
- [ ] Без command_handler (тестовый режим) — все wires серые (NOT_APPLIED)

**Out of scope:** Анимации. Tooltip с детальной информацией (fps, latency). Кнопка Apply для всей системы (только wires).

**Edge cases:**
- NodeGraphQt pipe item не имеет прямого API color — может потребоваться subclass или QGraphicsItem.setPen()
- При высокой частоте polling (< 500ms) — debounce update_wire_colors
- Wire создан на канвасе, но ещё не в _edge_items → пропустить

**Dependencies:** Task 4.4 (WireDataBridge), Task 4.2 (TopologyBridge)

---

### Task 4.6 — Тесты: unit + integration для Фазы 4

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Покрыть тестами все новые компоненты Фазы 4: конвертер, TopologyBridge wires, ProcessManager wire commands, WireDataBridge.

**Файлы:**
- `multiprocess_prototype/tests/unit/test_phase4_wire_commands.py` — новый файл
- `multiprocess_prototype/tests/unit/test_phase4_wire_data_bridge.py` — новый файл
- `multiprocess_prototype/tests/unit/test_phase4_topology_bridge_wires.py` — новый файл

**Steps:**

1. **test_phase4_wire_commands.py** — тесты конвертера (Task 4.1):
   - `test_diff_wire_configs_added` — новые wires
   - `test_diff_wire_configs_removed` — удалённые wires
   - `test_diff_wire_configs_modified` — изменённые wires (shm_config, transport)
   - `test_diff_wire_configs_no_changes` — без изменений
   - `test_diff_wire_configs_from_none` — первый запуск (current=None)
   - `test_extract_wire_commands_setup_order` — teardown before setup
   - `test_extract_wire_commands_auto_shm_name` — автогенерация shm_name
   - `test_extract_wire_commands_auto_owner` — автогенерация owner_process
   - `test_extract_wire_commands_empty` — пустые wires

2. **test_phase4_topology_bridge_wires.py** — тесты TopologyBridge (Task 4.2):
   - Mock command_handler
   - `test_apply_wires_sends_commands` — apply(SECTION_WIRES) отправляет команды
   - `test_apply_all_includes_wires` — apply(None) включает wires
   - `test_apply_wires_order_after_processes` — wires после processes
   - `test_apply_wires_no_handler` — graceful skip без handler
   - `test_apply_wires_empty` — пустые wires = no commands

3. **test_phase4_wire_data_bridge.py** — тесты WireDataBridge (Task 4.4):
   - Mock command_handler, mock topology_editor
   - `test_status_idle_after_setup` — wire.setup → IDLE
   - `test_status_not_applied_default` — по умолчанию NOT_APPLIED
   - `test_statuses_changed_signal` — Qt signal emit при обновлении
   - `test_pending_on_apply_started` — PENDING после on_apply_started

4. Запуск: `python -m pytest multiprocess_prototype/tests/unit/test_phase4_*.py -v`

**Acceptance criteria:**
- [ ] Все тесты проходят зелёными
- [ ] Покрытие конвертера: added/removed/modified/no_changes/from_none
- [ ] Покрытие TopologyBridge: apply(wires), apply(all), no handler, empty
- [ ] Покрытие WireDataBridge: статусы, сигналы, start/stop
- [ ] Тесты не требуют GUI (no Qt app) кроме WireDataBridge (pytest-qt)

**Out of scope:** E2E тест с реальными процессами (потребует отдельной инфраструктуры). GUI smoke-тест канваса.

**Dependencies:** Tasks 4.1-4.5

---

## Риски и ограничения

1. **RouterManager.remove_*_middleware не существует** — нужно добавить в фреймворк (Task 4.3, Step 5). Это единственное изменение в фреймворке помимо команд ProcessManager.

2. **ProcessModule не имеет wire.configure** — добавление в базовый класс ProcessModule влияет на все процессы. Нужна обратная совместимость: wire.configure — опциональная команда, существующие процессы без неё продолжают работать.

3. **Hardcoded FrameShmMiddleware** — CameraProcess, ProcessorProcess уже имеют hardcoded middleware. Wire-based middleware будет параллельным каналом. Конфликт возможен если wire описывает тот же SHM что hardcoded. Решение: в Фазе 4 wire-based и hardcoded сосуществуют, в Фазе 5+ — миграция на полный wire-based.

4. **NodeGraphQt pipe color API** — нестандартный, может потребовать monkey-patching или subclass. Исследовать в Task 4.5.

5. **Размеры кадра для SHM** — сейчас hardcoded (480x640x3). В будущем нужен auto-negotiation через port types. Для MVP достаточно defaults с возможностью override через shm_config.

6. **Pending wires при процессе не запущенном** — wire.configure не может быть отправлен процессу который ещё не стартовал. Нужен механизм deferred setup. Для MVP: wire.setup возвращает warning если процесс не найден.
