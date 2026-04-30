# Plan: Phase 6 — UI-интеграция plugin system в SystemTopology

**Date:** 2026-04-30
**Status:** DONE

## Обзор

Соединяем plugin system (Phase 1-5: PluginRegistry, Port, Wire, SystemBlueprint, PluginConfig) с SystemTopology UI (Phase 1-2: SystemTopologyEditor, ProcessesSectionView, ProcessesTab). Результат: пользователь видит каталог плагинов, собирает plugin chain в процессе, редактирует конфиг каждого плагина через авто-форму, валидирует цепочку портов, сохраняет/загружает blueprint как рецепт.

**Принцип:** SchemaBase насквозь. Плагины описываются как данные (dict at boundary), не как код. UI автогенерируется из FieldMeta. PluginRegistry используется только для чтения метаданных (порты, категории), а конфиг хранится в `ProcessDefinition.plugins: list[dict]`.

## Порядок выполнения

### Phase 6.1: Data Model — расширение схем и section view
- Task 6.1: Расширение ProcessDefinition плагинами [DONE — commit 5296174]
- Task 6.2: Plugin CRUD в ProcessesSectionView [DONE]
- Task 6.3: Валидация plugin chain в SystemTopologyEditor [DONE — commit 3955ab5]

### Phase 6.2: UI-виджеты — каталог, chain editor, config panel
- Task 6.4: PluginCatalogWidget — каталог плагинов [DONE — commit eccb0a9]
- Task 6.5: PluginChainEditor — редактор цепочки плагинов [DONE — commit f663ad0]
- Task 6.6: PluginConfigPanel — авто-форма конфига плагина [DONE — commit dd6a9db]

### Phase 6.3: Интеграция в ProcessesTab + Blueprint
- Task 6.7: Интеграция plugin UI в ProcessesTab [DONE — commit 46fad99]
- Task 6.8: Blueprint save/load в UI [DONE — commit 3d0e82a]
- Task 6.9: Интеграционные тесты Phase 6 [DONE — commit da64747]

---

## Детальные задачи

### Task 6.1 — Расширение ProcessDefinition плагинами

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Добавить поле `plugins: list[dict]` в `ProcessDefinition` и обновить `SystemTopology` для хранения plugin chain в конфигурации процесса.
**Context:** Сейчас `ProcessDefinition` содержит только name, class_path, priority, auto_start, sort_order. Для plugin system нужно хранить упорядоченный список плагинов (dict at boundary). Каждый dict — это `PluginConfig.model_dump()`. Формат совпадает с `ProcessConfig.plugins` из `blueprint.py`, что обеспечивает совместимость blueprint <-> topology.

**Files:**
- `multiprocess_prototype/registers/system_topology/schemas.py` — добавить поле plugins в ProcessDefinition
- `multiprocess_prototype/registers/system_topology/schemas.py` — обновить SECTION_KEYS если нужно
- `multiprocess_prototype/registers/system_topology/tests/` — тесты на новое поле

**Steps:**
1. В `ProcessDefinition` добавить поле:
   ```python
   plugins: Annotated[
       list[dict[str, Any]],
       FieldMeta("Плагины", info="Упорядоченный список конфигов плагинов (PluginConfig.model_dump())."),
   ] = Field(default_factory=list)
   ```
2. Добавить import `Any` из typing и `Field` из pydantic (Field уже импортирован).
3. Добавить хелпер-метод `ProcessDefinition.plugin_names() -> list[str]` — извлекает `plugin_name` из каждого dict в plugins.
4. Обновить `SystemTopology.validate_refs()` — добавить базовую проверку: каждый dict в plugins должен содержать `plugin_class` и `plugin_name`.
5. Написать тесты: создание ProcessDefinition с plugins, сериализация/десериализация (model_dump/model_validate), validate_refs.

**Acceptance criteria:**
- [ ] `ProcessDefinition(plugins=[{"plugin_class": "...", "plugin_name": "capture", "category": "source"}]).model_dump()` содержит ключ `plugins`
- [ ] `ProcessDefinition.model_validate({"name": "cam", "plugins": [...]})` парсит plugins
- [ ] `SystemTopology.validate_refs()` ловит plugin dict без `plugin_class`
- [ ] Пустой plugins=[] — валидно (процесс без плагинов = legacy)
- [ ] Тесты проходят: `pytest multiprocess_prototype/registers/system_topology/tests/ -v`

**Out of scope:** UI-виджеты, section view, конвертация ProcessConfig <-> ProcessDefinition (Task 6.8).
**Edge cases:** Пустой plugins (legacy процессы без плагинов должны работать как раньше). Дубли plugin_name внутри одного процесса — предупреждение в validate_refs.
**Dependencies:** Нет.

---

### Task 6.2 — Plugin CRUD в ProcessesSectionView

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Добавить методы управления плагинами процесса в ProcessesSectionView: add_plugin, remove_plugin, move_plugin, update_plugin_config.
**Context:** ProcessesSectionView управляет `editor._data["processes"]` и `["workers"]`. Теперь каждый процесс в `processes[key]` содержит `plugins: list[dict]`. Section view должен предоставить CRUD для плагинов аналогично CRUD для воркеров. Каждая мутация уведомляет подписчиков SECTION_PROCESSES.

**Files:**
- `multiprocess_prototype/frontend/models/sections/processes_section.py` — добавить plugin CRUD методы
- `multiprocess_prototype/frontend/models/sections/tests/` — тесты

**Steps:**
1. Добавить метод `plugins_for_process(proc_key: str) -> list[dict]` — возвращает список плагинов процесса (ссылка на данные editor, не копия).
2. Добавить метод `add_plugin(proc_key: str, plugin_dict: dict) -> int` — добавить плагин в конец цепочки. Возвращает индекс. Валидация: проверить что `plugin_class` и `plugin_name` заданы, проверить что `plugin_name` уникален в процессе. Вызвать `_editor._notify_section(SECTION_PROCESSES)`.
3. Добавить метод `remove_plugin(proc_key: str, index: int) -> dict` — удалить плагин по индексу. Возвращает удалённый dict. Raise IndexError если за границами.
4. Добавить метод `move_plugin(proc_key: str, from_idx: int, to_idx: int) -> None` — переместить плагин в цепочке (drag-and-drop). Используется `list.insert` + `list.pop`.
5. Добавить метод `update_plugin_config(proc_key: str, index: int, fields: dict) -> None` — обновить поля конфига плагина по индексу. `plugins[index].update(fields)`.
6. Обновить `full_snapshot()` — plugins уже входит в `processes` dict, дополнительных действий не нужно, но убедиться.
7. Обновить `validate()` — делегировать в `_editor.validate(SECTION_PROCESSES)`, которая уже вызывает `_validate_processes()`. Убедиться что новая валидация плагинов из Task 6.1 подхватывается.

**Acceptance criteria:**
- [ ] `section.add_plugin("cam", {"plugin_class": "...", "plugin_name": "capture", "category": "source"})` возвращает индекс 0
- [ ] `section.plugins_for_process("cam")` возвращает `[{"plugin_class": "...", ...}]`
- [ ] `section.remove_plugin("cam", 0)` удаляет плагин, возвращает его dict
- [ ] `section.move_plugin("cam", 0, 1)` перемещает, порядок меняется
- [ ] `section.update_plugin_config("cam", 0, {"h_min": 30})` обновляет поля
- [ ] Каждая мутация вызывает `_notify_section` → подписчики уведомлены
- [ ] `add_plugin` с дублирующимся `plugin_name` → ValueError

**Out of scope:** UI-виджеты. Валидация совместимости портов (Task 6.3).
**Edge cases:** add_plugin в несуществующий процесс → KeyError. remove_plugin с невалидным индексом → IndexError. move_plugin src==dst → no-op.
**Dependencies:** Task 6.1 (поле plugins в ProcessDefinition).

---

### Task 6.3 — Валидация plugin chain в SystemTopologyEditor

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** Добавить валидацию совместимости портов plugin chain в SystemTopologyEditor._validate_processes(), используя PluginRegistry и validate_chain().
**Context:** PluginRegistry содержит метаинформацию о портах (inputs/outputs каждого плагина). `validate_chain()` из `port.py` проверяет последовательную совместимость. Нужно интегрировать эту валидацию в поток SystemTopologyEditor. Важное решение: PluginRegistry живёт в runtime (импорт модулей с плагинами нужен для заполнения реестра). В design-time (UI без запущенного backend) реестр может быть пуст. Нужна graceful degradation.

**Files:**
- `multiprocess_prototype/frontend/models/system_topology_editor.py` — расширить `_validate_processes()`
- `multiprocess_prototype/registers/system_topology/schemas.py` — опционально: хелпер `ProcessDefinition.validate_plugins()`

**Steps:**
1. Решить архитектурный вопрос: как доставить PluginRegistry в SystemTopologyEditor. Варианты: (a) импорт глобального PluginRegistry напрямую, (b) передать registry в конструктор. Рекомендация: (a) — PluginRegistry глобальный singleton, import safe. Но обернуть в try-except: если registry пуст, пропустить валидацию портов.
2. В `_validate_processes()` добавить для каждого процесса с непустым `plugins`:
   - Для каждого plugin dict найти `PluginEntry` в `PluginRegistry.get(plugin_name)`.
   - Если плагин не найден в реестре — warning (не error), т.к. registry может быть не заполнен в design-time.
   - Если все плагины найдены — вызвать `validate_chain()` с их портами.
   - Ошибки `validate_chain()` добавить в результат.
3. Добавить проверку уникальности `plugin_name` внутри одного процесса (дубли → error).
4. Добавить cross-process wire валидацию: если в `SystemTopology` появятся wires (будущее расширение) — заготовить точку расширения.

**Acceptance criteria:**
- [ ] Процесс с цепочкой `[capture → color_mask]` валидируется без ошибок (порты совместимы)
- [ ] Процесс с цепочкой `[color_mask → capture]` даёт ошибку (вход capture не принимает mask)
- [ ] Пустой PluginRegistry → валидация портов пропускается (graceful degradation), остальные проверки работают
- [ ] Дублирование plugin_name в одном процессе → ошибка
- [ ] Тесты с mock PluginRegistry

**Out of scope:** Wire-валидация между процессами (будущая фаза). UI-отображение ошибок.
**Edge cases:** Процесс без plugins (legacy) — валидация пропускается. Плагин без портов (inputs=[], outputs=[]) — допустим.
**Dependencies:** Task 6.1.

---

### Task 6.4 — PluginCatalogWidget — каталог плагинов

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать Qt-виджет для отображения и фильтрации каталога плагинов из PluginRegistry. Поддержка drag-to-add и фильтрации по категории/совместимости с портом.
**Context:** PluginRegistry предоставляет `list()`, `filter(category)`, `compatible_with(port)`. Каталог показывается в левой части UI (sidebar или dropdown) при редактировании plugin chain процесса. Виджет должен быть самодостаточным (не зависеть от ProcessesTab напрямую).

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/plugin_catalog_widget.py` — создать новый файл
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/tests/test_plugin_catalog.py` — тесты

**Steps:**
1. Создать класс `PluginCatalogWidget(QWidget)` с:
   - `QComboBox` для фильтра по категории: "Все" / "source" / "processing" / "output"
   - `QListWidget` для отображения плагинов (имя, категория, описание в tooltip)
   - Каждый item хранит `PluginEntry` в `Qt.ItemDataRole.UserRole`
2. Метод `refresh(category_filter: str = "")` — заполняет список из `PluginRegistry.list()` или `PluginRegistry.filter(category)`.
3. Метод `filter_compatible(port: Port)` — показать только плагины, совместимые с данным портом (используя `PluginRegistry.compatible_with(port)`).
4. Сигнал `plugin_selected(str)` — эмитится при двойном клике или нажатии Enter. Передаёт plugin name.
5. Сигнал `plugin_activated(dict)` — эмитится при нажатии кнопки "Добавить" или drag. Передаёт dict с `plugin_class`, `plugin_name`, `category` (минимальный PluginConfig).
6. Поддержка `QDrag` для drag-and-drop (MIME type: `application/x-plugin-name`). Опционально — можно отложить drag в Phase 7.
7. Отображение входных/выходных портов в tooltip: `In: frame (image/bgr), Out: mask (image/gray)`.

**Acceptance criteria:**
- [ ] Виджет показывает все плагины из PluginRegistry
- [ ] Фильтр по категории "processing" показывает только processing-плагины
- [ ] Двойной клик эмитит `plugin_selected` с именем плагина
- [ ] Tooltip содержит описание и порты
- [ ] Пустой PluginRegistry → виджет показывает "Нет доступных плагинов"
- [ ] pytest-qt тест с mock PluginRegistry

**Out of scope:** Drag-and-drop (отложить). Поиск по имени (можно в Phase 7). Иконки.
**Edge cases:** PluginRegistry пуст. Категория не содержит плагинов. Плагин без описания.
**Dependencies:** Нет (читает только из PluginRegistry).

---

### Task 6.5 — PluginChainEditor — редактор цепочки плагинов

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Создать Qt-виджет для визуализации и редактирования упорядоченной цепочки плагинов процесса, с отображением портов и индикацией совместимости.
**Context:** Это центральный виджет Phase 6. Показывает plugin chain текущего процесса как горизонтальный/вертикальный список карточек. Каждая карточка: имя плагина, категория, входные/выходные порты. Между карточками — индикатор совместимости (зелёный/красный). Операции: добавить (из каталога), удалить, переместить (drag или кнопки up/down).

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/plugin_chain_editor.py` — создать новый файл
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/plugin_card_widget.py` — карточка одного плагина (вспомогательный виджет)
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/tests/test_plugin_chain.py` — тесты

**Steps:**
1. Создать `PluginCardWidget(QFrame)` — карточка одного плагина:
   - Заголовок: plugin_name (bold) + category badge (цветной QLabel)
   - Порты: слева inputs (имя:dtype), справа outputs (имя:dtype)
   - Кнопки: удалить (X), переместить вверх/вниз (стрелки)
   - Выделение: клик → selected state (border highlight)
   - Данные: хранит plugin dict + index + port info (из PluginRegistry)
   - Сигналы: `selected(int)`, `remove_requested(int)`, `move_requested(int, int)` — (from, direction: -1/+1)
2. Создать `PluginChainEditor(QWidget)` — контейнер:
   - `QVBoxLayout` с `PluginCardWidget`ами в порядке цепочки
   - Между карточками — `QLabel` со стрелкой и цветовой индикацией совместимости (зелёная "--->" если порты совместимы, красная "-->X" если нет)
   - Кнопка "+ Добавить плагин" в конце списка
   - `QScrollArea` wrapper для скроллинга длинных цепочек
3. Метод `set_chain(proc_key: str, plugins: list[dict])` — отрисовать цепочку. Для каждого plugin dict обращается к `PluginRegistry.get(plugin_name)` для получения портов. Если плагин не найден в реестре — показать карточку с предупреждением.
4. Метод `_update_compatibility_indicators()` — пересчитать индикаторы между карточками используя `are_ports_compatible`.
5. Сигналы наружу: `plugin_selected(str, int)` — (proc_key, plugin_index), `plugin_removed(str, int)`, `plugin_moved(str, int, int)`, `add_plugin_requested(str)` — (proc_key).
6. Метод `selected_plugin_index() -> int | None` — текущий выбранный индекс (для PluginConfigPanel).

**Acceptance criteria:**
- [ ] Цепочка из 3 плагинов отображается как 3 карточки с 2 индикаторами совместимости
- [ ] Клик по карточке эмитит `plugin_selected`
- [ ] Кнопка "Удалить" эмитит `plugin_removed`
- [ ] Кнопки "Вверх/Вниз" эмитят `plugin_moved`
- [ ] Несовместимые порты → красный индикатор
- [ ] Пустая цепочка → только кнопка "+ Добавить плагин"
- [ ] pytest-qt тест с mock данными

**Out of scope:** Drag-and-drop перестановка (кнопки up/down достаточно). Wire-визуализация между процессами. Горизонтальный node-graph.
**Edge cases:** Один плагин — нет индикаторов. Плагин без портов — карточка без секции портов. Плагин не в реестре — карточка с предупреждением (жёлтый фон).
**Dependencies:** Task 6.1, Task 6.2 (для данных).

---

### Task 6.6 — PluginConfigPanel — авто-форма конфига плагина

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Создать панель для редактирования конфига выбранного плагина, переиспользуя ParamsForm + SchemaInspectorPanel.
**Context:** Каждый плагин имеет config (наследник PluginConfig). Когда пользователь выделяет карточку плагина в PluginChainEditor, PluginConfigPanel строит авто-форму из FieldMeta полей конфига. Используем существующий `ParamsForm` (`widgets/base/editor/params_form.py`), который уже умеет строить формы из SchemaBase. Проблема: нужно найти config class по plugin_class path (import + inspect).

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/plugin_config_panel.py` — создать новый файл
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/tests/test_plugin_config_panel.py` — тесты

**Steps:**
1. Создать `PluginConfigPanel(QWidget)`:
   - Содержит `SchemaInspectorPanel` внутри.
   - Метод `show_plugin(proc_key: str, plugin_index: int, plugin_dict: dict)` — найти config class, показать форму.
   - Метод `clear()` — сбросить панель.
2. Логика поиска config class по `plugin_class` path:
   - Из `plugin_dict["plugin_class"]` (напр. `"...capture.plugin.CapturePlugin"`) получить config module path: заменить `.plugin.XXXPlugin` на `.config`.
   - Импортировать модуль, найти подкласс `PluginConfig`.
   - Fallback: если config class не найден — использовать базовый `PluginConfig` (показать только plugin_class, plugin_name, category).
   - Кэширование: `dict[str, type]` — один раз найденный config class кэшируется.
3. Сигнал `config_changed(str, int, dict)` — (proc_key, plugin_index, new_config_dict). Подключается к `SchemaInspectorPanel.field_changed`.
4. Фильтровать поля формы: скрыть поля `plugin_class`, `plugin_name`, `category` — они не редактируются пользователем (системные). Показать только plugin-specific поля.

**Acceptance criteria:**
- [ ] Для CapturePluginConfig показывает поля: camera_id, device_id, fps, resolution_width, resolution_height, ring_buffer_size
- [ ] Для ColorMaskPluginConfig показывает поля: h_min, h_max, s_min, s_max, v_min, v_max, camera_id, resolution_*
- [ ] Изменение поля эмитит `config_changed` с обновлённым dict
- [ ] Неизвестный plugin_class → базовый PluginConfig (3 поля), без crash
- [ ] pytest-qt тест

**Out of scope:** Inline-валидация полей (подсветка ошибок в форме). Undo/redo.
**Edge cases:** plugin_class path не существует (модуль удалён) → fallback. Config class без дополнительных полей → форма пуста ("Нет параметров"). Пустой plugin_dict → clear().
**Dependencies:** Task 6.1. Существующий `ParamsForm`, `SchemaInspectorPanel`.

---

### Task 6.7 — Интеграция plugin UI в ProcessesTab

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Встроить PluginCatalogWidget, PluginChainEditor и PluginConfigPanel в ProcessesTabWidget с правильным wiring между компонентами.
**Context:** ProcessesTabWidget сейчас имеет layout: `QSplitter(Vertical) = [toolbar + tree, detail_panel]`. Нужно расширить detail panel: когда выбран процесс, под ProcessInfoForm появляется PluginChainEditor + PluginConfigPanel. Когда выбран воркер — оставить как было. PluginCatalogWidget появляется как dialog или sidebar при нажатии "+ Добавить плагин".

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/widget.py` — расширить
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/process_detail_panel.py` — добавить страницу с plugin chain
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/__init__.py` — обновить exports

**Steps:**
1. Расширить `ProcessDetailPanel` — добавить страницу 3: `_PluginProcessPage(QWidget)` — QSplitter(Horizontal):
   - Слева (stretch 2): `PluginChainEditor`
   - Справа (stretch 1): `PluginConfigPanel`
   - Эта страница показывается вместо ProcessInfoForm когда процесс имеет plugins.
   - Метод `show_process_with_plugins(proc_key: str, proc_data: dict, plugins: list[dict])`.
2. В `ProcessesTabWidget._show_process_detail()`:
   - Проверить `plugins = ed_data.get("plugins", [])`.
   - Если plugins не пусты → `self._detail.show_process_with_plugins(proc_key, merged, plugins)`.
   - Если пусты → `self._detail.show_process(merged)` (legacy).
3. Wiring сигналов:
   - `PluginChainEditor.plugin_selected` → `PluginConfigPanel.show_plugin`
   - `PluginChainEditor.plugin_removed` → `ProcessesSectionView.remove_plugin` → refresh chain
   - `PluginChainEditor.plugin_moved` → `ProcessesSectionView.move_plugin` → refresh chain
   - `PluginChainEditor.add_plugin_requested` → открыть PluginCatalogWidget dialog
   - `PluginConfigPanel.config_changed` → `ProcessesSectionView.update_plugin_config` → refresh chain
   - `PluginCatalogWidget.plugin_activated` → `ProcessesSectionView.add_plugin` → refresh chain
4. Добавить кнопку "Плагины" в toolbar ProcessesTabWidget (после "+ Воркер") — переключает detail panel на plugin view для текущего процесса.
5. Обновить `_on_editor_changed()` — при изменении editor data, если показана plugin page, обновить chain.

**Acceptance criteria:**
- [ ] Выбор процесса с plugins → detail panel показывает chain editor + config panel
- [ ] Клик по карточке плагина → config panel справа показывает форму
- [ ] Удаление плагина через chain editor → обновление через section view → refresh tree
- [ ] Добавление плагина через каталог → append в section view → refresh chain
- [ ] Перемещение плагина вверх/вниз → обновление порядка в section view → refresh chain + индикаторы совместимости
- [ ] Изменение config поля → update через section view → dirty → Apply работает
- [ ] Процесс без plugins → legacy detail panel (ProcessInfoForm)

**Out of scope:** Горизонтальный node-graph. Визуализация wires между процессами. Undo/redo для plugin операций.
**Edge cases:** Переключение между процессом с plugins и без. Переключение с процесса на воркер и обратно. Удаление последнего плагина → переключение на legacy view.
**Dependencies:** Task 6.2, Task 6.4, Task 6.5, Task 6.6.

---

### Task 6.8 — Blueprint save/load в UI

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Добавить возможность сохранять текущую конфигурацию процессов с плагинами как SystemBlueprint (рецепт) и загружать blueprint в editor.
**Context:** SystemBlueprint из `blueprint.py` описывает процессы + plugins + wires. Нужна конвертация SystemTopology (section processes) <-> SystemBlueprint. Сохранение: toolbar кнопка "Сохранить рецепт" → диалог имени → JSON файл. Загрузка: кнопка "Загрузить рецепт" → file dialog → заполнение editor.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/blueprint_io.py` — конвертеры и file I/O
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/widget.py` — кнопки в toolbar
- `multiprocess_prototype/backend/plugins/blueprints/` — директория для сохранённых рецептов (JSON)

**Steps:**
1. Создать `blueprint_io.py`:
   - Функция `topology_to_blueprint(proc_data: dict[str, dict]) -> SystemBlueprint` — конвертирует processes dict из topology в SystemBlueprint. Каждый процесс → ProcessConfig. Wires пока пустые (auto-wiring внутри процессов покрывает).
   - Функция `blueprint_to_topology(bp: SystemBlueprint) -> dict[str, dict]` — обратная конвертация: ProcessConfig → ProcessDefinition dict (name, class_path, priority, plugins).
   - Функция `save_blueprint(bp: SystemBlueprint, path: Path) -> None` — `bp.model_dump()` → JSON файл.
   - Функция `load_blueprint(path: Path) -> SystemBlueprint` — JSON → `SystemBlueprint.model_validate(data)`.
2. В `ProcessesTabWidget`:
   - Добавить кнопку "Сохранить рецепт" в toolbar.
   - Handler: собрать processes из section view → `topology_to_blueprint()` → dialog имени → `save_blueprint()`.
   - Добавить кнопку "Загрузить рецепт" в toolbar.
   - Handler: file dialog → `load_blueprint()` → `blueprint_to_topology()` → `section.load_from_snapshot({"processes": ..., "workers": ...})`.
3. Дефолтная директория для рецептов: `multiprocess_prototype/backend/plugins/blueprints/`.

**Acceptance criteria:**
- [ ] "Сохранить рецепт" → JSON файл с полной структурой SystemBlueprint
- [ ] "Загрузить рецепт" → processes + plugins заполняются в editor
- [ ] Round-trip: save → load → идентичные данные
- [ ] Загрузка blueprint из `demo_color_mask.py` → корректное отображение цепочек
- [ ] Тесты на конвертеры: `topology_to_blueprint` / `blueprint_to_topology`

**Out of scope:** Wire editing в UI (wires создаются вручную в blueprint файлах или автоматически). Version migration. Cloud storage.
**Edge cases:** Загрузка blueprint с плагинами, не зарегистрированными в PluginRegistry. Загрузка повреждённого JSON. Сохранение пустой конфигурации.
**Dependencies:** Task 6.1, Task 6.2, Task 6.7.

---

### Task 6.9 — Интеграционные тесты Phase 6

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Интеграционные тесты полного flow: создание процесса → добавление плагинов → редактирование config → валидация chain → save/load blueprint.
**Context:** Каждая Task 6.X имеет unit-тесты. Здесь проверяем сквозной сценарий без Qt (data model) и с Qt (виджеты, pytest-qt).

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/tests/test_phase6_integration.py` — создать

**Steps:**
1. Data model тесты (без Qt):
   - Создать SystemTopologyEditor → add_process → add_plugin (capture) → add_plugin (color_mask) → validate → 0 ошибок.
   - Тот же flow но color_mask → capture → validate → ошибки несовместимости портов.
   - topology_to_blueprint → blueprint_to_topology → round-trip check.
2. UI тесты (pytest-qt):
   - Создать ProcessesTabWidget с mock command_handler и topology_editor.
   - Добавить процесс, открыть plugin chain editor, добавить плагин из каталога.
   - Проверить что plugin chain отображается.
   - Изменить config поле → verify dirty state.

**Acceptance criteria:**
- [ ] Все тесты проходят: `pytest multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/tests/test_phase6_integration.py -v`
- [ ] Покрытие: happy path + основные ошибки (невалидная цепочка, пустой registry)
- [ ] Тесты не требуют запуска backend (все зависимости mock)

**Out of scope:** Stress-тесты. Performance-тесты с большим количеством плагинов.
**Edge cases:** Mock PluginRegistry с 0 плагинами. Процесс без plugins (legacy). Плагин с пустым config.
**Dependencies:** Task 6.1-6.8.

---

## Риски и ограничения

1. **PluginRegistry в design-time**: Registry заполняется при импорте модулей плагинов. В GUI-режиме без запуска backend плагины могут не быть зарегистрированы. Решение: при старте UI выполнять discovery-импорт (`importlib` по known paths). Или показывать каталог на основе файловой системы. Graceful degradation обязательна.

2. **Dict at Boundary**: Все plugin configs пересекают границу процессов как dict. UI работает с dict, не с PluginConfig напрямую. Конвертация dict → PluginConfig нужна только для нахождения config class (поиск полей FieldMeta).

3. **Порядок фаз**: Data model (6.1-6.3) MUST быть завершён до UI виджетов (6.4-6.6). Интеграция (6.7) зависит от всех виджетов. Blueprint I/O (6.8) может идти параллельно с 6.7.

4. **Размер Phase**: 9 задач. При необходимости можно разбить на два этапа: 6.1-6.6 (MVP: каталог + chain editor) и 6.7-6.9 (интеграция + blueprint).

5. **Qt widget patterns**: Соблюдать паттерны из Memory — blockSignals при programmatic fill, setFlags для рекурсии, EditTriggers.
