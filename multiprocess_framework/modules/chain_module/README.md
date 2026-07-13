# chain_module

DAG/Chain execution engine для многопроцессных PySide6-приложений (Phase 2.3).

Модуль предоставляет универсальный движок исполнения pipeline-операций: последовательные цепочки, DAG с ветвлениями, параллельные бандлы, cross-process шаги через worker pool.

---

## Архитектура

### Исполнители

- **ChainRunnable** — последовательная цепочка. Получает список `RunnableStep`, применяет операции по порядку. Ошибки обрабатываются согласно `on_error` политике шага.
- **DagRunnable** — DAG (directed acyclic graph). Поддерживает ветвления 1→N и слияния N→1 через именованные порты (`port_data`). Исполняет по топологическому порядку.
- **ParallelChainRunnable** — параллельные бандлы через `ChainThreadPool`. Бандлы исполняются последовательно (barrier), шаги внутри бандла — параллельно.

### Graph utilities

- **topological_sort** — алгоритм Кана для ациклических графов нод.
- **is_nonlinear_graph** — определяет, нужен ли `DagRunnable` вместо `ChainRunnable`.
- **detect_parallel_bundles** — разбивает топологически отсортированные шаги на уровни для параллельного исполнения.

### Worker pool

- **WorkerTaskRequest / WorkerTaskResponse** — IPC-протокол между Processor и Worker-процессами. Dict at Boundary.
- **WorkerPoolDispatcher** — round-robin маршрутизация задач по worker-процессам. Backpressure (drop oldest), timeout, thread-safe.

### Metrics

- **LatencyTracker** — накапливает измерения latency, вычисляет p50/p95/p99 (linear interpolation). Интегрирован с `BaseManager + ObservableMixin`: каждый `record()` пишется в `stats` через `_record_timing`, `maybe_log()` публикует snapshot p50/p95/p99 как отдельные метрики.

### Observability

`ChainThreadPool`, `WorkerPoolDispatcher`, `LatencyTracker` наследуются от `BaseManager + ObservableMixin`. Принимают `logger=None`, `stats=None`, `errors=None` опционально:

| Сервис | Метрики (counter) | Метрики (timing) |
|--------|-------------------|------------------|
| `WorkerPoolDispatcher` | `worker_pool.dispatched`, `.timeouts`, `.drops`, `.late_responses`, `.errors` | `worker_pool.processing_time` |
| `LatencyTracker` | `<name>.p50`, `.p95`, `.p99` (snapshot per `maybe_log()`) | `<name>` per `record()` (default `chain.latency_ms`) |

Tag `operation` / `worker` добавляется где есть контекст. Если `stats` не передан — метрики тихо игнорируются (`_call_manager` возвращает `None`).

---

## Протоколы (interfaces.py)

| Протокол | Назначение |
|----------|-----------|
| `IStepNode` | Дескриптор ноды: node_id, operation_ref, inputs |
| `IStepNodeWithWorker` | Нода с worker-affinity: + worker_id |
| `INodeConnection` | Соединение: source, input_port, output_port |
| `IExecutionStep` | Операция: execute(data, context), configure(params) |
| `IChainRunnable` | Цепочка: execute(payload, metadata) → ChainResult (payload duck-typed: ndarray-кадр ИЛИ list[dict] items) |
| `IRemoteExecutable` | Cross-process шаг: dispatcher + execute_remote(frame, ctx, shm_name, shm_index) |

Доменные классы прототипа (`ProcessingNode`, `ProcessingOperation`, `CrossProcessStep`) реализуют эти протоколы структурно (duck-typing). `_is_cross_process(step)` определяет cross-process шаги через `hasattr` и поддерживается всеми тремя исполнителями (`ChainRunnable`, `DagRunnable`, `ParallelChainRunnable`).

## Обработка ошибок

Единая on_error политика — в `core/error_policy.apply_on_error_policy(step, exc, context, result)`:

| `on_error` | Поведение | Эффект |
|-----------|-----------|--------|
| `"skip"` | warning, продолжаем цепочку | `result.skipped_nodes.append(node_id)` |
| `"fail_region"` | error, прерываем цепочку | `result.failed=True`, `fail_level="region"` |
| `"fail_camera"` (или любое другое) | error, прерываем цепочку | `result.failed=True`, `fail_level="camera"` |

---

## Использование

```python
from multiprocess_framework.modules.chain_module import (
    ChainRunnable,
    ChainThreadPool,
    RunnableStep,
    ChainContext,
    detect_parallel_bundles,
    WorkerPoolDispatcher,
)

# Линейная цепочка
chain = ChainRunnable(steps=[step1, step2, step3])
result = chain.execute(frame, metadata={"camera_id": "cam_0", "seq_id": 42})

# Параллельная цепочка
pool = ChainThreadPool(max_workers=4, step_timeout=5.0)
bundles = detect_parallel_bundles(steps, nodes)
chain = ParallelChainRunnable(bundles=bundles, pool=pool)

# Worker pool dispatcher
dispatcher = WorkerPoolDispatcher(send_fn=router.send, worker_count=2)
response = dispatcher.dispatch(operation_ref="blur", ...)
dispatcher.handle_response(response_dict)
```

---

## Граница фреймворк / прототип

| В фреймворке | В прототипе |
|-------------|------------|
| Execution engines (Chain, DAG, Parallel) | `builder.py` — сборка из domain-каталога |
| Graph algorithms (topology, bundles) | `autofill.py` — Pydantic-специфичный |
| Worker pool protocol + dispatcher | `cross_process_step.py` — domain wrapper |
| ChainContext, ChainResult, RunnableStep | `ChainContext` re-export из fw |
| LatencyTracker | domain operations (`operations/base.py`) |
