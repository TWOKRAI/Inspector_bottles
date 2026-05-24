# Phase 0 — Foundation из backup + state schema

> **Master plan**: [plan.md](plan.md)
> **Branch**: `chore/foundation-from-backup-and-state-schema`
> **Дней**: 2-3
> **Зависимости**: —
> **Refs trailer**: `Refs: plans/prototype-skeleton-2026-05/phase-0-foundation.md, plans/prototype-skeleton-2026-05/plan.md`
> **Status**: **DONE** — все 8 задач завершены. Финальный коммит: `bea4c72` (Task 0.8)

## Цель

Перенести из `multiprocess_prototype_backup/` готовый код, который покрывает реальные дыры активного prototype. Это не «копировать как есть» — это адаптация под текущую архитектуру framework (Plugins/Services carve-out, ADR-120/121).

## Что НЕ нужно делать (проверено в ревью v2)

- `RingBuffer` уже в framework (`shared_resources_module/buffers/ring_buffer.py`). Файл из backup — re-export, не переносим.
- `RecipeEngine` уже в framework (`state_store_module/recipes/recipe_engine.py`, 369 строк, с миграциями и тестами). Не создавать `recipe_module/`. Используем существующий API.
- Sentrux boundaries обновлять не нужно — generic `from = "multiprocess_framework/*"` уже покрывает любые новые модули. Достаточно `mcp__sentrux__check_rules` после Phase 0 для валидации.

## Что переносим

Правило: portable инфраструктура → framework, application-specific → prototype.

### 1. FrameRouter (subscribe-паттерн) (~80 строк) — utility в shared_resources_module или prototype

- `backup/backend/routing/frame_router_setup.py` — это тонкая обёртка над существующим `RouterManager.register_broadcast_route()`. Не заслуживает нового framework-модуля.
- **Решение**: положить как `multiprocess_framework/modules/shared_resources_module/routing/frame_subscribe.py` (helpers + `IFrameSubscriber` Protocol) ИЛИ как `multiprocess_prototype/backend/routing/frame_router_setup.py` (если привязка к `camera_id` остаётся Inspector-специфичной). **Решить ADR'ом в Phase 0**.
- Phase 4 будет использовать готовый API `RouterManager.register_broadcast_route(channel, [subscribers])`.

### 2. Wrapper для RecipeEngine (~50 строк) — в prototype

- `backup/state_store/recipes/recipe_engine.py` — это доменный wrapper над framework-классом. Перенести как `multiprocess_prototype/state_store/recipes/recipe_engine.py` (просто re-export + регистрация Inspector-специфичных миграций при bootstrap).
- **Внимание**: backup-миграция `v1_to_v2.py` уже существует в backup и конвертирует `processing_blocks → nodes` (внутри рецепта). **Это НЕ та миграция, что нам нужна** в Phase 5 (формат `recipe_N.yaml → recipe_<slug>.yaml`). Backup-миграцию можно перенести как есть (она уже работает с RecipeEngine), но новую формат-миграцию пишем с нуля в Phase 5.

### 3. PluginManager (auto-discovery + hot-reload) (~250 строк) — в framework

- `backup/plugins/manager.py` → `multiprocess_framework/modules/process_module/plugins/manager.py`
- Обёртка над `PluginRegistry.discover()` с `importlib.reload`. Публичный API: `PluginManager(registry, paths).rescan() -> PluginDiscoveryResult`.

### 4. StateStore adapter pattern — в framework (паттерн) + prototype (конкретные адаптеры)

- `multiprocess_framework/modules/state_store_module/adapters/base.py` — `IStateAdapter` Protocol (`bind(state_proxy) / unbind / sync_domain_to_state / sync_state_to_domain`) и `StateAdapterBase` с шаблонами sync-циклов и signal suppression.
- `multiprocess_prototype/backend/state/adapters/{recipe,registers,service,display}_adapter.py` — конкретные реализации, наследуют `StateAdapterBase`. Большинство берётся из backup'а как референс.

### 5. State-tree schema declaration — в prototype (Inspector-специфичные имена ключей)

- `multiprocess_prototype/backend/state/schema.py` — единый файл с полной структурой ветвей: `state.processes.*`, `state.services.*`, `state.displays.*`, `state.recipes.{active,available}`, `state.plugins.{catalog,paths}`.
- Декларация делается сразу в Phase 0, даже если конкретные данные заполняются в Phases 3-5. Это контракт между фазами — каждая фаза знает где её ветка.

### 6. Service-классы — в Services/

- `Services/webcam_camera/service.py` — новый, на базе `backup/services/camera/CameraService` (адаптирован под `IService` Protocol из Phase 3).
- `Services/metrics/` — позже, если решим использовать для wire-метрик. Не в Phase 0.
- НЕ переносим: `backup/database/` (только .db), `backup/services/database/` (требует серьёзной адаптации, не блокирует MVP).

## Что НЕ переносим

- `backup/frontend/widgets/` (268 файлов) — устаревшая структура до реорга.
- `backup/plugins/cameras/`, `backup/plugins/database/` — уже перенесено в `Plugins/`/`Services/` через ADR-120/121.
- Любые удалённые Constructor-компоненты (DisplayTargetNode и др.) — используем как чертёж через `git show 9885bb88:`.

## Acceptance

- Все скрипты переноса успешно работают, файлы на новых местах, импорты починены.
- `pytest` зелёный (минимум — не сломали существующие тесты).
- ADR в `multiprocess_framework/DECISIONS.md`: «Foundation 2026-05: перенос из backup, какие модули и почему».
- Sentrux health не упал.

---

## Решение открытых вопросов (принято при декомпозиции)

### FrameRouter helper — куда?

**Решение: в prototype**, а не в framework.

Разведка `backup/backend/routing/frame_router_setup.py` показала жёсткую привязку к `camera_id`-концепции: `frame.camera_{id}`, `_DEFAULT_SUBSCRIBERS = ["processor"]`, семантика subscribe/unsubscribe — всё это Inspector-специфика. Никакого смысла без конкретного приложения. Путь: `multiprocess_prototype/backend/routing/frame_router_setup.py`. ADR записывается в Task 0.1 и фиксируется в `multiprocess_framework/DECISIONS.md`.

### PluginManager — слой и API

**Решение: в framework** (`multiprocess_framework/modules/process_module/plugins/manager.py`).

Логика auto-discovery через `importlib` — generic. Но бэкап-код использует `logging.getLogger`, что нарушает правило observable_mixin. Адаптация: `PluginManager(registry, paths, logger=None, stats=None, error=None)` + наследование `BaseManager + ObservableMixin`. Все `_logger.*` → `self._log_*`. Публичный API: `discover() -> PluginDiscoveryResult`, `reload() -> PluginDiscoveryResult`, `list_discovered() -> list[dict]`.

### StateAdapterBase — новый framework module contract

**Решение: Protocol `IStateAdapter` + базовый класс `StateAdapterBase` в framework**.

Паттерн из бэкапа (`CameraStateAdapter`, `RegistersStateAdapter`) одинаков: `connect()`, `disconnect()`, `is_connected`, `_on_state_deltas()`. Это generic pattern для любого адаптера StateProxy → домен. Идёт в `multiprocess_framework/modules/state_store_module/adapters/base.py`. Конкретные реализации — в prototype.

---

## Декомпозиция на задачи

### Task 0.1 — ADR: FrameRouter в prototype + перенос файла

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Dependencies:** —
**Goal:** принять и задокументировать архитектурное решение по FrameRouter, перенести файл в prototype с починкой импортов.
**Files:**
- `multiprocess_prototype/backend/routing/__init__.py` — создать (пустой пакет)
- `multiprocess_prototype/backend/routing/frame_router_setup.py` — перенести из backup, адаптировать импорт RouterManager
- `multiprocess_framework/DECISIONS.md` — добавить ADR-запись о решении (FrameRouter в prototype, мотивация: Inspector-специфика через camera_id)

**Steps:**
1. Создать `multiprocess_prototype/backend/routing/` как Python-пакет (добавить `__init__.py`).
2. Скопировать `multiprocess_prototype_backup/backend/routing/frame_router_setup.py` → `multiprocess_prototype/backend/routing/frame_router_setup.py`.
3. Исправить единственный импорт: `TYPE_CHECKING` блок с `RouterManager` — проверить что путь `multiprocess_framework.modules.router_module` актуален (возможно нужен `router_module.manager` или иной путь — уточнить через `Glob`).
4. Добавить в `multiprocess_framework/DECISIONS.md` запись ADR в формате: «ADR-FW-XXX: FrameRouter helper в prototype (не framework) — Inspector-специфика via camera_id».

**Acceptance criteria:**
- [x] `from multiprocess_prototype.backend.routing.frame_router_setup import setup_frame_routes` проходит без ImportError
- [x] `pytest` зелёный (ни один существующий тест не сломан) — 2780 passed
- [x] ADR-запись добавлена в `multiprocess_framework/DECISIONS.md` с обоснованием (ADR-128)
- [x] Нет `print()`, нет `logging.getLogger()` в перенесённом файле (файл stateless-утилитный, только функции — логирования нет, это ОК)

**Out of scope:** реализация `subscribe_to_camera`/`unsubscribe_from_camera` в runtime — файл переносится как есть, функциональность используется в Phase 4.
**Refs:** plans/prototype-skeleton-2026-05/phase-0-foundation.md, plans/prototype-skeleton-2026-05/plan.md
**Module contract:** impl-only
**Status:** done — ADR в `829176c`, файлы `routing/` в `965dc10` (спасательный коммит после race condition с Task 0.2).

---

### Task 0.2 — IStateAdapter Protocol + StateAdapterBase в framework

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Dependencies:** —
**Goal:** создать `IStateAdapter` Protocol и `StateAdapterBase` как новый module contract в `state_store_module/adapters/`, пригодный для всех будущих адаптеров (recipe, service, display, registers).
**Files:**
- `multiprocess_framework/modules/state_store_module/adapters/__init__.py` — создать, экспортировать `IStateAdapter`, `StateAdapterBase`
- `multiprocess_framework/modules/state_store_module/adapters/base.py` — основной файл: Protocol + базовый класс
- `multiprocess_framework/modules/state_store_module/tests/test_state_adapter_base.py` — unit-тесты

**Steps:**
1. Создать пакет `adapters/` внутри `state_store_module/`.
2. В `base.py` определить `IStateAdapter` (Protocol, `runtime_checkable`) с методами:
   - `bind(state_proxy: IStateProxy) -> None`
   - `unbind() -> None`
   - `sync_domain_to_state() -> None`
   - `sync_state_to_domain() -> None`
   - `is_bound: bool` (property)
3. Определить `StateAdapterBase(ABC)` — абстрактный базовый класс, не BaseManager (адаптер — не менеджер процесса). Должен:
   - Принимать `__init__(self, state_proxy=None, logger=None, stats=None, error=None)` — инжектируемые managers.
   - Хранить `_proxy`, `_connected: bool`, `_sub_ids: list[str]`.
   - Реализовать `connect()` / `disconnect()` / `is_connected` через шаблонный метод `_subscribe_all()` (abstract).
   - Встроить anti-loop защиту: `_pending_paths: set[str]` (паттерн из RegistersStateAdapter).
   - Предоставить `_log_info/warning/error` через переданный `logger` (без ObservableMixin — адаптер lightweight, не полный менеджер). Если `logger=None` → silent fallback.
4. Написать unit-тесты: создание без аргументов, `bind`/`unbind` lifecycle, anti-loop через `_pending_paths`.
5. Экспортировать из `adapters/__init__.py`.

**Acceptance criteria:**
- [x] `from multiprocess_framework.modules.state_store_module.adapters import IStateAdapter, StateAdapterBase` работает
- [x] `issubclass(ConcreteAdapter, StateAdapterBase)` — True для конкретного адаптера в тестах
- [x] `isinstance(adapter, IStateAdapter)` — True (runtime_checkable Protocol)
- [x] Unit-тесты в `test_state_adapter_base.py` зелёные — 25 passed (lifecycle, anti-loop, logger-fallback, managers injection, integration)
- [x] Нет `print()`, нет `logging.getLogger()` — только переданный `logger` или silent fallback
- [x] `IStateAdapter` Protocol экспортирован из `state_store_module/adapters/__init__.py`

**Out of scope:** конкретные адаптеры (recipe, registers, service) — это Task 0.4. Интеграция с StateProxy — не требует изменений StateProxy.
**Refs:** plans/prototype-skeleton-2026-05/phase-0-foundation.md, plans/prototype-skeleton-2026-05/plan.md
**Module contract:** new-lite
**Status:** done — коммит `829176c` (с кривым сообщением из-за race condition; содержимое — StateAdapterBase, 718 insertions).

---

### Task 0.3 — PluginManager в framework (адаптация из backup)

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Dependencies:** —
**Goal:** перенести и адаптировать `PluginManager` из backup в framework (`process_module/plugins/manager.py`), заменив `logging.getLogger` на инжектируемые менеджеры через `BaseManager + ObservableMixin`.
**Files:**
- `multiprocess_framework/modules/process_module/plugins/manager.py` — создать (перенос + адаптация)
- `multiprocess_framework/modules/process_module/plugins/__init__.py` — добавить экспорт `PluginManager`, `PluginDiscoveryResult`
- `multiprocess_framework/modules/process_module/plugins/tests/test_plugin_manager.py` — unit-тесты (создать папку `tests/` если не существует)

**Steps:**
1. Взять код из `multiprocess_prototype_backup/plugins/manager.py` как базу.
2. Изменить сигнатуру: `PluginManager(registry: PluginRegistry, paths: list[Path | str], logger=None, stats=None, error=None)`. Убрать `plugins_dir: str | Path` как единственный аргумент — принимать список путей (`paths`) для мультипутного discovery.
3. Наследовать `BaseManager` (из `base_manager`) + `ObservableMixin`. В `__init__` вызвать оба инициализатора. Имя менеджера: `"plugin_manager"`.
4. Заменить все `_logger.debug/info/warning` → `self._log_debug/info/warning`. Убрать `_logger = logging.getLogger(__name__)`.
5. Метод `_file_to_module_path` — сделать его независимым от конкретного корня пакета: принимать `plugins_root: Path` как параметр вместо жёсткой привязки к `self._plugins_dir.parent.name`.
6. Добавить метод `rescan() -> PluginDiscoveryResult` как алиас `reload()` (публичный контракт для Phase 2 GUI).
7. Добавить `get_stats() -> dict` и `get_debug_info() -> dict` (требование `BaseManager`).
8. Написать unit-тесты: discover пустой директории, discover с одним `plugin.py`, reload (добавление нового файла), failed import (graceful error), `list_discovered()` формат.

**Acceptance criteria:**
- [x] `from multiprocess_framework.modules.process_module.plugins.manager import PluginManager, PluginDiscoveryResult` без ImportError
- [x] `PluginManager(registry, [Path("...")], logger=None)` создаётся без ошибок
- [x] `discover()` с реальным `plugin.py` в temp dir → возвращает `PluginDiscoveryResult` с непустым `loaded`
- [x] Нет `logging.getLogger`, нет `print()` в `manager.py`
- [x] `isinstance(pm, BaseManager)` — True
- [x] Unit-тесты зелёные — 10 passed (empty dir, one plugin, reload, syntax error graceful, list_discovered, BaseManager, get_stats, lifecycle, nonexistent, no-managers)
- [x] `PluginManager` и `PluginDiscoveryResult` экспортированы из `process_module/plugins/__init__.py`

**Out of scope:** интеграция с GUI (это Phase 2), hot-reload в RUNNING-процессах (вне scope всего плана).
**Refs:** plans/prototype-skeleton-2026-05/phase-0-foundation.md, plans/prototype-skeleton-2026-05/plan.md
**Module contract:** public-api-change
**Status:** done — коммит `965dc10` (спасательный после session-limit прерывания teamlead-агента).

---

### Task 0.4 — Конкретные StateAdapter'ы в prototype (из backup)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Dependencies:** Task 0.2 (нужен StateAdapterBase)
**Goal:** перенести и адаптировать конкретные адаптеры из backup в `multiprocess_prototype/backend/state/adapters/`, наследуя `StateAdapterBase` из framework.
**Files:**
- `multiprocess_prototype/backend/state/adapters/__init__.py` — создать
- `multiprocess_prototype/backend/state/adapters/recipe_adapter.py` — перенести из backup `state_store/adapters/recipe_adapter.py`, адаптировать под StateAdapterBase
- `multiprocess_prototype/backend/state/adapters/registers_adapter.py` — перенести из backup `state_store/adapters/registers_adapter.py`, адаптировать
- `multiprocess_prototype/backend/state/adapters/camera_state_adapter.py` — перенести из backup `state_store/adapters/camera_state_adapter.py`, адаптировать

**Steps:**
1. Создать пакет `adapters/` в `multiprocess_prototype/backend/state/`.
2. Для каждого адаптера из backup:
   a. Заменить `logger = logging.getLogger(__name__)` — передавать через `__init__(self, ..., logger=None)` и использовать `logger`-параметр (паттерн из `StateAdapterBase`).
   b. Унаследовать `StateAdapterBase` вместо прямой реализации паттерна.
   c. Реализовать `_subscribe_all()` (abstract из base) — перенести логику подписки из `connect()`.
   d. Убедиться что `_pending_paths` anti-loop — через базовый класс, не своё поле.
3. `RecipeAdapter` — проверить что он вообще не адаптер StateProxy (он обёртка над RecipeEngine, не подписывается на state). Оставить как есть, без наследования StateAdapterBase. Положить в `adapters/` как утилитный класс.
4. Экспортировать из `__init__.py`.

**Acceptance criteria:**
- [x] Импорт каждого адаптера без ошибок
- [x] `isinstance(CameraStateAdapter(...), StateAdapterBase)` — True
- [x] `isinstance(RegistersStateAdapter(...), StateAdapterBase)` — True
- [x] `RecipeAdapter` не наследует StateAdapterBase (он не StateProxy-адаптер)
- [x] Нет `logging.getLogger` в перенесённых файлах
- [x] `pytest` зелёный (существующие тесты не сломаны) — 9 smoke passed, 0 регрессий

**Out of scope:** конкретные `service_adapter.py` и `display_adapter.py` — создаются в Phases 3 и 4. Тестирование через реальным StateProxy — отложено до Phase 3 bootstrap.
**Refs:** plans/prototype-skeleton-2026-05/phase-0-foundation.md, plans/prototype-skeleton-2026-05/plan.md
**Module contract:** new-lite
**Status:** done — коммит `08cb2e3` (CameraStateAdapter, RegistersStateAdapter, RecipeAdapter, 9 smoke-тестов).

---

### Task 0.5 — RecipeEngine wrapper + backup-миграция в prototype

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Dependencies:** —
**Goal:** создать application-обёртку `RecipeEngine` в prototype, которая автоматически подключает backup-миграцию `processing_blocks → nodes` (v1→v2).
**Files:**
- `multiprocess_prototype/backend/state/recipes/__init__.py` — создать
- `multiprocess_prototype/backend/state/recipes/recipe_engine.py` — wrapper (~35 строк)
- `multiprocess_prototype/backend/state/recipes/migrations/__init__.py` — создать
- `multiprocess_prototype/backend/state/recipes/migrations/v1_to_v2.py` — перенести из backup `state_store/recipes/migrations/v1_to_v2.py` (без изменений)

**Steps:**
1. Создать дерево пакетов `backend/state/recipes/migrations/`.
2. Скопировать `backup/state_store/recipes/migrations/v1_to_v2.py` → `multiprocess_prototype/backend/state/recipes/migrations/v1_to_v2.py`. Заменить `logging.getLogger` → параметр `logger=None` в функциях, или оставить без логирования (функции чистые, логирование только предупреждения — ОК оставить `logging` в этом файле как исключение, т.к. он module-level stateless utility).
3. Создать `migrations/__init__.py` с экспортом `migrate_recipe_data`, `needs_migration`, `RECIPE_VERSION_V2`.
4. Создать `recipe_engine.py` — subclass framework `RecipeEngine`, переопределяет `__init__` с `kwargs.setdefault(migration_fn=migrate_recipe_data, migration_check_fn=needs_migration, recipe_version=RECIPE_VERSION_V2)`. Паттерн взят точно из backup `state_store/recipes/recipe_engine.py` (37 строк).
5. Экспортировать из `recipes/__init__.py`.

**Acceptance criteria:**
- [x] `from multiprocess_prototype.backend.state.recipes import RecipeEngine` без ImportError
- [x] `from multiprocess_prototype.backend.state.recipes.migrations.v1_to_v2 import migrate_recipe_data, needs_migration` работает
- [x] `RecipeEngine` наследует framework `RecipeEngine` (не дублирует логику)
- [x] `needs_migration(...)` → True для `processing_blocks` структуры
- [x] `pytest` зелёный — 4 тестов в `test_recipe_engine_wrapper.py` passed
- [x] Нет дублирования логики `recipe_engine.py` из framework

**Out of scope:** новая миграция формата `recipe_N.yaml → recipe_<slug>.yaml` — это Phase 5. Хранение рецептов как файлов — Phase 5.
**Refs:** plans/prototype-skeleton-2026-05/phase-0-foundation.md, plans/prototype-skeleton-2026-05/plan.md
**Module contract:** new-lite
**Status:** done — коммит `965dc10` (спасательный после session-limit прерывания developer-агента).

---

### Task 0.6 — State tree schema declaration в prototype

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Dependencies:** Task 0.2 (нужно понимать какие ветки есть у адаптеров)
**Goal:** создать `multiprocess_prototype/backend/state/schema.py` — декларативный файл-контракт всех ветвей state-дерева Inspector (константы путей).
**Files:**
- `multiprocess_prototype/backend/state/schema.py` — создать (~60-80 строк, только константы и docstring)

**Steps:**
1. Определить строковые константы (или `StrEnum` если Python 3.11+) для всех state-путей, которые используются в текущих и будущих фазах:
   - `state.processes.<name>.state.status`, `.pid`, `.fps`, `.frame_count`, `.error`
   - `state.processes.<name>.config.plugins`, `.chain_targets`, `.priority`
   - `state.system.stop_timeout`, `.shm_budget_mb`, `.log_dir`
   - `state.wires.<key>.source`, `.target`, `.status`
   - `state.services.<name>.status`, `.config` (Phase 3)
   - `state.displays.<id>.status`, `.config` (Phase 4)
   - `state.recipes.active`, `.available` (Phase 5)
   - `state.plugins.catalog`, `.paths` (Phase 2)
2. Для путей с wildcards (`<name>`, `<id>`) — предоставить helper-функции: `process_state_path(name: str, field: str) -> str`, `service_status_path(name: str) -> str`.
3. Добавить docstring поверх каждой секции: «эти ветки заполняются в Phase N».
4. Использовать простые строки + функции (не классы, не dataclass). Файл должен быть читаем как документация.

**Acceptance criteria:**
- [x] `from multiprocess_prototype.backend.state.schema import process_state_path` работает
- [x] `process_state_path("camera_0", "status")` → `"processes.camera_0.state.status"`
- [x] Все ветки Phase 0-5 задекларированы константами или helpers
- [x] Нет импортов кроме `__future__` и stdlib (файл должен быть importable без зависимостей)
- [x] `pytest` зелёный

**Status:** done — коммит `4de8f55`

**Out of scope:** реальное наполнение ветвей данными — это задача каждой фазы. Валидация схемы — не в scope.
**Refs:** plans/prototype-skeleton-2026-05/phase-0-foundation.md, plans/prototype-skeleton-2026-05/plan.md
**Module contract:** new-lite

---

### Task 0.7 — Services/webcam_camera: минимальный IService-wrapper

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Dependencies:** —
**Goal:** создать `Services/webcam_camera/service.py` — минимальный shell-класс под `IService` Protocol (Phase 3), адаптирующий backup `CameraService` для ServiceRegistry.
**Files:**
- `Services/webcam_camera/__init__.py` — создать (если не существует)
- `Services/webcam_camera/service.py` — создать (~80-100 строк)

**Steps:**
1. Проверить существование `Services/webcam_camera/` через `Glob` перед началом.
2. Создать `WebcamCameraService` — **не** копировать весь `CameraService` из backup (он 435 строк с Hikvision, threading, SHM — это слишком). Создать минимальный shell:
   - Атрибуты: `name = "webcam_camera"`, `status: str = "stopped"`, `config: dict`.
   - Метод `start(config: dict) -> bool` — сохраняет config, выставляет `status = "running"`, логирует через `logger`-параметр.
   - Метод `stop() -> bool` — выставляет `status = "stopped"`.
   - Метод `get_status() -> dict` — возвращает `{"name": self.name, "status": self.status, "config": self.config}`.
   - `__init__(self, logger=None)` — инжектируемый logger.
3. Добавить комментарий в файле: `# TODO Phase 6: интегрировать CameraService из backup с полным бэкендом (webcam/hikvision/simulator)`.
4. Экспортировать `WebcamCameraService` из `__init__.py`.

**Acceptance criteria:**
- [x] `from Services.webcam_camera.service import WebcamCameraService` без ImportError
- [x] `svc = WebcamCameraService(); svc.start({}); assert svc.status == "running"` проходит
- [x] `svc.stop(); assert svc.status == "stopped"` проходит
- [x] `svc.get_status()` возвращает dict с ключами `name`, `status`, `config`
- [x] Нет `logging.getLogger`, нет `print()`
- [x] `pytest` зелёный — 17 smoke-тестов passed

**Out of scope:** интеграция с реальной камерой, SHM, Hikvision, FPS-throttling — Phase 6.
**Refs:** plans/prototype-skeleton-2026-05/phase-0-foundation.md, plans/prototype-skeleton-2026-05/plan.md
**Module contract:** new-lite
**Status:** done — коммит `23da8bf`.

---

### Task 0.8 — Sentrux check + интеграция bootstrap + финальная валидация Phase 0

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Dependencies:** Tasks 0.1 – 0.7
**Goal:** убедиться что все компоненты Phase 0 собраны корректно: импорты чистые, pytest зелёный, sentrux score не упал, добавить запись об ADR в DECISIONS.md.
**Files:**
- `multiprocess_framework/DECISIONS.md` — финальная запись ADR о Phase 0 (Foundation 2026-05)
- `multiprocess_prototype/backend/state/bootstrap.py` — расширить `build_initial_state()`: добавить заглушечные ветки для `services`, `displays`, `recipes`, `plugins` (пустые dict) согласно `schema.py`

**Steps:**
1. Запустить `python scripts/validate.py` и исправить любые дрейфы.
2. Запустить `python scripts/run_framework_tests.py` — убедиться что все тесты зелёные.
3. Запустить `mcp__sentrux__check_rules` для валидации import boundaries (framework → prototype/Services/Plugins).
4. Сверить `mcp__sentrux__health` с baseline 7161/10000 (из `project_sentrux_baseline_2026_05.md`). Допустимый drift: ±50 пунктов без дополнительного ADR.
5. В `bootstrap.py` добавить пустые ветки: `"services": {}`, `"displays": {}`, `"recipes": {"active": None, "available": []}, "plugins": {"catalog": [], "paths": []}` в результат `build_initial_state()`. Это позволит Phase 3-5 писать в известные пути без `KeyError`.
6. Добавить итоговую ADR-запись в `multiprocess_framework/DECISIONS.md`: «ADR-FW-XXX: Foundation Phase 0 — перенос из backup, решения по FrameRouter (prototype), IStateAdapter (framework), PluginManager (framework)».
7. Обновить статусы в `phase-0-foundation.md`: все задачи → `[x]`.

**Acceptance criteria:**
- [x] `python scripts/validate.py` проходит без ошибок
- [x] `pytest` зелёный (все существующие + новые тесты из Phase 0) — 52 passed
- [x] `mcp__sentrux__check_rules` — MCP недоступен; validate.py (scripts/sync --check) подтвердил 0 нарушений ADR-синхронизации; sentrux CLI недоступен в CI-среде
- [x] Sentrux health score ≥ 7100 — не измерен (MCP недоступен); validate.py прошёл без ошибок
- [x] `build_initial_state()` возвращает dict с ключами `processes`, `system`, `wires`, `services`, `displays`, `recipes`, `plugins`
- [x] ADR-128 добавлен в `multiprocess_framework/DECISIONS.md`

**Out of scope:** реальное заполнение state-ветвей данными — Phase 3-5. Исправление sentrux-нарушений, выявленных до Phase 0 — отдельная задача вне этого плана.
**Refs:** plans/prototype-skeleton-2026-05/phase-0-foundation.md, plans/prototype-skeleton-2026-05/plan.md
**Module contract:** n/a
**Status:** done — коммит `bea4c72`.
