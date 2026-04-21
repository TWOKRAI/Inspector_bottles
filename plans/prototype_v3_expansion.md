# Мета-план: Расширение multiprocess_prototype_v3 (финальная редакция)

## Context

**Текущее состояние:** Рабочий прототип с 6 процессами (Camera, Processor, Renderer, GUI, Database, Robot), 6 табами PyQt, register-driven state, IPC Queue+SHM, рецепты в YAML, детекции в SQLite.

**Цель:** Расширить прототип до полноценной промышленной системы инспекции. Доказать что Python через правильную процессную архитектуру решает задачи, которые коллеги считают прерогативой C++.

**Параметры (финальные, после TeamLead-review):**
- **Камеры:** типично 3-4, масштабируется от 1 до N без правки кода (профиль решает). Каждая камера — отдельный процесс + SHM-слот. Hikvision SDK / ctypes не даёт GIL поместиться в один процесс.
- **Frame routing:** центральный `RouterManager` — точка перехвата кадров. Любой consumer подписывается на выход камеры.
- **Display:** от 0 до N окон (обычно 2, иногда 4). Lazy SHM-аллокация.
- **Processing:** per-camera `Processor_{id}` + опциональный пул `ProcessorWorker_{n}` для тяжёлых шагов. Skip неактивных шагов без runtime-if.
- **Параллелизм в процессе:** `ThreadPoolExecutor` — несколько шагов одновременно (NumPy/OpenCV отпускают GIL).
- **Undo/Redo:** `ActionBus` (Command Pattern as first-class).
- **Настройки:** переключаемые профили (паттерн рецептов).
- **Graph-editor:** перенесён в Phase 8 вместе с миграцией модели; MVP начинает с плоского `ProcessingStep`.

**Принцип:** Максимум переиспользования `multiprocess_framework` (19 модулей). `SchemaBase` — модель для каждой сущности. Frame flow — только через `RouterManager` + `MemoryManager`.

---

## Архитектурные решения

### AD-1: Масштабируемая оркестрация камер (1..N)
**Решение:** Один `CameraProcess` на камеру, список — из активного профиля.
- `CameraConfig(camera_id, source_type, params)`; `process_name = f"camera_{id}"`; output SHM = `f"camera_{id}_frame"`.
- `AppConfig.all_process_configs()` **генерирует N конфигов** по `SettingsProfile.cameras`.
- Hot-add отложен (перезапуск приложения при добавлении камеры); per-camera start/stop — в Phase 3.
- **Почему:** Hikvision SDK + ctypes = GIL contention. Код работает для 1, 4, 12 камер без правок.

### AD-2: Frame Routing через RouterManager
**Решение:** Кадры камер → `RouterManager` → подписчики. Единая шина.
- Камера пишет кадр в output SHM + шлёт `frame_ready` с метаданными (camera_id, seq_id, ts, shape, slot).
- `FrameShmMiddleware` резолвит SHM-ссылки.
- Consumers подписываются на `frame.camera_{id}` (Processor, Display, Recorder).
- Router поддерживает **fan-out** (один кадр → N подписчиков), **drop-oldest**, **throttle-фильтры**.

### AD-3: Processing — per-camera host + thread workers + graph-ready модель (без портов в MVP)
**Решение:** Модель узла `ProcessingNode` с `inputs` — **с Phase 5** (не мигрируем через 2 месяца). UI v1 = таблица (auto-fill `inputs` по порядку), UI v2 = граф (Phase 8, ручное связывание). `input_ports/output_ports` в каталоге операций — **отложено на Phase 8** (в MVP не нужны).

**Модель узла (с Phase 5):**
```
ProcessingNode (SchemaBase):
  node_id: UUID           # стабильный
  operation_ref: str      # ссылка в каталог
  params: dict
  enabled: bool
  process_id: str         # "processor_1" | "worker_pool_heavy"
  worker_id: str | None   # thread внутри процесса
  inputs: list[NodeInput] # в Phase 5 auto-fill линейно; в Phase 8 — ручное редактирование
  position: (x, y) | None # используется только в Phase 8
```

- `Region.nodes: dict[node_id, ProcessingNode]` — единая структура для таблицы и графа.
- В UI-таблице (Phase 5): поле `inputs` скрыто, при reorder/add — авто-проставляется `inputs[i] = [{source: nodes[i-1].node_id}]`. Пользователь видит линейную таблицу.
- В graph-view (Phase 8): `inputs` становится видимым/редактируемым. Backend не меняется.
- **Skip inactive:** `enabled=False` узлы выбрасываются из runnable; потребитель получает вход от предшественника напрямую.
- **Три уровня параллелизма:** процессы (Processor_{id} + worker_pool), потоки (ThreadPool внутри процесса), DAG-scheduler (ready-queue — узлы без взаимных зависимостей исполняются параллельно).
- **Атомарный swap:** любое изменение — rebuild runnable + swap ссылки.

**Почему так, а не плоский `ProcessingStep`:** graph-editor точно будет в Phase 8. Миграция SchemaBase-схемы `ProcessingStep → ProcessingNode` с автоконверсией сохранённых YAML-профилей и SQL-записей через 2 месяца — это 3-5 дней работы + риск сломать prod-данные. Держим модель сразу как надо, прячем лишнее в UI-слое. В каталоге порты отложены — это действительно over-engineering для MVP.

### AD-4: Display — гибкое число окон (0..N) + lazy SHM
**Решение:** `DisplaySubscription(source_ref, window_id, transform)` → роутится через тот же `RouterManager`.
- `source_ref`: `camera_{id}` (raw) / `processor_{id}.{region}.{step}` / `processor_{id}.{region}.final`.
- N=0 — валидный (headless/CI). SHM на шаге создаётся только при хотя бы одной подписке.
- `subscribe_display` / `unsubscribe_display` → Router + `WindowManager`.

### AD-5: ActionBus (Undo/Redo as first-class)
**Решение:** Атомарный `Action` (SchemaBase) + единая шина + SQL-лог.
- `Action: forward_patch, inverse_patch, description, tags, correlation_id, created_at`.
- `ActionBus.execute / undo / redo / transaction(description)`.
- **Composite** — нативно через `with bus.transaction(): tx.set(...)`.
- **Coalescing** — декларативно: `tag + window_ms + merge_fn`.
- **Дисциплина:** `RegistersManager.set_field_value` → приватный `_apply_patch_internal`; единственный публичный путь — ActionBus. Debug-guard WARN при вызове не из bus.
- **Persistence:** `action_log` через `sql_module`; crash recovery = replay forward_patch.
- **Hardware side-effects** (camera start/stop, robot) вне ActionBus — идут через `CommandManager`.
- **Бонусы:** replay, macros, dry-run, deterministic bug-report.

### AD-6: SHM Buffer Ownership — ring-buffer + sequence counter
**Проблема:** fan-out без копирования → камера пишет следующий кадр, пока consumer ещё читает предыдущий → data corruption.

**Решение:** Ring-buffer из K слотов на камеру + монотонный `seq_id` + per-consumer last-read.
- `CameraOutputBuffer`: K SHM-слотов (`camera_{id}_frame_0..K-1`), writer write_ptr, per-consumer read_ptr.
- Writer: `slot = (write_ptr + 1) % K; write_frame(slot); write_ptr = slot; publish(seq_id, slot)`.
- Reader: получает (seq_id, slot), читает, потом `last_read[consumer_id] = seq_id`. Писатель не трогает слот пока `min(last_read)` меньше seq_id этого слота.
- **Drop-oldest политика:** если consumer отстаёт больше чем на K-1 — его read_ptr сдвигается к `write_ptr - (K-1)`, счётчик drops в StatsManager.
- **Seq_id хранится в отдельном SHM-слоте** (int64) через `MemoryManager`, обновляется атомарно.
- **Почему ring-buffer, а не refcount:** refcount требует cross-process atomic'ов; в multiprocessing Python это Lock (медленно) или Value (не атомарный inc по multiple bytes). Ring-buffer + per-consumer ptr проще и быстрее.

#### Memory budget — важная оговорка
Ring-buffer умножает расход SHM на K. Для высоких разрешений это критично:

| Разрешение | Один слот (BGR) | K=3 | 4 камеры × K=3 | 8 камер × K=3 |
|------------|-----------------|-----|-----------------|------------------|
| 720p (1280×720×3) | ~2.6 MB | 7.8 MB | 31 MB | 62 MB |
| 1080p (1920×1080×3) | ~6 MB | 18 MB | 72 MB | 144 MB |
| 4K (3840×2160×3) | ~24 MB | 72 MB | **288 MB** | **576 MB** |

**Правила:**
1. **K настраивается per-camera** в профиле (`camera.{id}.ring_buffer_size`), default=3.
2. **Separate K для raw и processed слотов** — raw обычно больше разрешения, processed часто даунсемплен; хранить их с одинаковым K — расточительно.
3. **Budget-check при старте:** `SettingsProfileManager` считает суммарный SHM и валидирует против `settings.shm_budget_mb` (default 512 MB). Превышение → hard-error со списком камер-виновников.
4. **Для 4K камер** рекомендуется K=2 (минимум для lockless write/read) + throttle на captured FPS.
5. **StatsManager экспортит `shm_usage_mb`** per-camera — видно в UI Camera Tab + лог при старте.

### AD-7: Error Model — pipeline failures *(ответ на TeamLead-review)*
**Решение:** Трёхуровневая обработка ошибок (узел / процесс / supervisor).

**Уровень 1 — ошибка в шаге обработки:**
- Шаг бросает exception → scheduler ловит → логирует через `ErrorManager` + прикрепляет `(camera_id, region_id, step_id, seq_id)`.
- Политика из каталога операции: `on_error: skip` (кадр пропускается), `fail_region` (регион выключается до перезапуска), `fail_camera` (камера останавливается).
- По умолчанию — `skip` + WARN каждые N ошибок (анти-спам лога).

**Уровень 2 — падение процесса:**
- `ProcessManagerProcess` (supervisor) детектит crash child-процесса.
- Политика per-process: `restart` (max 3 попытки с exponential backoff) / `stop` (отключить камеру, алерт в UI).
- Per-camera изоляция: падение `Processor_1` не трогает `Processor_2..N`.

**Уровень 3 — timeout на SHM-чтение:**
- Consumer ждёт `frame_ready` event > timeout (2 сек default) → WARN + increments stats → продолжает ждать.
- Если > hard_timeout (30 сек) → consumer считает камеру «мёртвой» → отписывается → supervisor получает сигнал restart.

**UI:** индикатор статуса per-camera/per-region (green/yellow/red) + лог ошибок в отдельной панели.

---

## Фазы реализации

### Phase 0: Инфраструктура настроек и профилей
**Цель:** Система профилей настроек (фундамент всех остальных фаз).
**Сложность:** M | **Срок:** ~1 нед | **Зависимости:** нет | **Ветка:** `feat/phase-0-settings-profiles`

**Задачи:**
1. `AppSettingsRegister` (SchemaBase) — поля для camera_count, display_defaults, processing_defaults.
2. `SettingsProfileManager` — зеркало `RecipeManager` (YAML-backed, list/get/save/switch).
3. Интеграция в `FrontendLauncher` + `FrontendAppContext`.

**Модули:** `data_schema_module`, `registers_module`.
**Файлы:** `registers/settings/`, `frontend/managers/settings_profile_manager.py`, `frontend/launcher.py`, `frontend/app_context.py`.
**Критерий:** Профиль из YAML → переключается → `RegistersManager` отражает значения.
**PR-чеклист:** ruff pass, `python scripts/validate.py` pass, минимум 1 smoke-test на profile switch.

---

### Phase 1: Рецепты (улучшение таба)
**Цель:** Табличное редактирование + переключение по номеру + двунаправленная синхронизация.
**Сложность:** M | **Срок:** ~1.5 нед | **Зависимости:** Phase 0 | **Ветка:** `feat/phase-1-recipes-table`

**Задачи:**
1. `StructuredTableWidget` для слота рецепта (столбцы из `FieldMeta`).
2. Переключение слотов по номеру (ComboBox).
3. Auto-save с debounce + версионирование YAML.

**Модули:** `frontend_module`, `data_schema_module`.
**Файлы:** `frontend/widgets/settings_recipe_widget/`, `frontend/widgets/tabs_setting/recipes_tab/`, `frontend/managers/recipe_manager.py`.
**Критерий:** Ячейка → регистр → IPC propagation. Переключение слота работает.

**⚠️ Можно делать параллельно с Phase 3** (если есть второй разработчик).

---

### Phase 2: Настройки (переключаемые профили)
**Цель:** Таб настроек с SchemaBase defaults + YAML overrides.
**Сложность:** M | **Срок:** ~1 нед | **Зависимости:** Phase 0, Phase 1 | **Ветка:** `feat/phase-2-settings-tab`

**Задачи:**
1. Переиспользовать паттерн Phase 1 для `AppSettingsRegister`.
2. Profile selector (как recipe slot selector).
3. Merge-логика: defaults + override.
4. Событие `profile_changed` — Phase 3+ подписываются.

**Файлы:** `frontend/widgets/settings_profile_widget/`, `frontend/widgets/tabs_setting/recipes_settings_tab/widget.py`.
**Критерий:** Переключение профиля обновляет все регистры.

---

### Phase 2.5: ActionBus ядро (сдвинуто вперёд по TeamLead-review)
**Цель:** Ядро ActionBus + приватизация `RegistersManager.set_field_value` + adapter-слой для постепенной миграции presenters. **Полная миграция presenters — в Phase 7**, но ядро должно быть готово ДО Phase 3, чтобы новые виджеты (camera tab, display tab) сразу писались «правильно».
**Сложность:** M+ | **Срок:** ~2 нед | **Зависимости:** Phase 2 | **Ветка:** `feat/phase-2_5-actionbus-core`

**Задачи:**
1. `Action` (SchemaBase) + `ActionBus` + `ActionStack` + `CoalescingRegistry` (см. AD-5).
2. Приватизация: `RegistersManager.set_field_value` → `_apply_patch_internal`; новый публичный `apply_patch(forward, inverse)`.
3. **Adapter-слой:** `RegisterWriterAdapter` — тонкая обёртка, которую используют старые presenters; внутри либо wraps в auto-Action (fallback), либо вызывает `ActionBus.execute` если вызывающий явно подключил bus.
4. Debug-guard в `_apply_patch_internal`: WARN если вызов не через ActionBus (для поиска мест, которые ещё не мигрированы).
5. Мигрировать **только** Phase 0-2 presenters на ActionBus (рецепты, настройки, профили). Остальные — поэтапно в Phase 7.

**Модули:** `data_schema_module`, `registers_module`, `dispatch_module` (pre/post-hooks).
**Файлы:** `frontend/actions/` (`action.py`, `action_bus.py`, `action_stack.py`, `coalescing.py`, `register_adapter.py`), `registers_module` (рефакторинг).
**Критерий:**
- Ctrl+Z отменяет изменение на рецептах / настройках / профилях.
- Coalescing для slider работает.
- Debug-guard выводит WARN для direct-writes из немигрированных presenters.

**Почему так:** чем раньше ActionBus внедрён, тем меньше presenters пишется «по-старому». Big-bang миграция в конце — риск. Adapter-слой = обратная совместимость на период Phase 3..6.

---

### Phase 3: Мульти-камеры + Frame Router + Ring-buffer
**Цель:** Динамическая оркестрация N камер + Router fan-out + SHM ring-buffer (AD-6).
**Сложность:** XL | **Срок:** ~3-4 нед | **Зависимости:** Phase 0, Phase 2.5 | **Ветка:** `feat/phase-3-multi-camera-router`

**Задачи:**
1. Параметризация `CameraProcess` — `camera_id`, output ring-buffer из K слотов.
2. `AppConfig.all_process_configs()` генерирует N конфигов по `SettingsProfile.cameras`.
3. **Ring-buffer implementation** (AD-6): writer write_ptr, per-consumer read_ptr, seq_id counter в отдельном SHM-слоте, drop-oldest при отставании.
4. Frame Router setup: `frame.camera_{id}` event-канал, `FrameShmMiddleware`, fan-out + drop-oldest.
5. `CameraRegistry` (frontend): id, type, status, process_name, fps, last_frame_ts, drops_count.
6. Enhanced Camera Tab: список + настройки + start/stop/restart + FPS + drops-индикатор.
7. Webcam panel (MVP) + File-source panel (зациклить видео для тестов без железа).
8. **Fan-out smoke-test:** 2 подписчика (Processor + тестовый Recorder) → verified что оба получают все кадры и писатель не обгоняет slowest consumer.

**Модули:** `process_module`, `worker_module`, `shared_resources_module`, `router_module`, `frontend_module`.
**Файлы:**
- Новые: `backend/routing/frame_router_setup.py`, `backend/shm/ring_buffer.py`, `frontend/managers/camera_registry.py`, `frontend/widgets/webcam_camera_mvp/`, `frontend/widgets/file_source_mvp/`.
- Изменить: `backend/processes/camera/`, `config/app.py`, `registers/camera/`, `main.py`, `frontend/widgets/tabs_setting/camera_tab/`.

**Критерий:**
- Профили `{1 cam}`, `{3 cam}`, `{8 cam}` работают **без правки кода**.
- **Ring-buffer stress-test:** медленный consumer (искусственный sleep) → drop-oldest срабатывает, writer не блокируется, fast consumer не теряет кадры.
- **Seq_id verified:** каждый consumer видит монотонно возрастающий seq_id.
- Per-camera start/stop, FPS и drops — в UI.

---

### Phase 4: Регионы (per-camera)
**Цель:** Per-camera CRUD регионов + привязка к будущей chain.
**Сложность:** L | **Срок:** ~1.5 нед | **Зависимости:** Phase 3 | **Ветка:** `feat/phase-4-regions-per-camera`

**Задачи:**
1. Рефакторинг `CroppedRegionsPanelWidget` — динамические камеры из `CameraRegistry`.
2. Структура `crop_regions: {camera_id: {region_id: Region}}`.
3. `Region` получает поле `steps: list` (пусто в Phase 4, заполняется в Phase 5).
4. Backend propagation → соответствующий `Processor_{id}` перестраивает сценарий.

**Файлы:** `frontend/widgets/cropped_regions_widget/`, `registers/pipeline/region.py`, `backend/processes/processor/process.py`.
**Критерий:** Регион per camera. CRUD. Propagation в правильный processor.

---

### Phase 5: Processing — плоский chain + thread workers + worker pool
**Цель:** Цепочка обработок per region (таблица), три уровня параллелизма. **Без графовой модели** — линейный список `ProcessingStep`.
**Сложность:** XL | **Срок:** ~6-7 нед суммарно (5a=3, 5b=1.5, 5c=2) | **Зависимости:** Phase 3, Phase 4

**Подфазы (отдельные ветки):**

#### 5a — Каталог + линейный chain в одном процессе
**Ветка:** `feat/phase-5a-chain-mvp`
**Срок:** ~3 нед
1. **Каталог операций:** `ProcessingOperationDef` (SchemaBase) — name, params schema, module path, `on_error` политика, `default_process_hint`. **Без `input_ports/output_ports`** в MVP — это Phase 8. YAML storage. Built-in: ColorDetection, BlobDetection.
2. **Модель узла:** `ProcessingNode` (SchemaBase) — `node_id (UUID), operation_ref, params, enabled, process_id, worker_id, inputs: list[NodeInput], position=None`. `Region.nodes: dict[node_id, ProcessingNode]`. См. AD-3.
3. **Auto-fill inputs:** UI-таблица при add/reorder проставляет `inputs[i] = [{source: prev_node.node_id}]` автоматически — пользователь видит линейную таблицу, поле `inputs` скрыто.
4. **`GraphRunnableBuilder`:** принимает `nodes` + профиль → выбрасывает `enabled=False` → топологическая сортировка по `inputs` → ready-queue. Для линейного случая даёт последовательность идентичную порядку таблицы.
5. **Skip inactive:** `enabled=False` узел выбрасывается; его потребители получают вход от предшественника (короткозамыкание).
6. **`Processor_{camera_id}`:** подписан на `frame.camera_{id}`, держит runnable per region.
7. **Chain editor (таблица):** колонки `#`, `operation`, `params`, `enabled`, `process`, `worker`. Drag-reorder, add from catalog, remove. Поле `inputs` скрыто.
8. **Auto-gen param panels** из FieldMeta.
9. **Catalog CRUD tab.**
10. **Error handling (AD-7):** scheduler ловит exceptions, применяет политику из каталога, логирует с контекстом.
11. **Атомарный swap:** любое изменение `nodes` → rebuild runnable → swap ссылки.

**Критерий 5a:**
- Chain per region; skip inactive verified в логах.
- Каталог CRUD; param panels генерируются.
- Атомарный swap: изменение chain во время работы не ломает текущий кадр.
- Error `on_error: skip` работает — кадр пропущен, следующий обрабатывается.
- **Модель готова к DAG:** ручная правка `nodes[X].inputs` в YAML (ветвление из Python без UI) → работает без изменений в backend.

#### 5b — Threading workers внутри процесса
**Ветка:** `feat/phase-5b-thread-workers`
**Срок:** ~1.5 нед
10. `ThreadPoolExecutor` внутри `Processor_{id}`; размер = `settings.workers_per_processor` (2-4).
11. **Parallel bundle detection:** соседние шаги в chain с одинаковым `worker_id=None` и без взаимной зависимости (inputs не перекрываются) → запускаются параллельно, результат мержится.
12. **Per-frame barrier:** кадр N+1 не стартует пока ветки кадра N не собраны — порядок сохраняется.
13. UI: колонка `worker` в таблице (dropdown из доступных или `auto`).

**Критерий 5b:**
- 2 независимых шага → параллельное исполнение в двух потоках → CPU > 1 core на NumPy-heavy.
- Per-frame barrier verified: seq_id строго возрастает на выходе.
- Timeout+watchdog: если thread висит > timeout → WARN + восстановление.

#### 5c — Cross-process worker pool
**Ветка:** `feat/phase-5c-worker-pool`
**Срок:** ~2-3 нед
14. `K` процессов `ProcessorWorker_{n}` стартуют из `AppConfig`; подписаны на `frame.worker_pool_in` (round-robin).
15. Шаг с `process_id="worker_pool_*"` → выход предыдущего шага в SHM → event `frame.worker.in` → worker обрабатывает → результат в SHM → event → Processor_{id} подхватывает.
16. Backpressure: drop-oldest на входе worker_pool; счётчик drops в UI.
17. Error (AD-7): timeout на ожидание ответа от worker'а → политика из каталога.

**Критерий 5c:**
- Chain с 1 heavy-шагом на `worker_pool_1` — end-to-end.
- Перегрузка worker'а → drop-oldest → основной pipeline не зависает.
- Crash worker'а → supervisor restart → pipeline продолжает после перерыва.

---

### Phase 6: Отображение (0..N окон)
**Цель:** Гибкое число окон + lazy SHM + layout presets.
**Сложность:** XL | **Срок:** ~2.5-3 нед | **Зависимости:** Phase 3, Phase 5a | **Ветка:** `feat/phase-6-display-windows`

**Задачи:**
1. `DisplaySubscription` (SchemaBase): `source_ref`, `window_id`, `transform` (resize, overlay, fps-limit).
2. `DisplayRouter` (frontend): подписки через `RouterManager`, lazy SHM.
3. Display window: `ImagePanelWidget` + source selector + close.
4. Display tab: таблица окон + **layout presets** (0/1/2/4/custom).
5. Headless mode (N=0) — pipeline работает, детекции в БД.
6. `WindowManager` для lifecycle.
7. `FrameThrottleMiddleware` — FPS-limit на display-каналах.

**Модули:** `shared_resources_module`, `router_module`, `frontend_module`.
**Файлы:** `frontend/managers/display_router.py`, `frontend/widgets/display_window/`, `frontend/widgets/tabs_setting/display_tab/`, `backend/routing/throttle_middleware.py`.
**Критерий:**
- Пресеты 0/1/2/4 окон без рестарта.
- Headless verified — детекции в БД без UI.
- 100 create/destroy циклов — нет SHM leaks (audit через `MemoryManager`).

**⚠️ MVP-вариант Phase 6** (только 2 окна без пресетов/throttle/headless) **можно делать раньше** — после Phase 3 вместо Phase 5. Даёт раннюю визуальную валидацию.

---

### Phase 7: ActionBus — полная миграция presenters + persistence
**Цель:** Завершить миграцию всех presenters (Phase 3-6) на ActionBus + SQL-лог + crash recovery.
**Сложность:** XL | **Срок:** ~3-4 нед | **Зависимости:** Phase 2.5, Phase 3-6 | **Ветка:** `feat/phase-7-actionbus-migration`

**Задачи:**

**7.1. Миграция presenters**
1. `RegisterBinding` — полностью на `bus.execute(ActionBuilder.from_field(...))`.
2. Presenters: camera_tab, regions_tab, processing_panel, display_tab, catalog_tab — все mutations через `self.actions.execute(...)`.
3. **Удалить** `RegisterWriterAdapter` (был нужен только на период Phase 3-6 для обратной совместимости).
4. Debug-guard: теперь должен давать 0 WARN'ов в прод-билде (если есть — рефакторить).

**7.2. ActionBuilder для доменных операций**
5. `ActionBuilder.region_add / region_remove` (для Phase 4).
6. `ActionBuilder.step_add / step_remove / step_modify / step_reorder` (для Phase 5).
7. `ActionBuilder.display_subscribe / display_unsubscribe / layout_change` (для Phase 6).
8. `ActionBuilder.profile_switch / recipe_switch` (для Phase 1-2).

**7.3. Persistence + recovery**
9. SQL: `GenericRepository[Action]` + `SchemaBaseMapper` → `action_log` таблица.
10. Batched writes (UnitOfWork).
11. Crash recovery: при старте — прочитать последние N Actions → накатить forward_patch.
12. Rotation: max 10k Actions; старые → `action_log_archive_{date}`.

**7.4. UI финализация**
13. Ctrl+Z / Ctrl+Y global shortcuts; кнопки в header; статус-бар с description последнего Action.
14. Dropdown «История» — последние 20 Actions (кликабельный откат).

**Модули:** `sql_module`, `registers_module`, `frontend_module`, `dispatch_module`.
**Файлы:** `frontend/actions/builders/` (region, step, display, profile, recipe), `frontend/actions/action_log.py`, все presenters.
**Критерий:**
- Ctrl+Z откатывает: параметр, регион add/remove, step add/remove/toggle, display subscribe.
- Recipe switch = 1 Action в стеке.
- Slider → 1 Action благодаря coalescing.
- Kill -9 в середине редактирования → старт → state восстановлен.
- Replay test: 20 Actions сохранены → применены на чистый state → идентичный результат.
- Debug-guard: 0 WARN'ов в prod-билде.

---

### Phase 8: Графовый редактор + порты в каталоге
**Цель:** Визуальный редактор с ветвлениями/merge. Модель `ProcessingNode` уже есть из Phase 5 — добавляем только UI и порты в каталоге.
**Сложность:** L | **Срок:** ~2.5-3 нед | **Зависимости:** Phase 5 (вся), Phase 7 | **Ветка:** `feat/phase-8-graph-editor`

**Задачи:**
1. **Расширение каталога:** `ProcessingOperationDef` получает `input_ports: list[Port]`, `output_ports: list[Port]` + типы для совместимости. Существующие операции (ColorDetection, BlobDetection) — один input `"in"`, один output `"out"` (миграция через default).
2. **Расширение модели:** `NodeInput` получает `output_port: str` (default `"out"`). Существующие `inputs` из Phase 5 остаются валидными (default применяется автоматически).
3. **`GraphRunnableBuilder`** расширяется до полноценного DAG с валидацией ацикличности и совместимости типов портов.
4. **GraphView** (QGraphicsScene/QGraphicsView): canvas, zoom/pan, snap-to-grid.
5. **NodeItem / EdgeItem / PortItem:** визуальные представления. Bezier-связи с валидацией типов портов.
6. **Интеракции:** drag-создание связи, Del, контекстное меню (Enable/Disable, Set Process, Set Worker, Duplicate).
7. **Catalog palette** слева (drag-drop на canvas).
8. **View switch:** таблица ⇄ граф для одного `region.nodes`. В табличном виде при наличии ветвлений — WARN «graph нелинеен, часть связей скрыта».
9. **Auto-layout** (Sugiyama / layered) для имеющихся линейных chain'ов (когда пользователь впервые открывает граф).
10. **Undo/Redo:** все графовые операции через ActionBus (готово из Phase 7 — добавляются только builder'ы `graph_connect`, `graph_disconnect`, `node_move`).

**Модули:** `frontend_module`, `dispatch_module` (GraphBuilder), `data_schema_module`.
**Файлы:** `frontend/widgets/graph_editor/`, `frontend/actions/builders/graph.py`, `registers/processor/ports.py` (новый), `backend/processing/graph_builder.py`.
**Критерий:**
- Graph view открывает регион → показывает узлы/связи из Phase 5 без конверсии.
- Ветвление (1 → 2) и merge (2 → 1) — backend исполняет через DAG scheduler.
- View switch таблица ⇄ граф — модель `region.nodes` идентична, представление меняется.
- Все графовые операции undoable через ActionBus.
- **Нет миграции SchemaBase** — модель `ProcessingNode` из Phase 5 переиспользуется как есть.

---

## Граф зависимостей

```
Phase 0 (Settings) ──┐
                     ├──→ Phase 1 (Recipes) ──→ Phase 2 (Settings tab) ──→ Phase 2.5 (ActionBus core)
                     │                                                            │
                     └────────────────────────────────────────────────────────────┤
                                                                                  │
  Phase 2.5 ──→ Phase 3 (Multi-Camera + Ring-buffer) ──→ Phase 4 (Regions)        │
                                                   │                    │         │
                                                   │                    └─→ Phase 5a (Chain MVP)
                                                   │                                 │
                                                   │                              Phase 5b (Threads)
                                                   │                                 │
                                                   │                              Phase 5c (Worker pool)
                                                   │                                 │
                                                   └──────→ Phase 6 (Display) ←──────┘
                                                                           │
                                    Phase 3-6 ─────────────→ Phase 7 (ActionBus full migration)
                                                                           │
                                                                   Phase 8 (Graph editor + DAG)
```

**Горячий путь кадра:**
```
Camera_{id} → RingBuffer[K slots] + seq_id ──→ Router(frame.camera_{id})
                                                    ├─→ Processor_{id}                   [per-camera process]
                                                    │     └─→ Scheduler (runnable)
                                                    │           ├─→ ThreadPool worker_A ─┐
                                                    │           ├─→ ThreadPool worker_B ─┼─→ merge
                                                    │           └─→ cross-process edge ──┘
                                                    │                        ↓
                                                    │              Router(worker_pool_in)
                                                    │                        ↓
                                                    │              ProcessorWorker_k → SHM → обратно
                                                    └─→ DisplayRouter → window (raw preview)
```

---

## Стратегия тестирования *(ответ на TeamLead-review)*

### Три слоя тестов

**L1 — Unit (pytest, быстро):**
- Каждый `SchemaBase` (`Action`, `ProcessingStep`, `ProcessingOperationDef`, и т.д.) — сериализация/десериализация, валидация.
- `ActionBus`: execute/undo/redo/transaction/coalescing — чистые объекты без GUI.
- `StepRunnableBuilder` / `GraphBuilder`: вход → ожидаемый runnable.
- `RingBuffer`: writer/reader scenarios в одном процессе (без multiprocessing).
- **Цель:** 100% unit-покрытие ядра ActionBus и scheduler'а.

**L2 — Integration (pytest + multiprocessing, медленно):**
- **`FakeCameraProcess`** — генератор синтетических кадров с заданным FPS + предсказуемым контентом (checkerboard с encoded seq_id).
- **Test harness** `ProcessPipelineTestbed`: стартует minimal config (1 fake camera + 1 processor + 0 GUI) → injects N кадров → asserts результаты.
- Scenarios:
  - Linear chain: fake camera → 3-step chain → check все кадры прошли, seq_id сохранён.
  - Ring-buffer under load: slow consumer → drop-oldest срабатывает, counter корректен.
  - Worker pool: chain с heavy-шагом → кадры проходят через 2 процесса без потерь.
  - Crash recovery: kill processor mid-stream → supervisor restart → pipeline восстанавливается.
- **Запускаются в CI** на каждый PR в Phase 3+.

**L3 — E2E smoke (manual / semi-auto):**
- Профили `{1 cam}`, `{3 cam}`, `{8 cam}` — запуск, 30 сек работы, проверка логов на ошибки.
- Chain swap во время работы — нет падений.
- Layout preset switch (0→2→4→0) — нет leaks.
- Kill -9 → restart → state восстановлен из action_log.
- **Semi-auto:** скрипт который стартует прототип, делает серию действий через Qt Test API, snapshot'ит state.

### Где тесты живут
- `Inspector_prototype/multiprocess_prototype_v3/tests/unit/` — L1.
- `Inspector_prototype/multiprocess_prototype_v3/tests/integration/` — L2 (с маркером `@pytest.mark.slow`).
- `Inspector_prototype/scripts/smoke_tests/` — L3 (shell + Python).
- `FakeCameraProcess` и `ProcessPipelineTestbed` — в `multiprocess_prototype_v3/testing/` (не `tests/`, т.к. это переиспользуемая инфраструктура).

### Регламент
- **На каждую фазу** — минимум один L2-тест, который проверяет главный сценарий фазы (см. «Критерий» фазы).
- **На каждый PR** — L1 + L2 (CI).
- **Перед merge фазы** — L3 smoke локально.

---

## Git branching strategy

### Правила
- **Одна ветка = одна фаза** (или подфаза для Phase 5).
- Базовая ветка: `main`.
- **Порядок:** каждая следующая фаза базируется на предыдущей смерженной в main. Исключение — параллельные (Phase 1 || Phase 3 после Phase 0).
- Формат имени: `feat/phase-{N}-{kebab-slug}` (пример: `feat/phase-3-multi-camera-router`).
- Для рефакторинга / hotfix внутри фазы — суб-ветки: `feat/phase-3-multi-camera-router/subtask-camera-registry` → PR в ветку фазы, не в main.

### Merge-стратегия
- **Squash merge** для маленьких фаз (Phase 0-2, 4, 2.5) — чистая история.
- **Rebase merge** для больших (Phase 3, 5a/5b/5c, 6, 7, 8) — сохраняем историю коммитов для постмортема.
- **Force push** запрещён на ветках фазы после открытия PR (только на суб-ветках).

### PR-чеклист (общий для всех фаз)
```
- [ ] ruff check + ruff format
- [ ] python Inspector_prototype/scripts/validate.py — pass
- [ ] python Inspector_prototype/scripts/run_framework_tests.py — pass
- [ ] Добавлены L1 unit-тесты для нового кода
- [ ] Добавлен минимум 1 L2 integration-тест на главный сценарий фазы
- [ ] Критерий фазы выполнен (см. план)
- [ ] Обновлены README.md / STATUS.md затронутых модулей
- [ ] Если меняется multiprocess_framework — добавлена запись в DECISIONS.md
- [ ] Self-review diff на тему «нет thin wrappers / нет _cmd_* дубликатов»
```

### Таблица веток

| Phase | Ветка | Base | Merge strategy | После merge |
|-------|-------|------|----------------|-------------|
| 0 | `feat/phase-0-settings-profiles` | `main` | squash | → main |
| 1 | `feat/phase-1-recipes-table` | `main` (после 0) | squash | → main |
| 2 | `feat/phase-2-settings-tab` | `main` (после 1) | squash | → main |
| 2.5 | `feat/phase-2_5-actionbus-core` | `main` (после 2) | rebase | → main |
| 3 | `feat/phase-3-multi-camera-router` | `main` (после 2.5) | rebase | → main |
| 4 | `feat/phase-4-regions-per-camera` | `main` (после 3) | squash | → main |
| 5a | `feat/phase-5a-chain-mvp` | `main` (после 4) | rebase | → main |
| 5b | `feat/phase-5b-thread-workers` | `main` (после 5a) | rebase | → main |
| 5c | `feat/phase-5c-worker-pool` | `main` (после 5b) | rebase | → main |
| 6 | `feat/phase-6-display-windows` | `main` (после 3, можно параллельно с 5) | rebase | → main |
| 7 | `feat/phase-7-actionbus-migration` | `main` (после 5, 6) | rebase | → main |
| 8 | `feat/phase-8-graph-editor` | `main` (после 7) | rebase | → main |

### Что делать в каждой ветке (кратко)

| Phase | Что конкретно делать в ветке |
|-------|------------------------------|
| **0** | Создать `SettingsProfileManager`, схемы настроек, YAML-backed профили. Smoke: переключить 2 профиля. |
| **1** | Заменить текстовое редактирование рецептов на `StructuredTableWidget`. Auto-save с debounce. |
| **2** | Таб настроек (таблица + profile selector). Событие `profile_changed` для подписчиков. |
| **2.5** | Ядро ActionBus, приватизация `set_field_value`, adapter-слой, миграция presenters Phase 0-2. |
| **3** | Параметризация CameraProcess, ring-buffer, RouterManager fan-out, Camera Registry, Enhanced Camera Tab. Stress-тесты ring-buffer. |
| **4** | Регионы per-camera, структура `{camera_id: {region_id: Region}}`, propagation в `Processor_{id}`. |
| **5a** | Каталог операций (CRUD, без портов), `ProcessingNode` с inputs (auto-fill линейно в таблице), `GraphRunnableBuilder`, skip inactive, error handling `on_error: skip`. |
| **5b** | `ThreadPoolExecutor` в `Processor_{id}`, parallel bundle detection, per-frame barrier. |
| **5c** | `ProcessorWorker_{n}` pool, cross-process edges через Router+SHM, backpressure. |
| **6** | `DisplayRouter`, 0..N окон, layout presets, headless mode, throttle middleware. |
| **7** | Полная миграция presenters, удаление adapter'а, ActionBuilder'ы для доменных операций, SQL persistence, crash recovery. |
| **8** | Порты в каталоге (`input_ports/output_ports`), графовый редактор (QGraphicsScene), view switch, undo для graph операций. Без миграции модели — `ProcessingNode` уже из Phase 5. |

---

## Оценка трудоёмкости (финальная, после TeamLead-review)

| Phase | Сложность | Срок (senior full-time) | Файлов изменить | Новых файлов |
|-------|-----------|-------------------------|------------------|---------------|
| 0 | M | 1 нед | 5 | 4 |
| 1 | M | 1.5 нед | 8 | 0 |
| 2 | M | 1 нед | 5 | 6 |
| 2.5 | M+ | 2 нед | 6 | 6 |
| 3 | XL | 3-4 нед | 15 | 9 |
| 4 | L | 1.5 нед | 6 | 0 |
| 5a | XL | 3 нед | 8 | 10 |
| 5b | M | 1.5 нед | 3 | 3 |
| 5c | XL | 2-3 нед | 5 | 4 |
| 6 | XL | 2.5-3 нед | 9 | 11 |
| 7 | XL | 3-4 нед | 12 | 8 |
| 8 | L | 2.5-3 нед | 5 | 8 |
| **Итого без Phase 8** | | **22-27 нед** (~5.5-6.5 месяцев) | ~82 | ~61 |
| **Итого с Phase 8** | | **24.5-30 нед** (~6-7 месяцев) | ~87 | ~69 |

*+ contingency 30% для неожиданных расширений фреймворка.*

---

## Минимальный viable путь (MVP)

Для демонстрации «Python решает задачу» — must-have набор:

| Phase | Что даёт | Срок (идеально) |
|-------|----------|:--------------:|
| 0 | Фундамент профилей | 1 нед |
| 2.5-lite | Ядро ActionBus без full migration | 1-1.5 нед |
| 3 (без webcam/file-source) | **Главное: N камер в процессах + ring-buffer + fan-out** | 2.5-3 нед |
| 4 | Регионы per camera | 1.5 нед |
| 5a-lite | Линейный chain в одном процессе (без каталога — hardcode 2 операции) | 2 нед |
| 6-MVP | 2 окна, без пресетов/throttle | 1.5 нед |

**Честная оценка:**
- **При идеальном исполнении:** ~9.5-11.5 недель (**2.5-3 месяца**).
- **С учётом отладки multiprocess-багов, расширений фреймворка, итераций на ring-buffer:** ~12-14 недель (**3-3.5 месяца**).

Не «2 месяца» — это самообман. **3 месяца — реалистичный таргет для демонстрации**.

Can-defer: Phase 1, 2, 5b, 5c, 7 (full), 8.

---

## Риски (обновлено)

| Риск | Влияние | Митигация |
|------|---------|-----------|
| **SHM corruption при fan-out** (writer обгоняет reader) | Data corruption | AD-6: ring-buffer + seq_id + per-consumer read_ptr + drop-oldest |
| SHM-exhaustion (N камер × M регионов × K шагов × lazy display) | OOM/crash | Lazy allocation + SHM budget в профиле + StatsManager мониторинг |
| IPC/Router saturation | Потеря кадров | Per-channel queue sizing, drop-oldest, FrameThrottleMiddleware для display |
| GIL при тяжёлых шагах | Падение FPS | Thread workers (5b) + worker_pool на CPU-bound (5c) |
| Cross-process latency | Задержки | Keep-local по умолчанию; heavy-узлы явно помечаются |
| Race при параллельных thread-узлах | Corruption | Каждый шаг получает свою копию output; inputs read-only; merge явный |
| Out-of-order кадров при параллельных ветках | Неверная детекция | Per-frame barrier в scheduler |
| Chain hot-swap race | Partial execution | Atomic rebuild + swap ссылки |
| **Exception в шаге обработки** | Падение pipeline | AD-7: политика из каталога (`skip`/`fail_region`/`fail_camera`) |
| **Падение process'а** | Каскадный отказ | AD-7: supervisor + exponential backoff restart |
| **SHM read timeout** | Deadlock | AD-7: soft timeout (WARN) + hard timeout (restart) |
| Прямая запись в RegistersManager в обход ActionBus | Протечки Undo | Приватизация + debug-guard + adapter-слой в Phase 2.5 |
| Слишком гранулярные Action при slider | UX Ctrl+Z | Coalescing rules |
| Action-log растёт бесконечно | Disk/slow startup | Rotation 10k Actions, архив в action_log_archive |
| Over-engineering graph-модели в MVP | Срыв timeline | **Решено:** flat `ProcessingStep` в Phase 5, `ProcessingNode` — в Phase 8 |
| Big-bang миграция presenters на ActionBus | Регрессии | **Решено:** ядро в Phase 2.5 + adapter + поэтапная миграция в Phase 7 |
| Schema evolution между профилями | Broken YAML | SchemaBase validation + migration |
| Headless mode воспринимается как «сломано» | UX | Статус-индикатор в title-bar |
| Комбинаторный пространство отладки (процессы×потоки×DAG) | Невоспроизводимые баги | L2 integration-тесты + timeout+watchdog на каждом уровне |

---

## Верификация (end-to-end)

1. **Phase 0-2:** Запуск → профиль → переключение рецепта/настроек обновляет UI+бэкенд.
2. **Phase 2.5:** Ctrl+Z на рецептах/настройках работает. Coalescing слайдера verified.
3. **Phase 3:** Профили `{1,3,8 cam}` работают без правки кода. Ring-buffer stress-test: slow consumer → drop-oldest, fast не теряет. Seq_id монотонен.
4. **Phase 4:** Регион per camera, propagation в правильный `Processor_{id}`.
5. **Phase 5a:** 3 шага в chain; skip inactive; каталог CRUD; `on_error: skip` работает.
6. **Phase 5b:** 2 независимых шага параллельно; CPU > 1 core; per-frame barrier сохраняет порядок.
7. **Phase 5c:** Heavy-шаг на worker_pool; drop-oldest при перегрузке; worker crash → supervisor restart.
8. **Phase 6:** Пресеты 0/1/2/4 без рестарта; headless verified; 100 create/destroy — нет leaks.
9. **Phase 7:** Ctrl+Z на всех mutations; recipe switch = 1 Action; kill -9 → state восстановлен; replay test pass; debug-guard 0 WARN.
10. **Phase 8:** Миграция Step→Node без потерь; ветвление/merge исполняется DAG-scheduler'ом; view switch table⇄graph бесшовно; graph undoable.
