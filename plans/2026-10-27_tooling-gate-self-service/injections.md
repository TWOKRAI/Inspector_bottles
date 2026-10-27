# Матрица инъекций — предсказания (записаны ДО прогона, база 0c7a96b7f)

База: слепой файл `test_machine_gate_self_service.py` (241) + hazards `test_machine_gate_self_service_hazards.py` (5) —
зелёные. Каждая мутация применяется к `scripts/machine_gate.sh` по одной, после прогона `git checkout -- scripts/machine_gate.sh`.
Прогон: оба файла целиком, `collected` числом на базе и на каждой мутации (guard против «0 красных, потому что не собрали»).
Предсказание = поимённый набор, который ДОЛЖЕН покраснеть; всё остальное должно остаться зелёным. Расхождение — находка.

| # | Мутация | Должны покраснеть |
|---|---|---|
| а | `release`: снимает окно без проверки владельца (ветка «чужое окно → отказ» удалена; остаётся снятие любого `window:`) | `test_release_by_stranger_is_refused_and_keeps_everything[*]` (оба параметра) |
| б | FIFO: `promote` берёт ПОСЛЕДНЮЮ `waiting:` | `test_queue_is_fifo_on_release`, `test_request_promotes_first_waiting_by_order_when_no_window` |
| в | `lock_commit`: захват tmp без `set -C` (O_EXCL убран, `: >tmp` всегда успешен) | `test_stale_read_is_not_written_back`, `test_fresh_foreign_tmp_is_waited_for_then_refused_and_kept[*]` (все 5 писателей); hazards: тест «свежий tmp убитого держателя даёт отказ» |
| г1 | `merge-begin`: проверка занятого слота удалена | `test_merge_begin_refused[*]` — параметры «слот занят» |
| г2 | `merge-begin`: проверка `quiet`-окна удалена | `test_merge_begin_refused[*]` — параметры «открыт quiet» |
| д | `validate_lock`: `merging:` с 2 полями принимается | `test_bad_merging_line_is_malformed[two_fields]` (и только родственные по полям) |
| е | `extend`: проверка владельца удалена | `test_extend_by_stranger_is_refused` |
| ж | ожидание занятого tmp заменено мгновенным отказом | `test_request_waits_for_busy_tmp_until_it_is_released` |
| з | `promote`: N жёстко 30 | `test_promote_takes_minutes_from_fourth_field[*]` (все, где N ≠ 30), `test_release_hands_window_to_next_in_queue` |
| и | остаток окна без `10#` | `test_status_overdue_survives_octal_looking_digits`, `test_wait_prints_overdue_for_foreign_window[decimal_*]`, `test_extend_moves_until[decimal_*]`, `test_request_at_0809_uses_decimal_arithmetic` |
| к | `wait`: `promote` удалён | `test_wait_promotes_when_no_window`, `test_running_wait_promotes_itself_after_close` |
| л | `release` своей заявки снимает и чужое окно | `test_release_of_queued_request_cancels_it_and_keeps_foreign_window` |
| м1 | `trap` без флага владения (проигравший удаляет tmp победителя) | `test_fresh_foreign_tmp_is_waited_for_then_refused_and_kept[*]` |
| м2 | `trap` не снимается после своего `mv` | `test_term_after_own_mv_does_not_remove_foreign_tmp` |
| н | stdout печатается до `mv` | `test_request_prints_result_only_after_mv` |
| о | возраст tmp считается от `MACHINE_GATE_NOW_EPOCH`, не от реальных часов | `test_tmp_younger_than_60_seconds_is_not_reclaimed` (подмена now далеко вперёд → свежий tmp реклеймится) |
| п | `close`/`grant` вызывает `promote` | `test_close_does_not_promote` |

Не ловится и это известно: «`now` читается один раз до tmp» (тест через slow-date план отверг); реальный дедлайн
`wait --timeout N>0`; остаточная гонка двух реклеймеров. Для этих свойств мутации в матрице нет.
