# Проверки перед слиянием 2.2d, 2.8f, 2.6 (2026-11-26, `lane-f-integ` = `19547fed0`, база `main` `53efe24b9`)

Окно `heavy`, python главного `.venv`, `PYTHONPATH` = дерево.

| Проверка | Итог |
|---|---|
| `scripts/validate.py` | ошибок нет |
| `multiprocess_prototype/backend/tests` | 413 passed |
| `multiprocess_prototype/recipes/tests` | 409 passed, 5 skipped |
| `scripts/run_framework_tests.py` | 14692 passed, 3 failed, 47 skipped, 2 xfailed, 44 мин |

Красные (файлы, из-за которых они красные, ветки не меняли):

| Тест | Причина | Где записано |
|---|---|---|
| `test_std_logger_guard::test_no_bare_stdlib_logger_outside_whitelist` | `getLogger` в `Services/camera_device` | C-106 |
| `test_gc_policy_guard::test_qt_tests_collect_through_policy` | 6 `gc.collect()` в тестах GUI | C-122 |
| `test_declarations_leak_order_independence::test_statistics_then_process_module_order_matches_the_reverse_order` | во вложенном прогоне 2 теста на срок из `test_t45b_process_fields.py`; отдельно 19 из 19 | C-20 |

В `19547fed0` нет коммита `2076e79c9` ветки 2.6 (правка одного ассерта в тесте заставки, тесты файла 3 из 3).
Не прогонялось: `pyright`, каталоги `multiprocess_prototype` кроме `backend/tests` и `recipes/tests` (радиус — в отчётах задач).
