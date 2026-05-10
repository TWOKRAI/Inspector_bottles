# План: Фаза 3 конструктора -- правые панели + SHM конфигурация

**Дата:** 2026-05-04
**Статус:** DONE

## Обзор

Фаза 3 добавляет интерактивные правые панели в ConstructorTabWidget: при клике
на ноду (процесс) открывается ProcessPluginPanel с chain editor / catalog / config;
при клике на wire открывается WireInspectorPanel с настройками транспорта и SHM.
Также реализуется edge->wire_key маппинг в адаптере и Save/Load Blueprint кнопки в toolbar.

Фазы 1-2 DONE: WireDefinition + WiresSectionView + WireEditorModel (Фаза 1),
NodeGraphQt канвас + PluginGraphAdapter + CrossProcessModel + GraphBuilder (Фаза 2).

## Порядок выполнения

### Phase 1: Панели (standalone виджеты)
- Task 1.1: ShmConfigPanel [DONE]
- Task 1.2: WireInspectorPanel [DONE]
- Task 1.3: ProcessPluginPanel [DONE]

### Phase 2: Интеграция в widget.py + адаптер
- Task 2.1: Edge->wire_key маппинг в адаптере [DONE]
- Task 2.2: QStackedWidget правой панели + wiring сигналов [DONE]
- Task 2.3: Toolbar расширение (Save/Load Blueprint) [DONE]

### Phase 3: Тесты
- Task 3.1: Unit-тесты панелей и интеграции [DONE]

---

## Детальные задачи

### Task 1.1 -- ShmConfigPanel

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Создать виджет формы SHM-конфигурации для wire-канала.

**Context:** ShmConfigPanel -- форма для редактирования полей ShmWireConfig
(shm_name, buffer_slots, owner_process, strategy). Показывается внутри
WireInspectorPanel когда transport=router (SHM всегда нужен для router transport)
или transport=direct. Скрывается при transport=ipc (если такой добавится в будущем).

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/panels/__init__.py` -- создать, экспорт
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/panels/shm_config_panel.py` -- создать

**Steps:**
1. Создать `constructor_tab/panels/` директорию с `__init__.py`
2. Создать класс `ShmConfigPanel(QWidget)`:
   - QFormLayout с полями:
     - `shm_name: QLineEdit` -- имя SHM региона, placeholder: auto-generate из wire_key
     - `buffer_slots: QSpinBox` -- min=2, max=32, default=4
     - `owner_process: QComboBox` -- заполняется списком процессов (source + target wire)
     - `strategy: QComboBox` -- items: ["direct", "via_pm"], default="direct"
   - Метод `set_config(shm_config: dict, source_proc: str, target_proc: str)`:
     - Заполнить поля из dict (Dict at Boundary!)
     - Заполнить owner_process ComboBox значениями [source_proc, target_proc], выбрать текущий
     - blockSignals при программном заполнении
   - Метод `get_config() -> dict`:
     - Собрать dict из полей формы (возвращает dict, не SchemaBase)
   - Метод `clear()` -- сбросить форму
   - Signal `config_changed(dict)` -- эмитировать при изменении любого поля
3. Подключить сигналы виджетов (textChanged, valueChanged, currentIndexChanged) к слоту,
   который собирает get_config() и эмитирует config_changed
4. Стиль: QGroupBox "SharedMemory" как обёртка формы

**Acceptance criteria:**
- [ ] `ShmConfigPanel` создаётся без ошибок
- [ ] `set_config({"buffer_slots": 8, "strategy": "direct"}, "cam_0", "proc_0")` корректно заполняет поля
- [ ] `get_config()` возвращает dict с 4 ключами (shm_name, buffer_slots, owner_process, strategy)
- [ ] `config_changed` эмитируется при изменении пользователем, НЕ эмитируется при программном заполнении (blockSignals)
- [ ] Dict at Boundary: никаких SchemaBase / ShmWireConfig в API панели

**Out of scope:** Валидация уникальности shm_name (это задача WireEditorModel).
**Edge cases:** Пустой shm_name -- допустимо, auto-generate при Apply (Фаза 4).
**Dependencies:** Нет.

---

### Task 1.2 -- WireInspectorPanel

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать панель редактирования свойств wire-соединения.

**Context:** При клике на wire на канвасе правая панель показывает WireInspectorPanel:
source/target адреса (read-only), transport combo, описание, встроенный ShmConfigPanel.
Все изменения идут через `WireEditorModel.modify_wire()`.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/panels/wire_inspector.py` -- создать

**Steps:**
1. Создать класс `WireInspectorPanel(QWidget)`:
   - Layout (QVBoxLayout):
     - Заголовок: QLabel "Wire: {wire_key}" (bold)
     - QFormLayout:
       - `source: QLabel` -- read-only, полный адрес "process.plugin.port"
       - `target: QLabel` -- read-only, полный адрес
       - `transport: QComboBox` -- items: ["router", "direct"], default="router"
       - `description: QLineEdit` -- редактируемое описание
     - Разделитель (QFrame HLine)
     - `ShmConfigPanel` -- встроен, видимость зависит от transport
     - Stretch внизу
2. Метод `show_wire(wire_key: str, wire_data: dict)`:
   - Заполнить все поля из wire_data dict (Dict at Boundary!)
   - Парсить source/target для определения source_proc / target_proc
   - Передать shm_config в ShmConfigPanel.set_config()
   - Показать/скрыть ShmConfigPanel в зависимости от transport:
     - "router" или "direct" -> показать
     - (будущие варианты без SHM -> скрыть)
   - blockSignals при программном заполнении
3. Метод `clear()` -- скрыть форму, показать placeholder
4. Signal `wire_changed(str, dict)` -- (wire_key, changed_fields):
   - При изменении transport -> emit с {"transport": new_value}
   - При изменении description -> emit с {"description": new_value}
   - При ShmConfigPanel.config_changed -> emit с {"shm_config": new_config}
5. Подключить transport.currentTextChanged -> toggle ShmConfigPanel visibility + emit
6. Сохранить self._wire_key для формирования сигнала

**Acceptance criteria:**
- [ ] `show_wire("w1", {"source": "cam.cap.frame", "target": "proc.mask.in", "transport": "router", "description": "test", "shm_config": {"buffer_slots": 4}})` корректно заполняет все поля
- [ ] Изменение transport эмитирует wire_changed с правильным wire_key и changed_fields
- [ ] Изменение SHM-полей эмитирует wire_changed с ключом "shm_config" содержащим полный shm_config dict
- [ ] Source/target -- read-only (QLabel, не QLineEdit)
- [ ] ShmConfigPanel видим только при transport in ("router", "direct")

**Out of scope:** Редактирование source/target (wire перетягивают на канвасе, а не в панели).
**Edge cases:** wire_data без shm_config -> ShmConfigPanel показывает дефолты.
**Dependencies:** Task 1.1 (ShmConfigPanel).

---

### Task 1.3 -- ProcessPluginPanel

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать панель с переиспользованием PluginChainEditor + PluginCatalogWidget + PluginConfigPanel для конструктора.

**Context:** При клике на ноду процесса правая панель показывает ProcessPluginPanel:
заголовок с именем процесса, chain editor, каталог плагинов, конфиг-панель.
Это аналог PluginPage из ProcessDetailPanel, но адаптированный для конструктора.
Панель работает через SystemTopologyEditor (не через ProcessesSectionView напрямую).

Ключевое отличие от ProcessesTab: панель НЕ создаёт/удаляет процессы,
а только редактирует plugin chain выбранного процесса. Мутации идут
через `editor.update_item("processes", proc_key, new_proc_data)`.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/panels/process_plugin_panel.py` -- создать

**Steps:**
1. Создать класс `ProcessPluginPanel(QWidget)`:
   - Layout (QVBoxLayout):
     - Заголовок: QLabel "{process_name}" (bold, 14px) + приоритет badge
     - QSplitter (Vertical):
       - Верх: `PluginChainEditor` -- показывает текущую цепочку
       - Низ: QSplitter (Horizontal):
         - `PluginCatalogWidget` -- каталог для добавления
         - `PluginConfigPanel` -- конфиг выбранного плагина
2. Метод `show_process(proc_key: str, proc_data: dict)`:
   - Сохранить self._proc_key, self._proc_data
   - Обновить заголовок: proc_data["name"]
   - Вызвать chain_editor.set_chain(proc_key, proc_data.get("plugins", []))
   - Очистить config_panel
   - Показать панель (setVisible(True))
3. Метод `clear()`:
   - Скрыть панель, сбросить все дочерние виджеты
4. Подключить сигналы PluginChainEditor:
   - `plugin_selected(proc_key, idx)` -> config_panel.show_plugin(proc_key, idx, plugins[idx])
   - `plugin_removed(proc_key, idx)` -> удалить из proc_data["plugins"], emit process_changed
   - `plugin_moved(proc_key, from_idx, to_idx)` -> переместить в списке, emit process_changed
   - `add_plugin_requested(proc_key)` -> (handled by catalog -- показать каталог)
5. Подключить сигналы PluginCatalogWidget:
   - `plugin_activated(dict)` -> добавить в proc_data["plugins"], emit process_changed
6. Подключить сигналы PluginConfigPanel:
   - `config_changed(proc_key, idx, fields)` -> обновить plugins[idx], emit process_changed
7. Signal `process_changed(str, dict)` -- (proc_key, updated_proc_data):
   - Собирает обновлённый proc_data (с изменёнными plugins)
   - Потребитель (widget.py) вызовет editor.update_item("processes", proc_key, data)
8. Внутренний метод `_emit_process_changed()`:
   - Пересобрать chain_editor после каждой мутации
   - emit process_changed с текущим proc_data

**Acceptance criteria:**
- [ ] Переиспользует существующие PluginChainEditor, PluginCatalogWidget, PluginConfigPanel (import из processes_tab)
- [ ] `show_process("cam_0", {"name": "cam_0", "plugins": [...]})` показывает chain
- [ ] Добавление плагина через каталог -> process_changed эмитируется с обновлённым plugins
- [ ] Удаление/перемещение плагина -> process_changed эмитируется
- [ ] Изменение конфига плагина -> process_changed эмитируется
- [ ] Dict at Boundary: proc_data -- dict, не ProcessDefinition

**Out of scope:** Создание/удаление/переименование процессов (это в ProcessesTab).
Drag-and-drop плагинов между процессами.
**Edge cases:** Процесс без плагинов -> chain_editor показывает только кнопку "Добавить".
PluginRegistry недоступен -> каталог показывает "Нет плагинов" (graceful degradation из CatalogWidget).
**Dependencies:** Нет (использует существующие виджеты).

---

### Task 2.1 -- Edge->wire_key маппинг в адаптере

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Реализовать маппинг edge (NodeGraphQt connection) -> wire_key для сигнала wire_selected.

**Context:** В Фазе 2 адаптер имеет `_wire_map: dict[str, str]` (пустой) и
сигнал `wire_selected = Signal(str)` -- оба placeholder для Фазы 3.
Нужно: при создании wire (через GraphBuilder или drag-connect) заполнять _wire_map,
при клике на edge -- эмитировать wire_selected(wire_key).

Проблема: NodeGraphQt v0.5.2 НЕ имеет нативного edge_selection_changed сигнала.
Нужен workaround: при клике на пустую область канваса (selection cleared) проверять
через `graph.all_pipes()` какой pipe выделен, или использовать eventFilter на scene.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/canvas/plugin_graph_adapter.py` -- модифицировать
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/canvas/graph_builder.py` -- модифицировать

**Steps:**
1. В `GraphBuilder._create_wire_connections()`:
   - После успешного `out_port.connect_to(in_port)` получить созданный pipe
   - Варианты получения pipe:
     a. `out_port.connected_pipes()` -- найти pipe к in_port
     b. Или использовать маппинг (source_addr, target_addr) -> wire_key
   - Вернуть из `build()` дополнительно wire_map: `dict[tuple[str, str], str]`
     где key=(source_addr, target_addr), value=wire_key
2. В `PluginGraphAdapter.load_scene()`:
   - После build() получить wire_map и сохранить в `self._wire_map`
   - Реформатировать _wire_map: хранить как `dict[str, str]` (pipe_id -> wire_key)
     или как `dict[tuple[str, str], str]` (source_addr, target_addr -> wire_key)
3. В `PluginGraphAdapter._on_port_connected()`:
   - После успешного add_wire() -- добавить запись в _wire_map
4. В `PluginGraphAdapter._on_port_disconnected()`:
   - После remove_wire() -- удалить запись из _wire_map
5. Реализовать обнаружение выделения wire:
   - **Вариант A (рекомендуемый):** Polling через scene.selectedItems() внутри
     `_on_node_selection_changed` -- если selected=[] и deselected=[], проверить
     scene для QGraphicsPathItem (pipe) selection
   - **Вариант B:** eventFilter на QGraphicsScene, отлавливать mouseReleaseEvent,
     проверять scene.selectedItems() на наличие Pipe item
   - **Вариант C (самый простой):** В `_on_node_selection_changed`: если selected==[]
     and deselected==[], вызвать `_check_pipe_selection()` который через
     `graph._viewer.scene().selectedItems()` находит выделенный pipe и эмитирует wire_selected
6. Метод `_check_pipe_selection()`:
   - Получить scene items: `self._graph.viewer().scene().selectedItems()`
   - Для каждого item проверить: isinstance(item, Pipe) (или по type name)
   - Если pipe найден -- по его портам найти wire_key через _wire_map
   - emit self.wire_selected(wire_key)
7. Метод `wire_key_for_edge(source_addr: str, target_addr: str) -> str | None`:
   - Публичный lookup в _wire_map

**Acceptance criteria:**
- [ ] После load_scene() с wires -- _wire_map содержит корректные записи
- [ ] После drag-connect (add_wire) -- _wire_map обновляется
- [ ] После disconnect (remove_wire) -- запись удаляется из _wire_map
- [ ] wire_selected сигнал эмитируется при клике на pipe на канвасе
- [ ] Обратная совместимость: node_selected и selection_cleared работают как прежде

**Out of scope:** Multi-select wires. Undo/redo wire операций.
**Edge cases:** Клик на pipe, который не имеет wire_key (программный pipe без записи в модели) -- игнорировать.
NodeGraphQt viewer может быть None при fallback -- проверять.
**Dependencies:** Нет.

---

### Task 2.2 -- QStackedWidget правой панели + wiring сигналов

**Level:** Senior (Opus, normal)
**Assignee:** teamlead
**Goal:** Заменить placeholder правой панели на QStackedWidget с тремя страницами и подключить все сигналы адаптер -> панели -> модель.

**Context:** Это центральная задача интеграции. ConstructorTabWidget.widget.py
должен оркестрировать: адаптер эмитирует node_selected/wire_selected/selection_cleared,
widget переключает QStackedWidget на нужную страницу и передаёт данные в панель,
панели эмитируют *_changed сигналы, widget записывает изменения в topology editor.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/widget.py` -- существенная модификация

**Steps:**
1. Удалить метод `_create_right_panel_placeholder()` и `self._right_info_label`
2. Создать метод `_create_right_panel() -> QWidget`:
   - Контейнер с QVBoxLayout
   - Заголовок "Свойства" (QLabel, bold)
   - `self._stack = QStackedWidget()`:
     - Страница 0: `_PlaceholderPage` -- "Выберите процесс или wire..."
     - Страница 1: `ProcessPluginPanel`
     - Страница 2: `WireInspectorPanel`
   - Добавить stack в layout, установить min/max width
3. Заменить в `_init_ui()`:
   - `right_panel = self._create_right_panel()` вместо `_create_right_panel_placeholder()`
4. Обновить `_on_node_selected(process_key: str)`:
   - Получить proc_data: `self._editor._data["processes"].get(process_key)`
   - Если есть -> `self._process_panel.show_process(process_key, dict(proc_data))`
   - `self._stack.setCurrentIndex(1)`
5. Добавить обработчик `_on_wire_selected(wire_key: str)`:
   - Подключить к `self._adapter.wire_selected` (в `_init_canvas` или `_subscribe_to_topology`)
   - Получить wire_data: `self._editor._data["wires"].get(wire_key)`
   - Если есть -> `self._wire_panel.show_wire(wire_key, dict(wire_data))`
   - `self._stack.setCurrentIndex(2)`
6. Обновить `_on_selection_cleared()`:
   - `self._stack.setCurrentIndex(0)` (placeholder)
   - `self._process_panel.clear()`
   - `self._wire_panel.clear()`
7. Подключить сигналы панелей к модели:
   - `self._process_panel.process_changed.connect(self._on_process_panel_changed)`
   - `self._wire_panel.wire_changed.connect(self._on_wire_panel_changed)`
8. Метод `_on_process_panel_changed(proc_key: str, proc_data: dict)`:
   - `self._editor.update_item("processes", proc_key, proc_data)`
   - Это вызовет notify -> _on_processes_changed -> adapter.refresh_from_topology
   - Нужно guard чтобы refresh не сбросил выделение: запомнить proc_key,
     после refresh восстановить selection
9. Метод `_on_wire_panel_changed(wire_key: str, changed_fields: dict)`:
   - `self._wire_model.modify_wire(wire_key, changed_fields)`
   - Обновить статус
10. Обеспечить корректный lifecycle при fallback (NodeGraphQt недоступен):
    - Панели создаются всегда
    - Если adapter=None, node_selected/wire_selected не эмитируются, панели остаются на placeholder

**Acceptance criteria:**
- [ ] При клике на ноду -> правая панель показывает ProcessPluginPanel с плагинами процесса
- [ ] При клике на wire -> правая панель показывает WireInspectorPanel с данными wire
- [ ] При клике на пустое место -> placeholder
- [ ] Изменение плагина в ProcessPluginPanel -> editor.update_item вызывается -> канвас обновляется
- [ ] Изменение transport в WireInspectorPanel -> wire_model.modify_wire вызывается
- [ ] Без NodeGraphQt -> панели создаются, placeholder виден, ошибок нет
- [ ] Guard: редактирование плагинов не теряет текущий выбор ноды

**Out of scope:** Undo/redo. Анимация переключения страниц.
**Edge cases:** Быстрое переключение между нодами -- blockSignals при programmatic fill.
Процесс удалён в другой вкладке пока конструктор открыт -- stack -> placeholder.
**Dependencies:** Task 1.2, Task 1.3, Task 2.1.

---

### Task 2.3 -- Toolbar: Save/Load Blueprint

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Добавить кнопки Save/Load Blueprint в toolbar конструктора.

**Context:** blueprint_io.py уже реализует topology_to_blueprint, blueprint_to_topology,
save_blueprint, load_blueprint. Нужно добавить кнопки в toolbar и подключить к file dialog.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/widget.py` -- модификация _create_toolbar

**Steps:**
1. В `_create_toolbar()` после separator с "Проверить":
   - `toolbar.addSeparator()`
   - QPushButton "Сохранить Blueprint" + icon (или без)
     - clicked -> `self._on_save_blueprint()`
   - QPushButton "Загрузить Blueprint"
     - clicked -> `self._on_load_blueprint()`
2. Метод `_on_save_blueprint()`:
   - `from PySide6.QtWidgets import QFileDialog`
   - `path, _ = QFileDialog.getSaveFileName(self, "Сохранить Blueprint", "", "JSON (*.json)")`
   - Если path пуст -- return
   - Получить proc_data: `self._editor._data.get("processes", {})`
   - Получить wires_data: `self._editor._data.get("wires", {})`
   - `from .../blueprint_io import topology_to_blueprint, save_blueprint`
   - `bp = topology_to_blueprint(proc_data, name=Path(path).stem, wires_data=wires_data)`
   - `save_blueprint(bp, Path(path))`
   - Обновить статус: "Blueprint сохранён: {path}"
   - try/except -> показать ошибку в статусе
3. Метод `_on_load_blueprint()`:
   - `path, _ = QFileDialog.getOpenFileName(self, "Загрузить Blueprint", "", "JSON (*.json)")`
   - Если path пуст -- return
   - `from .../blueprint_io import load_blueprint, blueprint_to_topology`
   - `bp = load_blueprint(Path(path))`
   - `topo_data = blueprint_to_topology(bp)`
   - `self._editor.load(topo_data)` -- ВАЖНО: полная замена данных editor
     Это вызовет notify -> все вкладки обновятся
   - После load: adapter.load_scene() (вызовется через подписку _on_processes_changed)
   - Обновить статус: "Blueprint загружен: {bp.name}"
   - try/except -> показать ошибку в статусе

**Acceptance criteria:**
- [ ] Кнопка "Сохранить Blueprint" -> QFileDialog -> JSON файл с wires
- [ ] Кнопка "Загрузить Blueprint" -> QFileDialog -> editor.load -> канвас обновлён
- [ ] Round-trip: save -> load -> те же процессы и wires
- [ ] Ошибки (невалидный JSON, нет прав) -> сообщение в статусной строке, без crash

**Out of scope:** Recent files. Auto-save. Merge blueprint (только полная замена).
**Edge cases:** Файл без секции wires (старый формат) -- blueprint_to_topology уже обрабатывает (wires: {}).
**Dependencies:** Нет (blueprint_io уже готов).

---

### Task 3.1 -- Unit-тесты панелей и интеграции

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Покрыть тестами все новые панели и интеграцию с widget.py.

**Context:** Тесты Фазы 2 в `test_constructor_phase2.py` -- образец. Фаза 3 тесты
разделяются на: (a) чистые тесты без Qt, (b) Qt-тесты с qapp fixture.

**Files:**
- `multiprocess_prototype/tests/unit/test_constructor_phase3.py` -- создать

**Steps:**
1. Чистые тесты (без Qt):
   - Нет чисто-логических классов в Фазе 3 (все панели -- QWidget).
     Но можно тестировать wire_map логику адаптера через mock.
2. Qt-тесты ShmConfigPanel:
   - test_set_config_fills_fields -- set_config dict -> проверить виджеты
   - test_get_config_returns_dict -- заполнить -> get_config -> проверить ключи
   - test_config_changed_emitted_on_user_edit -- изменить spinbox -> сигнал
   - test_no_signal_on_programmatic_fill -- set_config -> сигнал НЕ эмитирован
3. Qt-тесты WireInspectorPanel:
   - test_show_wire_fills_all_fields
   - test_wire_changed_on_transport_change
   - test_wire_changed_on_description_change
   - test_shm_panel_hidden_on_clear
   - test_source_target_readonly
4. Qt-тесты ProcessPluginPanel:
   - test_show_process_shows_chain
   - test_process_changed_on_plugin_add (мок PluginCatalogWidget.plugin_activated)
   - test_process_changed_on_plugin_remove
   - test_clear_resets_all
5. Интеграционные Qt-тесты:
   - test_stack_switches_to_process_panel_on_node_select
   - test_stack_switches_to_wire_panel_on_wire_select
   - test_stack_returns_to_placeholder_on_clear
   - test_save_load_blueprint_roundtrip (через tmpdir)
6. Использовать тот же паттерн stub-modules из test_constructor_phase2.py
7. Использовать `_make_editor()` helper из test_constructor_phase2.py (скопировать или импортировать)

**Acceptance criteria:**
- [ ] `pytest multiprocess_prototype/tests/unit/test_constructor_phase3.py` -- все тесты зелёные
- [ ] Покрытие: ShmConfigPanel (4+), WireInspectorPanel (5+), ProcessPluginPanel (4+), integration (4+)
- [ ] Тесты не зависят от PluginRegistry (graceful degradation mock)
- [ ] Qt-тесты используют qapp fixture

**Out of scope:** E2E тесты запуска прототипа. Performance тесты.
**Edge cases:** Тесты с пустым topology. Тесты с отсутствующим NodeGraphQt (skip).
**Dependencies:** Task 1.1, 1.2, 1.3, 2.1, 2.2, 2.3.

---

## Риски и ограничения

1. **NodeGraphQt edge selection:** Библиотека не имеет нативного сигнала edge_selected.
   Mitigation: workaround через scene.selectedItems() -- проверить в Task 2.1.
   Если не работает -- fallback: двойной клик на ноде показывает список wires процесса
   как альтернативный способ выбора wire.

2. **Circular import при переиспользовании виджетов из processes_tab:**
   Виджеты PluginChainEditor / CatalogWidget / ConfigPanel импортируют из
   multiprocess_framework (PluginRegistry, PluginConfig). При импорте через
   processes_tab/__init__.py может возникнуть circular dependency.
   Mitigation: импортировать напрямую из конкретных модулей, не через __init__.py.
   Паттерн уже применён в test_constructor_phase2.py (stub modules).

3. **blockSignals discipline:** При программном заполнении панелей обязательно
   blockSignals / suppress -- иначе цикл: panel -> editor -> notify -> refresh -> panel.
   Mitigation: строго следовать паттерну из PluginConfigPanel (blockSignals try/finally).

4. **Guard при обновлении канваса:** Когда ProcessPluginPanel изменяет plugins ->
   editor.update_item -> notify -> adapter.refresh_from_topology -> rebuild canvas ->
   selection lost. Нужен guard: запомнить текущий proc_key, после rebuild восстановить.
