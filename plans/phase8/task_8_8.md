### Task 8.8 -- Undo/Redo графовых операций через ActionBus

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Подключить все графовые операции (connect, disconnect, node_add, node_remove, node_move, node_toggle, node_property_change) к ActionBus через новые ActionBuilder-методы и GraphActionHandler.

**Контекст:**
ActionBus (Phase 7) уже поддерживает undo/redo, coalescing и persistence. Для графовых операций нужны: (1) новые `ActionType` значения, (2) методы в `ActionBuilder`, (3) `GraphActionHandler` для apply/revert. Паттерн полностью аналогичен существующим `ChainActionHandler`, `RegionHandler` -- snapshot before/after.

**Файлы:**
- `Inspector_prototype/multiprocess_prototype_v3/frontend/actions/schemas.py` -- добавить ActionType: GRAPH_CONNECT, GRAPH_DISCONNECT, GRAPH_NODE_ADD, GRAPH_NODE_REMOVE, GRAPH_NODE_MOVE
- `Inspector_prototype/multiprocess_prototype_v3/frontend/actions/builder.py` -- добавить методы: `graph_connect()`, `graph_disconnect()`, `graph_node_add()`, `graph_node_remove()`, `graph_node_move()`
- `Inspector_prototype/multiprocess_prototype_v3/frontend/actions/handlers/graph_handler.py` -- **создать**: GraphActionHandler
- `Inspector_prototype/multiprocess_prototype_v3/frontend/actions/handlers/__init__.py` -- зарегистрировать
- `Inspector_prototype/multiprocess_prototype_v3/frontend/widgets/graph_editor/graph_scene.py` -- подключить сигналы к ActionBus
- `Inspector_prototype/multiprocess_prototype_v3/tests/unit/test_graph_actions.py` -- **создать**

**Шаги:**

1. **Расширить `ActionType`** (в `schemas.py`):
   ```python
   # --- Графовый редактор (Phase 8) ---
   GRAPH_CONNECT = "graph_connect"
   GRAPH_DISCONNECT = "graph_disconnect"
   GRAPH_NODE_ADD = "graph_node_add"
   GRAPH_NODE_REMOVE = "graph_node_remove"
   GRAPH_NODE_MOVE = "graph_node_move"
   ```

2. **Добавить методы в `ActionBuilder`:**
   - `graph_connect(region_id, source_node_id, output_port, target_node_id, input_port, nodes_before, nodes_after)` -> Action(GRAPH_CONNECT)
   - `graph_disconnect(region_id, source_node_id, output_port, target_node_id, input_port, nodes_before, nodes_after)` -> Action(GRAPH_DISCONNECT)
   - `graph_node_add(region_id, node_data, nodes_before)` -> Action(GRAPH_NODE_ADD)
     - forward_patch: {node_data, region_id}
     - backward_patch: {nodes_before}
   - `graph_node_remove(region_id, node_id, nodes_before, nodes_after)` -> Action(GRAPH_NODE_REMOVE)
   - `graph_node_move(region_id, node_id, old_pos, new_pos)` -> Action(GRAPH_NODE_MOVE)
     - coalesce_key: `"graph_move:{region_id}:{node_id}"` -- группировка последовательных перемещений

3. **Создать `GraphActionHandler`:**
   - `apply()`: записать `nodes_after` или `node_data` в регистр через `rm.set_field_value(register_name, "vision_pipeline", ...)`
   - `revert()`: записать `nodes_before` в регистр
   - Для GRAPH_NODE_MOVE: apply записывает `new_pos`, revert записывает `old_pos` (только position ноды, не весь snapshot)
   - Паттерн полностью аналогичен `ChainActionHandler`

4. **Регистрация handler:**
   - В `handlers/__init__.py` добавить `GraphActionHandler` для GRAPH_CONNECT, GRAPH_DISCONNECT, GRAPH_NODE_ADD, GRAPH_NODE_REMOVE, GRAPH_NODE_MOVE

5. **Подключение в GraphScene:**
   - GraphScene (или presenter/controller) получает ссылку на `ActionBus`
   - При `edge_created` -> `ActionBus.execute(ActionBuilder.graph_connect(...))`
   - При `edge_removed` -> `ActionBus.execute(ActionBuilder.graph_disconnect(...))`
   - При `node_added` -> `ActionBus.execute(ActionBuilder.graph_node_add(...))`
   - При `node_removed` -> `ActionBus.execute(ActionBuilder.graph_node_remove(...))`
   - При `node_moved` -> `ActionBus.execute(ActionBuilder.graph_node_move(...))`
   - **Важно:** при undo/redo -> GraphScene должна обновить визуал. Подписка через `ActionBus.add_change_callback()` -> перезагрузить граф из регистров.

6. **Тесты:**
   - graph_connect -> undo -> связь удалена -> redo -> связь восстановлена
   - graph_node_add -> undo -> узел удалён
   - graph_node_move: 10 перемещений с одинаковым coalesce_key -> 1 Action в стеке
   - graph_node_remove -> undo -> узел и его связи восстановлены

**Критерии приёмки:**
- [ ] 5 новых ActionType в schemas.py
- [ ] 5 новых методов в ActionBuilder
- [ ] GraphActionHandler зарегистрирован для всех 5 типов
- [ ] Ctrl+Z откатывает: connect, disconnect, add, remove, move
- [ ] Ctrl+Y (redo) восстанавливает
- [ ] node_move coalescing: серия перемещений = 1 Action
- [ ] GraphScene обновляется при undo/redo (визуал соответствует модели)
- [ ] Тесты проходят
- [ ] `ruff check` + `ruff format` проходят

**Вне scope:**
- Batch-операции (удаление нескольких узлов одним Action) -- каждый узел отдельный Action
- Persistence графовых actions в SQLite (уже работает через общий ActionLogWriter)

**Edge cases:**
- Undo node_remove: узел восстанавливается с оригинальным position
- Undo graph_connect: если после connect была изменена позиция ноды, связь корректно восстанавливается
- Redo после серии undo: порядок operations сохраняется

**Зависимости:** Task 8.4 (сигналы GraphScene: node_added, edge_created и т.д.)
