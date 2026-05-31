# HANDOFF — backend-control-mcp (для нового чата)

**Дата:** 2026-06-01 · **Зона:** infra/tooling (+ framework) · **Ветка:** `feat/backend-control-mcp` (уже существует, 7 коммитов)

## Где мы (готово, закоммичено, framework 3051 passed)

- **P0.5 ✅ (`1a1b6b9b`)** — request-response в RouterManager (`request`/`reply_to_request`/
  `_resolve_pending` + резолвер в `receive` по correlation_id). Закрыты ДВЕ дыры fire-and-forget:
  PM-ответ без `targets` + выброшенный результат generic command-пути. Ответ едет system-очередью.
  **Контракт: `request()` нельзя звать из приёмного потока (дедлок).** 16 тестов.
- **P1 ✅ (`df8fa01f`)** — `introspect.handlers/registers/status` в `BuiltinCommands` (tags=system).
- **🔴→🟢 Reachability-fix ✅ (`a6f0221a`)** — **критично:** валидация вскрыла, что builtin-команды
  (`worker.*`/`wire.*`/`introspect.*`) регистрировались в `ProcessModule.run()` ПОСЛЕ единственного
  `register_commands_with_router()` в `initialize()` → были в CommandManager, но **НЕ в router
  `message_dispatcher`** → IPC-команды молча дропались. Фикс: ре-синк в `run()` после builtins.
  **Урок: тестировать команды через router.receive-путь, не вызовом handler напрямую.**
- **P1.5a ✅ (`abf0b65b`)** — `introspect.router_stats` (sent_ok/received/errors) + `introspect.queues`
  (backpressure). Дешёвые геттеры.
- **Решение владельца (2026-06-01): socket+MCP — ДА** (агенты делают работу). Driver = «GUI по сокету».

## Порядок остатка работ

1. **P1.5b ⏳ NEXT (framework, чувствительно):** стрим логов/ошибок/событий подписчику ЧЕРЕЗ router.
   Механика разведана: `LoggerManager._route_via_router` ([logger_manager.py:383](../../multiprocess_framework/modules/logger_module/core/logger_manager.py#L383))
   уже шлёт `Message(type=LOG, targets=["logger"])`, gated флагом `router_routing`. Стрим = команда
   `subscribe(process, kinds=[log,error,event])`, добавляющая socket/подписчика **доп. назначением**.
   ⚠️ горячий log-путь — следить за перфомансом, не допускать самоподписки/спама. **Сделать дизайн-док
   (как `P2_socket_design.md`) на ревью ПЕРЕД кодом.**
2. **P1.5c:** verify-probe (write→readback→diff) — driver-side композит (после P2).
3. **P2 (framework+infra):** по [`P2_socket_design.md`](P2_socket_design.md) (УТВЕРЖДЁН). Driver = «GUI по
   сокету»: шлёт идентичные `CommandSender`-сообщения + `request_id`/`reply_to=ProcessManager`;
   **общий билдер протокола** в `message_module` (один источник правды GUI+driver). SocketChannel —
   обычный `IMessageChannel`, всё через router. dev-гейт `BACKEND_CTL=1` + localhost:8765.
4. **P3 (infra):** MCP-обёртка над driver (stdio Claude↔driver + TCP driver↔backend).

## Подводные камни

- **`request()` ≠ приёмный поток** (дедлок) — P0.5 контракт.
- **Команды → тестировать через router**, не напрямую (урок reachability-бага).
- **ProcessManager — отдельный OS-процесс**; внешний процесс не делает request-response без двери
  (нет своей очереди в графе) → SocketChannel оправдан (подтверждено probe'ом).
- **Сериализация:** сокет = JSON (Dict at Boundary). Кадры/SHM через сокет НЕ гоняем.
- **Совпадает с transport-router-hub P3** — «ещё один IMessageChannel», не плодить второй транспорт.
- **Остановка:** PID-specific, не глобальный taskkill (memory `feedback_no_global_taskkill`).

## Старт нового чата

> Читай `plans/2026-05-31_backend-control-mcp/HANDOFF.md`, `plan.md` (секция P1.x), `P2_socket_design.md`.
> Ветка `feat/backend-control-mcp`. Делаем P1.5b: дизайн-док стрима логов через router → ревью → код.

## Ключевые memory

`project_backend_control_mcp` (обновлена), `project_transport_router_hub`,
`project_pipeline_live_control_stage2`, `project_priority_product_over_engine`,
`feedback_constructor_modularity`.
