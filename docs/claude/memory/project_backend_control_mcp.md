---
name: project-backend-control-mcp
description: План MCP-driver параллельно GUI — общение с бэкендом ТОЛЬКО через RouterManager
metadata:
  type: project
---

План `plans/2026-05-31_backend-control-mcp/plan.md` (зона infra/tooling, ветку `feat/backend-control-mcp` создать при старте P1). Замысел владельца: MCP-сервер параллельно GUI — отрабатывать бэкенд напрямую через MCP (целиться/слать/читать), не сражаясь с qt-mcp; отлаживать фронт и бэк раздельно, не гадать «где проблема».

**P0 recon ✅ · P0.5 ✅ (`1a1b6b9b`) · P1 ✅ (`df8fa01f`)** — ветка `feat/backend-control-mcp`, framework 3045 passed.

- **P0.5 (request-response, framework):** `RouterManager.request()/reply_to_request()/_resolve_pending` + резолвер в `receive()` по correlation_id (guard на пустой реестр = 0 оверхед). Найдены/закрыты **ДВЕ** дыры fire-and-forget: (1) PM `_handle_process_command` слал ответ без `targets`; (2) generic command-путь — результат `cm.handle_command` в `ProcessLifecycle.register_commands_with_router` **выбрасывался вообще** (теперь `_make_command_handler` → `reply_to_request`, no-op без correlation_id → fire-and-forget паритет). Ответ едет system-очередью (`queue_type="system"`). **Контракт:** `request()` нельзя звать из приёмного потока (дедлок). 16 тестов.
- **P1 (introspect, framework):** `introspect.handlers/registers/status` в `BuiltinCommands` (tags=system, регистрируются как worker.* → тот же IPC-путь). `handlers` = ключи router `message_dispatcher` + команды `CommandManager` (ловит «нет register_update» — диагноз Этапа 2). `registers` = `model_dump_all` оркестратора (пусто+note без register_schema). 10 тестов.
- **🔴→🟢 Reachability-баг (`a6f0221a`, 2026-06-01, найден валидацией):** builtin-команды (`worker.*`/`wire.*`/`introspect.*`) регистрировались в `ProcessModule.run()` ПОСЛЕ единственного `register_commands_with_router()` в `initialize()` → были в `CommandManager`, но **НЕ в router `message_dispatcher`** → входящие IPC-команды молча дропались. **introspect был недостижим по IPC; worker CRUD тоже задет** (GUI шлёт оптимистично, дроп не виден). Фикс: ре-синк команд в router в `run()` после `BuiltinCommands.register()` (register_message_handler идемпотентен). P1-юниттесты маскировали (звали handler через фейк, не через router). **Урок: тестировать команды через router.receive-путь, не напрямую.**
- **P1.5a наблюдаемость (`abf0b65b`):** `introspect.router_stats` (sent_ok/received/errors/middleware_dropped) + `introspect.queues` (backpressure). Дешёвые геттеры (`router.get_stats()`, `self.queues[*].qsize()`).
- **Решение владельца (2026-06-01): socket+MCP — ДА** (агенты делают работу, прямые руки в бэкенде ценны). Driver = «**GUI по сокету**»: шлёт идентичные `CommandSender`-сообщения + `request_id`/`reply_to=ProcessManager`; **общий билдер протокола** в `message_module` (один источник правды GUI+driver). Дизайн: [[plan]] `P2_socket_design.md`. **Порядок: P1.5b (стрим логов через router) → P1.5c (verify-probe) → P2 (socket) → P3 (MCP).** Stream-механика: `LoggerManager._route_via_router` уже шлёт `Message(type=LOG)`, gated `router_routing` → стрим = подписка, добавляющая socket доп. назначением.
- Архитектура подтверждена probe'ом: ProcessManager — **отдельный OS-процесс**, внешний процесс не делает request-response без двери (нет своей очереди в графе) → SocketChannel оправдан.

**ПЕРЕСМОТР ТРАНСПОРТА (решение владельца 2026-05-31):** НЕ driver-процесс-в-графе, а **`SocketChannel(MessageChannel)` в RouterManager** (сиблинг QueueChannel, by-design `register_channel` — router_manager.py:458) + тонкий ВНЕШНИЙ driver-модуль, который подключается к сокету и шлёт те же Message/dict, что GUI по queue. Хост канала — ProcessManager (accept-loop в WorkerManager-потоке), НЕ новый сиблинг-процесс. JSON wire (кадры/SHM не гоняем). Совпадает с transport-router-hub P3 (ещё один IMessageChannel), не плодит второй транспорт.

**Фазы (обновлено):** P0.5 prerequisite request-response (framework, ~130 строк) · P1 generic `introspect.handlers/registers/status` (паттерн worker.*) · P2 **SocketChannel + внешний driver** (вместо driver-в-графе) · P3 MCP-обёртка. Handoff: `plans/2026-05-31_backend-control-mcp/HANDOFF.md`.

Мотивация: диагностика Этапа 2 = ~30 шагов qt-mcp, а `introspect.handlers` показал бы блокер мгновенно. НО продукт (live-параметры) уже работает БЕЗ тулинга (resize-ретрофит 4327ccf8) → driver = ускорение отладки, не критический путь, держать тонким. Dev-гейт `BACKEND_CTL=1` + localhost.

Связано: [[project-transport-router-hub]] (транспорт, на котором ездит driver; P0-P2 на ветке), [[project-pipeline-live-control-stage2]] (фича, которую driver'ом быстрее добить), [[feedback-constructor-modularity]].
