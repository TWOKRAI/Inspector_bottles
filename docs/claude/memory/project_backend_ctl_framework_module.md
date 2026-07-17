---
name: project_backend_ctl_framework_module
description: bctl framework-module — Phase 0 (hardening) + Phase 2 (agent=GUI-паритет) на текущей раскладке; переезд/SDK отложены до codemod
metadata:
  type: project
---

План `plans/backend-ctl-framework-module.md` — превратить `backend_ctl` в модуль фреймворка + догнать GUI-паритет приёма. **Решение владельца 2026-07-17: продукт-first форк** — фичи Phase 2 строим на ТЕКУЩЕЙ раскладке `backend_ctl/` (не извлекаем в `modules/`/`tooling/`); переезд (Phase 1) + MCP-SDK (Phase 3) + Phase 4 отложены ЦЕЛИКОМ до codemod layer-grouping. Мотивация — [[feedback_priority_product_over_engine]]: ценность агент=GUI-паритет нужна сейчас, движковый детур (coherence 2-3 → codemod) откладывается.

**В main (2026-07-17):**
- **Phase 0 (hardening)** — второй чат, `cfc3e531`: durable-подписки переживают реконнект, гонка close()/request() закрыта, единый endpoint-конфиг, MCP-регистрация telemetry-методов (Task 0.5).
- **Phase 2 на текущей раскладке** (этот чат):
  - **2.1 `observability_tail`/`observability_untail` + `observability_records`** (`075a433b`) — live логи+ошибки+статистика (богаче `log_tail`), durable, классификатор по `kind`.
  - **2.2 `watch_like_gui()` + `unwatch()`** (`ea7009d1`, фикс `daee82ea`) — 4 GUI-wildcard'а (`processes/system/devices/calibration.**`) + obs-хвост на все процессы + авто-переподписка после авто-рестарта.
  - **2.4 `introspect.memory`** (`2b509c22`) — best-effort инвентарь memory/pool/queues/shm_registry, null-секции (не ошибка), Dict-at-Boundary (только статистика). `pool` берётся из router `_frame_middlewares` (LoanLedger живёт там, не в shared_resources); `shm_registry` в дочернем процессе штатно null (launcher-level).
- MCP-инструменты всех трёх зарегистрированы. Ниты/edge-cases отревьюены и закрыты.

**УРОК (thread-safety авто-переподписки) — дополняет известное «`request()` из приёмного потока = дедлок» ([[project-backend-control-mcp]] P0.5) техникой ОБХОДА:** слушатель авто-переподписки живёт в reader-потоке driver'а (колбэк `subscribe()`), а переподписка — это `request()`, который заблокировался бы навсегда (ответ дренирует ТОТ ЖЕ reader-поток). Решение: слушатель только КЛАДЁТ намерение (имя процесса) в `queue.Queue`, отдельный daemon-applier-поток (`_resub_loop`) применяет `observability_tail` на безопасном потоке. Общее правило: **из reader/subscribe-колбэка driver'а нельзя звать `request()` — только offload намерения в очередь + applier-поток.**

**Отложено:** 2.3 telemetry read-model — блокер: reuse-источник generic-`TelemetryViewModel` появится в coherence Task 3.5 ([[project_telemetry_coherence_remediation]]). Live-acceptance (Task 4.1) — pending; live-тест `test_mcp_server_live_against_backend` красный pre-existing на этой Windows-машине (SHM/spawn WinError, не регресс). Phase 1 переезд + Phase 3 SDK + Phase 4 — пост-codemod.

Связано: [[project-backend-control-mcp]] (транспорт/P0-P2, старый план), [[feedback_backend_ctl_for_agents]] (бэкенд тестировать driver'ом), [[feedback_priority_product_over_engine]].
