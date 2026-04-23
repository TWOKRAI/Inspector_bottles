### Task 8.4 -- Интеракции: drag-создание связей, Del, контекстное меню

**Уровень:** Senior (Opus, normal thinking)
**Исполнитель:** teamlead
**Цель:** Реализовать пользовательские интеракции графового редактора: drag для создания связей между портами, удаление узлов/связей по Del, контекстное меню для узлов.

**Контекст:**
GraphScene из Task 8.3 показывает статический граф. Эта задача добавляет редактирование: пользователь тянет мышь от output-порта к input-порту для создания связи, нажимает Del для удаления, правый клик для контекстного меню (Enable/Disable, Set Process, Set Worker, Duplicate).

**Файлы:**
- `Inspector_prototype/multiprocess_prototype_v3/frontend/widgets/graph_editor/graph_scene.py` -- расширить: drag-connect, delete
- `Inspector_prototype/multiprocess_prototype_v3/frontend/widgets/graph_editor/port_item.py` -- расширить: начало drag
- `Inspector_prototype/multiprocess_prototype_v3/frontend/widgets/graph_editor/edge_item.py` -- добавить "provisional edge" (тянущаяся линия)
- `Inspector_prototype/multiprocess_prototype_v3/frontend/widgets/graph_editor/context_menu.py` -- **создать**: контекстное меню узла
- `Inspector_prototype/multiprocess_prototype_v3/frontend/widgets/graph_editor/model.py` -- расширить: методы мутации

**Шаги:**

1. **Drag-создание связи:**
   - `PortItem.mousePressEvent` на output-порту -> начинает drag
   - `GraphScene` создаёт provisional `EdgeItem` (без target_port, конец следует за курсором)
   - `GraphScene.mouseMoveEvent` -> обновляет конец provisional edge
   - `GraphScene.mouseReleaseEvent`:
     - Если cursor над input-портом -> проверить совместимость типов
       - Совместимы -> `GraphScene.add_edge()` + emit `edge_created` signal
       - Несовместимы -> provisional edge мигает красным и исчезает
     - Если не над портом -> provisional edge исчезает
   - Запрет: output->output, input->input, соединение порта с самим собой (один и тот же узел)

2. **Визуальная подсветка при drag:**
   - При начале drag от output-порта -> подсветить все совместимые input-порты (зелёным ободком)
   - Несовместимые порты -> полупрозрачные
   - При наведении на совместимый порт -> увеличить порт

3. **Удаление (Del):**
   - `GraphView.keyPressEvent(Qt.Key_Delete)`:
     - Если выделены EdgeItem'ы -> удалить связи (emit `edge_removed`)
     - Если выделены NodeItem'ы -> удалить узлы и все их связи (emit `node_removed`)
     - Multi-select: удалить все выделенные
   - Confirmation: не нужен для связей, для узлов -- `QMessageBox.question` если выделено > 1 узла

4. **Контекстное меню узла:**
   - Правый клик на `NodeItem` -> `QMenu`:
     - **Enable / Disable** -- toggle `node.enabled`, обновить визуал (opacity)
     - **Set Process** -> submenu с доступными процессами (список из RegistersManager)
     - **Set Worker** -> submenu с доступными worker'ами (None = auto)
     - **Duplicate** -- создать копию узла (новый node_id, position += (40, 40))
     - **Delete** -- удалить узел
   - Правый клик на EdgeItem -> `QMenu`:
     - **Delete connection** -- удалить связь
   - Правый клик на пустом месте -> `QMenu`:
     - **Fit to content** -- zoom to fit all
     - **Select All** -- Ctrl+A

5. **Сигналы из GraphScene для интеграции с ActionBus (Task 8.8):**
   - `node_added(node_data: dict)` -- при Duplicate или drag-drop из каталога
   - `node_removed(node_id: str, node_data: dict)` -- при Delete
   - `node_toggled(node_id: str, enabled: bool)` -- при Enable/Disable
   - `node_property_changed(node_id: str, prop: str, old_val, new_val)` -- при Set Process/Worker
   - `edge_created(source_id, out_port, target_id, in_port)` -- при создании связи
   - `edge_removed(source_id, out_port, target_id, in_port)` -- при удалении связи

**Критерии приёмки:**
- [ ] Drag от output к совместимому input создаёт связь (Bezier-кривая)
- [ ] Drag к несовместимому input -- кривая мигает красным и исчезает
- [ ] Drag от input или к output -- ничего не происходит
- [ ] Совместимые порты подсвечиваются зелёным при drag
- [ ] Del удаляет выделенные узлы и связи
- [ ] Контекстное меню: Enable/Disable меняет opacity
- [ ] Контекстное меню: Duplicate создаёт копию со смещением
- [ ] Все сигналы emit'ятся корректно
- [ ] `ruff check` + `ruff format` проходят

**Вне scope:**
- Undo/Redo (Task 8.8) -- здесь только emit сигналов, подключение к ActionBus в 8.8
- Catalog palette drag-drop (Task 8.5)
- Auto-layout (Task 8.7)

**Edge cases:**
- Drag-связь на порт, уже имеющий связь -> заменить старую связь (input-порт принимает только одну связь, output-порт может иметь несколько)
- Duplicate узла, подключённого к disabled ноде -- копия не наследует связи
- Delete единственного узла -> пустой граф + placeholder

**Зависимости:** Task 8.3 (GraphScene, NodeItem, PortItem, EdgeItem)
