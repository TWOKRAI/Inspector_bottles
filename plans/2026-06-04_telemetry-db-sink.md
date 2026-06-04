# Plan: БД-сток истории телеметрии (sql_module) + миграция DatabasePlugin

- **Slug:** telemetry-db-sink
- **Дата:** 2026-06-04
- **Статус:** DRAFT
- **Ветка:** `feat/comm-system-target-architecture` (продолжение телеметрии, НЕ новый branch)
- **Родитель:** [`telemetry-self-publish-redesign.md`](telemetry-self-publish-redesign.md) (раздел «Осталось: БД-сток истории»), memory `project_telemetry_self_publish`
- **Связанные:** [`telemetry-delivery-simplification.md`](telemetry-delivery-simplification.md) (вариант D — fallback при провале спайка)

## Обзор

Две независимые цели на базе `Services/sql` (`SQLManager`):

1. **Телеметрия-sink** — отдельный лёгкий процесс-сток в прототипе, который **подписывается** на дерево StateStore (`processes.**` / `system.**`) через **тот же** IPC-механизм `state.subscribe`, что и GUI, **семплирует** снимок раз в N секунд (не каждую дельту) и **батчево** пишет историю в БД через `SQLManager`. I/O изолирован в своём процессе — не подвешивает `ProcessMonitor`, framework НЕ трогаем.
2. **Миграция `Plugins/io/database`** — заменить сырой `sqlite3.Connection` на `SQLManager`, перевести таблицу `detections` на `SchemaBase` + `SQLMeta` (auto-DDL), сохранить публичный контракт плагина (команды `flush`/`get_stats`/`set_batch_size`/`reset_stats`, batch-буфер, flush-worker).

Слои: `prototype → Services` и `Plugins → Services` разрешены (`.sentrux/rules.toml`). Framework и `ProcessMonitor` остаются без изменений.

> **ВАЖНО — путь импорта (уточнено 2026-06-04).** Каноническая реализация — **`Services/sql`**, импортируется как **`from Services.sql import SQLManager, SQLManagerConfig`** (`pythonpath=["."]` в pyproject делает `Services.sql` импортируемым; так импортируют тесты `Services/sql/tests/`). README в `Services/sql` показывает `from sql_module import ...` — **устаревший, НЕ использовать**. Каталог `multiprocess_framework/modules/sql_module/` — **мёртвый leftover** Phase 4 carve-out: НЕ в git, без `__init__.py`, неимпортируемый (только осиротевшие подпапки + `__pycache__`). Его игнорировать; опционально удалить отдельным cleanup-коммитом (вне scope этого плана).

## Итог разведки — главный риск СНЯТ по коду (но требует runtime-proof)

**Развилка «может ли backend-процесс (не GUI) подписаться на дерево StateStore»** разрешается уже на уровне кода:

- `StateProxy.subscribe(pattern, callback, exclude_self)` (`multiprocess_framework/modules/state_store_module/proxy/state_proxy.py:218`) — **generic**, не GUI-специфичен. GUI-специфика только в `GuiStateProxy` (Qt-маршалинг через `delta_sink`).
- Каждый backend-процесс прототипа уже создаёт `StateProxy` с `server_target="ProcessManager"` и регистрирует `state.changed` handler — `multiprocess_prototype/generic_process_app.py:23` (`GenericProcessApp._init_custom_managers`). Плагин получает его через `ctx.state_proxy` (`process_module/plugins/base.py:97`).
- **Initial-replay на subscribe подтверждён:** `StateStoreManager.handle_state_subscribe` → `_replay_initial_state` (`manager/state_store_manager.py:314-349`) адресно шлёт новому подписчику снимок текущих листьев (коммит 16e14084). Значит sink на старте сразу получит актуальное дерево, а не только будущие дельты.
- `GuiProcess` уже делает ровно это для `processes.**`/`system.**` (`frontend/process.py:76,80`) с пустым callback — рабочий прецедент.

**Вывод:** sink реализуется как **обычный плагин в обычном `GenericProcessApp`-процессе** — без нового framework-кода, без правки `ProcessMonitor`, без нового IPC-канала. Спайк (Task 0.1) — лёгкий **runtime-proof** этой гипотезы (а не исследование): временно подписать существующий backend-процесс и убедиться, что дельты `processes.**` реально доходят. Fallback (вариант D — `ProcessMonitor` публикует snapshot в data-канал, правка framework) в план заложен как явная ветка ТОЛЬКО если proof провалится.

## Ключевые design-решения (зафиксированы)

### (а) Схема `TelemetrySnapshot` — WIDE, рекомендуется
**Рекомендация: wide-таблица** (одна строка = один снимок одного процесса в момент `ts`), НЕ narrow/EAV. Причины: метрики фиксированы и немногочисленны (fps/latency/uptime/active), wide проще для аналитики/экспорта (`TableExporter` уже есть в sql_module), EAV избыточен без динамических ключей.

```
TelemetrySnapshot (SchemaBase + SQLMeta):
  id:           Optional[int] = None            # PK autoincrement
  ts:           float                           # время снимка (time.time())
  process_name: str                             # 'camera_0', 'system' для сводки
  fps:          float | None                    # processes.{p}.state.fps (max по воркерам)
  latency_ms:   float | None                    # processes.{p}.state.latency_ms
  uptime_s:     float | None                    # processes.{p}.state.uptime
  status:       str | None                      # processes.{p}.state.status ('running'/...)
  # Сводка system.* пишется отдельной строкой process_name='system':
  #   fps←system.health.avg_fps, плюс доп. поля в data-JSON (см. ниже)
  extra:        str | None = None               # JSON-«хвост» нестандартных полей (broken_wires, active и т.п.)
  SQLMeta:
    table_name = "telemetry_snapshots"
    indexes = [("ts",), ("process_name", "ts")]
```
Точный список листьев дерева уточнить при реализации (Task 1.1) по факту replay-снимка: брать листья `processes.*.state.*` и `system.health.*`. Нестандартные ключи — в `extra` (JSON), чтобы схема не ломалась при добавлении метрик.

### (б) Период семпла
`sample_interval_sec` — **по умолчанию 5.0 с**, конфигурируемо через register плагина (FieldMeta, min=0.5). Семпл = снимок текущего кэша подписки по таймеру (loop-worker), НЕ запись на каждую дельту. Батч накапливается между записями в БД (`db_flush_interval_sec`, по умолчанию = sample_interval — пишем сразу после каждого семпла, буфер мелкий).

### (в) Ретенция/ротация
**Сейчас — TODO, не реализуем** (явный scope-cut). Заложить параметр `retention_days` в register (default 0 = без ретенции) и команду-заглушку `purge_old` с TODO. Полноценную ротацию — отдельным `/plan` после подтверждения роста БД на проде. Риск роста зафиксирован в разделе «Риски».

### (г) Fork-safety SQLManager в дочернем процессе — КРИТИЧНО
- `SQLManager(config, managers, process)` создаётся и `initialize()` вызывается **ВНУТРИ дочернего процесса** (в `start()` плагина после fork), НЕ в родителе и НЕ в `configure()` родительского контекста.
- `SQLManagerConfig(fork_safe=True)` ИЛИ env `INSPECTOR_MULTIPROCESS=1` → NullPool (см. `async_adapter.py:32`, sync аналогично). Для sink задать `fork_safe=True` явно в конфиге — не полагаться на env.
- Для SQLite: `connect_args={"check_same_thread": False}` (sample-worker и subscribe-callback — разные потоки внутри процесса).
- Async (`uow_async`) — адаптер ленивый, создаётся при первом вызове в потоке sample-worker. **Решение по async:** для sink использовать **sync** `SQLManager` + `insert_many` через repo (проще, без event-loop в loop-worker; БД-I/O уже изолирован в отдельном процессе, async не даёт выигрыша). Async оставить как возможность, не требование. Это снимает риск «event loop внутри loop-worker».

## Vertical slice (tracer bullet)

**Task 1.1 — обязательный vertical slice.** Sink-процесс проходит через все слои фичи №1: подписка на дерево (StateStore) → семпл-таймер (worker) → запись через `SQLManager` (Services/sql) → объявление процесса в топологии. После 1.1 можно headless-запустить систему и увидеть **реальные строки** в `telemetry_snapshots`. Углубление (полный набор метрик, system-сводка, batch, команды) — в 1.2+.

Фича №2 (миграция плагина) — рефактор в одном слое (Plugins), vertical slice не нужен; атомарные задачи Phase 2.

## Порядок выполнения

### Phase 0: Спайк-развилка (главный риск)

- **Task 0.1:** Runtime-proof backend-подписки на `processes.**` [DONE 2026-06-04] ✅ proof успешен — ОСНОВНОЙ путь подтверждён
  - **Module contract:** n/a

### Phase 1: Телеметрия-sink (DatabaseProcess на sql_module)

- **Task 1.1: [VERTICAL SLICE]** Минимальный sink E2E: плагин подписывается → семплит → пишет одну метрику в БД через SQLManager → объявлен в топологии [DONE 2026-06-04] ✅ headless-smoke зелёный (rows>0, неск. ts)
  - **Module contract:** new-lite
  - **Сопутствующие framework-фиксы (вскрыты smoke'ом, write-путь плагинов):**
    `with_config` не пробрасывал `state_proxy`; `handle_state_merge` двойной unwrap (коллизия ключа `data`); `command_manager` логировал `reason` вместо `error`; `register_schema` терял подтип (TypeVar). Детали — `Plugins/io/telemetry_sink/STATUS.md`.
- **Task 1.2:** Полная схема `TelemetrySnapshot` + сбор всех листьев `processes.*.state.*` + сводка `system.*` [DONE 2026-06-04] ✅ smoke: per-process строки + system, extra JSON
  - **Module contract:** impl-only
- **Task 1.3:** Конфиг-параметры (sample_interval, retention) + команды (`flush`/`get_stats`/`purge_old`) [DONE 2026-06-04] ✅ purge_old — реальный on-demand DELETE (не заглушка), scheduled-ротация вне scope
  - **Module contract:** impl-only

### Phase 2: Миграция DatabasePlugin (sqlite3 → SQLManager)

- **Task 2.1:** `DetectionSchema` (SchemaBase + SQLMeta) + замена raw sqlite3 на SQLManager (auto-DDL, insert_many), сохранить контракт плагина [PENDING] (зависит от 0.1 — fork-safety паттерн общий)
  - **Module contract:** impl-only
- **Task 2.2:** Обновить команды и тесты плагина под SQLManager [PENDING] (зависит от 2.1)
  - **Module contract:** impl-only

### Phase 3: Тесты + приёмка

- **Task 3.1:** pytest: sink-агрегация/семпл/схема/fork-safety + плагин через SQLManager [PENDING] (зависит от 1.2, 1.3, 2.2)
  - **Module contract:** n/a
- **Task 3.2:** Headless/qt-mcp приёмка реальной записи в БД (query таблиц) [PENDING] (зависит от 3.1)
  - **Module contract:** n/a

---

## Phase 0 — Спайк-развилка

### Task 0.1 — Runtime-proof: backend-процесс получает дельты `processes.**`

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Доказать на живом запуске, что backend-процесс (не GUI) через `StateProxy.subscribe("processes.**", ...)` реально получает дельты телеметрии (включая initial-replay) — или зафиксировать провал и активировать fallback-ветку.
**Context:** Это единственная развилка плана. По коду гипотеза подтверждена (см. «Итог разведки»), но self-publish метрик доезжал не всегда (см. родительский план) — нужен runtime-факт ДО реализации sink.
**Files:**
- `multiprocess_prototype/generic_process_app.py` — временно (в спайк-ветке мысленно/локально) добавить в существующий backend-процесс пробную подписку с логированием числа дельт; НЕ коммитить как продакшн.
- (только чтение) `multiprocess_framework/modules/state_store_module/manager/state_store_manager.py:285-349` — `handle_state_subscribe` + `_replay_initial_state`.

**Steps:**
1. В существующем backend-процессе (`GenericProcessApp`) временно подписаться: `self._state_proxy.subscribe("processes.**", lambda d: self._log_info(f"[SPIKE] got {len(d)} deltas"), exclude_self=True)` сразу после `initialize()`.
2. Headless-запуск системы (`inspection_basic` или demo-pipeline с включённым self-publish метрик). Убедиться, что `ProcessMonitor`/self-publisher реально пишет `processes.*.state.*` (см. родительский план — это уже работает для статуса; для fps проверить отдельно).
3. В логах процесса найти `[SPIKE] got N deltas` с N>0, в т.ч. **сразу после subscribe** (initial-replay) и при последующих изменениях.
4. Зафиксировать: какие именно листья приходят (`state.status`, `state.fps`, `state.latency_ms`, `state.uptime`, `system.health.*`) — это вход для схемы Task 1.2.

**Acceptance criteria:**
- [x] В логах backend-процесса виден `[SPIKE] got N deltas` с N>0 после subscribe (initial-replay сработал)
- [x] При работе системы приходят последующие дельты `processes.*.state.*` (не только статус)
- [x] Задокументирован фактический список приходящих листьев (для Task 1.2)
- [x] Вынесено решение: ОСНОВНОЙ путь (плагин-sink с subscribe) подтверждён ИЛИ активирован FALLBACK

**РЕЗУЛЬТАТ ПРОБЫ (2026-06-04, runtime-proof — НЕ закоммичен, spike откатан):**
- Метод: временная подписка `processes.**`+`system.**` в `GenericProcessApp._init_custom_managers` + headless-запуск `region_pipeline` (7 backend-процессов, БЕЗ GUI, через `SystemBuilder.from_topology_path` — не мёржит base) на 20 с.
- **Initial-replay подтверждён:** сразу после `subscribe` каждый процесс получил снимок дерева (stitcher: 85 дельт config+state в первый тик), далее устойчивый поток (всего ~3748 delta-событий за 20 с по 7 процессам).
- **`exclude_self=True` работает:** процесс видит телеметрию ВСЕХ других процессов (напр. stitcher получает `processes.camera_0.state.fps`, `processes.preprocessor.state.latency_ms` и т.д.).
- **fps/latency реально доезжают** (баг self-publish из родительского плана закрыт): `state.fps=21.4`, `state.latency_ms=1.2`, `system.health.avg_fps=29.26`.

**Фактический список приходящих листьев (вход для схемы Task 1.2):**
- `processes.<P>.state.{fps, latency_ms, uptime, status}` — основные метрики процесса
- `processes.<P>.workers.<w>.{effective_hz, cycle_duration_ms, status}` — пер-воркер (хвост → `extra` JSON)
- `processes.<P>.config.{plugins, chain_targets, priority}` — конфиг (НЕ телеметрия, фильтровать в семпле)
- `system.health.{avg_fps, active, broken_wires}` — сводка (строка `process_name='system'`)
- `system.{stop_timeout, shm_budget_mb, log_dir}` — статичный конфиг (фильтровать)

**ВЫВОД:** ОСНОВНОЙ путь (плагин-sink с `StateProxy.subscribe`, обычный `GenericProcessApp`-процесс, без правок framework) подтверждён на живом запуске. FALLBACK (вариант D) НЕ требуется. Phase 1 разблокирована.

**Out of scope:** реализация самого sink; любые правки framework; коммит пробной подписки в прод.
**Edge cases:** дельты приходят, но `state.fps` всегда None/0 (self-publish метрик не доезжает) → это НЕ блокер для sink-механики (sink пишет что есть), но зафиксировать как known-gap; replay приходит пустым (дерево ещё не заполнено на момент subscribe) → проверить, что подписка живёт и ловит последующие дельты.
**FALLBACK (если proof провален):** перейти на вариант D из `telemetry-delivery-simplification.md` — `ProcessMonitor` публикует периодический snapshot в data-канал, sink читает канал, а не дерево. Это правка framework (менее предпочтительно) → требует отдельного согласования с владельцем ПЕРЕД продолжением Phase 1.
**Dependencies:** —
**Module contract:** n/a

---

## Phase 1 — Телеметрия-sink

### Task 1.1 — [VERTICAL SLICE] Минимальный sink E2E

**Level:** Senior (Opus, extended thinking)
**Assignee:** teamlead
**Goal:** Создать плагин-сток `TelemetrySinkPlugin` (в `Plugins/`), который в backend-процессе подписывается на `processes.**`, по таймеру семплит кэш и пишет минимум одну метрику в `telemetry_snapshots` через `SQLManager`; объявить sink-процесс в топологии. После задачи headless-запуск даёт реальные строки в БД.
**Context:** Tracer bullet через все слои фичи №1 (StateStore-подписка → worker-таймер → Services/sql → топология). Даёт feedback loop сразу. Архитектура: sink — НЕ source-плагин потока кадров, а side-effect плагин (нет inputs/outputs), живёт в `GenericProcessApp`-процессе, использует `ctx.state_proxy` и `ctx.worker_manager` (как `DatabasePlugin` использует `db_flush_worker`).
**Files:**
- `Plugins/io/telemetry_sink/__init__.py` — создать (public-export плагина)
- `Plugins/io/telemetry_sink/plugin.py` — создать `TelemetrySinkPlugin(ProcessModulePlugin)`
- `Plugins/io/telemetry_sink/registers.py` — создать `TelemetrySinkRegisters` (db_path, sample_interval_sec)
- `Plugins/io/telemetry_sink/config.py` — создать `TelemetrySinkPluginConfig` (identity + register binding)
- `Plugins/io/telemetry_sink/schemas.py` — создать `TelemetrySnapshot` (SchemaBase + SQLMeta) — минимальный вариант (ts, process_name, fps)
- `Plugins/io/telemetry_sink/README.md`, `STATUS.md` — создать (правило проекта: у модуля README+STATUS)
- `multiprocess_prototype/backend/topology/inspection_basic.yaml` (или новый `telemetry_sink.yaml` pipeline) — объявить процесс `telemetry_sink` (`process_class: multiprocess_prototype.generic_process_app.GenericProcessApp`, plugins: [telemetry_sink])

**Steps:**
1. `TelemetrySnapshot(SchemaBase)` с `SQLMeta.table_name="telemetry_snapshots"`, поля минимум: `id`, `ts: float`, `process_name: str`, `fps: float | None`.
2. `TelemetrySinkPlugin.configure(ctx)`: инициализировать register, буфер `list[dict]`, lock; СОХРАНИТЬ `ctx` (для `state_proxy`/`worker_manager`/`log_*`). НЕ создавать SQLManager здесь (fork!).
3. `start(ctx)`: создать `SQLManager(config=SQLManagerConfig(url=f"sqlite:///{db_path}", dialect="sqlite", fork_safe=True, connect_args={"check_same_thread": False}), managers={"logger": ...}, process=...)`, `initialize()`, `create_tables([TelemetrySnapshot])`. Затем `ctx.state_proxy.subscribe("processes.**", self._on_deltas, exclude_self=True)` — callback только кладёт листья в `self._cache: dict[path,value]`. Создать loop-worker `telemetry_sample_worker` (`ThreadConfig(execution_mode=ExecutionMode.LOOP)`, как у `DatabasePlugin._flush_loop`) с `sample_interval_sec`.
4. `_sample_loop`: раз в N секунд снять из `self._cache` минимум одну метрику (например любой `processes.*.state.fps`) → собрать `TelemetrySnapshot(ts=time.time(), process_name=..., fps=...)` → `repo.insert_many([...])` (sync).
5. `shutdown(ctx)`: финальный семпл/flush, `sql_manager.shutdown()`, unsubscribe (proxy.shutdown делает процесс).
6. Объявить процесс в топологии; убедиться, что плагин обнаруживается `PluginRegistry.discover` (путь в `discovery.plugin_paths` — проверить, что `Plugins/` уже сканируется).

**Acceptance criteria:**
- [ ] `make check` (ruff+pyright) проходит на новом пакете
- [ ] Плагин регистрируется (`@register_plugin("telemetry_sink", ...)`) и обнаруживается discover
- [ ] Headless-запуск: таблица `telemetry_snapshots` создаётся auto-DDL и получает ≥1 строку за время работы (query: `SELECT count(*) FROM telemetry_snapshots > 0`)
- [ ] SQLManager создаётся ВНУТРИ процесса в `start()` с `fork_safe=True` (визуально в коде + нет ошибок пула при запуске)
- [ ] sentrux `check_rules`: нет нарушения слоёв (Plugins→Services OK, нет Plugins→prototype)

**Out of scope:** полный набор метрик и system-сводка (Task 1.2); команды и retention (Task 1.3); async-запись; миграция detections-плагина.
**Edge cases:** `ctx.state_proxy is None` (процесс без proxy) → плагин логирует error и работает как no-op, не падает; кэш пуст на момент первого семпла → не писать пустую строку.
**Dependencies:** Task 0.1 (подтверждённый путь подписки)
**Module contract:** new-lite

### Task 1.2 — Полная схема и сбор всех метрик + system-сводка

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Расширить `TelemetrySnapshot` до полного набора (fps/latency_ms/uptime_s/status/extra) и собирать на каждом семпле снимок по ВСЕМ процессам (`processes.*.state.*`) + отдельную строку-сводку `process_name='system'` из `system.health.*`.
**Context:** Углубление слайса. Список листьев — из факта Task 0.1.
**Files:**
- `Plugins/io/telemetry_sink/schemas.py` — расширить `TelemetrySnapshot`
- `Plugins/io/telemetry_sink/plugin.py` — логика агрегации кэша в строки

**Steps:**
1. Добавить поля `latency_ms`, `uptime_s`, `status`, `extra: str | None` (JSON-хвост) + `SQLMeta.indexes=[("ts",),("process_name","ts")]`.
2. В `_sample_loop` сгруппировать кэш по `processes.<name>.state.<metric>` → одна строка `TelemetrySnapshot` на процесс.
3. Отдельная строка `process_name='system'`: `fps←system.health.avg_fps`, остальное (broken_wires, active) — в `extra` JSON.
4. `insert_many` всем пакетом за один семпл (транзакция).

**Acceptance criteria:**
- [ ] За один семпл создаётся по строке на каждый активный процесс + строка `system`
- [ ] Нестандартные листья не ломают запись (уходят в `extra` JSON)
- [ ] pyright/ruff чисто

**Out of scope:** команды/retention (1.3); ротация.
**Edge cases:** процесс с частичными метриками (есть status, нет fps) → пишем что есть, остальное None; метрика, которой нет в схеме → в `extra`.
**Dependencies:** Task 1.1, факт-список из 0.1
**Module contract:** impl-only

### Task 1.3 — Конфиг + команды + retention-заглушка

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Вынести параметры в register (sample_interval_sec, db_path, batch, retention_days=0) и добавить команды `flush`, `get_stats`, `purge_old` (заглушка с TODO).
**Files:**
- `Plugins/io/telemetry_sink/registers.py`, `plugin.py`

**Steps:**
1. Register: `sample_interval_sec` (FieldMeta unit="s", min=0.5, default=5.0), `db_path` (default "data/telemetry.db"), `retention_days` (default 0).
2. Команды по образцу `DatabasePlugin`: `_cmd_flush` (форс-семпл+запись), `_cmd_get_stats` (total_written, pending, db_path, last_ts), `_cmd_purge_old` (если retention_days>0 — DELETE WHERE ts<cutoff; иначе no-op + TODO-лог).
3. `commands = {...}` в классе плагина.

**Acceptance criteria:**
- [ ] Команды зарегистрированы и возвращают `{"status":"ok",...}`
- [ ] `purge_old` при retention_days=0 — no-op (TODO зафиксирован комментарием)
- [ ] sample_interval_sec реально влияет на период (проверка в тесте 3.1)

**Out of scope:** реальная ротация по расписанию (отдельный /plan).
**Dependencies:** Task 1.1
**Module contract:** impl-only

---

## Phase 2 — Миграция DatabasePlugin на SQLManager

### Task 2.1 — DetectionSchema + замена sqlite3 на SQLManager

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** developer
**Goal:** Заменить в `DatabasePlugin` сырой `sqlite3.Connection` на `SQLManager`; таблицу `detections` описать как `DetectionSchema(SchemaBase + SQLMeta)` с auto-DDL; batch-запись через `repo.insert_many`; сохранить публичный контракт (process pass-through, буфер, flush-worker).
**Context:** `Plugins → Services` разрешён. Текущая реализация: `plugin.py` (raw sqlite3, ручной CREATE TABLE, executemany). Перевести на тот же fork-safe паттерн, что sink (SQLManager в `start()`).
**Files:**
- `Plugins/io/database/schemas.py` — создать `DetectionSchema` (поля: id, timestamp, frame_id, camera_id, event_type, data, created_at; SQLMeta.table_name="detections")
- `Plugins/io/database/plugin.py` — заменить `_conn`/`sqlite3` на `self._sql: SQLManager`; `_do_flush` → `repo.insert_many`; убрать ручной CREATE TABLE → `create_tables([DetectionSchema])` в `start()`
- `Plugins/io/database/registers.py` — без изменений контракта (db_path/batch_size/flush_interval_sec остаются)

**Steps:**
1. `DetectionSchema(SchemaBase)`: повторить текущие колонки; `created_at` — default через FieldMeta/None (unixepoch обрабатывается на уровне записи, т.к. SchemaBase-DDL может не поддержать SQL-default-выражение — проверить DDLBuilder, при необходимости проставлять `created_at=time.time()` в коде).
2. `start()`: `SQLManager(config=SQLManagerConfig(url=f"sqlite:///{db_path}", dialect="sqlite", fork_safe=True, connect_args={"check_same_thread": False}), managers={"logger":...}, process=...)`, `initialize()`, `create_tables([DetectionSchema])`. Сохранить flush-worker как есть.
3. `_do_flush(batch)`: `repo = self._sql.get_repository(DetectionSchema)`; `repo.insert_many([DetectionSchema(**r) for r in batch])`; fallback one-by-one оставить через try/except. Обновить счётчики `_total_written/_total_errors`.
4. `shutdown()`: `self._sql.shutdown()` вместо `_conn.close()`.

**Acceptance criteria:**
- [ ] `detections` создаётся через `create_tables` (auto-DDL), не ручным SQL
- [ ] Запись идёт через `SQLManager`/`repo.insert_many` — нет `import sqlite3` в plugin.py
- [ ] Контракт плагина не изменился: `process(items)` pass-through, register-поля те же
- [ ] `make check` чисто; sentrux: Plugins→Services OK
- [ ] fork-safe: SQLManager создаётся в `start()`, `fork_safe=True`

**Out of scope:** изменение схемы команд (Task 2.2); изменение register-полей; новые поля detections.
**Edge cases:** `created_at` SQL-default-выражение не поддержано DDLBuilder → проставлять в коде; batch insert падает → fallback one-by-one (сохранить поведение); БД заблокирована → ловить и логировать через ObservableMixin SQLManager.
**Dependencies:** Task 0.1 (общий fork-safe паттерн)
**Module contract:** impl-only

### Task 2.2 — Команды и тесты плагина под SQLManager

**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Привести команды (`flush`/`get_stats`/`set_batch_size`/`reset_stats`) и тесты `tests/test_database_plugin.py` к SQLManager-реализации.
**Files:**
- `Plugins/io/database/plugin.py` — `_cmd_get_stats` (db_path из register, total/pending), остальные без логических изменений
- `Plugins/io/database/tests/test_database_plugin.py` — заменить mock raw-sqlite на in-memory `SQLManager` (url `sqlite:///:memory:`) или mock SQLManager

**Steps:**
1. Обновить фикстуры: вместо `plugin._conn = sqlite3.connect(...)` — внедрить настоящий `SQLManager(:memory:)` + `create_tables([DetectionSchema])` (StaticPool для in-memory — `async_adapter`/sync уже выбирают StaticPool для `:memory:`).
2. Тесты: запись batch → `count(*)` через `sql.query`; flush-команда; get_stats; реализация fallback one-by-one.
3. Убедиться, что `:memory:` в одном процессе виден sample/flush-воркеру (StaticPool — один connection).

**Acceptance criteria:**
- [ ] `pytest Plugins/io/database/tests` зелёный
- [ ] Тесты используют SQLManager, не raw sqlite3 mock
- [ ] Покрыты: batch-flush, force-flush, get_stats, fallback при ошибке вставки

**Out of scope:** новые команды; интеграционный headless (Phase 3).
**Dependencies:** Task 2.1
**Module contract:** impl-only

---

## Phase 3 — Тесты и приёмка

### Task 3.1 — pytest: sink + плагин

**Level:** Middle+ (Sonnet, extended thinking)
**Assignee:** tester
**Goal:** Юнит/интеграционные pytest для sink (агрегация кэша→строки, период семпла, схема, fork-safe конфиг) и подтверждение тестов плагина (Task 2.2).
**Files:**
- `Plugins/io/telemetry_sink/tests/__init__.py`, `test_telemetry_sink.py` — создать

**Steps:**
1. Mock `ctx.state_proxy` (записать `subscribe` вызов и эмулировать callback с фейковыми дельтами `processes.camera_0.state.fps=24.0`).
2. Тест агрегации: наполнить `_cache` → вызвать `_sample_once` → проверить строки в in-memory SQLManager (по процессу + system).
3. Тест схемы: `create_tables([TelemetrySnapshot])` → таблица есть, индексы есть.
4. Тест fork-safe: `SQLManagerConfig(fork_safe=True)` → адаптер с NullPool (проверить через тип пула, как в существующих sql-тестах).
5. Тест периода: маленький `sample_interval_sec`, эмулировать N тиков → N семплов.

**Acceptance criteria:**
- [ ] `pytest Plugins/io/telemetry_sink/tests` зелёный
- [ ] Покрыты: subscribe-вызов, агрегация, schema/DDL, fork_safe→NullPool, период
- [ ] `python scripts/run_framework_tests.py` / `scripts/validate.py` без регрессий

**Out of scope:** headless-проверка (3.2); pytest-qt (sink не GUI).
**Dependencies:** Task 1.2, 1.3, 2.2
**Module contract:** n/a

### Task 3.2 — Headless/qt-mcp приёмка реальной записи

**Level:** Senior (Opus)
**Assignee:** teamlead
**Goal:** Доказать на реальной сборке (не unit), что обе ветки пишут в БД: sink наполняет `telemetry_snapshots`, мигрированный плагин — `detections`.
**Context:** Memory `feedback_qt_mcp_smoke_verification` — pytest-qt/unit недостаточно для доказательства реальной сборки процесса. Нужен живой запуск + query.
**Files:** — (запуск и проверка, без правок кода; при найденных багах — отдельные fix-задачи)

**Steps:**
1. Headless-запуск pipeline с sink-процессом (+ при наличии — detections-плагином).
2. После ~30 с остановить, выполнить `SELECT count(*), min(ts), max(ts) FROM telemetry_snapshots` и `SELECT count(*) FROM detections` (через sqlite CLI или временный probe; если применимо — `BACKEND_CTL=1` probe-команда `db.query`).
3. Проверить: snapshots растут во времени (несколько семплов), `system`-строки присутствуют, нет ошибок пула/fork в логах процессов.
4. Зафиксировать результат в STATUS.md плагинов.

**Acceptance criteria:**
- [ ] `telemetry_snapshots`: count>0, несколько разных `ts` (семплинг работает), есть строки `system`
- [ ] `detections`: count>0 при активном detections-плагине
- [ ] В логах sink/output-процессов нет ошибок SQLAlchemy pool/fork
- [ ] `ProcessMonitor` без изменений, GUI телеметрия не сломана (статусы зелёные)

**Out of scope:** нагрузочное тестирование; ретенция.
**Dependencies:** Task 3.1
**Module contract:** n/a

---

## Риски и ограничения

- **Backend-подписка (главный риск)** — снят по коду (`StateProxy.subscribe` generic, `GenericProcessApp` создаёт proxy, replay подтверждён). Runtime-proof в Task 0.1; FALLBACK на вариант D (правка framework) ТОЛЬКО при провале proof, с согласованием владельца.
- **Fork-safety SQLManager в дочернем процессе** — критично: создание+`initialize()` ВНУТРИ `start()` после fork, `fork_safe=True` (NullPool), `check_same_thread=False`. Нарушение → падение пула/«database is locked».
- **Рост БД без ретенции** — осознанный scope-cut: `retention_days=0` + `purge_old`-заглушка с TODO; полноценная ротация — отдельный /plan после подтверждения роста на проде.
- **Async внутри loop-worker** — снят решением (г): sink использует SYNC SQLManager (БД-I/O уже изолирован в отдельном процессе); async не обязателен, event-loop в loop-worker не вводим.
- **Не сломать detections-плагин при миграции** — контракт плагина (process/register/команды) сохраняется; тесты 2.2 + headless 3.2 это страхуют; `created_at` SQL-default может не лечь в DDLBuilder → проставлять в коде.
- **Слои импортов** — `Plugins → Services` и `prototype → Services` разрешены; sentrux `check_rules` в acceptance каждой реализующей задачи; плагин НЕ импортирует `multiprocess_prototype.*`.
- **Discovery sink-плагина** — убедиться, что `Plugins/io/telemetry_sink` попадает в `discovery.plugin_paths` (sys_config); иначе процесс стартует без плагина.
