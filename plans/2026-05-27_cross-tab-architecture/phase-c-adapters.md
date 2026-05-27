# Plan: Phase C — Adapters (domain → реальные реестры)

- **Slug:** cross-tab-architecture / phase C
- **Дата:** 2026-05-27 (draft v1)
- **Статус:** APPROVED (open questions закрыты 2026-05-27 — см. decisions log; готов к имплементации)
- **Ветка:** `refactor/cross-tab-architecture` (та же)
- **Master plan:** [`plan.md`](plan.md)
- **Brief:** [`docs/refactors/2026-05_cross_tab_architecture.md`](../../docs/refactors/2026-05_cross_tab_architecture.md), раздел 5.3
- **Phase B (вход):** [`phase-b-domain.md`](phase-b-domain.md) — DONE 2026-05-27, 7 коммитов от `83274ef8` до `e65f7158`
- **Архитектурный обзор (вход):** investigator-отчёт 2026-05-27 (см. чат) — таблица «Protocol → adapter source → сложность 1-5», 6 risks, 4 open questions

## Контекст

Phase B создала `multiprocess_prototype/domain/` — изолированный пакет с 7 entities, 14 событий, 14 команд, 9 Protocols, `Project.apply()`, EventBus, AppServices. Никаких подключений к runtime. 233 теста зелёных.

Phase C создаёт **adapter-слой**: реализации 9 Protocols поверх существующих реестров (`PluginRegistry`, `ServiceRegistry`, `DisplayRegistry`, `RecipeManager`, `RegistersManager`, `TopologyHolder`, `ActionBus`, `AuthManager`/`AuthState`) + готовый `EventBus` из B.6. Adapter'ы живут в новом пакете `multiprocess_prototype/adapters/` и **тоже изолированы** от presenter-ов — их подключает только Phase D в `app.py:run_gui()`.

Параллельно Phase C — небольшие правки в `domain/` (data gaps, выявленные investigator'ом): `Wire.description`, `Process.source_target_fps`/`metadata`, lazy SchemaRegistry registration.

## Цели

- Создать пакет `multiprocess_prototype/adapters/` с 9 adapter-классами, каждый удовлетворяет соответствующий Protocol из `domain/protocols/`.
- Adapter-слой **runtime-aware**: знает про `TopologyHolder`, `RecipeManager`, `ActionBus` и т.д., **но не знает про PySide6/Qt** (это уровень presenter, Phase D).
- Каждый adapter — отдельный класс в отдельном модуле + unit/integration тесты на реальных in-memory fixtures (либо легковесных доменных доброволчах).
- **Domain hot-fixes** на основе investigator-feedback: дополнить entities, чтобы round-trip с framework `SystemBlueprint` был lossless.
- `CommandDispatcher` adapter — главный оркестратор: `dispatch(ProjectCommand)` запускает `Project.apply()`, синхронизирует `TopologyHolder` (с suppression legacy callbacks), публикует events.
- Готовая база для Phase D — собрать `AppServices` factory без необходимости править adapter'ы.

## Out of scope

- **Замена presenter-ов** — это Phase D (DI) и Phase E (per-tab migration).
- **Удаление `TopologyHolder` / `ActionBus` / `RecipeManager`** — Phase F (после миграции всех табов).
- **Qt-wrapper EventBus** — Phase D, отдельный Task в составе DI.
- **Undo / command history через ActionBus** — Phase E.
- **YAML versioning (recipe v2 → v3)** — Phase F.
- **Подключение adapter'ов в app.py** — Phase D.

## Phase C — структура папки

```
multiprocess_prototype/adapters/
├── __init__.py                       # public API (все 9 adapter'ов)
├── README.md                          # module contract
├── catalogs/
│   ├── __init__.py
│   ├── plugin_catalog.py             # PluginCatalogFromRegistry
│   ├── service_catalog.py            # ServiceCatalogFromRegistry
│   └── display_catalog.py            # DisplayCatalogFromRegistry
├── stores/
│   ├── __init__.py
│   ├── recipe_store.py               # RecipeStoreFromManager
│   ├── registers_backend.py          # RegistersBackendFromManager
│   └── topology_repository.py        # TopologyRepositoryFromHolder
├── dispatch/
│   ├── __init__.py
│   └── command_dispatcher.py         # CommandDispatcherOrchestrator
├── auth/
│   ├── __init__.py
│   └── auth_facade.py                # AuthFacadeFromAuthState
└── tests/
    ├── __init__.py
    ├── conftest.py                   # fixtures для adapter-тестов
    ├── test_catalogs.py              # 3 adapter'а
    ├── test_recipe_store.py
    ├── test_registers_backend.py
    ├── test_topology_repository.py
    ├── test_command_dispatcher.py    # самый объёмный
    └── test_auth_facade.py
```

**Принципы пакета:**

1. Adapter — тонкий обёртка над существующим реестром. Никакой бизнес-логики.
2. На границе adapter ↔ domain: ввод dict → `Entity.from_dict()`, вывод entity → `to_dict()` (правило 1 CLAUDE.md «Dict at Boundary»).
3. Adapter может импортировать из `multiprocess_prototype.domain` И из `multiprocess_framework.modules.*` / `Services/*` / `Plugins/*` / других `multiprocess_prototype/*` модулей (всё, что нужно для wrapping'а).
4. Adapter **НЕ** импортирует из `multiprocess_prototype/frontend/` (это нарушение слоёв; presenter'ы вызывают adapter, не наоборот).
5. README пакета фиксирует это правило.

## Phase C — Tasks

### Task C.0 — Domain hot-fixes (опционально, перед остальными)

- **Level:** Middle (Sonnet)
- **Assignee:** developer
- **Module contract:** patch (изменение существующего public API entity)

**Goal:** Закрыть data gaps, выявленные investigator-ревью Phase B, чтобы adapter'ы не били в `extra="forbid"` на реальных YAML.

**Файлы:**
- `multiprocess_prototype/domain/entities/wire.py` — добавить `description: str = ""`.
- `multiprocess_prototype/domain/entities/process.py` — добавить `metadata: dict[str, Any] = Field(default_factory=dict)` для passthrough runtime-полей (включая `source_target_fps`). Решение Q3 закрыто (см. decisions log): metadata-bag, не отдельное поле.
- `multiprocess_prototype/domain/__init__.py` — вынести регистрацию в default SchemaRegistry из import-time side-effect в explicit `register_domain_schemas(registry=None)` функцию. Сам импорт пакета **больше не должен** регистрировать ничего.
- `multiprocess_prototype/domain/tests/test_entities_roundtrip.py` — обновить тесты на новые поля (round-trip + frozen + extra-forbid).
- `multiprocess_prototype/domain/tests/test_schema_registry_lazy.py` — новый тест: импорт `multiprocess_prototype.domain` не регистрирует ничего в default registry; вызов `register_domain_schemas()` — регистрирует.

**Acceptance criteria:**
- [x] `Wire.description: str = ""` существует, round-trip lossless.
- [x] `Process.metadata: dict[str, Any]` существует, default empty dict, round-trip lossless.
- [x] `import multiprocess_prototype.domain` — 0 регистраций в `SchemaRegistry.get_default_registry()`.
- [x] `register_domain_schemas()` — регистрирует все 7 entities.
- [x] Все 233 теста Phase B остаются зелёными. (240 passed: 233 + 7 новых)

**Out of scope:** трогать `Recipe.from_dict` (там уже две формата поддержано), trogue `display_bindings` (миграция в Phase F).

**Refs:** investigator-ревью пункты 5 (gaps) + 7 (что бы изменил).

---

### Task C.1 — Read-only catalog adapters (PluginCatalog + ServiceCatalog + DisplayCatalog)

- **Level:** Middle (Sonnet)
- **Assignee:** developer
- **Module contract:** new-full (3 adapter'а одним Task'ом, потому что mapping тривиален и единообразен)

**Goal:** 3 простых wrapper'а над singleton-реестрами фреймворка. Каждый: `list_*`, `resolve(id)`, опционально `categories()`.

**Файлы:**
- `multiprocess_prototype/adapters/catalogs/plugin_catalog.py`
- `multiprocess_prototype/adapters/catalogs/service_catalog.py`
- `multiprocess_prototype/adapters/catalogs/display_catalog.py`
- `multiprocess_prototype/adapters/catalogs/__init__.py`
- `multiprocess_prototype/adapters/tests/test_catalogs.py`

**Steps:**

1. `PluginCatalogFromRegistry`:
   - Конструктор: `__init__(self, registry: _PluginRegistry)` — ссылку на singleton.
   - `list_plugins()` → `tuple(PluginSpec(...) for entry in registry.list())`.
   - `resolve(plugin_name)` → `PluginSpec` или `None`.
   - `categories()` → `tuple(set(e.category for e in registry.list()))`.
   - **Mapping `PluginEntry` → `PluginSpec`:** `name → name`, `category → category`, `inputs/outputs → ports` (tuple of `PortSpec`), `register_classes → config_schema` (dict с именами register_classes; точная схема — TODO Phase E).
2. `ServiceCatalogFromRegistry`: аналогично, `ServiceEntry → ServiceSpec`.
3. `DisplayCatalogFromRegistry`: аналогично, `DisplayEntry → DisplaySpec`. Singleton получается через `DisplayRegistry()` напрямую (audit зафиксировал: в `ctx.extras` его нет).

**Тесты:**
- `test_plugin_catalog_lists_known_plugins` — фейковый PluginRegistry с 2 plugin → list_plugins() возвращает 2 PluginSpec.
- `test_plugin_catalog_resolve_unknown_returns_none`.
- `test_plugin_catalog_categories_dedup`.
- Аналогично для service / display.
- `test_real_plugin_registry_smoke` — реальный модуль `Plugins/` подключается через `discover_plugins()`, adapter возвращает непустой список (smoke).

**Acceptance criteria:**
- [x] 3 adapter-класса + `__init__.py` экспорт.
- [x] Каждый adapter удовлетворяет соответствующий Protocol (assignment-проверка в тесте).
- [x] Round-trip: `entry.name == catalog.resolve(entry.name).name`.
- [x] Тесты на пустой registry (boundary).

**Out of scope:** `config_schema` детализация (Phase E когда нужен Inspector).

**Refs:** `multiprocess_framework/modules/process_module/plugins/registry.py` (PluginRegistry, fixed после C.1 discovery), `multiprocess_framework/modules/service_module/registry.py` (ServiceRegistry, fixed после C.1 discovery), `multiprocess_framework/modules/display_module/registry.py` (DisplayRegistry).

---

### Task C.1.5 — Backport PluginSpec/PortSpec gaps + DisplayRegistry preload

- **Level:** Middle (Sonnet)
- **Assignee:** developer
- **Module contract:** patch (расширение domain protocols + adapter mapping + app.py bootstrap)

**Goal:** Закрыть lossy mapping в PluginSpec/PortSpec, чтобы Phase E pipeline migration не упёрлась в отсутствие полей. + Загрузить DisplayRegistry из YAML в `app.py` до создания AppServices (чтобы read-only consumers видели данные).

**Reason:** investigator-отчёт 2026-05-27 выявил, что текущий PluginCatalog покрывает только 14% prod call sites (9/14 нуждаются в `description`, `optional`, ...). Pipeline migration в Phase E невозможна без этих полей. DisplayRegistry загружается лениво (только при открытии вкладки) — после Phase D `services.displays.list_displays()` вернёт пустой tuple.

**Файлы:**
- `multiprocess_prototype/domain/protocols/plugin_catalog.py` — добавить:
  - `PluginSpec.description: str = ""`
  - `PortSpec.optional: bool = False`
  - `PortSpec.shape: str = ""` (для round-trip lossless)
- `multiprocess_prototype/adapters/catalogs/plugin_catalog.py` — расширить mapping: `entry.description → spec.description`, для каждого `Port` → `PortSpec(name, kind, optional=port.optional, shape=port.shape or "")`.
- `multiprocess_prototype/frontend/app.py` — после строки `_service_registry = ServiceRegistry()` и discover, добавить `DisplayRegistry().load_from_yaml(...)` или эквивалент (найти как реальный DisplayRegistry знает path; вероятно `displays.yaml` в `multiprocess_prototype/`). Минимальное изменение: 3-5 строк.
- `multiprocess_prototype/adapters/tests/test_catalogs.py` — обновить fake-fixtures на новые поля, добавить тесты `test_plugin_spec_has_description`, `test_port_spec_has_optional_shape`.
- `multiprocess_prototype/domain/tests/test_protocols.py` (или соответствующий) — обновить assignment-проверки если требуется.

**Acceptance criteria:**
- [x] `PluginSpec.description: str = ""` добавлено.
- [x] `PortSpec.optional: bool = False` и `PortSpec.shape: str = ""` добавлены.
- [x] PluginCatalogFromRegistry заполняет эти поля из `PluginEntry` lossless.
- [x] `app.py` загружает DisplayRegistry из YAML до создания AppServices (если path существует).
- [x] 240 domain тестов passed + расширенные C.1 тесты passed.
- [x] 0 ruff errors.

**Out of scope:**
- `plugin_class: type` и `register_classes: list[type]` в PluginSpec — это явный compromise: adapter покрывает «catalog read» (~35%), а sandbox/command_catalog остаются на raw registry. Документировать в `adapters/README.md` (C.7).
- ServiceCatalog → ServiceManager расширение — это C.1.6.
- suppress_legacy_notify — не включаем в C.6 (см. decisions log Q7).

**Refs:** investigator-отчёт 2026-05-27, разделы 1.2 (Lossy mapping) и 3.1 (PluginSpec расширение).

---

### Task C.1.6 — ServiceCatalog → ServiceManager (расширение Protocol до lifecycle)

- **Level:** Senior (Opus)
- **Assignee:** teamlead
- **Module contract:** public-api-change (расширение domain Protocol + adapter API)

**Goal:** Текущий ServiceCatalog read-only не покрывает ни одного существующего consumer'а — ServicesPresenter мутирует `entry.lifecycle = RUNNING` и инстанцирует `entry.cls()` (start/stop/restart). Расширить до ServiceManager — добавить lifecycle methods, чтобы Phase E мог мигрировать ServicesPresenter.

**Reason:** investigator-отчёт 2026-05-27, раздел 1.1 / ServiceRegistry: 7 prod call sites, **0% покрыто** read-only adapter'ом.

**Decision (user-confirmed):** расширить, не убирать. Adapter охватывает реальный use case.

**Файлы:**
- `multiprocess_prototype/domain/protocols/service_catalog.py` — переименовать `ServiceCatalog` → `ServiceManager` (Protocol). Добавить методы:
  - `start(service_id) -> None` — инстанцирует и запускает сервис.
  - `stop(service_id) -> None` — останавливает.
  - `restart(service_id) -> None` — stop + start.
  - `get_lifecycle(service_id) -> ServiceLifecycle` — текущий статус.
  - `discover(*paths) -> DiscoveryResult` — пересканирование (опционально, если нужно из Services tab).
- `multiprocess_prototype/domain/__init__.py` — обновить re-export.
- `multiprocess_prototype/domain/app_services.py` — переименовать поле `services: ServiceCatalog` → `services: ServiceManager` (имя поля можно оставить `services` или переименовать в `service_manager` — решить teamlead).
- `multiprocess_prototype/domain/tests/_fakes.py` — `FakeServiceCatalog` → `FakeServiceManager` с lifecycle поддержкой.
- `multiprocess_prototype/adapters/catalogs/service_catalog.py` — переименовать класс в `ServiceManagerFromRegistry` (или новый файл `service_manager.py`), реализовать lifecycle методы делегацией к `ServiceRegistry.get(...).cls()` + lifecycle мутации. Read-only методы (`list_services`, `resolve`) остаются.
- `multiprocess_prototype/adapters/catalogs/__init__.py` — обновить re-export.
- `multiprocess_prototype/adapters/tests/test_catalogs.py` — обновить + добавить тесты lifecycle (start → RUNNING, stop → STOPPED, restart, get_lifecycle).
- `plans/2026-05-27_cross-tab-architecture/phase-d-app-services.md` — обновить D.1 snippet (`services: ServiceManagerFromRegistry(...)`).

**Edge cases:**
- Concurrent start/stop — single-threaded GUI предположение, но lock внутри adapter если нужен.
- `entry.cls()` падает — `DomainError` или `ServiceError`? Решить при имплементации.
- `start()` на уже запущенном сервисе — idempotent (no-op) или `DomainError`? Рекомендация: idempotent (no-op + log).

**Acceptance criteria:**
- [x] `ServiceManager` Protocol существует с 6 методами (list/resolve/start/stop/restart/get_lifecycle).
- [x] Adapter ServiceManagerFromRegistry satisfies Protocol.
- [x] Lifecycle тесты: start/stop/restart/get_lifecycle + error cases + idempotency.
- [x] `make_test_app_services()` builder использует `FakeServiceManager`.
- [x] AppServices.services: ServiceManager (расширено корректно).
- [x] 240+ domain тестов passed (240 domain + 51 adapter catalogs = 291 passed).
- [x] phase-d-app-services.md обновлён (D.1 snippet).

**Out of scope:**
- Migration ServicesPresenter — это Phase E.
- ConfigStore (D.2b) — независимая задача, не пересекается.

**Refs:** investigator-отчёт 2026-05-27, разделы 1.1/1.2/3.3.

---

### Task C.2 — AuthFacade adapter

- **Level:** Junior+ (Sonnet)
- **Assignee:** developer
- **Module contract:** new-lite (один маленький файл)

**Goal:** Тривиальный wrapper над `AuthManager` + `AuthState`. Read-only.

**Файлы:**
- `multiprocess_prototype/adapters/auth/auth_facade.py`
- `multiprocess_prototype/adapters/auth/__init__.py`
- `multiprocess_prototype/adapters/tests/test_auth_facade.py`

**Steps:**

1. `AuthFacadeFromAuthState`:
   ```python
   class AuthFacadeFromAuthState:
       def __init__(self, auth_state, auth_manager) -> None: ...
       @property
       def access_level(self) -> int:
           return self._state.access_context.level
       def is_authenticated(self) -> bool:
           return self._state.is_authenticated
       def has_permission(self, key: str) -> bool:
           return self._manager.permissions.has(key)
   ```

**Тесты:** 3-4 unit тестa с in-memory AuthState + AuthManager fakes.

**Acceptance criteria:**
- [x] AuthFacadeFromAuthState satisfies `AuthFacade` Protocol.
- [x] Тесты на (un)authenticated / level 0/100 / permission missing.

**Out of scope:** AuthLevelChanged / UserLoggedIn события через EventBus (Phase D / E).

---

### Task C.3 — TopologyRepository adapter

- **Level:** Middle+ (Sonnet)
- **Assignee:** developer
- **Module contract:** new-full (handoff source-of-truth решение)

**Goal:** Adapter поверх существующего `TopologyHolder`. На Phase C — bidirectional bridge: `load()` читает holder, `save()` пишет в holder (что триггерит legacy callbacks). На Phase D `CommandDispatcher` решит **сначала** `Project.apply()`, затем `holder.save()` — но это уже C.6 / D.

**Файлы:**
- `multiprocess_prototype/adapters/stores/topology_repository.py`
- `multiprocess_prototype/adapters/tests/test_topology_repository.py`

**Steps:**

1. **Decision Q1 закрыт (см. decisions log):** Project = source of truth в Phase D+. На уровне Phase C `TopologyRepositoryFromHolder` — bidirectional bridge, без переноса state в Project (Project живёт в C.6 `ProjectHolder`). `save()` пишет в holder; legacy callbacks подавляются через `suppress_legacy_notify()` cm (см. шаг 4).
2. `TopologyRepositoryFromHolder`:
   ```python
   class TopologyRepositoryFromHolder:
       def __init__(self, holder: TopologyHolder) -> None:
           self._holder = holder
       def load(self) -> Topology:
           return Topology.from_dict(self._holder.topology)
       def save(self, topology: Topology) -> None:
           self._holder.set_topology(topology.to_dict())
   ```
3. **Edge cases:**
   - `holder.topology` пустой / `None` → `Topology()` (пустой immutable).
   - `holder.set_topology()` валидирует через свой собственный pydantic? Проверь: может возникнуть рассинхрон с domain validate.
4. **`suppress_legacy_notify()` context manager** (Decision Q6 — toggle-флаг подход):
   ```python
   @contextlib.contextmanager
   def suppress_legacy_notify(self) -> Iterator[None]:
       self._holder._suppress_notify = True
       try:
           yield
       finally:
           self._holder._suppress_notify = False
   ```
   Реализация в `TopologyHolder._notify(...)`: если `_suppress_notify` истинно — `return` без вызова callbacks. Это **temporary measure до Phase F** (удаление `holder.on_changed`). Документировать в docstring adapter'а как «known compromise».

**Тесты:**
- `test_load_returns_topology_entity` — set_topology(...) → load() возвращает frozen domain.Topology с правильными полями.
- `test_save_writes_to_holder` — `save(topology)` → `holder.topology` содержит соответствующий dict.
- `test_round_trip_holder_load_save_load` — записываем pilot_widgets.yaml в holder, load → save → load — identical.
- `test_holder_callback_fires_on_save` — `holder.on_changed(cb)` → `repo.save(...)` → cb вызван 1 раз. **Это важно: подтверждает, что adapter использует legacy notification.**
- `test_suppress_legacy_notify_suppresses_callback` — внутри `with repo.suppress_legacy_notify(): repo.save(...)` cb не вызывается; после выхода из cm cb снова вызывается на следующий save.

**Acceptance criteria:**
- [ ] Adapter satisfies Protocol.
- [ ] Round-trip lossless на pilot_widgets.yaml.
- [ ] Legacy `holder.on_changed` callback продолжает работать (по умолчанию).
- [ ] `suppress_legacy_notify()` cm подавляет callbacks внутри блока, восстанавливает после.
- [ ] Edge case: пустой holder → пустой Topology.

**Out of scope:** Использование `suppress_legacy_notify()` из dispatcher — это C.6 (там cm применяется при `save()`).

**Refs:** `multiprocess_prototype/frontend/bridge/topology_bridge.py`, `multiprocess_prototype/frontend/topology_holder.py`.

---

### Task C.4 — RegistersBackend adapter

- **Level:** Middle+ (Sonnet)
- **Assignee:** developer
- **Module contract:** new-full

**Goal:** Адресация. RegistersManager использует `(process_name, register_name, field_name)`. Protocol — `(process_name, plugin_index, field_name)`. Нужна mapping-таблица «plugin_index → register_name».

**Файлы:**
- `multiprocess_prototype/adapters/stores/registers_backend.py`
- `multiprocess_prototype/adapters/tests/test_registers_backend.py`

**Steps:**

1. **Decision Q4 закрыт (см. decisions log): Variant A.** Adapter знает `TopologyRepository + PluginCatalog`. Для процесса `process_name` загружает topology → берёт `plugins[plugin_index].plugin_name` → через `PluginCatalog.resolve(plugin_name).config_schema` находит `register_class_name`. Protocol не меняется. Mapping локализован, документировать в docstring.

2. `RegistersBackendFromManager`:
   ```python
   class RegistersBackendFromManager:
       def __init__(self, registers_manager, topology_repo, plugin_catalog) -> None: ...
       def get_field_specs(self, process_name, plugin_index) -> tuple[FieldSpec, ...]: ...
       def get_value(self, process_name, plugin_index, field) -> Any: ...
       def set_value(self, process_name, plugin_index, field, value) -> None: ...
   ```

3. **Edge cases:**
   - `plugin_index` out of range → `KeyError` или `DomainError`? Уже зафиксировано в B.4: `DomainError`. Adapter повторяет.
   - Plugin без registers (например, `webcam_camera` сервис не имеет registers) → `()`.

**Тесты:**
- `test_get_field_specs_for_known_plugin` — реальный pilot_widgets.yaml (PilotWidgetsRegisters), get_field_specs возвращает 3 FieldSpec.
- `test_get_value_set_value_roundtrip` — `set_value(...)` → `get_value(...)` возвращает то же.
- `test_unknown_process_raises`.
- `test_plugin_without_registers_returns_empty`.

**Acceptance criteria:**
- [ ] Adapter satisfies Protocol.
- [ ] Mapping plugin_index → register_name работает (документировано в docstring).
- [ ] Round-trip set/get.

**Out of scope:** UI metadata (FieldSpec.label) — Phase E когда Inspector подключается.

**Refs:** `multiprocess_prototype/registers/manager.py`, `multiprocess_framework/modules/registers_module/`.

---

### Task C.5 — RecipeStore adapter (сложный)

- **Level:** Senior (Opus)
- **Assignee:** teamlead
- **Module contract:** new-full (главный сложный adapter)

**Goal:** `RecipeStoreFromManager` обходит `RecipeManager.save()` (там snapshot config-store семантика) и пишет YAML напрямую через `recipe_dir / f"{slug}.yaml"`. `read()` использует существующий `RecipeManager.read_recipe()`.

**Файлы:**
- `multiprocess_prototype/adapters/stores/recipe_store.py`
- `multiprocess_prototype/adapters/tests/test_recipe_store.py`

**Steps:**

1. **Decision Q2 закрыт (см. decisions log): Variant A** — денормализация `meta → top-level`. Adapter перед записью на диск переносит `data["meta"]["name"] → data["name"]`, `data["meta"]["version"] → data["version"]` и т.д. Live YAML остаётся читаемым legacy reader'ами; Phase C reversible без миграции файлов рецептов.
2. `RecipeStoreFromManager`:
   ```python
   class RecipeStoreFromManager:
       def __init__(self, recipe_manager, recipe_dir: Path) -> None: ...
       def list(self) -> tuple[str, ...]:
           return tuple(p.stem for p in self._dir.glob("*.yaml"))
       def read(self, slug) -> Recipe | None:
           raw = self._rm.read_recipe(slug)
           return Recipe.from_dict(raw) if raw else None
       def write(self, slug, recipe) -> None:
           data = self._denormalize(recipe.to_dict())  # meta → top-level
           (self._dir / f"{slug}.yaml").write_text(yaml.safe_dump(data))
       def delete(self, slug) -> None: ...
       def get_active(self) -> str | None:
           return self._rm.get_active_recipe()
       def set_active(self, slug) -> None:
           self._rm.activate(slug)
   ```
3. `_denormalize(data)` — перемещает `data["meta"]["name"]` → `data["name"]`, остальные `meta.*` → top-level. Также `display_bindings` — оставить в нормализованном формате (по плану F мигрировать) или преобразовать обратно к `source/display` (опц.).

**Тесты:**
- `test_list_returns_known_slugs`.
- `test_read_demo_recipe_returns_valid_recipe` — реальный `demo_webcam_split_merge.yaml` → `Recipe` instance со всеми полями.
- `test_write_recipe_roundtrips_through_disk` — write → read из tmp_path → equal в ключевых полях.
- `test_write_backward_compatible_format` — после write YAML имеет top-level `name/version`, не `meta:`.
- `test_get_active_returns_current_slug`.
- `test_delete_removes_file`.
- `test_unknown_slug_read_returns_none`.

**Acceptance criteria:**
- [ ] Adapter satisfies Protocol.
- [ ] Backward-compatible YAML формат при `write()`.
- [ ] Legacy `RecipeManager.activate()` продолжает работать.
- [ ] Тест на реальном demo_webcam_split_merge.yaml.

**Edge cases:**
- `RecipeManager.save(slug, paths)` — НЕ используется в этом adapter'е. Adapter пишет YAML напрямую. Это намеренное решение (engine ≠ recipe writer).

**Out of scope:** Migration v2 → v3 — Phase F.

**Refs:** `multiprocess_prototype/recipes/manager.py`, `multiprocess_prototype/recipes/recipe_engine.py`.

---

### Task C.6 — CommandDispatcher (оркестратор, самый сложный)

- **Level:** Senior (Opus)
- **Assignee:** teamlead
- **Module contract:** new-full (центральный orchestrator)

**Goal:** `dispatch(ProjectCommand) -> list[ProjectEvent]` — это **оркестратор**: (1) `Project.apply()`, (2) `TopologyRepository.save()` (с suppression legacy callbacks), (3) `EventBus.publish()` каждого события, (4) хранение текущего Project в self.

Это **сердце Phase C** — без него Phase D presenter не может работать.

**Файлы:**
- `multiprocess_prototype/adapters/dispatch/command_dispatcher.py`
- `multiprocess_prototype/adapters/tests/test_command_dispatcher.py`

**Steps:**

1. `CommandDispatcherOrchestrator`:
   ```python
   class CommandDispatcherOrchestrator:
       def __init__(
           self,
           project_holder: ProjectHolder,    # хранит current Project, B.6-style
           topology_repo: TopologyRepository,
           event_bus: EventBusProtocol,
           apply_context_factory: Callable[[], ApplyContext],
       ) -> None: ...

       def dispatch(self, command: ProjectCommand) -> list[ProjectEvent]:
           current = self._holder.get()
           catalogs = self._apply_context_factory()
           new_project, events = current.apply(command, catalogs=catalogs)
           # 1. save в topology repo (БЕЗ suppression — double notification до Phase F)
           self._topology_repo.save(new_project.topology)
           # 2. update holder
           self._holder.set(new_project)
           # 3. publish events
           for ev in events:
               self._event_bus.publish(ev)
           return events
   ```
2. `ProjectHolder` — простой mutable wrapper над текущим Project (frozen внутри). Живёт в `adapters/dispatch/project_holder.py` или прямо в `command_dispatcher.py`. Это **state** dispatcher'а.
3. **`suppress_legacy_notify` НЕ используется по умолчанию (Decision Q7 — user-confirmed 2026-05-27).** Context manager остаётся доступен в `TopologyRepository` adapter (C.3) на случай Phase F, но dispatcher вызывает `topology_repo.save()` штатно. Reason: investigator-отчёт 2026-05-27 (раздел 2.5) выявил 2 prod подписчика на `holder.on_changed`: `app.py:197` (TopologyBridge) + `pipeline/presenter.py:60` (PipelinePresenter). Подавление до миграции Phase E → UI рассинхрон. **Двойная нотификация (legacy callbacks + EventBus) — осознанный временный компромисс на Phase D/E.** Suppression включается только в Phase F после миграции всех подписчиков на EventBus.

**Тесты:**
- `test_dispatch_add_process_updates_project_and_publishes_event`.
- `test_dispatch_propagates_domain_error` — `AddProcess` с дубликатом имени → `DomainError`, holder/repo не меняется.
- `test_dispatch_save_to_topology_repo` — после dispatch, `repo.load()` отражает новое состояние.
- `test_dispatch_calls_legacy_notify_too` — legacy callback `holder.on_changed(cb)` **вызывается** при dispatch (Phase D/E — двойная нотификация по дизайну). Cb также получит EventBus event если подписан.
- `test_dispatch_publish_order` — события публикуются в порядке возврата из `apply()` (важно для cascade RemoveProcess).
- `test_dispatch_remove_process_cascade_events_published` — все 5 событий (ProcessRemoved + 3×WireDisconnected + 1×DisplayUnbound) опубликованы в порядке.
- `test_apply_context_factory_called_on_each_dispatch` — динамический контекст (catalogs могут меняться).

**Acceptance criteria:**
- [ ] Orchestrator satisfies CommandDispatcher Protocol.
- [ ] Dispatcher вызывает `topology_repo.save()` БЕЗ `suppress_legacy_notify` — legacy callbacks вызываются как обычно (двойная нотификация).
- [ ] Cascade events публикуются в правильном порядке.
- [ ] DomainError не оставляет holder в inconsistent state (rollback semantic не нужен, потому что `apply()` чистая функция — новый Project не записывается).

**Edge cases:**
- Что если `event_bus.publish()` бросает? Текущий EventBus ловит exceptions в handler'ах, но publish сам по себе не бросает. ОК.
- Concurrent dispatch — Phase D добавит lock (single-threaded предполагается в editor).

**Refs:** investigator risk #2 (двойная нотификация), B.4 Project.apply.

---

### Task C.7 — `adapters/__init__.py` + README + integration smoke

- **Level:** Middle (Sonnet)
- **Assignee:** developer
- **Module contract:** new-full

**Goal:** Сборка пакета: re-export 9 adapter'ов + README + integration smoke-тест, который собирает все 9 в `AppServices` (через `make_test_app_services` builder из B.6, но с реальными adapter'ами вместо `_fakes.py`).

**Файлы:**
- `multiprocess_prototype/adapters/__init__.py`
- `multiprocess_prototype/adapters/README.md`
- `multiprocess_prototype/adapters/tests/test_integration_assembly.py`

**Steps:**

1. README пакета — Purpose / Public API / Boundaries / Stability / Decisions:
   - Boundaries: adapter знает про `domain` + `framework` + `Services` + `Plugins` + другие `multiprocess_prototype/*`, но **не** про `frontend/`.
2. integration smoke test:
   ```python
   def test_assemble_app_services_with_real_adapters(tmp_path, ...) -> None:
       # реальный TopologyHolder с pilot_widgets.yaml
       # реальный PluginRegistry с discovered plugins
       # реальный RecipeManager на tmp_path
       # AuthState с mocked AuthManager
       services = AppServices(
           plugins=PluginCatalogFromRegistry(...),
           # ...
           commands=CommandDispatcherOrchestrator(...),
       )
       events = services.commands.dispatch(AddProcess(process_name="test"))
       assert any(isinstance(e, ProcessAdded) for e in events)
       assert "test" in {p.process_name for p in services.topology.load().processes}
   ```

**Acceptance criteria:**
- [ ] `from multiprocess_prototype.adapters import ...` — все 9 классов доступны.
- [ ] Integration smoke test проходит — `AddProcess` через `dispatch()` отражается в `topology.load()` и публикует событие.
- [ ] README соответствует структуре `domain/README.md` (Purpose / Public API / Boundaries / Stability / Decisions / References).

**Out of scope:** Adapter'ы подключаются в `app.py` — Phase D Task D.1.

---

## Acceptance criteria всей Phase C

- [ ] Все 9 Tasks (C.0, C.1, **C.1.5**, **C.1.6**, C.2—C.7) DONE.
- [ ] `python -m pytest multiprocess_prototype/adapters/tests/ -v` — все тесты passed.
- [ ] `python -m pytest multiprocess_prototype/domain/tests/ -v` — 233+ (плюс новые тесты C.0) тесты passed.
- [ ] `ruff check multiprocess_prototype/adapters/` — 0 errors.
- [ ] **Sentrux check:** adapter не импортирует `frontend/`. Добавить правило в `.sentrux/rules.toml`: `adapters → !frontend`.
- [ ] Integration smoke test (C.7) — реальные адаптеры собираются в AppServices, `dispatch(AddProcess)` работает end-to-end.
- [ ] `python scripts/validate.py` — passes.
- [ ] Никаких изменений вне `multiprocess_prototype/adapters/`, `multiprocess_prototype/domain/` (для C.0), и `.sentrux/rules.toml` (правило).
- [ ] Coverage `adapters/` ≥ 80%. Critical: `CommandDispatcherOrchestrator` ≥ 90%.

## Закрытые вопросы (decisions log)

Все 6 open questions закрыты 2026-05-27 (auto mode). См. секцию «Решения» ниже — каждое решение продублировано с обоснованием.

## Решения (decisions log)

### Стратегические (закрытые open questions)

- **2026-05-27 (closed Q1):** **Project = source of truth** в Phase D+. `TopologyHolder` остаётся как derived store: dispatcher после `Project.apply()` пишет в repo (под `suppress_legacy_notify`). Все читатели через AppServices видят `services.topology.load()` (derived из current Project) либо подписываются на EventBus. Holder.on_changed остаётся работать **только** для немигрированных presenter'ов (Phase E постепенно их переключает). Refs: investigator-ревью раздел 4.
- **2026-05-27 (closed Q2):** **Recipe YAML backward-compat — Variant A** (denormalize `meta → top-level` при `write()`). Reason: live YAML файлы (`demo_webcam_split_merge.yaml`, prod-рецепты) имеют top-level `name/version/...`; миграция формата = отдельный риск, отложить в Phase F. C.5 реализует `_denormalize(data)`.
- **2026-05-27 (closed Q3):** **Wire.description: str = "" как поле** + **Process.metadata: dict[str, Any]** как passthrough-bag. Reason: Wire.description — семантическая часть entity (используется в UI/документации wire), `Process.source_target_fps` — runtime-телеметрия (FPS-таргет), не часть persistent topology → metadata gracefully accumulates. **НЕ** добавляем `source_target_fps` как поле (избегаем расширения core entity ради runtime-полей).
- **2026-05-27 (closed Q4):** **RegistersBackend адресация — Variant A**. Adapter принимает `topology_repo` + `plugin_catalog` в ctor; в `get_field_specs(process, plugin_index)` читает текущую topology через repo, разрешает `plugin_index → plugin_name`, затем через `PluginCatalog.resolve(plugin_name).config_schema` находит `register_class_name`. Маппинг локализован в adapter, Protocol не меняется. Документировать в docstring + edge case `out of range → DomainError`.
- **2026-05-27 (closed Q5):** **DisplayRegistry — singleton напрямую**. Adapter получает `DisplayRegistry()` в ctor без захода через `ctx.extras`. Reason: audit зафиксировал, что в `ctx.extras` его нет; добавление = scope creep.
- **2026-05-27 (closed Q6):** **`suppress_legacy_notify` cm реализуется в C.3 как toggle-флаг** `holder._suppress_notify: bool` — но **НЕ применяется по умолчанию** (см. Q7 ниже). Контекст-менеджер остаётся в API repo для Phase F. Реализация: `holder._suppress_notify = True/False` через cm.
- **2026-05-27 (closed Q7 — user-confirmed после investigator-ревью):** **CommandDispatcher (C.6) НЕ использует `suppress_legacy_notify` по умолчанию.** Save через `topology_repo.save()` штатно вызывает legacy callbacks (`holder.on_changed`). EventBus publish идёт параллельно. **Двойная нотификация — осознанный временный компромисс Phase D/E.** Reason: investigator-отчёт 2026-05-27 (раздел 2.5) выявил 2 prod подписчика на legacy callbacks (`app.py:197` TopologyBridge + `pipeline/presenter.py:60` PipelinePresenter). Suppression до их миграции в Phase E → UI рассинхрон. Suppression активируется только в Phase F после полной миграции на EventBus.
- **2026-05-27 (added Tasks C.1.5 + C.1.6 — investigator follow-up):** В план Phase C добавлены 2 новых Task'а после C.1 (созданы пост-фактум после ревью реальных call sites):
  - **C.1.5** (Middle, developer): backport gaps в PluginSpec (`description`) и PortSpec (`optional`, `shape`) + загрузка DisplayRegistry из YAML в `app.py` до создания AppServices. Reason: PluginCatalog покрывает только 14% prod call sites без этих полей; DisplayRegistry загружается лениво и AppServices видит пустой tuple.
  - **C.1.6** (Senior, teamlead): расширение ServiceCatalog → **ServiceManager** Protocol с lifecycle методами (start/stop/restart/get_lifecycle). Reason: текущий read-only ServiceCatalog покрывает 0% prod call sites (ServicesPresenter мутирует lifecycle и инстанцирует cls()).
  - **Compromise documented:** PluginSpec НЕ получает `plugin_class: type` / `register_classes: list[type]` — sandbox и command_catalog остаются на raw registry. Adapter покрывает «catalog read» ~35%, не 100%.

### Тактические (структура Phase C)

- **2026-05-27 (draft):** Phase C — **7 Tasks**: C.0 hot-fix domain, C.1 catalogs (3-в-1), C.2 auth, C.3 topology, C.4 registers, C.5 recipes (сложный), C.6 dispatcher (центральный), C.7 README+integration. Группировка чтобы каждый Task ≤ 1 день.
- **2026-05-27 (draft):** Параллелизация: C.1, C.2, C.3, C.4 можно делать параллельно (3-4 worktree или последовательно). C.5 и C.6 зависят от C.3 (topology). C.7 — последним.
- **2026-05-27 (draft):** Adapter-пакет — UI-agnostic, не импортирует PySide6. Это enforced sentrux-правилом (новое правило, добавляется в C.0 или C.7).

## Что разблокирует Phase C

После approval deliverable Phase C можно начинать:

- **Phase D** — AppServices factory в `app.py:run_gui()`, постепенная подмена `ctx.extras` через deprecation-shim. Все 9 adapter'ов уже готовы; D.1 = собрать их в один dataclass.
- **Phase E** — per-tab migration. Каждый таб переходит на `services: AppServices` параметр вместо `ctx`.

---

> **Хранение:** `plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md`.
>
> **Workflow:** после approval плана пользователем — `/pipeline` или ручной запуск developer/teamlead агентов по Task'ам.
