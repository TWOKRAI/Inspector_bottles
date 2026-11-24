# T13 (очередь кадров источника камеры): предсказания инъекций лида, записаны ДО прогона (2026-11-24)

Worktree `.claude/worktrees/gfp-t13-dev` (ветка feat/gfp-t13-source-queue, база d72bcb8ab = T8+T8c). Правимые модули: `Services/camera_device/plugin_base.py` [P], `registers_base.py` [R]. Два набора: [T] = слепой tester (`Services/camera_device/tests/test_source_queue_frames.py`, 9 тестов), [D] = автор (`test_plugin_base_hazards.py`, 27 тестов, из них 8 новых; роли новых: гонка _on_frame/produce, K=1 из потока, K вне границ, K на границах 1 и 64, битый кадр в середине очереди, reset_stats обнуляет overwritten, pending = длина очереди, take_device на фейк-порту). Слепой набор T8 `test_plugin_base.py` (28; два теста приведены лидом к `source_queue_frames=1`) и Hikvision-тесты — регресс.

Исполнитель — developer T13 (владелец файлов); откат по sha256 от байтовой копии; Git Bash явно (не WSL); файлы по одному через `machine_gate.sh light`. Красный набор (минимум) ОБЯЗАН упасть; красные вне набора — «шире»; тест из набора, оставшийся зелёным, — находка. Правило проекта: решения developer-а, записанные в ADR-CAM-007/README, тоже попадают в матрицу.

| № | мутация | файл | красный набор (минимум) | примечание |
|---|---|---|---|---|
| J1 | вернуть одиночный слот (maxlen=1 по умолчанию / produce отдаёт последний) | P | [T] test_three_frames_between_polls_all_delivered; test_exactly_k_frames_all_delivered_none_overwritten; test_overflow_counts_overwritten; test_items_in_seq_order; test_paced_25fps_source_25hz_poll_no_loss | test_queue_of_one зелёный |
| J2 | `overwritten` не считается при полной очереди | P | [T] test_overflow_counts_overwritten; test_overwritten_metric_published; test_queue_of_one_keeps_latest_only | |
| J3 | `overwritten` считается и при неполной очереди (на каждый кадр) | P | [T] test_exactly_k_frames_all_delivered_none_overwritten; test_three_frames_between_polls_all_delivered (если проверяет 0) | |
| J4 | produce отдаёт items не по порядку seq (reversed) | P | [T] test_items_in_seq_order; test_three_frames_between_polls_all_delivered | |
| J5 | produce забирает не всё (только один кадр из очереди) | P | [T] test_three_frames_between_polls_all_delivered; test_produce_drains_queue_second_poll_is_empty или test_exactly_k_frames_all_delivered | |
| J6 | produce не очищает очередь (повторная выдача) | P | [T] test_produce_drains_queue_second_poll_is_empty | |
| J7 | при вытеснении seq сбрасывается/перенумеровывается | P | [T] test_overflow_counts_overwritten (seq 3..6) | |
| J8 | вытеснение удаляет НОВЫЙ кадр, а не старый | P | [T] test_overflow_counts_overwritten; test_queue_of_one_keeps_latest_only | |
| J9 | K = 1 ведёт себя иначе (хранит 2 кадра) | P | [T] test_queue_of_one_keeps_latest_only | |
| J10 | метрика `overwritten` не публикуется при нуле | P | [T] test_overwritten_metric_published или test_exactly_k_frames_all_delivered_none_overwritten (если требуют ключ при 0) | зависит от формы теста; зафиксировать |
| J11 | битый кадр считается `overwritten`, а не `dropped` | P | [T] test_broken_frame_counts_dropped_not_overwritten | |
| J12 | битый кадр в очереди роняет весь produce | P | [D] тест битого кадра в середине очереди | |
| J13 | `_on_frame` и `produce()` под разными замками / без замка | P | [D] гонка _on_frame/produce (3000 кадров, setswitchinterval 1e-6 при наличии); если зелёный — находка (потоковый тест слепнет без setswitchinterval) | |
| J14 | `pending` берётся не из длины очереди (константа 1) | P | [D] pending = длина очереди | |
| J15 | `reset_stats` не обнуляет overwritten | P | [D] reset_stats обнуляет overwritten | решение developer-а, не из брифа |
| J16 | `reset_stats` сбрасывает seq | P | [D] тест «seq продолжается» (из описания: seq_id продолжается) | |
| J17 | регистр без границ (ge=1/le=64 убраны) | R | [D] K вне границ (0, -1, 65, 1000) | |
| J18 | граница 64 исключена (le=63) | R | [D] K на границах 1 и 64 | |
| J19 | умолчание K не 4 | R | [T] test_three_frames_between_polls_all_delivered (три кадра в K=4) и test_overflow_counts_overwritten (K 4 задан явно?) — по факту; если зелёные, находка: умолчание 4 не закреплено | |
| J20 | K читается в configure неверно (сейчас константа 4 вне регистра) | P | [T] test_queue_of_one_keeps_latest_only; [D] K на границах | |
| J21 | подкласс Hikvision: в очередь попадает кадр без cap_ns (5-элементный кортеж теряет 5-й элемент) | P | существующие Hikvision test_capture_stamps.py (3) и test_plugin_on_core.py | регресс T8 |
| J22 | снимок `pending` и `overwritten` читается без замка (рваный снимок) | P | вероятно нет красного (неразличимо наблюдаемо) — подтвердить как известный пробел, не провал | |

Критерий находки: (a) тест из красного набора остался зелёным; (b) sha256 после отката не совпал; (c) J13 зелёный — потоковый тест слеп; (d) J19: если ни один тест не красный — умолчание K=4 не закреплено, developer добавляет тест; (e) J22: красный — расхождение.
