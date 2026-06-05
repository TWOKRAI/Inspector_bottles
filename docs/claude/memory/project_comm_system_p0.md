---
name: project_comm_system_p0
description: "comm-system-target-architecture — P0 §11 ЗАКРЫТ ПОЛНОСТЬЮ (вкл. осторожную зону, 2026-06-05). Следующее — P1 (единый _dispatch + чистка конверта). Телеметрия = отдельный план Option D."
metadata:
  node_type: memory
  type: project
  originSessionId: 81a6a5e9-4cae-45c4-ae94-56012cb4f3bd
---

Большой план `plans/comm-system-target-architecture.md` (ветка `feat/comm-system-target-architecture`) — целевая архитектура коммуникаций фреймворка: «не переписывание, а сборка в ОДНУ систему». Этапы P0→P1→P1.5→P2→P3 (§12). Трекинг — раздел «Трекинг (S8)» в плане.

**P0 §11 ПОЛНОСТЬЮ ЗАКРЫТ (2026-06-05).** Все пп.1-22 done. Безопасная зона (§11.1/4/5/6/7/8/9/10/13/14/16/17/18/19/20/21/22) — ранее, 4 батча (`b2b9519e`/`082ac031`/`48743bd7`/`80c1566e`). **Осторожная зона (§11.2/3/11/12/15) — закрыта в этой сессии**, 3 изолированных коммита (rollback-дисциплина):
- `a2fccdb5` (framework safe): §11.2 (мёртвое поле `routers` удалено отовсюду; ADR-MSG-004 отменён; MESSAGE_TYPE_EXCLUDE_FIELDS пуст generic), §11.3 (`subtype` убран из heartbeat + 2 status-broadcast'ов; тест→assert not in), §11.11 (param `strategy` в update_handler_*; _resolve_strategy + guard→False). +3 теста.
- `a1902a9f` (framework HOT-PATH, изолирован для `git revert`): §11.12 — `_select_queue_type`: type="system"→"system" (раньше падал в else→"data"). Heartbeat (type=system, command=heartbeat) теперь в system-очередь, которую опрашивает SystemThreads (channel_types=['system']) и где зарегистрирован `ProcessMonitor._on_heartbeat_received`. `broadcast` перестал хардкодить "system", зовёт хелпер (паритет). event/response/request СОЗНАТЕЛЬНО на data-правиле (EVENT→data воркерам; req/resp резолвятся в receive() до dispatch). RISK medium.
- `45d3873a` (prototype): §11.15 — `_state_multiplexer` closure → `DataReceiverBridge.add_state_listener` (multi-subscriber); topology_bridge явный 2-й подписчик, bindings держит primary set_state_callback. +2 теста.

**VERIFY-DONE (обязательно для hot-path, см. [[feedback_qt_mcp_smoke_verification]]):** baseline framework 3175 passed → после правок 3175 passed (паритет, +новые тесты). `/run-proto` + QT_MCP_PROBE=1: кадры идут, детектор рисует контуры, телеметрия БЕЗ регрессии (верхняя панель FPS 21.0; вкладка «Процессы»: Здоровье системы Активно/FPS цепочки 21.0/health-агрегаты заполнены; camera_0 ● running, Циклов/с 21.3). 0 tracebacks/ошибок state/heartbeat — только ожидаемый отказ Modbus 5020 (нет ПЛК). **Heartbeat→system-очередь подтверждён живым** (телеметрия течёт, значит handler срабатывает). prototype-сюит: 15 фейлов — ВСЕ пре-существующие (проверено стэшем на чистом HEAD: те же 15), к P0 отношения нет.

**Открытый долг (НЕ часть P0, отдельно):** 15 пре-существующих prototype-фейлов = 2 корня: (1) отсутствует файл `multiprocess_prototype/recipes/demo_webcam_split_merge.yaml` (~13 тестов demo-рецепта + entities_roundtrip), (2) устаревшие тесты против отрефакторенных внутренностей (`ProcessManagerProcessApp` нет `_lifecycle`; `test_lifecycle_start` ждёт target=camera_0, получает ProcessManager — вероятно lifecycle-команды корректно идут в PM). Воссоздавать demo-recipe файл НЕ стал (возможно намеренно удалён) — на решение владельца.

**Следующий шаг:** P1 — свести `send_to_process`/`_deliver_by_targets`/`broadcast` к одному `_dispatch`; расширить `_select_queue_type` (event/response→system) ПЕРЕД касанием хардкодов qtype; подключить `routing_table` в `_resolve_channels`; конверт (`request_id` единое имя, удалить vestigial `channel` у продюсеров — комплексно). Высокий риск (hot data-path) — нужен rollback-план + integration кадров vs baseline.

**Дисциплина (на каждый батч):** ruff-format hook переформатирует staged → re-stage+re-commit (см. [[feedback_commit_msg_format]]); правка module DECISIONS.md → `python -m scripts.sync` + `python scripts/validate.py` (правило 8); trailers Why:/Layer:/Refs: обязательны; hot-path → изолированный коммит + qt-mcp smoke перед закрытием.

Связано: [[project_telemetry_db_sink]], [[feedback_fix_framework_forward]], [[feedback_qt_mcp_smoke_verification]], [[feedback_commit_msg_format]].
