# Phase 9: Pipeline Builder — DAG-конструктор на NodeGraphQt (hybrid)

## Context

Inspector_bottles прошёл Phase 0–8. На сегодня:
- Камеры, регионы, базовая обработка работают (Phase 0–4).
- Модель `ProcessingNode` + каталог YAML + chain executor + cross-process workers есть (Phase 5a–5c).
- Собственный node-editor на 2500 LOC (`frontend/widgets/graph_editor/`) уже зрелый — Sugiyama auto-layout, type-validation, ActionBus undo/redo, two-view, тесты в `test_graph_actions.py` (Phase 8).
- PySide6 миграция в активном `multiprocess_prototype` завершена.
- Фреймворк подготовлен: `RouterManager` с динамическими каналами и broadcast, `ProcessRegistry.create_and_register()`, `DisplayRouter` с lazy SHM, `DisplayWindowManager` с реестром окон.

Пользователь хочет финальную сборку: единая вкладка «Pipeline» — модульный DAG-конструктор, библиотека блоков, two-view (граф ↔ таблица), узлы раскладываются по процессам через `process_id`, edges физически = router channels, live-preview thumbnail внутри ноды + опционально в DisplayWindow, всё это часть Recipe.

**Решение по UI-движку:** заменяем рисовку в собственном editor на **NodeGraphQt-PySide6 fork (C3RV1)**, но в **гибридном режиме** — NodeGraphQt берёт только отрисовку нод/портов/edges; вся бизнес-логика (GraphEditorModel, ActionBus, Sugiyama, type-validation, сериализация через Pipeline-Pydantic) остаётся нашей. Это исключает риск Issue #491 (плохая сериализация custom-widget'ов в NodeGraphQt) и сохраняет все тесты.

**Live-preview thumbnail** в каждой ноде — реализуется через subclass `BaseNode` с overlay QPixmap, подписка на DisplayRouter-канал с lazy SHM (нет подписчика — нет encode).

---

## Approach (Hybrid Architecture)

```
┌─────────────────────────────────────────────────────────────┐
│                  Pipeline Tab (PySide6)                      │
│  ┌─────────────┬───────────────────────────┬─────────────┐  │
│  │  Library    │   NodeGraphQt canvas      │  Inspector  │  │
│  │  (palette)  │   (наш custom BaseNode    │  (params,   │  │
│  │  категории  │    с thumbnail overlay)   │  process_id,│  │
│  │             │   ───── view_switch ──────│  displays)  │  │
│  │             │   QTreeView (table view)  │             │  │
│  └─────────────┴───────────────────────────┴─────────────┘  │
└──────────────┬──────────────────────────────────────────────┘
               │ signals (port_connected, node_created, ...)
               ▼
┌─────────────────────────────────────────────────────────────┐
│         NodeGraphQtAdapter (новый, тонкий слой)              │
│  - переводит NodeGraphQt-сигналы в Action-команды            │
│  - конвертирует ProcessingNode ↔ BaseNode-subclass           │
│  - применяет Sugiyama-координаты к NodeGraphQt-нодам         │
└──────────────┬──────────────────────────────────────────────┘
               │ Action.execute()
               ▼
┌─────────────────────────────────────────────────────────────┐
│   Бизнес-логика (БЕЗ изменений из текущего graph_editor):    │
│   - GraphEditorModel (model.py)                              │
│   - ActionBus + GraphActionHandler (undo/redo)               │
│   - linearity_check.py                                       │
│   - auto_layout.py (Sugiyama)                                │
│   - are_ports_compatible (type-validation)                   │
│   - Pipeline (Pydantic, single source of truth)              │
└──────────────┬──────────────────────────────────────────────┘
               │ Pipeline.to_router_topology()
               ▼
┌─────────────────────────────────────────────────────────────┐
│   Runtime: RouterManager + ProcessRegistry + DisplayRouter   │
│   (фреймворк, без изменений)                                 │
└─────────────────────────────────────────────────────────────┘
```

**Что меняем:**
- Удаляем: `node_item.py`, `port_item.py`, `edge_item.py`, `provisional_edge.py`, `graph_view.py`, `graph_scene.py` (рендеринг → NodeGraphQt).
- Сохраняем: `model.py`, `linearity_check.py`, `auto_layout.py`, `catalog_palette.py`, `constants.py`, `context_menu.py`, `view_switch.py` (адаптируется).
- Добавляем: `NodeGraphQtAdapter`, custom `InspectorBaseNode` с thumbnail overlay, `pipeline_tab/` директория.

---

## Tasks

### Task 9.0 — Установка NodeGraphQt-PySide6

**Уровень:** Junior (Haiku)
**Файлы:** `pyproject.toml`
**Шаги:**
1. Добавить зависимость: `NodeGraphQt-PySide6` (fork от C3RV1) через `[project.dependencies]`.
2. `uv sync` в `Inspector_bottles/`.
3. Smoke-test: импорт `from NodeGraphQt import NodeGraph, BaseNode` без ошибок.

**Acceptance:**
- [ ] `python -c "from NodeGraphQt import NodeGraph"` работает.
- [ ] `python scripts/validate.py` зелёный.

---

### Task 9.1 — DataType enum + is_compatible

**Уровень:** Middle (Sonnet)
**Файлы (новые):**
- `multiprocess_prototype/registers/pipeline/types.py`
- `tests/registers/test_data_types.py`

**Содержимое:** `DataType` enum (BGR_IMAGE, GRAYSCALE, BINARY_MASK, BBOX_LIST, KEYPOINTS, CONTOURS, SCALAR, STRING, DICT, TENSOR, ANY), `is_compatible(out, in)`, `_COMPATIBLE_PAIRS`.

**Reuse:** взять паттерн из `projects/Sketch_robot/sketch_robot/core/module_base.py` (DataType + is_compatible). Уже существующая `are_ports_compatible` в `registers/processor/catalog/port_types.py` — расширить, не дублировать.

**Acceptance:**
- [ ] 11 типов перечислены, ANY совместим со всеми, GRAYSCALE↔BINARY_MASK совместимы, BBOX_LIST≠BGR_IMAGE.
- [ ] Round-trip serialization.

---

### Task 9.2 — PortDef + расширение ProcessingOperationDef

**Уровень:** Middle (Sonnet)
**Файлы (изменить):**
- `multiprocess_prototype/registers/processor/catalog/schemas.py` — добавить `PortDef`, `category`, `input_ports: List[PortDef]`, `output_ports: List[PortDef]`, `multiplicity: Literal["fixed","dynamic"]`, `display_capable: bool` в `ProcessingOperationDef`.
- `multiprocess_prototype/data/processing_catalog.yaml` — обновить существующие 2 операции (color_detection, blob_detection) под новый формат.

**Acceptance:**
- [ ] Round-trip с новыми полями.
- [ ] Старые YAML без новых полей читаются (defaults).
- [ ] Тест: `multiplicity=dynamic` валидируется.

---

### Task 9.3 — Расширение ProcessingNode + Pipeline.validate_graph

**Уровень:** Senior (Opus, teamlead)
**Файлы (изменить):**
- `multiprocess_prototype/registers/pipeline/processing_node.py` — `outputs: List[NodeOutput]`, `display_targets: List[str]`, `channel_prefix: Optional[str]`.
- `multiprocess_prototype/registers/pipeline/schemas.py` — `Pipeline.validate_graph() -> List[ValidationError]` (циклы, type-mismatch, недостижимые узлы).
- `tests/registers/test_pipeline_validation.py`.

**Reuse:** `linearity_check.py` (DFS для cycles). `are_ports_compatible` для type-проверки.

**Acceptance:**
- [ ] Цикл A→B→A детектится.
- [ ] Type-mismatch на edge детектится с указанием порта.
- [ ] Round-trip serialization.

---

### Task 9.4 — Базовая библиотека операций (Input + ROI + Preprocess)

**Уровень:** Middle+ (Sonnet)
**Файлы (новые):**
- `multiprocess_prototype/services/processor/operations/input/{webcam,hikvision,file,simulator}_input.py` — обёртки над `services/camera/backends.py`.
- `multiprocess_prototype/services/processor/operations/roi/region_splitter.py` (1→N, multiplicity=dynamic).
- `multiprocess_prototype/services/processor/operations/preprocess/{resize,color_convert,clahe,blur,threshold}.py`.
- `multiprocess_prototype/data/processing_catalog.yaml` — добавить операции с категориями и портами.

**Reuse:** `services/camera/backends.py` (BaseCaptureBackend, SimulatorBackend, WebcamBackend, HikvisionBackend, FileSourceBackend).

**Acceptance:**
- [ ] Каждая операция реализует Protocol из Phase 5a.
- [ ] Smoke-test: pipeline `WebcamInput → Resize → CLAHE → DisplayOutput` валидируется.

---

### Task 9.5 — Pipeline.to_router_topology + ChainBuilder integration

**Уровень:** Senior+ (Opus, teamlead)
**Файлы (новые):**
- `multiprocess_prototype/services/processor/topology/builder.py` — `RouterTopology` dataclass + `to_router_topology(pipeline)`.
- `multiprocess_prototype/services/processor/topology/registrar.py` — `apply_topology(router, topology)` (динамическая регистрация каналов).

**Файлы (изменить):**
- `multiprocess_prototype/services/processor/service.py` — `rebuild_runnables` использует topology.
- `multiprocess_prototype/backend/processes/processor/process.py` — на старте читает topology.

**Reuse:** `RouterManager.register_channel`, `register_broadcast_route`, `connection_map`. См. `multiprocess_framework/router_module/`.

**Acceptance:**
- [ ] Каналы named `{node_id}.{port_name}` (или `{channel_prefix}.{port_name}`).
- [ ] Edge → `connection_map` запись.
- [ ] Fan-out → `register_broadcast_route`.
- [ ] Edge удалён → канал unregister'ится без рестарта процесса.
- [ ] DAG из 4 нод поднимается и крутится 5 секунд.

---

### Task 9.6 — Cross-process топология + динамические процессы

**Уровень:** Senior+ (Opus, teamlead)
**Файлы (изменить):**
- `multiprocess_prototype/services/processor/topology/{builder,registrar}.py` — группировка по `process_id`, маркировка cross-process edges, использование SHM (`FrameShmMiddleware`) для тяжёлых данных.
- `multiprocess_prototype/config/app.py` — `AppConfig` принимает topology, динамически разворачивает `processors[]`.
- `multiprocess_prototype/backend/processes/processor_worker/process.py` — поддержка произвольной операции из каталога.

**Reuse:** `ProcessRegistry.create_and_register` (multiprocess_framework/process_manager_module/), `FrameShmMiddleware`, `RingBufferWriter`.

**Acceptance:**
- [ ] DAG с нодами в разных `process_id` стартует.
- [ ] Cross-process edge передаёт BGR_IMAGE через SHM (не pickle).
- [ ] Изменение `process_id` ноды → graceful rebuild без потери остального графа.

---

### Task 9.7 — NodeGraphQtAdapter (ядро hybrid-подхода)

**Уровень:** Senior+ (Opus, teamlead)
**Файлы (новые):**
- `multiprocess_prototype/frontend/widgets/pipeline_tab/__init__.py`
- `multiprocess_prototype/frontend/widgets/pipeline_tab/adapter.py` — `NodeGraphQtAdapter`:
  - `__init__(self, graph: NodeGraph, model: GraphEditorModel, action_bus: ActionBus, catalog: dict)`
  - `load_pipeline(pipeline: Pipeline)` — переводит Pipeline → NodeGraphQt-сцену.
  - `_on_port_connected(in_port, out_port)` → проверяет `are_ports_compatible`, при failure отменяет соединение и шлёт notification; при success → `action_bus.execute(graph_connect_action)`.
  - `_on_port_disconnected` → `action_bus.execute(graph_disconnect_action)`.
  - `_on_node_created` (drop из палитры) → `action_bus.execute(graph_create_action)`.
  - `_on_node_deleted`, `_on_node_moved` (с coalescing для drag).
  - `apply_layout(positions)` — после Sugiyama применяет координаты к NodeGraphQt-нодам через `node.set_pos()`.

**Reuse:** существующий `model.py` (GraphEditorModel), `ActionBus` + `GraphActionHandler`, `auto_layout.py` (Sugiyama), `linearity_check.py`, `are_ports_compatible`.

**Acceptance:**
- [ ] Создание ноды в NodeGraphQt → ProcessingNode появляется в Pipeline.
- [ ] Удаление edge → исчезает из Pipeline и из RouterTopology.
- [ ] Несовместимый порт-коннект отменяется до создания edge.
- [ ] Undo/redo работает (тесты `test_graph_actions.py` зелёные).

---

### Task 9.8 — InspectorBaseNode с live-preview thumbnail

**Уровень:** Senior+ (Opus, teamlead)
**Файлы (новые):**
- `multiprocess_prototype/frontend/widgets/pipeline_tab/inspector_node.py` — `InspectorBaseNode(BaseNode)`:
  - Subclass NodeGraphQt `BaseNode`.
  - Override `paint()` или встраивание `QGraphicsPixmapItem` под заголовок для thumbnail.
  - `update_thumbnail(pixmap: QPixmap)` — slot для обновления превью.
  - `set_active_preview(active: bool)` — включает/выключает preview без destroy.

- `multiprocess_prototype/frontend/widgets/pipeline_tab/preview_bridge.py` — `NodePreviewBridge`:
  - Подписывается на DisplayRouter-канал `node_preview.{node_id}`.
  - При получении кадра → масштабирует до 160×120 → emits Qt signal → `InspectorBaseNode.update_thumbnail`.
  - Lazy: не подписывается если нода не в видимой области (viewport culling) или если node не помечена как `display_capable`.

**Файлы (изменить):**
- `multiprocess_prototype/services/renderer/display_router.py` — `is_anyone_subscribed(channel)` API.
- `multiprocess_prototype/services/processor/operations/base.py` — `should_emit_preview(ctx) -> bool` чек перед encode (не платим CPU если нет подписчика).

**Reuse:** `DisplayRouter` callback-mechanism, lazy SHM в `DisplayWindowManager`, `SourceSelectorCombo` (расширим под node-output).

**Acceptance:**
- [ ] Каждая нода в графе показывает thumbnail (после старта pipeline).
- [ ] Нода вне viewport не получает frame (нет CPU-нагрузки).
- [ ] Изменение `display_capable=False` в каталоге убирает thumbnail.
- [ ] FPS thumbnail throttled до 5–10 (не 30+) — экономия CPU.

**Risk note:** custom rendering в NodeGraphQt ограничено (см. Issue #491). Если override `paint()` ломает встроенные фичи (selection highlight, hover), — fallback к `QGraphicsPixmapItem` поверх `BaseNode` через `add_widget()` API.

---

### Task 9.9 — Library palette (категории + drag-drop)

**Уровень:** Middle (Sonnet)
**Файлы (изменить):**
- `multiprocess_prototype/frontend/widgets/graph_editor/catalog_palette.py` — переехать в `pipeline_tab/library_palette.py`, адаптировать MIME-drop под NodeGraphQt scene.
- `multiprocess_prototype/frontend/widgets/pipeline_tab/library_palette.py` — раскрывающиеся группы по `category`, drag → drop в `NodeGraph.widget`.

**Reuse:** существующая `catalog_palette.py` (122 LOC), её drag-drop MIME логика. `ProcessingOperationDef.category` (Task 9.2).

**Acceptance:**
- [x] 7 категорий (Input/ROI/Preprocess/Detect/Measure/Logic/Output) отображаются.
- [x] Drag из палитры → drop на canvas → `_on_node_created` вызывается → ProcessingNode добавлен в Pipeline.
- [x] Фильтр по тексту работает (наследуется из старой реализации).

**Реализация (commit pending):**
- `pipeline_tab/library_palette.py` — `LibraryPalette` (QTreeWidget с категориями, фиксированный порядок CATEGORY_ORDER, фильтр по name/description/type_key, pruning пустых категорий) + `LibraryDropTarget` (eventFilter на `graph.viewer().viewport()`, парсит MIME → `mapToScene()` → `callback(op_ref, scene_pos)`).
- Контракт callback: `add_node_from_catalog(op_ref, position)` уже есть в адаптере (Task 9.7).
- Тесты: `tests/unit/test_phase9_library_palette.py` (15 кейсов: категории, порядок, pruning, плейсхолдер, фильтр, MIME-приём/отказ, scene-pos, исключения callback, idempotent detach) — все зелёные.
- `validate.py` зелёный.

---

### Task 9.10 — Inspector panel (params + process_id + display_targets)

**Уровень:** Middle (Sonnet)
**Файлы (новые):**
- `multiprocess_prototype/frontend/widgets/pipeline_tab/inspector_panel.py` — `QFormLayout` авто-сгенерированный из `ProcessingOperationDef.params_schema`.
- `multiprocess_prototype/frontend/widgets/pipeline_tab/process_id_combo.py` — выбор процесса (existing + create new).
- `multiprocess_prototype/frontend/widgets/pipeline_tab/display_target_combo.py` — multi-select дисплеев (с опцией «+ новый дисплей»).

**Reuse:** `params_schema` из `ProcessingOperationDef` (есть с Phase 5a). `DisplayWindowManager._windows` как источник списка дисплеев. **Не использовать встроенный NodeGraphQt PropertiesBinWidget** — у нас сложнее логика и риск Issue #491.

**Acceptance:**
- [x] int/float/bool/choice виджеты генерируются автоматически.
- [x] Изменение → mutates `ProcessingNode.params` через ActionBus → reactive update topology.
- [x] Multi-select displays корректно сериализуется в `display_targets`.

**Реализация (Task 9.10):**
- Новый `ActionType.GRAPH_NODE_MODIFY` + `ActionBuilder.graph_node_modify()` с patch-форматом `{node_id, fields_before, fields_after, nodes_before/after}`.
- `GraphEditorModel.modify_node(node_id, fields)` — whitelist полей, merge для `params`, replace для остальных.
- `GraphActionHandler` расширен: apply/revert для GRAPH_NODE_MODIFY пишет `nodes_after/nodes_before` в register через `rm.set_field_value`.
- `ParamsForm` — авто-генерация виджетов из Pydantic-модели: int→QSpinBox, float→QDoubleSpinBox, bool→QCheckBox, Literal→QComboBox, List[int] len=3→3 QSpinBox.
- `ProcessIdCombo` — комбобокс с sentinel «+ Новый процесс...» + QInputDialog.
- `DisplayTargetCombo` — QToolButton с popup QMenu + чекбоксы + sentinel «+ Новый дисплей...».
- `InspectorPanel` — composition из 3 секций, подписка на ActionBus change_callback для undo/redo refresh.
- Тесты: 31 кейс в `test_phase9_inspector_panel.py` — все зелёные.
- `validate.py` зелёный, существующие Phase 9 тесты не сломаны.

---

### Task 9.11 — Two-view sync (Graph ⇄ Table)

**Уровень:** Middle+ (Sonnet)
**Файлы (изменить):**
- `multiprocess_prototype/frontend/widgets/graph_editor/view_switch.py` — переехать в `pipeline_tab/view_switch.py`, адаптировать (graph mode = NodeGraph.widget вместо GraphScene+GraphView).

**Файлы (новые):**
- `multiprocess_prototype/frontend/widgets/pipeline_tab/table_view.py` — `QTreeView` с моделью Camera→Region→Node. Bulk-edit `process_id`, `enabled`, `display_targets`.

**Reuse:** существующий `view_switch.py` (172 LOC), `linearity_check.py` (предупреждение для нелинейного графа в табличном виде).

**Acceptance:**
- [x] Изменение в graph → отражается в table (через ActionBus change_callback → refresh).
- [x] Bulk-edit `process_id` в таблице → обновляет graph (N GRAPH_NODE_MODIFY actions).
- [x] Переключение view не теряет выделение узла (_selected_node_id синхронизируется).

**Реализация (Task 9.11, commit pending):**
- `pipeline_tab/table_view.py` — `PipelineTableView` (QTreeView flat, 6 колонок, bulk-edit enabled/process_id через N GRAPH_NODE_MODIFY actions, linearity warning, ActionBus change_callback → refresh, selection sync).
- `pipeline_tab/view_switch.py` — `PipelineViewSwitch` (QToolButton toggle, QStackedWidget graph/table, selection_changed unified signal, sync при switch_to через adapter.node_map и table.select_node).
- `pipeline_tab/__init__.py` — добавлены `PipelineTableView`, `PipelineViewSwitch` в публичный API.
- Тесты: 30 кейсов в `test_phase9_two_view.py` — все зелёные.
- `validate.py` зелёный, регрессия Phase 9 не сломана (70/70).

---

### Task 9.12 — Pipeline в Recipe + миграция legacy формата

**Уровень:** Middle (Sonnet)
**Файлы (изменить):**
- `multiprocess_prototype/state_store/recipes/recipe_engine.py` — добавить `pipeline_graph` в `DEFAULT_CONFIG_PATHS`.

**Файлы (новые):**
- `multiprocess_prototype/state_store/recipes/migrations/v1_to_v2.py` — конвертер старых рецептов с `processing_blocks` → `nodes`.

**Reuse:** `RecipeEngine` snapshot/restore (state_store/recipes/recipe_engine.py:78-100).

**Acceptance:**
- [x] Сохранение/загрузка рецепта с DAG round-trip.
- [x] Старый рецепт автоматически мигрируется при load, backup `.bak` создаётся.

**Реализация (commit 9.12)**

Уточнение по сравнению с исходным планом: `pipeline_graph` как отдельная ветка **не добавлялась** в `DEFAULT_CONFIG_PATHS` — DAG (cameras.*.regions.*.nodes) уже сохраняется автоматически через ветку `cameras`. Вместо этого добавлен integration-тест round-trip Pipeline через cameras-ветку.

Что сделано:
- Новый пакет `state_store/recipes/migrations/` с модулем `v1_to_v2.py` — чистые функции `needs_migration`, `migrate_recipe_data` (без I/O).
- `migrate_recipe_data` конвертирует `processing_blocks` → `nodes` с linear chain: первая нода читает из `"frame"`, каждая следующая ссылается на предыдущую (`inputs=[{source: prev_id, ...}]`).
- `RecipeEngine.load()` проверяет `meta.version` (отсутствие = v1): при v1 создаёт `.bak` через `shutil.copy2`, применяет миграцию, перезаписывает файл с `meta.version=2, meta.migrated_from_v1=True`.
- `RecipeEngine.save()` всегда пишет `meta.version=2`.
- Повторный load мигрированного рецепта (version=2, нет processing_blocks) пропускает миграцию и не перезаписывает `.bak`.
- 24 новых теста в `test_recipe_migration_v1_to_v2.py`, все зелёные.

---

### Task 9.13 — Замена старых вкладок на единую Pipeline-tab

**Уровень:** Middle (Sonnet)
**Файлы (изменить):**
- `multiprocess_prototype/frontend/windows/main_window/tab_factory.py` — удалить `widget_key` для Camera/Processing/Cropped Regions/Display/Graph Editor; добавить `pipeline_tab`.

**Файлы (новые):**
- `multiprocess_prototype/frontend/widgets/pipeline_tab/widget.py` — `PipelineTabWidget`: composition из library + view_switch (canvas/table) + inspector.

**Файлы (удалить):**
- `multiprocess_prototype/frontend/widgets/graph_editor/node_item.py`
- `multiprocess_prototype/frontend/widgets/graph_editor/port_item.py`
- `multiprocess_prototype/frontend/widgets/graph_editor/edge_item.py`
- `multiprocess_prototype/frontend/widgets/graph_editor/provisional_edge.py`
- `multiprocess_prototype/frontend/widgets/graph_editor/graph_view.py`
- `multiprocess_prototype/frontend/widgets/graph_editor/graph_scene.py`

**Сохранить и переместить в `pipeline_tab/`:** `model.py`, `linearity_check.py`, `auto_layout.py`, `constants.py`, `context_menu.py`. Каталог `graph_editor/` удалить после миграции.

**Acceptance:**
- [x] Вкладки Settings и Recipes не тронуты.
- [x] Вкладка Pipeline функциональна end-to-end.
- [x] Старые вкладки удалены, нет orphan-кода.
- [x] Всё ещё проходит `python scripts/validate.py`.

**Реализация (Task 9.13, commit e????):**
- Перенесены: model.py, linearity_check.py, auto_layout.py, constants.py (-> _layout_constants.py), context_menu.py из graph_editor/ в pipeline_tab/.
- Удалены: graph_editor/ целиком (14 файлов), tabs_setting/graph_editor_tab/ (3 файла).
- Создан: pipeline_tab/widget.py (PipelineTabWidget).
- Обновлены импорты: adapter.py, inspector_panel.py, table_view.py, 5 тестов, tab_factory.py, widgets/__init__.py, tabs_setting/__init__.py, tabs_config.py.
- tab_factory: widget_key="graph_editor" -> widget_key="pipeline".
- 16 новых тестов в test_phase9_pipeline_tab_widget.py, все зелёные.
- validate.py зелёный. 175 Phase 9 тестов зелёные.

---

### Task 9.14 — Тесты + документация

**Уровень:** Middle (Sonnet)
**Исполнитель:** tester + docs-writer
**Файлы (новые):**
- `tests/integration/test_pipeline_e2e.py` — поднять простой DAG (Webcam→Resize→Display), прогнать 100 кадров, проверить thumbnail на ноде.
- `tests/frontend/test_node_graphqt_adapter.py` — мок NodeGraph, тест что сигналы корректно конвертируются в Action.
- `multiprocess_prototype/frontend/widgets/pipeline_tab/README.md` — как добавить новую операцию (Python-класс + YAML), как кастомизировать ноду.

**Reuse:** `tests/frontend/test_graph_actions.py` (645 LOC) — пересмотреть, обновить импорты под новые пути, ожидать что **большая часть тестов работает без изменений** (мы сохранили GraphEditorModel и ActionBus).

**Acceptance:**
- [x] E2E тест зелёный.
- [x] Все unit-тесты Phase 9 зелёные.
- [x] `python scripts/validate.py` без warning'ов.
- [ ] `python scripts/run_framework_tests.py` зелёный (отдельная сессия — не входит в smoke headless).

**Реализация:**
- `tests/integration/test_pipeline_e2e.py` (commit `453a379`) — 6 e2e-кейсов: SimulatorInput→Resize 20 кадров; chain_with_display_callback; ResizeParams ValidationError на width=0/height=0; SimulatorInput→ColorConvert(BGR→GRAY)→Resize (grayscale shape); Pipeline-pydantic.validate_graph для DAG с simulator_input→resize. Без QApplication/NodeGraphQt — runtime-уровень.
- `pipeline_tab/README.md` (commit `b8eec65`, 230 строк) — архитектура (ASCII-диаграмма composition), таблица 13 компонентов с файлами/ответственностью, where-is-state, HOWTO «добавить операцию» (4 шага), кастомизация ноды (Issue #491 caveat), индекс тестов, известные ограничения, ссылки.
- `tests/frontend/test_node_graphqt_adapter.py` из плана **уже покрыт** существующим `tests/unit/test_phase9_node_graphqt_adapter.py` (24 кейса, Task 9.7) — дублирование избыточно.
- Phase 9 регрессия: **275 unit/integration тестов pass** (на коммитах `c875d67` + `b8eec65` + `453a379`).
- 30-минутный smoke с реальной Hikvision-камерой — отложен (требует железо), отдельная сессия.

---

## Critical Files

**Reuse без изменений:**
- `multiprocess_prototype/frontend/widgets/graph_editor/model.py` (274 LOC) — GraphEditorModel.
- `multiprocess_prototype/frontend/widgets/graph_editor/linearity_check.py` (68 LOC).
- `multiprocess_prototype/frontend/widgets/graph_editor/auto_layout.py` (286 LOC) — Sugiyama.
- `multiprocess_prototype/registers/pipeline/processing_node.py` (Phase 5a) — расширить.
- `multiprocess_prototype/registers/processor/catalog/schemas.py` (Phase 5a) — расширить.
- `multiprocess_prototype/services/camera/backends.py` (Phase 0) — обернуть в operations.
- `multiprocess_prototype/state_store/recipes/recipe_engine.py` (Phase 5a) — добавить ветвь.
- `multiprocess_framework/router_module/` (RouterManager + register_broadcast_route).
- `multiprocess_framework/process_manager_module/` (ProcessRegistry.create_and_register).
- `multiprocess_prototype/services/renderer/display_router.py` — расширить `is_anyone_subscribed`.

**Создаются:**
- `multiprocess_prototype/registers/pipeline/types.py` (DataType).
- `multiprocess_prototype/services/processor/topology/{builder,registrar}.py`.
- `multiprocess_prototype/services/processor/operations/{input,roi,preprocess}/...`.
- `multiprocess_prototype/frontend/widgets/pipeline_tab/{adapter,inspector_node,preview_bridge,library_palette,inspector_panel,table_view,view_switch,widget,process_id_combo,display_target_combo}.py`.

**Удаляются:**
- `multiprocess_prototype/frontend/widgets/graph_editor/{node_item,port_item,edge_item,provisional_edge,graph_view,graph_scene}.py`.

---

## Verification

**После каждой Task:**
- `python scripts/validate.py` — статическая валидация (Phase 0+).
- Затронутые pytest-тесты зелёные.

**После Task 9.5 (топология):**
- Запустить `run.py`, поднять простой Pipeline (1 камера → 1 region → 1 операция → display) **через код** (без UI). Проверить что router-каналы зарегистрированы корректно (`router._channel_registry` логирование).

**После Task 9.7 (adapter):**
- Открыть UI, создать пустой Pipeline. Drag из палитры (но fallback на programmatic) → нода появляется на canvas. Соединить порты — edge создаётся, type-validation работает (несовместимые красные).

**После Task 9.8 (thumbnail):**
- Поднять Pipeline через UI (Webcam → Resize → DisplayOutput), запустить «Run» — thumbnail обновляется в каждой ноде ~5 FPS. Свернуть NodeGraph viewport чтобы нода ушла из видимости — CPU нагрузка падает (verify через `top`).

**После Task 9.13 (UI замена):**
- Полный e2e: запуск приложения, создание pipeline в UI, сохранение в рецепт, перезапуск, загрузка рецепта — всё восстанавливается включая раскладку по `process_id`.

**Финал (Task 9.14):**
- `python scripts/run_framework_tests.py` — все тесты зелёные.
- Запуск 30-минутный smoke-test с реальной Hikvision-камерой (или симулятором), 3 региона, 5 нод обработки, 2 дисплея — без утечек памяти, без warning'ов в логах.

---

## Out of Scope (Phase 10+)

- ML-операции (`YOLOInfer`, `OnnxInfer`) — отдельная категория `Detect`, реализация Phase 10.
- Не-display Output: `DatabaseOutput`, `RobotOutput`, `MQTTOutput` — заглушки в каталоге, реализация Phase 10+.
- Backpressure стратегии (drop-oldest / block / sample) — пока default drop-oldest, конфигурация Phase 10.
- Авто-планировщик (распределение нод без явного `process_id` по worker-pool) — Phase 10.
- Hot-reload каталога операций без рестарта — Phase 11.
- Multi-pipeline (несколько графов одновременно) — Phase 11.
