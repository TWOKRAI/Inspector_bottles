# Win-C: защита m2 — счётчик поколений вместо меток `time.monotonic()`

Дата: 2026-11-23. Исполнитель: teamlead. Заявка: `plans/queue/inbox/2026-11-23_lane-T-py314_9.md`.
Worktree: `Inspector_bottles--wf-c` (detached, c7a2ccca7).

## Предсказания инъекций (записаны ДО запуска)

| Инъекция | Что меняется | Ожидаемые красные (pytest файла) | Ожидаемо в повторе ×100 |
|---|---|---|---|
| I1a | убрать `self._run_generation += 1` | `test_stale_tick_after_start_does_not_fault` (:113, `'fault' == 'running'`); m1 и обратный тест зелёные | stale 100/100 красный, обратный 0 |
| I1b | файл менеджера = HEAD (сравнение меток времени) | `test_stale_...` — по investigator красный; мой прогон до правки дал зелёный 1 из 1, поэтому ожидаю «флейк, скорее зелёный» | stale 100/100 красный, обратный 0 |
| I2 | счётчик +1 на каждом такте (в `_run_readiness_tick` после чтения) | все такты отброшены: `test_stale_...` (:106, `booting`), `test_tick_started_after_start_still_faults` (START отказан, :124), m1 — красный (`rig.to_running` идёт через такты) | оба 100/100 красные |
| I2b | защита глушит всё после первого START: `self._run_generation > 0` вместо `!=` | только `test_tick_started_after_start_still_faults` (:129, `'running' == 'fault'`) | обратный 100/100 красный, stale 0 |

Базовая линия G4 для `test_run_eval_never_raises.py` (на исправлении G4 = 6): ожидаю 6 и на HEAD (потоки
настоящего PM в `test_dispatcher_start_eval_failure_reply`, правка потоков не добавляет).

## Итог

STATUS: DONE. Защита m2 работает на часах Windows. Устаревший такт отбрасывается по счётчику поколений
`_run_generation`, сравнение меток `time.monotonic()` удалено.

Импорт из worktree (cwd = `--wf-c/multiprocess_framework/modules`):
`D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles--wf-c\multiprocess_framework\__init__.py`, Python 3.12.12.
Часы: `time.get_clock_info("monotonic")` → `implementation='GetTickCount64()', resolution=0.015625`.

## Воспроизведение до правки (HEAD c7a2ccca7)

- pytest файла через гейт, прогон 1: `3 passed` (красный не воспроизвёлся).
- Повтор в одном процессе (`scratchpad/repeat_m2.py 100`): `test_stale_tick_after_start_does_not_fault: runs=100
  failed=100`, падение на `:113` (`assert pm._run_snapshot()[0].value == "running"`).
- pytest файла при I1b (тот же HEAD), прогон 2: `1 failed, 2 passed`, `:113: assert 'fault' == 'running'`.

Вывод: на HEAD тест красный в 99–100 из 100 вызовов в одном процессе и флейк под pytest (1 зелёный из 2).

## Правка

`multiprocess_framework/modules/process_manager_module/process/process_manager_process.py`:

- `:194–198` — поле `_run_generation: int = 0` вместо `_run_running_mono: float = 0.0`. У `_run_running_mono`
  не было других читателей (`git grep -n -E "_run_running_mono|eval_started" -- multiprocess_framework/` после правки — пусто).
- `:1080` — параметр `_run_apply`: `eval_generation: int | None` вместо `eval_started: float | None`; докстринг `:1104–1107`.
- `:1110` — отброс такта: `eval_generation != self._run_generation` (под `_run_lock`).
- `:1168` — вход в `running`: `self._run_generation += 1` (там же, под `_run_lock`).
- `:1611–1614` — `_run_readiness_tick` читает поколение под `_run_lock` до оценки; `:1621` — передаёт его в `_run_apply`.

Потоки: счётчик пишет только `_run_apply` под `_run_lock`; чтение такта — под тем же замком. Новой пары замков нет:
такт уже брал `_run_lock` в `_run_apply` под `monitor._iteration_lock`. Новых потоков нет.
POSIX: семантика та же — такт отбрасывается, если после начала его оценки был вход в `running`. Исчезает только
случай равных меток, в котором старый код применял устаревший такт.

`test_run_shutdown_from_running_hazards.py` не менялся: тест обратной гарантии уже есть —
`test_tick_started_after_start_still_faults` (`:119`). Инъекции I2 и I2b краснят его (таблица ниже).

## Приёмка (гейт light, сессия lane-T-py314, по одному файлу)

| Файл | Результат | G3 / G4 |
|---|---|---|
| test_run_shutdown_from_running_hazards.py | 3 passed | 0 / 0 |
| повтор ×100 (m2-тесты, одним процессом) | stale 0/100 failed, обратный 0/100 failed | — |
| test_run_commands.py | 20 passed | 0 / 0 |
| test_run_state_hazards.py | 28 passed | 0 / 0 |
| test_run_auto_restart_hazards.py | 19 passed | 0 / 0 |
| test_run_stop.py | 11 passed | 0 / 0 |
| test_run_ack.py | 15 passed | 0 / 0 |
| test_run_active_flag_hazards.py | 14 passed | 0 / 0 |
| test_run_apply_gate.py | 11 passed | 0 / 0 |
| test_run_apply_gate_hazards.py | 11 passed | 0 / 0 |
| test_run_autostart.py | 13 passed | 0 / 0 |
| test_run_autostart_hazards.py | 35 passed | 0 / 0 |
| test_run_eval_never_raises.py | 13 passed | 0 / **6** (на HEAD тоже 6 — до правки) |
| test_run_eval_never_raises_hazards.py | 10 passed | 0 / 0 |
| test_run_flag_pm_wiring.py | 8 passed | 0 / 0 |
| test_run_publish_snapshot_hazard.py | 3 passed | 0 / 0 |
| test_run_settle_guaranteed_hazards.py | 3 passed | 0 / 0 |
| test_boot_progress.py | 6 passed | 0 / 0 |
| test_liveness_fallback_series_guards.py | 4 passed | 0 / 0 |
| test_process_priority.py | 6 passed | 0 / 0 |

Список файлов: `git grep -n -w -E "m2|_run_readiness_tick|_run_apply" -- multiprocess_framework/modules/process_manager_module/tests`.
`ruff check -q` на изменённом файле — exit 0.

## Инъекции (ожидалось / получилось)

| Инъекция | Ожидалось | Получилось | Совпало |
|---|---|---|---|
| I1a: без `+= 1` | stale красный `:113`; ×100: 100/0 | `1 failed, 2 passed`, stale `:113 'fault' == 'running'`; ×100: stale 100, обратный 0 | да |
| I1b: HEAD (метки времени) | pytest: «флейк, скорее зелёный»; ×100: 100/0 | `1 failed, 2 passed`, stale `:113`; ×100: stale 99, обратный 0 | **нет** (pytest — красный; на HEAD тест флейк, 1 зелёный из 2) |
| I2: +1 на каждом такте | красные все три: stale `:106`, обратный `:124`, m1 | `1 failed, 2 passed`: только обратный `:129 'running' == 'fault'`; ×100: stale 0, обратный 100 | **нет**: `ready` даёт boot (`settled`), а не такт; m1 тоже не зависит от тактов |
| I2b: `_run_generation > 0` | обратный `:129`; ×100: 0/100 | `1 failed, 2 passed`, обратный `:129`; ×100: stale 0, обратный 100 | да |

После инъекций `git diff` совпал побайтно с сохранённым патчем правки (`cmp`), маркеров `INJ` в файле нет.

## Доработка 1: второй цикл STOP -> START (запрос координатора)

Новый hazard-тест `test_stale_tick_after_second_start_does_not_fault`. Сценарий: START -> STOP -> `ready` (ребёнок шлёт
`paused: true`). Затем начинается оценка такта, и второй START принимается внутри неё. Ожидаемые литералы: ответ
START `{"success": True, "state": "running"}`, состояние `running`, событие взведено, `last_fault` `None`.

Предсказания (записаны ДО запуска):

| Инъекция | Что меняется | Ожидаемые красные (pytest файла) | Ожидаемо в повторе ×100 (stale / второй цикл / обратный) |
|---|---|---|---|
| без инъекции | — | нет, `4 passed` | 0 / 0 / 0 |
| I1a | убрать `self._run_generation += 1` | `test_stale_...` (:113) и новый тест (ассерт `running`); m1 и обратный зелёные | 100 / 100 / 0 |
| I3 | счётчик только при первом входе: `self._run_generation = 1` | только новый тест (ассерт `running`, `'fault' == 'running'`) | 0 / 100 / 0 |

Результаты (гейт light, lane-T-py314; импорт `...--wf-c\multiprocess_framework\__init__.py`):

| Инъекция | Получилось (pytest файла) | Повтор ×100 (stale / второй цикл / обратный) | Совпало |
|---|---|---|---|
| без инъекции | `4 passed`, G3/G4 0/0 | 0 / 0 / 0 | да |
| I1a | `2 failed, 2 passed`: `:113` и `:138`, оба `assert 'fault' == 'running'` | 100 / 100 / 0 | да |
| I3 | `1 failed, 3 passed`: `:138 assert 'fault' == 'running'` (новый тест) | 0 / 100 / 0 | да |

Код после инъекций побайтно равен патчу правки (`cmp`). Новый тест: `test_run_shutdown_from_running_hazards.py:111-133`,
импорт `_beat` из `test_run_stop` (`:22`).

## Что интерпретировал, а не выполнил

- Сначала тест обратной гарантии не добавлял: её уже покрывает `test_tick_started_after_start_still_faults`, и его краснят I2 и I2b.
  По запросу координатора добавлен тест второго цикла (раздел «Доработка 1»).
- В новом тесте `paused: true` ребёнка подаётся одним прямым heartbeat (`_beat`). Двойник `_ChildSim` из `_Rig` не взят:
  его поток шлёт heartbeat раз в 10 мс и мог бы перезаписать лист «не готов» до оценки такта.
- Параметр `_run_apply` переименован в `eval_generation`: прямых вызовов с `eval_started=` в дереве нет (`git grep`).
- Чтение поколения взято под `_run_lock`, хотя чтение `int` атомарно и без замка: так порядок «чтение до оценки» явный
  и не зависит от сборки (free-threaded 3.14).

## Что осталось открытым или ненадёжным

- Не проверено на macOS/Linux, кроме логики по коду.
- Не проверено на Python 3.14 (полоса T): прогоны — 3.12.12 из основного `.venv`.
- Второй цикл закрыт тестом `test_stale_tick_after_second_start_does_not_fault`. Не проверены третий цикл и дальше
  и путь `fault -> ack -> START`: по коду они идут через тот же `+= 1`.
- Новый тест на HEAD (метки времени) не прогонялся: координатор не просил этот прогон.
- Под pytest на HEAD красный воспроизводится не всегда (1 зелёный из 2). Повтор ×100 одним процессом — надёжная проверка.
- G4 = 6 в `test_run_eval_never_raises.py::test_dispatcher_start_eval_failure_reply` — до правки, не по этой задаче.
- `STATUS.md` / `DECISIONS.md` модуля не обновлены (вне FILES; правка — ошибка кода, не архитектура).
