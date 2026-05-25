# Phase 3 — ServiceRegistry + первые сервисы

> **Master plan**: [plan.md](plan.md)
> **Branch**: `feat/service-registry`
> **Дней**: 3-4
> **Зависимости**: Phase 0 (для StateAdapterBase + регистрации сервисов)
> **Refs trailer**: `Refs: plans/prototype-skeleton-2026-05/phase-3-service-registry.md, plans/prototype-skeleton-2026-05/plan.md`

## Цель

ServiceRegistry для long-running объектов (камеры, БД, auth) с lifecycle, отдельно от PluginRegistry. В pipeline сервисы используются через плагин-обёртки (как `hikvision_camera`).

## Реюз готового

- Паттерн `PluginRegistry` (262 строки) — копируем структуру.
- `Services/hikvision_camera/` — образец плагина-обёртки.
- `backup/services/camera/CameraService` — первый сервис для демо (webcam через OpenCV).
- ADR-121, ADR-122 — границы слоя.

## Новое (минимально)

- `multiprocess_framework/modules/service_module/interfaces.py` — `ServiceLifecycle` enum (UNREGISTERED → READY → RUNNING → STOPPED → ERROR), `IService` Protocol (`start(config: dict) -> bool`, `stop() -> bool`, `get_status() -> dict`, свойство `name: str`).
- `multiprocess_framework/modules/service_module/registry.py` — `ServiceRegistry` (singleton, `@register_service`, `list/get/filter`).
- `multiprocess_framework/modules/service_module/scanner.py` — `discover(*dirs)` сканирует `service.py`.
- `Services/sql/service.py`, `Services/hikvision_camera/service.py`, `Services/auth/service.py` — точки регистрации `@register_service`.
- `Services/webcam_camera/service.py` — **уже создан в Phase 0** (shell-класс `WebcamCameraService`), здесь добавить `@register_service`.
- `multiprocess_prototype/backend/state/adapters/service_state_adapter.py` — двусторонняя sync ServiceRegistry ↔ `state.services.*`.
- ADR в `multiprocess_framework/DECISIONS.md`: «ServiceRegistry: гибрид с PluginRegistry, lifecycle, scanner».

## ServicesTab

- `tabs/services/tab.py` — переключить на `ServiceRegistry.list()`.
- Подвкладка «Пути» — аналог Phase 2 для `service_paths`.
- Action-кнопки: «Запустить / Остановить / Перезапустить» → `ServiceRegistry.get(name).start()/stop()`.
- Статус: из `state.services.<name>.status`.
- Утилитарные (Operation_crop, Region_processors) — показываются как «library, не запускаются».

## Acceptance

- В ServicesTab видны 5+ сервисов.
- `webcam_camera` можно запустить → state переходит в RUNNING → активный сервис доступен для sandbox в Phase 6 и для демо в Phase 7.
- Минимум 15-20 unit-тестов на ServiceRegistry+lifecycle.

---

## Декомпозиция на задачи

### Task 3.1 — ServiceLifecycle + IService + interfaces.py

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Создать публичный контракт нового framework-модуля `service_module` — `ServiceLifecycle` enum и `IService` Protocol, которые станут точкой зависимости для всего остального кода Phase 3.

**Context:** Это фундаментальный шаг «contract-first» по аналогии с `IStateAdapter` из Phase 0. Никакой реализации здесь нет — только типы и Protocol. `IService` должен быть `@runtime_checkable`, чтобы `isinstance(obj, IService)` работало без явного наследования (паттерн из `hikvision_camera/interfaces.py`). Lifecycle-автомат: `UNREGISTERED → READY → RUNNING → STOPPED → ERROR`; переходы должны быть задокументированы в docstring. Без этой задачи нельзя делать 3.2–3.5.

**Files:**
- `multiprocess_framework/modules/service_module/__init__.py` — создать, экспортировать `IService`, `ServiceLifecycle`
- `multiprocess_framework/modules/service_module/interfaces.py` — создать: `ServiceLifecycle` (StrEnum или Enum), `IService` Protocol (`start(config: dict) -> bool`, `stop() -> bool`, `get_status() -> dict`, свойство `name: str`)
- `multiprocess_framework/modules/service_module/STATUS.md` — создать (шаблон из `multiprocess_framework/docs/MODULE_README_TEMPLATE.md`)

**Steps:**
1. Создать директорию `multiprocess_framework/modules/service_module/`.
2. В `interfaces.py` определить `ServiceLifecycle(str, Enum)` с состояниями `UNREGISTERED`, `READY`, `RUNNING`, `STOPPED`, `ERROR`; добавить docstring с допустимыми переходами.
3. В `interfaces.py` определить `@runtime_checkable class IService(Protocol)` с методами `start(config: dict) -> bool`, `stop() -> bool`, `get_status() -> dict` и свойством `name: str`. Добавить docstring с примером использования.
4. Убедиться, что `service_module` НЕ импортирует ничего из `Services/`, `Plugins/`, `multiprocess_prototype/` — только stdlib и `__future__`.
5. Создать `STATUS.md` по шаблону (статус: DRAFT, фаза: Phase 3).
6. В `__init__.py` реэкспортировать `IService`, `ServiceLifecycle` через `__all__`.

**Acceptance criteria:**
- [ ] `from multiprocess_framework.modules.service_module import IService, ServiceLifecycle` работает без ошибок
- [ ] `isinstance(WebcamCameraService(), IService)` → `True` (структурная совместимость)
- [ ] `ServiceLifecycle.RUNNING` → строка `"running"` (если `StrEnum`) или проверяемое значение
- [ ] Нет импортов из `Services/`, `Plugins/`, `multiprocess_prototype/` в `interfaces.py`
- [ ] `STATUS.md` создан

**Out of scope:** реализация Registry, scanner, тесты (это Task 3.2). ADR (Task 3.8).

**Edge cases:** `IService.name` — свойство, а не атрибут класса; Protocol не требует явного наследования — проверить `isinstance` с `WebcamCameraService` (уже существует в `Services/webcam_camera/service.py`, атрибут `name: str = "webcam_camera"` — ок).

**Dependencies:** нет (первая задача фазы)

**Refs:** plans/prototype-skeleton-2026-05/phase-3-service-registry.md, plans/prototype-skeleton-2026-05/plan.md

**Module contract:** new-full

**Status:** ✅ Done

---

### Task 3.2 — ServiceRegistry (singleton + @register_service + list/get/filter)

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Реализовать `ServiceRegistry` — singleton-реестр сервисов с декоратором `@register_service`, методами `list()/get()/filter()` и unit-тестами.

**Context:** Образец — `PluginManager` из `multiprocess_framework/modules/process_module/plugins/manager.py` (262 строки), но `ServiceRegistry` проще: без hot-reload, без `importlib.reload`, без BaseManager. Это чистый in-memory каталог с thread-safe доступом. Структура записи `ServiceEntry` должна хранить: `name`, `cls` (класс сервиса), `lifecycle` (`ServiceLifecycle`), `meta` (опциональный dict). `@register_service` — декоратор над классом, автоматически добавляющий запись в singleton. Это критический модуль фреймворка — минимум 15 unit-тестов.

**Files:**
- `multiprocess_framework/modules/service_module/registry.py` — создать: `ServiceEntry` dataclass, `ServiceRegistry` singleton, `register_service` декоратор
- `multiprocess_framework/modules/service_module/tests/__init__.py` — создать (пустой)
- `multiprocess_framework/modules/service_module/tests/test_registry.py` — создать: ≥15 unit-тестов

**Steps:**
1. Определить `ServiceEntry` dataclass: поля `name: str`, `cls: type`, `lifecycle: ServiceLifecycle`, `meta: dict`. `lifecycle` по умолчанию `ServiceLifecycle.UNREGISTERED`.
2. Реализовать `ServiceRegistry` как singleton (metaclass или `__new__`, по аналогии с архитектурой проекта): внутри `_registry: dict[str, ServiceEntry]` + `threading.Lock`.
3. Методы: `register(entry: ServiceEntry) -> None`, `get(name: str) -> ServiceEntry | None`, `list() -> list[ServiceEntry]`, `filter(lifecycle: ServiceLifecycle) -> list[ServiceEntry]`, `unregister(name: str) -> bool`, `clear() -> None` (для тестов).
4. Реализовать `@register_service(name: str | None = None, meta: dict | None = None)` — декоратор над классом. Если `name=None`, берёт `cls.name` (атрибут класса). При регистрации проверяет `IService` Protocol через `issubclass` или `isinstance`.
5. Написать ≥15 unit-тестов: регистрация, дубликат-ошибка, get-miss → None, filter по lifecycle, clear() сбрасывает реестр, decorator-применение.
6. Добавить `ServiceRegistry`, `ServiceEntry`, `register_service` в `service_module/__init__.py`.

**Acceptance criteria:**
- [ ] `python -m pytest multiprocess_framework/modules/service_module/tests/test_registry.py` — все тесты зелёные
- [ ] Попытка зарегистрировать класс без `name` и без атрибута `cls.name` → `ValueError`
- [ ] Дубликат имени при регистрации → `ValueError` (или `KeyError`)
- [ ] `ServiceRegistry()` возвращает один и тот же экземпляр (singleton)
- [ ] `filter(ServiceLifecycle.RUNNING)` возвращает только сервисы в состоянии RUNNING

**Out of scope:** scanner/discover (Task 3.3), инстанцирование сервисов (Registry хранит классы, не экземпляры — экземпляры создаются при вызове `start()`).

**Edge cases:** thread-safety при конкурентной регистрации; `clear()` нужен для изоляции тестов (чистить singleton между тестами); пустой реестр — `list()` → `[]`, не исключение.

**Dependencies:** Task 3.1

**Refs:** plans/prototype-skeleton-2026-05/phase-3-service-registry.md, plans/prototype-skeleton-2026-05/plan.md

**Module contract:** new-full

**Status:** ✅ Done (commit 6be49c3)

---

### Task 3.3 — ServiceScanner (discover) + регистрация существующих сервисов

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Реализовать `scanner.discover(*dirs)` для автоматического поиска и регистрации сервисов из `service.py`-файлов, и добавить `@register_service` в существующие `Services/sql`, `Services/hikvision_camera`, `Services/auth`.

**Context:** Паттерн scanner-а идентичен `PluginManager.discover()` из `multiprocess_framework/modules/process_module/plugins/manager.py`: рекурсивный обход директорий, поиск `service.py`, `importlib.import_module`, декоратор при импорте сам регистрирует в Registry. Важно: `scanner.py` живёт в `service_module` (фреймворк) и НЕ знает о конкретных `Services/`. Сервисы в `Services/` добавляют `@register_service` — это application-слой. Для `Services/hikvision_camera` нужно создать `service.py` (его нет), для `Services/sql` и `Services/auth` — аналогично. Эти shell-классы аналогичны уже готовому `WebcamCameraService` в `Services/webcam_camera/service.py` (Task 3.4 уже выполнен!).

**Files:**
- `multiprocess_framework/modules/service_module/scanner.py` — создать: `discover(*dirs: Path) -> DiscoveryResult`, `DiscoveryResult` dataclass
- `multiprocess_framework/modules/service_module/tests/test_scanner.py` — создать: тесты с tmpdir
- `Services/sql/service.py` — создать: `SqlService` shell-класс с `@register_service`
- `Services/hikvision_camera/service.py` — создать: `HikvisionCameraService` shell-класс с `@register_service`
- `Services/auth/service.py` — создать: `AuthService` shell-класс с `@register_service`
- `Services/webcam_camera/service.py` — ИЗМЕНИТЬ: добавить `@register_service` к `WebcamCameraService` (файл уже существует)

**Steps:**
1. В `scanner.py` создать `DiscoveryResult` dataclass: `loaded: list[str]`, `failed: list[tuple[str, str]]`, свойство `total: int`.
2. Реализовать `discover(*dirs: Path, registry: ServiceRegistry | None = None) -> DiscoveryResult`: рекурсивный `glob("**/service.py")`, `importlib.import_module` через динамическое имя пакета (через `sys.path` или `importlib.util.spec_from_file_location`), при ошибке — запись в `failed`, не выброс.
3. В `multiprocess_framework/modules/service_module/tests/test_scanner.py` написать тесты с `tmp_path`: создать dummy `service.py` с `@register_service`, вызвать `discover()`, проверить что Registry заполнен.
4. В `Services/sql/service.py` создать `SqlService(name="sql")` shell-класс с `start/stop/get_status` + `@register_service`. **Не менять** `Services/sql/__init__.py` (не добавлять `SqlService` в публичный API если это нарушит контракт).
5. Аналогично для `Services/hikvision_camera/service.py` → `HikvisionCameraService(name="hikvision_camera")`.
6. Аналогично для `Services/auth/service.py` → `AuthService(name="auth")`.
7. В `Services/webcam_camera/service.py` добавить `@register_service` над классом `WebcamCameraService`. Тесты в `Services/webcam_camera/tests/` проверить — они не должны сломаться.

**Acceptance criteria:**
- [ ] `discover(Path("Services/"))` регистрирует ≥4 сервисов в `ServiceRegistry`
- [ ] `ServiceRegistry().list()` → список с именами `sql`, `hikvision_camera`, `auth`, `webcam_camera`
- [ ] Ошибка импорта в одном `service.py` не прерывает обход остальных
- [ ] `python -m pytest multiprocess_framework/modules/service_module/tests/test_scanner.py` — зелёные
- [ ] `python -m pytest Services/webcam_camera/tests/` — остаются зелёными (не сломали)

**Out of scope:** `Operation_crop` и `Region_processors` — они «library», не сервисы, `@register_service` не добавлять. AppContext не трогать (это Task 3.6).

**Edge cases:** директории без `service.py` — тихо пропустить; дубликат имени (два `service.py` с одинаковым `name`) → записать в `failed` с пояснением; `discover()` без аргументов → пустой `DiscoveryResult`.

**Dependencies:** Task 3.2

**Refs:** plans/prototype-skeleton-2026-05/phase-3-service-registry.md, plans/prototype-skeleton-2026-05/plan.md

**Module contract:** impl-only

**Status:** ✅ Done (commit d4eeb15)

---

### Task 3.4 — README.md + DECISIONS.md (локальный) для service_module

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Создать полный документационный обвес нового framework-модуля `service_module` — `README.md` и локальный `DECISIONS.md`, без которых модуль не считается завершённым по правилу «framework first».

**Context:** По правилу из `CLAUDE.md` (раздел «framework first»): каждый новый framework-модуль имеет `interfaces.py`, `README.md`, `STATUS.md`, `DECISIONS.md` и `tests/`. `STATUS.md` создаётся в Task 3.1. `README.md` создаётся по шаблону `multiprocess_framework/docs/MODULE_README_TEMPLATE.md`. Локальный `DECISIONS.md` фиксирует ключевые архитектурные решения Phase 3 на уровне `service_module` (singleton-паттерн, Protocol-vs-ABC выбор, scanner approach).

**Files:**
- `multiprocess_framework/modules/service_module/README.md` — создать по шаблону
- `multiprocess_framework/modules/service_module/DECISIONS.md` — создать (локальный ADR)

**Steps:**
1. Прочитать `multiprocess_framework/docs/MODULE_README_TEMPLATE.md` — взять структуру как основу.
2. В `README.md` описать: назначение модуля (ServiceRegistry для long-running объектов), публичный API (`IService`, `ServiceLifecycle`, `ServiceRegistry`, `register_service`, `scanner.discover`), пример регистрации сервиса через `@register_service`, пример discovery через `scanner.discover()`, ограничения (модуль не знает о конкретных Services/, не управляет жизненным циклом — только реестр).
3. В `DECISIONS.md` зафиксировать локальные решения:
   - `ADR-SM-001`: Singleton vs. глобальная переменная — выбрали metaclass singleton для thread-safety.
   - `ADR-SM-002`: Protocol vs ABC для `IService` — выбрали `@runtime_checkable Protocol` (structural subtyping, нет явного наследования).
   - `ADR-SM-003`: `ServiceRegistry` хранит классы (не экземпляры) — инстанцирование при вызове `start()` ответственность application-слоя.
4. Обновить `STATUS.md`: перевести из DRAFT в IN_PROGRESS (или актуальный статус по договорённости).

**Acceptance criteria:**
- [ ] `README.md` содержит секции: Назначение, Публичный API, Быстрый старт (код-пример), Ограничения
- [ ] `DECISIONS.md` содержит ≥3 ADR-SM-0NN записи с форматом: дата, статус, контекст, решение, причина
- [ ] Нет упоминаний конкретных `Services/sql`, `Services/auth` и т.п. в README (модуль generic)

**Out of scope:** глобальный ADR в `multiprocess_framework/DECISIONS.md` (Task 3.8). `scripts/sync` (Task 3.8).

**Edge cases:** нет

**Dependencies:** Tasks 3.1, 3.2

**Refs:** plans/prototype-skeleton-2026-05/phase-3-service-registry.md, plans/prototype-skeleton-2026-05/plan.md

**Module contract:** n/a (docs-only)

**Status:** ✅ Done (commit 6c40dd9)

---

### Task 3.5 — ServiceStateAdapter (двусторонняя sync ServiceRegistry ↔ state.services.*)

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Реализовать `ServiceStateAdapter` — адаптер, синхронизирующий состояние сервисов из `ServiceRegistry` в ветвь `state.services.*` и обратно, наследующий `StateAdapterBase`.

**Context:** Образец — `CameraStateAdapter` из `multiprocess_prototype/backend/state/adapters/camera_state_adapter.py`. `StateAdapterBase` находится в `multiprocess_framework/modules/state_store_module/adapters/base.py` и предоставляет: anti-loop через `_pending_paths`, bind/unbind/connect/disconnect lifecycle, шаблонные методы `_subscribe_all`/`_unsubscribe_all`. Пути в StateStore определены в `multiprocess_prototype/backend/state/schema.py`: `service_status_path(name)` → `"services.<name>.status"`, `service_config_path(name)` → `"services.<name>.config"`. Адаптер живёт в `multiprocess_prototype/backend/state/adapters/` (application-слой, не framework), т.к. он знает о конкретной схеме `state.services.*` Inspector-приложения. При вызове `start()` на сервисе через GUI → `ServiceRegistry` обновляет lifecycle → адаптер читает изменение → пишет в `state.services.<name>.status`.

**Files:**
- `multiprocess_prototype/backend/state/adapters/service_state_adapter.py` — создать
- `multiprocess_prototype/backend/state/adapters/tests/test_service_state_adapter.py` — создать (≥7 тестов)

**Steps:**
1. Создать `ServiceStateAdapter(StateAdapterBase)`.
2. Конструктор принимает `registry: ServiceRegistry`, `state_proxy: IStateProxy | None = None`, плюс стандартные `logger/stats/error`.
3. Реализовать `_subscribe_all()`: подписаться на `"services.*.*"` через `self._proxy.subscribe(pattern, callback=self._on_state_change)`, сохранить `sub_id` в `self._sub_ids`.
4. Реализовать `_unsubscribe_all()`: отписаться по всем `sub_id`.
5. Реализовать `sync_domain_to_state()`: для каждого `ServiceEntry` в `registry.list()` вызвать `self._proxy.set(service_status_path(entry.name), entry.lifecycle.value)`, используя anti-loop `_mark_pending`.
6. Реализовать `sync_state_to_domain()`: прочитать `self._proxy.get("services")` и обновить `lifecycle` в `ServiceRegistry` через `registry.get(name).lifecycle = ...`.
7. Реализовать `_on_state_change(delta)`: callback при изменении state → обновить lifecycle в registry (с `_check_and_clear_pending` для anti-loop).
8. Написать unit-тесты в `multiprocess_prototype/backend/state/adapters/tests/test_service_state_adapter.py` (или рядом): ≥7 тестов (bind/unbind, sync_domain_to_state записывает, anti-loop не циклит, callback обновляет registry).

**Acceptance criteria:**
- [ ] `adapter.sync_domain_to_state()` → в StateProxy появляются ключи `services.<name>.status` для всех сервисов из реестра
- [ ] Изменение `state.services.webcam_camera.status` из GUI → lifecycle в `ServiceRegistry` обновляется
- [ ] Anti-loop: адаптер не вызывает сам себя бесконечно при записи в state
- [ ] `python -m pytest` на тестах адаптера — зелёные

**Out of scope:** GUI-биндинг (Task 3.6/3.7). Bootstrap-интеграция в `multiprocess_prototype/main.py` (Task 3.6). Синхронизация config-ветви (только status в MVP).

**Edge cases:** registry пустой при `sync_domain_to_state()` — не падать; `proxy=None` при `sync_domain_to_state()` — логировать warning и возвращать.

**Dependencies:** Tasks 3.2, Task 3.1 (IStateAdapter через Phase 0 — уже готов)

**Refs:** plans/prototype-skeleton-2026-05/phase-3-service-registry.md, plans/prototype-skeleton-2026-05/plan.md

**Module contract:** impl-only

**Status:** ✅ Done (commit c3b6c89)

---

### Task 3.6 — ServicesTab: переключение на ServiceRegistry + подвкладка «Пути»

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Переключить `ServicesTab` с хардкода `SERVICE_PLUGINS` на динамическое `ServiceRegistry.list()` и добавить подвкладку «Пути» по образцу PluginsTab Phase 2.

**Context:** Текущий `ServicesPresenter` (в `multiprocess_prototype/frontend/widgets/tabs/services/presenter.py`) хардкодит 4 плагина через `SERVICE_PLUGINS` dict и обращается к `plugin_registry()` — это неправильно, сервисы должны браться из `ServiceRegistry`, а не `PluginRegistry`. `_sections.py` строит секции через `build_services_sections()` — нужно переписать под новый источник данных. Подвкладка «Пути» — точная копия паттерна `PathsSubtabWidget` из `multiprocess_prototype/frontend/widgets/tabs/plugins/paths_subtab.py`, только для директорий сервисов (`service_paths` вместо `plugin_paths`). `AppContext` нужно расширить методом `service_registry()` по аналогии с `plugin_registry()`. После этой задачи ServicesTab показывает сервисы из Registry, кнопки start/stop — всё ещё TODO (Task 3.7).

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/services/presenter.py` — переписать: убрать `SERVICE_PLUGINS`, добавить `list_services()` через `ServiceRegistry.list()`
- `multiprocess_prototype/frontend/widgets/tabs/services/_sections.py` — изменить: `build_services_sections()` через `presenter.list_services()` вместо `presenter.get_service_sections()`
- `multiprocess_prototype/frontend/widgets/tabs/services/paths_subtab.py` — создать: `ServicePathsSubtabWidget` (аналог `PathsSubtabWidget` для сервисов)
- `multiprocess_prototype/frontend/widgets/tabs/services/tab.py` — изменить: добавить секцию «Пути» в `build_services_sections`, добавить `refresh_catalog()` по сигналу от `paths_subtab`
- `multiprocess_prototype/frontend/app_context.py` — изменить: добавить `service_registry()` accessor
- `multiprocess_prototype/main.py` ИЛИ `multiprocess_prototype/frontend/app.py` — **bootstrap**: создать `ServiceRegistry()`, вызвать `discover(service_paths)`, положить в `AppContext.extras["service_registry"]`, создать и забиндить `ServiceStateAdapter`
- `multiprocess_prototype/frontend/widgets/tabs/services/tests/test_services_tab.py` — обновить тесты под новый API

**Steps:**
1. Добавить в `AppContext` метод `service_registry() -> ServiceRegistry | None` (по аналогии с `plugin_registry()`).
2. **Bootstrap в точке входа** (`main.py` или `app.py`, рядом с тем где сейчас инициализируется `PluginManager`): создать `registry = ServiceRegistry()`, прочитать `service_paths` из конфига (Phase 2 уже даёт `paths.service_paths`), вызвать `scanner.discover(*service_paths, registry=registry)`, положить в `app_context.extras["service_registry"] = registry`. Затем создать `adapter = ServiceStateAdapter(registry, state_proxy=...)`, `adapter.bind()`, `adapter.sync_domain_to_state()`. Сохранить ссылку на adapter (для unbind при shutdown).
3. Переписать `ServicesPresenter.list_services()`: обратиться к `ctx.service_registry().list()`, вернуть `list[tuple[str, str, ServiceLifecycle]]` — (name, title, lifecycle).
4. Обновить `_sections.py`: `_ServiceSection` теперь принимает `entry: ServiceEntry` вместо `plugin_name + fields`. Убрать `RegisterView` — вместо него простой `_ServiceInfoCard` (имя, статус из `entry.lifecycle`).
5. Создать `paths_subtab.py` с `ServicePathsSubtabWidget`: копия `PathsSubtabWidget`, заголовок «Директории сервисов», сигнал `catalog_updated`.
6. В `build_services_sections()` добавить секцию `__service_paths__` с `_ServicePathsSection` (аналог `_PathsSection` из plugins `_sections.py`).
7. Обновить тесты: mock `service_registry()` вместо `plugin_registry() + registers_manager()`.

**Acceptance criteria:**
- [ ] `ServicesTab` отображает сервисы из `ServiceRegistry.list()` (не хардкод)
- [ ] Подвкладка «Пути» присутствует в дереве навигации под ключом `__service_paths__`
- [ ] `ctx.service_registry()` возвращает registry из extras
- [ ] `python -m pytest multiprocess_prototype/frontend/widgets/tabs/services/tests/` — зелёные

**Out of scope:** реальный lifecycle start/stop из GUI (Task 3.7). Интеграция с state.services.* (Task 3.5 делает это на уровне backend). Подвкладка «Пути» — только UI, фактический rescan через scanner вызывается при клике «Рескан».

**Edge cases:** `service_registry()` → `None` (не инициализирован) → tab показывает пустой список без ошибок; `Operation_crop` и `Region_processors` появляться в ServicesTab не должны (они не регистрируются через `@register_service`).

**Dependencies:** Tasks 3.2, 3.3

**Refs:** plans/prototype-skeleton-2026-05/phase-3-service-registry.md, plans/prototype-skeleton-2026-05/plan.md

**Module contract:** public-api-change

**Status:** ✅ Done (commit 5dd5aa2)

---

### Task 3.7 — Action-кнопки start/stop/restart + биндинг статуса из state

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Подключить кнопки «Запустить / Остановить / Перезапуск» к реальным вызовам `ServiceRegistry.get(name).cls().start()/stop()` и отображать актуальный статус сервиса из `state.services.<name>.status`.

**Context:** Сейчас кнопки в `_ServiceSection._on_button_click()` показывают `QMessageBox` — заглушка. После Task 3.5 (`ServiceStateAdapter`) и Task 3.6 (`ServicesPresenter` + registry) у нас есть: (1) `ServiceRegistry` с классами сервисов; (2) `state.services.<name>.status` через `GuiStateProxy`; (3) `AppContext.bindings()` (GuiStateBindings) для реактивного обновления GUI. Нужно: при клике «Запустить» → инстанцировать сервис (или получить существующий экземпляр), вызвать `start({})` → `ServiceStateAdapter` обновит state → статус-лейбл обновится. Статус-лейбл обновляется через подписку на `bindings()` или напрямую через `GuiStateProxy.subscribe`. Паттерн «реактивный лейбл» есть в `ProcessesTab`.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/services/_sections.py` — изменить: `_ServiceSection._on_button_click()` → реальные start/stop/restart через presenter; добавить `_status_label` с подпиской на state
- `multiprocess_prototype/frontend/widgets/tabs/services/presenter.py` — изменить: добавить `start_service(name)`, `stop_service(name)`, `restart_service(name)` — делегируют в `ServiceRegistry` + вызывают `service.start({config})`

**Steps:**
1. В `ServicesPresenter` добавить: `_instances: dict[str, IService]` — кэш запущенных экземпляров (key = name). Методы `start_service(name: str) -> bool`, `stop_service(name: str) -> bool`, `restart_service(name: str) -> bool`.
2. `start_service`: взять `entry = registry.get(name)`, если `_instances.get(name)` нет → создать `entry.cls()`, вызвать `instance.start({})`, обновить `entry.lifecycle = ServiceLifecycle.RUNNING`, сохранить в `_instances`.
3. `stop_service`: взять из `_instances`, вызвать `instance.stop()`, обновить lifecycle → STOPPED.
4. В `_ServiceSection._build_buttons()` подключить реальные обработчики через `presenter.start_service(name)`, `stop_service`, `restart_service`.
5. В `_ServiceSection._build_widget()` добавить `_status_label = QLabel("stopped")`. Подписаться на `state.services.<name>.status` через `ctx.bindings()` или `ctx.extras.get("state_proxy")`. При изменении — обновить label.
6. Кнопка «Запустить» disabled когда lifecycle == RUNNING; «Остановить» disabled когда STOPPED. Состояние кнопок обновляется по тому же state-callback.

**Acceptance criteria:**
- [ ] Клик «Запустить» для `webcam_camera` → `WebcamCameraService.start({})` вызван, status-label меняется на "running"
- [ ] Клик «Остановить» → `stop()` вызван, label → "stopped"
- [ ] Кнопки disabled/enabled корректно по lifecycle-статусу
- [ ] Нет QMessageBox-заглушки при клике (убрать TODO)

**Out of scope:** persist конфига сервиса (start({}) без параметров в MVP). Реальный backend webcam с OpenCV (Phase 6). Биндинг через IPC/ProcessManager (сервисы запускаются в GUI-процессе в Phase 3 MVP).

**Edge cases:** `start_service()` выбрасывает исключение → label → "error", кнопки разблокированы для retry; `service_registry()` → None → кнопки disabled.

**Dependencies:** Tasks 3.5, 3.6

**Refs:** plans/prototype-skeleton-2026-05/phase-3-service-registry.md, plans/prototype-skeleton-2026-05/plan.md

**Module contract:** impl-only

**Status:** ✅ Done (commit TBD)

---

### Task 3.8 — ADR + scripts/sync (глобальный журнал DECISIONS.md)

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Добавить ADR-129 в `multiprocess_framework/DECISIONS.md` («ServiceRegistry: гибрид с PluginRegistry, lifecycle, scanner») и запустить `python -m scripts.sync` для обновления оглавления.

**Context:** По правилу проекта (CLAUDE.md п.3 + п.8): новый framework-модуль требует глобального ADR. Следующий свободный номер — ADR-129 (последний зафиксированный ADR-128 из grep по файлу). Формат ADR должен соответствовать шаблону из `DECISIONS.md` (см. строки 1-16 файла). После записи нужно запустить `python -m scripts.sync` (из корня проекта) для пересборки секции «Оглавление» — иначе CI поймает дрифт через `python scripts/validate.py`. Содержание ADR должно фиксировать: почему `ServiceRegistry` отдельно от `PluginRegistry` (разные lifecycle, сервисы не hot-reload), почему Protocol vs ABC, почему scanner через `importlib` а не через `__subclasses__`, границы слоя.

**Files:**
- `multiprocess_framework/DECISIONS.md` — добавить ADR-129 в конец секции «Принято»

**Steps:**
1. Открыть `multiprocess_framework/DECISIONS.md`, найти конец последнего ADR (ADR-128).
2. Добавить запись ADR-129 в формате: дата 2026-05-25, статус принято, контекст (Phase 3, нужен реестр long-running объектов), решение (singleton ServiceRegistry по образу PluginRegistry, IService Protocol, scanner.discover), причина (PluginRegistry не подходит — другой lifecycle, нет hot-reload для сервисов), отклонённые альтернативы (global dict — нет thread-safety; subclasses() — нет явной регистрации).
3. Добавить строку в оглавление в `DECISIONS.md` (секция `<!-- ADR-TOC:BEGIN … -->`) — или предоставить `scripts/sync` это сделать.
4. Запустить `python -m scripts.sync` из корня проекта (или указать Developer'у точную команду).
5. Запустить `python scripts/validate.py` для проверки что нет дрифта.

**Acceptance criteria:**
- [ ] ADR-129 присутствует в `multiprocess_framework/DECISIONS.md` в секции «Принято»
- [ ] `python scripts/validate.py` → 0 ошибок (нет дрифта оглавления)
- [ ] ADR-129 упомянут в оглавлении (секция `<!-- ADR-TOC:BEGIN -->`)
- [ ] Коммит содержит `docs(decisions): add ADR-129 ServiceRegistry` с `Layer: framework`

**Out of scope:** Локальный `service_module/DECISIONS.md` (Task 3.4). Изменения в других модулях.

**Edge cases:** `scripts/sync` может потребовать запуска из корня (не из подпапки). Если `validate.py` показывает ошибки не связанные с ADR-129 — не чинить их в этой задаче (scope cut).

**Dependencies:** Tasks 3.1, 3.2, 3.4 (должны быть завершены, чтобы корректно описать решения)

**Refs:** plans/prototype-skeleton-2026-05/phase-3-service-registry.md, plans/prototype-skeleton-2026-05/plan.md

**Module contract:** n/a

**Status:** ⏳ Todo

---

## Порядок выполнения задач

```
3.1 (interfaces)
    └── 3.2 (registry)
            ├── 3.3 (scanner + регистрация Services/)
            │       └── 3.6 (ServicesTab switch to registry + Paths subtab)
            │               └── 3.7 (start/stop buttons + state binding)
            └── 3.4 (README.md + локальный DECISIONS.md)  ← параллельно с 3.3
            └── 3.5 (ServiceStateAdapter)  ← параллельно с 3.3, нужен для 3.7
3.8 (ADR-129 + sync)  ← после 3.1, 3.2, 3.4; можно параллельно с 3.5/3.6/3.7
```

Критический путь: **3.1 → 3.2 → 3.3 → 3.6 → 3.7** (5 задач последовательно).
Параллельно с критическим путём: **3.4** (после 3.2), **3.5** (после 3.2), **3.8** (после 3.4).
