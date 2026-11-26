# H4, отчёт developer: опорные номера кадра при возврате из `lost`

Ветка `fix/dcb-h4-lost-frames`, база `364ae7b4b`. План: `plans/2026-11-26_device-common-base/plan.md`.

## Итог

Дефект воспроизведён и исправлен. В `CameraDevicePlugin._on_state` при `new == "grabbing"` и `old == "lost"`
под `self._lock` сбрасываются `_last_frame_num` и `_last_trigger`. Накопленные счётчики не меняются.
Строка модуля W1-a в `plugin_base.py` дополнена этим правилом.

## Файлы

- `Services/camera_device/plugin_base.py` — сброс опоры и две строки docstring.
- `Services/camera_device/tests/test_lost_frames_after_reconnect.py` — новый, 4 теста (5 запусков).
- `docs/reviews/2026-11-26_task-H4-developer.md` — этот отчёт.

## Путь импорта

`PYTHONPATH=$(pwd -W)`, python `../../../.venv/Scripts/python.exe`, тот же cwd, что у pytest:

```
D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\.claude\worktrees\k-h4\multiprocess_framework\__init__.py
D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\.claude\worktrees\k-h4\Services\camera_device\plugin_base.py
```

Все прогоны pytest шли через `machine_gate.sh`, сессия `inspector-bottles-2a`.

## RED на неизменённом коде

`light ... -m pytest Services/camera_device/tests/test_lost_frames_after_reconnect.py -q --tb=short -p no:logging`

```
test_reconnect_with_higher_numbers_not_counted[no_trigger_mode]   E   assert 489 == 0
test_reconnect_with_higher_numbers_not_counted[free_run]          E   assert 489 == 0
test_trigger_lost_reference_reset_after_reconnect                 E   assert 289 == 0
test_counted_losses_survive_reconnect_and_new_reference_counts_gaps  E   assert 496 == 2
=================== 4 failed, 1 passed, 1 warning in 5.05s ====================
```

Зелёным был только охранный `test_gap_inside_session_still_counted`.

## GREEN

```
======================== 5 passed, 1 warning in 4.29s =========================
```

Пять повторов подряд: каждый раз `5 passed` (4.23–6.27 с).

Каталог модуля, `medium ... -m pytest Services/camera_device/tests -q --tb=short`:

```
========== 664 passed, 10 skipped, 51 warnings in 225.96s (0:03:45) ===========
```

После этого прогона менялся только перенос строк docstring в `plugin_base.py`; пять повторов выше и матрица
ниже шли уже на финальном тексте. `ruff check` и `ruff format --check` по двум файлам чистые.

## Break-injection (`light`, файл восстановлен, sha256 до и после совпал)

| поломка | результат |
|---|---|
| I1: сброса в ветке `grabbing` нет | 4 failed: 489, 489, 289, 496 |
| I2: не сбрасывается `_last_trigger` | 2 failed: 289, 296 |
| I3: не сбрасывается `_last_frame_num` | 3 failed: 489, 489, 496 |
| I4: вместе с опорой обнуляются счётчики | 1 failed: `1 == 2` |

## Приёмка

- Кадры 1..10, `lost -> grabbing`, кадры с 500: `lost_frames == 0`, `link.outages == 1` (оба пути возврата).
- Триггер 1..10, возврат, 300: `trigger_lost == 0`.
- Пропуск 5 -> 7 внутри сеанса: `lost_frames == 1`.
- Без сброса первый тест даёт 489 (I1).

## Проверка путей сеанса

`_recovered` ставит `hold.up = True` после каждого возврата в `grabbing`. Поэтому следующий обрыв идёт через
`_lost_from_grabbing` и состояние `lost`. Повторы после взятого прибора тоже дают `lost` (`_retry_failed`).
`on_state("lost", "grabbing")` зовётся из потока-владельца до первого `on_frame` на обоих путях
(`_resume` до `_grab_loop`; `_grab_loop` перед `self._on_frame(raw)`).

## Что истолковано, а не выполнено буквально

- Первый тест параметризован: путь без режима триггера и свободный поток (`trigger_mode Off`). Node id получили
  суффиксы `[no_trigger_mode]`, `[free_run]`.
- Добавлен четвёртый тест: накопленные потери переживают переподключение, пропуск после возврата считается.
- Обрыв изображён событием `disconnected` (`make_link_event_port`, `link_silence_s 0`), как в
  `test_reconnect_does_not_repeat_identity_line`. `disconnect()`/`restore()` не использованы.
- В тесте обёрнут `port.get_frame`: фейк отдаёт ровно кадры сценария и дальше молчит. Без обёртки номер перед
  обрывом не равен 10. `fake_port.py` не менялся.
- Тест читает и подменяет приватные поля: `port._delivered`, `port._frame_meta`, `plugin._seq`, `plugin._session`.
- Первая правка сделана позже пятого вызова инструмента: сначала читались фейк и тесты W2-a.

## Что осталось открытым или ненадёжным

- Железо не проверено: как меняется номер кадра MVS после возврата (H6).
- Условие `old == "lost"` тестом не отличается от «сброс на любом входе в `grabbing`»: другие входы идут после
  сброса в `opening`, а перезахват внутри `grabbing` не зовёт `on_state`. Защиты от этой замены тестом нет.
- Перезахват (`restart_regrab`) отдельным тестом здесь не покрыт: код его не касается.
- Кадры, потерянные за время обрыва, не считаются нигде; виден только `link.outages` (решение лида).
- `frame_watch` при переподключении не проверялся.
- `pyright` и `sentrux check` не запускались: в коде продукта новых импортов нет.
- README и STATUS модуля не менялись (вне FILES). `grep -E "lost_frames|опорн"` по README, STATUS, DECISIONS
  совпадений не дал.
