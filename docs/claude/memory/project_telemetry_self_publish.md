---
name: project_telemetry_self_publish
description: Telemetry self-publish architecture + the cycle_metrics monotonic bug that made FPS=0
metadata:
  node_type: memory
  type: project
  originSessionId: 1ae441db-6354-4606-a3a9-9901693909d5
---

Телеметрия процессов (FPS/latency) переведена на **self-publish** (2026-06-04, ветка feat/comm-system-target-architecture, план plans/telemetry-self-publish-redesign.md).

**Архитектура:** каждый процесс САМ публикует свои метрики в дерево StateStore через `ProcessHeartbeat._publish_metrics_to_tree` → `state_proxy.set(...)` — тот же проверенный путь, что и статус (зелёный индикатор). НЕ через старую центральную heartbeat-агрегацию `ProcessMonitor._publish_process_aggregate` (она оказалась хрупкой/мёртвой для метрик — Task 2 плана = её удалить).
- Агрегат процесса: `processes.{p}.state.fps` = max(effective_hz), `state.latency_ms` = max(cycle_duration_ms) = время самого медленного воркера (узкое горло).
- Per-worker: `processes.{p}.workers.{w}.status/effective_hz/cycle_duration_ms` (коммит 61b02761).

**Корневой баг (почему FPS не работал у агентов раз за разом):** `CycleMetricsRecorder.effective_hz` считался как `1/cycle_duration`, а длительность мерилась `time.monotonic()`. На Windows у monotonic гранулярность ~15 мс → sub-миллисекундная работа consumer-воркеров (DataReceiver/PipelineExecutor) округлялась в 0 → `effective_hz=0.0` хотя cycles росли ~21/с. Камера работала только из-за throttle-sleep ~47 мс. **Фикс (b6ce2bb8):** effective_hz = частота ЗАВЕРШЕНИЯ циклов (интервал между `record()` через `time.perf_counter()`); consumer-раннеры тоже перешли на perf_counter.

**GUI per-worker (7e59e259):** `GuiStateBindings.bind_fanout(pattern, callback, owner)` — переиспользуемый fan-out (callback на каждую matching дельту + replay из кэша) для динамического обнаружения ключей. `SingleProcessPanel` обнаруживает рантайм-воркеров из телеметрии и подмешивает в `WorkerTable` read-only строками — потому что `presenter.get_workers()` возвращает только конфиг-топологию (WorkerSpec) + синтетический message_processor, БЕЗ рантайм-воркеров пайплайна (data_receiver/pipeline_executor/source_producer_*).

Связано: [[project_telemetry_subscription_bug]], [[project_processes_workers_runtime]], [[feedback_qt_mcp_smoke_verification]].
