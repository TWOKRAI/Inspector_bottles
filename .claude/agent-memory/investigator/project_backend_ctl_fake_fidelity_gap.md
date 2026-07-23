---
name: project-backend-ctl-fake-fidelity-gap
description: backend_ctl unit tests have no fake-vs-real sync mechanism; response shapes hand-fabricated, only 4 wrappers live-verified
metadata:
  type: project
---

Аудит test-honesty backend_ctl (2026-07-23, ветка fix/truth-holes-closure).

**Факт:** у юнит-тестов backend_ctl НЕТ механизма синхронизации фейка с реальными
хендлерами. Два уровня фейка, оба ручные:
- `FakeDriver` (tests/test_mcp_server_sdk.py:31) — `__getattr__`-эхо, отдаёт
  `{"success":True,"method":name}`. Проверяет ТОЛЬКО плумбинг диспетча (имя→метод,
  args, safety-гейт), не форму ответа.
- Ответы хендлеров вручную выписаны в каждом тесте (test_driver, test_wrappers
  `_ROUTER_RESP/_MEMORY_RESP/...`, test_overview `_healthy_responses`).
  `full_router_stats` дублируется в conftest.py:54 и test_wrappers.py:31.

**Единственный sync-мост:** live-тесты с `missing==[]` против headless-бэкенда —
но их всего 4 обёртки (router_stats/queues/worker_status/capabilities,
test_wrappers.py TestWrappersLive). MemoryStats, introspect.telemetry,
supervision_status, introspect.status(pid), plugins — форма НЕ сверена вживую.

**Why:** история проекта — тесты «пинят старую правду»; 85% fake-transport прятали
23 живых бага. Ручной фейк воспроизводит ровно тот класс.

**How to apply:** при правке любого introspect-хендлера в
process_module/builtin_commands.py форма молча разойдётся с фейком, юнит останется
зелёным. Требовать live `missing==[]` плечо для новых обёрток. Здоровый образец —
g7_soak_probe.py:396 (强制 missing→ПРОБА НЕВАЛИДНА) и test_wrappers ON/OFF-пары.
Связано с [[project_backend_ctl_signal_integrity]], [[feedback_single_marker_verdict_lies]].

**Дыры покрытия:** logger_sink_enable/disable — 0 тестов (жили в удалённом
test_mcp_server.py, остался только .pyc). Нет валидации inputSchema инструментов
против arg-доступа хендлера. Session-фикстура headless_backend висит на DEFAULT_PORT
8765 (конфликт с soak — причина запрета pytest).
