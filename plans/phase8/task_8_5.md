### Task 8.5 -- Catalog palette + drag-drop на canvas

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Создать панель каталога операций (слева от графа) с поддержкой drag-drop для добавления новых узлов на canvas.

**Контекст:**
Пользователь должен видеть доступные операции из каталога (`ProcessingOperationDef`) и перетаскивать их на canvas для создания новых узлов. Палитра -- `QListWidget` или `QTreeWidget` с группировкой по категориям. При drop на GraphScene создаётся новый `ProcessingNode` с default параметрами.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/graph_editor/catalog_palette.py` -- **создать**
- `multiprocess_prototype/frontend/widgets/graph_editor/graph_scene.py` -- расширить: `dropEvent` для приёма операций
- `multiprocess_prototype/frontend/widgets/graph_editor/graph_view.py` -- `setAcceptDrops(True)`

**Шаги:**

1. **`catalog_palette.py`** -- `CatalogPalette(QWidget)`:
   - Внутри: `QVBoxLayout` с поиском (`QLineEdit` сверху) + `QListWidget`
   - `load_catalog(catalog: dict[str, ProcessingOperationDef])` -- заполнить список
   - Каждый item: имя операции, иконка (по типу: processing=gear, detection=eye и т.д.), tooltip с description
   - Фильтрация по тексту в QLineEdit (case-insensitive)
   - **Drag:** `QListWidget.setDragEnabled(True)`, custom `QMimeData`:
     - MIME type: `application/x-inspector-operation`
     - Data: `type_key` операции (строка)
   - Стиль: компактный, ширина ~200px

2. **Drop на GraphScene:**
   - `GraphScene.dragEnterEvent` / `dragMoveEvent` -- проверить MIME type, `acceptProposedAction()`
   - `GraphScene.dropEvent`:
     - Извлечь `type_key` из `QMimeData`
     - Найти `ProcessingOperationDef` по `type_key` в каталоге
     - Создать `ProcessingNode` с:
       - `node_id = str(uuid4())`
       - `operation_ref = type_key`
       - `params = {}` (default)
       - `enabled = True`
       - `position = (scene_x, scene_y)` -- позиция drop
       - `inputs = []` -- без связей
     - Вызвать `GraphScene.add_node()` + emit `node_added` signal

3. **GraphView** -- `setAcceptDrops(True)` и проброс drop-событий в scene:
   - `dragEnterEvent`, `dragMoveEvent`, `dropEvent` -- конвертировать viewport coordinates в scene coordinates и передать в scene

4. **Визуальная обратная связь при drag-over:**
   - При drag над canvas -- полупрозрачный "ghost" NodeItem (preview) в позиции курсора
   - При drag за пределы canvas -- ghost исчезает

**Критерии приёмки:**
- [ ] CatalogPalette показывает все операции из каталога
- [ ] Поиск фильтрует операции по имени
- [ ] Drag операции из палитры на canvas создаёт новый узел
- [ ] Узел создаётся в позиции drop
- [ ] `node_added` signal emit'ится при drop
- [ ] Ghost-preview при drag-over
- [ ] Палитра занимает ~200px слева
- [ ] `ruff check` + `ruff format` проходят

**Вне scope:**
- Группировка операций по категориям (пока flat list)
- Иконки операций (пока текстовый список)
- Undo/Redo при drop (Task 8.8)

**Edge cases:**
- Drop за пределами scene -> игнорировать
- Каталог пуст -> палитра показывает "Нет доступных операций"
- Drop с зажатым Ctrl -> не дублировать (одна операция = один узел)

**Зависимости:** Task 8.3 (GraphScene с `add_node`)
