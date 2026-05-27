# Plan: Phase B — Domain skeleton (новый пакет, в изоляции)

- **Slug:** cross-tab-architecture / phase B
- **Дата:** 2026-05-27 (review v2)
- **Статус:** DRAFT-v2 (после review: SchemaBase интегрирован, auth Protocol добавлен, builder фикстура зафиксирована, coverage уточнён, open questions сокращены)
- **Ветка:** `refactor/cross-tab-architecture` (та же, что Phase A)
- **Master plan:** [`plan.md`](plan.md)
- **Brief:** [`docs/refactors/2026-05_cross_tab_architecture.md`](../../docs/refactors/2026-05_cross_tab_architecture.md) (разделы 4 и 6 — обязательны)
- **Audit (вход):** [`docs/refactors/2026-05_cross_tab_audit.md`](../../docs/refactors/2026-05_cross_tab_audit.md) — особенно Inventory 1-3 (поля, реестры) и Inventory 5 (16 полей в неформальном контракте)
- **Базовая инфраструктура:** [`multiprocess_framework/modules/data_schema_module/`](../../multiprocess_framework/modules/data_schema_module/) — `SchemaBase`, `FieldMeta`, `DataConverter`, `SchemaRegistry`. **Все domain entities в Phase B наследуются от SchemaBase**, а не от голого `pydantic.BaseModel` — это даёт `get_fields_for_access_level()` для permission-aware Inspector (Phase E), `FieldMeta` для UI-описаний полей, готовый `DataConverter` для dict/JSON/YAML вместо ручных `to_dict`/`from_dict`, опциональный `SchemaRegistry` для discovery.

## Контекст

Phase A зафиксировала «как есть»: 40 raw-dict чтений топологии, 16 не описанных нигде полей, 8 параллельных реестров, 6 типов триггеров без типизированного payload'а. Каждый таб тянет свою «модельку» из dict.

Phase B создаёт **изолированный** доменный слой — пакет `multiprocess_prototype/domain/`, который **не подключается** к существующему коду. Это «параллельный домен» в смысле физической изоляции: импортируется только в собственные тесты, никакие presenter/AppContext/TopologyHolder в Phase B **не правятся**.

Цель такая ленивая интеграция — мержить Phase B в main без риска: даже если domain выглядит «странно» после ревью, runtime прототипа не затронут. Подключение делается в Phase D (`AppServices` DI), миграция табов — Phase E.

## Цели

- Создать пакет `multiprocess_prototype/domain/` с **типизированными** entities, events, commands, Protocols.
- Доменный слой **UI-agnostic** (нет импортов из `PySide6`, `multiprocess_prototype/frontend/`, `multiprocess_framework/modules/frontend_module/`).
- Доменный слой **runtime-agnostic** (нет импортов из `multiprocess_prototype/backend/`, `Services/`, `Plugins/`).
- 100% type coverage (pyright strict mode для `domain/`), unit-тесты без Qt.
- Round-trip тесты `raw_dict ↔ entity ↔ raw_dict` для blueprint совместимости (входные дикты — реальные срезы из `topology` audit'а).
- `AppServices` dataclass как **контракт DI** (без implementations) — готов к использованию в Phase D.

## Out of scope

- **Подключение к существующему коду.** `AppContext.extras` не правится. `TopologyHolder` не правится. Presenter-ы не трогаются.
- **Adapter-реализации Protocols.** YAML I/O, TopologyHolder-bridge, ProcessManager-proxy, RecipeStorage — всё это Phase C.
- **Runtime snapshot.** Phase B делает **только editor state** (`Project` = draft). Live PID'ы / lifecycle / метрики — отдельный aggregate, добавляется позже (Phase E/G), сейчас не моделируется.
- **Command history / undo.** В Phase B `Project.apply(command)` возвращает `list[ProjectEvent]`, история не хранится. Undo — Phase E через интеграцию с существующим ActionBus.
- **Миграция legacy форматов рецептов / blueprint.** Domain читает текущий v2-формат `SystemBlueprint` (см. `multiprocess_framework/modules/state_store_module/`). Версионирование — Phase F.
- **Qt-wrapper EventBus.** Чистый Python pub/sub. Qt-signals layer — Phase D (в `AppServices`).
- **Замена ActionBus / RegistersManager / Logger.** Эти системы продолжают жить параллельно; domain ссылается на них только через Protocols, не реализует.

## Phase B — структура папки

```
multiprocess_prototype/domain/
├── __init__.py              # public API (entities + AppServices + events)
├── README.md                # назначение пакета, правила импорта, ссылки
├── errors.py                # DomainError, ValidationError, RepositoryError
├── entities/
│   ├── __init__.py
│   ├── plugin.py            # PluginInstance (внутри Process)
│   ├── wire.py              # Wire (source, target, dtypes)
│   ├── display.py           # DisplayInstance
│   ├── process.py           # Process (агрегирует Plugin[], target_process)
│   ├── recipe.py            # Recipe (meta + Blueprint)
│   ├── topology.py          # Topology (Process[], Wire[], Display[], metadata)
│   └── project.py           # Project (корневой агрегат: Topology + active Recipe)
├── events.py                # ProjectEvent (discriminated union) + конкретные dataclass'ы
├── commands.py              # ProjectCommand (discriminated union) + конкретные dataclass'ы
├── event_bus.py             # typed pub/sub, pure Python
├── app_services.py          # frozen dataclass — типизированный DI-контейнер
├── protocols/
│   ├── __init__.py
│   ├── plugin_catalog.py    # Protocol для PluginRegistry (read-only)
│   ├── service_catalog.py   # Protocol для ServiceRegistry
│   ├── display_catalog.py   # Protocol для DisplayRegistry
│   ├── recipe_store.py      # Protocol для RecipeManager (CRUD)
│   ├── registers_backend.py # Protocol для RegistersManager
│   ├── topology_repository.py  # Protocol для TopologyHolder + persistence
│   ├── command_dispatcher.py   # Protocol для ActionBus
│   ├── event_bus.py         # Protocol для подписок (subscribe / publish)
│   └── auth_facade.py       # Protocol для AuthManager + AuthState (permission-aware)
└── tests/
    ├── __init__.py
    ├── conftest.py          # фикстуры + make_test_app_services() builder
    ├── _fakes.py            # 9 default in-memory implementations Protocols
    ├── test_entities_roundtrip.py
    ├── test_project_invariants.py
    ├── test_event_bus.py
    ├── test_commands_apply.py
    └── test_app_services_contract.py
```

**Принципы пакета:**
1. `entities/` — frozen Pydantic v2 модели; `to_dict()` / `from_dict()` для границы.
2. `events.py` / `commands.py` — `@dataclass(frozen=True, slots=True)` или Pydantic frozen (одинаково; см. Task B.2 для решения).
3. `protocols/` — только `typing.Protocol` без default-реализаций. Реализации — в Phase C `adapters/`.
4. `event_bus.py`, `app_services.py` — pure Python, без Qt-зависимостей.
5. Все public-имена — в `__init__.py`. Внутренние имена — `_underscore`.

## Phase B — Tasks

### Task B.1 — Entities (SchemaBase + frozen)

- **Level:** Middle+ (Sonnet)
- **Assignee:** developer
- **Module contract:** full (новый пакет с public API)

**Goal:** Создать 7 entity-моделей на базе **SchemaBase** (из `data_schema_module`) с `frozen=True` переопределением и round-trip dict-совместимостью для всех 16 полей из audit Inventory 5. Использовать `FieldMeta` для human-readable описаний и `DataConverter` для сериализации вместо ручных `to_dict`/`from_dict`.

**Файлы:**
- `multiprocess_prototype/domain/entities/plugin.py`
- `multiprocess_prototype/domain/entities/wire.py`
- `multiprocess_prototype/domain/entities/display.py`
- `multiprocess_prototype/domain/entities/process.py`
- `multiprocess_prototype/domain/entities/recipe.py`
- `multiprocess_prototype/domain/entities/topology.py`
- `multiprocess_prototype/domain/entities/project.py`
- `multiprocess_prototype/domain/entities/__init__.py`
- `multiprocess_prototype/domain/errors.py`
- `multiprocess_prototype/domain/__init__.py`
- `multiprocess_prototype/domain/README.md`
- `multiprocess_prototype/domain/tests/test_entities_roundtrip.py`
- `multiprocess_prototype/domain/tests/conftest.py`

**Steps:**
1. Поля для каждой entity — из audit Inventory 5 + Inventory 1. Все entities наследуются от `SchemaBase`. Описания полей через `Annotated[T, FieldMeta(...)]` (read-only «human label», не UI-control — для Inspector в Phase E):

   ```python
   from typing import Annotated
   from pydantic import ConfigDict
   from multiprocess_framework.modules.data_schema_module import SchemaBase, FieldMeta

   class Wire(SchemaBase):
       model_config = ConfigDict(
           frozen=True,
           populate_by_name=True,
           extra="forbid",
           # NB: validate_assignment из SchemaBase теряет смысл при frozen — это OK.
       )

       source: Annotated[str, FieldMeta("Узел-источник (process.plugin или process)")]
       target: Annotated[str, FieldMeta("Узел-приёмник")]
       src_dtype: Annotated[str | None, FieldMeta("Тип данных источника")] = None
       tgt_dtype: Annotated[str | None, FieldMeta("Тип данных приёмника")] = None
   ```

   Поля каждой entity:
   - `PluginInstance`: `plugin_name: str`, `config: dict[str, Any]` (config — нетипизированный dict в Phase B; типизация через `PluginCatalog.resolve(name).config_schema` появится в Phase C как opt-in валидация).
   - `Wire`: `source`, `target`, `src_dtype: str | None`, `tgt_dtype: str | None`.
   - `DisplayInstance`: `node_id`, `display_id`, `display_name: str | None`.
   - `Process`: `process_name`, `plugins: tuple[PluginInstance, ...]`, `target_process: str | None`, `chain_targets: tuple[str, ...] = ()`, `description: str | None = None`, `protected: bool = False`, `category: str | None = None`.
   - `RecipeMeta`: `name`, `version: int = 2`, `description: str = ""`, `created_at: str` (ISO timestamp, не datetime — для прозрачной YAML-сериализации).
   - `Recipe`: `meta: RecipeMeta`, `blueprint: Topology`, `active_services: tuple[str, ...]`, `display_bindings: tuple[DisplayInstance, ...]`, `gui_positions: dict[str, tuple[float, float]]`.
   - `Topology`: `processes: tuple[Process, ...]`, `wires: tuple[Wire, ...]`, `displays: tuple[DisplayInstance, ...]`, `metadata: dict[str, Any] = Field(default_factory=dict)` (для extension fields, не интерпретируется доменом).
   - `Project`: `topology: Topology`, `active_recipe: str | None` (это **slug**, не материализованный Recipe; materialization делает adapter в Phase C через `RecipeStore.read(slug)`).

2. **model_config переопределение.** SchemaBase по умолчанию имеет `validate_assignment=True` (для `update_field` mutability). Все 7 entities **переопределяют**: `model_config = ConfigDict(frozen=True, populate_by_name=True, extra="forbid")`. `validate_assignment` при frozen теряет смысл — никаких setattr.

3. **Сериализация через DataConverter, не ручные to_dict.** Использовать `multiprocess_framework.modules.data_schema_module.DataConverter` для dict/JSON/YAML. Если SchemaBase даёт `model_dump()` и `model_validate(...)` из коробки (Pydantic v2) — этого достаточно для большинства случаев; `DataConverter` нужен только если потребуется кастомная (de)сериализация tuple ↔ list (YAML не имеет tuple). На каждом entity — методы-обёртки:
   ```python
   @classmethod
   def from_dict(cls, data: dict[str, Any]) -> Self:
       return cls.model_validate(data)

   def to_dict(self) -> dict[str, Any]:
       return self.model_dump(mode="json")  # mode="json" для tuple→list и datetime→str
   ```
   Это **тонкие aliases** для читаемости в presenter'ах; внутри — Pydantic.

4. **errors.py:** `DomainError(Exception)` базовый класс; `EntityValidationError(DomainError)` оборачивает `pydantic.ValidationError` для unify-стиля в domain.

5. **Round-trip тесты** на **реальных файлах** проекта:
   - `multiprocess_prototype/recipes/demo_webcam_split_merge.yaml` (live рецепт).
   - `multiprocess_prototype/blueprints/DEFAULT_BLUEPRINT.yaml` (или текущий путь — найти grep'ом `DEFAULT_BLUEPRINT`).
   - Тест: `yaml.safe_load(text)` → `Recipe.from_dict(...)` → `recipe.to_dict()` → `yaml.dump` → `yaml.safe_load` → deep-equal с оригиналом по ключевым полям. Допускается несовпадение `gui_positions` порядка (dict insertion order) и tuple→list (YAML).

6. **SchemaRegistry — опционально.** В `domain/__init__.py` зарегистрировать все 7 entities в `SchemaRegistry`:
   ```python
   from multiprocess_framework.modules.data_schema_module import SchemaRegistry
   for cls in (PluginInstance, Wire, DisplayInstance, Process, Recipe, Topology, Project):
       SchemaRegistry.register(cls)
   ```
   Это даёт Inspector (Phase E) возможность `SchemaRegistry.lookup("Process")` для построения формы по схеме. Если SchemaRegistry имеет другой API — адаптировать; это **необязательная** часть Task B.1, может быть выделена в B.1.1 при complexity overflow.

**Acceptance criteria:**
- [ ] 7 entity-модулей + `errors.py` + `__init__.py` существуют.
- [ ] Все entities наследуются от `SchemaBase` (import `from multiprocess_framework.modules.data_schema_module import SchemaBase`).
- [ ] Все entities переопределяют `model_config` на `frozen=True, populate_by_name=True, extra="forbid"`.
- [ ] Используются `Annotated[T, FieldMeta(...)]` для всех описуемых полей (минимум — `process_name`, `source`, `target`, `display_name`, `plugin_name` — те, что Inspector в Phase E будет показывать).
- [ ] Pyright strict mode: `pyright multiprocess_prototype/domain/entities/ multiprocess_prototype/domain/errors.py` — 0 errors.
- [ ] `ruff check multiprocess_prototype/domain/` — 0 errors.
- [ ] Round-trip тесты для `DEFAULT_BLUEPRINT.yaml` и `recipes/demo_webcam_split_merge.yaml` — passed.
- [ ] Unit-тесты на отказ при missing required (process без `process_name` → `EntityValidationError`).
- [ ] Все entities `frozen=True` — попытка mutation вызывает `pydantic.ValidationError` (тест прямого `process.process_name = "x"`).
- [ ] `Process.plugins` — `tuple[...]`, не `list` (immutability). Аналогично `Topology.processes/wires/displays`.
- [ ] README пакета фиксирует: импорт только из `multiprocess_prototype.domain` и из `multiprocess_framework` (SchemaBase, FieldMeta). Запрещены импорты `frontend/`, `backend/`, `PySide6`, `multiprocess_framework.modules.frontend_module`.

**Out of scope:**
- Connection к `PluginCatalog.resolve(plugin_name)` — config типизированной схемой будет в Phase C.
- Cycle detection, dangling-wire validation — это Project.invariants() в Task B.4.
- `SchemaRegistry.register(...)` — реализуется если API подходит; иначе откладывается в Phase D (когда подключение становится осмысленным). Не блокирует acceptance.

**Edge cases:**
- В реальных blueprint встречаются `extra` fields (`"description"` появилось в Phase 7d). Использовать `extra="forbid"` + полный список полей из audit Inventory 5 + явный `metadata: dict[str, Any]` для будущих расширений на уровне Topology.
- `gui_positions` в Recipe — это `dict[node_id -> [x, y]]` в YAML. Конвертация в `dict[str, tuple[float, float]]` — в `from_dict`.

**Refs:** audit Inventory 5 (поля), Inventory 1 (использование), brief раздел 4.1 (Project / Process / Plugin структура), CLAUDE.md правило 1 (Dict at Boundary).

---

### Task B.2 — Events (типизированные dataclass'ы + discriminated union)

- **Level:** Middle (Sonnet)
- **Assignee:** developer
- **Module contract:** lite (один файл с docstring)

**Goal:** Создать набор типизированных событий, которые `Project` эмитит при изменениях. Подписчик получает конкретный тип, не raw-dict.

**Файлы:**
- `multiprocess_prototype/domain/events.py`

**Steps:**
1. Перечислить события, основанные на cross-tab триггерах из audit Inventory 4 + brief 4.2:
   - `ProcessAdded(process_name: str, process: Process)`
   - `ProcessRemoved(process_name: str)`
   - `ProcessRenamed(old_name: str, new_name: str)`
   - `PluginInserted(process_name: str, plugin: PluginInstance, index: int)`
   - `PluginRemoved(process_name: str, plugin_name: str, index: int)`
   - `PluginConfigChanged(process_name: str, plugin_index: int, field: str, value: Any)`
   - `WireConnected(wire: Wire)`
   - `WireDisconnected(source: str, target: str)`
   - `DisplayBound(display: DisplayInstance)`
   - `DisplayUnbound(node_id: str)`
   - `TargetProcessAssigned(process_name: str, target: str | None)`
   - `RecipeActivated(slug: str)`
   - `RecipeDeactivated()`
   - `TopologyReplaced(reason: str)` — для catastrophic replace (recipe launch / blueprint reload). Кейс-эскейп: «полное состояние сменилось, сделайте full refresh».
2. Каждое событие — `@dataclass(frozen=True, slots=True)` с `event_type: ClassVar[str]` дискриминатором (для serialization в Phase C, не используется в Phase B).
3. `ProjectEvent = Union[все события]` (typing.Union), экспортировать.
4. Базовый `ProjectEvent` ABC **не делать** — discriminated union даёт лучшую type narrowing в pyright.
5. Краткий docstring каждого события: «когда эмитится» (одна строка).

**Acceptance criteria:**
- [ ] Файл `domain/events.py` существует.
- [ ] Все 14 событий из списка определены.
- [ ] `pyright --strict` 0 errors.
- [ ] `ProjectEvent` — экспортирован из `domain/__init__.py`.
- [ ] Unit-тест: `match` exhaustiveness — pyright не жалуется на missing cases в demo handler.

**Out of scope:**
- Implementation EventBus (Task B.6).
- Wiring к существующему ActionBus (Phase D).
- Serialization events в IPC-формат (если потребуется — Phase F).

**Refs:** audit Inventory 4, brief 4.2 (принцип 2 — доменные события).

---

### Task B.3 — Commands (типизированные dataclass'ы)

- **Level:** Middle (Sonnet)
- **Assignee:** developer
- **Module contract:** lite

**Goal:** Перечень типизированных команд, которые presenter-ы будут отправлять `Project` для mutation. Параллель с событиями: одна команда → 1..N событий.

**Файлы:**
- `multiprocess_prototype/domain/commands.py`

**Steps:**
1. Команды (исходя из cross-tab scenarios brief 4.3 + audit Inventory 4 dispatcher'ов):
   - `AddProcess(process_name: str, plugins: tuple[PluginInstance, ...] = ())`
   - `RemoveProcess(process_name: str)`
   - `RenameProcess(old_name: str, new_name: str)`
   - `InsertPlugin(process_name: str, plugin: PluginInstance, index: int | None = None)` (None → append)
   - `RemovePlugin(process_name: str, index: int)`
   - `SetPluginConfig(process_name: str, plugin_index: int, field: str, value: Any)`
   - `ConnectWire(source: str, target: str, src_dtype: str | None = None, tgt_dtype: str | None = None)`
   - `DisconnectWire(source: str, target: str)`
   - `BindDisplay(node_id: str, display_id: str)`
   - `UnbindDisplay(node_id: str)`
   - `AssignTargetProcess(process_name: str, target: str | None)`
   - `ActivateRecipe(slug: str)`
   - `DeactivateRecipe()`
   - `ReplaceTopology(topology: Topology, reason: str)` — fallback для recipe launch.
2. `ProjectCommand = Union[все команды]`.
3. `@dataclass(frozen=True, slots=True)` для каждой.
4. Никаких validation в командах — это «намерение». Validation делает Project.apply() (Task B.4).

**Acceptance criteria:**
- [ ] Файл `domain/commands.py` существует.
- [ ] 14 команд определены, экспортированы из `__init__.py`.
- [ ] `pyright --strict` 0 errors.
- [ ] Demo тест: pattern-match по `ProjectCommand` — exhaustiveness check проходит.

**Out of scope:**
- Implementation `Project.apply()` (Task B.4).
- Привязка к ActionBus / undo-history (Phase D/E).

**Refs:** brief 4.2 (принцип 6), audit Inventory 4 (ActionBus.execute уже есть как mutation entry).

---

### Task B.4 — Project aggregate root (apply + invariants)

- **Level:** Senior (Opus)
- **Assignee:** teamlead
- **Module contract:** full (центральная entity)

**Goal:** `Project` — корневой агрегат с методом `apply(command, catalogs) -> list[ProjectEvent]`. Чистая функция: input команда + catalogs (read-only DI) → новое состояние Project + список событий. Invariants проверяются здесь, не разбросаны по presenter-ам.

**Файлы:**
- `multiprocess_prototype/domain/entities/project.py` (расширение от B.1)
- `multiprocess_prototype/domain/tests/test_project_invariants.py`
- `multiprocess_prototype/domain/tests/test_commands_apply.py`

**Steps:**
1. `Project.apply(self, command: ProjectCommand, *, catalogs: AppServicesProtocols) -> tuple[Project, list[ProjectEvent]]`. Возвращает **новый** Project (frozen), не мутирует.
2. Для каждой команды — отдельный handler:
   - `_apply_add_process(...)` — проверяет уникальность имени, optional валидация plugins через `catalogs.plugins.resolve(plugin_name)`.
   - `_apply_remove_process(...)` — каскад: удаляет связанные wires + display bindings → события `ProcessRemoved` + N×`WireDisconnected` + M×`DisplayUnbound`.
   - `_apply_connect_wire(...)` — проверяет: 1) оба node существуют, 2) нет цикла, 3) (опционально) dtype-совместимость через catalogs.
   - `_apply_activate_recipe(...)` — читает recipe из `catalogs.recipes.read(slug)`, валидирует blueprint, эмитит `TopologyReplaced(reason="recipe:{slug}")` + `RecipeActivated(slug)`.
   - Остальные — аналогично.
3. **Invariants** (вынесены в helper-функции):
   - `_check_unique_process_names(topology)` — все `process_name` уникальны.
   - `_check_no_dangling_wires(topology)` — каждый wire src/tgt ссылается на существующий node.
   - `_check_no_cycles(topology)` — нет циклов в DAG.
   - `_check_plugin_references(topology, catalogs)` — все `plugin_name` существуют в `catalogs.plugins`.
   - `_check_display_references(topology, catalogs)` — все `display_id` существуют в `catalogs.displays`.
4. На любую нарушенную invariant — `raise DomainError(...)`. Никаких silent fallback (это **противоположно** текущему `for proc in topology.get("processes", []): if isinstance(proc, dict):` стилю — Phase B нарочно строгая).
5. **NB:** `apply()` — чистая функция, **никаких side effects**. Не пишет в YAML, не дёргает IPC, не публикует события. Возврат — `(new_project, events)`. Publishing делается на уровне выше (EventBus в Task B.6, который вызывается из adapter'а в Phase C).

**Acceptance criteria:**
- [ ] `Project.apply()` реализован для всех 14 команд.
- [ ] Invariants reify: 5 helper-функций + unit-тесты на каждую.
- [ ] Тест каскадного удаления: `RemoveProcess` с 2 plugins, 3 wires к нему, 1 display binding → события `ProcessRemoved` + 3×`WireDisconnected` + 1×`DisplayUnbound`. Порядок зафиксирован: process → wires → displays.
- [ ] Тест rejection: добавить процесс с дубликатом имени → `DomainError("process_name 'x' already exists")`.
- [ ] Тест cycle detection: A→B, B→C, C→A → `DomainError("cycle detected")`.
- [ ] Тест plugin resolution: команда `InsertPlugin` с unknown plugin_name → `DomainError`, mock catalog возвращает None.
- [ ] `Project.apply()` — frozen-safe: не модифицирует self, возвращает новый Project.
- [ ] Coverage `domain/entities/project.py` ≥ 95% (центральный aggregate — стандарт выше общего).

**Out of scope:**
- Реализация `catalogs` — Mock в тестах, реальные adapter'ы — Phase C.
- Undo / command history — Phase E.
- Persistence — Phase C.
- **Runtime state** (PID'ы, lifecycle, метрики). Project — это **editor state** (draft, что пользователь редактирует). Runtime — отдельный observable, presenter подписывается отдельно (Phase E/G). Project НЕ хранит ссылок на runtime.

**Edge cases:**
- `ReplaceTopology` — не идёт через invariants пошагово; принимает уже готовый `Topology` объект (он по построению прошёл `Topology.from_dict()` validation). Проверки целостности оборачиваются в один проход.
- Command `ActivateRecipe` без активного `catalogs.recipes` (None) → `DomainError("recipe_store unavailable")`. В Phase B это покрывается тестом с явно None'овым stub.

**Refs:** brief 4.2 (принципы 1, 6), audit Inventory 5 (паттерны raw-dict обхода — Phase B убирает их через типизацию).

---

### Task B.5 — Protocols для catalogs / stores / dispatcher

- **Level:** Middle (Sonnet)
- **Assignee:** developer
- **Module contract:** lite

**Goal:** Описать **минимальные** интерфейсы, которые domain ждёт от внешнего мира. Адаптеры (Phase C) реализуют эти Protocols, оборачивая существующие PluginRegistry / ServiceRegistry / DisplayRegistry / RecipeManager / RegistersManager / TopologyHolder / ActionBus.

**Файлы:**
- `multiprocess_prototype/domain/protocols/__init__.py`
- `multiprocess_prototype/domain/protocols/plugin_catalog.py`
- `multiprocess_prototype/domain/protocols/service_catalog.py`
- `multiprocess_prototype/domain/protocols/display_catalog.py`
- `multiprocess_prototype/domain/protocols/recipe_store.py`
- `multiprocess_prototype/domain/protocols/registers_backend.py`
- `multiprocess_prototype/domain/protocols/topology_repository.py`
- `multiprocess_prototype/domain/protocols/command_dispatcher.py`
- `multiprocess_prototype/domain/protocols/event_bus.py` (отдельный от impl — impl в Task B.6)
- `multiprocess_prototype/domain/protocols/auth_facade.py` — Protocol для AuthManager + AuthState (текущее состояние permission-aware UI)

**Steps:**
1. **PluginCatalog (read-only):**
   ```python
   class PluginCatalog(Protocol):
       def list_plugins(self) -> tuple[PluginSpec, ...]: ...
       def resolve(self, plugin_name: str) -> PluginSpec | None: ...
       def categories(self) -> tuple[str, ...]: ...
   ```
   `PluginSpec` — namedtuple/dataclass с `name: str, category: str, config_schema: dict, ports: tuple[PortSpec, ...]`. (Сейчас framework содержит `PluginMeta` — Phase C сделает adapter `PluginMeta → PluginSpec`.)
2. **ServiceCatalog:** аналогично, `list_services`, `resolve(service_id)` → `ServiceSpec`.
3. **DisplayCatalog:** `list_displays() -> tuple[DisplaySpec, ...]`, `resolve(display_id)`.
4. **RecipeStore (CRUD):**
   ```python
   class RecipeStore(Protocol):
       def list(self) -> tuple[str, ...]: ...
       def read(self, slug: str) -> Recipe | None: ...
       def write(self, slug: str, recipe: Recipe) -> None: ...
       def delete(self, slug: str) -> None: ...
       def get_active(self) -> str | None: ...
       def set_active(self, slug: str | None) -> None: ...
   ```
   Domain работает с `Recipe` entity (B.1), не с raw-dict.
5. **RegistersBackend:** `get_field_specs(process_name, plugin_index) -> tuple[FieldSpec, ...]`, `get_value(process, plugin_index, field) -> Any`, `set_value(...)`. Минимальный API под нужды Inspector.
6. **TopologyRepository:** `load() -> Topology`, `save(topology: Topology) -> None`. **Опционально** — `subscribe(callback)` или подписки идут через EventBus (см. Task B.6) — решить в decisions log.
7. **CommandDispatcher:** `dispatch(command: ProjectCommand) -> list[ProjectEvent]`. Это «вход в Project из presenter». В Phase B — Protocol; adapter поверх существующего ActionBus — Phase C/D.
8. **EventBusProtocol:** `publish(event: ProjectEvent) -> None`, `subscribe(event_type: type[E], handler: Callable[[E], None]) -> Subscription`.
9. **AuthFacade:** минимальный read-only API для permission-gating в presenter-ах:
   ```python
   class AuthFacade(Protocol):
       @property
       def access_level(self) -> int: ...
       def is_authenticated(self) -> bool: ...
       def has_permission(self, key: str) -> bool: ...
   ```
   Эквивалент текущего `ctx.auth.state.access_context.level`, упакованный в Protocol. Реализация в Phase C — wrapper над существующими `IAuthManager` + `AuthState`. **NB:** Auth-signals (current_user_changed, access_context_changed) идут через EventBus (через отдельные доменные события `AuthLevelChanged`, `UserLoggedIn`/`UserLoggedOut`) — НЕ через Qt-signals в domain.

Все Protocols — `runtime_checkable=False` (статическая проверка достаточна).

**Acceptance criteria:**
- [ ] 9 файлов Protocols + `__init__.py` экспорт.
- [ ] Pyright strict 0 errors.
- [ ] Demo тест: in-memory implementation `PluginCatalog` (5 строк) удовлетворяет Protocol — pyright/mypy подтверждают.
- [ ] Никаких **default-реализаций** в Protocols (только signatures).

**Out of scope:**
- Реализации в adapter'ах — Phase C.
- Подписка через TopologyRepository vs EventBus — обсуждается в decisions log (см. ниже).

**Refs:** audit Inventory 3 (8 реестров — каждый Protocol-обёртка), brief 4.1 (Catalogs слой).

---

### Task B.6 — EventBus (pure Python) + AppServices skeleton

- **Level:** Middle+ (Sonnet)
- **Assignee:** developer
- **Module contract:** full (EventBus — отдельный модуль с API)

**Goal:** Простой synchronous typed pub/sub без Qt + `AppServices` frozen dataclass — контракт DI, без implementation. **Builder фикстура** `make_test_app_services(...)` в `tests/conftest.py` — закрывает «53 MagicMock без spec» проблему из audit'а: новые тесты строят `AppServices` через builder с дефолтными mock-Protocols, не через `ctx = MagicMock()`.

**Файлы:**
- `multiprocess_prototype/domain/event_bus.py`
- `multiprocess_prototype/domain/app_services.py`
- `multiprocess_prototype/domain/tests/test_event_bus.py`
- `multiprocess_prototype/domain/tests/test_app_services_contract.py`
- `multiprocess_prototype/domain/tests/conftest.py` — расширить фикстуру `make_test_app_services()` builder'ом.

**Steps:**
1. **EventBus implementation:**
   ```python
   class EventBus:
       def __init__(
           self,
           error_handler: Callable[[Exception, ProjectEvent], None] | None = None,
       ) -> None: ...

       def subscribe(self, event_type: type[E], handler: Callable[[E], None]) -> Subscription: ...
       def publish(self, event: ProjectEvent) -> None: ...
   ```
   - Хранит `dict[type[ProjectEvent], list[Callable]]`.
   - `Subscription` — context manager + explicit `.unsubscribe()`.
   - Exception в одном handler не блокирует остальных. По умолчанию ошибки логируются через **stdlib `logging.getLogger(__name__).exception(...)`** (не silent). `error_handler` параметр позволяет переопределить (например, в Phase D обернуть через `error_manager` фреймворка). **Никаких silent swallow** — правило 5 CLAUDE.md.
   - Synchronous (не async). Если потребуется async — Phase G.
   - Pure Python, никаких Qt-сигналов.
2. **AppServices (9 обязательных полей):**
   ```python
   @dataclass(frozen=True, slots=True)
   class AppServices:
       plugins: PluginCatalog
       services: ServiceCatalog
       displays: DisplayCatalog
       recipes: RecipeStore
       registers: RegistersBackend
       topology: TopologyRepository
       commands: CommandDispatcher
       events: EventBusProtocol
       auth: AuthFacade  # ← добавлено из B.5; permission-aware Inspector требует
       # logging — Phase D (через error_manager обёртку, отдельный Protocol)
   ```
   - Все поля — **обязательные** Protocols (никаких `Optional`). Domain ждёт полный набор. Тесты строят полный набор через builder (см. шаг 3) — это **противоположно** текущему `ctx.recipe_manager() → None` паттерну, который скрывал баги (см. recipe_manager hotfix 85eec097).
   - Никаких accessor-методов (отличие от существующего AppContext с `topology_holder()`, `plugin_registry()` и т.д. — там доступ опциональный, тут — атрибутный и обязательный).
   - `AppServices` **не создаётся** в Phase B в `app.py`. Реальная фабрика — Phase D. В Phase B `AppServices` существует только в тестах через builder.

3. **Test builder в conftest.py:**
   ```python
   def make_test_app_services(
       *,
       plugins: PluginCatalog | None = None,
       services: ServiceCatalog | None = None,
       displays: DisplayCatalog | None = None,
       recipes: RecipeStore | None = None,
       registers: RegistersBackend | None = None,
       topology: TopologyRepository | None = None,
       commands: CommandDispatcher | None = None,
       events: EventBusProtocol | None = None,
       auth: AuthFacade | None = None,
   ) -> AppServices:
       """Сборщик AppServices для тестов. Каждый None заменяется на in-memory
       mock-Protocol с предсказуемым default-поведением (empty list, None resolve,
       silent dispatch). Тесту переопределить нужное."""
       return AppServices(
           plugins=plugins or _DefaultPluginCatalog(),
           services=services or _DefaultServiceCatalog(),
           # ...
       )
   ```
   - Эта фикстура — **обязательный паттерн** для всех новых тестов в Phase B–G.
   - **Запрет:** новые тесты в `multiprocess_prototype/domain/tests/` не должны использовать `MagicMock(spec=AppServices)` — только builder. Если в Phase E/F появится потребность в `spec=...` — добавлять отдельным решением.
   - Default mock-Protocols: 9 классов в `tests/_fakes.py` (минимум stub'ов), не Mock'и — это даёт **type-checked** mocks (pyright проверит сигнатуры).

**Acceptance criteria:**
- [ ] `EventBus` реализован, тесты:
  - subscribe + publish → handler вызван;
  - 2 subscriber'а на один event → оба вызваны в порядке регистрации;
  - exception в handler 1 не блокирует handler 2 (default — `logging.exception`; кастомный `error_handler` зафиксировал ошибку, остальные продолжили);
  - unsubscribe через `Subscription.__exit__` корректно удаляет handler;
  - publish для типа без subscriber'ов — no-op без ошибок.
- [ ] `AppServices` dataclass — frozen, slots, **9 полей** (включая `auth`).
- [ ] Contract тест: `make_test_app_services()` (без аргументов) возвращает валидный AppServices с дефолтами; `make_test_app_services(plugins=custom_catalog)` подменяет только plugins; pyright не ругается на типы.
- [ ] EventBus pure Python: `grep -r "PySide6\|PyQt" multiprocess_prototype/domain/event_bus.py` → empty.
- [ ] EventBus error_handler default: при отсутствии custom handler exception в подписчике пишется через `logging.exception(...)`, не silent (тест проверяет caplog).
- [ ] `tests/_fakes.py` содержит 9 default-implementations Protocols (минимальные in-memory). Pyright strict — каждый satisfies своего Protocol.

**Out of scope:**
- Qt-wrapper EventBus для GUI thread safety — Phase D (когда подключается к presenter-ам).
- Реальные implementations Protocols — Phase C.
- AppServices factory — Phase D.

**Edge cases:**
- Subscribe к базовому `ProjectEvent` (union) — нужно/нет? Решение: только конкретные типы (типа `ProcessAdded`). Подписка на union сложна для type-narrowing; presenter-ы будут подписываться на конкретные события.
- EventBus thread-safety: synchronous + single-threaded использование (Qt main thread в presenter-ах). Если кто-то публикует из worker thread — поведение undefined. Phase D Qt-wrapper будет marshalling-ить через `QMetaObject.invokeMethod` на main thread.

**Refs:** brief 4.2 (принцип 2), open question 3 brief'а (Qt vs Pure Python — выбрана Pure Python с Qt-wrapper'ом в Phase D).

---

## Acceptance criteria всей Phase B

- [ ] Все 6 Tasks DONE, deliverables в `multiprocess_prototype/domain/`.
- [ ] **SchemaBase** используется как базовый класс для всех 7 entities (не `pydantic.BaseModel` напрямую).
- [ ] `python scripts/validate.py` — passes (никаких регрессий в существующем коде).
- [ ] `python -m pytest multiprocess_prototype/domain/tests/ -v` — все тесты passed.
- [ ] `pyright --strict multiprocess_prototype/domain/` — 0 errors.
- [ ] `ruff check multiprocess_prototype/domain/` — 0 errors.
- [ ] `sentrux check_rules` — passes (никаких новых нарушений архитектурных границ; в частности, `domain/` не импортирует ни `frontend/`, ни `PySide6`, ни `multiprocess_framework/modules/frontend_module/`, ни `backend/`).
- [ ] `grep -r "PySide6\|PyQt\|from multiprocess_prototype.frontend\|from multiprocess_prototype.backend" multiprocess_prototype/domain/` → пусто.
- [ ] Coverage `multiprocess_prototype/domain/` ≥ 85%; **coverage `entities/project.py` ≥ 95%** (центральный aggregate).
- [ ] README пакета фиксирует правила импорта и ссылается на эту Phase B и brief.
- [ ] Никаких изменений вне `multiprocess_prototype/domain/` (исключение: добавление правила в `.sentrux/rules.toml` для нового пакета и обновление master plan.md статусом Phase B).
- [ ] Round-trip тесты на реальных файлах `recipes/demo_webcam_split_merge.yaml` и `multiprocess_prototype/blueprints/DEFAULT_BLUEPRINT.yaml` (или текущий путь default'ного blueprint) — passed.
- [ ] `make_test_app_services()` builder работает; ни один новый тест не использует `MagicMock(spec=AppServices)` или `ctx = MagicMock()` (это закрывает паттерн из audit Inventory 6 — 53 файла).
- [ ] Sentrux baseline `session_start` → `session_end` показывает **рост** modularity score или хотя бы без падения (новый изолированный пакет с явными контрактами должен поднять метрику).

## Открытые вопросы

- [x] **Pydantic v2 BaseModel vs SchemaBase?** — **РЕШЕНО (2026-05-27, review):** SchemaBase из `data_schema_module`. Даёт FieldMeta для UI-описаний, access-level фильтрацию (`get_fields_for_access_level`), готовый DataConverter, опциональный SchemaRegistry. `model_config` переопределяется на `frozen=True, populate_by_name=True, extra="forbid"` (SchemaBase по умолчанию `validate_assignment=True`, который при frozen теряет смысл).
- [ ] **Topology updates: TopologyRepository.subscribe vs EventBus?** — *Решение по умолчанию:* EventBus. `TopologyRepository.load()/save()` — синхронные. Подписки идут через EventBus с типизированными событиями. Это упрощает Protocols (`TopologyRepository` минимален) и не размывает ответственность. Подтвердить.
- [x] **Включать ли `RuntimeSnapshot` (PID'ы, lifecycle, метрики) в Phase B?** — **РЕШЕНО:** нет. Phase B — только editor state (`Project`). Runtime snapshot — отдельный aggregate, добавляется при необходимости в Phase E/G. Brief раздел 4.2 принцип 7 это поддерживает. Зафиксировано в Out of scope Task B.4.
- [x] **Coverage threshold?** — **РЕШЕНО:** 85% общий по `domain/`, 95% для `entities/project.py` (центральный aggregate).
- [ ] **TopologyRepository source of truth (Phase C handoff).** Кто является источником истины для текущей Topology: 1) live YAML на диске (read each time), 2) live state в TopologyHolder (existing), 3) Project в памяти (новый). Brief 4.2 принцип 1 («single source of truth — Project») склоняет к (3). Это означает, что TopologyHolder в Phase C/D становится **deprecated**, а его потребители переключаются на `AppServices.topology`. Подтвердить до старта Phase C — может потребовать дополнительный adapter `TopologyHolderCompat` для legacy подписчиков.
- [ ] **Topology size assumption.** Текущий дизайн (`tuple[Process, ...]` + `model_copy` на каждом change) оптимизирован для O(50-100) entities. Если в будущем понадобится O(1000+), потребуется immutable persistent collections (`pyrsistent`) или mutable inside-aggregate операции. Зафиксировать как ADR-стаб в `domain/README.md`. Текущие рецепты — единицы процессов; целевое — десятки.
- [ ] **SchemaRegistry registration — обязательно или опционально?** — *Решение по умолчанию:* опционально в B.1 (не блокирует acceptance). Если API SchemaRegistry плохо подходит для frozen domain entities — отложить до Phase D, когда подключается AppContext.

## Решения (decisions log)

- **2026-05-27:** Phase B держит **6 Tasks** (entities / events / commands / Project / Protocols / EventBus+AppServices). Это естественная декомпозиция; меньше = слишком крупные шаги для review, больше = атомизация без выгоды.
- **2026-05-27:** Domain **полностью изолирован** от существующего кода. Никаких импортов из `frontend/`, `backend/`, `multiprocess_framework/modules/frontend_module/`. Enforced через sentrux rules (добавить правило в `.sentrux/rules.toml` опционально как Task B.0 или вписать в B.1).
- **2026-05-27:** Project.apply() — **чистая функция** `(state, command, catalogs) -> (state', events)`. Никаких side effects. Publishing — слой выше (Phase C/D adapter).
- **2026-05-27:** EventBus — pure Python synchronous. Qt thread-safety — Phase D wrapper. Это разделение upfront избегает того, что произошло с TopologyHolder (mix UI-thread-only state + business logic).
- **2026-05-27 (после review):** `AppServices` имеет **9 обязательных полей** (включая `auth: AuthFacade`). Никаких `| None`. Domain работает только с полным набором catalogs. Degraded mode (например, тесты без RegistersBackend) решается через mock-implementations Protocols — это «нормальная» инжекция, не «отсутствующая зависимость». Это противоположно текущему `ctx.recipe_manager()` → `RecipeManager | None`-паттерну (который только что дал live-bug — см. hotfix 85eec097).
- **2026-05-27:** **Не подключать к runtime в Phase B.** Любая попытка `from multiprocess_prototype.domain import ...` в существующих presenter-ах / app.py — out of scope. Это правило позволяет мержить Phase B в main без эффекта. Подключение — Phase D.
- **2026-05-27 (после review):** **SchemaBase** из `data_schema_module` используется как база для всех 7 entities. Альтернатива (голый Pydantic v2 BaseModel) была в первом черновике плана; review показал, что SchemaBase уже даёт нужную инфраструктуру (FieldMeta, get_fields_for_access_level для auth-gating, DataConverter, опциональный SchemaRegistry) и не требует дублирования. Layer-rules не нарушены: `multiprocess_framework → ... → multiprocess_prototype`, импорт SchemaBase в `multiprocess_prototype/domain/` законен.
- **2026-05-27 (после review):** Test builder `make_test_app_services(...)` в `tests/conftest.py` + 9 default-implementations Protocols в `tests/_fakes.py` — **обязательная** замена `MagicMock(spec=...)`. Это **превентивная** мера против повторения паттерна из audit Inventory 6 (53 MagicMock без spec, скрывших recipe_manager-bug). Запрет на ad-hoc MagicMock зафиксирован в Acceptance criteria всей Phase B.
- **2026-05-27 (после review):** EventBus default error handling — **`logging.exception(...)`**, не silent. Если в Phase D появится `error_manager` (фреймворковый паттерн правила 6 CLAUDE.md) — внедряется через `error_handler` параметр. Правило 5 CLAUDE.md «не подавлять ошибки молча» соблюдается с самого начала.

## Что разблокирует Phase B

После approval'а deliverable'а Phase B можно начинать:

- **Phase C** — adapters: `TopologyRepositoryFromHolder` (поверх TopologyHolder), `RecipeStoreFromManager`, `PluginCatalogFromRegistry`, `CommandDispatcherFromActionBus` и т.д. Каждый adapter — отдельный Task с тестами.
- **Phase D** — `AppServices` factory в `app.py:run_gui()`, постепенная подмена `ctx.extras` через deprecation-shim.

Phase E / F / G — после Phase D, по плану из brief.

---

> **Хранение:** `plans/2026-05-27_cross-tab-architecture/phase-b-domain.md` (внутри multi-phase папки).
>
> **Workflow дальше:** после approval плана Director вызывает teamlead для Task B.4 (Senior, центральный) и developer-ов для B.1, B.2, B.3, B.5, B.6 (Middle/Middle+). Параллелизация: B.1 → потом B.2 + B.3 + B.5 параллельно → потом B.4 (зависит от B.1, B.2, B.3, B.5) + B.6 параллельно. Финальный коммит в ветку `refactor/cross-tab-architecture` с trailer `Refs: plans/2026-05-27_cross-tab-architecture/phase-b-domain.md`.
>
> Phase C детализируется отдельным `phase-c-adapters.md` после approval Phase B deliverable.
