# SYSTEM_SPEC.md — Inspector Bottles

> Реверс-промтинг документ. Читать перед любой задачей в `multiprocess_prototype/`.
> Последнее обновление: 2026-05-01.

---

## 1. Архитектура

### 1.1 Карта процессов

| Процесс | Модуль | Роль | Ключевые IPC-команды |
|---------|--------|------|----------------------|
| `ProcessManager` | `backend/processes/process_manager/` | Оркестратор: запускает дочерние процессы, хранит StateStore | `process.start`, `process.stop`, `process.restart`, `process.create`, `system.shutdown` |
| `camera_N` (N = 0..K) | `backend/processes/camera/` | Захват кадров с одной камеры → SHM ring-buffer | `start_capture`, `stop_capture`, `set_fps`, `set_camera_type`, `enum_devices`, `open`, `close`, `set_parameters` |
| `processor_N` | `backend/processes/processor/` | Обработка кадров: детекция, chain runnables, ROI | `set_color_range`, `set_min_area`, `set_max_area` |
| `processor_worker_N` | `backend/processes/processor_worker/` | Воркер пула: исполняет operation из каталога над SHM-кадром | (получает задачи через IPC от `processor`) |
| `renderer` | `backend/processes/renderer/` | Объединяет оригинал + маску → rendered_frame → SHM | `set_show_original`, `set_show_mask`, `set_draw_contours`, `set_draw_bboxes` |
| `robot` | `backend/processes/robot/` | Отбраковка: принимает detection_result → физическое действие | `reject_item` |
| `database` | `backend/processes/database/` | Запись детекций в SQLite/PostgreSQL (batch + flush) | `db.save_detections`, `db.query`, `db.flush` |
| `gui` | `backend/processes/gui/` | GUI-процесс: PySide6 event loop, polling сообщений | (отправляет все команды выше; получает `rendered_frame_ready`) |

**Важно:** `gui` — единственный источник пользовательских команд. Остальные процессы только слушают.

### 1.2 Поток данных

```
Камера (физическая / симулятор / файл)
    │
    ▼
CameraProcess [camera_N]
    │  capture_and_publish()
    │  frame → resize → SHM ring-buffer (camera_N_frame, слоты 0..K-1)
    │  IPC msg: "frame_ready" data_type → processor_N
    ▼
ProcessorProcess [processor_N]   ←── StateProxy: cameras.N.regions (ROI дерево)
    │  receive_message → FrameShmMiddleware читает кадр из SHM
    │  service.process_frame()
    │  chain runnables (per-region) → ColorBlobDetector / CV-операции
    │  маска → SHM (processor_N_mask)
    │  IPC msg: "detection_result" → renderer
    │  IPC cmd: "db.save_detections" → database
    ▼
RendererProcess [renderer]
    │  читает original из SHM camera_N_frame (по camera_id из msg)
    │  читает маску из SHM processor_N_mask
    │  RendererService.render_frame() → composite frame
    │  composite → SHM (renderer/rendered_frame)
    │  IPC msg: "rendered_frame_ready" → gui
    ▼
GuiProcess [gui]
    │  _handle_new_frame()
    │  читает rendered_frame из SHM renderer/rendered_frame
    │  MainWindow.update_frame()
    │  LatencyTracker: e2e latency = gui_ts - capture_ts
    ▼
MainWindow / DisplayRouter → виджеты PySide6
```

Параллельные ветки:
- `detection_result` → `RobotProcess` (если настроен `reject_item`)
- `detection_result` → `DatabaseProcess` (`db.save_detections`)

### 1.3 IPC контракты

| Команда / data_type | Отправитель | Получатель | Payload |
|---------------------|-------------|------------|---------|
| `frame_ready` | `camera_N` | `processor_N` | `{frame_id, capture_ts, shm_index, camera_id}` |
| `detection_result` | `processor_N` | `renderer`, `database`, `robot` | `{camera_id, frame_id, detections, shm_index, mask_shm_actual_name, mask_shm_index}` |
| `rendered_frame_ready` | `renderer` | `gui` | `{frame_id, shm_index, show_original, show_mask, capture_ts}` |
| `start_capture` | `gui` | `camera_N` | `{}` |
| `stop_capture` | `gui` | `camera_N` | `{}` |
| `set_fps` | `gui` | `camera_N` | `{fps: int}` |
| `set_camera_type` | `gui` | `camera_N` | `{camera_type: str}` |
| `enum_devices` | `gui` | `camera_N` | `{max_index: int, backend?: str}` |
| `set_color_range` | `gui` | `processor_N` | `{color_lower: [B,G,R], color_upper: [B,G,R]}` |
| `set_min_area` / `set_max_area` | `gui` | `processor_N` | `{min_area: int}` / `{max_area: int}` |
| `set_show_original` | `gui` | `renderer` | `{show_original: bool}` |
| `set_draw_contours` | `gui` | `renderer` | `{draw_contours: bool}` |
| `db.save_detections` | `processor_N` | `database` | `{detections: list[dict]}` |
| `reject_item` | `processor_N` или `renderer` | `robot` | `{frame_id, defects: list}` |
| `process.start/stop/restart` | `gui` | `ProcessManager` | `{process_name: str}` |
| `process.create` | `gui` | `ProcessManager` | `{process_name, class_path, config, priority}` |
| `shm_region_changed` | `ProcessManager` | `camera_N`, `processor_N`, `renderer` | `{region_name, new_width, new_height, camera_id}` |
| `state.set` | любой процесс | `ProcessManager` (StateStore) | `{path: str, value: Any}` |
| `state.changed` | `ProcessManager` | все подписчики | `{deltas: [{path, new_value, old_value}]}` |

**Правило routing команд из GUI:** `registers/commands/routing.py` — `resolve_command_targets(command_id)` возвращает список имён процессов-получателей.

### 1.4 Три системы данных

#### ConfigStore (запуск)
- **Что это:** Pydantic-конфиг `AppConfig` — собирается один раз до старта процессов.
- **Файлы:** `config/app.py` (`AppConfig`), `config/settings_profile.py` (`SettingsProfile`), `config/shm_region.py`.
- **Lifecycle:** создаётся в `main.py` → сериализуется в `dict` → передаётся в `SystemLauncher` → дочерние процессы читают через `process.get_config("config")`.
- **Когда использовать:** инициализация процессов, размеры SHM, тип камеры по умолчанию, количество воркеров.
- **Правило:** между процессами только `dict` (`model_dump()` или `to_dict()`). Pydantic-объекты только внутри одного процесса.

#### Registers (UI-схемы)
- **Что это:** Pydantic-схемы с `FieldMeta` и `FieldRouting` — описывают параметры для виджетов.
- **Файлы:** `registers/__init__.py`, `registers/camera/`, `registers/processor/`, `registers/renderer/`, `registers/sources/`, `registers/processing/`, `registers/settings/`.
- **Lifecycle:** создаются в `FrontendLauncher.build_registers()` → `RegistersManager` → привязываются к виджетам и StateStore через `RegistersStateAdapter`.
- **Когда использовать:** хранение текущих значений UI-параметров; `FieldRouting` определяет в какой процесс уходит изменение поля.
- **Правило:** каждое поле регистра несёт `FieldMeta` с routing-аннотацией — именно по ней `RegistersManager` определяет target-процесс.

#### StateStore (runtime)
- **Что это:** централизованное дерево состояния в `ProcessManager` — живёт всё время работы.
- **Файлы:** `state_store/bootstrap.py` (начальное дерево), `state_store/adapters/` (адаптеры для GUI), `backend/processes/process_manager/state_store_config.py` (middleware-правила).
- **Lifecycle:** `build_initial_state(app_config_dict)` → `StateStoreManager.initialize()` → процессы пишут через `StateProxy.set(path, value)` → подписчики получают `state.changed` с дельтами.
- **Когда использовать:** runtime-статус процессов (`status`, `actual_fps`), конфиг камеры/процессора в runtime, передача ROI-регионов.
- **Дерево состояния:**
  ```
  cameras.{id}.config.*     — параметры камеры
  cameras.{id}.state.*      — runtime статус (status, actual_fps, drops_count)
  cameras.{id}.regions.*    — ROI-регионы (заполняются из рецепта)
  processor.{id}.config.*   — параметры процессора
  processor.{id}.state.*    — runtime статус
  renderer.config.*         — параметры рендерера
  renderer.state.*
  robot.state.*
  database.state.*
  gui.state.*
  system.status
  ```

---

## 2. Доменная модель

### 2.1 Camera domain

| Слой | Файл | Что делает |
|------|------|------------|
| Config | `backend/processes/camera/config.py` — `CameraConfig` | ProcessLaunchConfig: camera_id, camera_type, fps, resolution, ring_buffer_size, SHM layout |
| Process | `backend/processes/camera/process.py` — `CameraProcess` | Инфраструктура: RingBufferWriter, FrameShmMiddleware, StateProxy, capture_worker |
| Commands | `backend/processes/camera/commands.py` | `build_command_table` — 14 команд; `build_state_config_handlers` — 11 полей |
| Adapter | `backend/processes/camera/adapter.py` — `CameraAdapter` | Реализует `CameraOutputPort`: write_to_shm, send_frame_ready |
| Service | `services/camera/service.py` — `CameraService` | Бизнес-логика: смена backend, захват, FPS throttle, Hikvision-специфика |
| Backends | `services/camera/backends.py` | `SimulatorBackend`, `WebcamBackend`, `HikvisionBackend`, `FileSourceBackend` |
| Register | `registers/camera/schemas.py` — `GuiCameraRegisters` | Поля для UI: camera_type, fps, resolution, device_id, Hikvision params |
| Policy | `registers/camera/policy.py` | `CAMERA_TYPES`, `SUPPORTS_ENUM`, `SUPPORTS_HARDWARE_HANDOFF` |
| Widget | `frontend/widgets/sources/camera_common/`, `frontend/widgets/sources/hikvision_camera_mvp/` | UI-виджеты камеры |
| State adapter | `state_store/adapters/camera_state_adapter.py` — `CameraStateAdapter` | Подписка на `cameras.*.state.**` → callback для виджетов |

### 2.2 Processor domain

| Слой | Файл | Что делает |
|------|------|------------|
| Config | `backend/processes/processor/config.py` | ProcessLaunchConfig: camera_id, resolution, workers_per_processor, worker_pool_size |
| Process | `backend/processes/processor/process.py` — `ProcessorProcess` | Инфраструктура: receive FrameShmMiddleware, send mask FrameShmMiddleware, StateProxy, processing_worker |
| Commands | `backend/processes/processor/commands.py` | `build_command_table`, `_apply_vision_pipeline` — применяет pipeline dict к сервису |
| Adapter | `backend/processes/processor/adapter.py` — `ProcessorAdapter` | `send_detection_to_renderer`, `send_detections_to_database`, `write_mask_to_shm` |
| Service | `services/processor/service.py` — `ProcessorService` | chain runnables, ColorBlobDetector, rebuild_runnables по ROI |
| Detection | `services/processor/detection.py` — `ColorBlobDetector` | OpenCV-детектор: color range + blob area |
| Chain | `services/processor/chain/` | `ChainRunnable`, `DAGRunnable`, `ChainThreadPool` — параллельное выполнение операций |
| Operations | `services/processor/operations/` | blur, clahe, color_convert, resize, threshold, blob_detection, color_detection, region_splitter |
| Catalog | `registers/processor/catalog/` | YAML-каталог операций: `ProcessingOperationDef`, `load_catalog()` |
| Register | `registers/processor/schemas.py` — `ProcessorRegisters` | Поля: color_lower/upper, min/max_area |
| Worker Process | `backend/processes/processor_worker/process.py` — `ProcessorWorkerProcess` | Отдельный процесс пула: получает задачу IPC → исполняет operation → возвращает результат |
| Worker Pool | `services/processor/worker_pool/dispatcher.py` — `WorkerPoolDispatcher` | Диспетчер задач: отправляет задачи в `processor_worker_N`, ждёт ответ с timeout |
| Router topology | `services/processor/topology/builder.py` — `RouterTopology` | Граф процессов для cross-process выполнения chain шагов (Task 9.6) |

### 2.3 Renderer domain

| Слой | Файл | Что делает |
|------|------|------------|
| Config | `backend/processes/renderer/config.py` | ProcessLaunchConfig: output_dir, save_frames, draw_bboxes/contours |
| Process | `backend/processes/renderer/process.py` — `RendererProcess` | Инфраструктура: render_worker, StateProxy, динамическое чтение SHM по camera_id |
| Commands | `backend/processes/renderer/commands.py` | Генерирует команды из `SERVICE_FLAGS`: set_show_original, set_show_mask, set_draw_contours, set_draw_bboxes, set_save_frames |
| Adapter | `backend/processes/renderer/adapter.py` — `RendererAdapter` | Записывает rendered_frame в SHM, отправляет `rendered_frame_ready` в `gui` |
| Service | `services/renderer/service.py` — `RendererService` | Композит: original + mask + bboxes/contours; опционально сохраняет кадры |
| Drawing | `services/renderer/drawing.py` | Утилиты OpenCV: draw_bboxes, draw_contours |
| Register | `registers/renderer/schemas.py` — `RendererRegisters` | Поля: show_original, show_mask, draw_contours, draw_bboxes |
| Widget | `frontend/widgets/sources/display_window/` | Виджет отображения rendered_frame |
| Display routing | `frontend/bridges/topology_bridge.py` → `_apply_displays` | Lifecycle display-окон через `DisplayWindowManager` |

### 2.4 Database domain

| Слой | Файл | Что делает |
|------|------|------------|
| Config | `backend/processes/database/config.py` | db_url, db_dialect, batch_size, flush_interval_sec, schema_module_path |
| Process | `backend/processes/database/process.py` — `DatabaseProcess` | Инфраструктура: SQLManager lifecycle, создание таблицы через SchemaBaseMapper |
| Commands | `backend/processes/database/commands.py` | `db.save_detections`, `db.query`, `db.flush` |
| Adapter | `backend/processes/database/adapter.py` — `DatabaseAdapter` | Исполнение SQL через SQLManager |
| Service | `services/database/service.py` — `DatabaseService` | Batch-буферизация детекций: накопить → flush по таймеру или размеру |
| Schema | `services/database/schema.py` — `DetectionSchema` | Pydantic-схема строки БД: frame_id, camera_id, timestamp, defect_type, bbox |
| Action log | `backend/processes/database/action_log_setup.py` | Настройка таблицы лога действий (undo/redo persistence) |

### 2.5 Robot domain

| Слой | Файл | Что делает |
|------|------|------------|
| Config | `backend/processes/robot/config.py` | log_file, reject_delay |
| Process | `backend/processes/robot/process.py` — `RobotProcess` | Инфраструктура: robot_worker (слушает system-канал), StateProxy |
| Commands | `backend/processes/robot/commands.py` | `reject_item` — процесс отбраковки |
| Adapter | `backend/processes/robot/adapter.py` — `RobotAdapter` | Логирование действий, IPC feedback |
| Service | `services/robot/service.py` — `RobotService` | `process_rejection()`, счётчик `action_count`, `reject_delay` |

---

## 3. Файловая карта

### 3.1 Точки входа и конфигурация

| Файл | Что делает | Изменение требует |
|------|------------|-------------------|
| `run.py` | Авто-детект venv, re-exec, запуск `main.py` | — |
| `main.py` | Сборка `AppConfig`, запуск `SystemLauncher` | Добавление нового процесса → `AppConfig.all_process_configs()` |
| `config/app.py` — `AppConfig` | Список всех процессов, SHM-регионы, headless-режим | Новый тип процесса → добавить поле в `AppConfig` |
| `config/settings_profile.py` — `SettingsProfile` | Валидированный профиль настроек из YAML | Новый профильный параметр → добавить поле сюда |
| `config/shm_region.py` — `ShmRegionSpec` | Спецификация одного SHM-региона | — |
| `backend/processes/process_manager/process.py` | `ProcessManagerProcessApp`: StateStoreManager + TopologyManager | Смена middleware StateStore → `state_store_config.py` |
| `backend/processes/process_manager/state_store_config.py` | `ValidationMiddleware` правила + `ThrottleMiddleware` правила | Новое поле StateStore → добавить правило валидации |
| `state_store/bootstrap.py` — `build_initial_state` | Начальное дерево состояния из AppConfig | Новый раздел StateStore → добавить сюда ветку |

### 3.2 IPC и routing

| Файл | Что делает | Изменение требует |
|------|------------|-------------------|
| `registers/commands/routing.py` | Маппинг `command_id → [target_process_name]` | Новая GUI-команда → добавить в `COMMAND_TO_REGISTER_KEY` или `EXPLICIT_COMMAND_TARGETS` |
| `registers/commands/catalog.py` — `GUI_COMMAND_CATALOG` | Builders payload'а для каждой команды | Новая команда → добавить builder-функцию |
| `backend/routing/frame_router_setup.py` | Broadcast fan-out: `frame.camera_N` → подписчики | Новый подписчик кадров → `setup_frame_routes()` или `subscribe_to_camera()` |
| `backend/routing/throttle_middleware.py` | Throttle высокочастотных data-сообщений | Новый высокочастотный тип → добавить правило |
| `backend/shm/` (re-export из framework) | `RingBufferWriter`, `RingBufferReader` | — |
| `backend/shm/registry.py` | Реестр SHM-сегментов | — |
| `backend/shm/cleanup.py` | Очистка осиротевших SHM при старте | — |

### 3.3 Registers

| Файл | Что делает | Изменение требует |
|------|------------|-------------------|
| `registers/__init__.py` — `create_registers()` | Собирает все регистры в `RegistersManager` | Новый регистр → добавить здесь |
| `registers/camera/schemas.py` | `GuiCameraRegisters`, `BaseCameraRegisters`, `WebcamCameraRegisters`, `HikvisionCameraRegisters` | Новый параметр камеры → добавить поле с `FieldMeta` и routing |
| `registers/camera/policy.py` | `CAMERA_TYPES`, `SUPPORTS_ENUM` | Новый тип камеры → добавить в список |
| `registers/processor/schemas.py` | `ProcessorRegisters`: color_lower/upper, min/max_area | Новый параметр детектора → добавить поле |
| `registers/processor/processings.py` | `ProcessorParams`, `ColorDetectionParams`, `BlobDetectionParams` | Новый тип обработки → добавить dataclass |
| `registers/renderer/schemas.py` | `RendererRegisters`: show_original, show_mask, draw_* | Новый flag рендерера → добавить поле |
| `registers/sources/schemas.py` — `SourceTopology` | Layer 1: топология источников (камеры + регионы) | — |
| `registers/processing/schemas.py` — `ProcessingConfig` | Layer 2: pipeline обработки per-region | Новый тип узла → `registers/pipeline/processing_node.py` |
| `registers/pipeline/` | `ProcessingNode`, `Rect`, `Region`, схемы пайплайна | — |
| `registers/settings/schemas.py` | `AppSettingsRegisters`: camera_count, ring_buffer_size | — |
| `registers/system_topology/` | Схемы и адаптер для `SystemTopologyEditor` | — |

### 3.4 Services (бизнес-логика)

| Файл | Что делает | Изменение требует |
|------|------------|-------------------|
| `services/camera/service.py` | CameraService: захват, switch backend, FPS throttle | Новый backend → `services/camera/backends.py` |
| `services/camera/backends.py` | Backends: Simulator, Webcam, Hikvision, FileSource | Новый тип камеры → добавить класс-наследник `BaseCaptureBackend` |
| `services/processor/service.py` | ProcessorService: process_frame, rebuild_runnables | Новая операция → `services/processor/operations/` |
| `services/processor/operations/` | CV-операции: blur, clahe, threshold, resize, blob/color detection, roi | Новая CV-операция → добавить файл + регистрация в YAML-каталоге |
| `services/processor/chain/` | DAG/Chain runnables, ChainThreadPool | — |
| `services/processor/topology/builder.py` | `RouterTopology`: граф процессов для cross-process шагов | — |
| `services/renderer/service.py` | RendererService: composite кадр, save frames | — |
| `services/database/service.py` | DatabaseService: batch buffer, flush | Схема DetectionSchema → `services/database/schema.py` |
| `services/robot/service.py` | RobotService: reject logic | — |
| `services/metrics/latency.py` | `LatencyTracker`: e2e latency logging | — |

### 3.5 Frontend

| Файл | Что делает | Изменение требует |
|------|------------|-------------------|
| `frontend/launcher/__init__.py` — `FrontendLauncher` | Оркестратор frontend: config, registers, windows | — |
| `frontend/launcher/register_binder.py` | Подключает `RegistersStateAdapter` и `CameraStateAdapter` | — |
| `frontend/launcher/hooks_setup.py` | `build_domain_context`: AppFrontendContext, DisplayRouter, TopologyBridge | — |
| `frontend/launcher/ui_builder.py` | Фабрики окон: `make_main_window_factory`, `make_loading_window_factory` | — |
| `frontend/app_context.py` — `AppFrontendContext` | DI-контейнер: registers, recipe_manager, action_bus, topology_editor, topology_bridge | Новая зависимость в вкладках → добавить поле сюда |
| `frontend/windows/main_window/window.py` — `MainWindow` | QMainWindow: Header + ImagePanel + TabWidget | — |
| `frontend/windows/main_window/tab_factory.py` — `create_tab_widget_factory` | Фабрика вкладок: recipes, settings, sources, display, pipeline | Новая вкладка → добавить ветку здесь |
| `frontend/actions/bus.py` — `ActionBus` | Undo/redo bus (реэкспорт из framework) | — |
| `frontend/actions/schemas.py` — `AppActionType` | Все типы action: FIELD_SET, REGION_*, STEP_*, DISPLAY_*, PROFILE_SWITCH, RECIPE_SWITCH, GRAPH_*, TOPOLOGY_* | Новый тип действия → добавить сюда |
| `frontend/actions/default_bus_factory.py` | Сборка ActionBus со стандартными handlers | Новый тип action → зарегистрировать handler |
| `frontend/actions/handlers/` | Handlers: field_set, region, chain, display, profile, recipe, graph, topology | Новый handler → создать файл, зарегистрировать в default_bus_factory |
| `frontend/bridges/topology_bridge.py` — `TopologyBridge` | Координирует три транспорта при применении SystemTopology | — |
| `frontend/commands/__init__.py` — `GuiCommandHandler` | Отправка команд через `RoutedCommandSender` | — |
| `state_store/adapters/registers_adapter.py` | Подписывается на StateStore → обновляет RegistersManager | Новый регистр → добавить в `build_path_mapping()` |
| `state_store/adapters/camera_state_adapter.py` | Подписывается на cameras.*.state.** → callback виджетам | — |

---

## 4. Система конфигурации

### AppConfig (запуск системы)

```
main.py
  │ Строит AppConfig (Pydantic) из settings profile или явного конфига
  │ Вызывает model_dump() → dict  ← Dict at Boundary!
  ▼
SystemLauncher(orchestrator_config={"app_config": app_config_dict})
  │
  ▼
ProcessManagerProcessApp._setup_state_store()
    build_initial_state(app_config_dict)  → StateStore
ProcessManagerProcessApp._create_processes_from_config()
    AppConfig.all_process_configs() → список ProcessLaunchConfig
    Каждый ProcessLaunchConfig.build() → (process_name, proc_dict)
    Дочерний процесс: process.get_config("config") → dict
```

**AppConfig.all_process_configs()** возвращает в порядке: cameras + processors + [renderer] + robot + database + gui + worker_pool + topology_workers.

### Settings Profiles (профили настроек приложения)

- Файл: `config/settings_profile.py` — `SettingsProfile`
- Поля: `camera_count`, `ring_buffer_size`, `worker_pool_size`, `camera_source_type`
- Загружаются из YAML → `SettingsProfile.model_validate(yaml_dict)` → передаются в `build_cameras_from_profile()` для формирования `AppConfig.cameras`
- UI: `frontend/widgets/recipes/settings_profile_widget/`

### Recipes (рецепты обработки)

- Хранят снимок состояния регистров: `{register_name: {field_name: value}}`
- `RecipeManager` (`frontend/managers/`) — загрузка/сохранение рецептов
- Переключение через `ActionBus` с типом `RECIPE_SWITCH` → `RecipeSwitchHandler.apply()` → `rm.set_field_value()` для каждого поля
- StateStore: рецепт → `cameras.N.regions` (ROI-регионы) → `ProcessorProcess._on_regions_changed()` → `rebuild_runnables()`

### StateStore (runtime состояние)

- Создаётся **до** запуска дочерних процессов → готов принимать `state.set` с первых секунд
- `ThrottleMiddleware`: ограничивает частоту обновлений для `cameras.*.state.actual_fps`, `cameras.*.state.is_capturing` и аналогичных высокочастотных полей
- `ValidationMiddleware`: проверяет допустимые значения полей (правила в `state_store_config.py`)
- Дочерние процессы пишут только через `StateProxy.set(path, value)` — **никаких прямых обращений к словарю**
- GUI читает через `GuiStateProxy` (Qt-safe: доставляет дельты в main thread)

---

## 5. Frontend архитектура

### 5.1 Launcher flow

```
GuiProcess.run()
  └─ FrontendLauncher(process_ref, app_config)
       ├─ build_config()              → frontend_config dict
       ├─ build_registers()           → (RegistersManager, connection_map)
       └─ run_process_attached_frontend(process, hooks)
            ├─ QApplication создаётся
            ├─ FrontendManager инициализируется (registers, sender)
            ├─ hooks.register_windows(wm, fm, config, sender, app, process)
            │    ├─ setup_state_adapters()      ← RegistersStateAdapter + CameraStateAdapter
            │    ├─ build_domain_context()      ← AppFrontendContext, DisplayRouter, TopologyBridge
            │    ├─ make_main_window_factory()
            │    └─ register_all_windows()
            ├─ wm.show_window("loading")        ← LoadingWindow 2 сек
            ├─ QTimer → wm.show_window("main")  ← MainWindow
            └─ QTimer(16ms) → GuiProcess._poll_messages()
```

### 5.2 Иерархия виджетов

```
MainWindow (QMainWindow)
├── AppHeaderWidget (chrome/app_header)      — заголовок, кнопки undo/redo, навигация вкладок
├── ImagePanelWidget                          — вывод rendered_frame
├── WatchdogOverlay                           — overlay при потере кадров > 5 сек
└── TabWidget
    ├── "recipes"    → RecipesTabWidget       — управление рецептами и профилями
    ├── "settings"   → SettingsContainerWidget — настройки UI + profile manager
    ├── "sources"    → SourcesTabWidget        — топология камер и регионов ROI
    │   └─ CameraPanel → CameraCommonWidget / HikvisionCameraMvpWidget
    ├── "display"    → DisplayTabWidget        — управление display-окнами
    └── "pipeline"   → PipelineTabWidget      — визуальный редактор pipeline (DAG-нод)
```

### 5.3 Action Bus (undo/redo)

- `ActionBus` (фреймворк) — стек действий с `do()`, `undo()`, `redo()`.
- Каждое действие — `Action(action_id, action_type, forward_patch, backward_patch)`.
- Handlers: `FieldSetHandler`, `RegionActionHandler`, `ChainActionHandler`, `DisplayActionHandler`, `ProfileSwitchHandler`, `RecipeSwitchHandler`, `GraphActionHandler`, `TopologyActionHandler`.
- **Создание:** `create_default_action_bus(rm)` в `frontend/actions/default_bus_factory.py`.
- **Передача:** через `AppFrontendContext.action_bus` → все виджеты.
- **Persistence:** `frontend/actions/persistence/` — запись лога в БД, recovery при перезапуске.

### 5.4 Register binding

Цепочка: `RegistersManager.set_field_value(reg, field, value)` → `FieldRouting` → IPC команда в target-процесс **И** `RegistersStateAdapter` синхронизирует StateStore.

Обратный путь: StateStore изменился → `GuiStateProxy` доставляет дельту в main thread → `RegistersStateAdapter` обновляет `RegistersManager` → `RegistersManager` нотифицирует виджеты через subscription.

### 5.5 Display routing

- `DisplayRouter` — роутинг rendered_frame в display-окна по подписке.
- `DisplayWindowManager` — lifecycle display-окон (`create_window`, `destroy_window`, `list_windows`).
- `TopologyBridge._apply_displays()` — diff старого и нового состояния displays, вызывает `wm.create_window/destroy_window`.
- Подписка: `DisplayRouter.get_active_subscriptions()` → `GuiProcess._handle_new_frame()` диспатчит кадры в каждое активное display-окно.

---

## 6. Гайды по изменениям (САМОЕ ВАЖНОЕ)

### Добавить новый тип камеры

1. **Backend:** `services/camera/backends.py` — добавить класс, наследующий `BaseCaptureBackend`, реализовать `capture_frame()`, `start()`, `stop()`, `close()`.
2. **Policy:** `registers/camera/policy.py` — добавить строку в `CAMERA_TYPES`; если поддерживает `enum_devices` — в `SUPPORTS_ENUM`.
3. **Register schema:** `registers/camera/schemas.py` — если нужны специфичные поля — добавить подкласс `BaseCameraRegisters` (по аналогии с `HikvisionCameraRegisters`).
4. **CameraService:** `services/camera/service.py` — в `switch_camera_type()` добавить ветку создания нового backend через `create_camera_backend()`.
5. **Config:** `backend/processes/camera/config.py` — при необходимости добавить специфичные поля конфига.
6. **UI:** `frontend/widgets/sources/` — добавить виджет (или расширить `camera_common`).
7. **Catalog resolver:** `services/camera/backends.py` — `create_camera_backend()` factory.

### Добавить новую CV-операцию

1. **Service:** `services/processor/operations/` — создать файл (например `my_op.py`), наследовать `ProcessingOperation` из `operations/base.py`, реализовать `process(ctx: ChainContext) → ChainContext`.
2. **YAML-каталог:** `data/processing_catalog.yaml` — добавить запись с `operation_ref` (полный python-путь), описанием параметров.
3. **Register schema:** `registers/processor/processings.py` — добавить Pydantic-класс параметров (если нужны параметры в UI).
4. **Loader:** `services/processor/operations/loader.py` — убедиться, что `load_operation_class(operation_ref)` умеет импортировать новый класс (обычно автоматически).
5. **Tests:** `tests/` — добавить unit-тест операции.

### Добавить новый тип процесса

1. **Process dir:** `backend/processes/myprocess/` — создать файлы: `process.py` (класс `MyProcess(ProcessModule)`), `config.py` (`MyProcessConfig(ProcessLaunchConfig)`), `commands.py`, `adapter.py`, `__init__.py`, `__main__.py`.
2. **Service:** `services/myprocess/` — `service.py`, `ports.py`.
3. **AppConfig:** `config/app.py` — добавить поле `myprocess: MyProcessConfig = MyProcessConfig()` и включить в `all_process_configs()`.
4. **StateStore bootstrap:** `state_store/bootstrap.py` — добавить секцию в `build_initial_state()`.
5. **StateProxy:** в `process.py` создать `StateProxy("myprocess", ...)` и сделать начальную запись `myprocess.state.status = "initialized"`.
6. **IPC routing:** если процесс получает команды из GUI — добавить маппинг в `registers/commands/routing.py`.

### Изменить pipeline editor

1. **Визуальный DAG:** `frontend/widgets/pipeline/pipeline_tab/` — canvas, library, inspector, views, bridges.
2. **Схема узла:** `registers/pipeline/processing_node.py` — `ProcessingNode`.
3. **YAML-каталог:** `data/processing_catalog.yaml` — новые типы узлов.
4. **Chain builder:** `services/processor/chain/builder.py` — `GraphRunnableBuilder.build()`.
5. **Action типы:** `frontend/actions/schemas.py` — `GRAPH_*` action types; handlers в `frontend/actions/handlers/graph_handler.py`.
6. **Bridge:** `frontend/bridges/topology_bridge.py` — `_apply_pipeline()` пишет в `PROCESSING_REGISTER`.

### Добавить новый параметр в Register

1. **Schema:** Файл `registers/<domain>/schemas.py` — добавить поле с `FieldMeta` и `routing=<FieldRouting-константа>`.
2. **FieldRouting константа:** `registers/constants.py` (или `registers/<domain>/schemas.py`) — убедиться что `FieldRouting(channel=..., process_targets=(...))` корректен.
3. **Backend handler:** В `backend/processes/<domain>/commands.py` — добавить команду в `build_command_table()` и поле в `build_state_config_handlers()`.
4. **StateStore path:** При необходимости обновить `state_store/bootstrap.py` и правило валидации в `backend/processes/process_manager/state_store_config.py`.
5. **StateProxy mapping:** `frontend/launcher/register_binder.py` — `build_path_mapping()` автоматически строит mapping по `PREFIX_MAP`, но только для стандартных регистров.

### Добавить новый виджет в UI

1. **Widget:** `frontend/widgets/<domain>/my_widget/` — создать QWidget-класс.
2. **Вкладка:** `frontend/windows/main_window/tab_factory.py` — добавить ветку в `factory(widget_key, ...)` если виджет — новая вкладка.
3. **AppFrontendContext:** `frontend/app_context.py` — добавить поле если виджет требует новой зависимости.
4. **Domain context:** `frontend/launcher/hooks_setup.py` — `build_domain_context()` — передать новую зависимость в context.
5. **Config:** `frontend/configs/frontend_config.py` — добавить секцию UI-конфига если нужно.

### Изменить количество камер или воркеров

- `config/settings_profile.py` — `SettingsProfile.camera_count` или `worker_pool_size`.
- `config/app.py` — `AppConfig.model_post_init()` автоматически создаёт N `ProcessorConfig` по N `CameraConfig`.
- `config/app.py` — `AppConfig.worker_configs` автоматически создаёт N `ProcessorWorkerConfig`.
- `state_store/bootstrap.py` — `build_initial_state()` итерирует по `app_config["cameras"]` — никаких изменений не нужно.

### Сменить схему БД

1. `services/database/schema.py` — `DetectionSchema` — добавить/изменить поля.
2. `backend/processes/database/process.py` — `_init_custom_managers()` → `DatabaseService.build_create_table_sql()` — перестроится автоматически из новой схемы.
3. Если существующая БД — написать SQL-миграцию отдельно (нет автомиграции).

---

## 7. Инварианты и правила

### Dict at Boundary
Между процессами передаются **только `dict`**. Pydantic-объекты, numpy-массивы — только внутри одного процесса. Кадры (numpy) передаются через SHM, в IPC-сообщении только индекс слота.

### Register-driven UI
Каждый UI-параметр описан в Register-схеме с `FieldMeta` и `FieldRouting`. Виджеты не знают напрямую про процессы — они пишут в `RegistersManager`, который по `FieldRouting` отправляет IPC-команду.

### Именование процессов vs. IPC-каналов
**Имена процессов** (`camera_0`, `processor_0`, `renderer`, `gui`) — используются в `send_message(target=...)` и `RegistersManager`.
**Каналы Router** (`control_camera`, `control_processor`, `control_rendering`, `frame.camera_N`) — используются в `FieldRouting.channel`. Это разные пространства имён. Документация: `ROUTING_GLOSSARY.md`.

### Framework vs. Prototype boundary
`multiprocess_framework/` — инфраструктура: `ProcessModule`, `RouterManager`, `StateStoreManager`, `RegistersManager`, `ActionBus`, `SQLManager`. Изменения только если нужна инфраструктурная функциональность.
`multiprocess_prototype/` — приложение: бизнес-логика, register-схемы, виджеты, services. Все задачи по Inspector Bottles — только здесь.

### Thread safety
- `GuiProcess` работает в Qt main thread. `_poll_messages()` вызывается через `QTimer` — всё в одном потоке.
- `GuiStateProxy` (в отличие от `StateProxy`) доставляет дельты в Qt main thread через Qt signal.
- `CameraService` и `ProcessorService` — чистые сервисы, не потокобезопасны; к ним обращается только один воркер своего процесса.
- `ChainThreadPool` — внутренний thread pool внутри ProcessorProcess; `ChainRunnable` должны быть thread-safe по данным.

### Adapter pattern (Ports & Adapters)
Каждый сервис (`CameraService`, `ProcessorService`, ...) работает через Output Port (интерфейс в `ports.py`). Adapter реализует порт через `ProcessIO` (IPC + SHM facade). Это позволяет тестировать сервисы без запуска процессов.

### StateProxy — единственный способ писать в StateStore из дочерних процессов
Прямой доступ к `StateStoreManager` есть только в `ProcessManagerProcessApp`. Дочерние процессы — только через `StateProxy.set(path, value)` → IPC `state.set` команда.

### headless-режим
`AppConfig.display_enabled = False` → RendererProcess не создаётся, SHM `renderer/rendered_frame` не аллоцируется. `GuiProcess` остаётся — он управляет pipeline-логикой. Проверять `display_enabled` перед обращением к renderer-SHM.
