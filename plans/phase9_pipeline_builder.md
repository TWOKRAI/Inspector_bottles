# Phase 9: Pipeline Builder — DAG-конструктор обработки

> **⚠️ SUPERSEDED.** Этот план — первоначальная концепция (собственный graph_editor). Финальная версия с NodeGraphQt-PySide6 (hybrid) и live-preview thumbnail: [`phase9_pipeline_builder_nodegraphqt.md`](./phase9_pipeline_builder_nodegraphqt.md). Документ оставлен для истории решений.

## Context

Phases 0-4: фундамент (камеры, регионы, базовая обработка).
Phase 5a-5c: модель `ProcessingNode` + каталог операций YAML + chain executor + cross-process workers.
Phase 8: визуальный graph_editor (`frontend/widgets/graph_editor/`) — собственный node-editor на PySide6 с node_item, port_item, edge_item, catalog_palette, view_switch, scene/view.

Phase 9 — финальная сборка. Превращаем разрозненные части в **единый Pipeline Builder**: модульный DAG-конструктор с библиотекой блоков, двумя представлениями (граф ↔ таблица), типобезопасными соединениями, динамической раскладкой узлов по процессам через RouterManager и live-preview только для нод, привязанных к дисплеям.

**Принципиальные решения:**
- **DAG, а не цепочка** — узел может иметь несколько выходов (ROI-splitter), несколько входов (merge), ветвления.
- **Edges = router channels** — соединение в графе физически реализуется как канал `RouterManager`. `register_route(from_channel → to_channel)`. Edge удалён → канал unregister'ится. Это делает граф «исполняемой topology» фреймворка, а не отдельной runtime-моделью.
- **process_id на узле = SystemLauncher target** — пользователь решает раскладку. Узлы без явного `process_id` группируются в общий процессор. ProcessRegistry создаёт процессы динамически.
- **Live-preview lazy** — узел шлёт thumbnail в DisplayRouter только если хотя бы один DisplayWindow подписан на его output-канал. Никаких подписчиков → нода вообще не аллоцирует SHM-слот для preview (механизм lazy SHM уже есть в DisplayWindowManager).
- **Two-view один data model** — `Pipeline` (Pydantic) → graph_editor рендерит DAG, table-view рендерит дерево Camera→Region→Node. Один источник истины, два renderer'а через одну модель.
- **Type-safe соединения** — `DataType` enum + `is_compatible()` (port из Sketch_robot). graph_editor подсвечивает несовместимые edges красным до фактического соединения.
- **Граф = часть рецепта** — `Pipeline` сериализуется внутрь Recipe целиком. Снос рецепта = снос всего графа.
- **Output пока только дисплеи** — категории `DatabaseOutput`, `RobotOutput`, `MQTTOutput` декларируются в каталоге, но реализации заглушками. Phase 10+ добавляет реальные.

---

## Final Vision (как пользователь работает)

1. Открывает вкладку **«Pipeline»** (заменяет Camera/Processing/Cropped Regions/Display/Graph Editor — слияние в одну).
2. Слева — **Library**: категории `Input` / `ROI` / `Preprocess` / `Detect` / `Measure` / `Logic` / `Output`. Drag-and-drop узлов на canvas.
3. В центре — **Canvas** (graph_editor). Тащит `HikvisionInput` → `RegionSplitter` → 3 выхода → 3 ветки `CLAHE` → `Threshold` → `ContourFind` → `DisplayOutput`. Edges рисуются вручную, типы проверяются на лету.
4. Справа — **Inspector**: параметры выбранного узла, авто-сгенерированные из `param_schema`. Внизу инспектора — выбор `process_id` (combo: `processor_main`, `worker_pool`, `+ создать новый`) и `display_target` (combo: `display_original`, `display_mask`, `+ новый дисплей`).
5. Вверху — **toolbar** с переключением `Graph ⇄ Table`. Table показывает то же дерево Camera→Region→Node, но позволяет bulk-edit: выделил 10 нод → задал всем `process_id=worker_pool`.
6. Кнопка «Run» → SystemLauncher динамически поднимает требуемые процессы, RouterManager регистрирует все каналы согласно edges, ChainBuilder строит runnables. Дисплеи, привязанные к узлам, начинают показывать кадры. Узлы без подписчиков-дисплеев не тратят CPU на encode preview.
7. Снапшот сохраняется в Recipe — открыл рецепт, всё восстановилось, включая раскладку нод по процессам.

---

## Architecture insights — как идея ложится на фреймворк

| Идея пользователя | Механизм фреймворка |
|---|---|
| Каждый модуль шлёт куда хочет | `RouterManager.register_channel()` динамически |
| Соединение между модулями | `connection_map` + `channel_dispatcher` маршрутизирует output→input |
| Ветвление (один источник → много получателей) | `register_broadcast_route()` (fan-out) |
| Узлы в разных процессах | `ProcessRegistry.create_and_register()` динамически + `process_id` уже есть в `ProcessingNode` |
| Live-preview только при наличии дисплея | `DisplayRouter` callback-mechanism + lazy SHM в `DisplayWindowManager` |
| Несколько дисплеев, переключение источника | `SourceSelectorCombo` уже умеет, расширим под node-output как источник |
| Граф = часть рецепта | `RecipeEngine` уже снапшотит config-ветви; добавляется ветвь `pipeline_graph` |
| Two-view | `Pipeline` Pydantic — single source of truth, view-switch.py уже заложен |
| Каталог операций | `data/processing_catalog.yaml` уже существует с Phase 5a — расширяется под input/output ports |

**Ничего нового на уровне инфраструктуры строить не надо.** Phase 9 — это интеграционный слой поверх готовых механизмов.

---

## Data model changes

### Расширение каталога операций (`registers/processor/catalog/schemas.py`)

Сейчас `ProcessingOperationDef` имеет: `name`, `type_key`, `params_schema`, `module_path`, `on_error`, `description`.

**Добавить:**
- `category: str` — `Input` / `ROI` / `Preprocess` / `Detect` / `Measure` / `Logic` / `Output` (для library-palette).
- `input_ports: List[PortDef]` — список входов с типами.
- `output_ports: List[PortDef]` — список выходов с типами.
- `multiplicity: Literal["fixed", "dynamic"]` — `RegionSplitter` имеет dynamic outputs (по числу регионов).
- `display_capable: bool` — может ли нода отдавать preview в DisplayRouter.

**Новая модель `PortDef`:**
```python
class PortDef(SchemaBase):
    name: str           # "image_in", "mask_out"
    data_type: DataType # enum
    optional: bool = False
    description: str = ""
```

### Новая модель `DataType` (`registers/pipeline/types.py`)

Порт из Sketch_robot, расширенный под Inspector:
- `BGR_IMAGE`, `GRAYSCALE`, `BINARY_MASK`
- `BBOX_LIST`, `KEYPOINTS`, `CONTOURS`
- `SCALAR`, `STRING`, `DICT`
- `TENSOR` — для будущих ML-нод
- `ANY` — universal compat

`is_compatible(out_type, in_type) -> bool` + `_COMPATIBLE_PAIRS` (например `GRAYSCALE ↔ BINARY_MASK`).

### Расширение `ProcessingNode` (`registers/pipeline/processing_node.py`)

Сейчас: `node_id`, `operation_ref`, `params`, `enabled`, `process_id`, `worker_id`, `inputs: List[NodeInput]`, `position`.

**Добавить:**
- `outputs: List[NodeOutput]` — раньше outputs были неявные. Теперь явные, чтобы edge мог ссылаться на конкретный output port (для multi-output нод).
- `display_targets: List[str]` — список window_id, куда нода отдаёт preview. Пусто = preview не генерируется.
- `channel_prefix: str` — префикс для router-каналов этой ноды (auto-generated из `node_id`, override-able).

### Расширение `Pipeline` (`registers/pipeline/schemas.py`)

- `Pipeline.validate_graph() -> List[ValidationError]` — проверка совместимости типов на всех edges, отсутствие циклов, недостижимых узлов.
- `Pipeline.to_router_topology() -> RouterTopology` — конвертер графа в набор каналов и маршрутов для RouterManager.

---

## Tasks

### Task 9.1 — DataType enum + is_compatible

**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Type-system для портов узлов.
**Файлы (новые):**
- `registers/pipeline/types.py` — `DataType` Enum, `is_compatible(out, in)`, `_COMPATIBLE_PAIRS`.
- `tests/registers/test_data_types.py` — round-trip + compat-matrix тесты.

**Критерии приёмки:**
- [ ] Все 11 типов перечислены.
- [ ] `is_compatible(BGR_IMAGE, BGR_IMAGE)` → True.
- [ ] `is_compatible(GRAYSCALE, BINARY_MASK)` → True.
- [ ] `is_compatible(BBOX_LIST, BGR_IMAGE)` → False.
- [ ] `ANY` совместим со всеми.

**Вне scope:** Реальные операции (Phase 9.4+).

---

### Task 9.2 — PortDef + расширение ProcessingOperationDef

**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Каталог операций знает про порты, категорию, dynamic-multiplicity.
**Файлы (изменить):**
- `registers/processor/catalog/schemas.py` — добавить `PortDef`, `category`, `input_ports`, `output_ports`, `multiplicity`, `display_capable` в `ProcessingOperationDef`.
- `data/processing_catalog.yaml` — обновить существующие 2 операции (color_detection, blob_detection) под новый формат.

**Критерии приёмки:**
- [ ] `ProcessingOperationDef` round-trip с новыми полями.
- [ ] Старые YAML-файлы без новых полей читаются (defaults).
- [ ] Тест: операция с `multiplicity=dynamic` валидируется.

**Вне scope:** Семантика multiplicity в runtime (Phase 9.5).

---

### Task 9.3 — Расширение ProcessingNode + Pipeline.validate_graph

**Уровень:** Senior (Opus, teamlead)
**Исполнитель:** teamlead
**Цель:** Узлы знают про outputs, display_targets, channel_prefix. Pipeline умеет валидировать DAG.
**Файлы (изменить):**
- `registers/pipeline/processing_node.py` — `outputs`, `display_targets`, `channel_prefix`, `NodeOutput` dataclass.
- `registers/pipeline/schemas.py` — `Pipeline.validate_graph() -> List[ValidationError]`.
- `tests/registers/test_pipeline_validation.py` — тесты на циклы, type-mismatch, недостижимые узлы.

**Критерии приёмки:**
- [ ] Цикл A→B→A детектится.
- [ ] Type-mismatch на edge детектится с указанием порта.
- [ ] Узел без входящих edges и не Input-категория → warning.
- [ ] Round-trip serialization.

**Вне scope:** Авто-генерация channel_prefix (Phase 9.5).

---

### Task 9.4 — Базовая библиотека операций (Input + ROI + Preprocess)

**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Минимальный набор операций для proof-of-concept DAG.
**Файлы (новые):**
- `services/processor/operations/input/webcam_input.py` (обёртка над WebcamBackend).
- `services/processor/operations/input/hikvision_input.py` (обёртка над HikvisionBackend).
- `services/processor/operations/input/file_input.py`.
- `services/processor/operations/input/simulator_input.py`.
- `services/processor/operations/roi/region_splitter.py` (1 input → N outputs, multiplicity=dynamic).
- `services/processor/operations/preprocess/{resize,color_convert,clahe,blur,threshold}.py`.
- `data/processing_catalog.yaml` — добавить все эти операции с категориями и портами.

**Критерии приёмки:**
- [ ] Каждая операция реализует Protocol из Phase 5a.
- [ ] Каждая декларирует input/output ports корректно.
- [ ] Smoke-тест: pipeline `WebcamInput → Resize → CLAHE → DisplayOutput` строится и валидируется.

**Вне scope:** Detect/Measure/Logic-категории (Phase 9.7+).

---

### Task 9.5 — Pipeline.to_router_topology + ChainBuilder integration

**Уровень:** Senior+ (Opus, teamlead)
**Исполнитель:** teamlead
**Цель:** DAG → набор каналов RouterManager + конфиг ProcessorService.
**Файлы (новые):**
- `services/processor/topology/builder.py` — `RouterTopology` dataclass + `to_router_topology(pipeline)`.
- `services/processor/topology/registrar.py` — `apply_topology(router, topology)` — регистрация каналов и маршрутов в живом RouterManager.

**Файлы (изменить):**
- `services/processor/service.py` — `rebuild_runnables` использует topology вместо ad-hoc построения.
- `backend/processes/processor/process.py` — на старте читает topology из конфига, регистрирует каналы.

**Критерии приёмки:**
- [ ] Каналы named `{node_id}.{port_name}` или `{channel_prefix}.{port_name}`.
- [ ] Edge → `connection_map` запись.
- [ ] Fan-out (один output → несколько inputs) → `register_broadcast_route`.
- [ ] Edge удалён в graph → канал unregister'ится без рестарта процесса.
- [ ] Тест: маленький DAG из 4 нод поднимается и крутится 5 секунд.

**Вне scope:** Cross-process edges (Phase 9.6).

---

### Task 9.6 — Cross-process топология + динамические процессы

**Уровень:** Senior+ (Opus, teamlead)
**Исполнитель:** teamlead
**Цель:** `process_id` на узлах раскладывает граф по процессам, SystemLauncher поднимает их динамически, edges между процессами идут через SHM.
**Файлы (изменить):**
- `services/processor/topology/builder.py` — группировка узлов по `process_id`, маркировка cross-process edges.
- `services/processor/topology/registrar.py` — для cross-process edge использовать SHM-канал (FrameShmMiddleware).
- `config/app.py` — `AppConfig` принимает topology и динамически разворачивает `processors[]`.
- `backend/processes/processor_worker/process.py` — расширить под произвольную операцию из каталога.

**Критерии приёмки:**
- [ ] DAG с 2 нодами в `processor_main` и 1 в `worker_pool` стартует.
- [ ] Cross-process edge передаёт BGR_IMAGE через SHM (не pickle).
- [ ] Изменение `process_id` ноды → graceful rebuild без потери остального графа.

**Вне scope:** Backpressure стратегии (Phase 9.10).

---

### Task 9.7 — Library-palette в graph_editor

**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Левая панель Pipeline-вкладки с категориями + drag-and-drop в canvas.
**Файлы (изменить):**
- `frontend/widgets/graph_editor/catalog_palette.py` — наполнить из `ProcessingOperationDef.category`, drag-mime для drop в scene.
- `frontend/widgets/graph_editor/graph_scene.py` — обработка drop event → создание `ProcessingNode` + `node_item`.

**Критерии приёмки:**
- [ ] Категории отображаются как раскрывающиеся группы.
- [ ] Drag из палитры → drop на canvas → новая нода появляется.
- [ ] Несовместимые edges подсвечиваются красным.
- [ ] Provisional-edge (`provisional_edge.py`) валидирует тип на лету.

**Вне scope:** Inspector-панель (Phase 9.8).

---

### Task 9.8 — Inspector-панель параметров (auto-generated)

**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Правая панель с автоматически сгенерированными виджетами параметров из `params_schema`.
**Файлы (новые):**
- `frontend/widgets/pipeline_tab/inspector_panel.py` — рендерит QFormLayout из `ProcessingOperationDef.params_schema`.
- `frontend/widgets/pipeline_tab/process_id_combo.py` — выбор `process_id` (existing + create new).
- `frontend/widgets/pipeline_tab/display_target_combo.py` — выбор `display_targets` (multi-select).

**Критерии приёмки:**
- [ ] int/float/bool/choice генерируются автоматически.
- [ ] Изменение → mutates ProcessingNode.params → reactive update topology.
- [ ] Multi-select displays корректно сериализуется.

---

### Task 9.9 — Two-view sync (Graph ⇄ Table)

**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Toolbar-toggle переключает view, обе работают с одним `Pipeline`.
**Файлы (изменить):**
- `frontend/widgets/graph_editor/view_switch.py` — расширить под полноценный switch.
- `frontend/widgets/pipeline_tab/table_view.py` (новый) — `QTreeView` модель Camera→Region→Node, bulk-edit.

**Критерии приёмки:**
- [ ] Изменение в graph → отражается в table.
- [ ] Bulk-edit `process_id` в таблице → обновляет graph.
- [ ] Переключение view не теряет выделение узла.

---

### Task 9.10 — Live-preview через DisplayRouter (lazy)

**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Узел отдаёт preview в DisplayWindow только если есть подписчики.
**Файлы (изменить):**
- `services/processor/topology/registrar.py` — для каждого `display_target` ноды регистрирует preview-канал в DisplayRouter.
- `services/renderer/display_router.py` — `is_anyone_subscribed(channel)` API.
- `services/processor/operations/base.py` — `should_emit_preview(ctx)` чек перед encode.

**Критерии приёмки:**
- [ ] Дисплей закрыт → нода не аллоцирует SHM, не делает encode.
- [ ] `SourceSelectorCombo` показывает узлы как доступные источники.
- [ ] Открытие нового дисплея → подписка на канал → preview оживает без рестарта.

---

### Task 9.11 — Pipeline в Recipe + миграция

**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** RecipeEngine снапшотит pipeline_graph. Старый формат `processing_blocks` конвертируется в `nodes` при загрузке.
**Файлы (изменить):**
- `state_store/recipes/recipe_engine.py` — добавить `pipeline_graph` в `DEFAULT_CONFIG_PATHS`.
- `state_store/recipes/migrations/v1_to_v2.py` (новый) — конвертер старых рецептов.

**Критерии приёмки:**
- [ ] Сохранение/загрузка рецепта с DAG round-trip.
- [ ] Старый рецепт автоматически мигрируется при load.
- [ ] Backup старого формата создаётся в `.bak`.

---

### Task 9.12 — Замена старых вкладок на единую Pipeline-tab

**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Camera/Processing/Cropped Regions/Display/Graph Editor → одна Pipeline-tab.
**Файлы (изменить):**
- `frontend/windows/main_window/tab_factory.py` — удалить старые tabs, добавить `PipelineTab`.
- `frontend/widgets/pipeline_tab/widget.py` (новый) — composition: library + canvas/table + inspector.

**Критерии приёмки:**
- [ ] Settings и Recipes вкладки не тронуты.
- [ ] Новая Pipeline-вкладка функциональна end-to-end.
- [ ] Старые вкладки удалены без orphan-кода.

**Вне scope:** Тесты (Phase 9.13).

---

### Task 9.13 — Тесты + документация

**Уровень:** Middle (Sonnet)
**Исполнитель:** tester + docs-writer
**Цель:** Покрытие критичных путей + README раздела.
**Файлы (новые):**
- `tests/integration/test_pipeline_e2e.py` — поднять простой DAG, прогнать 100 кадров, проверить на дисплее.
- `frontend/widgets/pipeline_tab/README.md` — как добавить новую операцию.

**Критерии приёмки:**
- [ ] E2E тест зелёный.
- [ ] Все unit-тесты Phase 9 зелёные.
- [ ] `python Inspector_prototype/scripts/validate.py` без warning'ов.

---

## Что получится в итоге

**Технически:** замкнутая визуальная среда, где пользователь конструирует pipeline из блоков как в TouchDesigner/ComfyUI, но с явной раскладкой по процессам и интеграцией с уже существующими камерами/дисплеями. Каждый edge — настоящий router channel, каждый узел — потенциально отдельный процесс или поток. Граф валидируется статически (типы) и динамически (циклы, недостижимости). Live-preview не тратит ресурсы вхолостую.

**По бизнес-смыслу:** оператор перестаёт зависеть от программиста. Чтобы добавить новую логику инспекции (например, «считай площадь контура и пиши в БД если > N»), достаточно набрать 3-4 блока в графе и сохранить как рецепт. Новая бутылка / новый дефект / новая камера — ещё один рецепт. Программист пишет только новые **операции** (Python-код), не интегрирует их вручную.

**По росту системы:** добавление ML-инференса (YOLOInfer-нода), новых output-целей (БД, робот, MQTT), новых типов данных (TENSOR) — расширение каталога без изменения UI и runtime. Phase 10+ ⊃ Phase 9 без ломающих изменений.

---

## Файлы — карта Phase 9

**Затрагиваются:**
- `registers/pipeline/` — types.py (новый), processing_node.py, schemas.py
- `registers/processor/catalog/schemas.py`
- `services/processor/` — operations/* (расширение), topology/* (новый каталог)
- `services/renderer/display_router.py`
- `state_store/recipes/recipe_engine.py` + migrations
- `frontend/widgets/graph_editor/` — catalog_palette, graph_scene, provisional_edge, view_switch
- `frontend/widgets/pipeline_tab/` (новый каталог) — widget, inspector_panel, table_view, combos
- `frontend/windows/main_window/tab_factory.py`
- `data/processing_catalog.yaml`

**Не трогаем:** Settings tab, Recipes tab, multiprocess_framework/ (за исключением `register_broadcast_route` если потребуется расширение API).
