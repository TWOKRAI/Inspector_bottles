# Проверки перед слиянием C-36 (2026-11-27, `lane-f-c36-integ` = `23892b698`, база `main` `889491c80`)

Дерево `23892b698` по содержимому совпадает с `git merge-tree main fix/c36-fresh-queues` до правки теста ниже.

| Проверка | Итог |
|---|---|
| `scripts/validate.py` | ошибок и предупреждений нет |
| `multiprocess_prototype/backend/tests` | 413 passed |
| `multiprocess_prototype/recipes/tests` | 413 passed, 5 skipped |
| `scripts/run_framework_tests.py` | 14801 passed, 4 failed, 47 skipped, 2 xfailed, 43 мин 16 с |

| Красный тест | Причина | Решение |
|---|---|---|
| `test_supervision_status_system_stop::test_per_process_fields_unchanged_by_system_stop_field` | **от C-36**: новое поле `orphaned_read_locks` в `supervision.status`, тест сравнивает набор ключей целиком | поле намеренное; ключ добавлен в набор, файл 34 из 34 |
| `test_after_shutdown_outcome::test_warning_race_no_true_after_shutdown_returns` | старая гонка логгера: на `main` без C-36 2 из 10 красных | C-127 |
| `test_std_logger_guard::test_no_bare_stdlib_logger_outside_whitelist` | `getLogger` в камерах и `run_control.py` | C-106 |
| `test_gc_policy_guard::test_qt_tests_collect_through_policy` | `gc.collect()` в тестах GUI | C-113 |

После правки теста полный прогон не повторялся: изменена одна строка в одном тестовом файле, его файл прогнан целиком.
Ревью: Opus `a20f3b5b94a59c5a6`, дельта перед слиянием APPROVED на `23892b698`; эту правку теста ревьюер не видел.
Слито 2026-11-27 по слову владельца («да» в вкладке полосы): `027706dbd`. Push не делался.
