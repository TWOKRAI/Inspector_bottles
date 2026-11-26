# Task H5 — отчёт разработчика

**STATUS: DONE_WITH_CONCERNS** (замечания — в разделе «Что осталось открытым»).

Ветка `fix/dcb-h5-probe-no-frame`, план `plans/2026-11-26_device-common-base/plan.md`.

## Что сделано

`Services/code_reader/tools/mvcr_probe.py`:

- `None` из `get_frame` — строка `{"event": "no_frame", "t_s": ..., "kind": "none"}`.
- `SdkError` — строка `{"event": "no_frame", "t_s": ..., "kind": "sdk_error", "error": ...}` вместо печати
  текста. Пауза `min(0.2, seconds / 4)` осталась.
- Перед `stop_grabbing` — строка `{"event": "summary", ...}`, только если захват начался. Она выходит и при
  Ctrl+C, и при чужом исключении. Отказ самой печати сводки не пропускает `stop_grabbing` (вложенный `finally`).
- Строки кадров и последняя строка `ИТОГ ...` не менялись. В докстринге модуля — две строки про новые события.

`Services/code_reader/tests/test_mvcr_probe_no_frame.py` (новый, 10 тестов). SDK подменён фейком через
`main(..., api=...)`, часы зонда подменены. Захват ограничен временем: часы двигает сам фейк, после шести
элементов сценария захват кончается. Лишний вызов `get_frame` переводит часы за конец захвата и бросает
`AssertionError`, поэтому сломанный зонд не повисает.

## Доказательства

Путь импорта (cwd = корень дерева, `PYTHONPATH` = `pwd -W`):

```
D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\.claude\worktrees\k-h5\multiprocess_framework\__init__.py
D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\.claude\worktrees\k-h5\Services\code_reader\tools\mvcr_probe.py
```

Все прогоны pytest — через `machine_gate.sh light inspector-bottles-2a ../../../.venv/Scripts/python.exe -m pytest`.

### Итоговый тестовый файл против старого зонда (`git show HEAD:...mvcr_probe.py`)

```
test_none_gives_no_frame_line FAILED
test_sdk_error_gives_no_frame_line FAILED
test_summary_line_counts FAILED
test_frame_lines_unchanged PASSED
test_foreign_exception_propagates_and_stops_grabbing PASSED
test_summary_is_printed_when_capture_is_broken_off[RuntimeError] FAILED
test_summary_is_printed_when_capture_is_broken_off[Ctrl+C] FAILED
test_summary_without_no_frame_has_null_times FAILED
test_no_summary_when_start_grabbing_failed PASSED
test_failed_summary_print_does_not_skip_stop_grabbing FAILED
7 failed, 3 passed
```

**Охранные тесты (зелёные и до правки):** `test_frame_lines_unchanged`,
`test_foreign_exception_propagates_and_stops_grabbing`, а также `test_no_summary_when_start_grabbing_failed`.
Бриф предсказывал красный `test_frame_lines_unchanged`; по уточнению лида это охранный тест.

### После правки

Три файла (`test_mvcr_probe_no_frame.py`, `test_mvcr_probe_hazards.py`, `test_sdk_params.py`):

```
G3 unclosed roots: 0
G4 threads without scope path: 0
======================= 203 passed, 1 warning in 10.57s =======================
```

Два старых файла не менялись. Предупреждение — `DeprecationWarning: legacy_sync` из фреймворка.

```
ruff check          -> All checks passed!
ruff format --check -> 2 files already formatted
sentrux check .     -> 43 rules checked, ✓ All rules pass
mvcr_probe.py --selfcheck -> SELFCHECK OK, exit 0
```

### Приёмка

| Пункт | Тест | Результат |
|---|---|---|
| 3 кадра, 2 `None`, 1 `SdkError` -> 3 строки кадров, 3 `no_frame` по порядку, `summary` с `none_count == 2`, `sdk_error_count == 1` | `test_summary_line_counts` | порядок `frame, no_frame, frame, no_frame, no_frame, frame, summary`; виды `none, sdk_error, none`; `frames 3`, `first 0.247`, `last 0.617` |
| Чужое исключение выходит наружу, `stop_grabbing` вызван | `test_foreign_exception_propagates_and_stops_grabbing` | тот же объект исключения; журнал `start_grabbing, stop_grabbing, close` |

### Поломки зонда по одной

Скрипт в scratchpad: замена строки, прогон нового файла, восстановление. `sha1sum` зонда до и после —
`45e049d004c944be74bf12140c888d21c6440b66`.

| Поломка | Красные | Итог |
|---|---|---|
| I1 `None` считается кадром | summary_line_counts, frame_lines_unchanged, broken_off ×2 | 4 failed, 6 passed |
| I2 чужое исключение глотается (`except Exception`) | foreign_exception_propagates, broken_off[RuntimeError] | 2 failed, 8 passed |
| I3 `t_s` без округления | none, sdk_error, summary_line_counts, broken_off ×2 | 5 failed, 5 passed |
| I4 нет паузы после `SdkError` | sdk_error_gives_no_frame_line | 1 failed, 9 passed |
| I5 сводка и без захвата (`if grabbing`) | no_summary_when_start_grabbing_failed | 1 failed, 9 passed |
| I6 нет защиты `stop_grabbing` от отказа печати | failed_summary_print_does_not_skip_stop_grabbing | 1 failed, 9 passed |
| I7 лишнее поле в строке кадра | frame_lines_unchanged | 1 failed, 9 passed |

## Что я истолковал, а не выполнил дословно

- «Захват начался» = `start_grabbing` вернулся без исключения. Если он бросил, `stop_grabbing` зовётся
  как раньше, а `summary` не печатается.
- `t0` берётся после возврата `start_grabbing` и после строки `>>> ЖДУ`, той же меткой, что и конец захвата.
- Вложенный `finally` вокруг печати сводки в DESIGN не описан: без него отказ `print` оставил бы захват включённым.
- Сверх четырёх тестов из REDS добавлены охранный тест чужого исключения и тесты опасностей.

## Что осталось открытым / ненадёжно

- На живом приборе зонд не запускался (это H8). Темп и объём строк `no_frame` на железе не измерены.
- Часы в тестах фейковые: настоящие значения `t_s` проверены только по формуле, не по реальному времени.
- Если `save_png` бросит, `summary.frames` посчитает кадр, строка которого не напечатана (так же считает `ИТОГ`).
- `Services/code_reader/README.md:60` и `docs/SETUP_GEV_V4.0.2.R.md:129` описывают вывод зонда без новых
  строк `no_frame` / `summary`. Файлы вне FILES, не менялись.
- `git grep -F mvcr_probe` не нашёл в коде репозитория разборщиков stdout, кроме тестов. Внешние скрипты,
  считающие каждую строку JSON кадром, теперь увидят и строки с ключом `event`.
- Брифовое «одно сообщение перед первой правкой под `src/`» не отправлялось: правки не под `src/`.

## Память

`python scripts/memory/search.py mvcr probe no frame get_frame` -> по теме:
`project_code_reader_focus_calibration_streams_frames.md` (прибор даёт кадр только на скан/триггер).
Новый урок: нет.
