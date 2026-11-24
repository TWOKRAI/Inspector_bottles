# Win-G: фейковый порт камеры отдавал None раньше таймаута (грубые часы Windows)

STATUS: DONE_WITH_CONCERNS (замечание: инъекция A, см. ниже)

## Итог
`Services/camera_device/testing/fake_port.py`: `start_grabbing` и `_wait_next_frame` переведены на `time.perf_counter()`;
`_wait_next_frame` переписан циклом до срока (deadline = perf_counter + timeout_ms/1000). `_created` (:210) и `_busy_for_s` (:283) не тронуты.
`Services/camera_device/tests/test_fake_port_options.py`: новый тест
`test_frame_period_малый_кадр_внутри_timeout_никогда_не_отдаётся_как_None` (период 0,05; 30 вызовов `get_frame(500)`; 0 `None`; номера кадров 1..30).
Не коммичено. Патч: `C:/Users/INNOTECH/AppData/Local/Temp/claude/65f734dde6ea3dc7/ad054591-efb3-40e2-a684-2e0d7b7b2962/scratchpad/patches/wf-g1.patch` (2 файла).

## Проверка импорта (cwd = worktree)
`multiprocess_framework.__file__` = `D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles--wf-b\multiprocess_framework\__init__.py`

## Красный ДО правки (с новым тестом, код не тронут)
`test_fake_port_options.py`: `2 failed, 18 passed`; новый тест `assert 22 == 0` (22 None из 30);
`test_frame_period_малый_get_frame_ждёт_следующего_кадра`: `assert None is not None`.

## После правки (через гейт light)
- `test_fake_port_options.py`, три запуска подряд: `20 passed` x3.
- `test_plugin_observability.py`: `18 passed` (было 1 failed, 17 passed).
- Остальные 27 файлов `Services/camera_device/tests` по одному: все passed, 0 failed
  (`test_port_contract.py`: 19 passed, 10 skipped — skip уже были в файле, не мои).
- `ruff check -q` на двух файлах: чисто.

## Инъекция (предсказание записано до запуска)
| вариант | ожидалось | получилось |
|---|---|---|
| A: `monotonic` вместо `perf_counter` внутри нового цикла `_wait_next_frame` | зелёный, 20 passed (цикл сам дожидается срока на любых часах) | 20 passed |
| B: старое тело `_wait_next_frame` (один сон + сверка) с `monotonic` | красный, новый тест: 5..25 None из 30 | 2 failed, 18 passed; новый тест `assert 23 == 0` |

После инъекций файл восстановлен из копии, `cmp` — идентично.

## What I interpreted rather than followed
- Инъекцию «верни `time.monotonic()` в `_wait_next_frame`» прочитал двояко и прогнал оба варианта (A и B).

## What I left open / unreliable
- Инъекция A остаётся зелёной: сам цикл (а не смена часов) снимает дефект, поэтому новый тест ловит регрессию класса «одиночный сон + сверка», но не регрессию «`perf_counter` -> `monotonic` при сохранённом цикле». Это допустимо (поведение корректно), но смена часов отдельным тестом не закреплена. Реальная проверка смены часов потребовала бы подмены часов — отклонено как хрупкое (урок про глобальный patch времени).
- Красный воспроизведён на этой Windows-машине (шаг часов 15,6 мс); на Linux/macOS (точные часы) новый тест и без правки зелёный, там он регрессию не поймает.
- Тест длится около 1,5 с (30 x 0,05 с); при высокой нагрузке машины дедлайн `_timed` — 10 с.
- `file` показывает у обоих файлов чистый CRLF; построчную проверку нетронутых строк не делал, кроме `git diff --stat` (18 и 9 строк).

## Files touched
- `Services/camera_device/testing/fake_port.py`: :347 (`start_grabbing`), :375-392 (`_wait_next_frame`).
- `Services/camera_device/tests/test_fake_port_options.py`: :91-98 (новый тест).

memory hits: `scripts/memory/search.py monotonic clock windows fake port` -> docs/claude/memory/project_monotonic_resolution_windows.md, docs/claude/memory/feedback_global_clock_patch_flake.md
