# MASTER PLAN — Inspector Prototype v2 (Полная реализация)

## Видение

**Inspector v2** — гибко настраиваемый фреймворк для создания систем технического зрения.
Архитектура v2 (config-driven конструктор) + GUI-дизайн v1 (богатые виджеты, табы, UX).

Ключевая метафора: **YAML topology = чертёж системы**, **плагины = детали конструктора**,
**GUI = панель управления и настройки** конструктора. Прототип = пример собранной системы.

## Принципы

1. **Topology-first:** система описывается в YAML, GUI лишь визуализирует и редактирует topology
2. **Plugin = единица расширения:** один плагин = один файл, `process(items) → items`
3. **GenericProcess only:** никаких хардкод-процессов (кроме GUI)
4. **Register-driven GUI:** виджеты строятся из plugin-конфигов автоматически
5. **Dict at Boundary:** между процессами только dict, Pydantic внутри
6. **Переносим GUI v1 с рефакторингом:** визуальный дизайн = v1, внутренности = v2 архитектура
7. **Инкрементально:** каждая фаза — рабочий прототип, не ломающий предыдущий

---

## Правило: v1 — АРХИВ (только чтение)

> **CRITICAL:** `multiprocess_prototype/` — архив. Никаких изменений.
> Всё, что нужно из v1, **пересоздаётся** в v2 с новой архитектурой.
> v1 используется только как **справочник** для дизайна и логики.

---

## Текущий статус

### Backend / Plugins

| Компонент | Статус | Источник |
|-----------|--------|----------|
| Bootstrap (main.py) | ✅ Готов | v2 |
| Config system (system.yaml + schemas) | ✅ Готов | v2 |
| Plugin discovery + registry | ✅ Готов | framework |
| GenericProcess + ChainWorker | ✅ Готов | framework |
| SHM ring-buffer + middleware | ✅ Готов | framework |
| Topology YAML + validation | ✅ Готов | v2 |
| Fan-out/Fan-in (region_split/stitcher) | ✅ Готов | v2 |

### Плагины — инвентаризация

| Плагин v2 | Категория | Статус | Эквивалент в v1 |
|-----------|-----------|--------|-----------------|
| `capture` | source | ✅ Базовый | CameraServicePlugin (неполный — только cv2) |
| `color_mask` | processing | ✅ Готов | color_mask |
| `grayscale` | processing | ✅ Готов | — (новый в v2) |
| `negative` | processing | ✅ Готов | — (новый в v2) |
| `flip` | processing | ✅ Готов | — (новый в v2) |
| `resize` | processing | ✅ Готов | — (новый в v2) |
| `region_split` | processing | ✅ Готов | — (новый в v2) |
| `stitcher` | processing | ✅ Готов | — (новый в v2) |
| `frame_counter` | output | ✅ Готов | — (новый в v2) |
| `frame_saver` | output | ✅ Готов | — (новый в v2) |
| `database` | storage | ✅ Готов | DatabasePlugin (упрощённый) |
| `heartbeat` | lifecycle | ✅ Готов | — (новый в v2) |
| **`camera_service`** | source | 🔲 НУЖЕН | CameraServicePlugin (multi-backend, 14 команд) |
| **`render_overlay`** | output | 🔲 НУЖЕН | RenderPlugin (mask overlay + alpha) |
| **`blob_detector`** | processing | 🔲 НУЖЕН | ProcessorService (ColorBlobDetector) |
| **`chain_executor`** | processing | 🔲 НУЖЕН | ProcessorService (chain pipeline) |
| **`robot_control`** | output | 🔲 НУЖЕН | RobotPlugin (hardware rejection) |
| **`renderer_compositor`** | output | 🔲 НУЖЕН | RendererService (multi-source compositing) |
| **`worker_pool`** | service | 🔲 НУЖЕН | ProcessorWorkerPlugin (pool execution) |

### GUI

| Компонент | Статус | Источник |
|-----------|--------|----------|
| GUI базовый (3 таба: Camera, Controls, Topology) | ✅ Готов | v2 Phase 4 |
| GUI полный (7+ табов, UX) | 🔲 Нужен | пересоздать по дизайну v1 |
| Registers system | 🔲 Нужен | пересоздать с автогенерацией |
| StateStore integration | 🔲 Нужен | из framework |
| Recipes / Presets | 🔲 Нужен | пересоздать |
| Undo/Redo (ActionBus) | 🔲 Нужен | пересоздать |
| TopologyBridge (GUI ↔ Runtime) | 🔲 Нужен | пересоздать |

---

## Фазы

### Phase 6 — Plugin Migration (Пересоздание плагинов v1 → v2)
### Phase 7 — Registers v2 (Plugin-Driven)
### Phase 8 — StateStore + Реактивность
### Phase 9 — GUI Foundations (MainWindow + табы)
### Phase 10 — GUI Tabs (полный набор виджетов v1)
### Phase 11 — Recipes + Presets + Undo/Redo
### Phase 12 — TopologyBridge v2 (GUI ↔ Runtime синхронизация)
### Phase 13 — Pipeline Editor (визуальный конструктор)
### Phase 14 — Polish + Production Ready

---

## Phase 6 — Plugin Migration (Пересоздание плагинов v1 → v2)

### Цель
Пересоздать все плагины/сервисы из v1 в v2 архитектуре.
В v1 каждый плагин = ProcessModule подкласс + Service + Adapter (~500 строк).
В v2 каждый плагин = один файл с `process(items) → items` (~50-150 строк).

**Правило:** v1 — только для чтения (справочник логики). Код пишем заново в v2 стиле.

### Архитектура плагинов v2

```
plugins/
├── sources/                    # Категория: source (produce → items)
│   ├── capture/                # ✅ Есть (базовый cv2)
│   └── camera_service/         # 🔲 Multi-backend (webcam/simulator/hikvision/file)
├── processing/                 # Категория: processing (process(items) → items)
│   ├── color_mask/             # ✅ Есть
│   ├── grayscale/              # ✅ Есть
│   ├── negative/               # ✅ Есть
│   ├── flip/                   # ✅ Есть
│   ├── resize/                 # ✅ Есть
│   ├── region_split/           # ✅ Есть
│   ├── stitcher/               # ✅ Есть
│   ├── blob_detector/          # 🔲 Контурная детекция + bounding boxes
│   └── chain_executor/         # 🔲 Последовательный pipeline обработки
├── output/                     # Категория: output (consume items, render/save)
│   ├── frame_counter/          # ✅ Есть
│   ├── frame_saver/            # ✅ Есть
│   ├── render_overlay/         # 🔲 Наложение маски на кадр
│   ├── renderer_compositor/    # 🔲 Compositing нескольких источников
│   └── robot_control/          # 🔲 Управление отбраковкой
├── storage/                    # Категория: storage
│   └── database/               # ✅ Есть
└── lifecycle/                  # Категория: lifecycle
    └── heartbeat/              # ✅ Есть
```

### Task 6.1 — CameraServicePlugin v2 (Multi-Backend)
**Level:** Senior (Opus/TeamLead)
**Assignee:** teamlead
**Goal:** Пересоздать CameraServicePlugin из v1 с multi-backend поддержкой
**Files:**
- `multiprocess_prototype_2/plugins/camera_service/plugin.py` (новый)
- `multiprocess_prototype_2/plugins/camera_service/config.py` (новый)
- `multiprocess_prototype_2/plugins/camera_service/backends/` (новая папка)
  - `base.py` — CameraBackend Protocol
  - `webcam.py` — WebcamBackend (cv2.VideoCapture)
  - `simulator.py` — SimulatorBackend (генерация тестовых кадров)
  - `hikvision.py` — HikvisionBackend (MVS SDK)
  - `file_source.py` — FileBackend (видео/изображения с диска)
**Справочник v1:** `multiprocess_prototype/plugins/cameras/camera_service/`, `multiprocess_prototype/services/camera/service.py`
**Steps:**
1. Изучить CameraService из v1 (backends, FPS throttling, SHM resize)
2. Создать Protocol `CameraBackend` с методами: `open()`, `read() → ndarray`, `close()`, `set_param()`
3. Реализовать 4 backend'а (webcam, simulator, hikvision, file)
4. CameraServicePlugin.produce() — вызывает backend.read(), возвращает items
5. Команды: start_capture, stop_capture, set_camera_type, set_resolution, set_fps, set_device_id
6. FPS throttling: если камера быстрее target_fps → sleep
7. Config: camera_type (Literal["webcam", "simulator", "hikvision", "file"]), device_id, fps, resolution, hikvision_*, file_path
**Acceptance criteria:**
- [ ] 4 backend'а работают через единый Protocol
- [ ] Переключение camera_type через команду (без перезапуска процесса)
- [ ] FPS throttling ≤ 2% отклонение от target
- [ ] Simulator генерирует тестовые кадры с timestamp overlay
- [ ] Команды: 8+ (start, stop, set_type, set_resolution, set_fps, set_device, set_exposure, set_gain)
- [ ] Тесты: 15+ (backend Protocol, simulator, throttling, command handling)
**Out of scope:** Hikvision hardware тестирование (mock-тесты)

### Task 6.2 — BlobDetectorPlugin (Детекция контуров)
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Пересоздать ColorBlobDetector из v1 как v2 processing plugin
**Files:**
- `multiprocess_prototype_2/plugins/blob_detector/plugin.py` (новый)
- `multiprocess_prototype_2/plugins/blob_detector/config.py` (новый)
**Справочник v1:** `multiprocess_prototype/services/processor/service.py` (ColorBlobDetector), `multiprocess_prototype/plugins/services/processor_service/`
**Steps:**
1. Изучить ColorBlobDetector из v1 ProcessorService
2. `process(items) → items` — для каждого кадра:
   a. Применить HSV маску (color_lower, color_upper)
   b. findContours → filter by area (min_area, max_area)
   c. Добавить bounding boxes + centers в item["detections"]
   d. Опционально: нарисовать контуры на кадре (draw_contours=True)
3. Config: color_lower/upper (HSV), min_area, max_area, draw_contours, show_mask
4. Команды: set_color_range, set_area_range, toggle_draw_contours
**Acceptance criteria:**
- [ ] Детектирует контуры по HSV маске
- [ ] Фильтрация по area работает
- [ ] item["detections"] содержит bbox + center + area
- [ ] Опциональная отрисовка контуров
- [ ] Тесты: 10+ (с синтетическими изображениями)
**Out of scope:** ML-детекция (Phase 14+)

### Task 6.3 — RenderOverlayPlugin (Наложение маски)
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Пересоздать RenderPlugin из v1 — наложение маски на оригинальный кадр
**Files:**
- `multiprocess_prototype_2/plugins/render_overlay/plugin.py` (новый)
- `multiprocess_prototype_2/plugins/render_overlay/config.py` (новый)
**Справочник v1:** `multiprocess_prototype/backend/plugins/render/plugin.py`
**Steps:**
1. `process(items) → items` — для каждого item:
   a. Взять item["frame"] (оригинал) и item["mask"] (бинарная маска)
   b. Наложить маску с alpha blending и цветом
   c. Нарисовать bounding boxes из item["detections"] если есть
   d. Записать результат в item["rendered_frame"]
2. Config: mask_alpha (0.0-1.0), mask_color_bgr (tuple), draw_detections (bool), line_thickness
3. Команды: set_alpha, set_color, toggle_detections
**Acceptance criteria:**
- [ ] Alpha blending маски на кадр
- [ ] Отрисовка bounding boxes из detections
- [ ] Настраиваемые цвет и прозрачность
- [ ] Тесты: 8+
**Out of scope:** Multi-layer compositing (Task 6.5)

### Task 6.4 — RobotControlPlugin (Управление отбраковкой)
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Пересоздать RobotPlugin из v1 — управление аппаратной отбраковкой
**Files:**
- `multiprocess_prototype_2/plugins/robot_control/plugin.py` (новый)
- `multiprocess_prototype_2/plugins/robot_control/config.py` (новый)
**Справочник v1:** `multiprocess_prototype/plugins/hardware/robot_control/`, `multiprocess_prototype/services/robot/service.py`
**Steps:**
1. `process(items) → items` — для каждого item:
   a. Проверить item["detections"] → есть дефект?
   b. Если дефект → отправить команду reject (через ctx.io.send_data)
   c. Логировать действие (timestamp, defect_type, action)
2. Config: reject_delay (ms), min_defect_area, log_file, enabled
3. Команды: enable, disable, set_delay, reset_counters
4. State: total_inspected, total_rejected, reject_rate
**Acceptance criteria:**
- [ ] Решение reject/pass на основе detections
- [ ] Настраиваемая задержка отбраковки
- [ ] Логирование действий
- [ ] State publishing (inspected/rejected/rate)
- [ ] Тесты: 8+
**Out of scope:** Реальное оборудование (используем mock output)

### Task 6.5 — RendererCompositorPlugin (Multi-Source Compositing)
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Пересоздать RendererService из v1 — compositing нескольких источников в один кадр
**Files:**
- `multiprocess_prototype_2/plugins/renderer_compositor/plugin.py` (новый)
- `multiprocess_prototype_2/plugins/renderer_compositor/config.py` (новый)
**Справочник v1:** `multiprocess_prototype/services/renderer/service.py`
**Steps:**
1. `process(items) → items` — принимает несколько кадров (от разных камер/процессов):
   a. Layout: grid (2x2, 3x3), side-by-side, picture-in-picture
   b. Resize каждый source под layout slot
   c. Composite в один выходной кадр
   d. Overlay: timestamp, FPS, status text
2. Config: layout_mode (Literal["grid", "side_by_side", "pip"]), grid_cols, grid_rows, overlay_enabled
3. Команды: set_layout, toggle_overlay
**Acceptance criteria:**
- [ ] Grid layout работает (NxM)
- [ ] Side-by-side работает
- [ ] PiP (picture-in-picture) работает
- [ ] Text overlay (fps, timestamp)
- [ ] Тесты: 8+
**Out of scope:** Кастомные layout (drag-and-drop позиционирование)

### Task 6.6 — ChainExecutorPlugin (Pipeline Orchestration)
**Level:** Senior (Opus/TeamLead)
**Assignee:** teamlead
**Goal:** Пересоздать ProcessorService chain logic — последовательное/параллельное выполнение шагов обработки
**Files:**
- `multiprocess_prototype_2/plugins/chain_executor/plugin.py` (новый)
- `multiprocess_prototype_2/plugins/chain_executor/config.py` (новый)
**Справочник v1:** `multiprocess_prototype/services/processor/service.py` (chain runnables, WorkerPoolDispatcher)
**Steps:**
1. ChainExecutorPlugin управляет цепочкой вложенных плагинов (sub-plugins):
   a. Config содержит список шагов: `steps: [{plugin: "color_mask", config: {...}}, {plugin: "blob_detector", config: {...}}]`
   b. `process(items)` → последовательно прогоняет items через каждый шаг
   c. Каждый шаг = экземпляр другого plugin (из PluginRegistry)
2. Опциональный parallel mode: шаги выполняются параллельно (ThreadPool)
3. Config: steps (list), parallel (bool), max_workers (int)
4. Команды: add_step, remove_step, reorder_steps, update_step_config
**Acceptance criteria:**
- [ ] Последовательное выполнение chain работает
- [ ] Параллельное выполнение (ThreadPool) работает
- [ ] Динамическое добавление/удаление шагов через команды
- [ ] Ошибка в шаге → skip + log (не ломает pipeline)
- [ ] Тесты: 12+
**Out of scope:** Распределённый worker pool (cross-process)

### Task 6.7 — WorkerPoolPlugin (Cross-Process Workers)
**Level:** Senior+ (Opus/TeamLead)
**Assignee:** teamlead
**Goal:** Пересоздать ProcessorWorkerPlugin — распределённые worker'ы для тяжёлых задач
**Files:**
- `multiprocess_prototype_2/plugins/worker_pool/plugin.py` (новый)
- `multiprocess_prototype_2/plugins/worker_pool/config.py` (новый)
**Справочник v1:** `multiprocess_prototype/plugins/services/processor_worker/`
**Steps:**
1. WorkerPoolPlugin запускается в отдельных процессах (topology: N worker processes)
2. Dispatcher (в основном процессе) распределяет задачи по worker'ам через IPC
3. Worker получает item → выполняет plugin.process() → возвращает результат
4. Load balancing: round-robin или shortest-queue
5. Config: pool_size, queue_size, timeout, balancing_strategy
**Acceptance criteria:**
- [ ] N worker-процессов обрабатывают задачи параллельно
- [ ] Round-robin и shortest-queue стратегии
- [ ] Timeout + error handling для зависших worker'ов
- [ ] Тесты: 10+
**Out of scope:** Auto-scaling (динамическое изменение pool_size)

### Task 6.8 — Обновление capture plugin (недостающие фичи)
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Дополнить существующий capture plugin фичами из v1 CapturePlugin
**Files:**
- `multiprocess_prototype_2/plugins/capture/plugin.py` — обновить
- `multiprocess_prototype_2/plugins/capture/config.py` — обновить
**Справочник v1:** `multiprocess_prototype/backend/plugins/capture/plugin.py`
**Steps:**
1. Добавить FPS throttling (если камера быстрее target)
2. Добавить frame resize (если native resolution ≠ config resolution)
3. Добавить SHM ring-buffer size configuration
4. Добавить frame metadata: timestamp, frame_id, camera_id, resolution
5. Добавить команды: pause_capture, resume_capture
**Acceptance criteria:**
- [ ] FPS throttling работает
- [ ] Resize кадра при несовпадении resolution
- [ ] Metadata в каждом item
- [ ] Pause/resume через команды
- [ ] Тесты: 5+
**Out of scope:** Multi-backend (это camera_service, Task 6.1)

### Task 6.9 — Обновление database plugin (batch strategy из v1)
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Дополнить database plugin batch-стратегиями из v1 DatabaseService
**Files:**
- `multiprocess_prototype_2/plugins/database/plugin.py` — обновить
- `multiprocess_prototype_2/plugins/database/config.py` — обновить
**Справочник v1:** `multiprocess_prototype/services/database/service.py`
**Steps:**
1. Batch insertion: буферизация N записей → bulk insert
2. Flush interval: автоматический flush каждые N секунд
3. Fallback strategy: если batch fails → try one-by-one
4. Schema validation через Pydantic перед вставкой
5. Команды: flush_now, set_batch_size, reset_stats
**Acceptance criteria:**
- [ ] Batch insertion работает (batch_size configurable)
- [ ] Auto-flush по таймеру
- [ ] Fallback strategy при ошибках
- [ ] Тесты: 8+
**Out of scope:** PostgreSQL backend (только SQLite)

### Task 6.10 — Example Topologies для новых плагинов
**Level:** Junior (Sonnet)
**Assignee:** developer
**Goal:** YAML topology файлы, демонстрирующие новые плагины
**Files:**
- `multiprocess_prototype_2/topology/inspection_basic.yaml` — камера → blob_detector → render_overlay → GUI
- `multiprocess_prototype_2/topology/inspection_full.yaml` — камера → chain(mask + detect + render) → DB + robot → GUI
- `multiprocess_prototype_2/topology/multi_camera.yaml` — 2 камеры → 2 процессора → compositor → GUI
**Steps:**
1. Каждый topology — рабочий пример
2. Включить все новые плагины хотя бы в одном topology
3. Проверить запуск каждого topology
**Acceptance criteria:**
- [ ] 3 topology файла
- [ ] Каждый запускается без ошибок
- [ ] Покрыты все новые плагины
**Out of scope:** GUI-специфичные topology (Phase 9+)

---

## Phase 7 — Registers v2 (Plugin-Driven)

### Цель
Система регистров, которая **автоматически строится из plugin-конфигов**, а не описывается вручную.
В v1 было 6 хардкод-регистров. В v2 — регистр = проекция plugin config на GUI.

### Архитектура

```
PluginRegistry.discover()
  → для каждого plugin: plugin.config_schema() → Pydantic model
  → RegistersManager собирает все config-схемы
  → GUI: CardsFieldFactory строит формы автоматически
```

### Task 6.1 — Plugin Config Schema Protocol
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Каждый плагин экспортирует свою Pydantic-схему конфига
**Files:**
- `multiprocess_framework/modules/process_module/plugins/base.py` — добавить `config_schema() → type[BaseModel]`
- `multiprocess_prototype_2/plugins/capture/config.py` — пример
- `multiprocess_prototype_2/plugins/color_mask/config.py` — пример
**Steps:**
1. Добавить метод `config_schema()` в базовый `ProcessModulePlugin`
2. Каждый config.py уже имеет Pydantic-модель — привязать к plugin
3. Добавить метаданные для GUI: `Field(title="FPS", ge=1, le=120, description="Частота кадров")`
**Acceptance criteria:**
- [ ] `plugin.config_schema()` возвращает Pydantic model class
- [ ] Модель содержит GUI-метаданные (title, min, max, description, category)
- [ ] Все 13 плагинов имеют config_schema
**Out of scope:** GUI-рендеринг форм (Phase 8)

### Task 6.2 — RegistersManager v2
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Менеджер регистров, собирающий схемы из PluginRegistry
**Files:**
- `multiprocess_prototype_2/registers/__init__.py`
- `multiprocess_prototype_2/registers/manager.py` (новый)
- `multiprocess_prototype_2/registers/field_metadata.py` (новый)
**Steps:**
1. `RegistersManager.from_plugins(registry)` — сканирует все плагины, собирает config_schema
2. Группировка по категориям: source, processing, output, storage
3. `get_fields(plugin_name)` → список полей с метаданными для GUI
4. `get_value(plugin_name, field)` / `set_value(plugin_name, field, value)` — чтение/запись
**Acceptance criteria:**
- [ ] RegistersManager строится из PluginRegistry автоматически
- [ ] Поддерживает get/set по plugin_name.field_name
- [ ] Валидация через Pydantic при set_value
- [ ] Тесты: 10+ unit-тестов
**Out of scope:** IPC-роутинг значений (Phase 11)

### Task 6.3 — Connection Map (Register → Process)
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Маппинг register field → target process для отправки команд
**Files:**
- `multiprocess_prototype_2/registers/connection_map.py` (новый)
**Steps:**
1. Из topology YAML извлечь: plugin X запущен в process Y
2. `ConnectionMap.resolve(plugin_name, field_name)` → `(process_name, command_id, args)`
3. Автогенерация command_id из plugin_name + field_name
**Acceptance criteria:**
- [ ] ConnectionMap строится из topology + RegistersManager
- [ ] resolve() возвращает target process и command для любого поля
- [ ] Тесты: 5+ unit-тестов
**Out of scope:** Реальная отправка команд (Phase 11)

---

## Phase 8 — StateStore + Реактивность

### Цель
Интеграция StateStore из фреймворка. Реактивное состояние всей системы:
процессы публикуют state, GUI подписывается на изменения.

### Архитектура

```
ProcessManager
  └─ StateStoreManager (TreeStore)
       ├─ processes.{name}.state → {status, fps, drops, ...}
       ├─ processes.{name}.config → plugin configs (из topology)
       └─ system.{key} → глобальные метрики

Каждый GenericProcess:
  └─ StateProxy → публикует state через router

GuiProcess:
  └─ GuiStateProxy (Qt-safe) → подписки → обновление виджетов
```

### Task 9.1 — State Bootstrap из Topology
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Начальное дерево состояния строится из topology YAML
**Files:**
- `multiprocess_prototype_2/state/bootstrap.py` (новый)
- `multiprocess_prototype_2/state/__init__.py` (новый)
**Steps:**
1. Из topology processes[] → начальный state: `{processes: {camera_0: {config: {...}, state: {status: "stopped"}}}}`
2. Из system.yaml → системные defaults
3. Функция `build_initial_state(topology, system_config) → dict`
**Acceptance criteria:**
- [ ] Строит корректное дерево из любого topology YAML
- [ ] Включает config + state для каждого процесса
- [ ] Тесты: 5+
**Out of scope:** Runtime-обновления (Task 7.2)

### Task 9.2 — StateStore интеграция в ProcessManagerApp
**Level:** Senior (Sonnet/TeamLead)
**Assignee:** teamlead
**Goal:** ProcessManager v2 использует StateStoreManager для хранения состояния
**Files:**
- `multiprocess_prototype_2/main.py` — интеграция в bootstrap
- `multiprocess_prototype_2/state/manager_setup.py` (новый)
**Steps:**
1. В main.py после build_configs() → build_initial_state()
2. Передать initial_state в ProcessManagerProcessApp через orchestrator_config
3. ProcessManagerProcessApp._setup_state_store() → StateStoreManager
4. Подключить middleware: Validation, Throttle
**Acceptance criteria:**
- [ ] StateStore инициализируется при старте
- [ ] Начальное состояние соответствует topology
- [ ] Процессы получают StateProxy через framework
- [ ] Smoke-тест: запуск → state_store содержит все процессы
**Out of scope:** GUI-подписки (Phase 8)

### Task 9.3 — Plugin State Publishing
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Плагины публикуют своё состояние через StateProxy
**Files:**
- `multiprocess_prototype_2/plugins/capture/plugin.py` — добавить state publishing
- `multiprocess_prototype_2/plugins/color_mask/plugin.py` — аналогично
**Steps:**
1. PluginContext получает state_proxy
2. Plugin.on_state_update() вызывается периодически
3. CapturePlugin публикует: fps, frame_count, status, drops
4. Processing plugins публикуют: processed_count, avg_latency
**Acceptance criteria:**
- [ ] CapturePlugin обновляет state каждую секунду
- [ ] Processing plugins обновляют state по завершении process()
- [ ] StateStore содержит актуальные метрики
**Out of scope:** GUI-отображение (Phase 8-9)

---

## Phase 9 — GUI Foundations (MainWindow + Система табов)

### Цель
Перенести MainWindow layout из v1: Header + ImagePanel + TabWidget.
Настроить систему DI (AppContext) для v2 архитектуры.

### Архитектура

```
MainWindow (v1 дизайн)
├── AppHeader (лого, кнопки, search)
├── ImagePanel (отображение кадров из SHM)
└── TabWidget
    ├── Tab 1: Camera View (уже есть в v2)
    ├── Tab 2: Sources (Phase 9)
    ├── Tab 3: Processing (Phase 9)
    ├── Tab 4: Pipeline (Phase 12)
    ├── Tab 5: Processes (Phase 9)
    ├── Tab 6: Recipes (Phase 10)
    └── Tab 7: Settings (Phase 9)
```

### Task 9.1 — FrontendAppContext v2
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** DI-контейнер для GUI, адаптированный под v2 архитектуру
**Files:**
- `multiprocess_prototype_2/frontend/app_context.py` (новый)
**Steps:**
1. Dataclass с полями: config, registers_manager, state_proxy, command_sender, plugin_registry, topology
2. Фабрика `build_context(gui_process, topology, registers)` → FrontendAppContext
3. Все виджеты получают context при создании
**Acceptance criteria:**
- [ ] Все зависимости доступны через единый контекст
- [ ] Нет глобальных переменных или синглтонов
- [ ] Тесты: context creation + mock injection
**Out of scope:** Содержимое табов (Phase 9)

### Task 9.2 — MainWindow v2 (Layout из v1)
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** MainWindow с дизайном v1 но архитектурой v2
**Files:**
- `multiprocess_prototype_2/frontend/windows/main_window.py` — рефакторинг
- `multiprocess_prototype_2/frontend/windows/config.py` (новый)
- `multiprocess_prototype_2/frontend/widgets/chrome/header.py` (новый)
- `multiprocess_prototype_2/frontend/widgets/chrome/image_panel.py` (новый)
**Steps:**
1. Перенести layout из v1: Header сверху, ImagePanel по центру, TabWidget снизу
2. Header: лого + кнопки действий + статусбар
3. ImagePanel: QLabel для отображения кадров (уже есть CameraView — интегрировать)
4. TabWidget: динамическая фабрика табов
5. Стили: перенести QSS из v1 `frontend/styles/`
**Acceptance criteria:**
- [ ] Окно визуально соответствует v1
- [ ] Header отображает статус системы
- [ ] ImagePanel показывает кадры
- [ ] TabWidget поддерживает динамическое добавление табов
- [ ] Тесты: window creation + tab switching
**Out of scope:** Содержимое табов кроме Camera (Phase 9)

### Task 9.3 — Tab Factory (Plugin-Aware)
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Фабрика табов, которая создаёт табы на основе topology и плагинов
**Files:**
- `multiprocess_prototype_2/frontend/tab_factory.py` (новый)
**Steps:**
1. `TabFactory.create_tabs(context) → list[QWidget]`
2. Стандартные табы: Camera, Sources, Processing, Processes, Settings — всегда
3. Опциональные табы: Pipeline, Recipes — если есть соответствующие плагины
4. Каждый таб получает FrontendAppContext
**Acceptance criteria:**
- [ ] Фабрика создаёт правильный набор табов из topology
- [ ] Табы ленивые (создаются при первом показе)
- [ ] Тесты: factory с разными topology → разные наборы табов
**Out of scope:** Внутренности табов (Phase 9)

### Task 9.4 — Стили и темы (перенос из v1)
**Level:** Junior (Sonnet)
**Assignee:** developer
**Goal:** Перенести QSS стили из v1 для единообразного дизайна
**Files:**
- `multiprocess_prototype_2/frontend/styles/` (новая папка)
- `multiprocess_prototype_2/frontend/styles/dark_theme.qss`
- `multiprocess_prototype_2/frontend/styles/theme_manager.py`
**Steps:**
1. Скопировать QSS из v1 `frontend/styles/`
2. Адаптировать под новую структуру классов
3. ThemeManager: загрузка и применение тем
**Acceptance criteria:**
- [ ] Тёмная тема работает
- [ ] Все виджеты стилизованы единообразно
**Out of scope:** Редактор тем (не нужен)

---

## Phase 10 — GUI Tabs (Полный набор виджетов)

### Цель
Перенести все основные табы из v1, адаптировав под v2 архитектуру.
Каждый таб = MVP (Model + View Protocol + Presenter).

### Task 10.1 — Sources Tab (Управление камерами)
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Таб управления источниками (камерами), аналог v1 SourcesTabWidget
**Files:**
- `multiprocess_prototype_2/frontend/widgets/sources/` (новая папка)
  - `view.py` — SourcesView (Protocol + Widget)
  - `presenter.py` — SourcesPresenter
  - `camera_card.py` — карточка камеры (параметры)
  - `region_editor.py` — редактор регионов
**Steps:**
1. Перенести дизайн из v1 `frontend/widgets/tabs_setting/sources_tab/`
2. Model = topology processes где category=source (не отдельный регистр!)
3. Presenter читает RegistersManager.get_fields("capture") → строит карточки
4. Карточка камеры: device_id, resolution, fps, camera_type — из plugin config_schema
5. Регионы: из region_split plugin config_schema
6. Изменения → сохранение в topology + команда через IPC (Phase 11)
**Acceptance criteria:**
- [ ] Список камер отображается из topology
- [ ] Параметры камеры редактируемы
- [ ] Регионы создаются/удаляются
- [ ] MVP: view не знает о данных, presenter не знает о Qt
- [ ] Тесты: presenter logic, 10+
**Out of scope:** Отправка изменений в runtime (Phase 11)

### Task 10.2 — Processing Tab (Параметры обработки)
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Таб настройки параметров обработки, аналог v1 ProcessingPanelWidget
**Files:**
- `multiprocess_prototype_2/frontend/widgets/processing/` (новая папка)
  - `view.py`
  - `presenter.py`
  - `plugin_params_card.py` — карточка параметров плагина
**Steps:**
1. Дизайн из v1 `frontend/widgets/processing/`
2. Model = topology processes где category=processing
3. Для каждого processing plugin → карточка с его config_schema полями
4. CardsFieldFactory v2: автогенерация виджетов из Pydantic Field metadata
5. Слайдеры для числовых, color picker для цветов, checkbox для bool
**Acceptance criteria:**
- [ ] Отображаются все processing плагины из topology
- [ ] Параметры каждого плагина редактируемы
- [ ] CardsFieldFactory генерирует правильные виджеты для разных типов
- [ ] Тесты: card generation, 10+
**Out of scope:** Undo/Redo (Phase 10)

### Task 10.3 — Processes Tab (Управление процессами)
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Таб управления процессами, аналог v1 ProcessesTabWidget
**Files:**
- `multiprocess_prototype_2/frontend/widgets/processes/` (новая папка)
  - `view.py`
  - `presenter.py`
  - `process_card.py`
  - `worker_tree.py`
**Steps:**
1. Дизайн из v1 `frontend/widgets/tabs_setting/processes_tab/`
2. Список процессов из topology + их runtime status из StateStore
3. Для каждого процесса: имя, статус, PID, плагины, метрики (fps, latency)
4. Кнопки: Start/Stop/Restart процесса
5. Worker tree: потоки внутри процесса (если есть worker_pool)
**Acceptance criteria:**
- [ ] Все процессы из topology отображаются
- [ ] Status обновляется из StateStore реактивно
- [ ] Start/Stop/Restart отправляют команды
- [ ] Тесты: presenter logic, 8+
**Out of scope:** Создание/удаление процессов из GUI (Phase 12)

### Task 10.4 — Settings Tab
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Таб глобальных настроек приложения
**Files:**
- `multiprocess_prototype_2/frontend/widgets/settings/` (новая папка)
  - `view.py`
  - `presenter.py`
**Steps:**
1. Дизайн из v1 `frontend/widgets/settings/`
2. Секции: System, Display, Storage — из config/system.yaml schema
3. Автогенерация полей из SystemConfig Pydantic model
4. Сохранение: перезапись system.yaml
**Acceptance criteria:**
- [ ] Все секции system.yaml отображаются
- [ ] Изменения сохраняются в файл
- [ ] Тесты: 5+
**Out of scope:** Hot-reload настроек (отдельная задача)

### Task 10.5 — Display Tab (Управление окнами отображения)
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Таб управления окнами вывода, аналог v1 DisplayTabWidget
**Files:**
- `multiprocess_prototype_2/frontend/widgets/display/` (новая папка)
  - `view.py`
  - `presenter.py`
  - `display_card.py`
**Steps:**
1. Дизайн из v1 `frontend/widgets/tabs_setting/display_tab/`
2. Список display-окон: имя, размер, привязка к камере/процессу
3. Создание/удаление/настройка display windows
4. Подписки: какой источник → какое окно
**Acceptance criteria:**
- [ ] CRUD для display windows
- [ ] Привязка к source процессу
- [ ] Тесты: 8+
**Out of scope:** DirectShow backend (позже)

### Task 10.6 — CardsFieldFactory v2 (Универсальная автогенерация форм)
**Level:** Senior (Opus/TeamLead)
**Assignee:** teamlead
**Goal:** Фабрика, строящая Qt-виджеты из Pydantic Field metadata
**Files:**
- `multiprocess_prototype_2/frontend/widgets/base/cards_factory.py` (новый)
- `multiprocess_prototype_2/frontend/widgets/base/field_widgets.py` (новый)
**Steps:**
1. Перенести концепцию из v1 `frontend/widgets/base/`
2. Маппинг типов: `int → QSpinBox`, `float → QDoubleSpinBox`, `str → QLineEdit`, `bool → QCheckBox`, `Literal[...] → QComboBox`, `tuple[int,int,int] → ColorPicker`
3. Учитывать метаданные: min/max → setRange, title → QLabel, description → tooltip
4. Группировка полей по `json_schema_extra["category"]`
5. Один вызов: `CardsFieldFactory.build(schema: type[BaseModel]) → QWidget`
**Acceptance criteria:**
- [ ] Генерирует формы для любого Pydantic model
- [ ] Все типы покрыты: int, float, str, bool, Literal, Color
- [ ] Поддержка min/max/title/description
- [ ] Группировка по категориям
- [ ] Тесты: 15+, включая edge cases
**Out of scope:** Кастомные виджеты для специфичных плагинов

---

## Phase 11 — Recipes + Presets + Undo/Redo

### Цель
Система рецептов (сохранение/загрузка конфигурации) и Undo/Redo.
Рецепт = snapshot topology + всех plugin configs.

### Task 11.1 — Recipe Model v2
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Рецепт = именованный snapshot topology + plugin configs
**Files:**
- `multiprocess_prototype_2/recipes/` (новая папка)
  - `model.py` — Recipe Pydantic model
  - `storage.py` — YAML-based persistence
  - `manager.py` — RecipeManager (CRUD + apply)
**Steps:**
1. Recipe = {name, description, topology_snapshot, plugin_configs, created_at}
2. Хранение: `data/recipes/` в YAML формате
3. RecipeManager: list, load, save, delete, apply
4. Apply = загрузить topology + подставить configs → перезапуск
**Acceptance criteria:**
- [ ] CRUD операции работают
- [ ] Recipe содержит полный snapshot для воспроизведения
- [ ] Apply рецепта восстанавливает состояние
- [ ] Тесты: 10+
**Out of scope:** Undo/Redo (Task 10.2), GUI (Task 10.3)

### Task 11.2 — ActionBus + Undo/Redo
**Level:** Senior (Opus/TeamLead)
**Assignee:** teamlead
**Goal:** Перенести ActionBus из v1 с адаптацией под v2
**Files:**
- `multiprocess_prototype_2/frontend/actions/` (новая папка)
  - `bus.py` — ActionBus
  - `history.py` — UndoStack
  - `handlers/` — обработчики по доменам
**Steps:**
1. ActionBus: register(action_id, handler), emit(action_id, *args), undo(), redo()
2. UndoStack: хранит пары (action, inverse_action)
3. Интеграция с RegistersManager: set_value → записать в стек
4. Интеграция с topology editor: add_process → записать в стек
**Acceptance criteria:**
- [ ] Ctrl+Z / Ctrl+Y работает
- [ ] Все изменения в GUI проходят через ActionBus
- [ ] Стек ограничен (50 операций)
- [ ] Тесты: 10+
**Out of scope:** Транзакции (группировка нескольких действий)

### Task 11.3 — Recipes Tab GUI
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Таб рецептов, аналог v1 RecipesTabWidget
**Files:**
- `multiprocess_prototype_2/frontend/widgets/recipes/` (новая папка)
  - `view.py`
  - `presenter.py`
  - `recipe_card.py` — карточка рецепта (slot button)
**Steps:**
1. Дизайн из v1 `frontend/widgets/recipes/`
2. Список слотов (8 слотов как в v1)
3. Load/Save/Delete/Create
4. Preview: показать topology рецепта
**Acceptance criteria:**
- [ ] Отображает список рецептов
- [ ] Load применяет рецепт к системе
- [ ] Save сохраняет текущее состояние
- [ ] Тесты: 8+
**Out of scope:** Рецепт-миграции

---

## Phase 12 — TopologyBridge v2 (GUI ↔ Runtime)

### Цель
Мост между GUI-редактированием и работающей системой.
В v1 было 3 транспорта. В v2 — **один транспорт через IPC команды**,
потому что всё управляется через topology и plugin configs.

### Архитектура

```
GUI (user edit) → TopologyBridge → IPC Command → Target Process → Plugin
                                                                    ↓
GUI (state update) ← StateProxy ← StateStore ← Process ← Plugin state
```

Однонаправленный цикл: GUI → Command → Process → State → GUI

### Task 12.1 — Command Protocol v2
**Level:** Senior (Opus/TeamLead)
**Assignee:** teamlead
**Goal:** Протокол команд для управления плагинами через GUI
**Files:**
- `multiprocess_prototype_2/commands/` (новая папка)
  - `protocol.py` — Command schema
  - `catalog.py` — автогенерируемый каталог из plugin commands
  - `sender.py` — CommandSender (GUI → router → process)
**Steps:**
1. Command = {target_process, plugin_name, command_id, args}
2. Каталог автогенерируется: PluginRegistry → plugin.commands → catalog
3. ConnectionMap (Phase 6) → resolve target process
4. CommandSender: send(plugin_name, command_id, args) → router.send_message
**Acceptance criteria:**
- [ ] Каталог команд строится автоматически из плагинов
- [ ] CommandSender корректно маршрутизирует
- [ ] Тесты: 10+ (mock router)
**Out of scope:** Batch-отправка

### Task 12.2 — TopologyBridge v2
**Level:** Senior+ (Opus/TeamLead)
**Assignee:** teamlead
**Goal:** Единый мост GUI → Runtime
**Files:**
- `multiprocess_prototype_2/frontend/bridges/topology_bridge.py` (новый)
**Steps:**
1. Слушает изменения в RegistersManager → отправляет команды через CommandSender
2. Слушает изменения topology (add/remove process) → lifecycle команды
3. Слушает StateStore changes → обновляет GUI виджеты
4. Debounce: группировка быстрых изменений (slider dragging)
**Acceptance criteria:**
- [ ] Изменение параметра в GUI → процесс получает команду
- [ ] Добавление процесса в topology → процесс запускается
- [ ] State update от процесса → GUI обновляется
- [ ] Debounce работает (≤50ms задержка)
- [ ] Тесты: 15+
**Out of scope:** Hot-reload topology (отдельная задача)

### Task 12.3 — Reactive State Subscriptions (GUI)
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Виджеты автоматически обновляются при изменении state
**Files:**
- `multiprocess_prototype_2/frontend/state/` (новая папка)
  - `subscriptions.py` — GuiStateSubscription (Qt-safe)
  - `bindings.py` — bind(state_path, widget, property)
**Steps:**
1. `bind("processes.camera_0.state.fps", fps_label, "text")` — автобиндинг
2. GuiStateSubscription обёртка над StateProxy с Qt QueuedConnection
3. Подписка по glob: `processes.*.state.*` → обновить все карточки
**Acceptance criteria:**
- [ ] Автобиндинг state → widget property работает
- [ ] Thread-safe (Qt QueuedConnection)
- [ ] Поддержка glob-подписок
- [ ] Тесты: 8+
**Out of scope:** Two-way binding (GUI → state → GUI)

---

## Phase 13 — Pipeline Editor (Визуальный конструктор)

### Цель
Визуальный редактор topology: drag-and-drop нод (процессов),
соединение wire'ами, настройка параметров. Аналог v1 PipelineTabWidget + ConstructorTab.

### Task 13.1 — Pipeline Canvas (Node Graph)
**Level:** Senior+ (Opus/TeamLead)
**Assignee:** teamlead
**Goal:** Canvas для визуального редактирования topology
**Files:**
- `multiprocess_prototype_2/frontend/widgets/pipeline/` (новая папка)
  - `canvas.py` — QGraphicsScene/View для node graph
  - `node.py` — ProcessNode (визуальное представление процесса)
  - `wire.py` — WireConnection (визуальная связь)
  - `port.py` — InputPort/OutputPort
**Steps:**
1. QGraphicsScene с процессами как нодами
2. Drag-and-drop из палитры плагинов
3. Соединение портов wire'ами (mouse drag from port to port)
4. Каждый node = один process из topology
5. Порты = inputs/outputs из plugin schema
6. Wire = один wire из topology.wires[]
**Acceptance criteria:**
- [ ] Визуализация текущей topology
- [ ] Drag-and-drop добавление процессов
- [ ] Визуальное соединение wire'ами
- [ ] Удаление нод и wire'ов
- [ ] Тесты: canvas operations, 10+
**Out of scope:** Auto-layout

### Task 13.2 — Plugin Palette
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Палитра доступных плагинов для drag-and-drop в canvas
**Files:**
- `multiprocess_prototype_2/frontend/widgets/pipeline/palette.py` (новый)
**Steps:**
1. Список плагинов из PluginRegistry, сгруппированный по category
2. Drag from palette → drop on canvas → create process node
3. Иконки/цвета по категории: source=зелёный, processing=синий, output=красный
**Acceptance criteria:**
- [ ] Все зарегистрированные плагины отображаются
- [ ] Группировка по category
- [ ] Drag-and-drop работает
- [ ] Тесты: 5+
**Out of scope:** Поиск плагинов

### Task 13.3 — Inspector Panel (Node Parameters)
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Панель параметров выбранной ноды
**Files:**
- `multiprocess_prototype_2/frontend/widgets/pipeline/inspector.py` (новый)
**Steps:**
1. При клике на ноду → Inspector показывает параметры плагина
2. Использует CardsFieldFactory (Phase 9.6) для автогенерации формы
3. Изменения → RegistersManager → TopologyBridge → Runtime
**Acceptance criteria:**
- [ ] Показывает параметры выбранной ноды
- [ ] Редактирование параметров обновляет систему
- [ ] Тесты: 5+
**Out of scope:** Multi-node selection

### Task 13.4 — Topology Import/Export
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Сохранение/загрузка topology из визуального редактора
**Files:**
- `multiprocess_prototype_2/frontend/widgets/pipeline/io.py` (новый)
**Steps:**
1. Export: canvas state → topology YAML (с позициями нод в метаданных)
2. Import: topology YAML → canvas state (с восстановлением позиций)
3. Toolbar кнопки: New, Open, Save, Save As, Validate
**Acceptance criteria:**
- [ ] Round-trip: load → save → load = идентичный результат
- [ ] Позиции нод сохраняются в metadata
- [ ] Тесты: 5+
**Out of scope:** Merge topologies

---

## Phase 14 — Polish + Production Ready

### Цель
Финальная полировка: стабильность, UX, документация, тесты.

### Task 14.1 — Error Handling + Graceful Degradation
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Обработка ошибок на всех уровнях
**Steps:**
1. Плагин упал → процесс логирует, state = "error", GUI показывает
2. Процесс упал → ProcessManager перезапускает, GUI обновляется
3. SHM недоступен → fallback на IPC (медленно, но работает)
4. GUI потеряла связь → reconnect + warning banner

### Task 14.2 — Performance Profiling
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Метрики производительности в GUI
**Steps:**
1. FPS counter per process (из StateStore)
2. Latency pipeline end-to-end
3. SHM usage (bytes allocated / total budget)
4. Memory per process

### Task 14.3 — Integration Tests
**Level:** Middle+ (Sonnet)
**Assignee:** tester
**Goal:** E2E тесты всего pipeline
**Steps:**
1. Тест: запуск с topology → все процессы стартуют → GUI показывает кадры
2. Тест: изменение параметра в GUI → процесс получает команду
3. Тест: save/load рецепта
4. Тест: добавление/удаление процесса через Pipeline Editor
**Acceptance criteria:**
- [ ] 20+ integration тестов
- [ ] CI-ready (pytest + pytest-qt)

### Task 14.4 — Документация
**Level:** Middle (Haiku)
**Assignee:** docs-writer
**Goal:** README, architecture docs, plugin development guide
**Steps:**
1. README.md: установка, запуск, overview
2. ARCHITECTURE.md: диаграммы, потоки данных
3. PLUGIN_GUIDE.md: как создать свой плагин
4. TOPOLOGY_GUIDE.md: формат YAML, примеры

### Task 14.5 — Example Topologies
**Level:** Junior (Sonnet)
**Assignee:** developer
**Goal:** Набор готовых topology для разных use-cases
**Steps:**
1. `topology/examples/single_camera.yaml` — минимальная система
2. `topology/examples/multi_camera.yaml` — 4 камеры параллельно
3. `topology/examples/inspection_line.yaml` — инспекция на конвейере
4. `topology/examples/quality_control.yaml` — контроль качества с ML

---

## Зависимости между фазами

```
Phase 6 (Plugins)  ─────────────────────────────────────────────┐
    ↓                                                            ↓
Phase 7 (Registers) ────────────────────────────────┐      Phase 8 (StateStore)
                                                    ↓           ↓
Phase 9 (GUI Foundation) ──────────────────→ Phase 10 (GUI Tabs)
                                                    ↓
                                              Phase 11 (Recipes/Undo)
                                                    ↓
                                              Phase 12 (TopologyBridge)
                                                    ↓
                                              Phase 13 (Pipeline Editor)
                                                    ↓
                                              Phase 14 (Polish)
```

**Параллельно можно:**
- Phase 6 задачи 6.1-6.5 параллельно (независимые плагины)
- Phase 7 + Phase 8 (Registers + StateStore — независимы)
- Phase 9 + Phase 7/8 (частично, layout не зависит от registers/state)
- Task 10.6 (CardsFieldFactory) можно начать параллельно с Phase 9

**Строго последовательно:**
- Phase 7 требует Phase 6 (плагины нужны для config_schema)
- Phase 10 требует Phase 7 + 8 + 9
- Phase 12 требует Phase 10 + 7
- Phase 13 требует Phase 12
- Phase 14 требует всё

---

## Оценка объёма

| Фаза | Задач | Файлов | Примерно строк | Сложность |
|------|-------|--------|---------------|-----------|
| **Phase 6** (Plugins) | **10** | **~25** | **~3000** | **Senior** |
| Phase 7 (Registers) | 3 | 6 | ~800 | Middle+ |
| Phase 8 (StateStore) | 3 | 5 | ~600 | Senior |
| Phase 9 (GUI Foundation) | 4 | 10 | ~1200 | Middle+ |
| Phase 10 (GUI Tabs) | 6 | 20 | ~3000 | Senior |
| Phase 11 (Recipes/Undo) | 3 | 10 | ~1500 | Senior |
| Phase 12 (TopologyBridge) | 3 | 6 | ~1200 | Senior+ |
| Phase 13 (Pipeline Editor) | 4 | 8 | ~2000 | Senior+ |
| Phase 14 (Polish) | 5 | 15 | ~2000 | Mixed |
| **Итого** | **41** | **~105** | **~15300** | |

---

## Ключевые отличия от v1

| Аспект | v1 | v2 (план) |
|--------|-----|-----------|
| Процессы | Хардкод-классы (7 штук) | GenericProcess для всего |
| Плагины | ProcessModule + Service + Adapter (~500 строк) | Plugin `process(items)→items` (~50-150 строк) |
| Регистры | 6 ручных регистров | Автогенерация из plugin config_schema |
| Формы GUI | CardsFieldFactory по регистрам | CardsFieldFactory по Pydantic schema |
| Транспорт GUI→Backend | 3 транспорта (IPC + FieldRouting + DirectAPI) | 1 транспорт (IPC commands) |
| Topology | В коде (default_system.py) | В YAML (topology/*.yaml) |
| Расширение | Новый класс + сервис + адаптер + регистр | Новый plugin.py + строка в YAML |
| Pipeline Editor | Отдельный код | Визуализация topology YAML |
| Рецепты | Отдельная система | Snapshot topology + configs |
| Camera backends | Внутри CameraService (монолит) | Отдельные backend-модули через Protocol |
| v1 код | АРХИВ — только чтение | Вся логика пересоздана заново |
