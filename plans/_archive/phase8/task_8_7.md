### Task 8.7 -- Auto-layout (Sugiyama / layered)

**Уровень:** Senior (Opus, normal thinking)
**Исполнитель:** teamlead
**Цель:** Реализовать алгоритм автоматического расположения узлов графа (Sugiyama layered layout) для случаев, когда пользователь впервые открывает граф или нажимает кнопку "Auto Layout".

**Контекст:**
Существующие цепочки из Phase 5 не имеют позиций (`position=None`). При первом открытии графового view нужно автоматически расположить узлы. Алгоритм Sugiyama -- стандарт для DAG-визуализации: (1) layer assignment, (2) crossing minimization, (3) coordinate assignment. Для линейных цепочек -- простой вертикальный/горизонтальный ряд.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/graph_editor/auto_layout.py` -- **создать**
- `multiprocess_prototype/frontend/widgets/graph_editor/graph_scene.py` -- интеграция: вызов auto_layout
- `multiprocess_prototype/tests/unit/test_auto_layout.py` -- **создать**

**Шаги:**

1. **`auto_layout.py`** -- модуль автоматического расположения:
   ```python
   def auto_layout(
       nodes: dict[str, ProcessingNode],
       node_width: float = NODE_WIDTH,
       node_height: float = 80,  # зависит от количества портов
       h_spacing: float = 100,
       v_spacing: float = 60,
       direction: str = "LR",  # left-to-right или "TB" (top-to-bottom)
   ) -> dict[str, tuple[float, float]]:
       """Вычислить позиции узлов по алгоритму Sugiyama (layered).
       
       Returns: {node_id: (x, y)}
       """
   ```

2. **Layer assignment** (аналог level в `parallel.py`):
   - Использовать тот же подход, что в `detect_parallel_bundles`:
     - Узлы без зависимостей -> layer 0
     - Узлы с зависимостями -> max(layer[dep]) + 1
   - Для LR-направления: layer = x-координата (столбец)

3. **Crossing minimization** (barycenter heuristic):
   - Для каждого слоя: упорядочить узлы по среднему положению их зависимостей в предыдущем слое
   - 2-3 итерации (forward + backward pass)
   - Для линейных цепочек crossing minimization тривиально (0 пересечений)

4. **Coordinate assignment:**
   - X: `layer * (node_width + h_spacing)` (для LR)
   - Y: позиция внутри слоя `* (node_height + v_spacing)`, центрировать относительно соседних слоёв
   - Результат: `dict[str, tuple[float, float]]`

5. **Интеграция в GraphScene:**
   - `GraphScene.load_graph()`: если хотя бы одна нода имеет `position=None` -> вызвать `auto_layout()`, записать позиции в ноды
   - Кнопка "Auto Layout" в toolbar графового view -> `auto_layout()` для всех нод -> анимация перемещения (QPropertyAnimation или `QTimeLine` + `setPos`)
   - При auto-layout -> emit `node_moved` для каждого перемещённого узла (для ActionBus)

6. **Тесты:**
   - Линейная цепочка A->B->C -> три столбца, один ряд
   - DAG с ветвлением A->{B,C}->D -> 3 слоя, B и C на одном слое
   - Одна нода -> позиция (0, 0)
   - Пустой граф -> пустой результат

**Критерии приёмки:**
- [ ] Линейная цепочка раскладывается горизонтально (LR) без пересечений
- [ ] DAG с ветвлением: узлы одного уровня в одном столбце
- [ ] Ноды без position -> auto-layout при `load_graph()`
- [ ] Кнопка "Auto Layout" перемещает все узлы
- [ ] Анимация перемещения (300ms, плавно)
- [ ] Позиции snap-to-grid (кратны GRID_SIZE)
- [ ] Тесты проходят
- [ ] `ruff check` + `ruff format` проходят

**Вне scope:**
- Edge routing (маршрутизация рёбер для избежания пересечений с узлами)
- Использование внешних библиотек (grandalf, pygraphviz) -- алгоритм реализуется вручную
- TB (top-to-bottom) направление -- только LR в первой итерации

**Edge cases:**
- Изолированные узлы (без связей) -> выстроить в отдельном столбце справа
- Очень широкий граф (>20 слоёв) -> scroll, не zoom
- Disconnect: нода, потерявшая все связи, остаётся на месте (не перемещается auto-layout)

**Зависимости:** Task 8.3 (GraphScene, NodeItem)
