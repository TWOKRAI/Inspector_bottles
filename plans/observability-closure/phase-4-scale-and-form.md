# Масштаб, форма, универсальность

> Фаза Ф4 плана [`observability-closure`](./plan.md). Правила приёмки — `plan.md` §3 (наследуют `observation-port/plan.md` §3), развилки владельца — `plan.md` §4, что удаляется и миграции — `plan.md` §9–§10. Номера находок (C*, M*, m*) — по [ревью 2026-08-28](../../docs/reviews/2026-08-28_observability-full-review.md).

## Ф4 — Масштаб, форма, универсальность

### Task 4.1 — Hub уровней как карта последних значений; ёмкость и каденция из политики (M10a)
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework
**Files:** `channel_routing_module/observability/observability_hub.py:90-130,170-200`, `channel_routing_module/observability/bounded_channel.py`,
`process_module/managers/observability_wiring.py:120-130`, `process_module/heartbeat/process_heartbeat.py:981-1013`, `statistics_module/observation/observation_manager.py:933-983` (`records_for_hub`).
**Steps:** канал уровней — карта `(writer, metric) → последнее значение` с эмиссией только изменившихся (`changed_only`, из политики), дренаж забирает карту целиком; ёмкость log/error/stats-каналов — `observability.hub.capacity` (L0 = 1024, провенанс, readback эффективного).
**Acceptance criteria:**
- [ ] Бенч: 1000 листьев × 5 тиков между дренажами → `dropped {}`, в сторе те же значения, что в дереве (пара с прежним `dropped 3976`).
- [ ] Живьём: синтетический плагин на 500 листьев → `queue_observability_evicted == 0`, `hub.dropped == {}` за 10 минут.
- [ ] Инъекция: вернуть очередь → бенч красный по `dropped`.

### Task 4.2 — Индекс подписок по статическому префиксу (M10b) + замер на 20 процессах
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework
**Files:** `state_store_module/core/subscription_manager.py:180-200,300-345`, `state_store_module/manager/delta_dispatcher.py:140-150`, рецепт для замера (`multiprocess_prototype/recipes/g1_perf_probe.yaml` или новый синтетический на N процессов).
**Acceptance criteria:**
- [ ] Бенч: 100 подписок → ≤ 30 мкс/дельта (было 188); 20 подписок → ≤ 10 мкс (было 25.5).
- [ ] Живьём 20 процессов × 100 листьев × 1 Гц: CPU `ProcessManager` числом до/после; `state`-очередь без `evicted`.
- [ ] Инъекция: индекс отключён → бенч красный.

### Task 4.3 — Протокол readback и распил хендлера (M11)
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework
**Files:** `channel_routing_module/interfaces.py` (Protocol `ObservabilityReadback`: `readback()`, `sinks()`, `counters()`), четыре менеджера,
`process_module/managers/observability_reload.py`, `process_module/managers/observability_wiring.py:380-420` (`_sink_readback`),
`process_module/commands/builtin_commands.py:1576-2300` → `commands/observability_commands.py` + `commands/introspect_commands.py`,
новый `run_config_reload(...)` в `observability_reload.py` с тестом на порядок стадий; `backend_ctl` — инструмент `flare` (конфиг-слои + счётчики + последние N аудита + версии одним ответом).
**Acceptance criteria:**
- [ ] `getattr(` по менеджерам в `observability_reload.py`/`observability_wiring.py` — 0 (AST-страж с литералом); `LoggerCore.get_stats` ключи = базе (`channel_count`).
- [ ] `_cmd_config_reload` ≤ 80 строк; стадии `validate → layer → apply → verify → audit → reply` — отдельные функции с тестом порядка (инъекция перестановки → красный).
- [ ] Контракт-оракул команд зелен; `flare` живьём возвращает бандл ≤ 200 КБ с `fw_version`.

### Task 4.4 — Точечные подписки переживают рестарт и креш клиента (M5, CTL-F3)
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework, tests (backend_ctl)
**Files:** `process_manager_module/process/observability_broker.py:250-300`, `process_manager_module/process/process_manager_process.py:2780-2820`,
`backend_ctl/driver.py:1517-1660`, `backend_ctl/recorder.py` (manifest с сервера).
**Steps:** реестр точечных намерений в брокере (`log.tail`, `observability.tail`, `ui.tap`) с `forget_session` и replay на `instance.started`; `record_status.subscriptions` — из серверного состояния; `untail` мёртвой инкарнации → `reason`.
**Acceptance criteria:**
- [ ] Живьём: точечный хвост `pult` → рестарт → записи от новой инкарнации идут (пара с прежним 0); RST-обрыв клиента → `errors_delivery_failed` не растёт через 30 с (зонд `probe_n3_1` расширен на точечные).
- [ ] Инъекция: replay снят → тест хвоста после рестарта красный.

### Task 4.5 — `ServiceContext`: разъём наблюдаемости для авторов сервисов (M13, DX А.2)
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework, services
**Files:** `service_module/interfaces.py:46-90`, новый `service_module/core/service_context.py` (зеркало обогащённого `PluginContext`: `log_*`, stats-четвёрка, `report_error`, `write_document`, `declare_metric`),
`Services/robot_comm/*`, `Services/modbus/*`, `Services/vfd_comm/*` (миграция), `CONNECTORS.md`, `NEW_MODULE_RECIPE.md` (раздел «сервис»).
**Acceptance criteria:**
- [ ] Живьём без робота: `robot_comm` даёт запись об отказе соединения с командой/попыткой/задержкой в `errors.log` и сторе (было 0 записей на 2336 строк).
- [ ] Контракт-тест: `ServiceContext` несёт весь протокол `PluginContext` наблюдаемости (оракул по интерфейсу); слепой прогон рецепта для сервиса.
- [ ] Инъекция: метод снят у контекста → оракул красный поимённо.

### Task 4.6 — Нейтральный словарь ядра и литералы в политику (m9, m10, m12, Р-4, Р-6)
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework, prototype
**Files:** `process_module/heartbeat/telemetry.py:58-61,160-170`, `process_manager_module/monitor/process_monitor.py:560-600`, `telemetry_readmodel_module/telemetry_read_model.py:45-75`,
`logger_module/core/logger_core.py:2064-2156` (`frame_trace` → `register_sink_factory`), `statistics_module/core/metric_record.py:30-60` (сетка бакетов из конфига),
`process_manager_module/core/alert_rules.py` + `monitor/process_monitor.py:158` (секция `observability.alerts.rules`, `DEFAULT_RULES` = L0),
`backend_ctl/registers.py:100-140` + `process_manager_module` (commit-confirmed на стороне ПМ под TTL-подметальщиком, Р-6а), рецепты и GUI, где встречаются `fps`/`latency_ms`.
**Acceptance criteria:**
- [ ] `rate_hz`/`cycle_ms` публикуются; `fps`/`latency_ms` — алиасы с провенансом `alias` и датой снятия в ADR; read-model и дашборд живут (qt-smoke); алерт `drops_growing` живьём срабатывает на новом пути (пара).
- [ ] `frame_trace` — сток по фабрике: `LoggerCore` не содержит слова `frame` (страж); `grep -rn "fps\b" multiprocess_framework/modules` вне алиас-таблицы → 0.
- [ ] Правило алертинга из рецепта (`p95 > X` по метрике окна) срабатывает живьём; `DEFAULT_RULES` виден как L0 в readback.
- [ ] `set_register(confirm_within=30)` → откат исполняет ПМ при креше клиента (kill -9 MCP-сервера — пара с прежним «остаётся применённым»).

### Task 4.7 — Реестр объявлений как объект процесса (Р-5а)
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework
**Files:** `multiprocess_framework/modules/observability_declarations.py`, `process_module/core/process_module.py`, все `declare_*` вызывающие (фасад совместим).
**Acceptance criteria:**
- [ ] Module-level API работает без изменений у вызывающих (0 правок в Plugins/Services); реестр процесса создаётся `ProcessModule`, тесты получают свежий через фикстуру; голого сброса нет как API.
- [ ] Гейт зелен в трёх случайных порядках модулей (`-p random-order` или скрипт перестановки).

### Task 4.8 — Живой стенд Ф4 (20 процессов) + ревью фазы
- [ ] Числа масштаба в отчёте: дельт/с, CPU ПМ, `hub.dropped`, `evicted` — все нули с контролем «нагрузка есть» (дельты > 0).
