# Inspector Bottles — Полная техническая спецификация прототипа

> **Назначение документа:** Обратный промпт-инженеринг `multiprocess_prototype/`.
> Описание достаточно детальное, чтобы разработчик (или агент) мог воспроизвести систему один-в-один.
> Редактируйте этот файл, чтобы описать **как должно быть** — затем агенты реализуют по нему.

---

## 1. Общая идея

Многопроцессная система инспекции дефектов бутылок через камеру.
Каждый функциональный блок (камера, обработка, рендеринг, БД, робот, GUI) —
**отдельный процесс ОС**, общающийся через IPC-очереди и SharedMemory.

Фреймворк (`multiprocess_framework/`) предоставляет базовые классы и модули.
Прототип (`multiprocess_prototype/`) — конкретное приложение поверх фреймворка.

---

## 2. Дерево файлов и назначение

```
multiprocess_prototype/
├── run.py                          # Bootstrap: находит venv, запускает main.py
├── main.py                         # Точка входа: профиль → blueprint → SystemLauncher
├── __init__.py
│
├── config/                         # Конфигурация приложения
│   ├── app.py                      # AppConfig (Pydantic), build_cameras_from_profile()
│   ├── settings_profile.py         # SettingsProfile — валидация YAML-профиля
│   └── __init__.py
│
├── templates/
│   └── default_system.py           # build_default_blueprint() — SystemBlueprint
│
├── state_store/
│   └── bootstrap.py                # build_initial_state() — начальное дерево StateStore
│
├── data/                           # Статические данные
│   ├── config.json                 # Дефолтный конфиг (legacy)
│   ├── settings_profiles.yaml      # Профили: camera_count, ring_buffer_size и т.д.
│   ├── settings_recipes.yaml       # Рецепты обработки (ROI + chain)
│   ├── processing_catalog.yaml     # Каталог операций (color_detection, blob и т.д.)
│   └── db/inspector.db             # SQLite для результатов детекции
│
├── backend/                        # Процессы и инфраструктура
│   ├── processes/                  # 7 процессов (+ ProcessManager)
│   │   ├── process_manager/        # Оркестратор (наследует ProcessManagerProcess)
│   │   ├── camera/                 # Захват кадров
│   │   ├── processor/              # Обработка (vision pipeline)
│   │   ├── processor_worker/       # Воркер для распределённых chain-шагов
│   │   ├── renderer/               # Визуализация (наложение масок, bbox)
│   │   ├── gui/                    # PySide6 GUI (polling IPC)
│   │   ├── database/               # SQLite persistence
│   │   └── robot/                  # Управление роботом (заглушка)
│   │
│   ├── plugins/                    # Legacy-плагины (старый формат)
│   ├── routing/                    # frame_router_setup, throttle_middleware
│   ├── shm/                        # ring_buffer, cleanup, registry
│   ├── workers/                    # recorder_worker
│   └── helpers.py                  # message_as_dict()
│
├── plugins/                        # Новые плагины (ProcessModulePlugin)
│   ├── cameras/camera_service/     # CameraServicePlugin
│   ├── services/processor_service/ # ProcessorServicePlugin
│   ├── services/processor_worker/  # ProcessorWorkerPlugin
│   ├── rendering/renderer_service/ # RenderPlugin
│   ├── database/sqlite_storage/    # DatabasePlugin
│   ├── hardware/robot_control/     # RobotPlugin
│   ├── image_processing/color_mask/# ColorMaskPlugin
│   ├── ml/                         # ML-плагины (будущее)
│   └── manager.py                  # PluginManager (auto-discovery)
│
├── services/                       # Бизнес-логика (framework-agnostic)
│   ├── camera/                     # CameraService + CameraOutputPort
│   ├── processor/                  # ProcessorService + chain/ + worker_pool/
│   ├── renderer/                   # RendererService
│   ├── database/                   # DatabaseService
│   ├── gui/                        # GuiService
│   ├── robot/                      # RobotService
│   └── metrics/                    # LatencyTracker
│
├── registers/                      # Pydantic-схемы параметров (SchemaBase)
│   ├── boot.py                     # Boot values для процессов
│   ├── camera/                     # CameraRegisters, policy, hikvision_params
│   ├── processor/                  # ProcessorRegisters, processings/, catalog/
│   ├── renderer/                   # RendererRegisters, presets
│   ├── display/                    # DisplayRegisters, presets, transform
│   ├── pipeline/                   # rect, region, widget_bridge
│   ├── payloads/                   # crop_regions, post_processing
│   ├── settings/                   # AppSettingsRegisters
│   ├── commands/                   # GUI_COMMAND_CATALOG, routing
│   ├── sources/                    # topology_commands, converters
│   └── system_topology/            # topology_adapter, converters
│
├── frontend/                       # GUI (PySide6)
│   ├── app_context.py              # AppContext — расшаренное состояние
│   ├── actions/                    # ActionBus + handlers + persistence
│   ├── managers/                   # access_context, camera_registry, yaml_store
│   ├── widgets/                    # ~209 файлов — виджеты PySide6
│   │   ├── base/                   # Базовые компоненты, editor/, cards_field_factory/
│   │   ├── chrome/                 # Хром: header, side_panels, watchdog, recording
│   │   ├── tabs_setting/           # Вкладки: sources, recipes, display, processing
│   │   ├── pipeline/               # Вкладка pipeline (DAG-редактор)
│   │   ├── settings/               # Вкладка настроек
│   │   ├── sources/                # display_window (отдельное окно)
│   │   └── coordinators/           # Координация виджетов
│   └── bridges/
│       └── topology_bridge.py      # UI ↔ топология
│
└── tests/unit/                     # Юнит-тесты
```

---

## 3. Запуск системы (последовательность)

### 3.1 Bootstrap (`run.py`)

1. Ищет `.venv/` в корне проекта
2. Перезапускает себя через правильный Python-интерпретатор
3. Вызывает `main.py`

### 3.2 Инициализация (`main.py`)

```
1. _load_profile()
   → SettingsYamlStore читает data/settings_profiles.yaml
   → SettingsProfile.model_validate(profile_dict)
   → Результат: camera_count, ring_buffer_size, worker_pool_size, camera_source_type

2. _build_camera_dicts(profile)
   → build_cameras_from_profile(count, source_type, ring_buffer_size)
   → Результат: list[dict] — конфиги камер

3. build_default_blueprint(cameras, worker_pool_size)
   → SystemBlueprint("default_inspection")
   → Добавляет ProcessConfig для каждого процесса:
      - camera_N × camera_count
      - processor_N × camera_count
      - renderer × 1
      - database × 1
      - robot × 1
      - processor_worker_K × worker_pool_size

4. _ensure_plugins_registered()
   → PluginRegistry.discover(plugins/, backend/plugins/)

5. blueprint.check() — валидация

6. cleanup_stale_shm(shm_names) — очистка старых SHM-сегментов

7. SystemLauncher(orchestrator_class_path=ProcessManagerProcessApp, config=...)
   → launcher.run() — блокирующий запуск
```

### 3.3 Оркестратор (`ProcessManagerProcessApp.initialize()`)

```
1. _setup_topology_manager()
   → TopologyManager + topology_adapter (diff + commands)

2. _setup_state_store()
   → StateStoreManager + ValidationMiddleware + ThrottleMiddleware
   → build_initial_state(app_config) → начальное дерево

3. _register_builtin_commands()
   → Встроенные команды фреймворка

4. _create_processes_from_config()
   → Для каждого процесса в blueprint:
      → Process(ProcessModule subclass) с конфигом
      → Запуск как отдельный процесс ОС
```

### 3.4 Инициализация дочернего процесса

```
Каждый ProcessModule:
  1. _init_configuration()   → get_config() из ConfigStore
  2. _init_queues()          → RouterManager (каналы IPC)
  3. _init_managers()        → Logger, Command, Worker managers
  4. _init_communication()   → подписка на каналы
  5. _init_application_threads() → создание доменных воркеров
  6. run()                   → главный цикл
```

---

## 4. Процессы и их роли

### 4.1 ProcessManagerProcessApp (оркестратор)

| Параметр | Значение |
|----------|----------|
| Наследует | `ProcessManagerProcess` (framework) |
| Роль | Запуск/остановка детей, StateStore-сервер, TopologyManager |
| Потоки | Основной (управление) |
| IPC входящие | Все команды от GUI, state.set/get от всех процессов |
| IPC исходящие | Команды управления процессами, state.changed события |

**StateStore-сервер** — централизованное дерево состояния:
- Принимает `state.set`, `state.merge`, `state.get`, `state.subscribe` через IPC
- Рассылает `state.changed` подписчикам (delta-only)
- Middleware: ValidationMiddleware (границы значений), ThrottleMiddleware (частота)

### 4.2 CameraProcess (camera_N)

| Параметр | Значение |
|----------|----------|
| Наследует | `ProcessModule` |
| Роль | Захват кадров → SHM ring-buffer → IPC "frame_ready" |
| Потоки | `capture_worker` (LOOP) |
| SHM запись | `camera_{id}_frame` (ring buffer, K слотов) |
| IPC входящие | 14 команд: `set_camera_type`, `start_capture`, `stop_capture`, `enum_devices`, `set_fps`, `set_resolution`, `set_device_id` и др. |
| IPC исходящие | `frame_ready` → processor_N; `status`, `fps_update`, `error` → gui |
| StateProxy | Подписка: `cameras.{id}.config.*`; Запись: `cameras.{id}.state.*` |

**Типы камер:** simulator, webcam, hikvision, file

**Ring buffer:**
- K слотов (default 3), round-robin запись
- Каждый слот = numpy array (H×W×3, BGR)
- IPC-сообщение содержит `shm_index` (0..K-1) и `seq_id` (монотонный счётчик)

### 4.3 ProcessorProcess (processor_N)

| Параметр | Значение |
|----------|----------|
| Наследует | `ProcessModule` |
| Роль | Vision pipeline: детекция цвета/блобов по ROI-регионам |
| Потоки | `processing_worker` (LOOP) |
| SHM чтение | `camera_{id}_frame` |
| SHM запись | `processor_{id}_mask` |
| IPC входящие | `frame_ready` (от camera); `set_color_range`, `set_min_area`, `set_max_area` |
| IPC исходящие | `detection_result` → renderer; `db.save_detections` → database; `reject_item` → robot |
| StateProxy | Подписка: `cameras.{id}.regions.*` (пересборка chain при смене рецепта) |

**Vision pipeline:**
- Для каждого ROI-региона создаётся `ChainRunnable` (DAG операций)
- Операции из каталога: `color_detection`, `blob_detection`, `resize`, `threshold`, `clahe` и т.д.
- Опционально: `CrossProcessStep` → отправка в `processor_worker_K` через `WorkerPoolDispatcher`

### 4.4 ProcessorWorkerProcess (processor_worker_K)

| Параметр | Значение |
|----------|----------|
| Наследует | `ProcessModule` |
| Роль | Параллельное выполнение тяжёлых chain-шагов |
| Потоки | `task_worker` (LOOP) |
| IPC входящие | `worker_task_request` (от processor) |
| IPC исходящие | `worker_task_response` (обратно в processor) |
| SHM | `worker_{k}_result` (запись результата) |

### 4.5 RendererProcess (renderer)

| Параметр | Значение |
|----------|----------|
| Наследует | `ProcessModule` |
| Роль | Композитинг: оригинал + маска + bbox + контуры |
| Потоки | `render_worker` (LOOP) |
| SHM чтение | `camera_{id}_frame`, `processor_{id}_mask` |
| SHM запись | `renderer/rendered_frame` |
| IPC входящие | `detection_result` (от всех processor-ов) |
| IPC исходящие | `rendered_frame_ready` → gui |

### 4.6 GuiProcess (gui)

| Параметр | Значение |
|----------|----------|
| Наследует | `ProcessModule` |
| Роль | PySide6 GUI, polling IPC каждые 16мс |
| Потоки | `gui_poller` (LOOP), Qt event loop |
| SHM чтение | `renderer/rendered_frame` |
| IPC входящие | `rendered_frame_ready`, `status`, `error`, `fps_update`, `parameters_response`, `camera_type_changed`, `enum_devices_response` |
| IPC исходящие | Все пользовательские команды → соответствующим процессам |

**Handler map:**
```python
_HANDLER_MAP = {
    "rendered_frame_ready": _handle_rendered_frame,
    "status":               _handle_status,
    "error":                _handle_error,
    "fps_update":           _handle_fps,
    "parameters_response":  _handle_parameters,
    ...
}
```

**GuiStateProxy** — Qt-safe вариант StateProxy:
- Callbacks через `QMetaObject.invokeMethod(..., QueuedConnection)`
- Не блокирует GIL

### 4.7 DatabaseProcess (database)

| Параметр | Значение |
|----------|----------|
| Наследует | `ProcessModule` |
| Роль | SQLite persistence (batch-buffered) |
| IPC входящие | `db.save_detections`, `db.query`, `db.aggregate` |
| Модель | `DetectionSchema` (ORM) |

### 4.8 RobotProcess (robot)

| Параметр | Значение |
|----------|----------|
| Наследует | `ProcessModule` |
| Роль | Управление роботом (заглушка) |
| IPC входящие | `reject_item` |

---

## 5. IPC и передача данных

### 5.1 Принцип Dict at Boundary

Между процессами передаются **только dict** (pickle-safe).
Pydantic-модели используются **внутри** процесса, на границе — `model_dump()`.

### 5.2 Трёхуровневая передача сообщений

```
Отправитель:
  Service → MessageAdapter → RouterManager → AsyncSender → Channel.send(msg.to_dict())

Транспорт:
  multiprocessing.Queue (SRM)

Получатель:
  AsyncReceiver.poll() → recv_middleware → message_dispatcher → CommandManager/Handler
```

### 5.3 Типы сообщений

| Тип | Назначение |
|-----|-----------|
| `COMMAND` | Команда с аргументами → `CommandManager.dispatch()` |
| `DATA` | Данные (кадр, детекция) → зарегистрированный handler |
| `EVENT` | Событие (state.changed) → подписчики |
| `LOG` | Лог → LoggerManager |
| `SYSTEM` | Системные (heartbeat, shutdown) |
| `BROADCAST` | Широковещательные (frame routing) |

### 5.4 Маршруты кадров

```
camera_0 → "frame.camera_0" (broadcast) → [processor_0] + опционально [display, recorder]
camera_1 → "frame.camera_1" (broadcast) → [processor_1]
```

Настройка: `backend/routing/frame_router_setup.py`

### 5.5 Основной data flow

```
camera_N  ──frame_ready──►  processor_N  ──detection_result──►  renderer  ──rendered_frame_ready──►  gui
                                │                                                                      
                                ├──db.save_detections──►  database
                                └──reject_item──────────►  robot
```

### 5.6 SharedMemory (SHM) регионы

| Регион | Владелец (Writer) | Читатели | Формат | Размер |
|--------|-------------------|----------|--------|--------|
| `camera_{id}_frame` | camera_N | processor_N, renderer | Ring Buffer (K слотов) | H×W×3×K |
| `processor_{id}_mask` | processor_N | renderer | Single slot | H×W×1 |
| `renderer/rendered_frame` | renderer | gui | Single slot | H×W×3 |
| `worker_{k}_result` | processor_worker_K | processor_N | Single slot | Variable |

**FrameShmMiddleware** — middleware на RouterManager:
- Отправитель кладёт ссылку на SHM-слот (`shm_index`, `shm_name`)
- Получатель читает numpy array напрямую из SharedMemory

---

## 6. StateStore — централизованное состояние

### 6.1 Дерево состояния (bootstrap)

```json
{
  "cameras": {
    "0": {
      "config": {
        "type": "simulator",
        "device_index": 0,
        "fps": 30,
        "resolution_width": 640,
        "resolution_height": 480
      },
      "state": {
        "status": "stopped",
        "actual_fps": 0.0,
        "is_capturing": false,
        "frame_count": 0
      },
      "regions": {}
    }
  },
  "renderer": { "config": {...}, "state": {...} },
  "database": { "config": {...}, "state": {...} },
  "robot":    { "config": {...}, "state": {...} },
  "display":  { "config": {...}, "state": {...} },
  "gui":      { "state": {"status": "initialized"} }
}
```

### 6.2 StateProxy (клиент в каждом процессе)

```python
# Чтение
value = state_proxy.get("cameras.0.config.fps")
subtree = state_proxy.get_subtree("cameras.0")

# Запись (асинхронная, через IPC)
state_proxy.set("cameras.0.state.actual_fps", 29.5)
state_proxy.merge("cameras.0.config", {"fps": 60, "resolution_width": 1280})

# Подписка (glob-паттерны)
state_proxy.subscribe("cameras.0.config.*", callback=on_config_changed)
state_proxy.subscribe("cameras.*.state.*", callback=on_any_camera_state)
```

### 6.3 Middleware

**ValidationMiddleware:**
```python
{
    "cameras.*.config.fps":              {"min": 1, "max": 60},
    "cameras.*.config.resolution_width": {"min": 320, "max": 4096},
}
```

**ThrottleMiddleware:**
```python
{
    "cameras.*.state.actual_fps": 1.0,       # макс 1 Hz
    "processor.*.state.detections_count": 2.0 # макс 2 Hz
}
```

---

## 7. Система плагинов

### 7.1 ProcessModulePlugin паттерн

```python
class CameraServicePlugin(ProcessModulePlugin):
    name = "capture"
    category = "source"
    inputs = []
    outputs = ["frame"]
    
    def configure(self, ctx: PluginContext) -> None:   # IDLE → READY
    def start(self, ctx: PluginContext) -> None:       # READY → RUNNING
    def shutdown(self, ctx: PluginContext) -> None:     # RUNNING → IDLE
```

### 7.2 Каталог плагинов

| Плагин | Категория | Путь | Назначение |
|--------|-----------|------|-----------|
| CameraServicePlugin | source | plugins/cameras/camera_service/ | Захват кадров |
| ProcessorServicePlugin | processing | plugins/services/processor_service/ | Vision pipeline |
| ProcessorWorkerPlugin | processing | plugins/services/processor_worker/ | Worker pool |
| RenderPlugin | output | plugins/rendering/renderer_service/ | Визуализация |
| DatabasePlugin | storage | plugins/database/sqlite_storage/ | Persistence |
| RobotPlugin | hardware | plugins/hardware/robot_control/ | Робот |
| ColorMaskPlugin | processing | plugins/image_processing/color_mask/ | Цветовая маска |

### 7.3 Auto-discovery

```python
PluginRegistry.discover(proto_root / "plugins", proto_root / "backend/plugins")
# Ищет plugin.py в поддиректориях
# Регистрирует через @register_plugin декоратор
```

---

## 8. Vision Pipeline (Chain)

### 8.1 Операции из каталога

Файл: `data/processing_catalog.yaml`

| Операция | Категория | Входы | Выходы |
|----------|-----------|-------|--------|
| color_detection | Detect | image | detections, mask |
| blob_detection | Detect | image | detections, mask |
| resize | Transform | image | image |
| threshold | Transform | image | mask |
| clahe | Transform | image | image |
| blur | Transform | image | image |
| color_convert | Transform | image | image |
| region_splitter | ROI | image | image[] |

### 8.2 Построение pipeline

```python
# ProcessorService.process_frame():
for region in regions:
    chain = GraphRunnableBuilder.build(
        pipeline_data=region["pipeline"],
        catalog=operation_catalog,
        router=router_manager  # для cross-process steps
    )
    result = chain.invoke(ChainContext(
        camera_id=camera_id,
        seq_id=seq_id,
        frame=frame_slice  # ROI-вырезка
    ))
```

### 8.3 Cross-process dispatch (Phase 5c)

```python
# Тяжёлые шаги отправляются в worker pool:
dispatcher = WorkerPoolDispatcher(
    worker_targets=["processor_worker_0", "processor_worker_1"],
    router=router_manager
)
result = dispatcher.dispatch_task(WorkerTaskRequest(
    node="detector",
    frame_ref="camera_0_frame_0",
    metadata={...}
))
```

---

## 9. GUI (PySide6)

### 9.1 Иерархия окна

```
MainWindow (QMainWindow, 1280×720 min)
├── AppHeaderWidget (заголовок + кнопки Undo/Redo)
├── QHBoxLayout (контент)
│   ├── CollapsibleSidePanel (левая: "Дисплеи")
│   ├── ImagePanelWidget (центр: отображение кадров)
│   └── CollapsibleSidePanel (правая: "Статусы")
├── TabWidget (вкладки)
│   ├── RecipesWidget ("Рецепты")
│   ├── PipelineTabWidget ("Pipeline" — DAG-редактор)
│   ├── ProcessesTabWidget ("Процессы")
│   ├── ConstructorTabWidget ("Конструктор")
│   ├── SourcesTabWidget ("Источники" — камеры + топология)
│   └── SettingsTabWidget ("Настройки")
└── StatusBar (latency, resolution, undo/redo)
```

### 9.2 ActionBus

Внутренняя система событий GUI:

```python
action_bus = ActionBus()
action_bus.subscribe("UpdateChainAction", chain_handler)
action_bus.subscribe("SetFieldAction", field_set_handler)
action_bus.publish(SetFieldAction(register="camera", field="fps", value=60))
```

**Handlers:**
- `chain_handler` — изменения chain/pipeline
- `display_handler` — дисплей
- `field_set_handler` — установка значений полей
- `recipe_handler` — загрузка/сохранение рецептов
- `region_handler` — ROI-регионы
- `profile_handler` — профили настроек
- `graph_handler` — граф обработки
- `topology_handler` — топология системы

### 9.3 Persistence (Action Log)

```
persistence/
├── log_writer.py   — append-only журнал действий
├── recovery.py     — восстановление при запуске (replay)
├── repository.py   — репозиторий состояния
├── rotation.py     — ротация логов
└── schema_ext.py   — расширенные схемы
```

### 9.4 Managers (frontend)

| Manager | Роль |
|---------|------|
| `AppContext` | Расшаренное состояние GUI |
| `AccessContext` | Контроль доступа |
| `CameraRegistry` | Регистрация/обнаружение камер |
| `SettingsYamlStore` | Чтение/запись YAML-настроек |

---

## 10. Registers (схемы параметров)

### 10.1 Основные регистры

| Регистр | Путь | Ключевые поля |
|---------|------|---------------|
| `CameraRegisters` | registers/camera/schemas.py | fps, resolution, device_id, camera_type |
| `ProcessorRegisters` | registers/processor/schemas.py | color_lower/upper, min_area, max_area, vision_pipeline, crop_regions |
| `RendererRegisters` | registers/renderer/schemas.py | show_mask, show_bbox, overlay_alpha |
| `DisplayRegisters` | registers/display/schemas.py | display_mode, presets |
| `AppSettingsRegisters` | registers/settings/schemas.py | camera_count, ring_buffer_size, worker_pool_size |

### 10.2 FieldRouting (связка GUI → процесс)

```python
class CameraRegisters(SchemaBase):
    fps: int = Field(30, routing=FieldRouting(
        channel="camera_channel",
        process_targets=["CameraProcess"]
    ))
```

Изменение поля через GUI → RegistersManager → FieldRouting → IPC-сообщение → процесс.

### 10.3 Command Catalog

```python
# registers/commands/catalog.py
GUI_COMMAND_CATALOG = {
    "start_capture":  {"targets": ["camera_N"], "args": {}},
    "stop_capture":   {"targets": ["camera_N"], "args": {}},
    "set_fps":        {"targets": ["camera_N"], "args": {"fps": int}},
    "set_color_range":{"targets": ["processor_N"], "args": {"lower": list, "upper": list}},
    ...
}

# registers/commands/routing.py
resolve_command_targets(command_name, camera_id) → list[str]
```

---

## 11. Конфигурация

### 11.1 settings_profiles.yaml

```yaml
version: 1
current_profile: default
profiles:
  default:
    camera_count: 1
    ring_buffer_size: 3
    shm_budget_mb: 512
    workers_per_processor: 2
    display_count: 2
    camera_source_type: simulator
```

### 11.2 processing_catalog.yaml

```yaml
operations:
  - type_key: color_detection
    name: "Цветовая детекция"
    category: "Detect"
    params_schema: "registers.processor.processings.color_detection.ColorDetectionParams"
    module_path: "services.processor.operations.color_detection_op.ColorDetectionOp"
    input_ports: [{name: "in", data_type: "image"}]
    output_ports: [{name: "detections", data_type: "detections"}, {name: "mask", data_type: "mask"}]
```

### 11.3 Иерархия конфигурации (приоритет)

1. `ConfigStore` (dict в SRM) — shared at startup
2. `settings_profiles.yaml` — профиль пользователя
3. Environment variables — fallback
4. Process launch dict — per-process конфиг

---

## 12. Сервисы (бизнес-логика)

Каждый ProcessModule оборачивает Service + OutputPort (Protocol):

### 12.1 Паттерн

```python
# Port (Protocol — интерфейс)
class CameraOutputPort(Protocol):
    def send_frame_to_processor(self, data: dict) -> None: ...
    def write_frame_to_shm(self, frame: np.ndarray) -> None: ...

# Service (бизнес-логика, framework-agnostic)
class CameraService:
    def __init__(self, output: CameraOutputPort):
        self._output = output
    
    def capture_and_publish(self):
        frame = self._backend.read()
        self._output.write_frame_to_shm(frame)
        self._output.send_frame_to_processor({"camera_id": self._id, "seq_id": self._seq})

# Adapter (мост Service ↔ IPC)
class CameraAdapter(CameraOutputPort):
    def __init__(self, router: RouterManager, shm_writer: RingBufferWriter):
        self._router = router
        self._shm = shm_writer
    
    def send_frame_to_processor(self, data):
        self._router.send(Message(type=DATA, targets=["processor_N"], data=data))
    
    def write_frame_to_shm(self, frame):
        self._shm.write(frame)
```

### 12.2 Сервисы

| Сервис | Ключевые методы |
|--------|-----------------|
| CameraService | `start_capture()`, `stop_capture()`, `switch_camera_type()`, `set_fps()`, `enumerate_devices()` |
| ProcessorService | `process_frame()`, `set_color_range()`, `rebuild_runnables()` |
| RendererService | `render_frame()` |
| DatabaseService | `save_detections()`, `query()` |
| RobotService | `move()`, `pick()`, `place()` |
| GuiService | `handle_frame()`, `send_command()` |

---

## 13. TopologyManager (динамическая топология)

### 13.1 Структура

```json
{
  "sources": {
    "cameras": {
      "0": {
        "config": {...},
        "regions": {
          "roi_1": {"name": "ROI 1", "rect": [x,y,w,h], "nodes": {...}}
        }
      }
    }
  },
  "processes": {
    "camera_0": {...},
    "processor_0": {...},
    "renderer": {...}
  },
  "displays": {
    "display_0": {"config": {...}}
  }
}
```

### 13.2 Diff & Commands

```python
# Сравнение текущей и желаемой топологии
diff = system_diff_fn(current_topology, desired_topology)
# → {has_changes, source_diff, process_diff, display_diff}

# Генерация команд из diff
commands = system_commands_fn(diff)
# → [AddRegion(...), RemoveProcess(...), ModifyDisplay(...)]
```

---

## 14. Дефолтные значения (hardcoded)

| Параметр | Значение | Где |
|----------|----------|-----|
| Разрешение | 640×480 | camera, processor, renderer configs |
| Ring buffer K | 3 | settings_profiles.yaml |
| Color range (lower) | [0, 0, 150] BGR | registers/processor/constants.py |
| Color range (upper) | [100, 100, 255] BGR | registers/processor/constants.py |
| Min area | 500 px | registers/processor/constants.py |
| Max area | 50000 px | registers/processor/constants.py |
| GUI poll interval | 16 ms | gui/process.py |
| Watchdog timeout | 3 sec | gui/process.py |
| Workers per processor | 2 | settings_profiles.yaml |
| SHM budget | 512 MB | settings_profiles.yaml |

---

## 15. Завершение работы (Shutdown)

```
1. Ctrl+C (SIGINT) или SIGTERM
2. ProcessSpawner signal handler
3. stop_event.set() (per-process)
4. Каждый ProcessModule:
   - Workers видят should_stop() → graceful exit
   - RouterManager.AsyncReceiver прекращает polling
   - shutdown()
   - thread.join(timeout=5)
5. ProcessManagerProcess:
   - ProcessMonitor прекращает heartbeat
   - ProcessRegistry.stop_all()
   - Финальный state broadcast
6. cleanup_stale_shm() через atexit
```

---

## 16. Известные ограничения и TODO

1. **Worker task broadcasting** — все воркеры получают все задачи (Task 9.7 добавит фильтрацию по process_id)
2. **Ring buffer коллизии** — нет явной синхронизации при wraparound, полагается на seq_id
3. **SHM утечки при crash** — `atexit` не гарантирует очистку при kill -9
4. **Recipe validation** — нет явной валидации схемы рецепта перед применением
5. **DisplayWindow lifecycle** — окна создаются on-demand, не очищаются при смерти процесса
6. **Robot** — заглушка, реального управления нет
7. **CollapsibleSidePanel** — "Дисплеи" и "Статусы" помечены как TODO
8. **StatusBar** — часть статусов не реализована
