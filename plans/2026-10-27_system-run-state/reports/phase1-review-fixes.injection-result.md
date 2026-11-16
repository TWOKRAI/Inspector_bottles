# Правки ревью Ф1 (fix-A/B/C) — результат матрицы инъекций (лид, 2026-11-15)

Предсказания — `phase1-review-fixes.injection-predictions.md` (коммит до прогона). Прогон: набор из 8 файлов (нулевой прогон 74 passed), одна замена на инъекцию в отдельном worktree от `fix/run-state-phase1-review`, откат копией файла, `git diff --stat` пуст после каждой. J1–J11 — агент haiku, J12 — лид (многострочный якорь).

| № | Предсказано красных | Получено красных | Совпало? |
|---|---|---|---|
| J1 | 4 теста отказа исполнителя (+ допустимо graceful) | те же 4; graceful зелёный | точно |
| J2 | `test_executor_raises_same_path_for_stop_and_fault_stop` | он один | точно |
| J3 | 0 (дыра) | 0 | точно — **дыра**: ветка «`False` без ответа» не проверена |
| J4 | 0 (дыра) | 0 | точно — **дыра**: охрана «один обход на подачу» не проверена |
| J5 | `test_graceful_shutdown_from_running_refused_executor_leaves_running_no_more` | он один | точно |
| J6 | `test_stale_tick_after_start_does_not_fault` | он один; `test_tick_started_after_start_still_faults` зелёный | точно |
| J7 | свой тест + «флаг без enabled» в старых | свой + `test_flag_requires_enabled[flag-without-enabled]`, `[flag-with-enabled-false]` | надмножество |
| J8 | параметры `test_invalid_per_process_dict_...`; возможно `test_bad_max_retries_...` | оба параметра + `test_bad_max_retries_pm_and_monitor_agree` | точно (с «возможно») |
| J9 | 3: чужой pid вне рестарта, H5, поздний лист после снятия | 2: чужой pid вне рестарта, поздний лист после снятия; **H5 зелёный** | подмножество — **ошибка предсказания лида**: H5 идёт внутри окна «перезапускается», его держит ветка рестарта (J10 красит H5), а не `elif` чужого pid |
| J10 | свой тест + тесты 1.7c (число не знал) | 13: свой, 10 в `test_run_restart_incarnation_hazards.py`, 2 в `test_supervisor_restart_incarnation_hazards.py` (H5 и пометка) | надмножество |
| J11 | `test_gave_up_clears_restarting_reason` | он один | точно |
| J12 | 0 (гипотеза: гард лишний) | 0 (74 passed) | точно — **гипотеза подтверждена**: возвращённый `not in self._restarting` в `_check_heartbeats` ничего не ловит, M3 заменил его полностью |

**Итог:** 10 из 12 совпали или надмножество, 1 подмножество (ошибка предсказания, не дыра), 2 ожидаемые дыры (J3, J4) — закрываются тестами. Замечание: J1–J7 шли классом `medium`, J8–J11 и нулевой повтор — `heavy`; гейт не отказывал.
