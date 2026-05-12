---
name: Worker cycle timing — monitor and control
description: Each worker should show cycle frequency/duration and allow editing target interval. Smart sleep fills the gap between actual execution and target.
type: project
originSessionId: 2ed0c757-d56b-40b4-b6d8-e47cf654ed2f
---
User wants per-worker cycle timing:

1. **Monitor:** show actual cycle duration (e.g. 130ms) and effective frequency (e.g. 7.7 Hz)
2. **Control:** editable `target_interval_ms` — if cycle takes 130ms and target is 200ms, smart sleep adds 70ms
3. **Applies to ALL workers** including the protected RouterManager polling worker — can be slowed down if needed
4. **Workers are fully configurable entities** — create, edit (including timing), delete (except protected). They get "filled" with actual work in other tabs (Sources, Pipeline)

**Why:** Allows fine-tuning system load, debugging timing issues, and preventing CPU-hogging workers.

**How to apply:** 
- Add `target_interval_ms` to worker config dict in ProcessEditorModel
- ProcessMonitorModel receives `cycle_duration_ms` and `effective_hz` in worker heartbeat data
- ProcessDetailPanel (WorkerInfoForm) shows both monitored timing and editable target interval
- Backend WorkerManager implements smart sleep: `sleep(max(0, target - actual))`
