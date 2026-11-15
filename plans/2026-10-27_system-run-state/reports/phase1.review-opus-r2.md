# Ф1 run-state — ревью Opus, раунд 2 (итерация 2 из 2, 2026-11-15)

Ветка `fix/run-state-phase1-review`, HEAD `08d8f96c8`. Дифф: `git diff 506eea281..HEAD -- multiprocess_framework Services multiprocess_prototype` (17 файлов, +1157/−113). Read-only; стенд и приложение не запускал.

## Вердикт

**CHANGES REQUESTED (итерация 2 из 2) — один пункт обязателен (N1), остальное — minor.**

Все находки раунда 1 закрыты воспроизведением. Новый дефект один, и его внесла сама правка: снятый в M3 гард `proc.name not in self._restarting` в `_check_heartbeats` прикрывал микроокно (б). Без гарда это окно даёт ложное `recovered` и снимает сторож H3 (воспроизведено принудительным чередованием, N1). Правка — одна строка или атомарная пара. Если N1 не закрыть, третьего раунда нет: эскалация к teamlead.

## Чем проверено

| проверка | команда | итог |
|---|---|---|
| Тесты Ф1 + правок (43 файла) | `machine_gate.sh medium rs-review-r2 .venv/bin/python -m pytest -q --tb=short <43 файла>` | `686 passed, 2 warnings in 116.39s`; xfail H5 больше нет (зелёный); потоков `run-stop`/`run-fault-stop` после тестов нет, остались только `QueueFeederThread` (были и до Ф1) |
| Воспроизведения | `scratchpad/repro/repro_r2.py` через `machine_gate.sh light rs-review-r2` | вывод ниже |
| ruff | `ruff check -q multiprocess_framework/modules/process_manager_module Services/ml_inference multiprocess_prototype/backend/tests/test_activate_while_running.py` | exit 0 |
| Слой в тестах (M4) | `git grep -c -E "^\s*(from\|import) multiprocess_prototype" -- 'multiprocess_framework/**/tests/*.py'` | пусто (0) |
| Приватные методы в тестах (m4) | `grep -E "_run_stale_s\(\)\|_admission_stale_s\(\)\|\"fault_stop_done\" in"` по трём файлам | 0 строк |

Вывод `repro_r2.py` (дословно):
```
R1 STOP mode=executor_busy: reply={'success': True, 'accepted': True, 'state': 'stopping'} -> state=ready submit_calls=1 live_threads=[]
R1 STOP mode=system_stopping: ... -> state=ready submit_calls=1 live_threads=[]
R1 STOP mode=raise: ... -> state=ready submit_calls=1 live_threads=[]
R1 STOP mode=false_no_reply: ... -> state=ready submit_calls=1 live_threads=[]
R1b FAULT mode=executor_busy: state=fault fault_stop_done=True ack={'success': True, 'state': 'ready', 'error': None}
R1b FAULT mode=raise: state=fault fault_stop_done=True ack={'success': True, 'state': 'ready', 'error': None}
R1b FAULT mode=false_no_reply: state=fault fault_stop_done=True ack={'success': True, 'state': 'ready', 'error': None}
R5 bad max_retries: PM active=[] cfg=['restart_policy негоден: cam'] | monitor enabled=False flag=False valid=False | state=not_ready
R5 enabled as 1: PM active=['cam'] cfg=[] | monitor enabled=True flag=True valid=True | state=ready
R5 enabled as 'true': PM active=['cam'] cfg=[] | monitor enabled=True flag=True valid=True | state=ready
R5 bad, NO flag: PM active=[] cfg=['restart_policy негоден: cam'] | monitor enabled=False flag=False valid=False | state=not_ready
R3 new pid: restarting= [] state= ready
R7 after decision: restarting= ['cam'] pending_recovery= ['cam'] last_hb set= True deadline= True
R7 after _check_heartbeats: events= [('cam', 'recovered')] pending_recovery= [] deadline= False restarting= ['cam']
R9 global flag: PM active= ['cam', 'gui'] protected= ['ProcessManager', 'gui']
```

## Закрытие находок раунда 1

| № | закрыто? | чем |
|---|---|---|
| M1 | да | R1 (4 режима: `executor_busy`, `system_stopping`, исключение, `False` без ответа) -> `ready`, один вызов подачи, живых потоков нет; R1b (3 режима) -> `fault_stop_done=True`, `ack` успешен |
| M2 | да | R5: PM и монитор согласны во всех четырёх входах (раньше расходились в обе стороны) |
| M3 | да для листа и статуса; **регресс в микроокне — N1** | H5 стал зелёным (прогон без xfail); R3: новое воплощение снимает пометку |
| M4 | да | grep = 0; тест в `multiprocess_prototype/backend/tests/` и входит в прогон |
| M5 | да | 8 ветвей `error` в `registry.diagnose` — 8 `reason=` без значений; `_asset_reason = f"ml_inference: {reason}"`; в `health.degraded` и `last_error` — прежний текст со значениями. Буквально по контракту `readiness()` (`base.py`: «`reason` — БЕЗ значений входа: путь, ключ конфига, данные») — соответствует |
| m1 | да | `finish` зовёт `_run_apply("shutdown")`; инъекция J5 краснит `test_graceful_shutdown_from_running_refused_executor_leaves_running_no_more` (отчёт матрицы) |
| m2 | да | `eval_started < _run_running_mono` -> такт отброшен целиком; инъекция J6 краснит `test_stale_tick_after_start_does_not_fault` |
| m3 | да (для одиночного gave_up) | инъекция J11; групповой случай — ниже |
| m4 | да | grep = 0 |
| m5 | да | в выводе pytest нет `run-stop`/`run-fault-stop` |

## Изменения поведения

| изменение | оценка | вход -> результат, чем проверено |
|---|---|---|
| M1: отказ исполнителя -> одна последовательность на daemon-потоке | **улучшение** | R1/R1b: было «`stopping`/`fault` навсегда», стало `ready` / `ack` успешен. Двойное исполнение: `taken` под `once` пропускает только один обход; `on_reply` с результатом исполненного `action` (ошибка не из `refusals`) обход не заводит. Гонка с закрытием: поток видит `shutdown` через `_run_stop_cancel_source` и выходит без итога за ≤ 50 мс (шаг опроса). Поток без join при гашении PM — daemon, прерывается сам; приемлемо. Утечки нет (R1 `live_threads=[]`) |
| m1: `finish` подаёт `shutdown` | **улучшение** | J5 (отчёт матрицы); повтор после прохода — no-op по таблице (`shutdown` из `shutting_down`) |
| m2: устаревший такт отброшен | **улучшение** | J6. Сдвиг `down_since` отброшенным тактом **безвреден**: такт, начатый до START, оценён при `running=False`, а `restart_window` вне `running` даёт `{}` — то же значение, что держат все такты до START. Такты монитора идут последовательно на одном потоке, поэтому поздний `{}` не перетирает запись следующего такта (чтение `run_state.restart_window`, `_run_readiness_tick`) |
| M2: один разборщик | **улучшение** | R5 |
| M2: негодный per-process `restart_policy` без флага -> `failure`/`config` и `not_ready` | **улучшение (громкий отказ), риск для боевых рецептов низкий** | R5 «bad, NO flag» -> `not_ready`. Раньше супервизор молча брал глобальную политику (WARNING на каждом решении), и рецепт делал не то, что в нём написано. Все 9 блоков в репо проходят схему (проверка координатора). Решение (г) — за владельцем |
| M2: глобальная политика `enabled + run_auto_restart` включает флаг | **нейтрально с дырой — N2** | R9: флаг включается и у `protected` (GUI), которого супервизор не поднимает никогда |
| M2: проверка формы результата `resolve_policy` в PM | **костыль под двойник — N3** | `isinstance(resolved, tuple) and len(resolved) == 2` существует только из-за `MagicMock` в `make_pm` |
| M3: забор на входе, heartbeat без `pid` в перезапуске не принят | **улучшение** | H5 зелёный. Живого ребёнка без `pid` нет: один производитель heartbeat (`process_heartbeat.py:423`). Windows с повтором pid — не проверено (стенд) |
| M3: снят гард `not in self._restarting` в `_check_heartbeats` | **регресс — N1** | R7 |
| m3: `gave_up` снимает пометку | **улучшение** | J11. `_escalate_group_giveup` пометку членов не снимает — по чтению члены живы, их induced-рестарты уже исполнены или в плане, пометку снимет heartbeat нового воплощения. Остаток (в) — advisory, низкая серьёзность |
| M4, M5, m4, m5 | **улучшение** | таблица выше |

## Новые находки

### N1 [major, IPC/concurrency, регресс правки M3] Ложное `recovered` и потеря сторожа H3 в микроокне heartbeat × решение о рестарте

`process_monitor.py` `_on_heartbeat_received`: `_admit_heartbeat` решает под `_readiness_lock`, а `self._last_heartbeat[sender] = ts` пишется ПОСЛЕ, вне замка. Поток монитора в этот промежуток делает `_try_auto_restart`: `_last_heartbeat.pop`, затем `mark_restarting`. Время heartbeat, принятого до решения, ложится после `pop`. Гард `proc.name not in self._restarting` в `_check_heartbeats` это прикрывал; правка его сняла (инъекция J12 показала только, что тесты окно не трогают, а не что гард лишний).

Воспроизведение (принудительное чередование: обёртка над `_admit_heartbeat` вызывает настоящий `_try_auto_restart` между приёмом и записью времени):
```
R7 after decision: restarting= ['cam'] pending_recovery= ['cam'] last_hb set= True deadline= True
R7 after _check_heartbeats: events= [('cam', 'recovered')] pending_recovery= [] deadline= False restarting= ['cam']
```
Результат: событие `recovered` при ещё не исполненном рестарте; `_recovery_deadline` снят. Если рестарт потом тихо провалится, повтора и `gave_up` не будет, пометка `restarting` останется, и процесс навсегда «перезапускается супервизором» (система `not_ready`). Природная частота — окно в микросекунды × момент решения; выше всего при выходе из заморозки (heartbeat и решение `unresponsive` совпадают). Не мерил.

Решение (любое из двух): (а) вернуть гард `and proc.name not in self._restarting` в блок `recovered` — стоит ноль, и инвариант M3 держится при любом чередовании; (б) атомарно: `_admit_heartbeat` пишет `_last_heartbeat` под `_readiness_lock`, а `mark_restarting` сам делает `_last_heartbeat.pop` под тем же замком. Тест: обёртка-чередование как в R7, ожидаемое — `events == []`, `deadline` есть. Поправить docstring `_admit_heartbeat` («между решением и записью листа пометка не успеет встать» верно для листа, но не для `_last_heartbeat`).

### N2 [minor, architecture] Флаг автоперезапуска включается у `protected`-процесса

R9: глобальная политика `RestartPolicy(enabled=True, run_auto_restart=True)` -> PM `active= ['cam', 'gui']`, а `gui` в `protected`. `_try_auto_restart` для `protected` выходит сразу. Значит, падение GUI в `running` даёт 30 с `out_of_spec` «перезапуск gui» вместо `fault`, затем `fault` по сроку (вывод по `evaluate`; сам сценарий не запускал). Per-process флаг на `protected` давал то же и до правки; глобальный путь — новый. Решение: в `_run_auto_restart_flags` исключать `_get_protected_names()` (флаг на `protected` — причина `failure`/`config`, как «флаг без `enabled`»).

### N3 [minor, quality] Проверка формы `resolve_policy` в коде PM — под тест-двойник

`_run_auto_restart_flags`: `if not (isinstance(resolved, tuple) and len(resolved) == 2): continue` — комментарий сам говорит «монитор-двойник (MagicMock в тестах PM)». Это код боевого пути, подогнанный под двойник; та же форма уже есть в `_readiness_view`. Убрать: в `conftest.make_pm` создавать `MagicMock(spec=ProcessMonitor)` с `resolve_policy.return_value = (RestartPolicy(), True)` (и `readiness_view` аналогично), а в PM вызывать `resolve(name)` без проверки формы. Не блокер; можно в Task 3.2.

### N4 [minor, quality] Комментарий в `_check_heartbeats` теперь неверен

Над блоком `recovered`: «Семантика ТРИГГЕРА не тронута: его self-heal до диспатча остаётся честным recovered». После M3 heartbeat того же pid в перезапуске не принимается, поэтому self-heal до диспатча `recovered` не даёт — только новое воплощение. Комментарий искажает смысл (п.6 брифа). Заодно: фикстура `_join_run_sequence_threads` ждёт `run-stop`/`run-fault-stop`, но не `run-shutdown`.

## Матрица инъекций (J1–J12)

Дыры сверх J3/J4 (закрыты в fix-A2): (1) J12 — вывод «гард мёртв» верен только для набора тестов; теста на чередование heartbeat × решение нет (N1). (2) Нет теста на флаг у `protected` (N2). (3) Нет теста, что обход M1 для `run-shutdown` (без шагов) подаёт `shutdown` и взводит события стопа при отказе исполнителя — J1 говорит «+ допустимо graceful», отдельного красного нет.

## Остатки из OPEN_QUESTIONS (оценка)

- (а) STOP × graceful shutdown — было до правок; оба пути видят `shutdown` в машине и выходят; без воспроизведения. Низкая.
- (б) микроокно — **не остаток, а регресс правки: N1, major**.
- (в) `gave_up` группы — низкая (см. таблицу).
- (г) негодная политика -> `not_ready` — улучшение, решение владельца.
- ENOSPC на полном каталоге `process_manager_module/tests` (macOS, лимит семафоров) — не перепроверял; мой прогон по файлам зелёный.

## Эффективность

- M3: работы под замком не прибавилось (тот же опрос pid реестра до замка, те же операции под ним); чужой heartbeat теперь отбрасывается раньше — чуть меньше работы.
- m2: одно `time.monotonic()` на такт и одно сравнение под замком; отброшенный такт экономит публикацию — случай редкий, выигрыш пренебрежимый.
- M2: `resolve_policy` строит `RestartPolicy(**rp)` (валидация pydantic) на КАЖДОЙ оценке для каждого процесса набора (такт 0,5 с, плюс START/ack). Раньше — поиск в dict. Цену не мерил; по порядку величины это десятки мкс на процесс. Если понадобится — кэш по `id`/версии конфига.
- M1: на счастливом пути — пара замыканий на подачу, ноль потоков.
- Рычаг латентности из раунда 1 (push heartbeat при смене `ready`/блокирующих причин) **подтверждаю как рекомендацию; делать отдельной задачей** (новый механизм: слепой tester, матрица, стенд с замером задержки ЗАПУСТИТЬ), не в этой ветке.

## Стало ли лучше, надёжнее, эффективнее

**Частично.** Лучше и надёжнее — да по M1, M2, M3 (лист и статус), M4, M5, m1–m5: зависания `stopping`/`fault` нет, два разборщика стали одним, путь в причине исчез, слой в тестах чист. Один шаг назад — N1: снятие гарда ухудшило устойчивость к чередованию (ложное `recovered`, потеря сторожа H3). Эффективность — нейтрально: заметного выигрыша или потери нет, кроме неизмеренной цены разбора политики на каждой оценке.

## Что оставил открытым / ненадёжно

- R7 — принудительное чередование на двойниках (MockProcess, настоящий `ProcessMonitor`); природную частоту не знаю.
- N2 — последствие (30 с `out_of_spec` у GUI) выведено чтением `evaluate`, не запуском.
- Стенд, Windows (повтор pid), полный каталог тестов (ENOSPC) — не запускал.
- Матрицу J1–J12 не перепрогонял; опираюсь на `phase1-review-fixes.injection-result.md`.
- Цену `RestartPolicy(**rp)` на такт не мерил.
- Имя сессии гейта `rs-review-r2` — моё (в брифе его нет; `machine.lock` нет).
