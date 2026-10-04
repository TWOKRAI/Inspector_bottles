# 5.5B — предсказания до прогона (лид)
Ветка fix/t55-green-main, HEAD 6f5468af1. Наборы: P = hot_rebuild + catalog (cwd = корень worktree); F = hol_hazards + test_declarations_leak_session_catalogue_guard (cwd = multiprocess_framework/modules).
BASE: P и F зелёные, collected — число.
J1 из снимка hot_rebuild удалена строка `compress_rotated` → +1 красный: test_hot_rebuild_framework_layer_key_count_is_pinned, в сообщении `compress_rotated`.
J2 из снимка catalog удалена строка `blob_detector.contour_thickness` → +1 красный в test_catalog_kind_roundtrip.py, имя в сообщении.
J3 socket_channel.send: убрать проверку `sock in self._dead` → +1 красный: test_second_sender_to_stuck_socket_does_not_wait_again (второй отправитель снова ждёт таймаут). Возможны ещё красные в hol_hazards — тогда записать какие.
J3b тест: убрать `warnings.clear()` после прогрева → остаётся зелёным (на Windows прогрев не даёт WARNING; clear — страховка). Зелёный здесь ожидаем, не находка.
J4 _declarations_catalogue_guard.py: убрать `"pacer_late"` из литерала → красный/ERROR на закрытии сессии F.
J4b test_declarations_leak_session_catalogue_guard.py: убрать `"pacer_late"` из `_EXPECTED_FRAMEWORK_METRICS` → +1 красный/ERROR.

## Итог прогона (лид, HEAD 6f5468af1)
- BASE: P `6 passed`, F `11 passed` — зелёные.
- J1: `1 failed, 5 passed` — test_hot_rebuild_framework_layer_key_count_is_pinned, сообщение «появились ['compress_rotated'] … (было 37, стало 38)». **Совпало.**
- J2: `1 failed, 5 passed` — test_resolve_kind_stable_across_json_roundtrip_for_all_register_fields, «появились ['blob_detector.contour_thickness'] (было 448, стало 449)». **Совпало.**
- J3: `1 failed, 10 passed` — test_second_sender_to_stuck_socket_does_not_wait_again, «assert 0.5 < 0.2» (второй отправитель снова ждёт 0.5 с). Других красных в hol_hazards нет. **Совпало.**
- J3b: `11 passed` — `warnings.clear()` на Windows страховка, как предсказано.
- J4: `11 passed, 1 error` — teardown test_session_guard_fixture_is_wired_into_this_session, «лишние=['pacer_late']». **Совпало.**
- J4b: `11 passed, 1 error` — то же место, литерал теста. **Совпало.**
Не инъецировано: skipif win32 (yaml_io, r2) — свойства нет, есть только «красный до» в отчёте разработчика; H8/H9 — проверено разработчиком запуском из cwd=C:/ (11 passed).
