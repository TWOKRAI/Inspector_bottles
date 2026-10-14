# Инъекции Task 1.1 и 1.2 — план [2026-10-13_tooling-machine-gate-hook](../2026-10-13_tooling-machine-gate-hook.md)

> Вынесено из classification.md §8 (бюджет 32 КБ на файл). Предсказания пишутся ДО прогона.

## Таблица и факт

Лид записывает факт рядом с предсказанием; каждая инъекция — `light` прогон одного файла. Имена — тесты
`test_machine_gate_hook.py` (I, M) и `test_machine_gate_lock.py` (J); в скобках — id параметров.

| ID | Поломка | Предсказанные красные |
|---|---|---|
| I1 | хук: проверка замка инвертирована (`exit 0` при наличии замка) | `test_hook_blocks` (C10, C12, C15), `test_hook_blocks_unwrapped_segment_after_wrapped`, `test_hook_independent_of_cwd`, `test_hook_allows[no_lock]` |
| I2 | `classify`: удалено правило `-n` | `test_classify` (C11, C25) |
| I3 | `classify`: снята привязка к позиции команды | гарантированно `test_classify_none` (N1, N6, N7), `test_hook_allows` (N1, N6, N7); N2–N5 — зависят от реализации (подстрока против токена), не обещаются |
| I4 | хук: «обёрнуто», если `machine_gate.sh` есть где угодно в строке (не по сегментам) | `test_hook_blocks_unwrapped_segment_after_wrapped` |
| I5 | гейт: убрана вся реклассификация (класс = заявка) | `test_gate_claim` (R1–R3), `test_gate_medium` (G8, G9, T8) |
| I6 | хук: убран `tr -d '\r'` | **может остаться зелёной**: в тестах хука нет многострочных команд, python CR не выдаёт; если зелёная — записать как необнаруженную, тест под неё не придумывать |
| I7 | хук: вызов python без обработки ошибки (битый JSON → traceback, ненулевой код) | `test_hook_allows[bad_json]` |
| M1 | `classify`: правило 5 даёт `heavy` вместо `medium` (reason прежний) | `test_classify` (C15–C18, C30), `test_hook_blocks[C15]`, `test_gate_medium` (G1–G11, T1–T8, T10, T11, T14): строка `reclassified … -> heavy` там, где stderr должен быть пуст |
| M2 | `classify`: reason `pytest_module_dir` переименован в `pytest_module_tests` | `test_classify` (C15–C18, C30), `test_hook_blocks[C15]`, `test_gate_medium` (G8, G9, T8) |
| M3 | `classify`: каталог модуля — любой каталог, чей последний сегмент (разбивка по `/`) равен `tests`, сегменты не считаются | `test_classify[C22]`; C28 остаётся зелёной (`/` нет — один сегмент `Services\robot_comm\tests`, не `tests`) |
| M4 | `classify`: значения опций списка §3 не пропускаются | `test_classify` (C29, C30) |
| M5 | гейт: не-timed `medium` не проверяет чужое `quiet` | `test_gate_medium` (G2, G8) |
| M6 | гейт: чужое `stand` не блокирует не-timed `medium` | `test_gate_medium` (G3, G9) |
| M7 | гейт: класс = вывод `classify`, если он не пуст (понижение разрешено) | `test_gate_medium` (T9, T13), `test_gate_call_form_compat[K6]` |
| M8 | гейт: `timed` не вычисляется (список не читается, флаг снимается и забывается) | `test_gate_medium` (T1–T4, T8–T11, T13, T14, G10) |
| M9 | гейт: `--timed` снимается, но не учитывается (список работает) | `test_gate_medium[G10]` |
| M10 | гейт: `--timed` не разбирается (первый аргумент считается классом) | `test_gate_medium` (G10, G11, G12) — код 2 |
| M11 | гейт: подстрока заменена точным равенством токена записи | `test_gate_medium` (T1–T4, T8, T9, T13, T14) |
| M12 | гейт: timed `medium` под чужим `quiet` отвечает `QUIET WINDOW` | `test_gate_medium[T3]` |
| M13 | гейт: список читается только рядом с гейтом, env `MACHINE_GATE_TIMED_LIST` не учитывается | `test_gate_medium` (T10, T11, T14) — T1–T9 зелёные: `Services/robot_comm/` есть и в поставляемом списке |
| M14 | гейт: fail-closed убран (список недоступен → ничего не timed; строка stderr остаётся) | `test_gate_medium[T10]` |
| M15 | гейт: `--timed` действует и на `light` (как timed `medium`) | `test_gate_medium[G12]` |
| M16 | гейт: совпадение по списку действует и на `light` | `test_gate_medium[T12]` |
| M17 | гейт: в токене не делается `\` → `/` | `test_gate_medium[T13]` |
| M18 | гейт: `\r` в конце записи списка не отбрасывается (временный список тестов записан с `\r\n`) | `test_gate_medium` (T1–T4, T8, T9, T13, T14) |
| J1 | `validate_lock` всегда успешен | `test_malformed_lock_exit_2` (все) |
| J2 | `grant` не проверяет существующее окно | `test_grant_refuses[second_window]` |
| J3 | `close` удаляет любое окно | `test_close_refuses[foreign_window]` |
| J4 | `grant` не удаляет `waiting:` своей сессии | `test_grant_writes_window_and_drops_waiting` |
| J5 | `validate_lock` и перезапись не снимают `\r` | валидатор на bash `read`: `test_live_sample_lock_is_valid[crlf]`, `test_grant_writes_window_and_drops_waiting[crlf]`; на awk — эквивалентный мутант на Git Bash (gawk 5.0.0 снимает `\r` сам: длина 25 против 26 с `BINMODE=3`) — записать как необнаруженную на Windows |
| J6 | `validate_lock` вызывается только для `heavy|light` (режим `medium` замок не проверяет) | `test_malformed_lock_exit_2` (режимы `medium`, `--timed medium`) |
| J7 | `kind` окна принимает и `medium` (в `grant` и в `validate_lock`) | `test_grant_refuses[medium_kind]`, `test_malformed_lock_exit_2` (замок с `medium`) |
| J8 | `close` не сверяет имя координатора | `test_close_refuses[non_coordinator]` |
| J9 | запись не атомарная: файл открывается на запись до проверок (`: >machine.lock` в начале `grant`) | `test_grant_refuses` (все параметры: файл обрезан или создан) |
| J10 | `grant` не сверяет имя координатора | `test_grant_refuses` (non_coordinator, coordinator_prefix, coordinator_regex) |
| J11 | имя координатора сравнивается регуляркой (`grep "^coordinator: $1 |"`) | `test_grant_refuses[coordinator_regex]` |
| J12 | строки сессии ищутся по префиксу поля 1 (`window: s2*`, `waiting: s2*`) | `test_grant_writes_window_and_drops_waiting` (пропала `waiting: s22`), `test_close_refuses[foreign_window]` |
| J13 | код `mv` не проверяется, tmp не удаляется | `test_grant_refuses[busy]` (только Windows) |
| J14 | запись прямо в `machine.lock` после всех проверок (без tmp и `mv`) | `test_grant_writes_window_and_drops_waiting` и `test_close_removes_own_window` (`st_ino` не изменился) |
| J15 | `set -C` убран | `test_grant_refuses[tmp_exists]` |
| J16 | валидатор теряет последнюю строку без `\n` | `test_live_sample_lock_is_valid[no_final_newline]` — если валидатор на bash `read`; на awk — неприменимо |
| J17 | `status` печатает замок через `cat` | `test_status_prints_lock_and_metrics[no_final_newline]` |
| J18 | `status` не снимает `\r` с вывода powershell | `test_status_prints_lock_and_metrics` (все, регулярки с `$`), если два значения идут одной строкой через `read`; иначе эквивалентный |

Стражи `test_gate_call_form_compat` (K1–K7) и `test_gate_light_file_runs_without_window` зелёные при каждой
инъекции, кроме M7 (K6). I1 включает `test_hook_allows[no_lock]`: без замка инвертированный хук идёт дальше и
блокирует C9.

**Факт прогона инъекций 2026-10-14** (реализация `5f14906c2`; база — 102 passed; механический прогон — агент haiku,
скрипт с зашитыми предсказаниями; каждая — один файл, `light`, откат `git checkout`; worktree после матрицы чист).
Предсказано / наблюдено числом упавших: I1 6/7, I2 2/2, I3 6/6, I4 1/1, I5 6/6, I6 0/0, I7 1/1, M1 32/32, M2 9/9,
M3 1/1, M4 2/2, M5 2/2, M6 2/2, M7 3/3, M8 11/11, M9 1/1, M10 3/3, M11 8/8, M12 1/1, M13 3/3, M14 1/1, M15 1/1,
M16 1/1, M17 1/1, M18 8/8; добавочная I7b (только `except` сломан, `2>/dev/null` на месте) 0/0.
Расхождения поимённо: **I1** — лишний красный `test_hook_allows[reach_C9]` (инвертированный хук не блокирует C9, а
параметр `reach_C9` ждёт блока): предсказание было неполным, поломка поймана. **I6 остался зелёным** — как предсказано:
в тестах хука нет многострочной команды с CR; необнаруженная поломка, тест под неё не придуман. **I7b зелёная**: хук
проглатывает ошибку python дважды (`except` и `2>/dev/null` + `tr` в конце конвейера), поэтому красную даёт только
поломка обоих слоёв (I7). I3: N2–N5 остались зелёными (подстрока против токена не срабатывает), красные ровно N1, N6, N7.


## Раунд 2 (после ревью кода 1): инъекции Q — предсказания записаны ДО прогона

Тесты — `test_machine_gate_classify_hazards.py` (авторские, developer); id параметров — как в classification.md §2.
Q-инъекции ломают реализацию после исправления ревью; I6 по ревью — эквивалентный мутант (`classify_cmd` срезает ``
на концах сегментов), тест под неё невозможен.

| ID | Поломка | Предсказанные красные |
|---|---|---|
| Q1 | `classify`: границы сегментов снова режутся без учёта кавычек | `test_classify_hazards` (N9, N10, N11, N12, N13), `test_hook_hazards_allow` (N9, N11, N12, N13); C46 и C47 остаются зелёными (результат тот же) |
| Q2 | `classify`: тело heredoc не пропускается | `test_classify_hazards` (N14, N15, N16), `test_hook_hazards_allow` (N14, N15, N16) |
| Q3 | `classify`: тело heredoc пропускается до конца строки ввода (ограничитель не ищется) | `test_classify_hazards[C45]` |
| Q4 | хук: ведущие `VAR=val` остаются внутри совета (не переносятся перед `bash`) | `test_hook_advice[H1]` |
| Q5 | хук: берёт первую строку `classify`, а не строку с наибольшим рангом | `test_hook_advice[H2]` |
| Q6 | `classify`: правило `make` удалено | `test_classify_hazards` (C43, C44), `test_hook_advice[H3]` |
| Q7 | `classify`: у powershell скрипт — первый неопционный токен (как было) | `test_classify_hazards[C32]`, `test_hook_advice[H4]`; C33 зелёная (`-File` — опция, первый неопционный — сам скрипт) |
| Q8 | `classify`: значения `-X` и `-W` перед `-m` не пропускаются | `test_classify_hazards` (C34, C35, C36) |
| Q9 | `classify`: слова `do`, `then`, `else`, `!`, `{`, `(` не пропускаются в префиксе | `test_classify_hazards` (C39, C40, C48) |
| Q10 | гейт: слова-кандидаты не фильтруют сегменты до `classify_segment` | `test_classify_many_segments_is_fast` (1500 сегментов ≈ 11 с против предела 8 с) |
| Q11 | `classify`: ведущие `do`/`then`/`{`/`time` не удаляются из третьего поля | `test_classify_hazards` (C38, C39, C40, C48) |
| Q12 | `classify`: значения `-k`/`-s` у `timeout` не пропускаются | `test_classify_hazards[C42]` |
| Q13 | `classify`: значения `--python`/`--with`/`--project`/`--directory`/`-p` у `uv run` не пропускаются | `test_classify_hazards[C41]` |
| Q14 | `classify`: слова `env` и `time` не пропускаются в префиксе | `test_classify_hazards` (C37, C38) |

**Уточнение предсказаний Q после чтения реализации 6818bfc77, ДО прогона** (первая таблица писалась по спеке, не по коду):
- **Q9** (пропуск слов `do`/`then`/… сломан только в `classify_segment`): предсказание — **0 красных**. `strip_lead` снимает те же
  слова раньше, слой избыточен; ожидаемая необнаруженная поломка (эквивалентный мутант по двум слоям).
- **Q9b** (новая): сломаны оба слоя — правило в `strip_lead` и пропуск в `classify_segment`: `test_classify_hazards` (C38, C39, C40, C48).
- **Q14** (слова `env`/`time` в префиксе): красный только C37; C38 зелёная — `time` снимает `strip_lead`.
- **Q10** (префильтр сегментов убран): предсказание — **зелёный**: разработчик убрал подоболочку `$(classify_segment)` (результат
  через переменную CLS), основную стоимость, и 1500 сегментов идут < 8 с и без префильтра; тест скорости стережёт итог,
  а не префильтр. Если замер покажет красное — предсказание неверно.
- **Q15** (новая): хук: из grep-префильтра убрано слово `make` → `test_hook_advice[H3]`.

**Факт прогона Q 2026-10-14** (реализация `6818bfc77`; база — 144 passed: 102 слепого tester + 42 авторских; прогон — агент haiku,
скрипт с зашитыми предсказаниями; один файл-пара через `light`, откат `git checkout`, worktree после матрицы чист).
Предсказано / наблюдено числом упавших: Q1 9/10, Q2 6/6, Q3 1/1, Q4 1/1, Q5 1/1, Q6 3/3, Q7 2/2, Q8 3/3, Q9 0/0, Q9b 4/4,
Q10 0/0, Q11 4/4, Q12 1/1, Q13 1/1, Q14 1/1, Q15 1/1 (первый запуск агента не считается: скрипт брал один файл, все
`obs=0` — ошибка лида, исправлена и перезапущено). Расхождение: **Q1** — лишний красный `test_hook_hazards_allow[N10]`:
в предсказании забыт параметр N10 (`rg -n "conftest|pytest|unittest" scripts` через хук); поломка поймана. **Q9** — 0/0, как
предсказано: эквивалентный мутант (слой `strip_lead` дублирует пропуск слов в `classify_segment`). **Q10** — 0/0, как
предсказано: удаление префильтра сегментов не ловится; тест скорости стережёт итоговую скорость, а не сам префильтр
(основную стоимость убрала замена подоболочки на переменную `CLS`) — необнаруженная поломка записана, теста под неё нет.
