# Мини-план D.4 — Flight recorder (запись → offline-реплей в read-model)

- **Slug:** `backend-ctl-d4-flight-recorder`
- **Родитель:** [`backend-ctl-debug-console.md`](backend-ctl-debug-console.md) → Task D.4 (Phase D)
- **Ветка (при старте):** `feat/bctl-d4-flight-recorder`
- **Дата:** 2026-07-19
- **Level / исполнитель:** Senior (Opus) → `teamlead` | **Layer:** mixed (tools + один additive-шов framework)
- **Гейт-статус:** ✅ ОДОБРЕН (2026-07-19) — §Записка ратифицирована владельцем (все 6 дефолтов Fable приняты). Код разрешён.

> Основа — чтение кода 2026-07-19, все якоря `file:line` верифицированы. Перед правкой перепроверить якоря — код мог сдвинуться. Детерминированный rr-реплей **отклонён родителем** (multiprocess+SHM исключают) — здесь НЕ проектируется.

---

## 1. Зачем (проблема)

Живая сессия отладки невоспроизводима: агент видит поток событий один раз, а «что происходило перед сбоем» после обрыва/рестарта недоступно. Нужен дешёвый тайм-трэвел (аналог Java Flight Recorder / Chrome tracing): `record_start` пишет снимок + JSONL событий, `record_load` прогружает запись в **тот же** read-model оффлайн — `telemetry_snapshot` / `telemetry_history` / `await_condition` / `events_page` работают над записью без живой системы. Вторичный эффект: запись — переносимый артефакт для bug-report'а («вот лента событий, воспроизводи анализ у себя»).

---

## 2. Карта кода — что уже есть (верифицировано)

**Источник потока и целевой read-model — одни и те же объекты driver'а:**

1. `EventHub` ([events.py:203](../backend_ctl/events.py#L203)) — arrival-кольцо оригиналов (плотный глобальный seq) + 7 плоскостных колец через единый классификатор `_classify` ([events.py:135](../backend_ctl/events.py#L135)). Вход — `emit(msg)` ([events.py:233](../backend_ctl/events.py#L233)); синхронные подписчики зовутся в потоке эмиттера.
2. Driver подключает telemetry-ingest подписчиком в `__init__`: `self.subscribe(self._ingest_state_changed)` ([driver.py:192](../backend_ctl/driver.py#L192)) → `TelemetryReadModel.ingest` ([driver.py:1029](../backend_ctl/driver.py#L1029)). Читатели: `telemetry_snapshot` ([driver.py:1079](../backend_ctl/driver.py#L1079)), `telemetry_history` ([driver.py:1117](../backend_ctl/driver.py#L1117)).
3. `await_condition` ([conditions.py:138](../backend_ctl/conditions.py#L138)) — подписка на hub + начальная проверка read-model. Настройщики предикатов `_setup_state_path` / `_setup_metric_threshold` / `_setup_event_matches` — модульные функции ([conditions.py:209](../backend_ctl/conditions.py#L209), 240, 281), переиспользуемы реплеером без дублирования.
4. **Ключевой факт для offline:** `transport.request()` на неподключённом driver'е возвращает `{"success": False, "error": "not connected"}` ([transport.py:126](../backend_ctl/transport.py#L126)), **не бросает**. При этом hub, telemetry-model и подписчики создаются в `__init__` до всякого connect ([driver.py:173](../backend_ctl/driver.py#L173), [driver.py:190](../backend_ctl/driver.py#L190)) → **неподключённый `BackendDriver` уже является рабочим offline read-model**: `_emit_event` / `events_page` / `telemetry_*` / предикаты `await_condition` живут без сокета.
5. `interfaces.py:34 def load(self, intents)` — это `ISubscriptionRegistry.load` (durable-подписки, Task 0.3), **НЕ** готовый Recorder-контракт — не переиспользуем.
6. `system_overview` ([overview.py:31](../backend_ctl/overview.py#L31)) — IPC fan-out, оффлайн не исполним → отдаём записанный в header снимок с меткой `"recorded": true`.
7. Единственная преграда честному реплею: `TelemetryReadModel._record_history` штампует `time.time()` ([telemetry_read_model.py:208](../multiprocess_framework/modules/telemetry_readmodel_module/telemetry_read_model.py#L208)) — история при реплее получила бы «сейчас» вместо записанных ts. Также нет экспорта/импорта кольцевых буферов истории.
8. MCP-слой: реестр `ToolSpec` ([mcp_tools.py:34](../backend_ctl/mcp_tools.py#L34)), классы безопасности `TOOL_SAFETY` ([mcp_tools.py:934](../backend_ctl/mcp_tools.py#L934)), lifecycle `DriverSession` ([mcp_driver_session.py:50](../backend_ctl/mcp_driver_session.py#L50)): `ensure()` (141, lazy-connect), `reset()` (212), `close_graceful()` (245).

---

## 3. Дизайн: единый read-model для live и offline (ответ на вопрос §1 родителя)

**Решение — «detached driver»: реплей идёт через ТОТ ЖЕ вход, что и живой поток.**

- `record_load` создаёт **неподключённый** `BackendDriver` (никогда не зовём `connect()`), и `ReplayPlayer` качает записанные события через `drv._emit_event(msg)` — ровно ту точку входа, которой пользуется reader-поток транспорта ([events.py:496](../backend_ctl/events.py#L496)). Классификация по плоскостям, telemetry-ingest, подписчики, курсоры, `dropped` — всё исполняется тем же кодом, что вживую. **Второго read-model / второго классификатора не появляется** (тот же принцип «нет второго парсера», что у `iter_state_deltas`).
- `DriverSession` получает режим `mode: live | replay`: `record_load` подменяет `self._driver` на detached-driver и выставляет режим; `ensure()` в replay-режиме возвращает его **без** connect и без isolation-пробы. Возврат к живой системе — `record_unload()` (сбрасывает в live, следующий `ensure()` переподключается штатно).
- Инструменты в replay-режиме делятся на два множества:
  - **REPLAY_SERVED** (работают над записью): `events_page`, `events`, `telemetry_snapshot`, `telemetry_history`, `await_condition` (offline-семантика §5.1), `system_overview` (записанный, с `"recorded": true`), `state_get` / `state_get_subtree` (из read-model: точный путь / префикс по flatten-снимку), `record_status`, `record_unload`.
  - **Все остальные** (IPC/write/subscribe) → обучающая ошибка: `«offline-реплей записи <name>: инструмент требует живой системы — record_unload() для возврата к live»` — НЕ сырое «not connected».
- Часы реплея: detached-driver получает `TelemetryReadModel(clock=player.now)` (additive-шов §6 Step 1) — точки истории несут **записанные** ts, а не время загрузки.

**Отклонено:** отдельный класс `ReplayReadModel` с собственными snapshot/history/await (дублирование трёх читателей + дрейф семантики); прогрузка записи в живой driver (смешение записанных и живых событий в одних кольцах — неотличимо для читателя).

## 4. Формат файла записи (JSONL, Dict at Boundary)

Один файл = одна запись. Строки — JSON-объекты (`ensure_ascii=False`, по строке на событие):

```jsonl
{"format": "bctl-record", "version": 1, "created_ts": 1789000000.0,
 "endpoint": {"host": "127.0.0.1", "port": 8765}, "session": "a1b2c3d4e5f6",
 "subscriptions": [ {"command": "state.subscribe", "target": "ProcessManager", "args": {...}} ],
 "snapshot": {
   "overview":  { ...результат system_overview()... },
   "state":     { ...state.get_subtree("") — полное дерево (dict)... },
   "telemetry": {"values": {"processes.cam.state.fps": 30, ...},
                 "history": {"processes.cam.state.fps": [[ts, v], ...], ...}},
   "events_stats": { ...events_stats() на момент старта... }
 }}
{"seq": 1, "ts": 1789000000.123, "event": { ...оригинальный push-dict бит-в-бит... }}
{"seq": 2, "ts": 1789000000.456, "event": { ... }}
{"footer": true, "stopped_ts": 1789000060.0, "events_written": 2, "dropped": 0,
 "reason": "stopped"}
```

- **Header (строка 1):** версия формата (несовместимое изменение → bump + отказ грузить чужую версию с обучающим текстом), endpoint/session (провенанс), активные подписки (`export_subscriptions` — видно, ЧТО вообще писалось), снимок: overview + полное state-дерево + telemetry (values + history с ts) + events_stats.
- **Событийные строки:** пишется **только arrival-плоскость** (оригиналы в порядке прихода; `seq` — собственный плотный счётчик recorder'а, `ts` — время приёма). Плоскостные кольца при загрузке восстанавливаются тем же `_classify` — хранить их отдельно значило бы завести второй источник правды.
- **Footer:** маркер чистого завершения + `reason ∈ {stopped, limit, disconnect}` + счётчик потерь очереди writer'а. Файл без footer = запись оборвана жёстко (crash) — при загрузке это честно сообщается (`"truncated": true`), но грузится всё разобранное.
- Реплей стартового состояния: `telemetry.values` + flatten(state-дерево → dotted-пути) → `prime()` read-model; `telemetry.history` → `import_history()` (Step 1). Дальнейшие событийные строки — дельты поверх.

## 5. Развилки дизайна (решения предложены; финальное слово — владельца, §Записка)

### 5.1. Offline-семантика `await_condition` (вопрос §3 родителя) — «прокрутка до попадания»

Живой `await_condition` ждёт будущего; над записью будущее — это остаток ленты. Семантика:

1. Проверить условие на **текущем достигнутом состоянии** read-model (`initial_check` — тот же код) → мгновенный успех, лента не двигается.
2. Иначе — **прокручивать playhead**: подписать `_Waiter.offer` на hub detached-driver'а и качать события лентой (`_emit_event` в вызывающем потоке — подписчики синхронны, wall-clock ожидания НЕТ) до попадания либо конца записи.
3. Попадание → обычная форма успеха + секция `"replay": {"position": <seq>, "of": <total>}`. Playhead ОСТАЁТСЯ на месте попадания — снимок/история после await показывают состояние «на момент срабатывания» (это и есть тайм-трэвел: await = навигация по ленте).
4. Конец записи без попадания → таймаут-эквивалент: `{"success": False, "timed_out": True, "end_of_recording": True, "waited", "events_seen", "last_seen", ...}` — та же диагностика, что вживую; параметр `timeout` в offline игнорируется (нечего ждать — задокументировать в описании инструмента).

Предикаты и `_Waiter` переиспользуются из `conditions.py` (настройщики — модульные функции, §2 п.3); offline-обвязку (прокрутка вместо `wait(timeout)`) держит `recorder.py`.

### 5.2. Позиция загрузки: `record_load(name, position="end"|"start")`, дефолт `"end"`

- `"end"` (дефолт): прогрузить снимок + всю ленту сразу — агент немедленно видит финальное состояние (`snapshot`/`history` полные, `events_page` листает ленту с начала в пределах кольца). Типовой сценарий «разобрать, чем кончилось».
- `"start"`: только снимок header'а, playhead = 0 — чистый тайм-трэвел: агент двигает ленту `await_condition`'ами (§5.1) и смотрит промежуточные состояния.
- Кольца detached-driver'а: `event_queue_maxlen = min(число событий записи, 10_000)` (переопределяемо аргументом `ring_maxlen`) — длинная запись при `"end"` честно показывает вытеснение через `dropped`/`evicted`, как вживую.

### 5.3. Чёрный ящик (вопрос §4 родителя) — split: дешёвая половина сейчас, авто-dump — follow-up

- **В этот план входит `record_dump(name)`** — one-shot дамп «что driver видел»: header-снимок + текущее содержимое arrival-кольца как событийные строки (`reason: "dump"`). Кольцо УЖЕ есть (EventHub — и есть always-on чёрный ящик в пределах maxlen); дамп — это тот же writer-код на готовых данных, ~ноль дополнительной цены. Покрывает сценарий «система умерла — сохрани, что успел увидеть».
- **Авто-dump при обрыве соединения — follow-up:** требует хука в teardown reader-потока/`close()` ([driver.py:849](../backend_ctl/driver.py#L849)) + env-флага + аккуратности с потоками при умирании транспорта — отдельная маленькая задача после обкатки формата, чтобы не тащить рискованную половину в первый заход. Обоснование: ценность авто-dump'а без обкатанного `record_load` нулевая, а поверх готового writer'а он тривиален.

### 5.4. Границы и безопасность (вопрос §5 родителя)

- **Safety-классы:** все `record_*` → `SAFETY_READ` — бэкенд не мутируется вообще (запись — локальный наблюдатель hub'а; загрузка — session-локальный режим). `record_unload` тоже read (возврат к live ничего не пишет).
- **Файлы — только в отведённом каталоге:** MCP-инструменты принимают `name` (не путь); сервер резолвит в `BACKEND_CTL_RECORD_DIR` (default `./backend_ctl_records/`), валидация имени (без разделителей/`..`) — агент не может писать/читать произвольные пути. Driver/recorder-API (не-MCP) принимает настоящий `path` — для тестов и harness.
- **PII/секреты:** header несёт полное state-дерево — там могут быть пути, конфиги, параметры рецептов. Решение v1: **без редакции** — инструмент dev-only, файл локален (тот же trust-домен, что логи), редакция по glob-маскам — YAGNI до реального кейса. В AGENTS.md/README — явное предупреждение «запись содержит состояние системы, не прикладывать к публичным issue».
- **Размер:** `record_start(name, max_events=100_000)` (+ мягкий `max_bytes≈200MB`) — по достижении лимита запись авто-останавливается с `reason: "limit"` (файл валиден). Ротация отклонена: одна запись = один конечный файл, flight-recorder сессия коротка по природе.
- **Откат:** новые инструменты аддитивны, бэкенд не трогается, replay-режим session-scoped → откат = не звать `record_*` (та же дисциплина, что `--http` в D.2); FW-флаг не нужен. Единственная правка framework (Step 1) — аддитивная с дефолтами бит-в-бит (`clock=time.time`).

---

## 6. Steps по файлам (по-коммитно; тест — в том же коммите, ПЕРЕД правкой где применимо)

1. **`multiprocess_framework/modules/telemetry_readmodel_module/` — additive-швы** (Layer: framework, module contract: **public-api-change**): (а) параметр конструктора `clock: Callable[[], float] = time.time`, `_record_history` берёт `self._clock()` ([telemetry_read_model.py:208](../multiprocess_framework/modules/telemetry_readmodel_module/telemetry_read_model.py#L208)); (б) `export_history() -> dict[str, list[tuple[float, float]]]`; (в) `import_history(data)` (восстановление буферов с записанными ts, maxlen соблюдается). Контракт-тесты: дефолтный clock бит-в-бит (пин существующего поведения), round-trip export→import, `interfaces.py`/README/STATUS модуля обновлены.
2. **`backend_ctl/recorder.py` (новый) — формат + writer:** константы формата (`FORMAT`, `VERSION=1`); `RecordWriter` (header/event/footer, `ensure_ascii=False`, flush по батчу, fsync на stop); `Recorder` — подписчик hub'а (`drv.subscribe`, колбэк лёгкий: только enqueue в bounded-deque; счётчик потерь → footer.dropped) + writer-поток; `stop(reason)` идемпотентен; лимиты §5.4. Сбор header'а: `system_overview()` + `state.get_subtree("")` + telemetry values/history (под `_telemetry_lock`, через `export_history` Step 1) + `export_subscriptions()` + `events_stats()`. Unit-тесты на fake-driver.
3. **`backend_ctl/recorder.py` — loader + detached driver:** `load_recording(path)` (парсинг, валидация версии, `truncated`-детект); `ReplayPlayer`: фабрика неподключённого `BackendDriver` (подмена `_telemetry_model` на clock-aware инстанс ДО прокрутки; `_ingest_state_changed` уже подписан из `__init__` — путь единый), prime снимка (values + flatten state-дерева + `import_history`), playhead/`pump(n)`, `position="end"|"start"` (§5.2). Тест: запись из Step 2 грузится, `telemetry_snapshot`/`telemetry_history`/`events_page` отвечают по записи, ts истории — записанные.
4. **`backend_ctl/recorder.py` — offline `await_condition` (§5.1):** переиспользование `_setup_*`/`_Waiter` из `conditions.py` (экспортировать их публично из модуля — сейчас underscore); прокрутка до попадания / `end_of_recording`; секция `"replay"` в ответе. Тесты: успех по достигнутому состоянию (лента не двинулась), успех с прокруткой (playhead на месте попадания, snapshot после = состояние момента), EOF-диагноз, `event_matches` по плоскости.
5. **`backend_ctl/mcp_driver_session.py` — режим replay + владение recorder'ом:** `DriverSession.mode`, `start_recording`/`stop_recording` (recorder привязан к текущему driver'у; `reset()` финализирует активную запись `reason="disconnect"` ДО закрытия — файл не остаётся без footer'а), `load_replay`/`unload_replay` (подмена driver'а §3; `ensure()` в replay не коннектится и не пробит isolation). Тесты на fake-driver-factory.
6. **`backend_ctl/mcp_tools.py` — 5 инструментов:** `record_start(name, max_events?)`, `record_stop()`, `record_status()` (активная запись: файл/счётчики; загруженный реплей: имя/позиция/total), `record_load(name, position?, ring_maxlen?)`, `record_unload()` (+ `record_dump(name)` — §5.3, тем же PR). `TOOL_SAFETY` — все read (§5.4); резолв `name`→путь в `BACKEND_CTL_RECORD_DIR` + валидация имени; REPLAY_SERVED-маршрутизация и обучающая ошибка для остальных инструментов в replay-режиме (§3). Тесты: safety-пин, path-confinement, ошибка offline-инструмента.
7. **Сквозной контракт-тест (acceptance родителя):** живой fake-бэкенд (существующий стиль `tests/test_driver`/`conftest`) → `record_start` → активность (state-дельты/логи/телеметрия) → `record_stop` → **новый процесс-контекст без живой системы**: `record_load` → `snapshot`/`history`/`await_condition` отвечают по записи (оба `position`); файл без footer'а → `truncated: true`, но грузится.
8. **Docs + ревью:** `backend_ctl/AGENTS.md` + `README.md` (новые инструменты, offline-режим, предупреждение о содержимом записи, env `BACKEND_CTL_RECORD_DIR`) — **обязательный шаг, известная граблина отставания агентских доков**; `DECISIONS.md` → **BCTL-ADR-006** (единый read-model через detached-driver + playhead-семантика offline-await; отклонённые альтернативы §3); `CAPABILITIES.yaml` — не меняется (новых backend-команд нет; общий долг регенерации на рабочем харнессе остаётся за D.1/D.5). Формальный `/code-review` high → merge.

---

## 7. Контракт-тесты (сводно)

- **Round-trip (ядро):** записанная лента → загрузка → `telemetry_snapshot`/`telemetry_history` (с записанными ts!)/`events_page`/`await_condition` эквивалентны наблюдению вживую; плоскости восстановлены тем же `_classify` (пин: событие `observability.record` смешанного батча расщепляется при реплее так же, как вживую).
- **Offline-await:** мгновенный успех по достигнутому состоянию; прокрутка до попадания + позиция; `end_of_recording`-диагноз с `events_seen`/`last_seen`; `timeout` игнорируется (нет wall-clock ожидания).
- **Изоляция режимов:** в replay-режиме write/IPC-инструменты дают обучающую ошибку (не «not connected»), `record_unload` возвращает live; replay-driver никогда не зовёт `connect`.
- **Writer-дисциплина:** колбэк recorder'а не блокирует reader (только enqueue); переполнение очереди → `dropped` в footer, не тихая потеря; `reset()` сессии финализирует запись footer'ом `disconnect`; лимит `max_events` → авто-stop `limit`.
- **Формат:** незнакомая `version` → обучающий отказ; файл без footer → `truncated: true` + загрузка разобранного; header-снимок восстанавливает состояние ДО первого события.
- **Framework-шов:** дефолтный `clock` — бит-в-бит прежнее поведение (характеризация до правки); `export_history`/`import_history` round-trip.
- **Safety/границы:** все `record_*` = read; `name` с `../`/разделителями → отказ.

## 8. Риски

| Риск | Митигация |
|---|---|
| Тяжёлый header (полное state-дерево) на большом бэкенде | однократный вызов существующей ручкой (тот же вес, что `state_get_subtree("")` сегодня); best-effort: недоступная секция снимка → честная пометка в header, запись не срывается |
| Колбэк записи тормозит reader-поток | контракт «только enqueue» + writer-поток; потеря очереди видима в footer.dropped (пин §7) |
| Реплей длинной записи выталкивает ранние события из колец | `ring_maxlen` §5.2 + видимые `dropped`/`evicted` — та же честная семантика потери, что вживую |
| ts истории при реплее = время загрузки | шов `clock` (Step 1) — единственная правка framework, аддитивная, с характеризационным пином |
| Запись без активных подписок = пустая лента | `record_start` возвращает `subscriptions` из header + `hint`, если список пуст («активируй watch_like_gui/state_subscribe») — не авто-подписка (запись не должна молча менять топологию наблюдения) |
| `supervisor.recovered` в ленте ротирует gen курсоров при реплее | поведение идентично живому (§8 D.1) — задокументировать; курсор агента получает штатный `reset_required` |
| Секреты/PII в файле записи | §5.4: dev-only, локальный каталог, предупреждение в доках; редакция — YAGNI до кейса |
| Дрейф формата в будущем | `version` в header + отказ грузить незнакомую версию с обучающим текстом |

## 9. Acceptance / DoD (из родителя + план)

- [x] записанная сессия грузится в read-model **без живой системы**; `snapshot`/`history`/`await_condition` отвечают по записи (сквозной тест Step 7)
- [x] offline-`await_condition`: успех по состоянию / прокрутка / `end_of_recording` — семантика §5.1 запинена тестами
- [x] запись не деградирует живую сессию (лёгкий колбэк, потери видимы) и корректно финализируется на всех путях (stop/limit/disconnect)
- [x] MCP: `record_start`/`record_stop`/`record_status`/`record_load`/`record_unload`/`record_dump`, все SAFETY_READ, path-confinement; в replay-режиме прочие инструменты отказывают обучающе
- [x] framework-шов clock/`export_history`/`import_history` — аддитивен, дефолт бит-в-бит, контракт-тесты модуля зелёные
- [x] `AGENTS.md`/`README` обновлены; BCTL-ADR-006 записан; `python scripts/validate.py` чист; sentrux baseline→delta не хуже (трогается framework-модуль)
- [ ] формальный `/code-review` high (финдеры Sonnet, оценка Fable, 8 углов) — находки закрыты до merge (оркеструет родитель)

## Резидуалы ревью

Находки формального ревью, **осознанно не закрытые** в заходе `fix/d4-review` (обязательные
1-5, 7, 9 закрыты там же). Здесь — то, что требует отдельного решения или объёма.

### R1. Реплей примируется полным state-деревом — богаче живого read-model

`recorder.py` (`ReplayPlayer._prime`) заливает в read-model ПОЛНОЕ state-дерево из
header-снимка, тогда как живой read-model содержит только пути, реально пришедшие
дельтами. Следствие: `telemetry_snapshot()` над записью богаче живого, а
`await_condition` в реплее может сработать мгновенно там, где вживую пришлось бы ждать
первой дельты — то есть тайм-трэвел оптимистичнее реальности.

Варианты: (а) задокументировать в BCTL-ADR-006 как осознанный компромисс («снимок — это
стартовое состояние, а не лента»); (б) не писать историю на prime-пути вне
`telemetry.values`, оставив дерево только для `state_get`/`state_get_subtree`.
Решение за владельцем — это семантика тайм-трэвела, не дефект реализации.

### R2. `load_recording` читает файл дважды в память

`recorder.py` (`load_recording`) держит одновременно список сырых строк и список
разобранных объектов. При штатном `max_bytes=200MB` это несколько ГБ объектов на один
`record_load`, без предупреждения. Двойное чтение не случайно: оно нужно, чтобы отличить
битую СРЕДНЮЮ строку (порча файла) от оборванного ХВОСТА (crash) — по ходу потокового
чтения этого не различить. Минимум — предупреждать по размеру файла; полноценно —
потоковый разбор с однострочным look-ahead.

### R3. Тесты recorder'а идут по удобным путям

Во всех четырёх тестовых модулях «живой» бэкенд — тот же detached `BackendDriver`,
поэтому `collect_header` возвращается мгновенно error-dict'ами. Как следствие:

- ветка `"value"` в `_extract_state_tree` / `_flatten_tree` / `_prime` не исполняется
  ни разу — реальная форма ответа `state.get_subtree` не покрыта;
- не покрыты: отказ `write_footer` (ENOSPC), fallback `stop()` при истёкшем
  `join(timeout=5.0)`, лимит `max_bytes`;
- `test_queue_overflow_counts_dropped` набивает `rec._queue` руками — пинит
  реализацию, а не поведение.

Окно старта записи и гонка параллельного `record_start` покрыты регресс-тестами в
`fix/d4-review`; остальное из списка — долг.

## Порядок исполнения

0. **Владелец отвечает на §Записку (ниже).** ← гейт, код до этого не пишется
1. Ветка `feat/bctl-d4-flight-recorder`; `sentrux session_start` (baseline — трогаем framework-модуль).
2. Step 1 (framework-шов, с характеризацией до правки) → Steps 2–4 (`recorder.py`) → Steps 5–6 (MCP) — по одному коммиту, `Refs: plans/backend-ctl-debug-console.md, plans/backend-ctl-d4-flight-recorder.md`, `Layer:` по шагу (Step 1 — framework, прочие — tools/mixed).
3. Step 7 — сквозной acceptance-тест.
4. Step 8: docs + BCTL-ADR-006 → `/code-review` high → `sentrux session_end` → merge (owner-gated).

---

## Записка владельцу — РАТИФИЦИРОВАНО (2026-07-19)

**Все 6 пунктов приняты дефолтами Fable:** (1) detached-driver read-model — ✅; (2) offline-await = навигация playhead'ом — ✅; (3) `record_load` дефолт `position="end"` — ✅; (4) чёрный ящик split — `record_dump` в этом плане, авто-dump на обрыв → follow-up — ✅; (5) safety=READ + файлы только в `BACKEND_CTL_RECORD_DIR` по имени + без PII-редакции в v1 — ✅; (6) единственная аддитивная правка framework (`telemetry_readmodel_module`: `clock` + export/import history, дефолт бит-в-бит) — ✅ допущена. Гейт открыт.

<details><summary>Исходные вопросы (для истории)</summary>

1. **§3 Единый read-model через detached-driver.** Реплей качает события через тот же `_emit_event`, что живой транспорт; неподключённый `BackendDriver` уже умеет всё нужное (верифицировано: `request()` без сокета отдаёт error-dict, не бросает). Альтернатива (отдельный ReplayReadModel) отклонена как второй источник правды. Подтверди подход.
2. **§5.1 Offline-await = навигация playhead'ом.** `await_condition` над записью прокручивает ленту до попадания и ОСТАВЛЯЕТ позицию там (snapshot после — состояние момента срабатывания); конец ленты → `end_of_recording`-диагноз. Это ядро тайм-трэвела.
3. **§5.2 Дефолт `record_load` — `position="end"`** (сразу финальное состояние; `"start"` — для пошагового тайм-трэвела). ОК?
4. **§5.3 Чёрный ящик split:** one-shot `record_dump` — в этом плане (почти бесплатен поверх writer'а); авто-dump на обрыв соединения — follow-up (хук в teardown транспорта, отдельный маленький заход). ОК?
5. **§5.4 Safety и PII:** все `record_*` = SAFETY_READ; файлы только в `BACKEND_CTL_RECORD_DIR` по имени (не пути); редакции state в v1 нет (dev-only, локальный файл, предупреждение в доках). Подтверди, что редакция не нужна сейчас.
6. **Step 1 — единственная правка framework** (telemetry_readmodel_module: `clock` + export/import history, аддитивно, дефолты бит-в-бит). Без неё история при реплее несёт ложные ts. Подтверди допуск в framework-слой.

</details>
