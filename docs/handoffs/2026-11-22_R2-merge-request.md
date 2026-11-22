# Заявка на слияние — полоса Р2, брифы А и Б, C-104 (2026-11-22)

Ветка `fix/r2-reconnect0-c101-c104` (worktree `Inspector_bottles--lane-R2-d2`), база `main` `15858154e`. Слияние делает лид/координатор: `machine_gate.sh merge-begin|merge-end`, тема `feat: …` (хук режет `merge(...)`), `Why:`/`Layer:`/`Refs:` из файла. Отчёт — `docs/reports/2026-11-22_R2_lane.md`.

## Что входит

| Коммит | Суть | Слой |
|---|---|---|
| `07ca276f3` + правка | C-101: `test_no_private_driver_state.py` — `_SCANNED_FILES = 73`, швы `_clock 1`, `_dispatch 3`, `_park 3` | services (тесты) |
| `488085e4d` | тест «params рецепта → драйвер» (8 тестов, слепой tester) | plugins (тесты) |
| `a8413da94` | `letter_robot_sim.yaml`: `max_reconnect_attempts: 0` у `robot_main`, `vfd_belt`; тест рецепта; две записи в `_EXPECTED_DIFFS` сим-против-β | prototype |
| `ff0b61b87`, `b4fbc39a1`, `129b74016`, `be4e63783` | C-104: `robot_io` — подпись задания в голосе health, `forward_ok`/`last_dropped_job`, state `robot_io`, один разъём `log_warning`; приёмка (10) и тест на настоящих объектах (2) | plugins |
| docs-коммиты | OPEN_QUESTIONS (C-104, C-72, tick, β-рецепт, границы C-104), сверка дня №2, отчёт | docs |

## Проверки (литералы запусков)

- `Plugins/io/robot_io/tests` — 27 passed; страж «один разъём» — 19 passed; `Services/device_hub/tests/test_no_private_driver_state.py` — 6 passed.
- `multiprocess_prototype/recipes/tests` + `test_recipe_1_0.py` — 240 passed, 5 skipped.
- Инъекции совпали с предсказаниями (C-101: 5, бриф А: 3, C-104: J1–J8, K1–K3); расхождения — перекрытие assert'ов, объяснены в отчёте.
- Ревью стадии 0 (C-104): CHANGES REQUESTED → внесено; стадия 5: раунд 1 CHANGES REQUESTED → исправлено, раунд 2 **APPROVED** (sonnet, воспроизведено запуском).
- Полный прогон `Plugins/hub/device_hub/tests` + `Services/device_hub/tests` (HEAD ветки, Mac, `machine_gate.sh medium`): **1710 passed, 6 skipped, 0 failed**, 756,89 с (12 мин 36 с).

## Перед слиянием

1. Сторож C-101 считает файлы: если до слияния в `Services/device_hub/tests` или `Plugins/hub/device_hub/tests` добавлен новый `*.py`, поправить `_SCANNED_FILES` (проверить прогоном сторожа после слияния).
2. `OPEN_QUESTIONS.md` — только добавления в конец, конфликт вероятен при слиянии соседей.
3. Живой стенд на sim НЕ гонялся (`stand.lock` держит Пульт): перед или сразу после слияния — «Домой → слово → диск» на sim: ожидание — строка `[health] ResourceUnavailable @ robot_io.forward.refused: hub отказ (буква 'М', ячейка 0): робот остановлен: включите серво` в `system.log` процесса `layout` и `processes.layout.state.robot_io.jobs_dropped == 1` (`backend_ctl`, `state_get`).

## Строки для других полос

- **К (`hikvision_letter_robot.yaml`, R4):** то же `max_reconnect_attempts: 0` у `robot_main` и `vfd_belt` (дифф — `docs/handoffs/2026-11-20_R2-recipe-diff-reconnect.md`, действует и на v1-драйвер `delta_universal3`), затем снять две записи `.devices[0|1].params.max_reconnect_attempts` и комментарий в `_EXPECTED_DIFFS` (`test_letter_robot_sim_diff.py`).
- **Пульт (блок `pult`):** путь для монитора — `processes.layout.state.robot_io.{forward_ok,jobs_dropped,last_dropped_job}`; `forward_ok` — флаг последнего исхода, для «потеря была» смотреть `jobs_dropped`/`last_dropped_job`; что показывать оператору — решает владелец.
- **line_sim (C-72):** правка теста — вариант A в OPEN_QUESTIONS.
- **Координатор:** `defects.md:307` числит C-60 открытым, `ORDER.md:39` — влитым `116ed6964`; карточка C-104 ищет строку в `messages.log` — она в `system.log`/`errors.log`.

## Открыто / ненадёжно

Живой стенд не гонялся; ветка исключения запроса не пишет подпись в текст строки; настоящий `LoggerManager`/`ErrorManager` с файлами — только в пробах ревьюера, не в репозитории; `jobs_dropped` — старая гонка двух потоков; список рецептов 1.0 не получен.
