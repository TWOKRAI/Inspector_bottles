# Ф1 run-state — ревью Opus на объединённый diff (стадия 5, 2026-11-15)

Диапазон: `git diff dd5378bb8 506eea281` (main, merge `506eea281`). Ревьюер: reviewer (Opus), read-only.
memory hits: `scripts/memory/search.py executor refusal reply stuck state` и `... incarnation pid heartbeat restart` -> прямых уроков нет (ближайшие: `feedback_single_marker_verdict_lies.md`, `feedback_absence_of_news_is_not_evidence.md`).

## Вердикт

**CHANGES REQUESTED (итерация 1 из 2).**

Основание: 5 major, все с воспроизведением (M1–M4) или с прочтением контракта и кода (M5). Blocker нет. Архитектура в целом верная: один писатель состояния (`_run_apply`), чистая таблица (`run_state.py`), транспорт готовности полем heartbeat, гейт через одно `mp.Event`. Дефекты — в краевых путях: отказ исполнителя, два разборщика конфига, неполный забор воплощения, слой в тестах, контракт причин.

## Чем проверено

| проверка | команда | итог |
|---|---|---|
| Тесты diff (39 файлов) | `machine_gate.sh medium rs-review-opus .venv/bin/python -m pytest -q --tb=line <39 файлов>` | `652 passed, 1 xfailed, 2 warnings in 117.47s`; xfail = strict H5 (см. M3); предупреждения — живые daemon-потоки `run-stop`/`run-fault-stop`/`QueueFeederThread` после тестов |
| Воспроизведения | `scratchpad/repro/repro_review.py`, `repro_review2.py` через `machine_gate.sh light` | вывод процитирован у каждой находки |
| Слои | `sentrux check .` | `43 rules checked … ✓ All rules pass` (правила тесты не покрывают — см. M4) |
| Импорты framework | `git diff … -- multiprocess_framework \| grep '^\+.*import'` | в коде framework новых импортов Services/Plugins/prototype нет; в тесте — есть (M4) |
| Секреты | `secrets_audit.py --format json --root multiprocess_framework/modules/process_manager_module` | exit 0, `total: 0` |
| Dict at Boundary (`severity`) | чтение `plugin_orchestrator._canonical_items` | закрыто: `severity` берётся из литерала `_SEVERITIES`, `reason` — `str(...)` |
| Стенд | — | НЕ запускался (heavy, окна нет; `machine.lock` нет — окно не запрашивал) |
| Матрицы инъекций | — | НЕ перепрогонялись; опираюсь на `*.injection-result.md` |

## Находки (по убыванию серьёзности)

### M1 [major, IPC] Отказ исполнителя `pm-lifecycle` вешает машину в `stopping` или `fault` навсегда

`process_manager_process.py` `_submit_run_sequence` (≈стр. 1779–1796). Контракт `OrderedExecutor.submit` (`worker_module/interfaces.py`): отказ = `reply({"success": False, "error": "executor_busy" | "system_stopping"})` и `False`, без исключения. Код ловит только исключение. `reply` для STOP и аварии — `lambda _result: None`. Ветка исключения доводит до итога только `run-stop`; для `run-fault-stop` итога нет. Docstring обещает «stopping не должно зависнуть» — это неверно. Нарушено правило design §3.2 п.3: «после срока `ack` разрешён».

Воспроизведение (PM из `make_readiness_pm`, двойник подачи с отказом по контракту):
```
R1 STOP reply: {'success': True, 'accepted': True, 'state': 'stopping'}
R1 state after 0.3s + 3 ticks: stopping event set: False
R1 start: {'success': False, 'state': 'stopping', 'error': 'stopping', 'reasons': []}
R1 stop again: {'success': True, 'accepted': False, 'state': 'stopping'}
R1b state: fault fault_stop_done: False ack_allowed: False
R1b ack: {'success': False, 'state': 'fault', 'error': 'fault_stopping'}
R6 state: fault fault_stop_done: False ack: {'success': False, 'state': 'fault', 'error': 'fault_stopping'}
R6 errors: ['run-fault-stop: исполнитель не принял последовательность (RuntimeError)']
```
Выход из `stopping` — только `system.shutdown` (`topology.apply` в `stopping` отказан). `executor_busy` — потолок очереди `_L_CAP + _T_CAP`; редко, но контрактно.

Решение: в `done` распознать отказ (результат-dict с `success: False`, `action` не исполнялся) и для обоих путей выполнить ту же последовательность на одноразовом daemon-потоке (ожиданию `paused` сериализация с L не нужна) либо итог сразу: STOP — `_run_stop_finish(fault=False, …)`, авария — `fault_stop_done` после ожидания. Ветку исключения сделать одинаковой для `run-stop` и `run-fault-stop`. Hazard-тест: двойник с отказом для STOP и для аварии, ожидаемое — `ready`/`not_ready` и `ack_allowed: True` к сроку.

### M2 [major, architecture] Два разборщика `restart_policy`: PM и супервизор расходятся в обе стороны (C5)

PM `_run_auto_restart_flags` читает сырой dict (`enabled is True`, `run_auto_restart is True`). Монитор `_resolve_policy` строит `RestartPolicy(**rp)` (схема уже несёт `run_auto_restart`, `restart_policy.py:86`), при ошибке — глобальная политика. Два источника правды о «супервизор поднимет».

Воспроизведение:
```
R5 bad max_retries: PM flag active=['cam'] config_reasons=[] | monitor enabled=False run_auto_restart=False
R5 enabled as 1: PM flag active=[] config_reasons=['cam: `run_auto_restart` требует `enabled: true`'] | monitor enabled=True run_auto_restart=True
R5 enabled as 'true': PM flag active=[] config_reasons=['cam: `run_auto_restart` требует `enabled: true`'] | monitor enabled=True run_auto_restart=True
```
Следствие 1: при негодной политике никто не перезапускает, а PM 30 с держит `running` с `out_of_spec` «перезапуск cam», потом `fault`; ошибка конфига в причинах не видна. Следствие 2: супервизор перезапускает, а PM держит `not_ready` с ложной ошибкой конфига навсегда.

Решение: один разборщик. PM берёт решённую политику у монитора (публичный `resolve_policy(name)` поверх `_resolve_policy`) и читает поля схемы. Негодный per-process dict — причина `failure`/`config` «restart_policy негоден» (без значений). Тесты — три входа выше, ожидаемые литералы.

### M3 [major, architecture] Забор воплощения стоит в одном потребителе, а не на входе heartbeat

`process_monitor.py` `_on_heartbeat_received`: проверка pid есть только в `_accept_readiness` (лист). `_last_heartbeat` и статус `previous_states` принимают heartbeat старого воплощения. Плюс отдельная заплатка в `_check_heartbeats` (`proc.name not in self._restarting`). Это защита по симптому, потребитель за потребителем.

Воспроизведение: strict-xfail в diff — `test_supervisor_restart_incarnation_hazards.py::test_late_old_pid_heartbeat_status_does_not_overwrite_new_incarnation_status` (прогон: `1 xfailed`). Вход: поздний heartbeat `pid 41001, status: paused` после рестарта. Результат: статус нового воплощения становится `paused` (текст xfail: «выдаёт новому воплощению чужой статус»).

Решение: в начале `_on_heartbeat_received` один раз решить «сообщение текущего воплощения?» (pid целый, pid реестра известен и не равен -> чужое; в `_restarting` и не новое -> чужое). Чужое не трогает ни `_last_heartbeat`, ни статус, ни лист. Тогда гард в `_check_heartbeats` и xfail уходят. Один механизм вместо трёх.

### M4 [major, architecture] Тест framework импортирует prototype (первый прецедент)

`multiprocess_framework/modules/recipe/tests/test_activate_while_running.py:60` — `from multiprocess_prototype.orchestrator import build_recipe_service`; `:34` читает `multiprocess_prototype/recipes/bridge_synth.yaml`. На `dd5378bb8` таких тестов во framework — 0 (`git grep -l -E "^\s*(from|import) multiprocess_prototype" dd5378bb8 -- 'multiprocess_framework/**/tests/*.py' | wc -l` -> `0`). Нарушен слой (принцип 1: framework не зависит от prototype). `sentrux check` это не ловит — правила не покрывают тесты.

Решение: перенести тест в `multiprocess_prototype/tests/` (он проверяет проводку prototype) либо собрать `RecipeService` во framework-фикстуре без prototype.

### M5 [major, spec] Первый реализатор `readiness()` нарушает контракт хука из того же diff (C3)

`plugins/base.py` `readiness()`: «`reason` — короткий текст БЕЗ значений входа: путь, ключ конфига, данные — в `log_*`». `Services/ml_inference/plugin/plugin.py:344` кладёт в причину `diagnosis.message`; `core/registry.py` даёт `f"каталог моделей не найден: {root}"` (абсолютный путь) и `f"нет sidecar … для модели '{model_id}'"`; `plugin.py:316` — `f"не удалось загрузить '{self._reg.model}'…"`. Причина уходит через heartbeat в `system.run.reasons` и в GUI. Тест `test_readiness_reason.py:121` проверяет только префикс `ml_inference: ` — путь в тексте не ловит. Воспроизведение запуском не делал (вывод из чтения кода и контракта) — по правилу это advisory по степени, но контракт и код однозначны.

Решение: в причину — код/короткий текст без значений («ассеты модели непригодны: нет каталога моделей»), значения — в `log_*`/`last_error`. Тест на отсутствие `/` и id модели в `reason`.

### m1 [minor, advisory] Graceful `system.shutdown` из `running`: отказ `_pre_stop_executor` оставляет `running`

`_shutdown_graceful`: при `from_running` `_run_apply("shutdown")` зовёт только `_run_shutdown_pass`. Отказ `executor.submit` зовёт `finish` (= `_finish_pre_stop`), `shutdown` в машину не подаётся: в ходе стопа системы статус `running`, `run_event` взведён. Без воспроизведения. Решение: в `finish` подать `_run_apply("shutdown")` (идемпотентно).

### m2 [minor, advisory] Такт оценивается вне `_run_lock`: старый `tick` может лечь после START

`_run_readiness_tick`: `evaluate` (и чтение `running`) вне замка, затем `_run_apply("tick")`. Последовательность «такт оценил `ready=False` -> готовность вернулась -> START принят -> такт применён» даёт `fault` сразу после START. Нужен перелёт готовности внутри окна в миллисекунды; без воспроизведения. Решение: `_run_apply` отбрасывает `tick`, оценка которого начата раньше последнего входа в `running` (`eval_started < _run_since`).

### m3 [minor, advisory] После `gave_up` причина говорит «перезапускается супервизором»

Пометка `_restarting` при отказе супервизора не снимается; `_process_reasons` отдаёт её первой. Вне `running` оператор видит «перезапускается», хотя супервизор сдался. Решение: при `gave_up` снимать пометку (процесс мёртв — причина «процесс не жив») или давать текст по `given_up`.

### m4 [minor, tests] Тесты сверяют приватные методы

`test_run_admission_margin.py:58-63`, `test_run_state_hazards.py:255-261` — `pm._run_stale_s()`, `pm._admission_stale_s()`; `test_run_stop.py` ищет атрибут по подстроке `fault_stop_done`. Правило §9: эффект, не имя реализации. Литералы — да (`== 15.0`, `== 10.0`), vacuous-тестов в просмотренных файлах не нашёл (просмотр выборочный).

### m5 [minor, tests] Утечка потоков в тестах

Вывод pytest: потоки `run-stop`, `run-fault-stop` живы после `test_run_state_hazards.py::test_ticks_beats_and_starts_race_keep_event_equal_state` и др. Источник — ветка `threading.Thread(...)` в `_submit_run_sequence` у PM без исполнителя. Решение: фикстура ждёт/гасит поток, либо тестовый исполнитель.

## Таблица C1–C12

| № | вердикт | чем проверено |
|---|---|---|
| C1 `_admission_stale_s` | **оставить как гистерезис, не заплатка** (см. C12). Механизм: удержание 15 с, допуск 10 с — допуск строже на один интервал | чтение `_admission_stale_s`; тест `test_run_admission_margin.py` зелёный (литералы 15.0/10.0, 6.0/4.0) |
| C2 опрос, задержка до 5 с | **подтверждаю, открыто**. Push только на смену `paused` (`push_if_paused_changed`); смена `ready`/блокирующих причин ждёт обычного heartbeat (до `heartbeat_interval` + 0,5 с) | чтение `process_heartbeat.py`, `process_module.py` |
| C3 причины ml_inference | **подтверждаю, хуже заявленного** — нарушение контракта хука (M5) | чтение `plugin.py:316,344`, `registry.py` |
| C4 `_skipped_requires` по имени | подтверждаю, minor; кортеж неизменяемый, чтение без замка безопасно | чтение `plugin_orchestrator.py` |
| C5 флаг в сыром `restart_policy` | **дефект** (M2): проглатывание есть — негодная политика молча включает окно | R5 |
| C6 россыпь kwargs | **закрыт**: `EvalInput` (frozen dataclass) | чтение `run_state.py:52-76` |
| C7 размер PM-файла | подтверждаю: 5745 -> 6493 строк (`git show <sha>:… \| wc -l`); вынос `run_control` — отдельная задача | `wc -l` |
| C8 стенд только macOS | подтверждаю; добавляю риск повторного pid на Windows (C11) | — |
| C9 пустой `label` | по дизайну, ок | чтение `_boot_progress_finish` |
| C10 причины отказа | **закрыт**: `reasons` пишутся только при `code is None or new is not prev` | чтение `_run_apply`; `test_run_refusal_keeps_reasons_hazards.py` зелёный |
| C11 `pid` в heartbeat | поле — ок, cto для поля не нужен (см. ниже); забор неполный (M3) | R3, grep производителей heartbeat |
| C12 гистерезис + воплощение | **не дубль**: разные классы отказа (замороженный ребёнок без решения супервизора vs. воплощение после рестарта). Оставить оба, записать в ADR (2.5) | чтение; A/B 1.7b в отчёте лида (не перепроверял) |

**C11 — вердикт.** Производитель heartbeat один: `process_heartbeat.py:423` (`git grep '"command": "heartbeat"'` вне тестов — одна строка кода). Значит «ребёнок без `pid`» в живой системе не встречается. Строгость видна на R3: `restarting: ['cam'] state: not_ready`, причина `cam: перезапускается супервизором` держится, пока heartbeat без `pid`. `pid` уже служит маркером замены инстанса в `supervision.status` («pid+instance_restarts») — поле согласовано с существующей идентичностью. Вывод: поле аддитивное, внутри framework (оба конца — PM и `ProcessModule`); **эскалация в cto не обязательна**, нужна запись ADR-PMM и строка в README контракта heartbeat. В cto — только если лид решит менять маркер воплощения (pid -> жетон спавна) из-за повторного pid на Windows: это меняет kwargs спавна.

## Архитектура и эффективность

- Единая точка записи: все переходы — через `_run_apply` под `_run_lock`. Вне `_run_apply` пишут `_fault_stop_done` (`_run_stop_finish`, `_start_fault_stop`) и снимают событие (`_run_stop_clear_event`) — тоже под `_run_lock`, с проверкой `_fault_seq`/состояния. Обхода таблицы не нашёл.
- Два понятия «готов» (барьер boot и лист) — сознательное решение design §3.3; гейт START смотрит только лист; `start_allowed`/`ack_allowed` выводятся из состояния. Третий источник — health — мостом не связан (C3).
- Нагрузка: ребёнок — `run_watch` 20 Гц (только с оркестратором), снимок 2 Гц, `is_set()` на `mp.Event`; PM — такт монитора 0,5 с (`monitor_poll_interval`), ожидание `paused` 50 мс. Для N ≈ 10 процессов это ~200 пробуждений/с суммарно — дёшево. Лучший рычаг латентности не частота, а push на смену `ready`/блокирующих причин тем же путём, что 1.2c: доступность START с ≤ 5,5 с до ≤ ~1 с, `stale_s` и окно `fault` не меняются.
- Окно `fault` при заморозке (15,27 с при допуске 16 с) — следствие `stale_s = 3 × interval`; не перемерял.
- Размер PM-класса растёт (C7); run-state добавил ~50 методов — компонент `run_control` снизит связность.

## Что оставил открытым / ненадёжно

- Стенд не запускал (heavy, окна нет): не перепроверены 1.8b (второй `kill -9`), окно `fault` 15,27 с, Windows, реальный `pre_stop`.
- Матрицы инъекций не перепрогонял; «тест краснеет при откате» знаю только из отчётов.
- M1, M2, M3: воспроизведения на двойниках (`make_readiness_pm`, MockProcess), не на живых процессах. M1 зависит от отказа исполнителя — на живой системе нужен полный потолок очереди; частоту не знаю.
- M5, m1, m2, m3 — выведены чтением, без запуска.
- Тесты просматривал выборочно (grep по константам и приватным методам), не все 10 270 строк.
- Повтор pid на Windows для забора воплощения — гипотеза, не проверена.
- Сессия gate `rs-review-opus` — имя моё (в брифе имени нет, `machine.lock` нет).
