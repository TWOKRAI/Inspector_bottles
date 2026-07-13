# chain_module — STATUS

**Статус:** ✅ Готов (Phase 2.3 + точечная полировка 2026-05-07)

## Реализовано

| Компонент | Файл | Строк |
|-----------|------|-------|
| Публичные контракты | `interfaces.py` | ~95 |
| ChainContext | `core/context.py` | ~38 |
| ChainResult, RunnableStep | `core/result.py` | ~63 |
| apply_on_error_policy (общая on_error логика) | `core/error_policy.py` | ~75 |
| ChainRunnable | `core/chain.py` | ~95 |
| DagRunnable | `core/dag.py` | ~155 |
| ParallelChainRunnable | `core/parallel.py` | ~165 |
| topological_sort, is_nonlinear_graph | `graph/topology.py` | ~87 |
| detect_parallel_bundles | `graph/bundles.py` | ~86 |
| ChainThreadPool (BaseManager + ObservableMixin) | `thread_pool/pool.py` | ~116 |
| WorkerTaskRequest/Response | `worker_pool/protocol.py` | ~145 |
| WorkerPoolDispatcher (BaseManager + ObservableMixin) | `worker_pool/dispatcher.py` | ~245 |
| LatencyTracker (BaseManager + ObservableMixin, linear-interpolation percentiles) | `metrics/latency.py` | ~110 |
| **Итого (без тестов)** | | **~1,610** |

## Зависимости

- `numpy` — ChainResult.masks/contours, ChainThreadPool.submit_bundle (frame.copy()); `ChainResult.frame`/`execute(payload)` теперь `Any` (duck-typed: ndarray-кадр ИЛИ list[dict] items processing-pipeline, C6d)
- `base_manager` — ChainThreadPool (BaseManager, ObservableMixin)
- Стандартная библиотека: `concurrent.futures`, `threading`, `dataclasses`, `math`, `uuid`
- Нет зависимостей от прототипа (`multiprocess_prototype.*`)

## Тесты

Написаны и проходят (67 тестов):

| Файл | Покрытие |
|------|---------|
| `test_chain_runnable.py` | ChainRunnable: sequential execution, on_error policies |
| `test_dag_runnable.py` | DagRunnable: branching, merge, port routing |
| `test_parallel_runnable.py` | ParallelChainRunnable: cross-process ветка, параллельные бандлы, on_error |
| `test_latency_tracker.py` | LatencyTracker: linear-interpolation percentiles, maybe_log |
| `test_thread_pool.py` | ChainThreadPool: submit_bundle, collect_results, timeout, resize |
| `test_topology.py` | topological_sort, detect_parallel_bundles, is_nonlinear_graph |

## История изменений

- **2026-05-07** — точечная полировка:
  - 🐛 Fix: `ParallelChainRunnable` теперь корректно вызывает `execute_remote` для cross-process шагов (раньше пропускалось → AttributeError на `step.operation.execute`).
  - ♻️ Refactor: общая on_error логика вынесена в `core/error_policy.apply_on_error_policy` (DRY: chain.py + dag.py + parallel.py).
  - 📐 API: добавлен `IRemoteExecutable` Protocol в `interfaces.py` (явный контракт cross-process step).
  - 🔡 Types: `RunnableStep.node` / `RunnableStep.operation` теперь типизированы через `IStepNode` / `IExecutionStep` (вместо `Any`).
  - 📊 Metrics: `LatencyTracker.percentiles()` использует linear interpolation (numpy `linear` mode) вместо `int(n * pct)` — точные значения для маленьких N.
  - 🧰 Observability: `WorkerPoolDispatcher` и `LatencyTracker` интегрированы с `BaseManager + ObservableMixin`. Принимают `logger=None`, `stats=None`, `errors=None` (опц.), используют `self._log_*` / `self._record_metric` / `self._record_timing` / `self._track_error`. Обратно-совместимо. Метрики: `worker_pool.dispatched/timeouts/drops/late_responses/errors`, `worker_pool.processing_time` (timing), `chain.latency_ms` (timing) + `.p50/.p95/.p99` (snapshot per `maybe_log()`).
- **2026-05-01** — Phase 2.3: модуль выделен из прототипа в фреймворк (Protocol-based decoupling, ADR-CHN-001).
