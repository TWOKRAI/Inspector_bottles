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
- **P2-P3 — ПАУЗА (решение владельца 2026-05-31):** ценность фронт-лоадед в P0.5+P1. Перед socket+MCP оценить дешёвую альтернативу — **headless in-process харнесс** (поднять бэкенд, звать `router.request(...)` напрямую, без сокета/MCP) — даёт ~90% отладочной ценности за ~20% стоимости. Полный socket+MCP оправдан, только если нужен интерактивный драйв бэкенда именно Claude.

**ПЕРЕСМОТР ТРАНСПОРТА (решение владельца 2026-05-31):** НЕ driver-процесс-в-графе, а **`SocketChannel(MessageChannel)` в RouterManager** (сиблинг QueueChannel, by-design `register_channel` — router_manager.py:458) + тонкий ВНЕШНИЙ driver-модуль, который подключается к сокету и шлёт те же Message/dict, что GUI по queue. Хост канала — ProcessManager (accept-loop в WorkerManager-потоке), НЕ новый сиблинг-процесс. JSON wire (кадры/SHM не гоняем). Совпадает с transport-router-hub P3 (ещё один IMessageChannel), не плодит второй транспорт.

**Фазы (обновлено):** P0.5 prerequisite request-response (framework, ~130 строк) · P1 generic `introspect.handlers/registers/status` (паттерн worker.*) · P2 **SocketChannel + внешний driver** (вместо driver-в-графе) · P3 MCP-обёртка. Handoff: `plans/2026-05-31_backend-control-mcp/HANDOFF.md`.

Мотивация: диагностика Этапа 2 = ~30 шагов qt-mcp, а `introspect.handlers` показал бы блокер мгновенно. НО продукт (live-параметры) уже работает БЕЗ тулинга (resize-ретрофит 4327ccf8) → driver = ускорение отладки, не критический путь, держать тонким. Dev-гейт `BACKEND_CTL=1` + localhost.

Связано: [[project-transport-router-hub]] (транспорт, на котором ездит driver; P0-P2 на ветке), [[project-pipeline-live-control-stage2]] (фича, которую driver'ом быстрее добить), [[feedback-constructor-modularity]].
