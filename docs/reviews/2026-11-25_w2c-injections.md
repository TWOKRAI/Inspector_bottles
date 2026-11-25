# W2-c: прогон инъекций (`dev/w2-c`, `c05489444`)

Дерево: `.claude/worktrees/mco-d-w2-c`. Файл мутаций: `multiprocess_framework/modules/frontend_module/bridge/frame_pump.py`.
Прогнозы: `.claude/worktrees/mco-integ/plans/2026-11-25_multicam-observability/injection-W2-c.md` (не менялся).
Коммитов нет. После прогона `git status --short` пуст, HEAD `c05489444`.

## Команда

Из корня worktree, на каждый прогон:

```
PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 PYTHONPATH="$PWD" bash <git-common-dir>/../scripts/machine_gate.sh light inspector-bottles-19 \
  D:/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/.venv/Scripts/python.exe -m pytest -q --tb=line -rfE -p no:cacheprovider \
  -o faulthandler_timeout=90 test_frame_pump_silence.py test_frame_pump_silence_hazards.py test_frame_pump.py
```

Первые два базовых прогона шли без `-o faulthandler_timeout=90`; `baseline1` и `baseline2` имели те же остальные ключи, `baseline2` дополнительно был обёрнут в `timeout 100`.

Проверка импорта под тем же `PYTHONPATH`:
`D:\PROJECT_INNOTECH\Inspector_vision\Inspector_bottles\.claude\worktrees\mco-d-w2-c\multiprocess_framework\modules\frontend_module\bridge\frame_pump.py`.

## База (без `-k`)

| прогон | collected | passed | failed | прочее |
|---|---|---|---|---|
| baseline1 | 54 | 44 | 10 | 62.09 с |
| baseline2 | нет итога | нет итога | не меньше 1 | прерван моим `timeout 100`, exit 124 |
| baseline2b | 54 | 53 | 1 | 55.63 с |
| baseline3 (после мутантов) | 54 | 54 | 0 | 47.15 с |

Все красные базы лежат в `test_frame_pump.py`; в двух файлах тишины красных в базе нет (по `baseline1`, `2b`, `3`).

`baseline1`, 10 красных:

- `test_rate_capped_by_fps_limit[30-2.0-52-62]`
- `test_per_key_rates_differ`
- `test_put_posts_no_qt_event`
- `test_unconfigured_key_found_by_scan_and_served`
- `test_zero_fps_limit_capped_at_60[0]`, `[120]`, `[240]`, `[inf]`
- `test_sink_error_log_is_rate_limited`
- `test_huge_fps_limit_does_not_half_apply_set_keys`

`baseline2b`, 1 красный: `test_put_posts_no_qt_event` (`put породил Qt-события: [170]`).

Тесты флакают. Наблюдение: в `baseline1` счётчики вызовов `sink` ниже нижней границы (например 42 при 52..62). Причина (нагрузка машины) — гипотеза, не проверена.

## Мутанты

Коды тестов: как в файле прогнозов. `rf` = `[returns_false]`, `rs` = `[raises]`. Перед каждым прогоном `git diff --stat` показал правку, после — `git checkout --`, дерево чистое. Каждый мутант прогнан один раз.

| № | прогноз | факт: красные | passed/failed | совпало? |
|---|---|---|---|---|
| M1 | T1, H3, H4, H5 | T1, T7 rf+rs, H4 rf+rs | 49/5 | нет: H3, H5 зелёные; T7 лишний |
| M2 | T2, T7, H2, H4 | T2, T7 rf+rs, H4 rf+rs | 49/5 | нет: H2 зелёный (оба параметра) |
| M3 | T2, T5, T6 | T1, T2, T5, T6, H5 | 49/5 | прогноз покраснел; лишние T1, H5 |
| M4 | T1, T7, H4 | T1, T7 rf+rs, H4 rf+rs | 49/5 | да |
| M5 | T5, T6 | T5, T6 | 52/2 | да |
| M6 | T6 | T6 | 53/1 | да |
| M6b (вариант) | T6 | T6 | 53/1 | да |
| M7 | T3, H1 | T3, T7 rf+rs, H1, H4 rf+rs | 48/6 | прогноз покраснел; лишние T7, H4 |
| M8 | T4, H1 | T4, H1, 4 теста `test_frame_pump.py` | 48/6 | прогноз покраснел; лишние 4 |
| M9 | T7 (оба), H4 (оба) | T7 rf+rs, H4 rf+rs | 50/4 | да |
| M10 | H1 | H1 | 53/1 | да |
| M11 | T8 | T8 | 53/1 | да |
| M12 | H2 (`stop` из `sink`) | **ничего** | 54/0 | **нет: мутант выжил** |
| M13 | H3 | H3 (1 failed + 1 error того же теста) | 53/1, 1 error | да |

Полные имена:

- T1 `test_silence_reported_once_per_second_with_bounds`
- T2 `test_frame_after_silence_reports_none_once`
- T3 `test_configured_key_without_any_frame_is_silent`
- T4 `test_disabled_modes_never_call_back`
- T5 `test_steady_frames_report_nothing`
- T6 `test_silence_is_per_key`
- T7 `test_unshown_frame_keeps_silence[returns_false]`, `[raises]`
- T8 `test_stats_keys_unchanged`
- H1 `test_disabled_reads_no_clock`
- H3 `test_on_silence_exception_on_number_and_none`
- H4 `test_never_empty_mailbox_unshown_frames_still_report_silence[returns_false]`, `[raises]`
- H5 `test_dropped_key_forgets_silence`
- M8, лишние: `test_sink_exception_does_not_stop_pump`, `test_stats_snapshot_has_no_references_to_internal_state`, `test_sink_error_log_is_rate_limited`, `test_sink_error_log_period_is_five_seconds`. В логе M8 при этом `TypeError: 'NoneType' object is not callable`: насос зовёт `on_silence=None`.

Зависаний у мутантов не было.

## Как применены правки

Скрипт делал точную замену строк, требовал ровно одно вхождение и компилировал результат. Уточнения там, где прогноз допускает чтения:

- M2: блок вставлен прямо перед `started = time.perf_counter()` / вызовом `sink`.
- M3: `self._silent.pop(key, None)` оставлен, вызов `_call_on_silence(key, None)` сделан безусловным.
- M4: `... and key not in self._silent`.
- M6: на общий ключ `"_"` переведены все четыре обращения, включая `pop` в `_drop_key`. M6b: то же, но `pop` оставлен по `key`.
- M7: из `_ensure_key` убран весь блок `if self._silence_on:` с записью; в `_check_silence` `.get(key, 0.0)`.
- M10: безусловный `time.perf_counter()` добавлен перед блоком `if self._silence_on:`.
- M13: тело `_call_on_silence` заменено одной строкой `self._on_silence(key, age_s)`.

## Разбор расхождений (чтение кода, отдельным прогоном не проверено)

- **M12 — эквивалентный мутант.** `stop()` ставит `_stopped = True` (строка 182) и делает `self._timers.clear()` (строка 187). Условие в строке 308 `not self._stopped and key in self._timers` после `stop()` ложно и без первой половины. Тест не может убить этот мутант, пока `stop()` чистит `_timers`.
- **M2 / H2.** `stop_in="sink"`: `expected` снимается после появления `("sink", "a")`, поэтому `None`, вставленный до `sink`, уже входит в `expected`. `stop_in="on_silence"`: насос остановлен на первой тишине, до `sink` дело не доходит. H2 этот порядок не проверяет.
- **M1 / H3, H5.** Причину, почему они зелёные, не разбирал.

## Что оставил открытым / ненадёжно

- Каждый мутант прогнан один раз; повторов нет. Тесты `test_frame_pump.py` флакают (база 10, 1, 0 красных), поэтому «лишние» красные вне файлов тишины проверены только по тексту ошибки (M8).
- `baseline2` прерван моим лимитом 100 с. Это не доказанное зависание. Остался ли после `timeout` дочерний процесс pytest, не проверено: команду со списком процессов и чтением `machine.lock` отклонил классификатор разрешений, повторять её я не стал. Свои PID не убивал.
- Если такой процесс пережил `timeout`, он мог работать параллельно со следующими прогонами. Проверить это нечем из имеющегося вывода.
- Объяснения M12 и M2 получены чтением кода.
- Выживший M12 и незакрытые прогнозы H2 (M2), H3 и H5 (M1) — на решение лида. Тесты и код не менялись.
