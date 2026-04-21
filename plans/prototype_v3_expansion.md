# Мета-план: Расширение multiprocess_prototype_v3

## Context

**Текущее состояние:** Рабочий прототип с 6 процессами (Camera, Processor, Renderer, GUI, Database, Robot), 6 табами PyQt, register-driven state, IPC Queue+SHM, рецепты в YAML, детекции в SQLite.

**Цель:** Расширить прототип до полноценной промышленной системы инспекции с 8 новыми возможностями.

**Параметры (по ответам пользователя):**
- Камеры: **10+** → динамическая оркестрация, отдельный процесс на камеру
- Undo/Redo: **всё кроме I/O** → Command Pattern + SQL-лог
- Настройки: **переключаемые профили** (как рецепты)
- Display: **динамически, без лимита** → ленивая SHM-аллокация

**Принцип:** Максимальное переиспользование `multiprocess_framework` (19 модулей). `SchemaBase` — модель для каждой сущности (камера, регион, обработка, рецепт, настройка, undo-команда, display-подписка).

---

## Архитектурные решения (зафиксировать ДО начала кода)

### AD-1: Процессная модель для N камер
**Решение:** Один `CameraProcess` на камеру, динамический spawn при старте.
- `CameraConfig` получает `camera_id: str`, `process_name` = `f"camera_{camera_id}"`
- SHM-слот = `f"camera_{camera_id}_frame"`
- `AppConfig.all_process_configs()` генерирует конфиги по списку камер из профиля настроек
- Hot-add отложен — при добавлении камеры нужен перезапуск (Phase 3)
- **Почему:** Hikvision SDK + ctypes = GIL contention в одном процессе; отдельные процессы решают

### AD-2: Исполнение processing chain
**Решение:** Один Processor-процесс с `dispatch_module` Scenarios per region.
- Каждый регион → именованный `Scenario` из `ScenarioBuilder`
- Каждый шаг обработки → `handler` на нумерованном `stage`
- Frames приходят по разным SHM-слотам, Processor определяет camera+region и запускает Scenario
- **Почему:** NumPy отпускает GIL; сценарии атомарны (swap ссылки); один процесс проще N

### AD-3: Undo/Redo — frontend-only middleware
**Решение:** Middleware вокруг `RegistersManager.set_field_value()` в GUI-процессе.
- Все изменения состояния проходят через RegistersManager → middleware перехватывает
- Hardware I/O исключён автоматически (это backend→frontend, не register writes)
- SQL-лог через `sql_module` (GenericRepository + SchemaBaseMapper) для crash recovery
- **Почему:** RegistersManager — single point of truth для GUI; backend — производное от регистров

### AD-4: Display routing — подписка + ленивый SHM
**Решение:** `DisplaySubscription` (camera_id, region_id, step_id) → window_id.
- SHM создаётся только при подписке (`MemoryManager.create_memory_dict()`)
- Unsubscribe → `close_memory()`
- IPC-команды `create_display_shm` / `destroy_display_shm`
- **Почему:** 10 камер × 5 регионов × 5 обработок = 250 потенциальных буферов; ленивая аллокация = только активные

---

## Фазы реализации

### Phase 0: Инфраструктура настроек и профилей (фундамент)
**Цель:** Система профилей настроек, от которой зависят все остальные фазы.
**Сложность:** M | **Зависимости:** нет

**Задачи:**
1. `AppSettingsRegister` (SchemaBase) — `registers/settings/schemas.py`
   - Поля: camera_count, display_defaults, processing_defaults
   - `FieldMeta` с label/min/max/unit, `RegisterDispatchMeta(process_targets=("gui",))`
2. `SettingsProfileManager` — `frontend/managers/settings_profile_manager.py`
   - Зеркало RecipeManager: YAML-backed, list/get/save/switch profiles
   - Merge: SchemaBase defaults + YAML overrides через `DataConverter`
3. Интеграция в `FrontendLauncher` и `FrontendAppContext`

**Модули фреймворка:** `data_schema_module` (SchemaBase, FieldMeta, DataConverter, FileStorage), `registers_module`

**Файлы:**
- Новые: `registers/settings/schemas.py`, `registers/settings/constants.py`, `frontend/managers/settings_profile_manager.py`
- Изменить: `frontend/launcher.py`, `frontend/app_context.py`, `registers/__init__.py`

**Критерий:** Профиль загружается из YAML, переключается, RegistersManager отражает значения.

---

### Phase 1: Рецепты (улучшение таба)
**Цель:** Табличное редактирование рецептов, переключение по номеру, двунаправленная синхронизация.
**Сложность:** M | **Зависимости:** Phase 0

**Задачи:**
1. Заменить текущий view на `StructuredTableWidget` (frontend_module)
   - Столбцы из `FieldMeta` (label, type, min/max, unit)
   - Редактируемые ячейки → `RecipeManager.save_slot()`
2. Переключение слотов по номеру (ComboBox/Spin)
   - Switch → `RecipeManager.get_slot()` → update всех регистров → IPC propagation
3. Auto-save с debounce, версионирование YAML

**Модули фреймворка:** `frontend_module` (StructuredTableWidget, BaseWidget, RegisterBinding), `data_schema_module`

**Файлы:** `frontend/widgets/settings_recipe_widget/`, `frontend/widgets/tabs_setting/recipes_tab/`, `frontend/managers/recipe_manager.py`

**Критерий:** Редактирование ячейки → обновление регистра → propagation в бэкенд. Переключение слота работает.

---

### Phase 2: Настройки (переключаемые профили)
**Цель:** Таб настроек с SchemaBase defaults + YAML overrides. Переключаемые профили.
**Сложность:** M | **Зависимости:** Phase 0, Phase 1 (паттерн таблицы)

**Задачи:**
1. Переиспользовать паттерн Phase 1 (StructuredTableWidget) для AppSettingsRegister
2. Profile selector (как recipe slot selector)
3. Merge-логика: defaults из SchemaBase + override из YAML profile
4. Событие `profile_changed` — Phase 3+ компоненты подписываются

**Файлы:**
- Новые: `frontend/widgets/settings_profile_widget/` (model, presenter, panel, view, schemas)
- Изменить: `frontend/widgets/tabs_setting/recipes_settings_tab/widget.py`

**Критерий:** Переключение профиля обновляет все регистры. Defaults видны. YAML пишется при Save.

---

### Phase 3: Мульти-камеры (10+)
**Цель:** Динамическая оркестрация процессов камер. Per-camera статус, start/stop.
**Сложность:** XL | **Зависимости:** Phase 0

**Задачи:**
1. Параметризация `CameraProcess` — `camera_id` в конфиге, SHM-слот = `f"camera_{id}_frame"`
2. Динамическая генерация конфигов в `AppConfig.all_process_configs()`
3. `CameraRegistry` (frontend) — реестр камер: id, type, status, process_name
4. Enhanced Camera Tab: список камер (слева) + настройки камеры (справа) + статусы + start/stop
5. Webcam panel (MVP-паттерн, как Hikvision)
6. Per-camera routing: `f"control_camera_{id}"` каналы

**Модули фреймворка:** `process_module`, `worker_module`, `shared_resources_module` (MemoryManager), `router_module` (FrameShmMiddleware), `frontend_module`

**Файлы:**
- Изменить: `backend/processes/camera/` (config, process, adapter), `config/app.py`, `registers/camera/`, `registers/constants.py`, `main.py`
- Новые: `frontend/managers/camera_registry.py`, `frontend/widgets/webcam_camera_mvp/`
- Изменить: `frontend/widgets/tabs_setting/camera_tab/`, `frontend/launcher.py`

**Критерий:** 10 камер загружаются из конфига, каждая в своём процессе с SHM. Start/stop по отдельности. Статусы в UI.

---

### Phase 4: Регионы (per-camera)
**Цель:** Per-camera управление регионами. CRUD + привязка к processing chain.
**Сложность:** L | **Зависимости:** Phase 3

**Задачи:**
1. Рефакторинг `CroppedRegionsPanelWidget` — динамические камеры из CameraRegistry
2. Структура `crop_regions`: `{camera_id: {region_id: Region}}`
3. Расширение `Region` — поле `processing_chain_id: str` (подготовка для Phase 5)
4. Backend propagation: register_update → Processor перестраивает Scenarios

**Файлы:** `frontend/widgets/cropped_regions_widget/`, `registers/pipeline/region.py`, `registers/processor/schemas.py`, `backend/processes/processor/process.py`

**Критерий:** Регионы per camera. Добавление/удаление. Propagation в Processor.

---

### Phase 5: Processing Chain + Каталог обработок
**Цель:** Цепочка обработок per region + библиотека операций + CRUD каталога.
**Сложность:** XL | **Зависимости:** Phase 4

**Задачи:**
1. Каталог: `ProcessingOperationDef` (SchemaBase) — name, params schema, module path. YAML storage.
2. `CatalogManager` — CRUD. Built-in: ColorDetection, BlobDetection.
3. Processing chain editor: region selector + ordered list (drag-reorder) + catalog browser + param panel
4. Chain→Scenario mapping: `ScenarioBuilder` из `dispatch_module`, атомарный swap
5. Auto-generated param panels из SchemaBase FieldMeta → frontend_module контролы
6. Catalog CRUD tab: таблица операций, add/edit/delete

**Модули фреймворка:** `dispatch_module` (ScenarioBuilder, CHAIN_MATCH), `frontend_module` (StructuredTableWidget, TreeWithToolbar), `data_schema_module`

**Файлы:**
- Новые: `registers/processor/catalog/`, `frontend/managers/catalog_manager.py`, `frontend/widgets/tabs_setting/catalog_tab/`
- Redesign: `frontend/widgets/processing_panel_widget/`
- Изменить: `backend/processes/processor/process.py`, `commands.py`, `tab_factory.py`

**Критерий:** Chain per region, reorder, add from catalog. Param panel per step. Каталог CRUD. Backend processing по chain.

---

### Phase 6: Отображение (динамические окна)
**Цель:** Неограниченные display-окна. Маршрутизация любого выхода в любое окно. Lazy SHM.
**Сложность:** XL | **Зависимости:** Phase 3, Phase 5

**Задачи:**
1. `DisplaySubscription` модель (SchemaBase): source → window_id
2. `DisplayRouter` (frontend) — управление подписками, lazy SHM через MemoryManager
3. Display window widget: ImagePanelWidget + source selector (combobox всех доступных выходов)
4. Display tab: таблица окон, create/close, route selector
5. SHM routing: processing steps пишут промежуточные результаты в именованные слоты
6. Window lifecycle через `WindowManager`

**Модули фреймворка:** `shared_resources_module` (MemoryManager), `router_module` (FrameShmMiddleware), `frontend_module` (ImagePanelWidget, WindowManager)

**Файлы:**
- Новые: `frontend/managers/display_router.py`, `frontend/widgets/display_window/`, `frontend/widgets/tabs_setting/display_tab/`
- Изменить: `backend/processes/renderer/process.py`, `backend/processes/gui/process.py`, `frontend/launcher.py`

**Критерий:** Создание окна из UI. Роутинг любого источника. SHM только при подписке. Нет утечек при create/destroy.

---

### Phase 7: Undo/Redo
**Цель:** Command Pattern + SQL-лог. Все изменения кроме I/O. Глубина 100.
**Сложность:** XL | **Зависимости:** Все предыдущие фазы (Undo оборачивает все действия)

**Задачи:**
1. Command-абстракция: `UndoableCommand` protocol (execute/undo/description)
   - `RegisterFieldCommand`, `CompositeCommand`, `RecipeSwitchCommand`
   - `RegionAddCommand`, `RegionRemoveCommand`, `ProcessingChainCommand`
2. `UndoStack` — circular buffer (deque, max 100), undo pointer, redo branch truncation
3. SQL persistence через `sql_module`: `GenericRepository` + `SchemaBaseMapper` → таблица `undo_log`
4. Middleware вокруг `RegistersManager.set_field_value()` — перехват, запись old/new, push в stack
5. UI: Ctrl+Z / Ctrl+Y, кнопки в header, статус-бар с описанием последнего действия

**Модули фреймворка:** `sql_module` (SQLManager, GenericRepository, SchemaBaseMapper, UnitOfWork), `registers_module`, `frontend_module`

**Файлы:**
- Новые: `frontend/undo/` (commands.py, undo_stack.py, sql_log.py, register_middleware.py)
- Изменить: `frontend/launcher.py`, `frontend/windows/main_window/window.py`, `frontend/app_context.py`

**Исключения из Undo:** camera start/stop (hardware), file save (I/O), messages to backend (side effects of register changes — Undo replays register)

**Критерий:** Ctrl+Z отменяет изменение параметра. 100 шагов. Recipe switch = 1 undo step. Region CRUD undoable. SQL-лог пишется. Camera I/O НЕ отменяется.

---

## Граф зависимостей

```
Phase 0 (Settings/Profiles) ─────────────────────────────┐
  │                                                        │
  ├──→ Phase 1 (Recipes Enhanced) ──→ Phase 2 (Settings)  │
  │                                                        │
  └──→ Phase 3 (Multi-Camera) ──→ Phase 4 (Regions) ──→ Phase 5 (Processing Chain)
                                                      │           │
                                                      └─→ Phase 6 (Display) ←─┘
                                                                  │
  Phases 0-6 ─────────────────────────────────→ Phase 7 (Undo/Redo)
```

## Оценка трудоёмкости

| Phase | Фича | Сложность | Файлов изменить | Новых файлов |
|-------|-------|-----------|----------------|-------------|
| 0 | Settings/Profiles | M | 5 | 4 |
| 1 | Recipes Enhanced | M | 8 | 0 |
| 2 | Settings Tab | M | 5 | 6 |
| 3 | Multi-Camera | XL | 15 | 5 |
| 4 | Regions | L | 6 | 0 |
| 5 | Processing Chain | XL | 10 | 12 |
| 6 | Display Windows | XL | 8 | 10 |
| 7 | Undo/Redo | XL | 5 | 5 |
| **Итого** | | | **~62** | **~42** |

## Риски

| Риск | Влияние | Митигация |
|------|---------|-----------|
| SHM-exhaustion (10+ камер + dynamic display) | OOM/crash | Lazy allocation + SHM budget config + мониторинг |
| IPC-queue saturation при N камерах | Потеря кадров | Per-camera queue sizing + priority queues + drop-oldest |
| GIL в Processor при 10 camera streams | Падение FPS | NumPy отпускает GIL; если мало — ProcessPoolExecutor |
| Undo с cross-process state divergence | Inconsistent state | Undo replays register writes → re-sends IPC → backend синхронизируется |
| Schema evolution между профилями | Broken YAML | SchemaBase validation с defaults + migration в ProfileManager |
| Processing chain hot-reload race | Partial chain | Atomic scenario swap (build new → swap reference) |

## Верификация (end-to-end)

1. **Phase 0-2:** Запуск → профиль загрузился → переключение рецепта/настроек обновляет UI и бэкенд
2. **Phase 3:** Запуск с 3+ камерами → каждая стримит → start/stop индивидуально
3. **Phase 4:** Добавить регион на камеру → виден в дереве → propagation в Processor
4. **Phase 5:** Создать обработку в каталоге → добавить в chain региона → видеть результат на кадре
5. **Phase 6:** Создать 3 display-окна → роутнуть разные источники → все обновляются live
6. **Phase 7:** Изменить 5 параметров → Ctrl+Z ×5 → всё вернулось → Ctrl+Y ×5 → всё вернулось
