# Архитектура multiprocess_prototype_v3

Полная техническая спецификация прототипа системы инспекции бутылок.
Этот документ — эталонное описание: по нему можно воспроизвести систему с нуля.

> **Версия:** 2026-04-23 | **Статус:** актуальная

---

## Содержание

1. [Назначение системы](#1-назначение-системы)
2. [Общая архитектура](#2-общая-архитектура)
3. [Фреймворк: ProcessModule и оркестрация](#3-фреймворк-processmodule-и-оркестрация)
4. [Процессы системы](#4-процессы-системы)
5. [Разделяемая память (SHM) и Ring Buffer](#5-разделяемая-память-shm-и-ring-buffer)
6. [IPC: межпроцессное взаимодействие](#6-ipc-межпроцессное-взаимодействие)
7. [Цепочка данных: от камеры до экрана](#7-цепочка-данных-от-камеры-до-экрана)
8. [Обработка кадров и детекция](#8-обработка-кадров-и-детекция)
9. [GUI (PyQt5)](#9-gui-pyqt5)
10. [База данных](#10-база-данных)
11. [Конфигурация и профили](#11-конфигурация-и-профили)
12. [Запуск системы](#12-запуск-системы)
13. [Найденные проблемы и несостыковки](#13-найденные-проблемы-и-несостыковки)

---

## 1. Назначение системы

Система визуальной инспекции бутылок на конвейере:
- Захват видеопотока с N камер (промышленных или веб)
- Детекция дефектов по цвету (Color Blob Detection)
- Визуализация результатов в реальном времени (маски, bounding boxes)
- Сохранение результатов в SQLite
- Управление роботом-отбраковщиком

**Ключевое свойство:** многопроцессная архитектура основанная на собственном фраемворке multiprocess_framework. Каждая функциональная единица — отдельный OS-процесс, общение через роутер (очереди и разделяемую память). Это даёт:
- Параллелизм на уровне ядер CPU
- Изоляцию сбоев (падение одного процесса не убивает систему)
- Масштабирование (добавление камер/процессоров без перестройки)

---

## 2. Общая архитектура

### 2.1 Диаграмма процессов

```
┌──────────────────────────────────────────────────────────────────────┐
│                        SystemLauncher (main.py)                      │
│                              │                                       │
│                    ProcessManagerProcess                              │
│                    (оркестратор, мониторинг)                          │
│                              │                                       │
│    ┌─────────┬────────┬──────┴──────┬──────────┬──────────┬────────┐ │
│    │         │        │             │          │          │        │ │
│  Camera_0  Camera_1  Processor   Renderer    GUI     Database  Robot│ │
│  (захват)  (захват)  (детекция)  (рисовка)  (PyQt5)  (SQLite) (отбр)│ │
│    │         │        │             │          │                   │ │
│    │         │    Worker_0..K       │          │                   │ │
│    │         │   (пул обработки)    │          │                   │ │
│    └─────────┴────────┴─────────────┴──────────┴──────────┴────────┘ │
│                                                                      │
│  ════════════════ Shared Memory (SHM) ═══════════════════════════════│
│  camera_0_frame[0..K]  processor_mask  rendered_frame  mask_frame    │
└──────────────────────────────────────────────────────────────────────┘
```

### 2.2 Слои системы

| Слой | Что делает | Где находится |
|------|-----------|---------------|
| **Фреймворк** | ProcessModule, IPC, SHM, WorkerManager, Router | `multiprocess_framework/modules/` |
| **Backend / Processes** | Бизнес-логика каждого процесса | `backend/processes/` |
| **Services** | Чистая логика без IPC (камера, детекция, рендер) | `services/` |
| **Frontend** | PyQt5 GUI, окна, виджеты | `frontend/` |
| **Registers** | Схемы данных GUI ↔ Backend, роутинг команд | `registers/` |
| **Config** | AppConfig, LoggingConfig, профили | `config/`, `data/` |

### 2.3 Зависимости между слоями

```
Frontend → Registers → Backend/Processes → Services
                ↓               ↓
             Config          Framework
```

**Правила:**
- Services НЕ знают о Framework (чистая бизнес-логика)
- Backend/Processes связывают Services с Framework через адаптеры (Ports)
- Frontend общается с Backend только через роутер менеджер IPC (очереди), НЕ напрямую
- Registers — единый словарь полей, понятный обеим сторонам

### 2.4 Философия данных: единое связанное хранилище

**Принцип:** все данные системы — рецепты, конфигурации процессов, runtime-состояния, настройки
камер, регионы, параметры обработки — это **единая связанная база данных**. Изменение одного
параметра должно автоматически отражаться во всех связанных местах.

Концептуальная модель:

```
┌─────────────────────────────────────────────────────────────────┐
│                  Единое пространство данных                     │
│                                                                 │
│  Конфигурация (что запускать)                                   │
│  ├── Профили         — camera_count, source_type, ring_buffer   │
│  ├── Рецепты         — именованные снимки всех настроек         │
│  └── ProcessConfigs  — per-process dict (class, queues, shm)    │
│                                                                 │
│  Параметры (как работать)                                       │
│  ├── Камеры          — fps, device_id, resolution, тип          │
│  ├── Обработка       — color_range, min_area, max_area          │
│  ├── Регионы         — ROI, crop-зоны, SHM per region           │
│  ├── Визуализация    — bbox, контуры, overlay, show_original    │
│  └── Цепочка (graph) — pipeline_data, операции, связи           │
│                                                                 │
│  Состояние (что происходит сейчас)                              │
│  ├── Статусы         — running / stopped / crashed / failed     │
│  ├── Heartbeat       — last_heartbeat per process               │
│  ├── Метрики         — fps, latency, missed_frames              │
│  └── Детекции        — bbox, area, timestamp → SQLite           │
│                                                                 │
│  Ресурсы (чем оперировать)                                      │
│  ├── Очереди         — system/data per process                  │
│  ├── SHM-регионы     — camera_N_frame, processor_mask, ...      │
│  └── События         — stop, pause per process                  │
└─────────────────────────────────────────────────────────────────┘
```

**Связи между данными (почему «база данных»):**

Данные не изолированы — они образуют граф зависимостей:

```
Профиль (camera_count=3)
  │
  ├──► CameraConfig × 3 (каждая со своим типом, разрешением)
  │       │
  │       ├──► ShmRegionSpec (camera_N_frame, width×height×slots)
  │       ├──► ProcessorConfig (привязан к camera_id, наследует разрешение)
  │       │       └──► ShmRegionSpec (processor_N_mask)
  │       └──► Registers.camera (fps, device_id → GUI-поля)
  │
  ├──► RendererConfig (знает все камерные регионы)
  │       └──► ShmRegionSpec (rendered_frame, mask_frame)
  │
  └──► GuiConfig (camera_configs[] → CameraRegistry в frontend)

Рецепт = снимок всех Registers → применяется → register_update × N → Backend
```

**Текущая реализация — где что живёт:**

| Данные | Хранилище | Доступ |
|--------|-----------|--------|
| Конфиги процессов | SRM → ConfigStore (dict per process) | Записываются при старте, read-only |
| Runtime-состояние | SRM → ProcessStateRegistry (ProcessData) | Обновляются процессами, читает Monitor |
| Очереди, SHM, Events | SRM → QueueRegistry, MemoryManager | Создаются при регистрации процесса |
| Параметры (fps, цвет, ...) | GUI: RegistersManager (Pydantic) | GUI → register_update → Backend |
| Профили | `settings_profiles.yaml` (диск) | Frontend-only, загрузка при старте |
| Рецепты | `settings_recipes.yaml` (диск) | Frontend-only, загрузка/сохранение по запросу |
| Детекции | SQLite (`inspector.db`) | DatabaseProcess — запись, GUI — чтение |

**Текущие разрывы связности (известные, будут закрываться):**

1. **GUI RegistersManager ↔ ConfigStore** — два параллельных хранилища одних и тех же данных.
   GUI не читает ConfigStore, ConfigStore не знает о RegistersManager
2. **Backend → GUI обратная связь** — backend не подтверждает применение настройки.
   GUI не знает, что fps реально изменился на камере
3. **Профили ↔ SRM** — профиль влияет на систему только через `main.py` при старте.
   Нет механизма «применить другой профиль в runtime»
4. **Рецепты ↔ Backend** — рецепт = снимок GUI-регистров, не backend-состояния.
   После применения рецепта backend может рассинхронизироваться

**Целевое состояние (Phase 4 — StateStore):**

> Подробный дизайн: `docs/plans/STATE_STORE_DESIGN.md`
> План реализации: `docs/plans/phase4_state_store_plan.md`

Все данные проходят через единое реактивное дерево с подпиской на изменения:

```
Любой источник (GUI / Backend / Config / Recipe)
  │
  └──► StateStore (TreeStore + Subscriptions, в ProcessManager)
        │
        ├── Дерево: cameras.0.config.fps = 30
        │           cameras.0.state.actual_fps = 28.5
        │           cameras.0.regions.roi_left.processing.nodes.blur_1.params.kernel_size = 5
        │
        ├── Подписки (glob-style):
        │   ├── CameraProcess  ← "cameras.0.config.*"
        │   ├── ProcessorProcess ← "cameras.0.regions.**"
        │   ├── GUI ← "cameras.*.state.*"
        │   └── RecipeEngine ← "**.config.**"
        │
        ├── Dispatch: Delta(path, old, new, source, tx_id)
        │   ├── CameraProcess.set_fps(30)
        │   ├── GUI.update_fps_widget(28.5)  ← подтверждение через state
        │   └── RecipeEngine.mark_dirty()
        │
        └── Persistence (debounced) → YAML
```

Ключевые решения:
- **config / state разделение:** GUI пишет config, Backend пишет state — нет конфликтов
- **Точечные пути:** `cameras.0.regions.roi_left.processing.nodes.blur_1.params.kernel_size`
- **Транзакции:** загрузка рецепта = один batch, не 50 отдельных уведомлений
- **StateProxy:** лёгкий клиент в каждом процессе (Dict at Boundary сохраняется)
- **Рецепт = snapshot config-ветвей** реального состояния, не только GUI

---

## 3. Фреймворк: ProcessModule и оркестрация

### 3.1 ProcessModule — базовый класс процесса

Каждый процесс наследует `ProcessModule`. Жизненный цикл:

```
__init__(name, shared_resources, config)
    │
initialize()
    ├─ _init_configuration()     загрузка конфига из dict
    ├─ _init_queues()            создание/подключение очередей
    ├─ _init_managers()          WorkerManager, CommandManager, RouterManager, LoggerManager
    ├─ _init_communication()     регистрация каналов (очереди, SHM) в RouterManager
    ├─ _register_process_state() регистрация в ProcessStateRegistry
    ├─ _init_system_threads()    message_processor (системный воркер)
    └─ _init_application_threads()  ← ПЕРЕОПРЕДЕЛЯЕТСЯ в каждом процессе
    │
run()                            основной цикл (блокирующий до stop)
    │
shutdown()                       остановка воркеров, очистка ресурсов
```

**Ключевой момент:** `_init_application_threads()` — точка расширения.
Каждый конкретный процесс (Camera, Processor и т.д.) создаёт здесь свои рабочие потоки.

### 3.2 SharedResourcesManager (SRM)

Общий контейнер ресурсов, разделяемый между всеми процессами. Pickle-safe.

```
SharedResourcesManager
├── ConfigStore (dict)              — статические конфиги процессов
├── ProcessStateRegistry            — runtime-состояние: Queue/Event refs
├── QueueRegistry                   — создание очередей
├── EventManager                    — системные Event'ы (stop, pause)
└── MemoryManager                   — SharedMemory: выделение/освобождение
```

**Dict at Boundary (ключевой паттерн):** между процессами передаются ТОЛЬКО `dict`.
SchemaBase на основе Pydantic-модели используются только внутри процесса для валидации. 

### 3.3 WorkerManager и потоки

Внутри каждого процесса — пул потоков (threading). Два режима:

| Режим | Поведение | Пример |
|-------|----------|--------|
| **LOOP** | `while not stop: run()` — бесконечный цикл | capture_worker, processing_worker |
| **TASK** | `run()` однократно, потом выход | разовые операции |

```python
# Создание воркера внутри _init_application_threads():
manager.create_worker(
    name="capture",
    target=self._capture_loop,
    config=ThreadConfig(execution_mode=ExecutionMode.LOOP),
    auto_start=True
)
```

### 3.4 SystemLauncher → ProcessManagerProcess

Цепочка запуска:

```
SystemLauncher.run()
    │
ProcessSpawner.launch_orchestrator()
    ├── Создаёт SharedResourcesManager
    ├── Регистрирует все процессы в SRM (очереди, SHM, события)
    ├── Устанавливает SIGINT/SIGTERM хендлеры
    │
    └── Для каждого процесса:
        Process(target=run_process_function, args=(bundle,))
            ├── Unpickle bundle
            ├── class_loader загружает класс (CameraProcess и т.д.)
            ├── srm.reinitialize_in_child()
            ├── process.initialize()
            ├── process.run()
            └── process.shutdown()
```

**ProcessManagerProcess — постоянный фоновый оркестратор:**

ProcessManagerProcess — это **главный процесс**, который живёт всё время работы системы.
Он не выполняет бизнес-логику (захват, детекцию), а управляет жизненным циклом всех остальных процессов.

Ключевые обязанности:
1. **Контроль процессов** — создание, запуск, остановка, перезапуск любого процесса в системе
2. **Динамическое создание** — может в реальном времени создавать новые процессы и регистрировать для них очереди и разделяемую память (например, для новых регионов/камер)
3. **Heartbeat-мониторинг** — каждый процесс отправляет heartbeat каждые 5с; если heartbeat не приходит 15с → статус `UNRESPONSIVE`
4. **Auto-restart** — при crash (exitcode ≠ 0) или UNRESPONSIVE → автоматический перезапуск с backoff (max 3 попытки, затем статус `FAILED`)
5. **Единая точка доступа** — предоставляет всем процессам общую информацию: конфиги, очереди, разделяемую память через SharedResourcesManager

```
ProcessManagerProcess (фоновый, всегда работает)
├── ProcessRegistry          — реестр OS-процессов (create/start/stop)
├── ProcessMonitor           — heartbeat + liveness + auto-restart
│   ├── _last_heartbeat{}    — время последнего heartbeat per process
│   ├── _restart_counts{}    — счётчик попыток рестарта per process
│   └── RestartPolicy        — enabled, max_retries=3, backoff=2с
├── ProcessPriority          — OS-приоритеты процессов
├── ProcessStatus            — агрегация статусов
└── Встроенные команды:
    ├── process.create/start/stop/restart/list/status
    └── system.shutdown/stats
```

Цикл мониторинга (каждые 0.5с):
```
ProcessMonitor._monitoring_loop()
  ├─ Опрос ProcessStateRegistry → снимок состояний
  ├─ Сравнение с previous_states → детекция изменений
  ├─ _check_heartbeats():
  │   ├─ is_alive() == False → _handle_dead_process() → auto-restart
  │   └─ heartbeat timeout > 15с → UNRESPONSIVE → auto-restart
  └─ broadcast status_changed → все процессы получают уведомление
```

**Процессы как настраиваемые схемы (шаблоны):**

Каждый тип процесса (CameraProcess, ProcessorProcess, RendererProcess и т.д.) — это **схема**
(шаблон) с настраиваемыми параметрами, а не единственный экземпляр. При конфигурации системы
ProcessManager создаёт **N экземпляров** одного шаблона, каждый со своими настройками:

```
CameraProcess (схема/шаблон)
  ├── camera_0  — simulator, 640×480, fps=30, ring_buffer=3
  ├── camera_1  — webcam, 1280×720, device_id=0, fps=25
  └── camera_2  — hikvision, 1920×1080, ip=192.168.1.10

ProcessorProcess (схема/шаблон)
  ├── processor_0  — привязан к camera_0, BGR-детекция
  ├── processor_1  — привязан к camera_1, свои цветовые диапазоны
  └── processor_2  — привязан к camera_2, другой min_area

RendererProcess (схема/шаблон)
  └── renderer     — один на все камеры (или N при необходимости)
```

Это работает потому что:
- Конфиг каждого экземпляра — отдельный `ProcessLaunchConfig` (dict) с уникальным `name`
- Один и тот же класс (`CameraProcess`) инстанцируется в отдельном OS-процессе с разным конфигом
- У каждого экземпляра свои очереди, SHM-регионы, stop_event
- ProcessManager хранит конфиг каждого экземпляра в `_process_configs` и может пересоздать его при restart

Пример масштабирования (4 камеры → 4 процессора → 1 рендерер → 1 GUI):
```
AppConfig(cameras=[cam0, cam1, cam2, cam3])
  → model_post_init() автоматически создаёт processors=[proc0, proc1, proc2, proc3]
  → all_process_configs() = [cam0, cam1, cam2, cam3, proc0, proc1, proc2, proc3,
                              renderer, robot, database, gui, worker_0..K]
  → SystemLauncher создаёт по Bundle на каждый → ProcessManager запускает все
```

**Bundle (пакет запуска):**
```python
bundle = {
    "class_path": "backend.processes.camera.CameraProcess",
    "name": "camera_0",
    "shared_resources": srm,       # pickle-safe
    "config": {...},               # dict (уникальный для этого экземпляра)
    "stop_event": Event(),         # индивидуальный для процесса
}
```

### 3.5 Graceful Shutdown

```
Ctrl+C (SIGINT)
  └─ ProcessSpawner._signal_handler()
     └─ _stop_event.set()          # глобальный сигнал
        │
  ProcessManagerProcess.shutdown()
     ├─ ProcessMonitor.stop()
     ├─ Для каждого процесса:
     │   stop_events[name].set()   # индивидуальный сигнал
     │   join(timeout=5s)
     │   terminate() если завис
     └─ Очистка SHM, очередей
```

---

## 4. Процессы системы

### 4.1 Таблица процессов

| Процесс | Класс | Назначение | Кол-во экземпляров |
|----------|-------|-----------|-------------------|
| **camera_N** | `CameraProcess` | Захват кадров с устройства | N (по числу камер) |
| **processor** | `ProcessorProcess` | Детекция дефектов на кадрах | 1 |
| **processor_worker_K** | `ProcessorWorkerProcess` | Воркер пула обработки (Phase 5c) | 0..K (опционально) |
| **renderer** | `RendererProcess` | Наложение масок и bbox'ов на кадр | 1 (или 0 в headless) |
| **gui** | `GuiProcess` | PyQt5 интерфейс | 1 |
| **database** | `DatabaseProcess` | SQLite хранилище детекций | 1 |
| **robot** | `RobotProcess` | Управление отбраковщиком | 1 |

### 4.2 CameraProcess

**Файлы:** `backend/processes/camera/`

**Что делает:**
1. Запускает CameraService с выбранным бэкендом (simulator/webcam/hikvision/file)
2. В цикле: захват кадра → resize до SHM-размеров → запись в Ring Buffer
3. Отправляет IPC-сообщение `frame_ready` с координатами кадра в SHM
4. Обрабатывает команды от GUI (смена типа камеры, параметров)

**Компоненты:**
```
CameraProcess (ProcessModule)
├── CameraService          — бизнес-логика захвата + FPS throttling
│   └── Backend            — simulator | webcam | hikvision | file
├── CameraAdapter          — IPC порт (реализует CameraOutputPort)
├── RingBufferWriter       — запись кадров в K SHM-слотов по кругу
├── _capture_worker        — LOOP-поток: захват → SHM → IPC
└── command handlers       — set_camera_type, set_parameters, enum_devices
```

**Бэкенды камер:**

| Бэкенд | Источник | Enum (перечисление устройств) |
|--------|---------|------|
| `simulator` | Генерирует цветные прямоугольники | Нет |
| `webcam` | `cv2.VideoCapture(device_id)` | Да |
| `hikvision` | Hikvision SDK (IP-камеры) | Да |
| `file` | Видеофайл с диска | Нет |

**Переключение типа камеры (CameraService.switch_camera_type):**
```
1. Пауза capture_worker
2. Закрытие текущего бэкенда
3. Ожидание освобождения устройства (0.3с для USB/сетевых)
4. Создание нового бэкенда
5. Возобновление capture_worker
```

### 4.3 ProcessorProcess

**Файлы:** `backend/processes/processor/`

**Что делает:**
1. Получает `frame_ready` от камеры
2. Читает кадр из SHM через FrameShmMiddleware
3. Запускает ColorBlobDetector → детекции + маска
4. (Опционально) запускает цепочку обработки (Phase 5a/5b/5c)
5. Записывает маску в SHM (`processor_mask`)
6. Отправляет `detection_result` в Renderer и GUI

**Три режима обработки:**

| Режим | Условие | Как работает |
|-------|---------|-------------|
| **Линейный** | `workers_per_processor ≤ 1` | Последовательное выполнение шагов |
| **Phase 5b** | `workers_per_processor > 1` | `ChainThreadPool` — параллельные шаги внутри процесса |
| **Phase 5c** | `worker_pool_size > 0` | `WorkerPoolDispatcher` — задачи отправляются в отдельные процессы |

**Phase 5c: WorkerPoolDispatcher:**
```
Processor → dispatch(operation, params, frame_shm) → Worker_0
                                                   → Worker_1
                                                   → Worker_K
            ← worker_task_response (результат в SHM worker_K_result)
```
Round-robin балансировка. Backpressure: при перегрузке — drop-oldest.

### 4.4 ProcessorWorkerProcess (Phase 5c)

**Файлы:** `backend/processes/processor_worker/`

**Что делает:**
1. Ожидает `worker_task_request` от Processor
2. Читает входной кадр из SHM (по имени/индексу из запроса)
3. Загружает операцию из каталога (`processing_catalog.yaml`)
4. Выполняет `operation.execute(frame, context)`
5. Записывает результат в свой SHM-слот (`worker_K_result`)
6. Отправляет `worker_task_response` обратно в Processor

**Активируется только если** `AppConfig.worker_pool_size > 0`.

### 4.5 RendererProcess

**Файлы:** `backend/processes/renderer/`

**Что делает:**
1. Получает `detection_result` от Processor
2. Читает оригинальный кадр из SHM камеры
3. Читает маску из SHM процессора
4. RendererService рисует bounding boxes + контуры на кадре
5. Записывает `rendered_frame` и `mask_frame` в свои SHM-слоты
6. Отправляет `rendered_frame_ready` в GUI

**Отключается** при `display_enabled = False` (headless режим).

### 4.6 GuiProcess

**Файлы:** `backend/processes/gui/` + `frontend/`

**Что делает:**
1. Запускает Qt event loop (PyQt5)
2. Таймер 16мс (≈60fps) опрашивает IPC-очередь (`_poll_messages`)
3. При получении `rendered_frame_ready` — читает кадр из SHM → обновляет дисплей
4. Обрабатывает сообщения: `status`, `error`, `fps_update`, `parameters_response`
5. Отправляет команды пользователя в backend через `GuiCommandHandler`

**Связь GUI → Backend (команды):**
```
Пользователь нажимает кнопку
  → GuiCommandHandler.handle_xxx()
    → RoutedCommandSender.send_routed_command(command_id, args)
      → resolve_command_targets(command_id) → ["camera_0"]
        → MessageAdapter.command(targets=["camera_0"], ...)
          → router.send(msg)
            → IPC: в очередь camera_0
```

### 4.7 DatabaseProcess

**Файлы:** `backend/processes/database/`

**Что делает:**
1. При инициализации создаёт таблицу `detections` в SQLite
2. Получает данные детекций через IPC
3. Сохраняет через `DatabaseService` (SQL INSERT)

### 4.8 RobotProcess

**Файлы:** `backend/processes/robot/`

**Что делает:**
1. Получает команды на отбраковку из GUI/системы
2. `RobotService` выполняет физическое действие (с задержкой `reject_delay`)
3. Отправляет `action_completed` обратно

---

## 5. Разделяемая память (SHM) и Ring Buffer

### 5.1 Зачем SHM

Кадры изображений — это большие numpy-массивы (640×480×3 = ~900 КБ).
Передавать их через `multiprocessing.Queue` (pickle) — медленно.
SHM позволяет записать кадр один раз, а читать из любого процесса по указателю.

### 5.2 Структура SHM

| Имя SHM | Размер | Владелец (пишет) | Читатели |
|---------|--------|-------------------|---------|
| `camera_N_frame[0..K-1]` | (480, 640, 3) × K | Camera_N | Processor, Renderer |
| `processor_mask` | (480, 640, 3) | Processor | Renderer |
| `rendered_frame` | (480, 640, 3) | Renderer | GUI |
| `mask_frame` | (480, 640, 3) | Renderer | GUI |
| `worker_K_result` | (480, 640, 3) | Worker_K | Processor |

Размеры определяются константами: `CAMERA_SHM_WIDTH = 640`, `CAMERA_SHM_HEIGHT = 480`.

### 5.3 Ring Buffer (AD-6)

**Файл:** `backend/shm/ring_buffer.py`

**Проблема:** один кадр в SHM — если камера пишет быстрее чем читатель, данные перезаписываются.

**Решение:** K слотов (по умолчанию K=3), запись по кругу.

```
Слоты:  [0] [1] [2]
Write→   ●   ·   ·     seq_id=1
Write→   ·   ●   ·     seq_id=2
Write→   ·   ·   ●     seq_id=3
Write→   ●   ·   ·     seq_id=4  ← перезаписал слот 0
```

**RingBufferWriter** (в CameraProcess):
```python
class RingBufferWriter:
    def write(self, frame: np.ndarray) -> tuple[int, int]:
        slot = self._seq_id % self._k      # текущий слот
        shm.write(frame, index=slot)        # запись в SHM
        self._seq_id += 1                   # монотонный счётчик
        return (slot, self._seq_id)
```

**RingBufferReader** (в ProcessorProcess, RendererProcess):
```python
class RingBufferReader:
    def read(self, slot: int, seq_id: int) -> tuple[np.ndarray, dict]:
        if seq_id <= self._last_read_seq:
            return None  # уже читали этот кадр
        frame = shm.read(index=slot)
        missed = seq_id - self._last_read_seq - 1
        self._last_read_seq = seq_id
        return (frame, {"missed_frames": missed})
```

**Политика при отставании:**
- Если consumer отстал на K-1 кадров, writer принудительно двигает его вперёд
- Это значит: лучше пропустить кадр, чем читать устаревший

### 5.4 FrameShmMiddleware

**Обёртка над SHM** для процессов-читателей. Подключается при инициализации и автоматически читает кадр из SHM при получении IPC-сообщения с координатами (slot, seq_id).

---

## 6. IPC: межпроцессное взаимодействие

### 6.1 Типы сообщений

Все сообщения — `dict` (Dict at Boundary). 9 типов:

| Тип | Назначение | Пример |
|-----|-----------|--------|
| `command` | Вызов функции с аргументами | `set_camera_type("webcam")` |
| `request` | Запрос с ожиданием ответа | `enum_devices("webcam")` |
| `response` | Ответ на request | `{"devices": [...]}` |
| `data` | Данные/кадры с типом `data_type` | `frame_ready`, `detection_result` |
| `event` | Событие приложения | `camera_connected` |
| `log` | Запись лога | `{"level": "info", "msg": "..."}` |
| `system` | Системное управление | `pause`, `shutdown` |
| `broadcast` | Multi-target | `status_update` |
| `custom` | Пользовательский | — |

### 6.2 Потоки сообщений

```
                     register_update
              GUI ─────────────────────► Camera
              GUI ─────────────────────► Processor
              GUI ─────────────────────► Renderer

                       frame_ready
           Camera ─────────────────────► Processor

                    detection_result
         Processor ─────────────────────► Renderer

                  rendered_frame_ready
          Renderer ─────────────────────► GUI

                     status, error
     Camera/Proc ──────────────────────► GUI

                   fps_update
     Camera/Proc ──────────────────────► GUI

                 worker_task_request
         Processor ─────────────────────► Worker_K

                worker_task_response
          Worker_K ─────────────────────► Processor

                    system commands
              GUI ─────────────────────► Robot
```

### 6.3 Очереди (Queue)

Каждый процесс имеет два типа очередей:
- **system** — системные команды (stop, pause, register_update)
- **data** — данные приложения (frame_ready, detection_result)

Очереди создаются при регистрации процесса в SRM:
```python
srm.register_process("camera_0", {
    "queues": {"system": {"maxsize": 100}, "data": {"maxsize": 50}},
    ...
})
```

### 6.4 RouterManager — единая точка коммуникации

**Ключевой принцип:** вся коммуникация в системе — как внутри процесса, так и между
процессами — идёт **исключительно через RouterManager**. Процессы не обращаются к очередям
или SHM напрямую. Вместо этого очереди и SHM-слоты регистрируются как **каналы** в роутере,
и весь обмен данными происходит через эти каналы.

**Каналы (channels):**
Канал — это абстракция транспорта, зарегистрированная под определённую нужду:

| Тип канала | Транспорт | Для чего |
|------------|-----------|----------|
| `system` | `multiprocessing.Queue` | Системные команды (stop, pause, register_update) |
| `data` | `multiprocessing.Queue` | Данные приложения (frame_ready, detection_result) |
| `shm` | `SharedMemory` | Кадры, маски (zero-copy через указатель) |

При `_init_communication()` каждый процесс регистрирует свои каналы в RouterManager:
- Очереди из SRM → каналы `system` и `data`
- SHM-слоты → каналы для zero-copy передачи кадров
- После этого `send_message()`, `receive_message()`, `broadcast()` — всё через роутер

```
Отправка (процесс A → процесс B):
  router.send_async(msg, priority="high")
    → AsyncSender._queue (PriorityQueue)
      → background thread → MiddlewarePipeline → channel.send()
        → target_process.queue.put(msg_dict)

Приём (внутри процесса):
  AsyncReceiver (background thread)
    → poll channels каждые 10мс
      → message_dispatcher.dispatch(msg)
        → зарегистрированный callback (handler)
```

**Почему через роутер, а не напрямую:**
- Единообразие — один API для очередей, SHM, broadcast
- Middleware — логирование, валидация, приоритизация на уровне роутера
- Масштабирование — добавление нового канала не требует изменений в процессах-отправителях
- Мониторинг — роутер знает обо всех сообщениях, может собирать метрики

### 6.5 Маршрутизация команд (Registers)

**Файл:** `registers/commands/routing.py`

GUI отправляет команды по имени → система определяет целевой процесс:

```python
COMMAND_TO_REGISTER_KEY = {
    "set_fps":           "camera",
    "set_camera_type":   "camera",
    "enum_devices":      "camera",
    "set_color_range":   "processor",
    "set_min_area":      "processor",
    "set_show_original": "renderer",
}

# Пример:
resolve_command_targets("set_fps") → ["camera_0"]
resolve_command_targets("set_color_range") → ["processor"]
```

---

## 7. Цепочка данных: от камеры до экрана

### 7.1 Полная цепочка (happy path)

```
[1] Camera._capture_worker (LOOP, каждый 1/fps секунд)
    │
    ├─ backend.read_frame()           ← захват с устройства/симулятора
    ├─ cv2.resize(frame, (640, 480))  ← масштабирование до SHM-размера
    ├─ RingBufferWriter.write(frame)  ← запись в SHM, получение (slot, seq_id)
    └─ adapter.send("frame_ready", {slot_index, seq_id, camera_id})
                    │
                    │ IPC: через data-очередь
                    ▼
[2] Processor._processing_worker (LOOP)
    │
    ├─ receive_message("frame_ready")
    ├─ FrameShmMiddleware.on_receive() ← чтение кадра из SHM
    ├─ ColorBlobDetector.detect(frame)
    │   ├─ BGR range mask             ← двоичная маска по цветовому диапазону
    │   ├─ cv2.findContours()         ← поиск контуров
    │   └─ → detections, mask, contours
    ├─ SHM.write(mask, "processor_mask")
    └─ adapter.send("detection_result", {detections, mask_slot, camera_id, seq_id})
                    │
                    │ IPC
                    ▼
[3] Renderer._render_worker (LOOP)
    │
    ├─ receive_message("detection_result")
    ├─ FrameShmMiddleware: читает оригинальный кадр из camera SHM
    ├─ SHM.read("processor_mask")     ← читает маску
    ├─ RendererService.render_frame(original, mask, detections)
    │   ├─ cv2.rectangle()            ← bounding boxes
    │   ├─ cv2.drawContours()         ← контуры
    │   └─ overlay mask               ← полупрозрачная маска
    ├─ SHM.write(rendered, "rendered_frame")
    ├─ SHM.write(mask_vis, "mask_frame")
    └─ adapter.send("rendered_frame_ready", {frame_id})
                    │
                    │ IPC
                    ▼
[4] GUI._poll_messages (Timer, каждые 16мс)
    │
    ├─ receive_message("rendered_frame_ready")
    ├─ SHM.read("rendered_frame")     ← визуализированный кадр
    ├─ SHM.read("mask_frame")         ← маска для второго окна
    └─ MainWindow.update_frame(rendered, mask)
        └─ QLabel.setPixmap(QImage(rendered))  ← отображение на экране
```

### 7.2 Временные характеристики

| Участок | Время | Лимитирующий фактор |
|---------|-------|---------------------|
| Захват кадра | ~1/fps с (40мс при 25fps) | FPS камеры |
| Запись в SHM | <1мс | Копирование numpy массива |
| Передача IPC | 1-5мс | Очередь + pickle мелкого dict |
| Детекция (BGR) | 5-20мс | CPU, размер кадра |
| Рендер + overlay | 2-10мс | cv2 drawing |
| Чтение SHM в GUI | <1мс | Копирование numpy |
| QImage → QLabel | 1-3мс | Qt pixel format conversion |

**Итого:** end-to-end latency ≈ 50-80мс (при 25fps камере).

### 7.3 Обработка пропущенных кадров

Если Processor не успевает обработать кадр до прихода следующего:
- RingBufferReader обнаруживает gap в seq_id
- Кадр пропускается (missed_frames > 0)
- Статистика пропусков логируется
- GUI показывает актуальный кадр, не зависший

---

## 8. Обработка кадров и детекция

### 8.1 ColorBlobDetector

**Файл:** `services/processor/detection.py`

Простой детектор цветных пятен по BGR-диапазону:

```python
class ColorBlobDetector:
    def __init__(self, color_lower, color_upper, min_area, max_area):
        self._color_lower = np.array(color_lower)  # [B_min, G_min, R_min]
        self._color_upper = np.array(color_upper)  # [B_max, G_max, R_max]
        self._min_area = min_area                   # мин. площадь пятна (пиксели)
        self._max_area = max_area                   # макс. площадь (0 = без ограничения)

    def detect(self, frame: np.ndarray):
        # 1. Бинарная маска: пиксель в диапазоне [lower, upper]
        mask = np.all((frame >= lower) & (frame <= upper), axis=2)
        
        # 2. Площадь пятна = число True пикселей
        area = np.count_nonzero(mask)
        
        # 3. Фильтр по площади
        if area < min_area or (max_area > 0 and area > max_area):
            return ([], empty_mask, [])
        
        # 4. Bounding box: min/max координат True пикселей
        ys, xs = np.where(mask)
        bbox = (xs.min(), ys.min(), xs.max(), ys.max())
        
        # 5. Контуры через OpenCV
        contours, _ = cv2.findContours(mask, RETR_EXTERNAL, CHAIN_APPROX_SIMPLE)
        
        return (detections, mask_display, contours)
```

**Результат детекции:**
```python
detection = {
    "bbox": [x1, y1, x2, y2],    # ограничивающий прямоугольник
    "center": [cx, cy],           # центр масс
    "area": 1234                  # площадь в пикселях
}
```

### 8.2 Каталог обработки (Processing Catalog)

**Файл:** `data/processing_catalog.yaml`

YAML-каталог операций — расширяемый список обработок:

```yaml
blur:
  name: "Gaussian Blur"
  module_path: "services.processor.operations.gaussian_blur"
threshold:
  name: "Binary Threshold"
  module_path: "services.processor.operations.threshold"
```

Каждая операция — Python-класс с методом `execute(frame, context) → frame`.
Загружается лениво по `module_path`.

### 8.3 Цепочка обработки (Processing Chain)

**Файлы:** `services/processor/chain/`

Цепочка обработки = последовательность операций из каталога:

```
GraphRunnableBuilder
  ├── input: ProcessingNode (из GUI graph editor)
  ├── build(): nodes → ChainRunnable
  └── output: ChainRunnable.run(frame) → result_frame

ChainRunnable = [Step1, Step2, Step3]
  Step1: blur(frame) → blurred
  Step2: threshold(blurred) → binary
  Step3: detect(binary) → detections
```

**Phase 5b — параллельные шаги:**
Если шаги независимы, ChainThreadPool выполняет их параллельно:
```
Step1 ──┐
Step2 ──┼── ThreadPool → [result1, result2, result3]
Step3 ──┘
```

### 8.4 Graph Editor (GUI)

Пользователь собирает цепочку обработки визуально в node-based редакторе:
- Каждый узел = операция из каталога
- Связи = потоки данных между операциями
- Сохраняется как `pipeline_data` → отправляется в Processor через `register_update`
- Processor вызывает `rebuild_runnables(pipeline_data)` → пересоздаёт цепочку

---

## 9. GUI (PyQt5)

### 9.1 Архитектура Frontend

```
GuiProcess.run()
  └── FrontendLauncher.run()
        ├── build_config()        → FrontendConfig (dict)
        ├── build_registers()     → RegistersManager + connection_map
        ├── register_windows()
        │   ├── LoadingWindow     ← показывается 2 секунды при старте
        │   └── MainWindow        ← основное окно с табами
        └── FrontendManager.run() ← запуск Qt event loop
```

### 9.2 Структура MainWindow

```
MainWindow (QMainWindow)
├── TabWidget (QTabWidget)
│   ├── CameraTab          — выбор камеры, enum устройств, параметры
│   ├── ProcessingTab      — параметры детекции (цвет, площадь)
│   ├── RendererTab        — настройки визуализации (bbox, контуры)
│   ├── GraphEditorTab     — node-based редактор цепочки обработки
│   ├── CropRegionsTab     — области интереса (ROI)
│   └── RecipesTab         — управление рецептами (сохранение/загрузка)
│
├── DisplayWindow          — отображение видео (original + mask)
├── StatusBar              — FPS, номер кадра, статус камеры
└── Menu                   — настройки, справка
```

### 9.3 Менеджеры Frontend

| Менеджер | Назначение |
|----------|-----------|
| `SettingsYamlStore` | Загрузка/сохранение `settings_profiles.yaml` |
| `RecipeManager` | Управление рецептами (presets настроек) |
| `CameraRegistry` | Реестр активных камер (`camera_id → status`) |
| `SettingsProfileManager` | Выбор профиля настроек |

### 9.4 Цикл обработки сообщений в GUI

```python
# Timer каждые 16мс (≈60fps)
def _poll_messages(self):
    msg = receive_message(timeout=0.001, channel="data")
    if msg is None:
        return

    match msg.data_type:
        case "rendered_frame_ready":
            frame = shm.read("rendered_frame")
            mask = shm.read("mask_frame")
            display_window.update(frame, mask)
        
        case "status":
            status_bar.update(msg.data)
        
        case "fps_update":
            fps_label.setText(f"FPS: {msg.data['fps']:.1f}")
        
        case "error":
            show_error_dialog(msg.data["message"])
        
        case "enum_devices_response":
            camera_tab.populate_devices(msg.data["devices"])
        
        case "parameters_response":
            processing_tab.update_values(msg.data)
```

### 9.5 Registers: схема данных GUI ↔ Backend

**Файлы:** `registers/`

Registers — это описание всех полей, которыми GUI и Backend обмениваются:

```python
# Пример: GuiCameraRegisters
class GuiCameraRegisters(SchemaBase):
    camera_type: str = "simulator"     # Какой бэкенд камеры
    camera_id: int = 0                 # Идентификатор камеры
    fps: int = 30                      # Целевой FPS
    device_id: int = 0                 # ID устройства (для webcam)
    # ...каждое поле с FieldRouting → целевой процесс
```

Когда пользователь меняет поле в GUI:
```
GUI: registers["camera"].camera_type = "webcam"
  → send_callback(register_name="camera", field="camera_type", value="webcam")
    → IPC: register_update → camera_0
      → CameraProcess.handlers["camera_type"](value="webcam")
        → CameraService.switch_camera_type("webcam")
```

---

## 10. База данных

### 10.1 Схема

**Файл:** `services/database/schema.py`

```python
class DetectionSchema(SchemaBase):
    id: Optional[int] = None           # PK, autoincrement
    timestamp: float = 0.0             # время детекции (unix)
    frame_name: str = ""               # имя камеры
    frame_id: int = 0                  # seq_id кадра
    x1: int = 0                        # bbox left
    y1: int = 0                        # bbox top
    x2: int = 0                        # bbox right
    y2: int = 0                        # bbox bottom
    center_x: int = 0                  # центр X
    center_y: int = 0                  # центр Y
    area: int = 0                      # площадь пятна
```

**SQL:**
```sql
CREATE TABLE IF NOT EXISTS detections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp REAL,
    frame_name TEXT,
    frame_id INTEGER,
    x1 INTEGER, y1 INTEGER, x2 INTEGER, y2 INTEGER,
    center_x INTEGER, center_y INTEGER,
    area INTEGER
);
```

### 10.2 Поток данных в БД

```
Processor.detect()
  → detection = {bbox, center, area, frame_id, camera_id}
    → IPC: detection_data → DatabaseProcess
      → DatabaseService.save(DetectionSchema(**detection))
        → SQL INSERT INTO detections (...)
```

### 10.3 Ограничения текущей реализации

- Нет индексов кроме PK (потенциально медленные SELECT по timestamp/frame_id)
- Нет очистки старых записей (таблица растёт бесконечно)
- Нет batch INSERT (каждая детекция — отдельная транзакция)
- SQLite single-writer → потенциальное узкое место при высоком FPS

---

## 11. Конфигурация и профили

### 11.1 AppConfig (корневой конфиг)

**Файл:** `config/app.py`

```python
class AppConfig(SchemaBase):
    logging: LoggingConfig
    cameras: list[CameraConfig] = []    # N камер (гетерогенных!)
    processor: ProcessorConfig
    renderer: RendererConfig
    robot: RobotConfig
    database: DatabaseConfig
    gui: GuiConfig
    stop_timeout: float = 5.0           # таймаут graceful shutdown
    worker_pool_size: int = 0           # Phase 5c: 0 = отключено
    display_enabled: bool = True        # False = headless (без renderer)
```

**Генерация списка процессов:**
```python
def all_process_configs(self) -> list:
    configs = []
    for cam in self.cameras:
        configs.append(cam)              # N CameraProcess'ов
    configs.append(self.processor)
    if self.display_enabled:
        configs.append(self.renderer)
    configs.append(self.robot)
    configs.append(self.database)
    configs.append(self.gui)
    for i in range(self.worker_pool_size):
        configs.append(ProcessorWorkerConfig(worker_index=i))
    return configs
```

### 11.2 Профили настроек

**Файл:** `data/settings_profiles.yaml`

```yaml
version: 1
current_profile: default
profiles:
  default:
    camera_count: 1                     # число камер
    camera_source_type: simulator       # тип бэкенда по умолчанию
    ring_buffer_size: 3                 # K слотов Ring Buffer
    worker_pool_size: 0                 # Phase 5c отключен
    shm_budget_mb: 512                  # лимит SHM
    workers_per_processor: 2            # Phase 5b потоков
    display_count: 2                    # число окон отображения
  production:
    camera_count: 4
    camera_source_type: hikvision
    ring_buffer_size: 5
    worker_pool_size: 2
```

### 11.3 Рецепты

**Файл:** `data/settings_recipes.yaml`

Рецепт = именованный снепшот всех настроек (камеры + обработка + визуализация).
Пользователь может сохранить текущие настройки как рецепт и загрузить позже.

### 11.4 Каталог обработки

**Файл:** `data/processing_catalog.yaml`

Определяет доступные операции для Graph Editor:
```yaml
operation_ref:
  name: "Человекочитаемое имя"
  module_path: "services.processor.operations.module_name"
```

---

## 12. Запуск системы

### 12.1 Точки входа

**Вариант 1 — через корневой run.py:**
```bash
cd Inspector_bottles
python run.py          # → запуск v3 (по умолчанию)
python run.py v2       # → запуск v2
```

**Вариант 2 — напрямую:**
```bash
cd Inspector_prototype/multiprocess_prototype_v3
python run.py
```

### 12.2 Последовательность запуска

```
run.py (venv detection)
  │
  ├── Проверяет наличие .venv
  ├── Если Python не из venv → re-exec с правильным Python
  │
  └── main.py
      │
      ├── _load_cameras_from_profile()
      │   └── Читает settings_profiles.yaml
      │       → camera_count, camera_source_type, ring_buffer_size, ...
      │
      ├── AppConfig(cameras=[...], processor=..., ...)
      │
      ├── SystemLauncher(stop_timeout=5.0)
      │   └── for cfg in app.all_process_configs():
      │       launcher.add_process(*process(cfg))
      │                            ↑
      │                process() = Pydantic → (name, dict)
      │
      └── launcher.run()
          │
          └── ProcessSpawner.launch_orchestrator()
              ├── SRM: register_process() × N
              ├── Process.start() × N
              │   ├── camera_0
              │   ├── camera_1 (если camera_count > 1)
              │   ├── processor
              │   ├── renderer (если display_enabled)
              │   ├── database
              │   ├── robot
              │   ├── gui
              │   └── worker_0..K (если worker_pool_size > 0)
              │
              └── wait() → Ctrl+C → graceful shutdown
```

### 12.3 Порядок запуска процессов

| # | Процесс | Приоритет | Зависит от |
|---|---------|-----------|-----------|
| 1 | ProcessManagerProcess | — | — (оркестратор) |
| 2 | Camera_0..N | HIGH | SHM выделен |
| 3 | Processor | NORMAL | Camera SHM существует |
| 4 | Renderer | NORMAL | Camera + Processor SHM |
| 5 | Database | NORMAL | — |
| 6 | Robot | NORMAL | — |
| 7 | GUI | NORMAL | Renderer SHM (для чтения кадров) |
| 8 | Worker_0..K | NORMAL | Processor (для получения задач) |

---

## 13. Найденные проблемы и несостыковки

### 13.1 Архитектурные

**P1. Processor — единая точка отказа (single point of failure)**
- Все камеры отправляют кадры в один Processor
- При его зависании — вся детекция останавливается
- **Рекомендация:** поддержка N Processor'ов (по одному на камеру или группу)

**P2. Отсутствие heartbeat/health check между процессами**
- ProcessMonitor проверяет `is_alive()` (жив ли OS-процесс)
- Но НЕ проверяет: обрабатывает ли процесс сообщения, не завис ли в бесконечном цикле
- **Рекомендация:** периодический heartbeat + watchdog таймер

**P3. Жёсткая привязка SHM-размеров**
- `CAMERA_SHM_WIDTH = 640`, `CAMERA_SHM_HEIGHT = 480` — константы
- Все процессы должны использовать одинаковые размеры
- При изменении разрешения камеры — нужно менять константы и перезапускать
- **Рекомендация:** размеры SHM из конфига, динамическая аллокация

**P4. GUI опрашивает очередь по таймеру (polling), а не по событию**
- `_poll_messages()` каждые 16мс — лишние wake-up'ы при отсутствии кадров
- **Рекомендация:** Qt signal от IPC-адаптера при поступлении сообщения

### 13.2 Производительность

**P5. Нет batch-записи в БД**
- Каждая детекция = отдельный INSERT
- При 25fps × 5 детекций/кадр = 125 INSERT/с
- SQLite может стать узким местом
- **Рекомендация:** batch INSERT каждые N детекций или каждые T секунд

**P6. Ring Buffer не отслеживает множественных читателей корректно**
- Writer знает про consumers, но при добавлении нового consumer в runtime — нужна перерегистрация
- **Рекомендация:** динамическая регистрация/дерегистрация читателей

**P7. Отсутствие метрик latency**
- Нет измерения end-to-end задержки (от захвата кадра до отображения)
- FPS измеряется, но latency — нет
- **Рекомендация:** timestamp в metadata кадра, измерение на каждом этапе

### 13.3 Конфигурация

**P8. Дублирование SHM-размеров в разных конфигах**
- `CameraConfig.resolution_width/height` vs `CAMERA_SHM_WIDTH/HEIGHT`
- Потенциальное рассогласование: камера может захватывать 1920×1080, а SHM = 640×480
- Resize происходит в CameraService, но если забыть — crash или corruption

**P9. settings_profiles.yaml не валидируется при загрузке**
- Если пользователь укажет `camera_count: -1` — поведение неопределено
- **Рекомендация:** Pydantic-валидация при загрузке профиля

### 13.4 Устойчивость

**P10. Нет восстановления после краша процесса**
- Если CameraProcess упал (например, камера отключилась):
  - ProcessMonitor зафиксирует `is_alive() = False`
  - Но автоматический перезапуск не реализован
- **Рекомендация:** auto-restart политика в ProcessManagerProcess

**P11. SHM cleanup при аварийном завершении**
- Если процесс убит kill -9, SHM-сегменты остаются в ОС
- На Linux: `/dev/shm/` захламляется
- На Windows: cleanup при закрытии handle, но не гарантирован
- **Рекомендация:** cleanup утилита при старте + atexit handler

### 13.5 GUI

**P12. Qt thread safety**
- GUI обновляет виджеты из `_poll_messages()` (вызывается из Qt timer = main thread) — ок
- Но если добавить callback из IPC-потока напрямую в виджет — нарушение thread safety
- **Рекомендация:** все обновления GUI строго через `QTimer` или `QMetaObject.invokeMethod`

**P13. Отсутствие обработки потери связи с Backend**
- Если все backend-процессы упали — GUI продолжает показывать последний кадр
- Нет индикации "Backend не отвечает"
- **Рекомендация:** watchdog в GUI: если нет `rendered_frame_ready` > N секунд → показать предупреждение

---

## Приложение A: Структура файлов

```
multiprocess_prototype_v3/
├── __init__.py
├── run.py                          # точка входа (venv detection)
├── main.py                         # оркестрация AppConfig → SystemLauncher
├── camera_policy.py                # типы камер, enum-политика
│
├── config/
│   ├── app.py                      # AppConfig: корневой конфиг
│   └── logging.py                  # LoggingConfig: настройка логов
│
├── backend/
│   ├── helpers.py                  # утилиты register_update + IPC
│   ├── shm/
│   │   └── ring_buffer.py          # RingBufferWriter/Reader (AD-6)
│   ├── routing/
│   │   └── frame_router_setup.py   # маршрутизация кадров
│   └── processes/
│       ├── camera/                 # CameraProcess (захват)
│       │   ├── process.py
│       │   ├── adapter.py          # CameraAdapter (IPC port)
│       │   ├── commands.py         # таблица команд
│       │   ├── handlers.py         # обработчики register_update
│       │   └── config.py           # CameraConfig (Pydantic)
│       ├── processor/              # ProcessorProcess (детекция)
│       │   ├── process.py
│       │   ├── adapter.py
│       │   ├── commands.py
│       │   ├── handlers.py
│       │   └── config.py
│       ├── processor_worker/       # ProcessorWorkerProcess (пул Phase 5c)
│       │   ├── process.py
│       │   ├── adapter.py
│       │   ├── commands.py
│       │   └── config.py
│       ├── renderer/               # RendererProcess (визуализация)
│       │   ├── process.py
│       │   ├── adapter.py
│       │   ├── commands.py
│       │   └── config.py
│       ├── gui/                    # GuiProcess (PyQt5 frontend)
│       │   ├── process.py
│       │   ├── adapter.py
│       │   ├── handlers.py
│       │   └── config.py
│       ├── database/               # DatabaseProcess (SQLite)
│       │   └── process.py
│       └── robot/                  # RobotProcess (отбраковка)
│           ├── process.py
│           └── service.py
│
├── services/
│   ├── camera/
│   │   ├── service.py              # CameraService (захват + FPS throttle)
│   │   ├── backends/               # simulator, webcam, hikvision, file
│   │   ├── ports.py                # CameraOutputPort (interface)
│   │   └── constants.py            # SHM resolution constants
│   ├── processor/
│   │   ├── service.py              # ProcessorService (обработка кадров)
│   │   ├── detection.py            # ColorBlobDetector (BGR range)
│   │   ├── chain/                  # цепочка обработки
│   │   │   ├── runner.py           # ChainRunnable, ChainResult
│   │   │   ├── builder.py          # GraphRunnableBuilder
│   │   │   ├── thread_pool.py      # ChainThreadPool (Phase 5b)
│   │   │   └── autofill.py         # автосвязывание входов
│   │   ├── operations/             # операции обработки (blur, threshold)
│   │   ├── worker_pool/
│   │   │   ├── dispatcher.py       # WorkerPoolDispatcher (Phase 5c)
│   │   │   ├── protocol.py         # WorkerTaskRequest/Response
│   │   │   └── backpressure.py     # политика при перегрузке
│   │   └── ports.py                # ProcessorOutputPort
│   ├── database/
│   │   ├── service.py              # DatabaseService (SQL ops)
│   │   ├── schema.py               # DetectionSchema (Pydantic)
│   │   └── ports.py                # DatabaseOutputPort
│   ├── gui/
│   │   ├── service.py              # GuiService (чтение кадров + palette)
│   │   └── ports.py                # GuiOutputPort
│   └── renderer/
│       ├── service.py              # RendererService (overlay + bbox)
│       └── ports.py                # RendererOutputPort
│
├── frontend/
│   ├── launcher.py                 # FrontendLauncher (bootstrap GUI)
│   ├── app_context.py              # FrontendAppContext
│   ├── commands.py                 # GuiCommandHandler
│   ├── managers/
│   │   ├── settings_yaml_store.py  # YAML профили
│   │   ├── recipe_manager.py       # рецепты
│   │   ├── camera_registry.py      # реестр камер
│   │   ├── settings_profile_manager.py
│   │   └── app_recipe_aggregate.py
│   ├── widgets/                    # PyQt5 виджеты
│   │   ├── camera_tab/
│   │   ├── processing_tab/
│   │   ├── display_window/
│   │   ├── graph_editor/
│   │   ├── settings_profile_widget.py
│   │   └── settings_recipe_widget.py
│   ├── windows/
│   │   ├── main_window/
│   │   └── loading/
│   ├── styles/
│   │   ├── qss/                    # Qt stylesheets
│   │   └── schemas/
│   └── threads/
│
├── registers/
│   ├── constants.py                # имена регистров
│   ├── commands/
│   │   ├── catalog.py              # GUI_COMMAND_CATALOG
│   │   └── routing.py              # resolve_command_targets
│   ├── camera/                     # GuiCameraRegisters
│   ├── processor/                  # ProcessorRegisters
│   ├── renderer/                   # RendererRegisters
│   ├── display/                    # DisplaySubscription
│   ├── pipeline/                   # ProcessingNode (graph nodes)
│   ├── settings/                   # AppSettingsRegisters
│   ├── payloads/                   # Crop, post-processing payloads
│   └── schemas/                    # UI schema definitions
│
├── persistence/                    # YAML/JSON storage
├── data/
│   ├── config.json                 # static runtime config
│   ├── settings_profiles.yaml      # профили (camera_count, type, ...)
│   ├── settings_recipes.yaml       # именованные рецепты
│   └── processing_catalog.yaml     # каталог операций обработки
│
├── database/                       # SQLite файлы
├── logs/                           # runtime логи
├── tests/
│   ├── unit/
│   └── integration/
└── docs/
    ├── ARCHITECTURE.md             # ← этот документ
    ├── README.md
    └── STAGE_LOG.md
```

---

## Приложение B: Глоссарий

| Термин | Описание |
|--------|---------|
| **ProcessModule** | Базовый класс процесса (фреймворк) |
| **SRM** | SharedResourcesManager — менеджер общих ресурсов |
| **SHM** | Shared Memory — разделяемая память ОС |
| **Ring Buffer** | Кольцевой буфер: K слотов, запись по кругу |
| **seq_id** | Монотонный счётчик кадров (никогда не сбрасывается) |
| **Dict at Boundary** | Паттерн: между процессами только dict, не Pydantic |
| **Phase 5a** | Каталог обработки (YAML-driven) |
| **Phase 5b** | Параллельные шаги в ThreadPool (внутри процесса) |
| **Phase 5c** | Пул воркеров (отдельные процессы) |
| **Register** | Схема данных поля (GUI ↔ Backend) |
| **register_update** | IPC-сообщение: GUI изменил настройку → Backend |
| **frame_ready** | IPC-сообщение: камера записала кадр в SHM |
| **detection_result** | IPC-сообщение: процессор нашёл дефект |
| **FrameShmMiddleware** | Обёртка: автоматически читает кадр из SHM при получении IPC |
| **ColorBlobDetector** | Детектор цветных пятен по BGR-диапазону |
| **ChainRunnable** | Цепочка операций обработки (из Graph Editor) |
| **FrontendLauncher** | Bootstrap PyQt5 GUI (конфиг → регистры → окна → event loop) |
| **Backpressure** | Политика при перегрузке: drop-oldest (выбросить старейшую задачу) |

---

## Приложение C: Как вносить изменения

### Добавить новый тип камеры

1. Создать бэкенд в `services/camera/backends/new_type.py`
2. Реализовать интерфейс: `open()`, `read()`, `close()`, `is_opened()`
3. Зарегистрировать в `camera_policy.py`: добавить в `CameraTypeStr`
4. Добавить в `CameraService._create_backend()` — создание по типу
5. Если поддерживает enum — добавить в `SUPPORTS_ENUM`

### Добавить новую операцию обработки

1. Создать класс в `services/processor/operations/new_op.py`
2. Реализовать `execute(frame, context) → frame`
3. Добавить запись в `data/processing_catalog.yaml`
4. Операция станет доступна в Graph Editor автоматически

### Добавить новый процесс

1. Создать Config в `backend/processes/new/config.py` (наследник ProcessLaunchConfig)
2. Создать Process в `backend/processes/new/process.py` (наследник ProcessModule)
3. Реализовать `_init_application_threads()` — создание воркеров
4. Добавить в `AppConfig.all_process_configs()` — включение в оркестрацию
5. При необходимости: adapter, commands, handlers

### Изменить GUI

1. Виджеты: `frontend/widgets/`
2. Окна: `frontend/windows/`
3. Связь с backend: через `registers/` (добавить поле) + `commands/routing.py` (маршрут)
4. Обработка ответа: в `backend/processes/gui/handlers.py`
