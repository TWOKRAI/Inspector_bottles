---
title: pipeline_tab — DAG-конструктор для Inspector_bottles
created: 2026-04-26
---

# pipeline_tab — DAG-конструктор для Inspector_bottles

Единая вкладка Pipeline: визуальный редактор цепочки обработки изображений (DAG),
библиотека блоков, переключаемые виды (граф / таблица) и панель инспектора свойств.

---

## Архитектура

```
┌──────────────────────────────────────────────────────────────────────────┐
│                     PipelineTabWidget (widget.py)                        │
│                                                                          │
│  ┌──────────────┐  ┌────────────────────────────────┐  ┌─────────────┐  │
│  │ LibraryPalette│  │   PipelineViewSwitch           │  │ InspectorPanel│ │
│  │ (palette)    │  │   (view_switch.py)              │  │ (inspector_ │  │
│  │ QTreeWidget  │  │  ┌──────────┬───────────────┐  │  │  panel.py)  │  │
│  │ drag-source  │  │  │ page 0   │ page 1        │  │  │             │  │
│  │ MIME drop    │  │  │ NodeGraph│ PipelineTable │  │  │ ProcessId   │  │
│  │    |         │  │  │ .widget  │ View          │  │  │ Combo       │  │
│  │    v         │  │  │ (canvas) │ (table_view)  │  │  │ DisplayTarget│ │
│  │ LibraryDrop  │  │  └──────────┴───────────────┘  │  │ Combo       │  │
│  │ Target       │  └────────────────────────────────┘  │ ParamsForm  │  │
│  │ eventFilter  │                                        └─────────────┘  │
│  └──────────────┘                                                         │
└────────────────────────────────────┬─────────────────────────────────────┘
                 MIME drop / signals  │  node_selected / selection_cleared
                                      v
┌──────────────────────────────────────────────────────────────────────────┐
│              NodeGraphQtAdapter (adapter.py) — QObject                   │
│  - node_map: {node_id -> InspectorBaseNode} (двусторонний маппинг)       │
│  - _block_signals(): context manager против рекурсии сигналов            │
│  - load_pipeline(nodes)  / apply_layout(positions)                       │
│  - add_node_from_catalog(op_ref, pos) — единая точка входа для drag-drop │
│                                                                          │
│  NodeGraphQt Qt-signals -> record(Action) -> ActionBus                   │
│  ActionBus undo/redo -> _refresh_from_model()                            │
└──────────────────────────────────────┬───────────────────────────────────┘
                                        │  Action.execute() / record()
                                        v
┌──────────────────────────────────────────────────────────────────────────┐
│  GraphEditorModel (model.py) — SSOT для in-memory DAG                    │
│  ActionBus + GraphActionHandler — undo/redo стек                         │
│  auto_layout.py (Sugiyama) / linearity_check.py                          │
└──────────────────────────────────────┬───────────────────────────────────┘
                                        │  Pipeline.to_router_topology()
                                        v
                           Runtime: RouterManager + ProcessRegistry
```

---

## Ключевые компоненты

| Компонент | Файл | Ответственность |
|---|---|---|
| `PipelineTabWidget` | `widget.py` | Composition-root: создаёт NodeGraph, адаптер, палитру, inspector |
| `LibraryPalette` | `library_palette.py` | Дерево операций по категориям + текстовый фильтр; drag-source |
| `LibraryDropTarget` | `library_palette.py` | eventFilter на viewport NodeGraphQt; MIME → `adapter.add_node_from_catalog` |
| `NodeGraphQtAdapter` | `adapter.py` | Мост NodeGraphQt-сигналы ↔ ActionBus; identity-маппинг `node_id ↔ InspectorBaseNode` |
| `InspectorBaseNode` | `inspector_node.py` | Subclass `BaseNode` (NodeGraphQt); проксирует thumbnail API в `InspectorNodeItem` |
| `InspectorNodeItem` | `inspector_node.py` | Subclass `NodeItem`; `QGraphicsPixmapItem` overlay (Issue #491 — не paint()) |
| `NodePreviewBridge` | `preview_bridge.py` | `DisplayRouter` → QPixmap thumbnail; throttle ~10 FPS + viewport culling |
| `InspectorPanel` | `inspector_panel.py` | Секции process_id / display_targets / params; все изменения через `ActionBus.record` |
| `ParamsForm` | `params_form.py` | `QFormLayout` по полям `params_class`; типы: bool, int, float, Literal, List[int], str |
| `ProcessIdCombo` | `process_id_combo.py` | QComboBox выбора process_id с editable-режимом |
| `DisplayTargetCombo` | `display_target_combo.py` | Multi-select дисплеев для display_capable-операций |
| `PipelineViewSwitch` | `view_switch.py` | `QToolButton` + `QStackedWidget`; синхронизация выделения graph ↔ table |
| `PipelineTableView` | `table_view.py` | Плоский `QTreeView`; inline bulk-edit `process_id` и `enabled` |
| `GraphEditorModel` | `model.py` | SSOT DAG: `add_node`, `remove_node`, `connect`, `disconnect`, `modify_node`, проверка ацикличности (DFS) |

---

## Где живёт state

`GraphEditorModel.nodes` — словарь `node_id -> ProcessingNode` в памяти (runtime-only,
сбрасывается при закрытии). Персистентность — через `RecipeEngine`
(`cameras.{cid}.regions.{rid}.nodes` ветка `TreeStore`); pipeline_tab читает
это хранилище через `PipelineTabWidget.set_pipeline(nodes)` и сохраняет
через `current_pipeline()`. Каталог операций (`processing_catalog.yaml`) —
read-only, загружается при старте и передаётся во все компоненты через `catalog: dict`.

---

## Как добавить новую операцию

Пример: добавляем «Gaussian Blur» в категорию Preprocess.

### Шаг 1. Схема параметров

Создай `registers/processor/processings/blur_params.py`:

```python
from typing import Annotated, Literal
from data_schema_module import SchemaBase, FieldMeta, register_schema
from registers.processor.processings.base_params import ProcessingParamsBase

@register_schema("BlurParamsV3")
class BlurParams(ProcessingParamsBase):
    type: Literal["blur"] = "blur"
    kernel_size: Annotated[int, FieldMeta("Размер ядра", min=1, max=99, info="Нечётный.")] = 5
    sigma: Annotated[float, FieldMeta("Sigma", min=0.0, max=20.0, unit="")] = 1.0
```

### Шаг 2. Реализация операции

Создай `services/processor/operations/preprocess/blur_op.py`:

```python
class BlurOp:
    def __init__(self, params: BlurParams) -> None:
        self._params = params

    def process(self, ctx, frame):
        import cv2
        k = self._params.kernel_size
        if k % 2 == 0:
            k += 1
        return cv2.GaussianBlur(frame, (k, k), self._params.sigma)
```

### Шаг 3. Запись в каталог

Добавь запись в `data/processing_catalog.yaml`:

```yaml
- type_key: gaussian_blur
  name: "Gaussian Blur"
  category: "Preprocess"
  params_schema: "registers.processor.processings.blur_params.BlurParams"
  module_path: "services.processor.operations.preprocess.blur_op.BlurOp"
  on_error: skip
  description: "Гауссово размытие OpenCV."
  input_ports:
    - { name: "in", data_type: "image" }
  output_ports:
    - { name: "out", data_type: "image" }
  multiplicity: fixed
  display_capable: true
```

### Шаг 4. Проверка

Перезапусти приложение. Новая операция появится в `LibraryPalette` под
категорией «Preprocess — предобработка». Параметры (`kernel_size`, `sigma`)
авто-генерируются `ParamsForm` через `params_class.get_all_fields_meta()`.
Если `display_capable: true` — `DisplayTargetCombo` в инспекторе активна.

---

## Как кастомизировать ноду

Для кастомного внешнего вида — создай subclass `InspectorBaseNode`:

```python
from frontend.widgets.pipeline_tab.inspector_node import InspectorBaseNode

class MyNode(InspectorBaseNode):
    __identifier__ = "myapp.nodes"
    NODE_NAME = "MyNode"
    # Переопредели update_thumbnail или set_active_preview
```

Зарегистрируй до первого `create_node`:

```python
graph.register_node(MyNode)
node = graph.create_node("myapp.nodes.MyNode")
```

Управление thumbnail:
- `set_display_capable(False)` — полностью убирает overlay (для операций без preview).
- `set_active_preview(True/False)` — включает/выключает показ кадров в рантайме.
- `update_thumbnail(pixmap)` — обновляет кадр (вызывает `NodePreviewBridge`).

**Важно:** не переопределяй `NodeItem.paint()` целиком — это ломает selection
highlight и proxy mode (Issue #491). Используй `add_widget()` или дочерний
`QGraphicsPixmapItem`, как сделано в `InspectorNodeItem` (`inspector_node.py`).

---

## Тесты

| Файл | Покрытие |
|---|---|
| `tests/unit/test_phase9_node_graphqt_adapter.py` | Adapter: сигналы → Action'ы (24 кейса) |
| `tests/unit/test_phase9_inspector_panel.py` | InspectorPanel + ParamsForm + GRAPH_NODE_MODIFY (31) |
| `tests/unit/test_phase9_library_palette.py` | LibraryPalette: drag-drop MIME, фильтр (15) |
| `tests/unit/test_phase9_two_view.py` | PipelineViewSwitch: selection sync graph ↔ table (30) |
| `tests/unit/test_phase9_pipeline_tab_widget.py` | PipelineTabWidget: composition (16) |
| `tests/unit/test_phase9_pipeline_smoke.py` | Pipeline-pydantic snapshot |
| `tests/integration/test_phase9_topology_e2e.py` | Topology e2e (runtime) |

Запуск:

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m pytest \
  tests/unit/test_phase9_*.py \
  tests/integration/test_phase9_topology_e2e.py \
  -x --no-header -p no:cacheprovider
```

---

## Известные ограничения / TODO

- `processing_catalog` в `tab_factory.py` пока подаётся пустым через `ctx.extras`;
  реальная загрузка YAML — Phase 10.
- Старые вкладки (camera, processing, post_processing, cropped_regions, display)
  ещё в `tab_factory.py`; `pipeline_tab` их не вытесняет (Phase 10+).
- ML-операции (YOLO, ONNX) — категория Detect, реализация Phase 10.
- Multi-region table view — Phase 10+ (сейчас показывает одну region).
- Bulk-action для N нод: пока N отдельных `GRAPH_NODE_MODIFY` (нет составного патча).
- `NodePreviewBridge` создаётся адаптером при `add_node`, удаляется при `remove_node`;
  при `_refresh_from_model()` (undo/redo) мосты пересоздаются — подписки сбрасываются.

---

## Связанная документация

- Phase 9 план: `projects/Inspector_bottles/plans/phase9_pipeline_builder_nodegraphqt.md`
- Pipeline Pydantic-модели (Phase 5a): `registers/pipeline/`
- Схема операции из каталога: `registers/processor/catalog/schemas.py` (`ProcessingOperationDef`)
- Базовый класс операций: `services/processor/operations/base.py`
- Framework narrative: `Inspector_prototype/docs/claude/FRAMEWORK_CONSTRUCTOR_OVERVIEW.md`
