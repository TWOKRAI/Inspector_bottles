# Plan: Phase 2 SystemTopology -- миграция вкладок на SystemTopologyEditor

**Date:** 2026-04-29
**Status:** DONE

## Overview

Перевести 4 вкладки настроек (Processes, Sources, Display, Pipeline) с изолированных моделей/bridge-ов на единый `SystemTopologyEditor` + `TopologyBridge` из Phase 1 (commit 7f21b30). Вкладки перестают хранить данные самостоятельно -- работают через section views. Кнопка "Применить" в каждой вкладке вызывает `bridge.apply(SECTION_X)`.

## Результат Phase 1 (что готово)

- `registers/system_topology/schemas.py` -- SystemTopology, секционные константы
- `frontend/models/system_topology_editor.py` (458 строк) -- центральная модель
- `frontend/models/sections/` -- 4 section views (780 строк суммарно)
- `frontend/bridges/topology_bridge.py` (365 строк) -- единый bridge
- 71 тест (schema, editor, sections, bridge, converters)

## Ключевые API-несовместимости (выявлены при анализе)

| Где | Старый API | Новый API (section view) | Решение |
|-----|-----------|--------------------------|---------|
| `SourcesTabWidget._on_add_camera` | `_, (cam_key, _reg_key) = model.add_camera()` возвращает `tuple[None, tuple[str, str]]` | `SourcesSectionView.add_camera()` возвращает `tuple[str, str]` | Обновить вызов в widget.py |
| `SourcesTabWidget` wiring | `model.add_change_callback(cb)` через `BaseEditorModel` | `editor.subscribe(SECTION_SOURCES, cb)` | Заменить wiring |
| `ProcessesTabWidget` wiring | `editor_model.add_change_callback(cb)` | `editor.subscribe(SECTION_PROCESSES, cb)` | Заменить wiring |
| `TopologyActionHandler.apply()` | `model.load_from_topology(snapshot)` | `SourcesSectionView.load_from_snapshot(data)` | Обновить handler |
| `TopologyTreeView.__init__` | type hint `TopologyEditorModel` | `SourcesSectionView` (duck-typed: `.cameras`, `.regions`, `.regions_for_camera()`) | Расширить type hint |
| `ProcessTreeView` | принимает `editor_model: ProcessEditorModel` | `ProcessesSectionView` (duck-typed: `.processes`, `.workers_for_process()`) | Расширить type hint |

---

## Execution order

### Phase 2.0: Подготовка (wiring + context)

- Task 2.1: FrontendAppContext + Launcher wiring [DONE — commit 3664444]

### Phase 2.1: Миграция вкладок (параллельно)

- Task 2.2: ProcessesTab [DONE — commit cc045da]
- Task 2.3: SourcesTab [DONE — commit 95f901c]
- Task 2.4: DisplayTab [DONE — commit 95f901c]
- Task 2.5: PipelineTab [DONE — commit ecb6636]

### Phase 2.2: Cross-tab виджет

- Task 2.6: CrossTabComboBox [DONE — commit 25f948f]

### Phase 2.3: Тесты + cleanup

- Task 2.7: Тесты Phase 2 [DONE — commit 38c28d0]
- Task 2.8: Удаление deprecated файлов [DONE — commit 2fc9f14]

---

## Задачи

### Task 2.1 -- Wiring: FrontendAppContext + Launcher + TabFactory

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать единственные экземпляры SystemTopologyEditor + TopologyBridge в launcher, передать через FrontendAppContext в tab_factory, чтобы все вкладки получали общие объекты.

**Context:** Сейчас каждая вкладка создаёт свою модель/bridge. Нужна единая точка создания в `register_windows()` (launcher.py строки 80-197), передача через `FrontendAppContext` (dataclass) и потребление в `create_tab_widget_factory()` (tab_factory.py).

**Files:**
- `multiprocess_prototype/frontend/app_context.py` -- добавить поля `topology_editor` и `topology_bridge`
- `multiprocess_prototype/frontend/launcher.py` -- создать editor + bridge в `register_windows()`
- `multiprocess_prototype/frontend/windows/main_window/tab_factory.py` -- передавать editor/bridge в вкладки

**Steps:**

1. В `app_context.py` добавить два поля в dataclass `FrontendAppContext`:
   ```python
   topology_editor: Optional[Any] = None   # SystemTopologyEditor
   topology_bridge: Optional[Any] = None   # TopologyBridge
   ```
   Тип `Any` (не прямой import) -- для обратной совместимости, когда editor ещё не создан.

2. В `launcher.py`, в методе `register_windows()`, после создания `cmd = GuiCommandHandler(process_ref)` (строка 80) и перед созданием `app_ctx = FrontendAppContext(...)` (строка 181):
   ```python
   from multiprocess_prototype.frontend.models.system_topology_editor import SystemTopologyEditor
   from multiprocess_prototype.frontend.bridges.topology_bridge import TopologyBridge

   topology_editor = SystemTopologyEditor()
   topology_bridge = TopologyBridge(
       editor=topology_editor,
       command_handler=cmd,
       registers_manager=regs,
       window_manager=window_manager_display,
       display_router=display_router,
   )
   ```

3. Передать в `FrontendAppContext(...)` (строка 181):
   ```python
   app_ctx = FrontendAppContext(
       ...  # все существующие аргументы без изменений
       topology_editor=topology_editor,
       topology_bridge=topology_bridge,
   )
   ```

4. В `create_main_window` (строка 206), после создания окна, вызвать загрузку из бэкенда:
   ```python
   topology_bridge.load_from_backend()
   topology_bridge.subscribe_to_changes()
   ```
   ВАЖНО: вызывать ПОСЛЕ создания MainWindow и запуска QTimer, чтобы registers были уже подключены.

5. В `tab_factory.py` -- обновить создание каждой вкладки (в последующих Task 2.2-2.5). На данном этапе -- только убедиться что `ctx.topology_editor` и `ctx.topology_bridge` доступны.

**Acceptance criteria:**
- [ ] `FrontendAppContext` имеет поля `topology_editor` и `topology_bridge`
- [ ] При запуске `python multiprocess_prototype/run.py` -- editor и bridge создаются без ошибок
- [ ] `topology_bridge.load_from_backend()` вызывается, данные загружаются в editor
- [ ] Существующие вкладки продолжают работать без изменений (обратная совместимость)

**Out of scope:** Изменение самих вкладок -- только wiring. Не менять logic в editor/bridge.

**Edge cases:**
- `regs is None` (тесты без регистров) -- bridge создаётся с `registers_manager=None`, `load_from_backend()` загрузит пустые данные
- `window_manager_display` может быть None если `display_enabled=False` -- bridge примет None

**Dependencies:** Phase 1 (commit 7f21b30)

---

### Task 2.2 -- ProcessesTab: миграция на SystemTopologyEditor

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Заменить `ProcessEditorModel` + `ProcessConfigBridge` на `ProcessesSectionView` + `TopologyBridge` в ProcessesTabWidget, сохранив ProcessDataBridge (мониторинг) и ProcessTreeView.

**Context:** ProcessesTabWidget (771 строк) использует 3 модели: ProcessEditorModel (CRUD конфигурации), ProcessMonitorModel (runtime), ProcessDataBridge (polling). Заменяется только первая -- ProcessEditorModel -> ProcessesSectionView (API совместим). ProcessConfigBridge удаляется -- "Применить" -> `bridge.apply(SECTION_PROCESSES)`.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/widget.py` -- основные изменения
- `multiprocess_prototype/frontend/windows/main_window/tab_factory.py` -- обновить создание ProcessesTabWidget

**Steps:**

1. В `tab_factory.py`, секция `widget_key == "processes"` (строки 105-111), обновить:
   ```python
   if widget_key == "processes":
       from multiprocess_prototype.frontend.widgets.tabs_setting.processes_tab.widget import (
           ProcessesTabWidget,
       )
       return ProcessesTabWidget(
           command_handler=ctx.command_handler,
           topology_editor=ctx.topology_editor,
           topology_bridge=ctx.topology_bridge,
       )
   ```

2. В `widget.py`, обновить `__init__` сигнатуру (строка 70):
   ```python
   def __init__(
       self,
       *,
       command_handler: Any | None = None,
       topology_editor: Any | None = None,   # SystemTopologyEditor
       topology_bridge: Any | None = None,    # TopologyBridge
       config: dict | None = None,
       parent: QWidget | None = None,
   ) -> None:
   ```

3. Заменить создание моделей (строки 101-111):
   - Убрать `self._editor_model = ProcessEditorModel()`
   - Добавить:
     ```python
     self._editor = topology_editor
     self._bridge = topology_bridge
     self._section = self._editor.processes if self._editor else None
     ```
   - Убрать `self._config_bridge = ProcessConfigBridge(...)` -- больше не нужен
   - `self._data_bridge = ProcessDataBridge(self._monitor_model, command_handler)` -- ОСТАВИТЬ

4. Заменить все обращения `self._editor_model` на `self._section`:
   - `self._editor_model.processes` -> `self._section.processes` (строки 198, 231, 670)
   - `self._editor_model.add_process(...)` -> `self._section.add_process(...)` (строка 217)
   - `self._editor_model.add_worker(...)` -> `self._section.add_worker(...)` (строка 270)
   - `self._editor_model.remove_process(...)` -> `self._section.remove_process(...)` (строка 311)
   - `self._editor_model.remove_worker(...)` -> `self._section.remove_worker(...)` (строка 346)
   - `self._editor_model.modify_worker(...)` -> `self._section.modify_worker(...)` (строка 511)
   - `self._editor_model.workers_for_process(...)` -> `self._section.workers_for_process(...)` (строка 700)
   - `self._editor_model.validate()` -> `self._section.validate()` (строка 474)
   - `self._editor_model.dirty` -> `self._section.dirty` (строка 527)

5. Заменить wiring подписок (строка 152):
   - Убрать: `self._editor_model.add_change_callback(self._on_editor_changed)`
   - Добавить: `self._editor.subscribe(SECTION_PROCESSES, self._on_editor_changed)` (import SECTION_PROCESSES из schemas)

6. Заменить `_on_apply` (строки 472-486):
   ```python
   def _on_apply(self) -> None:
       errors = self._section.validate()
       if errors:
           error_text = "\n".join(f"  - {e}" for e in errors)
           QMessageBox.warning(self, "Ошибки валидации", ...)
           return
       if self._bridge:
           self._bridge.apply(SECTION_PROCESSES)
       self._toolbar.set_dirty(False)
   ```

7. Обновить `_on_monitor_changed` (строки 529-564):
   - `self._config_bridge.load_from_snapshot(snapshot)` -> заменить на загрузку через editor:
     ```python
     # Конвертировать monitor snapshot в формат editor
     from .process_config_bridge import _snapshot_to_editor_format  # extract as standalone fn
     editor_data = _snapshot_to_editor_format(snapshot)
     self._section.load_from_snapshot(editor_data)
     ```
   - АЛЬТЕРНАТИВА (проще): извлечь логику конвертации из `ProcessConfigBridge.load_from_snapshot()` в standalone функцию, оставив ProcessConfigBridge.py на месте до Task 2.8.

8. Обновить `ProcessTreeView` (строка 126):
   - `self._tree = ProcessTreeView(self._monitor_model, editor_model=self._editor_model)` -> 
   - `self._tree = ProcessTreeView(self._monitor_model, editor_model=self._section)`
   - ProcessTreeView работает duck-typed (`.processes`, `.workers_for_process()`) -- совместимо.

9. Убрать import `ProcessEditorModel` и `ProcessConfigBridge` из widget.py.

**Acceptance criteria:**
- [ ] ProcessesTab создаётся через tab_factory с editor/bridge
- [ ] Добавление/удаление процесса -> editor.is_dirty(SECTION_PROCESSES) == True
- [ ] "Применить" -> bridge.apply(SECTION_PROCESSES) отправляет IPC-команды
- [ ] Мониторинг (ProcessDataBridge) продолжает работать
- [ ] ProcessTreeView корректно отображает merge editor + monitor
- [ ] Нет регрессий в CRUD и управляющих кнопках (start/stop/restart)

**Out of scope:** Не менять ProcessTreeView, ProcessDetailPanel, ProcessMonitorModel, ProcessDataBridge. Не удалять файлы (Task 2.8).

**Edge cases:**
- `topology_editor=None` (backward compat / тесты) -- fallback на создание локального ProcessEditorModel
- `_on_monitor_changed` при `_editor_initialized=False` -- первый snapshot инициализирует editor через section

**Dependencies:** Task 2.1

---

### Task 2.3 -- SourcesTab: миграция на SystemTopologyEditor

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Заменить `TopologyEditorModel` + `TopologyRegisterBridge` на `SourcesSectionView` + `TopologyBridge` в SourcesTabWidget, обновить TopologyActionHandler.

**Context:** SourcesTabWidget (414 строк) проще ProcessesTab -- нет мониторинга, есть ActionBus undo/redo через snapshot-подход. Главные API-несовместимости: 1) `add_camera()` возвращает разный tuple, 2) `add_change_callback` -> `subscribe`, 3) TopologyActionHandler использует `load_from_topology()`.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/sources_tab/widget.py` -- основные изменения
- `multiprocess_prototype/frontend/windows/main_window/tab_factory.py` -- обновить создание
- `multiprocess_prototype/frontend/actions/handlers/topology_handler.py` -- обновить API
- `multiprocess_prototype/frontend/widgets/tabs_setting/sources_tab/topology_tree_view.py` -- обновить type hint

**Steps:**

1. В `tab_factory.py`, секция `widget_key == "sources"` (строки 50-65), добавить передачу editor/bridge:
   ```python
   return SourcesTabWidget(
       camera_type=camera_type,
       registers_manager=registers_manager,
       callbacks_map=camera_callbacks_map,
       command_handler=ctx.command_handler,
       ...  # все существующие аргументы
       topology_editor=ctx.topology_editor,
       topology_bridge=ctx.topology_bridge,
   )
   ```

2. В `widget.py`, обновить `__init__` сигнатуру -- добавить `topology_editor` и `topology_bridge`.

3. Заменить создание модели (строка 64):
   - Убрать: `self._model = TopologyEditorModel()`
   - Добавить:
     ```python
     self._editor = topology_editor
     self._section = self._editor.sources if self._editor else None
     # Для backward compat -- TopologyTreeView и ActionBus используют self._model
     self._model = self._section  # duck-typed: .cameras, .regions, .regions_for_camera()
     ```

4. Исправить `_on_add_camera` (строка 233-236):
   - Было: `_, (cam_key, _reg_key) = self._model.add_camera(self._camera_type)`
   - Стало: `cam_key, _reg_key = self._section.add_camera(self._camera_type)`
   - Аналогично: `full_snapshot()` уже совместим.

5. Исправить `_on_add_region` (строка 239-245):
   - Было: `_, reg_key = self._model.add_region(cam_key)`
   - Стало: `reg_key = self._section.add_region(cam_key)`
   - `SourcesSectionView.add_region()` возвращает `str`, не `tuple`.

6. Заменить wiring подписок (строка 127):
   - Убрать: `self._model.add_change_callback(self._on_model_changed)`
   - Добавить: `self._editor.subscribe(SECTION_SOURCES, self._on_model_changed)`

7. Убрать bridge (строки 116-121):
   - Убрать: `self._bridge: TopologyRegisterBridge | None = None` и всю инициализацию
   - Хранить: `self._bridge = topology_bridge`

8. Обновить `_on_apply` (строки 362-367):
   ```python
   def _on_apply(self) -> None:
       if self._bridge is not None:
           if self._bridge.apply(SECTION_SOURCES):
               self._btn_apply.setEnabled(False)
               self._btn_apply.setStyleSheet("")
   ```

9. Обновить `_on_model_changed` (строки 178-189):
   - `self._model.dirty` -> `self._section.dirty`

10. Обновить `TopologyActionHandler` (topology_handler.py):
    - `self._model.load_from_topology(snapshot)` -> `self._model.load_from_snapshot(snapshot)`
    - Или: на SourcesSectionView уже есть `load_from_snapshot(data)` -- просто переименовать вызов.

11. В `topology_tree_view.py` (строка 72):
    - Расширить type hint: `def __init__(self, model: TopologyEditorModel | Any, ...)` или использовать Protocol.
    - Функционально ничего не меняется -- duck-typed доступ к `.cameras`, `.regions`, `.regions_for_camera()`.

12. ActionBus wiring (строки 122-124):
    - Было: `action_bus._topology_handler.set_model(self._model)`
    - Стало: `action_bus._topology_handler.set_model(self._section)` -- set_model() принимает Any.

13. Убрать imports: `TopologyEditorModel`, `TopologyRegisterBridge`.

**Acceptance criteria:**
- [ ] SourcesTab создаётся через tab_factory с editor/bridge
- [ ] Добавление камеры -> editor.is_dirty(SECTION_SOURCES) == True
- [ ] "Применить" -> bridge.apply(SECTION_SOURCES) записывает в регистры
- [ ] Undo/redo через ActionBus работает (snapshot-based)
- [ ] TopologyTreeView корректно отображает камеры/регионы
- [ ] RegionForm -> modify_region -> tree обновляется

**Out of scope:** Не менять CameraTabWidget, RegionForm, TopologyTreeView (кроме type hint). Не удалять файлы.

**Edge cases:**
- `topology_editor=None` -- fallback на создание TopologyEditorModel (backward compat)
- `_on_add_region` без выбранной камеры -- `_selected_cam()` уже возвращает None
- `reorder_cameras`/`reorder_regions` -- в SourcesSectionView нет этих методов. НУЖНО ДОБАВИТЬ или проксировать через `modify_camera`/`modify_region` с пересчётом sort_order.

**ВАЖНО -- reorder методы:**
`TopologyEditorModel` имеет методы `reorder_cameras(cam_key, direction)` и `reorder_regions(reg_key, direction)` (строки 276-282 в widget.py). `SourcesSectionView` НЕ имеет этих методов. Варианты:
- A) Добавить `reorder_cameras()` и `reorder_regions()` в SourcesSectionView (предпочтительно)
- B) Реализовать reorder через modify с пересчётом sort_order в widget

Выбрать вариант A: добавить методы в SourcesSectionView.

**Dependencies:** Task 2.1

---

### Task 2.4 -- DisplayTab: миграция на SystemTopologyEditor

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Перевести DisplayTabWidget на работу через DisplaysSectionView + TopologyBridge вместо прямых вызовов DisplayWindowManager и DisplayRouter.

**Context:** DisplayTabWidget (258 строк) -- самая простая вкладка. Напрямую вызывает `window_manager.create_window()` и `display_router.apply_preset()`. Нужно перевести на: редактирование через DisplaysSectionView -> "Применить" -> bridge.apply(SECTION_DISPLAYS). Пресеты реализуются через `DisplaysSectionView.apply_preset()`.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/display_tab/widget.py` -- основные изменения
- `multiprocess_prototype/frontend/windows/main_window/tab_factory.py` -- обновить создание

**Steps:**

1. В `tab_factory.py`, секция `widget_key == "display"` (строки 66-82), обновить:
   ```python
   if widget_key == "display":
       window_manager = ctx.extras.get("window_manager")
       display_router = ctx.extras.get("display_router")
       camera_registry = ctx.camera_registry
       if window_manager is None or display_router is None or camera_registry is None:
           ...  # warning, return None
       return DisplayTabWidget(
           window_manager=window_manager,
           display_router=display_router,
           camera_registry=camera_registry,
           topology_editor=ctx.topology_editor,
           topology_bridge=ctx.topology_bridge,
       )
   ```

2. В `widget.py`, обновить `__init__` сигнатуру -- добавить `topology_editor` и `topology_bridge`.

3. Добавить хранение editor/bridge:
   ```python
   self._editor = topology_editor
   self._bridge = topology_bridge
   self._section = self._editor.displays if self._editor else None
   ```

4. Обновить `_on_preset_clicked` (строки 148-174):
   - Вместо прямых вызовов `display_router.apply_preset()` + `window_manager.create_window()`:
   ```python
   def _on_preset_clicked(self, preset: LayoutPreset) -> None:
       camera_keys = self._get_camera_keys()  # из editor, не из camera_registry
       preset_map = {LayoutPreset.NONE: "none", LayoutPreset.SINGLE: "single",
                     LayoutPreset.DUAL: "dual", LayoutPreset.QUAD: "quad"}
       preset_name = preset_map.get(preset, "none")
       if preset_name == "none":
           # Очистить все displays
           for key in list(self._section.displays.keys()):
               self._section.remove_display(key)
       else:
           self._section.apply_preset(preset_name, camera_keys)
       if self._bridge:
           self._bridge.apply(SECTION_DISPLAYS)
       self._refresh_table()
   ```

5. Обновить `_on_add_window` (строки 176-182):
   ```python
   def _on_add_window(self) -> None:
       self._section.add_display(name="Display", source_ref="camera_0", fps_limit=30)
       # Не вызываем bridge.apply -- пользователь должен нажать "Применить"
       self._refresh_table()
   ```

6. Обновить `_on_remove_window` (строки 185-192):
   ```python
   def _on_remove_window(self, window_id: str) -> None:
       self._section.remove_display(window_id)
       self._refresh_table()
   ```

7. Добавить кнопку "Применить" в UI (`_build_ui`), по аналогии с SourcesTab:
   ```python
   self._btn_apply = QPushButton("Применить")
   self._btn_apply.clicked.connect(self._on_apply)
   bottom_row.addWidget(self._btn_apply)
   ```

8. Добавить `_on_apply`:
   ```python
   def _on_apply(self) -> None:
       if self._bridge:
           self._bridge.apply(SECTION_DISPLAYS)
   ```

9. Обновить `_get_camera_ids` -> `_get_camera_keys`:
   - Было: `self._camera_registry.camera_ids()` -> `list[int]`
   - Стало: `self._editor.camera_keys()` -> `list[str]`

10. Обновить `_refresh_table` (строки 198-235):
    - Вместо `self._display_router.get_active_subscriptions()` -- читать из `self._section.displays`
    - Каждый display -> строка таблицы с window_id, source_ref, fps_limit

**Acceptance criteria:**
- [ ] Пресеты создают display definitions в section view
- [ ] "Применить" -> bridge.apply(SECTION_DISPLAYS) создаёт/удаляет окна через Direct API
- [ ] Таблица отображает текущее состояние из section view
- [ ] Add/Remove обновляют section (dirty), не трогают бэкенд до "Применить"

**Out of scope:** Не менять DisplayWindowManager, DisplayRouter. Не менять layout presets logic (она переехала в DisplaysSectionView.apply_preset).

**Edge cases:**
- Пресет "0" (NONE) при пустом state -- ничего не должно падать
- `topology_editor=None` -- fallback на прежнее поведение (direct API)

**Dependencies:** Task 2.1

---

### Task 2.5 -- PipelineTab: интеграция с SystemTopologyEditor

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Подключить PipelineTabWidget к SystemTopologyEditor для получения camera/region/process списков и сохранения pipeline через TopologyBridge.

**Context:** PipelineTabWidget (152 строки) -- наименьшие изменения. GraphEditorModel ОСТАЁТСЯ (специализирован для node-graph). Нужно: 1) `known_processes_provider` из editor, 2) camera/region selection из editor, 3) save/load через pipeline_section.

**Files:**
- `multiprocess_prototype/frontend/widgets/pipeline/pipeline_tab/widget.py` -- минимальные изменения
- `multiprocess_prototype/frontend/windows/main_window/tab_factory.py` -- обновить создание

**Steps:**

1. В `tab_factory.py`, секция `widget_key == "pipeline"` (строки 83-104), обновить:
   ```python
   if widget_key == "pipeline":
       catalog = ctx.extras.get("processing_catalog", {}) or {}
       editor = ctx.topology_editor
       return PipelineTabWidget(
           action_bus=ctx.action_bus,
           catalog=catalog,
           region_id="default",
           known_processes_provider=editor.process_names if editor else lambda: [],
           known_displays_provider=lambda: list(
               (ctx.extras.get("window_manager")
                and ctx.extras["window_manager"]._windows.keys()) or [],
           ),
           topology_editor=editor,
           topology_bridge=ctx.topology_bridge,
       )
   ```
   Заменить `lambda: list(ctx.extras.get("known_processes", []))` на `editor.process_names`.

2. В `widget.py`, обновить `__init__` сигнатуру -- добавить `topology_editor` и `topology_bridge` (опциональные).

3. Добавить хранение:
   ```python
   self._editor = topology_editor
   self._bridge = topology_bridge
   ```

4. В `set_pipeline()` (строки 136-145), после загрузки в GraphEditorModel -- также обновить pipeline_section:
   ```python
   def set_pipeline(self, nodes: dict[str, Any]) -> None:
       self._model.load(nodes, self._catalog)
       self._adapter.load_pipeline(nodes)
       self._table.refresh()
       self._inspector.clear()
       # Синхронизировать с SystemTopologyEditor
       if self._editor:
           self._editor.pipeline_section.set_pipeline_for_region(
               self._region_id, nodes
           )
   ```
   Сохранить `self._region_id = region_id` в конструкторе.

5. Добавить метод для сохранения pipeline через bridge (будущий "Применить"):
   ```python
   def apply_pipeline(self) -> bool:
       if self._bridge:
           return self._bridge.apply(SECTION_PIPELINE)
       return False
   ```

**Acceptance criteria:**
- [ ] `known_processes_provider` возвращает актуальный список из editor
- [ ] При добавлении процесса в ProcessesTab -> PipelineTab видит обновлённый список
- [ ] GraphEditorModel остаётся без изменений
- [ ] `set_pipeline()` синхронизирует данные с editor

**Out of scope:** Не менять GraphEditorModel, NodeGraphQtAdapter, InspectorPanel. Не добавлять кнопку "Применить" (будет в Phase 3 при полной интеграции pipeline -> register).

**Edge cases:**
- `topology_editor=None` -- fallback: `known_processes_provider` из `ctx.extras` (как сейчас)
- `region_id="default"` -- пока единственный pipeline, multi-region в будущем

**Dependencies:** Task 2.1

---

### Task 2.6 -- CrossTabComboBox: авто-обновляемый виджет

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Создать переиспользуемый QComboBox, который автоматически обновляет список при изменении указанной секции SystemTopologyEditor.

**Context:** После миграции вкладок нужен виджет для cross-tab зависимостей: ComboBox "выбор процесса" в SourcesTab, "выбор камеры" в PipelineTab/DisplayTab. Подписывается на editor.subscribe(section, callback) и вызывает provider_fn для получения актуальных данных.

**Files:**
- `multiprocess_prototype/frontend/widgets/base/editor/cross_tab_combo.py` -- СОЗДАТЬ

**Steps:**

1. Создать файл `cross_tab_combo.py`:
   ```python
   """CrossTabComboBox -- QComboBox с авто-обновлением из SystemTopologyEditor."""
   from __future__ import annotations
   from collections.abc import Callable
   from typing import Any

   from PySide6.QtWidgets import QComboBox, QWidget


   class CrossTabComboBox(QComboBox):
       """ComboBox, авто-обновляющийся при изменении секции editor.

       Использует editor.subscribe(section, callback) для реактивного обновления.
       provider_fn возвращает актуальный список строк.
       """

       def __init__(
           self,
           editor: Any,
           provider_fn: Callable[[], list[str]],
           section: str,
           *,
           parent: QWidget | None = None,
       ) -> None:
           super().__init__(parent)
           self._provider = provider_fn
           self._editor = editor
           self._section = section
           editor.subscribe(section, self._refresh)
           self._refresh()

       def _refresh(self) -> None:
           """Перестроить items, сохранив текущий выбор."""
           current = self.currentText()
           self.blockSignals(True)
           self.clear()
           items = self._provider()
           self.addItems(items)
           idx = self.findText(current)
           if idx >= 0:
               self.setCurrentIndex(idx)
           self.blockSignals(False)

       def disconnect_editor(self) -> None:
           """Отписаться при уничтожении виджета."""
           if self._editor:
               self._editor.unsubscribe(self._section, self._refresh)
   ```

2. Добавить export в `multiprocess_prototype/frontend/widgets/base/editor/__init__.py`:
   ```python
   from .cross_tab_combo import CrossTabComboBox
   ```

**Acceptance criteria:**
- [ ] CrossTabComboBox(editor, editor.process_names, SECTION_PROCESSES) -- показывает актуальные процессы
- [ ] При добавлении процесса -> ComboBox обновляется автоматически
- [ ] blockSignals предотвращает ложные сигналы при refresh
- [ ] Текущий выбор сохраняется после refresh (если элемент ещё существует)

**Out of scope:** Не интегрировать в вкладки (будет отдельно по мере необходимости). Не добавлять фильтрацию/поиск.

**Edge cases:**
- provider_fn возвращает пустой список -- ComboBox пуст, currentText() = ""
- Текущий выбранный элемент удалён -- idx = -1, выбор сбрасывается на первый элемент
- Виджет уничтожается -- вызвать `disconnect_editor()` для cleanup

**Dependencies:** Task 2.1 (editor API)

---

### Task 2.7 -- Тесты Phase 2

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Написать/обновить тесты для миграции вкладок, покрывающие wiring, CRUD через section views, apply через bridge, cross-tab обновления.

**Context:** Существующие тесты Phase 1 покрывают editor/sections/bridge в изоляции (71 тест). Нужны тесты уровня интеграции: tab widget получает editor -> CRUD -> bridge.apply() -> mock backend.

**Files:**
- `multiprocess_prototype/tests/unit/test_phase2_tab_wiring.py` -- СОЗДАТЬ
- `multiprocess_prototype/tests/unit/test_cross_tab_combo.py` -- СОЗДАТЬ
- `multiprocess_prototype/tests/unit/test_topology_action_handler.py` -- СОЗДАТЬ или обновить

**Steps:**

1. `test_phase2_tab_wiring.py` -- тесты wiring без Qt:
   - Тест: создать FrontendAppContext с editor/bridge -> ctx.topology_editor is not None
   - Тест: editor + bridge с mock command_handler -> bridge.apply(SECTION_PROCESSES) -> mock.send called
   - Тест: editor + bridge с mock registers_manager -> bridge.apply(SECTION_SOURCES) -> mock.set_field_value called
   - Тест: cross-tab -- добавить процесс -> editor.process_names() обновляется
   - Тест: cross-tab -- добавить камеру -> editor.camera_keys() обновляется

2. `test_cross_tab_combo.py` -- тесты с pytest-qt:
   - Тест: CrossTabComboBox(editor, provider, section) -> items заполнены
   - Тест: мутация в editor -> provider возвращает новые данные -> ComboBox обновляется
   - Тест: текущий выбор сохраняется при refresh
   - Тест: удалённый элемент -> выбор сбрасывается
   - Тест: disconnect_editor() -> подписка снята

3. `test_topology_action_handler.py`:
   - Тест: handler.set_model(section_view) -> apply(action) -> section.load_from_snapshot called
   - Тест: handler.revert(action) -> snapshot_before загружен

4. Убедиться что существующие Phase 1 тесты проходят без регрессий:
   ```
   python -m pytest multiprocess_prototype/tests/unit/test_system_topology*.py multiprocess_prototype/tests/unit/test_section_views.py multiprocess_prototype/tests/unit/test_topology_bridge.py -v
   ```

**Acceptance criteria:**
- [ ] Все новые тесты проходят
- [ ] Существующие Phase 1 тесты проходят без изменений
- [ ] Coverage: wiring, CRUD, apply, cross-tab, undo/redo handler
- [ ] pytest-qt тесты для CrossTabComboBox

**Out of scope:** Не тестировать GUI layout (визуальные тесты). Не тестировать реальный IPC.

**Dependencies:** Task 2.2, 2.3, 2.4, 2.5, 2.6

---

### Task 2.8 -- Cleanup: удаление deprecated файлов

**Level:** Middle (Sonnet, normal thinking)
**Assignee:** developer
**Goal:** Удалить файлы, ставшие ненужными после миграции, обновить __init__.py и imports.

**Context:** После успешной миграции и прохождения тестов -- удалить deprecated модели/bridge-ы, обновить re-exports.

**Files для удаления:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/process_config_bridge.py` (374 строки)
- `multiprocess_prototype/frontend/widgets/tabs_setting/sources_tab/register_bridge.py` (171 строк)

**Files для проверки перед удалением:**
- `multiprocess_prototype/frontend/widgets/tabs_setting/processes_tab/process_editor_model.py` (456 строк) -- проверить использование вне ProcessesTabWidget. Если используется -- ОСТАВИТЬ.
- `multiprocess_prototype/frontend/widgets/base/editor/topology_editor_model.py` (456 строк) -- используется в `topology_tree_view.py` (type hint) и `topology_handler.py`. После миграции type hint обновлён на Any/Protocol -> можно удалить. НО: если другие потребители есть -- ОСТАВИТЬ.

**Steps:**

1. `grep -r "ProcessConfigBridge" multiprocess_prototype/` -- убедиться нет других потребителей
2. `grep -r "TopologyRegisterBridge" multiprocess_prototype/` -- убедиться нет других потребителей
3. `grep -r "ProcessEditorModel" multiprocess_prototype/` -- проверить вне processes_tab/
4. `grep -r "TopologyEditorModel" multiprocess_prototype/` -- проверить вне sources_tab/
5. Удалить файлы, обновить `__init__.py`, убрать re-exports
6. Запустить `python scripts/validate.py` и `python scripts/run_framework_tests.py`

**Acceptance criteria:**
- [ ] Все тесты проходят после удаления
- [ ] Нет broken imports
- [ ] `python scripts/validate.py` -- OK

**Out of scope:** Не удалять BaseEditorModel (используется GraphEditorModel). Не удалять ProcessEditorModel если используется вне ProcessesTabWidget.

**Dependencies:** Task 2.7 (все тесты проходят)

---

## Дополнение к SourcesSectionView: reorder методы

**ВАЖНО для Task 2.3:** Перед миграцией SourcesTab нужно добавить в SourcesSectionView два метода, которые использует widget:

```python
# В sources_section.py

def reorder_cameras(self, cam_key: str, direction: int) -> None:
    """Переместить камеру вверх/вниз (direction: -1 или +1).

    Пересчитывает sort_order для всех камер.
    """
    ...

def reorder_regions(self, reg_key: str, direction: int) -> None:
    """Переместить регион вверх/вниз."""
    ...
```

Это можно сделать в рамках Task 2.3 (шаг 0) или как отдельный prep-task.

---

## Риски и ограничения

1. **API несовместимость add_camera/add_region return types** -- выявлена, описано решение в Task 2.3
2. **reorder_cameras/reorder_regions отсутствуют в SourcesSectionView** -- нужно добавить
3. **TopologyActionHandler.load_from_topology vs load_from_snapshot** -- переименование вызова
4. **backward compat** -- все вкладки должны работать с `topology_editor=None` (fallback на локальные модели) для поэтапной миграции
5. **ProcessDataBridge первый snapshot** -- конвертация runtime формата в editor формат (extract из ProcessConfigBridge.load_from_snapshot)
6. **Порядок инициализации** -- bridge.load_from_backend() должен вызываться после подключения регистров (после QTimer.start)
