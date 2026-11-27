# Прогон перед слиянием: C-125 (`fix/vfd-draw-lock`) и docs 2.5 (`docs/run-state-2-5`)

Дерево-кандидат `integ/25-c125` `f73d1e824`: `main` `6aa7d0dad` + `fix/vfd-draw-lock` `decdbcb04` + `docs/run-state-2-5` `81ecbb102`. Windows 10, окно `heavy` `inspector-bottles-9f`, 2026-11-27 ~19:35–20:37.

| Набор | Итог |
|---|---|
| `scripts/validate.py` | rc 0 |
| вкладка ПЧ | 95 passed |
| `devices_common` | 153 passed |
| вкладка робота | 141 passed |
| `Services/device_hub/tests` | 1171 passed, 6 skipped |
| `Plugins/hub/device_hub/tests` | 585 passed |
| `multiprocess_prototype/backend/tests` | 413 passed |
| фреймворк (`run_framework_tests.py`) | 14803 passed, **2 failed**, 47 skipped, 2 xfailed за 2819 с |

Красные, оба старые, их файлы вне диффа кандидата:

- `logger_module/tests/test_std_logger_guard.py::test_no_bare_stdlib_logger_outside_whitelist` — C-106 (6 строк в `Services/camera_device`, `hikvision_camera`, `run_control.py`);
- `tests/test_gc_policy_guard.py::test_qt_tests_collect_through_policy` — C-113 (6 вызовов `gc.collect()` в трёх GUI-тестах).

## Слияние

- `docs/run-state-2-5` влита в `main` `555a72724` (2026-11-27), дерево слияния совпало с `git merge-tree`. Только `.md`. Слово владельца в этой вкладке: «да» на вопрос о вливании после зелёного прогона; полоса робота (`inspector-bottles-22`) согласовала, ей сообщён новый SHA. `validate.py` на `main` после слияния: ошибок нет.
- Прогон шёл на дереве вместе с C-125; отдельно «`main` + только docs» тесты не гонялись.
- `fix/vfd-draw-lock` **не влита**: нет живого стенда и отдельного «да» владельца. Если `main` сдвинется, перед слиянием влить его в ветку и повторить прогон.
- Push не делался.
