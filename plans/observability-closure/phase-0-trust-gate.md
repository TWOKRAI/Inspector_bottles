# Доверие: гейт и «verified»-ответы

> Фаза Ф0 плана [`observability-closure`](./plan.md). Правила приёмки — `plan.md` §3 (наследуют `observation-port/plan.md` §3), развилки владельца — `plan.md` §4, что удаляется и миграции — `plan.md` §9–§10. Номера находок (C*, M*, m*) — по [ревью 2026-08-28](../../docs/reviews/2026-08-28_observability-full-review.md).

## Ф0 — Доверие: гейт и «verified»-ответы (поведение продукта не меняется)

Цель фазы: после неё зелёный гейт и ответы инструментов означают то, что говорят. Ни одна задача не
меняет формат записей, конфиг или команды — только тесты, порядок вызовов и схемы MCP.

### Task 0.1 — Утечка реестра объявлений (C1) — **[DONE]** `0ae55ac8`, `154ca59d`, `e9a5c898`
**Level:** Middle (Sonnet) · **Assignee:** developer · **Layer:** framework, tests
**Goal:** гейт фреймворка зелен в любом порядке сбора модулей, и голый сброс каталога больше невозможен.
**Files:** `multiprocess_framework/modules/statistics_module/tests/test_observation_port_hazards.py:853`,
`multiprocess_framework/modules/observability_declarations.py:278-322`, `statistics_module/tests/conftest.py`,
`process_module/tests/conftest.py` (новая autouse-фикстура), `multiprocess_framework/modules/tests/` (страж).
**Steps:**
1. `grep -rn "forget_declarations()" --include=*.py` — инвентарь голых вызовов (ожидание: только тесты).
2. В тесте `:853` — `forget_declarations(names=[name])`.
3. Autouse-фикстура `declarations_snapshot` (session- и function-scope) в обоих `conftest.py`: снимок
   реестра до теста, восстановление после; реализовать через публичный API реестра (добавить
   `snapshot()`/`restore()` в `observability_declarations`, если их нет).
4. `forget_declarations()` без `names`/`kind` → `TypeError` с адресом фикстуры в тексте.
5. Страж сетки: тест в `multiprocess_framework/modules/tests/`, который на закрытии сессии сверяет каталог
   фреймворка с ожидаемым литералом `('cycle_duration_ms','effective_hz','fps','latency_ms','shm')` —
   утечка любого будущего теста краснеет по имени.
**Acceptance criteria:**
- [ ] `pytest statistics_module/tests process_module/tests` и в обратном порядке — оба зелёные, числа
      записаны (ожидание ~2749 passed / 1 xfailed в обоих).
- [ ] Инъекция: вернуть голый вызов в тест → «плохой» порядок красный поимённо (предсказать 20).
- [ ] Инъекция: снять фикстуру → страж сетки красный.
- [ ] `OPEN_QUESTIONS.md`: запись «какая глобаль течёт» переведена в статус «закрыт» со ссылкой.
**Out of scope:** реестр как объект процесса (Ф4.7).

### Task 0.2 — `process_restart_verified` не лжёт (M4) — **[DONE]** `5226045a`, `e9a5c898`
**Level:** Middle (Sonnet) · **Assignee:** developer · **Layer:** tests (backend_ctl)
**Goal:** вердикт рестарта не зависит от соотношения `timeout` и `wait`.
**Files:** `backend_ctl/driver.py:519-640`, `backend_ctl/mcp_tools.py` (докстрока инструмента), `backend_ctl/tests/`.
**Steps:**
1. Запрос `process.restart` уходит с коротким таймаутом (`min(timeout, 5.0)`), ответ — справка, не вердикт (как и было задумано).
2. Дедлайн `wait` стартует **после** возврата запроса; в ответ добавить `polls` (сколько снимков сделано) — ноль опросов невозможен молча.
3. Докстрока: `timeout` относится к запросу, `wait` — к подтверждению; пример с обоими.
**Acceptance criteria:**
- [ ] Живьём: `process_restart_verified(pult, wait=60, timeout=90)` → `restarted: true`, `pid` сменился, `elapsed < 20`, `polls ≥ 2`.
- [ ] Пара инъекций: (ложноотрицательная) вернуть старый порядок → при `timeout > wait` `restarted: false` при живом новом pid — тест красный; (ложноположительная) подменить снимок «после» снимком «до» с выросшим `instance_restarts` — `restarted` не должен стать `true` без `alive`.
- [ ] Юнит на фейковом драйвере: запрос длительностью > `wait` не съедает окно опроса.
**Out of scope:** graceful-stop 5 с (долг `project_graceful_stop_debt`).

### Task 0.3 — Каталог метрик полон к моменту проверки (M1) — **[DONE]** `5226045a`
**Level:** Middle+ (Sonnet) · **Assignee:** developer · **Layer:** framework
**Goal:** ни одного WARNING «Неизвестные ключи … метрика игнорируется» при живой метрике; каталог не зависит от порядка импортов.
**Files:** `process_module/heartbeat/process_heartbeat.py:376-410,540-600`, `process_module/configs/telemetry_publish_config.py:32-60,138-165`,
`multiprocess_framework/modules/observability_declarations.py`.
**Steps:**
1. Явная функция `ensure_framework_producers()` в `observability_declarations` (или рядом с `gated_metrics`), импортирующая модули-производители фреймворка поимённо; вызывается в `gated_metrics()` до чтения реестра.
2. `_warn_unknown_metrics` — после сборки гейта (когда `TelemetryGate` уже импортирован), не до; либо на первом тике.
3. Тест: «каталог после `gated_metrics()` содержит пять имён фреймворка при любом порядке импортов» (свежий интерпретатор через `subprocess`, два порядка).
4. Тест на стенде-харнессе: журнал бута процесса не содержит строки `Неизвестные ключи telemetry.publish.metrics` при конфиге прототипа.
**Acceptance criteria:**
- [ ] Живьём: бут `webcam_sketch` → 0 строк этого WARNING (было 7 за прогон, включая рестарт); опечатка в конфиге (`latency` вместо `latency_ms`) по-прежнему даёт WARNING один раз — контрольная пара.
- [ ] Инъекция: вернуть порядок «проверка до импорта» → тест двух порядков красный.
**Out of scope:** реестр как объект процесса.

### Task 0.4 — MCP: `full` у всех капнутых инструментов, `introspect_observability`, честный `rules_matched_nothing` (M2, M3, m6) — **[DONE, кроме критерия 5]** `5226045a`, `de8bc0a9`, `a69b3ef3`
**Level:** Middle+ (Sonnet) · **Assignee:** developer · **Layer:** tests (backend_ctl), framework (readback)
**Goal:** агент читает через MCP всё, что читает драйвер; подсказка об усечении не обещает того, чего нет.
**Files:** `backend_ctl/mcp_tools.py:36-60,400-460` (`_cap_heavy`, реестр схем), `backend_ctl/dispatch.py:267-312`,
`backend_ctl/driver.py:468-492` (`observability_counters`), `process_module/configs/observation_policy.py:390-410`,
`multiprocess_framework/docs/observability/CONTROL_PANEL.md`, `backend_ctl/README.md`.
**Steps:**
1. Механизм, не правка 44 схем руками: капающий хелпер сам добавляет `full: _FULL` в схему любого инструмента, который может быть усечён (одно место в реестре); `_UNCAPPED_TOOLS` — исключения. Подсказка `_hint` строится из фактической схемы.
2. Инструмент `introspect_observability(process, section=None, full=False)` — зеркало команды; `section` сужает до одной из `effective/counters/provenance/history/observation/audit/layers`.
3. `rules_matched_nothing` в readback только для правил, доживших до ≥ 1 тика; для свежих — `rules_pending: [...]`. Ответ `config.reload` с правилом порта несёт `evaluated_ticks`.
4. Контракт-тест: каждая схема с капом содержит `full`; `jsonschema.validate({"full": true})` проходит у 50/50.
5. `CONTROL_PANEL.md` + `backend_ctl/README.md`: таблица инструментов ↔ команд регенерируется скриптом (страж паритета в `docs_verify`).
**Acceptance criteria:**
- [ ] Живьём: `capabilities(format="concise", full=true)` возвращает > 12 000 Б без `_truncated`; `introspect_observability(seg)` читается без драйвера.
- [ ] Живьём: правило порта сразу после применения → `rules_pending`, через 2 тика → `rule_hits > 0`, `rules_matched_nothing: []`.
- [ ] Инъекция: снять автодобавление `full` → контракт-тест красный на 44 инструментах поимённо.
- [ ] Страж паритета инструментов ↔ документа красный при добавлении инструмента без строки в CONTROL_PANEL.
**Out of scope:** `history_query` (Ф3.5), flare-бандл (Ф4.3).

### Task 0.5 — Живой стенд Ф0 + ревью фазы — **[PARTIAL]** см. [`review-phase-0.md`](./review-phase-0.md)
**Level:** — · **Assignee:** владелец (стенд), reviewer (синхронно)
**Acceptance criteria:**
- [ ] Корневой гейт и `run_framework_tests.py` на принимаемом HEAD, числа записаны; матрица инъекций владельца по всем свойствам Ф0.
- [ ] Агентская сессия только MCP-инструментами: `capabilities` → `introspect_observability` → `process_restart_verified` — без единого обхода драйвером.


---

## Итог фазы (2026-08-29)

**Гейты на принимаемом HEAD:** корневой **7239 passed / 64 skipped**, фреймворка
**8995 passed / 8 skipped / 1 xfailed**, `backend_ctl` **693 passed / 44 skipped**.
Независимость порядка сбора — **2762 passed, 1 deselected, 1 xfailed в обоих порядках**
(было `20 failed / 2729 passed` против `2749 passed`).

**Матрица инъекций** — [`injections-phase-0.md`](./injections-phase-0.md): 14 предсказаний по
четырём задачам, совпало 6. Четыре расхождения вскрыли реальные дыры в сторожах (все закрыты),
остальные оказались дефектами модели, а не кода.

**Ревью фазы** — [`review-phase-0.md`](./review-phase-0.md): вердикт первой итерации
CHANGES REQUESTED, один блокер (вакуумный сторож критерия 1 + мёртвый `--deselect` + падение
на кодировке). Из 12 находок 7 закрыто, 5 отложено с записью, одна вынесена в развилку Р-8.

**Два чекбокса НЕ закрыты и закрывать их нельзя:**
- критерий 5 задачи 0.4 (страж паритета инструментов ↔ `CONTROL_PANEL.md`) — сторож проверяет
  один литерал и зелен при 34 неупомянутых инструментах из 51; решение владельца Р-8;
- «агентская сессия только MCP-инструментами» из 0.5 — MCP-сервер держал код, загруженный до
  правок дня, поэтому проверка шла хендлерами напрямую. Нужен перезапуск сессии с MCP.
  **ЗАКРЫТ 2026-09-01 стендом Ф1.5:** свежая сессия, MCP-сервер держал актуальный код backend_ctl
  (последняя правка 2026-08-31, сервер поднят 2026-09-01), весь обход шёл через настоящий сервер —
  capabilities (усечение с честным `_hint` про `full`) → system_overview → introspect_observability
  (`section=counters`) → state_get_subtree → config_reload_verified (`confirmed`, TTL) →
  logger_sink_disable (TTL) → system_command. Детали — `review-phase-1.md`. Оговорка: правка
  overview в Task 1.5 легла ПОСЛЕ подъёма сервера, для НЕЁ чистый MCP-прогон — при следующем
  перезапуске сессии.
