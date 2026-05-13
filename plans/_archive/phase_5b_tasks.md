# Phase 5b: Threading Workers внутри процесса Processor — План реализации

**Дата:** 2026-04-22
**Статус:** DRAFT

## Обзор

Phase 5a ввела per-region chain runnables с последовательным выполнением шагов. Phase 5b добавляет параллельное выполнение независимых шагов через `ThreadPoolExecutor` внутри процесса `Processor_{id}`. Ключевые элементы: определение параллельных "бандлов" из topological sort, per-frame barrier (кадр N+1 не стартует пока N не завершён), timeout/watchdog, UI колонка worker (dropdown).

Все пути относительно `multiprocess_prototype/`.

---

## Задачи

### Task 5b.1 — Parallel Bundle Detector (анализ графа)

**Уровень:** Senior (Opus)
**Исполнитель:** teamlead
**Цель:** Алгоритм разбиения topological sort на "уровни" (bundles) — группы нод без взаимных зависимостей, которые можно исполнять параллельно.

**Файлы (новые):**
- `services/processor/chain/parallel.py` — `detect_parallel_bundles(steps: list[RunnableStep], nodes: dict[str, ProcessingNode]) -> list[list[RunnableStep]]`

**Шаги:**
1. Принять на вход список `RunnableStep` (уже topologically sorted) и исходный dict нод (для доступа к `inputs`).
2. Построить множество зависимостей для каждой ноды: `deps[node_id] = set(source_node_ids)`.
3. Используя алгоритм "уровней" (level assignment): нода без зависимостей → уровень 0; нода с зависимостями → `max(level[dep]) + 1`. Ноды с одинаковым уровнем образуют один bundle.
4. Дополнительное условие: ноды с явным `worker_id` (не None) — НЕ объединяются в бандл с нодами, имеющими другой `worker_id`. Ноды с `worker_id=None` объединяются свободно.
5. Бандл из 1 ноды — не требует параллелизма, исполняется как раньше.
6. Вернуть `list[list[RunnableStep]]` — каждый внутренний список = один bundle (уровень).

**Критерии приёмки:**
- [ ] Линейная цепочка A→B→C → 3 бандла по 1 ноде
- [ ] DAG: A→C, B→C (A и B независимы) → bundle[0]=[A,B], bundle[1]=[C]
- [ ] Ноды с разным явным `worker_id` на одном уровне → разделены в отдельные бандлы
- [ ] Пустой список → пустой результат

**Вне scope:** Собственно параллельное исполнение — только анализ графа.

---

### Task 5b.2 — ThreadPool Manager (lifecycle)

**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Обёртка над `ThreadPoolExecutor` с настраиваемым размером пула, graceful shutdown и timeout на submit.

**Файлы (новые):**
- `services/processor/chain/thread_pool.py` — класс `ChainThreadPool`

**Шаги:**
1. `ChainThreadPool.__init__(max_workers: int, step_timeout: float = 10.0)` — создать `ThreadPoolExecutor(max_workers)`. Хранить `step_timeout`.
2. `submit_bundle(steps: list[RunnableStep], frame: np.ndarray, context: ChainContext) -> list[Future]` — для каждого step в bundle отправить `executor.submit(step.operation.execute, frame, context)`. Вернуть list futures.
3. `collect_results(futures: list[Future], steps: list[RunnableStep], timeout: float | None = None) -> list[tuple[RunnableStep, np.ndarray | Exception]]` — `concurrent.futures.wait(futures, timeout=timeout or self._step_timeout)`. Для каждого future: если done — result(); если not done или exception — вернуть Exception. Логировать WARN для timeout.
4. `shutdown(wait: bool = True)` — graceful shutdown executor.
5. `resize(max_workers: int)` — пересоздать executor с новым размером (shutdown старого + создание нового). Атомарность: через lock.
6. Property `max_workers` — текущий размер пула.

**Критерии приёмки:**
- [ ] Создание пула с max_workers=2 → executor.\_max_workers == 2
- [ ] submit_bundle с 2 steps → 2 futures
- [ ] collect_results: timeout → WARN в логе + Exception для "зависшего" step
- [ ] shutdown → executor закрыт, повторный submit → RuntimeError
- [ ] resize(4) → новый executor с 4 workers

**Вне scope:** Интеграция с ChainRunnable (Task 5b.3).

---

### Task 5b.3 — ParallelChainRunnable (параллельный executor)

**Уровень:** Senior+ (Opus)
**Исполнитель:** teamlead
**Цель:** Новый класс `ParallelChainRunnable`, расширяющий логику `ChainRunnable` — исполняет бандлы параллельно через `ChainThreadPool`, с per-frame barrier и merge результатов.

**Файлы (новые):**
- `services/processor/chain/parallel_runnable.py` — `ParallelChainRunnable`

**Файлы (изменить):**
- `services/processor/chain/__init__.py` — добавить экспорт `ParallelChainRunnable`

**Шаги:**
1. `ParallelChainRunnable.__init__(bundles: list[list[RunnableStep]], pool: ChainThreadPool)`.
2. `execute(frame, metadata) -> ChainResult` — основной метод:
   a. Создать `ChainContext` из metadata (как в текущем `ChainRunnable.execute`).
   b. Итерировать по bundles последовательно (каждый bundle — barrier).
   c. Для bundle из 1 step — вызвать синхронно (без overhead пула).
   d. Для bundle из 2+ steps — `pool.submit_bundle(steps, current_frame, context)` → `pool.collect_results(futures, steps)`.
   e. **Merge результатов bundle:** все steps в bundle получают один и тот же `current_frame` (fan-out). Результат merge: кадр от последнего step в исходном topological порядке (т.к. они не зависят друг от друга, каждый возвращает свою версию — для Phase 5b берём frame от первого step, побочные результаты собираем со всех). **Альтернативный подход:** если все steps возвращают тот же frame (детекции — побочные эффекты), frame не мержится, а передаётся дальше как есть. Это корректно для операций-детекторов (ColorDetection, BlobDetection).
   f. Собрать side results (`_collect_side_results`) из каждого step bundle.
   g. Обработать ошибки по `on_error` политике — аналогично `ChainRunnable`.
3. **Per-frame barrier:** метод `execute()` блокирующий — возвращает `ChainResult` только когда все bundles завершены. Это гарантирует, что вызывающий код (`_process_frame_via_chain`) не начнёт следующий кадр раньше.
4. Property `steps` — flattened список всех steps (для совместимости).

**Критерии приёмки:**
- [ ] 2 независимых step (A, B без зависимостей) → исполняются в разных потоках (проверка через `threading.current_thread().name` в mock операциях)
- [ ] Линейная цепочка A→B→C → 3 sequential bundles, результат идентичен `ChainRunnable`
- [ ] Per-frame barrier: execute() блокирует до завершения всех bundles
- [ ] Timeout step → WARN + on_error policy применяется
- [ ] Side results (detections, masks, contours) собраны со всех параллельных steps

**Вне scope:** Управление seq_id ordering (это ответственность вызывающего кода — service уже sequential).
**Edge cases:**
- Один step в bundle с exception + on_error=skip → другие steps bundle завершаются нормально
- Все steps в bundle failed + on_error=fail_region → bundle прерывает chain

---

### Task 5b.4 — GraphRunnableBuilder: выбор sequential/parallel

**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Расширить `GraphRunnableBuilder.build()` — если `max_workers > 1` и есть параллельные bundles, возвращать `ParallelChainRunnable`; иначе — `ChainRunnable` (без regression).

**Файлы (изменить):**
- `services/processor/chain/builder.py` — расширить `build()` новым параметром `pool: ChainThreadPool | None = None`

**Шаги:**
1. Добавить параметр `pool: ChainThreadPool | None = None` в `GraphRunnableBuilder.build()`.
2. После topological sort + создания steps: вызвать `detect_parallel_bundles(steps, active_nodes)`.
3. Если `pool is not None` и хотя бы один bundle содержит > 1 step → вернуть `ParallelChainRunnable(bundles, pool)`.
4. Иначе → вернуть `ChainRunnable(steps)` как раньше (полная обратная совместимость).
5. Логировать: "Цепочка построена: N шагов, M параллельных бандлов" или "Цепочка линейная, параллелизм не требуется".

**Критерии приёмки:**
- [ ] `build(nodes, catalog)` без pool → `ChainRunnable` (backward compat)
- [ ] `build(nodes, catalog, pool=pool)` с 2 независимыми нодами → `ParallelChainRunnable`
- [ ] `build(nodes, catalog, pool=pool)` с линейной цепочкой → `ChainRunnable`
- [ ] Все существующие тесты `test_chain_builder.py` проходят без изменений

**Вне scope:** Изменение сигнатуры `ChainRunnable.__init__`.

---

### Task 5b.5 — ProcessorService + ProcessorProcess: интеграция ThreadPool

**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** Создать `ChainThreadPool` в ProcessorProcess при инициализации, передать в ProcessorService, использовать при rebuild_runnables.

**Файлы (изменить):**
- `services/processor/service.py` — добавить `_pool: ChainThreadPool | None`, передавать в `GraphRunnableBuilder.build()`
- `backend/processes/processor/process.py` — создать `ChainThreadPool(workers_per_processor)` при инициализации, передать в service, shutdown при выключении

**Шаги:**
1. `ProcessorService.__init__` — новый параметр `pool: ChainThreadPool | None = None`. Хранить как `self._pool`.
2. `ProcessorService.rebuild_runnables()` — передавать `pool=self._pool` в `GraphRunnableBuilder.build()`.
3. `ProcessorService.resize_pool(max_workers: int)` — делегировать `self._pool.resize(max_workers)` + `rebuild_runnables()`. Для реакции на смену `workers_per_processor` из settings.
4. `ProcessorProcess._init_application_threads()`:
   a. Прочитать `workers_per_processor` из `app_cfg` (default 2).
   b. Прочитать `step_timeout` из `app_cfg` (default 10.0).
   c. Создать `ChainThreadPool(max_workers, step_timeout)`.
   d. Передать pool в `ProcessorService`.
5. `ProcessorProcess.shutdown()` — вызвать `pool.shutdown()` перед `super().shutdown()`.
6. `commands.py` — добавить handler для register_update по ключу `workers_per_processor`: вызывать `service.resize_pool(value)`.

**Файлы (изменить дополнительно):**
- `backend/processes/processor/commands.py` — handler для `workers_per_processor`

**Критерии приёмки:**
- [ ] При workers_per_processor=1 → все chain'ы — ChainRunnable (без параллелизма)
- [ ] При workers_per_processor=2 и 2 независимых ноды → ParallelChainRunnable
- [ ] Смена workers_per_processor через register_update → pool.resize() + rebuild
- [ ] Shutdown: pool.shutdown() вызывается
- [ ] Backward compat: без nodes → legacy path работает

**Вне scope:** Per-frame barrier на уровне IPC (кадры уже приходят последовательно из воркера).

---

### Task 5b.6 — Watchdog: timeout + recovery

**Уровень:** Middle+ (Sonnet)
**Исполнитель:** developer
**Цель:** При timeout thread'а — WARN в лог + применение on_error политики + восстановление (cancel future, пул продолжает работать).

**Файлы (изменить):**
- `services/processor/chain/thread_pool.py` — расширить `collect_results()` логикой recovery
- `services/processor/chain/parallel_runnable.py` — обработка timeout-exception из collect_results

**Шаги:**
1. В `ChainThreadPool.collect_results()`: для future не завершившихся за timeout — вызвать `future.cancel()`. Если cancel не удался (thread уже запущен) — пометить как `TimeoutError`. Логировать `logger.warning(f"Операция '{step.node.operation_ref}' превысила timeout {timeout}s")`.
2. В `ParallelChainRunnable.execute()`: при получении `TimeoutError` от collect_results — обработать как exception в соответствии с `step.on_error`.
3. Счётчик timeout'ов в `ChainResult.context` — добавить поле `timeouts: list[str]` в `ChainContext` (node_id зависших нод).

**Файлы (изменить дополнительно):**
- `services/processor/operations/base.py` — добавить `timeouts: list[str] = field(default_factory=list)` в `ChainContext`

**Критерии приёмки:**
- [ ] Step с sleep(20) + timeout=1 → TimeoutError → WARN в логе
- [ ] on_error=skip + timeout → chain продолжает со следующим bundle
- [ ] on_error=fail_region + timeout → chain прерывается
- [ ] Пул не "ломается" после timeout — следующий кадр обрабатывается нормально
- [ ] `ChainContext.timeouts` содержит node_id зависшего step

**Edge cases:**
- Все steps в bundle timeout → chain failed
- Timeout на первом bundle, остальные не запускаются при fail_region

---

### Task 5b.7 — UI: колонка Worker (dropdown)

**Уровень:** Middle (Sonnet)
**Исполнитель:** developer
**Цель:** Заменить readonly QLabel в колонке Worker на QComboBox с вариантами: "auto" (= None), "worker_0", "worker_1", ..., "worker_{N-1}" (N = workers_per_processor).

**Файлы (изменить):**
- `frontend/widgets/chain_editor/panel_widget.py` — заменить QLabel на QComboBox в `_fill_row()` для `_COL_WORKER`, добавить handler `_on_worker_changed()`
- `frontend/widgets/chain_editor/panel_widget.py` — обновить `get_nodes()` для чтения worker_id из QComboBox
- `frontend/widgets/chain_editor/panel_widget.py` — добавить метод `set_worker_count(count: int)` для обновления dropdown вариантов
- `frontend/widgets/chain_editor/model.py` — добавить `worker_count: int = 2` в `ChainEditorModel`
- `frontend/widgets/chain_editor/presenter.py` — передавать `worker_count` при load

**Шаги:**
1. `ChainEditorModel`: добавить поле `worker_count: int = 2`.
2. `ChainEditorWidget._fill_row()`: колонка `_COL_WORKER` — `QComboBox` с items: `["auto", "worker_0", "worker_1", ...]`. Количество worker items = `self._worker_count`. Текущее значение: если `node.worker_id is None` → "auto", иначе `node.worker_id`.
3. `ChainEditorWidget.set_worker_count(count: int)` — обновить `self._worker_count`, пересоздать dropdown'ы.
4. `ChainEditorWidget.get_nodes()`: для worker колонки — `combo.currentData()` где "auto" → `None`, "worker_N" → `"worker_N"`.
5. `ChainEditorWidget._on_worker_changed()`: аналогично `_on_operation_changed` — синхронизировать `worker_id` в `self._nodes`.
6. `ChainEditorPresenter.load()`: передавать `worker_count` в виджет.

**Критерии приёмки:**
- [ ] Колонка Worker показывает QComboBox вместо QLabel
- [ ] Варианты: "auto", "worker_0", "worker_1" (при worker_count=2)
- [ ] Выбор "auto" → node.worker_id = None
- [ ] Выбор "worker_1" → node.worker_id = "worker_1"
- [ ] Изменение worker_count → dropdown обновляется
- [ ] `get_nodes()` корректно читает worker_id из combo

**Вне scope:** Визуализация текущей загрузки worker'ов. Привязка worker_id к конкретному thread (это делает пул автоматически в Phase 5b).

---

### Task 5b.8 — Тесты Phase 5b

**Уровень:** Middle+ (Sonnet)
**Исполнитель:** tester
**Цель:** Unit и integration тесты для всех компонентов Phase 5b.

**Файлы (новые):**
- `tests/unit/test_parallel_bundles.py` — тесты `detect_parallel_bundles()`
- `tests/unit/test_chain_thread_pool.py` — тесты `ChainThreadPool`
- `tests/unit/test_parallel_runnable.py` — тесты `ParallelChainRunnable` с mock-операциями
- `tests/integration/test_parallel_chain_execution.py` — L2: реальная chain с 2 независимыми операциями + numpy frame → параллельное исполнение

**Шаги:**
1. `test_parallel_bundles.py`:
   - Линейная цепочка → N bundles по 1
   - DAG с параллельными ветками → корректные bundles
   - Разный worker_id → разделение
   - Пустой вход → пустой выход

2. `test_chain_thread_pool.py`:
   - Создание / shutdown
   - submit_bundle → futures
   - collect_results: normal / timeout / exception
   - resize

3. `test_parallel_runnable.py`:
   - 2 параллельных step → исполнение в разных threads (проверка `threading.current_thread().ident`)
   - Side results merge
   - Error handling + on_error
   - Timeout recovery
   - Per-frame barrier: execute блокирует

4. `test_parallel_chain_execution.py`:
   - Реальные ColorDetectionOp + BlobDetectionOp параллельно
   - Результат: detections собраны с обоих
   - seq_id строго возрастает при обработке 3 кадров подряд

**Критерии приёмки:**
- [ ] Все unit тесты без Qt/OpenCV (mock-операции, синтетические frames)
- [ ] L2: real chain + numpy frame → detections, параллельное исполнение подтверждено
- [ ] Timeout тест: mock operation с sleep → watchdog срабатывает
- [ ] Backward compat: `ChainRunnable` тесты из Phase 5a проходят без изменений

**Вне scope:** GUI тесты (chain editor dropdown).

---

## Граф зависимостей

```
5b.1 (Bundle Detector) ──┐
                          ├──→ 5b.3 (ParallelChainRunnable) ──→ 5b.4 (Builder расширение) ──→ 5b.5 (Service интеграция)
5b.2 (ThreadPool Manager)┘                                                                         │
                                                                                                    │
5b.6 (Watchdog) ← 5b.2 + 5b.3                                                                     │
                                                                                                    ├──→ 5b.8 (Тесты)
5b.7 (UI Worker dropdown) — независима (только frontend)                                           │
```

## Порядок исполнения

### Batch 1 (параллельно):
- Task 5b.1 — Bundle Detector [PENDING]
- Task 5b.2 — ThreadPool Manager [PENDING]
- Task 5b.7 — UI Worker dropdown [PENDING]

### Batch 2:
- Task 5b.3 — ParallelChainRunnable [PENDING] (зависит от 5b.1 + 5b.2)

### Batch 3:
- Task 5b.4 — Builder расширение [PENDING] (зависит от 5b.1 + 5b.3)
- Task 5b.6 — Watchdog timeout [PENDING] (зависит от 5b.2 + 5b.3)

### Batch 4:
- Task 5b.5 — Service интеграция [PENDING] (зависит от 5b.4)

### Batch 5:
- Task 5b.8 — Тесты [PENDING] (зависит от всех)

---

## Ключевые файлы

| Что | Путь | Действие |
|-----|------|----------|
| ChainRunnable (текущий) | `services/processor/chain/runnable.py` | Не менять (оставить как sequential fallback) |
| GraphRunnableBuilder | `services/processor/chain/builder.py` | Расширить (5b.4) |
| ChainContext | `services/processor/operations/base.py` | Добавить `timeouts` (5b.6) |
| ProcessingNode | `registers/pipeline/processing_node.py` | Не менять (worker_id уже есть) |
| ProcessorService | `services/processor/service.py` | Расширить pool (5b.5) |
| ProcessorProcess | `backend/processes/processor/process.py` | Создать pool (5b.5) |
| Processor commands | `backend/processes/processor/commands.py` | Handler для workers_per_processor (5b.5) |
| ChainEditorWidget | `frontend/widgets/chain_editor/panel_widget.py` | Worker dropdown (5b.7) |
| ChainEditorModel | `frontend/widgets/chain_editor/model.py` | worker_count (5b.7) |
| AppSettings | `registers/settings/schemas.py` | Уже есть `workers_per_processor` — не менять |

**Новые файлы:**
- `services/processor/chain/parallel.py` — detect_parallel_bundles
- `services/processor/chain/thread_pool.py` — ChainThreadPool
- `services/processor/chain/parallel_runnable.py` — ParallelChainRunnable

---

## Риски и ограничения

1. **GIL и NumPy:** NumPy-heavy операции (detect, threshold) отпускают GIL при C-level вычислениях — параллелизм через threads реально ускоряет. Но чистый Python-код (цикл по контурам) будет сериализован GIL. Это ожидаемо и приемлемо для Phase 5b — полный параллелизм через процессы в Phase 5c.
2. **Thread safety операций:** каждый step получает свой экземпляр операции (создаётся builder'ом) → нет shared state между threads. Операции НЕ должны мутировать frame — если мутируют, нужен `frame.copy()` перед submit. В текущих ColorDetectionOp / BlobDetectionOp — frame не мутируется (cv2 создаёт новые массивы).
3. **Frame copy для fan-out:** при параллельном bundle все steps получают один `current_frame`. Если операция мутирует frame in-place — race condition. Решение: `ParallelChainRunnable` делает `frame.copy()` для каждого step в bundle размером > 1.
4. **Future cancel:** `ThreadPoolExecutor.Future.cancel()` работает только если task ещё не начался. Для уже запущенного — нет механизма принудительного kill. Timeout → WARN + продолжение.

---

## Верификация

1. **Unit:** `pytest tests/unit/test_parallel_bundles.py tests/unit/test_chain_thread_pool.py tests/unit/test_parallel_runnable.py -v`
2. **L2:** `pytest tests/integration/test_parallel_chain_execution.py -v`
3. **Все тесты:** `pytest multiprocess_prototype/tests/ -v`
4. **Ruff:** `ruff check && ruff format --check`
5. **Smoke:** Запуск прототипа → 2 независимые ноды в chain → проверить что CPU > 1 core → disable одну → chain продолжает sequential → seq_id строго возрастает
