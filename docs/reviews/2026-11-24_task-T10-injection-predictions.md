# T10 (плагин буфера кадров): предсказания инъекций лида, записаны ДО кода developer-а и ДО прогона (2026-11-24)

Worktree `.claude/worktrees/gfp-t10-dev` (ветка feat/gfp-t10-frame-buffer-plugin, база fcbbd46bd = T8 + T9). Правимые модули: `Plugins/io/frame_buffer/plugin.py` [P], `registers.py` [R], `config.py` [C]. Два набора: [T] = слепой tester (`test_frame_buffer_plugin.py`, 10 тестов, sha256 d0312de5…e957), [D] = хазард-тесты developer-а (`test_frame_buffer_hazards.py`: test_plugin_accepts_markers, test_item_without_seq_id_counted_not_raised, test_rejected_frame_does_not_move_prev_seq, test_oversize_frame_counted_not_raised, test_process_does_not_touch_disk, test_command_during_process_not_blocked и др.). Регресс — шесть соседей из ACCEPTANCE (по одному файлу, medium) и `scripts.lifecycle_guards check`.

Исполнитель мутаций — developer T10 (владелец файлов); откат по sha256 от байтовой копии; Git Bash явно. Красный набор (минимум) ОБЯЗАН упасть; красные вне набора — «шире»; тест из набора, оставшийся зелёным, — находка. Решения developer-а, записанные в README (О9) и ADR-подобные пометки, тоже попадают в матрицу.

| № | мутация | файл | красный набор (минимум) | примечание |
|---|---|---|---|---|
| K1 | кадр без `capture_ns` кодируется и кладётся | P | [T] test_missing_capture_ns_rejected | |
| K2 | `float` 1.0 принимается как штамп (`isinstance(.., (int, float))`) | P | [T] test_missing_capture_ns_rejected | |
| K3 | `True` принимается как штамп (`isinstance(.., int)`) | P | [T] test_missing_capture_ns_rejected | именно bool: ловит только вариант с `True` |
| K4 | `None` принимается как штамп | P | [T] test_missing_capture_ns_rejected | |
| K5 | маркер считается отвергнутым кадром (`rejected_no_capture_ns` +1 вместо `lag_markers`) | P | [T] test_lag_marker_becomes_gap | |
| K6 | `missed_seq` растёт на 1 вместо разности | P | [T] test_seq_gap_of_three_counts_missed_seq_3 | |
| K7 | рестарт (`seq <= prev_seq`) добавляет разность/отрицательное в `missed_seq` | P | [T] test_seq_gap_of_three_counts_missed_seq_3 | |
| K8 | `missed_device` читает `seq_id` | P | [T] test_device_frame_num_gap_counts_missed_device | |
| K9 | `missed_device` считает при `None` у одного из соседей | P | [T] test_device_frame_num_gap_counts_missed_device (второй сценарий: у всех `None` → 0) | |
| K10 | константа вместо `buffer_seconds` | P/C | [T] test_buffer_seconds_from_config | |
| K11 | ошибка `imencode` (`(False, None)` или `cv2.error`) останавливает `process()` | P | [T] test_encode_failure_does_not_stop_plugin | |
| K12 | `encode_errors` не считает `cv2.error` (только `(False, None)`) | P | [T] test_encode_failure_does_not_stop_plugin | |
| K13 | `seek` без учёта `max_width` | P | [T] test_seek_respects_max_width | |
| K14 | `seek` увеличивает кадр меньше предела | P | [T] test_seek_respects_max_width (пределы 4000x4000 → (1080, 1440, 3)) | |
| K15 | `seek` ищет по `seq_id`, а не по `capture_ns` | P | [T] test_seek_returns_frame_of_requested_time | |
| K16 | `seek` режим `nearest` ведёт себя как `prev` | P | [T] test_seek_returns_frame_of_requested_time (t_ns 2600 → 3000) | |
| K17 | `seek` за пределами окна бросает исключение вместо `status: "empty"` | P | [T] test_seek_returns_frame_of_requested_time | |
| K18 | `buffer.pin` не вызывает кольцо | P | [T] test_pin_command_protects_range | |
| K19 | `buffer.pin` при `t0 > t1` бросает исключение, а не `status: "error"` | P | [T] test_pin_command_protects_range | |
| K20 | индекс по `capture_ts`, а не `capture_ns` | P | [T] test_every_frame_indexed_by_capture_ns | |
| K21 | `accepts_markers` не объявлен (False) | P | [D] test_plugin_accepts_markers; [T] test_lag_marker_becomes_gap НЕ ловит (маркер подаётся прямо в `process()`) — подтвердить | пара «одно имя, две двери» |
| K22 | `item["seq_id"]` вместо `.get` | P | [D] test_item_without_seq_id_counted_not_raised | [T] зелёные |
| K23 | `prev_seq`/`prev_device` двигаются на отвергнутом кольцом кадре | P | [D] test_rejected_frame_does_not_move_prev_seq | |
| K24 | `rejected_oversize` не публикуется; кадр больше `buffer_max_mb` роняет плагин | P | [D] test_oversize_frame_counted_not_raised | |
| K25 | запись на диск в `process()` (`open`, `imwrite`) | P | [D] test_process_does_not_touch_disk (слабый), строка `git grep` в ACCEPTANCE (красная = exit 0) | |
| K26 | замок счётчиков держится на `imencode`/`imdecode` | P | [D] test_command_during_process_not_blocked | зависит от дедлайна; если зелёный — находка |
| K27 | счётчики публикуются не в конце каждого `process()` (пропуск при вызове, где все item отвергнуты) | P | [T] test_missing_capture_ns_rejected («счётчики опубликованы и после вызова, где отвергнуты все item») | |
| K28 | `frames_in` не считает отвергнутые кадры | P | [D] если есть тест на frames_in при отвергнутом; иначе НЕТ красного — находка (решение DESIGN п.4) | |
| K29 | `max_height` отсутствует → KeyError | P | [D] тест «ключ отсутствует» (поручено лидом); иначе НЕТ красного | |
| K30 | `pin_max_mb` умолчание 0 не расшифровывается как `buffer_max_mb` (кольцо получает 0) | P/R | [T] test_pin_command_protects_range (pin с buffer_max_mb 1024) / test_buffer_seconds_from_config; уточнить по факту | |
| K31 | граница регистра `buffer_seconds` (min 0.1) или `jpeg_quality` (1..100) убрана | R | [D] тест границ регистров; иначе НЕТ красного — дыра | |
| K32 | слой: плагин импортирует PySide6 или `multiprocess_prototype` | P | строка `git grep` слоя (красная = exit 0) | |

Критерий находки: (a) тест из красного набора остался зелёным; (b) sha256 после отката не совпал; (c) K21: если [T] красный — расхождение; (d) K26: зелёный — потоковый тест слеп (без setswitchinterval); (e) K28, K29, K31: если красных нет — developer ДОБАВЛЯЕТ тест (решения брифа без стража); (f) K3: если зелёный — [T] не различает `True` и int.
