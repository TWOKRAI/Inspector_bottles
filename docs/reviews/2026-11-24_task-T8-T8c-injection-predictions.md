# T8 + T8c (контракт времени кадра): предсказания инъекций лида, записаны ДО прогона (2026-11-24)

Worktree `.claude/worktrees/gfp-t8-dev` (ветка feat/gfp-t8-capture-time, база bc82d9363). Исполнитель мутаций — developer (владелец файлов): правка копии/временная правка с откатом по sha256. Две группы тестов: [T] = файлы слепого tester-а (test_source_producer_capture_stamps.py 14; Services/camera_device/tests/test_plugin_base.py новые 5; Plugins/sources/synthetic_frame_source/tests/test_capture_stamps.py 7), [D] = тесты developer-а (process_module/tests/test_plugin_runner.py, 7 новых) и существующие соседи. Базовая линия: [T] 26 passed (14+5 из 28+7), test_plugin_runner.py 35 passed, test_plugin_on_core.py (hikvision) 17 passed.

«Красный набор (минимум)» — тесты, которые ОБЯЗАНЫ упасть; дополнительные красные не из набора фиксируются отдельно («шире»); тест из набора, оставшийся зелёным, — находка. Файлы прогоняются по одному через machine_gate light, python `../../../.venv/Scripts/python.exe`.

| № | мутация | красный набор (минимум) | примечание |
|---|---|---|---|
| N1 | source_producer: запасной штамп capture_ns не ставится вовсе | [T] test_producer_stamps_capture_ns_when_plugin_did_not; test_mixed_batch_only_unstamped_items_are_stamped; test_none_or_non_int_capture_ns_counts_as_absent[none, float, str]; test_capture_ns_strictly_increasing_1000_items; test_capture_ns_is_int; test_capture_ns_non_decreasing_within_one_batch; test_capture_ns_and_group_id_survive_real_producer_and_fresh_dict_plugin; test_fallback_capture_ns_survives_fresh_dict_plugin | по отчёту tester-а 10 красных из 14 |
| N2 | проверка типа заменена на setdefault (любое присутствие ключа = штамп) | [T] test_none_or_non_int_capture_ns_counts_as_absent[none, float, str] | остальные [T] зелёные |
| N3 | безусловная перезапись capture_ns продюсером | [T] test_plugin_stamp_not_overwritten; test_zero_plugin_stamp_is_kept; test_mixed_batch_only_unstamped_items_are_stamped; test_capture_ns_and_group_id_survive_real_producer_and_fresh_dict_plugin | |
| N4 | проверка штампа через истинность (`if not item.get("capture_ns")`) | [T] test_zero_plugin_stamp_is_kept; test_none_or_non_int_capture_ns_counts_as_absent[float]; ...[str] | параметр [none] ЗЕЛЁНЫЙ (None ложно, заменяется) |
| N5 | capture_ns = perf_counter() (float) вместо perf_counter_ns() | [T] test_capture_ns_is_int; test_producer_stamps_capture_ns_when_plugin_did_not | шире: тесты скобок |
| N6 | одно значение capture_ns на весь прогон | [T] test_capture_ns_strictly_increasing_1000_items | |
| N7 | capture_ns = time.time_ns() | [T] test_producer_stamps_capture_ns_when_plugin_did_not (скобка); test_capture_ns_strictly_increasing_1000_items (577 равных пар из 1000 по замеру reviewer-а) | test_capture_ns_is_int ЗЕЛЁНЫЙ |
| N8 | capture_ns убран из _CARRIED_SYSTEM_FIELDS (plugin_runner) | [T] test_capture_ns_and_group_id_survive_real_producer_and_fresh_dict_plugin; test_fallback_capture_ns_survives_fresh_dict_plugin; [D] test_capture_ns_survives_plugin_hop | test_group_id_survives_plugin_hop зелёный |
| N9 | group_id убран из _CARRIED_SYSTEM_FIELDS | [T] test_capture_ns_and_group_id_survive_real_producer_and_fresh_dict_plugin; [D] test_group_id_survives_plugin_hop | test_capture_ns_survives_plugin_hop зелёный |
| N10 | продюсер назначает group_id=0 | [T] test_producer_does_not_assign_group_id | |
| N11 | камера: capture_ns берётся в produce()/_build_item (perf_counter_ns() там), а не в _on_frame | [T] test_camera_device_item_has_capture_ns_and_capture_ts; test_camera_capture_ns_taken_at_on_frame_not_at_produce; test_camera_capture_ns_is_of_latest_frame_when_two_frames_before_produce | |
| N12 | камера: capture_ts = time.time() в _build_item вместо ts | [T] test_camera_device_item_has_capture_ns_and_capture_ts (capture_ts == ts и разрыв >= 40 мс) | остальные камерные [T] зелёные |
| N13 | hikvision plugin.py: _build_item снова с 4 параметрами (откат правки варианта A) | hikvision test_plugin_on_core.py: все 17 (TypeError) | test_4_2d_acceptance.py — не уверен, наблюдение |
| N14 | синтетика: штампы не ставятся | [T] test_synthetic_item_has_capture_ns_and_capture_ts; test_synthetic_capture_ns_stamped_inside_produce; test_synthetic_capture_ts_stamped_inside_produce; test_synthetic_capture_ns_differs_between_produce_calls | test_synthetic_timestamp_stays_monotonic_float зелёный |
| N15 | синтетика: capture_ns = time.time_ns() | [T] test_synthetic_capture_ns_stamped_inside_produce | test_synthetic_capture_ns_differs_between_produce_calls — вероятно красный при шаге часов, наблюдение |
| N16 | камера: timestamp/ts переносятся из _on_frame в produce() | [T] test_camera_timestamp_and_ts_still_taken_at_on_frame | |
| N17 | камера: слот возвращается к 4-элементному кортежу, cap_ns берётся в produce() | как N11 | |

Критерий находки: (a) тест из «красного набора (минимум)» остался зелёным; (b) sha256 после отката не совпал; (c) параметр [none] при N4 стал красным (значит проверка не по истинности) — это тоже расхождение.
Файлы прогона после каждой мутации (по одному): process_module/tests/test_source_producer_capture_stamps.py; process_module/tests/test_plugin_runner.py; Services/camera_device/tests/test_plugin_base.py; Plugins/sources/synthetic_frame_source/tests/test_capture_stamps.py; Services/hikvision_camera/tests/test_plugin_on_core.py.

## Дополнение после стадии 5, раунд 1 (2026-11-24): дыра в покрытии подкласса Hikvision

Результат матрицы N1..N17: 14 из 17 совпали по минимуму; N1, N11, N17 — ошибки предсказаний (тесты не зависят от запасного штампа / проверяют capture_ns только по типу; мутации убиты другими тестами). Стадия 5 нашла дыру: подкласс `HikvisionCameraPlugin._build_item` передаёт `cap_ns` в super(), и мутант «передаётся 0» оставляет все 45 тестов Hikvision зелёными. Решение лида: новый файл автора `Services/hikvision_camera/tests/test_capture_stamps.py` (developer T8 — тест своего подкласса; слепого tester-а на подкласс не назначаю: механизм штампа проверен слепым набором камеры, здесь тест проводки подкласса). Тест идёт через настоящие `_on_frame` и `produce()` (через `_feed` из `core_rig`), проверяет `type(capture_ns) is int`, `n0 <= capture_ns <= n1`, `capture_ts == ts`, и сон 50 мс между `_on_frame` и `produce()` с разрывом >= 40 мс.

| № | мутация | красный набор (минимум) | примечание |
|---|---|---|---|
| N18 | Hikvision `_build_item`: в super() передаётся `0` вместо `cap_ns` | новый test_capture_stamps.py: тест «capture_ns в скобке n0..n1» и тест «штамп взят в _on_frame, не в produce»; | 17+17+2+9 существующих Hikvision зелёные (как у reviewer-а) |
| N19 | Hikvision `_build_item`: `cap_ns = time.perf_counter_ns()` внутри подкласса (штамп produce вместо _on_frame) | новый тест «взят в _on_frame, не в produce» (разрыв 50 мс) | тест скобки зелёный |
| N20 | Hikvision `_build_item`: `capture_ts=time.time()` вместо `ts` | новый тест `capture_ts == ts` | остальные зелёные |
