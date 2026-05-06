# Task 5.3 — Компонентная архитектура GenericProcess

**Status:** IN PROGRESS
**Branch:** `feat/phase5-task5.3-generic-process`
**Level:** Senior+ (Opus)
**Assignee:** teamlead

## Цель

Декомпозиция GenericProcess на компоненты: DataReceiver, PipelineExecutor, SourceProducer + FrameShmMiddleware адаптация. Реализация backpressure (Q6) и error policy (Q7).

## Архитектурное решение

**chain_module НЕ используется напрямую** — он работает с `frame: ndarray → ChainResult`, а наш контракт `process(items: list[dict]) -> list[dict]`. Вместо адаптации на ChainRunnable/DagRunnable (которые не знают про items) — пишем свой легковесный PipelineExecutor (~100 строк), который напрямую вызывает `plugin.process(items)` по цепочке.

**Обоснование:** chain_module предназначен для image processing pipeline (отдельные шаги работают с ndarray). Наш pipeline работает с абстрактными items — совершенно другая семантика. Адаптер был бы сложнее чем простой for-loop. В будущем если нужен DAG — добавим, но для Phase 5 хватит линейного chain.

## Файлы

| Действие | Путь |
|----------|------|
| СОЗДАТЬ | `process_module/generic/data_receiver.py` (~100 строк) |
| СОЗДАТЬ | `process_module/generic/pipeline_executor.py` (~130 строк) |
| СОЗДАТЬ | `process_module/generic/source_producer.py` (~70 строк) |
| СОЗДАТЬ | `process_module/generic/frame_shm_middleware.py` (~80 строк) |
| ИЗМЕНИТЬ | `process_module/generic/generic_process.py` (добавить pipeline bootstrap) |
| ИЗМЕНИТЬ | `process_module/generic/generic_process_config.py` (chain_targets, queue_size, etc.) |
| ИЗМЕНИТЬ | `process_module/generic/__init__.py` (экспорты) |
| СОЗДАТЬ | `process_module/tests/test_data_receiver.py` |
| СОЗДАТЬ | `process_module/tests/test_pipeline_executor.py` |
| СОЗДАТЬ | `process_module/tests/test_source_producer.py` |

## Компоненты

### DataReceiver
- `run_loop(stop_event, pause_event)` — LOOP worker
- receive IPC → FrameShmMiddleware.restore_frame() → item → InspectorManager.on_item()
- Периодически check_timeouts()

### PipelineExecutor
- `run_loop(stop_event, pause_event)` — LOOP worker
- chain_queue.get() → sequential plugin.process(items) → FrameShmMiddleware.strip_frame() → IPC send
- Error policy (Q7): try/except per plugin, circuit breaker
- Routing (Q1): item["target"] override, else chain_targets

### SourceProducer
- `run_loop(stop_event, pause_event)` — LOOP worker
- plugin.produce() → FrameShmMiddleware.strip_frame() → IPC send в chain_targets
- Smart sleep для target FPS

### FrameShmMiddleware (адаптация)
- `restore_frame(msg: dict) -> dict` — SHM ref → ndarray в item["frame"]
- `strip_and_write(item: dict) -> dict` — ndarray → SHM write, убрать frame, добавить shm_ref

## Конфигурация (GenericProcessConfig расширение)

```python
chain_targets: list[str] = []
queue_size: int = 64
lag_alert_threshold_sec: float = 2.0
error_max_consecutive_fails: int = 5
error_auto_reset_sec: float = 60.0
error_critical_plugins: list[str] = []
source_target_fps: float = 25.0
```

## Acceptance Criteria

- [ ] DataReceiver: SHM → item → InspectorManager
- [ ] PipelineExecutor: chain of plugin.process() + error policy + routing
- [ ] SourceProducer: produce() loop + SHM write + IPC send
- [ ] Backpressure: block + alert (Q6)
- [ ] Error policy: pass-through + circuit breaker (Q7)
- [ ] Routing: item["target"] override + chain_targets default (Q1)
- [ ] GenericProcess: thin composition, workers via WorkerManager
- [ ] Каждый компонент ≤ 200 строк
- [ ] ≥ 5 тестов на компонент
