# Phase 5c: Cross-process Worker Pool -- План реализации

**Дата:** 2026-04-22
**Статус:** DONE (все 9 задач завершены, 67 unit-тестов проходят)

## Обзор

Phase 5b добавила параллельное исполнение шагов через ThreadPoolExecutor **внутри** процесса Processor. Phase 5c выносит тяжёлые шаги в **отдельные процессы** (`ProcessorWorker_{n}`), общающиеся через SHM + IPC. Это снимает ограничение GIL для CPU-bound операций (inference, тяжёлая фильтрация). Ключевые элементы: K worker-процессов из AppConfig, cross-process edge в chain (Processor пишет кадр в SHM -> event -> worker обрабатывает -> результат в SHM -> event -> Processor подхватывает), backpressure (drop-oldest), timeout на ожидание ответа (AD-7).

Все пути относительно `Inspector_prototype/multiprocess_prototype_v3/`.

---

## Задачи

### Task 5c.1 -- ProcessorWorkerConfig (конфигурация worker-процесса)

**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Создать `ProcessLaunchConfig`-наследник для worker-процессов пула, с поддержкой генерации K конфигов из AppConfig.

**Файлы (новые):**
- `backend/processes/processor_worker/config.py` -- `ProcessorWorkerConfig(ProcessLaunchConfig)`
- `backend/processes/processor_worker/__init__.py`

**Файлы (изменить):**
- `config/app.py` -- добавить поля `worker_pool_size: int = 0`, `worker_pool_configs: list[ProcessorWorkerConfig]`, генерация в `all_process_configs()`

**Шаги:**
1. Создать `ProcessorWorkerConfig(ProcessLaunchConfig)`:
   - `process_name: str` -- `f"processor_worker_{n}"` (генерируется при создании)
   - `process_class: str` -- путь к `ProcessorWorkerProcess` (Task 5c.3)
   - `worker_index: int` -- индекс воркера (0..K-1)
   - `step_timeout: float = 10.0` -- timeout операции
   - `input_queue_size: int = 4` -- размер входной очереди (backpressure)
   - `priority: ProcessPriorityLevel = ProcessPriorityLevel.NORMAL`
   - Property `memory` -- SHM-регион для записи результата: `f"worker_{worker_index}_result"` с shape из resolution
2. В `AppConfig`:
   - Поле `worker_pool_size: int = 0` (0 = пул отключён, K>0 = запустить K воркеров)
   - `model_post_init`: если `worker_pool_size > 0`, генерировать список `ProcessorWorkerConfig(worker_index=i)` для i=0..K-1
   - `all_process_configs()` -- включить worker-конфиги в список
3. В `main.py` -- прочитать `worker_pool_size` из settings profile, передать в `AppConfig`

**Критерии приёмки:**
- [ ] `AppConfig(worker_pool_size=3).all_process_configs()` содержит 3 конфига `processor_worker_0..2`
- [ ] `AppConfig(worker_pool_size=0).all_process_configs()` не содержит worker-конфигов
- [ ] `ProcessorWorkerConfig(worker_index=1).process_name == "processor_worker_1"`

**Вне scope:** Реализация самого ProcessorWorkerProcess (Task 5c.3).

---

### Task 5c.2 -- WorkerPoolDispatcher (маршрутизация задач в пул)

**Уровень:** Senior+ (Opus)
**Исполнитель:** teamlead
**Цель:** Компонент внутри `ProcessorService`, который отправляет шаг с `process_id="worker_pool_*"` на обработку в один из worker-процессов через IPC+SHM и ожидает результат с timeout.

**Файлы (новые):**
- `services/processor/worker_pool/__init__.py`
- `services/processor/worker_pool/dispatcher.py` -- `WorkerPoolDispatcher`
- `services/processor/worker_pool/protocol.py` -- `WorkerTaskRequest`, `WorkerTaskResponse` (dataclass/SchemaBase для сериализации задач)

**Шаги:**
1. Определить протокол обмена данными (в `protocol.py`):
   - `WorkerTaskRequest(SchemaBase)`: `task_id: str (UUID)`, `correlation_id: str`, `camera_id: str`, `region_id: str`, `seq_id: int`, `operation_ref: str`, `params: dict`, `input_shm_owner: str`, `input_shm_slot: str`, `input_shm_index: int`, `frame_shape: tuple[int, int, int]`
   - `WorkerTaskResponse(SchemaBase)`: `task_id: str`, `correlation_id: str`, `success: bool`, `error: str | None`, `output_shm_owner: str`, `output_shm_slot: str`, `output_shm_index: int`, `detections: list[dict]`, `masks_count: int`, `processing_time: float`
2. Создать `WorkerPoolDispatcher`:
   - `__init__(self, process_io: ProcessIO, memory_manager, worker_count: int, timeout: float = 5.0, input_queue_size: int = 4)`
   - Хранит `_pending: dict[str, PendingTask]` -- ожидающие ответа задачи (`task_id -> (event, response)`)
   - Хранит `_worker_names: list[str]` -- `["processor_worker_0", ..., "processor_worker_{K-1}"]`
   - `_next_worker: int` -- round-robin индекс
3. `dispatch(step: RunnableStep, frame: np.ndarray, context: ChainContext) -> WorkerTaskResponse`:
   - Записать frame в SHM (через `process_io.write_frames_to_shm`) в слот `"worker_pool_input"`
   - Создать `WorkerTaskRequest` с SHM-координатами
   - Выбрать worker round-robin: `worker_name = self._worker_names[self._next_worker % K]`
   - Отправить request как DATA-сообщение (`data_type="worker_task_request"`) целевому worker-процессу
   - Зарегистрировать pending task
   - Ожидать ответ с timeout (через `threading.Event.wait(timeout)`)
   - При timeout -- вернуть `WorkerTaskResponse(success=False, error="timeout")`
4. `handle_response(msg_dict: dict) -> None`:
   - Вызывается из processing_worker loop при получении `data_type="worker_task_response"`
   - Парсит `WorkerTaskResponse`, находит pending task по `task_id`, сигналит event
5. **Backpressure (drop-oldest):**
   - Если количество pending tasks >= `input_queue_size` -- отбросить самую старую задачу (WARN + increment drop counter)
   - Counter `drops_total: int` для UI/StatsManager

**Критерии приёмки:**
- [ ] `dispatch()` отправляет request через ProcessIO и блокирует до ответа или timeout
- [ ] Round-robin: 3 dispatch'а при K=2 -> worker_0, worker_1, worker_0
- [ ] Timeout -> `WorkerTaskResponse(success=False, error="timeout")`
- [ ] Backpressure: 5 dispatch'ей при queue_size=4 -> drop самого старого
- [ ] `handle_response()` разблокирует соответствующий `dispatch()`

**Вне scope:** Чтение результирующего кадра из SHM worker'а (это делает `CrossProcessEdge`, Task 5c.4).
**Edge cases:**
- Worker не существует (crash) -> timeout -> error
- Два concurrent dispatch к одному worker -> round-robin разведёт

---

### Task 5c.3 -- ProcessorWorkerProcess (worker-процесс)

**Уровень:** Senior (Opus)
**Исполнитель:** teamlead
**Цель:** Отдельный процесс (`ProcessModule`-наследник), принимающий задачи по IPC, исполняющий одну операцию из каталога над кадром из SHM, возвращающий результат через SHM + IPC.

**Файлы (новые):**
- `backend/processes/processor_worker/process.py` -- `ProcessorWorkerProcess(ProcessModule)`
- `backend/processes/processor_worker/adapter.py` -- `WorkerAdapter` (ProcessIO facade)
- `backend/processes/processor_worker/commands.py` -- command table

**Шаги:**
1. `ProcessorWorkerProcess(ProcessModule)`:
   - `_init_application_threads()`:
     a. Создать `FrameShmMiddleware` для чтения входных кадров (owner=processor, slot=worker_pool_input) -- receive middleware
     b. Создать `FrameShmMiddleware` для записи результатов (owner=self.name, slot=worker_result) -- send middleware
     c. Загрузить каталог операций (путь из config, аналогично ProcessorProcess)
     d. Создать worker-thread (`ExecutionMode.LOOP`)
   - `_worker_loop(stop_event, pause_event)`:
     a. `receive_message(timeout=0.1, channel_types=["data"])`
     b. Фильтровать `data_type == "worker_task_request"`
     c. Десериализовать `WorkerTaskRequest`
     d. Прочитать frame из SHM по координатам из request (через MemoryManager)
     e. Загрузить операцию из каталога по `operation_ref` (кэшировать экземпляры)
     f. `operation.configure(request.params)`; `output = operation.execute(frame, context)`
     g. Записать output frame в SHM результата
     h. Собрать side results (detections, masks, contours) через duck-typing
     i. Отправить `WorkerTaskResponse` обратно source-процессу (processor)
   - `shutdown()`: graceful cleanup SHM
2. `WorkerAdapter`:
   - `send_response(target: str, response: WorkerTaskResponse)` -- через ProcessIO.send_data
   - `read_input_frame(owner, slot, index, shape)` -- через MemoryManager.read_images
   - `write_output_frame(frame)` -- через ProcessIO.write_frames_to_shm
3. `commands.py`:
   - `build_command_table(worker)` -- команды health-check, catalog reload

**Критерии приёмки:**
- [ ] Worker стартует как отдельный процесс через SystemLauncher
- [ ] Получает `worker_task_request` -> читает frame из SHM -> execute -> пишет результат в SHM -> отправляет response
- [ ] Кэш операций: повторный запрос с тем же `operation_ref` не пересоздаёт экземпляр
- [ ] Graceful shutdown: SHM cleanup, воркер-thread остановлен
- [ ] Ошибка execute -> response с `success=False, error=str(exc)`

**Вне scope:** Backpressure (это ответственность dispatcher'а в Processor).
**Edge cases:**
- operation_ref не найден в каталоге -> error response
- frame не прочитан из SHM (stale) -> error response
- Worker получает request после shutdown signal -> игнорирует

---

### Task 5c.4 -- CrossProcessEdge: интеграция в chain builder

**Уровень:** Senior+ (Opus)
**Исполнитель:** teamlead
**Цель:** Расширить `GraphRunnableBuilder` и chain execution для поддержки шагов с `process_id` начинающимся с `"worker_pool"` -- такие шаги делегируются через `WorkerPoolDispatcher` вместо локального исполнения.

**Файлы (новые):**
- `services/processor/chain/cross_process_step.py` -- `CrossProcessStep` (обёртка RunnableStep для cross-process dispatch)

**Файлы (изменить):**
- `services/processor/chain/runnable.py` -- расширить `ChainRunnable.execute()` для обработки CrossProcessStep
- `services/processor/chain/parallel_runnable.py` -- аналогичное расширение для `_execute_single()`
- `services/processor/chain/builder.py` -- при `node.process_id.startswith("worker_pool")` создавать `CrossProcessStep`

**Шаги:**
1. Создать `CrossProcessStep`:
   - Наследует / оборачивает `RunnableStep`
   - Дополнительные поля: `dispatcher: WorkerPoolDispatcher` (ссылка, устанавливается builder'ом)
   - Метод `execute_remote(frame, context) -> np.ndarray`:
     a. `response = dispatcher.dispatch(self.step, frame, context)`
     b. Если `response.success` -- прочитать output frame из SHM worker'а (по координатам из response)
     c. Извлечь detections из response, записать в context
     d. Если `not response.success` -- raise Exception (обработается on_error политикой)
2. Расширить `GraphRunnableBuilder.build()`:
   - Новый параметр: `dispatcher: WorkerPoolDispatcher | None = None`
   - При создании `RunnableStep`: если `node.process_id.startswith("worker_pool")` и `dispatcher is not None` -- создать `CrossProcessStep(step, dispatcher)` вместо обычного `RunnableStep`
   - Если `process_id` начинается с `"worker_pool"`, но `dispatcher is None` -- WARN + fallback на локальное исполнение
3. Расширить `ChainRunnable.execute()`:
   - При итерации по steps: если step -- `CrossProcessStep` -> вызвать `step.execute_remote(frame, context)` вместо `step.operation.execute(frame, context)`
   - Остальная логика (on_error, side results collection) остаётся идентичной
4. Расширить `ParallelChainRunnable`:
   - `_execute_single()`: проверка на CrossProcessStep
   - **ВАЖНО:** в parallel bundle cross-process step всегда исполняется "синхронно-блокирующе" (dispatch ждёт ответ). Параллельность внутри bundle сохраняется через ThreadPool -- pool.submit вызывает `execute_remote` в потоке

**Критерии приёмки:**
- [ ] Шаг с `process_id="worker_pool_heavy"` -> dispatch через WorkerPoolDispatcher, не локально
- [ ] Шаг с `process_id="processor"` -> локальное исполнение (как раньше)
- [ ] Если dispatcher=None + process_id="worker_pool_*" -> WARN + локальный fallback
- [ ] Cross-process step в параллельном bundle -> работает через ThreadPool submit
- [ ] on_error=skip + worker timeout -> chain продолжает
- [ ] Backward compat: chain без worker_pool шагов -> идентичное поведение Phase 5b

**Вне scope:** UI для выбора process_id (пока ручная правка в YAML/таблице).

---

### Task 5c.5 -- ProcessorService + ProcessorProcess: интеграция dispatcher

**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Создать `WorkerPoolDispatcher` в ProcessorProcess при инициализации, передать в ProcessorService, подключить обработку ответов от worker'ов.

**Файлы (изменить):**
- `services/processor/service.py` -- добавить `_dispatcher: WorkerPoolDispatcher | None`, передавать в `GraphRunnableBuilder.build()`
- `backend/processes/processor/process.py` -- создать `WorkerPoolDispatcher`, подключить handle_response
- `backend/processes/processor/commands.py` -- handler для `worker_task_response` в воркер-loop

**Шаги:**
1. `ProcessorService.__init__` -- новый параметр `dispatcher: WorkerPoolDispatcher | None = None`. Хранить как `self._dispatcher`.
2. `ProcessorService.rebuild_runnables()` -- передавать `dispatcher=self._dispatcher` в `GraphRunnableBuilder.build()`.
3. `ProcessorProcess._init_application_threads()`:
   a. Прочитать `worker_pool_size` из `app_cfg` (default 0)
   b. Если > 0: создать `WorkerPoolDispatcher(process_io=adapter._io, memory_manager=self.memory_manager, worker_count=worker_pool_size, timeout=app_cfg.get("worker_timeout", 5.0))`
   c. Передать dispatcher в ProcessorService
4. `ProcessorProcess._processing_worker()`:
   a. При получении `data_type == "worker_task_response"` -- вызвать `dispatcher.handle_response(msg_dict)`
   b. Не прерывать обычный цикл обработки frame_ready

**Критерии приёмки:**
- [ ] При worker_pool_size=0 -> dispatcher=None, chain работает без worker pool
- [ ] При worker_pool_size=2 -> dispatcher создан с 2 worker'ами
- [ ] response от worker'а -> dispatcher.handle_response() разблокирует ожидающий dispatch
- [ ] Backward compat: chain без cross-process шагов -> идентично Phase 5b

**Вне scope:** Hot-resize worker pool (изменение K на лету). Отложено.
**Зависимости:** Task 5c.2, Task 5c.4

---

### Task 5c.6 -- main.py: запуск worker pool + end-to-end smoke

**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Обновить точку входа для запуска K worker-процессов из settings profile. Проверить end-to-end: Processor -> worker -> результат.

**Файлы (изменить):**
- `main.py` -- прочитать `worker_pool_size` из profile, передать в AppConfig

**Шаги:**
1. В `_load_cameras_from_profile()` (или рядом): прочитать `worker_pool_size` из active profile (default 0).
2. Передать `worker_pool_size` в `AppConfig(worker_pool_size=..., ...)`.
3. `AppConfig.all_process_configs()` уже генерирует worker-конфиги (Task 5c.1).
4. Smoke-проверка: запустить с profile `worker_pool_size=2`, chain с одним шагом `process_id="worker_pool_heavy"` -> кадры проходят end-to-end.

**Критерии приёмки:**
- [ ] Запуск с `worker_pool_size=2` -> 2 процесса `processor_worker_0`, `processor_worker_1` стартуют
- [ ] Запуск с `worker_pool_size=0` -> без worker-процессов (как раньше)
- [ ] SystemLauncher логирует все процессы при старте

**Вне scope:** Settings profile UI для worker_pool_size.
**Зависимости:** Task 5c.1

---

### Task 5c.7 -- Backpressure: drop-oldest + StatsManager интеграция

**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Реализовать drop-oldest политику на входе worker pool при перегрузке. Экспортировать счётчик drops в StatsManager для UI.

**Файлы (изменить):**
- `services/processor/worker_pool/dispatcher.py` -- drop-oldest логика (уже заложена в Task 5c.2, здесь доработка + stats)
- `backend/processes/processor/process.py` -- экспорт stats в StatsManager

**Шаги:**
1. В `WorkerPoolDispatcher`:
   - При `len(self._pending) >= self._input_queue_size`:
     a. Найти самую старую задачу (по timestamp или FIFO-порядку)
     b. Отменить её (signal event с `success=False, error="dropped"`)
     c. Логировать `logger.warning("Worker pool backpressure: dropped task %s")`
     d. Increment `self._drops_total`
   - Property `stats -> dict`: `{"pending": len(self._pending), "drops_total": self._drops_total, "dispatched_total": self._dispatched_total}`
2. В `ProcessorProcess`:
   - Периодически (каждые N кадров) экспортировать `dispatcher.stats` через `self.update_process_state(custom={"worker_pool": stats})`
   - Или через StatsManager если доступен

**Критерии приёмки:**
- [ ] 5 dispatch'ей при queue_size=3 -> 2 drops
- [ ] Dropped task возвращает response с `success=False, error="dropped"`
- [ ] `dispatcher.stats["drops_total"]` инкрементируется
- [ ] Stats доступны через `update_process_state`

**Вне scope:** UI-виджет для отображения drops (Phase 6).
**Зависимости:** Task 5c.2

---

### Task 5c.8 -- Error handling: timeout + supervisor restart

**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Реализовать AD-7 для cross-process шагов: timeout на ожидание ответа от worker'а + интеграция с on_error политикой из каталога. Проверить supervisor restart при crash worker'а.

**Файлы (изменить):**
- `services/processor/worker_pool/dispatcher.py` -- timeout handling уже в dispatch (5c.2), здесь: logging, retry policy
- `services/processor/chain/cross_process_step.py` -- маппинг timeout -> on_error политика
- `backend/processes/processor_worker/process.py` -- unhandled exception -> graceful error response

**Шаги:**
1. Timeout в `WorkerPoolDispatcher.dispatch()`:
   - `threading.Event.wait(timeout)` возвращает False -> `WorkerTaskResponse(success=False, error="timeout:{timeout}s")`
   - Логировать через ErrorManager: `logger.warning("Worker pool timeout: task %s, worker %s")`
   - Pending task остаётся (worker может вернуть результат позже -- ответ игнорируется)
2. В `CrossProcessStep.execute_remote()`:
   - `response.success == False` -> raise RuntimeError(response.error)
   - ChainRunnable/ParallelChainRunnable обрабатывает exception по `step.on_error` политике из каталога
   - `on_error=skip` + timeout -> chain продолжает со следующим шагом
   - `on_error=fail_region` + timeout -> region выключается
   - `on_error=fail_camera` + timeout -> camera останавливается
3. Supervisor restart (уже в фреймворке):
   - `ProcessManagerProcess` детектит crash child-процесса worker'а
   - Стандартная политика restart (max 3 попытки, exponential backoff)
   - Убедиться что `ProcessorWorkerConfig` задаёт правильный restart policy
   - После restart worker'а -- pipeline продолжает (pending задачи получат timeout, следующие кадры обрабатываются нормально)

**Критерии приёмки:**
- [ ] Worker не отвечает за timeout -> `on_error=skip` -> chain продолжает
- [ ] Worker не отвечает -> `on_error=fail_region` -> region отключён
- [ ] Worker crash (kill -9) -> supervisor restart -> следующие кадры обрабатываются
- [ ] Late response (worker ответил после timeout) -> ответ игнорируется, нет crash
- [ ] Error в операции worker'а -> response с `success=False` -> on_error policy

**Edge cases:**
- Worker crash во время обработки -> timeout -> skip + supervisor restart -> recovery
- Все K worker'ов crash -> все задачи timeout -> pipeline деградирует, не зависает

**Вне scope:** Автоматическое увеличение pool size при перегрузке (auto-scaling).
**Зависимости:** Task 5c.2, Task 5c.3, Task 5c.4

---

### Task 5c.9 -- Тесты Phase 5c (unit + integration)

**Уровень:** Middle+ (Sonnet)
**Исполнитель:** tester
**Цель:** Unit и integration тесты для всех компонентов Phase 5c.

**Файлы (новые):**
- `tests/unit/test_worker_pool_protocol.py` -- сериализация/десериализация WorkerTaskRequest/Response
- `tests/unit/test_worker_pool_dispatcher.py` -- dispatch, round-robin, timeout, backpressure (с mock ProcessIO)
- `tests/unit/test_cross_process_step.py` -- CrossProcessStep с mock dispatcher
- `tests/unit/test_processor_worker_config.py` -- конфигурация, all_process_configs
- `tests/integration/test_worker_pool_execution.py` -- L2: полный pipeline Processor + 1 worker через multiprocessing

**Шаги:**
1. `test_worker_pool_protocol.py`:
   - `WorkerTaskRequest` сериализация `to_dict()` / `from_dict()` round-trip
   - `WorkerTaskResponse` с success/error/detections
   - Валидация обязательных полей

2. `test_worker_pool_dispatcher.py`:
   - Mock `ProcessIO`: перехват send_data вызовов
   - Round-robin: 3 dispatch'а при K=2 -> targets корректны
   - Timeout: dispatch без response -> timeout error
   - Backpressure: overflow -> drop-oldest
   - handle_response: разблокирует pending dispatch (через threading.Event)

3. `test_cross_process_step.py`:
   - Mock dispatcher, mock step
   - success response -> frame корректно возвращён
   - error response -> RuntimeError raised
   - on_error=skip + error -> chain продолжает

4. `test_processor_worker_config.py`:
   - `ProcessorWorkerConfig(worker_index=2).process_name == "processor_worker_2"`
   - `AppConfig(worker_pool_size=3).all_process_configs()` содержит 3 worker-конфига
   - `AppConfig(worker_pool_size=0)` -- нет worker-конфигов

5. `test_worker_pool_execution.py` (L2, integration):
   - Стартовать minimal config: 1 fake camera + 1 processor + 1 processor_worker
   - Chain с одним шагом `process_id="worker_pool_heavy"` (ColorDetectionOp)
   - Inject 3 кадра -> все обработаны worker'ом -> detections получены processor'ом
   - Маркер `@pytest.mark.slow`

**Критерии приёмки:**
- [ ] Все unit тесты без multiprocessing / Qt / реальных процессов
- [ ] L2: end-to-end через multiprocessing -- кадр прошёл Processor -> Worker -> Processor
- [ ] Timeout тест: mock worker не отвечает -> dispatcher возвращает error
- [ ] Backpressure тест: overflow -> drops counter > 0
- [ ] Backward compat: тесты Phase 5a/5b проходят без изменений

**Вне scope:** GUI тесты.
**Зависимости:** Task 5c.1--5c.8

---

## Граф зависимостей

```
5c.1 (WorkerConfig) ───────────────────────┐
                                            ├──→ 5c.6 (main.py + smoke)
5c.2 (Dispatcher) ──┬──→ 5c.5 (Service интеграция) ──→ 5c.6
                    ├──→ 5c.7 (Backpressure + stats)
                    └──→ 5c.8 (Error handling)
                    │
5c.3 (WorkerProcess) ──→ 5c.8
                    │
5c.4 (CrossProcessEdge) ──→ 5c.5
                    │
                    └──────────────────────→ 5c.9 (Тесты, зависит от всех)
```

## Порядок исполнения

### Batch 1 (параллельно):
- Task 5c.1 -- WorkerConfig [DONE]
- Task 5c.2 -- WorkerPoolDispatcher [DONE]
- Task 5c.3 -- ProcessorWorkerProcess [DONE]

### Batch 2 (параллельно):
- Task 5c.4 -- CrossProcessEdge [DONE] (зависит от 5c.2)
- Task 5c.7 -- Backpressure + stats [DONE] (dispatcher stats + экспорт через update_process_state)

### Batch 3:
- Task 5c.5 -- Service интеграция [DONE] (зависит от 5c.2, 5c.4)

### Batch 4 (параллельно):
- Task 5c.6 -- main.py + smoke [DONE] (зависит от 5c.1, 5c.5)
- Task 5c.8 -- Error handling [DONE] (зависит от 5c.2, 5c.3, 5c.4)

### Batch 5:
- Task 5c.9 -- Тесты [DONE] (67 unit-тестов: protocol, dispatcher, cross_process_step, config)

---

## Ключевые файлы

| Что | Путь | Действие |
|-----|------|----------|
| AppConfig | `config/app.py` | Расширить (5c.1) |
| main.py | `main.py` | Расширить (5c.6) |
| ProcessorConfig | `backend/processes/processor/config.py` | Не менять |
| ProcessorProcess | `backend/processes/processor/process.py` | Расширить dispatcher (5c.5) |
| ProcessorService | `services/processor/service.py` | Расширить dispatcher (5c.5) |
| Processor commands | `backend/processes/processor/commands.py` | Handler для response (5c.5) |
| GraphRunnableBuilder | `services/processor/chain/builder.py` | Расширить dispatcher param (5c.4) |
| ChainRunnable | `services/processor/chain/runnable.py` | CrossProcessStep support (5c.4) |
| ParallelChainRunnable | `services/processor/chain/parallel_runnable.py` | CrossProcessStep support (5c.4) |
| ProcessingNode | `registers/pipeline/processing_node.py` | Не менять (process_id уже есть) |
| ChainContext | `services/processor/operations/base.py` | Не менять (timeouts уже есть) |

**Новые файлы:**
- `backend/processes/processor_worker/__init__.py`
- `backend/processes/processor_worker/config.py` -- ProcessorWorkerConfig
- `backend/processes/processor_worker/process.py` -- ProcessorWorkerProcess
- `backend/processes/processor_worker/adapter.py` -- WorkerAdapter
- `backend/processes/processor_worker/commands.py` -- command table
- `services/processor/worker_pool/__init__.py`
- `services/processor/worker_pool/dispatcher.py` -- WorkerPoolDispatcher
- `services/processor/worker_pool/protocol.py` -- WorkerTaskRequest/Response
- `services/processor/chain/cross_process_step.py` -- CrossProcessStep

---

## Протокол обмена данными (cross-process)

```
Processor_{id}                             ProcessorWorker_{n}
     |                                            |
     |  [1] write frame to SHM                    |
     |       (worker_pool_input)                   |
     |                                            |
     |  [2] send WorkerTaskRequest                |
     |       (data_type="worker_task_request")     |
     |  ────────────────────────────────────────> |
     |                                            |
     |                          [3] read frame from SHM
     |                          [4] execute operation
     |                          [5] write result to SHM
     |                               (worker_{n}_result)
     |                                            |
     |  [6] send WorkerTaskResponse               |
     |       (data_type="worker_task_response")    |
     |  <──────────────────────────────────────── |
     |                                            |
     |  [7] read result from SHM                  |
     |  [8] continue chain                        |
```

---

## Важные конвенции (из handoff Phase 5a/5b)

1. **Короткие импорты:** `from services...`, `from registers...` (не `from multiprocess_prototype_v3.services...`) в коде v3. В тестах -- `sys.path.insert(0, v3_root)` через conftest.
2. **frame.copy() при fan-out:** worker получает кадр через SHM (read -- это уже копия из shared memory в numpy), дополнительный copy не нужен.
3. **Составной ключ runnables:** `"{cam_id}/{region_id}"` для уникальности.
4. **Backward compat через dual path:** если worker_pool_size=0 -- всё работает как в Phase 5b.
5. **Builder сам выбирает:** sequential vs parallel vs cross-process -- по node.process_id и наличию dispatcher/pool.
6. **НЕ коммитить:** проект в `.gitignore` основного репо.

---

## Риски и ограничения

1. **SHM координация:** Processor пишет кадр в SHM `worker_pool_input`, worker читает. Если Processor перезаписывает slot до прочтения worker'ом -- data corruption. Решение: использовать уникальный `shm_index` per task (find_free_index) + хранить координаты в request.
2. **IPC latency:** round-trip через Queue добавляет 0.5-2ms. Для операций <5ms cross-process нецелесообразен. Пользователь должен помечать только действительно тяжёлые шаги (>50ms) как `worker_pool`.
3. **Серилизация через dict:** WorkerTaskRequest/Response сериализуются в dict (Dict at Boundary). numpy frames через SHM, не через IPC.
4. **Worker crash:** supervisor (ProcessManagerProcess) рестартит worker, но pending задачи получат timeout. Это ожидаемо -- pipeline деградирует на 1 timeout, потом восстанавливается.
5. **GIL не ограничение:** каждый worker -- отдельный процесс, GIL не разделяется. Это главное преимущество Phase 5c перед 5b.

---

## Верификация

1. **Unit:** `pytest tests/unit/test_worker_pool_*.py tests/unit/test_cross_process_step.py tests/unit/test_processor_worker_config.py -v`
2. **L2:** `pytest tests/integration/test_worker_pool_execution.py -v -m slow`
3. **Все тесты:** `pytest multiprocess_prototype_v3/tests/ -v`
4. **Ruff:** `ruff check && ruff format --check`
5. **Smoke:** Запуск с `worker_pool_size=2` + chain с heavy-шагом `process_id="worker_pool_heavy"` -> кадры проходят end-to-end -> drops=0 при нормальной нагрузке -> kill worker -> supervisor restart -> pipeline восстанавливается
