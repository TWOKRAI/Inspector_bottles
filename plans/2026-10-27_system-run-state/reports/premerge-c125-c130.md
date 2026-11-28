# Прогон перед слиянием: C-125 (`fix/vfd-draw-lock`) и C-130 (`fix/splash-stall-timeout`)

Дерево-кандидат `integ/213-214` `d41d2b789`: `main` `aaf25a4c5` + `fix/vfd-draw-lock` `c9c8baef4` +
`fix/splash-stall-timeout` `001883e58`. `git merge-tree --write-tree main integ/213-214` равен дереву кандидата
(`ef5c8505e`). Windows 10, окно `heavy` `inspector-bottles-9f`, 2026-11-28 с ~14:35. Строка правила: «код вне
фреймворка».

| Набор | Итог | Время |
|---|---|---|
| `scripts/validate.py` | rc 0 | 56 с |
| `multiprocess_prototype` целиком | 5732 passed, 14 skipped | 434 с |
| `Services/device_hub/tests` | 1256 passed, 6 skipped | 722 с |
| `Plugins/hub/device_hub/tests` | 585 passed | 314 с |
| `Plugins/calibration/camera_robot/tests` | 51 passed | 14 с |
| `Services/auth/tests` | 173 passed | 13 с |
| `Services/sql/tests` | 108 passed | 6 с |
| `backend_ctl/tests/test_harness.py` | 10 passed, 3 skipped | 5 с |
| `backend_ctl/tests/test_harness_run_gate.py` | 22 passed | 11 с |
| тесты фреймворка, смотрящие наружу | 1220 passed, 28 skipped, **2 failed** | 1018 с |

Всего ~43 минуты. Первый замер набора «смотрящие наружу»: **17 минут**.

Красные, оба из реестра, файлы вне диффа кандидата:

- `logger_module/tests/test_std_logger_guard.py::test_no_bare_stdlib_logger_outside_whitelist` — C-106
  (`Services/camera_device`, `hikvision_camera`, `frontend/widgets/chrome/run_control.py`);
- `tests/test_gc_policy_guard.py::test_qt_tests_collect_through_policy` — C-113 (`gc.collect()` в трёх GUI-тестах).

Обе ветки проверены одним деревом. Промежуточное состояние «`main` + только замок ПЧ» отдельно этим прогоном не
гонялось; сливать обе подряд под одним слотом, итоговое дерево должно совпасть с проверенным.

Слияние: **не сделано**, ждёт «да» владельца.
