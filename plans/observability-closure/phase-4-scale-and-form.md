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

**Добор ревью Ф1 (2026-09-01) — сюда же, той же волной: окно голосов за потолком.** Устоявшие
находки угла «универсальность» ([`review-phase-1.md`](./review-phase-1.md)): при алфавите ключей
> `MAX_TRACKED_KEYS` (512) окно голоса **выключается целиком** — обрыв, не деградация (замер
угла: 600 устройств × окно 5 с × такт 2 с → 180 000 голосов на 180 000 событий против 33 % при
512); `take()` за потолком дорожает ~**172×** и делает это под локом держателя на дороге отказа;
существующие сторожа потолка проверяют только память и только сценарий с должниками. Требуется:
деградация вместо обрыва (вытеснение старейшего ключа, не отказ всем новым), цена за потолком —
числом до/после, сторож режима отказа (не памяти). Ручка и readback потолка — уже в Task 2.7.
**Условие подтягивания вперёд:** device-heavy прототип (сотни устройств/ключей на процесс)
раньше Ф4 — тогда этот кусок идёт отдельной задачей до своей фазы.

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
`backend_ctl/registers.py:100-140` + `process_manager_module` (commit-confirmed на стороне ПМ под TTL-подметальщиком, Р-6а), рецепты и GUI, где встречаются `fps`/`latency_ms`,
`backend_ctl/overview.py` (секция `telemetry.fps`, аномалия `fps_zero_while_running`), подписи GUI (`StatusLabel «FPS»`).

**Р-4 решена владельцем 2026-09-01 — принцип, которому следует задача:** универсальный дефолт
ядра — исполнение, и это **пара** чисел: темп (`rate_hz`) и занятость (`cycle_ms`); у воркеров
пара уже живёт в нейтральной форме (`effective_hz`/`target_interval_ms` — их задача НЕ трогает).
`fps` — доменное имя камеры и дисплеев изображений, и метрика ДРУГОГО РОДА — пропускная
способность полезной нагрузки, не темп петли (живое расхождение: стенд Ф1.5, `camera_0` без
камеры — петля 21.5 Гц при 0 кадров). **Исполнителю: не выводить `rate_hz` из числа кадров и не
подменять fps темпом петли** — их расхождение и есть диагноз «петля жива / нагрузки нет».
Обобщение fps — throughput с единицей из метаданных метрики (Task 3.4 / M12). `fps` законно в
прикладных модулях, GUI и у камеры (`fps_limit` дисплея, `capture_fps` плагина — остаются), но
как имя АГРЕГАТА ФРЕЙМВОРКА (`processes.<p>.state.fps`, `latency_ms`) уходит в алиас с датой
снятия. Критерий «grep fps → 0 вне алиас-таблицы» относится к `multiprocess_framework/` —
доменные `fps` прототипа и плагинов под него не подпадают.
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

### Task 4.9 — Универсальный механизм ручек: `KnobManager` уровня фреймворка, observability — первый потребитель (ревью Ф2 §6, §2.2а; направление владельца 2026-09-02)
> Заведена 2026-09-02 по [`review-phase-2.md`](./review-phase-2.md). **Направление владельца
> (2026-09-02): ручка — универсальный механизм со своим менеджером/инспектором, потому что ручки
> живут по всей наблюдаемости и за её пределами.** Поэтому цель задачи не «реестр внутри
> observability», а менеджер фреймворка, у которого observability — первый, но не единственный
> потребитель. Предпосылка Task 4.3 (Protocol readback менеджеров). Порядок: 4.3 → 4.9.
> **Порог:** если инвентарь шага 1 покажет ≥3 потребителя, задача выделяется в собственный план
> (`/dev:plan`, slug `knobs-universal-manager`) по правилу «10+ файлов, архитектура → Manager →
> TeamLead → Reviewer»; здесь остаётся ссылка.

**Level:** Senior (Opus) · **Assignee:** teamlead (после Manager-декомпозиции) · **Layer:** framework
**Goal:** добавить ручку в любом месте системы — значит написать **одно объявление** (`KnobSpec`: путь, схема значения, применитель на живом объекте, геттер readback, справочная строка), после чего слои L0→L3 с TTL и аудитом, провенанс, вердикт `confirmed/failed/unverifiable`, `introspect` и справочник получаются **даром**, из менеджера, а не из пяти ручных ветвлений на каждую ручку.

**Что уже есть и переиспользуется, а не пишется заново** (инвентарь ревью Ф2):
- `ObservabilityLayers` (`process_module/configs/observability_layers.py`) — четыре слоя, TTL-подметальщик, `session_keys`, аудит `reverts`, провенанс `_schema_keys()`. Это и есть универсальный слоёный стор ручек, названный по первому потребителю. Переезжает в менеджер как ядро.
- `observability_verified` — трёхзначный вердикт, round-trip неизвестных ключей. Переезжает как метод менеджера; `expected` строится из реестра.
- `backend_ctl.set_register_verified` / `register_snapshot` / `register_rollback_log` — та же форма «применил → сверил → откатил» у регистров, написанная второй раз (`backend_ctl/registers.py`, commit-confirmed, Р-6). Второй потребитель-кандидат.
- `telemetry.reconfigure`/`_apply_telemetry_from_layers` — третья копия дороги ручки со своими слоями (`TELEMETRY_KEY`). Третий кандидат, после снятия легаси (Task 2.5, ADR-PM-041).
- `FW_*`-флаги (реестр `ctor > env > default`), пресеты камеры (`camera settings`), параметры рецептов — за пределами наблюдаемости; в инвентарь входят, в первую волну миграции — нет.

**Files:** новый модуль фреймворка (имя и ярус — решение teamlead в ADR; кандидаты: `knob_module` как core-модуль на `BaseManager`, по правилу владельца «всё через BaseManager, три менеджера — одна база»), `process_module/configs/observability_layers.py` (→ ядро менеджера), `process_module/managers/observability_reload.py` (`_rebuild_and_apply`, `observability_effective`, `observability_verified` → потребители менеджера), `process_module/commands/builtin_commands.py` (`config.reload`/`introspect.observability` → тонкие алиасы над `knob.set`/`knob.readback`/`knob.verify`), `backend_ctl` (инструменты `config_reload_verified`, `set_register_verified` — общий драйверный путь), `scripts/docs_verify/docs_check.py`, `CONTROL_PANEL.md`, `CONNECTORS.md`, `NEW_MODULE_RECIPE.md` (раздел «как объявить ручку»), `MODULE_TIERS.md` + контракт-тест ярусов.
**Steps:**
1. **Инвентарь числом** (Manager): все дороги «ключ → применение → readback → вердикт» в дереве: observability (20 веток с пометкой `unverifiable` в `observability_reload.py`), регистры, `telemetry.*`, `FW_*`, камера, рецепты. Для каждой: сколько ручных точек стоит одна ручка сегодня (у `heartbeat_interval_sec` — 7, ревью Ф2 §2.2а). Таблица в `workspace`-заметке задачи; она же решает порог выделения в план.
2. **Контракт** (`module-contract`, full): `KnobSpec` (`path`, `schema`, `apply(live, value)`, `readback(live)`, `doc`, `scope`: процесс/ПМ/глобально), `KnobManager` (`declare(spec)`, `set(path, value, layer, ttl)`, `readback()`, `verify(requested) -> verdict`, `provenance()`, `audit()`), `introspect.knobs` — одна команда на все namespace'ы. Под-секции с собственным механизмом (`observation`, `voices`, `events`, `flight`, `history`) — `KnobSpec` на секцию с нормализацией (как сегодня `normalized_observation_section`).
3. **Первый потребитель — observability**: описатели для всех ручек `observability.*`; `_rebuild_and_apply`, `observability_effective`, `observability_verified` становятся обходом реестра; `IDENTITY_SECTION_KEYS`, `_TOP_LEVEL_DICT_KEY_READERS`, ручные строки (`session_ttl_sec`) исчезают. Старые команды и инструменты работают как алиасы — 0 правок у вызывающих (`backend_ctl`-тесты зелены без изменений, кроме форм ответа, названных в ADR).
4. **Второй потребитель доказывает универсальность**: регистры (`set_register_verified` через тот же менеджер, commit-confirmed = слой с TTL — Р-6а) либо `telemetry.*` — по инвентарю выбирается тот, у кого дорога короче. Без второго потребителя задача не считается закрытой: «универсальный механизм с одним потребителем» — это переименование.
5. **Стражи**: лист схемы без описателя — красный поимённо; описатель без листа — красный поимённо (пара); `docs_verify` сверяет справочники с реестром; AST-счёт ручных ветвлений применения/readback вне менеджера.
**Acceptance criteria:**
- [ ] Эксперимент «новая ручка»: тестовая ручка добавляется ОДНИМ объявлением + строкой схемы; `config_reload_verified` даёт `confirmed`, `introspect.knobs` показывает провенанс и TTL, справочник проходит `docs_verify` — при `git diff --stat`, в котором нет ни `observability_reload.py`, ни `builtin_commands.py`. Пара: та же ручка без описателя → страж красный по имени.
- [ ] Два потребителя на одном менеджере живьём: `config_reload_verified(camera_0, …)` и `set_register_verified(…)` дают вердикт одной формы, откат по TTL пишется в один аудит; инъекция «снять TTL-подметальщик» → красны сторожа ОБОИХ потребителей.
- [ ] Число ручных ветвлений применения/readback вне менеджера ≤ 3 (AST-счёт до/после в коммите; «до» — по инвентарю шага 1).
- [ ] Гейты фреймворка, `sentrux check .`, `docs_verify` зелены; `MODULE_TIERS.md` и карта ответственности содержат новый модуль; полная секция `observability` через `config_reload_verified` → `unverifiable: []` на всех восьми процессах.
- [ ] Цена: `config.reload` не медленнее, чем до задачи (три соло-замера пары «до/после», отношение ≤ 1.2).
**Out of scope:** миграция `FW_*`-флагов, пресетов камеры и параметров рецептов (инвентаризируются, переезжают отдельными задачами после доказанного второго потребителя); новые ручки; GUI-редактор ручек (после того, как `introspect.knobs` даст один источник для вкладки Settings).

### Task 4.10 — Словарь политики в один модуль ниже обеих плоскостей; кольцо `process_module ↔ statistics_module` снято (ревью Ф2, M4)
> Заведена 2026-09-02 по [`review-phase-2.md`](./review-phase-2.md) §2.2(г). sentrux кольца не видит (одна половина ленивая), поэтому нужен собственный страж.

**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework
**Goal:** `ObservationPolicy`, `PathSchedule`, помощники путей (`stats_metric_path`, `state_metric_path`, `plugin_metric_path`) и `PolicyDecision` живут в одном модуле, от которого зависят и `process_module`, и `statistics_module`; обратных импортов (в том числе ленивых) между этими двумя пакетами нет.
**Files:** `process_module/configs/observation_policy.py`, `statistics_module/observation/numbers_gate.py`, `statistics_module/observation/observation_manager.py:135,:253` (ленивые импорты), `process_module/heartbeat/telemetry.py:29`, место назначения — по решению teamlead с доводом в ADR (кандидаты: `channel_routing_module` как общая база трёх менеджеров; `state_store_module`, где уже живёт `match_pattern`; новый модуль только если оба не подходят — тогда `MODULE_TIERS.md` и контракт-тест ярусов).
**Steps:**
1. Замер до: список всех импортов `process_module → statistics_module` и обратных, включая ленивые внутри функций (AST по `Import`/`ImportFrom` в любой глубине тела), числом в коммите.
2. Перенос словаря; `TelemetryPublishConfig` (легаси-вход политики) остаётся в `process_module` — политика принимает его duck-typed, как сегодня `NumbersGate` принимает политику.
3. AST-страж «нет импортов между `process_module` и `statistics_module` ни на уровне модуля, ни внутри функций» в одну сторону, которую назовёт ADR; инъекция «вернуть ленивый импорт» → красный по адресу файл:строка.
**Acceptance criteria:**
- [ ] Обратных импортов (по AST, включая ленивые) между двумя пакетами — 0; страж красен на инъекции.
- [ ] `sentrux check .` и полный гейт фреймворка зелены; E2/E5 матрицы Ф2 (второй потребитель отвалился; расписание — один класс) остаются красными под своими заплатами.
- [ ] Порядок импорта пакетов не значим: гейт зелен в трёх случайных порядках модулей (тот же приём, что у Task 4.7).
**Out of scope:** перенос самого `ObservationManager`/`NumbersGate` (они остаются плоскостью чисел).

### Task 4.11 — Голос конфига переезжает со стадии «разбор» на стадию «применяю»; адрес аварийного выхода вычищен (вердикт CTO 2026-09-03, корень m1)
**Level:** Middle (Sonnet) · **Assignee:** developer · **Layer:** framework
**Goal:** предупреждение о смене смысла ключа звучит один раз на ДЕЙСТВИЕ, а не N раз на разбор, и число «подавлено» считает действия; ни один голос оператору не уходит в `stderr` мимо журнала.

**Откуда задача.** Task 2.12 (m1) закрыла симптом: голос ADR-PM-046 шёл шестью копиями на один `config.reload`, теперь дросселируется окном. Вердикт CTO снял моё объяснение причины стеком вызовов: шесть — это шесть **явных** разборов секции из ТРЁХ стадий команды (`проверить` → `применить` → `сверить`, решение B2 / Task 5.7), а не пересборка Pydantic внутри одного разбора. Трёхстадийность сознательна и дефектом не является. Дефект — **ввод-вывод внутри функции, которую зовут как парсер**. Окно это МАСКИРУЕТ: число голосов стало зависеть от часов, а «подавлено: N» считает разборы — три `config.reload` за одно окно дают «подавлено: 17», честное число не той величины, которую ждёт читатель.

Второй адресат задачи — тот же класс у соседей. Замер CTO грепом: боевых вызовов `emergency_log` — **21** в 10 файлах. В ошибочной позиции (сообщение ОПЕРАТОРУ, а не самоотчёт сломавшегося маршрута) — **6 в 3 файлах**; ещё **3 пограничных**; законных 12. Task 2.12 починила один из шести.

**Files:**
- `process_module/configs/observability_config.py` — снять голос из `_complain_about_repurposed_enabled` (валидатор остаётся ЧИСТЫМ), перенести в `expand_observability` / вызывающую его `compose_managers_payload`;
- `process_module/managers/process_managers.py:130` (дорога boot) и `process_module/managers/observability_reload.py:219` (дорога reload) — обе уже зовут `compose_managers_payload`; **пересчитать вызывающих грепом**, утверждение «единственная apply-дорога» у CTO опирается на докстринг и один стек, а не на полный обход;
- `Services/documents/wiring.py:173,183,191`, `multiprocess_framework/modules/observability_declarations.py:145`, `process_module/configs/observability_config.py:800` — пять оставшихся вызовов `emergency_log` в ошибочной позиции → вид (`FallbackLogger`);
- `channel_routing_module/observability/observability_store.py:284,350,372` — три пограничных: довод о рекурсии здесь защитим (стор сам tap логгера), **решать отдельно и записать решение**, не переводить механически;
- тесты задачи 2.12 (`test_f2_task212_repurposed_voice_window.py`, `test_repurposed_voice_window_hazards.py`) — перенести к новой двери.

**Steps:**
1. Пересчитать грепом вызывающих `compose_managers_payload` и назвать число: «единственная apply-дорога» — гипотеза CTO, а не факт.
2. Перенести голос. Валидатор становится чистым парсером; окно остаётся ВТОРЫМ рубежом для цикла ассемблера по процессам (на boot родитель зовёт `apply_layers_to_proc_dict` по разу на процесс — замер CTO на blueprint из трёх процессов дал 3 срабатывания, окно схлопнуло в один голос «(подавлено: 2)»).
3. Пять `emergency_log` → вид. Три пограничных — решение с записью, не механический перевод.
4. Замер boot на БОЕВОМ blueprint прототипа, а не на тестовом из трёх процессов (оговорка CTO).

**Acceptance criteria:**
- [ ] Один `config.reload` со `stats.enabled: false` → **1** голос, и «подавлено» после трёх reload за окно называет **2**, а не 17 — то есть считает действия оператора.
- [ ] Голос читается ИЗ ФАЙЛА журнала настоящего `LoggerManager` (золотой путь; `caplog` для этого вопроса — фейковый харнесс, доказано J12: 24 теста зелены при неверном адресе, красный даёт ровно один).
- [ ] Boot боевого прототипа со старым конфигом: голос в файле, число названо; между процессами окно не работает по построению — сказать это вслух, а не считать дефектом.
- [ ] Инъекция «вернуть голос в валидатор» → красный по числу; инъекция «вернуть `emergency_log`» → красный золотого пути.
- [ ] Число оставшихся `emergency_log` в ошибочной позиции — **0**, посчитано грепом; для трёх пограничных записано решение с доводом.
**Out of scope:** трёхстадийность `config.reload` (сознательное решение B2/5.7, не трогать); контракт самого `emergency_log` (он остаётся дверью для самоотчёта сломавшегося маршрута).

### Task 4.8 — Живой стенд Ф4 (20 процессов) + ревью фазы
- [ ] Числа масштаба в отчёте: дельт/с, CPU ПМ, `hub.dropped`, `evicted` — все нули с контролем «нагрузка есть» (дельты > 0).
