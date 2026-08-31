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
| `driver.py` | ✓ готово | `BackendDriver` — фасад: композиция подсистем + ~30 доменных обёрток + telemetry (1922→1054 в C.1; сейчас 1270 — регистровый аппарат в `registers.py`, `debug_session`/`debug_stop` удалены как дубль watch в Task 4.1) |
| `protocol.py` | ✓ готово | `unwrap` + 6 dataclass-результатов интроспекции (C.1) |
| `subscriptions.py` | ✓ готово | `_SubscriptionRegistry` — durable-намерения, replay при реконнекте (C.1) |
| `events.py` | ✓ готово | `_EventChannelMixin` — событийный канал push-сообщений, курсорные плоскости `events_page` (B.1); legacy-дренаж `events()` удалён (F.1) |
| `transport.py` | ✓ готово | `_TransportMixin` + `_Pending` — сокет/reader/request + concurrency-фиксы Phase A (C.1) |
| `watch.py` | ✓ готово | `WatchController` (композиция) — GUI-профиль + авто-resub, владеет своим состоянием (C.1 headline) |
| `registers.py` | ✓ готово | `RegisterOps` (композиция) — verify-probe / snapshot-restore / commit-confirmed запись; владеет `_pending_commits` + журналом откатов, вынесен из `driver.py` бит-в-бит |
| `interfaces.py` | ✓ готово | `IBackendClient` / `IEventSource` / `ISubscriptionRegistry` (Protocol, C.2) |
| `endpoint_config.py` | ✓ готово | `resolve_endpoint`: арг > env `BACKEND_CTL_HOST/PORT` > дефолт |
| `mcp_server_sdk.py` | ✓ готово | Сервер на официальном MCP SDK (BCTL-ADR-001), lazy-connect driver |
| `mcp_tools.py` | ✓ готово | ToolSpec-реестр (47 инструментов) + annotations + safety-классификация (BCTL-ADR-002); 1581→1193 после выноса `dispatch.py` |
| `dispatch.py` | ✓ готово | `dispatch_tool` (D.4 session-aware; E.1 аудит-вотка, E.2 send_command-валидация, E.3 byte-cap) + session-owned record-хендлеры + replay-роутинг; `build_registry()` под `@lru_cache` — вынесен из `mcp_tools.py` (Task 2.2) |
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
о завершении C.1-распила. См. план [`plans/backend-ctl-debug-console.md`](../plans/_archive/2026-07-19_backend-ctl-debug-console.md)
(поглощён [`plans/backend-ctl-proof-discipline.md`](../plans/backend-ctl-proof-discipline.md) 2026-07-21).

## Задача 3.3 (2026-08-11) — harness не кормит корневой `logs/` (ADR-138)

`headless_backend` поднимает настоящую систему из девяти процессов, а каталог логов брала из
`system.yaml` (`logs/prototype_2` относительно cwd). Замер: `test_capabilities.py` дописывал
**163 909 байт** за прогон, полный корневой гейт — **428 736**; после правки оба — **0**.

`BackendHarness(log_dir=...)` пробрасывает каталог в `build_headless_launcher` →
`system.log_dir`. Дорога КОНФИГОМ, а не env, намеренно: `launch._ENV_LOG_DIR_OVERRIDE`
снимается один раз при импорте, и первый harness заморозил бы снимок на своём каталоге —
золотой снапшот сборки в том же pytest-процессе начал бы зависеть от порядка тестов.

**Дефолт harness НЕ менялся:** 28 из 34 живых зондов каталог себе не задают, и подмена дефолта
увела бы их логи туда, где оператор их не ищет. Каталог задаёт тестовая фикстура. Страж —
`tests/test_harness_log_dir.py` (5 тестов, внесён в `testpaths`: правка снимается одной строкой,
и без стража в гейте возврат дефекта был бы полностью бесшумным).

## Task 2.4 telemetry-stage6 (2026-08-14) — вытеснение колец обрело голос

Кольца `EventHub` (`deque(maxlen=1000)`) теряли события молча: `evicted` считался только
в `stats()`, то есть был виден, **когда спросишь**. Живой замер под `watch_like_gui`:
**587 и 599 вытеснений** плоскости `telemetry` за 30 с — и ни одной строки в логе.

Голос — WARNING в `backend_ctl.events`, **один раз на эпизод** (порог затишья
`EVICTION_VOICE_QUIET_SEC = 30.0`), эпизоды независимы по кольцам, покрыт и arrival.
Живая приёмка: 599 вытеснений → ровно **1** голос; контроль — тихое кольцо даёт 0.
Зонд: [`probes/probe_2_4_eviction_voice_live.py`](probes/probe_2_4_eviction_voice_live.py).

Замер снял два моих неверных допущения. Первое: arrival-кольцо **не** переполняется
быстрее плоскостей — `telemetry` получает k item'ов на одно сообщение и обгоняет его
(`all` не вытеснился ни разу). Второе: первая версия текста писала `'telemetry'=1`, когда
потеряно 587 — счётчик, значащий не то, что написано; текст переписан, а адрес полной
величины указывает на `events_stats()`, а НЕ на `system_overview → events_evicted`
(последний строится из `planes` и кольцо `all` не показывает — долг K-6).

Стражи: `tests/test_eviction_voice.py` (6, независимый тестер, писались до реализации)
+ `tests/test_eviction_voice_hazards.py` (7, автор механизма). Корпус доказан: при снятом
голосе краснеют **12 из 13**, тринадцатый — отрицательный контроль, доказан отдельной
инъекцией «детектор срабатывает на событие раньше».

## Task Т.2 observation-port (2026-08-23) — два молчащих класса потерь + слепота waiter'ов к удалению предка

**overview.py.** `queue_data_evicted` и `queue_never_drop_loss_total` `RouterStats`
уже разбирал (`protocol.py:203`/`:216`), но `system_overview` их не называл нигде —
ни в карточке процесса, ни в `anomalies`. Асимметрия: транспортные потери ХВОСТА
наблюдаемости (`obs_transport`) уже были видны, а потеря на очереди ПОЛУЧАТЕЛЯ —
нет, хотя `queue_never_drop_loss_total` строже (сорвана гарантия «не дропаем»,
control-плоскость), чем `queue_data_evicted` (ожидаемое вытеснение data-очереди,
тот же счётчик, что `data_receiver.py:120` называет по имени на живом инциденте
2026-08-12: 1646 вытесненных кадров у `seg`). Два новых kind — `queue_data_loss` и
`control_plane_loss` — не пересекаются с `router_dropped`/`router_errors`
(middleware/обработка сообщений, не очередь получателя). Отсутствующий счётчик
(старая сборка router'а) по-прежнему уходит в существующий `counter_missing`,
дублирования нет.

**conditions.py.** `_setup_state_path`/`_setup_metric_threshold` сравнивали путь
дельты с наблюдаемым БУКВАЛЬНО — удаление ПРЕДКА (`processes.gui` целиком, пока
ждём `processes.gui.state.plugins.capture.capture_fps`) проходило незамеченным:
`last_seen` оставался `None`, таймаут отдавал пустой hint вместо диагноза. Общий
хелпер `_is_ancestor_path` (сегментная проверка через `candidate + "."`, не
`str.startswith` — иначе `processes.gu` ложно считался бы предком
`processes.gui.x`) используется в обоих настройщиках: удаление предка ложится в
`last_seen` как `{deleted: True, ancestor: ...}`, но НЕ засчитывается совпадением
условия. Стоимость на дельту, не совпавшую с наблюдаемым путём буквально: одна
строковая конкатенация + `startswith`, и только для дельт с
`new_value == MISSING_MARKER` — до сравнения предка доходят не все дельты подряд.

Стражи: `tests/test_overview_loss_counters.py` (7) + `tests/test_conditions_ancestor_deletion.py`
(6) — независимый тестер, писались до реализации, 13/13 зелёных. + `tests/test_t2_author_hazards.py`
(7, автор механизма) — грани хелпера предка (корневой предок, путь не предок сам
себе, наблюдаемый путь сам корень), различение `MISSING_MARKER` от легитимного
`None` на пути предка, и форма/порядок аномалий на нескольких процессах разом.
Полный `backend_ctl/tests`: 618 passed / 6 failed / 44 skipped → 624 passed / 0
failed / 44 skipped (регрессий нет, прирост ровно на 6 бывших красных).
