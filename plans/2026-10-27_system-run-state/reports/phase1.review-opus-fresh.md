# Ф1 run-state — свежее ревью Opus (2026-11-15)

Ветка `fix/run-state-phase1-review`, HEAD `810fa88f6`, код как в `9784900d5`. Диапазон: `git diff dd5378bb8..HEAD -- multiprocess_framework Services multiprocess_prototype`.
За время ревью ветка ушла на `362ebf442` (два коммита только `docs(plans)`; `git diff --stat 9784900d5 362ebf442 -- multiprocess_framework Services multiprocess_prototype` пуст — код тот же).
Сессия гейта: `rs-review-fresh`, все прогоны — `machine_gate.sh light`. Скрипты: `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/d2c67523-26b4-41a7-a0e5-4ce5d93d7eca/scratchpad/rs/repro.py` (R1–R5), `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/d2c67523-26b4-41a7-a0e5-4ce5d93d7eca/scratchpad/rs/inject.py` (инъекции I1–I5, отдельный worktree, откат `cp`).
memory hits: `scripts/memory/search.py run state readiness heartbeat supervisor` -> `project_plugin_paused_is_a_label.md`, `project_industrial_standards_packml.md` (контекст, находок не даёт).

## 1. Вердикт

**CHANGES REQUESTED (итерация 1 из 2).** Три major с воспроизведением (F1, F2, F3), один major с низкой вероятностью (F4). Остальное — advisory и советы.

## 2. Фаза 1 — независимые находки (записаны ДО чтения отчётов r1/r2, инъекций, known-compromises)

### F1 — major (угол 3, принцип 5): битый лист готовности одного процесса выключает обнаружение аварии во всей системе

- Где: `run_state.py:94` (`for r in (leaf.get("reasons") or [])`), вход без проверки формы — `process_monitor.py` `_admit_heartbeat` (`self._readiness[sender] = dict(readiness)`).
- Вход: система в `running` (a, b); heartbeat от `a` с `readiness = {"ready": True, "reasons": 5, "paused": False, "at": now}`; затем `b` падает (`_alive=False`, `exitcode=-9`); 3 такта монитора.
- Наблюдаемо (R1): `state after b died, a sent reasons=5: running`; журнал — `Error in run readiness tick: 'int' object is not iterable` на каждом такте. Контроль (R1ctl, `reasons: []`): `fault`.
- Причина: `evaluate` бросает на одном листе, такт целиком теряется (`process_monitor._tick_run_readiness` ловит и пишет ERROR). Один узел роняет оценку всех.
- Решение: проверка формы на ВХОДЕ (одна функция `normalize_leaf` в `run_state.py`, зовёт `_admit_heartbeat`): `reasons` не list / `at` не конечное число / `ready` не bool → лист негоден → у ЭТОГО процесса одна `failure` «лист готовности негоден» (`source: report`). Плюс `math.isfinite(at)` (сейчас `at = nan` даёт «свежий навсегда»: `now - nan > stale_s` ложно — по чтению, не запускал).
- Вероятность сегодня низкая: единственный отправитель — `ProcessHeartbeat` с санитизированным снимком оркестратора. Это защита границы, а не текущий живой дефект.

### F2 — major (угол 1): `booting` (и `stopping`) — тупик, если итог `settled` один раз не дошёл

- Где: таблица `run_state.transition` + `_settle_run_state` (`process_manager_process.py` ~`:1586`), `_cmd_topology_apply` (`finally: self._settle_run_state()`), `_run_stop_sequence` -> `_run_stop_finish` (оценка вне `try`).
- Перебор таблицы (R4, все события × `ready` × `stop_done`): выходы `booting` = `[settled, shutdown]`, `stopping` = `[settled, shutdown]`, `fault` = `[ack, shutdown]`; поглощающее — только `shutting_down`; в `running` входит только из `ready`. Таблица сама живая; живость `booting`/`stopping` целиком держится на том, что PM ВСЕГДА подаст `settled`.
- Вход (R1b): `apply`, затем `_settle_run_state()` бросает (лист из F1), затем лист исправлен, все свежие, 3 такта.
- Наблюдаемо: `settle raised: TypeError`; `state after 3 clean ticks: booting`; `system.run.start` -> `{'success': False, 'state': 'booting', 'error': 'not_ready', 'reasons': []}` — оператор видит «поднимается» без причин навсегда (выход — только `system.shutdown`).
- Та же ветка у `stopping`: в `_run_stop_sequence` вызов `_run_stop_finish` стоит после `try/except`, а он зовёт `_evaluate_run_readiness()` — исключение убивает поток, `stopping` навсегда. **По чтению кода, отдельным запуском не проверено.**
- Решение: итог не имеет права не случиться. `_settle_run_state` и ветка STOP в `_run_stop_finish`: `try: ready, reasons = evaluate…` `except Exception as exc: ready, reasons = False, [failure «оценка готовности не удалась: <Тип>»]`; `settled` подаётся всегда. Тест: `_evaluate_run_readiness` бросает -> после apply и после STOP состояние `not_ready` с этой причиной.

### F3 — major (углы 2, 3; IPC): `run_event` — `multiprocessing.Event`; смерть ребёнка внутри `is_set()` вешает замок машины PM навсегда

- Где: `_run_apply` (`run_event.is_set()` / `set()` / `clear()` под `self._run_lock`), `_run_stop_clear_event` (то же). У `mp.Event` каждый `is_set/set/clear/wait` берёт межпроцессный замок (`with self._cond`, CPython `multiprocessing/synchronize.py`). Дети трогают событие непрерывно: `reconcile_run_event` — на КАЖДЫЙ плагин каждого прохода 20 Гц (`plugin_orchestrator.py:411`), снимок 2 Гц, `SourceProducer` на каждой итерации.
- Вход (R2): PM с `run_gate: true`; spawn-ребёнок получает `pm._run_event`, берёт `ev._cond.acquire()` (имитация: SIGKILL пришёл внутри `is_set()`), `SIGKILL` ребёнку (`exitcode -9`).
- Наблюдаемо: `system.run.start -> HUNG>3s`, `system.run.status -> HUNG>3s`, `monitor tick -> HUNG>3s`. `_run_lock` занят навсегда: команды работы, публикация, такт монитора (= супервизор) стоят.
- Вероятность естественного попадания — оценка, не замер: `is_set` = 1,94 мкс (замер R3) × ~90 вызовов/с на ребёнка ≈ 1–2·10⁻⁴ на одно падение ребёнка (SIGKILL, OOM, segfault нативного драйвера камеры). Редко, но невосстановимо без перезапуска всей системы, и задевает не процесс, а PM целиком. Новое по сравнению с прежними `mp.Event` (`stop_event` свой у процесса; `system_ready_event` — только boot).
- Решение (fix forward, меньше слоёв): флаг работы без замка — `multiprocessing.RawValue(ctypes.c_bool)` (или байт в shared memory, `shared_resources_module` уже есть): один писатель (PM), читатели без замка; `_run_apply` ничего не ждёт. Минимум, если флаг менять нельзя до 1.0: не трогать `mp.Event` под `_run_lock` (переключать после замка, отдельным потоком с таймаутом и ERROR). Нужен слепой tester (гонка) + стенд `kill -9` серией.

### F4 — major, низкая вероятность (угол 3): провал `restart_process` оставляет пометку «перезапускается» навсегда

- Где: `process_manager_process.py:5527-5532` (пометка до `stop_process`; выходы `return False` после неё — `stop_process` ложь, `create_and_register` None, исключение — пометку не снимают); `process_monitor._admit_heartbeat`.
- Вход (R5): `running`; `stop_process` возвращает `False` (старое воплощение не подтвердило смерть — `stop_one`), `restart_process("a")`; затем 3 heartbeat от живого `a` с тем же pid.
- Наблюдаемо: `restart_process -> False`; `restarting: frozenset({'a'})`; `last_hb has a: False` (heartbeat живого процесса отбрасываются все); причины: `['a: перезапускается супервизором']` — навсегда. Следствие по чтению (не запускал): монитор без `_last_heartbeat` сочтёт живой процесс `unresponsive`.
- Решение: у пометки два владельца исхода — успех (heartbeat нового pid) и провал. Добавить `ProcessMonitor.unmark_restarting(name)` и звать на всех `return False` после `mark` (и в `except`), либо `try/finally` вокруг тела рестарта. Тест на каждый выход.

### Advisory (без воспроизведения запуском или с малым эффектом)

- **A1 (угол 3, по чтению):** `_process_alive` и `_supervisor_gave_up` пишут `log_error(... {exc})` на каждый процесс на каждой оценке (2 Гц + START/ack) без дросселя — постоянный сбой реестра = поток ERROR; текст исключения может нести значения входа (правило ADR-PMM-044 п.1).
- **A2 (угол 3/8, арифметика):** PM судит молчание по СВОЕМУ `heartbeat_interval` (`_run_stale_s`), а ребёнок шлёт heartbeat по своему (`process_heartbeat.py:141`, `self._services.get_config("heartbeat_interval", 5.0)`). Ребёнок с 12 с при PM 5 с: допуск 10 с — START периодически отказан; с > 15 с — `fault` в `running`. Распространяется ли интервал PM детям — не проверял.
- **A3 (угол 1, по чтению):** `_paused_pending` принимает `paused: true` листа любого возраста. Процесс, замёрзший в первые ~0,6 с после START, держит лист `paused: true` прошлого STOP; STOP в пределах `stale_s` подтверждает его мгновенно, `settled` по тому же листу даёт `ready`. Окно узкое.
- **A4 (угол 6):** классовые изменяемые умолчания `_run_unconfirmed: dict = {}`, `_run_down_since: dict = {}`, `_run_reasons: tuple | list = ()` безопасны только дисциплиной «заменять целиком» (общие на все PM). Работает, но хрупко.

## 3. По углам (что проверено и чем)

| угол | проверено | итог |
|---|---|---|
| 1. Живость таблицы | R4 — полный перебор `transition` (7 состояний × 7 событий × 4 параметра); R1b — тупик `booting` запуском | таблица живая; тупики `booting`/`stopping` — от PM, не от таблицы (F2) |
| 2. Замки | граф по чтению: `_run_publish_lock` → `_run_lock` (через `_run_ack_allowed`, `_run_detail_snapshot`); `_run_lock` → межпроцессный замок `mp.Event`; `_readiness_lock`, `_unconfirmed_lock`, `_run_restart_lock` — листовые, под ними нет других замков и вызовов наружу; pid реестра читается до замка. Обратного порядка не нашёл. R2 — запуском | инверсии нет; межпроцессный замок под `_run_lock` — F3 |
| 3. Отказ внешних вызовов | R1 (битый лист), R5 (рестарт не удался), R2 (ребёнок умер с замком); I3 (отказ исполнителя — тесты краснеют) | F1, F3, F4; отказ исполнителя закрыт |
| 4. Тесты как доказательство | 5 инъекций (см. §4.1) — все красные; тестов на битую форму листа на стороне PM нет | свойства из списка охранены; пробел — форма входа (F1) |
| 5. Потребители вне PM | `git grep -F "system.run."` по prototype/Services/Plugins/scripts — 0 совпадений; отправитель heartbeat в PM — только `ProcessHeartbeat`, читатель `pid` — только монитор | контракт ни у кого не сломан; C11 — см. §5 |
| 6. Избыточность | по чтению | см. «Советы» |
| 7. Эффективность | R3 `timeit` на настоящих PM + `ProcessMonitor`, N = 8 процессов с политикой: такт 33,5 мкс, оценка 28,8 мкс, `RestartPolicy(**rp)` 1,4 мкс, `mp.Event.is_set` 1,94 мкс; такт монитора 0,5 с | ≈ 0,007 % CPU — горячего пути нет, находки нет |
| 8. Код ↔ документы | §3.2 таблица = код (R4 + чтение); §3.7 отказ apply = код; amendments §9 порядок shutdown = код (`from_running`); §10 антидребезг 0,5 с = `_PUSH_MIN_INTERVAL_SEC`; отличие: отказ apply в `shutting_down` — «система завершает работу» вместо «сначала ОСТАНОВИТЬ» (1.5 DESIGN) — улучшение, документ поправить | расхождений по смыслу не нашёл; проверено выборочно |

### 4.1. Инъекции (worktree в scratchpad, откат `cp`; предсказание записано до прогона — «краснеет файл X»)

| # | что сломано | предсказание | получено |
|---|---|---|---|
| I1 | отброс устаревшего такта (`eval_started < _run_running_mono`) | `test_run_state_hazards.py` / `test_run_commands.py` | **не совпало по файлу**: там 48 passed; красный — `test_run_shutdown_from_running_hazards.py::test_stale_tick_after_start_does_not_fault` (1 failed). Свойство охранено |
| I2 | ветка `restarting` в `_process_reasons` | `test_run_restart_incarnation*.py` | 5 failed (4 + 1 hazard) |
| I3 | обход отказа исполнителя в `_submit_run_sequence` | `test_run_submit_refusal_hazards.py` | 5 failed из 8 |
| I4 | запас допуска (`_admission_stale_s` = `stale_s`) | `test_run_admission_margin.py` | 4 failed из 10 |
| I5 | забор чужого pid вне перезапуска | `test_monitor_foreign_incarnation_heartbeat.py` | 1 failed из 7 |

## 5. Фаза 2 — сверка с r1 (`phase1.review-opus.md`), r2 (`phase1.review-opus-r2.md`), `phase1.known-compromises.md`

### 5.1. Мои находки против прежних

| моя | статус | пояснение |
|---|---|---|
| F1 битый лист роняет оценку всех | **нашёл один я** | r1/r2 форму листа на стороне PM не проверяли |
| F2 тупик `booting`/`stopping` при исключении оценки | **новая, родственна r1 M1** | M1 — тот же класс («итог не доходит»), но вход — отказ исполнителя; закрыт (моя инъекция I3 это подтверждает). Вход «исключение в оценке» и ветка `booting` не закрыты |
| F3 `mp.Event` под `_run_lock` | **нашёл один я** | r1 упоминает `is_set()` на `mp.Event` только как цену опроса |
| F4 провал `restart_process` оставляет пометку | **частично совпало с r2 N1** | r2 назвал «пометка навсегда» следствием микроокна N1 (нет повтора и `gave_up`). N1 закрыт правкой B2 (запись времени под `_readiness_lock` — видел в коде). Мой вход другой — явные `return False` после `mark`. По чтению: у авто-рестарта пометку со временем снимет `gave_up` (fix m3), у ручного `process.restart` и при `enabled: false` — никто |
| A1–A4 | нашёл один я | advisory |

### 5.2. Прежние находки, которые я не нашёл или оцениваю иначе

| прежняя | моя оценка | чем проверено |
|---|---|---|
| r1 M1 отказ исполнителя | согласен, закрыт | I3: откат обхода -> 5 failed в `test_run_submit_refusal_hazards.py` |
| r1 M2 два разборщика политики | согласен, закрыт | чтение: один `ProcessMonitor.resolve_policy` |
| r1 M3 / r2 N1 забор воплощения, микроокно | согласен, закрыт | чтение `_admit_heartbeat` (время пишется под замком), I5 — забор краснеет |
| r1 M4, M5, m1–m5 | не перепроверял, кроме m2 | m2: I1 — краснеет `test_stale_tick_after_start_does_not_fault` |
| r2 N2 `protected` | согласен, закрыт | чтение `_run_auto_restart_flags` (`name not in protected`) |
| r2 N3 проверка формы под `MagicMock` | **согласен, НЕ закрыт**: `if not (isinstance(resolved, tuple) and len(resolved) == 2): continue  # монитор-двойник (MagicMock …)` в боевом коде; та же форма в `_readiness_view` | чтение текущего HEAD |
| r2 «`resolve_policy` — десятки мкс на процесс, кэш» | **не согласен по числу**: `RestartPolicy(**rp)` = 1,4 мкс, вся оценка N = 8 — 28,8 мкс, такт — 33,5 мкс (R3, `timeit` на настоящих объектах). Кэш не нужен | R3 |
| r1/r2 C2 push только на `paused` | согласен: рекомендация, отдельной задачей (совет С5) | чтение `push_if_paused_changed` |
| C11 `pid` в heartbeat | согласен с r1: cto не нужен — отправитель один (`ProcessHeartbeat`), читатель один (монитор), оба во framework, поле аддитивно (`git grep` производителей heartbeat). Риск повтора pid ОС — совет С10 | grep |
| C12 гистерезис + воплощение | согласен с r1: два разных класса отказа, не дубль. После С5 гистерезис станет менее нагруженным, но остаётся честным «запасом в один интервал» | чтение; A/B 1.7b не перепроверял |

## 6. Ответ на вопрос владельца

«Архитектура отличная, без костылей и багов, максимально эффективно и правильно?» — **частично.**

- Да: таблица переходов чистая и живая (R4), одна точка записи `_run_apply`, оценка — чистая функция с объектом входа, свойства из списка охранены тестами (I1–I5 красные), горячего пути нет (R3: 33,5 мкс на такт).
- Нет: граница входа не защищена (F1 — один битый лист выключает аварии всей системы, против принципа 5); живость `booting`/`stopping` держится на том, что оценка никогда не бросит (F2); межпроцессный замок `mp.Event` взят под центральным замком PM (F3 — смерть одного ребёнка может остановить PM целиком); пометка «перезапускается» без владельца провала (F4). Остался один костыль под тест-двойник (N3).

## 7. Советы по улучшению (по убыванию пользы; находки — разделы 2 и 5)

Пометка: [замер] / [воспроизведено] — подкреплено запуском; [рассуждение] — нет.

**С1. Итог `settled` гарантирован конструкцией, а не дисциплиной** [воспроизведено R1b]. Приоритет: **сейчас**.
- Где: `_settle_run_state` (`process_manager_process.py` ~`:1586`), `_run_stop_sequence`/`_run_stop_finish` (~`:892-988`).
- Почему: у `booting` и `stopping` выход только `settled`; любое исключение оценки = тупик без причин. Свойство «из `booting`/`stopping` выходим всегда» станет локальным, а не зависящим от всех вызываемых функций.
- Как: одна функция «оценка, которая не бросает»:
  ```python
  def _evaluate_or_fail(self, **kw) -> tuple[bool, list[dict]]:
      try:
          return self._evaluate_run_readiness(**kw)
      except Exception as exc:  # noqa: BLE001 — итог машины не имеет права не случиться
          self._log_error(f"readiness: оценка не удалась ({type(exc).__name__})")
          return False, [{"node": self.name, "severity": "failure", "source": "report",
                          "reason": "оценка готовности не удалась"}]
  ```
  Её зовут `_settle_run_state`, `_run_stop_finish`, `_run_readiness_tick`; в `_run_stop_sequence` итог — в `finally`.
- Цена/риск: ~15 строк + 2 теста (apply и STOP при бросающей оценке -> `not_ready` с причиной). Стенд не нужен.

**С2. Проверка формы листа на входе, одна функция** [воспроизведено R1]. Приоритет: **сейчас**.
- Где: `run_state.py` (новая `normalize_leaf`), вызов в `ProcessMonitor._admit_heartbeat`.
- Почему: Dict at Boundary проверяется там, где dict пересёк границу; `evaluate` перестаёт быть хрупкой к чужому входу; один процесс не роняет оценку соседей (принцип 5).
- Как:
  ```python
  def normalize_leaf(raw: object) -> dict | None:
      if not isinstance(raw, dict): return None
      at, reasons, ready, paused = raw.get("at"), raw.get("reasons"), raw.get("ready"), raw.get("paused")
      if not (type(at) in (int, float) and math.isfinite(at)) or not isinstance(reasons, list) \
         or type(ready) is not bool or type(paused) is not bool:
          return {"ready": False, "paused": False, "at": time_of_receipt, "reasons": [BAD_LEAF]}
      return {"ready": ready, "paused": paused, "at": float(at), "reasons": [r for r in reasons if _valid_reason(r)][:32]}
  ```
  (`BAD_LEAF` — `failure`/`report` «лист готовности негоден», без значений.)
- Цена/риск: ~30 строк + тест-таблица негодных форм на настоящем мониторе. Риск — поменять смысл для `ready` не-bool (сейчас «truthy»): тесты 1.2/1.3 со строгими литералами это покажут.

**С3. Флаг работы без межпроцессного замка** [воспроизведено R2 (имитация попадания), вероятность — оценка]. Приоритет: **сейчас, до стенда серии `kill -9`**; если не успевается — до 1.0 отдельной задачей с записью в known-compromises.
- Где: `_create_components` (создание `_run_event`), `_run_apply`, `_run_stop_clear_event`; читатели — `source_producer.py`, `plugin_orchestrator.py` (`_run_event()`, `_target_pause`, `reconcile_run_event`), `process_module.py` (`_refresh_readiness_snapshot`).
- Почему: `mp.Event` = семафор + условие с замком; замок не освобождается при смерти держателя. Флаг одного писателя замка не требует: чтение байта атомарно. Уходит класс «ребёнок умер — PM встал»; `_run_apply` перестаёт делать межпроцессные вызовы под своим замком; опрос дешевле (`is_set` 1,94 мкс [замер] -> чтение `RawValue` ~0,1 мкс [рассуждение]).
- Как: маленький класс с тем же API, что используют читатели:
  ```python
  class RunFlag:  # process_module/run_flag.py, Dict at Boundary не затрагивает (передаётся при spawn, как Event)
      def __init__(self, ctx): self._v = ctx.RawValue(ctypes.c_bool, False)
      def is_set(self) -> bool: return bool(self._v.value)
      def set(self) -> None: self._v.value = True
      def clear(self) -> None: self._v.value = False
  ```
  `wait()` читателям не нужен (все опрашивают). Передача — тем же путём kwargs `Process`, что `run_event` сейчас (Windows spawn наследует `RawValue` так же, как `Event`).
- Цена/риск: ~25 строк + замена создания в PM; читатели не меняются (тот же API). Нужны слепой tester (гонка, смерть ребёнка с замком больше не вешает), стенд Windows (наследование при spawn).

**С4. Пометка «перезапускается» с владельцем провала** [воспроизведено R5]. Приоритет: **сейчас**.
- Где: `restart_process` (`:5527-5568`), `ProcessMonitor.mark_restarting`.
- Почему: сейчас пометку снимает только успех (heartbeat нового pid) и `gave_up`; провал рестарта у ручного пути и при `enabled: false` оставляет живой процесс невидимым навсегда.
- Как: `ProcessMonitor.unmark_restarting(name)` (pop под `_readiness_lock`, без сброса времени) и `try/finally` в `restart_process`: `ok = False; try: …; ok = True; return True; finally: if not ok: unmark(name)`.
- Цена/риск: ~10 строк + тест на каждый выход (`stop_process` ложь, `create_and_register` None, исключение). Риск: снять пометку при провале, а старое воплощение уже убито — тогда «процесс не жив», это честнее.

**С5. Внеочередной heartbeat при смене готовности, а не только `paused`** [рассуждение; задержка 3,0–5,7 с — из known-compromises C2, не перемерял]. Приоритет: **после слияния, отдельной задачей** (новый механизм: слепой tester, матрица, стенд с замером).
- Где: `ProcessHeartbeat.push_if_paused_changed` -> `push_if_changed`.
- Почему: снимается задержка до `heartbeat_interval` у `ready`/блокирующих причин; окно `fault` при заморозке и порог допуска перестают быть «впритык».
- Как: сравнивать подпись `(paused, ready, frozenset((r["node"], r["severity"]) for r in reasons if r["severity"] in BLOCKING))` с ушедшей; антидребезг 0,5 с тот же.
- Цена/риск: ~15 строк; риск — шторм при дребезге плагина: держит тот же антидребезг.

**С6. Срок молчания — от отправителя** [рассуждение, A2]. Приоритет: **после 1.0**.
- Где: снимок (`plugin_orchestrator.readiness_snapshot`, `process_module._refresh_readiness_snapshot`) и `_run_stale_s`.
- Почему: убирает связь «PM знает интервал heartbeat каждого ребёнка»; процесс с другим интервалом не даёт ложного `fault`/отказа START.
- Как: ребёнок кладёт `"stale_after_s": 3 * own_interval` в снимок; PM берёт `min(max(leaf_value, floor), ceiling)`; нет поля — как сейчас.
- Цена/риск: ~10 строк, аддитивное поле (как `pid`).

**С7. Убрать подгонку под двойник (r2 N3)** [чтение]. Приоритет: **сейчас** (дёшево).
- Где: `_run_auto_restart_flags` (`isinstance(resolved, tuple) …  # монитор-двойник`), `_readiness_view` (та же форма).
- Как: в фабрике тестов (`conftest.make_pm`) монитор — `create_autospec(ProcessMonitor, instance=True)` с `resolve_policy.return_value = (RestartPolicy(), True)` и `readiness_view.return_value = ({}, frozenset())`; в боевом коде — прямой вызов.
- Цена/риск: правка фабрики может покраснить тесты, которые полагались на `MagicMock` без формы — это и нужно увидеть.

**С8. Подтверждение `paused` — снимком, посчитанным после снятия** [рассуждение, A3]. Приоритет: после 1.0.
- Как: `_run_stop_clear_event`/аварийная ветка запоминают `t_clear = time.time()`; `_paused_pending` принимает лист только при `leaf["at"] >= t_clear`.
- Цена: ~5 строк + тест «лист `paused: true` старше снятия не подтверждает».

**С9. Номер воплощения от PM вместо pid ОС** [рассуждение]. Приоритет: после 1.0 (вне 1.7c по её тексту).
- Почему: pid ОС переиспользуется (особенно Windows); номер, выданный PM при spawn (`incarnation` в kwargs, эхо в heartbeat), однозначен и не требует опроса реестра на каждом heartbeat.

**С10. Мелочи** [чтение]: дроссель `log_error` в `_process_alive`/`_supervisor_gave_up` (один лог на серию, без текста исключения — A1); классовые изменяемые умолчания (`_run_unconfirmed`, `_run_down_since`) — в `__init__`/ленивое свойство, как замки (A4); документ 1.5 — текст отказа apply в `shutting_down`.

Разбиение `process_manager_process.py` (Task 3.2) не оценивал — дизайн `pm-split.design.md` не читал.

## 8. Что не проверено / ненадёжно

- Стенд и живой бэкенд не запускал (heavy/стенд запрещены брифом). Все воспроизведения — на `make_readiness_pm` (настоящие PM + `ProcessMonitor`, но `MockProcessRegistry`, `MagicMock` у связи и роутера).
- F3: попадание `SIGKILL` внутрь `is_set()` имитировано явным `ev._cond.acquire()`; естественная частота — оценка по скважности (1,94 мкс × ~90 вызовов/с), не замер. На Windows (`mp.Event` на семафорах Win32) не проверял.
- F2, ветка `stopping`: выведена чтением, отдельного запуска нет. Ветка `booting` воспроизведена.
- F4: следствие «монитор сочтёт живой процесс `unresponsive`» — чтением; снятие пометки через `gave_up` у авто-рестарта — чтением.
- A1–A4 — без запуска. A2: распространяет ли PM свой `heartbeat_interval` детям — не проверял.
- Угол 4: настоящий `OrderedExecutor` в тестах STOP/аварии — не проверял, какие файлы его поднимают (видел только упоминание в `test_run_shutdown_from_running_hazards.py`, `test_run_submit_refusal_hazards.py`). Сквозного теста «PM + ProcessMonitor + OrderedExecutor + настоящий процесс» не искал до конца.
- Инъекций — 5, не 8–10; I1 не совпала по файлу (свойство охранено другим файлом). Остальные свойства (`ack` × `fault_stop_done`, публикация по порядку, `_fault_seq`) инъекцией не проверял.
- Тесты диффа (~10 тыс. строк) читал выборочно; полный прогон набора не делал (только файлы инъекций, все зелёные без инъекции не перепроверял отдельно — зелёные прогоны видел только как «passed» у непострадавших тестов).
- Угол 8 — выборочная сверка (§3.2, §3.7, amendments §9, §10), не построчная.
- Порядок фаз: раздел 2 записан до чтения отчётов r1/r2/known-compromises; раздел 5 — после. Отчёты инъекций (`*injection-result.md`) не открывал.
