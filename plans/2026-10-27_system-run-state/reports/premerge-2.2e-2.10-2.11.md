# Проверки перед слиянием 2.2e, 2.10, 2.11 (2026-11-27, `lane-f-integ` = `5e6aded45`, база `main` `7164a8bb4`)

Окно `heavy`, python главного `.venv`, `PYTHONPATH` = дерево. 24 коммита, 35 файлов, +2702 / −21.

| Проверка | Итог |
|---|---|
| `scripts/validate.py` | ошибок и предупреждений нет |
| `multiprocess_prototype/backend/tests` | 413 passed |
| `multiprocess_prototype/recipes/tests` | 413 passed, 5 skipped |
| `scripts/run_framework_tests.py` | 14740 passed, 2 failed, 47 skipped, 2 xfailed, 43 мин 40 с |

Красные. Файлы, из-за которых они красные, кандидат не меняет (`git diff main 5e6aded45` по ним пуст):

| Тест | Причина | Где записано |
|---|---|---|
| `test_std_logger_guard::test_no_bare_stdlib_logger_outside_whitelist` | 6 `getLogger`: `Services/camera_device` (3), `Services/hikvision_camera` (2), `run_control.py:32` | C-106 (в записи 5 мест и старые номера строк) |
| `test_gc_policy_guard::test_qt_tests_collect_through_policy` | 6 `gc.collect()` в тестах GUI | C-113 |

Не прогонялось: `pyright`; каталоги `multiprocess_prototype` кроме `backend/tests` и `recipes/tests` (радиус — в отчётах задач).

Ревью ветки (Opus `a98f3b84d593b38e1`) APPROVED на этом же кандидате: `reports/branch-review-2.2e-2.10-2.11.md`.
Слияние — по слову владельца.
