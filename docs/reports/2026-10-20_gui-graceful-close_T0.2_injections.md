# Task 0.2 — матрица инъекций (прогнозы лида до прогона)

Лид: inspector-bottles-cc, 2026-10-20. Прогнозы записаны ДО любого прогона инъекций. База — зелёная реализация
(U + D: 20 passed). Каждая инъекция — отдельно, откат перед следующей. Набор U+D — без `-k`, collected числом.

U = `multiprocess_framework/modules/process_manager_module/tests/test_system_shutdown_force.py`,
D = `backend_ctl/tests/test_system_shutdown_driver.py`, L = `backend_ctl/tests/test_system_shutdown_force_live.py`.

| № | Инъекция (что ломаем) | Прогноз: красные | Прогноз: остальные |
|---|---|---|---|
| И1 | `_ChildrenStop.join_until` без `min` (срок группе — исходный `deadline`) | U::caps[0.1, 0.5, 1.0, 5.0], U::before_group_exists, U::join_after_kill_not_capped; L6 (окно) | зелёные |
| И2 | срок жёстко 1,0 (`deadline_s` игнорируется в `set_force_deadline`) | U::caps[0.1], [0.5], [5.0]; U::caps[1.0] зелёный | зелёные |
| И3 | повторный `set_force_deadline` перезаписывает срок | U::sets_deadline_then_events_and_replies_immediately | зелёные |
| И4 | убрать проверку `bool` у `deadline_s` | U::bad_mode_or_deadline_rejected[True] (ровно 1 параметр) | зелёные |
| И5 | драйвер: `pm_gone=True` по истечении `wait_timeout` | D::wait_distinguishes[никогда] (1 параметр) | зелёные |
| И6 | graceful тоже ставит срок (`set_force_deadline` в graceful-ветке) | U::graceful_unchanged_no_force_deadline — оба параметра | зелёные |
| И7 | нет записи `system_shutdown` в `TOOL_SAFETY` | D::test_mcp_tool_registered_as_escalated | зелёные |
| И8 | обрезка всегда (без проверки `_killed`) | U::join_after_kill_not_capped; L6 (окно: «ВЫЖИЛИ»/код ≠ 0) | зелёные |
| И9 | события взводятся ДО `set_force_deadline` (порядок шага 2) | 0 красных — слепое пятно (однопоточный тест порядка не видит); наблюдение, не дефект теста | все зелёные |
| И10 | проверка аргументов ПОСЛЕ взведения событий | U::bad_mode_or_deadline_rejected — все 7 параметров | зелёные |
| И11 | драйвер ждёт при `accepted is False` (откат решения лида) | 0 красных — тестов на это нет (правка лида после стадии 1); наблюдение | все зелёные |

## Результат

Набор скрипта: U + D (L в скрипте не прогонялся, поэтому строки L6 не наблюдались). Collected = 20 на каждой строке.

| № | Прогноз: красные | Наблюдено: красные | Сводка pytest | Совпало? |
|---|---|---|---|---|
| И1 | U::caps[0.1, 0.5, 1.0, 5.0], U::before_group_exists, U::join_after_kill_not_capped; L6 | U::caps[0.1, 0.5, 1.0, 5.0], U::before_group_exists, U::join_after_kill_not_capped, U::sets_deadline_then_events_and_replies_immediately | 7 failed, 13 passed | нет — лишний U::sets_deadline_then_events_and_replies_immediately; L6 не прогонялся скриптом |
| И2 | U::caps[0.1], [0.5], [5.0]; caps[1.0] зелёный | U::before_group_exists, U::caps[0.1], [0.5], [5.0] | 4 failed, 16 passed | нет — лишний U::before_group_exists (в прогнозе не назван) |
| И3 | U::sets_deadline_then_events_and_replies_immediately | U::sets_deadline_then_events_and_replies_immediately | 1 failed, 19 passed | да |
| И4 | U::bad_mode_or_deadline_rejected[deadline-True] | U::bad_mode_or_deadline_rejected[deadline-True] | 1 failed, 19 passed | да |
| И5 | D::wait_distinguishes[никогда] | D::wait_distinguishes_gone_from_timeout[never-lost] | 1 failed, 19 passed | да (id «never-lost» сопоставлен с «никогда» по смыслу, не проверено по исходнику) |
| И6 | U::graceful_unchanged_no_force_deadline — оба параметра | U::graceful_unchanged_no_force_deadline[graceful-ignores-deadline], [no-args] | 2 failed, 18 passed | да |
| И7 | D::test_mcp_tool_registered_as_escalated | D::test_mcp_tool_registered_as_escalated | 1 failed, 19 passed | да |
| И8 | U::join_after_kill_not_capped; L6 | U::join_after_kill_not_capped | 1 failed, 19 passed | нет — L6 не прогонялся скриптом |
| И9 | 0 красных | U::sets_deadline_then_events_and_replies_immediately | 1 failed, 19 passed | нет — лишний красный U::sets_deadline_then_events_and_replies_immediately (слепое пятно не подтвердилось) |
| И10 | U::bad_mode_or_deadline_rejected — все 7 параметров | U::bad_mode_or_deadline_rejected[deadline-0.05], [deadline-5.1], [deadline-True], [deadline-inf], [deadline-nan], [deadline-str], [mode-x]; U::sets_deadline_then_events_and_replies_immediately | 8 failed, 12 passed | нет — лишний U::sets_deadline_then_events_and_replies_immediately |
| И11 | 0 красных | 0 красных | 20 passed, rc=0 | да |
| БАЗА | зелёная (20 passed) | 0 красных | 20 passed, rc=0 | да |
| БАЗА после отката | (прогноза нет; ожидание — зелёная) | 0 красных | 20 passed, rc=0 | да |

### Вердикт лида (против прогнозов)

- Каждая инъекция И1–И10 даёт ≥ 1 красного; база зелёная до и после отката (20 passed, collected 20 на каждой строке).
- Расхождения И1, И2, И9, И10 — только ЛИШНИЕ красные; это находка о модели лида, не о тестах:
  U1 (`test_force_sets_deadline_then_events_and_replies_immediately`) через шпиона на `set()` событий проверяет, что срок
  уже стоял (`:163-168`), — ловит И9 (порядок) и И10 (события до проверки аргументов); он же проверяет срок повтора через
  join (`:172-179`) — ловит И1. U3 (`before_group_exists`) работает со сроком 0,5 — ловит И2. Прогноз И9 «слепое пятно»
  ошибочен: слепоты нет.
- И11 — 0 красных, как предсказано: правка лида после стадии 1 без теста. Закрывается авторским тестом
  `backend_ctl/tests/test_system_shutdown_driver_author.py::test_rejected_command_returns_without_wait` с собственной
  проверкой укуса (результат — ниже, отдельной строкой).
- И1 и И8 на L6 — в окне стенда (L скриптом не гонялся).

Raw-вывод скрипта (1:1 из прогона, без правок):

```text
=== БАЗА: gate rc=0; ======================== 20 passed, 1 warning in 2.40s ========================
=== И1: gate rc=1; =================== 7 failed, 13 passed, 1 warning in 1.91s ===================
    FAILED test_force_before_group_exists_applies_when_group_appears
    FAILED test_force_caps_children_join_at_deadline[0.1]
    FAILED test_force_caps_children_join_at_deadline[0.5]
    FAILED test_force_caps_children_join_at_deadline[1.0]
    FAILED test_force_caps_children_join_at_deadline[5.0]
    FAILED test_force_sets_deadline_then_events_and_replies_immediately
    FAILED test_join_after_kill_not_capped
=== И2: gate rc=1; =================== 4 failed, 16 passed, 1 warning in 1.85s ===================
    FAILED test_force_before_group_exists_applies_when_group_appears
    FAILED test_force_caps_children_join_at_deadline[0.1]
    FAILED test_force_caps_children_join_at_deadline[0.5]
    FAILED test_force_caps_children_join_at_deadline[5.0]
=== И3: gate rc=1; =================== 1 failed, 19 passed, 1 warning in 2.01s ===================
    FAILED test_force_sets_deadline_then_events_and_replies_immediately
=== И4: gate rc=1; =================== 1 failed, 19 passed, 1 warning in 2.06s ===================
    FAILED test_bad_mode_or_deadline_rejected_no_event_set[deadline-True]
=== И5: gate rc=1; =================== 1 failed, 19 passed, 1 warning in 1.91s ===================
    FAILED test_wait_distinguishes_gone_from_timeout[never-lost]
=== И6: gate rc=1; =================== 2 failed, 18 passed, 1 warning in 2.03s ===================
    FAILED test_graceful_unchanged_no_force_deadline[graceful-ignores-deadline]
    FAILED test_graceful_unchanged_no_force_deadline[no-args]
=== И7: gate rc=1; =================== 1 failed, 19 passed, 1 warning in 1.88s ===================
    FAILED test_mcp_tool_registered_as_escalated
=== И8: gate rc=1; =================== 1 failed, 19 passed, 1 warning in 1.81s ===================
    FAILED test_join_after_kill_not_capped
=== И9: gate rc=1; =================== 1 failed, 19 passed, 1 warning in 1.96s ===================
    FAILED test_force_sets_deadline_then_events_and_replies_immediately
=== И10: gate rc=1; =================== 8 failed, 12 passed, 1 warning in 1.86s ===================
    FAILED test_bad_mode_or_deadline_rejected_no_event_set[deadline-0.05]
    FAILED test_bad_mode_or_deadline_rejected_no_event_set[deadline-5.1]
    FAILED test_bad_mode_or_deadline_rejected_no_event_set[deadline-True]
    FAILED test_bad_mode_or_deadline_rejected_no_event_set[deadline-inf]
    FAILED test_bad_mode_or_deadline_rejected_no_event_set[deadline-nan]
    FAILED test_bad_mode_or_deadline_rejected_no_event_set[deadline-str]
    FAILED test_bad_mode_or_deadline_rejected_no_event_set[mode-x]
    FAILED test_force_sets_deadline_then_events_and_replies_immediately
=== И11: gate rc=0; ======================== 20 passed, 1 warning in 1.99s ========================
=== БАЗА после отката: gate rc=0; ======================== 20 passed, 1 warning in 1.90s ========================
```

## Стенд (окно 20:05–20:30) — прогнозы лида ДО прогона

L = `backend_ctl/tests/test_system_shutdown_force_live.py`, `--backend-live`, порты 7920–7929, класс heavy.

| Прогон | Код | Прогноз |
|---|---|---|
| S1 красная база | worktree tester, f2008ee01 (до правки) + файлы tester | L6 красный: выход PM ≥ 5,0 с (terminate на +5), строки `force: срок стопа детей` нет; smoke красный (`AttributeError`); L7 (страж) зелёный. Выход < 5,0 с — неверная база (не провал реализации), стоп и решение лида |
| S2 зелёный | worktree реализации, b8197afd1 | L6: 5/5 выход < 4,0 с, медиана ≤ 2,5 с, код PM 0, `ВЫЖИЛИ` 0, `did not stop in X.Xs, terminating` есть; L7 зелёный; smoke зелёный |
| S3 И1 на L6 | b8197afd1 + `join_until` без `min` | L6 красный: выход ≥ 5,0 с |
| S4 И8 на L6 | b8197afd1 + обрезка всегда | L6 красный: код PM 76 или строка `ВЫЖИЛИ`; время выхода может быть < 4,0 |

## Стенд — наблюдено

Исполнитель: junior (haiku), прогоны строго по порядку S1 → S2 → S3+S4, один бэкенд за раз. Предикты не менялись.

| Прогон | Прогноз (из таблицы выше) | Наблюдено (статус по тестам, числа из сообщений) | Совпало? |
|---|---|---|---|
| S1 красная база (tester, до правки) | L6 красный: выход PM ≥ 5,0 с, строки `force: срок стопа детей` нет; smoke красный (`AttributeError`); L7 зелёный | L6 `test_force_with_hung_child_tree_gone_fast` FAILED; smoke `test_driver_system_shutdown_live_smoke` FAILED; L7 `test_force_on_healthy_system_not_slower_than_graceful` PASSED. Время выхода, текст `AttributeError` и наличие строки `force:` в логе S1 НЕ СОБРАНЫ: `tail -60` обрезал сообщения падений, PM-логи собраны только для S2 | Частично: статусы совпали; числа и причина не проверены |
| S2 зелёный (реализация b8197afd1) | L6 5/5 выход < 4,0 с, медиана ≤ 2,5 с, код PM 0, `ВЫЖИЛИ` 0, `did not stop in X.Xs, terminating` есть; L7 зелёный; smoke зелёный | L6 FAILED (1 тест из 1 падающих в прогоне; сообщение падения не в `tail -60`, 5/5, медиана и коды не собраны). L7 PASSED. smoke PASSED. Строк `ВЫЖИЛИ` в логах: 0. `did not stop in 0.9s, terminating`: 6 строк. `force: срок стопа детей 1.0 с`: 6 строк; `… 5.0 с`: 10 строк. Строка закрытия корня (smoke): `survivors=[] killed=['proc/ProcessManager/work/children/processes'] errors=[] emits_after_close=0 complete=True elapsed=1.000s` | Нет: L6 красный вместо зелёного. Причина НЕ установлена |
| S3 И1 на L6 (`join_until` без `min`) | L6 красный: выход ≥ 5,0 с | L6 FAILED (101,15 с прогона). Время выхода не собрано | Да по статусу; число не проверено |
| S4 И8 на L6 (обрезка всегда) | L6 красный: код PM 76 или `ВЫЖИЛИ`; время < 4,0 возможно | L6 FAILED (61,67 с прогона). Код PM и `ВЫЖИЛИ` не собраны (лог-сбор после S3/S4 не запускался) | Да по статусу; код/строка не проверены |

Предпрогонные проверки (перед каждым шагом; порог `ram_free_mb` ≥ 500, процессов `gui-close-0.2` = 0):

| Шаг | ram_free_mb | процессов python `gui-close-0.2` | Итог |
|---|---|---|---|
| S1 | 2163 | 0 | прогон |
| S2 | 2692 | 0 | прогон |
| S3+S4 | 2652 | 0 | прогон |

Сырые хвосты.

S1 (`tail -60`, начало обрезано), последние строки:

```text
WARNING  multiprocess_framework.modules.channel_routing_module.core.channel_routing_manager:_fallback.py:67 [WARNING] [logger_launcher] [system] приёмники не приняли ни одной записи за прогон: performance_file — проверьте правила маршрутизации и пороги (список также в introspect.observability -> effective.*.idle_sinks)
=========================== lifecycle-guards report ===========================
G3 unclosed roots: 0
G4 threads without scope path: 0
=========================== short test summary info ===========================
PASSED backend_ctl/tests/test_system_shutdown_force_live.py::test_force_on_healthy_system_not_slower_than_graceful
FAILED backend_ctl/tests/test_system_shutdown_force_live.py::test_force_with_hung_child_tree_gone_fast
FAILED backend_ctl/tests/test_system_shutdown_force_live.py::test_driver_system_shutdown_live_smoke
============= 2 failed, 1 passed, 1 warning in 338.08s (0:05:38) ==============
```

S2 (`tail -60`, начало обрезано), последние строки:

```text
PASSED backend_ctl/tests/test_system_shutdown_force_live.py::test_driver_system_shutdown_live_smoke
FAILED backend_ctl/tests/test_system_shutdown_force_live.py::test_force_with_hung_child_tree_gone_fast
FAILED backend_ctl/tests/test_system_shutdown_force_live.py::test_force_on_healthy_system_not_slower_than_graceful
============= 2 failed, 1 passed, 1 warning in 329.29s (0:05:29) ==============
```

S2, PM-строки из newest pytest temp dir (кодировка исправлена повторным чтением; в первом чтении кириллица побилась, данные те же), 16 строк `force:` и 6 строк `did not stop`, все строки:

```text
#76 2026-10-20 20:13:36,989 [INFO] [ProcessManager] ProcessManager: force: срок стопа детей 1.0 с
#75 2026-10-20 20:13:49,122 [INFO] [ProcessManager] ProcessManager: force: срок стопа детей 1.0 с
#75 2026-10-20 20:14:02,586 [INFO] [ProcessManager] ProcessManager: force: срок стопа детей 1.0 с
#75 2026-10-20 20:14:15,730 [INFO] [ProcessManager] ProcessManager: force: срок стопа детей 1.0 с
#76 2026-10-20 20:14:29,435 [INFO] [ProcessManager] ProcessManager: force: срок стопа детей 1.0 с
#75 2026-10-20 20:14:41,774 [INFO] [ProcessManager] ProcessManager: force: срок стопа детей 1.0 с
#75 2026-10-20 20:15:04,795 [INFO] [ProcessManager] ProcessManager: force: срок стопа детей 5.0 с
#75 2026-10-20 20:15:29,459 [INFO] [ProcessManager] ProcessManager: force: срок стопа детей 5.0 с
#75 2026-10-20 20:15:53,760 [INFO] [ProcessManager] ProcessManager: force: срок стопа детей 5.0 с
#75 2026-10-20 20:16:18,746 [INFO] [ProcessManager] ProcessManager: force: срок стопа детей 5.0 с
#76 2026-10-20 20:16:44,664 [INFO] [ProcessManager] ProcessManager: force: срок стопа детей 5.0 с
#75 2026-10-20 20:17:09,568 [INFO] [ProcessManager] ProcessManager: force: срок стопа детей 5.0 с
#76 2026-10-20 20:17:34,203 [INFO] [ProcessManager] ProcessManager: force: срок стопа детей 5.0 с
#75 2026-10-20 20:17:58,273 [INFO] [ProcessManager] ProcessManager: force: срок стопа детей 5.0 с
#75 2026-10-20 20:18:21,101 [INFO] [ProcessManager] ProcessManager: force: срок стопа детей 5.0 с
#75 2026-10-20 20:18:43,148 [INFO] [ProcessManager] ProcessManager: force: срок стопа детей 5.0 с
#86 2026-10-20 20:13:37,984 [WARNING] [ProcessManager] ProcessManager: Process 'storage' did not stop in 0.9s, terminating...
#84 2026-10-20 20:13:50,131 [WARNING] [ProcessManager] ProcessManager: Process 'storage' did not stop in 0.9s, terminating...
#85 2026-10-20 20:14:03,583 [WARNING] [ProcessManager] ProcessManager: Process 'storage' did not stop in 0.9s, terminating...
#85 2026-10-20 20:14:16,722 [WARNING] [ProcessManager] ProcessManager: Process 'storage' did not stop in 0.9s, terminating...
#85 2026-10-20 20:14:30,449 [WARNING] [ProcessManager] ProcessManager: Process 'storage' did not stop in 0.9s, terminating...
#84 2026-10-20 20:14:42,777 [WARNING] [ProcessManager] ProcessManager: Process 'storage' did not stop in 0.9s, terminating...
```

Строка с `survivors after root close` и `ВЫЖИЛИ` в логах не найдена (искомый текст в логе — `root close … survivors=[]`, см. stdout smoke в S2).

S3+S4 (`tail -80`), итоги:

```text
=== И1: gate rc=1; =========== 1 failed, 2 deselected, 1 warning in 101.15s (0:01:41) ============
    FAILED test_force_with_hung_child_tree_gone_fast
=== И8: gate rc=1; ============ 1 failed, 2 deselected, 1 warning in 61.67s (0:01:01) ============
    FAILED test_force_with_hung_child_tree_gone_fast
```

git status после всех прогонов (`cd "$IW" && git status --short`):

```text
?? backend_ctl/tests/test_system_shutdown_driver_author.py
?? docs/reports/2026-10-20_gui-graceful-close_T0.2_impl.md
?? docs/reports/2026-10-20_gui-graceful-close_T0.2_injections.md
```

`git diff --stat` пустой: src и тесты не изменены, инъекции откатились.

## Что осталось открытым / ненадёжно

- Причина падения L6 в S2 (реализация) не установлена: сообщение падения не попало в `tail -60`. Нужен отдельный прогон с `-k test_force_with_hung_child_tree_gone_fast` и полным выводом; я его не запускал (один прогон на шаг, без повторов).
- Числа (время выхода, медиана, коды PM) для S1/S3/S4 не собраны: не было вывода в хвостах, а PM-лог собирался только после S2.
- `smoke` в S1: `AttributeError` не подтверждён текстом.
- Загрузка CPU во время S2 была 77% (при S1 46%, при S3+S4 53%); влияние на тайминги L6 не измерялось.

### Поправки лида к «Стенд — наблюдено» (по сырым хвостам выше, 20:35)

- **S2: L7 КРАСНЫЙ**, не PASSED, как стоит в таблице: сырой хвост S2 — `PASSED …smoke`, `FAILED …L6`, `FAILED …L7`,
  `2 failed, 1 passed` (329 с). Причину красного L7 хвост не показал (`tail -60` обрезал), установит следующий стенд.
- S1 по сырому хвосту: `PASSED …L7`, `FAILED …L6`, `FAILED …smoke`, `2 failed, 1 passed` (338 с) — как прогноз.
- S2 L6 (повтор лида, только L6, полный вывод в `scratchpad/s2_l6_full.txt`): красный ТОЛЬКО на ассерте INFO
  `force: срок стопа детей 1.0 с` у прогона 1. Доказано для всех 5: выход < 4,0 с, медиана ≤ 2,5 с. Код 0, «ВЫЖИЛИ» 0,
  terminate у `storage` — только прогоны 0–1, т.к. цикл проверок остановился на прогоне 1.
- Причина (investigator, воспроизведено без бэкенда): `multiprocess_prototype/backend/launch.py:669`
  `os.environ.setdefault("INSPECTOR_LOG_DIR", …)` закрепляет каталог первого `build()` на весь процесс pytest. PM и
  лаунчер берут каталог из env, поэтому логи PM всех 5 прогонов легли в `run_0` (5 строк INFO, по одной на прогон).
  Дефект старый, есть на main.
- Вывод: S3/S4 (И1/И8 на L6) НЕ В ЗАЧЁТ — L6 красный уже на реализации. Повтор — после правки логов, с поимённым
  прогнозом ассертов.

### Находка о процессе (координатор inspector-bottles-42, 20:40)

Сводная таблица агента-исполнителя стенда (Haiku) записала L7 в S2 как PASSED при красном сыром хвосте. Правило для
этой задачи и дальше: сводку агента сверять с сырым выводом, таблице не верить; полный вывод прогона — в файл, не
`tail -N` (обрезанный хвост скрыл причины падений S1–S4 — дефект брифа лида).

## Повтор после правок (HEAD fix(launch)…) — прогнозы лида ДО прогона

### Юнит-матрица v2 (light): U, D, U-author (`test_system_shutdown_force_author.py`), D-author, `test_launch_log_dir.py`

| № | Прогноз: красные (остальное зелёное) |
|---|---|
| БАЗА | 0 failed |
| И12 `launch.py` → `setdefault` | launch::second_build_with_other_explicit_dir_moves_env, launch::explicit_dir_beats_env_written_after_import |
| И1 | U::caps×4, U::before_group, U::join_after_kill, U1; U-author тест срока по умолчанию |
| И2 | U::caps[0.1], [0.5], [5.0], U::before_group |
| И3 | U1; U-author тест повтора (`already_set`) |
| И4 | U::bad[deadline-True] |
| И5 | D::wait[never-lost] |
| И6 | U::graceful_unchanged ×2 |
| И7 | D::mcp_tool_registered |
| И8 | U::join_after_kill |
| И9 (события до срока; ветка `already_set` недостижима) | U1; U-author тест повтора |
| И10 | U::bad ×7, U1; U-author тест `10**400` |
| И11 | D-author::test_rejected_command_returns_without_wait |

### Стенд T1–T4 (heavy, полный вывод в файл, таблица по прогонам печатается тестом)

| Прогон | Прогноз по проверкам |
|---|---|
| T1 вся L на HEAD | L6: 5/5 по всем пунктам ✓ (reply, < 4,0, exit0, no_surv, term_re, info), медиана ≤ 2,5; smoke ✓; L7 ✓ — уверенность низкая: причина красного L7 в S2 не установлена, при красном таблица назовёт пункт |
| T2 И1 на L6 | < 4,0 ✗ во всех 5, медиана ✗; reply, exit0, no_surv, term_re (`did not stop in 4.Xs`), info ✓ |
| T3 И8 на L6 | no_surv ✗ и/или exit0 ✗ (76) — во всех 5; < 4,0 ✓, term_re ✓, info ✓ |
| T4 И12 на L6 | прогон 0 — всё ✓; прогоны 1–4 — info ✗, остальное ✓ |

### Юнит-матрица v2 — наблюдено (сырой вывод: scratchpad/matrix_v2.txt; сверено лидом построчно)

- БАЗА 37 passed до и после отката. И1, И2, И3, И4, И5, И7, И8, И9, И10, И11, И12 — набор FAILED совпал с прогнозом
  поимённо (12 из 13 строк, считая БАЗУ).
- И6 — расхождение: сверх прогноза (graceful_unchanged ×2) красный U-author::test_graceful_without_mode_exact_old_reply —
  авторский тест строже, чем учёл прогноз; лишний красный, не пропуск.
- Ни одна инъекция не прошла незамеченной (0 строк с 0 красных).
