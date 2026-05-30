# Pipeline: процесс-контейнер с отдельными нодами-плагинами

**Slug:** `pipeline-process-container-nodes`
**Связано:** [[pipeline-node-process-worker]] (Phase B+ долг), [[pipeline-ux-displays-gui-layout]]
**Ветка:** `refactor/config-driven-launch` (там же незакоммиченные Phase A + B MVP).
**Статус:** D.1 ✅ · D.2 ✅ · D.3 ✅ · D.4 ✅ — ГОТОВО (не закоммичено). 704 теста зелёные
(domain ≈257 + pipeline ≈447, из них +22 новых: container/inspector/drag), ruff чист,
live-smoke (qt-mcp) подтвердил рендер контейнеров без ошибок.

## Context (зачем)

Сейчас в редакторе **нода = процесс** (`node_id == process_name`, один `NodeItem` на процесс).
Когда несколько плагинов попадают в один процесс/воркер (через карточку «Перенести в
процесс» → domain `MovePlugin`), на графе два узла **схлопываются в один бокс** — плагины
видны только списком в инспекторе. Нужно: слияние в один процесс остаётся семантически
верным (один процесс = последовательная цепочка), но **визуально процесс = рамка-контейнер,
а каждый плагин внутри — отдельная нода**. Плюс: выбирать/инспектировать конкретный плагин,
перетаскивать плагин между контейнерами (= `MovePlugin` cross-process) и менять порядок
внутри контейнера перетаскиванием (= `MovePlugin` same-process reorder).

**Domain трогать НЕ нужно** — `MovePlugin` уже умеет cross-process и reorder
(`from_index`→`to_index`, `project.py:577-666`), `SetPluginConfig` принимает `plugin_index`.
Меняем **рендер + интерактив + инспектор**.

## Ключевые дизайн-решения

1. **`node_id` плагина = `{process}.{plugin_name}`.** Совпадает с префиксом endpoint'а wire
   (`process.plugin.port`) → внешние провода мапятся 1:1, domain-rewrite уже на этом построен.
   Дубликаты `plugin_name` в одном процессе → суффикс `#i` для GUI-уникальности + warning.
2. **Контейнер — backdrop-рамка ПОД нодами, не Qt-parent.** Плагин-ноды top-level (как `NodeItem`);
   `ProcessContainerItem(QGraphicsRectItem)` рисуется под ними (`setZValue(-1)`), авто-fit по
   членам + заголовок (имя процесса). Drag между контейнерами без reparent — целевой контейнер
   определяется по позиции центра ноды.
3. **Внутри контейнера — неявные стрелки цепочки** между соседними плагинами (`implicit=True`):
   не экспортируются, не удаляются пользователем.
4. **Внешние провода** соединяют конкретные плагин-ноды (`procA.pluginX` → `procB.pluginY`),
   порт — первый out/in.

## Что сделано (итог)

- **Идентичность ноды:** process→plugin. `node_id` плагин-ноды = `{process}.{plugin}`
  ([presenter.py](../presenter.py) `_topology_to_graph`, `_unique_plugin_node_id`).
  Backward-compat `GraphScene.get_node(process_name)` → первая плагин-нода (reveal/тесты).
- **Контейнер:** [graph/process_container_item.py](../graph/process_container_item.py) —
  backdrop-рамка под нодами (z=-1), `fit_to_members`; реестр `_containers`/`_members_by_process`
  в [graph/graph_scene.py](../graph/graph_scene.py).
- **Implicit-стрелки:** флаг `implicit` в [graph/edge_item.py](../graph/edge_item.py) —
  пунктир, не selectable/exportable, без edge-телеметрии.
- **Инспектор per-plugin:** `current_plugin_index` в
  [inspector/inspector_panel.py](../inspector/inspector_panel.py); presenter читает его в
  `_on_inspector_field_changed` → SetPluginConfig(plugin_index).
- **Drag/reorder:** `NodeItem.mouseRelease` → `GraphScene.on_node_drag_finished` →
  `plugin_drop_requested` → `presenter.on_plugin_dropped` → MovePlugin (cross/reorder) или
  snap-back reload. Дроп вне контейнеров → no-op.
- **Удаление плагин-ноды:** `presenter._delete_command_for` → RemovePlugin (если в процессе
  >1 плагина) или RemoveProcess (последний/legacy).
- **Layout:** `auto_layout_scene` раскладывает по процессам (ширина колонки = макс контейнер),
  плагины внутри слева-направо группой.
- **Тесты:** test_process_container.py (11), test_inspector_per_plugin.py (4),
  test_plugin_drag.py (7); адаптированы test_presenter_enhanced/test_yaml_positions (node=plugin).

## Фазы

### Phase D.1 — Рендер контейнеров + плагин-ноды (визуализация) ✅
- `graph/node_item.py`: `PluginNodeData`/расширить `NodeData` полями `process_name`,
  `plugin_index`, `plugin_name` для маршрутизации drop; backward-compat конструктор.
- `graph/process_container_item.py` (новый): `ProcessContainerItem` — заголовок + рамка;
  `fit_to_members(...)`; `setZValue(-1)`; прозрачен для кликов по дочерним нодам.
- `graph/edge_item.py`: флаг `implicit` в `EdgeData`.
- `graph/graph_scene.py`: реестр `_containers`; `load_from_data`/`clear_all`/`on_node_moved`
  обновляют контейнеры (`fit_to_members`).
- `presenter.py` `_topology_to_graph`: процесс → 1 контейнер + N `PluginNodeData`
  (node_id=`proc.plugin`); внешние wires → `EdgeData(proc.plugin → proc2.plugin2)` (не схлопывать);
  неявные стрелки между соседями. Display-боксы без изменений.
- Тесты: `test_process_container.py` + адаптация `test_pipeline_scene.py`/`test_presenter_enhanced.py`.

### Phase D.2 — Инспектор по конкретному плагину
- `tab.py` `_on_selection_changed`: node_id=`proc.plugin` → процесс + плагин по индексу →
  `show_plugin_node` с config ЭТОГО плагина.
- `inspector_panel.py`: `_current_plugin_index`; сигнал правки несёт индекс.
- `presenter.py` `_on_inspector_field_changed`: использовать переданный `plugin_index` (не хардкод 0).
- Тесты: `test_inspector.py`, `test_presenter_*`.

### Phase D.3 — Drag плагина между контейнерами + reorder
- scene/node_item: на завершение drag определить целевой контейнер + `to_index` →
  `plugin_drop_requested(node_id, to_process, to_index)`.
- tab/presenter: другой процесс → `MovePlugin(cross)`; тот же + изменился порядок →
  `MovePlugin(same reorder)`; мимо → no-op. Permission-gating `tabs.pipeline.edit`.
- combo «Перенести в процесс» — оставить как fallback.
- Тесты: `test_plugin_drag.py`, `test_presenter_domain_dispatch.py`.

### Phase D.4 — Layout + позиции + live-проверка
- `auto_layout_scene`: контейнеры по process-DAG (`node_width` = макс ширина контейнера),
  плагины внутри слева-направо; `fit_to_members`.
- `gui_positions` по node_id плагина; round-trip `graph_to_blueprint`.
- Live smoke (qt-mcp): demo-рецепт, 2 плагина в контейнере, drag/reorder/undo, `qt_messages` чисто.

## Acceptance
- Процесс с 2+ плагинами = рамка с 2+ нодами + стрелки; одиночный процесс — тоже в рамке.
- Выбор плагин-ноды → config именно этого плагина; правка → его `plugin_index`.
- Drag в другой контейнер = `MovePlugin` cross; reorder = `MovePlugin` same; undo обратим.
- domain-тесты зелёные без изменений; pipeline-тесты адаптированы + новые; ruff чисто; smoke ок.

## Риск
medium-high: меняется модель идентичности ноды (process→plugin), ~8 файлов рендера + ~8–10
тестов. Снижение: domain неизменен; контейнер-backdrop без Qt parent-child; combo-fallback.

## Verification
1. `.venv/Scripts/python.exe -m pytest multiprocess_prototype/domain/tests/ multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/ -q`
2. `ruff check` на затронутых файлах.
3. Live `/run-proto` → Pipeline → demo-рецепт → qt-mcp snapshot/drag/reorder/undo.
4. `mcp__sentrux__dsm` — нет цикла из-за нового `process_container_item.py`.
