# backend_ctl — STATUS.md

**Готовность:** Production (dev-инструмент) · Phases 0–3 закрыты + отревью · Phase A hardening + C.1 partial split

**Обновлено:** 2026-07-18

## Что это

Тонкий внешний driver управления живым бэкендом по TCP («GUI по сокету»): подключается
к `SocketChannel` хоста (ProcessManager), шлёт те же router-сообщения, что GUI, плюс
reply-поля для request-response. Плюс MCP-сервер (официальный SDK) — контрол-плейн для агента.
Граница ровно Claude↔driver; гейт на хосте: `BACKEND_CTL=1` + localhost-bind. Кадры/SHM по сокету НЕ гоняются.

## Текущее состояние

| Компонент | Статус | Комментарий |
|-----------|--------|-------------|
| `driver.py` | ✓ готово | `BackendDriver` — TCP-клиент + request-id matching + ~30 доменных обёрток + watch |
| `protocol.py` | ✓ готово | `unwrap` + 6 dataclass-результатов интроспекции (C.1, вынесено из god-file) |
| `subscriptions.py` | ✓ готово | `_SubscriptionRegistry` — durable-намерения, replay при реконнекте (C.1) |
| `interfaces.py` | ✓ готово | `IBackendClient` / `IEventSource` / `ISubscriptionRegistry` (Protocol, C.2) |
| `endpoint_config.py` | ✓ готово | `resolve_endpoint`: арг > env `BACKEND_CTL_HOST/PORT` > дефолт |
| `mcp_server_sdk.py` | ✓ готово | Сервер на официальном MCP SDK (BCTL-ADR-001), lazy-connect driver |
| `mcp_tools.py` | ✓ готово | ToolSpec-реестр + annotations + safety-классификация (BCTL-ADR-002) |
| `mcp_errors.py` | ✓ готово | Actionable-ошибки: hint + валидные альтернативы (BCTL-ADR-003) |
| `mcp_driver_session.py` | ✓ готово | Общий lifecycle обоих серверов + readiness + durable-реконнект (BCTL-ADR-004) |
| `mcp_server.py` | ⚠ legacy | Рукописный сервер — удаляется после SDK-смоука (Phase F, BCTL-ADR-001) |
| `harness.py` | ✓ готово | `BackendHarness` — headless-спавн прототипа + env-restore + kill-tree |
| `dump_capabilities.py` | ✓ готово | CLI drift-gate `docs/contracts/CAPABILITIES.md` (`python -m backend_ctl.dump_capabilities`) |
| `probes/` | ✓ готово | Ручные live-пробники (g1/g7/telemetry/smoke) — вынесены из корня (C.2) |
| Тесты (unit) | ✓ зелёные | driver / wrappers / telemetry / mcp / session / interfaces — на fake-транспорте |
| Тесты (live) | ✓ зелёные | 11+ suites на реальном spawn через harness; C.0 reconnect-якорь |

## Незакрытое (Phase C / плана backend-ctl-debug-console)

- **C.1 распил god-file — ЧАСТИЧНО.** Вынесены `protocol.py` + `subscriptions.py` (driver.py 1922 → ~1694).
  Отложено (сцеплено с concurrency-ядром Phase A, заслуживает отдельного захода + ревью): transport
  (`SocketConnection`), events (`EventHub` — перестраивает B.1), watch (`WatchController`).
- **C.2 гигиена — этот заход:** STATUS.md + interfaces.py + probes/.

## ADR

- BCTL-ADR-001: MCP-сервер на официальном SDK за реестром ToolSpec (Phase 3).
- BCTL-ADR-002: класс безопасности инструмента — единый источник annotations и режимов.
- BCTL-ADR-003: контракт ошибок dict + «ошибки, которые учат».
- BCTL-ADR-004: общий `DriverSession` — один lifecycle для обоих серверов.

Полный текст — [`DECISIONS.md`](DECISIONS.md).

## Зависимости

- `multiprocess_framework.modules.message_module` — `build_command_message` / `build_system_command_message`.
- `multiprocess_framework.modules.telemetry_readmodel_module` — `TelemetryReadModel` (общее Qt-free ядро с GUI).
- `mcp` (официальный SDK) — сервер (опционально, lazy-import).

## Следующий шаг

Phase B (P0-эргономика: cursor list-watch B.1, await_condition, system_overview) — после решения
о завершении C.1-распила. См. план [`plans/backend-ctl-debug-console.md`](../plans/backend-ctl-debug-console.md).
