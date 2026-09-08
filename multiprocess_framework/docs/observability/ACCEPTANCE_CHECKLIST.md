# Чек-лист приёмки наблюдаемости глазами потребителя

> Заведён **2026-09-08** по заказу владельца: «какие функции наблюдаемости есть, как ими управлять
> и как убедиться, что они работают, — чтобы на это можно было опираться дальше».
> Первый прогон — [`docs/reviews/2026-09-08_observability-consumer-acceptance.md`](../../../docs/reviews/2026-09-08_observability-consumer-acceptance.md)
> (числа, находки, вердикты по строкам). Зонд, который гоняет этот чек-лист автоматически —
> [`backend_ctl/probes/probe_observability_consumer_acceptance.py`](../../../backend_ctl/probes/probe_observability_consumer_acceptance.py).
> Соседние справочники: [`CONTROL_PANEL.md`](CONTROL_PANEL.md) (ручки), [`SINKS_MAP.md`](SINKS_MAP.md)
> (куда попадает запись), [`CONNECTORS.md`](CONNECTORS.md) (чем писать), [`../OBSERVABILITY_MAP.md`](../OBSERVABILITY_MAP.md).

Документ отвечает на три вопроса про КАЖДУЮ функцию: **чем управлять** (точная ручка/команда),
**чем потребитель видит эффект** (инструмент, файл или SQL-запрос — не ответ команды) и **как
принять** (шаги + ожидаемое наблюдение, записанное ДО прогона). Колонка «статус в плане» —
по чекбоксам `plans/observability-closure/phase-*.md`, `plans/otel-export.md` и git log, не по прозе.

## 0. Правила честности, без которых чек-лист ничего не стоит

1. **`success=True` в ответе команды — не вердикт.** Вердикт выносит независимый арбитр:
   файл на диске (`open()`), стор (`sqlite3` по `file:…?mode=ro`), пуш, прибывший подписчику,
   или часы `perf_counter_ns` с обеих сторон у потребителя.
2. **Ноль наблюдений — вопрос, а не результат.** Рядом с каждым «перестало приходить» стоит
   контроль «а до ручки приходило» (пара ON/OFF). Ноль без контроля = `NOT_REACHED`.
3. **Число без разброса — наблюдение, не замер.** Задержки — ≥ 5 повторов, медиана/мин/макс.
   На этой машине `time.time()` шагает **0.01 мс** (высокоточный таймер поднят), сетки 15.6 мс
   в замерах 2026-09-08 не было; на другой машине первым делом измерить шаг (`L0`).
4. **Приёмник назван в каждой строке.** Если данные принимает наш собственный код (драйвер
   `backend_ctl`), вердикт проверяет и оснастку; где возможно — файл/SQLite (внешний арбитр).
5. Вердикты: `PASS` / `FAIL` / `PARTIAL` / `NOT_REACHED` (не смог прогнать — сказано почему) /
   `UNVERIFIED` (документировано, не гонялось). Строка с пустым «наблюдал» не бывает `PASS`.
   Функция, которая **запланирована, но не построена** — `NOT_REACHED — запланировано`, не `FAIL`.

## 1. Как поднять стенд (5 минут)

```bash
# из корня, порт 8765 обязан быть свободен: netstat -ano | grep 8765 → пусто
PYTHONIOENCODING=utf-8 PYTHONPATH=$PWD .venv/Scripts/python.exe \
    -m backend_ctl.probes.probe_observability_consumer_acceptance
# артефакты: logs_live/2026-09-08_qa-acceptance_<ts>/{acceptance_results.md,json, observability.db, <процесс>/*.log}
```

Зонд поднимает `BackendHarness(recipe=inspection_full, port=8765, log_dir=logs_live/…)` — топология с
единственным боевым `write_event` (`robot_control`), семь процессов: `ProcessManager`, `camera_0`,
`gui`, `inspector`, `processor`, `renderer`, `storage`. Ничего в tracked-дереве не мутирует
(`system.yaml`, рецепты — только читаются). Ручной стенд для агентской линзы: тот же harness из
Python, а инструменты — `mcp__backend-ctl__*` (сессия MCP подключается к 8765 вторым клиентом,
`session_isolation` включена по умолчанию).

**Ловушки стенда, найденные прогоном:**
- на Windows дети спавнятся переимпортом главного модуля — каталог логов считать один раз (`os.environ.get`),
  мутации только под `if __name__ == "__main__"`;
- останов штатно упирается в `ProcessManager did not stop in 5.0s, terminating` (долг Task 4.8) —
  строки `store flush` при этом всё равно пишутся всеми семью процессами;
- второй клиент (MCP) на том же стенде добавляет свои записи в процессы (`self_cost` опроса) —
  строки, где сравниваются счётчики, гонять без параллельного клиента.

## 2. Раскладка, которую надо знать до чтения

| Что | Где | Замечание |
|---|---|---|
| журналы процесса | `<log_dir>/<процесс>/messages.log` (INFO, скоуп BUSINESS), `system.log` (WARNING+ и DEBUG-скоуп), `performance.log` (снапшоты stats), `busy.log`, `gui.log`, `trace.log` | INFO и WARNING+ **в разных файлах**; «полного журнала в одном файле» нет ни на одном уровне (Р-7(а), Task 3.2) |
| плоскость ошибок | **`<log_dir>/errors.log`, `warnings.log`, `critical.log` — в корне, ОБЩИЕ для всех процессов** | не per-process; дефолт `error_manager_config.py: logs/errors.log`. Лаунчер держит свой набор в `launcher/` |
| пол ошибок | `errors_floor.jsonl` рядом с логами | появляется **только** когда штатный маршрут записал ноль каналов (`error_floor.py`); у здорового процесса файла нет — это норма, а не потеря |
| стор истории | `<log_dir>/observability.db` (SQLite, WAL) | путь — из readback `introspect.observability → history.db_path`, не из догадки; колонки `id, kind, process, module, ts, severity, message, extra, severity_number, metric`; FTS5 по `message/module/process` |
| кольцо записей процесса | memory-приёмник `flight_ring` у `inspector` (рецепт `inspection_full.yaml`) | читается ретроспективно `observability.sink.tail`; дамп в файл — `ctx.flight_dump` только на фронте pass→reject |
| запись драйвера | `backend_ctl_records/<имя>.jsonl` (env `BACKEND_CTL_RECORD_DIR`) | только из MCP-сессии (`record_*`), у голого `BackendDriver` нет |

## 3. Семьи функций — что есть, чем управлять, как принять

Ниже `id` строк совпадают с зондом и протоколом. «Статус» — по планам на 2026-09-08.

### 3.1. Самоописание (S) — «что система говорит о себе, и сходится ли это с диском»

| id | функция | ручка | потребитель видит | приёмка (шаги → ожидание) | статус в плане |
|---|---|---|---|---|---|
| S1 | `system_overview` — состав, статусы, anomalies | — | `drv.system_overview()` / MCP | процессов ровно 7, `anomalies` — список с `kind`/`process`/`detail` | закрыто (backend_ctl B.3; `telemetry_readmodel_empty` — closure Task 2.8) |
| S2 | `capabilities` — контактная книжка | — | MCP `capabilities(format=concise)` → dict; `drv.capabilities()` → dataclass `Capabilities` (`.processes[<имя>].commands`) — **две формы одного ответа** | у каждого процесса ⊇ `config.reload, introspect.observability, observability.sink.*, health.report, diag.thread_raise, diag.warn, introspect.telemetry`; регистры плагинов по именам | закрыто (backend_ctl B.4) |
| S3 | `introspect.observability` — семь секций | `section=` сужает | `send_command(<p>, introspect.observability {flush:true})` / MCP `introspect_observability(process, section)` | секции `effective, counters, provenance, history, observation, audit, layers` + `documents, stats, events, flight` | закрыто (closure Task 0.4 `5226045a`, `de8bc0a9`) |
| S4 | `history.db_path` совпадает с файлом | — | readback ↔ `os.path.exists` | путь = `<log_dir>/observability.db`, файл есть, `enabled=true` | закрыто (Ф5.2 ADR-PM-047, closure 2.2) |
| S5 | `effective.logger.log_directory` ↔ каталоги на диске | — | readback ↔ `os.listdir` | у всех 7 процессов есть `system.log`/`messages.log`; поле лежит в `effective.logger.log_directory` (не на верхнем уровне `effective`) | закрыто |
| S6 | `introspect.telemetry` — gate/resolved/levels/tick | — | `introspect_telemetry(<p>)` | `gate_active=true`, `resolved ⊇ {fps, latency_ms, effective_hz, cycle_duration_ms, shm}`, `levels` не null, `tick_effective_sec=5.0` | закрыто (Ф4.1 telemetry, closure 2.3 честный такт) |
| S7 | `supervision_status` — pid/incarnation/restarts | — | `supervision_status()`; ответ — конверт `result.processes` | у 7 процессов `pid`, `alive=true`, `instance_restarts=0` на старте | закрыто (D.1b, closure Task 0.2) |

### 3.2. Чтение потребителем (R) — «что БЫЛО» и «что СЕЙЧАС»

| id | функция | ручка | потребитель видит | приёмка | статус |
|---|---|---|---|---|---|
| R1 | файлы журналов per-process | — | `open()` | у каждого процесса есть оба файла; PM `system.log` непустой | закрыто (Task 3.2 `messages.log` без дубля) |
| R2 | стор напрямую | — | `sqlite3 file:<db>?mode=ro` | схема из §2; `kind ∈ {log,error,stats,observation}`; `process` ⊆ состав S1 | закрыто (3.1 колонка `metric`, 3.3 батч) |
| R3 | `history_query` ↔ стор | фильтры `kind/process/module/severity/min_severity/since/until/text/metric/limit` | `drv.history_query` → каждую строку найти по `id` в sqlite | 5/5 строк подтверждены арбитром | закрыто (closure Task 3.5, 3.1) |
| R4 | `log_tail` — живой пуш логов | `log_tail(<p>, level=INFO)` | пуш `log.record` (`data.record`) в `drv.subscribe`; строка в `messages.log` | эмиссия `health.report level=INFO` → пуш ≤ 5 с **и** строка в файле ≤ 3 с (замер: 6 мс / 6 мс) | закрыто (A1 level доезжает) |
| R5 | `observability_tail` — три плоскости | `observability_tail(<p>, level=INFO)` | пуш `observability.record` с `kind ∈ {log,error,stats}` | `health.report level=WARNING` → пуш с `kinds=[error, log]`; строка в `<p>/system.log` (WARNING → SYSTEM) | закрыто (Ф1.1b мост, 5.5/5.6 брокер) |
| R6 | `events_page` — курсорное чтение по плоскостям | `plane=logs|errors|stats|telemetry|state|ui|all` | `events_page(plane, cursor, limit)` → `items/next_cursor/dropped/bookmark` | маркер R4 в `logs`, маркер R5 в `errors`; `dropped=0` | закрыто (B.1) |
| R7 | `watch_like_gui` → read-model телеметрии | `watch_like_gui(tail_level=INFO)` | `telemetry_snapshot(process)`, `telemetry_history(path)` — 0 IPC | snapshot `count>0` сразу; точка `fps` ≤ 12 с (такт 5 с) | закрыто (ADR-136, 5.11) |
| R8 | `record_start/stop/status/dump/load` — чёрный ящик драйвера | MCP `record_start(name)` … `record_stop()`; `record_load` → реплей | файл `backend_ctl_records/<name>.jsonl`; в реплее `telemetry_snapshot` отвечает ПО ЗАПИСИ | `events_written>0`, `dropped=0`; `record_load` → `mode=replay`, снимок `count>0` без живой системы; `record_unload` → `live` | закрыто (D.4, BCTL-ADR-006) |
| R9 | широкие записи (`ctx.write_event`) в стор + FTS по `trace_id` | `config.reload {events: {first_n, every_mth}, ttl}` | sqlite `message LIKE 'event %'`; `history_query(text=<trace_id>)`; readback `events.kinds.<род>.{selected,skipped,decisive}` | **селектор считает от старта процесса**: `first_n` на бегу уже потрачен, проходит каждая `every_mth`-я → ожидать `Δselected = Δединиц/every_mth ± 1`; след находится ровно одной строкой; контроль по несуществующему следу — 0 | закрыто (ADR-PM-036; 3.8 стенд) |
| R10 | `observability.sink.tail` — ретроспектива memory-кольца | `{sink: flight_ring, limit}` | ответ `records` | ≥ 1 запись из кольца инспектора | закрыто (Ф5 5.1, ADR-PM-037) |
| R12 | `history_query(metric=…)` / идентичность чисел | — | sqlite `metric IS NOT NULL` | на `inspection_full` — **ноль** строк с `metric` (источник `camera_service` чисел не пишет; снапшоты — `metric=NULL`) | закрыто как факт (3.8 (б)); писатель чисел — задача продукта, не фреймворка |

### 3.3. Ручки (K) — «включить, увидеть, выключить, и когда оно само умрёт»

Три слоя поверх кода: **L1** `system.yaml`, **L2** рецепт + спутник, **L3** память процесса
(`config.reload` inline, срок **300 с** по умолчанию, продлить `ttl=<сек>`, сделать вечным —
только `observability.persist`). Применение — пересборка из источников, «вернуть как было» =
`config.reload {observability_reset: [<ключ>]}`, не присвоение прежнего значения.

| id | функция | ручка | потребитель видит | приёмка | статус |
|---|---|---|---|---|---|
| K1 | уровень логгера процесса | `config_reload_verified(<p>, {log_level: DEBUG})` → `observability_reset: [log_level]` | `grep -c "[DEBUG]" <p>/system.log` до/после; сосед тем же способом | `verdict=confirmed`, `delivering=true`; Δ[DEBUG] у цели > 0 за 4 с (замер 255), у соседа == 0; после reset Δ == 0, `layers.session_keys` пуст | закрыто (5.12 слои, 5.7 verified) |
| K2 | уровень по имени источника | `{loggers: {<источник>: {level: DEBUG}}}` | те же файлы, имя источника в 6-й колонке строки | все новые DEBUG-строки — от названного источника, сосед-процесс молчит. Источники, которые реально болтают на DEBUG: `router_<процесс>`, `router_messages` (не `process_module`) | закрыто (Ф2.5 группы, ADR-LOG-010) |
| K3 | приёмник (sink) выкл/вкл на лету | `logger_sink_disable(<p>, messages_file)` / `enable` | `messages.log` (маркер не появляется/появляется); readback `effective.logger.sinks_disabled_by_operator`; счётчик `counters.logger.records_without_channels` растёт; `system_overview.anomalies` → `observability_loss` | OFF: маркер НЕ в файле, readback называет `messages_file`, `records_without_channels` +N, голос WARNING «запись уровня INFO потеряна: нет приёмника»; ON: маркер ≤ 3 с. Побочно: включение кладёт в L3 ключ `channels.messages_file.enabled` со сроком | закрыто (5.4 обе оси адресации) |
| K4 | срок правки (TTL) и авто-возврат | `config.reload {observability: {...}, ttl: 20}` | `<p>/system.log`: `[WARNING] … TTL истёк — рантайм-правки возвращены к нижнему слою: <ключи>`; `layers.session_keys/ttl/reverts` | голос в интервале `(ttl; ttl + heartbeat 5 с]` (замер: 21.2 с при 20); после — Δ[DEBUG]==0. Свип **молчит** про ADR-PM-046 намеренно (ADR-PM-048) — искать строку возврата, не голос про `stats.enabled` | закрыто (5.12 TTL; 4.11 `1ce1102f`) |
| K5 | publisher-gate телеметрии (push уровней в дерево) | `telemetry_set(<p>, fps, enabled=false, verify=true)` | дельты `state.changed` по `processes.<p>.state.fps` (подписка) | пара ON/OFF **достижима только если значение дрожит**: `TreeStore.set` гасит дельту при неизменном значении, у стабильного `fps=21.3` контроль даёт 0 дельт за 12 с → `NOT_REACHED`; readback `introspect_telemetry.resolved.fps.enabled` подтверждает правило независимо от дельт. Срок правки 300 с (L3) | закрыто (PC 1.3/2.1; ловушка TTL — память `project_runtime_knob_expires_in_300s`) |
| K6 | плоскость чисел: glob-правило по пути | `{observation: {rules: {processes.<p>.stats.<имя>: {enabled: false}}}}` | readback `stats.policy.{rules,hits,dropped_by_rule}`, `counters.stats.numbers_policy_dropped`; свежий снапшот в сторе без метрики | достижимо только там, где есть писатель чисел с именами; на `inspection_full` снапшоты без имён → `NOT_REACHED` | закрыто (closure Task 2.1) |
| K7 | порог записи в стор `history.level` | `config.reload {history: {level: WARNING}}` → reset | sqlite `COUNT(kind='log' AND severity='info' AND process=<p>)` до/после; контроль — `grep -c "[INFO]" messages.log` | INFO-строки в файл идут, в стор — нет (Δstore==0 при Δfile≥3); WARNING/ERROR — в сторе ≤ 3 с; после reset INFO снова в сторе. **Ловушка:** `health.report` всегда кладёт строку плоскости ОШИБОК с тем же текстом — по маркеру порог не проверить, только по `kind/severity` | закрыто (closure 2.2, ADR-PM-047) |
| K8 | опечатка в имени ключа | `{log_levl: DEBUG}` | ответ команды; `layers.session_keys` | `success=false`, ключ назван; в L3 ничего не легло | закрыто (5.4) |
| K9 | окно голоса | `{voices: {default_window_sec: 30}}` | readback `effective.voices` | `verdict=confirmed`, значение в readback; эффект (подавление повторов) отдельно не воспроизведён — `UNVERIFIED` | закрыто (1.4, 2.7) |
| K10 | регистр плагина с readback | `set_register_verified(inspector, robot_control, reject_delay_ms, 1)` | `verified/expected/actual`; аудит — MCP `session_log` | `verified=true`, `actual=1`; возврат `actual=0`; замер 22–46 мс | закрыто (Ф1.6, E.1) |
| K11 | охват `applied` в ответе `config.reload` | — | ответ команды | `applied` называет только `log_level`; секции едут отдельными ключами `events_applied`, `flight_applied`, `voices_applied`, `observation_applied` — читать их, не `applied` | известное (3.8), нет в планах |
| K12 | `observability.persist` (L3 → L2) | `observability.persist {}` | файл-спутник рецепта | не гоняется на общем дереве (писал бы спутник рядом с рецептом) — гонять в worktree/копии рецепта | закрыто (5.12); `NOT_REACHED` по правилу дерева |
| K13 | `history.purge_interval_sec` укорочен | `{history: {purge_interval_sec: 5, max_age_sec: 20}}` | строка «уборка истории: снято N» | **срок следующей уборки ждёт СТАРЫЙ период**: голос через ~300 с, не через 5, при `success=true` (замер 298 с, 3.8 заход 3) | закрыто как факт; исправление — нет в планах |
| K14 | `telemetry_reconfigure(mode=replace)` | — | `introspect_telemetry` | разрушающая (сносит белый список и IPC-страховку) — в приёмке не гоняется | закрыто (PC 2.1) |

### 3.4. Задержки между модулями (L) — «сколько едет»

Все числа — на потребителе, `perf_counter_ns` с обеих сторон (не на сетке). Полные таблицы —
в протоколе прогона.

| id | что меряется | как | ожидание (по прогону 2026-09-08) | статус |
|---|---|---|---|---|
| L0 | шаг часов | `time.time()` в цикле | 0.01 мс на этой машине (сетки 15.6 мс нет) | — |
| L1 | RTT команды через роутер | 20× `introspect.status` → `camera_0`/`processor`/`PM` | ребёнок медиана **11–14 мс**, бимодально 10.5 / 21.5; PM **22 мс** (см. находку о ~10 мс шаге) | закрыто (инструмент) |
| L2 | эмиссия → видно в SQLite | `health.report` + опрос sqlite 5 мс | медиана **59 мс** (31–118); wall−`ts` 46 мс | закрыто (3.3: такт дренажа 100 мс) |
| L3 | эмиссия → пуш живого хвоста | колбэк `subscribe` в reader-потоке | медиана **23 мс** (15–32); wall−`ts` 14 мс | закрыто |
| L4 | `state.set` → пуш `state.changed` | подписка `qa.**`, 7× `state.set`; дельта имеет форму `data.deltas[{path, old_value, new_value}]` (не `value`) | медиана **25 мс** (15–40), 7/7 | закрыто (1.1b) |
| L5 | запись регистра → readback | `set_register_verified` ×5 | медиана **41 мс** (22–46) | закрыто |
| L6 | **путь кадра camera → processor → inspector (хоп-лаг)** | — | **поверхности нет**: `latency_ms` = время цикла воркера, не хопа; `item["timestamp"]` (monotonic) не экспортируется; широкая запись несёт `trace_id` без отметки захвата | **нет в планах** — заявка владельцу |

### 3.5. Ошибки и отказы (E)

| id | функция | ручка | потребитель видит | приёмка | статус |
|---|---|---|---|---|---|
| E1 | инъекция ERROR | `health.report {level: ERROR}` | `<log_dir>/errors.log` (общий), стор `kind=error`, пуш `kind=error`, `system_overview.anomalies[kind=health_errors]` | маркер в файле ≤ 3 с; строка в сторе; anomaly с `last_error` | закрыто (1.3a/b, ADR-PM-030) |
| E2 | необработанное исключение потока | `diag.thread_raise` | ответ `thread_exceptions`, `joined`; `errors.log` с traceback | `thread_exceptions ≥ 1`; traceback в `<log_dir>/errors.log` и в сторе (`kind=error`, многострочный `message`) | закрыто (closure 1.1) |
| E3 | `warnings.warn` | `diag.warn` | `warnings_captured`; `<p>/system.log` | счётчик ≥ 1; строка в `system.log` (в `warnings.log` — наблюдать) | закрыто (1.1) |
| E4 | пол `errors_floor.jsonl` | — | glob + `counters.error.errors_to_floor` | у здорового процесса файла нет и `errors_to_floor=0`; появление файла = штатный маршрут сломан | закрыто (Ф0.9 unified-routing) |
| E5 | счётчики потерь трёх плоскостей | — | `counters.{logger,error,stats,observation}` ⊇ `LOSS_COUNTER_KEYS`; `counters.hub.dropped`; голоса окна — `windowed_suppressed` (после Task 4.13 рядом появится `windowed_delivery_failed`) | проверять «**названные поля присутствуют**», не «ровно столько полей»; суффикс «(подавлено с прошлой записи: N)» читать как «N событий этого ключа не дошли до журнала с прошлой записи» (верно до и после 4.13); **рост под перегрузкой не вызывался** → `PARTIAL`; `store_evicted` стора в readback **не публикуется** (только строка `store flush` на останове) | ключи закрыто; `windowed_delivery_failed` — в работе (Task 4.13); `store_evicted` — нет в планах |
| E6 | «нет приёмника» | `send_command(<p>, qa.nonexistent)` | `introspect_handlers`; ответ | команды нет в `commands`/`router_handlers`; ответ `{status: error, reason: "No handler for key …"}` за 20 мс (форма без `success`) | закрыто (Этап 2 proof) |
| E7 | OTLP-экспорт наружу | фрагмент топологии `otel_export.yaml` | внешний коллектор | **не в дефолтной топологии** — `NOT_REACHED`; приёмник обязан быть внешним (`otelcol`), не своя заглушка (урок otel Ф2) | в работе (otel Ф2, Task 2.3–2.5) |
| E8 | дренаж стора у второго потребителя: `BatchDrainWorker.flush(timeout)` — ограничен по времени, исход парой чисел (записано / потеряно) | — | возврат `flush(timeout)` ≤ timeout и при ЗАВИСШЕМ стоке, не только при бросающем; строка `store flush` на останове | контракт otel Task 2.4 (`2034c20e`): дренаж описывать как `flush(timeout)`, не «поток + close» — иначе фиксируется половина контракта; бюджет останова 5 с, таймаут SDK его не даёт (замер CTO: потолок 3000 мс → 4.08 с, чёрная дыра → 42.08 с) | `UNVERIFIED` — заведено с слов otel 2026-09-08, зондом не гонялось; closure 3.3 закрыто, otel 2.4 в работе |
| E9 | страж от петли наблюдаемости несущий: у otel своего предохранителя нет (ADR-OTEL-008), опора — страж фреймворка `process_module/core/process_module.py:1263` (`if subscriber == self.name` → отказ «подписка процесса на собственный хвост — петля», Task 5.11) | — | греп стража; тест фреймворка на петлю | страж существует и не смягчён; если исчезнет или станет мягче — петля вернётся у otel, сигнала нет; проверять на каждой фазовой точке closure | `UNVERIFIED` — греп 2026-09-08 подтвердил строку 1263 (`grep -n 'петля' …/core/process_module.py`), тест на петлю не гонялся; контракт otel ADR-OTEL-008 |

### 3.6. Жизненный цикл (LC)

| id | функция | ручка | потребитель видит | приёмка | статус |
|---|---|---|---|---|---|
| LC1 | `config.reload` всем под нагрузкой | `config_reload("all", …)` | `counters.logger.unresolved_channel_records` до/после | batch-ответ на 7; Δ ≤ 2 на процесс (замер: 0 у всех); сброс — `send_command_many("all", config.reload, {observability_reset: […]})`, `send_command("all", …)` никуда не доходит | закрыто (6.1 окно) |
| LC2 | рестарт с доказательством | `process_restart_verified(renderer)` | `pid_before/after`, `instance_restarts`; `layers.session_keys` до/после; `channel_written_records`; пуши после рестарта | pid сменился (5.8 с); **L3 теряется**; счётчики обнуляются; хвост переподписывается сам (`watch_like_gui`) | закрыто (Ф4.4 restart, D.1b); точечные подписки после рестарта — Task 4.4 **запланировано** |
| LC3 | срок сессии по умолчанию | — | `layers.{ttl_default_sec, ttl_enforced, ttl}` | `300.0`, `true`, карта «ключ → остаток секунд» | закрыто |
| LC4 | останов: `store flush: N записано, M потеряно` | `harness.stop()` | `<p>/messages.log` после останова | у всех 7 процессов, `M=0`; при `terminate` после 5 с — тоже пишется | закрыто (3.3) |
| LC5 | порт освобождён | — | `socket.connect_ex` | `!= 0` | — |

## 4. Чего чек-лист НЕ покрывает (честный список)

- **Хоп-лаг между модулями (L6)** — нет наблюдаемого. Что нужно: отметка захвата в `unit`
  широкой записи (или спан `capture→decision`) — заявка владельцу, дом не назначен.
- **Потери под перегрузкой (E5)** — счётчики видны, но не показаны растущими; для этого нужен
  шторм (`probes/log_storm_plugin.py`) на отдельном стенде.
- **`store_evicted` в рантайме** — в readback не публикуется; потребитель узнаёт о потере стора
  только строкой на останове.
- **Голос окна (K9), `observability.persist` (K12), `telemetry_reconfigure replace` (K14)** —
  readback/документ, без эффекта у потребителя.
- **Экспорт OTLP (E7)** — трек otel Ф2, отдельный стенд с настоящим коллектором.
- **Второе приложение / другая топология** — весь прогон на `inspection_full`; `region_pipeline`
  несёт плагин `capture`, который числа ПИШЕТ (там K6/R12 достижимы).

## 5. Как расширять

Новая функция наблюдаемости заводится здесь строкой с теми же шестью колонками и, если она
проверяема автоматически, — функцией в зонде (семья по буквам). Строка без «чем потребитель видит»
не принимается: ручка без наблюдаемого — это ручка без доказательства.
