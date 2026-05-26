# Phase 7a — DisplayNodeItem + target_process + graph↔blueprint serialization

> **Master plan**: [plan.md](plan.md)
> **Branch**: `feat/pipeline-display-node-and-io`
> **Дней**: 4-5
> **Зависимости**: Phase 4 (DisplayRegistry), Phase 5 (RecipeManager / RecipeEngine)
> **Refs trailer**: `Refs: plans/prototype-skeleton-2026-05/phase-7a-display-node-and-io.md, plans/prototype-skeleton-2026-05/plan.md`
> **Парная фаза**: [phase-7b-telemetry-and-demo.md](phase-7b-telemetry-and-demo.md)

## Цель

Добавить в `PipelineTab` (`multiprocess_prototype/frontend/widgets/tabs/pipeline/`) новый тип узла `DisplayNode` (привязка к SHM-каналу из `DisplayRegistry`); реализовать `target_process` для plugin-узлов; двустороннюю сериализацию графа в рецепт (`SystemBlueprint` + `display_bindings`); валидацию wire через `PluginRegistry.compatible_with(port)`. Телеметрия edges и end-to-end demo — Phase 7b.

## Реальная фундация

- `multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/node_item.py` — нативный `QGraphicsItem` со Schema-Driven Ports (`NodeItem` + `NodeData`).
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/edge_item.py` — кубический Bezier 1:1, fan-out через несколько edges с одного output_port.
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/graph_view.py` — wire creation через drag (`wire_created` signal).
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/graph_scene.py` — CRUD узлов/связей.
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py` — `PipelineModel` (SSOT topology dict с `processes`/`wires`).
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py` — `NodeInspectorPanel` (имя процесса + параметры через `CardsFieldFactory`).
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py` — `PipelinePresenter` (координация Model ↔ Scene ↔ Inspector ↔ TopologyHolder).
- `multiprocess_framework/modules/display_module/{interfaces,registry}.py` — `DisplayEntry` + `IDisplayRegistry` (Phase 4 DONE).
- `multiprocess_framework/modules/process_module/plugins/{registry,port}.py` — `PluginRegistry.compatible_with(port)` + `are_ports_compatible()`.
- `multiprocess_framework/modules/process_module/generic/blueprint.py` — `SystemBlueprint` (SchemaBase) c `processes`/`wires`.
- `multiprocess_prototype/recipes/manager.py` — `RecipeManager.save(slug, paths, …)` + `state.recipes.active`.

## Унаследованные идеи

Из удалённого Constructor (через `git show 9885bb88:`):
- **Display = узел с одним входным портом `frame`** и properties (display_key, display_name).
- **Signal suppression context** `_block_signals()` для предотвращения циклов sync (уже частично есть в `PipelinePresenter._suppress`).
- **display_bindings** хранятся отдельной секцией рецепта (не внутри `SystemBlueprint`) — каждая запись `{source: "process.plugin.port", display: "<display_id>"}`.

## Декомпозиция (Task X.Y)

### Task 7a.1 — DisplayNodeItem + DisplayNodeData ✅ DONE (bac860c2)

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Добавить визуальный узел `DisplayNode` на `QGraphicsScene` с одним входным портом `frame` и properties `display_id`/`display_name`.
**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/display_node_item.py` (новый)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/constants.py` (добавить `DISPLAY_CATEGORY_COLOR = "#2e7d32"` — зелёный)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_display_node_item.py` (новый)
**Steps:**
1. Создать `@dataclass DisplayNodeData(node_id, display_id, display_name, x, y)` — отдельный от `NodeData` (категория всегда «display»).
2. Реализовать `DisplayNodeItem(QGraphicsRectItem)`: цвет `DISPLAY_CATEGORY_COLOR`, заголовок «Display», подзаголовок `display_name` или `display_id` если имя пустое.
3. Один входной порт `frame` (slot, `image/bgr`-совместимый через wildcard `image/*`) — используем существующий `PortItem` с координатой левой стороны.
4. Метод `set_display(display_id: str, display_name: str)` — обновляет подзаголовок без рекреации узла.
5. Свойство `display_id` для round-trip сериализации.
6. Unit-тесты (pytest-qt): создание узла, обновление display_id через `set_display`, наличие одного входного порта и нуля выходных.
**Acceptance criteria:**
- [ ] `DisplayNodeItem(DisplayNodeData(...))` создаётся, добавляется в `GraphScene` без ошибок.
- [ ] У узла ровно 1 входной порт с именем `frame`, 0 выходных.
- [ ] Цвет фона — зелёный (`DISPLAY_CATEGORY_COLOR`).
- [ ] `set_display(...)` обновляет subtitle.
- [ ] 4-5 unit-тестов проходят, smoke-тест GraphScene с DisplayNode проходит.
**Out of scope:** combo выбора display_id в inspector (это Task 7a.3), сериализация в YAML (Task 7a.4), подписка на `state.displays.changed` (Task 7a.3).

---

### Task 7a.2 — PipelineModel расширение для display-узлов ✅ DONE (793649a6)

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Расширить `PipelineModel` поддержкой display-узлов в topology dict (новый ключ `displays`) — для in-memory SSOT и round-trip.
**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py` (расширить)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_model.py` (дополнить)
**Steps:**
1. Расширить `PipelineModel.__init__` — добавить дефолтный ключ `"displays": []` в topology dict.
2. Реализовать `add_display(node_id: str, display_id: str, display_name: str = "") → (old_topo, new_topo)`. Защита от дубликатов `node_id`.
3. Реализовать `remove_display(node_id: str) → (old_topo, new_topo)` — каскадно удалить wire'ы, у которых target — display_node.
4. Реализовать `get_displays() → list[dict]` — копия списка для read-only доступа.
5. Поддержать display-узлы как target wire (текущий `add_wire` парсит endpoint как `process.plugin.port`; для display endpoint — `display.<node_id>.frame`). НЕ менять формат — добавить prefix-обработку: если target начинается с `display.` — пропускать cycle/self-loop проверку (display — terminal node).
6. Дополнить `validate()` — display_id из wires должен существовать в `displays`; warning «display не имеет ни одного источника» (orphan-display).
7. Unit-тесты: add/remove display, wire к display, валидация ссылок.
**Acceptance criteria:**
- [ ] `model.add_display("display1", "main_output")` создаёт запись и возвращает `(old, new)`.
- [ ] `model.add_wire("proc.plugin.frame", "display.display1.frame")` работает без cycle-ошибки.
- [ ] Каскадное удаление: `remove_display("display1")` чистит все wire'ы к `display.display1.*`.
- [ ] `validate()` ловит ссылку на несуществующий display.
- [ ] 6-8 новых unit-тестов проходят.
**Out of scope:** визуализация (Task 7a.1 уже сделана), inspector-combo (Task 7a.3), сериализация в blueprint (Task 7a.4).

---

### Task 7a.3 — Inspector: target_process combo + display_id combo ✅ DONE (72fab8a7)

**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Расширить `NodeInspectorPanel` двумя комбо-боксами: (1) `target_process` для plugin-узлов (выбор процесса из активного рецепта); (2) `display_id` для display-узлов (выбор из `DisplayRegistry`).
**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py` (расширить)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py` (подписка на изменения)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py` (передать `DisplayRegistry` в inspector через `set_context`)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_inspector.py` (дополнить)
**Steps:**
1. В `NodeInspectorPanel` добавить два режима отображения: `show_plugin_node(node_id, process_name, target_process, …)` и `show_display_node(node_id, display_id, …)`.
2. Для plugin-узла: `QComboBox` «Процесс» — список процессов из `state.recipes.active` (через `ctx.recipe_manager()` + `read_recipe(slug)`).
3. Для display-узла: `QComboBox` «Display» — список из `ctx.display_registry().list()` (id + name).
4. Сигналы: `target_process_changed(node_id, new_process)` и `display_id_changed(node_id, new_display_id)`.
5. В `PipelinePresenter` — обработчики этих сигналов, мутации модели + sync со сценой через `_suppress`-контекст.
6. Подписка на `state.displays.changed` (если StateProxy доступен через ctx) — обновлять combo `display_id` без перевыборки.
7. Unit-тесты (pytest-qt): combo заполняется из реестра, выбор отправляет правильный сигнал, signal suppression не вызывает цикла.
**Acceptance criteria:**
- [x] При выборе display-узла в Inspector появляется combo с display_id из реестра.
- [x] При выборе plugin-узла в Inspector появляется combo `target_process` со списком процессов.
- [x] Изменение combo обновляет `PipelineModel` и `topology dict` (проверка в тесте через `to_topology_dict()`).
- [x] 5-7 unit-тестов проходят (фактически: 13 в test_inspector.py + 11 в test_presenter_inspector_integration.py = 24 новых).
**Out of scope:** запись в рецепт (Task 7a.5), валидация wire (Task 7a.6), создание display-узла из палитры (это уже в Task 7a.1).

---

### Task 7a.4 — pipeline/io.py — graph↔blueprint serialization ✅ DONE (554c2f29)

**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Реализовать двустороннюю сериализацию `GraphScene` ↔ `SystemBlueprint` + `display_bindings` секция, чтобы рецепт можно было сохранить и восстановить без потерь.
**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/io.py` (новый)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_io_roundtrip.py` (новый)
**Steps:**
1. Реализовать `graph_to_blueprint(model: PipelineModel) → tuple[dict, list[dict]]` — возвращает `(blueprint_dict, display_bindings)`.
2. `blueprint_dict` — соответствует `SystemBlueprint` (поля `name`, `description`, `processes`, `wires`). Wire'ы к display-узлам **исключить** из `blueprint.wires` и перевести в `display_bindings: [{source: "proc.plugin.port", display: "<display_id>"}]`.
3. Реализовать `blueprint_to_graph(blueprint: dict, display_bindings: list[dict], model: PipelineModel) → None` — наполняет модель: процессы → `add_process`, wire'ы → `add_wire`, display_bindings → `add_display` + wire к нему.
4. Координаты узлов (`x`, `y`) сохранять/восстанавливать через расширение topology dict (`"gui_positions": {node_id: (x, y)}` — уже есть `_gui_positions` в presenter).
5. Round-trip-тесты: создаём граф → конвертируем в blueprint → конвертируем обратно → сравниваем. Минимум 3 сценария: только процессы; процессы + wires; процессы + wires + displays + display_bindings.
6. Edge cases: пустой граф; рецепт с `display_bindings` ссылающимся на отсутствующий display (warning, не падать).
**Acceptance criteria:**
- [ ] `graph_to_blueprint` возвращает корректный dict для `SystemBlueprint.model_validate(...)` (валидируется через Pydantic).
- [ ] `blueprint_to_graph` восстанавливает модель из dict без потерь.
- [ ] Round-trip: `graph → blueprint → graph` идентичен (по `to_topology_dict()`).
- [ ] 8-10 unit-тестов проходят, включая edge cases.
**Out of scope:** UI кнопка «Сохранить» (Task 7a.5), валидация wire (Task 7a.6), интеграция с RecipeManager (Task 7a.5).

---

### Task 7a.5 — Кнопка «Сохранить в рецепт» + интеграция с RecipeManager

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Добавить в action-колонку PipelineTab кнопку «Сохранить в рецепт» — вызывает `graph_to_blueprint` и пишет результат через `RecipeManager.save(active_slug, paths={...})`.
**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py` (добавить кнопку и handler)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py` (метод `save_to_active_recipe()`)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_save_recipe.py` (новый, smoke + integration)
**Steps:**
1. Кнопка `«Сохранить в рецепт»` в action-колонке (между «Валидация» и «По размеру»). Permission gate: `tabs.pipeline.edit`.
2. `PipelinePresenter.save_to_active_recipe()`:
   - Получить `active_slug` через `ctx.recipe_manager().get_active()`. Если `None` — показать `QMessageBox.warning("Не выбран активный рецепт")` и выйти.
   - `graph_to_blueprint(self._model) → (bp_dict, bindings)`.
   - Считать текущий рецепт через `RecipeManager.read_recipe(slug)` (для сохранения остальных секций: `active_services`, метаданные).
   - Обновить секции `blueprint` и `display_bindings` в dict рецепта.
   - Записать через `RecipeManager.save(slug, paths={"blueprint": bp_dict, "display_bindings": bindings, "gui_positions": {...}})`.
3. По успеху — `QMessageBox.information("Рецепт сохранён: <slug>")`. По ошибке — `QMessageBox.critical` с текстом исключения.
4. Smoke-тест: создаём временный RecipeManager в tmp dir, активируем рецепт, вызываем `save_to_active_recipe`, перечитываем YAML — проверяем, что blueprint/display_bindings корректны.
**Acceptance criteria:**
- [ ] Кнопка «Сохранить в рецепт» появляется в action-колонке.
- [ ] При нажатии без активного рецепта — warning.
- [ ] При нажатии с активным рецептом — `recipes/<slug>.yaml` обновляется с новой blueprint+display_bindings.
- [ ] 3-4 smoke/integration-теста проходят.
**Out of scope:** загрузка рецепта при старте (это уже делает `_load_topology`), создание нового рецепта из GUI (отдельная фича), миграции формата.

---

### Task 7a.6 — Валидация wire через PluginRegistry.compatible_with

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** При создании wire через `GraphView.wire_created` сигнал — проверить совместимость портов через `are_ports_compatible(out_port, in_port)`. Несовместимые wire'ы — красная подсветка + блокировка добавления.
**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py` (добавить проверку в `add_wire`)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/edge_item.py` (поддержка стиля «invalid» — красная пунктирная линия 1с, потом отмена)
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_wire_validation.py` (новый)
**Steps:**
1. В `PipelinePresenter.add_wire(source, target)`:
   - Получить `Port` источника и приёмника из `PluginRegistry` через `ctx.plugin_registry()`.
   - Если оба `Port` найдены — вызвать `are_ports_compatible(out, inp)`.
   - Если несовместимо — лог warning, `QMessageBox.warning(parent, "Несовместимые порты", "<dtype_out> → <dtype_in>")`, не добавлять wire в модель.
2. Для display-узлов: target порт — `image/*` (wildcard), всегда совместим с image-выходами.
3. В тестах проверить:
   - Совместимые порты (image/bgr → image/bgr): wire добавляется.
   - Несовместимые (image/bgr → tensor/float32): wire не добавляется, выводится сообщение.
   - Wildcard (image/bgr → image/*): совместимо.
   - Wire к display: совместимо при любом image-выходе.
**Acceptance criteria:**
- [ ] Создание несовместимого wire блокируется + warning.
- [ ] Совместимые wire'ы создаются без задержки.
- [ ] Display-узлы принимают любой image-выход.
- [ ] 4-6 unit-тестов проходят.
**Out of scope:** drag-time preview (красный wire при ведении) — отложено в Phase 7b если будет время; ranking of suggested connections.

---

## Acceptance (Phase 7a в целом)

- DisplayNodeItem можно добавить в сцену через GUI (D&D или контекст-меню), выбрать display из combo, сохранить в рецепт.
- `target_process` редактируется в Inspector-панели и попадает в `blueprint.processes`.
- `graph_to_blueprint` / `blueprint_to_graph` — round-trip без потерь (минимум 3 сценария).
- Wire-валидация блокирует несовместимые порты с понятным сообщением.
- Кнопка «Сохранить в рецепт» пишет `recipes/<slug>.yaml` через `RecipeManager`.
- 30-40 unit/integration тестов суммарно по Task 7a.1-7a.6.
- Демо и телеметрия — в Phase 7b.

## Out of scope (отложено в Phase 7b или после MVP)

- WireMetricsBadge / WireStatus (Phase 7b).
- Плагин `blur` (Phase 7b).
- Demo-рецепт `demo_webcam_split_merge.yaml` (Phase 7b).
- Drag-and-drop DisplayNode из палитры (можно реализовать через context-menu в Task 7a.1 — но не обязательно).
- Layout-композитор дисплеев (1x1, 2x2) — отложен до после MVP.
- Hot-reload рецепта в рабочих процессах (это часть Phase 5 `replace_blueprint` — DONE).
