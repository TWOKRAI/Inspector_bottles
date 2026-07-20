# backend_ctl — STATUS.md

**Готовность:** Production (dev-инструмент) · Phases 0–3 закрыты + отревью · Phase A hardening + C.1 partial split · Phase D (D.1/D.2/D.4/D.5) + Phase E (доверие)

**Обновлено:** 2026-07-20

## Что это

Тонкий внешний driver управления живым бэкендом по TCP («GUI по сокету»): подключается
к `SocketChannel` хоста (ProcessManager), шлёт те же router-сообщения, что GUI, плюс
reply-поля для request-response. Плюс MCP-сервер (официальный SDK) — контрол-плейн для агента.
Граница ровно Claude↔driver; гейт на хосте: `BACKEND_CTL=1` + localhost-bind. Кадры/SHM по сокету НЕ гоняются.

## Текущее состояние

| Компонент | Статус | Комментарий |
|-----------|--------|-------------|
| `driver.py` | ✓ готово | `BackendDriver` — фасад: композиция подсистем + ~30 доменных обёрток + telemetry (1922→1054 в C.1; сейчас 1560 — ре-рост в основном за счёт D.5-регистров, кандидат на вынос `registers.py`) |
| `protocol.py` | ✓ готово | `unwrap` + 6 dataclass-результатов интроспекции (C.1) |
| `subscriptions.py` | ✓ готово | `_SubscriptionRegistry` — durable-намерения, replay при реконнекте (C.1) |
| `events.py` | ✓ готово | `_EventChannelMixin` — событийный канал push-сообщений, курсорные плоскости `events_page` (B.1); legacy-дренаж `events()` удалён (F.1) |
| `transport.py` | ✓ готово | `_TransportMixin` + `_Pending` — сокет/reader/request + concurrency-фиксы Phase A (C.1) |
| `watch.py` | ✓ готово | `WatchController` (композиция) — GUI-профиль + авто-resub, владеет своим состоянием (C.1 headline) |
| `interfaces.py` | ✓ готово | `IBackendClient` / `IEventSource` / `ISubscriptionRegistry` (Protocol, C.2) |
| `endpoint_config.py` | ✓ готово | `resolve_endpoint`: арг > env `BACKEND_CTL_HOST/PORT` > дефолт |
| `mcp_server_sdk.py` | ✓ готово | Сервер на официальном MCP SDK (BCTL-ADR-001), lazy-connect driver |
| `mcp_tools.py` | ✓ готово | ToolSpec-реестр + annotations + safety-классификация (BCTL-ADR-002) + `dispatch_tool` (D.4 session-aware; E.1 аудит-вотка, E.2 send_command-валидация, E.3 byte-cap) |
| `audit.py` | ✓ готово | **E.1** `AuditLog`: кольцо сессии + durable JSONL; write/escalated → журнал, инструмент `session_log` |
| `command_validate.py` | ✓ готово | **E.2** чистая сверка args `send_command` по `params_schema` свода (капабилити-кэш держит сессия) |
| `recorder.py` | ✓ готово | **D.4 flight recorder**: запись (RecordWriter/Recorder) + offline-реплей (load_recording/ReplayPlayer/replay_await_condition) + dump (BCTL-ADR-006) |
| `mcp_errors.py` | ✓ готово | Actionable-ошибки: hint + валидные альтернативы (BCTL-ADR-003) |
| `mcp_driver_session.py` | ✓ готово | Общий lifecycle сервера + readiness + durable-реконнект (BCTL-ADR-004) |
| `harness.py` | ✓ готово | `BackendHarness` — headless-спавн прототипа + env-restore + kill-tree |
| `dump_capabilities.py` | ✓ готово | CLI drift-gate `docs/contracts/CAPABILITIES.md` (`python -m backend_ctl.dump_capabilities`) |
| `probes/` | ✓ готово | Ручные live-пробники (g1/g7/telemetry/smoke) — вынесены из корня (C.2) |
| Тесты (unit) | ✓ зелёные | driver / wrappers / telemetry / mcp / session / interfaces — на fake-транспорте |
| Тесты (live) | ✓ зелёные | 11+ suites на реальном spawn через harness; C.0 reconnect-якорь |

## Phase C (плана backend-ctl-debug-console) — закрыта

- **C.0** live-якорь reconnect (`test_reconnect_live.py`) — сетка сплита, прогон до/после каждого шага.
- **C.1 распил god-file — ЗАВЕРШЁН.** driver.py 1922 → 1054, 6 модулей (protocol/subscriptions/events/transport/watch + фасад), поведение бит-в-бит.
- **C.2 гигиена** — STATUS.md + interfaces.py + probes/.

Дальше по плану: Phase B (P0-эргономика; B.1 перестроит `events.py` на курсорные плоскости).

## Phase E (доверие) — закрыта

- **E.1** аудит-журнал мутаций: `audit.py` + `session_log` (кольцо сессии + durable JSONL, best-effort).
- **E.2** предполётная валидация `send_command` по схеме свода — обучающая ошибка вместо таймаута.
- **E.3** byte-cap тяжёлых ответов (`state_get_subtree`/`system_overview`/`telemetry_history`) + `full=true`.

Тесты — `test_phase_e_trust.py` (26). D.3 (trace-id) ждёт внешний Ф7 G.6; дальше F.1 (live-смоук).

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
