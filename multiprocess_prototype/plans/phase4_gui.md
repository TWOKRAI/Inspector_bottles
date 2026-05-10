# Plan: Phase 4 — GUI для multiprocess_prototype

**Date:** 2026-05-05
**Status:** ✅ DONE

## Overview

Реализация PySide6 GUI как отдельного ProcessModule (GuiProcess) в v2.
GuiProcess запускает Qt event loop в main thread дочернего процесса, использует QTimer для polling IPC.
Topology Editor позволяет редактировать YAML-чертежи системы прямо из UI.

## Архитектурные решения

- **GuiProcess = ProcessModule** (не GenericProcess + GuiPlugin). Qt требует main thread, plugin.start() должен вернуть управление.
- **GuiProcess.run()** → QApplication.exec() (блокирует main thread, как в v1)
- **`_init_system_threads()` — оставить стандартный** (message_processor для system channel: stop, heartbeat, lifecycle)
- **Отдельный worker thread `data_receiver`** — блокируется на очереди `data` канала, при получении emit Qt signal → main thread обновляет UI
- **НЕ QTimer polling** — worker на блокирующем receive эффективнее (нет холостых вызовов, ниже latency, CPU idle когда нет данных)
- **GuiProcess описывается в topology YAML** как обычный процесс с `process_class: ...GuiProcess`
- **Dict at Boundary** — все данные между процессами только dict
- **MVP pattern** для табов (presenter + view Protocol)

### Threading model GuiProcess

```
Main thread (Qt event loop)
├── QApplication.exec()
├── Slot: on_frame_received(dict)   — обновление CameraView
├── Slot: on_state_updated(dict)    — обновление StatusWidget
└── Slot: on_command_response(dict) — обработка ответов

Worker: message_processor (framework, system channel)
└── router.receive(channel_types=['system'], timeout=0.1)
    → stop, heartbeat, lifecycle commands

Worker: data_receiver (app, data channel)
└── router.receive(channel_types=['data'], timeout=0.1)
    → msg → classify → emit Qt signal → main thread slot
```

**DataReceiverBridge(QObject)** — мост между worker thread и Qt main thread:
- `frame_received = Signal(dict)`
- `state_updated = Signal(dict)`  
- `command_response = Signal(dict)`

Worker `data_receiver` вызывает `bridge.signal.emit(msg_dict)` — Qt thread-safe доставка.

## Execution order

### Phase 4.1: GuiProcess
- Task 4.1: GuiProcess (ProcessModule) [DONE] ✅

### Phase 4.2: Базовые виджеты
- Task 4.2: MainWindow + табы + camera view [DONE] ✅ (depends on 4.1)

### Phase 4.3: Topology Editor
- Task 4.3: Topology Editor [DONE] ✅ (depends on 4.2)

### Phase 4.4: Registers Bridge
- Task 4.4: Registers Bridge [DONE] ✅ (depends on 4.2)

---

## Детальные спецификации

---

### Task 4.1 — GuiProcess (ProcessModule для Qt)

**Level:** Senior (Opus, normal thinking)
**Assignee:** teamlead
**Goal:** Создать GuiProcess — наследник ProcessModule с Qt event loop в main thread и data_receiver worker для IPC

**Context:**
В v1 GuiProcess наследует ProcessModule, делает `super().run()` (статус RUNNING + heartbeat),
затем создаёт FrontendLauncher и вызывает `launcher.run()` → `QApplication.exec()`.
В v2 аналогично, но без FrontendLauncher (упрощённый bootstrap).
GuiProcess описывается в topology YAML как обычный процесс, но с кастомным `process_class`.

**Ключевое отличие от v1:** вместо QTimer polling — о��дельный worker thread `data_receiver`,
который блокируется на очереди и при получении сообщения emit'ит Qt signal.
`_init_system_threads()` оставляем стандартный (message_processor для system channel).

**Files:**
- `multiprocess_prototype/frontend/__init__.py` — создать (пустой пакет)
- `multiprocess_prototype/frontend/process.py` — создать GuiProcess
- `multiprocess_prototype/frontend/bridge.py` — создать DataReceiverBridge (QObject + signals)
- `multiprocess_prototype/frontend/app.py` — создать: QApplication bootstrap

**Steps:**
1. Создать `frontend/__init__.py`

2. Создать `frontend/bridge.py` — DataReceiverBridge:
   - `DataReceiverBridge(QObject)` с Qt signals:
     - `frame_received = Signal(dict)`
     - `state_updated = Signal(dict)`
     - `command_response = Signal(dict)`
   - Метод `dispatch(msg_dict: dict)` — классифицирует по `data_type` и emit нужный signal
   - Thread-safe: signals можно emit из любого потока, Qt доставит в main thread

3. Создать `frontend/process.py`:
   - Класс `GuiProcess(ProcessModule)`
   - `_init_application_threads()`:
     - Создать `DataReceiverBridge()`
     - Создать worker `data_receiver` через `self.worker_manager.create_worker()`
     - Worker функция: `while not stop_event.is_set(): msgs = router.receive(data channel, timeout=0.1); for msg: bridge.dispatch(msg)`
     - PluginRegistry.discover() для доступа к каталогу плагинов (Task 4.3)
   - `_init_system_threads()` — **НЕ переопределять** (framework message_processor обрабатывает system channel)
   - `run()`:
     - `super().run()` (heartbeat, status RUNNING)
     - Вызов `run_gui(self)` из `app.py`
     - После возврата (Qt closed): `self._stop_requested = True`
   - `shutdown()` — graceful (cleanup Qt resources если нужно)

4. Создать `frontend/app.py`:
   - Функция `run_gui(process: GuiProcess)`:
     - `QApplication(sys.argv)`
     - Создать MainWindow (заглушка — пустое окно с заголовком)
     - QTimer(interval=1000) → проверка `process.should_stop()` → `app.quit()` (safety: если system послал stop)
     - `app.aboutToQuit.connect(lambda: setattr(process, '_stop_requested', True))`
     - `app.exec()`

5. Расширить topology для поддержки кастомных process classes:
   - В `multiprocess_framework/modules/process_module/generic/blueprint.py`:
     - `ProcessConfig` — добавить поле `process_class: str = ""`
     - `as_generic_config()` — если `process_class` не пустой, передать в GenericProcessConfig
   - Проверить `generic_process_config.py` — поле `process_class` уже должно быть или добавить

6. Создать topology YAML `multiprocess_prototype/topology/phase4_gui.yaml`:
   ```yaml
   name: phase4_gui
   description: "GUI process only (smoke test)"
   processes:
     - process_name: gui
       process_class: multiprocess_prototype.frontend.process.GuiProcess
       plugins: []
   wires: []
   ```

7. Тесты: `multiprocess_prototype/frontend/tests/test_gui_process.py`
   - Юнит-тест: GuiProcess инстанцируется, DataReceiverBridge создаётся
   - Юнит-тест: topology YAML парсится, blueprint.check() без ошибок
   - Юнит-тест: DataReceiverBridge.dispatch() emit'ит правильные signals
   - Интеграционный smoke: GuiProcess.run() открывает окно и закрывает (pytest-qt)

**Acceptance criteria:**
- [ ] `GuiProcess` наследует `ProcessModule`, реализует `run()` с Qt event loop
- [ ] `_init_system_threads()` стандартный (framework message_processor для system channel)
- [ ] Worker `data_receiver` блокируется на data-очереди, emit Qt signals через DataReceiverBridge
- [ ] topology `phase4_gui.yaml` с `process_class` проходит `blueprint.check()`
- [ ] Окно PySide6 открывается и graceful shutdown
- [ ] Тесты: `pytest multiprocess_prototype/frontend/tests/test_gui_process.py`

**Out of scope:** MainWindow с табами, виджеты, registers — это Task 4.2+
**Edge cases:**
- Qt event loop блокирует main thread — `should_stop()` проверяется через QTimer(1s) safety
- Если процесс убит (SIGKILL) — Qt не получит aboutToQuit; worker threads прервутся автоматически
- DataReceiverBridge emit из worker thread — Qt гарантирует queued connection для cross-thread signals
**Dependencies:** нет

---

### Task 4.2 — MainWindow + табы + Camera View

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Создать MainWindow с QTabWidget, вкладка CameraView отображает кадры из SHM ring-buffer

**Context:**
MainWindow — центральный виджет с табами. Первый таб — CameraView: отображение BGR-кадров,
получаемых через IPC (frame_ready → read SHM). Паттерн MVP: CameraPresenter управляет CameraView.
Нужен также StatusBar с fps/latency.

**Files:**
- `multiprocess_prototype/frontend/windows/__init__.py` — создать
- `multiprocess_prototype/frontend/windows/main_window.py` — создать MainWindow
- `multiprocess_prototype/frontend/widgets/__init__.py` — создать
- `multiprocess_prototype/frontend/widgets/camera/__init__.py` — создать
- `multiprocess_prototype/frontend/widgets/camera/view.py` — CameraView (QLabel + pixmap)
- `multiprocess_prototype/frontend/widgets/camera/presenter.py` — CameraPresenter
- `multiprocess_prototype/frontend/app.py` — обновить: создать MainWindow вместо заглушки
- `multiprocess_prototype/frontend/process.py` — обновить poll_messages: dispatch frame_ready

**Steps:**
1. Создать `windows/main_window.py`:
   - `MainWindow(QMainWindow)` с QTabWidget central widget
   - Метод `add_tab(widget, title)` для динамического добавления табов
   - StatusBar с QLabel для fps и latency
   - Метод `update_status(fps: float, latency_ms: float)`
   - Метод `update_frame(frame: np.ndarray | None)` → делегирует в CameraView

2. Создать `widgets/camera/view.py`:
   - Protocol `ICameraView`: `update_pixmap(pixmap: QPixmap)`, `set_placeholder(text: str)`
   - `CameraView(QWidget)` реализует ICameraView
   - QLabel с QPixmap, масштабирование AspectRatioMode.KeepAspectRatio
   - Конвертация BGR numpy → QImage → QPixmap (cv2 → RGB → QImage Format_RGB888)

3. Создать `widgets/camera/presenter.py`:
   - `CameraPresenter`:
     - `__init__(view: ICameraView)`
     - `on_frame(frame: np.ndarray)` — конвертация + view.update_pixmap()
     - `on_no_signal()` — view.set_placeholder("Нет сигнала")

4. Обновить `frontend/app.py`:
   - `run_gui()` создаёт MainWindow, CameraView, CameraPresenter
   - Регистрирует MainWindow в GuiProcess как `process._window = window`

5. Подключить signals в `frontend/app.py`:
   - `process.bridge.frame_received.connect(window.on_frame_received)`
   - `process.bridge.state_updated.connect(window.on_state_updated)`
   - Slot `on_frame_received(msg_dict)`: чтение из SHM → presenter.on_frame(frame)
   - FPS counter: инкремент в on_frame_received + QTimer(1000ms) для расчёта

6. Topology: обновить `phase4_gui.yaml` → добавить camera_0 процесс + wire → gui:
   ```yaml
   processes:
     - process_name: camera_0
       plugins:
         - plugin_class: ...CapturePlugin
           plugin_name: capture
           category: source
           camera_id: 0
     - process_name: gui
       process_class: multiprocess_prototype.frontend.process.GuiProcess
       plugins: []
   wires:
     - source: camera_0.capture.frame
       target: gui.display.frame
   ```
   Примечание: gui не имеет плагинов с портами, поэтому wire target придётся обработать иначе.
   **Решение:** GuiProcess подписывается на IPC-сообщение `frame_ready` напрямую (по data_type),
   wire для gui не нужен. Camera шлёт frame_ready адресно в gui (через targets в topology или hardcode).

   Итого topology:
   ```yaml
   processes:
     - process_name: camera_0
       plugins: [...]
     - process_name: gui
       process_class: multiprocess_prototype.frontend.process.GuiProcess
       plugins: []
   wires: []
   ```
   CapturePlugin уже шлёт `frame_ready` в `processor_{camera_id}`. Для GUI — изменить target
   в CapturePlugin config или добавить broadcast. **Проще**: в конфиге capture указать
   `target_process: gui` (override). Или GuiProcess слушает через router по channel "data".

   **Финальное решение**: GuiProcess в `poll_messages()` слушает все входящие data-сообщения.
   В topology camera_0.capture конфиг добавить параметр `frame_target: gui` (куда слать frame_ready).
   CapturePlugin уже использует `ctx.io.send_data(target, ...)` — просто изменить target из config.

7. Тесты: `multiprocess_prototype/frontend/tests/test_camera_view.py`
   - pytest-qt: CameraView отображает numpy frame (проверка pixmap не null)
   - CameraPresenter.on_frame() вызывает view.update_pixmap()

**Acceptance criteria:**
- [ ] MainWindow открывается с QTabWidget (вкладка "Camera")
- [ ] CameraView отображает BGR numpy frame через QPixmap
- [ ] StatusBar показывает fps (обновляется раз в секунду)
- [ ] MVP: CameraPresenter управляет CameraView через Protocol
- [ ] Тесты: `pytest multiprocess_prototype/frontend/tests/test_camera_view.py`

**Out of scope:** множественные камеры, mask overlay, recording indicator, watchdog
**Edge cases:**
- Нет кадров (camera не запущена) → placeholder "Нет сигнала"
- Frame resize (окно изменяет размер) → pixmap масштабируется с KeepAspectRatio
**Dependencies:** Task 4.1

---

### Task 4.3 — Topology Editor

**Level:** Senior+ (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** UI-виджет для визуального редактирования topology YAML: CRUD процессов/wires, валидация через blueprint.check(), выбор плагинов из PluginRegistry

**Context:**
Topology Editor — новая функциональность v2. Позволяет:
- Загружать/сохранять YAML topology файлы
- Добавлять/удалять процессы (с выбором плагинов из каталога PluginRegistry)
- Добавлять/удалять wire-связи (с autocomplete адресов портов)
- Валидировать чертёж (blueprint.check()) и показывать ошибки
- Применять topology к runtime (hot-reload — future, пока только save + restart)

SystemBlueprint уже имеет: model_validate(dict), check() → list[str], build_configs(), describe().
PluginRegistry.list() → все зарегистрированные плагины с inputs/outputs портами.

**Files:**
- `multiprocess_prototype/frontend/widgets/topology/__init__.py` — создать
- `multiprocess_prototype/frontend/widgets/topology/editor.py` — TopologyEditorWidget (главный)
- `multiprocess_prototype/frontend/widgets/topology/process_list.py` — ProcessListWidget (QListWidget)
- `multiprocess_prototype/frontend/widgets/topology/wire_list.py` — WireListWidget (QTableWidget)
- `multiprocess_prototype/frontend/widgets/topology/plugin_selector.py` — PluginSelectorDialog
- `multiprocess_prototype/frontend/widgets/topology/validation_panel.py` — ValidationPanel
- `multiprocess_prototype/frontend/widgets/topology/presenter.py` — TopologyPresenter (MVP)
- `multiprocess_prototype/frontend/windows/main_window.py` — обновить: добавить таб "Topology"

**Steps:**
1. Создать `widgets/topology/presenter.py` — TopologyPresenter (центральная логика):
   - Хранит текущий `SystemBlueprint` (in-memory)
   - `load_from_file(path: Path)` — yaml.safe_load → SystemBlueprint.model_validate()
   - `save_to_file(path: Path)` — model_dump() → yaml.dump()
   - `add_process(name: str, plugins: list[dict])` — добавить ProcessConfig
   - `remove_process(name: str)` — удалить + все связанные wires
   - `add_wire(source: str, target: str, description: str)` — добавить Wire
   - `remove_wire(index: int)`
   - `validate()` → list[str] (через blueprint.check())
   - `available_plugins()` → list[PluginEntry] (через PluginRegistry.list())
   - `available_ports(process_name: str, direction: "input"|"output")` → list[str] (адреса портов)
   - `get_blueprint_dict()` → dict (для отображения YAML preview)

2. Создать `widgets/topology/process_list.py` — ProcessListWidget:
   - QListWidget с процессами (имя + количество плагинов)
   - Кнопки: Add, Remove, Edit
   - Double-click → открыть PluginSelectorDialog для редактирования плагинов
   - Signal: `process_selected(name: str)`, `process_added()`, `process_removed(name: str)`

3. Создать `widgets/topology/wire_list.py` — WireListWidget:
   - QTableWidget: columns = [Source, Target, Description]
   - Кнопки: Add Wire, Remove Wire
   - При Add → QComboBox с доступными адресами (autocomplete из presenter.available_ports())
   - Signal: `wire_added(source, target)`, `wire_removed(index)`

4. Создать `widgets/topology/plugin_selector.py` — PluginSelectorDialog:
   - QDialog: доступные плагины из PluginRegistry (QListWidget с category группировкой)
   - Для каждого плагина: имя, category, описание, inputs/outputs
   - Выбор → добавить в процесс
   - Inline-редактор конфига: QFormLayout с полями из plugin_config defaults

5. Создать `widgets/topology/validation_panel.py` — ValidationPanel:
   - QTextEdit (read-only) для отображения ошибок валидации
   - Кнопка "Validate" → presenter.validate() → отобразить результат
   - Цветовая индикация: зелёный = OK, красный = ошибки

6. Создать `widgets/topology/editor.py` — TopologyEditorWidget:
   - QSplitter: слева ProcessListWidget + WireListWidget, справа ValidationPanel
   - Toolbar: Load YAML, Save YAML, Validate, New
   - QFileDialog для load/save
   - Связывает все sub-widgets через TopologyPresenter

7. Обновить `main_window.py`: добавить таб "Topology" → TopologyEditorWidget

8. Тесты: `multiprocess_prototype/frontend/tests/test_topology_editor.py`
   - Presenter: load YAML → validate → OK
   - Presenter: add_process + add_wire → validate
   - Presenter: remove_process → wires удалены
   - pytest-qt: TopologyEditorWidget отображается, load file работает

**Acceptance criteria:**
- [ ] TopologyEditorWidget отображается как таб в MainWindow
- [ ] Load YAML: файл → SystemBlueprint → отображение процессов и wires
- [ ] Save YAML: текущий blueprint → YAML файл
- [ ] Add/Remove Process: CRUD через UI, обновление списка
- [ ] Add/Remove Wire: выбор source/target из доступных портов
- [ ] Validate: blueprint.check() → отображение ошибок/OK
- [ ] Plugin Selector: отображение каталога из PluginRegistry.list()
- [ ] Тесты: `pytest multiprocess_prototype/frontend/tests/test_topology_editor.py`

**Out of scope:**
- Визуальный граф (node editor с drag-and-drop) — future
- Hot-reload topology без перезапуска
- Undo/Redo
**Edge cases:**
- YAML с синтаксической ошибкой → QMessageBox с ошибкой парсинга
- Плагин из topology не найден в PluginRegistry → warning в validation
- Дублирование имён процессов → ошибка validate
- Пустой topology (0 процессов) — допустим (для создания с нуля)
**Dependencies:** Task 4.2

---

### Task 4.4 — Registers Bridge (UI <-> Runtime State)

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Мост между GUI-виджетами и runtime-состоянием процессов: команды из UI → IPC, state updates → UI refresh

**Context:**
В v1 есть FrontendRegistersBridge + GuiStateProxy + RoutedCommandSender.
В v2 упрощаем: CommandPanel (UI) → GuiProcess → IPC send_data → target process → CommandManager.
State updates: процесс → IPC status/state → GuiProcess.poll_messages() → UI update.
Ключевые use cases:
- Кнопка "Start Capture" → команда start_capture → camera_0
- Кнопка "Stop Capture" → команда stop_capture → camera_0
- Process status (RUNNING/STOPPED/ERROR) → отображение в UI

**Files:**
- `multiprocess_prototype/frontend/widgets/controls/__init__.py` — создать
- `multiprocess_prototype/frontend/widgets/controls/command_panel.py` — CommandPanel
- `multiprocess_prototype/frontend/widgets/controls/process_status.py` — ProcessStatusWidget
- `multiprocess_prototype/frontend/bridge/__init__.py` — создать
- `multiprocess_prototype/frontend/bridge/command_sender.py` — CommandSender (обёртка IPC)
- `multiprocess_prototype/frontend/process.py` — обновить: dispatch команд и state updates
- `multiprocess_prototype/frontend/windows/main_window.py` — обновить: добавить таб "Controls"

**Steps:**
1. Создать `bridge/command_sender.py` — CommandSender:
   - `__init__(process: GuiProcess)` — ссылка на GuiProcess для отправки
   - `send_command(target_process: str, command: str, args: dict = {})`:
     - Формирует dict-сообщение: `{"type": "command", "data_type": command, "data": args}`
     - `process.send(target_process, message_dict)` через router
   - Простая обёртка без каталогов команд (в отличие от v1 RoutedCommandSender)

2. Создать `bridge/state_receiver.py` — StateReceiver:
   - `__init__()`
   - `on_message(msg_dict: dict)` — dispatch по data_type:
     - `"status"` → emit signal `status_changed(process_name, status)`
     - `"fps_update"` → emit signal `fps_updated(process_name, fps)`
   - QObject с Qt signals для thread-safe UI update
   - `subscribe(callback: Callable)` для виджетов

3. Создать `widgets/controls/command_panel.py` — CommandPanel:
   - QGroupBox с кнопками для управления камерой:
     - QPushButton "Start Capture" → command_sender.send_command("camera_0", "start_capture")
     - QPushButton "Stop Capture" → command_sender.send_command("camera_0", "stop_capture")
   - В будущем — динамическая генерация кнопок из plugin.commands

4. Создать `widgets/controls/process_status.py` — ProcessStatusWidget:
   - QGroupBox со списком процессов и их статусов
   - QTableWidget: columns = [Process, Status, PID]
   - Обновляется через StateReceiver signals
   - Цветовая индикация: RUNNING=зелёный, STOPPED=серый, ERROR=красный

5. Подключить bridge signals в `frontend/app.py`:
   - `process.bridge.state_updated.connect(status_widget.on_state_updated)`
   - `process.bridge.command_response.connect(command_panel.on_response)`
   - StateReceiver из отдельного файла не нужен — DataReceiverBridge уже классифицирует и emit'ит

6. Обновить `main_window.py`: таб "Controls" → QWidget с CommandPanel + ProcessStatusWidget

7. Тесты: `multiprocess_prototype/frontend/tests/test_bridge.py`
   - CommandSender.send_command() формирует корректный dict
   - StateReceiver.on_message() emit signal для status
   - pytest-qt: CommandPanel click → send_command вызван
   - ProcessStatusWidget обновляется при status_changed signal

**Acceptance criteria:**
- [ ] CommandPanel: кнопки Start/Stop Capture отправляют команды через IPC
- [ ] ProcessStatusWidget: отображает статусы процессов (обновляется real-time)
- [ ] CommandSender: формирует корректные dict-сообщения для router
- [ ] StateReceiver: Qt signals для thread-safe dispatch в виджеты
- [ ] Таб "Controls" в MainWindow
- [ ] Тесты: `pytest multiprocess_prototype/frontend/tests/test_bridge.py`

**Out of scope:**
- Полный каталог команд (как GUI_COMMAND_CATALOG в v1)
- Динамическая генерация UI из plugin.commands
- StateStore / GuiStateProxy (v2 использует прямой IPC, без глобального state tree)
- Registers / FrontendRegistersBridge (v1 legacy)
**Edge cases:**
- Команда отправлена, но target процесс не запущен → timeout/no response (не блокировать UI)
- Множественные status updates за один poll cycle → обработать все
- GUI закрыт до получения ответа → не crash (weak ref на window)
**Dependencies:** Task 4.2

---

## Risks and constraints

- **Qt main thread constraint:** GuiProcess.run() блокирует main thread OS-процесса. Это нормально — framework ожидает это в `_run_lifecycle()` (while loop после run() проверяет stop_event).
  `_run_lifecycle` после `process.run()` уходит в while-loop. Если `run()` = `app.exec()` (блокирует), то while-loop не выполнится. **Решение**: GuiProcess.run() после app.exec() сразу ставит `self._stop_requested = True` — process_runner увидит should_stop() и завершится.
- **Worker thread + Qt signals:** DataReceiverBridge emit из worker thread. Qt гарантирует queued connection для cross-thread signals (AutoConnection = Queued если sender/receiver в разных потоках). Это thread-safe без дополнительных lock'ов.
- **Блокирующий receive в worker:** timeout=0.1 обеспечивает что worker проверяет stop_event каждые 100ms. Не будет зависания при shutdown.
- **ProcessConfig.process_class:** минимальное изменение фреймворка. Нужен 1 тест на новое поле в blueprint тестах.
- **PluginRegistry state:** discover() вызывается в main процессе. В дочернем GUI-процессе реестр пуст. **Решение**: PluginRegistry — module-level dict, discover() при import. Или GUI-процесс делает свой discover(). Для Task 4.3 GUI должен иметь доступ к PluginRegistry.list() — вызвать discover() в GuiProcess._init_application_threads().
- **SHM в GUI-процессе:** Для чтения кадров из SHM нужен MemoryManager. ProcessModule уже имеет self.memory_manager. Проверить что он инициализирован для GuiProcess (в v1 работает).
