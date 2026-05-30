# Pipeline UX: дисплеи в списке, скрытие gui, auto-layout, карточки

**Slug:** pipeline-ux-displays-gui-layout
**Ветка:** refactor/config-driven-launch (правки поверх текущей)
**Статус:** in progress

## Контекст

4 жалобы пользователя по вкладке Pipeline (проверено в работающем приложении через qt-mcp):

1. **В списке нет дисплеев.** Палитра грузит только плагины; дисплеи доступны лишь
   через ПКМ по фону → «Add Display →». Нужно: дисплеи в левом списке, drag → display-бокс.
2. **Нода `gui` бессмысленна.** `gui` из `backend/topology/base.yaml` (`protected: true`)
   попадает в топологию и рисуется на графе. Нужно: не показывать protected-процессы.
3. **Карточки не показываются при выборе.** Карточка появляется, но: (а) на старте граф —
   мешанина наложенных нод → клики мимо; (б) поля параметров пусты (имена процессов в
   редакторе ≠ именам запущенного рецепта → `registers_manager.get_fields` пуст).
4. **Нет раскладки при старте.** `_load_topology` грузит без auto-layout.

## Задачи

### Task 1 — Скрыть protected-процессы из графа (issue 2)
- **Файл:** `presenter.py` → `_topology_to_graph`
- Пропускать процессы с `protected == True` (gui-фундамент). Рёбра к ним отсеются
  автоматически (`add_edge` вернёт None при отсутствии target).
- [x] Реализовано

### Task 2 — Auto-layout при старте (issue 4)
- **Файл:** `tab.py` → `_load_topology`
- После `load_scene_with_ports` вызвать `auto_layout_scene()` + `fit_to_view()`.
- [x] Реализовано

### Task 3 — Дисплеи в палитре + drag (issue 1)
- **Файлы:** `palette/palette_widget.py`, `palette/drop_target.py`, `tab.py`
- Палитра: секция «Displays — дисплеи», элементы тащатся с MIME `x-inspector-display`.
- DropTarget: принимать display-MIME → callback `on_display_drop`.
- Tab: грузить дисплеи в палитру; drop → `presenter.place_display(display_id, x, y)`.
- [x] Реализовано

### Task 4 — Надёжный показ карточки (issue 3, слой A)
- Следствие Task 2: после auto-layout клики по нодам надёжны → карточка стабильно
  появляется. Отдельного кода не требует.
- [x] Покрыто Task 2

### Task 5 — Редактируемые параметры в карточке (issue 3, слой B) — ПОСЛЕ Task 1–4
- **Директива пользователя:** переиспользовать виджеты конфигурации плагина из
  вкладки Plugins (не дублировать код). Карточка ноды под графом должна рендерить
  тот же per-plugin config-виджет, что и Plugins-tab.
- Найти компонент Plugins-tab (config panel / forms factory по plugin_name) и
  встроить его в `NodeInspectorPanel.show_plugin_node`.
- [x] Реализовано. Корень: `inspector_panel.py` строил поля по `node_id` (process_name),
  а `RegistersManager.get_fields` ключует по plugin_name. Фикс: `show_plugin_node`
  получил параметр `plugin_name`; tab берёт его + config из `plugins[0]`. Поля строит
  тот же `CardsFieldFactory` + `RegistersManager.get_fields(plugin_name)`, что и
  `PluginsPresenter.get_register_fields` — без дублирования.

## Проверка
- [x] pytest вкладки pipeline зелёный (421 passed, +11 новых тестов)
- [x] ruff check / format чистые
- [x] Live smoke (qt-mcp): gui скрыт, граф разложен на старте, дисплеи в списке
  («Debug дисплей (debug)» / «Основной дисплей (main)»), карточка `preprocessor`
  показывает поля resize (scale_factor=1.0, interpolation=linear)

### Task 6 — Display-нода-сток в конце пайплайна (issue: «в конце должна быть нода дисплей»)
- **Корень:** редактор грузит region_pipeline (app.yaml: pipeline), где вывод по старой
  модели `chain_targets:[gui]` и НЕТ секции `displays` → бокса-стока нет. Плюс
  `merge_topologies` отбрасывала секцию `displays`.
- Фиксы:
  - `backend/launch.py merge_topologies` — переносит `displays` (+ `metadata`).
  - `backend/topology/region_pipeline.yaml` — `displays: [{node_id: stitcher.stitcher.frame,
    display_id: main}]` → Display-бокс «Основной дисплей» на выходе stitcher.
  - `presenter.auto_layout_scene` — display-боксы участвуют в раскладке (binding-ребро
    source→box) → сток встаёт в конце графа, а не на fallback-позиции.
- [x] Live: граф `camera_0 → … → stitcher → Display «Основной дисплей»` (бокс в конце)
- [x] Тесты: pipeline 421 + base_merge 12 зелёные

## Изменённые файлы
- `presenter.py` — фильтр protected в `_topology_to_graph`
- `tab.py` — auto-layout в `_load_topology`; дисплеи в `_load_palette`;
  `_on_display_dropped`; `plugin_name`+config в `_on_selection_changed`
- `palette/palette_widget.py` — MIME_TYPE_DISPLAY, `_KIND_ROLE`, `load_displays`,
  выбор MIME в `startDrag`
- `palette/drop_target.py` — приём display-MIME, callback `on_display_drop`
- `inspector/inspector_panel.py` — параметр `plugin_name`, поля по plugin_name
- tests: test_palette / test_inspector / test_presenter_enhanced (+11)
