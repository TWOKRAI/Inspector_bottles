# Инъекции W2-c (`dev/w2-c` `c05489444`)

Прогнозы записаны лидом ДО прогона. Файл кода: `multiprocess_framework/modules/frontend_module/bridge/frame_pump.py`.
Тесты: `test_frame_pump_silence.py` (T), `test_frame_pump_silence_hazards.py` (H).

| код | тест |
|---|---|
| T1 | `test_silence_reported_once_per_second_with_bounds` |
| T2 | `test_frame_after_silence_reports_none_once` |
| T3 | `test_configured_key_without_any_frame_is_silent` |
| T4 | `test_disabled_modes_never_call_back` |
| T5 | `test_steady_frames_report_nothing` |
| T6 | `test_silence_is_per_key` |
| T7 | `test_unshown_frame_keeps_silence` (2 параметра) |
| T8 | `test_stats_keys_unchanged` |
| H1 | `test_disabled_reads_no_clock` |
| H2 | `test_stop_inside_on_silence_ends_calls` (2 параметра) |
| H3 | `test_on_silence_exception_on_number_and_none` |
| H4 | `test_never_empty_mailbox_unshown_frames_still_report_silence` (2 параметра) |
| H5 | `test_dropped_key_forgets_silence` |

| № | инъекция | точная правка | обязаны покраснеть |
|---|---|---|---|
| M1 | `silence_every_tick` | в `_check_silence` убрать `and int(age_s) != self._silent.get(key)` | T1, H3, H4, H5 |
| M2 | `none_before_sink` | в `_tick` перед вызовом `sink`: если механизм включён и `self._silent.pop(key, None) is not None`, позвать `_call_on_silence(key, None)` | T2, T7, H2, H4 |
| M3 | `none_before_every_frame` | в ветке `if shown:` звать `_call_on_silence(key, None)` всегда, без проверки `_silent` | T2, T5, T6 |
| M4 | `once_per_episode` | в `_check_silence` заменить `int(age_s) != self._silent.get(key)` на `key not in self._silent` | T1, T7, H4 |
| M5 | `age_not_reset_by_frame` | в ветке `if shown:` убрать `self._last_shown[key] = finished` | T5, T6 |
| M6 | `age_shared_across_keys` | все записи и чтения `_last_shown[...]` свести к одному общему ключу `"_"` | T6 |
| M7 | `age_from_zero_never_seen` | в `_ensure_key` не заводить `_last_shown`; в `_check_silence` брать `self._last_shown.get(key, 0.0)` | T3, H1 |
| M8 | `disabled_flag_ignored` | `self._silence_on = True` | T4, H1 |
| M9 | `unshown_frame_resets_age` | в ветке `else` перед `_check_silence` поставить `self._last_shown[key] = finished` | T7 (оба), H4 (оба) |
| M10 | `clock_read_when_disabled` | в `_ensure_key` читать `time.perf_counter()` безусловно | H1 |
| M11 | `stats_gets_silence_key` | в `_new_counters` добавить ключ `"silence_s": 0.0` | T8 |
| M12 | `callback_after_stop` | в `_tick` после `sink` убрать `and not self._stopped` | H2 (параметр с `stop` из `sink`) |
| M13 | `exception_stops_pump` | в `_call_on_silence` убрать `try/except`, звать колбэк прямо | H3 |

## Результат прогона

Заполняется после прогона.
