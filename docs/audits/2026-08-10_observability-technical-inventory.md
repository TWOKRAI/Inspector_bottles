# Техническая инвентаризация подсистемы наблюдаемости — 2026-08-10

> Снято read-only агентом-инвентаризатором 2026-08-10 на HEAD `42d1eb41` (ветка `feat/observability-review-remediation`), 101 инструментальный проход по коду.
> Заказчик — [стратегическое ревью 2026-08-10](../reviews/2026-08-10_observability-strategy-review.md); карта «что работает/что страдает» — [real-state-map](../reviews/2026-08-10_observability-real-state-map.md).
> Здесь — **факты без оценок**: что существует и как устроено. Якоря `file:line` действительны на указанный HEAD.

---

## 1. База: `channel_routing_module` — LoggerManager/ErrorManager/StatsManager

**Механизм.** `ChannelRoutingManager` (`multiprocess_framework/modules/channel_routing_module/core/channel_routing_manager.py:85`) — общая база всех трёх плоскостей плюс `RouterManager`: реестр каналов (`ChannelRegistry`), опциональный `IBufferStrategy`, `normalize_config` (Dict-at-Boundary), учёт потерь/доставки, tap-механика, sink-control (`set_sink_enabled`/`read_sink_tail`/`routes_using_sink`), `reconfigure` по схеме validate-then-swap с откатом (`_rollback_to`, ADR-CRM-010). Иерархия: `LoggerCore → {LoggerManager, ErrorManager}` (братья), `StatsManager` и `RouterManager` — прямые наследники CRM.

**Каналы и буферизация.**
- `observability/bounded_channel.py:31` `BoundedChannel` — thread-safe кольцо на `deque`, политики `drop_oldest` (по умолчанию, через `maxlen`) / `drop_newest`, счётчики `dropped`/`written`, pull-модель `drain()`.
- `buffers/direct_buffer.py` (без буферизации), `buffers/async_sender_buffer.py` (для роутера). **`BatchBuffer` снят целиком** (ADR-LOG-008, Ф7.4) — запись синхронна на всех уровнях.
- `AggregationWindow` (см. §3) — единственный оставшийся буфер у плоскостей наблюдаемости.

**Drop-политики / классы потерь.** Единый список `LOSS_COUNTER_KEYS` — `channel_routing_manager.py:46`: `unresolved_channel_records`, `channel_write_errors`, `channel_refused_records`, `records_without_channels`, `tap_reentrant_suppressed`. Рядом `DELIVERY_COUNTER_KEYS = ("channel_written_records",)` (`:61`) и `OBSERVED_AT_KEY` (`:77`) — момент снятия снимка; **темп наружу не считается**, частное берёт потребитель.

**Уровни.** `levels.py` — общее хозяйство трёх плоскостей: `SEVERITY_NUMBERS` (OTel SeverityNumber: DEBUG=5, INFO=9, WARNING=13, ERROR=17, CRITICAL=21, `:61`), `LEVEL_ALIASES` (WARN/FATAL), `UNSPECIFIED=0`, `UNKNOWN_SEVERITY=-1`, `normalize_level_name` (`:96`, только на границе), `record_severity` / `threshold_severity` (противоположные дефолты: запись → DEBUG, порог → fail-open), `is_error_level` (`:178`).

**Процессоры (цепочка, Ф4.1).** Тип `Processor = Callable[(scope, level, record_dict) -> Optional[dict]]` (`logger_module/core/log_types.py:117`). Добавление — `LoggerCore.add_processor`/`remove_processor` (`logger_core.py:1646`), исполнение — `_run_processors` (`:1683`): `None` = поглощено (`records_dropped_by_processor`), исключение = запись всё равно доставляется (`processor_failures`). Два штатных процессора: `SecretRedactor` (ADR-LOG-006) и `RateSampler`.
- `contextualize(**fields)` — `logger_core.py:113`, contextmanager поверх `ContextVar log_context` (`:110`); самый низкий приоритет слоя контекста; слои сливаются в `_build_context` (`:1758`).
- **Редакция секретов** — `logger_module/core/redaction.py`: класс `SecretRedactor` (`:242`), 18 имён в `SECRET_FIELD_NAMES`, точное сравнение по ключам `extra` + регулярка `ключ=значение` / `"ключ": "значение"` по тексту сообщения + `_URL_CREDENTIALS_RE` (пароль в `scheme://user:pass@host`) + `AUTH_SCHEMES` (Bearer/Basic/…). Дешёвый предфильтр `SECRET_NAME_ROOTS` (0.57 мкс против 3.9 мкс полной регулярки). Конфигурации **нет намеренно**, fail-closed при отказе. Глубина спуска `MAX_DEPTH=6`, в списки не спускается.

**Форвардеры/tap'ы.**
- `observability/record_forward_channel.py:49` `RecordForwardChannel` — адресный router-push `command="observability.record"`, `queue_type="observability"` (best_effort/drop_oldest, глубина 256; счётчик `observability_evicted`). Два метода: `write` (одна запись из tap) и `push_batch` (пачка из drain).
- `observability/store_tap.py:32` `StoreTapChannel` — LogRecord-dict → `ObservabilityStore`.
- `observability/drain_adapter.py:73` `ObservabilityDrainAdapter` — duck-typed переводчик dict-записей hub'а в вызовы реальных менеджеров (`apply_log`/`apply_error`/`apply_stat`/`apply_drained`).
- `observability/observability_hub.py:66` `ObservabilityHub` — фасад «модуль = 3 сигнала», три `BoundedChannel` (log/error/stats), pickle-safe dict-записи, `drain_all()`, реализует duck-протоколы `LoggerLike/StatsLike/ErrorLike` (`observability/protocols.py`).
- `observability/record_display.py` — **единый нормализатор** live↔history: `hub_record_to_display` (`:115`), `log_record_to_display` (`:185`), `kind_for_severity` (`:159`), `severity_number_for` (`:49`), `stamp_observed` (`:72`, ставит **только принимающая** сторона).

---

## 2. Логгер: писатель, sinks, формат, per-подписчик tail

**Механизм.** `LoggerCore` (`multiprocess_framework/modules/logger_module/core/logger_core.py:269`, 2122 строки) — **единственный писатель**; `LoggerManager` = LoggerCore + process-singleton (`core/logger_manager.py`). Точка эмиссии одна — `LoggerCore.log()` (`:1444`): гейт (кэш решений `_route_cache`, потолок `_DECISION_CACHE_CEILING=4096`) → материализация отложенного сообщения (`Callable`/`%`-формат) → сборка `LogRecord` с пломбой `seq` → `to_dict()` **один раз на запись** → процессоры → tap'ы → каналы. Гейт — по **имени источника** (longest-prefix, `NameHierarchy`, `core/name_hierarchy.py`), у скоупа осталась одна ось `channels` (ADR-LOG-010).

**Sinks** — реестр `_SINK_FACTORIES` (`channels/log_channel.py:1450`), расширяемый `register_sink_factory` / `get_registered_sink_types`:

| type | класс | детали |
|---|---|---|
| `file` | `FileChannel` (`:962`) | `_SafeRotatingFileHandler` (`:271`), **общий хэндлер на abspath** (реестр `_shared_handlers`, refcount), дефолт 10 МиБ × 5 бэкапов |
| `console` | `ConsoleChannel` (`:1043`) | лесенка перегрузки ADR-LOG-009: `write_deadline_sec=0.25`, `degrade_after=3`, `slow_write_sec=0.05` |
| `http` | `HttpChannel` (`:1116`) | POST JSON, таймаут 5 с, требует `requests` |
| `frame_trace` | `FrameTraceChannel` (`:1135`) | снимок одного кадра по `extra.seq_id`, перезапись файла |
| `memory` | `MemoryChannel` (`:1315`) | кольцо `_MemoryRing` (`:1202`), `DEFAULT_CAPACITY=500`, **процессный реестр `_memory_rings`** — переживает пересоздание канала |
| `null` | `NullChannel` (`:1415`) | это доставка (`written += 1`), не потеря |

**DB-sink.** Отдельного «DB-sink» у логгера нет; персистентность даёт **tap** `StoreTapChannel` → SQLite `ObservabilityStore`.

**Формат записи.** `LogRecord` — dataclass, 7 полей (`core/log_types.py:11`): `timestamp, level, scope, message, module, extra, seq`. В файлы пишется **текстом** через `SealFormatter` (`log_channel.py:946`) — префикс `#<seq> ` ставится ПОСЛЕ форматирования и не отменяется `config.format`; дефолтный формат `%(asctime)s [%(levelname)s] %(name)s: %(message)s`. **JSON — только в двух местах**: `ErrorFloor` (`core/error_floor.py`, JSON Lines со всеми полями, включая многострочный traceback) и `FileStatsChannel` (`statistics_module/channels/file_stats_channel.py`, `format="json"`). Структурные поля внутри `extra`: `trace_id` (32 hex, W3C) + Resource-набор `proc_name/fw_version/incarnation/recipe/pid` (`process_module/core/process_module.py:~505`). Таблица соответствий OTel зафиксирована в докстринге `LogRecord`.

**Уровни/скоупы.** `LogLevel` (DEBUG…CRITICAL) и `LogScope` (`SYSTEM/BUSINESS/PERFORMANCE/DEBUG`) — `core/log_config.py`; маршруты скоупов: SYSTEM→console+system_file, BUSINESS→system_file+messages_file, PERFORMANCE→performance_file, DEBUG→system_file.

**Per-подписчик tail.** `add_tap(channel, min_level="ERROR", name=...)` (`channel_routing_manager.py:791`), раздача — `_emit_to_taps` (`:1039`) с **поточной защитой от реентрантности** (`_tap_depth`, счётчик `tap_reentrant_suppressed`, D1). Tap'ы **переживают `reconfigure()`** (не лежат в реестре каналов). Имена keyed по подписчику:
- `log_tail::{subscriber}` — `process_module/commands/builtin_commands.py:2629`, sink = `RouterPushChannel` (`logger_module/channels/router_push_channel.py`), `command="log.record"`;
- `observability_forward::{subscriber}::{batch|error|logger_error}` — `forward_tap_names()` в `process_module/managers/observability_wiring.py:83`;
- `observability_store::error` / `observability_store::logger_error` (`:73-74`).

**Прочее логгера:** `error_floor` (пол ошибок, JSONL, саморотация 32 МиБ × 1 бэкап, один дескриптор на процесс), `frame_trace()` (`:2030`, идёт мимо цепочки, но редакция зовётся явно), retention (`enforce_log_retention` `:623`, фоновый свип `retention_sweep_interval_sec=3600`, `sweep_log_dir_tree` `:735`, `find_foreign_log_roots` `:820` — только называет), вид над писателем `get_std_logger` (`adapters/std_facade.py`, связывание по `OBSERVABILITY_EPOCH`).

---

## 3. StatsManager: метрики, агрегация, темп

**Механизм.** `StatsManager` (`multiprocess_framework/modules/statistics_module/core/stats_manager.py:86`) — наследник CRM, буфер = `AggregationWindow`. Два уровня хранения: live-метрики `self._metrics` (для `get_metric`/`get_all_metrics`) и окно агрегации. Единственная точка эмиссии `_emit_record` (`:437`): сырая запись → tap'ы **сразу**, затем **одна** запись в буфер под сентинелом `__stats__` (защита от N-кратного счёта при N каналах). `_do_flush` (`:386`) транслирует снапшот во все каналы общим писателем базы.

**Типы метрик** (`core/metric_record.py:12`): `counter`, `gauge`, `timing`, `histogram`. Агрегация (`MetricRecord.aggregate()` `:67`):
- counter → сумма (`count`);
- gauge → последнее значение;
- timing → `count/min/max/avg/**p95**` (p95 = `sorted[int(n*0.95)-1]`);
- histogram → **то же самое**: хранит полный список значений и отдаёт `count/min/max/avg/p95`. **Бакетов/HDR/квантильных скетчей нет; кроме p95 других перцентилей нет.**

**Период публикации.** `resolve_tempo(cfg)` (`:67`) → `(запрошенный, пол, действующий = max(пол, запрошенный))` из `aggregation_interval` и `flush_interval` (`configs/stats_config.py`). Окно пересобирается при `reconfigure` (`_swap_aggregation_window` `:178`), readback темпа — из **живого окна** (`observability_readback` `:226`). Фоновый поток `aggregation-window-timer` (`aggregation_window.py:181`).

**Учёт объёма.** `AggregationWindow.stats` (`:211`): `flush_interval, total_enqueued, total_flushes, total_flushed, flush_failed, errors, pending_metrics, channels, running`. Инвариант «положили = сброшено + в очереди» сторожит `tests/test_stats_no_double_count.py`.

**Каналы статистики.** `LogStatsChannel` (`STATS_LOG_CHANNEL="log_stats"`) — снапшот через `logger_manager.performance(...)`, то есть физически в `performance.log`; `FileStatsChannel` (`STATS_FALLBACK_CHANNEL="file_stats"`, JSON). Отсюда порядок останова: **stats гасится раньше логгера**.

**Известный факт (не закрыт):** у плагина **stats-разъёма нет** — `IProcessServices` не объявляет stats-методов, 0 использований на ~30 плагинов; `kind=stats` до стора не доезжает (`docs/observability/CONNECTORS.md` §3 — единственная открытая асимметрия). Бизнес-числа плагин отдаёт телеметрией, а не StatsManager.

---

## 4. ErrorManager: маршруты, схлопывание, связь с логами

**Механизм.** `ErrorManager` (`multiprocess_framework/modules/error_module/core/error_manager.py:178`) — **брат** LoggerManager через `LoggerCore`. Вся разница между путями эмиссии — переопределённый `_route()` (`:400`) + `_is_gate_open()` (`:383`): WARNING/ERROR/CRITICAL идут по severity-карте `_level_to_channel` (O(1)) мимо гейта скоупа; DEBUG/INFO — родительским scope-резолвом. Карта строится `_setup_level_routes()` (`:266`) из **данных** `severity_routes` (`configs/error_manager_config.py:29`, `DEFAULT_SEVERITY_ROUTES`) — лестница предпочтения: CRITICAL→`critical_file`→`errors_file`; ERROR→`errors_file`→`critical_file`; WARNING→`warnings_file`→`errors_file`→`critical_file`. Пересобирается на `_on_channels_changed` (`:363`).

**Дедупликации/схлопывания повторов у самого ErrorManager НЕТ.** Схлопывание существует в трёх соседних местах:
- **`HealthState.report_error`** (`process_module/health/state.py:227`) — дроссель по ключу `f"{type(exc).__name__}|{context}"`, окно `throttle` (`DEFAULT_THROTTLE`); счётчик ошибок растёт **всегда** (для breaker), а лог + маршрут в плоскость ошибок идут не чаще раза в окно;
- **`RateSampler`** (`logger_module/core/sampling.py:119`) — общий дроссель повторов по ключу `уровень+текст` (`first_n`/`every_mth`/`burst_reset_sec`), **ERROR/CRITICAL не сэмплируются никогда** (граница прибита в коде);
- **аудит наблюдаемости** схлопывает подряд идущие одинаковые записи (`_same_condition` + `repeats`/`last_ts`, `configs/observability_audit.py:115`).

**Связь с логами.** Общий предок → общие каналы, tap'ы, процессоры, floor, счётчики. `log_exception()` (`:437`) склеивает traceback в текст; `track_error()` (`:461`) — вход из `ObservableMixin`. Store-tap и forward-tap висят **на обоих** менеджерах; дублей нет по построению — hub-буфера для лога больше не существует. `_write_error_record` (`logger_core.py:1721`): floor пишет **только** если обычный маршрут записал ноль каналов.

---

## 5. `telemetry_readmodel_module` (ADR-136): чтение GUI без блокирующего IPC

**Механизм.** `TelemetryReadModel` (`multiprocess_framework/modules/telemetry_readmodel_module/telemetry_read_model.py:57`) — Qt-free ядро: плоский словарь `path → value` + кольцевые буферы истории `deque(maxlen=ceil(window_sec*sample_hz))` ≈ 600 точек / 10 мин. Питается **уже разобранными дельтами** через `ingest(path, value, deleted=)`; транспорта не знает, ссылок на router/state-proxy не держит → структурно не может создать подписку. `prime()`, `get()`, `snapshot(prefix)` (граница — точка-разделитель), `history(path, since)`, `export_history()`/`import_history()` (для offline-реплея flight recorder'а с записанными ts).

`DEFAULT_TRACKED_SUFFIXES` (`:48`): `.state.fps`, `.state.latency_ms`, `.state.uptime`, `.effective_hz`, `.cycle_duration_ms`.

**Инварианты ADR-136** (`multiprocess_framework/DECISIONS.md:2287`): (1) GUI main thread никогда не делает блокирующий `router.request` при открытии вкладки; (2) открытие вкладки не создаёт серверных подписок. Механизмы: coverage-check вместо строкового дедупа (`state_proxy.py:408`, glob `pattern_covers`, только подтверждённые паттерны), async `subscribe(sync=False)` (`:256`), replay по префиксу паттерна (`state_store_manager.py:396`), `TelemetryViewModel` (коалесинг сигнала таймером), `TelemetryHistorySource` (pull из `telemetry.db` вне main thread), дебаунс каскада воркеров + ленивые панели. Enforcement — `test_tab_open_invariant.py`.

**Публикация.** Self-publish в дерево состояния по такту heartbeat одним `proxy.merge` вместо 3W+2 `proxy.set` (`process_module/heartbeat/telemetry.py`, `build_worker_telemetry`), publisher-gate `TelemetryGate` per-метрика (вкл/выкл + интервал, `configs/telemetry_publish_config.py`, каталог `gated_metrics()` из `observability_declarations.declare_metric`). `status`/errors — always-on, мимо гейта.

**Важно:** **seqlock и SHM-колец в этом пути нет.** Read-model работает поверх обычного потока `state.changed`-дельт (pickle-dict через router). Seqlock/SHM живут в кадровом транспорте (`shared_resources_module/memory/**`: `format/buffer.py`, `reader/shm_frame_reader.py`, `validation/access.py`, тесты `test_seqlock.py`, `test_seqlock_multiprocess.py`) и к телеметрии отношения не имеют.

---

## 6. Слои конфигурации наблюдаемости L0→L3 (Ф5)

**Механизм.** `multiprocess_framework/modules/process_module/configs/observability_layers.py` (1324 строки). `LAYER_ORDER = (framework, app, recipe, session)` (`:77`); L0 — код (`ObservabilityConfig`, `configs/observability_config.py`), подставляется не здесь, а в `expand_observability` (единственная точка раскладки, ADR-CRM-006). Класс `ObservabilityLayers` (`:320`) — реестр слоёв + provenance (считается **по сырым секциям, до expand**) + бухгалтерия сроков L3. Ключи транспорта: `OVERRIDE_CONFIG_KEY="observability_override"` (L2), `APP_CONFIG_KEY="observability_app"` (L1), `RECIPE_PATH_CONFIG_KEY`.

**Reload = пересборка из источников, а не дельта.** `apply_observability_layers` (`managers/observability_reload.py:595`) — **единственное** место раскладки; зовут и файловый watcher, и IPC-команда. Порядок: `base = managers_from_log_dir(машинный каталог)` → `merge(base, expand(layers.resolve()))` → профиль уровня → точечные scopes-переопределения. `log_directory` — из машинного контекста, переопределяется только явным ключом слоя. Валидация значения — **на записи в слой** (`validate_layer_section` `:1122`, `canonical_level_or_raise`), применяется в четырёх точках (`replace_layer`, `session_set`, хендлер `config.reload`, persist).

**TTL L3.** `managers/observability_ttl.py` + `session_ttl_sec`: дефолт **300 с**, потолок `MAX_SESSION_TTL_SEC=86400.0`, `0` = сроков нет. Исполняет такт heartbeat (`sweep_session_ttl`), точность — не позже `ttl + heartbeat_interval`; процесс без heartbeat отвечает `ttl_enforced: false`. Сделать вечным — только `observability.persist` (L3 → L2, спутник рецепта).

**Subscription broker.** `multiprocess_framework/modules/process_manager_module/process/observability_broker.py:49` `ObservabilitySubscriptionBroker` — реестр намерений «хочу всё» у оркестратора + разворачивание в `observability.tail.subscribe` на процессах; сам записей **не видит** (брокер, не транзит). Методы: `subscribe_all` (`:89`), `unsubscribe_all` (`:128`), `forget_subscriber`, `forget_session`, `replay(reason=instance.started|command)` (`:208`), `snapshot`. Обе отправки fire-and-forget (`broadcast`/`send_to`) — дедлок структурно невозможен.

**Audit-журнал.** `configs/observability_audit.py`: `ObservabilityAudit` (`:131`), кольцо `AUDIT_HISTORY=100` (вытесненное считает `dropped`), 8 закрытых действий (`set/touch/reset/clear/expire/persist/layer/rebuild`), `origin` обязателен **сигнатурой** (`TypeError` при пропуске), значение усекается `_VALUE_CAP=1024`. Своего файла нет — каждая запись кладёт одну строку в журнал процесса (`make_audit_log`) и, опционально, документ в `DocumentStore` (`_emit_document` `:263`). Схлопывание подряд идущих одинаковых записей (`repeats`/`last_ts`, `seq` не растёт).

**Вердикт применения.** `observability_verified` (`managers/observability_reload.py:210`) — трёхзначный `confirmed`/`failed`/`unverifiable`; отдельно `DeliveryWindow` (`backend_ctl/protocol.py:444`): `delivering`/`losing`/`silent_source`, `written_delta`, `self_cost` (~5.1 записи на опрос, замер live 2026-07-30), `written_net`, `cost_exceeds_window`, `counters_reset`+`reset_planes`. Публикуемые счётчики — `PLANE_COUNTER_KEYS` (`:399`, ~35 ключей).

**Что на лету НЕ действует** (`docs/observability/CONTROL_PANEL.md` §6): `config.reload {"persist": true}` (адресный отказ), `observability.documents` и `observability.history` (сшиваются один раз на `initialize()`, `process_module.py:411` и `:427`), опечатка в имени ключа (ловится вердиктом `unknown_keys`), снятые ключи батчинга (`REMOVED_BATCHING_KEYS` → `emergency_log`).

---

## 7. `backend_ctl`: observability-поверхность

**Механизм.** `backend_ctl/driver.py` (127 КБ) — клиентский драйвер поверх сокета ProcessManager; MCP-обёртка `mcp_tools.py` с классификацией безопасности (`TOOL_SAFETY`: read/subscribe/write/escalated).

| Поверхность | Адрес | Что делает |
|---|---|---|
| `log_tail` / `log_untail` | `driver.py:1437` / `:1457` | подписка на `LogRecord` уровня ≥ level; sink = `RouterPushChannel`, `command="log.record"`, читается через `events_page` |
| `observability_tail` / `observability_untail` | `:1479` / `:1521` | live-хвост трёх плоскостей, `command="observability.record"`, `data.records` (пачка) / `data.record` (одна); порог задаёт подписчик (`level`) |
| `observability_tail_all` / `observability_untail_all` | `:1541` / `:1584` | через брокер PM — подписка на все процессы + автопереподписка свежих инкарнаций |
| `observability_records` | `:1602` | клиентский классификатор событий по `kind`/`level` |
| `telemetry_snapshot` | `:1304` | **0 IPC** — локальный снимок read-model; отдаёт `ingest_active`, `ingested_total`, `ingest_patterns` |
| `telemetry_history` | `:1358` | **0 IPC** — кольцевой буфер, `tracked` (внутри `DEFAULT_TRACKED_SUFFIXES`), `points: [[ts, value]]` |
| `telemetry_set` / `telemetry_reconfigure` / `introspect_telemetry` | `:951` / `:885` / `:397` | управление publisher-gate и чтение его состояния |
| `logger_sink_enable` / `logger_sink_disable` | `:857` / `:866` | снять/вернуть приёмник |
| `system_overview` | `:1407` → `overview.py:85` | fan-out по introspect + локальные источники, anomalies-подсказки, ноль новых IPC-команд |
| `await_condition` | `:1418` → `conditions.py` | `state_path` / `event_matches` / `metric_threshold` |
| `events` / `events_page` | `events.py:494` | пагинация событийных колец |
| `session_log` | `mcp_driver_session.py` + `audit.py` | аудит мутаций сессии |

**`record_*` — recorder** (`backend_ctl/recorder.py`, 51 КБ; MCP-описания `mcp_tools.py:1072-1155`). Формат JSONL `bctl-record` v1: header (версия, endpoint/session, активные подписки, снимок + экспорт колец истории) → строки `{"seq","ts","event"}` → footer (`reason` ∈ `stopped/limit/disconnect/dump`, счётчик `dropped`). Лимиты: `DEFAULT_MAX_EVENTS=100_000`, `DEFAULT_MAX_BYTES≈200 МБ`, `DEFAULT_QUEUE_MAXLEN=50_000`, `DEFAULT_RING_MAXLEN=10_000`. Инструменты: `record_start`, `record_stop`, `record_status`, `record_load` (offline-реплей через **ту же** точку `BackendDriver._emit_event`, `position=end|start` для тайм-трэвела), `record_unload`, `record_dump` (one-shot чёрный ящик). Все — `SAFETY_READ`. Файл без footer = `truncated: true`, грузится всё разобранное.

---

## 8. Трейсинг

**Есть два независимых механизма.**

**(а) `trace_id` — корреляция лог↔кадр, ВСЕГДА активна.** `process_module/generic/frame_trace.py`: `new_trace_id()` (`:103`) = `uuid4().hex`, 32 hex, формат W3C trace-id (без зависимости от OTel SDK); `ensure_trace_id(item)` (`:109`) — идемпотентно, единственное место рождения — `SourceProducer` (`generic/source_producer.py:165-171`); дальше поле едет вместе с item/data как обычное метаданное. Доставка в записи — `log_correlation(items)` (`:150`) поверх `contextualize(trace_id=...)`; ставится **в каждом потоке отдельно** (ContextVar не пересекает поток): `source_producer.py:180`, `data_receiver.py:191`, `pipeline_executor.py:195`. `_single_trace_id` (`:126`): смешанная пачка → пусто (чужой след не приписывается). Тесты: `test_g6_trace_id_correlation.py`, `test_frame_log_correlation.py`.

**(б) Спаны кадра (`item["trace"]`) — perf-профиль, гейтится env.** Флаг `MULTIPROCESS_FRAME_TRACE=1` (легаси-алиас `INSPECTOR_FRAME_TRACE`), по умолчанию **OFF**. Виды спанов: `transport` (`stamp_send`/`record_transport`, `:188`/`:200`, wall-часы), `process` (`record_process` `:222`, `perf_counter`, per-item деление батча), `merge` (`record_merge` `:229`). Fan-out — `fork_trace` (`:265`); fan-in — `merge_trace` (`:290`, critical path = ветвь с max суммой `ms`, + сводка `trace_branches`). Автообёртка плагинов — `traced` (`:355`) + `install_tracing` (`:388`) из `PluginOrchestrator.boot()`. Приёмник — `FrameTraceChannel` (перезапись `logs/trace/<process>.log` по кадру), вход `LoggerCore.frame_trace(message, seq_id)` (`logger_core.py:2030`).

**Чего нет:** нет `span_id`/`parent_span_id`, нет W3C `traceparent` на проводе, нет OTel SDK/OTLP-экспортёра (план `plans/otel-export.md` — «старт не согласован»; ревью спеки нашло блокер: `scope` до экспортёра не доезжает вовсе).

---

## 9. Хот-пас: цена эмиссии, batching, объёмы

**Замеры (все — в коде/доках, а не оценки).**
- **Гейт отклонённой записи** ≈ **240 нс** (`observability_wiring.py:44`); бенчи `logger_module/tests/test_gate_cost_bench.py` печатают: гейт (нс), решение скоупа (338 vs 330 нс — паритет), запись отклонена/принята (мкс), готовая строка vs callable, ключ кэша identity-хэш vs `Enum.__hash__`, скоуп строкой vs enum (53 vs 52 нс). Есть страж «бенчи ничего не теряют».
- **Эмиссия ~4.3 мкс**; полная регулярка редакции стоила бы 3.9 мкс на записи → введён предфильтр 0.57 мкс (`redaction.py:84-96`).
- **Защита реентрантности tap'а (D1)**: база эмиссии 0.36–0.41 мкс → 0.52 мкс, дельта +0.12…+0.16 мкс; при живом темпе ~44 записи/с ≈ 7 мкс/с (5 серий × 200 000 вызовов, медиана).
- **Учёт доставки (`_count_channel_written`)**: **+376 нс (+34 %)** против реального файлового стока; сам lock — 162 нс из 318.
- **Удобный метод логгера** (`.info()` и т.п.) — **219 нс** на переупаковке `*args/**extra`; поэтому `get_std_logger` зовёт `LoggerCore.log` напрямую.
- **Вся плоскость на живой нагрузке** (8 процессов × 21 Гц) — **0.03 % ядра**.
- **`DocumentStore.append`** под конкуренцией шести процессов: медиана 3.6 мс, p95 82 мс, **max 928 мс** — бюджет редкого события.
- **`VACUUM` миграции стора** на БД 200 000 строк / 118.3 МиБ — **1.06 с** (разово, при открытии).

**Batching.** Батчинг **файловой записи снят целиком** (ADR-LOG-008, Ф7.4: p99 хвоста эмитента 1348 против 75 мкс). Осталось три вида пакетирования: `AggregationWindow` (метрики, один снапшот за окно), `ObservabilityStore.append_records` (одна транзакция на пачку drain), `RecordForwardChannel.push_batch` (одна пачка на push), плюс `FrameTraceChannel` (один write на кадр).

**Объёмы.**
- **4.78 МБ/час** суммарно по восьми процессам (было 5.4 до миграции Ф6) — `docs/OBSERVABILITY_MAP.md:119`; отсюда арифметика ретеншена в `multiprocess_prototype/backend/config/system.yaml:136` (≈16 МБ/сут на процесс, 200 МБ ≈ 12 суток).
- **Доля stats**: замер 2026-08-03 — `performance.log` (плоскость статистики) даёт **5.27 МБ из 9.38 МБ** у ProcessManager = **56 %**; 2.33 из 8.88 у gui, 2.08 из 8.63 у region_splitter. Одна строка снапшота ≈ **7 КБ**. Суммарная запись на диск после выноса `PERFORMANCE` в свой файл **не уменьшилась ни на байт**.
- **ObservabilityStore**: 542 Б на строку (замер, 1369 строк = 0.707 МиБ), темп 5040 строк/час → потолок `max_rows=200_000` ≈ **110 МБ** и наступает через ~40 часов.
- **Шторм Б-6** (webcam_sketch, ~25 мин): 97 066 повторов одного текста, 21 903 потерянных записи, 88 313 вытеснений из событийного кольца → отсюда `RateSampler` и `queue_type="observability"`.

**Sampling есть**, но **выключен по умолчанию**: `sampling_first_n=0` (`configs/logger_manager_config.py:352`), `sampling_every_mth=100`, `sampling_burst_reset_sec=5.0` (нижняя граница `MIN_BURST_RESET_SEC`), `sampling_max_level="DEBUG"`; ERROR/CRITICAL не дросселируются никогда.

---

## 10. Дашборд: PyQtGraph-телеметрия

**Механизм.** Generic-компонент `TelemetryChart` (`multiprocess_framework/modules/frontend_module/widgets/telemetry_chart.py:68`) + декларативный `SeriesSpec{key,label,color,y_axis}` (`:50`). Строится по списку серий; `pg.PlotWidget` с `pg.DateAxisItem` (контракт: X = Unix-epoch wall-clock), `showGrid`, `setDownsampling(mode="peak", auto=True)` + `setClipToView`, легенда-чекбоксы (`set_visible`), zoom/pan, зум колесом по X, crosshair с панелью точных значений всех серий (Grafana-style), `compact`-режим как замена спарклайну, палитра `_DEFAULT_PALETTE` (8 цветов). API: `set_series_data(key, points)`, `set_visible`, `set_y_label`. pyqtgraph **0.14.0**, backend PySide6.

**Что показывает (прототип).**
- `SystemDashboardSection` (`multiprocess_prototype/frontend/widgets/tabs/processes/_system_dashboard.py:36`) — вкладка «Все процессы», **серия на процесс**, переключатель метрики `_DASHBOARD_METRICS = (fps, latency_ms)`, данные из ring-истории `TelemetryViewModel.history` (10 мин). Дашборд — **только чтение**: скрыть кривую ≠ выключить публикацию (это делает секция контролов Ф4.1). Пересборка при смене топологии — через `ProcessesTab._on_topology_replaced`.
- Мини-графики на карточке процесса (`_panels.py:829-838`): `fps` (#2563eb) и `latency` (#d97706) тем же `TelemetryChart` с `legend=False`.
- Вкладка «Наблюдаемость» (`multiprocess_prototype/frontend/widgets/tabs/observability/`): `ObservabilityTabs` (3 раздела Логи/Ошибки/Статистика), `RecordHistoryPanel` (пагинация из `ObservabilityStore`, live-append из `DataReceiverBridge.observability_received`, фильтр по уровню, `EMPTY_HINTS` — три причины пустоты), `RecordHistoryPresenter`, `RecordSource`, `tail_activator.py` (`ObservabilityTailActivator`).
- `wire_metrics_*` (`tabs/pipeline/telemetry/`) — бейдж метрик проводов.

---

## Итог: что ЕСТЬ

- Три плоскости на общей базе `ChannelRoutingManager` + четвёртая (документы, `DocumentStore`).
- `ObservabilityHub` — 3 bounded-канала (log/error/stats) на процесс, pull-drain по heartbeat.
- `BoundedChannel` с политиками `drop_oldest`/`drop_newest` и счётчиками `dropped`/`written`.
- Пять именованных классов потери + отдельный счётчик доставки `channel_written_records`.
- OTel-совместимые SeverityNumber (5/9/13/17/21) + `UNSPECIFIED=0` для плоскости без уровней.
- Цепочка процессоров записи (`add_processor`), контракт как у `logging.Filter`.
- Редакция секретов `SecretRedactor` (ADR-LOG-006): `extra` по именам + текст регуляркой + URL-креды + auth-схемы, fail-closed, без выключателя.
- Дроссель повторов `RateSampler` (first_n / every_mth / burst_reset), выключен по умолчанию, ERROR+ не трогает.
- `contextualize(**fields)` — публичная форточка контекста через ContextVar.
- Шесть типов sink'ов + `register_sink_factory` для седьмого без правки фреймворка.
- Ротация файлов (общий `_SafeRotatingFileHandler` на abspath, 10 МиБ × 5), retention по возрасту/весу + фоновый свип, сжатие бэкапов.
- Кольцо `memory` в процессном реестре `_memory_rings` — переживает пересоздание канала, читается ретроспективно (`observability.sink.tail`).
- `ErrorFloor` — синхронный конфиго-независимый пол, JSON Lines, саморотация 32 МиБ.
- Пломба `seq` — сквозной номер записи в пределах процесса + внешний проверяющий `scripts/observability_seal`.
- Severity-лестница ошибок **данными** (`severity_routes`), пересборка на смену состава каналов.
- `AggregationWindow`: counter/gauge/timing/histogram, min/max/avg/**p95**, темп из живого окна, учёт `total_flushed`/`flush_failed`.
- SQLite `ObservabilityStore`: WAL + `synchronous=NORMAL` + `busy_timeout`, `auto_vacuum=INCREMENTAL` с миграцией по `user_version`, `severity_number`-колонка + индекс, пагинация, `purge` по возрасту и числу строк.
- Единый нормализатор `record_display` — форма live == форма history по построению.
- `observed_ts` (OTel ObservedTimestamp) ставит только приёмник, не перетирается.
- Tap-механика с per-subscriber именами, поточной защитой от реентрантности и счётчиком подавленных.
- Живой хвост своим QoS-классом `queue_type="observability"` (best_effort, drop_oldest, глубина 256).
- 4 слоя конфигурации L0→L3 с провенансом по сырым секциям, пересборкой из источников, TTL 300 с и `observability.persist`.
- Audit-кольцо смен наблюдаемости (100 записей, 8 действий, обязательный `origin`, схлопывание повторов).
- Трёхзначный вердикт применения + `DeliveryWindow` с вычетом цены самого опроса.
- Subscription broker у оркестратора с автопереподпиской свежих инкарнаций.
- `trace_id` (32 hex, W3C-формат) — рождение у источника, доставка в каждую запись через `log_correlation`.
- Span-трассировка кадра (transport/process/merge, critical path на fan-in) за env-флагом.
- Read-model телеметрии без блокирующего IPC (ADR-136) + publisher-gate per-метрика.
- `backend_ctl`: `log_tail`, `observability_tail(_all)`, `telemetry_snapshot/history` (0 IPC), `system_overview`, `await_condition`, `introspect_telemetry`, `session_log`.
- Recorder `record_start/stop/status/load/unload/dump` с offline-реплеем в тот же read-model.
- `TelemetryChart` (PyQtGraph) + системный дашборд «серия на процесс» + вкладка «Наблюдаемость» с пагинацией и live-хвостом.
- Реестр объявлений `declare_log_source` / `declare_metric` — каталог метрик наполняется рядом с вычислением.
- `get_std_logger` — вид над единственным писателем; страж `test_std_logger_guard.py` по AST на четыре дерева.
- Замеры хот-паса зафиксированы бенч-тестами и ADR (нс/мкс, а не «незначительно»).

## Итог: чего НЕ нашёл

- **Нет OTLP/OTel-экспортёра** — только план `plans/otel-export.md`, старт не согласован; соответствие модели OTel остаётся заявленным.
- **Нет `span_id`/`parent_span_id`/`traceparent`** — есть только `trace_id` и in-band список спанов кадра.
- **Нет сквозного трейсинга не-кадровых сообщений** — span-трассировка привязана к item пайплайна и к env-флагу.
- **Нет гистограмм в индустриальном смысле** — `MetricType.HISTOGRAM` хранит полный список значений и отдаёт те же min/max/avg/p95; ни бакетов, ни HDR, ни квантильных скетчей; в продовом коде `histogram()` не вызывается нигде, кроме теста.
- **Нет перцентилей кроме p95** (ни p50/p99, ни настраиваемых).
- **Нет темпа/rate в счётчиках** — снят намеренно (`observed_rate_per_sec` удалён), наружу едут counter + `observed_at`.
- **Нет seqlock и SHM-колец в подсистеме телеметрии/наблюдаемости** — они существуют только в кадровом транспорте (`shared_resources_module/memory`).
- **Нет stats-разъёма у плагина** — `IProcessServices` не объявляет stats-методов, `kind=stats` до стора не доезжает (единственная незакрытая асимметрия).
- **Нет JSON-формата у обычных лог-файлов** — только текст через `SealFormatter`; JSON есть у `ErrorFloor` (JSONL) и `FileStatsChannel`.
- **Нет sampling'а по умолчанию** — механизм есть, но `sampling_first_n=0`; ретеншен логов тоже выключен из коробки (`retention_days`/`retention_total_mb` = 0).
- **Нет per-callsite тумблеров** — отвергнуты сознательно, гранулярность = источник/группа.
- **Не действуют на лету** `observability.documents` и `observability.history` (сшиваются один раз на `initialize()`); `config.reload {"persist": true}` не реализован.
- **Нет графы «кто» в аудите** — только `origin` (механизм), человек не фиксируется ни одним конвертом команды.
- **Нет ограничения на поток, вошедший в блокирующий `write()` стока** — лесенка ADR-LOG-009 спасает остальных, не жертву.
- **Нет разделения «мои записи / чужие»** в `DeliveryWindow` — вычет `self_cost` верен только в эксклюзивном окне.
- **Нет автоматической уборки чужих деревьев логов** — `find_foreign_log_roots` только называет путь/число файлов/вес.
- **Нет живого Linux-прогона** — Linux-вердикты подтверждены только CI на ubuntu.
