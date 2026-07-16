# Plan: GUI Telemetry Read-Model — «запись всегда, чтение локально, история по запросу»

- **Slug:** gui-telemetry-read-model
- **Дата:** 2026-07-16
- **Ветка:** feat/gui-telemetry-read-model (Фаза 0 допустимо hotfix-ом раньше остальных)
- **Статус:** ACTIVE (реализация начата 2026-07-16; чекбоксы, предзаполненные при написании плана
  несуществующими хешами, сброшены — отмечаются заново по мере реальных коммитов)
- **Реактивирует:** [`telemetry-delivery-simplification.md`](telemetry-delivery-simplification.md) Option D (был DEFERRED
  «до gate: 2-й реактивный потребитель ИЛИ замер показал боль двойного glob»). **Gate сработал 2026-07-16:**
  диагностирован шторм блокирующих подписок при открытии вкладки «Процессы» (см. Context). После Фазы 3 пометить
  telemetry-delivery-simplification как SUPERSEDED (ссылкой сюда).
- **Координация:** [`framework-layer-grouping/plan.md`](framework-layer-grouping/plan.md) — НЕ выполнять параллельно
  с его Фазой 3 (codemod переписывает импорты по всему репо). Порядок: Фаза 0 отсюда → затем либо этот план целиком,
  либо layer-grouping Инициатива 1 — по приоритету владельца, но строго последовательно.

---

## Context (диагноз 2026-07-16, доказан по коду)

Первое открытие вкладки «Процессы» всегда фризит GUI на ~5 с (теперь дольше). Корневая причина:

1. `ProcessesTab._sync_nav()` жадно создаёт панели **всех** процессов; каждый `bindings.bind()` зовёт
   `ensure_subscription(pattern)` → `StateProxy.subscribe()` → `router.request(timeout=5.0)` —
   **блокирующий IPC-раундтрип в Qt main thread** на каждый уникальный паттерн (~60–150 подряд).
2. Дедуп подписок — по **точному совпадению строки**; стартовые wildcard'ы `processes.**`/`system.**`
   (frontend/process.py) уже покрывают все пути, но точечные подписки создаются всё равно.
3. Сервер на каждый subscribe делает `_replay_initial_state` → `get_subtree("")` — **deep-copy всего
   дерева состояния** (state_store_manager.py:412). Растёт с размером телеметрии (Ф7, dualcam).
4. Каскад: fan-out `workers.*.status` обнаруживает runtime-воркеров по одному → полное перестроение
   WorkerTable + новые биндинги + новые блокирующие подписки на каждого.
5. Побочный налог навсегда: ~100 лишних серверных подписок → PM матчит каждую дельту против всех.

Данные при этом **уже текут** в GUI одним wildcard-потоком и лежат в `GuiStateProxy._cache` — точечные
подписки дублируют существующую доставку. История **уже пишется** плагином `telemetry_sink`
(`Plugins/io/telemetry_sink`, SQLite, семпл 5 с) — read-стороны для GUI нет.

## Принцип (кандидат в глобальный ADR)

**«Запись — всегда, чтение — локально, история — по запросу»** (паттерн вкладки «Наблюдаемость»):

- Backend публикует телеметрию постоянно (троттлинг 1 Гц), независимо от открытых вкладок.
- GUI держит **один** локальный read-model, наполняемый **одним** wildcard-потоком, оформленным при старте.
- Виджеты читают **только локально**. Инварианты (enforce тестом):
  1. GUI main thread никогда не делает блокирующий IPC (`router.request`).
  2. Открытие вкладки не создаёт серверных подписок (`state.subscribe` == 0 на открытие).
- Live ≠ история: live — из read-model (push-поток), история/графики — pull страницами из БД стока.
  Live-значения из SQLite не читаем (семпл 5 с, чужой процесс, лишний I/O-путь).

---

## Фазы

### Фаза 0 — Hotfix шторма подписок (самодостаточна, шипится отдельно и первой)

#### Task 0.1 — Coverage-check вместо строкового дедупа
**Level:** Middle+ (Sonnet) · **Assignee:** developer
**Goal:** паттерн, уже покрытый существующей серверной подпиской, не создаёт новую.
**Files:** `multiprocess_framework/modules/state_store_module/proxy/state_proxy.py` (`ensure_subscription`),
  реюз glob-матчера модуля (`core/subscription_manager` / `pattern_utils`), tests.
**Steps:** 1. В `ensure_subscription`: перед созданием проверить, покрывает ли какой-либо активный паттерн
  (`_sub_patterns` + `_pattern_sub_id`) новый паттерн (glob-накрытие: `processes.**` ⊇ `processes.X.state.fps`).
  2. Покрыт → зарегистрировать refcount на покрывающий, серверный subscribe НЕ слать.
**Acceptance:**
- [x] Открытие ProcessesTab при живых стартовых wildcard'ах → 0 исходящих `state.subscribe` (характеризационный тест) — `TestCoverageCheck::test_covered_pattern_sends_no_server_subscribe` + `test_covered_pattern_still_receives_delta`
- [x] Непокрытый паттерн по-прежнему создаёт подписку (регресс-тест 5.9 «панель мертва») — `TestCoverageCheck::test_uncovered_pattern_creates_subscription`
**Out of scope:** доставка/replay, GUI-код.

#### Task 0.2 — Fire-and-forget подписка вне main thread
**Level:** Middle+ (Sonnet) · **Assignee:** developer
**Goal:** непокрытые паттерны подписываются без блокировки вызывающего потока.
**Files:** `state_proxy.py` (`subscribe`/`_send_sync`), `frontend/state/bindings.py` (`_ensure`), tests.
**Steps:** 1. Вариант async: `subscribe(..., sync: bool = True)`; из `bindings._ensure` звать `sync=False` —
  отправка `send()` без ожидания ответа, ошибка сервера ловится логом (warning), sub_id локальный.
  2. Replay при этом приедет асинхронно штатным путём дельт — виджеты обновятся через bindings.
**Acceptance:**
- [x] Ни одного `router.request` из Qt main thread на пути `bind()` (тест с мок-router, assert по потоку) — `TestAsyncSubscribe::test_ensure_new_subscription_uses_only_send_async` (request_calls==[], send_calls==[], только send_async) + `test_subscribe_sync_false_uses_send_async`; sync=True сохранён (`test_subscribe_sync_true_still_uses_request`)
**Out of scope:** переделка `router.request` как такового.

#### Task 0.3 — Реплей по префиксу паттерна, не всё дерево
**Level:** Middle+ (Sonnet) · **Assignee:** developer
**Goal:** `_replay_initial_state` копирует только поддерево статического префикса паттерна.
**Files:** `state_store_module/manager/state_store_manager.py:395-433`, tests.
**Steps:** 1. Выделить статический префикс паттерна до первого wildcard-сегмента
  (`processes.cam.state.fps` → сам путь; `processes.**` → `processes`). 2. `get_subtree(prefix)` вместо `""`.
**Acceptance:**
- [x] Реплей эквивалентен прежнему по содержимому (характеризационный тест на матчи) — `TestSubscribe::test_replay_by_prefix_equivalent_to_full_tree` (узкий + wildcard + `**`, эталон = старый get_subtree('')+iter_matches)
- [x] Тест: подписка на узкий паттерн не вызывает копию корня (spy на `get_subtree`) — `test_replay_narrow_pattern_does_not_copy_root` (get_subtree('') не вызывается) + `test_replay_wildcard_copies_prefix_not_root` (только get_subtree('processes'))
**Out of scope:** формат Delta, dispatcher.

#### Task 0.4 — Дебаунс каскада runtime-воркеров
**Level:** Middle (Sonnet) · **Assignee:** developer
**Goal:** N обнаружений воркеров → 1 перестроение таблицы.
**Files:** `multiprocess_prototype/frontend/widgets/tabs/processes/_panels.py`
  (`_on_worker_discovered`/`_refresh_workers`), tests (pytest-qt).
**Steps:** 1. `_on_worker_discovered` только копит имя и взводит `QTimer.singleShot(50, ...)`
  (coalescing-флагом). 2. Однократный `_refresh_workers` по срабатыванию.
**Acceptance:**
- [x] Тест: 5 обнаружений подряд → 1 вызов `set_workers` — `test_worker_debounce.py::test_five_discoveries_coalesce_into_one_refresh` (+ `test_duplicate_discovery_does_not_reschedule`, `test_flush_skips_when_panel_marked_destroyed`)
- [x] Qt-smoke: proto + qt_snapshot, вкладка живая (правило feedback_qt_mcp_smoke_verification) — dualcam_synth (4 синт-процесса), probe :9142: ProcessesTab собрана и отзывчива (фриза нет), в стеке РОВНО 1 панель (AllProcessesPanel — ленивость подтверждена, не 5+), консоль без ошибок/трейсбеков
**Verification Фазы 0 (整):** запуск `webcam_sketch`, открытие вкладки «Процессы» — без фриза
  (замер лог-таймстампом); `INSPECTOR_STALL_DUMP=1` — нет срезов >1 с в момент открытия.

> Хвост 0.4 (2026-07-16): в нативном Windows-запуске владельца открытие вкладки ~30с. Инструментирование
> (INSPECTOR_TAB_TRACE) показало: Python-конструктор вкладки быстрый, стойло в Qt C++ (show/layout/paint)
> при глубокой вложенности (панель×N процессов × QTableWidget×3 + QSS). Фикс: ленивое создание
> SingleProcessPanel (только активная панель при открытии) — реализовано в 0.4 через opt-in
> `lazy_content` в `BaseListNavTab` (тесты `test_lazy_panels.py`: `test_open_creates_only_active_panel`,
> `test_switching_between_two_processes_creates_both`, `test_lazily_created_panel_shows_live_state`).
> Первый показ строит 1 панель вместо N. Верификация на нативном Windows — за владельцем.

> **Угловое ревью Фазы 0 закрыто (2026-07-16, teamlead):** (1) покрывающими считаются только
> ПОДТВЕРЖДЁННЫЕ серверные подписки (`_confirmed_patterns` заполняется в `subscribe()` при валидном
> серверном sub_id; неподтверждённый широкий паттерн не «усыновляет» узкий → fallback на async-subscribe,
> закрывает риск «мёртвого виджета» из таблицы Риски); (2) доставка покрытому паттерну доказана на РЕАЛЬНОМ
> GUI-пути `GuiStateProxy(delta_sink)`→bridge→`GuiStateBindings` (тест `TestGuiDeliveryPathIntegration`),
> комментарии в `state_proxy.py` уточнены (базовый proxy — `_invoke_callbacks`, GUI — delta_sink);
> (3) async-подписки наблюдаемы (счётчик `_async_subscribe_count` + метрика `state_proxy.async_subscribe` +
> INFO-лог с маркером `[async-subscribe]`).

### Фаза 1 — TelemetryViewModel: локальный read-model

#### Task 1.1 — TelemetryViewModel (владелец «снимок→виджет»)
**Level:** Senior (Opus) · **Assignee:** teamlead
**Goal:** один объект в GUI: текущие значения телеметрии + батч-сигнал обновления; питается существующим
  wildcard-потоком (delta_sink), поглощает роль `cache_snapshot`-replay.
**Files:** новый `multiprocess_prototype/frontend/state/telemetry_view_model.py`, wiring в `app.py`, tests.
**Steps:** 1. Модель: `dict[path, value]` + `updated(list[tuple[path, value]])` Qt-сигнал (батч на пачку дельт).
  2. Подключить вторым потребителем `bridge.add_state_listener` (рядом с bindings, §11.15).
  3. API чтения: `get(path)`, `snapshot(prefix)` — для открытия вкладок без ожидания дельт.
**Acceptance:**
- [x] Вкладка, созданная после публикации, видит значения сразу (тест late-binding) — `test_telemetry_view_model.py::test_snapshot_available_immediately_after_delta` (+ `test_initial_cache_primes_snapshot`, `test_updated_emitted_once_per_packet`, `test_deleted_removes_path_and_batches_none`)
- [x] Ни одной серверной подписки из view-model (стартовые wildcard'ы — единственный источник) — `test_view_model_creates_no_server_subscriptions` (VM не держит router/proxy/subscribe); wiring в `app.py` вторым `add_state_listener`

#### Task 1.2 — Кольцевые буферы для мгновенных графиков
**Level:** Middle+ (Sonnet) · **Assignee:** developer
**Goal:** последние ~10 мин ключевых метрик (fps/latency/hz) в памяти GUI для спарклайнов без похода в БД.
**Files:** `telemetry_view_model.py` (ring buffer per отслеживаемый путь, конфиг: длительность/набор префиксов), tests.
**Acceptance:**
- [x] Fixed-size deque, O(1) append; выборка диапазона для графика — `test_history_ring_buffer_evicts_oldest` (maxlen-вытеснение), `test_history_since_filters_range`, `test_history_records_tracked_numeric_only` (суффиксы `.state.fps`/`.latency_ms`/`.uptime`/`.effective_hz`/`.cycle_duration_ms`)

#### Task 1.3 — Перевод панелей «Процессов» на view-model
**Level:** Senior (Opus) · **Assignee:** teamlead
**Goal:** `_panels.py` (карточки, health, WorkerTable) читают view-model; `bindings.bind(glob)` на телеметрию
  процессов из панелей уходит.
**Files:** `processes/_panels.py`, `processes/tab.py`, tests.
**Steps:** 1. Подписка панели: один слот на `updated`, фильтрация по своим путям (как `matches_live`
  в Наблюдаемости). 2. Первичное наполнение из `snapshot()`. 3. Обнаружение runtime-воркеров — из тех же батчей.
**Acceptance:**
- [x] Открытие вкладки: 0 `state.subscribe`, 0 блокирующих IPC (инвариант-тест) — `test_telemetry_vm_panels.py::TestNoServerSubscriptionsInVmMode` (`test_all_panel_vm_makes_no_bind_calls`, `test_single_panel_vm_makes_no_bind_calls`, `test_tab_open_and_select_makes_no_bind_calls` — мок-bindings, 0 bind/bind_fanout/ensure_subscription из панелей в VM-режиме)
- [ ] Live-обновления карточек/воркеров работают (qt-smoke по правилу — прогонит Director) · pytest-покрытие: `TestLiveUpdateViaVm` (карточки/health/trace-fanout/воркеры через батч + первичное наполнение из snapshot late-binding), `TestFallbackWithoutVm` (telemetry=None → прежний bind-путь)
**Out of scope:** остальные вкладки (devices/calibration) — мигрируют по мере надобности этим же паттерном.

### Фаза 2 — История и графики (pull из telemetry_sink)

#### Task 2.1 — Read-сторона telemetry.db
**Level:** Middle+ (Sonnet) · **Assignee:** developer
**Goal:** страничный/диапазонный доступ к `telemetry_snapshots` для GUI (паттерн RecordSource Наблюдаемости).
**Files:** новый `TelemetryHistorySource` (рядом с observability/record_source-паттерном),
  чтение SQLite read-only (`data/telemetry.db`), tests.
**Steps:** 1. `list_range(process_name, ts_from, ts_to, metrics, max_points)` c даунсемплом до max_points.
  2. Read-only подключение (`mode=ro`), отказоустойчиво к отсутствию файла.
**Acceptance:**
- [x] Диапазонная выборка с даунсемплом; отсутствие БД → пустой результат, не исключение —
  `test_telemetry_history.py::TestListRangeDownsample` (`test_downsamples_to_at_most_max_points`,
  `test_no_downsample_when_under_max_points`, `test_filters_by_process_name_and_ts_bounds`,
  `test_record_shape_is_dict_with_ts_and_requested_metrics`) + `TestMissingDbIsFaultTolerant`
  (`test_missing_file_returns_empty_list`, `test_missing_table_returns_empty_list`,
  `test_empty_range_returns_empty_list`) + `TestMetricsWhitelist`
  (`test_unknown_metric_is_ignored_known_still_returned` — попытка SQL-инъекции через имя метрики,
  `test_all_metrics_unknown_returns_empty_without_query`, `test_allowed_metrics_matches_telemetry_snapshot_columns`)
  + `TestResolveTelemetryDbPath` (`test_default_path`, `test_env_override` — путь к БД изолирован в
  `resolve_telemetry_db_path()`, env `INSPECTOR_TELEMETRY_DB`)

#### Task 2.2 — Графики в SingleProcessPanel
**Level:** Middle+ (Sonnet) · **Assignee:** developer
**Goal:** график fps/latency процесса: последние минуты — из ring buffer (Task 1.2), глубже — из Task 2.1.
**Files:** `processes/_panels.py` (+ мини-виджет графика), tests.
**Acceptance:**
- [x] Открытие графика не блокирует main thread (чтение БД — в воркере/по таймеру) —
  `test_history_graph.py::TestDeeperRangeReadsHistorySourceOffMainThread::test_history_source_called_off_main_thread`
  (сравнение `threading.get_ident()` вызова `list_range` с main-thread) — читает через `RequestRunner`
  (QThreadPool, тот же приём, что command-result-bridge P2), не новый механизм
- [x] Переключение диапазона (10 мин / час / день) — `TestTenMinuteRangeUsesRingBuffer`
  (10м → ring-буфер VM, `history_source.list_range` НЕ вызывается) +
  `TestDeeperRangeReadsHistorySourceOffMainThread` (`test_switch_to_1h_calls_history_source`,
  `test_1d_range_requests_86400s_window`, `test_history_result_applied_to_sparklines_in_main_thread`,
  `test_switching_back_to_10m_does_not_call_history_source_again`) + `TestGracefulDegradation`
  (VM=None / пустая БД → спарклайн без данных, без падений)

### Фаза 3 — Cleanup + enforcement + docs

#### Task 3.1 — Вырезать дублирующий механизм
**Level:** Senior (Opus) · **Assignee:** teamlead
**Goal:** после миграции панелей: убрать `ensure_subscription` из `bind()`-пути телеметрии, убрать
  `cache_snapshot`-replay из `GuiStateBindings` (роль у view-model), снять мёртвые точечные подписки.
**Acceptance:**
- [ ] Нет вызовов `ensure_subscription` из `bind()` для путей, покрытых wildcard (координация с Task 0.1)
- [ ] Тест-инвариант в CI: открытие каждой вкладки → счётчик `state.subscribe` == 0

#### Task 3.2 — ADR + память + статусы планов
**Level:** Middle (Sonnet) · **Assignee:** tech-writer
**Goal:** зафиксировать инвариант и закрыть хвосты знаний.
**Steps:** 1. Глобальный ADR «GUI read-model: запись всегда, чтение локально, история по запросу»
  (`multiprocess_framework/DECISIONS.md` + `python -m scripts.sync`). 2. Обновить memory
  `project_webcam_sketch_freeze` (диагноз «Python ни при чём» опровергнут: блокирующий IPC в main thread).
  3. `telemetry-delivery-simplification.md` → SUPERSEDED (ссылка сюда). 4. Dual-write memory.
**Acceptance:**
- [ ] ADR в индексе; memory обновлена в обоих местах; статусы планов согласованы

---

## Что сознательно НЕ делаем

- **Snapshot-канал вместо дельт (полный Option D, бэкенд-часть)** — отложено ещё раз: после Фаз 0–1 двойной
  glob-матчинг перестаёт быть болью (подписок мало, биндинги локальные). Реанимировать, если замер покажет
  боль на масштабе (20 проц × 50 метрик). Текущий план даёт read-model поверх работающего потока — меньший риск.
- Live-чтение из SQLite; изменение серверной публикации/троттлинга; миграция вкладок вне «Процессов».

## Follow-up: telemetry-publish-control (отдельный план, ПОСЛЕ этого — решение владельца 2026-07-16)

Замысел владельца: управлять **публикующей** стороной телеметрии — задавать частоту опроса per-параметр/
группу и вкл/выкл, через statistics manager, чтобы не грузить систему. Комплементарно этому плану
(тот — про дешёвое GUI-**чтение**; follow-up — про «публиковать ровно сколько надо»). Кирпичи уже есть:
- per-паттерн троттл `backend/state/manager_setup.py:build_throttle_rules()` (сейчас **хардкод** `{glob → min_interval}`) → сделать **config-driven** (рецепт/секция);
- observability control-plane (секция `observability` + hot-reload watcher + `reconfigure()` + IPC `config.reload`) — готовый канал рантайм-изменений ([[project_observability_control_plane]]);
- `ObservableMixin` per-slot тумблеры (`enable/disable/context`) — есть, но **не проброшены** в hot-reload-конфиг (пробел из layer-grouping Инициатива 2 п.3);
- fan-out конфига на дочерние процессы — пробел (layer-grouping 2C).
Не хватает: троттл из конфига, вкл/выкл публикации метрики/группы, рантайм-крутилки через stats manager + fan-out.
Оформить как `plans/telemetry-publish-control.md` после закрытия этого плана.

## Риски

| Риск | Митигация |
|------|-----------|
| Coverage-check ломает случай «wildcard ещё не подтверждён сервером» | Считать покрывающими только подтверждённые подписки; иначе fallback на async-subscribe (Task 0.2) |
| Async-subscribe теряет отказ сервера | Warning-лог + счётчик в статистику; replay приедет потоком — виджет не «мёртв», а пуст |
| Два потребителя state-потока (bindings + view-model) на переходный период | Штатный multi-subscriber (§11.15); после Фазы 3 телеметрию читает только view-model |
| Конфликт с codemod layer-grouping | Не выполнять параллельно; порядок фиксирован в шапке |
| telemetry_sink переезжает в stdlib/ (layer-grouping 2D) | Task 2.1 изолирует путь к БД в одном месте (конфиг), переезд кода истории не трогает |

## Verification (весь план)

1. Инвариант-тест: открытие каждой вкладки → 0 `state.subscribe`, 0 `router.request` из main thread.
2. Открытие «Процессов» на `webcam_sketch` < 300 мс (замер логом), stall-dump чистый.
3. Live-телеметрия карточек/воркеров живая (qt-smoke: proto + `QT_MCP_PROBE=1` + qt_snapshot).
4. График процесса строится за историю (telemetry_sink включён в рецепт) и за последние минуты (ring).
5. `python scripts/run_framework_tests.py` + тесты прототипа зелёные; sentrux не хуже baseline.
