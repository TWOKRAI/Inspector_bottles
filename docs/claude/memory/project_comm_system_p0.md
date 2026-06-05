---
name: project_comm_system_p0
description: "comm-system-target-architecture — P0 quick-wins §11 безопасная зона ЗАКРЫТА (2026-06-05). Остаток §11 — осторожная зона (P1, нужен rollback+qt-smoke). Handoff для нового чата."
metadata:
  node_type: memory
  type: project
  originSessionId: 81a6a5e9-4cae-45c4-ae94-56012cb4f3bd
---

Большой план `plans/comm-system-target-architecture.md` (532 строки, ветка `feat/comm-system-target-architecture`) — целевая архитектура коммуникаций фреймворка: «не переписывание, а сборка в ОДНУ систему», убрать дубли + достроить периметр. Этапы P0→P1→P1.5→P2→P3 (§12). Трекинг — в самом плане (раздел «Трекинг (S8)», ~строка 458).

**P0 quick-wins §11 — БЕЗОПАСНАЯ ЗОНА ЗАКРЫТА (2026-06-05), 3 батча:**
- `b2b9519e`: §11.4 (IMessageFactory удалён), §11.7+8 (мёртвый relay register_schemas/register_changed→PM + битый MessageAdapter.create_message), §11.14 (DispatcherConfig удалён), §11.19 (асимметрия expects_full_message → ADR-DSP-004; флаг НЕ убирать).
- `082ac031`: §11.9 (дубль ChainMatchStrategy.scenarios+CRUD+dispatch_scenario удалён; берегли ScenarioManager-канон core/scenarios.py + ScenarioBuilder; редундантный TestChainMatchStrategy убран) + `.gitignore data/`.
- `48743bd7`: §11.13 (GuiStateBindings silent pass→_logger.debug), §11.16 (LoggerManager no-op _dispatcher.init/shutdown убраны; инстанс в базе ChannelRoutingManager сохранён для ErrorManager), §11.5 (RolesPanel: editable требует И прав И рабочего bus).
- Ранее уже было DONE: §11.1 (shadow bridge.py), §11.10 (console help), §11.17 (CRM-конфиги ADR-CRM-005), §11.18 (AsyncSenderBuffer.flush — документирован inline).

**Осталось PENDING — ОСТОРОЖНАЯ ЗОНА (кандидаты P1, нужен rollback-план + инвариант Pipeline зелёный, `/run-proto`+qt-smoke, baseline перед стартом):**
- §11.2 `routers` (поле Message/Log/Command schemas — cross-process pickle, осторожно), §11.3 `subtype` (heartbeat/broadcast — hot-path, есть тест test_process_monitor.py:120), §11.6 `get_field` (registers_adapter.py:109 зовёт несуществующий метод → sync_domain_to_state падает в except; чинить через getattr(rm.get_register(reg), field)), §11.11 update_handler API (хардкод default_strategy), §11.12 broadcast queue_type (process_communication.py:238 system vs _select_queue_type — hot-path), §11.15 `_state_multiplexer` (app.py closure → нужен add_state_listener).
- §11.20-22 (active-bugs, P0 но с риском): §20 `_route_to_worker` помечает consumed при ошибке handler → ТЕРЯЮТСЯ process.stop/worker.pause (критично); §21 GuiStateProxy._dispatch_via_qt нарушает main-thread контракт (риск Qt-краша); §22 _init_state_proxy в finally — silent skip.
- Телеметрия P0 (Option D) — отдельный план `telemetry-delivery-simplification.md`.

**Рекомендованный следующий шаг (моё предложение, не утверждено владельцем):** вариант 2 — §11.20–22 (макс эффект на надёжность, точечные правки), ЛИБО заход в осторожную зону §11.2/3/6/12. Перед стартом — baseline (sentrux session_start или прогон framework-тестов) + помнить про `/run-proto`+qt-smoke перед merge.

**Дисциплина (на каждый батч в этой ветке):** ruff-format hook переформатирует → re-stage+re-commit (см. [[feedback_commit_msg_format]]); правка module-level DECISIONS.md → `python -m scripts.sync` (правило проекта 8); trailers Why:/Layer:/Refs: обязательны; `data/` теперь в .gitignore (runtime БД). Investigator-аудит остатка §11 делал agent (read-only) — образец для повторного аудита.

Связано: [[project_telemetry_db_sink]] (боковая ветка внутри P0, закрыта), [[feedback_fix_framework_forward]], [[feedback_qt_mcp_smoke_verification]].
