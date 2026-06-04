---
name: project_telemetry_db_sink
description: Telemetry DB-sink plan — Task 0.1+1.1 DONE; framework fix activated plugin state-publishing (Phase 3.2 must verify GUI telemetry)
metadata:
  node_type: memory
  type: project
  originSessionId: bb0fcd93-6055-4985-9294-c8457ff65f72
---

План `plans/2026-06-04_telemetry-db-sink.md` (ветка feat/comm-system-target-architecture). Цель: БД-сток истории телеметрии (`Plugins/io/telemetry_sink`, Services/sql) + миграция DatabasePlugin.

**Сделано (2026-06-04):**
- Task 0.1 (10b6b20b): runtime-proof — backend-процесс через `StateProxy.subscribe("processes.**")` реально получает дельты + initial-replay. ОСНОВНОЙ путь подтверждён, FALLBACK (вариант D) не нужен.
- Task 1.1 (9644d2fd): `TelemetrySinkPlugin` (subscribe→семпл loop-worker→SQLManager fork-safe). Топология `backend/topology/telemetry_sink.yaml` (launchable headless). Smoke зелёный.

**КРИТИЧНО для Phase 3.2 / следующих задач:** реализация Task 1.1 вскрыла, что `PluginContext.with_config()` НЕ пробрасывал `state_proxy` → у ВСЕХ плагинов `ctx.state_proxy` был None, и их `_publish_state()` (`merge()`) был **мёртвым кодом**. Фикс `with_config` + фикс `handle_state_merge` (двойной unwrap из-за коллизии ключа `data`) **активировали** публикацию у `capture`/`color_mask`/`pilot_widgets` — теперь они пишут в `processes.*.state` (тот же subtree, что ProcessMonitor). **GUI-приёмка ПРОЙДЕНА (qt-mcp, 2026-06-04):** вкладка «Процессы» в `color_inspect` здорова — FPS 15.0 live, latency 0.0ms, «Активно: 6», карточки процессов на месте, 0 Qt-warnings. Двойная запись `processes.*.state` (ProcessMonitor + capture/color_mask) панель НЕ сломала. См. [[feedback_qt_mcp_smoke_verification]].

**Осталось:** Task 1.2 (полная схema + system-сводка), 1.3 (команды+retention-заглушка), Phase 2 (миграция DatabasePlugin sqlite3→SQLManager), Phase 3 (pytest+GUI/headless-приёмка). Импорт SQL — только `from Services.sql import ...`. Связано: [[project_telemetry_self_publish]], [[project_telemetry_subscription_bug]].
