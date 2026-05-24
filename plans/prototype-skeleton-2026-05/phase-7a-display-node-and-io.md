# Phase 7a — DisplayNodeItem + target_process + graph↔blueprint serialization

> **Master plan**: [plan.md](plan.md)
> **Branch**: `feat/pipeline-display-node-and-io`
> **Дней**: 4-5
> **Зависимости**: Phase 4 (DisplayRegistry), Phase 5 (recipe → graph IO)
> **Refs trailer**: `Refs: plans/prototype-skeleton-2026-05/phase-7a-display-node-and-io.md, plans/prototype-skeleton-2026-05/plan.md`
> **Парная фаза**: [phase-7b-telemetry-and-demo.md](phase-7b-telemetry-and-demo.md)

## Цель

Добавить в PipelineTab новый тип узла `DisplayNode` (привязка к SHM-каналу из DisplayRegistry); реализовать привязку plugin-узлов к процессам; сериализация графа в рецепт. Подготовить почву для 7b (телеметрия + демо).

## Реальная фундация

- `multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/node_item.py` — нативный QGraphicsItem со Schema-Driven Ports. **Унаследовать**.
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/edge_item.py` — кубический Bezier 1:1. Fan-out через несколько edges с одного output_port.
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/graph_view.py` — wire creation через drag (`wire_created` signal).
- `multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/graph_scene.py` — CRUD узлов/связей.
- **Унаследованные идеи** из удалённого Constructor (через `git show 9885bb88:`):
  - Display = узел с одним входным портом `frame` и properties (display_key, display_name, fps_limit).
  - Signal suppression context `_block_signals()` для предотвращения циклов sync.

## Новое

### 1. DisplayNodeItem (новый QGraphicsItem) — в `pipeline/graph/display_node_item.py`

- Один входной порт `frame`. Зелёный фон. Properties: `display_id` (combo из DisplayRegistry).
- При создании в сцене — слушает `state.displays.changed` для обновления combo.

### 2. Привязка узла к процессу

- В `pipeline/model.py` (`PipelineModel`) добавить свойство `target_process` у plugin-узла.
- В Inspector-панели (создать новый компонент `pipeline/inspector/node_inspector.py` если нет) — combo с процессами из активного рецепта.

### 3. Двусторонняя сериализация рецепта

- `pipeline/io.py` (новый или существующий) — `graph_to_blueprint(scene) → SystemBlueprint` и обратно `blueprint_to_graph(bp, scene)`.
- Display-узлы → `display_bindings` в рецепте.
- Кнопка «Сохранить в рецепт» пишет в `recipes/<active>.yaml`.

### 4. Валидация wire

- При подключении портов проверка через `PluginRegistry.compatible_with(port)`.
- Несовместимые — красная подсветка.

## Acceptance

- DisplayNodeItem можно добавить в сцену, выбрать display из combo, сохранить в рецепт.
- target_process редактируется в Inspector-панели и попадает в blueprint.
- `graph_to_blueprint` / `blueprint_to_graph` — round-trip без потерь.
- 15-20 unit-тестов: DisplayNodeItem, target_process binding, graph↔blueprint serialization.
- Демо и телеметрия — в Phase 7b.
