### Task 8.6 -- View switch: таблица <-> граф

**Уровень:** Middle+ (Sonnet, extended thinking)
**Исполнитель:** developer
**Цель:** Реализовать переключатель между табличным представлением (существующий processing panel) и графовым представлением (GraphView) для одного `region.nodes`. При наличии ветвлений в табличном виде -- WARN.

**Контекст:**
Текущий UI обработки -- табличный (ProcessingPanelWidget, cropped_regions_widget). Phase 8 добавляет графовый вид, но табличный остаётся для простых линейных цепочек. Оба view работают с одной моделью `region.nodes` -- переключение не конвертирует данные, только меняет представление.

**Файлы:**
- `Inspector_prototype/multiprocess_prototype_v3/frontend/widgets/graph_editor/view_switch.py` -- **создать**: виджет-контейнер с кнопкой переключения
- `Inspector_prototype/multiprocess_prototype_v3/frontend/widgets/graph_editor/linearity_check.py` -- **создать**: утилита проверки линейности графа
- `Inspector_prototype/multiprocess_prototype_v3/frontend/widgets/tabs_setting/processing_tab/widget.py` -- расширить: встроить ViewSwitchWidget

**Шаги:**

1. **`linearity_check.py`** -- утилита проверки линейности графа:
   ```python
   def is_linear(nodes: dict[str, ProcessingNode]) -> bool:
       """Проверить, что граф линеен (каждая нода <= 1 input, <= 1 dependent)."""
       # Подсчитать in_degree и out_degree
       # Линеен если max(in_degree) <= 1 и max(out_degree) <= 1
   
   def get_linearity_warning(nodes: dict[str, ProcessingNode]) -> str | None:
       """Вернуть предупреждение если граф нелинеен, иначе None."""
       # "Граф нелинеен: {N} ветвлений, {M} merge. Часть связей скрыта в табличном виде."
   ```

2. **`view_switch.py`** -- `ViewSwitchWidget(QWidget)`:
   - Содержит `QStackedWidget` с двумя страницами:
     - Page 0: табличное представление (существующий виджет цепочки из cropped_regions_widget)
     - Page 1: `GraphView` с `CatalogPalette` (QSplitter: palette | graph_view)
   - Кнопка-переключатель: `QPushButton` или `QToolButton` с иконками (таблица/граф)
   - При переключении на табличный вид:
     - Вызвать `is_linear(region.nodes)`
     - Если нелинеен -> показать `QLabel` с предупреждением (жёлтый фон) над таблицей
   - При переключении на граф:
     - `GraphScene.load_graph(region.nodes, catalog)`
   - Сигнал `view_changed(mode: str)` -- "table" | "graph"

3. **Интеграция в ProcessingTab:**
   - В `ProcessingTabWidget` (или его родителе `cropped_regions_tab`) заменить прямое использование виджета цепочки на `ViewSwitchWidget`
   - `ViewSwitchWidget` получает ссылку на `region_id` и `RegistersManager`
   - При изменении region.nodes (через регистры) -> обновить текущую view

4. **Синхронизация модели:**
   - Граф и таблица работают с одной моделью `region.nodes`
   - При переключении view -> не создавать/конвертировать данные, только отображать
   - Мутации в графовом view -> обновляют `region.nodes` -> табличная view покажет актуальное при переключении

**Критерии приёмки:**
- [ ] Кнопка переключения таблица/граф видна в UI
- [ ] Переключение не изменяет `region.nodes`
- [ ] В табличном виде при нелинейном графе -- жёлтое предупреждение
- [ ] В графовом виде -- все узлы и связи отображаются
- [ ] Мутация в одном view видна после переключения на другой
- [ ] `ruff check` + `ruff format` проходят

**Вне scope:**
- Одновременное отображение обеих view (split-view)
- Редактирование в табличном виде нелинейных связей

**Edge cases:**
- Регион без узлов -> обе view показывают placeholder
- Регион с одним узлом -> обе view корректны
- Переключение view во время drag-операции (не должно крашить)

**Зависимости:** Task 8.3 (GraphScene, GraphView), Task 8.4 (интеракции в графовом view)
