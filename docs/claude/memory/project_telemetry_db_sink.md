---
name: project_telemetry_db_sink
description: Telemetry DB-sink plan — ВЕСЬ ЗАКРЫТ (Phase 0–3, 1ab30a1c): sink + DatabasePlugin→SQLManager + 23 pytest + headless live-proof. Долг insert_many атомарности → дочерний план sql-insert-many-atomic.
metadata:
  node_type: memory
  type: project
  originSessionId: bb0fcd93-6055-4985-9294-c8457ff65f72
---

План `plans/2026-06-04_telemetry-db-sink.md` (ветка feat/comm-system-target-architecture). Цель: БД-сток истории телеметрии (`Plugins/io/telemetry_sink`, Services/sql) + миграция DatabasePlugin.

**Сделано (2026-06-04):**
- Task 0.1 (10b6b20b): runtime-proof — backend-процесс через `StateProxy.subscribe("processes.**")` реально получает дельты + initial-replay. ОСНОВНОЙ путь подтверждён, FALLBACK (вариант D) не нужен.
- Task 1.1 (9644d2fd): `TelemetrySinkPlugin` (subscribe→семпл loop-worker→SQLManager fork-safe). Топология `backend/topology/telemetry_sink.yaml` (launchable headless). Smoke зелёный.
- Task 1.2+1.3 (6883c6ef/957ba386): полная схема `TelemetrySnapshot` (fps/latency/uptime/status/extra JSON) + per-process строки + system-сводка; команды flush/get_stats/purge_old + retention_days. Ревью Phase 1 APPROVE.
- **Phase 2 — Task 2.1+2.2 (476e760e): миграция `Plugins/io/database` sqlite3→SQLManager.** `DetectionSchema(SchemaBase+SQLMeta)` (auto-DDL), `SQLManager` в `start()` (fork_safe=True, NullPool, check_same_thread=False), `_do_flush`→`repo.insert_many` (fallback one-by-one сохранён), `created_at` в коде (DDLBuilder не переносит SQL-default `unixepoch`). Контракт плагина не изменён. Тесты на in-memory SQLManager, 17 passed. README+STATUS добавлены.

**Паттерн fork-safe SQLManager (общий для sink и database):** SQLManager создаётся ВНУТРИ `start()` (после fork), НЕ в `configure()`; `fork_safe=True`→NullPool; `connect_args={"check_same_thread": False}`. Для тестов `:memory:` — БЕЗ fork_safe (иначе NullPool пересоздаёт БД и теряет данные; нужен StaticPool, который фабрика выбирает для `:memory:` сама). Импорт SQL — только `from Services.sql import SQLManager, SQLManagerConfig`.

**КРИТИЧНО для Phase 3.2:** реализация Task 1.1 вскрыла, что `PluginContext.with_config()` НЕ пробрасывал `state_proxy` → у ВСЕХ плагинов `ctx.state_proxy` был None, и их `_publish_state()` (`merge()`) был **мёртвым кодом**. Фикс `with_config` + фикс `handle_state_merge` (двойной unwrap из-за коллизии ключа `data`) **активировали** публикацию у `capture`/`color_mask`/`pilot_widgets` — теперь они пишут в `processes.*.state` (тот же subtree, что ProcessMonitor). **GUI-приёмка ПРОЙДЕНА (qt-mcp, 2026-06-04):** вкладка «Процессы» в `color_inspect` здорова — FPS live, «Активно: 6», 0 Qt-warnings. Двойная запись `processes.*.state` панель НЕ сломала. См. [[feedback_qt_mcp_smoke_verification]].

**Phase 3.2 для database — ЗАКРЫТО live-proof (578c5243):** живой headless-запуск wired-топологии `camera_service→hsv_mask→contour_finder→robot_control→database` → 318 строк в `detections` через реальный процесс `storage`+SQLManager. При этом вскрыты ДВА pre-existing дефекта (НЕ от миграции): (1) `inspection_full.yaml` устарел — нет секции `wires:`, только `chain_targets` → port-валидация `SystemBlueprint.check()` его отвергает, запустить нельзя; (2) вход `database.result` был `dict shape="(*,)"` — несовместим с ЕДИНСТВЕННЫМ dict-производителем `robot_control.inspection_result` (`dict "1"`) → вход неудовлетворим. Fix: shape→`"1"` (fix-forward, тест `TestPortContract`). Единственный dict-output во всём `Plugins/` — `robot_control.inspection_result`.

**Phase 2 database — ПОЛНОСТЬЮ ЗАКРЫТА (ревью Opus APPROVE + добивка):** коммиты 476e760e (миграция), 578c5243 (port-fix+live-proof), 0da4d582 (атомарность по ревью: `repo.insert_many` = per-row commit, НЕ транзакция → старый batch+fallback давал дубли; теперь `_do_flush` пишет построчно), 1096ea1f (created_at `Optional[float]`→`float` NOT NULL; **inspection_full.yaml ПОЧИНЕН** — добавлены `wires:`+`displays:`, был незапускаем, live-proof 258 строк; `telemetry_sink._sample_loop` обёрнут в try/except — транзиентная ошибка БД не убивает worker). 18 тестов database, ruff/pyright чисто.

**Phase 3 — ЗАКРЫТА (1ab30a1c, 2026-06-05):** Task 3.1 — `Plugins/io/telemetry_sink/tests/`, 23 теста (register/период, schema/DDL, кэш `_on_deltas`, агрегация `_sample_once` state-колонки/extra JSON/system-сводка, команды flush/get_stats/purge_old, fork-safe конфиг `start()`, гонка flush/worker под `_write_lock` — на ФАЙЛОВОЙ БД, т.к. in-memory StaticPool теряет схему под потоками). Task 3.2 — live headless-proof `backend_ctl/telemetry_sink_proof.py` (`python -m backend_ctl.telemetry_sink_proof`): 20 строк в `data/telemetry.db` (camera_0/system/ProcessManager/telemetry_sink × 5 окон ts, span 15.2с), `total_written=20` в логе = число строк, 0 SQL/pool/fork-ошибок. **ВЕСЬ план telemetry-db-sink закрыт (Phase 0–3).**

**Дочерний план `plans/2026-06-05_sql-insert-many-atomic.md` (DRAFT, ветка `fix/sql-insert-many-atomic`):** чинит долг — `GenericRepository.insert_many` сейчас per-row commit (не атомарен). После фикса: `DatabasePlugin._do_flush` откатывается на атомарный batch+fallback, `telemetry_sink._sample_once` получает атомарность снимка бесплатно, docstring `_sample_loop`+race-теста про «per-row, дублей нет» — обновить (Task 2.x того плана). Связано: [[project_telemetry_self_publish]], [[project_telemetry_subscription_bug]], [[feedback_fix_framework_forward]].
