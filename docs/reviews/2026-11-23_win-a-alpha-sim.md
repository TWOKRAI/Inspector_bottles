# Win-A: сторож P0 run_alpha сравнивает пути с разными разделителями

STATUS: DONE_WITH_CONCERNS

## Что сделано
- scripts/alpha_sim/run_alpha.py `_listener_problem` (~:334): обе стороны сравнения приводятся через
  `os.path.normcase(os.path.normpath(...))` (`want_path` считается один раз до цикла).
- scripts/alpha_sim/tests/test_p4_alpha_runner.py: фейк `World.read_lines` пишет `path.as_posix()` (:282);
  новый прямой тест `test_listener_problem_compares_paths_across_separators` (перед `test_port_guard_other_mismatches`).

## Доказательства
Импорт (cwd = worktree, PYTHONPATH = worktree):
`D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles--wf-a\multiprocess_framework\__init__.py`

До правки (один тест): `test_full_run_on_fakes` -> `assert 3 == 0`, `1 failed`.

После правки, через гейт light, по файлу:
- test_p4_alpha_runner.py: `9 passed` (8 + новый)
- test_p4_alpha_hazards.py: `34 passed`
- test_alpha_split_acceptance.py: `89 passed`
- test_alpha_split_hazards.py: `21 passed`
- ruff check по двум файлам: код выхода 0

Контрфакт нового теста: run_alpha.py возвращён к HEAD (as_posix в тесте оставлен) ->
`6 failed, 3 passed`, среди красных `test_listener_problem_compares_paths_across_separators`; после возврата правки `9 passed`.

POSIX: `posixpath.normcase(posixpath.normpath('/stand/apps/line_sim/run.py'))` -> `/stand/apps/line_sim/run.py` (без изменений).
Префикс: `ntpath.normcase(ntpath.normpath(r'\?\D:\stand/apps/line_sim/run.py'))` -> `\?\d:\stand\apps\line_sim\run.py`
(normpath префикс сохраняет, не срезает).

## Открыто
- Если realpath одной стороны вернёт `\?\` (гонка с mkdir, см. память), а другой нет, сравнение даст ложный отказ.
  Обе стороны идут через realpath, поэтому в обычном случае префикс одинаков; срез префикса вне DESIGN, не делался.
- Новый тест на POSIX проверяет только то, что совпадение и несовпадение работают; «\» на левой стороне он
  получает лишь на Windows (реально прогнан на Windows).
- Живой прогон на Windows и `lsof_listeners` не трогались.
