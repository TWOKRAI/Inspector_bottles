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

**Fable-ревью Phase 2 (2026-07-17, 34→51/60) + фиксы F1-F7 в main** (`f36f194a`+`6b1c3441`): Fable нашёл ЭМЕРДЖЕНТНЫЕ дефекты на границах, которые unit/одиночный-live не ловят. Главный — **F1 (блокер «watch параллельно с GUI»):** observability-форвардер был ОДИН слот на процесс → `watch_like_gui` угонял хвост у GUI (вкладки Логи/Ошибки/Статистика молча умирали). Фикс: **per-subscriber форвардер** (`_observability_forwarders: dict[subscriber→(fwd,taps)]`, tap-имена `observability_forward::{subscriber}::…`, симметрия с `log_tail::{subscriber}`); `observability.tail.unsubscribe` теперь несёт `subscriber` (смена wire-контракта). F2 реконнект-durable (re-watch манифест в mcp_server + unwatch чистит durable даже inactive), F3 гонка unwatch↔in-flight resub (само-исцеление), F4 listener до подписок, F5 severity-фильтр tail_level (был пустышкой), F6 pool из публичного `router.get_stats()`, F7 контракт-тест. **Урок ревью-находка (мой пост-мерж hardening `6b1c3441`):** фан-аут форвардеров ввёл ИТЕРАЦИЮ dict в heartbeat hot-path — in-place мутация из command-потока → `RuntimeError: dict changed size during iteration`; фикс — **atomic-rebind** (`{**old,k:v}` / comprehension), читатель видит стабильный снимок. Общее: при фан-ауте по подписчикам в hot-path — не мутируй dict in-place, ребайндь атомарно.

**Live-verify (2026-07-17):** ✅ `introspect_memory` (memory.written/queues/pool — типизированные поля полны; «all-null» был багом моего verify-скрипта, читавшего не тот уровень конверта), ✅ `watch_like_gui` state (83+ дельты, все wildcard'ы), ✅ авто-resub (0 errors), ✅ `log_tail` доставка (мост работает), ✅ регрессия после F1-F7 (не сломано). **НЕ доказан live:** F1 dual-consumer (GUI+driver одновременно получают record'ы) — плоскость `observability.record` тиха в здоровом synth (после ADR-136 stats→state, логи=WARNING+ ~0); механизм доказан unit-тестом «два независимых подписчика», но полный live-пруф требует GUI-вкладки под qt-mcp + индуцированного WARNING/ошибки. Резидуал.

**Отложено:** 2.3 telemetry read-model — блокер: reuse-источник generic-`TelemetryViewModel` появится в coherence Task 3.5 ([[project_telemetry_coherence_remediation]]). **Split god-file `driver.py` (~1567 строк, растёт)** — можно СЕЙЧАС на текущей раскладке (развязан от переезда), с директивой владельца «сделать красиво» (вычистить процессные комментарии: хеши/ревью-пометки/Task-номера → чистый production-код). Phase 1 переезд в `tooling/` + Phase 3 SDK + Phase 4 — пост-codemod.

Связано: [[project-backend-control-mcp]] (транспорт/P0-P2, старый план), [[feedback_backend_ctl_for_agents]] (бэкенд тестировать driver'ом), [[feedback_priority_product_over_engine]].
