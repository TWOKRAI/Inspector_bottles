# База красных до волны 1 (заполняет лид)

- **Коммит:** `85a7906d1` (`integ/multicam-obs`)
- **Когда:** до старта developer-ов W1-a, W1-a2, W1-b, W1-c
- **Радиусы (по одному каталогу, класс medium):** `Services/camera_device/tests`, `Services/hikvision_camera/tests`, `Services/code_reader/tests`, `multiprocess_framework/modules/process_module/tests`, `multiprocess_framework/modules/logger_module/tests`
- **Команда:** `bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" medium <session> <py> -m pytest -q --tb=no -rfE <каталог>`

| test id | status | note |
|---|---|---|
| multiprocess_framework/modules/logger_module/tests/test_std_logger_guard.py::test_no_bare_stdlib_logger_outside_whitelist | FAILED | logger_module/tests; текст assert не захвачен (--tb=no), перезапуска не было |

Исходники в прогоне идентичны `85a7906d1` (различие только в тестах). Агент снимка заявил, что три файла слепых тестеров из `ff2e7e2df` были в прогоне и прошли; это противоречит измерениям тестеров (красных 10 + 9 + 2 в их worktree), поэтому заявление НЕ принято: вероятно, каталоги стартовали до переноса файлов. База ниже = красные существующих тестов; три новых файла в неё не входят и проверяются отдельно (красные до кода).
camera_device/tests: 499 passed, 0 failed, 0 errors, 10 skipped, wall 75s (0 red)
hikvision_camera/tests: 350 passed, 0 failed, 0 errors, 4 skipped, wall 11s (0 red)
code_reader/tests: 738 passed, 0 failed, 0 errors, 0 skipped, wall 76s (0 red)
process_module/tests: 3843 passed, 0 failed, 0 errors, 0 skipped (1 xfailed), wall 393s (0 red)
logger_module/tests: 948 passed, 1 failed, 0 errors, 2 skipped, wall 45s (1 red)
