# MASTER PLAN — Inspector Prototype v2 (Полная реализация)

## Видение

**Inspector v2** — гибко настраиваемый фреймворк для создания систем технического зрения.
Архитектура v2 (config-driven конструктор) + GUI-дизайн v1 (богатые виджеты, табы, UX).

Ключевая метафора: **YAML topology = чертёж системы**, **плагины = детали конструктора**,
**GUI = панель управления и настройки** конструктора. Прототип = пример собранной системы.

## Принципы

1. **Topology-first:** система описывается в YAML, GUI лишь визуализирует и редактирует topology
2. **Plugin = единица расширения:** один плагин = один файл, `process(items) → items`
3. **GenericProcess only:** никаких хардкод-процессов (кроме GUI)
4. **Register-driven GUI:** виджеты строятся из plugin-конфигов автоматически
5. **Dict at Boundary:** между процессами только dict, Pydantic внутри
6. **Переносим GUI v1 с рефакторингом:** визуальный дизайн = v1, внутренности = v2 архитектура
7. **Инкрементально:** каждая фаза — рабочий прототип, не ломающий предыдущий

---

## Правило: v1 — АРХИВ (только чтение)

> **CRITICAL:** `multiprocess_prototype/` — архив. Никаких изменений.
> Всё, что нужно из v1, **пересоздаётся** в v2 с новой архитектурой.
> v1 используется только как **справочник** для дизайна и логики.

---

## Общий статус прототипа v2

**Прогресс: 100%** | Backend 100% | Frontend infrastructure 100% | GUI табы 100% | Recipes + Undo 100% | TopologyBridge 100% | Bridge Runtime 100% | Pipeline Editor 100% | Schema Ports + FW Extraction 100% | Production Ready 100%

| Слой | Статус | Детали |
|------|--------|--------|
| **Backend / Plugins** | ✅ 100% | 21 плагин, все работают, 9 с registers.py |
| **State / StateStore** | ✅ 100% | Bootstrap + throttle + bindings + 4 теста |
| **Registers / RegistersManager** | ✅ 100% | Auto-discovery + FieldInfo + ConnectionMap |
| **Frontend infrastructure** | ✅ 100% | MainWindow, AppContext, TabFactory, Forms, Themes, Bridges, Primitives |
| **GUI табы** | ✅ 100% | Все 7 табов реализованы (154 теста Phase 10) |
| **Recipes / Undo** | ✅ 100% | Phase 11: TopologyHolder, ActionBus, Ctrl+Z/Y, 35 тестов |
| **TopologyBridge runtime** | ✅ 100% | Phase 12.5: diff_engine + wire_protocol + system_commands + wire_monitor, 94 теста |
| **Pipeline Editor** | ✅ 100% | Phase 13: 3-panel editor, D&D, undo/redo, Sugiyama, wire creation, 181 тест |

### Backend / Plugins — инвентаризация (21 плагин)

| Плагин | Категория | Статус | Registers |
|--------|-----------|--------|-----------|
| `capture` | source | ✅ | — |
| `camera_service` | source | ✅ | — |
| `frame_counter` | utility | ✅ | — |
| `color_mask` | processing | ✅ | ✓ |
| `grayscale` | processing | ✅ | — |
| `negative` | processing | ✅ | — |
| `flip` | processing | ✅ | — |
| `resize` | processing | ✅ | — |
| `region_split` | processing | ✅ | ✓ |
| `blob_detector` | processing | ✅ | ✓ |
| `stitcher` | processing | ✅ | — |
| `chain_executor` | control | ✅ | ✓ |
| `worker_pool` | control | ✅ | ✓ |
| `render_overlay` | rendering | ✅ | ✓ |
| `renderer_compositor` | rendering | ✅ | ✓ |
| `database` | output | ✅ | ✓ |
| `frame_saver` | output | ✅ | ✓ |
| `robot_control` | service | ✅ | ✓ |
| `heartbeat` | utility | ✅ | — |

### GUI — текущее состояние табов

| Tab ID | Title | Статус | Модуль |
|--------|-------|--------|--------|
| `settings` | Settings | ✅ DONE | `widgets/tabs/settings/tab.py` — полный YAML-редактор |
| `recipes` | Recipes | ✅ DONE | `widgets/tabs/recipes/` — 8 слотов, YAML storage, Load/Save/Delete |
| `processes` | Processes | ✅ DONE | `widgets/tabs/processes/` — EntityCard × N, Start/Stop/Restart |
| `services` | Services | ✅ DONE | `widgets/tabs/services/` — SectionedForm, RegisterView per service |
| `plugins` | Plugins | ✅ DONE | `widgets/tabs/plugins/` — MasterDetailLayout, RegisterView/InfoCard |
| `pipeline` | Pipeline | ✅ DONE | `widgets/tabs/pipeline/` — GraphScene, NodeItem, EdgeItem, zoom/pan |
| `displays` | Displays | ✅ DONE | `widgets/tabs/displays/` — SlotSelector, CrudTable, source binding |

### Frontend infrastructure (готово)

| Компонент | LOC | Назначение |
|-----------|-----|------------|
| MainWindow | ~100 | Header + ImagePanel + TabWidget + statusbar |
| AppContext | ~95 | DI-контейнер |
| TabFactory | ~150 | Lazy-загрузка табов, custom factories |
| CardsFieldFactory | ~428 | Генерация Qt-виджетов из FieldInfo |
| FormBuilder | ~226 | build_form_for_register(), build_table_for_register() |
| RegisterView | ~285 | Cards/Table stacked view |
| GuiStateBindings | ~180 | Реактивные подписки через glob-паттерны |
| CommandSender | ~100 | GUI → orchestrator |
| DataReceiverBridge | ~63 | Thread-safe Qt bridge |
| ThemeLoader | ~60 | Тёмная тема + variables.yaml |
| UiPrefsStore | ~80 | Персистенция UI-настроек через QSettings |

### Тесты — 40 файлов

| Категория | Кол-во |
|-----------|--------|
| Frontend (app, bridge, camera, window, tabs...) | 13 |
| Forms (factory, builder, color_picker...) | 5 |
| State bindings | 2 |
| Prefs | 2 |
| Settings tab | 2 |
| Plugins | 10 |
| State bootstrap | 4 |
| Actions / Undo (Phase 11) | 4 |
| Registers | 2 |

---

## Фазы — дорожная карта

| Фаза | Название | Статус | Прогресс |
|------|----------|--------|----------|
| Phase 6 | Plugin Migration | ✅ ЗАКРЫТА | 100% |
| Phase 7 | Registers v2 | ✅ ЗАКРЫТА | 100% |
| Phase 8 | StateStore + Реактивность | ✅ ЗАКРЫТА | 100% |
| Phase 9 | GUI Foundations | ✅ ~90% | Settings tab done, infrastructure done |
| **Phase 10** | **GUI Tabs** | **✅ ЗАКРЫТА** | **7/7 табов, 154 теста, primitives layer** |
| **Phase 11** | **Recipes + Presets + Undo/Redo** | **✅ ЗАКРЫТА** | **100%** |
| **Phase 12** | **TopologyBridge v2** | **✅ ЗАКРЫТА** | **9 подзадач, 82 теста, ~770 LOC** |
| **Phase 12.5** | **TopologyBridge Runtime** | **✅ ЗАКРЫТА** | **94 теста, ~820 LOC** |
| **Phase 13** | **Pipeline Editor Enhanced** | **✅ ЗАКРЫТА** | **181 тест, ~2500 LOC** |
| **Phase 14** | **Schema Ports + Inspector + Safe FW Extraction** | **✅ ЗАКРЫТА** | **4 задачи, 94 новых теста, ~910 LOC** |
| **Phase 15** | **Production Ready** | **✅ ЗАКРЫТА** | **7 задач, 63 новых теста, ~1100 LOC + ~900 md** |

---

## ✅ Phase 6 — Plugin Migration (ЗАКРЫТА)

**Результат:** 21 плагин в v2 архитектуре. Все категории покрыты:
source (3), processing (8), control (2), rendering (2), output (2), service (1), utility (2).
9 плагинов имеют registers.py для GUI-интеграции. 10 тестовых файлов.

4 production topology: `region_pipeline.yaml` (default), `inspection_basic.yaml`, `inspection_full.yaml`, `multi_camera.yaml`.

---

## ✅ Phase 7 — Registers v2 (ЗАКРЫТА)

**Результат:** `RegistersManagerV2` с auto-discovery из `PluginRegistry`.
`FieldInfo` — метаданные для GUI-генерации. `ConnectionMap` — маппинг wire/topology.
Методы: `from_registry()`, `from_topology()`, `get_fields()`, `get_categories()`, `set_value()`, `validate()`.
2 тестовых файла.

---

## ✅ Phase 8 — StateStore + Реактивность (ЗАКРЫТА)

**Результат:** `state/bootstrap.py` строит дерево состояния из topology YAML.
`manager_setup.py` — throttle rules. `GuiStateBindings` — glob-подписки (Qt-safe).
Дерево: `processes.{name}.{config|state}` + `system.*` + `wires.*`.
4 тестовых файла.

---

## ✅ Phase 9 — GUI Foundations (~90%)

**Результат:** MainWindow (header + ImagePanel + TabWidget + statusbar), AppContext DI,
TabFactory (lazy + custom), CardsFieldFactory + FormBuilder + RegisterView,
ThemeLoader (dark theme), GuiStateBindings, CommandSender, DataReceiverBridge.
SettingsTab — полноценный YAML-редактор с Cards/Table режимами.

**Оставшиеся мелочи Phase 9 (~10%):**
- ImagePanel: базовый multi-slot, но без GUI управления слотами
- StatusBar: FPS/latency метки, но без live-обновлений из StateStore
- Стили: базовая тёмная тема, но без полного QSS из v1

> Эти доработки можно делать параллельно с Phase 10 или в Phase 14 (Polish).

---

## ✅ Phase 10 — GUI Tabs (ЗАКРЫТА)

### Результат

Реализованы все 7 табов (Settings + 6 новых). 154 теста, ~2800 LOC.
**Архитектура: модульный конструктор** — 7 универсальных примитивов (`widgets/primitives/`) + 6 табов, каждый собран из блоков.
Каждый таб = Presenter (pure Python) + Tab (конструктор из примитивов).
Данные берутся из: topology YAML, RegistersManager, StateStore, PluginRegistry.

### Архитектура табов

```
TabFactory (tab_factory.py)
  └── custom_factories[tab_id] = lambda ctx: create_XXX_tab(ctx)

Каждый таб:
  frontend/widgets/tabs/{tab_id}/
  ├── __init__.py
  ├── tab.py          — главный виджет (собирает presenter + view)
  ├── view.py         — View Protocol + реализация (Qt виджеты)
  ├── presenter.py    — логика, работает с AppContext
  └── tests/
      └── test_{tab_id}.py
```

**Общие зависимости (уже готовы):**
- `CardsFieldFactory` → генерация форм из FieldInfo
- `RegistersManager` → данные о plugin-конфигах
- `GuiStateBindings` → реактивные обновления из StateStore
- `CommandSender` → отправка команд в runtime
- `AppContext` → DI-контейнер

### TAB_ORDER (из tab_factory.py)

```python
TAB_ORDER = [
    {"id": "settings",  "title": "Settings"},   # ✅ DONE
    {"id": "recipes",   "title": "Recipes"},     # Phase 10.1
    {"id": "processes", "title": "Processes"},    # Phase 10.2
    {"id": "services",  "title": "Services"},     # Phase 10.3
    {"id": "plugins",   "title": "Plugins"},      # Phase 10.4
    {"id": "pipeline",  "title": "Pipeline"},     # Phase 10.5
    {"id": "displays",  "title": "Displays"},     # Phase 10.6
]
```

---

### Task 10.1 — Recipes Tab (Пресеты/рецепты обработки)
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Таб управления рецептами — сохранение/загрузка конфигурации системы
**Files:**
- `multiprocess_prototype_2/frontend/widgets/tabs/recipes/` (новая папка)
  - `tab.py` — RecipesTab (MVP entry point)
  - `view.py` — RecipesView Protocol + Widget
  - `presenter.py` — RecipesPresenter
  - `recipe_card.py` — карточка рецепта (slot)
  - `tests/test_recipes.py`
- `multiprocess_prototype_2/recipes/` (новая папка)
  - `model.py` — Recipe Pydantic model
  - `storage.py` — YAML persistence (data/recipes/)
  - `manager.py` — RecipeManager (CRUD)
**Справочник v1:** `multiprocess_prototype/frontend/widgets/recipes/`
**Steps:**
1. Recipe model: `{name, description, topology_snapshot, plugin_configs, created_at, updated_at}`
2. RecipeManager: list, load, save, delete. Хранение в `data/recipes/*.yaml`
3. GUI: список слотов (8 как в v1), Load/Save/Delete/Create кнопки
4. Preview: при наведении/выборе показать topology + плагины рецепта
5. Apply = загрузить topology + подставить configs (без перезапуска в Phase 10, только сохранение)
6. Регистрация factory в TabFactory: `custom_factories["recipes"] = create_recipes_tab`
**Acceptance criteria:**
- [ ] Recipe Pydantic model + YAML storage
- [ ] RecipeManager CRUD работает
- [ ] GUI: список слотов, Load/Save/Delete
- [ ] MVP: presenter не знает о Qt, view — Protocol
- [ ] Тесты: 10+ (model, storage, presenter)
**Out of scope:** Apply с live-перезапуском (Phase 12), Undo/Redo (Phase 11)

---

### Task 10.2 — Processes Tab (Управление процессами)
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Таб мониторинга и управления процессами
**Files:**
- `multiprocess_prototype_2/frontend/widgets/tabs/processes/` (новая папка)
  - `tab.py` — ProcessesTab
  - `view.py` — ProcessesView Protocol + Widget
  - `presenter.py` — ProcessesPresenter
  - `process_card.py` — карточка процесса (статус, метрики, плагины)
  - `tests/test_processes.py`
**Справочник v1:** `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/`
**Steps:**
1. Список процессов из topology (через AppContext)
2. Для каждого процесса — карточка: имя, статус, PID, список плагинов, метрики (fps, latency, frame_count)
3. Кнопки: Start / Stop / Restart процесса → CommandSender
4. Статус обновляется реактивно из StateStore через GuiStateBindings: `processes.{name}.state.*`
5. Группировка: source processes, processing processes, output processes
6. Индикаторы: зелёный=running, серый=stopped, красный=error
**Acceptance criteria:**
- [ ] Все процессы из topology отображаются
- [ ] Статус обновляется реактивно (StateStore binding)
- [ ] Start/Stop/Restart через CommandSender
- [ ] Карточки группируются по категории плагинов
- [ ] MVP: presenter не зависит от Qt
- [ ] Тесты: 8+ (presenter logic, card rendering)
**Out of scope:** Создание/удаление процессов из GUI (Phase 12), worker tree (отдельная задача)

---

### Task 10.3 — Services Tab (Камеры, БД, робот)
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Таб управления «тяжёлыми» сервисами — камеры (backends), БД, робот, нейронки
**Files:**
- `multiprocess_prototype_2/frontend/widgets/tabs/services/` (новая папка)
  - `tab.py` — ServicesTab
  - `view.py` — ServicesView Protocol + Widget
  - `presenter.py` — ServicesPresenter
  - `camera_panel.py` — панель камеры (backend, device_id, resolution, fps)
  - `database_panel.py` — панель БД (connection, batch_size, stats)
  - `robot_panel.py` — панель робота (enabled, delay, counters)
  - `tests/test_services.py`
**Справочник v1:** `multiprocess_prototype/frontend/widgets/tabs_setting/sources_tab/`
**Steps:**
1. Presenter собирает из RegistersManager плагины категорий source, output, service
2. Секция «Камеры»: camera_service config (backend type, device, resolution, fps) через CardsFieldFactory
3. Секция «БД»: database config (path, batch_size, flush_interval)
4. Секция «Робот»: robot_control config (enabled, reject_delay, counters)
5. Секция «Нейронки»: заглушка (placeholder для Phase 14+ ML-плагинов)
6. Каждая секция = карточка, сгенерированная из registers.py плагина
**Acceptance criteria:**
- [ ] Секции для camera_service, database, robot_control
- [ ] Параметры редактируемы через CardsFieldFactory
- [ ] Нейронки — placeholder секция
- [ ] MVP pattern
- [ ] Тесты: 8+ (presenter, panel generation)
**Out of scope:** Live-команды в runtime (Phase 12), Hikvision UI (hardware-specific)

---

### Task 10.4 — Plugins Tab (Параметры обработки)
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Таб настройки processing-плагинов — аналог v1 ProcessingPanel
**Files:**
- `multiprocess_prototype_2/frontend/widgets/tabs/plugins/` (новая папка)
  - `tab.py` — PluginsTab
  - `view.py` — PluginsView Protocol + Widget
  - `presenter.py` — PluginsPresenter
  - `plugin_card.py` — карточка параметров плагина
  - `tests/test_plugins.py`
**Справочник v1:** `multiprocess_prototype/frontend/widgets/processing/`
**Steps:**
1. Presenter собирает из RegistersManager плагины категории processing + rendering + control
2. Для каждого плагина с registers.py → карточка параметров (через CardsFieldFactory)
3. Список плагинов слева, параметры справа (master-detail layout)
4. Плагины без registers.py → информационная карточка (имя, категория, описание)
5. Фильтр по категории: processing / rendering / control
6. Поиск по имени плагина
**Acceptance criteria:**
- [ ] Все плагины из PluginRegistry отображаются
- [ ] Плагины с registers → editable карточка параметров
- [ ] Плагины без registers → info карточка
- [ ] Master-detail layout
- [ ] Фильтрация по категории
- [ ] MVP pattern
- [ ] Тесты: 10+ (presenter, card factory, filtering)
**Out of scope:** Drag-and-drop плагинов (Phase 13), enable/disable плагинов в runtime

---

### Task 10.5 — Pipeline Tab (Визуальный конструктор цепочек)
**Level:** Senior (Opus/TeamLead)
**Assignee:** teamlead
**Goal:** Таб визуализации и редактирования topology — Phase 10 = read-only + базовое редактирование
**Files:**
- `multiprocess_prototype_2/frontend/widgets/tabs/pipeline/` (новая папка)
  - `tab.py` — PipelineTab
  - `view.py` — PipelineView Protocol + Widget
  - `presenter.py` — PipelinePresenter
  - `topology_graph.py` — визуализация графа процессов (QGraphicsScene)
  - `node_widget.py` — нода процесса
  - `wire_widget.py` — связь между нодами
  - `tests/test_pipeline.py`
**Справочник v1:** `multiprocess_prototype/frontend/widgets/pipeline/`, конструктор-табы
**Steps:**
1. **Phase 10 scope:** визуализация текущей topology + базовое редактирование
2. TopologyGraph: QGraphicsScene с нодами (процессы) и wire'ами (связи)
3. Каждая нода = прямоугольник с именем процесса, иконкой категории, портами in/out
4. Wire'ы = линии между портами (из topology.wires[])
5. Кнопки: Zoom In/Out, Fit to View, Validate topology
6. Интеграция с существующим TopologyEditorWidget (текстовый — для advanced users)
7. **Базовое редактирование:** добавить/удалить ноду, добавить/удалить wire
8. Export topology → YAML
**Acceptance criteria:**
- [ ] Визуализация topology как граф (ноды + wire'ы)
- [ ] Цветовая кодировка по категориям плагинов
- [ ] Zoom, pan, fit-to-view
- [ ] Добавление/удаление нод и wire'ов
- [ ] Export в YAML
- [ ] MVP pattern
- [ ] Тесты: 10+ (graph rendering, node operations, YAML export)
**Out of scope:** Drag-and-drop из палитры (Phase 13), auto-layout, live topology sync

---

### Task 10.6 — Displays Tab (Управление экранами вывода)
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Таб управления окнами/слотами отображения кадров
**Files:**
- `multiprocess_prototype_2/frontend/widgets/tabs/displays/` (новая папка)
  - `tab.py` — DisplaysTab
  - `view.py` — DisplaysView Protocol + Widget
  - `presenter.py` — DisplaysPresenter
  - `display_card.py` — карточка дисплея (source binding, size, layout)
  - `tests/test_displays.py`
**Справочник v1:** `multiprocess_prototype/frontend/widgets/tabs_setting/display_tab/`
**Steps:**
1. Список текущих DisplaySlot'ов из ImagePanel
2. Для каждого слота: имя, привязанный источник (процесс), размер, режим масштабирования
3. Добавить / удалить слот
4. Привязка слота к источнику: выпадающий список процессов из topology (category=source или output)
5. Layout: grid / single / side-by-side
6. Preview: миниатюра текущего кадра в карточке
**Acceptance criteria:**
- [ ] CRUD для display-слотов
- [ ] Привязка слота к source-процессу
- [ ] Выбор layout
- [ ] MVP pattern
- [ ] Тесты: 8+ (presenter, slot management)
**Out of scope:** DirectShow backend, multi-monitor, fullscreen mode

---

### Task 10.7 — Интеграция табов в TabFactory
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Подключить все реализованные табы через custom_factories
**Files:**
- `multiprocess_prototype_2/frontend/tab_factory.py` — обновить
- `multiprocess_prototype_2/frontend/process.py` — обновить создание factories
**Steps:**
1. Для каждого нового таба создать factory function: `create_{tab_id}_tab(ctx) → QWidget`
2. Зарегистрировать в custom_factories при инициализации GuiProcess
3. Убедиться, что LazyTabWidget корректно загружает каждый таб
4. Smoke-тест: запуск приложения → все табы доступны, переключение работает
**Acceptance criteria:**
- [ ] Все 7 табов создаются через custom_factories (не PlaceholderTab)
- [ ] Lazy-загрузка работает (таб инициализируется при первом показе)
- [ ] Переключение между табами без ошибок
- [ ] Тесты: обновить test_tab_factory.py
**Out of scope:** —

---

## ✅ Phase 11 — Recipes + Presets + Undo/Redo (ЗАКРЫТА)

### Результат

Recipe Apply (GUI-level topology swap) + ActionBus (undo/redo для ВСЕХ параметров).
TopologyHolder инжектирует topology при старте, RegisterView.field_changed — единый сигнал.
35 новых тестов, ~900 LOC.

### Архитектура

```
FieldEditor.change_signal (любой виджет в любом табе)
  → RegisterView.field_changed(register_name, field_name, old, new)
    → Tab._on_field_changed() → ActionBus.execute(Action)
      → FieldSetHandler.apply() → RegistersManager.set_field_value()
```

Undo: `ActionBus.undo()` → `FieldSetHandler.revert()` → `rm.set_field_value(old)` → editor.setter()

### Новые компоненты

| Компонент | Файл | LOC | Назначение |
|-----------|------|-----|------------|
| TopologyHolder | `frontend/topology_holder.py` | ~60 | Контейнер topology dict с callbacks |
| V2ActionBuilder | `frontend/actions/builder.py` | ~30 | recipe_apply() Action |
| FieldSetHandler | `frontend/actions/handlers/field_set_handler.py` | ~45 | apply/revert через rm.set_field_value() |
| RecipeApplyHandler | `frontend/actions/handlers/recipe_handler.py` | ~35 | apply/revert через TopologyHolder |
| bus_factory | `frontend/actions/bus_factory.py` | ~30 | create_action_bus(rm, holder) → ActionBus(max=50) |

### Модификации

- `app.py` — topology loading, ActionBus wiring, Ctrl+Z/Y
- `app_context.py` — action_bus(), topology_holder() accessors
- `register_view.py` — field_changed Signal + value tracking + set_editor_value
- `recipes/presenter.py` — fix save (TopologyHolder), add apply_recipe()
- `recipes/tab.py` — Load → apply + ActionBus.record
- `plugins/tab.py` — field_changed → ActionBus.execute
- `services/tab.py` — field_changed → ActionBus.execute
- `settings/tab.py` — field_changed → ActionBus.execute
- `windows/main_window.py` — set_action_bus(), Ctrl+Z/Y shortcuts

### Тесты

| Файл | Тестов |
|------|--------|
| `test_recipe_apply.py` | 10 |
| `test_handlers.py` | 8 |
| `test_action_bus_v2.py` | 12 |
| `test_register_view_signals.py` | 5 |
| **Итого** | **35** |

---

## ✅ Phase 12 — TopologyBridge v2 (ЗАКРЫТА)

### Результат

Единый мост GUI ↔ Runtime. 9 подзадач, 82 теста, ~770 LOC.
**Архитектура: модульный конструктор** — 5 независимых блоков (CommandCatalog, CommandValidator, CommandSender v2, TopologyBridge, state_multiplexer) собираются через DI.

### Новые компоненты

| Компонент | Файл | LOC | Назначение |
|-----------|------|-----|------------|
| CommandCatalog | `bridge/command_catalog.py` | ~190 | Каталог IPC-команд из PluginRegistry + ConnectionMap |
| CommandValidator | `bridge/command_validator.py` | ~95 | Валидация команд перед отправкой |
| CommandSender v2 | `bridge/command_sender.py` | ~130 | Debounce 50ms для slider, coalescing, flush |
| TopologyBridge | `bridge/topology_bridge.py` | ~210 | Единый мост: field_set→IPC, state_delta→rm, lifecycle |
| State multiplexer | `app.py` | ~10 | bindings + bridge.on_state_delta из одного callback |

### Модификации

- `app.py` — Phase 12 bootstrap: CommandCatalog + Validator + Bridge + multiplexer
- `app_context.py` — topology_bridge(), command_catalog() accessors
- `actions/handlers/field_set_handler.py` — опциональный bridge, notify после apply/revert
- `actions/bus_factory.py` — topology_bridge= kwarg
- `widgets/tabs/processes/tab.py` — live bindings (FPS, latency, status)
- `widgets/tabs/processes/presenter.py` — bridge.start/stop/restart
- `windows/main_window.py` — connect_bindings(), frames_label

### Тесты (82)

| Файл | Тестов |
|------|--------|
| `bridge/tests/test_command_catalog.py` | 25 |
| `bridge/tests/test_command_sender.py` | 13 |
| `bridge/tests/test_command_validator.py` | 11 |
| `bridge/tests/test_topology_bridge.py` | 21 |
| `actions/tests/test_bridge_integration.py` | 7 |
| `tests/test_phase12_integration.py` | 5 |

### Архитектура

```
GUI (user edit) → TopologyBridge → IPC Command → Target Process → Plugin
                                                                    ↓
GUI (state update) ← StateProxy ← StateStore ← Process ← Plugin state
```

### Task 12.1 — Command Protocol v2
**Level:** Senior (Opus/TeamLead)
**Assignee:** teamlead
**Goal:** Формализованный протокол команд для управления плагинами через GUI
**Steps:**
1. Command = {target_process, plugin_name, command_id, args}
2. Каталог автогенерируется: PluginRegistry → plugin.commands → catalog
3. CommandSender (уже есть) → расширить валидацией и батчингом
**Acceptance criteria:**
- [ ] Каталог команд из плагинов
- [ ] Валидация команд
- [ ] Тесты: 10+

### Task 12.2 — TopologyBridge v2
**Level:** Senior+ (Opus/TeamLead)
**Assignee:** teamlead
**Goal:** Единый мост GUI → Runtime
**Steps:**
1. RegistersManager changes → команды через CommandSender
2. Topology changes (add/remove process) → lifecycle команды
3. StateStore changes → GUI widget updates
4. Debounce для slider dragging
**Acceptance criteria:**
- [ ] Параметр в GUI → процесс получает команду
- [ ] State update → GUI обновляется
- [ ] Debounce ≤50ms
- [ ] Тесты: 15+

### Task 12.3 — Reactive State Subscriptions (Live)
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Live-обновление виджетов из StateStore
**Steps:**
1. GuiStateBindings (уже есть) → подключить к реальным TabWidget'ам
2. Processes tab: fps, latency, status — live
3. Services tab: camera stats, DB counters — live
4. StatusBar: system fps, total frames — live
**Acceptance criteria:**
- [ ] Все метрики обновляются в реальном времени
- [ ] Thread-safe (Qt QueuedConnection)
- [ ] Тесты: 8+

---

## ✅ Phase 12.5 — TopologyBridge Runtime (ЗАКРЫТА)

### Цель

Расширить bridge до **полноценного runtime-моста**: hot_add/remove процессов, wire management (SHM), diff-based topology apply. После Phase 12.5 — **любой таб** может управлять runtime через единый bridge API.

**Подробная спека:** [`plans/PHASE_12_5.md`](plans/PHASE_12_5.md)

### Новые модули (конструктор)

```
bridge/
├── diff_engine.py      ← ЧТО изменилось?  (old, new → TopologyDiff)
├── wire_protocol.py    ← КАК описать wire? (WireConfig, ShmConfig, validate)
├── system_commands.py  ← КАКУЮ IPC-команду? (build_hot_add, build_wire_setup)
└── topology_bridge.py  ← КООРДИНАЦИЯ       (diff → commands → sender)
```

### Задачи

| Task | Название | Level | LOC |
|------|---------|-------|-----|
| 12.4 | TopologyDiffEngine | Middle+ | ~150 |
| 12.5 | WireProtocol + SystemCommands | Middle+ | ~250 |
| 12.6 | TopologyBridge Runtime Extensions | Senior | ~270 |
| 12.7 | WireStatusMonitor | Middle+ | ~150 |

### Порядок

```
Wave 1 (параллельно):
  ├── Task 12.4 TopologyDiffEngine
  ├── Task 12.5 WireProtocol + SystemCommands
  └── Task 12.7 WireStatusMonitor

Wave 2 (зависит от Wave 1):
  └── Task 12.6 TopologyBridge Runtime Extensions
```

### Что это даёт Phase 13

- **Task 13.10 (Live sync) — УДАЛЕНА** — hot_add/hot_remove уже в bridge
- **Task 13.1a упрощается** — TopologyMutationHandler вызывает `bridge.apply_topology_diff()`
- **Task 13.4 (wire creation) — end-to-end** — `bridge.connect_wire()` → SHM в runtime + мониторинг
- **Pipeline statusbar** — `wire_monitor.summary()` → "3 active, 0 broken"

---

## ✅ Phase 13 — Pipeline Editor Enhanced (ЗАКРЫТА)

### Результат

Pipeline Tab → полноценный визуальный конструктор. 12 задач, 4 волны, 181 тест, ~2500 LOC.

**Подробный план:** [`~/.claude/plans/synchronous-munching-charm.md`]

### Новые компоненты

| Компонент | Файл | LOC | → Framework? |
|-----------|------|-----|-------------|
| dag_utils | `pipeline/dag_utils.py` | ~80 | **✓ сразу** (0 deps) |
| SugiyamaLayout | `pipeline/layout.py` | ~200 | **✓ сразу** (generic API) |
| PipelineModel | `pipeline/model.py` | ~200 | ✓ после стабилизации |
| TopologyMutationHandler | `actions/handlers/topology_mutation_handler.py` | ~80 | ✓ generic |
| NodeMoveHandler | `actions/handlers/node_move_handler.py` | ~60 | ✓ generic |
| PortItem | `pipeline/graph/port_item.py` | ~80 | ✓ universal |
| TempWireItem | `pipeline/graph/temp_wire.py` | ~60 | ✓ universal |
| PluginPalette | `pipeline/palette/` | ~230 | Base → FW, domain → proto |
| NodeInspectorPanel | `pipeline/inspector/` | ~170 | Base → FW, domain → proto |
| Enhanced Presenter | `pipeline/presenter.py` | ~270 | Прототип-specific |
| PipelineTab | `pipeline/tab.py` | ~150 | Прототип-specific |
| Context menus | `pipeline/graph/graph_scene.py` | ~80 | Signals → FW |

### Ключевые архитектурные решения
1. **Трёхслойная архитектура:** dag_utils (0 deps) → PipelineModel → SugiyamaLayout
2. **Signal suppression** (из v1) — `_block_signals()` context manager
3. **ActionBus unified** — все мутации через undo/redo
4. **Graceful degradation** — без bridge = GUI-only mode
5. **Wire creation end-to-end** — PortItem → TempWireItem → Model → ActionBus → Bridge

---

## ✅ Phase 14 — Schema Ports + Inspector + Safe FW Extraction (ЗАКРЫТА)

### Результат

Фичи + безопасная экстракция. 4 задачи, 94 новых теста, ~910 LOC.
Стратегия изменена по сравнению с первоначальным планом: вместо полной экстракции (5 задач, ~1180 LOC) — сначала фичи, потом только бесспорно generic код. GraphModel base, PortItem/TempWireItem в FW, BasePalette/GenericDropTarget — отложены до Phase 16 (второй consumer).

### Новые компоненты

| Компонент | Файл | LOC | Тип |
|-----------|------|-----|-----|
| PortSchema | `pipeline/graph/port_schema.py` | ~30 | Фича |
| validate_port_compatibility (dtype) | `dag_utils.py` | ~40 | Фича |
| Inspector + CardsFieldFactory | `inspector/inspector_panel.py` | ~120 | Фича |
| dag_utils (FW) | `frontend_module/graph/dag_utils.py` | ~120 | Extraction |
| layout (FW) | `frontend_module/graph/layout.py` | ~280 | Extraction |
| TopologyMutationHandler (FW) | `frontend_module/actions/handlers/topology_handler.py` | ~80 | Extraction |
| NodeMoveHandler (FW) | `frontend_module/actions/handlers/move_handler.py` | ~60 | Extraction |
| Protocol-заглушки (FW) | `topology_handler.py` | ~20 | Extraction |

### Подробный план
[`plans/PHASE_14.md`](plans/PHASE_14.md)

### Тесты (94 новых)

| Файл | Тестов |
|------|--------|
| `test_schema_driven_ports.py` | 28 |
| `test_inspector.py` (новые) | 13 |
| FW `test_dag_utils.py` | 19 |
| FW `test_layout.py` | 12 |
| FW `test_topology_handler.py` | 8 |
| FW `test_move_handler.py` | 6 |
| **+ 8 FW init/import** | 8 |

### Архитектурные решения
1. **Фичи перед экстракцией** — Schema Ports и Inspector улучшают прототип сразу, экстракция идёт потом
2. **Re-exports** — `pipeline/dag_utils.py` и `pipeline/layout.py` стали thin re-exports из FW
3. **Protocol isolation** — FW handlers используют `TopologyHolderProtocol`/`TopologyBridgeProtocol` вместо прямых импортов прототипа
4. **Отложенная экстракция** — GraphModel base, PortItem/TempWireItem, BasePalette/GenericDropTarget → Phase 16 (когда появится второй consumer)

---

## ✅ Phase 15 — Production Ready (ЗАКРЫТА)

### Результат

Стабильность, UX, документация, onboarding. 7 задач, 3 волны, ~1100 LOC + ~900 строк docs.
Единый паттерн: все компоненты используют FW-менеджеры (LoggerManager, ErrorManager, StatsManager) через ObservableMixin.

### Новые компоненты

| Компонент | Файл | LOC | Назначение |
|-----------|------|-----|------------|
| ErrorBannerWidget | `widgets/chrome/error_banner.py` | ~80 | Баннер ошибок (max 3, dismiss, FIFO) |
| StartupChecker | `frontend/startup_checks.py` | ~90 | Валидация topology/plugins при старте |
| Health Dashboard | `widgets/tabs/processes/tab.py` | +50 | Сводка: total/active/broken/fps |
| hello_world.yaml | `topology/hello_world.yaml` | ~30 | Минимальная topology |
| TEMPLATE.yaml | `topology/TEMPLATE.yaml` | ~60 | Комментированный шаблон |
| README.md | `multiprocess_prototype_2/README.md` | ~370 | Quick start + структура |
| ARCHITECTURE.md | `multiprocess_prototype_2/ARCHITECTURE.md` | ~530 | Полная архитектура |

### Модификации

- `frontend/process.py` — exponential backoff в data_receiver_loop (+40 LOC)
- `frontend/app.py` — StartupChecker интеграция (+15 LOC)
- `frontend/windows/main_window.py` — ErrorBanner + bindings (+20 LOC)
- `frontend/widgets/tabs/processes/presenter.py` — get_health_summary() (+30 LOC)

### Тесты (63 новых)

| Файл | Тестов |
|------|--------|
| `chrome/tests/test_error_banner.py` | 7 |
| `tests/test_gui_process.py` (recovery) | 5 |
| `topology/tests/test_topology_schemas.py` | 26 |
| `tests/test_startup_checks.py` | 10 |
| `processes/tests/test_health_summary.py` | 6 |
| `tests/test_phase15_smoke.py` | 3 |
| **+ topology test init** | 6 |

### Архитектурные решения

1. **FW Manager pattern** — все новые компоненты используют `_log_info/_track_error/_record_metric` через ObservableMixin, НЕ `logging.getLogger()`
2. **ErrorBanner = passive** — только отображает, источник — state_delta из ErrorManager
3. **StartupChecker = pure Python** — без Qt, тестируется без pytest-qt
4. **Exponential backoff** — 0.1s → 5.0s cap, сброс при успехе, threshold для CRITICAL
5. **Health Dashboard** — начальные значения из topology, live-обновления через GuiStateBindings

---

## Архитектура конструктора (после Phase 14)

```
┌─────────────────────────────────────────────────────────┐
│  multiprocess_framework  (КОНСТРУКТОР — generic)         │
│                                                          │
│  modules/                                                │
│  ├── process_module      ← GenericProcess, Plugin API    │
│  ├── shared_resources    ← SHM, MessageAdapter           │
│  ├── state_store         ← StateStoreManager, StateProxy │
│  ├── config_module       ← ConfigStore, SchemaBase       │
│  ├── chain_module        ← DAG/Chain engine              │
│  └── frontend_module     ← ВЕСЬ generic GUI              │
│       ├── actions/       ← ActionBus, handlers, builder  │
│       ├── graph/         ← dag_utils, layout, ports      │
│       ├── dnd/           ← drop_target                   │
│       ├── forms/         ← CardsFieldFactory, FormBuilder │
│       ├── widgets/       ← BasePalette, BaseInspector    │
│       └── bridges/       ← TopologyBridge, CommandSender  │
└─────────────────────────────────────────────────────────┘
                           ↓ использует
┌─────────────────────────────────────────────────────────┐
│  multiprocess_prototype_2  (ПРОТОТИП — domain-only)      │
│                                                          │
│  plugins/     ← 21 плагин (business logic)               │
│  registers/   ← Pydantic schemas (config_schema)         │
│  topology/    ← YAML blueprints                          │
│  frontend/                                               │
│    ├── app.py            ← bootstrap (собирает FW-блоки) │
│    ├── app_context.py    ← DI (wiring)                   │
│    └── widgets/tabs/     ← 7 табов                       │
│         └── каждый таб = Presenter + View из FW-блоков   │
└─────────────────────────────────────────────────────────┘
```

**Новый прототип (другой домен) = только:**
1. `plugins/` — доменные плагины
2. `registers/` — Pydantic schemas
3. `topology/*.yaml` — конфиг системы
4. `frontend/app.py` — bootstrap из FW-блоков
5. `frontend/widgets/tabs/` — доменные табы (optional)

**Фреймворк даёт "из коробки":**
- Процессы, SHM, IPC, StateStore, Config
- GUI: forms, actions/undo, graph editor, palette, inspector, bridges
- Pipeline: DAG validation, Sugiyama layout, wire management

---

## Зависимости между фазами

```
Phase 6-8 (DONE) → Phase 9 (~90%) → Phase 10 (DONE) → Phase 11 (DONE) → Phase 12 (DONE)
                                                                                    ↓
                                                                              Phase 12.5 (DONE)
                                                                                    ↓
                                                                              Phase 13 (DONE)
                                                                                    ↓
                                                                              Phase 14 (DONE)
                                                                                    ↓
                                                                              Phase 15 (DONE) ← ВСЕ ФАЗЫ ЗАКРЫТЫ
```

---

## Оценка объёма

| Фаза | Задач | Статус | Примерно строк |
|------|-------|--------|---------------|
| Phase 6 (Plugins) | 10 | ✅ DONE | ~4000 |
| Phase 7 (Registers) | 3 | ✅ DONE | ~350 |
| Phase 8 (StateStore) | 3 | ✅ DONE | ~500 |
| Phase 9 (GUI Foundation) | 4 | ✅ ~90% | ~2500 |
| Phase 10 (GUI Tabs) | 7 | ✅ DONE | ~2800 |
| Phase 11 (Recipes/Undo) | 2 | ✅ DONE | ~900 |
| Phase 12 (TopologyBridge) | 9 | ✅ DONE | ~770 |
| Phase 12.5 (Bridge Runtime) | 4 | ✅ DONE | ~820 |
| Phase 13 (Pipeline Editor) | 12 | ✅ DONE | ~2500 |
| Phase 14 (FW Extraction) | 4 | ✅ DONE | ~910 |
| Phase 15 (Production Ready) | 7 | ✅ DONE | ~1100 + ~900 md |
| **Итого** | **66** | **100%** | **~18150** |

---

## Ключевые отличия от v1

| Аспект | v1 | v2 |
|--------|-----|-----|
| Процессы | Хардкод-классы (7 штук) | GenericProcess для всего |
| Плагины | ProcessModule + Service + Adapter (~500 строк) | Plugin `process(items)→items` (~50-150 строк) |
| Регистры | 6 ручных регистров | Автогенерация из plugin config_schema |
| Формы GUI | CardsFieldFactory по регистрам | CardsFieldFactory по Pydantic schema |
| Транспорт GUI→Backend | 3 транспорта (IPC + FieldRouting + DirectAPI) | 1 транспорт (IPC commands) |
| Topology | В коде (default_system.py) | В YAML (topology/*.yaml) |
| Расширение | Новый класс + сервис + адаптер + регистр | Новый plugin.py + строка в YAML |
| Рецепты | Отдельная система | Snapshot topology + configs |
