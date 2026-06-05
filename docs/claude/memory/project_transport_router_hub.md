---
name: project-transport-router-hub
description: Решение — модернизировать существующий хаб фреймворка (RouterManager+каналы) в ЕДИНЫЙ механизм общения для прототипа и будущих систем. План plans/2026-05-31_transport-router-hub/.
metadata:
  node_type: memory
  type: project
  originSessionId: 78570f3b-c446-4359-bb07-5c336d210b2c
---

Решение владельца (2026-05-31): транспорт всей системы свести к **одному механизму** — хабу `RouterManager`, который уже спроектирован во фреймворке, но на уровне IPC его обходят. Прототип и будущие приложения должны общаться ТОЛЬКО через него.

**Прогресс (2026-05-31, ветка `refactor/transport-router-hub`):** P0 ✅ + P1 ✅ + **P2 ✅** закрыты. P1 = консолидация (хаб-путь уже построен долгом #1). **P2 иерархическая адресация** (`09cd95a6` P2.1 + `d12726cf` P2.2/P2.3): доставка по `process_of`/`address[0]` в `_deliver_by_targets`, воркер+ в билете под `_address`. **Решение ГИБРИД (владелец):** кадры (data) — статическая топология in-process очередей («трубы», assigned_worker вариант A без изменений); команды воркеру — иерархический адрес `proc.worker` через `register_worker_handler`/`_route_to_worker` («почта»), guard «type==data не уводим». Оси ортогональны → нет двух транспортов. 3010 framework + smoke (дисплей кажет кадры, 0 ERROR). **P3 (каналы по kind) ОТЛОЖЕН** ради продуктового направления [[project-pipeline-recipe-driven-launch]] (владелец: продукт > движок). НЕ в рантайме пока: kind→channel-таблица (`resolve_channel_kind`) — это P3.

**Прогресс P3 (2026-06-05, всё в `main`, запушено):** P3.1 фактически закрыт.
- **P3.1.1** (`4f4dbb28`): два `FrameShmMiddleware` слиты в ЕДИНЫЙ канон в `router_module/middleware/` (весь SHM-транспорт кадров — в router, НЕ в process_module; решение владельца). generic-методы strip_and_write/restore_frame (канон) + middleware-протокол on_send/on_receive; общий `_read_shm_from_actual_name`. process_module/generic импортирует канон из router (process→router, цикла нет).
- **P3.1.2** (`7b841750`): SHM-strip кадров перенесён из producer'ов (SourceProducer/PipelineExecutor) в router send-middleware `FrameShmMiddleware.strip_data_frame_on_send` (регистрируется в GenericProcess через `add_send_middleware`). Claim Check — забота хаба; guard `type=="data"+data.frame`. Verify: framework 3194 + qt-smoke FPS/cycle паритет (47мс, FPS 21.0, 0 ошибок кадров). Откат — один revert (strip_and_write остаётся методом класса).
- **Остаток P3:** RingBufferWriter (мёртв, 0 callers → изоляция P5). **P3.3 EventChannel — отложено** (0 живых потребителей triple-write → строить ради нуля преждевременно, мёртвый путь → P5). **P3.2 StateChannel — DEFERRED** (нет 2-го реактивного потребителя, решение #2 execution-order).
- Investigation-first отчёт: FrameChannel как новый IMessageChannel-класс НЕ нужен — `_deliver_by_targets` уже маршрутизирует type=data→{proc}_data.

**СЛЕДУЮЩЕЕ — P4 (новый чат):** миграция отправителей `send_message`→`router.send`: P4.1 CommandSender→фабрика Message; P4.2 heartbeat/relays/broadcasts; P4.3 `queue_registry.send_to_queue`/SHM → приватные детали каналов + sentrux-правило; **P4.4 убрать двойную диспетчеризацию** (message_dispatcher→lambda→CommandManager.dispatcher); P4.5 слить дубли. HIGH риск (hot data-path) — rollback-план + integration кадров vs baseline. Параллельно **observability Phase 2-4**: секция `observability` в конфиге + ConfigFileWatcher hot-reload + IPC `config.reload` (другой файл-набор CRM, не пересекается с P4). **observability Phase 1 УЖЕ влит** (`d63bae62`: reconfigure(config) на CRM + invalidate_decision_cache LoggerManager; ветка `feat/observability-control-plane` отребейзена на main и влита ff, §11 CRM авто-мерж без конфликта). План `plans/2026-06-03_observability-control-plane/`.

> **Baseline для P4 (новый чат):** origin/main = `4ee87adf` (запушено), framework **3194 passed**, sentrux quality **7037** (depth 0.6154<0.65 — ПРЕ-существующая violation, НЕ регресс; boundary-нарушений 0). qt-smoke эталон: FPS 21.0, camera_0 Циклов/с 21.3, Время цикла ~47мс, кадры+детектор идут. Дисциплина: investigation-first перед фазой, изолированные коммиты для hot-path (откат revert), qt-smoke обязателен ([[feedback_qt_mcp_smoke_verification]]), ruff-format hook → re-stage+re-commit ([[feedback_commit_msg_format]]).

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
