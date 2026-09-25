# Task 1.5 (`lifecycle-stop-ownership`) — отчёт teamlead

**Статус:** DONE_WITH_CONCERNS (запас boot-гонки ≈ 0.1 с из 2.0)
**Ветка:** `fix/lifecycle-1.5` (main 31ddc570 + тестер ae35bed3)
**ADR:** ADR-PMM-032 (`multiprocess_framework/modules/process_manager_module/DECISIONS.md`)

## Что сделано

- `runner/process_runner.py`: keyword `parent_pid=None` у `run_process_function`; первым действием
  (до `setsid`/`register_self`/загрузки класса) — `_start_parent_watcher` → daemon-поток `_watch_parent`.
  Правило взведения, цикл 0.25 с, ветка смерти (`emergency_log` → оба события → grace 1.5 с →
  `os._exit(75)`) — как в DESIGN брифа, без отступлений. Константы `_PARENT_POLL_S`,
  `_PARENT_DEATH_GRACE_S`, `_PARENT_DEATH_EXIT_CODE = 75` с арифметикой бюджета рядом.
- `core/process_registry.py::_create_process`: `kwargs={"parent_pid": os.getpid()}` (+ `import os`).
  Единственная точка взведения; `spawner.py` не тронут.
- `tests/test_parent_death_hazards.py` — 7 hazard-тестов автора.
- ADR-PMM-032, абзацы в `STATUS.md` и `README.md`, `python -m scripts.sync` → сводный
  `multiprocess_framework/DECISIONS.md`.

## Тесты (команды — из брифа)

- REDS тестера + остальные 5 его тестов: `test_parent_death_acceptance.py` + `test_harness_parent_death_acceptance.py`
  → `9 passed in 23.52s`.
- Радиус брифа (7 файлов, Task 1.5 + Task 1.4) → `48 passed in 92.38s`.
- Весь `process_manager_module/tests` → `991 passed, 1 skipped in 120.67s`, падений нет — сверка с main не нужна.
- `ruff check -q` и `ruff format --check` на трёх .py — чисто.
- Хвосты: `spawn_main` после прогонов — только чужие деревья (стенд `4ce68ece…/stand.py`, чужой pytest по
  `service_module`); моих нет.

## Break-injection (скрипт в scratchpad, текстовая подмена `process_runner.py`, откат в finally)

Предсказание записано до прогона; все 5 совпали ТОЧНО (набор упавших = предсказанный).

| Поломка | Упало (hazard-файл) |
|---|---|
| B1: взводить от `os.getppid()` при `parent_pid=None` | `test_no_parent_pid_means_not_armed` |
| B2: ветка «не прямой родитель» проваливается в цикл | `test_not_direct_child_is_not_armed` |
| B3: ветка «умер до старта» — `return` вместо смерти | `test_parent_dead_before_watcher_start_exits`, `test_events_set_before_forced_exit` |
| B4: события не взводятся | `test_events_set_before_forced_exit`, `test_cooperative_child_exits_itself_before_grace` |
| B5: нет `os._exit` | `test_hung_child_gets_forced_exit_code`, `test_parent_dead_before_watcher_start_exits`, `test_events_set_before_forced_exit` |

`test_budget_arithmetic` проверяет литералы констант. Его валит любая правка чисел, а не отказ механизма.

Ловушка 1 брифа (страховка маскирует основную правку): удалил `kwargs={"parent_pid": ...}` из registry →
упали все 4 REDS, включая `test_kill9_pm_leaves_no_children` (`4 failed, 5 passed`). Значит, guard/harness
Task 1.4 харнесс-тест не зеленит, его зеленит сторож.

## Замеры (macOS, spawn, 3 прогона, SIGKILL хоста → ребёнок исчез)

быстрый 0.28/0.31/0.28 с; зависший 1.67/1.67/1.66 с; смерть сразу после `start()` 1.89/1.89/1.90 с.

## Что я истолковал, а не выполнил буквально

- Процессные hazard-тесты эмулируют смерть родителя подменой `os.getppid` внутри ребёнка, а не SIGKILL:
  только так `exitcode` ребёнка наблюдаем (усыновлённого init не реапнуть). Настоящий SIGKILL покрывает
  приёмка тестера. Цена: мои процессные тесты не видят поломку, при которой перестаёт меняться реальный
  `getppid` (это ядро, не код).
- «Не взводится при `parent_pid=None`» проверено на уровне runner'а (подмена getppid), а не SIGKILL'ом
  настоящего родителя.
- Отвергнутый вариант «sentinel родителя» в ADR — моя формулировка: под fork это та же труба
  (`popen_fork.py`, строки 65–78), сверено с исходником CPython 3.12.

## Что оставил открытым / ненадёжно

- **Boot-гонка: запас ≈ 0.1 с.** 1.75 с арифметики + ≈ 0.4 с spawn-boot до старта сторожа (интерпретатор и
  распаковка target'а идут ДО `run_process_function`, сторож раньше не поставить в рамках DESIGN).
  Приёмочный C3 может флапать под нагрузкой. Варианты — решение лида: grace короче в ветке «умер до старта»
  (там класс ещё не загружен, кооперативный стоп маловероятен) или меньше `_PARENT_DEATH_GRACE_S`.
- Linux не проверен (решение владельца); пункт приёмки открыт.
- Ребёнок, держащий GIL, сторожем не спасается; forkserver не взводится; Windows — no-op (всё в ADR).
- Переиспользование pid PM в ветке «умер до старта» → сторож не взведётся (окно — мс, оборот pid ~30 мин).
- `DECISIONS.md` модуля 199 КБ при бюджете doc-size-guard 32 КБ — существовало до задачи, не делил.
- Тестер: в C4c (`test_restarted_child_survives`) порог 2.0 с выбран им самим (в контракте нет числа) — он
  это оговорил; претензий к его тестам нет.
