# Красный `test_declarations_leak_order_independence`: диагноз

- Дата: 2026-11-25. Роль: debugger. Сессия: `inspector-bottles-19`.
- Дерево: `.claude/worktrees/mco-d-redtest` (`dev/redtest-decl` от `80db98e7e`). Код не менялся, коммитов нет.

## Вывод

1. Тест красный по **таймауту**. Подпрогон pytest не укладывается в `_SUBPROCESS_TIMEOUT_SEC = 300.0`.
2. Утечка объявлений **не обнаружена и не проверена**. До сравнения порядков тест не доходит.
3. Тест красный и при запуске одного, без соседей.
4. Волна 1 и W2-a не причина. Набор уже не помещался в 300 с до них.
5. Тот же отказ на `main` весьма вероятен, но прогоном на `main` не подтверждён.

## Доказательство: вход и выход

Вход: только этот тест, дерево `mco-integ`, HEAD `91193ab39`, 2026-11-25 13:32–13:37.

Выход (транскрипт `679b0d9a-…/subagents/agent-a11095a7e657736c0.jsonl`, строка 162):

```
tests\test_declarations_leak_order_independence.py:153: in test_statistics_then_process_module_order_matches_the_reverse_order
    forward, forward_output = _run_order(_STATS_DIR, _PROCESS_DIR)
E   subprocess.TimeoutExpired: Command '[... '-m', 'pytest', 'multiprocess_framework/modules/statistics_module/tests',
    'multiprocess_framework/modules/process_module/tests', '-q', '--deselect', '...']' timed out after 300.0 seconds
1 failed, 1 warning in 301.56s (0:05:01)
```

Отказ случился на строке 153, то есть в первом из двух подпрогонов. Ни один assert теста не выполнялся.

Этот прогон делал не я. Я нашёл его вывод в транскрипте. Свой прогон я сделать не смог (раздел «Мой запуск»).

В полном прогоне (`3 failed, 14676 passed`, 35:05) у этой строки `FAILED` нет текста ошибки. Что там был тот же таймаут, это вывод по повтору, а не прямое чтение.

## Почему не хватает 300 с

Замеры одного `process_module/tests`, без `statistics_module`:

| Дата | Тестов passed | Время | Источник |
|---|---|---|---|
| до 2026-11-16 | 3625 | 245 с | `docs/reviews/2026-11-15_task-1.10.md:43` |
| 2026-11-16 | 3648 | 249 с | `docs/reports/2026-11-16_lane-D_summary.md:27` |
| 2026-11-21 | 3745 | 308 с | `docs/reviews/2026-11-21_task-0.5c-teamlead.md:146` |
| 2026-11-21 | 3771 | 307 с | `docs/reviews/2026-11-21_task-0.9-developer.md:24` |
| 2026-11-25 | 3843 | 388 с | `baseline-red.md` и вывод `b7hgvedxe.output` |
| 2026-11-25 | 3849 | 388 с | вывод `bzhtypgpw.output` |

Подпрогон теста содержит этот каталог целиком и ещё `statistics_module/tests` (355 passed за 6 с по старому замеру). Значит, подпрогону нужно больше, чем 300 с, уже с 2026-11-21. Числа сняты на разных коммитах и при разной нагрузке машины.

Дедлайн 300 с введён 2026-08-29 (`80332537c`). По докстрингу `_parse_summary`, 2026-09-03 вся пара шла 132 с (3235 passed). Теперь тест гоняет пару дважды.

`docs/reviews/2026-11-16_task-c92-1.1-review.md:47` уже тогда оценивал вложенный прогон в «~250–300 с».

## Вклад этой ветки

`git diff --stat main dev/redtest-decl -- multiprocess_framework` даёт три файла:

- `process_module/core/process_module.py` (+28/−10): перенос `set_base_context` на более ранний шаг;
- `process_module/tests/test_log_base_context_order.py` (5 тестов по `def test_`);
- `process_module/tests/test_plugin_log_proc_name_mp.py` (3 теста, один настоящий spawn-процесс).

В добавленных строках diff нет `forget_declarations`, `declare_`, `observability_declarations` (grep пустой). Сам тест и `statistics_module` совпадают с `main`.

8 новых тестов на фоне примерно 3840 не объясняют превышение. Их собственное время я не замерял.

## Есть ли это на `main`

- Прогоном не подтверждено. Агент в 13:39 запустил этот тест на `main` (`743641727`). Прогон снят (`b4sdpftgn.output` = `[killed]`, `main_decl.txt` пустой).
- 2026-11-23 тест был красным в базовом прогоне Windows (`docs/reports/2026-11-23_deps-py314_win-compare.md:63`, база `c7a2ccca7`, предок `main`). Причина там записана как «тайминговый вложенный pytest» со ссылкой на реестр C-5, C-20. C-5 и C-20 описывают другой отказ: тайминговый тест краснеет **внутри** подпрогона. Текст того отказа я не видел.
- По арифметике: `main` отличается от ветки только этими тремя файлами, поэтому подпрогон на `main` тоже длиннее 300 с.

## Мой запуск

Вход: тест через `machine_gate.sh medium inspector-bottles-19 …`. Выход: `rc=75`, `NO WINDOW — skipped`.

Причина: путь под `multiprocess_framework/` считается timed и требует строки `window: inspector-bottles-19` (`scripts/machine_gate.sh:1147`). Команда не запускалась. Окно субагент не берёт и не ждёт. Гейт я не обходил. Второе дерево для `main` не создавал.

## Предлагаемая правка (НЕ применена)

Файл `multiprocess_framework/modules/tests/test_declarations_leak_order_independence.py`:

```diff
-_SUBPROCESS_TIMEOUT_SEC = 300.0
+#: Дедлайн от зависания, не бюджет скорости. 2026-11-25: process_module/tests один — 388 с под нагрузкой.
+_SUBPROCESS_TIMEOUT_SEC = 900.0
```

Проверяемые свойства (оба порядка без `failed`/`error`, сводки равны) правка не трогает. Меняется только защита от зависания.

Почему не применил:

1. Проверить нечем: нет окна. Зелёный результат после правки никем не наблюдался.
2. Это изменение порога приёмочного теста. Решение за лидом.
3. За таймаутом может прятаться настоящий красный внутри подпрогона.

Как проверить (окно `heavy`, около 15 минут: два подпрогона по 5–7 минут):

```
bash "$MAIN/scripts/machine_gate.sh" request inspector-bottles-19 heavy 20 "declarations order test"
PYTHONPATH="$PWD" PYTHONUTF8=1 bash "$MAIN/scripts/machine_gate.sh" heavy inspector-bottles-19 "$MAIN/.venv/Scripts/python.exe" -m pytest -q --tb=short --durations=0 multiprocess_framework/modules/tests/test_declarations_leak_order_independence.py
```

Ожидание: либо `5 passed`, либо assert с настоящей сводкой подпрогона. Во втором случае это новый, отдельный диагноз.

## Что оставил открытым / ненадёжно

- Свойство «порядок сбора не влияет» **сейчас никем не проверяется**. Полный прогон идёт в порядке `process_module` раньше `statistics_module` (`pytest.ini`, `testpaths`). Прямой порядок проверяет только этот тест, а он не доходит до конца.
- Прогона на `main` нет.
- Своего воспроизведения нет: доказательство взято из чужого прогона того же дня.
- Разброс 307 с и 388 с не разделён на рост набора и нагрузку машины.
- 900 с это запас около 2,3× к худшему замеру, а не расчёт. Набор растёт, и дедлайн снова может стать мал. Более прочный вариант (меньше тестов в подпрогоне) меняет охват сторожа и требует отдельного решения.
- Название теста вводит в заблуждение при таком отказе: `TimeoutExpired` читается как «утечка объявлений».
- Реестр `plans/queue/defects.md` не знает причину «таймаут 300 с»: C-5 и C-20 про другое. Я реестр не менял.

memory hits: `python scripts/memory/search.py declarations leak test order independence` и `… nested pytest subprocess timeout suite grew guard red` -> урока о дедлайне вложенного прогона нет.
