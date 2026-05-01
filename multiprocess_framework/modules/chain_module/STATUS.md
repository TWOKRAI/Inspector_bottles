# chain_module — STATUS

**Статус:** ✅ Готов (Phase 2.3, 2026-05-01)

## Реализовано

| Компонент | Файл | Строк |
|-----------|------|-------|
| Публичные контракты | `interfaces.py` | ~50 |
| ChainContext | `core/context.py` | ~30 |
| ChainResult, RunnableStep | `core/result.py` | ~60 |
| ChainRunnable | `core/chain.py` | ~100 |
| DagRunnable | `core/dag.py` | ~150 |
| ParallelChainRunnable | `core/parallel.py` | ~130 |
| topological_sort, is_nonlinear_graph | `graph/topology.py` | ~80 |
| detect_parallel_bundles | `graph/bundles.py` | ~80 |
| ChainThreadPool | `thread_pool/pool.py` | ~90 |
| WorkerTaskRequest/Response | `worker_pool/protocol.py` | ~150 |
| WorkerPoolDispatcher | `worker_pool/dispatcher.py` | ~160 |
| LatencyTracker | `metrics/latency.py` | ~55 |
| **Итого** | | **~1,135** |

## Зависимости

- `numpy` — ChainResult.frame, ChainThreadPool.submit_bundle
- `base_manager` — ChainThreadPool (BaseManager, ObservableMixin)
- Стандартная библиотека: `concurrent.futures`, `threading`, `dataclasses`, `uuid`
- Нет зависимостей от прототипа (`multiprocess_prototype.*`)

## Тесты

Написаны и проходят (~60+):

| Файл | Покрытие |
|------|---------|
| `test_chain_runnable.py` | ChainRunnable: sequential execution, on_error policies |
| `test_dag_runnable.py` | DagRunnable: branching, merge, port routing |
| `test_latency_tracker.py` | LatencyTracker: percentiles, maybe_log |
| `test_thread_pool.py` | ChainThreadPool: submit_bundle, collect_results, timeout, resize |
| `test_topology.py` | topological_sort, detect_parallel_bundles, is_nonlinear_graph |
