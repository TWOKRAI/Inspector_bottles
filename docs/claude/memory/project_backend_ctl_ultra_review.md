---
name: project-backend-ctl-ultra-review
description: Итоги ultra-ревью backend_ctl 2026-07-20 — оценка 4.5→7.5→8.0; крит-баги ЗАКРЫТЫ hardening'ом того же дня, открытые резидуалы живут в плане
metadata:
  type: project
---

> **ОБНОВЛЕНО 2026-07-20 вечер: крит-баги ниже ЗАКРЫТЫ.** План `plans/backend-ctl-hardening.md` (14 задач / 18 коммитов, слит в main) починил все пять пунктов; оценка 7.5 → **8.0/10** как инструмент отладки (структурно 7.0 без изменений — структурные долги отложены сознательно). Список ниже держим как **историю причин**, не как список работ. **Актуальные открытые резидуалы — в самом плане, раздел «Открытые резидуалы»**, не дублируем сюда: MED полумёртвый сокет (нет SO_KEEPALIVE), MED слепая зона live-introspect, LOW связность `_tool_cursor_lock`, LOW неполный контракт-тест паритета + «мина под переезд» (`harness.py` импортирует прототип). Рекомендованный порядок: (1) `_system_ready_event` во фреймворке, (2) полумёртвый сокет, (3) `registers.py` + разрез harness ДО переезда.

Ultra-ревью всего backend_ctl (2026-07-20, 13 финдеров + 15 верификаторов + sweep): **оценка как инструмента отладки 4.5→7.5/10** (рефакторинг A–F стоил того, но заявленные в плане 8.9 не подтверждены).

**Крит-баги (CONFIRMED — все ЗАКРЫТЫ hardening'ом 2026-07-20, оставлены как история):**
1. `transport.py:146` — разрыв сокета → error-dict вместо raise → reconnect-аппарат D.1 (reset/replay/resume) НИКОГДА не срабатывает; сессия мертва до пересоздания.
2. `mcp_server_sdk.py:105` — fail-open: опечатка в BACKEND_CTL_MCP_MODE молча даёт MODE_FULL.
3. Системный диагноз: **session-слой писался как однопоточный, а SDK гоняет tools/call в параллельных потоках** (anyio.to_thread + tg.start_soon) → гонки: ensure()/reset() (утечка драйвера), AuditLog._seq, _events_tool_cursor, capabilities_cache, gen-TOCTOU в EventHub.
4. Replay ≠ live: await_condition мёртв при position='end' (дефолт), форма state_get расходится (status:'ok' vs success:True), error-секции header отдаются как есть.
5. `harness.py:346` — на таймауте readiness force-kill получает (None,[]) → сироты.

**Причина пропуска багов:** при удалении mcp_server.py (b128c246) потеряны 844 строки тестов error/reconnect-контракта; 85% тестов — fake-transport, флагманские фичи (recorder, await_condition, D.5-регистры, Phase E) не имеют live-доказательств.

**Что хорошо:** ядро распила C.1 чистое (WatchController/миксины/ReplayPlayer — no defect), 18→49 инструментов, циклов импортов нет, тест:код 0.89. Ре-рост driver.py 1054→1541 — на 75% D.5-регистры, добавленные in-place (следующий кандидат на вынос registers.py). REFUTED-примеры: ui_untap (бэкенд-тап — глобальный синглтон), telemetry limit=0 (драйвер защищён).

Полный список: 23 CONFIRMED + PLAUSIBLE в отчёте ReportFindings сессии 2026-07-20. Связано: [[project_backend_ctl_framework_module]].
