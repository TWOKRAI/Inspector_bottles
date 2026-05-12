---
name: Phase 5 Data Pipeline refactoring
description: GenericProcess refactor — 3 workers + InspectorManager + plugin.process() contract
type: project
originSessionId: 7bde3598-7b2e-4498-8c8b-09d76cc85d95
---
Phase 5: Data Pipeline Architecture — рефакторинг GenericProcess.

**Why:** Плагины сейчас дублируют IPC/SHM boilerplate (register_message_handler, _pending_frame_info, mm.read_images). Нарушает изоляцию. Также system_threads message_processor читает только system queue — DATA-сообщения никто не обрабатывает в GenericProcess.

**How to apply:** План в `multiprocess_prototype_2/plans/phase5_data_pipeline.md`. 8 задач в 3 фазах:
- 5.1-5.3: InspectorManager + process()/produce() + Data Worker/Chain Worker
- 5.4-5.7: Миграция всех 12 плагинов на process(items) -> items
- 5.8: Topology + e2e
Ключевое: один RouterManager, три воркера (System/Data/Chain). Плагины — чистые функции.
