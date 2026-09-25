# Task 1.5 (`lifecycle-stop-ownership`) — merge gate, CTO (Fable)

- **Дата:** 2026-09-25 · **Роль:** cto (Fable), по просьбе владельца · **Ветка:** `fix/lifecycle-1.5`, `31ddc570..a8095e8f`
- Текст — ответ агента без правок, сохранён ведущим (у cto нет инструмента записи).

**Вердикт: ACCEPT_WITH_DEBT** — сливать в `main` можно (Task 1.5, `31ddc570..a8095e8f`; сухое `git merge-tree` в текущий `main 00743214` — чисто, пересечений по файлам нет; трейлеры всех 4 коммитов на месте, worktree чист).

## Воспроизведения (macOS, ветка, всё руками cto)

1. Полный `multiprocess_framework/modules/process_manager_module/tests` на HEAD `a8095e8f`: **992 passed, 1 skipped, 119.8 с**. `python scripts/validate.py`: ошибок нет, ADR-индекс синхронизирован.
2. Живой `inspection_full` (BackendHarness, порт 9901), `kill -9` PM 4948: 6/6 детей ушли за **0.25 / 0.25 / 0.30 / 0.30 / 0.33 / 1.00 с**, выживших 0, хвостов 0. Повтор после рестарта (порт 9902, PM 5178): 0.23–0.65 с, 0 выживших. База main `31ddc570` (временный detached-worktree, снят): **6/6 сирот** через 6 с — как заявлено лидом.
3. Ложные срабатывания: SIGSTOP PM на 3.0 с → детей умерло 0, строк сторожа 0, после SIGCONT PM отвечает; штатный `harness.stop()` 1.41 с, строк сторожа 0. Перезапущенный `processor` (pid 5192, ppid = PM) сторожится: умер за 0.25 с после `kill -9`, строки «НЕ взведён» в stderr нет.
4. **Загадка рестарта снята:** в `multiprocess_prototype/backend/topology/inspection_full.yaml` нет процесса `preprocessor` — есть `processor`. `process.restart processor` → `success: true` за 0.83 с; `preprocessor` → `success: false` за 0.02 с (тот самый ответ лида). Рестарт на ветке работает.
5. Инъекция I6 (сторож перенесён к `_run_lifecycle`, worktree на `a8095e8f`, снят): прогноз до запуска «1 красный из 15» — факт **1 failed (`test_parent_sigkill_during_child_initialize`), 14 passed**. Совпало.
6. `backend_ctl/tests/test_system_shutdown_live.py --backend-live` (8860–8869): **2 passed** (10 стопов `system.shutdown` ≤ 2.0 с + маркер `(system-wide)`); без флага оба теста `skipped` — учесть при цитировании «прогнал». `backend_ctl/tests/test_harness_parent_death_acceptance.py`: **2 passed**.
7. Утечки resource_tracker после `kill -9` PM: ветка «359 семафоров / 3 SHM», база main «389 / 6», штатный стоп на ветке — 0 предупреждений. Утечки — от SIGKILL самого PM (его ресурсы никто не снимет с учёта); ветка их не добавляет, а уменьшает (кооперативные дети успевают отпуститься).
8. Общий `system_stop_event` из сироты: `SystemLauncher.run()` (`multiprocess_framework/modules/process_manager_module/launcher/system_launcher.py:496-504`) выходит в `stop()` и по `is_running()==False`, и по событию; политики рестарта PM у лаунчера нет — меняется только строка лога. **По чтению, не запуском** `run.py`.
9. ADR-PMM-032 (`multiprocess_framework/modules/process_manager_module/DECISIONS.md`) честен: «невозможно/гарантирует» нет; утверждение про `popen_fork.py` сверено с CPython 3.12.13 (ребёнок закрывает только свою пару `parent_r/parent_w`, чужой `parent_w` наследуется); «не воспроизводилось на Linux» сказано прямо.

## Linux

Может остаться открытым после слияния. Ветвления по платформе в `runner/process_runner.py` нет (кроме `nt` → no-op), механизм — POSIX-переродительство; худший исход при ошибке на Linux — «как сегодня» (сироты), не хуже: ложное срабатывание требует смены `getppid()` при живом PM, чего POSIX не делает. Условие: пункт приёмки «Linux-путь проверен» остаётся **незакрытым** в `plans/lifecycle-stop-ownership.md` с пометкой «отложено владельцем 2026-09-25» и попадает в `docs/claude/OPEN_QUESTIONS.md` со сроком (Orin).

**Условия слияния (не блокеры):** `docs(plans)`-коммит закрывает 3 из 4 чекбоксов Task 1.5 (живой kill; стоп/рестарт — с правкой «`preprocessor` → `processor`, 0.83 с»; инъекции по macOS), 4-й — явно deferred.

## Долги

- D1. Linux/Orin живая проверка (выше).
- D2. Запас бюджета на пути «опрос + grace» — 0.25 с из 2.0 (1.75 с); интервал опроса пинит только `test_budget_arithmetic` (находка I4 лида). Риск флака на медленном CI; при первом флаке — поднять приёмку до 2.5 с или снизить grace, а не опрос.
- D3. Внуки ребёнка (пул/`subprocess`) на принудительной ветке `os._exit(75)` остаются сиротами — по чтению, не воспроизведено; закрыть при первом реальном ребёнке с внуками.
- D4. Код 75 совпадает с `EX_TEMPFAIL` из sysexits.h — косметика, одна строка в ADR.
- D5. Предупреждения `ResourceTracker called reentrantly` в `test_pm_marks_gone_reader_hazards.py::test_system_stop_mid_restart_refuses_the_spawn` — чужой тест (Task 1.3), на main не сверял.

## Не проверено и почему

Linux (нет машины); путь `run.py`/`SystemLauncher.run` при `kill -9` PM — только чтением (стенд через harness); рестарт до/после — только ветка (0.83 с), на main не мерил; устойчивость 2.0-секундных тестов под нагрузкой — по одному прогону, при живом соседнем pytest на машине; наличие D5 на main. Хвостов после прогонов нет (`spawn_main` — 0), оба временных worktree сняты, скрипты и логи — только в scratchpad.
