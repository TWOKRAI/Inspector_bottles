# Plan: Рефакторинг вкладок Процессы/Источники -- Phase 1

**Дата:** 2026-04-29
**Статус:** DRAFT

## Обзор

Извлечь общие компоненты из SourcesTab/ProcessesTab в `widgets/base/editor/`,
переработать ProcessesTab из read-only монитора в полноценный редактор+монитор,
поменять порядок вкладок.

## Текущее состояние

- `BaseEditorTreeView` (`widgets/base/editor/base_editor_tree.py`) -- уже есть: QTreeView + QStandardItemModel, signal suppression, save/restore selection, abstract `_populate()`
- `BaseEditorModel` (`widgets/base/editor/base_editor_model.py`) -- уже есть: dict-based, dirty tracking, add/remove/modify, callbacks
- `TopologyEditorModel` -- наследник BaseEditorModel с двухслойной структурой cameras+regions
- `ProcessMonitorModel` -- НЕ наследник BaseEditorModel, отдельная реализация без dirty tracking
- `ProcessTreeView` -- наследник BaseEditorTreeView (read-only), уже переопределяет `_save_selection`/`_restore_selection`/`_save_expand_state`/`_restore_expand_state`/`refresh`/`_populate`
- `TopologyTreeView` -- наследник BaseEditorTreeView с domain-specific логикой (cam/reg params, toggle bool)

## Архитектурные решения

1. **НЕ создаём `EntityTreeView`/`EntityToolbar`/`EntityEditorModel` как новые классы.** `BaseEditorTreeView` и `BaseEditorModel` УЖЕ являются этими базами. Задача -- вынести expand state в базу и добавить toolbar widget.
2. **ProcessEditorModel** -- новый наследник `BaseEditorModel` для CRUD конфигурации процессов/воркеров (аналог TopologyEditorModel для процессов). Хранит "желаемое" состояние, которое apply записывает в ProcessManager.
3. **ProcessMonitorModel** -- остаётся отдельным (не наследник BaseEditorModel), т.к. это read-only push-модель без dirty tracking.
4. **ProcessesTabWidget** -- будет содержать ОБА: ProcessEditorModel (конфигурация) и ProcessMonitorModel (runtime статусы). Дерево отображает merge обеих моделей.

## Порядок выполнения

### Phase 1.1: Улучшение базовых компонентов
- Task 1.1: Перенести expand state в BaseEditorTreeView [PENDING]
- Task 1.2: Создать BaseEditorToolbar [PENDING]

### Phase 1.2: ProcessEditorModel
- Task 2.1: Создать ProcessEditorModel [PENDING]
- Task 2.2: Создать ProcessRegisterBridge [PENDING]

### Phase 1.3: Переработка ProcessesTab UI
- Task 3.1: Переработать ProcessTreeView (editor+monitor) [PENDING]
- Task 3.2: Расширить CreateProcessDialog (процессы + воркеры) [PENDING]
- Task 3.3: Создать ProcessDetailPanel (QStackedWidget) [PENDING]
- Task 3.4: Собрать новый ProcessesTabWidget [PENDING]

### Phase 1.4: Порядок вкладок
- Task 4.1: Обновить tabs_config.py [PENDING]

---

### Task 1.1 -- Перенести expand state в BaseEditorTreeView

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Вынести логику сохранения/восстановления expand state из ProcessTreeView в BaseEditorTreeView, чтобы все деревья-наследники получили её бесплатно.

**Контекст:** Сейчас `ProcessTreeView` переопределяет `refresh()` целиком только чтобы добавить save/restore expand state. `TopologyTreeView` не имеет этой логики (вызывает `expandAll()`). Если expand state будет в базе -- `ProcessTreeView.refresh()` не нужно переопределять.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/base/editor/base_editor_tree.py` -- изменить
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/process_tree_view.py` -- упростить (удалить `refresh`, `_save_expand_state`, `_restore_expand_state`)
- `multiprocess_prototype/frontend/widgets/tabs_setting/sources_tab/topology_tree_view.py` -- проверить совместимость

**Шаги:**
1. В `BaseEditorTreeView` добавить атрибут `_expand_all_on_first: bool = True` (конструктор, kwarg).
2. В `BaseEditorTreeView` добавить методы `_save_expand_state() -> dict[str, bool]` и `_restore_expand_state(state)`. Реализация: обход root children, сохранение `{item.data(Qt.UserRole): is_expanded}` рекурсивно. Это обобщённая версия -- не привязана к ROLE_PROC.
3. В `BaseEditorTreeView.refresh()` вставить вызовы expand state: сохранить ДО очистки, восстановить ПОСЛЕ populate. При первом вызове (пустой state) -- `expandAll()` если `_expand_all_on_first`.
4. В `ProcessTreeView` удалить переопределённые `refresh()`, `_save_expand_state()`, `_restore_expand_state()`.
5. В `TopologyTreeView._populate()` убрать `self._tree.expandAll()` в конце (база теперь сделает это).

**Acceptance criteria:**
- [ ] `BaseEditorTreeView.refresh()` сохраняет/восстанавливает expand state
- [ ] `ProcessTreeView` НЕ переопределяет `refresh()`
- [ ] `TopologyTreeView._populate()` не вызывает `expandAll()`
- [ ] Оба дерева корректно сохраняют раскрытие узлов при refresh

**Out of scope:** Не менять логику selection persistence. Не трогать _populate() кроме удаления expandAll().

**Edge cases:** Пустое дерево (0 процессов/камер) -- expandAll на пустом дереве безопасен. Узел был раскрыт, но удалён из данных -- просто не найдётся при restore (ОК).

---

### Task 1.2 -- Создать BaseEditorToolbar

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Создать переиспользуемый виджет toolbar для editor-вкладок с настраиваемыми кнопками и кнопкой Apply с dirty-индикацией.

**Контекст:** Сейчас toolbar в SourcesTabWidget собирается inline в `_build_toolbar()` как QHBoxLayout с хардкод-кнопками. Аналогичный toolbar понадобится в ProcessesTab. Вместо копирования -- выносим в базу.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/base/editor/base_editor_toolbar.py` -- создать
- `multiprocess_prototype/frontend/widgets/base/editor/__init__.py` -- добавить экспорт

**Шаги:**
1. Создать класс `BaseEditorToolbar(QWidget)`.
2. Конструктор принимает `buttons: list[tuple[str, str, Callable]]` -- список `(label, tooltip, slot)` для кнопок действий (левая часть). И опциональный `show_apply: bool = True`.
3. Layout: `QHBoxLayout` -- кнопки слева, stretch, кнопка "Применить" справа.
4. Метод `set_dirty(dirty: bool)` -- включает/выключает кнопку "Применить" и меняет стиль (accent оранжевый при dirty).
5. Signal `apply_clicked` -- emit при нажатии "Применить".
6. Метод `get_button(label: str) -> QPushButton | None` -- для доступа к конкретным кнопкам (напр. для enable/disable).
7. Добавить `BaseEditorToolbar` в `__init__.py` экспорт.

**Acceptance criteria:**
- [ ] `BaseEditorToolbar` создаётся с произвольным набором кнопок
- [ ] `set_dirty(True)` включает Apply и ставит оранжевый стиль
- [ ] `set_dirty(False)` выключает Apply и убирает стиль
- [ ] Signal `apply_clicked` эмитится при нажатии Apply

**Out of scope:** НЕ переключать SourcesTab на этот toolbar в этой фазе (можно в Phase 2). Не добавлять undo/redo кнопки.

**Dependencies:** Нет.

---

### Task 2.1 -- Создать ProcessEditorModel

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Создать модель данных для редактирования конфигурации процессов и воркеров, аналогичную TopologyEditorModel.

**Контекст:** Сейчас ProcessMonitorModel хранит runtime-статус (push от backend). Нужна отдельная модель для "желаемой" конфигурации: какие процессы должны быть, какие воркеры у каждого, параметры. При Apply -- конфигурация отправляется в ProcessManager. Двухслойная модель: Layer 1 -- процессы, Layer 2 -- воркеры (foreign-key `process_ref`).

**Файлы:**
- `multiprocess_prototype/frontend/widgets/base/editor/process_editor_model.py` -- создать
- `multiprocess_prototype/frontend/widgets/base/editor/__init__.py` -- добавить экспорт

**Шаги:**
1. Создать `ProcessEditorModel(BaseEditorModel)` по образцу `TopologyEditorModel`.
2. Два dict-хранилища: `_processes: dict[str, dict]` и `_workers: dict[str, dict]`.
3. Свойства: `processes`, `workers`, `workers_for_process(proc_key)`.
4. `load_from_config(data: dict)` -- загрузка из `{"processes": {...}, "workers": {...}}`.
5. `full_snapshot() -> dict` -- deepcopy обоих слоёв.
6. Dirty tracking: переопределить `dirty`, `snapshot()`, `mark_clean()`.
7. Мутации процессов: `add_process(name, class_path, priority) -> (None, str)`, `remove_process(proc_key) -> (dict, None)` (каскадное удаление воркеров), `modify_process(proc_key, fields) -> (old, new)`.
8. Мутации воркеров: `add_worker(process_ref, worker_name, worker_type) -> (None, str)`, `remove_worker(worker_key) -> (dict, None)`, `modify_worker(worker_key, fields) -> (old, new)`.
9. `reorder_processes(proc_key, direction)` -- аналог reorder_cameras.
10. `validate() -> list[str]` -- проверка: имена уникальны, process_ref существует, class_path не пуст.

**Формат dict процесса:**
```python
{
    "name": "camera_0",
    "class_path": "multiprocess_prototype.backend.processes.camera.process.CameraProcess",
    "priority": "normal",
    "auto_start": True,
    "sort_order": 0,
}
```

**Формат dict воркера (конфигурация — editor):**
```python
{
    "process_ref": "camera_0",
    "name": "main_worker",
    "worker_type": "camera_capture",
    "enabled": True,
    "protected": True,           # главный воркер -- нельзя удалить/остановить
    "target_interval_ms": 0,     # 0 = без ограничения (макс. скорость), >0 = smart sleep
    "sort_order": 0,
}
```

**Формат dict воркера (runtime — monitor, приходит в heartbeat):**
```python
{
    "status": "running",
    "worker_type": "camera_capture",
    "is_alive": True,
    "restart_count": 0,
    "last_error": "",
    "cycle_duration_ms": 130.5,  # фактическое время выполнения цикла
    "effective_hz": 7.65,        # эффективная частота (1000 / реальный_интервал)
    "target_interval_ms": 200,   # текущая настройка (для отображения)
    "sleep_ms": 69.5,            # добавленная задержка (target - actual)
}
```

**Cycle timing (smart sleep):**
Backend WorkerManager реализует: `sleep(max(0, target_interval_ms - actual_cycle_ms))`.
- `target_interval_ms = 0` → без sleep, максимальная скорость
- `target_interval_ms = 200` и цикл 130ms → sleep 70ms → effective ~5 Hz
- GUI может редактировать `target_interval_ms` для ЛЮБОГО воркера, включая protected (замедлить можно, остановить — нельзя)
- Мониторинг: `cycle_duration_ms`, `effective_hz`, `sleep_ms` показываются в detail panel и в дереве

**Важно: protected-воркеры.**
Каждый процесс имеет главный воркер (опрос RouterManager). Этот воркер помечается `"protected": True`.
- `remove_worker()` на protected воркере → ValueError
- `modify_worker()` на protected воркере → нельзя менять `enabled` на False
- При `add_process()` автоматически создаётся default protected воркер
- GUI не показывает кнопку удаления для protected воркеров

**Acceptance criteria:**
- [ ] `ProcessEditorModel` наследует `BaseEditorModel`
- [ ] CRUD для процессов и воркеров работает корректно
- [ ] Каскадное удаление воркеров при удалении процесса
- [ ] `dirty` корректно отслеживает изменения обоих слоёв
- [ ] `validate()` ловит: пустое имя, дубликат имени, пустой class_path, несуществующий process_ref
- [ ] Protected воркер нельзя удалить (`remove_worker` → ValueError)
- [ ] Protected воркер нельзя отключить (`modify_worker` с `enabled=False` → ValueError)
- [ ] `add_process()` автоматически создаёт default protected воркер
- [ ] Нет зависимостей от Qt -- чистая бизнес-логика

**Out of scope:** Не привязывать к регистрам (Task 2.2). Не добавлять merge с runtime данными (Task 3.1).

**Edge cases:** Попытка удалить несуществующий процесс -- KeyError. Попытка добавить воркера к несуществующему процессу -- KeyError. Имя воркера уникально в рамках процесса. Попытка удалить protected воркер -- ValueError с понятным сообщением.

---

### Task 2.2 -- Создать ProcessConfigBridge

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать bridge между ProcessEditorModel и ProcessManager для загрузки текущей конфигурации и отправки изменений.

**Контекст:** В отличие от TopologyRegisterBridge (работает с RegistersManager), ProcessConfigBridge работает через IPC-команды к ProcessManager. Загрузка: запрос `process.list` -> ответ -> заполнение модели. Сохранение: для каждого изменения -> команда `process.create`/`process.stop`/etc.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/process_config_bridge.py` -- создать

**Шаги:**
1. Создать `ProcessConfigBridge` с зависимостями: `ProcessEditorModel`, `command_handler`.
2. Метод `load_from_snapshot(snapshot: dict)` -- преобразование формата `process_full_status` в формат ProcessEditorModel (`{"processes": {...}, "workers": {...}}`). Вызывается из ProcessDataBridge при получении полного снимка.
3. Метод `apply_changes() -> bool` -- сравнивает текущее состояние модели со snapshot, генерирует набор команд (create/stop для разницы), отправляет через `command_handler`.
4. Логика diff для процессов:
   - Новые процессы (есть в модели, нет в snapshot) -> `process.create`
   - Удалённые процессы (есть в snapshot, нет в модели) -> `process.stop`
   - Изменённые параметры -> пока не поддерживается (log warning)
5. Логика diff для воркеров:
   - Новые воркеры -> команда через RouterManager → WorkerManager целевого процесса: `worker.create`
   - Удалённые воркеры (кроме protected!) -> `worker.stop` + `worker.remove`
   - Protected воркеры пропускаются (никогда не отправлять stop/remove)
6. `mark_clean()` после успешного apply.

**Acceptance criteria:**
- [ ] `load_from_snapshot` корректно преобразует формат runtime -> editor (включая protected флаг для main worker)
- [ ] `apply_changes` отправляет `process.create` для новых процессов
- [ ] `apply_changes` отправляет `process.stop` для удалённых процессов
- [ ] `apply_changes` отправляет `worker.create`/`worker.stop` для воркеров (через RouterManager → целевой процесс)
- [ ] Protected воркеры НИКОГДА не попадают в команды stop/remove
- [ ] После apply модель помечается чистой

**Out of scope:** Inline-edit параметров запущенного процесса. Hot-reload конфигурации воркера без перезапуска.

**Dependencies:** Task 2.1

---

### Task 3.1 -- Переработать ProcessTreeView (editor + monitor merge)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Расширить ProcessTreeView для отображения merged данных из ProcessEditorModel (конфигурация) и ProcessMonitorModel (runtime), с визуальным отличием.

**Контекст:** Дерево должно показывать: (1) процессы из конфигурации (editor) -- даже если не запущены; (2) runtime-статус от монитора (статус, PID, heartbeat). Процессы только в editor (новые, ещё не apply) -- серым курсивом. Процессы только в monitor (не в конфиге, внешние) -- обычным текстом с пометкой.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/process_tree_view.py` -- переработать

**Шаги:**
1. Конструктор принимает ОБА: `editor_model: ProcessEditorModel`, `monitor_model: ProcessMonitorModel`.
2. `_populate()` строит merged двухуровневое дерево:
   - Собрать union ключей из editor_model.processes и monitor_model.processes
   - Для каждого процесса: editor дает конфигурацию (class_path, priority), monitor дает runtime (status, pid, alive, workers)
   - Воркеры: union из editor_model.workers_for_process() и monitor workers
3. Визуальное различие:
   - Процесс только в editor (не запущен) -- italic шрифт, статус "configured"
   - Процесс только в monitor (нет в editor) -- обычный, пометка "(external)" в имени
   - Процесс в обоих -- обычный bold + runtime статус
4. Колонки воркера включают timing: `cycle_duration_ms` и `effective_hz` из monitor data.
   Формат в summary-колонке: `"130ms / 7.7Hz"` (или `"—"` если нет данных).
   Protected воркер: значок замка в имени.
5. Сохранить обратную совместимость сигналов `item_selected`/`selection_cleared`.

**Acceptance criteria:**
- [ ] Дерево показывает процессы из обеих моделей
- [ ] Новые (только editor) процессы визуально отличаются italic
- [ ] Runtime-статус отображается для запущенных процессов
- [ ] Воркеры показываются как дочерние узлы (как было + из editor)
- [ ] Selection persistence работает при refresh

**Out of scope:** Inline editing в дереве. Drag-and-drop.

**Dependencies:** Task 1.1, Task 2.1

---

### Task 3.2 -- Расширить CreateProcessDialog (процессы + воркеры)

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Расширить CreateProcessDialog для создания и процессов, и воркеров через табы или mode-switch.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/create_process_dialog.py` -- переработать

**Шаги:**
1. Добавить в диалог QTabWidget с двумя табами: "Процесс" и "Воркер".
2. Таб "Процесс" -- существующая форма (имя, класс, приоритет) + новый QCheckBox "Автозапуск".
3. Таб "Воркер" -- новая форма:
   - Имя воркера (QLineEdit)
   - Процесс-владелец (QComboBox, заполняется из переданного списка имён процессов)
   - Тип воркера (QComboBox: camera_capture, frame_processor, data_writer, custom)
   - Enabled (QCheckBox, по умолчанию True)
   - Целевой интервал, мс (QSpinBox, 0-10000, default 0, tooltip "0 = макс. скорость")
4. Метод `set_available_processes(names: list[str])` -- обновить QComboBox процессов.
5. Метод `set_mode(mode: str)` -- "process" или "worker", переключает активный таб.
6. Метод `get_data() -> dict` -- возвращает данные с ключом `"mode": "process"|"worker"`.

**Acceptance criteria:**
- [ ] Диалог имеет два таба: Процесс и Воркер
- [ ] `get_data()` возвращает `mode` + соответствующие поля
- [ ] QComboBox процессов заполняется через `set_available_processes()`
- [ ] Backward-compatible: если не вызвать set_mode, работает как раньше (таб "Процесс")

**Out of scope:** Валидация уникальности имени (делается в widget.py).

**Dependencies:** Нет.

---

### Task 3.3 -- Создать ProcessDetailPanel (QStackedWidget)

**Level:** Middle (Sonnet, normal)
**Assignee:** developer
**Goal:** Заменить QLabel detail panel на QStackedWidget с формами процесса и воркера.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/process_detail_panel.py` -- создать

**Шаги:**
1. Создать `ProcessDetailPanel(QStackedWidget)` с тремя pages:
   - Page 0: Placeholder QLabel "Выберите элемент"
   - Page 1: ProcessInfoForm -- QFormLayout с полями: Имя (QLabel), Статус (QLabel с цветом), PID (QLabel), Класс (QLabel), Приоритет (QLabel), Alive (QLabel), Workers summary (QLabel)
   - Page 2: WorkerInfoForm -- QFormLayout:
     - Имя (QLabel), Процесс (QLabel), Статус (QLabel с цветом), Тип (QLabel)
     - Protected (QLabel — "Защищён" если protected)
     - **Timing секция (QGroupBox "Timing"):**
       - Целевой интервал (QSpinBox, 0-10000 мс, **редактируемый** — signal `target_interval_changed(worker_key, value)`)
       - Цикл (QLabel, readonly) — `cycle_duration_ms` из monitor
       - Частота (QLabel, readonly) — `effective_hz` из monitor
       - Задержка (QLabel, readonly) — `sleep_ms` из monitor
     - Alive (QLabel), Рестарты (QLabel), Ошибка (QLabel, wordWrap)
2. Метод `show_placeholder()` -- page 0.
3. Метод `show_process(data: dict)` -- заполнить ProcessInfoForm и переключить на page 1.
4. Метод `show_worker(proc_name: str, data: dict)` -- заполнить WorkerInfoForm и переключить на page 2. Заполняет и config-поля (target_interval) и monitor-поля (cycle, hz, sleep).
5. Signal `target_interval_changed(str, int)` -- emitится при изменении QSpinBox target_interval. Widget.py ловит и обновляет editor_model + отправляет IPC-команду для hot-update.
6. Внутри форм: QLabel-ы обновляются через setText, цвет статуса через `setStyleSheet`.

**Acceptance criteria:**
- [ ] 3 pages: placeholder, process, worker
- [ ] `show_process()` отображает все поля процесса
- [ ] `show_worker()` отображает все поля воркера с timing секцией
- [ ] Цвет статуса соответствует STATUS_COLORS/WORKER_STATUS_COLORS
- [ ] QSpinBox target_interval — редактируемый, emitит signal
- [ ] Monitor-поля timing (cycle, hz, sleep) — readonly QLabel, обновляются при refresh
- [ ] Protected воркер: target_interval всё равно редактируемый (замедлить можно)

**Out of scope:** Не делать ДРУГИЕ поля редактируемыми (только target_interval). Не добавлять кнопки управления.

**Dependencies:** Нет.

---

### Task 3.4 -- Собрать новый ProcessesTabWidget

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Пересобрать ProcessesTabWidget как полноценный editor+monitor, используя все новые компоненты.

**Контекст:** Это интеграционная задача. ProcessesTabWidget должен совмещать редактирование конфигурации (ProcessEditorModel, toolbar, dirty tracking, Apply) с runtime мониторингом (ProcessMonitorModel, ProcessDataBridge, polling).

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/widget.py` -- переписать
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/__init__.py` -- проверить экспорты

**Шаги:**
1. Конструктор принимает `command_handler` (как сейчас).
2. Создать ProcessEditorModel и ProcessMonitorModel.
3. Создать ProcessTreeView с обеими моделями.
4. Создать BaseEditorToolbar с кнопками:
   - "+ Процесс" -> _on_add_process()
   - "+ Воркер" -> _on_add_worker()
   - "Удалить" -> _on_remove()
   - Разделитель
   - Кнопки управления: "Запустить", "Остановить", "Перезапустить", "Пауза"
   - Apply (через BaseEditorToolbar.apply_clicked)
5. Создать ProcessDetailPanel вместо QLabel.
6. Создать ProcessConfigBridge и ProcessDataBridge.
7. Layout: QSplitter(Vertical) -- [tree + toolbar] сверху, detail panel снизу.
8. Wiring:
   - editor_model.add_change_callback -> tree.refresh + toolbar.set_dirty
   - monitor_model.add_change_callback -> tree.refresh + обновить detail panel
   - tree.item_selected -> переключить detail panel + обновить кнопки управления
   - toolbar.apply_clicked -> config_bridge.apply_changes
   - toolbar кнопки: + Процесс -> CreateProcessDialog(mode="process") -> editor_model.add_process
   - toolbar кнопки: + Воркер -> CreateProcessDialog(mode="worker") -> editor_model.add_worker
   - toolbar кнопки: Удалить -> editor_model.remove_process/remove_worker
   - toolbar кнопки управления: -> ProcessControlPanel._send_pm_command (перенести логику)
9. Инициализация: ProcessDataBridge.start_polling(), при получении первого snapshot -> ProcessConfigBridge.load_from_snapshot() для инициализации editor.

**Acceptance criteria:**
- [ ] Дерево показывает merge конфигурации и runtime
- [ ] Toolbar с кнопками CRUD + управления + Apply
- [ ] Apply отправляет команды в ProcessManager
- [ ] Detail panel переключается между process/worker/placeholder
- [ ] Runtime обновления (polling + broadcast) отражаются в дереве и detail panel
- [ ] Dirty tracking: Apply активна только при наличии изменений
- [ ] Создание процесса через диалог -> добавление в editor_model -> дерево обновляется
- [ ] Создание воркера через диалог -> добавление в editor_model -> дерево обновляется
- [ ] Удаление выбранного элемента с confirmation

**Out of scope:** Undo/redo (ActionBus для процессов). Drag-and-drop в дереве. Inline editing параметров.

**Dependencies:** Task 1.1, Task 1.2, Task 2.1, Task 2.2, Task 3.1, Task 3.2, Task 3.3

---

### Task 4.1 -- Обновить порядок вкладок

**Level:** Junior (Haiku, normal)
**Assignee:** docs-writer
**Goal:** Поменять порядок вкладок на: Процессы, Источники, Pipeline, Дисплей, Рецепты, Настройки.

**Файлы:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/tabs_config.py` -- изменить

**Шаги:**
1. В функции `_default_tabs()` изменить порядок return на:
   ```python
   return [_processes(), _sources(), _graph(), _disp(), _rec(), _set()]
   ```
2. Обновить docstring модуля, отразив новый порядок.

**Acceptance criteria:**
- [ ] Порядок вкладок: Процессы -> Источники -> Pipeline -> Дисплей -> Рецепты -> Настройки
- [ ] Приложение запускается без ошибок с новым порядком

**Out of scope:** Не менять содержимое TabItemConfig. Не трогать логику TabsConfig.

**Dependencies:** Нет (можно делать параллельно).

---

## Риски и ограничения

1. **Backend API для воркеров** -- сейчас ProcessManager поддерживает только CRUD процессов. CRUD воркеров через IPC пока нет. ProcessConfigBridge.apply_changes() для воркеров -- только локальное изменение модели, без отправки в backend. Нужна backend-доработка в Phase 2.
2. **Merge двух моделей** -- ProcessTreeView должен корректно merge-ить editor и monitor. Edge case: процесс создан в editor, ещё не apply, но ProcessManager уже знает о нём (из предыдущей сессии) -- дубликатов не должно быть.
3. **ProcessControlPanel** -- его логика (send_pm_command, debounce, confirmation) переносится в ProcessesTabWidget. Сам ProcessControlPanel можно удалить или оставить как legacy.
4. **Тестирование** -- для ProcessEditorModel и ProcessConfigBridge нужны unit-тесты. Для UI -- ручное тестирование.
