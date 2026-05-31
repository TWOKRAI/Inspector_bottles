---
name: project-transport-router-hub
description: Решение — модернизировать существующий хаб фреймворка (RouterManager+каналы) в ЕДИНЫЙ механизм общения для прототипа и будущих систем. План plans/2026-05-31_transport-router-hub/.
metadata:
  type: project
---

Решение владельца (2026-05-31): транспорт всей системы свести к **одному механизму** — хабу `RouterManager`, который уже спроектирован во фреймворке, но на уровне IPC его обходят. Прототип и будущие приложения должны общаться ТОЛЬКО через него.

**Прогресс (2026-05-31, ветка `refactor/transport-router-hub`):** P0 ✅ (контракт + ADR-COMM-001/004) + P1 ✅ (хаб на отправке) закрыты. P1 оказался КОНСОЛИДАЦИЕЙ, не стройкой: хаб-путь `router.send→_deliver_by_targets→queue_registry` уже построен долгом #1, новый класс канала НЕ понадобился. `send_to_process`→`router.send` (обход B1 убран), channel-guard fix (recon #3), qtype DRY (recon #5). +483 прод-строки, 0 циклов (sentrux acyclicity 10000). **Smoke end-to-end:** вебкамера→split→processors→stitcher→GUI, дисплей FPS 14, 0 ERROR — кадры идут через `router.send`. Handoff для P2: `plans/2026-05-31_transport-router-hub/HANDOFF_P2.md`. **Долг:** P0.2-контракт (`resolve_route`/addressing) ещё НЕ в рантайме — это суть P2 (доставка по `process_of`/address[0]).

**Ключевая находка (чтение README модулей):** хаб = уже задокументированная архитектура. Переиспользуем, НЕ изобретаем:
- `ChannelRoutingManager` (CRM) — «телефонная станция»: `ChannelRegistry` + `register_route(key→channel)` + `route()`. База для `RouterManager`/`LoggerManager`/`ErrorManager`.
- `RouterManager.send → _resolve_channels → IMessageChannel.send`; `receive → message_dispatcher → handler`.
- `Message.type` (`MessageType`) = «kind» (НЕ вводить новое поле). `Message`+`MessageAdapter` = билет.
- `IMessageChannel`/`QueueChannel` = каналы; кастомные by-design. `MessageType.DATA`+`use_shared_memory`+`memory_key` = Claim Check для кадров.
- Логи/ошибки — тоже каналы той же станции (`ILogChannel(IChannel)`).

**Что реально новое:** подключить очереди `queue_registry` как address-aware `QueueChannel` (1 канал на qtype, читает адрес из `targets`); иерархическая адресация в `targets` (dotted `proc.worker`, см. [[project-hierarchical-addressing]]); `Frame/Event/StateChannel`; миграция вызовов с `send_message`/прямого `queue_registry` на `router.send`; `correlation_id` (анти fire-and-forget, он в Roadmap).

**Решения по процессу:**
- **Сиквенс S1:** хаб (P0–P2) делаем ДО `assigned_worker` Фазы 2 — чтобы воркер-исполнение строилось сразу на правильной иерархической адресации (без костылей). assigned_worker = уровень «воркер» в адресе хаба.
- **P5 удаление — только после обсуждения** каждого модуля; дефолт — изоляция, не `rm` (многое — намеренный конструктор-задел).
- Аудит §5.1 (`COMMUNICATION_MAP.md`) ОТМЕНЁН: там было «депрекейтить каналы», владелец выбрал «достроить хаб».

**Артефакты:** план [`plans/2026-05-31_transport-router-hub/plan.md`](../../../plans/2026-05-31_transport-router-hub/plan.md); карта [`multiprocess_framework/docs/COMMUNICATION_MAP.md`](../../../multiprocess_framework/docs/COMMUNICATION_MAP.md) + `COMMUNICATION_MAP_raw.json` (call-sites обходов в `router_audit.bypasses`). Ветка реализации: `refactor/transport-router-hub`.

Связано: [[project-hierarchical-addressing]], [[processes-workers-runtime-feature]], [[project_command_engine_audit]], [[feedback_logger_error_stats_managers]], [[feedback_dict_at_boundary_gui]].
