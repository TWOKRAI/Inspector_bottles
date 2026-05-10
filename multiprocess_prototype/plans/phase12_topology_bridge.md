# Plan: Phase 12 — TopologyBridge v2 (GUI <-> Runtime)

**Date:** 2026-05-08
**Status:** ✅ DONE (2026-05-08)

## Обзор

Phase 12 связывает GUI-редактирование с работающей системой. Три основных потока данных:
1. **GUI -> Runtime:** пользователь меняет параметр -> IPC-команда -> плагин в целевом процессе
2. **Runtime -> GUI:** плагин обновляет state -> StateStore -> state_delta -> GuiStateBindings -> виджет
3. **Lifecycle:** добавление/удаление процессов из GUI -> ProcessManager

Текущее состояние: GUI-табы (Phase 10) записывают изменения в RegistersManager (локальный, in-process), ActionBus (Phase 11) обеспечивает undo/redo, но изменения **не покидают GUI-процесс**. ConnectionMap уже знает plugin -> process маппинг. CommandSender уже умеет отправлять IPC-сообщения. GuiStateBindings уже умеет подписывать виджеты на state_delta. Нужно замкнуть цикл.

## Архитектура (целевая)

```
User edit (any tab)
  -> RegisterView.field_changed(register_name, field_name, old, new)
    -> Tab._on_field_changed()
      -> ActionBus.execute(field_set Action)
        -> FieldSetHandler.apply() -> rm.set_field_value()
        -> TopologyBridge.on_field_set(register_name, field_name, value)  [NEW]
          -> ConnectionMap.resolve() -> ResolvedTarget
          -> CommandSender.send_command(target_process, command, {field: value})
            -> IPC -> target ProcessModule -> CommandManager -> Plugin method

Plugin updates state:
  Plugin -> ctx.state_proxy.set("processes.X.state.fps", 30)
    -> StateStoreManager -> state.changed IPC -> all subscribers
      -> GuiProcess._bridge -> state_delta message
        -> GuiStateBindings._on_state_msg() -> widget.setter()
```

## Порядок выполнения

### Phase 1: Command Protocol v2 (фундамент)
- Task 12.1.1: CommandCatalog [PENDING]
- Task 12.1.2: CommandValidator [PENDING]
- Task 12.1.3: CommandSender v2 (batching + debounce) [PENDING]

### Phase 2: TopologyBridge (ядро)
- Task 12.2.1: TopologyBridge core [PENDING] (depends on 12.1.1, 12.1.2, 12.1.3)
- Task 12.2.2: Интеграция с ActionBus [PENDING] (depends on 12.2.1)
- Task 12.2.3: Lifecycle commands [PENDING] (depends on 12.2.1)

### Phase 3: Live State Subscriptions
- Task 12.3.1: ProcessesTab live bindings [PENDING] (depends on 12.2.1)
- Task 12.3.2: ServicesTab + StatusBar live bindings [PENDING] (depends on 12.3.1)
- Task 12.3.3: Интеграция TopologyBridge в AppContext и app.py [PENDING] (depends on 12.2.2, 12.3.2)

## Риски и ограничения

- **IPC latency:** debounce нужен для slider dragging (50ms), иначе спам команд
- **Thread safety:** CommandSender вызывается из Qt main thread, IPC — асинхронный. Текущая реализация через process.send_message() уже thread-safe (pickle + queue)
- **Плагины без commands:** ~8 плагинов имеют `commands = {}`. Для них field_set не генерирует IPC-команду (только локальное сохранение в RegistersManager). Это нормально — stateless плагины (flip, grayscale и т.п.)
- **Нет bootstrap для StateStore:** Phase 8 создала bootstrap.py в framework, но в v2 prototype его нет. State bindings работают через DataReceiverBridge, который получает state_delta сообщения если runtime запущен. Для тестирования Phase 12 без running processes — mock state_delta

---

## Детализация задач

---

### Task 12.1.1 — CommandCatalog (каталог команд из плагинов)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Автогенерация каталога доступных IPC-команд из PluginRegistry + plugin.commands
**Context:** Сейчас ConnectionMap знает plugin->process, но не знает какие команды доступны. CommandCatalog агрегирует plugin.commands со всех плагинов и предоставляет lookup: (plugin_name, field_name) -> (command_name, target_process). Это основа для валидации и маршрутизации.

**Files:**
- `multiprocess_prototype/frontend/bridge/command_catalog.py` — создать
- `multiprocess_prototype/frontend/bridge/tests/__init__.py` — создать
- `multiprocess_prototype/frontend/bridge/tests/test_command_catalog.py` — создать

**Steps:**
1. Создать класс `CommandCatalog` с двумя источниками данных:
   - `PluginRegistry` — для получения `plugin_class.commands` dict (mapping command_name -> method_name)
   - `ConnectionMap` — для маппинга plugin_name -> process_name
2. Метод `CommandCatalog.from_registry_and_topology(registry, topology_dict)` — строит каталог
3. Внутренняя структура: `dict[str, PluginCommands]` где `PluginCommands` = dataclass с полями:
   - `plugin_name: str`
   - `process_name: str`
   - `commands: dict[str, str]` (command_name -> method_name, из plugin.commands)
   - `register_fields: list[str]` (имена полей из registers, если есть)
4. Метод `resolve_field_command(plugin_name, field_name) -> ResolvedCommand | None`:
   - Если plugin.commands содержит `set_{field_name}` -> вернуть его
   - Иначе -> convention: command = `plugin.set_config`, args = `{field_name: value}`
   - Если plugin.commands пуст -> вернуть None (stateless плагин, команда не нужна)
5. Метод `resolve_action_command(plugin_name, command_name) -> ResolvedCommand | None` — для явных команд (Start/Stop и т.п.)
6. Метод `list_commands(plugin_name) -> list[str]` — все команды плагина
7. Метод `all_plugins() -> list[str]` — все плагины с командами
8. Dataclass `ResolvedCommand(process_name, command_name, plugin_name)`

**Acceptance criteria:**
- [ ] `CommandCatalog.from_registry_and_topology()` строит каталог из PluginRegistry + topology dict
- [ ] `resolve_field_command("color_mask", "h_min")` -> ResolvedCommand с process_name и command
- [ ] `resolve_field_command("grayscale", "anything")` -> None (нет commands)
- [ ] `resolve_action_command("capture", "start_capture")` -> ResolvedCommand
- [ ] Тесты: 10+ (построение, resolve field, resolve action, пустые commands, несуществующий плагин)
- [ ] Класс pure Python, без Qt зависимостей

**Out of scope:** Интеграция в AppContext (Task 12.3.3). Валидация аргументов (Task 12.1.2).
**Edge cases:** Плагин есть в registry, но не в topology (нет process) -> resolve возвращает None. Два плагина с одинаковым command_name в разных процессах — разные ResolvedCommand.
**Dependencies:** нет

---

### Task 12.1.2 — CommandValidator (валидация команд перед отправкой)

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Валидация IPC-команд: проверка target_process существования, command_name в каталоге, типов аргументов через FieldInfo
**Context:** Без валидации ошибки молча проглатываются IPC-слоем. Валидатор отсекает невалидные команды на стороне GUI до отправки.

**Files:**
- `multiprocess_prototype/frontend/bridge/command_validator.py` — создать
- `multiprocess_prototype/frontend/bridge/tests/test_command_validator.py` — создать

**Steps:**
1. Создать класс `CommandValidator`:
   - Constructor принимает `CommandCatalog` и `RegistersManagerV2`
2. Метод `validate_field_command(plugin_name, field_name, value) -> ValidationResult`:
   - Проверить: плагин существует в каталоге
   - Проверить: field_name существует в registers (через rm.get_fields())
   - Проверить: value проходит Pydantic валидацию (через rm.validate())
   - Вернуть `ValidationResult(ok=True/False, error=str|None)`
3. Метод `validate_action_command(plugin_name, command_name) -> ValidationResult`:
   - Проверить: команда есть в каталоге для этого плагина
4. Dataclass `ValidationResult(ok: bool, error: str | None)`

**Acceptance criteria:**
- [ ] `validate_field_command("color_mask", "h_min", 50)` -> ok=True
- [ ] `validate_field_command("nonexistent", "x", 1)` -> ok=False, error содержит "плагин"
- [ ] `validate_field_command("color_mask", "nonexistent_field", 1)` -> ok=False
- [ ] `validate_action_command("capture", "start_capture")` -> ok=True
- [ ] Тесты: 8+ (happy path, несуществующий плагин, невалидное поле, невалидное значение)
- [ ] Pure Python, без Qt

**Out of scope:** Валидация сложных типов (nested dict). Валидация lifecycle команд (process.start/stop).
**Edge cases:** Плагин без registers (commands есть, register нет) — validate_field_command возвращает ok=False, validate_action_command работает.
**Dependencies:** Task 12.1.1

---

### Task 12.1.3 — CommandSender v2 (debounce + batch)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Расширить CommandSender: debounce для slider dragging, batch-отправка, интеграция с CommandCatalog
**Context:** Текущий CommandSender (36 LOC) просто формирует dict и вызывает process.send_message(). Нужно: (a) debounce — при быстром перетаскивании slider отправляется только последнее значение за 50ms, (b) опциональный batch — несколько field_set в одном сообщении

**Files:**
- `multiprocess_prototype/frontend/bridge/command_sender.py` — модифицировать
- `multiprocess_prototype/frontend/bridge/tests/test_command_sender.py` — создать

**Steps:**
1. Добавить зависимость на `QTimer` для debounce (ленивый import, чтобы тесты без Qt тоже работали)
2. Новый метод `send_field_command(plugin_name, field_name, value, *, debounce_ms=0)`:
   - Если `debounce_ms > 0`: сохранить (plugin_name, field_name, value) в pending dict, запустить/перезапустить QTimer
   - При срабатывании таймера: вызвать `_flush_pending()` -> формирует и отправляет IPC msg
   - Если `debounce_ms == 0`: отправить немедленно
3. Pending dict: `dict[tuple[str, str], Any]` — ключ = (plugin_name, field_name), значение = последний value. Это обеспечивает coalescing: несколько быстрых изменений одного поля -> одна отправка
4. Существующий `send_command()` остаётся без изменений (обратная совместимость)
5. Новый метод `send_action_command(plugin_name, command_name, args=None)` — для явных команд (Start/Stop)
6. Принимает опциональный `CommandCatalog` для resolve target_process
7. Fallback: если catalog не задан, используется прямой target (как сейчас)

**Acceptance criteria:**
- [ ] `send_field_command("color_mask", "h_min", 50, debounce_ms=50)` — отправка через 50ms
- [ ] При 10 быстрых вызовах с debounce_ms=50 — отправляется 1 IPC-сообщение с последним значением
- [ ] `send_command()` работает как прежде (обратная совместимость)
- [ ] Тесты: 10+ (immediate send, debounce coalescing, flush, action command, без catalog)
- [ ] При отсутствии Qt (тесты) — fallback на немедленную отправку

**Out of scope:** Batch из нескольких разных полей в одном сообщении (можно добавить позже). Retry при ошибке IPC.
**Edge cases:** Вызов send_field_command после shutdown процесса -> log warning, не падать. Два разных поля с debounce -> два разных таймера/записи в pending.
**Dependencies:** Task 12.1.1 (для resolve, но опционально — работает и без catalog)

---

### Task 12.2.1 — TopologyBridge core (ядро моста GUI -> Runtime)

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** Единый класс TopologyBridge, который при field_set автоматически отправляет IPC-команду в целевой процесс, а при state_delta — обновляет RegistersManager
**Context:** Сейчас FieldSetHandler.apply() вызывает rm.set_field_value() — это чисто in-process. TopologyBridge перехватывает этот момент и дополнительно отправляет IPC. Обратный путь: state_delta от runtime -> обновление rm (чтобы RegistersManager отражал реальное состояние).

**Files:**
- `multiprocess_prototype/frontend/bridge/topology_bridge.py` — создать
- `multiprocess_prototype/frontend/bridge/tests/test_topology_bridge.py` — создать
- `multiprocess_prototype/frontend/bridge/__init__.py` — обновить (re-export)

**Steps:**
1. Создать класс `TopologyBridge`:
   - Constructor: `(command_sender, command_catalog, command_validator, registers_manager, topology_holder)`
   - Все зависимости через DI (не глобалы)
2. Метод `on_field_set(register_name: str, field_name: str, value: Any) -> bool`:
   - Вызывает `command_validator.validate_field_command()` -> если не ok, log warning, return False
   - Вызывает `command_catalog.resolve_field_command()` -> ResolvedCommand
   - Если resolved is None (stateless плагин) -> return True (нет IPC, но не ошибка)
   - Определить debounce: для полей с FieldInfo.widget_type in ("slider", "spinbox") -> debounce_ms=50, иначе 0
   - Вызвать `command_sender.send_field_command(resolved.process_name, resolved.command_name, {field_name: value}, debounce_ms=...)`
   - Return True
3. Метод `on_action_command(plugin_name: str, command_name: str, args: dict | None = None) -> bool`:
   - Валидация + resolve + send_action_command
4. Метод `on_state_delta(path: str, value: Any)`:
   - Парсить path: `processes.{name}.config.{field}` -> обновить rm.set_field_value(plugin_name, field, value)
   - Это обратная синхронизация: runtime сообщает что параметр реально применён
5. Метод `on_topology_changed(new_topology: dict)`:
   - Пересобрать ConnectionMap и CommandCatalog
   - Вызывается при recipe_apply или hot-reload
6. Property `is_connected: bool` — флаг, показывающий есть ли живой IPC (пока всегда True)

**Acceptance criteria:**
- [ ] `on_field_set("color_mask", "h_min", 50)` -> send_field_command вызван с правильным process_name
- [ ] `on_field_set("grayscale", "x", 1)` -> не вызывает send (stateless плагин), return True
- [ ] Невалидная команда -> log warning, return False
- [ ] debounce 50ms для slider-полей
- [ ] `on_state_delta("processes.cam.config.fps", 30)` -> rm обновлён
- [ ] `on_topology_changed()` -> catalog пересобран
- [ ] Тесты: 15+ (field_set happy path, stateless skip, validation fail, state_delta sync, topology_changed, debounce detection)
- [ ] Pure Python core, Qt только через CommandSender (ленивый import)

**Out of scope:** Lifecycle commands (process start/stop) — Task 12.2.3. Подключение к реальному IPC (Task 12.3.3).
**Edge cases:** field_set для поля, которого нет в registers -> validator отклонит. state_delta с неизвестным path -> игнорировать (log debug). Concurrent field_set + state_delta для одного поля -> field_set побеждает (user intent > runtime state).
**Dependencies:** Task 12.1.1, 12.1.2, 12.1.3

---

### Task 12.2.2 — Интеграция TopologyBridge с ActionBus

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** При ActionBus.execute(field_set) автоматически вызывать TopologyBridge.on_field_set(), при undo — отправлять revert-команду
**Context:** Сейчас FieldSetHandler.apply() только вызывает rm.set_field_value(). Нужно добавить вызов bridge.on_field_set() после успешного apply. Два варианта: (a) модифицировать FieldSetHandler, (b) добавить callback в ActionBus. Выбираем (b) — чище, не ломает существующий handler.

**Files:**
- `multiprocess_prototype/frontend/actions/handlers/field_set_handler.py` — модифицировать
- `multiprocess_prototype/frontend/actions/bus_factory.py` — модифицировать
- `multiprocess_prototype/frontend/actions/tests/test_bridge_integration.py` — создать

**Steps:**
1. Модифицировать `FieldSetHandler.__init__()`: принимает опциональный `topology_bridge: TopologyBridge | None = None`
2. В `FieldSetHandler.apply()`: после `rm.set_field_value()` вызвать `self._bridge.on_field_set(register_name, field_name, value)` если bridge задан
3. В `FieldSetHandler.revert()`: аналогично вызвать `self._bridge.on_field_set(register_name, field_name, old_value)` — при undo отправляем откат в runtime
4. Модифицировать `bus_factory.create_action_bus()`: принимает опциональный `topology_bridge` -> передаёт в FieldSetHandler
5. Обратная совместимость: если bridge=None, поведение не меняется (текущие тесты не ломаются)

**Acceptance criteria:**
- [ ] `bus.execute(field_set_action)` -> `bridge.on_field_set()` вызван
- [ ] `bus.undo()` -> `bridge.on_field_set()` вызван с old_value
- [ ] `bus.execute(field_set_action)` с bridge=None -> работает как раньше (обратная совместимость)
- [ ] Существующие тесты `test_handlers.py` проходят без изменений
- [ ] Новые тесты: 8+ (apply+bridge, revert+bridge, bridge=None fallback, bridge validation fail)

**Out of scope:** Recipe apply через bridge (topology lifecycle — Task 12.2.3). Coalescing в ActionBus (уже есть).
**Edge cases:** bridge.on_field_set() возвращает False (validation fail) -> log warning, не блокировать apply (GUI всегда responsive).
**Dependencies:** Task 12.2.1

---

### Task 12.2.3 — Lifecycle commands (process start/stop/restart)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** TopologyBridge обрабатывает lifecycle-команды: start/stop/restart процесса, add/remove процесса из topology
**Context:** ProcessesTab уже отправляет `process.start` / `process.stop` / `process.restart` через CommandSender напрямую. Нужно маршрутизировать эти команды через TopologyBridge для валидации и единообразия. Также: add_process / remove_process для будущего Pipeline Editor (Phase 13).

**Files:**
- `multiprocess_prototype/frontend/bridge/topology_bridge.py` — дополнить
- `multiprocess_prototype/frontend/bridge/tests/test_topology_bridge.py` — дополнить
- `multiprocess_prototype/frontend/widgets/tabs/processes/presenter.py` — модифицировать

**Steps:**
1. Добавить в TopologyBridge методы:
   - `start_process(process_name: str) -> bool`
   - `stop_process(process_name: str) -> bool`
   - `restart_process(process_name: str) -> bool`
   - Каждый: валидация (process_name существует в topology) -> CommandSender.send_command(process_name, "process.{action}")
2. Добавить методы для будущего Phase 13:
   - `add_process(process_name: str, plugins: list[dict]) -> bool` — добавить процесс в TopologyHolder + отправить IPC
   - `remove_process(process_name: str) -> bool` — убрать из TopologyHolder + отправить IPC
   - Пока это заглушки с TODO для Phase 13 (Hot-reload), но сигнатуры и валидация работают
3. Модифицировать `ProcessesPresenter.on_process_action()`:
   - Вместо прямого `ctx.command_sender.send_command()` -> получить TopologyBridge из ctx и вызвать `bridge.start_process()` / `stop_process()` / `restart_process()`
   - Fallback: если bridge нет в ctx -> текущее поведение (обратная совместимость)

**Acceptance criteria:**
- [ ] `bridge.start_process("camera_0")` -> CommandSender.send_command("camera_0", "process.start") вызван
- [ ] `bridge.start_process("nonexistent")` -> return False, log warning
- [ ] ProcessesPresenter использует bridge если он доступен
- [ ] Без bridge — ProcessesPresenter работает как раньше
- [ ] `add_process()` / `remove_process()` — обновляют TopologyHolder.topology
- [ ] Тесты: 8+ (start/stop/restart, validation, add/remove topology update)

**Out of scope:** Hot-reload процессов в runtime (Phase 13.4). Автоматический перезапуск при crash.
**Edge cases:** stop уже остановленного процесса -> log info, return True (idempotent). remove несуществующего -> return False.
**Dependencies:** Task 12.2.1

---

### Task 12.3.1 — ProcessesTab live bindings (FPS, status, latency)

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Подключить ProcessesTab к реальным state_delta для live-обновления статуса, FPS и latency каждого процесса
**Context:** ProcessesTab._connect_bindings() уже содержит TODO Phase 12. GuiStateBindings уже работает. Нужно: (a) привязать StatusIndicator к `processes.{name}.state.status`, (b) привязать метрики (FPS, latency) к labels на EntityCard.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/processes/tab.py` — модифицировать
- `multiprocess_prototype/frontend/widgets/tabs/processes/tests/test_processes_tab.py` — дополнить

**Steps:**
1. В `_connect_bindings()` для каждого процесса:
   - Создать QLabel для FPS и добавить в EntityCard метрики
   - `bindings.bind(f"processes.{name}.state.status", card_status_indicator, "text", formatter=_status_to_text)`
   - `bindings.bind(f"processes.{name}.state.fps", fps_label, "text", formatter=lambda v: f"{v:.1f} FPS")`
   - `bindings.bind(f"processes.{name}.state.latency_ms", latency_label, "text", formatter=lambda v: f"{v:.0f} ms")`
2. Добавить formatter-функции: `_status_to_text(status)` -> русский текст + цвет, `_fps_format(v)`, `_latency_format(v)`
3. При получении state_delta со status -> обновить цвет StatusIndicator (зелёный/серый/красный)
4. Добавить метод `card.set_status_indicator()` в EntityCard если его нет, или использовать существующий `set_status()`

**Acceptance criteria:**
- [ ] При state_delta `processes.camera_0.state.fps = 25.3` -> FPS label на карточке обновляется
- [ ] При state_delta `processes.camera_0.state.status = "running"` -> StatusIndicator зелёный
- [ ] При state_delta `processes.camera_0.state.status = "error"` -> StatusIndicator красный
- [ ] Тесты: 6+ (fps binding, status binding, latency binding, formatter tests)

**Out of scope:** PID, memory, thread count (Phase 14). Worker tree внутри процесса.
**Edge cases:** state_delta приходит для процесса, которого нет в GUI (добавлен runtime) -> ignore. NaN/None значения fps -> показать "-".
**Dependencies:** Task 12.2.1 (TopologyBridge для on_state_delta, но bindings работают и без него — через GuiStateBindings напрямую)

---

### Task 12.3.2 — ServicesTab + StatusBar live bindings

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Подключить ServicesTab (camera stats, DB counters) и MainWindow StatusBar к live state_delta
**Context:** ServicesTab показывает параметры сервисов (camera_service, database, robot_control). StatusBar показывает system-wide FPS и latency. Нужно: live-обновление метрик из StateStore.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/services/tab.py` — модифицировать
- `multiprocess_prototype/frontend/windows/main_window.py` — модифицировать
- `multiprocess_prototype/frontend/widgets/tabs/services/tests/test_services_tab.py` — дополнить (или создать)
- `multiprocess_prototype/frontend/tests/test_statusbar_bindings.py` — создать

**Steps:**
1. **ServicesTab:** в `__init__()` после создания страниц:
   - Для camera_service: `bindings.bind("processes.*.state.camera_fps", label, "text")` — или конкретный процесс
   - Для database: `bindings.bind("processes.*.state.db_rows", label, "text")`
   - Для robot_control: `bindings.bind("processes.*.state.robot_rejects", label, "text")`
   - Использовать паттерны glob для матчинга — или конкретные пути из ConnectionMap
2. **StatusBar:**
   - Добавить в MainWindow метод `connect_bindings(bindings: GuiStateBindings)`:
     - `bindings.bind("system.fps", fps_label, "text", formatter=lambda v: f"FPS: {v:.0f}")`
     - `bindings.bind("system.latency_ms", latency_label, "text", formatter=lambda v: f"Latency: {v:.0f}ms")`
     - `bindings.bind("system.total_frames", frame_label, "text", formatter=lambda v: f"Frames: {v}")`
   - Это заменяет текущий QTimer-based FPS counter более точным runtime-значением
3. Оба: fallback — если bindings=None, показывать дефолтные значения ("—")

**Acceptance criteria:**
- [ ] ServicesTab: camera FPS label обновляется при state_delta
- [ ] StatusBar: system.fps, system.latency_ms, system.total_frames — live
- [ ] StatusBar graceful degradation: если нет state_delta — показывает QTimer-based FPS (как сейчас)
- [ ] Тесты: 8+ (services bindings, statusbar bindings, formatter tests, fallback)

**Out of scope:** Графики метрик (sparklines). Алерты при аномальных значениях.
**Edge cases:** Несколько camera-процессов -> показывать агрегат или первый. State_delta приходит до построения UI -> bindings.bind() буферизуется.
**Dependencies:** Task 12.3.1 (общий паттерн), но можно делать параллельно

---

### Task 12.3.3 — Интеграция TopologyBridge в AppContext и app.py (финальная сборка)

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** Собрать все компоненты Phase 12 в app.py: создать CommandCatalog, CommandValidator, TopologyBridge, подключить к ActionBus и GuiStateBindings
**Context:** Все отдельные компоненты готовы (12.1.x, 12.2.x, 12.3.x). Нужно: (a) создать их в правильном порядке в run_gui(), (b) передать через AppContext, (c) подключить state_delta callback к TopologyBridge.on_state_delta().

**Files:**
- `multiprocess_prototype/frontend/app.py` — модифицировать
- `multiprocess_prototype/frontend/app_context.py` — модифицировать (добавить topology_bridge accessor)
- `multiprocess_prototype/frontend/bridge/__init__.py` — обновить re-exports
- `multiprocess_prototype/frontend/tests/test_phase12_integration.py` — создать

**Steps:**
1. В `app_context.py`:
   - Добавить метод `topology_bridge() -> TopologyBridge | None` — аналогично action_bus()
   - Добавить метод `command_catalog() -> CommandCatalog | None`
2. В `app.py` `run_gui()` после создания RegistersManager и TopologyHolder:
   - Создать `CommandCatalog.from_registry_and_topology(PluginRegistry, _topology_dict)`
   - Создать `CommandValidator(catalog, registers_manager)`
   - Создать `TopologyBridge(command_sender, catalog, validator, registers_manager, topology_holder)`
   - Сохранить в `ctx.extras["topology_bridge"]` и `ctx.extras["command_catalog"]`
   - Передать bridge в `create_action_bus(..., topology_bridge=bridge)`
3. Подключить state_delta к bridge:
   - В GuiStateBindings или параллельно: `bridge.on_state_delta()` вызывается при каждом state_delta message
   - Вариант: создать обёртку, которая из _on_state_msg вызывает и bindings, и bridge
4. Подключить StatusBar bindings: `window.connect_bindings(bindings)` после создания window
5. Подключить topology_holder.on_changed -> bridge.on_topology_changed
6. Интеграционный тест: mock GuiProcess -> создать все компоненты -> проверить цепочку field_set -> IPC

**Acceptance criteria:**
- [ ] `ctx.topology_bridge()` возвращает TopologyBridge
- [ ] `ctx.command_catalog()` возвращает CommandCatalog
- [ ] Изменение поля в PluginsTab -> ActionBus.execute -> FieldSetHandler.apply -> bridge.on_field_set -> CommandSender.send_field_command
- [ ] state_delta message -> bridge.on_state_delta -> rm обновлён
- [ ] StatusBar получает live метрики
- [ ] Интеграционный тест: 5+ (полный pipeline mock)
- [ ] Приложение запускается без ошибок (smoke test)

**Out of scope:** E2E тест с реальными процессами (Phase 14). Hot-reload topology.
**Edge cases:** PluginRegistry пуст -> CommandCatalog пуст, bridge работает но не отправляет команд. Topology не загружена -> bridge создан с пустым catalog.
**Dependencies:** Task 12.2.2, 12.2.3, 12.3.1, 12.3.2

---

## Граф зависимостей

```
12.1.1 (CommandCatalog)
  |
  ├─→ 12.1.2 (CommandValidator) ─┐
  |                               |
  └─→ 12.1.3 (CommandSender v2)──┤
                                  |
                                  ▼
                            12.2.1 (TopologyBridge core)
                              |        |
                              ▼        ▼
                       12.2.2        12.2.3
                    (ActionBus      (Lifecycle
                     integration)    commands)
                              |        |
                              ▼        ▼
                            12.3.3 (Final integration)
                              ▲        ▲
                              |        |
                       12.3.1        12.3.2
                    (ProcessesTab    (Services +
                     live bindings)   StatusBar)
```

## Рекомендуемый порядок выполнения

1. **Task 12.1.1** — CommandCatalog (фундамент, без зависимостей)
2. **Task 12.1.2 + 12.1.3** — параллельно (оба зависят только от 12.1.1)
3. **Task 12.2.1** — TopologyBridge core (после 12.1.x)
4. **Task 12.2.2 + 12.2.3 + 12.3.1 + 12.3.2** — параллельно (все зависят от 12.2.1)
5. **Task 12.3.3** — финальная сборка (после всего)

## Оценка объёма

| Task | LOC (approx) | Тесты |
|------|-------------|-------|
| 12.1.1 CommandCatalog | ~120 | 10+ |
| 12.1.2 CommandValidator | ~60 | 8+ |
| 12.1.3 CommandSender v2 | ~100 | 10+ |
| 12.2.1 TopologyBridge | ~180 | 15+ |
| 12.2.2 ActionBus integration | ~40 | 8+ |
| 12.2.3 Lifecycle commands | ~80 | 8+ |
| 12.3.1 ProcessesTab bindings | ~50 | 6+ |
| 12.3.2 Services + StatusBar | ~80 | 8+ |
| 12.3.3 Final integration | ~60 | 5+ |
| **Итого** | **~770** | **78+** |
