# Phase 4 — Декомпозиция: DisplayRegistry + DisplaysTab

> **Мастер-план**: [plan.md](plan.md)
> **Спецификация фазы**: [phase-4-displays-tab.md](phase-4-displays-tab.md)
> **Ветка**: `feat/displays-tab`
> **Дата**: 2026-05-25
> **Статус**: DRAFT

---

## Порядок выполнения

```
Task 4.1 (interfaces)
    └─→ Task 4.2 (registry)
            ├─→ Task 4.3 (blueprint integration + SHM lifecycle)
            └─→ Task 4.5 (state adapter + bootstrap)
                    └─→ Task 4.6 (tab MVP)
                            └─→ Task 4.7 (preview window)
Task 4.4 (displays.yaml + loader) ──→ Task 4.2 (зависит по персист)
Task 4.8 (тесты) ──────────────── зависит от 4.1–4.7
Task 4.9 (документация + ADR) ──── зависит от 4.1–4.3
```

---

### Task 4.1 — Интерфейсы display_module: Protocol + DisplayEntry

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Создать `display_module/interfaces.py` с Protocol-контрактами `IDisplayRegistry`, `IDisplayChannel` и dataclass `DisplayEntry`.
**Context:** Первый шаг по принципу «framework first» — определить публичный контракт нового модуля до написания реализации. Все остальные задачи фазы зависят от этих типов. Образец — `service_module/interfaces.py`.

**Files:**
- `multiprocess_framework/modules/display_module/__init__.py` — создать (пустой, заполнить после 4.2)
- `multiprocess_framework/modules/display_module/interfaces.py` — создать

**Steps:**
1. Создать директорию `multiprocess_framework/modules/display_module/` со скелетом `__init__.py`.
2. Определить `DisplayEntry` — dataclass с полями:
   - `id: str` — уникальный идентификатор дисплея (ключ в реестре и в YAML)
   - `name: str` — человекочитаемое имя
   - `width: int` — ширина кадра в пикселях
   - `height: int` — высота кадра в пикселях
   - `format: str` — формат кадра (например `"BGR"`, `"GRAY"`, `"RGBA"`)
   - `fps_limit: float` — ограничение частоты кадров (0.0 = без ограничения)
   - `ring_buffer_blocks: int` — количество SHM-блоков в ring-buffer для канала
   - Поля vision-специфичной семантики (`element_shape`, `dtype`) **НЕ** включать — они в prototype-обёртке.
3. Определить `@runtime_checkable class IDisplayChannel(Protocol)` с методами:
   - `channel_key: str` (свойство) — ключ маршрута в RouterManager (например `"display.<display_id>"`)
   - `subscribe(consumer_id: str) -> bool`
   - `unsubscribe(consumer_id: str) -> bool`
   - `is_active() -> bool`
4. Определить `@runtime_checkable class IDisplayRegistry(Protocol)` с методами:
   - `register(entry: DisplayEntry) -> None`
   - `unregister(display_id: str) -> bool` — возвращает `True` если удалён
   - `get(display_id: str) -> DisplayEntry | None`
   - `list() -> list[DisplayEntry]`
   - `persist() -> None` — сохранить текущее состояние реестра (путь к файлу — в реализации)
5. Строго соблюдать правило слоёв: **НИКАКИХ** импортов из `Services/`, `Plugins/`, `multiprocess_prototype/` — только stdlib и `__future__`.
6. Добавить docstring-секцию «ADR-решение по семантике»: image-specific поля (`element_shape`, `dtype`) намеренно вынесены за пределы framework-контракта — находятся в prototype-обёртке.

**Acceptance criteria:**
- [ ] `from multiprocess_framework.modules.display_module.interfaces import DisplayEntry, IDisplayChannel, IDisplayRegistry` — без ошибок
- [ ] `isinstance(obj, IDisplayRegistry)` работает через structural subtyping (runtime_checkable)
- [ ] `DisplayEntry(id="main", name="Main", width=1280, height=720, format="BGR", fps_limit=30.0, ring_buffer_blocks=3)` — конструируется без ошибок
- [ ] `ruff check` — нет нарушений
- [ ] Нет импортов из layers выше framework

**Out of scope:** Реализация реестра (registry.py) — это Task 4.2. Тесты Protocol — Task 4.8.

**Refs trailer:** `Refs: plans/prototype-skeleton-2026-05/phase-4-displays-tab.md, plans/prototype-skeleton-2026-05/plan.md`
**Status:** [DONE 8a58221b]

---

### Task 4.2 — DisplayRegistry: реализация реестра

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Реализовать `DisplayRegistry` — thread-safe singleton-реестр дисплеев с CRUD-операциями и persist-в-YAML.
**Context:** Центральное доменное хранилище дисплеев в framework. Образец реализации — `service_module/registry.py` (singleton через `__new__`, threading.Lock, `ServiceEntry`). Важно: при `unregister` нужно сделать cleanup broadcast-маршрута — это ключевой риск SHM lifecycle.

**Files:**
- `multiprocess_framework/modules/display_module/registry.py` — создать
- `multiprocess_framework/modules/display_module/__init__.py` — дополнить публичным API

**Steps:**
1. Реализовать `DisplayRegistry` по паттерну singleton из `ServiceRegistry`:
   - `__new__` с double-checked locking через `threading.Lock`
   - внутренний `_registry: dict[str, DisplayEntry]` под `self._lock`
2. Реализовать `register(entry: DisplayEntry) -> None`:
   - проверка дубликата по `entry.id` → `ValueError` если уже есть
   - под lock записывает в `_registry`
3. Реализовать `unregister(display_id: str) -> bool`:
   - под lock удаляет из `_registry`
   - если удалён — вызывает `_cleanup_shm_channel(display_id)` (приватный метод)
   - `_cleanup_shm_channel` принимает `display_id: str` и **логирует предупреждение** о необходимости остановить SHM-канал перед следующим стартом процессов; фактическое освобождение SHM делается в prototype-слое при старте/остановке (см. ADR-025). Метод не должен импортировать router или SHM напрямую.
   - возвращает `True` если удалён, `False` если не найден
4. Реализовать `get(display_id: str) -> DisplayEntry | None` (под lock).
5. Реализовать `list() -> list[DisplayEntry]` (копия, под lock).
6. Реализовать `persist(path: Path) -> None`:
   - Сериализует список `DisplayEntry` в YAML-формат через `yaml.safe_dump`
   - Принимает `path: Path` явным аргументом (не хранить путь внутри singleton, т.к. prototype решает где хранить)
   - При ошибке записи — логирует ошибку через internal `_log_error` (паттерн logger-fallback как в StateAdapterBase: если `_logger` не передан — silent)
7. Реализовать `load(path: Path) -> None`:
   - Читает YAML, десериализует в список `DisplayEntry`, заменяет содержимое реестра
   - При отсутствии файла — тихо игнорирует (файл создаётся при первом `persist`)
   - При ошибке парсинга — логирует ошибку, реестр остаётся без изменений
8. Реализовать декоратор `register_display` по образцу `register_service` — опционально (только если нужен паттерн declarative registration; если не нужен — пропустить).
9. Добавить `clear() -> None` для изоляции тестов.
10. Обновить `display_module/__init__.py` — реэкспортировать `DisplayEntry`, `DisplayRegistry`.

**Acceptance criteria:**
- [ ] `DisplayRegistry()` возвращает тот же instance при повторном вызове
- [ ] `register` → `get` → `list` работают корректно
- [ ] `unregister` несуществующего id → `False` (не исключение)
- [ ] `persist(path)` создаёт YAML с полями DisplayEntry
- [ ] `load(несуществующий_файл)` — не вызывает исключений
- [ ] `load(path)` после `persist(path)` — восстанавливает реестр идентично
- [ ] Thread-safety: 10 параллельных `register`/`list` — нет race condition
- [ ] `ruff check` — нет нарушений
- [ ] Нет импортов из `multiprocess_prototype/` или `Services/`

**Out of scope:** Запись в blueprint memory (Task 4.3). Создание SHM-сегмента (делается процессами при старте, не реестром). Тесты — Task 4.8.

**Edge cases:**
- `persist` при пустом реестре — создаёт пустой файл
- `load` с повреждённым YAML — логирует ошибку, реестр без изменений (не crash)
- `unregister` уже удалённого id — `False`, не исключение

**Dependencies:** Task 4.1 (DisplayEntry, IDisplayRegistry)

**Refs trailer:** `Refs: plans/prototype-skeleton-2026-05/phase-4-displays-tab.md, plans/prototype-skeleton-2026-05/plan.md`
**Status:** [DONE 2ae2de87]

---

### Task 4.3 — Blueprint integration: blueprint memory при регистрации дисплея

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** Интегрировать `DisplayRegistry.register` с ADR-025 config-driven memory — при добавлении дисплея автоматически записывать `ui_process.memory["display_<id>"]` в SystemBlueprint.
**Context:** По ADR-025 (`shared_resources_module`) SHM-сегменты объявляются в blueprint как секция `memory`. `ui_process.memory["display_main"] = {"blocks": 3, "frame_shape": [720, 1280, 3]}`. Это не дублирование данных — это единственный механизм, по которому `SharedResourcesManager` создаёт SHM-сегмент при старте. Задача сложная архитектурно: нужно найти правильный слой для этой связи, не нарушая «framework first» и не создавая лишнюю связность.

**Files:**
- `multiprocess_prototype/backend/displays/` — создать пакет
- `multiprocess_prototype/backend/displays/__init__.py` — создать
- `multiprocess_prototype/backend/displays/blueprint_binding.py` — создать

**Steps:**
1. Изучить `shared_resources_module/` — найти где и как blueprint memory объявляется для других сегментов (например, camera ring_buffer). Убедиться в структуре поля `memory` в SystemBlueprint.
2. Реализовать функцию `bind_displays_to_blueprint(registry: DisplayRegistry, blueprint: dict) -> dict` в `blueprint_binding.py`:
   - Принимает `registry` и blueprint dict (результат `SystemBlueprint.model_dump()` или raw dict).
   - Для каждого `DisplayEntry` из `registry.list()` добавляет в `blueprint["processes"]["ui_process"]["memory"]` запись `"display_<entry.id>"` со структурой:
     ```python
     {
         "blocks": entry.ring_buffer_blocks,
         "frame_shape": [entry.height, entry.width, _format_to_channels(entry.format)]
     }
     ```
   - Вспомогательная функция `_format_to_channels(fmt: str) -> int`: `"BGR"/"RGB"` → 3, `"GRAY"` → 1, `"RGBA"` → 4, иначе → 3 (с логированием предупреждения).
   - Возвращает изменённый blueprint dict (не мутирует аргумент — возвращает копию).
3. Обработать случай, когда `blueprint["processes"]["ui_process"]` отсутствует: добавить секцию с минимальной структурой + лог-предупреждение.
4. Реализовать функцию `cleanup_display_from_blueprint(display_id: str, blueprint: dict) -> dict`:
   - Удаляет `blueprint["processes"]["ui_process"]["memory"]["display_<display_id>"]` если существует.
   - Возвращает изменённый blueprint dict (не мутирует аргумент).
   - Если ключа нет — тихо возвращает blueprint без изменений.
5. Обе функции должны быть чистыми (pure functions по смыслу), без side-effects помимо возврата результата.
6. В docstring: явно указать, что фактическое создание SHM-сегмента происходит при следующем запуске `ProcessManagerProcess` — эти функции только формируют описание.

**Acceptance criteria:**
- [ ] `bind_displays_to_blueprint(registry, {})` с двумя дисплеями → blueprint содержит оба ключа `"display_main"` и `"display_debug"` с корректными `blocks` и `frame_shape`
- [ ] `"GRAY"` → `frame_shape[-1] == 1`, `"BGR"` → `frame_shape[-1] == 3`, `"RGBA"` → `frame_shape[-1] == 4`
- [ ] `cleanup_display_from_blueprint("main", blueprint)` → ключ `"display_main"` исчез
- [ ] `cleanup_display_from_blueprint` несуществующего id → blueprint без изменений, нет исключений
- [ ] Аргументные dict не мутируются (проверить через `id()` или сравнение до/после)
- [ ] Нет импортов из `multiprocess_framework/` кроме `display_module` и `shared_resources_module`

**Out of scope:** Перезапись blueprint в файл (делается выше, в application bootstrap). Интеграция с ProcessManagerProcess — Phase 5. Тесты — Task 4.8.

**Edge cases:**
- Дисплей с неизвестным `format` → `channels=3` + предупреждение в лог
- Пустой `registry.list()` → blueprint без изменений (не добавлять пустую секцию)
- `"ui_process"` не найден в blueprint → создать минимальную запись

**Dependencies:** Task 4.1 (DisplayEntry), Task 4.2 (DisplayRegistry)

**Refs trailer:** `Refs: plans/prototype-skeleton-2026-05/phase-4-displays-tab.md, plans/prototype-skeleton-2026-05/plan.md`
**Status:** [DONE cfcaa48f]

---

### Task 4.4 — displays.yaml + загрузчик конфигурации

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Создать `displays.yaml` — application-специфичный конфиг дисплеев и `DisplaysConfig` — Pydantic-схему для его загрузки и валидации.
**Context:** По правилу «application-specific config в prototype». Формат YAML должен совпадать с тем, что `DisplayRegistry.persist()` генерирует, чтобы bootstrap мог загружать файл через `registry.load()`. Pydantic-схема — только внутри процесса (правило Dict at Boundary).

**Files:**
- `multiprocess_prototype/backend/config/displays.yaml` — создать (с двумя дефолтными дисплеями)
- `multiprocess_prototype/backend/config/schemas.py` — добавить `DisplayEntrySchema` и `DisplaysConfig`

**Steps:**
1. Создать `multiprocess_prototype/backend/config/displays.yaml` с содержимым:
   ```yaml
   # Реестр дисплеев Inspector — создаётся и обновляется через DisplayRegistry
   # Автогенерируется DisplayRegistry.persist() при CRUD-операциях из GUI
   displays:
     - id: main
       name: Основной дисплей
       width: 1280
       height: 720
       format: BGR
       fps_limit: 30.0
       ring_buffer_blocks: 3
     - id: debug
       name: Debug дисплей
       width: 640
       height: 480
       format: BGR
       fps_limit: 15.0
       ring_buffer_blocks: 2
   ```
2. Открыть `multiprocess_prototype/backend/config/schemas.py`, прочитать существующие схемы. Добавить в конец:
   - `class DisplayEntrySchema(BaseModel)` — поля соответствуют `DisplayEntry` (id, name, width, height, format, fps_limit, ring_buffer_blocks) с валидаторами:
     - `width` и `height` — Annotated[int, Field(gt=0, le=7680)]
     - `fps_limit` — Annotated[float, Field(ge=0.0, le=240.0)]
     - `ring_buffer_blocks` — Annotated[int, Field(ge=1, le=32)]
     - `format` — Literal["BGR", "RGB", "GRAY", "RGBA"]
   - `class DisplaysConfig(BaseModel)` — поле `displays: list[DisplayEntrySchema] = []`
3. Реализовать функцию `load_displays_config(path: Path) -> DisplaysConfig` в том же файле или в отдельном `displays_loader.py` (решить по месту, предпочтительно рядом с другими загрузчиками):
   - Читает YAML через `yaml.safe_load`
   - Валидирует через `DisplaysConfig.model_validate(raw_dict)`
   - При `ValidationError` — логирует ошибку, возвращает `DisplaysConfig()` (пустой)
   - При отсутствии файла — возвращает `DisplaysConfig()` (пустой, не исключение)
4. Реализовать функцию `displays_config_to_registry(config: DisplaysConfig, registry: DisplayRegistry) -> None`:
   - Для каждого `DisplayEntrySchema` в `config.displays` конвертирует в `DisplayEntry` и вызывает `registry.register(entry)`
   - Пропускает дубликаты (перехватывает `ValueError` от `register` — тихо логирует)

**Acceptance criteria:**
- [x] `DisplaysConfig.model_validate({"displays": [{"id": "main", "name": "Main", ...}]})` — без ошибок
- [x] `DisplayEntrySchema` отклоняет `width=0` или `fps_limit=-1`
- [x] `load_displays_config(несуществующий_путь)` → `DisplaysConfig()` без исключений
- [x] `displays.yaml` проходит `load_displays_config(Path("multiprocess_prototype/backend/config/displays.yaml"))` без ValidationError
- [x] `ruff check` — нет нарушений
- [x] Нет импортов из `multiprocess_framework/modules/display_module/` в схемах (схема — это dict-уровень, без зависимости от framework)

**Out of scope:** Запись в YAML через схему — `persist()` делает registry напрямую. GUI для редактирования — Task 4.6. Тесты — Task 4.8.

**Dependencies:** Task 4.2 (DisplayRegistry для `displays_config_to_registry`)

**Refs trailer:** `Refs: plans/prototype-skeleton-2026-05/phase-4-displays-tab.md, plans/prototype-skeleton-2026-05/plan.md`
**Status:** [DONE 011cda67]

---

### Task 4.5 — DisplayStateAdapter + расширение bootstrap

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать `DisplayStateAdapter` — двусторонняя синхронизация `DisplayRegistry ↔ state.displays.*`, расширить `bootstrap.py` для наполнения ветки `displays` из `displays.yaml`.
**Context:** Паттерн один в один с `ServiceStateAdapter` (Task 3.5 Phase 3). `STATE_DISPLAYS` уже объявлен в `schema.py`, путь-хелперы `display_status_path` / `display_config_path` уже готовы. В `bootstrap.py` уже есть заглушка `STATE_DISPLAYS: {}` — нужно наполнить реальными данными.

**Files:**
- `multiprocess_prototype/backend/state/adapters/display_state_adapter.py` — создать
- `multiprocess_prototype/backend/state/adapters/__init__.py` — добавить реэкспорт
- `multiprocess_prototype/backend/state/bootstrap.py` — расширить `build_initial_state`
- `multiprocess_prototype/backend/state/schema.py` — добавить `display_entry_path` хелпер (если нужен)

**Steps:**
1. Создать `display_state_adapter.py` по образцу `service_state_adapter.py`:
   - `class DisplayStateAdapter(StateAdapterBase)` с `__init__(self, registry: DisplayRegistry, state_proxy=None, logger=None, stats=None, error=None)`
   - `_subscribe_all()` — подписка на `"displays.*.status"` через `self._proxy.subscribe("displays.*.status", self._on_state_deltas)`
   - `_unsubscribe_all()` — отписка от всех `self._sub_ids`
   - `sync_domain_to_state()` — для каждого `entry` в `registry.list()`:
     - пишет `displays.<id>.status` = `"registered"` (дисплей зарегистрирован, SHM ещё не открыт)
     - пишет `displays.<id>.config` = `entry.__dict__` (сериализованная конфигурация)
     - anti-loop: `_mark_pending` перед каждым `set()`
   - `sync_state_to_domain()` — читает `state.displays.*` и синхронизирует статусы обратно в registry (если нужно). Для Phase 4 достаточно no-op или минимальной реализации (registry не хранит статус, только конфигурацию).
   - `_on_state_deltas(deltas)` — разбирает `displays.*.status`, обновляет registry или просто логирует (в Phase 4 можно логировать без действия, полная логика в Phase 5).
2. Расширить `build_initial_state()` в `bootstrap.py`:
   - Добавить параметр `displays_config: DisplaysConfig | None = None` (опциональный, обратная совместимость).
   - Если `displays_config` передан: для каждого `DisplayEntrySchema` в `displays_config.displays` добавить в словарь `displays` запись `{entry.id: {"status": "registered", "config": entry.model_dump()}}`.
   - Если не передан: `STATE_DISPLAYS` остаётся `{}` (как раньше).
3. Добавить реэкспорт в `adapters/__init__.py`.
4. **Не** трогать существующую логику `build_initial_state` — только добавить ветку для displays.

**Acceptance criteria:**
- [ ] `DisplayStateAdapter(registry=DisplayRegistry())` — конструируется без ошибок
- [ ] `isinstance(adapter, IStateAdapter)` → `True`
- [ ] `adapter.bind(proxy); adapter.connect()` — создаёт подписку на `displays.*.status`
- [ ] `adapter.sync_domain_to_state()` с 2 дисплеями в registry → `proxy.set` вызывается 4 раза (2 × status + 2 × config)
- [ ] `build_initial_state({}, {})` — без изменений (обратная совместимость)
- [ ] `build_initial_state({}, {}, displays_config=cfg)` с 2 дисплеями → `state["displays"]` содержит 2 ключа
- [ ] `ruff check` — нет нарушений
- [ ] Тест из `test_bootstrap.py` существующий — не сломан

**Out of scope:** Полная двусторонняя синхронизация (Phase 5 уточнит семантику). PreviewWindow subscribe — Task 4.7. Тесты — Task 4.8.

**Edge cases:**
- Anti-loop: `sync_domain_to_state` не должна вызывать рекурсивный `_on_state_deltas`
- `registry` пустой → `sync_domain_to_state` делает 0 вызовов `set()`

**Dependencies:** Task 4.1, Task 4.2, Task 4.4 (DisplaysConfig)

**Refs trailer:** `Refs: plans/prototype-skeleton-2026-05/phase-4-displays-tab.md, plans/prototype-skeleton-2026-05/plan.md`
**Status:** [PENDING]

---

### Task 4.6 — DisplaysTab v2: полное переписывание (MVP pattern)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Переписать `tabs/displays/tab.py` и `presenter.py` под CRUD-паттерн DisplayRegistry (список дисплеев → форма → кнопки: Создать/Удалить/Дублировать/Открыть превью) с полным MVP (presenter + view Protocol).
**Context:** Текущий `DisplaysTab` — слотовые пресеты без persistence, полностью устаревший. По `feedback_mvp_pattern` все новые GUI-вкладки требуют full MVP: отдельный `IDisplaysView` Protocol + `DisplaysPresenter` с бизнес-логикой, `DisplaysTab` только реализует Protocol. Образец — `tabs/services/`.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/displays/tab.py` — полностью переписать
- `multiprocess_prototype/frontend/widgets/tabs/displays/presenter.py` — полностью переписать
- `multiprocess_prototype/frontend/widgets/tabs/displays/__init__.py` — обновить реэкспорты

**Steps:**
1. Определить `IDisplaysView(Protocol)` в начале `tab.py` или в отдельном `view.py`:
   ```python
   class IDisplaysView(Protocol):
       def refresh_list(self, entries: list[DisplayEntry]) -> None: ...
       def show_entry(self, entry: DisplayEntry | None) -> None: ...
       def set_buttons_state(self, has_selection: bool) -> None: ...
       def get_form_data(self) -> dict: ...
       def show_error(self, message: str) -> None: ...
   ```
2. Переписать `DisplaysPresenter`:
   - `__init__(self, registry: DisplayRegistry, view: IDisplaysView, yaml_path: Path)`
   - `load()` — загружает дисплеи из registry, вызывает `view.refresh_list()`
   - `on_select(display_id: str | None)` — вызывает `view.show_entry(registry.get(id))`
   - `on_create()` — читает `view.get_form_data()`, создаёт `DisplayEntry`, вызывает `registry.register()`, `registry.persist(yaml_path)`, `view.refresh_list()`
   - `on_delete(display_id: str)` — `registry.unregister(id)`, `registry.persist(yaml_path)`, `view.refresh_list()`
   - `on_duplicate(display_id: str)` — копирует entry с новым `id = f"{id}_copy"`, регистрирует, persist, refresh
   - `on_open_preview(display_id: str)` — эмитит сигнал или вызывает callback для открытия `PreviewWindow` (не создаёт окно напрямую — это view-ответственность). В Phase 4 достаточно `logger.info("Открыть превью %s", display_id)` + callback.
   - При `ValueError` от `registry.register()` → `view.show_error(str(e))`
3. Переписать `DisplaysTab(BaseListNavTab)` — реализует `IDisplaysView`:
   - Левый nav-список: имена дисплеев (через `add_item(entry.id, entry.name)`)
   - Правая панель (form): поля `QLineEdit` для name, `QSpinBox` для width/height/ring_buffer_blocks, `QDoubleSpinBox` для fps_limit, `QComboBox` для format (BGR/RGB/GRAY/RGBA)
   - Поле `id` — `QLineEdit`, только при создании нового (при выборе существующего — read-only)
   - Кнопки в action-колонке: «Создать», «Удалить» (disabled без выбора), «Дублировать» (disabled без выбора), «Открыть превью» (disabled без выбора)
   - `get_form_data()` — собирает dict из полей формы
   - `show_entry(entry)` — заполняет поля формы из entry (или очищает при `None`)
   - `refresh_list(entries)` — перестраивает nav-список через `add_item`
   - `show_error(message)` — `QMessageBox.warning(self, "Ошибка", message)`
4. Удалить весь legacy-код пресетов (`DISPLAY_PRESETS`, slot-логику) — он полностью заменяется.
5. Сохранить `create(ctx)` фабричный метод — `TabFactory` его использует.
6. Permission gating через `install_permission_aware_enable` на кнопках мутации (как в текущем `tab.py`).

**Acceptance criteria:**
- [ ] `DisplaysTab.create(ctx)` — без ошибок при MagicMock ctx (ctx.display_registry = MagicMock DisplayRegistry)
- [ ] `isinstance(DisplaysTab(...), IDisplaysView)` → `True`
- [ ] Нажатие «Создать» с валидными данными → `registry.register()` вызван, `refresh_list()` вызван
- [ ] Нажатие «Удалить» → `registry.unregister()` вызван, `refresh_list()` вызван
- [ ] Нажатие «Дублировать» → в registry появился entry с суффиксом `_copy`
- [ ] «Удалить» и «Дублировать» disabled при пустом выборе
- [ ] `show_error()` → `QMessageBox` появляется (в тесте — mock)
- [ ] `ruff check` — нет нарушений
- [ ] Легаси-тест `test_displays_tab.py` (старые пресеты) — **удалён** или переписан под новый API

**Out of scope:** `PreviewWindow` создание — Task 4.7. Layout-compositor (1x1/2x2 в одно окно) — вне Phase 4. Тесты — Task 4.8.

**Edge cases:**
- Попытка создать дисплей с дублирующимся id → `show_error`
- Форма с пустым id → `show_error`
- `on_duplicate` с id, у которого уже есть `_copy` суффикс → добавить `_copy2` или аналогично

**Dependencies:** Task 4.1 (DisplayEntry), Task 4.2 (DisplayRegistry), Task 4.4 (yaml_path)

**Refs trailer:** `Refs: plans/prototype-skeleton-2026-05/phase-4-displays-tab.md, plans/prototype-skeleton-2026-05/plan.md`
**Status:** [PENDING]

---

### Task 4.7 — PreviewWindow: окно превью SHM-канала

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** Реализовать `PreviewWindow` — автономное QWidget-окно с `QLabel` для отображения кадров из SHM-канала, подписанное на RouterManager broadcast через frame_route утилиту.
**Context:** Сложная задача: нужно связать Qt main thread (QLabel.setPixmap) с поступающими кадрами из SHM, которые приходят через IPC-callback из RouterManager. Неправильный threading → freeze GUI. Образец подписки — `frame_router_setup.py` из backup (функции `subscribe_to_camera`/`unsubscribe_from_camera` через `RouterManager.register_broadcast_route`). PreviewWindow должна быть самодостаточной: создаётся, открывается, при закрытии — отписывается.

**Files:**
- `multiprocess_prototype/frontend/widgets/displays/` — создать пакет
- `multiprocess_prototype/frontend/widgets/displays/__init__.py` — создать
- `multiprocess_prototype/frontend/widgets/displays/preview_window.py` — создать

**Steps:**
1. Создать `PreviewWindow(QWidget)`:
   - Конструктор: `__init__(self, display_entry: DisplayEntry, router_manager: RouterManager | None = None, parent: QWidget | None = None)`
   - Заголовок окна: `f"Превью: {display_entry.name}"` (включая id в скобках)
   - Минимальный размер: `display_entry.width × display_entry.height` (или `640x480` если <= 0)
   - Флаги окна: `Qt.Window` (автономное окно, не дочернее)
2. Layout: `QVBoxLayout` → `QLabel` (центрированный, масштабируемый через `setScaledContents(True)`) → статус-строка `QLabel` (пустая пока нет кадров).
3. Состояния:
   - «Ожидание» (по умолчанию): серый placeholder `"Ожидание кадров..."` в label
   - «Активно»: QPixmap из последнего кадра
   - «Отключено»: серый placeholder `"Канал отключён"`
4. Метод `subscribe(router_manager: RouterManager)`:
   - Вычисляет `channel_key = f"display.{display_entry.id}"` — ключ маршрута в RouterManager
   - Вызывает `router_manager.register_broadcast_route(channel_key, [self._channel_name])` где `_channel_name = f"preview_{display_entry.id}_{id(self)}"`
   - Сохраняет ссылку на `router_manager` для отписки в `closeEvent`
5. Метод `_on_frame_received(frame_data: dict)` — callback при получении кадра:
   - **КРИТИЧНО**: НЕ вызывать Qt UI-методы напрямую из callback — использовать `QMetaObject.invokeMethod` или сигнал `_frame_signal = Signal(object)` → подключить к `_update_frame_slot`
   - `_update_frame_slot(frame_data: dict)` — запускается в main thread:
     - Читает массив из frame_data (ключ `"frame"` или `"data"` — уточнить по реальному IPC-формату)
     - Конвертирует numpy array → QImage → QPixmap (через `QImage.Format_BGR888` или `Format_Grayscale8` в зависимости от `display_entry.format`)
     - `self._label.setPixmap(pixmap)`
6. `closeEvent(event)`:
   - Вызывает `unsubscribe()` — убирает broadcast-маршрут
   - `super().closeEvent(event)`
7. Метод `unsubscribe()`:
   - Если `router_manager` сохранён — вызывает логику отписки (убирает `_channel_name` из broadcast subscribers для `channel_key`)
   - Логирует отписку
8. Статический метод `open_for_display(display_entry: DisplayEntry, router_manager: RouterManager | None, parent: QWidget | None = None) -> "PreviewWindow"`:
   - Фабрика: создаёт окно, вызывает `subscribe` если `router_manager` не None, показывает `show()`, возвращает экземпляр.
9. В docstring: явно указать, что пока никто не пишет в SHM-канал — окно показывает placeholder (это ожидаемое поведение Phase 4; реальные кадры — Phase 7).

**Acceptance criteria:**
- [ ] `PreviewWindow(entry)` — конструируется без ошибок без router_manager
- [ ] `preview.show()` — окно открывается с placeholder
- [ ] `preview.close()` — `closeEvent` вызван, `unsubscribe()` — без исключений
- [ ] `_update_frame_slot` вызывается в main thread (Signal-Slot механизм, не прямой callback)
- [ ] `open_for_display(entry, None)` → окно видно в qtbot
- [ ] При конвертации BGR numpy array 720×1280×3 → QPixmap — нет исключений
- [ ] `ruff check` — нет нарушений

**Out of scope:** Фактическое получение кадров из SHM (пишет Phase 7). Layout-compositor (несколько дисплеев в одно окно) — отложен. Тесты live-frame — Task 4.8 (stub-режим).

**Edge cases:**
- `router_manager=None` → subscribe/unsubscribe ничего не делают (graceful degradation)
- Frame с некорректными размерами → логировать ошибку, показать placeholder
- Множественные `close` → `unsubscribe` вызывается только один раз (guard `_subscribed: bool`)

**Dependencies:** Task 4.1 (DisplayEntry), Task 4.2 (DisplayRegistry), Task 4.6 (вызывается из presenter)

**Refs trailer:** `Refs: plans/prototype-skeleton-2026-05/phase-4-displays-tab.md, plans/prototype-skeleton-2026-05/plan.md`
**Status:** [PENDING]

---

### Task 4.8 — Unit-тесты Phase 4 (20-25 тестов)

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Написать 20-25 unit-тестов покрывающих `DisplayRegistry`, `DisplayStateAdapter`, `blueprint_binding` и `PreviewWindow` stub.
**Context:** По стандарту проекта все новые модули фреймворка обязаны иметь `tests/` с покрытием публичного API. Образец — `service_module/tests/test_registry.py` и `backend/state/adapters/tests/test_service_state_adapter.py`.

**Files:**
- `multiprocess_framework/modules/display_module/tests/__init__.py` — создать
- `multiprocess_framework/modules/display_module/tests/test_registry.py` — создать
- `multiprocess_prototype/backend/state/adapters/tests/test_display_state_adapter.py` — создать
- `multiprocess_prototype/backend/displays/tests/__init__.py` — создать
- `multiprocess_prototype/backend/displays/tests/test_blueprint_binding.py` — создать
- `multiprocess_prototype/frontend/widgets/displays/tests/__init__.py` — создать
- `multiprocess_prototype/frontend/widgets/displays/tests/test_preview_window.py` — создать
- `multiprocess_prototype/frontend/widgets/tabs/displays/tests/test_displays_tab.py` — переписать (старые пресет-тесты удалить, добавить MVP-тесты)

**Steps:**
1. **test_registry.py** (≥8 тестов):
   - Singleton: `DisplayRegistry() is DisplayRegistry()` → True
   - `register` → `get` → entry идентична
   - `register` дубликата → `ValueError`
   - `unregister` существующего → `True`, entry не в `list()`
   - `unregister` несуществующего → `False`, нет исключения
   - `persist(tmp_path / "d.yaml")` → файл создан, содержит id дисплея
   - `load(путь)` после `persist` → registry восстановлен идентично
   - `load(несуществующий_файл)` → нет исключения, registry пуст
   - Thread-safety: 20 параллельных `register` (разные id) → все зарегистрированы
   - Фикстура `_clean_registry` (autouse) — очищает singleton через `clear()`

2. **test_display_state_adapter.py** (≥6 тестов):
   - `bind(proxy); connect()` → `proxy.subscribe("displays.*.status", ...)` вызван
   - `sync_domain_to_state()` с 2 дисплеями → `proxy.set` вызван ≥2 раз
   - Anti-loop: `sync_domain_to_state` не вызывает рекурсивный callback
   - `disconnect()` → подписки отменены (через `proxy.unsubscribe`)
   - `proxy=None` → все методы — no-op без исключений
   - `build_initial_state(displays_config=cfg)` с 2 дисплеями → `state["displays"]` содержит 2 ключа

3. **test_blueprint_binding.py** (≥4 теста):
   - `bind_displays_to_blueprint(registry_с_2_дисплеями, {})` → blueprint содержит оба ключа
   - `"GRAY"` format → `frame_shape[-1] == 1`
   - `cleanup_display_from_blueprint("main", blueprint)` → ключ исчез
   - Аргументные dict не мутированы

4. **test_preview_window.py** (≥4 теста, pytest-qt):
   - `PreviewWindow(entry)` конструируется без router_manager
   - `preview.show()` — окно открывается (qtbot.addWidget)
   - `preview.close()` — нет исключений
   - `open_for_display(entry, None)` — возвращает видимый экземпляр

5. **test_displays_tab.py** (переписать):
   - Удалить все тесты на пресеты (`test_apply_preset_1x1` и т.д.)
   - Добавить: `DisplaysTab.create(ctx)` — конструируется, `isinstance(tab, IDisplaysView)` → True
   - Добавить: mock `registry.register()` → `refresh_list()` вызван
   - Добавить: mock `registry.unregister()` → `refresh_list()` вызван

**Acceptance criteria:**
- [ ] `pytest multiprocess_framework/modules/display_module/tests/` — все проходят
- [ ] `pytest multiprocess_prototype/backend/state/adapters/tests/test_display_state_adapter.py` — все проходят
- [ ] `pytest multiprocess_prototype/backend/displays/tests/` — все проходят
- [ ] `pytest multiprocess_prototype/frontend/widgets/displays/tests/` — все проходят (qt тесты с --qt-api=pyside6)
- [ ] `pytest multiprocess_prototype/frontend/widgets/tabs/displays/tests/` — старые пресет-тесты удалены, новые проходят
- [ ] Итого тестов в новых файлах: ≥20
- [ ] Фикстура `_clean_registry` сбрасывает singleton между тестами (no leakage)

**Out of scope:** Integration-тесты с реальным SHM (Platform-зависимы, отложены). End-to-end с кадрами — Phase 7.

**Dependencies:** Task 4.1–4.7 (все)

**Refs trailer:** `Refs: plans/prototype-skeleton-2026-05/phase-4-displays-tab.md, plans/prototype-skeleton-2026-05/plan.md`
**Status:** [PENDING]

---

### Task 4.9 — Документация + ADR display_module

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Создать `display_module/{README.md, STATUS.md, DECISIONS.md}` + добавить ADR-запись в `multiprocess_framework/DECISIONS.md` + запустить `python -m scripts.sync`.
**Context:** По стандарту проекта каждый новый framework-модуль обязан иметь эти три файла. Без них модуль не считается завершённым (правило из CLAUDE.md). Образец — `service_module/` (README.md, STATUS.md, DECISIONS.md).

**Files:**
- `multiprocess_framework/modules/display_module/README.md` — создать
- `multiprocess_framework/modules/display_module/STATUS.md` — создать
- `multiprocess_framework/modules/display_module/DECISIONS.md` — создать
- `multiprocess_framework/DECISIONS.md` — добавить ADR-запись

**Steps:**
1. Прочитать `multiprocess_framework/modules/service_module/README.md`, `STATUS.md`, `DECISIONS.md` как шаблоны.
2. Создать `display_module/README.md`:
   - Назначение: декларативный реестр именованных SHM-каналов для отображения кадров
   - Публичный API: `DisplayEntry`, `IDisplayRegistry`, `IDisplayChannel`, `DisplayRegistry`
   - Пример регистрации дисплея и persist
   - Пример `bind_displays_to_blueprint` (ссылка на prototype)
   - Что НЕ входит: создание SHM (делает SharedResourcesManager), чтение кадров (делает PreviewWindow), fan-out routing (делает RouterManager)
3. Создать `display_module/STATUS.md`:
   - Статус: ACTIVE (Phase 4)
   - Покрытие тестами: N тестов (заполнить после Task 4.8)
   - Известные ограничения: `_cleanup_shm_channel` — только предупреждение, фактический cleanup — в prototype
4. Создать `display_module/DECISIONS.md` с ADR локального уровня:
   - **ADR-DM-001**: Почему DisplayEntry не содержит `element_shape`/`dtype` — vision-специфика в prototype, framework остаётся generic
   - **ADR-DM-002**: Почему `persist(path)` принимает `path` аргументом, а не хранит внутри singleton — prototype решает где хранить (ADR-025 config-driven)
   - **ADR-DM-003**: SHM cleanup при `unregister` — только предупреждение-лог; фактическое освобождение при следующем старте ProcessManagerProcess (избегаем прямой связи display_module → shared_resources_module)
5. Обновить `multiprocess_framework/DECISIONS.md`:
   - Добавить глобальный ADR (следующий номер после ADR-129): «DisplayRegistry: декларативный реестр SHM-каналов через RouterManager — не плагин, не процесс, узел в PipelineTab»
   - Ссылку на `display_module/DECISIONS.md`
6. Запустить `python -m scripts.sync` для пересборки сводных разделов `DECISIONS.md`.
7. Проверить `python scripts/validate.py` — нет drift.

**Acceptance criteria:**
- [ ] `display_module/README.md`, `STATUS.md`, `DECISIONS.md` созданы
- [ ] `multiprocess_framework/DECISIONS.md` содержит новый ADR с номером и ссылкой
- [ ] `python -m scripts.sync` — выполнен без ошибок
- [ ] `python scripts/validate.py` — нет drift (CI-check проходит)
- [ ] Все три файла написаны на **русском** языке (policy проекта)

**Out of scope:** Обновление `MODULES_STATUS.md` и `MODULES_OVERVIEW.md` — сделать только если это входит в `scripts.sync` автоматически; иначе отдельный коммит.

**Dependencies:** Task 4.1, Task 4.2, Task 4.3 (нужно понимать финальный API для документирования)

**Refs trailer:** `Refs: plans/prototype-skeleton-2026-05/phase-4-displays-tab.md, plans/prototype-skeleton-2026-05/plan.md`
**Status:** [PENDING]

---

## Сводная таблица

| Task | Название | Level | Assignee | Зависит от |
|------|----------|-------|----------|-----------|
| 4.1 | Интерфейсы display_module | Middle | developer | — |
| 4.2 | DisplayRegistry реализация | Middle+ | developer | 4.1 |
| 4.3 | Blueprint integration | Senior | teamlead | 4.1, 4.2 |
| 4.4 | displays.yaml + загрузчик | Middle | developer | 4.2 |
| 4.5 | DisplayStateAdapter + bootstrap | Middle+ | developer | 4.1, 4.2, 4.4 |
| 4.6 | DisplaysTab MVP переписать | Middle+ | developer | 4.1, 4.2, 4.4 |
| 4.7 | PreviewWindow | Senior | teamlead | 4.1, 4.2, 4.6 |
| 4.8 | Тесты (20-25 штук) | Middle | developer | 4.1–4.7 |
| 4.9 | Документация + ADR + sync | Middle | developer | 4.1, 4.2, 4.3 |

**Критический путь:** 4.1 → 4.2 → 4.5 → 4.6 → 4.7 → 4.8

**Параллелизация:**
- 4.1 → 4.2 и 4.4 можно запускать параллельно (4.2 и 4.4 независимы после 4.1)
- 4.3 и 4.5 можно параллельно после 4.2
- 4.9 можно начать после 4.1–4.3 (не ждёт GUI)
- 4.8 только в конце (зависит от всех)
