# Стор и сигнал

> Фаза Ф3 плана [`observability-closure`](./plan.md). Правила приёмки — `plan.md` §3 (наследуют `observation-port/plan.md` §3), развилки владельца — `plan.md` §4, что удаляется и миграции — `plan.md` §9–§10. Номера находок (C*, M*, m*) — по [ревью 2026-08-28](../../docs/reviews/2026-08-28_observability-full-review.md).

## Ф3 — Стор и сигнал

**Порядок исполнения фазы:** 3.0 (добор вердикта CTO Ф2, один файл механизма) → 3.5
(`history_query`, половина `kind=log/error` не ждёт 3.1) → 3.1 → 3.2 → 3.3 → 3.4 → 3.6 → 3.7 → 3.8.
Merge Ф2 в `main` — после 3.0 (условие вердикта CTO от 2026-09-03,
[`review-phase-2-cto.md`](./review-phase-2-cto.md)).

### Task 3.0 — Сверщик потолков: реальный ask и честное «не судил» (F1, F2 вердикта CTO Ф2)
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework
**Goal:** отчёт `capped_by_throttle` называет потолок, который реально сработает (публикатор не может
просить чаще такта), а кандидаты, которых сверщик не судил, называются вслух, а не пропускаются молча.

**Откуда:** вердикт CTO по Ф2 (2026-09-03), находки F1 и F2. F1 — ошибка модели в безопасную сторону:
при `interval_sec=1.0`, такте `5.0` и троттле `2.0` отчёт называет потолок, хотя публикатор попросит
`5.0` и троттл его не режет; Task 2.11 заместила тактом только ноль, положительная заявка ниже такта
осталась дословной. F2 — развилка вынесена CTO в вариант **(б)**: ответ веера на «такта нет» сейчас
неотличим от «потолков нет» (класс «`checked` отвечает за вызов, не за охват»); вариант (в) — публикация
такта ребёнка в payload heartbeat'а — это новое поле payload и задача Ф4 рядом с 4.11, здесь не делается.

**Files:** `multiprocess_framework/modules/process_module/managers/telemetry_reload.py`
(`_publisher_ask`, `_judge`, новый `judge_throttle_caps`, `detect_throttle_caps` → обёртка, `__all__`),
`multiprocess_framework/modules/process_module/managers/observability_reload.py:1584`
(вызывающий кладёт поле только при непустом списке), тесты модуля,
`multiprocess_framework/modules/process_module/README.md` + `STATUS.md`,
`multiprocess_framework/docs/OBSERVABILITY_MAP.md`, `CONTROL_PANEL.md` (описание поля ответа `config.reload`).

**Steps:**
1. **Реальный ask (F1).** `_publisher_ask`: при пригодном такте (`effective_tick > 0`) ask =
   `max(pub_interval, tick)` — публикатор не публикует чаще такта; при `pub_interval > 0` и
   такте неизвестном/непригодном ask = заявка (поведение до правки, без регресса); при
   `pub_interval <= 0` и такте неизвестном/непригодном — не судим.
2. **Один проход (F2).** `judge_throttle_caps(...) -> (caps, unjudged)` — единственный проход по
   обеим половинам (`metrics.<имя>` и правила по пути); `unjudged` — `{ключ: причина}`, причина —
   литерал (`"no_tick"` для непригодного/неизвестного такта при `pub_interval <= 0`).
   `detect_throttle_caps` остаётся обёрткой с прежней сигнатурой и прежним типом ответа —
   вызывающие вне этой задачи не правятся.
3. **Ответ.** `apply_observation_policy` кладёт `capped_by_throttle_unjudged` в `applied` **только**
   при непустом списке. GUI-presenter не трогается.
4. Докстринги `_publisher_ask` и `detect_throttle_caps` приводятся в соответствие: замер F1
   (вход → вывод) переносится в текст, «замещение при нуле» переформулируется в «нижняя граница —
   такт».

**Acceptance criteria** (контракт для независимого тестера; `store_throttle` — объект с атрибутом
`rules: dict[glob → interval_sec]`, сигнатура `detect_throttle_caps(publish_section, store_throttle, *,
observation_rules, default_interval_sec, effective_tick)`):
- [ ] `interval_sec=1.0`, `effective_tick=5.0`, троттл `2.0` → потолок **не** называется (было: назывался).
- [ ] `interval_sec=1.0`, `effective_tick=5.0`, троттл `6.0` → потолок назван, `publisher_interval_sec == 5.0`
      (реальный ask, не заявленная 1.0).
- [ ] `interval_sec=1.0`, `effective_tick=None`, троттл `2.0` → потолок назван, `publisher_interval_sec == 1.0`
      (регресса нет: без такта судим по заявке).
- [ ] `interval_sec=0.0` (дефолт поддерева), `effective_tick=0.0` → кандидат не судится **и** назван
      в `unjudged` с причиной-литералом.
- [ ] `judge_throttle_caps` возвращает пару; `detect_throttle_caps` возвращает только `caps` и
      сохраняет прежний тип (страж «обёртка не сменила контракт»).
- [ ] `apply_observation_policy`: при пустом `unjudged` ключа `capped_by_throttle_unjudged` в ответе
      **нет**; при непустом — есть и содержит причину.
- [ ] Пара на диагностический ответ (правило §3 плана): «срез есть, отчёт пуст» и «среза нет, отчёт
      непуст» — обе инъекции с предсказанием до прогона.
**Out of scope:** публикация такта ребёнка в payload heartbeat'а (Ф4, рядом с 4.11); GUI; авто-ослабление
троттла (отвергнуто ADR-PM-017); переименование поля `capped_by_throttle`.

### Task 3.1 — Одна числовая запись `NumberRecord`; снапшот в стор один раз и структурно (M6, M11-часть)
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework
**Goal:** число ходит одной схемой от порта до стора; в сторе — одна строка на снапшот, JSON, колонка `metric`, запрос по имени.
**Files:** новый `statistics_module/core/number_record.py` (SchemaBase), `statistics_module/core/stats_manager.py:960-1060`,
`statistics_module/observation/observation_manager.py:380-410`, `channel_routing_module/observability/observability_hub.py:170-200`,
`channel_routing_module/observability/record_display.py:100-330` (один нормализатор), `channel_routing_module/observability/observability_store.py`
(миграция `user_version` +1: колонка `metric`, индекс `(metric, ts)`, backfill из JSON), `statistics_module/channels/log_stats_channel.py`
(лог-строка остаётся для человека, в стор не идёт), `process_module/managers/observability_wiring.py:1400-1410` (store-tap не берёт `origin=stats_snapshot`).
**Steps:**
1. `NumberRecord{name, kind(counter|gauge|timing|histogram), value|aggregate, tags, unit, ts, writer}` — единственная форма; три диалекта → адаптеры удаляются, а не оборачиваются.
2. В стор — только через hub (`kind=stats`, `message` = JSON, без усечения по 2048 Б; предел — по строкам); `log_stats` пишет `performance.log` и не попадает в стор.
3. `severity` для чисел — `'info'` (не `'snapshot'`/`'level'`); `kind=observation` рядов — оставить, но `metric` колонка заполняется и у них.
4. Миграция + backfill + тест на «старый файл открывается, запрос по `metric` работает после backfill».
**Acceptance criteria:**
- [ ] Живьём 30 мин: `kind=log` строк «metrics snapshot» в сторе = 0; `kind=stats` строк = числу флешей; средний размер строки `kind=stats` ≤ 1 КБ; `select … where metric='capture.frames'` возвращает ряд.
- [ ] Горизонт стора при INFO на 8 процессах ≥ 24 ч (экстраполяция по замеренному темпу, число в отчёте).
- [ ] Инъекция: вернуть store-tap на `log_stats` → тест «снапшот один раз» красный; снять индекс → тест плана запроса красный (EXPLAIN).
- [ ] Ни одного `getattr` по форме числовой записи в `record_display.py` (AST-страж).
**Out of scope:** `telemetry.db` (Task 3.7).

### Task 3.2 — Уровни логов и раскладка файлов: болтовня → DEBUG, `messages.log` без дубля (M6, m1, Р-7)
**Level:** Middle (Sonnet) · **Assignee:** developer · **Layer:** framework, prototype
**Goal:** старт процесса даёт < 100 строк INFO в стор; `system.log` и `messages.log` не дублируют друг друга.
**Files:** `dispatch_module/*` и `command_module/*` («registered successfully» → DEBUG + одна INFO-сводка «N хендлеров, M команд»),
`logger_module/configs/logger_manager_config.py:491-500` (дефолт скоупов по Р-7а), `multiprocess_prototype/backend/config/system.yaml`,
`SINKS_MAP.md`.
**Acceptance criteria:**
- [ ] Живьём: стор на 2-й минуте < 100 строк на процесс; `diff system.log messages.log` — файлы различаются по составу (пара: BUSINESS-строка есть в одном, SYSTEM — в другом).
- [ ] Инъекция: вернуть INFO регистрации → тест бюджета строк на бут красный.

### Task 3.3 — Store-tap батчем из потока hub'а (M7)
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework
**Goal:** запись в стор не стоит потоку-эмитенту больше цены постановки в очередь; потеря при переполнении — со счётом и голосом; останов дожимает и записывает исход.
**Files:** `channel_routing_module/observability/store_tap.py`, `channel_routing_module/observability/observability_store.py:440-470`,
`channel_routing_module/observability/observability_hub.py` (drain-петля), `process_module/managers/observability_wiring.py`.
**Steps:** tap кладёт запись в bounded-канал (ёмкость — из политики `history.queue_capacity`, `drop_oldest`, счётчик `store_evicted` с голосом окном); drain-поток пишет пачкой (`N` или 100 мс — из политики); один `commit` на пачку; `flush()` при останове с исходом в журнале (`dожато/потеряно`).
**Acceptance criteria:**
- [ ] Бенч соло ×3: принятая INFO-запись с tap'ом ≤ база + 5 мкс (было +120).
- [ ] Пара инъекций: очередь без потолка (память растёт) → тест ёмкости красный; потеря без голоса → тест голоса красный.
- [ ] Останов под нагрузкой: журнал содержит `store flush: N записано, M потеряно` — литералы в тесте.

### Task 3.4 — Метаданные метрик: единица, описание, род (M12)
**Level:** Middle+ (Sonnet) · **Assignee:** developer · **Layer:** framework, plugins, docs
**Files:** `multiprocess_framework/modules/observability_declarations.py:220-260`, `process_module/plugins/base.py` (`declare_metric`),
`process_module/commands/builtin_commands.py` (`introspect.telemetry`/`introspect.observability` — `metadata`), `Plugins/sources/capture/plugin.py:103-105`,
`multiprocess_prototype/frontend/widgets/tabs/observability/*` (единица в таблице), `CONNECTORS.md`.
**Steps:** `declare_metric(name, *, owner, unit="", description="", kind="gauge")`; все объявления фреймворка и `capture` получают единицы; `record_timing` — страж единицы (`unit="s"`; объявление с `unit="ms"` для timing → отказ с адресом); readback отдаёт metadata; GUI показывает.
**Acceptance criteria:**
- [ ] `introspect.telemetry(camera_0).metadata.capture_fps == {unit:"Hz", kind:"gauge", description:...}` живьём.
- [ ] Инъекция: `declare_metric("x_ms", kind="timing", unit="ms")` → отказ с адресом (тест литералом).

### Task 3.5 — `history_query`: история для агентов и операторов (T6/CTL-F6)
**Level:** Middle+ (Sonnet) · **Assignee:** developer · **Layer:** tests (backend_ctl)
**Goal:** агент получает историю логов/ошибок/чисел из стора одним инструментом, без чтения файла и без драйвера.
**Приоритет поднят ревью Ф1 (2026-09-01):** это самый большой недостающий кусок агентского DX —
две агентские сессии стенда Ф1.5 видели только «сейчас», «как дошло» приходилось читать sqlite
руками. Исполнять ПЕРВОЙ задачей фазы, какой позволит зависимость: половина инструмента
(`kind=log/error`) не ждёт колонки `metric` из 3.1 — можно дать раньше, ряд по метрике добрать
после 3.1.
**Files:** `backend_ctl/driver.py` (метод `history_query`), `backend_ctl/mcp_tools.py`, `channel_routing_module/observability/observability_store.py:481-533`
(`_filter_clauses` + `metric`), `CONTROL_PANEL.md`, `backend_ctl/AGENTS.md`.
**Steps:** путь к БД — из `introspect.observability.history.db_path` (readback, не догадка); read-only соединение; фильтры `kind/metric/process/module/severity/min_severity/since/until/text(FTS)/limit`; кап + `full`; для `kind=stats` — ряд `[ts, value]` по `metric`.
**Acceptance criteria:**
- [ ] Живьём: `history_query(metric="capture.frames", since=-600)` → ряд ≥ 50 точек; `history_query(kind="error", since=-3600)` → строки с `trace_id` колонкой.
- [ ] Инъекция: путь БД захардкожен → тест «путь из readback» красный.

### Task 3.6 — Сигнал: восемь метрик и второй эмитент wide event (Н-1, Н-7, Н-9 ревью)
**Level:** Middle+ (Sonnet) · **Assignee:** developer · **Layer:** framework, plugins, services
**Goal:** плоскость чисел обслуживает не 3 вызова, а работу машины: задержки, отказы, ресурсы.
**Files:** `Services/ml_inference/*`, `Services/hikvision_camera/*`, `Plugins/sources/capture/plugin.py`, `router_module/core/router_manager.py`,
`worker_module/*`, `chain_module/metrics/latency.py`, `process_module/heartbeat/telemetry.py` (ресурсы процесса), `Plugins/processing/segmentation/*` или `chain_executor` (второй `write_event`).
**Метрики (литералы, единицы):** `inference.latency` (s, timing), `inference.model_load` (s, timing), `camera.open_failed` (counter),
`router.send.duration` (s, timing), `worker.cycle.duration` (s, timing), `chain.stage.duration` (s, timing), `queue.evicted` (counter),
`process.rss` (MiB, gauge — из heartbeat, с политикой по умолчанию 1 раз/такт).
**Acceptance criteria:**
- [ ] Живьём каждая метрика ≠ 0 при контроле (например, `camera.open_failed == 0` с камерой и `> 0` без — пара).
- [ ] Второй `write_event` на стенде: запись находится поиском по `trace_id` ровно одной строкой (как А4 гейта Ф6).
- [ ] Цена каждой точки — дельтой против базы, три прогона; бюджет `record_timing` на горячем пути ≤ 5 мкс.

### Task 3.7 — Уборка стора голосом; `telemetry.db` с ретенцией по умолчанию (m14, T7)
**Level:** Middle (Sonnet) · **Assignee:** developer · **Layer:** framework, plugins
**Files:** `process_module/heartbeat/process_heartbeat.py:485-500`, `process_module/managers/observability_wiring.py:1340-1360`,
`Plugins/io/telemetry_sink/registers.py:38-46`, `Plugins/io/telemetry_sink/plugin.py` (PRAGMA `auto_vacuum=INCREMENTAL` при создании).
**Acceptance criteria:**
- [ ] Живьём: `purge` пишет INFO с числом удалённых строк (пара: 0 при пустом, N при заполненном).
- [ ] `telemetry_sink` с `retention_days=0` отказывается стартовать с адресом ключа (или дефолт 7 — решение в задаче с доводом); `PRAGMA auto_vacuum` у нового файла ≠ 0.

### Task 3.8 — Живой стенд Ф3 + ревью фазы
- [ ] Горизонт стора и МиБ/ч — числами на 8 процессах с включёнными wide events (`every_mth` как в гейте Ф6 А6): цель ≥ 24 ч, ≤ ~4 МиБ/ч; агентская сессия: `history_query` отвечает «почему изделие забраковано» без драйвера.
