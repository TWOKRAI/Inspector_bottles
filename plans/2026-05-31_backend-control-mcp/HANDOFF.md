# HANDOFF — backend-control-mcp (для нового чата)

**Дата:** 2026-05-31 · **Зона:** infra/tooling (+ framework) · **Ветка:** `feat/backend-control-mcp` (создать при старте P1/P0.5)

## Где мы

- **P0 recon ✅ · P0.5 ✅ (`1a1b6b9b`) · P1 ✅ (`df8fa01f`)** — ветка `feat/backend-control-mcp`.
  - **P0.5:** generic request-response в RouterManager (`request`/`reply_to_request`/`_resolve_pending`
    + резолвер в `receive`). Закрыты ДВЕ дыры fire-and-forget: PM-ответ без `targets` + выброшенный
    результат generic command-пути. Ответ едет system-очередью. 16 тестов.
  - **P1:** `introspect.handlers/registers/status` в `BuiltinCommands` (tags=system, как worker.*).
    Воспроизводит диагноз Этапа 2 (нет `register_update` в handlers). 10 тестов. framework 3045 passed.
  - **P2-P3 — ПАУЗА** (решение владельца): сначала оценить headless in-process харнесс
    (`router.request(...)` без сокета/MCP) против полного socket+MCP-стека. Ценность фронт-лоадед.
- **P0 recon** — см. «P0 ИТОГ» в [plan.md](plan.md). 4 из 5 допущений зелёные, 1 жёлтое (request-response, закрыто P0.5).
- **Транспорт пересмотрен (решение владельца):** НЕ driver-процесс-в-графе, а **`SocketChannel` в RouterManager** + тонкий внешний driver. Это by-design расширение (`register_channel`), под которое и делался RouterManager.
- **Продукт-контекст:** live-параметры уже работают без этого тулинга (resize-ретрофит, commit 4327ccf8 на ветке `feat/pipeline-live-control`). Socket-driver = ускорение отладки бэкенда, держать тонким.

## Порядок работ

1. **P0.5 (prerequisite, framework):** починить request-response. Сейчас ответ `_handle_process_command` шлётся без `targets` → теряется ([process_manager_process.py:876](../../multiprocess_framework/modules/process_module/process_manager_process.py#L876)). Нужен `targets=[sender]`/`reply_to` + `correlation_id` + `await_response` на отправителе. Generic. ~130 строк.
2. **P1 (framework):** generic `introspect.handlers/registers/status` builtin-команды (паттерн `worker.*` из [builtin_commands.py](../../multiprocess_framework/modules/process_module/commands/builtin_commands.py)). Геттеры уже есть: `command_manager.get_commands()`, `message_dispatcher.get_all_handlers()`, `registers_manager.model_dump_all()`, `ProcessManager.get_all_processes_status()`. Возвращают dict.
3. **P2 (framework+infra):** `SocketChannel(MessageChannel)` в `router_module/channels/` (сиблинг `queue_channel.py`), хост — ProcessManager (`register_channel` + accept-loop в `WorkerManager`-потоке). Внешний driver-модуль (`message_module` + socket-клиент) говорит теми же `Message`/dict, что GUI. JSON wire, кадры/SHM НЕ гоняем. dev-гейт `BACKEND_CTL=1` + localhost.
4. **P3 (infra):** MCP-обёртка над driver-модулём (5-7 инструментов: send_command, list_processes/handlers, get_registers/status, get_topology, set_register).

## Подводные камни

- **Сериализация:** очереди = pickle in-process; сокет = JSON (Dict at Boundary спасает). Кадры через сокет не гоняем — драйверу не нужны.
- **request-response обязателен** до P1 (иначе introspect слеп).
- **Совпадает с transport-router-hub P3** (`plans/2026-05-31_transport-router-hub/`) — «ещё один IMessageChannel», не плодить второй транспорт.
- **Остановка процессов:** PID-specific, не глобальный taskkill (memory `feedback_no_global_taskkill`).

## Ключевые memory

`project_backend_control_mcp`, `project_transport_router_hub`, `project_pipeline_live_control_stage2`, `project_priority_product_over_engine`, `feedback_constructor_modularity`.
