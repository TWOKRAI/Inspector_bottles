# Plan: Phase D — AppServices DI + Qt-wrapper EventBus

- **Slug:** cross-tab-architecture / phase D
- **Дата:** 2026-05-27 (draft v1)
- **Статус:** APPROVED (open questions закрыты 2026-05-27 — см. decisions log; старт только после Phase C DONE)
- **Ветка:** `refactor/cross-tab-architecture` (та же)
- **Master plan:** [`plan.md`](plan.md)
- **Brief:** [`docs/refactors/2026-05_cross_tab_architecture.md`](../../docs/refactors/2026-05_cross_tab_architecture.md), раздел 5.4
- **Phase C (вход):** [`phase-c-adapters.md`](phase-c-adapters.md) — 9 adapter'ов готовы
- **Архитектурный обзор (вход):** investigator-отчёт 2026-05-27, разделы 4 (готовность к Phase D) и 5.2 (двойная нотификация)

## Контекст

Phase B создала domain skeleton (frozen entities + Project.apply + EventBus + AppServices dataclass). Phase C создаёт adapter-слой (9 классов, реализующие Protocols поверх существующих реестров). **Phase D — это момент подключения:** AppServices factory в `app.py:run_gui()`, Qt-wrapper EventBus для thread-safety, deprecation `ctx.extras` dict-bag.

**Важно:** Phase D **не мигрирует presenter-ы** — это Phase E. Phase D создаёт **инфраструктуру**, на которой presenter'ы будут жить. Один из presenter'ов мигрируется в рамках D **proof-of-concept'а** (вероятно Settings — самый простой, минимум topology consumer'ов), чтобы валидировать паттерн.

## Цели

- **AppServices factory** в `app.py:run_gui()` — собирает 9 adapter'ов в один frozen dataclass.
- **Qt-wrapper EventBus** — `QtEventBus` поверх pure Python `EventBus`, маршалит publish через `QMetaObject.invokeMethod` на main thread. Сохраняет EventBusProtocol-совместимость.
- **`register_domain_schemas()`** вызывается при инициализации (после C.0 lazy-fix).
- **Deprecation shim** для `ctx.extras` — emit `DeprecationWarning` при доступе к ключам, мигрированным в AppServices. Не удалять — это Phase F.
- **Proof-of-concept migration**: один presenter переходит на `AppServices` параметр (рекомендация: Settings tab, минимум коду). Удостоверение, что паттерн работает на реальном GUI.
- **Migration guide** — `docs/refactors/2026-05_phase_e_migration_guide.md` или раздел в brief'е: как presenter мигрирует с `ctx` на `AppServices` (сниппеты, до/после).

## Out of scope

- **Per-tab migration** — это Phase E (Pipeline → Processes → Recipes → Services → Plugins → Displays → Settings, но последний может быть proof-of-concept в D).
- **Удаление `ctx.extras` / `TopologyHolder` / `ActionBus`** — Phase F.
- **Удаление 4 параллельных dataclass-обёрток** (TopologyContext, StateContext, PluginsContext, ActionsContext) — Phase F или решение в D (если они мешают).
- **Live runtime snapshot** (PID'ы, FPS) — отдельный aggregate, Phase E/G.
- **`bindings` (GuiStateBindings) переход в AppServices** — investigator подтвердил: это **другой слой** (Qt-signal runtime state), оставить отдельно.

## Phase D — Tasks

### Task D.1 — AppServices factory в `app.py`

- **Level:** Senior (Opus)
- **Assignee:** teamlead
- **Module contract:** public-api-change (изменение `run_gui()` сигнатур + AppContext API)

**Goal:** В `app.py:run_gui()`, после того как `ctx.extras` заполнен (строки ~107-417), создать `AppServices` instance и сохранить его в `ctx.app_services` (новый атрибут на AppContext, opt-in, без удаления `extras`).

**Файлы:**
- `multiprocess_prototype/frontend/app.py` — расширение `run_gui()`.
- `multiprocess_prototype/frontend/app_context.py` — добавить `app_services: AppServices | None = None` атрибут (или property).
- `multiprocess_prototype/frontend/startup_checks.py` — может потребоваться правка, если startup читает topology через ctx.extras (audit показал — да). Сначала просто игнорируем, Phase E мигрирует.
- `multiprocess_prototype/tests/test_app_services_factory.py` — новый тест.

**Steps:**

1. В `run_gui()` после строки заполнения `ctx.extras["recipe_manager"] = ...` (или последняя строка extras-инициализации):
   ```python
   from multiprocess_prototype.domain import (
       AppServices, EventBus, register_domain_schemas,
   )
   from multiprocess_prototype.adapters import (
       AuthFacadeFromAuthState, CommandDispatcherOrchestrator,
       DisplayCatalogFromRegistry, PluginCatalogFromRegistry,
       RecipeStoreFromManager, RegistersBackendFromManager,
       ServiceCatalogFromRegistry, TopologyRepositoryFromHolder,
   )

   register_domain_schemas()  # вместо import-time side-effect
   bus = QtEventBus()  # см. D.2

   topology_repo = TopologyRepositoryFromHolder(ctx.extras["topology_holder"])
   plugins = PluginCatalogFromRegistry(plugin_registry)
   displays = DisplayCatalogFromRegistry(DisplayRegistry())

   apply_ctx_factory = lambda: ApplyContext(
       plugins=plugins, displays=displays, recipes=recipes,
   )
   project_holder = ProjectHolder(initial=Project.from_topology(topology_repo.load()))
   commands = CommandDispatcherOrchestrator(
       project_holder=project_holder,
       topology_repo=topology_repo,
       event_bus=bus,
       apply_context_factory=apply_ctx_factory,
   )

   ctx.app_services = AppServices(
       plugins=plugins,
       services=ServiceCatalogFromRegistry(ctx.extras["service_registry"]),
       displays=displays,
       recipes=recipes,
       registers=RegistersBackendFromManager(
           ctx.extras["registers_manager"], topology_repo, plugins,
       ),
       topology=topology_repo,
       commands=commands,
       events=bus,
       auth=AuthFacadeFromAuthState(ctx.auth_state, auth_manager),
       config=ConfigStoreFromManager(ctx.extras["config_store"]),  # D.2b
   )
   ```
2. **Failure handling:** если какой-то adapter падает на инициализации (например, plugin discovery провалился) — логировать и `sys.exit(1)`, аналогично текущим startup-checks. **Нет `AppServices = None` варианта.**
3. **Compatibility:** существующие presenter'ы продолжают работать через `ctx.extras`. Только новые / мигрированные используют `ctx.app_services`.

**Тесты:**
- `test_factory_returns_valid_app_services` — запустить `run_gui()` в `pytest-qt` режиме (нет live window), проверить `ctx.app_services` инстанцирован, все 9 полей не None, dispatch'ить AddProcess через `services.commands` — изменение отражается в `services.topology.load()`.
- `test_factory_fails_loudly_on_adapter_init_error` — если plugin_registry empty / RecipeManager не может прочитать recipe_dir — `sys.exit(1)` или RuntimeError.

**Acceptance criteria:**
- [ ] `ctx.app_services` создаётся в `run_gui()` после всех extras.
- [ ] AppServices содержит 10 полей (включая `config`), все не None.
- [ ] Existing tests (test_phase15_smoke, test_app_context) проходят без изменений (backward-compat).
- [ ] Новый тест: `dispatch(AddProcess(...))` через `services.commands` → процесс появляется в `services.topology.load()`.
- [ ] `register_domain_schemas()` вызывается ровно один раз.

**Edge cases:**
- Auth не инициализирован (пользователь нажал Cancel) — `ctx.auth_state.is_authenticated = False`, но `AppServices.auth` всё равно создаётся (level 0). **Не блокер.**

**Refs:** investigator раздел 4 (готовность к Phase D), B.6 AppServices контракт.

---

### Task D.2 — QtEventBus (thread-safe wrapper)

- **Level:** Middle+ (Sonnet)
- **Assignee:** developer
- **Module contract:** new-full

**Goal:** Wrapper над pure Python `EventBus` из B.6, который маршалит `publish()` на main thread через `QMetaObject.invokeMethod`. Это нужно, потому что Project entities могут «утечь» в worker thread (например, через ProcessManager IPC), и подписка из presenter (main thread) должна получать события на main thread.

**Файлы:**
- `multiprocess_prototype/frontend/qt_event_bus.py` — новый файл. **Внимание:** это `frontend/`, не `domain/`! Domain должен оставаться UI-agnostic.
- `multiprocess_prototype/frontend/tests/test_qt_event_bus.py`.

**Steps:**

1. `QtEventBus`:
   ```python
   class QtEventBus(QObject):
       """Qt-aware обёртка над domain.EventBus.

       publish() из любого thread'а маршалится на main thread через
       QMetaObject.invokeMethod(_dispatch_on_main, Qt.QueuedConnection).
       subscribe — pass-through.

       Удовлетворяет domain.protocols.EventBusProtocol.
       """
       def __init__(self, parent: QObject | None = None) -> None:
           super().__init__(parent)
           self._bus = EventBus(error_handler=self._on_error)

       def publish(self, event: ProjectEvent) -> None:
           if _is_main_thread():
               self._bus.publish(event)
           else:
               QMetaObject.invokeMethod(
                   self,
                   "_dispatch_on_main",
                   Qt.ConnectionType.QueuedConnection,
                   Q_ARG(object, event),
               )

       @Slot(object)
       def _dispatch_on_main(self, event: ProjectEvent) -> None:
           self._bus.publish(event)

       def subscribe(self, event_type, handler) -> Subscription:
           return self._bus.subscribe(event_type, handler)
   ```
2. `_is_main_thread()` — `QThread.currentThread() is QApplication.instance().thread()`.

**Тесты (pytest-qt):**
- `test_publish_main_thread_synchronous` — handler вызван до возврата publish() (synchronous на main thread).
- `test_publish_worker_thread_marshals_to_main` — publish из QRunnable → handler вызван на main thread (через `Qt.QueuedConnection`).
- `test_subscribe_returns_subscription`.
- `test_qt_event_bus_satisfies_protocol` — assignment check.

**Acceptance criteria:**
- [ ] QtEventBus satisfies EventBusProtocol.
- [ ] publish из worker thread не падает (test проверяет `Qt.QueuedConnection` доставил event).
- [ ] publish на main thread — synchronous.
- [ ] AppServices.events в D.1 использует QtEventBus, не pure EventBus.

**Out of scope:**
- async / signals.signal — не сегодня. Phase G если нужно.

**Refs:** investigator risk #3 (mutability leak — это снимается при condi marshalling).

---

### Task D.2b — ConfigStore Protocol + adapter

- **Level:** Middle+ (Sonnet)
- **Assignee:** developer
- **Module contract:** new-full (protocol в domain + adapter в adapters/, AppServices field)

**Goal:** Добавить `ConfigStore` Protocol в `domain/protocols/`, реализовать `ConfigStoreFromManager` adapter поверх существующего `ConfigStore` (или `ConfigManager`) из `multiprocess_framework/modules/config_module/`, добавить поле `config: ConfigStore` в `AppServices`. Settings tab (D.5) использует `services.config` вместо `ctx.config`.

**Файлы:**
- `multiprocess_prototype/domain/protocols/config_store.py` — Protocol с read/write/observe методами.
- `multiprocess_prototype/domain/protocols/__init__.py` — re-export.
- `multiprocess_prototype/domain/app_services.py` — добавить поле `config: ConfigStore`.
- `multiprocess_prototype/domain/tests/_fakes.py` — `FakeConfigStore` для builder.
- `multiprocess_prototype/domain/tests/test_make_app_services_builder.py` — обновить (теперь 10 полей).
- `multiprocess_prototype/adapters/stores/config_store.py` — `ConfigStoreFromManager`.
- `multiprocess_prototype/adapters/tests/test_config_store.py`.

**Steps:**

1. Protocol (минимальный, расширяется в Phase E):
   ```python
   class ConfigStore(Protocol):
       def get(self, key: str, default: Any = None) -> Any: ...
       def set(self, key: str, value: Any) -> None: ...
       def get_section(self, section: str) -> Mapping[str, Any]: ...
       def list_keys(self, prefix: str = "") -> Sequence[str]: ...
       def subscribe(self, key_pattern: str, handler: Callable[[str, Any], None]) -> Subscription: ...
       def save(self) -> None: ...  # persist to disk
   ```
   - **Решить при имплементации:** `Subscription` — re-use из EventBus или отдельный тип? Рекомендация: re-use (Phase E может обсудить, если нужна другая семантика).
2. `ConfigStoreFromManager` adapter в `adapters/stores/config_store.py`:
   - Wrapper над `multiprocess_framework/modules/config_module/ConfigStore` (или `ConfigManager` — проверить точный singleton).
   - `subscribe` — обёртка над механизмом change-callbacks из config_module (если есть; иначе simple internal pub-sub).
3. Добавить `AppServices.config: ConfigStore` (10-е поле).
4. `make_test_app_services()` builder возвращает `FakeConfigStore` по умолчанию.
5. В D.1 — `ctx.app_services = AppServices(..., config=ConfigStoreFromManager(ctx.extras["config_store"]))`.

**Тесты:**
- `test_config_store_protocol_satisfaction` (assignment check).
- `test_config_store_get_set_roundtrip`.
- `test_config_store_get_section_returns_mapping`.
- `test_config_store_subscribe_fires_on_change`.
- `test_config_store_save_persists_to_disk`.
- Builder: `test_make_app_services_builds_with_fake_config`.

**Acceptance criteria:**
- [ ] Protocol существует в domain.
- [ ] Adapter satisfies Protocol.
- [ ] AppServices.config — обязательное поле (не Optional).
- [ ] Settings tab (D.5) использует `services.config`, не `ctx.config`.
- [ ] Builder обновлён.

**Out of scope:**
- Validation / schema enforcement — Phase E если нужно (Settings tab уже Pydantic-validate'ит).
- Multi-tenant config — нет такой потребности.

**Edge cases:**
- Config file отсутствует → `get(...)` возвращает default. `save()` создаёт файл.
- Concurrent writes — single-threaded GUI assumption, lock внутри adapter если нужно.

**Refs:** `multiprocess_framework/modules/config_module/`, memory `project_settings_mvp_refactor`.

---

### Task D.3 — ProjectHolder + initial Project bootstrap

- **Level:** Middle (Sonnet)
- **Assignee:** developer
- **Module contract:** new-lite

**Goal:** `ProjectHolder` — простой mutable wrapper над текущим Project. Нужен `CommandDispatcherOrchestrator` (C.6) и presenter'ам Phase E для получения current state. Bootstrap: при старте `run_gui()` Project создаётся из `TopologyRepository.load()`.

**Файлы:**
- `multiprocess_prototype/adapters/dispatch/project_holder.py` (если не создан в C.6).
- `multiprocess_prototype/adapters/tests/test_project_holder.py`.

**Steps:**

1. `ProjectHolder`:
   ```python
   class ProjectHolder:
       def __init__(self, initial: Project) -> None:
           self._current = initial
           self._lock = RLock()  # для thread-safety в Phase D wrapper

       def get(self) -> Project:
           with self._lock:
               return self._current

       def set(self, project: Project) -> None:
           with self._lock:
               self._current = project
   ```
2. **Decision закрыт (см. decisions log):** ProjectHolder — «тупой» state-контейнер. Granular events публикует CommandDispatcher (он знает, какие domain-events вернула `Project.apply()`). Holder не публикует ничего.
3. `Project.from_topology(topology: Topology) -> Project` — convenience factory в `domain/entities/project.py`: `Project(topology=topology, active_recipe=None)`.

**Тесты:**
- `test_holder_get_returns_initial`.
- `test_holder_set_updates_current`.
- `test_holder_thread_safe` (concurrent get/set из 2 потоков).

**Acceptance criteria:**
- [ ] ProjectHolder реализован.
- [ ] D.1 использует его для bootstrap.
- [ ] Lock реально работает (smoke на race condition).

**Out of scope:** observable / on_changed callbacks — это уже EventBus.

---

### Task D.4 — Deprecation shim для `ctx.extras`

- **Level:** Middle (Sonnet)
- **Assignee:** developer
- **Module contract:** public-api-change (AppContext.extras поведение)

**Goal:** При доступе к ключам `extras`, мигрированным в AppServices, эмитить `DeprecationWarning`. Это даёт Phase E presenter'ам сигнал: «переходите на ctx.app_services». При этом extras продолжает работать (backward-compat).

**Файлы:**
- `multiprocess_prototype/frontend/app_context.py` — заменить `extras: dict[str, Any]` на `extras: _DeprecatedExtrasDict`.
- `multiprocess_prototype/frontend/_deprecated_extras.py` — новый wrapper.
- `multiprocess_prototype/tests/test_extras_deprecation.py`.

**Steps:**

1. `_DeprecatedExtrasDict(dict)`:
   ```python
   _DEPRECATED_KEYS = {
       "topology_holder", "plugin_registry", "service_registry",
       "recipe_manager", "registers_manager", "action_bus",
       "display_registry", "command_catalog", "topology_bridge",
       # ... 16 ключей из audit
   }

   class _DeprecatedExtrasDict(dict):
       def __getitem__(self, key):
           if key in _DEPRECATED_KEYS:
               warnings.warn(
                   f"ctx.extras[{key!r}] deprecated; use ctx.app_services.{_KEY_MAP[key]}",
                   DeprecationWarning, stacklevel=2,
               )
           return super().__getitem__(key)

       def get(self, key, default=None):
           # аналогично
   ```
2. `_KEY_MAP`: `"topology_holder" → "topology"`, `"plugin_registry" → "plugins"`, `"recipe_manager" → "recipes"`, ...
3. **Не делать ничего** для не-deprecated ключей (например, `topology` raw-dict если он используется — оставить тихо).

**Тесты:**
- `test_extras_emit_warning_for_deprecated_keys` (через `pytest.warns(DeprecationWarning)`).
- `test_extras_silent_for_other_keys`.
- `test_existing_code_still_works` — backward-compat.

**Acceptance criteria:**
- [ ] DeprecationWarning эмитится для всех 16 ключей.
- [ ] Существующие тесты не падают (warnings filter в pytest.ini).
- [ ] Phase E migration log будет полным после прогона тестов (видно, какие presenter'ы ещё используют extras).

**Out of scope:**
- Удаление ключей — Phase F.
- Force-fail на использовании — Phase F (можно `DeprecationWarning → FutureWarning → RuntimeError`).

---

### Task D.5 — Proof-of-concept: Settings tab на AppServices

- **Level:** Middle+ (Sonnet)
- **Assignee:** developer
- **Module contract:** public-api-change (Settings tab __init__ сигнатура)

**Goal:** Мигрировать Settings tab — самый простой consumer (audit показал: ни одного topology чтения, только AppContext access для config). Доказательство концепции, шаблон для Phase E.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs/settings/*.py` — пройтись по presenter и subtabs (system, history, administration), заменить `ctx.action_bus()` → `services.commands.dispatch(...)`, `ctx.auth` → `services.auth`.
- `multiprocess_prototype/frontend/widgets/tabs/settings/tab.py` — `__init__(self, services: AppServices, ...)`.
- `multiprocess_prototype/frontend/tab_factory.py` — при создании Settings передавать `ctx.app_services`.
- Тесты: `settings/system/tests/test_system_presenter.py`, etc. — заменить `ctx = MagicMock()` на `make_test_app_services()` builder.

**Steps:**

1. Скопировать паттерн использования `services` из `domain/tests/` (там `apply()` уже использует `ApplyContext`). Presenter подписывается на EventBus, dispatch'ит команды.
2. Settings tab имеет:
   - SettingsSystemPresenter — config edits через `services.commands` или прямой `ConfigStore`. Если ConfigStore не входит в Protocols — оставить как есть (Phase E может добавить `ConfigStore Protocol`).
   - SettingsHistoryPresenter — потенциально использует `services.events.subscribe(...)` для timeline.
   - SettingsAdministration — uses `services.auth` для permission checks.
3. **Тесты обязательно через `make_test_app_services()`** builder, не MagicMock. Это zero-tolerance запрет из B.6.
4. **ConfigStore через services.config** (D.2b закрыл вопрос Q3): SettingsSystemPresenter использует `services.config.get_section("display")` вместо `ctx.config.get(...)`. Замена прямой.

**Тесты:**
- Все existing test_*.py для Settings tab — переписать на builder.
- Новый тест: Settings tab construction with full AppServices — smoke.
- pytest-qt: open Settings tab → click `Save` → verify dispatch happened (mock'нув CommandDispatcher через builder override).

**Acceptance criteria:**
- [ ] Settings tab принимает `AppServices` в `__init__`.
- [ ] Существующие 22 settings + 67 admin тестов проходят (после миграции на builder).
- [ ] **Никаких MagicMock в новых тестах.**
- [ ] Smoke pytest-qt: открытие Settings tab из реального GUI — не падает (если pytest-qt доступен).
- [ ] DeprecationWarning'и от extras не появляются в Settings tab (всё через AppServices).

**Edge cases:**
- ConfigStore теперь часть AppServices (D.2b) — Settings использует `services.config`. `ctx.config` остаётся для backward-compat (тоже через DeprecationWarning, если pattern попадает в Phase F).

**Out of scope:**
- Pipeline/Processes/Recipes/Services/Plugins/Displays — Phase E.

**Refs:** memory `project_settings_mvp_refactor` (Settings уже на MVP, упрощает миграцию).

---

### Task D.6 — Migration guide + sentrux baseline update

- **Level:** Junior+ (Sonnet)
- **Assignee:** docs-writer / tech-writer

**Goal:** Документация для Phase E разработчиков. Sentrux baseline после Phase D для понимания эффекта на DSM.

**Файлы:**
- `docs/refactors/2026-05_phase_e_migration_guide.md` — новый. Снiппеты до/после для presenter'а.
- `plans/2026-05-27_cross-tab-architecture/plan.md` — статус Phase D → DONE, Phase E ready.
- `docs/claude/memory/project_cross_tab_phase_d.md` — memory.
- `.sentrux/rules.toml` — обновить: `frontend → adapters` разрешено, `adapters → frontend` запрещено, `domain → adapters/frontend` запрещено.
- Sentrux baseline: `mcp__sentrux__session_end` после Phase D, сравнить с pre-Phase-B.

**Steps:**

1. Migration guide содержит:
   - **До:** `class FooTab(QWidget):\n    def __init__(self, ctx: AppContext): ...`
   - **После:** `class FooTab(QWidget):\n    def __init__(self, services: AppServices): ...`
   - Замена `ctx.extras["X"]` → `services.X` (по таблице из audit).
   - Замена `ctx.action_bus().execute(...)` → `services.commands.dispatch(SomeCommand(...))`.
   - Подписка на EventBus: `subscription = services.events.subscribe(ProcessAdded, self._on_process_added)`.
   - Тесты: `make_test_app_services(plugins=FakePluginCatalog(...))`.
2. Sentrux baseline после Phase D: ожидаем рост modularity score (изолированный domain + adapter слой).

**Acceptance criteria:**
- [ ] Migration guide написан.
- [ ] Sentrux baseline зафиксирован (числа в memory).
- [ ] Sentrux rules обновлены (frontend → adapters → domain — допустимо, обратное — запрещено).
- [ ] Master plan.md обновлён (Phase D DONE).
- [ ] Memory обновлена (dual-write).

---

## Acceptance criteria всей Phase D

- [ ] Все 7 Tasks (D.1, D.2, D.2b, D.3—D.6) DONE.
- [ ] `python -m pytest multiprocess_prototype/ -v` — все тесты passed (включая Settings миграцию).
- [ ] `ctx.app_services` создаётся в `run_gui()` для всех сценариев запуска.
- [ ] Все 16 deprecated `ctx.extras` ключей эмитят `DeprecationWarning`.
- [ ] Settings tab работает на `AppServices` параметре (proof of concept).
- [ ] Existing tests не падают (backward-compat для не-мигрированных tabs).
- [ ] Sentrux baseline — modularity score ≥ baseline или вырос.
- [ ] `.sentrux/rules.toml` обновлены — нет нарушений (frontend → adapters → domain).
- [ ] Никаких изменений в `domain/` кроме `register_domain_schemas()` (если не сделано в C.0).
- [ ] Migration guide опубликован — Phase E разработчики могут стартовать.
- [ ] **`grep -rn "MagicMock(spec=AppContext)"` в новых/мигрированных тестах = 0** (правило B.6 сохраняется).

## Закрытые вопросы (decisions log)

Все 5 open questions закрыты 2026-05-27 (с подтверждением пользователя через AskUserQuestion на 2 ключевых). См. секцию «Решения» ниже.

## Решения (decisions log)

### Стратегические (закрытые open questions)

- **2026-05-27 (closed Q1):** **QtEventBus в `frontend/qt_event_bus.py`** — один файл достаточно. Domain остаётся UI-agnostic. Альтернатива (`multiprocess_prototype/qt_layer/` пакет) отложена до тех пор, пока не появится 2+ Qt-aware wrapper'ов.
- **2026-05-27 (closed Q2):** **ProjectHolder в `adapters/dispatch/project_holder.py`** — mutable wrapper не является domain-сущностью. Также: holder НЕ публикует event'ы (тупой state-контейнер), все publish'ы делает `CommandDispatcherOrchestrator`.
- **2026-05-27 (closed Q3 — user-confirmed):** **ConfigStore Protocol добавляется в Phase D** (новый Task D.2b). Settings tab сразу мигрирует на `services.config`, не на `ctx.config`. Reason: пользовательское решение — лучше единая инкапсуляция через AppServices, чем смешанный паттерн. Domain Protocol простой (get/set/section/subscribe/save), adapter wraps `multiprocess_framework/modules/config_module/`.
- **2026-05-27 (closed Q4):** **`bindings` остаётся вне AppServices**. Это Qt-signal runtime state (live data binding), не editor state. 25+ точек `ctx.bindings()` в presenter'ах продолжают работать через AppContext, без deprecation. Возможно ревизия в Phase G (если bindings объединять с EventBus).
- **2026-05-27 (closed Q5):** **DeprecationWarning verbosity** — `pytest.ini` добавляет `filterwarnings = ignore::DeprecationWarning:multiprocess_prototype.frontend._deprecated_extras`. Тесты НЕ падают на warnings. Logging-mode (`always::DeprecationWarning`) для одной локальной сессии — опционально, документировать в migration guide D.6. Удаление ключей и `error::DeprecationWarning` — Phase F.

### Тактические (структура Phase D)

- **2026-05-27 (user-confirmed):** **Phase D PoC — Settings tab.** Pipeline остаётся первым приоритетом Phase E (главный consumer, валидирует архитектуру end-to-end). Settings выбран для D.5 потому что: (а) уже на MVP-паттерне, (б) минимум topology consumer'ов, (в) низкий риск регрессии — безопасный «sanity check» что AppServices + QtEventBus + dispatcher работают вместе.
- **2026-05-27:** Phase D — **7 Tasks** (после добавления D.2b ConfigStore): D.1 factory, D.2 QtEventBus, D.2b ConfigStore Protocol+adapter, D.3 ProjectHolder, D.4 deprecation shim, D.5 Settings PoC, D.6 docs+baseline.
- **2026-05-27:** **Не удалять `ctx.extras`.** Только deprecation. Удаление — Phase F.
- **2026-05-27:** **Не мигрировать Pipeline tab в Phase D.** Phase E начинается с Pipeline.
- **2026-05-27:** QtEventBus реализуется в `frontend/`, не в `domain/`. Domain остаётся UI-agnostic (правило B.6).

## Что разблокирует Phase D

После approval deliverable Phase D можно начинать:

- **Phase E** — per-tab migration. По таблице из audit + brief 5.5: Pipeline → Processes → Recipes → Services → Plugins → Displays. Settings уже сделан в D.5.
- **Phase F** — удаление legacy: `ctx.extras` dict-bag, TopologyHolder (или редукция до compat-adapter'а), fallback chains.

---

> **Хранение:** `plans/2026-05-27_cross-tab-architecture/phase-d-app-services.md`.
>
> **Workflow:** после approval плана пользователем — `/pipeline` или ручной запуск teamlead на D.1, developer'ов на остальное.
