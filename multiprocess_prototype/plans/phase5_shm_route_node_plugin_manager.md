# План: Фаза 5 -- ShmRouteNode + PluginManagerTab

**Дата:** 2026-05-04
**Статус:** DONE

## Обзор

Фаза 5 добавляет два блока функциональности:
1. **ShmRouteNode** -- специальная нода на канвасе конструктора для визуализации fan-out маршрутизации (1 вход, N выходов). При подключении одного выхода к нескольким входам автоматически вставляется route node.
2. **PluginManagerTab** -- новая вкладка главного окна: каталог всех зарегистрированных плагинов (PluginRegistry), lifecycle control (enable/disable/reload), runtime-метрики (PluginMetrics), конфигурация дефолтов, фильтрация и поиск.

Фазы 1-4 завершены (73 теста). Канвас работает с PluginProcessNode, wire-соединения синхронизированы с SystemTopologyEditor, runtime-интеграция через TopologyBridge + ProcessManager.

**Оценка объёма:** ~12 новых файлов, ~1500-1800 строк нового кода, ~5 модифицированных файлов.

## Порядок выполнения

### Часть A: ShmRouteNode (канвас)
- Task 1.1: ShmRouteNode -- кастомная нода NodeGraphQt [DONE]
- Task 1.2: Auto-insert route node при fan-out [DONE] (зависит от 1.1)
- Task 1.3: Тесты ShmRouteNode [DONE] (зависит от 1.1, 1.2)

### Часть B: PluginManagerTab (новая вкладка)
- Task 2.1: PluginManagerModel -- модель данных для вкладки [DONE]
- Task 2.2: PluginCatalogTable -- таблица каталога плагинов [DONE] (зависит от 2.1)
- Task 2.3: PluginDetailPanel -- правая панель с метриками и конфигурацией [DONE] (зависит от 2.1)
- Task 2.4: PluginManagerTabWidget -- сборка вкладки [DONE] (зависит от 2.2, 2.3)
- Task 2.5: Регистрация вкладки в TabFactory + TabsConfig [DONE] (зависит от 2.4)
- Task 2.6: Тесты PluginManagerTab [DONE] (зависит от 2.1-2.5)

## Риски и ограничения

1. **NodeGraphQt multi_output=True** -- уже используется для выходных портов PluginProcessNode. Но при fan-out из одного порта ко многим, визуально получается N pipes из одного порта. ShmRouteNode делает это нагляднее, но не обязателен для функциональности.
2. **PluginRegistry -- in-process singleton** -- PluginRegistry живёт в основном процессе (GUI). Для метрик runtime-плагинов (которые в дочерних процессах) нужен IPC-запрос. MVP: метрики только для зарегистрированных плагинов, runtime stats -- через IPC polling (аналогично WireDataBridge).
3. **Enable/disable плагинов** -- PluginState (IDLE/READY/RUNNING/PAUSED/STOPPED) управляется GenericProcess в дочерних процессах. GUI disable = IPC-команда pause/shutdown в целевой процесс. MVP: пометка "disabled" в конфигурации, применение при следующем Apply/Restart.
4. **Hot-reload** -- PluginManager.reload() перезагружает Python-модули через importlib.reload. Работает для discovery, но НЕ обновляет уже запущенные экземпляры в дочерних процессах. MVP: reload обновляет каталог, для применения нужен restart процесса.

---

## Детальные задачи

### Task 1.1 -- ShmRouteNode: кастомная нода fan-out маршрутизации

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать ShmRouteNode -- специальную ноду NodeGraphQt для визуализации fan-out (1 вход → N выходов) на канвасе конструктора.

**Контекст:** Сейчас fan-out реализуется подключением нескольких wires к одному выходному порту (multi_output=True). ShmRouteNode -- промежуточная нода, визуализирующая точку ветвления данных. Она не соответствует реальному процессу, а представляет RouterManager маршрутизацию. На канвасе выглядит как маленькая нода с 1 входом и N динамических выходов.

Визуально:
```
+==================+
| Route: frame_shm |
|------------------|
| IN: o frame      |
| OUT: o out_1     |
|      o out_2     |
|      o out_3     |
+==================+
```

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/canvas/shm_route_node.py` -- создать
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/canvas/__init__.py` -- добавить экспорт

**Steps:**
1. Создать класс `RouteNodeItem(NodeItem)`:
   - Компактная визуализация: меньший размер чем ProcessNodeItem
   - Body: текст "Route" + имя SHM-канала
   - Цвет фона: отличается от ProcessNodeItem (например #3a3a5a -- синеватый)
   - Min height: 60px (вместо 80px у ProcessNodeItem)

2. Создать класс `ShmRouteNode(BaseNode)`:
   - `__identifier__ = "constructor.nodes"`
   - `NODE_NAME = "ShmRouteNode"`
   - Использует RouteNodeItem как qgraphics_item
   - Properties:
     - `route_key: str` -- уникальный ключ route node
     - `shm_name: str` -- имя SHM-канала (отображается в body)
   - Один фиксированный входной порт: `add_input("in", multi_input=False)`
   - Метод `add_fan_out_port(name: str)` -- добавить выходной порт:
     - Генерирует имя `out_{N}` если name не задано
     - Вызывает `self.add_output(name, multi_output=False)` (каждый выход -- к одному потребителю)
     - Обновляет высоту ноды
   - Метод `remove_fan_out_port(name: str)` -- удалить выходной порт (если потребитель отключился)
   - Метод `set_route_data(route_key: str, shm_name: str, output_count: int)`:
     - Установить данные route node
     - Создать output_count выходных портов

3. Зарегистрировать `ShmRouteNode` в `ConstructorTabWidget._init_canvas()`:
   - `self._graph.register_node(ShmRouteNode)` -- после регистрации PluginProcessNode

4. Определить константу `ROUTE_NODE_TYPE = "constructor.nodes.ShmRouteNode"`

**Acceptance criteria:**
- [ ] ShmRouteNode визуально отличается от PluginProcessNode (размер, цвет)
- [ ] 1 входной порт + N динамических выходных портов
- [ ] Регистрируется в NodeGraphQt и создаётся через `graph.create_node(ROUTE_NODE_TYPE)`
- [ ] set_route_data() корректно создаёт N выходных портов
- [ ] Нода отображает имя SHM-канала

**Out of scope:** Интеграция с WireEditorModel (Task 1.2). Runtime-статусы route node. Правая панель для route node (будущее).

**Edge cases:**
- 0 выходных портов -- корректное отображение (только вход)
- Имя порта конфликтует с уже существующим -- добавить суффикс

---

### Task 1.2 -- Auto-insert route node при fan-out wires

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** Автоматически вставлять ShmRouteNode когда один выходной порт подключается к нескольким входным (fan-out > 1).

**Контекст:** Когда пользователь создаёт второй wire от одного выходного порта, адаптер должен: (1) удалить прямой wire, (2) вставить ShmRouteNode, (3) подключить исходный порт к входу route node, (4) подключить оба потребителя к выходам route node. Это визуальное улучшение -- route node делает fan-out явным. В модели данных (WireEditorModel) wire-ключи сохраняются с маппингом через route node.

Алгоритм:
```
До: A.out --wire1--> B.in
После добавления wire2 от A.out к C.in:
    A.out --> [Route] --> B.in  (wire1, route)
                    +--> C.in  (wire2, route)
```

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/canvas/plugin_graph_adapter.py` -- модифицировать _on_port_connected(), добавить логику auto-insert
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/canvas/graph_builder.py` -- модифицировать _create_wire_connections() для поддержки route nodes при загрузке
- `multiprocess_prototype/frontend/widgets/tabs_setting/constructor_tab/canvas/shm_route_node.py` -- использовать (из Task 1.1)

**Steps:**

1. В PluginGraphAdapter добавить dict `_route_nodes: dict[str, ShmRouteNode]`:
   - Ключ: "source_addr" (адрес выходного порта, от которого идёт fan-out)
   - Значение: ShmRouteNode на канвасе

2. Добавить вспомогательный метод `_count_outgoing_wires(source_addr: str) -> int`:
   - Подсчёт wires из одного source_addr по данным WireEditorModel

3. Модифицировать `_on_port_connected()`:
   - После успешного add_wire проверить: `_count_outgoing_wires(source_addr) >= 2`
   - Если fan-out >= 2 и route node ещё нет:
     a. Получить первый wire из source_addr (уже существующий)
     b. Удалить визуальные pipes прямых соединений (block_signals)
     c. Создать ShmRouteNode в позиции между source и targets
     d. Подключить source port → route.input
     e. Для каждого target: route.out_N → target port
     f. Сохранить в _route_nodes[source_addr]
     g. Обновить _wire_key_to_pipe для всех затронутых wires
   - Если fan-out >= 2 и route node уже есть:
     a. Добавить новый выходной порт в route node
     b. Подключить route.out_new → target port

4. Модифицировать `_on_port_disconnected()`:
   - Если при удалении wire fan-out снижается до 1:
     a. Удалить route node и все его pipes
     b. Восстановить прямое соединение source → единственный оставшийся target
     c. Удалить из _route_nodes
   - Если fan-out снижается до 0:
     a. Удалить route node
     b. Удалить из _route_nodes

5. Модифицировать GraphBuilder._create_wire_connections():
   - После создания всех wires: выявить fan-out (groupBy source_addr, count > 1)
   - Для каждой группы с fan-out > 1: создать ShmRouteNode, перестроить pipes
   - Вернуть дополнительно route_nodes_map в результате build()

6. Обновить `GraphBuilder.build()` возвращаемый тип:
   - `tuple[dict, dict, dict]` -- (node_map, addr_to_wire_key, route_nodes_map)
   - Обновить вызовы в PluginGraphAdapter.load_scene()

7. Позиционирование route node:
   - Среднее между source node и средним target nodes (по X)
   - Среднее targets (по Y)
   - Snap to grid через auto_layout._snap()

**Acceptance criteria:**
- [ ] При втором wire от одного порта автоматически появляется route node
- [ ] При удалении wire до fan-out=1 route node удаляется
- [ ] При загрузке Blueprint с fan-out wires route nodes создаются автоматически
- [ ] Wire model НЕ изменяется: route node -- чисто визуальный элемент
- [ ] Позиция route node -- между source и targets
- [ ] Выделение route node НЕ эмитит node_selected (это не процесс)

**Out of scope:** Правая панель для route node. Ручное создание route node. Persist позиции route node в Blueprint (автогенерация при загрузке).

**Edge cases:**
- Fan-out = 3+ -> route node имеет 3+ выходных порта
- Удаление target-процесса -> fan-out уменьшается, возможно удаление route node
- Source процесс удалён -> route node удаляется вместе со всеми wires
- Два разных выходных порта одного процесса с fan-out -> два разных route nodes

**Dependencies:** Task 1.1

---

### Task 1.3 -- Тесты ShmRouteNode + auto-insert

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Покрыть тестами ShmRouteNode (unit) и auto-insert логику (integration с mock NodeGraphQt).

**Файлы:**
- `multiprocess_prototype/tests/unit/test_constructor_phase5_route_node.py` -- создать

**Steps:**
1. **ShmRouteNode unit-тесты** (без NodeGraphQt, mock BaseNode):
   - `test_route_node_creation` -- создание с route_key и shm_name
   - `test_route_node_add_fan_out_port` -- добавление выходных портов
   - `test_route_node_remove_fan_out_port` -- удаление выходных портов
   - `test_route_node_set_route_data` -- N портов создаются

2. **Auto-insert unit-тесты** (mock adapter, mock graph):
   - `test_fan_out_creates_route_node` -- второй wire от одного порта -> route node
   - `test_fan_out_removes_route_on_disconnect` -- fan-out 2→1 -> route node удалён
   - `test_fan_out_triple` -- fan-out 3 -> route node с 3 выходами
   - `test_builder_creates_route_nodes` -- GraphBuilder с fan-out wires

3. Использовать паттерн stub-модулей из test_constructor_phase3.py (circular import workaround)

4. Запуск: `python -m pytest multiprocess_prototype/tests/unit/test_constructor_phase5_route_node.py -v`

**Acceptance criteria:**
- [ ] Все тесты зелёные
- [ ] Покрытие: создание route node, add/remove портов, auto-insert, auto-remove
- [ ] Тесты не требуют GUI

**Out of scope:** E2E тесты с реальным NodeGraphQt (требует QApplication).

**Dependencies:** Tasks 1.1, 1.2

---

### Task 2.1 -- PluginManagerModel: модель данных вкладки

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать модель данных PluginManagerModel, агрегирующую данные PluginRegistry, PluginManager и runtime-метрики для отображения во вкладке.

**Контекст:** Модель отделена от виджетов (паттерн MVC как в CrossProcessModel, WireEditorModel). Работает с Dict at Boundary -- виджеты получают list[dict]. Для runtime-метрик использует IPC polling (аналогично WireDataBridge) через command_handler.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/plugin_manager_tab/models/__init__.py` -- создать
- `multiprocess_prototype/frontend/widgets/tabs_setting/plugin_manager_tab/models/plugin_manager_model.py` -- создать

**Steps:**

1. Определить структуру данных плагина для UI:
   ```python
   # Каждый плагин в таблице:
   PluginRowData = TypedDict("PluginRowData", {
       "name": str,              # уникальное имя
       "category": str,          # source / processing / output
       "description": str,       # описание
       "class_path": str,        # dotted path к классу
       "inputs": int,            # количество входных портов
       "outputs": int,           # количество выходных портов
       "enabled": bool,          # включён / отключён (конфигурационный флаг)
       "instances": int,         # сколько экземпляров в запущенных процессах
       "metrics": dict | None,   # PluginMetrics.snapshot() или None
   })
   ```

2. Создать класс `PluginManagerModel(QObject)`:
   - `__init__(self, plugin_manager: PluginManager | None, command_handler: Any | None, parent=None)`
   - Сохранить ссылки на PluginManager и command_handler
   - Dict `_disabled_plugins: set[str]` -- множество disabled plugin names (persist в конфигурации)
   - Dict `_default_configs: dict[str, dict]` -- дефолтные конфигурации по имени плагина
   - Signal `plugins_updated = Signal()` -- данные обновлены

3. Метод `get_all_plugins() -> list[dict]`:
   - Обойти PluginRegistry.list()
   - Для каждого PluginEntry: собрать PluginRowData
   - enabled = name not in _disabled_plugins
   - instances: подсчитать вхождения в текущих процессах SystemTopologyEditor (если доступен)
   - metrics: из кэша runtime-метрик (если polling активен)

4. Метод `filter_plugins(category: str | None, search: str) -> list[dict]`:
   - Фильтрация по category (None = все)
   - Поиск по name + description (case-insensitive substring)

5. Метод `set_enabled(plugin_name: str, enabled: bool)`:
   - Добавить/удалить из _disabled_plugins
   - Emit plugins_updated

6. Метод `reload_plugins() -> PluginDiscoveryResult`:
   - Вызвать PluginManager.reload()
   - Emit plugins_updated
   - Вернуть результат

7. Метод `get_default_config(plugin_name: str) -> dict`:
   - Вернуть _default_configs.get(name, {})

8. Метод `set_default_config(plugin_name: str, config: dict)`:
   - Сохранить в _default_configs

9. Runtime-метрики (IPC polling):
   - QTimer с интервалом 5000ms (конфигурируемый)
   - Команда `plugins.metrics` в ProcessManager -- запрашивает PluginMetrics.snapshot() от всех процессов
   - Кэш `_metrics_cache: dict[str, dict]` -- plugin_name → aggregated metrics
   - Метод `start_metrics_polling()` / `stop_metrics_polling()`

**Acceptance criteria:**
- [ ] get_all_plugins() возвращает list[dict] со всеми полями PluginRowData
- [ ] filter_plugins() корректно фильтрует по категории и поиску
- [ ] set_enabled/reload_plugins эмитят plugins_updated
- [ ] Dict at Boundary: все методы возвращают dict/list[dict]
- [ ] Без PluginManager -- graceful degradation (пустой каталог)

**Out of scope:** IPC-команда plugins.metrics в ProcessManager (отдельная задача, MVP без runtime метрик). Persist disabled_plugins в файл конфигурации.

**Edge cases:**
- PluginRegistry пуст (ни одного плагина) -- корректная работа
- PluginManager is None (тестовый режим) -- reload_plugins возвращает пустой результат
- Два плагина с одинаковым name -- PluginRegistry это предотвращает (ValueError)

---

### Task 2.2 -- PluginCatalogTable: таблица каталога плагинов

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Создать виджет таблицы всех зарегистрированных плагинов с фильтрацией, поиском и toggle enabled/disabled.

**Контекст:** Таблица -- главный элемент вкладки PluginManagerTab. QTableWidget с колонками: checkbox (enabled), имя, категория, описание, порты (in/out), экземпляры. Над таблицей -- toolbar с поиском (QLineEdit) и фильтром по категории (QComboBox). Паттерн из ProcessesSectionView (таблица процессов в ProcessesTab).

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/plugin_manager_tab/__init__.py` -- создать
- `multiprocess_prototype/frontend/widgets/tabs_setting/plugin_manager_tab/schemas.py` -- создать
- `multiprocess_prototype/frontend/widgets/tabs_setting/plugin_manager_tab/plugin_catalog_table.py` -- создать

**Steps:**

1. Создать `schemas.py`:
   ```python
   def default_tab_item() -> TabItemConfig:
       return TabItemConfig(id="plugin_manager", widget="plugin_manager", title="Плагины")
   ```

2. Создать класс `PluginCatalogTable(QWidget)`:
   - Layout:
     ```
     ┌───────────────────────────────────────────────┐
     │ [Поиск: ___________] [Категория: v] [Обновить] │
     ├───────────────────────────────────────────────┤
     │ [ ] | Имя        | Категория  | Описание | I/O │
     │ [x] | capture    | source     | Захват.. | 0/2 │
     │ [x] | color_mask | processing | Цветовая | 1/1 │
     │ [ ] | renderer   | output     | Отрисовка| 2/0 │
     └───────────────────────────────────────────────┘
     ```
   - QVBoxLayout: toolbar (QHBoxLayout) + QTableWidget
   - Toolbar:
     - QLineEdit с placeholder "Поиск по имени..." + textChanged → _on_search
     - QComboBox с items ["Все", "source", "processing", "output"] + currentTextChanged → _on_filter
     - QPushButton "Обновить" → reload_plugins()
   - QTableWidget:
     - Колонки: Enabled (checkbox), Имя, Категория, Описание, Порты (I/O), Экземпляры
     - setSelectionBehavior(QAbstractItemView.SelectRows)
     - setSelectionMode(QAbstractItemView.SingleSelection)
     - horizontalHeader().setStretchLastSection(True)
   - Signal `plugin_selected = Signal(str)` -- эмит при клике на строку (plugin name)
   - Signal `plugin_enabled_changed = Signal(str, bool)` -- эмит при toggle checkbox

3. Метод `set_data(plugins: list[dict])`:
   - Очистить таблицу
   - Заполнить строки из list[dict] (Dict at Boundary!)
   - Для каждого плагина: checkbox в колонке 0, данные в остальных колонках
   - blockSignals при заполнении (паттерн из ProcessesTab)

4. Метод `refresh(model: PluginManagerModel)`:
   - Вызвать model.filter_plugins(self._current_category, self._search_text)
   - Вызвать set_data(result)

5. `_on_search(text: str)` -- обновить _search_text, вызвать refresh
6. `_on_filter(category: str)` -- обновить _current_category (None если "Все"), вызвать refresh
7. `_on_cell_clicked(row, col)` -- если col != 0 (не checkbox): emit plugin_selected
8. `_on_checkbox_changed(row)` -- emit plugin_enabled_changed

**Acceptance criteria:**
- [ ] Таблица отображает все плагины из PluginRegistry
- [ ] Фильтрация по категории работает (source/processing/output/все)
- [ ] Поиск по имени + описанию (case-insensitive)
- [ ] Checkbox toggle эмитит plugin_enabled_changed
- [ ] Выделение строки эмитит plugin_selected
- [ ] blockSignals при set_data (нет ложных эмитов)

**Out of scope:** Drag-and-drop из таблицы на канвас. Контекстное меню. Сортировка по колонкам (будущее).

**Edge cases:**
- Пустой каталог -- показать placeholder "Плагины не найдены"
- Очень длинное описание -- ellipsis в ячейке
- Категория не из стандартных (source/processing/output) -- отображать как есть

**Dependencies:** Task 2.1

---

### Task 2.3 -- PluginDetailPanel: правая панель с метриками и конфигурацией

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать правую панель, показывающую детали выбранного плагина: информация, порты, метрики, дефолтная конфигурация.

**Контекст:** Правая панель появляется при выборе плагина в таблице. Аналог правой панели ConstructorTabWidget (QStackedWidget). Содержит несколько секций: информация о плагине, список портов (inputs/outputs с типами), runtime-метрики (если доступны), редактор дефолтной конфигурации.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/plugin_manager_tab/plugin_detail_panel.py` -- создать

**Steps:**

1. Создать класс `PluginDetailPanel(QWidget)`:
   - Layout:
     ```
     ┌────────────────────────┐
     │ Имя: color_mask        │
     │ Категория: processing  │
     │ Путь: ...ColorMaskPlug │
     │ Статус: enabled        │
     ├────────────────────────┤
     │ Порты:                 │
     │  IN:  frame (image/bgr)│
     │  OUT: mask (image/gray)│
     ├────────────────────────┤
     │ Метрики:               │
     │  uptime: 42.3s         │
     │  configure: 1.2ms      │
     │  total_errors: 0       │
     ├────────────────────────┤
     │ Дефолтная конфигурация:│
     │  [QTextEdit / JSON]    │
     │  [Сохранить дефолты]   │
     └────────────────────────┘
     ```

2. QVBoxLayout с QScrollArea (содержимое может быть длинным):
   - **Секция "Информация"** -- QFormLayout:
     - name: QLabel (bold)
     - category: QLabel с цветовой меткой (badge)
     - class_path: QLabel (monospace, word-wrap)
     - description: QLabel (word-wrap)
     - enabled/disabled: QLabel с цветом (зелёный/красный)
   - **Секция "Порты"** -- QGroupBox с QVBoxLayout:
     - Для каждого input: QLabel "IN: {name} ({dtype}, {shape})"
     - Для каждого output: QLabel "OUT: {name} ({dtype}, {shape})"
     - Пустая секция если портов нет
   - **Секция "Метрики"** -- QGroupBox с QFormLayout:
     - uptime_s: QLabel
     - lifecycle (configure_ms, start_ms, shutdown_ms): QLabel
     - commands: QLabel (count + avg_ms для каждой)
     - total_errors: QLabel (красный если > 0)
     - Скрывается если метрики None
   - **Секция "Дефолтная конфигурация"** -- QGroupBox:
     - QTextEdit (JSON формат, monospace)
     - QPushButton "Сохранить дефолты"
   - Signal `default_config_changed = Signal(str, dict)` -- (plugin_name, config)

3. Метод `show_plugin(plugin_data: dict, port_details: dict | None, metrics: dict | None)`:
   - plugin_data: dict из PluginManagerModel.get_all_plugins() (одна запись)
   - port_details: {"inputs": [...], "outputs": [...]} с dtype/shape из PluginEntry
   - metrics: PluginMetrics.snapshot() dict или None
   - Заполнить все секции

4. Метод `update_metrics(metrics: dict | None)`:
   - Обновить только секцию метрик (при polling)

5. Метод `clear()`:
   - Сбросить все поля

6. Получение данных портов из PluginRegistry:
   - PluginEntry.inputs / .outputs -- list[Port]
   - Port имеет атрибуты: name, dtype, shape
   - Сериализовать в dict для Dict at Boundary

**Acceptance criteria:**
- [ ] Панель показывает информацию о выбранном плагине
- [ ] Секция портов отображает inputs/outputs с типами
- [ ] Секция метрик обновляется при наличии данных
- [ ] Секция конфигурации позволяет редактировать JSON
- [ ] Кнопка "Сохранить дефолты" эмитит default_config_changed
- [ ] clear() корректно сбрасывает все поля

**Out of scope:** Валидация JSON конфигурации (будущее). Inline-редактирование портов. Графики метрик (Фаза 6).

**Edge cases:**
- Плагин без портов -- секция портов показывает "Нет портов"
- Плагин без метрик (не запущен) -- секция метрик скрыта
- Невалидный JSON в конфигурации -- подсветка ошибки в QTextEdit, кнопка disabled

**Dependencies:** Task 2.1

---

### Task 2.4 -- PluginManagerTabWidget: сборка вкладки

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Создать PluginManagerTabWidget -- корневой виджет вкладки, объединяющий таблицу каталога и правую панель.

**Контекст:** Аналог ConstructorTabWidget по структуре: toolbar + splitter (таблица + правая панель). Toolbar: кнопка "Обновить плагины" (reload), статусная строка.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/plugin_manager_tab/widget.py` -- создать

**Steps:**

1. Создать класс `PluginManagerTabWidget(QWidget)`:
   - `__init__(self, plugin_manager: PluginManager | None = None, command_handler: Any = None, parent=None)`
   - Создать PluginManagerModel (из Task 2.1)
   - Инициализировать UI

2. Layout:
   ```
   ┌──────────────────────────────────────────────────────────┐
   │ Toolbar: [Обновить плагины] [Статус: 12 плагинов]       │
   ├───────────────────────────────┬──────────────────────────┤
   │                               │                          │
   │   PluginCatalogTable          │   PluginDetailPanel      │
   │   (таблица + фильтры)        │   (детали + метрики)     │
   │                               │                          │
   └───────────────────────────────┴──────────────────────────┘
   ```

3. `_init_ui()`:
   - QVBoxLayout: toolbar + splitter
   - Toolbar (QToolBar):
     - QPushButton "Обновить плагины" → _on_reload
     - QLabel статус (count плагинов, результат reload)
   - QSplitter (Horizontal): 70% таблица, 30% правая панель
   - PluginCatalogTable (из Task 2.2) в левой части
   - PluginDetailPanel (из Task 2.3) в правой части

4. Wiring сигналов:
   - PluginCatalogTable.plugin_selected → _on_plugin_selected
   - PluginCatalogTable.plugin_enabled_changed → _on_plugin_enabled_changed
   - PluginDetailPanel.default_config_changed → _on_default_config_changed
   - PluginManagerModel.plugins_updated → _on_model_updated

5. `_on_plugin_selected(plugin_name: str)`:
   - Получить данные плагина из PluginManagerModel
   - Получить port details из PluginRegistry
   - Получить метрики из кэша модели
   - Вызвать PluginDetailPanel.show_plugin(...)

6. `_on_plugin_enabled_changed(plugin_name: str, enabled: bool)`:
   - Вызвать PluginManagerModel.set_enabled(plugin_name, enabled)

7. `_on_default_config_changed(plugin_name: str, config: dict)`:
   - Вызвать PluginManagerModel.set_default_config(plugin_name, config)

8. `_on_reload()`:
   - result = PluginManagerModel.reload_plugins()
   - Обновить статус в toolbar
   - Обновить таблицу

9. `_on_model_updated()`:
   - PluginCatalogTable.refresh(model)

**Acceptance criteria:**
- [ ] Вкладка показывает таблицу плагинов при открытии
- [ ] Клик на плагин -> правая панель заполняется
- [ ] Кнопка "Обновить" -> reload плагинов + обновление таблицы
- [ ] Enable/disable через checkbox -> обновление модели
- [ ] Splitter: корректные пропорции, ресайз работает

**Out of scope:** Runtime метрики polling (MVP без IPC). Persist состояния enabled/disabled.

**Dependencies:** Tasks 2.1, 2.2, 2.3

---

### Task 2.5 -- Регистрация PluginManagerTab в TabFactory + TabsConfig

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Зарегистрировать PluginManagerTabWidget как новую вкладку в TabFactory и добавить в TabsConfig.

**Контекст:** TabFactory (tab_factory.py) -- единая фабрика вкладок, создаёт виджет по widget_key. TabsConfig (tabs_config.py) -- список вкладок с порядком. Нужно добавить widget_key="plugin_manager" и TabItemConfig в дефолтный список вкладок.

**Файлы:**
- `multiprocess_prototype/frontend/windows/main_window/tab_factory.py` -- добавить case "plugin_manager"
- `multiprocess_prototype/frontend/widgets/tabs_setting/tabs_config.py` -- добавить вкладку в _default_tabs()
- `multiprocess_prototype/frontend/widgets/tabs_setting/plugin_manager_tab/schemas.py` -- уже создано в Task 2.2

**Steps:**

1. В `tab_factory.py` добавить блок после `if widget_key == "processes":`:
   ```python
   if widget_key == "plugin_manager":
       from multiprocess_prototype.frontend.widgets.tabs_setting.plugin_manager_tab.widget import (
           PluginManagerTabWidget,
       )
       return PluginManagerTabWidget(
           plugin_manager=ctx.extras.get("plugin_manager"),
           command_handler=ctx.command_handler,
       )
   ```
   **ВАЖНО:** Lazy import (внутри if) -- паттерн из всех остальных вкладок.

2. В `tabs_config.py` обновить `_default_tabs()`:
   - Добавить `_plugin_manager()` -- TabItemConfig(id="plugin_manager", widget="plugin_manager", title="Плагины")
   - Вставить после _processes() и перед _sources(): `[_set(), _rec(), _processes(), _plugin_manager(), _sources(), _graph(), _disp()]`

3. Убедиться что PluginManager доступен через `ctx.extras["plugin_manager"]`:
   - Проверить `multiprocess_prototype/frontend/launcher.py` или аналог -- где extras заполняются
   - Если PluginManager не передаётся в extras -- добавить (или widget создаст fallback с None)

**Acceptance criteria:**
- [ ] Вкладка "Плагины" появляется в главном окне
- [ ] tab_factory создаёт PluginManagerTabWidget по ключу "plugin_manager"
- [ ] Порядок вкладок: Настройки, Рецепты, Процессы, Плагины, Источники, Pipeline, Дисплей
- [ ] Без PluginManager в extras -- вкладка создаётся с пустым каталогом (graceful)

**Out of scope:** Условная видимость вкладки (скрывать если плагинов нет). Сортировка вкладок.

**Edge cases:**
- FrontendAppContext без extras["plugin_manager"] -- PluginManagerTabWidget(plugin_manager=None) работает корректно

**Dependencies:** Task 2.4

---

### Task 2.6 -- Тесты PluginManagerTab

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Покрыть тестами все компоненты Фазы 5 Part B: PluginManagerModel, PluginCatalogTable, PluginDetailPanel, PluginManagerTabWidget.

**Файлы:**
- `multiprocess_prototype/tests/unit/test_constructor_phase5_plugin_manager.py` -- создать

**Steps:**

1. **PluginManagerModel** (без Qt):
   - `test_get_all_plugins_from_registry` -- mock PluginRegistry с 3 плагинами → list[dict] с корректными полями
   - `test_filter_by_category` -- фильтр source → только source плагины
   - `test_filter_by_search` -- поиск "mask" → color_mask
   - `test_set_enabled_disable` -- disable плагина → enabled=False в get_all_plugins
   - `test_reload_plugins` -- mock PluginManager.reload → plugins_updated signal emitted

2. **PluginCatalogTable** (pytest-qt):
   - `test_table_set_data` -- set_data с list[dict] → корректное количество строк
   - `test_table_filter_category` -- фильтр processing → только processing строки
   - `test_table_search` -- ввод текста → фильтрация строк
   - `test_table_checkbox_toggle` -- toggle checkbox → plugin_enabled_changed signal
   - `test_table_row_select` -- клик на строку → plugin_selected signal

3. **PluginDetailPanel** (pytest-qt):
   - `test_show_plugin_info` -- show_plugin → заполнены name, category, class_path
   - `test_show_plugin_ports` -- порты отображены (IN/OUT)
   - `test_show_plugin_metrics` -- метрики отображены
   - `test_clear` -- clear → пустые поля
   - `test_default_config_save` -- ввод JSON + "Сохранить" → default_config_changed signal

4. **PluginManagerTabWidget** (pytest-qt):
   - `test_widget_init` -- создание без PluginManager → работает
   - `test_reload_button` -- клик "Обновить" → reload вызван на модели

5. Использовать паттерн stub-модулей из test_constructor_phase3.py

6. Запуск: `python -m pytest multiprocess_prototype/tests/unit/test_constructor_phase5_plugin_manager.py -v`

**Acceptance criteria:**
- [ ] Все тесты зелёные
- [ ] Покрытие: model (CRUD, filter, search), table (data, filter, signals), detail (show, metrics, config)
- [ ] Mock PluginRegistry -- тесты не зависят от реальных плагинов

**Out of scope:** E2E тесты с реальным PluginManager.discover(). Тесты IPC-метрик.

**Dependencies:** Tasks 2.1-2.5

---

## Структура новых файлов

```
multiprocess_prototype/frontend/widgets/tabs_setting/
    constructor_tab/canvas/
        shm_route_node.py                    # ShmRouteNode + RouteNodeItem (Task 1.1)
    plugin_manager_tab/                      # НОВАЯ вкладка
        __init__.py                          # экспорты
        schemas.py                           # TabItemConfig (Task 2.2)
        widget.py                            # PluginManagerTabWidget (Task 2.4)
        plugin_catalog_table.py              # PluginCatalogTable (Task 2.2)
        plugin_detail_panel.py               # PluginDetailPanel (Task 2.3)
        models/
            __init__.py
            plugin_manager_model.py          # PluginManagerModel (Task 2.1)

multiprocess_prototype/tests/unit/
    test_constructor_phase5_route_node.py    # Тесты ShmRouteNode (Task 1.3)
    test_constructor_phase5_plugin_manager.py # Тесты PluginManagerTab (Task 2.6)
```

## Модифицируемые файлы

| Файл | Задача | Что меняется |
|------|--------|-------------|
| `constructor_tab/canvas/__init__.py` | 1.1 | Экспорт ShmRouteNode |
| `constructor_tab/canvas/plugin_graph_adapter.py` | 1.2 | Auto-insert route node, _route_nodes dict |
| `constructor_tab/canvas/graph_builder.py` | 1.2 | Fan-out detection, route nodes при build |
| `constructor_tab/widget.py` | 1.1 | register_node(ShmRouteNode) |
| `windows/main_window/tab_factory.py` | 2.5 | Case "plugin_manager" |
| `widgets/tabs_setting/tabs_config.py` | 2.5 | _default_tabs += plugin_manager |
