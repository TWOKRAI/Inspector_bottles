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

# Результат прогона (haiku-агент, gsi @ 0c7a96b7f; сырой вывод — `injections-run.md`)

База: collected 246, passed 246, 0 красных. Каждая мутация: collected 246 (guard «не собрали» не сработал).
Сверка: `✓` — все предсказанные имена красные; «+N» — красных больше предсказанного.

| # | красных | предсказание | сверка |
|---|---|---|---|
| а | 5 | stranger[*] оба параметра | ✗ в части: красный только `foreign_window_s3_has_nothing`; +4 (cancel×2, mv_calls[release_refused], fast_paths[release_refused]) |
| б | 4 | fifo, promotes_first_waiting | ✓ +2 (position_counts_own_line_after_promote, term_after_own_mv — оба зависят от «первая waiting») |
| в | 13 | stale_read, fresh_foreign×5, hazards killed-holder | ✓ +6 (parallel, tmp_younger_60, tmp_wait_zero, busy_tmp_released, hazards three_parallel, request_during_release) |
| г1 | 3 | merge_begin_refused «слот занят» | ✓ +1 (fast_paths[merge_begin_refused]) |
| г2 | 2 | merge_begin_refused «открыт quiet» | ✓ точно (quiet, own_quiet) |
| д | 9 | bad_merging[two_fields] | ✓ +8: патч д ослабил число полей до «≥2» и подставил `since` по умолчанию — краснеют four_fields, line_number_counts_stand и malformed_lock[merging_2_fields-*] ×6 |
| е | 3 | extend_by_stranger | ✓ +2 (mv_calls[extend_refused], fast_paths[extend_refused]) |
| ж | 10 | busy_tmp_until_released | ✓ +9 (подмножество в) |
| з | 46 | promote_takes_minutes (N≠30), release_hands_window | ✓ +много: `request` выдаёт окно через `promote`, поэтому краснеют все тесты выдачи после `request` |
| и | 9 | overdue/extend decimal_*, 0809, status_octal | ✓ +2 (wait_prints_overdue[one_minute_over], [plus_659_left]) |
| к | 18 | wait_promotes, running_wait_promotes | ✓ +16 (все тесты, где окно выдаёт `wait`) |
| л | 2 | release_of_queued... | ✓ +1 (cancel_removes_all_own_waiting_lines) |
| м1 | 8 | fresh_foreign×5 | ✓ +3 (tmp_younger_60, tmp_wait_zero, hazards killed-holder) |
| м2 | 1 | term_after_own_mv | ✓ точно |
| н | 12 | request_prints_result_only_after_mv | ✓ +11 (отказ печатает до mv: parallel, stale_read, mv_busy_forever, fresh_foreign×5, hazards×3) |
| о | 12 | tmp_younger_than_60 | ✓ +11 (набор как у в: без реального возраста tmp реклеймится свежий) |
| п | 1 | close_does_not_promote | ✓ точно |

Находки сверки (все — про предсказания, не про дыры в тестах):
1. (а) Предсказание «оба параметра» ошибочно: второй параметр (`no_window_s3_has_nothing`) не заходит в мутированную ветку — окна нет, отказ идёт другим путём. Тест держит свойство через первый параметр; второй — отдельная проверка отказа.
2. Предсказания по именам занижали охват в 14 из 17 мутаций (+2…+45 красных): я перечислял «главный» тест, а побочные (mv_calls, fast_paths, зависимые от выдачи) не учёл. Ни одна мутация не дала 0 красных и ни одно предсказанное имя не осталось зелёным (кроме п. 1).
3. Мутация д была шире описанной (≥2 полей + дефолт `since`), поэтому покрыла и четыре поля; чистую «2 поля принимается» отдельно не ставили — свойство «ровно 3 поля» держат three/four/two_fields вместе.
4. Не ловится и известно (см. выше): «now читается один раз до tmp», реальный дедлайн `wait --timeout N>0`, гонка двух реклеймеров.
5. Операционное: прогон к — 288 с при таймауте Bash 300 с; в следующий раз ставить таймаут 600 с или резать запуск на два файла.
