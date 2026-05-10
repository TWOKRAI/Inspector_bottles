# План: Фаза 2.2 — Frontend Base во фреймворк

**Дата:** 2026-05-01
**Статус:** DRAFT
**Зависит от:** Фаза 2.1 (state_store_module) — DONE; Фаза 2 завершила реорганизацию widgets v3 (`docs/refactors/2026-04_widgets_reorg.md`)

---

## 1. Цель и scope

### Цель

Перенести **generic-инфраструктуру frontend** из `multiprocess_prototype/frontend/` в расширение существующего модуля `multiprocess_framework/modules/frontend_module/`. После Фазы 2.2 в прототипе остаются только доменные виджеты/менеджеры (камеры, регионы, pipeline, processing, recipes), а универсальные подсистемы (entity editor, action bus, chrome, themes, styles, threads) живут во фреймворке.

### Что входит в scope (~5 760 строк)

| Подсистема | Источник | Цель | Прибл. строк |
|---|---|---|---|
| **Entity Editor** | `frontend/widgets/base/editor/` | `frontend_module/widgets/entity_editor/` | ~1 775 |
| **Action Bus** | `frontend/actions/{schemas,builder,bus,persistence}` | `frontend_module/actions/` | ~680 |
| **Chrome Widgets** | `frontend/widgets/chrome/` | `frontend_module/widgets/chrome/` | ~800 |
| **Managers (generic)** | `frontend/managers/` (часть) | `frontend_module/managers/` | ~1 423 |
| **Styles** | `frontend/styles/` | `frontend_module/styling/` | ~400 |
| **Threads** | `frontend/threads/` | `frontend_module/core/threads/` | ~150 |
| **qt_thread_guard** | `frontend/utils/qt_thread_guard.py` | `frontend_module/core/qt_thread_guard.py` | ~50 |
| **Generic Qt-models** | `frontend/models/` (только generic) | `frontend_module/models/` | ~300 |
| **app_context** | `frontend/app_context.py` | `frontend_module/core/app_context.py` | ~100 |
| **diagnostics** | `frontend/diagnostics.py` | `frontend_module/core/diagnostics.py` | ~80 |

### Что НЕ входит в scope (остаётся в прототипе)

- **Доменные actions:** `frontend/actions/handlers/` (FieldSetHandler, RegionAddHandler, etc.), `default_bus_factory.py`, `action_logger.py` (если он завязан на доменные регистры)
- **Доменные виджеты:** `frontend/widgets/{pipeline,processing,recipes,settings,sources,tabs_setting,base/*}` (кроме `base/editor/`)
- **Доменные menager-ы:** `camera_registry.py`, `app_recipe_aggregate.py`
- **Доменные модели:** `frontend/models/sections/` (всё, что специфично для бутылок)
- **Доменные методы и атрибуты в actions/builder.py:** методы `region_*`, `step_*`, `graph_*`, `topology_*`, `display_*`, `layout_change` — оставить в прототипе как наследник `ActionBuilder` (см. §3.3)
- **Доменные ActionType:** `REGION_*`, `STEP_*`, `GRAPH_*`, `TOPOLOGY_*`, `DISPLAY_*`, `LAYOUT_*`, `PROFILE_SWITCH`, `RECIPE_SWITCH` — переносится только generic ядро, остальные регистрируются проектом (см. §3.4)
- **`frontend/managers/window_manager.py`** — это `DisplayWindowManager`, доменный (display-окна, подписки на камеры). Остаётся в прототипе под доменным именем.
- **`frontend/configs/frontend_config.py`** (доменный)
- **`frontend/coordinators/logical_cameras.py`** (доменный)
- **`frontend/launcher.py`, `bridges/`, `commands/`** — Фаза 4 (не сейчас)

### Принцип границы

> Если модуль читает/обращается к именам доменных регистров (`registers.display`, `registers.camera`, `registers.theme`) или знает про `vision_pipeline`/«камеру»/«регион» — он доменный. Всё остальное (универсальные паттерны Qt + персистентность + темизация) — generic.

---

## 2. Анализ зависимостей

### 2.1 Карта переносимых модулей и их зависимостей

```
schemas.py (Action, ActionType-generic)
   └── data_schema_module.SchemaBase (fw)         [уже в fw]

builder.py (ActionBuilder generic core)
   └── schemas.py
   └── frontend_module.schemas.register_binding   [уже в fw]

bus.py (ActionBus + Protocols)
   └── schemas.py
   └── persistence/log_writer.py (TYPE_CHECKING)

actions/persistence/*
   └── schemas.py
   └── (опционально) ConfigStore / data_schema   [уже в fw]

entity_tree_config.py (ParamDef, EntityLevel) — pure dataclass

base_editor_model.py — pure Python (без Qt)

base_editor_tree.py
   └── PySide6 (Qt)

base_editor_toolbar.py
   └── PySide6

entity_tree_widget.py
   └── base_editor_tree.py
   └── entity_tree_config.py

params_form.py
   └── PySide6
   └── (через FieldMeta) data_schema_module        [уже в fw]

schema_inspector_panel.py
   └── params_form.py

chrome/app_header,recording_indicator,search_filter_bar,
side_panels,view_mode_toggle,watchdog_overlay
   └── PySide6
   └── frontend_module.core.qt_imports             [уже в fw]
   └── (некоторые) registers.* — ПРОВЕРИТЬ при переносе

theme_manager.py
   └── PySide6
   └── (read_default_variables) registers.theme.schemas  ← ДОМЕННАЯ ЗАВИСИМОСТЬ — разрезать (см. §3.5)

theme_presets_manager.py
   └── yaml, Path

settings_yaml_store.py → yaml_persistence_store.py
   └── pydantic
   └── multiprocess_prototype.config.settings_profile (SettingsProfile)  ← ДОМЕННАЯ — разрезать
   └── multiprocess_prototype.registers.settings (AppSettingsRegisters)  ← ДОМЕННАЯ — разрезать

recipe_manager.py → config_snapshot_manager.py
   └── yaml, Path
   (generic полностью)

recipe_manager_protocol.py — pure Protocol

settings_profile_protocol.py — pure Protocol

access_context.py — pure dataclass

display_router.py
   ⚠ ДОМЕННЫЙ:
   └── backend.routing.frame_router_setup
   └── registers.display.{schemas,presets}
   ⇒ НЕ ПЕРЕНОСИТСЯ! (см. §3.6)

styles/  (QSS, schemas, variables.yaml)
   └── PySide6 (косвенно через ThemeManager)

threads/ (Qt worker thread helpers) — PySide6, generic

utils/qt_thread_guard.py — pure Qt

models/ (generic Qt models) — PySide6
   ⚠ Перенести только generic; section-specific остаются

app_context.py
   └── recipe_manager_protocol.py
   └── settings_profile_protocol.py
   ⇒ generic-каркас (FrontendAppContext) можно перенести; доменные get_*_tab_ui методы вынести в подкласс прототипа

diagnostics.py
   └── frontend_module.core.qt_imports             [уже в fw]
   └── frontend_module.widgets.widget_signal_bus   [уже в fw]
   ⇒ полностью generic
```

### 2.2 Direct Acyclic Graph (порядок переноса)

```
Уровень 0 (фундамент, без зависимостей от других переносимых):
  • styles/                              → frontend_module/styling/
  • utils/qt_thread_guard.py             → frontend_module/core/qt_thread_guard.py
  • threads/                             → frontend_module/core/threads/
  • access_context.py                    → frontend_module/managers/access_context.py
  • recipe_manager_protocol.py           → frontend_module/managers/config_snapshot_protocol.py
  • settings_profile_protocol.py         → frontend_module/managers/settings_profile_protocol.py
  • diagnostics.py                       → frontend_module/core/diagnostics.py
  • models/ (generic)                    → frontend_module/models/

Уровень 1 (зависят от уровня 0):
  • theme_presets_manager.py             → frontend_module/managers/theme_presets_manager.py
  • theme_manager.py (с разрезом доменной зависимости — см. §3.5)
                                          → frontend_module/managers/theme_manager.py
  • settings_yaml_store.py (generic-каркас YamlPersistenceStore[T])
                                          → frontend_module/managers/yaml_persistence_store.py
  • recipe_manager.py (как ConfigSnapshotManager)
                                          → frontend_module/managers/config_snapshot_manager.py
  • app_context.py (generic-каркас FrontendAppContext)
                                          → frontend_module/core/app_context.py

Уровень 2 (Action Bus core):
  • actions/schemas.py (generic-Action + базовый ActionType — см. §3.4)
                                          → frontend_module/actions/schemas.py
  • actions/builder.py (generic core ActionBuilder)
                                          → frontend_module/actions/builder.py

Уровень 3 (зависят от Action schemas):
  • actions/bus.py                       → frontend_module/actions/bus.py
  • actions/persistence/                 → frontend_module/actions/persistence/

Уровень 4 (Entity Editor — все файлы взаимозависимы):
  • entity_tree_config.py                → frontend_module/widgets/entity_editor/entity_tree_config.py
  • base_editor_model.py                 → frontend_module/widgets/entity_editor/base_editor_model.py
  • base_editor_tree.py                  → frontend_module/widgets/entity_editor/base_editor_tree.py
  • base_editor_toolbar.py               → frontend_module/widgets/entity_editor/base_editor_toolbar.py
  • params_form.py                       → frontend_module/widgets/entity_editor/params_form.py
  • schema_inspector_panel.py            → frontend_module/widgets/entity_editor/schema_inspector_panel.py
  • entity_tree_widget.py                → frontend_module/widgets/entity_editor/entity_tree_widget.py

Уровень 5 (Chrome Widgets):
  • app_header/, recording_indicator/, search_filter_bar/,
    side_panels/, view_mode_toggle/, watchdog_overlay/
                                          → frontend_module/widgets/chrome/*

Уровень 6 (публичный API):
  • Обновить frontend_module/__init__.py, frontend_module/widgets/__init__.py,
    frontend_module/actions/__init__.py, frontend_module/managers/__init__.py
```

---

## 3. Решение конфликтов и архитектурных развилок

### 3.1 Конфликт `WindowManager`

**Найдено:** в `multiprocess_framework/modules/frontend_module/application/window_manager.py` уже есть `WindowManager` — управляет окнами приложения (singleton-реестр окон, fullscreen, cursor, access_level). Файл `frontend/managers/window_manager.py` в прототипе — это совершенно другая сущность: `DisplayWindowManager` (управляет display-окнами видеопотока, имеет зависимость от `DisplayRouter`, `DisplaySubscription`).

**Решение:**
- Прототип-овый `frontend/managers/window_manager.py` **не переносится** во фреймворк.
- Содержит класс `DisplayWindowManager` — доменная сущность (display-окна, подписки на камеры). Остаётся в прототипе.
- Чтобы убрать путаницу — переименовать **файл в прототипе** (Task 1.1) с `window_manager.py` на `display_window_manager.py`. Все импорты обновить.
- Существующий fw `WindowManager` остаётся без изменений.

### 3.2 Конфликт `recipe_manager.py`

**Решение:** переносится во фреймворк под именем `ConfigSnapshotManager` (`frontend_module/managers/config_snapshot_manager.py`). Класс — обобщённый YAML-storage для именованных слотов конфигурации. Доменная семантика «рецепт» убирается из имени и docstring.

В прототипе остаётся **тонкий subclass** `RecipeManager(ConfigSnapshotManager)` с предустановленными путями (`data/recipes.yaml`, `data/settings_recipes.yaml`) и доменными slot-операциями, если они есть. Имя класса/импорт-алиас сохраняется для обратной совместимости.

### 3.3 Generic core ActionBuilder vs доменные методы

**Найдено:** `actions/builder.py` (~770 строк) содержит:
- Generic ядро (~50 строк): `ActionBuilder._make_id`, `field_set`, `from_field`, `command`
- Доменные фабрики (~700 строк): `region_*`, `step_*`, `graph_*`, `topology_*`, `display_*`, `layout_change`, `profile_switch`, `recipe_switch`

**Решение:**
1. **Во фреймворк** — только generic core (`field_set`, `from_field`, `command`, `_make_id`).
2. **В прототипе** — наследник `class AppActionBuilder(ActionBuilder)` в `frontend/actions/app_action_builder.py` со всеми доменными статическими методами. Имя `ActionBuilder` сохраняется через alias `ActionBuilder = AppActionBuilder` в `frontend/actions/__init__.py`, чтобы не ломать существующие импорты.

### 3.4 ActionType: generic vs доменный

**Решение:**
1. Во фреймворке `frontend_module/actions/schemas.py` определить базовый `ActionType` enum **только** с generic-значениями: `FIELD_SET`, `COMMAND`. Реализовать `ActionType` как `str, Enum` (как сейчас).
2. В прототипе расширить через `class AppActionType(str, Enum)` со всеми доменными значениями (`REGION_ADD`, `STEP_ADD`, …, `LAYOUT_CHANGE`).
3. Поле `action_type: ActionType` в `Action` сделать `str`-типом (через `Field(...)` с указанием `description`), чтобы оба enum проходили pydantic-валидацию (значения у обоих — строки). Если pydantic настаивает на enum — использовать `Union[ActionType, AppActionType]` или (предпочтительно) объявить поле как `str` с pre-validator-ом, проверяющим, что значение принадлежит одному из зарегистрированных enum-ов.

**Альтернатива (запасная):** оставить `ActionType` во фреймворке полным (со всеми текущими значениями), но пометить большинство как «domain extension». Это проще, но засоряет фреймворк. **Не выбираем**, кроме случая, когда §3.4 окажется слишком сложным при реализации — тогда Developer фиксирует это в DECISIONS.md и применяет fallback.

### 3.5 ThemeManager и доменная зависимость от `registers.theme.schemas`

**Найдено:** `theme_manager.py:144-148` — `read_default_variables()` импортирует `from multiprocess_prototype.registers.theme.schemas import get_default_variables`.

**Решение:**
1. Во фреймворке `theme_manager.py` принимает callable-провайдер дефолтных переменных в `__init__`:
   ```python
   def __init__(
       self,
       styles_dir: Path | None = None,
       *,
       default_variables_provider: Callable[[], dict[str, str]] | None = None,
   ): ...
   ```
2. Если провайдер не задан — используется пустой dict (graceful fallback) или встроенный минимум (только то, что нужно для работы fw-уровня).
3. В прототипе при создании `ThemeManager(default_variables_provider=get_default_variables)` сохраняется текущее поведение.

### 3.6 DisplayRouter — НЕ переносится

`frontend/managers/display_router.py` (~450 строк) импортирует `backend.routing.frame_router_setup`, `registers.display.schemas`, `registers.display.presets` — это **полностью доменный** код, привязанный к концепции «камера/кадр/подписка».

**Решение:** остаётся в прототипе. В исходном описании Фазы 2.2 он указан как generic ошибочно — фиксируется в плане как отдельный пункт «DisplayRouter не переносится, обоснование выше». Это не блокирует Фазу 2.2.

### 3.7 SettingsYamlStore: разрез доменной части

**Найдено:** `settings_yaml_store.py:30-31` импортирует `SettingsProfile` и `AppSettingsRegisters` (обе — доменные).

**Решение:**
1. Во фреймворке создать `frontend_module/managers/yaml_persistence_store.py` с **обобщённым** `class YamlPersistenceStore[T]` (generic над типом профиля). Класс:
   - Принимает в конструкторе фабрику снимков (`default_snapshot_factory: Callable[[], dict]`),
   - Принимает валидатор профиля (`profile_validator: Callable[[dict], None] | None`) — может быть `pydantic_model.model_validate`,
   - Не импортирует доменных типов.
2. В прототипе создать тонкий `class SettingsYamlStore(YamlPersistenceStore[SettingsProfile])` в `multiprocess_prototype/frontend/managers/settings_yaml_store.py`, который:
   - Передаёт `default_snapshot_factory=default_profile_snapshot`,
   - Передаёт `profile_validator=AppSettingsRegisters.model_validate`.
3. Имена и пути файлов модулей сохраняются: ничего не ломается во внешнем коде.

### 3.8 FrontendAppContext: доменные `get_*_tab_ui`

**Найдено:** `app_context.py:38-49` — поля `dataclass` (универсальные слоты + `extras`), методы `get_recipes_tab_ui`, `get_camera_tab_ui`, …, `get_processing_tab_ui` — доменные.

**Решение:**
1. Во фреймворке создать `frontend_module/core/app_context.py` с базовым `FrontendAppContext` без доменных `get_*_tab_ui`. Поля: `config`, `registers_manager`, `command_handler`, `extras`, `action_bus`. Generic-метод: `get_section(name: str) -> Any` (читает из `config[name]`).
2. В прототипе — `class AppFrontendContext(FrontendAppContext)` с расширенными полями (`camera_callbacks_map`, `camera_type`, `recipe_manager`, `settings_profile_manager`, `camera_registry`, `topology_editor`, `topology_bridge`) и доменными `get_*_tab_ui` методами.

---

## 4. Задачи по шагам

> **Соглашения для всех задач:**
> - Все команды выполняются из `/Users/twokrai/Project_code/Inspector_bottles/`
> - Импорты во фреймворке: `from multiprocess_framework.modules.frontend_module.X import Y`
> - Импорты внутри прототипа на перенесённое: тоже `from multiprocess_framework.modules.frontend_module.X import Y` (никаких реэкспортов через старые пути для new-кода)
> - Shim-файлы в прототипе создаются ТОЛЬКО для модулей со старым стабильным путём, на который завязан существующий код — для обратной совместимости (см. §5).
> - У каждого подкаталога во фреймворке должен быть `__init__.py` с публичным API; внутренние модули могут не реэкспортироваться из верхнеуровневого `frontend_module/__init__.py` напрямую — пусть импортируются через подпакеты.
> - Тесты для перенесённых модулей **в этой фазе не переносятся** — это Фаза 3.

---

### Phase 2.2.0 — Подготовка

#### Task 0.1 — Переименование `window_manager.py` в прототипе для устранения семантического конфликта

**Уровень:** Simple
**Файлы-источники:** `multiprocess_prototype/frontend/managers/window_manager.py`
**Файлы-цели:** `multiprocess_prototype/frontend/managers/display_window_manager.py`
**Шаги:**
1. Переименовать файл (git mv).
2. Обновить все импорты в прототипе через grep/qex (`mcp__qex__search_code "DisplayWindowManager"`, затем `Grep "from multiprocess_prototype.frontend.managers.window_manager"`).
3. Заменить во всех найденных местах: `window_manager` → `display_window_manager`.
4. Оставить shim `multiprocess_prototype/frontend/managers/window_manager.py` с одной строкой:
   ```python
   from .display_window_manager import DisplayWindowManager  # noqa: F401
   ```
   (deprecation-комментарий в шапке файла на 3 строки)

**Изменения импортов:** ~5–10 мест (точно — после grep).
**Shims в прототипе:** `frontend/managers/window_manager.py` → реэкспорт `DisplayWindowManager`.
**Верификация:**
- `python scripts/validate.py`
- `pytest multiprocess_prototype/tests/ -k window -v`
- `python multiprocess_prototype/run.py` — UI должен запуститься (smoke).

**DAG:** не зависит ни от чего; должен выполняться **до** Уровня 0, чтобы избежать путаницы при последующем переносе.

---

### Phase 2.2.1 — Уровень 0: фундамент

#### Task 1.1 — Перенести `frontend/styles/` → `frontend_module/styling/`

**Уровень:** Simple
**Источники:** `multiprocess_prototype/frontend/styles/` (вся папка: `*.qss`, `themes/`, `schemas/`, `variables.yaml`, `__init__.py`).
**Цели:** `multiprocess_framework/modules/frontend_module/styling/` (создать).
**Шаги:**
1. Создать каталог `frontend_module/styling/`. Скопировать содержимое.
2. Если есть `styles/schemas/*.py` со ссылками на `multiprocess_prototype` — обновить импорты на новый путь (или вернуть в прототип, если это доменные схемы).
3. Если в QSS-файлах есть абсолютные пути / переменные, привязанные к структуре прототипа — оставить как есть (пути из `Path(__file__).parent` сами скорректируются).
4. В прототипе оставить тонкий редирект: `frontend/styles/__init__.py` экспортирует `from multiprocess_framework.modules.frontend_module.styling import *`. Файлы `.qss` физически — во фреймворке; ThemeManager после переноса (Task 2.2) будет читать их оттуда.

**Shims:** `frontend/styles/__init__.py` (только если есть Python-модули в styles/).
**Верификация:**
- `python -c "from multiprocess_framework.modules.frontend_module.styling import __file__; print(__file__)"`
- Проверить, что `glob('*.qss')` через `Path(frontend_module.styling.__file__).parent` находит файлы тем.

**DAG:** не зависит ни от чего.

---

#### Task 1.2 — Перенести `frontend/utils/qt_thread_guard.py` → `frontend_module/core/qt_thread_guard.py`

**Уровень:** Simple
**Источник:** `multiprocess_prototype/frontend/utils/qt_thread_guard.py`
**Цель:** `multiprocess_framework/modules/frontend_module/core/qt_thread_guard.py`
**Шаги:**
1. Скопировать файл (git mv не подходит — путь меняет репо).
2. Заменить `from PySide6.QtCore import ...` на `from multiprocess_framework.modules.frontend_module.core.qt_imports import ...` (если такой alias существует во фреймворке; иначе оставить прямой импорт PySide6).
3. Найти все usage в прототипе (`mcp__qex__search_code "qt_thread_guard"`), переписать импорты на `from multiprocess_framework.modules.frontend_module.core.qt_thread_guard import ...`.
4. Оставить shim `frontend/utils/qt_thread_guard.py`:
   ```python
   from multiprocess_framework.modules.frontend_module.core.qt_thread_guard import *  # noqa: F401,F403
   ```

**Shims:** `frontend/utils/qt_thread_guard.py` — реэкспорт.
**Верификация:** `pytest multiprocess_prototype/tests/ -k thread_guard -v`.

**DAG:** не зависит ни от чего.

---

#### Task 1.3 — Перенести `frontend/threads/` → `frontend_module/core/threads/`

**Уровень:** Simple
**Источник:** `multiprocess_prototype/frontend/threads/` (все файлы)
**Цель:** `multiprocess_framework/modules/frontend_module/core/threads/`
**Шаги:**
1. Создать каталог. Скопировать все файлы вместе с `__init__.py`.
2. Обновить внутренние импорты на абсолютные через `multiprocess_framework.modules.frontend_module.core.threads.*`.
3. Найти usage в прототипе, заменить пути импортов.
4. Shim `frontend/threads/__init__.py` — реэкспорт.

**Shims:** `frontend/threads/__init__.py`.
**Верификация:** smoke + grep `from frontend.threads`.

**DAG:** не зависит ни от чего.

---

#### Task 1.4 — Перенести `frontend/managers/access_context.py` → `frontend_module/managers/access_context.py`

**Уровень:** Simple
**Источник:** `multiprocess_prototype/frontend/managers/access_context.py`
**Цель:** `multiprocess_framework/modules/frontend_module/managers/access_context.py`
**Шаги:**
1. Создать каталог `frontend_module/managers/` (если ещё нет) с `__init__.py`.
2. Скопировать `access_context.py` без изменений (pure dataclass).
3. Найти usage. Обновить импорты: `from multiprocess_framework.modules.frontend_module.managers.access_context import AccessContext`.
4. Shim в прототипе: `frontend/managers/access_context.py` — реэкспорт.

**Shims:** `frontend/managers/access_context.py`.
**Верификация:** unit-тесты по grep `AccessContext`.

**DAG:** не зависит ни от чего.

---

#### Task 1.5 — Перенести `recipe_manager_protocol.py` и `settings_profile_protocol.py`

**Уровень:** Simple
**Источники:**
- `multiprocess_prototype/frontend/managers/recipe_manager_protocol.py`
- `multiprocess_prototype/frontend/managers/settings_profile_protocol.py`

**Цели:**
- `multiprocess_framework/modules/frontend_module/managers/config_snapshot_protocol.py` (с `ConfigSnapshotProtocol = RecipeManagerProtocol` для совместимости)
- `multiprocess_framework/modules/frontend_module/managers/settings_profile_protocol.py`

**Шаги:**
1. Скопировать оба файла.
2. В `config_snapshot_protocol.py` сохранить имя `RecipeManagerProtocol` (для совместимости) **и** добавить алиас `ConfigSnapshotProtocol = RecipeManagerProtocol` для нового кода.
3. Обновить импорты в прототипе: `app_context.py` (Task 2.5), `recipe_manager.py` (Task 2.4) — заменить пути.
4. Shim в прототипе: `frontend/managers/recipe_manager_protocol.py` — реэкспорт `RecipeManagerProtocol`. Аналогично для `settings_profile_protocol.py`.

**Shims:** оба `*_protocol.py` файла в прототипе.
**Верификация:** smoke (Protocol-ы).

**DAG:** не зависит ни от чего.

---

#### Task 1.6 — Перенести `frontend/diagnostics.py` → `frontend_module/core/diagnostics.py`

**Уровень:** Simple
**Источник:** `multiprocess_prototype/frontend/diagnostics.py`
**Цель:** `multiprocess_framework/modules/frontend_module/core/diagnostics.py`
**Шаги:**
1. Скопировать файл. Импорты `qt_imports` и `widget_signal_bus` уже корректные (из fw).
2. Найти usage в прототипе, заменить импорты.
3. Shim в прототипе: `frontend/diagnostics.py` — реэкспорт всех публичных функций.

**Shims:** `frontend/diagnostics.py`.
**Верификация:** запуск GUI с `ui_diagnostics.enabled=true` — логи UI-событий должны идти.

**DAG:** не зависит ни от чего.

---

#### Task 1.7 — Перенести generic Qt-models из `frontend/models/`

**Уровень:** Medium
**Источник:** `multiprocess_prototype/frontend/models/` — **только generic** Qt-models. Domain-specific (`models/sections/*` в большинстве — доменные) **не переносятся**.
**Цель:** `multiprocess_framework/modules/frontend_module/models/` (если ещё нет).
**Шаги:**
1. Проинвентаризировать `frontend/models/` (`ls`, открыть `__init__.py`). Для каждого файла определить: импортирует ли `registers.*` или `multiprocess_prototype.config.*`. Если да — доменный, оставить.
2. Generic Qt-модели (например, базовые `QAbstractTableModel`-подклассы без знания о камерах/регионах) — перенести.
3. В каждом перенесённом файле обновить относительные импорты.
4. Создать shims-реэкспорты для перенесённых; доменные модели остаются нетронутыми.

**Shims:** реэкспорты по каждому перенесённому файлу.
**Верификация:** `python -c "from multiprocess_framework.modules.frontend_module.models import *"` + smoke GUI.

**DAG:** не зависит ни от чего.

> ⚠ Пограничный случай: если `frontend/models/` содержит мало generic-кода (<100 строк) — оставить целиком в прототипе и не делать перенос на этом этапе. Решение Developer фиксирует в коммите.

---

### Phase 2.2.2 — Уровень 1: managers и app_context

#### Task 2.1 — Перенести `theme_presets_manager.py`

**Уровень:** Simple
**Источник:** `multiprocess_prototype/frontend/managers/theme_presets_manager.py`
**Цель:** `multiprocess_framework/modules/frontend_module/managers/theme_presets_manager.py`
**Шаги:**
1. Скопировать. Параметризовать путь данных через конструктор (уже есть `data_dir` параметр).
2. В прототипе создать тонкий subclass или фабрику, передающую `data_dir = <prototype>/data`.
3. Shim: `frontend/managers/theme_presets_manager.py` → реэкспорт + (если нужно) preset класса с `data_dir` дефолтом.

**Shims:** `frontend/managers/theme_presets_manager.py`.
**Верификация:** smoke; ручной тест: `python -c "from multiprocess_framework.modules.frontend_module.managers.theme_presets_manager import ThemePresetsManager; ThemePresetsManager().list_presets()"`.

**DAG:** зависит от Task 1.1 (styles/) — не строго, но удобно делать вместе.

---

#### Task 2.2 — Перенести `theme_manager.py` с разрезом доменной зависимости

**Уровень:** Medium
**Источник:** `multiprocess_prototype/frontend/managers/theme_manager.py`
**Цель:** `multiprocess_framework/modules/frontend_module/managers/theme_manager.py`
**Шаги:**
1. Скопировать файл.
2. Удалить импорт `from multiprocess_prototype.registers.theme.schemas import get_default_variables`.
3. Изменить `__init__`:
   ```python
   def __init__(
       self,
       styles_dir: Path | None = None,
       *,
       default_variables_provider: Callable[[], dict[str, str]] | None = None,
   ):
       ...
       self._default_variables_provider = default_variables_provider or (lambda: {})
   ```
4. В `read_default_variables`: `defaults = self._default_variables_provider()`.
5. `_STYLES_DIR` пересчитать относительно нового расположения (`frontend_module/styling/`).
6. В прототипе создать `frontend/managers/theme_manager.py` как тонкий wrapper:
   ```python
   from multiprocess_framework.modules.frontend_module.managers.theme_manager import (
       ThemeManager as _ThemeManagerBase,
   )
   from multiprocess_prototype.registers.theme.schemas import get_default_variables

   class ThemeManager(_ThemeManagerBase):
       def __init__(self, styles_dir=None):
           super().__init__(styles_dir, default_variables_provider=get_default_variables)
   ```
7. Все usage `ThemeManager` в прототипе уже импортируют из `frontend.managers.theme_manager` — продолжают работать.

**Shims:** `frontend/managers/theme_manager.py` — wrapper-класс.
**Верификация:**
- `python multiprocess_prototype/run.py` — тема применяется (смотреть QSS на виджетах).
- Unit-тест на `ThemeManager.apply_theme("innotech_theme")` если есть.

**DAG:** зависит от Task 1.1 (styles), Task 2.1 (рекомендуется параллельно).

---

#### Task 2.3 — Перенести `settings_yaml_store.py` как `YamlPersistenceStore[T]`

**Уровень:** Medium
**Источник:** `multiprocess_prototype/frontend/managers/settings_yaml_store.py`
**Цель:** `multiprocess_framework/modules/frontend_module/managers/yaml_persistence_store.py`
**Шаги:**
1. Создать в fw `yaml_persistence_store.py` с обобщённым классом:
   ```python
   class YamlPersistenceStore[T]:
       def __init__(
           self,
           file_path: Path,
           *,
           default_snapshot_factory: Callable[[], dict],
           profile_validator: Callable[[dict], None] | None = None,
           file_version: int = 1,
           default_profile_id: str = "default",
       ): ...
   ```
2. Перенести из исходника всю YAML-логику (load/save/migrate), но без импортов `SettingsProfile`, `AppSettingsRegisters`.
3. В прототипе обновить `frontend/managers/settings_yaml_store.py`:
   ```python
   from multiprocess_framework.modules.frontend_module.managers.yaml_persistence_store import (
       YamlPersistenceStore,
   )
   from multiprocess_prototype.config.settings_profile import SettingsProfile
   from multiprocess_prototype.registers.settings import AppSettingsRegisters

   def default_settings_profiles_path() -> Path: ...
   def default_profile_snapshot() -> dict: ...

   class SettingsYamlStore(YamlPersistenceStore[SettingsProfile]):
       def __init__(self, file_path=None):
           super().__init__(
               file_path or default_settings_profiles_path(),
               default_snapshot_factory=default_profile_snapshot,
               profile_validator=AppSettingsRegisters.model_validate,
           )
   ```
4. Все существующие импорты `SettingsYamlStore` продолжают работать.

**Shims:** `frontend/managers/settings_yaml_store.py` (заменён, но публичный API сохранён).
**Верификация:**
- Unit-тесты на `SettingsYamlStore` (если есть в `tests/unit/frontend/managers/`).
- Smoke: запустить GUI, переключить профиль, перезапустить — профиль восстанавливается.

**DAG:** зависит от Task 1.5.

---

#### Task 2.4 — Перенести `recipe_manager.py` как `ConfigSnapshotManager`

**Уровень:** Medium
**Источник:** `multiprocess_prototype/frontend/managers/recipe_manager.py`
**Цель:** `multiprocess_framework/modules/frontend_module/managers/config_snapshot_manager.py`
**Шаги:**
1. Перенести логику класса под именем `ConfigSnapshotManager`. Параметризовать оба файла YAML через конструктор (уже сделано).
2. Сохранить в шапке: «Generic snapshot/recipe manager. Хранит именованные конфигурационные слоты в YAML».
3. В прототипе `frontend/managers/recipe_manager.py` оставить тонкий subclass:
   ```python
   from multiprocess_framework.modules.frontend_module.managers.config_snapshot_manager import (
       ConfigSnapshotManager,
   )

   DEFAULT_RECIPE_SLOT_ID = "default"

   class RecipeManager(ConfigSnapshotManager):
       def __init__(self, data_path=None, app_recipes_path=None):
           super().__init__(
               data_path or _PROTO_ROOT / "data" / "recipes.yaml",
               app_recipes_path or _PROTO_ROOT / "data" / "settings_recipes.yaml",
           )
   ```
4. `RecipeManagerProtocol` уже перенесён (Task 1.5); проверить, что `RecipeManager` соответствует ему.

**Shims:** `frontend/managers/recipe_manager.py` — subclass.
**Верификация:**
- `python multiprocess_prototype/run.py` — открыть Recipes tab; список слотов появляется; save/load работает.

**DAG:** зависит от Task 1.5.

---

#### Task 2.5 — Перенести `app_context.py` как generic `FrontendAppContext`

**Уровень:** Medium+
**Источник:** `multiprocess_prototype/frontend/app_context.py`
**Цель:** `multiprocess_framework/modules/frontend_module/core/app_context.py`
**Шаги:**
1. Создать в fw `app_context.py` с базовым `FrontendAppContext`:
   ```python
   @dataclass
   class FrontendAppContext:
       config: Dict[str, Any]
       registers_manager: Optional[Any] = None
       command_handler: Optional[Any] = None
       action_bus: Optional[Any] = None
       extras: Dict[str, Any] = field(default_factory=dict)

       def get_section(self, name: str) -> Any:
           return self.config.get(name)
   ```
2. В прототипе создать `frontend/app_context.py` (заменить старый файл) с `class AppFrontendContext(FrontendAppContext)` со всеми доменными полями (camera_callbacks_map, camera_type, recipe_manager, settings_profile_manager, camera_registry, topology_editor, topology_bridge) и доменными `get_*_tab_ui` методами.
3. Сохранить класс-алиас `FrontendAppContext = AppFrontendContext` в `frontend/app_context.py`, чтобы существующий код прототипа (использующий имя `FrontendAppContext`) не сломался.

**Shims:** `frontend/app_context.py` целиком превращается в наследник + alias.
**Верификация:**
- `python multiprocess_prototype/run.py` — все вкладки открываются (доменные `get_*_tab_ui` работают).
- `python -c "from multiprocess_framework.modules.frontend_module.core.app_context import FrontendAppContext"` — generic-каркас импортируется.

**DAG:** зависит от Task 1.5 (Protocol-ы используются в полях AppFrontendContext).

---

### Phase 2.2.3 — Уровень 2: Action Bus core (schemas + builder)

#### Task 3.1 — Перенести `actions/schemas.py` (generic Action + базовый ActionType)

**Уровень:** Medium+
**Источник:** `multiprocess_prototype/frontend/actions/schemas.py`
**Цель:** `multiprocess_framework/modules/frontend_module/actions/schemas.py`
**Шаги:**
1. Создать в fw `frontend_module/actions/__init__.py` (пустой, заполним в Task 6.1).
2. Создать `frontend_module/actions/schemas.py`. Перенести классы `ActionType`, `Action` со следующими изменениями:
   - В `ActionType` оставить **только** `FIELD_SET = "field_set"` и `COMMAND = "command"`.
   - В `Action.action_type` поле объявить как `str` (не enum), с pre-validator-ом, валидирующим, что это известный тип. **Альтернатива (упрощение):** оставить `ActionType` enum, но открыть его для расширения через `ActionType._add_member_` или второй enum (см. §3.4). **Рекомендуется** объявить поле как `str` — это самое чистое решение для extension.
3. Создать пробный регистр расширения:
   ```python
   _registered_action_types: set[str] = set(ActionType)

   def register_action_type(value: str) -> None:
       """Регистрация доменных типов action из приложения."""
       _registered_action_types.add(value)
   ```
   Pre-validator проверяет членство в `_registered_action_types`.
4. В прототипе создать `frontend/actions/schemas.py` (заменить старый):
   ```python
   from multiprocess_framework.modules.frontend_module.actions.schemas import (
       Action,
       ActionType as _BaseActionType,
       register_action_type,
   )
   from enum import Enum

   class AppActionType(str, Enum):
       FIELD_SET = "field_set"
       COMMAND = "command"
       REGION_ADD = "region_add"
       # ... все остальные доменные значения из старого ActionType
       LAYOUT_CHANGE = "layout_change"

   for member in AppActionType:
       register_action_type(member.value)

   ActionType = AppActionType  # alias для обратной совместимости
   ```

**Shims:** `frontend/actions/schemas.py` — переписан как extension; имена `Action`, `ActionType` сохранены.
**Верификация:**
- `pytest multiprocess_prototype/tests/unit/frontend/actions/ -v`
- `python -c "from frontend.actions.schemas import Action, ActionType; a = Action(action_type=ActionType.REGION_ADD); print(a)"`

**DAG:** не зависит от других; **должна быть выполнена до Task 3.2 и 3.3**.

---

#### Task 3.2 — Перенести `actions/builder.py` (generic core)

**Уровень:** Medium+
**Источник:** `multiprocess_prototype/frontend/actions/builder.py`
**Цель:**
- `multiprocess_framework/modules/frontend_module/actions/builder.py` (generic core)
- `multiprocess_prototype/frontend/actions/app_action_builder.py` (доменные методы)

**Шаги:**
1. Во фреймворке создать `builder.py` с классом `ActionBuilder`, содержащим **только**: `_make_id`, `field_set`, `from_field`, `command`. Импорт `RegisterBinding` остаётся как был (`TYPE_CHECKING`).
2. В прототипе создать `frontend/actions/app_action_builder.py`:
   ```python
   from multiprocess_framework.modules.frontend_module.actions.builder import (
       ActionBuilder as _ActionBuilderBase,
   )
   from .schemas import Action, ActionType  # AppActionType из Task 3.1

   class AppActionBuilder(_ActionBuilderBase):
       @staticmethod
       def region_add(...): ...
       @staticmethod
       def step_add(...): ...
       # ... все остальные доменные методы из исходного builder.py
   ```
3. В прототипе `frontend/actions/builder.py` (shim):
   ```python
   from .app_action_builder import AppActionBuilder as ActionBuilder  # noqa: F401
   ```
   Все существующие `from frontend.actions.builder import ActionBuilder` продолжают работать.

**Shims:** `frontend/actions/builder.py` — alias на `AppActionBuilder`.
**Верификация:**
- `pytest multiprocess_prototype/tests/unit/frontend/actions/ -v`
- Smoke: открыть Sources tab, добавить регион → undo → проверить, что регион удалился.

**DAG:** зависит от Task 3.1.

---

### Phase 2.2.4 — Уровень 3: ActionBus + persistence

#### Task 4.1 — Перенести `actions/bus.py`

**Уровень:** Medium
**Источник:** `multiprocess_prototype/frontend/actions/bus.py`
**Цель:** `multiprocess_framework/modules/frontend_module/actions/bus.py`
**Шаги:**
1. Скопировать файл. Импорт `from .schemas import Action, ActionType` — корректный (теперь из fw).
2. Импорт `ActionLogWriter` (`TYPE_CHECKING`) обновить на путь fw: `from .persistence.log_writer import ActionLogWriter`.
3. В прототипе `frontend/actions/bus.py` — shim:
   ```python
   from multiprocess_framework.modules.frontend_module.actions.bus import (
       ActionBus, ActionHandler, IRegistersManagerGui,
   )  # noqa: F401
   ```

**Shims:** `frontend/actions/bus.py`.
**Верификация:** smoke + undo/redo тест.

**DAG:** зависит от Task 3.1, Task 3.2; **должна выполняться до Task 4.2** (persistence ссылается на bus в TYPE_CHECKING).

---

#### Task 4.2 — Перенести `actions/persistence/`

**Уровень:** Medium+
**Источник:** `multiprocess_prototype/frontend/actions/persistence/` (вся папка)
**Цель:** `multiprocess_framework/modules/frontend_module/actions/persistence/`
**Шаги:**
1. Проинвентаризировать содержимое (`log_writer.py`, `log_reader.py`, `recovery.py`, `rotation.py`, `__init__.py`).
2. Скопировать всё. Внутренние импорты (между модулями persistence) уже относительные — корректны.
3. Внешние импорты (на `Action`, `ActionType`) — обновить на `from multiprocess_framework.modules.frontend_module.actions.schemas import ...`.
4. **Если** какой-то persistence-модуль импортирует доменные SQL-таблицы/конфиги (`backend.database`, etc.) — этот файл доменный, оставить в прототипе и пометить в DECISIONS.md.
5. В прототипе `frontend/actions/persistence/` — shims-реэкспорты:
   ```python
   from multiprocess_framework.modules.frontend_module.actions.persistence import *  # noqa
   ```

**Shims:** `frontend/actions/persistence/__init__.py`.
**Верификация:**
- Запустить GUI с `action_log` enabled, выполнить несколько действий, перезапустить → recovery восстановил undo-стек.

**DAG:** зависит от Task 4.1.

---

### Phase 2.2.5 — Уровень 4: Entity Editor

#### Task 5.1 — Перенести Entity Editor (целиком, как набор)

**Уровень:** Medium+
**Источники:** `multiprocess_prototype/frontend/widgets/base/editor/`:
- `entity_tree_config.py`
- `base_editor_model.py`
- `base_editor_tree.py`
- `base_editor_toolbar.py`
- `params_form.py`
- `schema_inspector_panel.py`
- `entity_tree_widget.py`

**Цель:** `multiprocess_framework/modules/frontend_module/widgets/entity_editor/` (создать)
**Шаги:**
1. Создать каталог `frontend_module/widgets/entity_editor/` с `__init__.py`.
2. Перенести файлы по одному в порядке зависимостей: `entity_tree_config.py` → `base_editor_model.py` → `base_editor_tree.py` → `base_editor_toolbar.py` → `params_form.py` → `schema_inspector_panel.py` → `entity_tree_widget.py`.
3. В каждом файле: переписать импорты с `multiprocess_prototype.frontend.widgets.base.editor.X` на `multiprocess_framework.modules.frontend_module.widgets.entity_editor.X`.
4. Импорты `PySide6.*` оставить (или, если в fw используется `core.qt_imports`, переписать единообразно — выбор Developer-а).
5. `params_form.py`: импорт `FieldMeta` (если есть) — пересмотреть путь (вероятно, уже `data_schema_module` из fw).
6. **НЕ переносим:** `cross_tab_combo.py`, `topology_editor_model.py` (доменные).
7. `frontend_module/widgets/entity_editor/__init__.py`:
   ```python
   from .entity_tree_config import EntityTreeConfig, EntityLevel, ParamDef
   from .entity_tree_widget import EntityTreeWidget
   from .base_editor_model import BaseEditorModel
   from .base_editor_tree import BaseEditorTreeView
   from .base_editor_toolbar import BaseEditorToolbar
   from .params_form import ParamsForm
   from .schema_inspector_panel import SchemaInspectorPanel

   __all__ = [...]
   ```
8. Найти все usage в прототипе (`mcp__qex__search_code "EntityTreeWidget"`, `BaseEditorModel`, `ParamsForm`, `SchemaInspectorPanel`, `BaseEditorTreeView`, `BaseEditorToolbar`, `EntityTreeConfig`, `EntityLevel`, `ParamDef`). Для каждого: либо переписать импорт на fw, либо положиться на shim (см. ниже).
9. Shim в прототипе: `frontend/widgets/base/editor/__init__.py`:
   ```python
   from multiprocess_framework.modules.frontend_module.widgets.entity_editor import *  # noqa: F401,F403
   ```
   Каждый отдельный файл `frontend/widgets/base/editor/<name>.py` тоже превратить в реэкспорт-модуль.

**Shims:** все 7 файлов в `frontend/widgets/base/editor/` — реэкспорты.
**Верификация:**
- `pytest multiprocess_prototype/tests/unit/frontend/widgets/base/editor/ -v`
- `python multiprocess_prototype/run.py` — открыть Pipeline tab, Sources tab — деревья отрисовываются, выделение работает.

**DAG:** зависит от Task 1.7 (если перенесли generic models), не зависит от Action Bus.

---

### Phase 2.2.6 — Уровень 5: Chrome Widgets

#### Task 6.1 — Перенести `frontend/widgets/chrome/` целиком

**Уровень:** Medium
**Источник:** `multiprocess_prototype/frontend/widgets/chrome/` (вся папка):
- `app_header/` — header, info_ticker, mode_toggle, status_strip
- `recording_indicator/` — widget, schemas
- `search_filter_bar/` — bar
- `side_panels/` — collapsible
- `view_mode_toggle/` — toggle
- `watchdog_overlay/` — widget

**Цель:** `multiprocess_framework/modules/frontend_module/widgets/chrome/`
**Шаги:**
1. Создать каталог. Скопировать всю структуру вместе с lazy-loading `__init__.py` (как в исходном).
2. Для каждого подмодуля проверить импорты на доменные:
   - `recording_indicator/widget.py` — может ссылаться на `registers.recording.*` или `services.recording.*` → если так, **разрезать** (передавать конфиг/состояние через параметры конструктора, не импортировать `registers.*`).
   - `app_header/info_ticker.py` — может читать данные из state_store → должен принимать `state_proxy` через DI, не импортировать конкретные пути.
   - `app_header/status_strip.py` — аналогично.
   - `search_filter_bar/bar.py` — обычно generic.
   - `side_panels/collapsible.py` — generic.
   - `view_mode_toggle/toggle.py` — generic.
   - `watchdog_overlay/widget.py` — может зависеть от health-monitor → проверить.
3. Если найдена жёсткая доменная зависимость — создать sub-task внутри Task 6.1.X для разреза (DI/callback).
4. Внутренние импорты (между chrome-подмодулями) — переписать на абсолютные через `multiprocess_framework.modules.frontend_module.widgets.chrome.*`.
5. Найти usage в прототипе (`mcp__qex__search_code` по именам `AppHeaderWidget`, `RecordingIndicator`, `SearchFilterBar`, `CollapsibleSidePanel`, `ViewModeToggle`, `WatchdogOverlay`, `InfoTickerWidget`, `HeaderModeToggle`, `StatusStripWidget`).
6. Shim в прототипе `frontend/widgets/chrome/__init__.py` — заменить весь контент на:
   ```python
   from multiprocess_framework.modules.frontend_module.widgets.chrome import *  # noqa
   from multiprocess_framework.modules.frontend_module.widgets.chrome import __all__  # noqa
   ```
   Lazy-loading сохранить во фреймворке (он там нужнее).

**Shims:** `frontend/widgets/chrome/__init__.py` + один shim-файл на каждый подмодуль (`app_header.py`, `recording_indicator.py`, …) если на них есть прямые импорты типа `from frontend.widgets.chrome.app_header import AppHeaderWidget`.
**Верификация:**
- `python multiprocess_prototype/run.py` — header, status strip, side panels, watchdog overlay видимы и работают.
- pytest для chrome (если есть).

**DAG:** зависит от Task 1.1 (styles — расположение QSS), может зависеть от Task 2.5 (если виджеты получают AppContext).

---

### Phase 2.2.7 — Уровень 6: публичный API и финал

#### Task 7.1 — Обновить публичный API `frontend_module/__init__.py`

**Уровень:** Simple
**Файл:** `multiprocess_framework/modules/frontend_module/__init__.py`
**Шаги:**
1. Расширить docstring модуля: упомянуть `actions`, `widgets.entity_editor`, `widgets.chrome`, `managers`, `styling`, `core.threads`, `core.app_context`, `core.diagnostics`, `core.qt_thread_guard`.
2. Обновить `__version__` → `0.4.0` (расширение API).
3. Решение: **не реэкспортировать** новые символы из верхнеуровневого `__init__`. Это позволит избежать раздувания. Все новые подсистемы доступны через подпакеты (`from multiprocess_framework.modules.frontend_module.actions import ActionBus`).
4. В docstring добавить раздел «Phase 2.2 (2026-05) — добавлены подсистемы …».

**Шаги верификации:** `python -c "from multiprocess_framework.modules.frontend_module import FrontendManager"` — ничего не сломалось.

**DAG:** последний шаг, зависит от всех Task 1.x — 6.x.

---

#### Task 7.2 — Обновить `frontend_module/widgets/__init__.py`, `frontend_module/managers/__init__.py`, `frontend_module/actions/__init__.py`

**Уровень:** Simple
**Шаги:**
1. `frontend_module/widgets/__init__.py` — добавить ленивый/прямой реэкспорт `entity_editor` и `chrome` подпакетов (учесть, что chrome имеет свой lazy-loading).
2. `frontend_module/managers/__init__.py`:
   ```python
   from .access_context import AccessContext
   from .config_snapshot_protocol import RecipeManagerProtocol, ConfigSnapshotProtocol
   from .config_snapshot_manager import ConfigSnapshotManager
   from .settings_profile_protocol import SettingsProfileManagerProtocol
   from .theme_manager import ThemeManager
   from .theme_presets_manager import ThemePresetsManager
   from .yaml_persistence_store import YamlPersistenceStore

   __all__ = [...]
   ```
3. `frontend_module/actions/__init__.py`:
   ```python
   from .schemas import Action, ActionType, register_action_type
   from .builder import ActionBuilder
   from .bus import ActionBus, ActionHandler, IRegistersManagerGui

   __all__ = [...]
   ```

**Верификация:** smoke + `python -c "from multiprocess_framework.modules.frontend_module.actions import ActionBus, Action; from multiprocess_framework.modules.frontend_module.managers import ThemeManager"`.

**DAG:** зависит от Task 7.1.

---

#### Task 7.3 — Обновить `frontend_module/STATUS.md` и DECISIONS.md

**Уровень:** Simple
**Файлы:**
- `multiprocess_framework/modules/frontend_module/STATUS.md` — указать «Phase 2.2 (2026-05) — расширено: actions, entity_editor, chrome, managers (themes, snapshots, profiles), styling, core threads/app_context/diagnostics/qt_thread_guard».
- `multiprocess_framework/modules/frontend_module/DECISIONS.md` — добавить ADR-FM-XXX:
  - ADR-FM-XXX: «Action Bus core vs domain split» (§3.3)
  - ADR-FM-XXX+1: «ActionType extension via str + register_action_type» (§3.4)
  - ADR-FM-XXX+2: «ThemeManager default_variables_provider DI» (§3.5)
  - ADR-FM-XXX+3: «WindowManager: framework vs DisplayWindowManager (prototype)» (§3.1)
  - ADR-FM-XXX+4: «YamlPersistenceStore[T] generic вместо доменного SettingsYamlStore» (§3.7)
- `multiprocess_framework/DECISIONS.md` — обновить индекс ADR (если ведётся).

**Верификация:** `python scripts/validate.py` (проверяет наличие STATUS/README в модулях).

**DAG:** последний.

---

## 5. Стратегия shims (обратная совместимость прототипа)

### 5.1 Принципы

1. **Shim — это однострочный реэкспорт + deprecation-комментарий.** Никакой логики. Файл из 3–5 строк:
   ```python
   """DEPRECATED: модуль перенесён во фреймворк (Phase 2.2, 2026-05).
   Импортируйте из multiprocess_framework.modules.frontend_module.X вместо этого пути.
   """
   from multiprocess_framework.modules.frontend_module.<path> import *  # noqa: F401,F403
   ```
2. **Shim ≠ subclass.** Subclass (как у `ThemeManager`, `RecipeManager`, `SettingsYamlStore`, `AppFrontendContext`, `AppActionBuilder`) — отдельный паттерн, когда в прототипе нужно сохранить доменные дефолты или методы.
3. **Никаких циклических импортов:** shim в прототипе импортирует **только** из fw, fw — никогда из прототипа.
4. **Shim удаляется в Phase 4–5** после полного переключения внутреннего кода прототипа на fw-импорты.

### 5.2 Полный список shim-файлов после Phase 2.2

| Shim в прототипе | Тип | Цель |
|---|---|---|
| `frontend/managers/window_manager.py` | реэкспорт | прототип-овый `display_window_manager.py` (Task 0.1) |
| `frontend/styles/__init__.py` | реэкспорт | `frontend_module/styling/` (Task 1.1) |
| `frontend/utils/qt_thread_guard.py` | реэкспорт | `frontend_module/core/qt_thread_guard.py` (Task 1.2) |
| `frontend/threads/__init__.py` | реэкспорт | `frontend_module/core/threads/` (Task 1.3) |
| `frontend/managers/access_context.py` | реэкспорт | `frontend_module/managers/access_context.py` (Task 1.4) |
| `frontend/managers/recipe_manager_protocol.py` | реэкспорт | `frontend_module/managers/config_snapshot_protocol.py` (Task 1.5) |
| `frontend/managers/settings_profile_protocol.py` | реэкспорт | `frontend_module/managers/settings_profile_protocol.py` (Task 1.5) |
| `frontend/diagnostics.py` | реэкспорт | `frontend_module/core/diagnostics.py` (Task 1.6) |
| `frontend/models/<generic>.py` | реэкспорт | `frontend_module/models/<...>` (Task 1.7) |
| `frontend/managers/theme_presets_manager.py` | реэкспорт | `frontend_module/managers/theme_presets_manager.py` (Task 2.1) |
| `frontend/managers/theme_manager.py` | **subclass** | wrapper с `default_variables_provider=get_default_variables` (Task 2.2) |
| `frontend/managers/settings_yaml_store.py` | **subclass** | `SettingsYamlStore(YamlPersistenceStore[SettingsProfile])` (Task 2.3) |
| `frontend/managers/recipe_manager.py` | **subclass** | `RecipeManager(ConfigSnapshotManager)` (Task 2.4) |
| `frontend/app_context.py` | **subclass + alias** | `class AppFrontendContext(FrontendAppContext)` + `FrontendAppContext = AppFrontendContext` (Task 2.5) |
| `frontend/actions/schemas.py` | **extension** | `AppActionType` + `register_action_type` для всех доменных типов (Task 3.1) |
| `frontend/actions/builder.py` | alias | `from .app_action_builder import AppActionBuilder as ActionBuilder` (Task 3.2) |
| `frontend/actions/app_action_builder.py` | **новый файл** (subclass) | домен-наследник `ActionBuilder` (Task 3.2) |
| `frontend/actions/bus.py` | реэкспорт | `frontend_module/actions/bus.py` (Task 4.1) |
| `frontend/actions/persistence/__init__.py` | реэкспорт | `frontend_module/actions/persistence/` (Task 4.2) |
| `frontend/widgets/base/editor/<7 файлов>` | реэкспорт | `frontend_module/widgets/entity_editor/<X>` (Task 5.1) |
| `frontend/widgets/chrome/__init__.py` + подмодули | реэкспорт | `frontend_module/widgets/chrome/` (Task 6.1) |

**Итого:** ~30–35 shim-файлов, средний размер 3–5 строк = ~150 строк дополнительного «технического долга», который удаляется в Phase 4.

### 5.3 Журнал deprecation

Создать (или дополнить) `multiprocess_prototype/DECISIONS.md` записью «Phase 2.2 shims (2026-05) — список устаревших путей и сроков удаления (Phase 4)».

---

## 6. Верификация

### 6.1 После каждой задачи

```bash
# 1. Структурная валидация
python scripts/validate.py

# 2. Тесты фреймворка
python scripts/run_framework_tests.py

# 3. Тесты прототипа (точечно по затронутой подсистеме)
pytest multiprocess_prototype/tests/ -v -k <keyword>

# 4. Smoke GUI (после задач, затрагивающих UI)
python multiprocess_prototype/run.py
# — проверить вкладки: Sources, Pipeline, Recipes, Settings; темы переключаются; undo/redo работает.
```

### 6.2 После каждой подфазы (Phase 2.2.0 — 2.2.7)

- Все 4 проверки выше — должны быть зелёными.
- Дополнительно: `python -c "from multiprocess_prototype.main import *"` — никаких ImportError.
- `python -c "from frontend.actions.builder import ActionBuilder; from frontend.managers.theme_manager import ThemeManager; from frontend.widgets.chrome import AppHeaderWidget; from frontend.widgets.base.editor import EntityTreeWidget"` — старые пути работают через shims.
- `python -c "from multiprocess_framework.modules.frontend_module.actions import ActionBus; from multiprocess_framework.modules.frontend_module.widgets.entity_editor import EntityTreeWidget; from multiprocess_framework.modules.frontend_module.managers import ThemeManager"` — новые пути работают.

### 6.3 Финальная проверка после Phase 2.2.7

1. **Импорт-граф:**
   ```bash
   python -c "import multiprocess_prototype.main"
   python -c "import multiprocess_framework.modules.frontend_module"
   ```
2. **Полный pytest:**
   ```bash
   pytest multiprocess_prototype/tests/ -v
   pytest multiprocess_framework/ -v
   ```
3. **GUI smoke (минимум 5 минут):**
   - Запуск, переключение тем, открытие всех вкладок, добавление/удаление региона, undo/redo, выход.
4. **Проверка деления fw/proto:**
   - `grep -r "multiprocess_prototype" multiprocess_framework/modules/frontend_module/` — должен быть **пуст**.
5. **Метрики:**
   - Подсчитать `wc -l` для `multiprocess_prototype/frontend/` до и после: ожидаемое сокращение ~5 760 строк (минус ~150 строк shims) = ~5 600 строк net reduction.
   - Подсчитать `wc -l` для `multiprocess_framework/modules/frontend_module/`: ожидаемый прирост ~5 760 строк.

---

## 7. Риски и ограничения

| Риск | Вероятность | Митигация |
|---|---|---|
| Циркулярный импорт fw ↔ prototype через extension-точки (ActionType, ThemeManager) | Средняя | DI через конструктор + lazy-import; никаких импортов прототипа из fw. |
| `Action.action_type: str` ломает существующие сравнения `action.action_type == ActionType.X` | Высокая | В прототипе `ActionType = AppActionType` — `==` работает (str-enum). Проверить тестами Task 3.1. |
| Pydantic `frozen=True` + extension enum — неожиданное поведение | Низкая | Тесты Task 3.1 покрывают |
| QSS-пути в темах резолвятся относительно `Path(__file__)` — после переноса styles/ зависимые ссылки могут поломаться | Средняя | Все пути в коде вычисляются от `Path(theme_manager_module).parent.parent / "styling"`; QSS не содержит абсолютных путей внутри. |
| Chrome-виджет имеет скрытую доменную зависимость (например, `info_ticker` тянет state_store-селектор для бутылок) | Средняя | На этапе Task 6.1 для каждого виджета сделать grep на `registers.`, `multiprocess_prototype.`. Если найдено — DI или оставить в прототипе. |
| Тесты ломаются из-за изменения `__init__.py` в подпакетах | Средняя | Перед каждым переименованием — найти тесты по старым именам, обновить. |
| `frontend/models/` сложно классифицировать (generic vs domain) | Средняя | См. Task 1.7 — допустимо оставить целиком в прототипе, если grep показывает >70% доменности. |
| Shims накапливаются и затрудняют чтение | Низкая | План удаления — Phase 4; до того shims минимальны (3–5 строк). |

### Ограничения

- **Тесты не переносятся** в Phase 2.2 (это Phase 3). Тесты `tests/unit/frontend/...` для перенесённых модулей продолжают работать через shim-импорты. Если какой-то тест жёстко завязан на путь — обновить только его (точечно).
- **launcher.py** не трогаем (Phase 4).
- **bridges/, commands/, actions/handlers/** — все доменные, не трогаем.
- **DisplayRouter, DisplayWindowManager** — доменные, остаются в прототипе.

---

## 8. Сводная таблица задач

| Подфаза | Task | Уровень | Assignee | Зависимости |
|---|---|---|---|---|
| 2.2.0 | 0.1 — Переименование window_manager.py в proto | Simple | developer | — |
| 2.2.1 | 1.1 — styles/ | Simple | developer | — |
| 2.2.1 | 1.2 — qt_thread_guard.py | Simple | developer | — |
| 2.2.1 | 1.3 — threads/ | Simple | developer | — |
| 2.2.1 | 1.4 — access_context.py | Simple | developer | — |
| 2.2.1 | 1.5 — Protocols | Simple | developer | — |
| 2.2.1 | 1.6 — diagnostics.py | Simple | developer | — |
| 2.2.1 | 1.7 — generic models | Medium | developer | — |
| 2.2.2 | 2.1 — theme_presets_manager | Simple | developer | 1.1 |
| 2.2.2 | 2.2 — theme_manager (DI) | Medium | developer | 1.1, 2.1 |
| 2.2.2 | 2.3 — yaml_persistence_store | Medium | developer | 1.5 |
| 2.2.2 | 2.4 — config_snapshot_manager | Medium | developer | 1.5 |
| 2.2.2 | 2.5 — FrontendAppContext | Medium+ | teamlead | 1.5 |
| 2.2.3 | 3.1 — actions/schemas | Medium+ | teamlead | — |
| 2.2.3 | 3.2 — actions/builder | Medium+ | teamlead | 3.1 |
| 2.2.4 | 4.1 — actions/bus | Medium | developer | 3.1, 3.2 |
| 2.2.4 | 4.2 — actions/persistence | Medium+ | developer | 4.1 |
| 2.2.5 | 5.1 — entity_editor (7 файлов) | Medium+ | developer | 1.7 |
| 2.2.6 | 6.1 — chrome | Medium | developer | 1.1, 2.5 |
| 2.2.7 | 7.1 — frontend_module/__init__.py | Simple | developer | все 1.x–6.x |
| 2.2.7 | 7.2 — sub-package __init__.py | Simple | developer | 7.1 |
| 2.2.7 | 7.3 — STATUS.md, DECISIONS.md | Simple | docs-writer | 7.1 |

**Распараллеливание:**
- Phase 2.2.1 — все 7 задач можно делать параллельно (разные файлы, нет связи).
- Phase 2.2.2 — 2.1 и 2.2 последовательно; 2.3 и 2.4 параллельно; 2.5 параллельно с 2.3/2.4.
- Phase 2.2.3 — 3.1 → 3.2 строго последовательно.
- Phase 2.2.4 — 4.1 → 4.2.
- Phase 2.2.5 и 2.2.6 — параллельно друг с другом, после 2.2.4.
- Phase 2.2.7 — финал.

**Оценка времени:** 5–8 рабочих дней при последовательной работе одного developer-а; 2–3 дня при параллельной работе двух developer-ов + teamlead.

---

## 9. Что дальше (Phase 3+)

После Phase 2.2:
- **Phase 2.3** — Chain/DAG Engine → `chain_module`
- **Phase 2.4** — SHM Ring Buffer → `shared_resources_module`
- **Phase 3** — перенос тестов (включая тесты для перенесённого frontend_module)
- **Phase 4** — `launcher.py` cleanup + удаление всех shim-файлов из Phase 2.2

После завершения Phase 4 структура `multiprocess_prototype/frontend/` должна содержать ~1 700 строк строго доменного кода (см. оценки в `general_refactoring.md`, раздел «Что остаётся в прототипе»).
