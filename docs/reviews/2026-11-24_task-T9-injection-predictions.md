# T9a + T9b (TimeRing, формат сегмента): предсказания инъекций лида, записаны ДО прогона (2026-11-24)

Worktree `.claude/worktrees/gfp-t9-dev` (ветка feat/gfp-t9-frame-buffer, база bc82d9363). Модули: `Services/frame_buffer/time_ring.py` [R], `Services/frame_buffer/segment.py` [S]. Наборы: [T] = три файла слепого tester-а (`test_time_ring.py` 78 с параметрами / 45 функций, `test_segment.py` 32 / 19, `test_time_ring_pin_export.py` 38 / 36), [H] = `test_time_ring_hazards.py` (3, автор). Базовая линия: [T] 148 passed, [H] 3 passed. Каждая мутация гоняется против ОБОИХ наборов; файлы по одному через `machine_gate.sh light inspector-bottles-K`.

Исполнитель — developer T9 (владелец файлов): временная правка с откатом по sha256 от байтовой копии. «Красный набор (минимум)» ОБЯЗАН упасть; красные вне набора фиксируются как «шире»; тест из набора, оставшийся зелёным, — находка. Имена тестов сверены с `grep "def test_"` по файлам tester-а.

| № | мутация | файл | красный набор (минимум) | примечание |
|---|---|---|---|---|
| R1 | вытеснение по времени отключено | R | test_evicts_older_than_buffer_seconds; test_time_eviction_counts_only_time_evictions; test_low_fps_keeps_same_seconds | шире: test_matches_naive_model_without_pins |
| R2 | граница по времени строгая (кадр ровно на границе вытесняется) | R | test_time_eviction_keeps_frame_exactly_at_buffer_boundary; test_time_eviction_one_nanosecond_boundary | |
| R3 | потолок байтов не применяется | R | test_bytes_cap_evicts_oldest_and_span_reported; test_bytes_cap_counters; test_bytes_held_never_exceeds_max_bytes; test_big_frame_evicts_several_oldest | |
| R4 | вставка раньше вытеснения по байтам (пик выше потолка) | R | test_bytes_held_never_exceeds_max_bytes; test_bytes_held_peak_is_maximum_not_current | [H] зелёные |
| R5 | вытеснение по байтам берёт самые новые, не самые старые | R | test_byte_eviction_takes_oldest_not_newest | шире: test_bytes_cap_evicts_the_oldest_frames |
| R6 | at(): ничья «nearest» -> next вместо prev | R | test_at_modes_literal_table; test_at_nearest_prev_next | |
| R7 | at() на пустом кольце бросает исключение | R | test_at_on_empty_ring_returns_none | |
| R8 | нулевые device_frame_num / group_id считаются отсутствующими (проверка по истинности) | R | test_zero_device_frame_num_and_group_id_are_not_none; test_find_group_zero_is_a_real_group_distinct_from_none | |
| R9 | разрывы seq не записываются | R | test_seq_gap_recorded; test_seq_restart_recorded_with_restart_flag; test_seq_gap_after_rejected_frame_uses_last_accepted_seq | test_contiguous_seq_has_no_gaps зелёный |
| R10 | отвергнутый кадр двигает last_seq | R | test_seq_gap_after_rejected_frame_uses_last_accepted_seq | остальные зелёные |
| R11 | порядок только по capture_ns (равный capture_ns отвергается независимо от seq) | R | test_equal_capture_ns_lower_seq_rejected_higher_seq_accepted | шире: test_at_nearest_prev_next_with_equal_capture_ns, test_find_group_orders_by_capture_ns_then_seq |
| R12 | кадр с парой, равной последней принятой, вставляется (<= -> <) | R | test_rejected_duplicate_of_last_pair; test_rejected_order | |
| R13 | oversize сначала вытесняет кольцо, потом отвергается | R | test_oversize_leaves_ring_untouched | test_rejected_oversize, вероятно, зелёный (проверяет счётчик) |
| R14 | проверка зарезервированных бит flags убрана | R | test_append_reserved_flag_bits_raise_value_error; test_append_reserved_flag_error_message_omits_the_input_value | |
| R15 | текст ValueError содержит значение flags | R | test_append_reserved_flag_error_message_omits_the_input_value | test_append_reserved_flag_bits_raise_value_error зелёный |
| R16 | конструктор не проверяет pin_max_bytes <= max_bytes | R | test_constructor_rejects_pin_max_bytes_above_max_bytes | test_constructor_accepts_..._equal зелёный |
| R17 | границы закрепления исключающие (> вместо >=) | R | test_pin_interval_inclusive_on_both_ends; test_pin_single_instant_interval_is_allowed | |
| R18 | закрепление не покрывает будущие кадры | R | test_pin_covers_future_frames; test_pin_covers_future_frames_and_nothing_outside_the_interval | test_pinned_range_survives_eviction зелёный |
| R19 | при нехватке бюджета освобождается самый НОВЫЙ пин | R | test_pin_budget_exceeded_oldest_pin_released_and_counted; test_full_pinned_ring_with_two_pins_releases_only_the_oldest_pin | |
| R20 | pins_released не увеличивается | R | test_pin_budget_exceeded_oldest_pin_released_and_counted; test_pin_budget_exceeded_two_pins_released_counts_only_what_was_needed | |
| R21 | перекрывающиеся пины считаются в бюджете дважды | R | test_overlapping_pins_counted_once_in_pin_budget | |
| R22 | unpin одного тега снимает все пины | R | test_two_overlapping_pins_unpin_one_keeps_other | test_unpin_releases_range зелёный |
| R23 | закреплённые кадры не входят в bytes_held | R | test_pinned_frames_count_toward_bytes_held | шире: test_max_bytes_never_exceeded_with_pins |
| R24 | find_group ищет в журнале, включая вытесненные | R | test_find_group_excludes_evicted_frames | |
| R25 | границы export исключающие | R | test_export_bounds_are_inclusive_on_both_ends | |
| R26 | смещения export для поддиапазона не от нуля | R | test_export_offsets_restart_from_zero_for_a_subrange | |
| R27 | export снимает кадры из кольца | R | test_export_does_not_change_the_ring | |
| R28 | export: склейка blob под замком | R | НИ ОДИН тест не красный (0 из 148 + 3) | ожидаемый пробел: без блокирующего теста не наблюдается; фиксировать как «подтверждён пробел», не как провал |
| S1 | формат записи другой ("<QIqdqqqQ") | S | test_record_struct_is_56_bytes; test_fixed_record_length; test_record_fields_at_fixed_offset | шире: тесты reader с ручной упаковкой |
| S2 | reader не отбрасывает запись за концом blob | S | test_reader_drops_only_last_record_on_truncated_tail; test_reader_hand_packed_record_one_byte_past_blob_end_is_dropped | |
| S3 | reader отбрасывает запись, оканчивающуюся ровно на конце blob (>= вместо >) | S | test_reader_boundary_offset_plus_length_equal_to_blob_size_is_kept; test_reader_hand_packed_record_ending_exactly_at_blob_end_is_kept | шире: test_reader_keeps_all_when_not_truncated |
| S4 | reader бросает struct.error на неполном хвосте индекса | S | test_reader_ignores_incomplete_record_at_index_tail; test_reader_index_cut_mid_record_does_not_raise_struct_error; test_reader_index_shorter_than_one_record_returns_empty | |
| S5 | бит has_group_id не выставляется / не читается | S | test_record_flags_encode_presence_bits_and_user_bits; test_reader_restores_present_fields_and_user_flags_without_reserved_bits | |
| H1 | замок снят целиком (R, три метода записи и чтения) | R | [H] test_concurrent_append_and_at; test_concurrent_pin_unpin_under_writer; test_concurrent_export_under_writer (все 3) | [T] 148 зелёных; developer получил 3 из 3 на трёх мутантах |

Критерий находки: (a) тест из «красного набора (минимум)» остался зелёным; (b) sha256 после отката не совпал; (c) для R28 красный тест — расхождение (значит, пробел закрыт и надо обновить запись); (d) красный набор [T] при H1 не пуст — расхождение.
Файлы прогона после каждой мутации (по одному): Services/frame_buffer/tests/test_time_ring.py; test_segment.py; test_time_ring_pin_export.py; test_time_ring_hazards.py.

## Дополнение после стадии 5, раунд 1 (2026-11-24): решения ADR без мутаций

Матрица R/S/H: 30 из 34 по минимуму совпали (расхождения R4, R6, R12, S1 — слабые тесты слепого tester-а, соседние тесты держат свойства; S1 — вакуумный тест `test_record_struct_is_56_bytes`, находка про слепого tester-а). Стадия 5 добавила 8 мутантов по решениям developer-а, записанным в ADR: все выжили во всех 4 файлах — предсказания лида писались по DESIGN, а решения в неоднозначных местах попали только в ADR. Правило на будущее: после отчёта developer-а — по одному мутанту на каждую строку решений ADR.

Решения лида по правкам (применяет developer T9, файлы tester-а не правятся; новые тесты — в новом файле автора `Services/frame_buffer/tests/test_time_ring_decisions.py` и в `test_time_ring_hazards.py`):
1. `append` проверяет диапазон i64 (capture_ns, seq, device_frame_num, group_id) и тип `capture_ts` (число, приводится к float); нарушение — ValueError с константным текстом без значения; кольцо и счётчики не меняются.
2. `pinned_bytes` — инкрементальный счётчик (пересчёт при pin/unpin/освобождении, `+size` при append закреплённого кадра), не скан; ADR-RING-003 исправить замером (1,2–4,5 мс под замком на 3000 кадрах при скане), «микросекунды» убрать.
3. `export` с t0 > t1 — ValueError (симметрия с `pin`: перепутанные концы не должны молча давать пустое доказательство); ADR поправить.
4. Остальные решения developer-а принимаются как записаны (повторный pin = самый молодой; seq <= last_seq = рестарт; order+size -> rejected_order; unpin не вытесняет сразу) и закрепляются тестами.
5. `S1`: тест автора `RECORD.size == 56 and RECORD.format == "<QIqdqqqI"` (импорт из пакета); тест tester-а не правится.
6. Тест R28 (по сценарию reviewer-а: подмена `Services.frame_buffer.time_ring.build_segment` обёрткой с `entered/release`, писатель в daemon-потоке с `done.wait(2)`) и hazard-тест `find_group` под писателем.
7. `Services/frame_buffer/.claude/` (логи агентов) не стейджить, не удалять.

| № | мутация (после правок) | красный набор (минимум) |
|---|---|---|
| E1 | seq == last_seq не считается рестартом | тест решения «seq равен последнему -> gap {after_seq 5, before_seq 5, missed 0, restart True}» |
| E3 | бюджет пинов в append не учитывает новый кадр | тест сценария A (pin_max_bytes 3000, два кадра по 2000: pins_released 0 после первого, 1 после второго) |
| E4 | повторный pin сохраняет старую позицию (не самый молодой) | тест «pin a, pin b, pin a; превышение бюджета освобождает b, не a» |
| E5 | oversize проверяется раньше порядка | тест «нарушены порядок и размер: rejected_order 1, rejected_oversize 0» |
| E6 | export с t0>t1 возвращает пусто | тест «export(t0>t1) -> ValueError» |
| E7 | unpin вытесняет сразу | тест «unpin не меняет range()["frames"] до следующего append» |
| E8 | новый незакреплённый кадр считается в бюджет пинов | тест сценария B (закреплён кадр 2000, затем кадр 2000 вне интервала: pins_released 0) |
| E9 | проверка i64 в append убрана | тест «append(capture_ns=2**63) -> ValueError, stats frames == 0» (и по одному на seq, device_frame_num, group_id) |
| E10 | capture_ts=None принимается | тест на тип capture_ts |
| E11 | счётчик pinned_bytes не уменьшается при unpin | тесты бюджета пинов и тест «счётчик равен наивному пересчёту после последовательности pin/unpin/append/вытеснение» |
| E12 | счётчик pinned_bytes не растёт при append закреплённого кадра | тот же набор |
| R28t | export склеивает blob под замком | новый тест R28 (писатель блокирован) |
| LF | замок снят в find_group | hazard-тест find_group |
| S1t | RECORD.format другой | новый тест S1 автора |
Критерий находки: красный набор не красный — находка; отката sha256 не совпал — провал; тест из набора, красный на чистом коде — дефект теста. После правок прогнать ВСЮ прежнюю матрицу R/S/H (34) повторно: счётчик и ValueError не должны менять прежние совпадения.
