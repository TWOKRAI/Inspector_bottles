### Task 8.3 -- GraphScene + NodeItem / PortItem / EdgeItem

**Уровень:** Senior+ (Opus, extended thinking)
**Исполнитель:** teamlead
**Цель:** Создать графический canvas на QGraphicsScene/QGraphicsView с визуальными представлениями узлов, портов и связей (Bezier-кривые). Zoom, pan, snap-to-grid.

**Контекст:**
Это центральная UI-задача Phase 8. Создаётся новый пакет `frontend/widgets/graph_editor/` с QGraphicsView-based виджетом. Каждый `ProcessingNode` отображается как `NodeItem` (прямоугольник с заголовком, портами и параметрами). Связи (`NodeInput`) отображаются как `EdgeItem` (Bezier-кривые). Порты (`PortItem`) -- маленькие круги на краях узла, типизированные по цвету.

**Файлы (все -- создать):**
- `multiprocess_prototype/frontend/widgets/graph_editor/__init__.py`
- `multiprocess_prototype/frontend/widgets/graph_editor/graph_view.py` -- QGraphicsView с zoom/pan
- `multiprocess_prototype/frontend/widgets/graph_editor/graph_scene.py` -- QGraphicsScene, управление items
- `multiprocess_prototype/frontend/widgets/graph_editor/node_item.py` -- QGraphicsItem для узла
- `multiprocess_prototype/frontend/widgets/graph_editor/port_item.py` -- QGraphicsItem для порта
- `multiprocess_prototype/frontend/widgets/graph_editor/edge_item.py` -- QGraphicsPathItem для связи (Bezier)
- `multiprocess_prototype/frontend/widgets/graph_editor/constants.py` -- цвета, размеры, grid step
- `multiprocess_prototype/frontend/widgets/graph_editor/model.py` -- GraphEditorModel (данные из region.nodes)

**Шаги:**

1. **`constants.py`** -- визуальные константы:
   ```python
   GRID_SIZE = 20           # пиксели
   NODE_WIDTH = 180
   NODE_HEADER_HEIGHT = 28
   PORT_RADIUS = 6
   PORT_SPACING = 22
   EDGE_WIDTH = 2.0
   ZOOM_MIN = 0.2
   ZOOM_MAX = 5.0
   ZOOM_STEP = 1.15
   
   # Цвета портов по типу данных
   PORT_COLORS = {
       "image": QColor("#4FC3F7"),      # голубой
       "mask": QColor("#81C784"),       # зелёный
       "detections": QColor("#FFB74D"), # оранжевый
       "contours": QColor("#CE93D8"),   # фиолетовый
       "any": QColor("#BDBDBD"),        # серый
   }
   
   NODE_BG_COLOR = QColor("#2D2D2D")
   NODE_HEADER_COLOR = QColor("#3D3D3D")
   NODE_SELECTED_BORDER = QColor("#FFA726")
   NODE_DISABLED_OPACITY = 0.4
   EDGE_COLOR = QColor("#90CAF9")
   EDGE_INVALID_COLOR = QColor("#EF5350")
   ```

2. **`port_item.py`** -- `PortItem(QGraphicsEllipseItem)`:
   - Свойства: `port_name`, `data_type`, `is_input`, `parent_node_item`
   - Цвет по `data_type` из `PORT_COLORS`
   - Метод `center_scene_pos()` -- позиция центра порта в scene coordinates (для EdgeItem)
   - Hover: подсветка + tooltip с именем и типом
   - Input-порты -- слева от NodeItem, output-порты -- справа

3. **`node_item.py`** -- `NodeItem(QGraphicsItem)`:
   - Принимает `ProcessingNode` + `ProcessingOperationDef` (для имени и портов)
   - Рисует: заголовок (имя операции), input/output порты (создаёт `PortItem` как child items)
   - `setFlag(ItemIsMovable | ItemIsSelectable | ItemSendsGeometryChanges)`
   - `itemChange(ItemPositionHasChanged)` -> обновляет position ноды + перерисовывает EdgeItem'ы
   - Snap-to-grid в `itemChange`: округление позиции до `GRID_SIZE`
   - Disabled nodes: `setOpacity(NODE_DISABLED_OPACITY)`
   - Метод `get_port(name, is_input) -> PortItem | None`
   - Метод `update_from_node(node: ProcessingNode)` -- обновить позицию и состояние

4. **`edge_item.py`** -- `EdgeItem(QGraphicsPathItem)`:
   - Принимает `source_port: PortItem`, `target_port: PortItem`
   - Рисует Bezier-кривую (QPainterPath с cubicTo) между центрами портов
   - Цвет: `EDGE_COLOR` по умолчанию, `EDGE_INVALID_COLOR` если типы несовместимы
   - Метод `update_path()` -- пересчитать Bezier при перемещении узлов
   - Стрелка на конце (target) -- маленький треугольник
   - Hover: утолщение + подсветка

5. **`graph_scene.py`** -- `GraphScene(QGraphicsScene)`:
   - `load_graph(nodes: dict[str, ProcessingNode], catalog: dict[str, ProcessingOperationDef])`:
     - Очистить scene
     - Создать `NodeItem` для каждой ноды
     - Создать `EdgeItem` для каждого `NodeInput`
     - Если `node.position` is None -- расположить по умолчанию (вертикальный список с отступом)
   - `add_node(node, op_def) -> NodeItem`
   - `remove_node(node_id: str)`
   - `add_edge(source_node_id, output_port, target_node_id, input_port) -> EdgeItem`
   - `remove_edge(edge_item)`
   - Сигналы: `node_moved(node_id, x, y)`, `edge_created(source_id, out_port, target_id, in_port)`, `edge_removed(...)`, `node_selected(node_id)`, `selection_changed(node_ids: list[str])`
   - `_node_items: dict[str, NodeItem]`, `_edge_items: list[EdgeItem]`
   - Grid: рисовать точки/линии через `drawBackground()` override

6. **`graph_view.py`** -- `GraphView(QGraphicsView)`:
   - Zoom: `wheelEvent` -> `scale()` с зажимом `[ZOOM_MIN, ZOOM_MAX]`
   - Pan: middle mouse button drag (или Ctrl+LMB drag)
   - `setDragMode(RubberBandDrag)` для выделения группы
   - `setRenderHints(Antialiasing | SmoothPixmapTransform)`
   - `setViewportUpdateMode(FullViewportUpdate)` для корректной отрисовки grid
   - Fit-to-content: `fitInView(scene.itemsBoundingRect(), Qt.KeepAspectRatio)` по горячей клавише (например, Home)

7. **`model.py`** -- `GraphEditorModel`:
   - Хранит ссылку на `region_id`, `nodes: dict[str, ProcessingNode]`, `catalog`
   - Предоставляет методы для мутации: `add_node()`, `remove_node()`, `connect()`, `disconnect()`, `move_node()`
   - Каждая мутация возвращает tuple `(old_state, new_state)` для ActionBuilder
   - Валидация: проверка ацикличности при `connect()`, совместимость портов

**Критерии приёмки:**
- [ ] `GraphView` отображает scene с grid (точки через GRID_SIZE)
- [ ] Zoom колесом мыши работает в пределах [0.2, 5.0]
- [ ] Pan средней кнопкой мыши
- [ ] `NodeItem` отображает заголовок операции + порты слева/справа
- [ ] `PortItem` окрашен по типу данных
- [ ] `EdgeItem` рисует Bezier между портами
- [ ] Перетаскивание `NodeItem` -> snap-to-grid + обновление EdgeItem
- [ ] Disabled ноды полупрозрачны
- [ ] `GraphScene.load_graph()` загружает существующие `region.nodes` без ошибок
- [ ] `ruff check` + `ruff format` проходят

**Вне scope:**
- Drag-создание связей (Task 8.4)
- Контекстное меню (Task 8.4)
- Catalog palette (Task 8.5)
- Undo/Redo (Task 8.8)
- Интеграция с табличной view (Task 8.6)

**Edge cases:**
- Пустой граф (0 нод) -- показать placeholder "Перетащите операцию из каталога"
- Нода без позиции (`position=None`) -- авто-расположение по вертикали
- Нода с 0 input-портов (source) -- без портов слева
- Нода с 0 output-портов (sink) -- без портов справа
- Очень длинное имя операции -- обрезка с `...`

**Зависимости:** Task 8.1 (Port schema, PORT_COLORS по data_type)
