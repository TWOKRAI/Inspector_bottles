# Архитектура Inspector Prototype v2

## Обзор

Inspector v2 — это config-driven конструктор для систем технического зрения. YAML-файл topology описывает чертёж системы (процессы, плагины, цепочки), фреймворк автоматически собирает многопроцессную архитектуру с IPC, общей памятью (SHM) и GUI.

**Ключевой принцип:** Dict at Boundary — между процессами только словари (pickle-safe), Pydantic схемы используются внутри процесса.

## Поток данных (простой пример: hello_world)

```
CameraServicePlugin (camera_0)
  └─ read camera → frame: ndarray (640, 480, 3)
     └─ send IPC msg: {"channel": "data", "owner": "camera_0", "data": {...}}
        └─ SHM write: frame_shm[slot_0] = frame
           └─ IPC send (to gui): frame_ready{owner, slot, seq_id}

GuiProcess (gui)
  └─ receive IPC: frame_ready
     └─ SHM read: frame = shm[slot_0]
        └─ ImagePanel.update(frame)
           └─ Qt repaint
```

Сложнее (inspection_basic):

```
CameraServicePlugin → SHM[camera_0] + IPC(frame_ready)
     ↓
ColorMaskPlugin (processor) [Data Worker] reads SHM[camera_0], writes SHM[processor]
     ↓ IPC(frame_ready)
BlobDetectorPlugin (processor) [Chain Worker] reads SHM[processor]
     ↓ (list[dict] → plugin.process() → list[dict])
RenderOverlayPlugin (renderer) [Chain Worker] reads SHM[processor], writes SHM[renderer]
     ↓ IPC(frame_ready)
GuiProcess → SHM[renderer] + ImagePanel.update()
```

## Архитектура процессов

```
SystemLauncher (основной процесс)
  ├── ProcessManagerProcess (оркестратор)
  │     ├── GenericProcessApp (camera_0) — source process
  │     │     └── 3 worker'а:
  │     │           ├── System Worker: handle stop/pause/resume
  │     │           ├── Data Worker: receive IPC (frame_ready), SHM read, InspectorManager
  │     │           └── Chain Worker: plugin.process(), SHM write, IPC send
  │     │
  │     ├── GenericProcessApp (processor) — processing process
  │     │     └── 3 worker'а (идентичны camera_0)
  │     │
  │     ├── GenericProcessApp (renderer) — rendering process
  │     │     └── 3 worker'а (идентичны)
  │     │
  │     └── GuiProcess (gui) — Qt event loop
  │           ├── QApplication + MainWindow
  │           ├── 7 tabs (settings, recipes, processes, ...)
  │           ├── TopologyBridge (commands → IPC)
  │           └── GuiStateBindings (state → widgets)
```

## Внутри GenericProcessApp

Каждый процесс = `ProcessModule` (из фреймворка) + плагины. Наследует менеджеры:

```
ProcessModule
  ├── LoggerManager (scope: SYSTEM / BUSINESS / PERFORMANCE)
  ├── ErrorManager (severity: WARNING / ERROR / CRITICAL → отдельные файлы)
  ├── StatsManager (метрики: COUNTER, GAUGE, TIMING, HISTOGRAM)
  ├── RouterManager (IPC message routing by channel)
  ├── CommandManager (обработка команд: start, pause, resume, ...)
  └── WorkerManager (пулинг потоков внутри процесса)
```

Все менеджеры используют `ObservableMixin` для логирования:

```python
class MyWorker:
    def __init__(self, logger=None):
        self._logger = logger  # LoggerManager

    def run(self):
        # Внутри worker'а вызываешь методы через DI-логгер
        if self._logger:
            self._logger.info("что-то произошло", module="my_worker")
```

Если в ProcessModule:

```python
class GenericProcessApp(ProcessModule):
    def run(self):
        # Можно напрямую через ObservableMixin
        self._log_info("процесс стартует", module="generic")
        self._record_metric("startup.time", 123)
        self._track_error(exc, context={"handler": "frame_ready"})
```

## Data Pipeline (внутри процесса)

Каждый GenericProcessApp имеет три worker'а:

### 1. System Worker
Обработка команд: start, stop, pause, resume, shutdown.

```python
def run(self):
    while not self.stop_event.is_set():
        msg = self.router.receive(channel_types=['system'])
        if msg:
            cmd = msg["command"]
            if cmd == "stop":
                break
            elif cmd == "pause":
                self.pause_event.set()
            elif cmd == "resume":
                self.pause_event.clear()
```

### 2. Data Worker
Читает IPC-сообщения (frame_ready, region_ready), выполняет SHM-read и буферизацию.

```python
def run(self):
    while not self.stop_event.is_set():
        if self.pause_event.is_set():
            time.sleep(0.01)
            continue

        # Получить сообщение frame_ready от upstream процесса
        msg = self.router.receive(channel_types=['data'])
        if msg:
            owner, slot, seq_id = msg["owner"], msg["slot"], msg["seq_id"]

            # SHM middleware: read frame → dict
            frame = self.mm.read_images(owner, shm_name, shm_index)
            item = {
                "frame": frame,
                "timestamp": msg.get("timestamp"),
                "seq_id": seq_id,
            }

            # InspectorManager буферизирует по seq_id (для fan-in)
            self.inspector_mgr.add_item(item)

            # Когда полная коллекция готова
            items = self.inspector_mgr.get_ready_items()
            if items:
                self.data_queue.put(items)
```

### 3. Chain Worker
Выполняет `plugin.process(items)`, пишет результат в SHM, отправляет IPC.

```python
def run(self):
    while not self.stop_event.is_set():
        if self.pause_event.is_set():
            time.sleep(0.01)
            continue

        # Получить готовые items из data_queue
        try:
            items = self.data_queue.get(timeout=0.1)
        except queue.Empty:
            continue

        # Выполнить плагины (цепочка)
        for plugin in self.plugins:
            items = plugin.process(items)

        # SHM write: items → frame
        for item in items:
            frame = item["frame"]
            slot = self.mm.alloc_slot(owner, shm_name)
            self.mm.write_images(owner, slot, [frame], 0)

            # IPC send to chain_targets
            for target in self.chain_targets:
                self.router.send({
                    "channel": "data",
                    "target": target,
                    "owner": self.process_name,
                    "slot": slot,
                    "seq_id": item["seq_id"],
                })
```

## GUI архитектура (PySide6)

### Структура окна

```
┌─────────────────────────────────────────┐
│ AppHeaderWidget (60px) — бренд + статус │
├─────────────────────────────────────────┤
│ ErrorBannerWidget (динамическая высота) │
├─────────────────────────────────────────┤
│                                         │
│  ImagePanelWidget (stretch)             │
│  └─ live preview camera feed            │
│                                         │
├─────────────────────────────────────────┤
│ QTabWidget (7 табов)                    │
│  ├─ Settings — YAML editor topology     │
│  ├─ Recipes — Save/load/apply presets   │
│  ├─ Processes — Monitor + start/stop    │
│  ├─ Services — Camera/DB/Robot config   │
│  ├─ Plugins — Параметры processing      │
│  ├─ Pipeline — DAG editor (граф + палит │
│  └─ Displays — Управление экранами      │
├─────────────────────────────────────────┤
│ StatusBar: FPS | Latency | Process CPU% │
└─────────────────────────────────────────┘
```

### Паттерны

#### 1. MVP (Model-View-Presenter)

Каждый таб = Presenter (чистый Python) + View (Qt виджеты):

```python
# frontend/widgets/tabs/plugins/presenter.py
class PluginsPresenter:
    def __init__(self):
        self.plugins = []

    def load_plugins(self, plugin_list):
        self.plugins = plugin_list
        return [
            {"name": p.name, "category": p.category, "state": p.state}
            for p in plugin_list
        ]

    def set_plugin_param(self, plugin_name: str, param: str, value):
        # Pure logic, no Qt
        plugin = next((p for p in self.plugins if p.name == plugin_name), None)
        if plugin:
            plugin.config[param] = value
            return True
        return False

# frontend/widgets/tabs/plugins/tab.py
class PluginsTab(QWidget):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self._presenter = PluginsPresenter()
        self._ctx = ctx

        self._table = QTableWidget()
        self._param_spinbox = QSpinBox()
        self._param_spinbox.valueChanged.connect(self._on_param_changed)

    def _on_param_changed(self, value):
        # Qt event → Presenter → commands → IPC
        plugin_name = self._get_current_plugin()
        param_name = self._param_spinbox.objectName()

        if self._presenter.set_plugin_param(plugin_name, param_name, value):
            # Send IPC command
            self._ctx.command_sender.send_field_set(
                target="processor",
                field=f"plugins.{plugin_name}.{param_name}",
                value=value,
            )
```

#### 2. AppServices + RuntimeDeps (DI без контейнера-обёртки)

> **G.5 (cross-tab-architecture):** монолитный `AppContext`/`ctx.extras` удалён.
> Composition root (`app.py:run_gui`) держит зависимости локальными переменными
> (живы весь lifetime — `app.exec()` блокирует) и собирает два явных DI-контейнера:
> **AppServices** (editor-state: каталоги/реестры/команды) и **RuntimeDeps**
> (runtime-layer: IPC-мосты, bindings, callbacks). Табы получают `(services, runtime)`.

```python
# Composition root (app.py)
app_services = build_app_services(AppServicesDeps(
    event_bus=event_bus, topology_store=topology_store,
    plugin_registry=PluginRegistry, display_registry=display_registry,
    service_registry=service_registry, registers_manager=registers_mgr,
    config={}, recipe_manager=recipe_manager, auth_state=auth_state,
))
runtime = RuntimeDeps(
    command_sender=command_sender, topology_bridge=topology_bridge,
    bindings=bindings, plugin_manager=plugin_manager,
    registers_manager=registers_mgr, auth_ctx=auth_ctx,
    request_ui_restart=lambda: ...,  # узкий callback для InterfaceSection
)
tab_factory = TabFactory(app_services, auth_ctx=auth_ctx, runtime=runtime,
                         custom_factories=register_all_tabs())

# Использование в табах: фабрика create(services, runtime)
class MyTab(QWidget):
    @classmethod
    def create(cls, services: AppServices, runtime: RuntimeDeps):
        # services.topology / services.commands / services.plugins — editor-state
        # runtime.command_sender — IPC; runtime.registers_manager — live-регистры
        # runtime.bindings — реактивные подписки
        return cls(services, runtime=runtime)
```

#### 3. ActionBus (Undo/Redo)

```python
class SettingsTab(QWidget):
    def __init__(self, ctx):
        self._bus = ctx.action_bus

    def _on_yaml_edit(self, new_yaml):
        # Создать действие
        action = EditTopologyAction(old=self.current_yaml, new=new_yaml)

        # Выполнить и добавить в очередь Undo
        self._bus.execute(action)

        # Пользователь нажал Ctrl+Z
        # → action.undo() → revert YAML
        # Пользователь нажал Ctrl+Y
        # → action.redo() → apply YAML
```

#### 4. GuiStateBindings (реактивные подписки)

```python
bindings = ctx.bindings()

# Синхронизация: state_store.processes[camera_0].fps → label.text
bindings.bind(
    path="processes.camera_0.state.fps",
    widget=fps_label,
    property="text",
    formatter=lambda fps: f"{fps:.1f} fps",
)

# Обратный поток: user edits spinbox → command_sender → process
bindings.bind_reverse(
    path="plugins.color_mask.threshold",
    widget=threshold_spinbox,
    property="value",
    debounce_ms=50,
)
```

#### 5. TopologyBridge (GUI ↔ Runtime)

```
GUI edit: YAML in SettingsTab
    ↓
TopologyBridge.diff() — что изменилось
    ↓
CommandCatalog — какие команды нужны
    ↓
CommandValidator — валидация перед отправкой
    ↓
CommandSender — debounce (50ms) + отправка IPC
    ↓
ProcessModule receives: field_set("plugins.color_mask.threshold", 120)
    ↓
Plugin.configure({"threshold": 120})

---

Обратный поток: Process state updated
    ↓
StateStore.set({processes.camera_0.state.fps: 29.5})
    ↓
bridge.set_state_callback({...delta...})
    ↓
GuiStateBindings.apply_delta()
    ↓
bindings.bind(...) — refresh widgets
```

## Менеджеры фреймворка (5 основных)

### LoggerManager

```python
# В ProcessModule:
self._log_info("сообщение", module="generic")  # → $LOG_DIR/business.log
self._log_error("ошибка", module="worker_1")   # → $LOG_DIR/errors.log

# В чистом классе (DI):
class MyWorker:
    def __init__(self, logger=None):
        self._logger = logger

    def run(self):
        if self._logger:
            self._logger.info("работаю", module="my_worker")
```

**Scope-based routing:**
- `SYSTEM` → system.log (StartUp, Shutdown, процессы)
- `BUSINESS` → business.log (события приложения)
- `PERFORMANCE` → performance.log (метрики, FPS)
- все ошибки → errors.log (наследуют severity)

### ErrorManager

```python
# Автоматическое распределение по файлам
self._track_error(exc, context={"where": "frame_handler"})
# → WARNING → warnings.log
# → ERROR → errors.log
# → CRITICAL → critical.log
```

### StatsManager

```python
self._record_metric("camera_fps", 29.5)           # GAUGE
self._record_metric("frames_processed", 1)         # COUNTER (agregates)
self._record_metric("processing_time_ms", 12.3)   # TIMING
```

Агрегирует в окнах (1s, 10s, 60s) → отправляет в браузер StatsDashboard.

### RouterManager

```python
# Send message
self.router.send({
    "channel": "data",
    "target": "processor",
    "owner": "camera_0",
    "payload": {...},
})

# Receive with timeout
msg = self.router.receive(channel_types=['system'], timeout=0.1)
```

### CommandManager

```python
# Register handler
self.command_manager.register_handler("pause", self._on_pause)

# Receive command (в System Worker)
cmd = self.command_manager.receive(timeout=0.01)
if cmd:
    self.command_manager.execute(cmd)
```

## SHM (Shared Memory) Layout

```
SHM池:
  camera_0/
    └─ slot_0: frame (640×480×3, uint8) = 920KB
    └─ slot_1: frame (640×480×3, uint8) = 920KB
    └─ metadata: {owner, timestamp, seq_id, slots_in_use}

  processor/
    └─ slot_0: processed_frame (640×480×3, uint8) = 920KB
    └─ slot_1: ...

  renderer/
    └─ slot_0: rendered_frame (640×480×3, uint8) = 920KB
```

**Жизненный цикл:**
1. Process пишет: `mm.write_images(owner="camera_0", slot=0, [frame], 0)`
2. SHM получает: `data/camera_0/slot_0 = frame` + обновляет metadata
3. Downstream получает IPC: `{owner: "camera_0", slot: 0, seq_id: 123}`
4. Downstream читает: `frame = mm.read_images("camera_0", "data", 0)`
5. Когда больше не нужен: `mm.free_slot("camera_0", 0)`

## Topology YAML структура

```yaml
name: hello_world
description: "Описание системы"

processes:
  # Process definition (обязательные поля)
  - process_name: camera_0
    process_class: multiprocess_prototype.generic_process_app.GenericProcessApp
    priority: normal  # normal / high / low
    chain_targets: [gui]  # куда отправляет результаты
    source_target_fps: 10  # целевое FPS для source плагина

    # Плагины (отрезко выполняются в Chain Worker)
    plugins:
      - plugin_class: Plugins.sources.camera_service.plugin.CameraServicePlugin
        plugin_name: camera_service
        category: source
        # Параметры (dict → cfg.configure(params))
        camera_type: simulator
        camera_id: 0
        resolution_width: 640
        resolution_height: 480
        auto_start: true

  # GUI процесс (всегда последний)
  - process_name: gui
    process_class: multiprocess_prototype.frontend.process.GuiProcess
    plugins: []
```

## Запуск топологии

```python
# multiprocess_prototype/main.py
import yaml
from multiprocess_framework.processes.system_launcher import SystemLauncher

topology = yaml.safe_load(open("topology.yaml"))
launcher = SystemLauncher(topology)
launcher.run()  # Блокирующий вызов до shutdown
```

## Тестирование

### Unit-тесты плагинов

```python
# tests/test_my_plugin.py
def test_process_increases_brightness():
    plugin = MyPlugin()
    plugin.configure({"brightness": 50})

    # Мок-items
    items = [
        {
            "frame": np.ones((100, 100, 3), dtype=np.uint8) * 100,
            "timestamp": 0.0,
            "seq_id": 0,
        }
    ]

    result = plugin.process(items)
    assert len(result) == 1
    assert result[0]["frame"].mean() > 100  # Светлее
```

### Интеграционные тесты

```python
# tests/test_topology.py
def test_hello_world_topology():
    topology = yaml.safe_load(Path("topology/hello_world.yaml").read_text())

    launcher = SystemLauncher(topology)
    launcher.start()

    # Дождаться запуска (check processes alive)
    time.sleep(1.0)

    # Отправить команду
    launcher.send_command("camera_0", {"command": "pause"})

    # Проверить, что обработка остановилась
    assert launcher.get_process_state("camera_0").paused

    launcher.shutdown()
```

## Производительность и оптимизация

1. **SHM pool resizing:** Если памяти не хватает, фреймворк автоматически расширяет pool
2. **Worker debouncing:** CommandSender дебаунсирует изменения параметров (50ms)
3. **Fan-out через worker_pool:** Для параллельной обработки нескольких регионов
4. **State aggregation:** StatsManager агрегирует метрики в окнах (избегаем шума)

## Для быстрого понимания

Читай в таком порядке:
1. **README.md** — Quick start
2. **hello_world.yaml** — Минимальный пример
3. **inspection_basic.yaml** — Pipeline с обработкой
4. **generic_process_app.py** — Внутренняя логика процесса
5. **frontend/app.py** — Инициализация GUI
6. **frontend/widgets/tabs/plugins/tab.py** — Пример таба (MVP паттерн)
7. **multiprocess_framework/docs/MODULES_OVERVIEW.md** — Фреймворк (менеджеры, контракты)
