# Проверки перед слиянием C-117 (2026-11-27, `fix/vfd-reply-envelope` = `b69110948`, база `main` `027706dbd`)

Окно `heavy`, python главного `.venv`, `PYTHONPATH` = дерево. 12 файлов, все под `multiprocess_prototype/frontend/widgets/tabs/services/`.

| Проверка | Итог |
|---|---|
| `scripts/validate.py` | ошибок и предупреждений нет |
| `tabs/services/vfd/tests` | 47 passed |
| `tabs/services/devices_common/tests` | 153 passed |
| `tabs/services/robot/tests` | 141 passed |
| `multiprocess_prototype/backend/tests` | 413 passed |
| `scripts/run_framework_tests.py` | 14803 passed, 2 failed, 47 skipped, 2 xfailed, 44 мин 46 с |

Красные. Файлы, из-за которых они красные, кандидат не меняет, новых `gc.collect` и `getLogger` в его диффе 0:

| Тест | Причина | Где записано |
|---|---|---|
| `test_gc_policy_guard::test_qt_tests_collect_through_policy` | 6 `gc.collect()` в тестах GUI | C-113 |
| `test_std_logger_guard::test_no_bare_stdlib_logger_outside_whitelist` | 6 `getLogger`: `Services/camera_device` (3), `Services/hikvision_camera` (2), `run_control.py:32` | C-106 |

C-127 (гонка логгера) в этом прогоне не проявилась.

После прогона `main` ушёл на `721bd29f9` (слияния layer-render): 7 файлов в `docs/`, `plans/layer-render/` и `scripts/label_angle*`.
С файлами C-117 они не пересекаются, `git merge-tree` даёт дерево `f5e9d48f5` без конфликтов. Прогон на новом `main` не повторялся.

Не прогонялось: `pyright`; каталоги `multiprocess_prototype` кроме перечисленных; живой стенд (кнопка «Обновить» вкладки ПЧ входит в остаток приёмки 2.4).
