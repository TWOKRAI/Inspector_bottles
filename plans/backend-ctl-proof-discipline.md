# backend-ctl-proof-discipline — доказательность, сплит, приговоры

> Slug: `backend-ctl-proof-discipline` · Ветка: `fix/backend-ctl-proof-discipline` · Создан 2026-07-21
> Основание: архитектурное ревью backend_ctl 2026-07-21 (Fable), принято владельцем.
> Эталон формата и закрытия: `plans/_archive/2026-07-20_backend-ctl-hardening.md` (16/16 за один заход).

## Статус документа: единственный план backend_ctl

**Этот файл поглощает все планы инструмента.** Решение владельца 2026-07-21: один большой подробный документ вместо семи, чтобы ничего не терялось между треками. Шесть предшественников уходят в архив (Task 0.1), их незакрытые хвосты перенесены сюда целиком:

| Поглощённый план | Что от него осталось живого | Куда легло здесь |
|---|---|---|
| `backend-ctl-hardening` | ничего (16/16 закрыт) | — (архив, эталон формата) |
| `backend-ctl-debug-console` | ничего (Phases C/D/E/F закрыты) | — (архив) |
| `backend-ctl-d1-session-isolation` | ничего | — (архив; session-identity несущая, **не удалять код**) |
| `backend-ctl-d2-streamable-http` | ничего | — (архив; заморожен, см. «НЕ входит») |
| `backend-ctl-d4-flight-recorder` | приговор с критерием | **Task 4.2** |
| `backend-ctl-framework-module` | сплит, live-тесты, доки, переезд, DEFER'ы | **Фаза 2, Фаза 6, разделы «За внешним гейтом» и «Отложено с блокерами»** |

Правило дальше: **один активный план на инструмент**. Новая задача по backend_ctl вносится сюда, а не отдельным файлом — именно раздельность треков дала дефект «D.4 построил отменённое GATE G3».

Смежный активный план — [`plans/transport-single-policy.md`](transport-single-policy.md) — этому правилу не противоречит: это план транспорта (продукт), а не инструмента. Разграничение по провенансу и общий файл `g7_soak_probe.py` — см. «Порядок и зависимости».

**Что из поглощённого framework-module действует как решение (не пересматривается):**

- **Фаза 2 здесь = «сплит на текущей раскладке отдельным заходом»** (решение владельца 2026-07-17, секвенция hardening → сплит → post-codemod переезд). Не новое решение — исполнение записанного.
- **Директива «сделать красиво»** (вычистить хеши коммитов, ревью-пометки, inline-номера задач; оставить только «почему»-комментарии) применяется внутри задач сплита, не отдельным проходом.
- **Продукт-first:** фичи строятся на текущей раскладке `backend_ctl/`, в `modules/` не извлекаются; переезд отложен целиком до пост-codemod.

---

## Фаза 0 — Гигиена треков и документация (параллельно Фазе 1, не блокирует)

### Task 0.1 — Архив шести поглощённых планов + строка в QUEUE.md
**Level:** Middle (Haiku/Sonnet)
**Assignee:** docs-writer
**Goal:** Шесть планов инструмента уходят в архив; этот файл остаётся единственным; очередь планов знает о нём.
**Files:**
- `plans/backend-ctl-hardening.md` → `plans/_archive/2026-07-20_backend-ctl-hardening.md`
- `plans/backend-ctl-debug-console.md` → `plans/_archive/2026-07-19_backend-ctl-debug-console.md`
- `plans/backend-ctl-d1-session-isolation.md` → `plans/_archive/2026-07-19_backend-ctl-d1-session-isolation.md`
- `plans/backend-ctl-d2-streamable-http.md` → `plans/_archive/2026-07-19_backend-ctl-d2-streamable-http.md`
- `plans/backend-ctl-d4-flight-recorder.md` → `plans/_archive/2026-07-19_backend-ctl-d4-flight-recorder.md`
- `plans/backend-ctl-framework-module.md` → `plans/_archive/2026-07-21_backend-ctl-framework-module.md`
- `plans/QUEUE.md` (трек backend_ctl: шесть строк схлопываются в одну — этот план)
- `docs/claude/memory/feedback_one_active_plan_per_tool.md` (+ dual-write в локальную память, + строка в оба MEMORY.md)

**Steps:**
1. `git mv` шести файлов (имена с датой закрытия, как выше); внутренние ссылки поправить `link-check`'ом.
2. В шапку каждого архивируемого — строка «поглощён `plans/backend-ctl-proof-discipline.md` 2026-07-21», чтобы переход по старой ссылке вёл к живому документу.
3. `QUEUE.md`: в треке «backend_ctl + телеметрия» таблица из шести строк заменяется одной со ссылкой сюда; телеметрийные планы остаются как есть (другой трек).
4. Память: правило «один активный план на инструмент» + why (D.4 против GATE G3; сплит «можно сейчас» простоял, пока файл рос на 500 строк).

**Acceptance criteria:**
- [ ] `ls plans/backend-ctl-*.md` показывает ровно 1 файл — этот
- [ ] Ни один незакрытый пункт архивируемых планов не потерян: сверка чекбоксов `[ ]` шести файлов против разделов этого плана (сверку приложить к коммиту)
- [ ] `/core:quality:link-check` чист по `plans/` и `backend_ctl/`
- [ ] `QUEUE.md` ссылается на этот план; memory-запись создана в обоих местах

**Out of scope:** правка содержимого архивируемых планов, кроме строки-указателя в шапке.

### Task 0.2 — AGENTS.md: класс слепоты «драйвер входит мимо receive-мидлвари»
**Level:** Middle (Sonnet)
**Assignee:** docs-writer (факт перепроверен координатором)
**Goal:** Ограничение инструмента названо там, где его прочтёт агент перед работой.
**Files:** `backend_ctl/AGENTS.md`, `backend_ctl/README.md` (сноска к «шлёт те же router-сообщения, что GUI»).

**Steps:**
1. В AGENTS.md — раздел «Чего драйвером проверить НЕЛЬЗЯ»: inbound идёт push'ем `on_inbound → router.request → _deliver_by_targets`, минуя `receive()`/`_recv_mw` хоста (`socket_channel.py:248-254` — осознанный no-op `poll()`); значит fence-фильтр и contract-check команды драйвера **не судят**, и инъекцией через драйвер нельзя тестировать фильтры приёма. Драйвер также не штампует `_fence`.
2. Там же: «если понадобится судимость драйвер-трафика — это отдельное решение („парадная дверь“ через system-очередь хоста), не „оно и так работает“».
3. В README поправить «те же сообщения, что GUI» → «та же форма сообщений; путь приёма отличается (см. AGENTS.md)».

**Acceptance criteria:**
- [ ] Абзац ссылается на память `project_backend_ctl_socket_bypasses_mw` и на файлы/строки механизма
- [ ] README не обещает эквивалентность пути GUI

**Out of scope:** реализация «парадной двери» (см. «Что сознательно НЕ входит»).

---

## Фаза 1 — P0: строгий край (первое)

### Task 1.1 — Строгий край `protocol.py`: отсутствующее поле ≠ ноль
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Типизированные обёртки перестают молча подставлять 0/дефолт вместо отсутствующих данных.
**Files:** `backend_ctl/protocol.py`, `backend_ctl/driver.py` (потребители `router_stats`/`queues`/`worker_status`/`introspect_memory`), `backend_ctl/overview.py`, `backend_ctl/probes/g7_soak_probe.py`, `backend_ctl/tests/test_wrappers.py`, `backend_ctl/tests/test_overview.py`.

**Steps:**
1. `RouterStats` / `QueueDepths` / `WorkerStatus` / `MemoryStats`: числовые поля → `Optional[int]`, плюс поле `missing: List[str]` — имена ключей, которых не было в ответе (сейчас `protocol.py:91-94` — `int(stats.get("sent_ok", 0) or 0)`).
2. `unwrap(res, *keys)`: ключи не найдены за 4 уровня → возвращаемый dict несёт служебный признак (`_unwrap_miss: [keys]`), а не молча `res` (сейчас `protocol.py:36-50`).
3. `overview.py`: anomalies-проверки становятся None-safe; «счётчик отсутствует» — сам по себе anomaly (`counter_missing`), а не тихий пропуск.
4. Потребители в `driver.py` и пробах — под новый контракт.

**Acceptance criteria:**
- [ ] Пара ON/OFF: ответ с полем → значение и `missing == []`; ответ с переименованным полем → `None` + имя в `missing` (unit на оба плеча)
- [ ] `system_overview` на подставном ответе без `router_stats` показывает `counter_missing`, не «0 и тишина»
- [ ] Live: `router_stats("ProcessManager")` на живом харнессе — `missing == []` (форма сервера сверена делом)
- [ ] Весь unit-suite backend_ctl зелёный

**Out of scope:** серверные счётчики провенанса (`connected`/`last_increment`); вердикты `BLIND_SPOT` / `path_active` в soak-пробе — это Task 3.1 транспортного плана (см. «Порядок и зависимости»). Правка `g7_soak_probe.py` здесь — только механическая адаптация к missing-контракту.

### Task 1.2 — Провенанс нулей телеметрии: `count=0` объявляет причину
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** «Нет данных», «нет подписки» и «путь не трекается» перестают быть одним и тем же нулём.
**Files:** `backend_ctl/driver.py` (telemetry read-model, ~1044-1178), `backend_ctl/tests/test_telemetry_driver.py`.

**Steps:**
1. Счётчик `ingested_total` в `_ingest_state_changed` (под `_telemetry_lock`).
2. `telemetry_snapshot`: в ответ — `ingest_active` (есть ли живое durable-намерение `state.subscribe`), `ingested_total`.
3. `telemetry_history`: в ответ — `tracked: bool` (путь входит в трекаемые суффиксы read-model), тот же `ingest_active`.

**Acceptance criteria:**
- [ ] Пара ON/OFF: без подписки → `count=0, ingest_active=false`; после `watch_like_gui` на живом харнессе → `ingest_active=true, ingested_total > 0` (live)
- [ ] `telemetry_history("не.трекаемый.путь")` → `tracked=false` (unit)
- [ ] Существующие telemetry-тесты зелёные без смысловых правок

**Out of scope:** новые метрики, изменение ingest-семантики.

### Task 1.3 — Guard: `request()` из reader-потока — немедленная обучающая ошибка
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Дедлок-конвенция «не звать `request()` из подписчика» превращается из докстринга в enforcement.
**Files:** `backend_ctl/transport.py` (`request()`, ~127), `backend_ctl/tests/test_transport_guard.py`.

**Steps:**
1. В `request()`: `threading.current_thread() is self._reader` → немедленный `{"success": False, "error": ...}` с обучающим текстом (очередь намерений + applier-поток, ссылка на паттерн `WatchController`). Error-dict, не исключение — контракт BCTL-ADR-003.
2. Тест: подписчик hub'а зовёт `request()` → мгновенная ошибка (не таймаут); applier-поток и timer-поток commit-confirmed guard'ом НЕ ловятся.

**Acceptance criteria:**
- [ ] Пара: из reader → ошибка сразу (< default_timeout); из чужого потока → штатная работа
- [ ] Текст ошибки называет правильный паттерн (queue + applier)

**Out of scope:** переделка существующих подписчиков (они дисциплинированы).

### Task 1.4 — Имена метрик под сверку (расширение E.2 с команд на сигналы)
**Level:** Middle+ (Sonnet), ревью Reviewer (Opus)
**Assignee:** developer
**Goal:** Неизвестное имя метрики даёт громкий признак, а не пустой результат или вечное ожидание.
**Files:** `backend_ctl/conditions.py` (`metric_threshold`), `backend_ctl/driver.py` (`telemetry_set` / `telemetry_history`), `backend_ctl/tests/test_await_condition.py`, `backend_ctl/tests/test_telemetry_driver.py`.

**Steps:**
1. `metric_threshold`: при `initial_check`, если путь/суффикс не встречался среди наблюдённых путей read-model И не входит в трекаемые суффиксы — в диагноз таймаута и в немедленный ответ добавляется `unknown_metric: true` + список ближайших наблюдённых путей (difflib, зеркало BCTL-ADR-003).
2. `telemetry_set`: ответ сервера с `reached=0` / `target_count=0` дополняется клиентской подсказкой «метрика/процесс не достигнуты — проверь имя». Консервативно: **не блокируем**, только маркируем (как E.2, без ложных блоков).
3. Консервативность зафиксировать в докстринге: пустой свод / деградация → пропуск проверки.

**Acceptance criteria:**
- [ ] Пара: известная метрика → поведение бит-в-бит; опечатка → `unknown_metric: true` + кандидаты (unit)
- [ ] Таймаут `await_condition` по опечатке несёт `unknown_metric` в диагнозе (unit)
- [ ] Ложных блоков нет: легитимная, но ещё не публиковавшаяся метрика проходит с маркером, не с отказом

**Out of scope:** серверный реестр метрик (нет такой ручки; появится — сверять с ней).

### Task 1.5 — Правило «докажи ненуль» + образцовый live-тест
**Level:** Middle (Sonnet)
**Assignee:** developer + docs-writer
**Goal:** Каждый новый сигнал инструмента обязан быть показан отклоняющимся от дефолта хотя бы раз; приёмка гоночного/флагового поведения — только парой.
**Files:** `backend_ctl/DECISIONS.md` (BCTL-ADR-007), `backend_ctl/AGENTS.md` (чек-лист нового сигнала), `backend_ctl/tests/test_signal_liveness_live.py`.

**Steps:**
1. BCTL-ADR-007: «сигнал без доказанной способности к ненулю не считается подключённым». Чек-лист: (а) live-тест ненуля, (б) поле `missing`/провенанс, (в) имя сверяемо.
2. В ADR — живой прецедент приёмки-парой: **ADR-SS-019 / `b1a6ef37`** (гейт топологии: ON — 4/4 зелёных, OFF — призраки воспроизводятся 2/2). Пара ON/OFF ловит то, чего одиночный зелёный не ловит в принципе: одиночный зелёный при ON неотличим от «фикс ни на что не влияет».
3. Явная перекрёстная ссылка: правило распространяется и на счётчики, вводимые транспортным планом (двери `sent_via_channel` / `sent_via_targets`, `f64ba05e`, и последующие) — новый транспортный счётчик без live-ненуля не принимается.
4. Образцовый live-тест: на харнессе `send_command` → `router_stats` показывает `received > 0` и `sent_ok > 0` (сигнал физически двигается), `missing == []`.

**Acceptance criteria:**
- [ ] ADR в DECISIONS.md с прецедентом ADR-SS-019, чек-лист в AGENTS.md
- [ ] Live-тест зелёный 3/3 подряд

**Out of scope:** ретроактивная проверка всех 49 инструментов (правило действует вперёд; ретроспектива — по мере касания).

---

## Фаза 2 — Санкционированный сплит (исполнение решения владельца 2026-07-17)

> После Фазы 1: строгий край переезжает уже готовым, конфликтов правок нет. Live-якорь — методика C.1: `test_reconnect_live` + `harness_smoke` до и после каждого шага. Sentrux (если доступен): `session_start` до 2.1 → `session_end` после 2.2, не хуже baseline.

### Task 2.1 — Вынос `registers.py` из `driver.py` + «сделать красиво»
**Level:** Senior+ (Opus)
**Assignee:** teamlead
**Goal:** Регистровый аппарат D.5 (snapshot/restore/commit-confirmed/журнал) — отдельный владелец состояния по образцу `WatchController`; фасад возвращается к размеру после C.1.
**Files:** `backend_ctl/driver.py` (~485-880: `_read_registers`, snapshot/restore, `_set_register_confirmed`, `register_confirm`, `_auto_rollback`, `_record_rollback`, `register_rollback_log`, `_cancel_all_pending_commits`, `_PendingCommit`) → новый `backend_ctl/registers.py` (`RegisterOps`, композиция `self._registers = RegisterOps(self)`); `backend_ctl/STATUS.md`; тесты D.5 в `backend_ctl/tests/test_driver.py`.

**Steps:**
1. Перенос поведения бит-в-бит; driver-обёртки — тонкие делегаты (паттерн `watch.py`). `close()` продолжает снимать таймеры (`RegisterOps.stop()`).
2. Директива «сделать красиво» на вынесенном коде: убрать хеши коммитов, «ревью #N», inline-пометки «Task X.Y» / «Ф1.6»; оставить «почему»-комментарии (инварианты: pre-image до записи, readback до арминга, pop-арбитр гонки confirm/rollback). Докстроки без процессных хвостов.
3. STATUS.md: строка про `registers.py`, размер `driver.py` обновлён.

**Acceptance criteria:**
- [x] поведение бит-в-бит (514 unit зелёные БЕЗ правки тестов — back-compat через property `_pending_commits`/`_rollback_journal`); `wc -l driver.py` = 1323 (не ≤1200: 6 публичных обёрток обязаны остаться делегатами по Out-of-scope, ~68 строк не удаляются — вынос несвязанного кода запрещён брифом)
- [x] Live-якорь `test_reconnect_live` + `harness_smoke` зелёные до и после (3/3)
- [x] `grep -nE "Task [0-9]|ревью|Ф[0-9]\.[0-9]|[0-9a-f]{8}" backend_ctl/registers.py` пуст
- [x] Пометка в `plans/_archive/2026-07-21_backend-ctl-framework-module.md`: «сплит-заход выполнен, Refs: plans/backend-ctl-proof-discipline.md»

**Статус:** ✅ DONE (Task 2.1). registers.py + RegisterOps, driver.py 1672→1323.

**Out of scope:** переезд в `tooling/` (гейт codemod); вынос telemetry-блока; переименование публичного API.

### Task 2.2 — Вынос `dispatch.py` из `mcp_tools.py` + кэш реестра
**Level:** Middle+ (Sonnet), ревью Reviewer (Opus)
**Assignee:** developer
**Goal:** Диспетчеризация / усечение / replay-роутинг / record-handlers отделены от декларативного реестра инструментов.
**Files:** `backend_ctl/mcp_tools.py` (~1249-1582: `resolve_record_path`, `_ArgError`, record-handlers, `RECORD_HANDLERS`, `_REPLAY_*`, `_serve_replay`, `_cap_*`, `dispatch_tool`, `_session_log`) → новый `backend_ctl/dispatch.py`; `backend_ctl/mcp_server_sdk.py` (импорт); `backend_ctl/tests/test_recorder_mcp.py`, `test_phase_e_trust.py`.

**Steps:**
1. Перенос бит-в-бит; в `mcp_tools.py` остаются handlers + `TOOLS` + safety-политика (законный реестр).
2. Кэшировать `build_registry()` (сейчас перестраивается на каждый вызов — `mcp_tools.py:1532`); реестр иммутабелен после импорта.
3. «Сделать красиво» на вынесенном коде — те же критерии, что в 2.1.

**Acceptance criteria:**
- [ ] `tools/list` = 49 инструментов бит-в-бит; полный unit-suite зелёный
- [ ] grep процессных пометок по `dispatch.py` пуст
- [ ] MCP-смоук: initialize → tools/list → tools/call `capabilities` (subprocess, как в F.1)

**Out of scope:** изменение семантики byte-cap / replay; новые инструменты (запрещены до конца плана).

---

## Фаза 3 — Реалтайм-края

### Task 3.1 — RSS в `introspect.memory` (сервер) + поле в `MemoryStats`
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Имя инструмента перестаёт обманывать: инвентарь SHM/пула дополняется памятью процесса ОС.
**Files:** `multiprocess_framework/modules/process_module/commands/builtin_commands.py` (handler `introspect.memory`: секция `os: {rss, vms, pid}` через psutil по СВОЕМУ pid, best-effort — нет psutil → `None`), `backend_ctl/protocol.py` (`MemoryStats.os_memory`), `backend_ctl/probes/g7_soak_probe.py` (`_rss_mb` упростить до чтения ответа), тесты process_module + `test_wrappers.py`.
**Layer коммита:** `framework`.

**Acceptance criteria:**
- [ ] Live: `introspect_memory("ProcessManager").os_memory["rss"] > 0` — **PENDING живой прогон**
- [x] Секция best-effort: отсутствие psutil не ломает ответ (unit с подменой импорта) — `test_os_section_null_without_psutil`
- [x] Soak-проба больше не ходит за RSS отдельным psutil-путём — `_rss_mb` читает секцию `os` ответа

**Статус:** 🟡 unit DONE (пара ON/OFF psutil в process_module + `MemoryStats.os_memory` строгий край в test_wrappers), live-плечо RSS>0 ждёт живого прогона Фазы 3.

**Out of scope:** переименование команды (аддитивно достаточно); историзация RSS.

### Task 3.2 — `effective_hz` per-process в `system_overview`
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** «Один вызов = вся картина» перестаёт терять главный перф-сигнал.
**Files:** `backend_ctl/overview.py`, `backend_ctl/tests/test_overview.py`.

**Steps:** из уже собираемого `introspect_status` пробрасывать `effective_hz` (и `target_interval_ms`, если есть) в per-process сводку; аномалия `hz_degraded` при hz < доли target.

**Acceptance criteria:**
- [x] Unit на подставном статусе: hz в сводке, аномалия срабатывает/молчит (пара) — `TestEffectiveHz` (5 плеч)
- [x] Ответ остаётся под `RESPONSE_BYTE_CAP` на fake-своде 7 процессов — `test_seven_process_summary_under_byte_cap`

**Статус:** ✅ DONE (unit). Карточка несёт `hz` (ведущий effective_hz по воркерам), аномалия `hz_degraded` при `effective_hz < 50%` от `1000/target_interval_ms`; воркер без target порогом не судится.

**Out of scope:** `perf_probes` целиком (тяжёлые — по запросу per-process).

---

## Фаза 4 — Приговоры

### Task 4.1 — Удаление `debug_session` / `debug_stop`
**Level:** Middle (Sonnet)
**Assignee:** developer
**Goal:** Одна поверхность «включить всё» вместо двух дублирующих.
**Files:** `backend_ctl/driver.py` (~1429-1477), `backend_ctl/mcp_tools.py` (handlers, `TOOLS`, `TOOL_SAFETY`), `backend_ctl/README.md`, `backend_ctl/AGENTS.md`, тесты.

**Steps:** удалить сразу (потребители — только агенты, deprecation-период не нужен); в AGENTS.md таблицу режимов отладки переписать на `watch_like_gui` + `ui_tap` / `ui_tap_ping`.

**Acceptance criteria:**
- [ ] `tools/list` = 47; `grep -rn "debug_session\|debug_stop" backend_ctl/ docs/` пуст (вне архива планов)
- [ ] Сценарий совместной отладки в AGENTS.md воспроизводим live (watch + `ui_tap_ping`)

**Out of scope:** `_discover_processes` (остаётся — им пользуется watch).

### Task 4.2 — Условный приговор recorder'у: критерий и дата
**Level:** Middle (решение — владелец)
**Assignee:** Director (проверка), владелец (вердикт)
**Goal:** Заморозка D.4 превращается из отсрочки в проверяемое решение.
**Files:** `backend_ctl/DECISIONS.md` (приписка к BCTL-ADR-006), `docs/claude/memory/project_backend_ctl_recorder_probation.md`.

**Формулировка приговора (записать дословно):**
- Инвестиции в record/replay заморожены с 2026-07-21.
- **Критерий выживания:** до **2026-08-31** существует ≥1 реальный (не тестовый) случай отладки, где `record_load` / replay дал вывод, зафиксированный в `docs/audits/*` или memory-записи со ссылкой на файл записи (`BACKEND_CTL_RECORD_DIR`).
- **Проверка 2026-08-31:** `grep -rln "record_load\|record_start" docs/audits/ docs/claude/memory/` + опрос владельца. Нет случая → задача-триггер: удалить `recorder.py`, record-ветки `mcp_driver_session.py`, 5 инструментов (`record_start/stop/status/load/unload`) и их тесты. **`record_dump` оставить** (чёрный ящик — единственная дешёвая ценность поверх writer'а; при удалении writer'а переписать dump на прямой слив arrival-кольца, ~50 строк).

**Acceptance criteria:**
- [ ] Приписка в DECISIONS.md + memory-запись с датой проверки
- [ ] Дата проверки 2026-08-31 отражена в how-to-apply memory-записи

**Out of scope:** само удаление (только по исходу проверки).

---

## Фаза 5 — Доказательство fencing (переформа единственного красного live-теста)

### Task 5.1 — Fencing: заменить тест-гонку на пару «bump доказан» + unit-инвариант фильтра
**Level:** Middle+ (Sonnet)
**Assignee:** developer

**Ответ на вопрос формы: понизить.** E2E-тест в текущем виде требует исхода гонки (стейл-сообщение должно существовать в момент бампа, а `restart_process` добивает старый инстанс с подтверждением смерти ДО бампа — дропать штатно нечего). Детерминированная live-инъекция стейл-билета невозможна: драйвер входит мимо receive-мидлвари (Task 0.2), а тестовая «задняя дверь» в очередь противоречила бы инварианту «одна дверь». Требовать от теста исхода гонки — значит держать его вечно флаки-красным и приучаться игнорировать красное, что прямо вредит доказательности.

**Инвариант декомпозируется на три детерминированных плеча:**
1. **Live «bump доказан»:** `supervision_status` до/после `restart_process` → `incarnation` строго вырос, `epoch` вырос. Это та часть, которую действительно может и должен доказывать живой прогон.
2. **Unit-инвариант фильтра:** `make_fence_filter_middleware` — дроп при `inc < expected`, прозрачный проход при `>=` / без `_fence` / неизвестный sender; счётчик `fence_dropped` растёт (в `multiprocess_framework/modules/message_module/tests/`, дополнить недостающие плечи).
3. **Unit-проводка парой ON/OFF:** `FW_FENCE=ON` → `add_receive_middleware` получает fence-фильтр (fake-router, `builtin_commands.py:1688-1714`); `OFF` → не получает.

**Files:** `backend_ctl/tests/test_fencing_live.py` (переписать в плечо 1; старый тест удалить с комментарием-ссылкой на память `project_fencing_test_race`), тесты message_module (плечо 2), тесты process_module (плечо 3).

**Acceptance criteria:**
- [ ] Плечо 1 зелёное 3/3 подряд (детерминизм, без гонки)
- [ ] Плечи 2-3 зелёные, пара ON/OFF в плече 3 явная
- [ ] В плече 1 комментарий: e2e стейл-дропа вернуть, если появится «парадная дверь» (судимый receive-путь драйвера)

**Out of scope:** «парадная дверь»; правки самого fence-механизма (исправен — `bumped=True` доказан логом из точки решения).

---

## Фаза 6 — Наследство framework-module, доступное сейчас

> Эти задачи стояли в поглощённом плане как открытые и **не гейтятся codemod** — их отложили не по решению, а по инерции. Переносятся дословно по смыслу.

### Task 6.1 — Live-тесты флагманских фич (ex-Task 4.1 framework-module)
**Level:** Middle+ (Sonnet)
**Assignee:** developer
**Goal:** Фичи Phase 2 и telemetry-в-MCP получают живые доказательства вместо fake-transport.
**Files:** `backend_ctl/tests/test_telemetry_live.py`, `backend_ctl/tests/test_watch_like_gui_live.py` (или дополнение существующих live-suites).

**Контекст (почему важно):** 85% тестов инструмента — fake-transport; именно поэтому ultra-ревью нашло 23 бага в фичах, которые «покрыты». Task 0.5 (telemetry в MCP) и Task 2.1 (`observability_tail`) закрывались с явной пометкой «live-тест — в 4.1», и этот долг не отдан.

**Steps:**
1. Telemetry live: `telemetry_set` / `telemetry_reconfigure` → снимок показывает применённый gate (пара: до/после).
2. `watch_like_gui` live: подписки поднялись, `events()` содержит записи всех трёх плоскостей, доступных рецепту; для «тихих» плоскостей — явная фиксация, что тишина есть свойство рецепта (урок: black-box live-пруф для них невозможен, корректный уровень — unit-инвариант).
3. Reconnect live: durable-подписки восстановлены, reconnect-report доехал ровно один раз.

**Acceptance criteria:**
- [ ] Новые live-тесты зелёные локально (Windows, реальный spawn), 3/3 подряд
- [ ] `scripts/run_framework_tests.py` без регрессий
- [ ] Каждый новый сигнал в тестах удовлетворяет BCTL-ADR-007 (показан ненулевым)

**Out of scope:** новые фичи; ретроспективное покрытие всех 49 инструментов.

### Task 6.2 — Документация + CAPABILITIES-regen (ex-Task 4.2 framework-module)
**Level:** Middle (Haiku/Sonnet)
**Assignee:** docs-writer
**Goal:** Контракт инструмента и документация не расходятся с кодом после Фаз 1–4 этого плана.
**Files:** `backend_ctl/README.md`, `backend_ctl/AGENTS.md`, `backend_ctl/STATUS.md`, `backend_ctl/CAPABILITIES.yaml`.

**Steps:**
1. Перегенерировать `CAPABILITIES.yaml` (`dump_capabilities`) — после удаления `debug_session`/`debug_stop` (Task 4.1) и правок Фазы 1.
2. AGENTS.md: каждый MCP-инструмент упомянут; таблица режимов отладки без удалённых инструментов.
3. STATUS.md: новые файлы `registers.py`/`dispatch.py`, актуальные размеры.

**Acceptance criteria:**
- [ ] `dump_capabilities --check` чист (drift-gate зелёный)
- [ ] `link-check` чист; AGENTS.md упоминает каждый инструмент из `tools/list`
- [ ] `python -m scripts.sync` без дрифта

**Out of scope:** документация переезда в `tooling/` (за гейтом).

---

## За внешним гейтом codemod (не начинать; перенесено из framework-module целиком)

Эти две задачи ждут `framework-layer-grouping` Фазу 3 (codemod ~1970 импортов / 910 файлов, freeze-окно). Смысл ожидания: модуль должен родиться сразу в пост-codemod раскладке, без двойного переписывания шимов.

**Phase 1 / Task 1.1 — Скелет модуля + перенос driver-ядра.** Senior (Opus), teamlead, Layer: framework. Модуль `multiprocess_framework/tooling/backend_ctl/` по правилу №2 (README/STATUS/DECISIONS/interfaces.py); перенос по карте бит-в-бит; `interfaces.py` с `IBackendClient`/`IEventSource`/`ISubscriptionRegistry`; шимы re-export в `backend_ctl/`; `.importlinter` — слой `tooling` самый верх, `forbidden` на импорт `tooling`; контракт-тест границ (весь модуль не импортирует `multiprocess_prototype`). Приёмка: `pytest` обоих деревьев зелёный, `lint-imports` + `check_rules` чисты, старый импорт `from backend_ctl import BackendDriver` работает.

**Phase 1 / Task 1.2 — Generic harness + прототип-глю + перенос MCP-файлов.** Senior (Opus), teamlead, Layer: mixed. `launcher_factory` обязателен; `backend_ctl/proto_harness.py` собирает прототипную фабрику и экспортирует обёртку со старой сигнатурой (фикстуры live-тестов не меняются); MCP → `mcp/`, entrypoint `python -m multiprocess_framework.tooling.backend_ctl.mcp.server` + шим; `.mcp.json` правится один раз на финальный путь. Приёмка: MCP-смоук через оба entrypoint'а, 11 live-suites зелёные без правок фикстур.

**Важно при старте codemod:** rename-таблица плана layer-grouping не знает про переезд `backend_ctl → tooling/` и про `telemetry_readmodel_module` — пересобрать. Плюс в `plans/framework-layer-grouping/plan.md` добавить слой `tooling/` в целевую структуру и контракт import-linter.

**Сплит (Фаза 2 этого плана) ⟂ переезд:** сплит делается СЕЙЧАС на текущей раскладке, на codemod гейтится только `git mv` уже разбитых файлов.

---

## Отложено с блокерами (перенесено из framework-module; не воскрешать без снятия блокера)

| Пункт | Блокер | Условие возврата |
|---|---|---|
| **Task 2.3 — Telemetry read-model на generic-VM** | reuse-источник `TelemetryViewModel` появится только в coherence Task 3.5 | Task 3.5 плана `telemetry-coherence-remediation` в `main` |
| **Task 3.3 — `capabilities(concise)` / help-рендер** | опциональная идея владельца, плоскость закрыта и без неё | явный запрос владельца |
| **Task 3.1 — живой смоук MCP из Claude Code** | шаг владельца (`.mcp.json` уже на `mcp_server_sdk`; subprocess-smoke зелёный) | владелец прогоняет вручную; отражено в gate плана п.5 |
| **Вынос telemetry-блока из `driver.py`** | ~135 строк, не тянет на модуль | следующий рост фасада |

---

## Порядок и зависимости

```
Фаза 0 (docs) ─── параллельно ──┐
Фаза 1: 1.1 → 1.4;  1.2, 1.3 параллельно;  1.5 после 1.1-1.4
Фаза 2: 2.1 → 2.2   (после Фазы 1 целиком — сплит переносит уже-строгий код)
Фаза 3: 3.1 параллельно Фазе 2 (framework-файлы, не пересекаются); 3.2 после 2.2
Фаза 4: 4.1 после 2.2 (не конфликтовать со сплитом); 4.2 — сразу (запись решения)
Фаза 5: 5.1 после 0.2
Фаза 6: 6.1 после Фазы 1 (live-тесты сигналов — уже по строгому краю); 6.2 ПОСЛЕДНЕЙ (доки после всех правок)
```

**Гейт выхода плана:** закрыты Фазы 0–6. Раздел «За внешним гейтом codemod» в счёт закрытия НЕ входит — он ждёт чужого плана и переживёт этот документ (при закрытии перенести в новый или обратно в `framework-layer-grouping`).

**Стыковка с `plans/transport-single-policy.md` (третий активный план; транспорт, не backend_ctl):**

- **Независимость — подтверждено явно: Фаза 1 этого плана НЕ блокируется транспортной Фазой 1.** Default-0 в `protocol.py` и неразличимый `count=0` — клиентский край драйвера; они чинятся одинаково при одной двери или двух и не читают ничего из дескрипторов каналов. Это записанный аргумент делать P0 сейчас, не дожидаясь транспортных 1.1 → 1.2 (там жёсткий порядок) и невыполненного Task 0.2 (живой замер по дверям).
- **Владение провенансом — три яруса, без дублей:**
  1. *Клиентский строгий край* (типизированный `missing`, провенанс телеметрии, правило «докажи ненуль») — **этот план, Фаза 1, сейчас**.
  2. *Вердиктные счётчики soak-пробы* (`provenance: {present, path_active}`, вердикт `BLIND_SPOT` вместо CLEAN по LEAK-ключам) — **остаются Task 3.1 транспортного плана**: `path_active` честно выводится только из дескрипторов каналов его Task 1.2, раньше него это были бы эвристики по флагам — ровно то, что транспортный план запрещает.
  3. *Полный серверный провенанс всех наблюдаемых* (`connected` / `last_increment` у каждого счётчика) + слепые плоскости логов — как транспортный план и резервирует: **после закрытия транспорта, отдельным планом**. Ни один из двух текущих планов его не берёт.
- **Точка пересечения файлов: `backend_ctl/probes/g7_soak_probe.py`.** Task 1.1 правит её механически (адаптация к missing-контракту), транспортный Task 3.1 строит поверх вердикты. Порядок: 1.1 первым (транспортная Фаза 1 не начата), транспортный 3.1 ребейзится на новый контракт. Одновременная работа над файлом — только через worktree (память: `feedback_worktree_for_parallel_samefile`).
- **Перекрёсток правил:** BCTL-ADR-007 (Task 1.5) обязателен и для новых счётчиков транспортного плана — счётчик без live-ненуля не принимается ни в одном из планов.

Общие правила: максимум 2 агента без worktree (память: `feedback_parallel_agents_commit_race`); параллельные правки одного файла — только через git worktree. Каждый коммит: `Refs: plans/backend-ctl-proof-discipline.md`, `Why:`, `Layer: mixed` (backend_ctl) / `Layer: framework` (Task 3.1), `Tested:`. qex недоступен при лежащей Ollama — поиск только Grep/Read; после подъёма — `/mcp-qex:qex-reindex` до любого семантического поиска.

## Вход плана — ЗАМЕРЕНО 2026-07-21 (а не заявлено)

Черновик этого плана утверждал «на входе единственный красный — `test_fencing_live`». **Замер опроверг это**: полный live-прогон дал **3 красных**, и ещё один прогон до того дал 8 — из-за наложения двух suite'ов на порт 8765 (ловушка «двух бэкендов»; одиночный прогон обязателен). Разбор:

| Тест | Замер | Диагноз | Исход |
|---|---|---|---|
| `test_fencing_live` | красный 2/2 | гонка недоказуема детерминированно (память `project_fencing_test_race`) | остаётся входным красным → Task 5.1 |
| `test_subtree_delete_live` | красный 2/2 | **в плане не значился**; стоял на инварианте, отменённом ADR-SS-019 — `TopologyGateMiddleware` отклоняет выдуманное имя процесса | ЗАКРЫТ `ed64bec9` (путь ушёл в namespace вне `processes.*`) |
| `test_switch_honest_state_live` | красный в полном прогоне, зелёный в изоляции | план звал его зелёным; на деле порядко-зависимый — ассерт Ж-3 ловил подстроку `state.merge` внутри штатной строки fence-дропа | ЗАКРЫТ `bf6bede3` (ассерт сужен) |
| `test_build_characterization[phone_sketch, hikvision_letter_robot]` | красный на ветке, зелёный на main | регрессия `a7266fef` (M-1): идиома `.get("priority") or "normal"` сменила поведение, снапшоты не перегенерировали | ЗАКРЫТ `1e9268ef` |

Побочно закрыт дефект прозрачности, стоивший полного расследования: `TopologyGateMiddleware` был единственной мидлварью, не писавшей `rejection_reason` — отказ приходил безымянным `"middleware"` (`f58eff45`, теперь `"topology_gate"` + имя процесса, лог поднят с debug до warning).

**Урок в копилку BCTL-ADR-007:** утверждение о состоянии тестов — такой же сигнал, как счётчик, и подлежит тому же правилу «докажи замером». Три из четырёх строк выше опровергают написанное в плане.

## Верификация (gate плана)

1. Полный suite: `python -m pytest backend_ctl -q` — unit зелёные. Live: **на входе единственный красный — `test_fencing_live`** (снимается Task 5.1; состояние ДОСТИГНУТО фиксами выше, а не застано); на выходе плана live-suites зелёные полностью. Прогон live — **строго одиночный**: параллельный suite на том же порту даёт каскад `BackendUnavailable` и ложные красные.
2. `python scripts/validate.py` чист; `python -m pytest backend_ctl -m harness_smoke` 3/3.
3. Все гоночные/флаговые приёмки — **парой ON/OFF** (1.1-1.4, 5.1 плечо 3); одиночный зелёный не принимается.
4. Sentrux (если доступен): `session_start` до Фазы 2 → `session_end` после — не хуже baseline.
5. MCP-смоук из Claude Code: initialize → tools/list (47) → `capabilities` → `system_overview` (с hz).
6. `plans/`: два файла backend-ctl (спящий + этот), архив укомплектован, link-check чист.

## Что сознательно НЕ входит

- **Переезд в `tooling/`** — за гейтом codemod; задачи не выброшены, а перенесены сюда в раздел «За внешним гейтом codemod» (в гейт выхода плана не входят).
- **«Парадная дверь»** (inbound через system-очередь хоста, судимость драйвер-трафика receive-мидлварью) — только при реальной нужде; здесь лишь документируется как ограничение (0.2) и как триггер возврата e2e-fencing (5.1).
- **`path_active` и вердикты `BLIND_SPOT` soak-пробы** — Task 3.1 транспортного плана `transport-single-policy` (зависят от дескрипторов каналов его Task 1.2); этот план их не дублирует и не блокирует.
- **Полный серверный провенанс счётчиков** (`connected` / `last_increment`) + **слепые плоскости logs/errors** (loguru Services, неподключённые логгеры framework) — после закрытия транспорта, отдельным планом (резерв, записанный в транспортном плане; продуктовый заход, не инструментный).
- **Task 2.3 / 3.3 / вынос telemetry-блока** — см. «Отложено с блокерами»: не выброшены, но и не воскрешаются без снятия блокера.
- **Новые MCP-инструменты — запрещены до закрытия плана** (урок 4.5/10: периферия впереди доказательств).
- **Удаление/развитие D.2 HTTP** — заморожен решением ревью, задач не порождает.
