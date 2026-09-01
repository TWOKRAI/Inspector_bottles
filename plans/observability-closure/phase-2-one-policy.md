# Один язык политики на все плоскости; честный readback

> Фаза Ф2 плана [`observability-closure`](./plan.md). Правила приёмки — `plan.md` §3 (наследуют `observation-port/plan.md` §3), развилки владельца — `plan.md` §4, что удаляется и миграции — `plan.md` §9–§10. Номера находок (C*, M*, m*) — по [ревью 2026-08-28](../../docs/reviews/2026-08-28_observability-full-review.md).

## Ф2 — Один язык политики на все плоскости; честный readback

### Task 2.1 — Политика для чисел `StatsManager` (C2, Р-2, Р-3)
**Level:** Senior (Opus) · **Assignee:** teamlead · **Layer:** framework
**Goal:** любая метрика плоскости чисел включается/выключается и троттлится тем же glob-правилом, что уровни, до сборки записи; выключенная стоит не дороже гейта.
**Files:** `statistics_module/observation/observation_manager.py:380-470` (`_route_number`), `process_module/configs/observation_policy.py`,
`process_module/configs/observability_config.py:239-300` (`stats.*`), `process_module/managers/observability_reload.py:940-1020`
(`apply_observation_policy` → и в порт), `statistics_module/core/stats_manager.py` (счётчик `numbers_policy_dropped`),
`process_module/heartbeat/process_heartbeat.py` (readback), `CONTROL_PANEL.md`, `CONNECTORS.md`.
**Steps:**
1. Путь числа: `processes.<p>.stats.<имя>` (Р-2а); порт спрашивает `policy.resolve(path)` **до** `NumberRecord`; `enabled=False` → early return + `numbers_policy_dropped[<имя>]`; `interval_sec` → пропуск по расписанию на путь (как `_next_due` у уровней), тот же класс расписания, не копия.
2. `stats.enabled` = плоскость (Р-3а): `false` → все числа `numbers_policy_dropped`, readback говорит `plane_disabled: true`; `stats.log_snapshots` — лог-канал.
3. Пересборка политики на `config.reload` доставляется и в порт (та же `apply_observation_policy`, второй потребитель — не второй механизм).
4. Readback: `introspect.observability.stats.policy` — правила, попадания, `dropped_by_rule`; `telemetry_set`/`config_reload_verified` верифицируют правило порта по `checked`.
5. Бенч: выключенная метрика ≤ 0.5 мкс (цель — цена гейта), включённая без изменений; три прогона соло.
**Acceptance criteria:**
- [ ] Юнит: правило `processes.*.stats.capture.frames: {enabled:false}` → `capture.frames` отсутствует в окне и в hub при живых `capture.drops` и `capture.frames` другого процесса; `numbers_policy_dropped == N`.
- [ ] Живьём: `config_reload_verified(camera_0, observation.rules=…)` → `confirmed`, `checked` включает правило порта; через два флеша снапшот без метрики, счётчик растёт; TTL возвращает.
- [ ] `stats.enabled=false` живьём → `plane_disabled: true`, 0 строк `kind=stats` за окно при `numbers_policy_dropped > 0` (пара).
- [ ] Пара инъекций: правило не доезжает до порта (readback показывает, эффекта нет) → `verified` обязан сказать `failed`, тест красный при `confirmed`; политика режет после сборки записи → бенч красный.
- [ ] М5 (`observation-port` §3) перепроверен: единственность писателя не нарушена (тест фазы 5 зелен, инъекция на второй вход красная).
**Out of scope:** адресация по тегам (Р-2б), экспорт.

### Task 2.2 — Схема без мёртвых и без-схемных ключей (m4, M7-часть)
**Level:** Middle+ (Sonnet) · **Assignee:** developer · **Layer:** framework
**Goal:** каждый ключ секции `observability` объявлен схемой, читается кодом и подтверждается верификатором; ключа, который «принимается и ничего не делает», нет.
**Files:** `process_module/configs/observability_config.py:216-240,319-500`, `process_module/managers/observability_wiring.py:1250-1280`
(`resolve_history_policy`), `process_module/managers/observability_reload.py:150-170,340-370`, `process_module/configs/observability_layers.py:1320-1340`.
**Steps:**
1. `history` — под-секция `ObservabilityConfig` (`enabled/level/max_rows/max_age_sec/purge_interval_sec/db_path`); `resolve_history_policy` читает схему; L3 принимает `history.level`.
2. `errors.enabled` — читается: `false` → `ErrorManager` не создаётся, readback `error.enabled: false`, `report_error` идёт в логгер с маркером; либо (решение в задаче с доводом) ключ снимается из схемы с громкой жалобой на старый конфиг (как `REMOVED_BATCHING_KEYS`).
3. Readback `logger.logger_groups` (не `groups`); верификатор покрывает `session_ttl_sec`, `retention_*`, `compress_rotated`, `console/file`, `channels.*.enabled`, `errors.*`, `commands.log_success` через readback, а не `unverifiable`.
4. Страж: тест, обходящий поля схемы и требующий, чтобы каждое либо читалось в `expand_observability`/менеджерах (AST), либо было в явном списке «принято сознательно» с причиной.
**Acceptance criteria:**
- [ ] Живьём: `config_reload_verified(seg, history.level=WARNING)` → `confirmed`; стор перестаёт принимать INFO (пара: до/после по счётчику строк).
- [ ] Полная секция через `config_reload_verified` → `unverifiable: []`.
- [ ] Инъекция: добавить в схему поле без читателя → страж красный по имени.
**Out of scope:** новые ручки.

### Task 2.3 — Честный такт: эффективная каденция в readback и голосом (M9)
**Level:** Middle (Sonnet) · **Assignee:** developer · **Layer:** framework
**Goal:** readback показывает эффективный интервал публикации каждой метрики; расхождение «сконфигурировано 1 с, действует 5 с» слышно.
**Files:** `process_module/heartbeat/process_heartbeat.py:90-135,360-390`, `process_module/heartbeat/telemetry.py` (`capped_metrics`),
`process_module/commands/builtin_commands.py` (`introspect.telemetry` — поле `effective_interval_sec`), `CONTROL_PANEL.md`.
**Steps:**
1. `heartbeat_interval` — ключ слоёв `observability.heartbeat_interval_sec` (L0 = 5.0, провенанс), применяется reload'ом без рестарта.
2. `_warn_capped_metrics` работает и при `tick_sec=None` (такт = heartbeat); голос один раз на пересборку, с адресами ключей.
3. `introspect.telemetry.resolved[*].effective_interval_sec = max(interval_sec, такт)`, `tick_effective_sec` на верхнем уровне; `introspect.observability.observation.effective` — то же для правил порта.
**Acceptance criteria:**
- [ ] Живьём: readback `effective_interval_sec: 5.0` при `interval_sec: 1.0` + один WARNING с адресом; `config_reload(heartbeat_interval_sec=1.0)` → дельты каждые 1 с (пара по `events_page`), readback 1.0.
- [ ] Инъекция: убрать `max()` → тест «readback = эффективному» красный.

### Task 2.4 — Кэш решений политики и предкомпиляция правил (m8)
**Level:** Middle+ (Sonnet) · **Assignee:** developer · **Layer:** framework
**Goal:** решение политики по пути стоит O(1) после первого вызова; выключенный лист не стоит ничего, кроме поиска в кэше.
**Files:** `process_module/configs/observation_policy.py:300-390`, `process_module/heartbeat/telemetry.py:880-950`.
**Steps:** memoize `(path) → PolicyDecision` на экземпляре политики (политика неизменяема после сборки); `split_pattern` в `__init__`; счётчики попаданий — отдельно от кэша (`count=True` инкрементит и при кэш-хите); бенч трижды соло.
**Acceptance criteria:**
- [ ] Бенч: 500 листьев выключены → ≤ 10 % от цены 500 включённых; 50 правил → тик ≤ 3 мс (было 19.3).
- [ ] Инъекция: кэш не инвалидируется при новой политике → тест «новое правило действует после reload» красный.

### Task 2.5 — Legacy `telemetry.publish` → адаптер с датой снятия (m11)
**Level:** Middle+ (Sonnet) · **Assignee:** developer · **Layer:** framework, docs
**Goal:** одна политика, один дефолт; легаси-секция читается как вход и переводится в правила при загрузке; срок её жизни записан.
**Files:** `process_module/configs/observation_policy.py:340-385`, `process_module/configs/telemetry_publish_config.py`, `process_module/DECISIONS.md` (ADR-PM-041/042 — дополнить датой),
`multiprocess_prototype/backend/config/system.yaml` (секция `telemetry:` — комментарий-миграция).
**Steps:** транслятор `telemetry.publish → observation.rules` с провенансом `legacy_source`; `default_enabled` → `subtree_enabled` (один дефолт); `telemetry.reconfigure` пишет правила тем же путём; ADR: снятие легаси-чтения — через одну фазу после Ф5 (дата).
**Acceptance criteria:**
- [ ] Паритетный тест: старый конфиг прототипа даёт те же решения по всем путям, что до правки (литералы по 8 именам).
- [ ] Readback показывает правило с `source: legacy:telemetry.publish`.

### Task 2.6 — Живой стенд Ф2 + ревью фазы (операторская сессия М4 расширена на числа)
- [ ] Транскрипт: одними и теми же командами оператор (а) видит политику логов, уровней и чисел, (б) меняет каждую, (в) убеждается вердиктом, (г) читает хвост — новых имён команд ноль.
- [ ] Сценарий переполнения очереди (`gui` под нагрузкой) → ≤ 1 голос на окно при растущем
      `queue_full_events`. Перенесён из Task 1.4: там чекбокс стоял шире факта — бут-половина
      снята, эта половина живьём не строилась (находка ревью Ф1).
- [ ] Первый стенд после перезапуска сессии: аномалия `health_errors` (Task 1.5) читается
      **через настоящий MCP-сервер** (`system_overview` без драйвера) — закрывает оговорку
      Ф1.5 «сервер держал код до правки».

### Task 2.7 — Добор ревью Ф1: пары счётчиков и литералы окна голоса
> Задачи 2.7–2.8 заведены 2026-09-01 по ревью фазы Ф1 и исполняются ДО стенда 2.6
> (номера — порядок добавления, стенд остаётся последним актом фазы).

**Level:** Middle+ (Sonnet) · **Assignee:** developer · **Layer:** framework, tests
**Goal:** три устоявших major-находки ревью Ф1 (см. [`review-phase-1.md`](./review-phase-1.md))
закрыты числом: у каждого диагностического счётчика — ОБЕ половины пары; литералы окна голоса —
в политике с readback; реестр снятых копий окна не расходится с деревом.
**Files:** `shared_resources_module/queues/core/manager.py` (`queue_full_events`),
`process_manager_module/**` (`pid_registry_failures`), `logger_module/core/windowed_voice.py`
(`MAX_TRACKED_KEYS = 512`, `_STALE_WINDOWS = 10`, реестр `REPLACED_MANUAL_WINDOWS` и его сторож
`_WATCHED`), схема `observability.voices.*`.
**Steps:**
1. Ложноположительные половины пар (правило 3 §1): «события нет, счётчик растёт» — красный.
   **Уточнение 2026-09-01 (посылка первой редакции была неверна, проверено):** ревью доказало
   не дефект боевого кода, а СЛЕПОТУ НАБОРА. `queue_full_events` инкрементится строго внутри
   `except` под `isinstance(e, Full)` (`queues/core/manager.py:299`), на успешной отправке не
   растёт; `pid_registry_failures` — так же на реальном отказе реапа. Числа 6447 и 894 дала
   заплатка ревьюера (monkeypatch-плагин), и ценность находки в том, что под ней **ноль красных**
   при 246 и 894 зелёных — сторожа этого класса в дереве нет ни одного.
   Следствие: по шагу 1 **правки кода не требуется**, требуется сторож (половина «события нет →
   дельта 0») и инъекция, доказывающая, что он не пустой. Читать первую редакцию как «счётчик
   врёт в бою» — и «чинить» верное поведение — прямая дорога к регрессии.
2. `MAX_TRACKED_KEYS`/`_STALE_WINDOWS` → `observability.voices.*` (L0-дефолты те же), readback
   ЭФФЕКТИВНОГО значения + счётчик насыщения (по образцу `sampler_keys_tracked`/`saturated`).
   Поведение ЗА потолком — отдельно в Task 4.1 (там же обрыв → деградация).
3. `REPLACED_MANUAL_WINDOWS`: сторож сужен до трёх файлов, а расхождение уже живёт (реестр — 6,
   комментарий `router_manager.py:320` — 8). Либо `_WATCHED` расширяется до заявления, либо
   заявление сужается до охвата — молча расходиться нельзя.
4. Опционально (minor ревью): ручка для `DIAG_JOIN_TIMEOUT_SEC` (readback уже есть).
**Acceptance criteria:**
- [x] (инъекции A1/A2/A4, 2026-09-01) Пара инъекций на каждый из двух счётчиков: «событие есть,
      счётчик 0» И «события нет, счётчик растёт» — обе красные, поимённо. A1 = заплатка ревью Ф1
      дословно: 2 красных там, где у ревью было 246 зелёных. Базы 1144 / 1143.
- [x] `introspect.observability` показывает эффективные значения бывших литералов и насыщение
      (доказано B1 — 4 красных, B3 — 2 красных). **Инъекция B2 вскрыла вторую поверхность:** ответ
      `config.reload` о применённых ручках не сторожился (0 красных из 928) — закрыто
      `test_f2_task27_voices_reload_response_gap.py`.
- [x] (инъекции C1/C2) Инъекция: девятая ручная копия окна в НЕнаблюдаемом файле → сторож
      реестра красный. Заявление сужено до охвата: «восемь» → «шесть», сверено с ADR-LOG-012 и
      реестром (6 записей); то же расхождение снято в `docs/claude/memory`.
**Out of scope:** обрыв окна при >512 ключей (Task 4.1), пер-ключевой счётчик подавлений.

### Task 2.8 — Агентский DX сводки: пустой read-model называет себя
**Level:** Middle (Sonnet) · **Assignee:** developer · **Layer:** tests (backend_ctl)
**Goal:** холодная агентская сессия перестаёт молча получать пустую телеметрию: сводка сама
говорит, что read-model пуст и почему (находка стенда Ф1.5: `telemetry.fps == {}` и немота
`fps_zero_while_running` без активной подписки — предусловие документировано, но сводка о нём
молчит, что ломает обещание «один вызов = вся картина» ровно для агентов).
**Files:** `backend_ctl/overview.py`, `backend_ctl/tests/test_overview*.py`.
**Steps:** если `telemetry_snapshot` пуст И подписка не активна → hint
`{"kind": "telemetry_readmodel_empty", "detail": "state-подписки нет — watch_like_gui наполнит"}`;
при активной подписке и пустом снимке — НЕ выдавать (законное «дельт ещё не было»).
**Acceptance criteria:**
- [x] Холодный `system_overview` → hint есть; после `watch_like_gui` + первая дельта → hint нет.
- [x] (инъекции D1/D2/D3, база 41) Пара инъекций: hint при активной подписке
      (ложноположительный) и тишина при пустом read-model без подписки (ложноотрицательный) — оба
      красные. D3 добором: пустота меряется всем read-model, а не fps-срезом.
**Out of scope:** сама история (Task 3.5).
