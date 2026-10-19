# T5.3 round 2 — последние 8 строк инъекций (HEAD 630e158ec, worktree robot-v2-t53r2-inj)

Прогон: run_row.sh ROW SET, один прогон на строку, без повторов. Инъекции временные, после каждой откат через git show HEAD.
Якоря patches_final для n1/n13/n21/n28/a-I28pp совпали с HEAD по одному разу, правок якорей не потребовалось.

| row | change | set | collected | failed names | predicted | match |
|---|---|---|---|---|---|---|
| BASE-HA-last | без инъекции | HA | 56 | — (56 passed) | зелёный | yes |
| BASE-SC-last | без инъекции | SC | 24 | — (24 passed) | зелёный | yes |
| n1-last | защёлка `if False:` и `elif False:` | HA | 56 | 12: a1_jog, a1_program, a2_peer_unconfirmed, a4_both_confirm, a5_idle, hazards: second_request_stop_all_after_scope_close, second_process_stop_while_motion_alive, plugin_shutdown_scope_closed_spawn, plugin_shutdown_two_idle, idle_robot_disconnect_after_process_stop, idle_robot_shutdown_after_operator_stop, shutdown_after_jog_release_long_ago | test_second_process_stop_while_motion_alive_writes_once (+ plan: one_silent, T:A1, T:A3, T:A4) | partial (predicted красный; 11 лишних, plan-список не покраснел) |
| n13-last | abort: `_stop_and_wait` -> `_stop_latched(mode)` | HA | 56 | 2: test_operator_robot_stop_writes_after_latch, test_abort_rejects_bad_level_with_constant_text | test_operator_robot_stop_writes_after_latch | partial (предсказанный красный; 1 лишний) |
| n21-last | abort через защёлку -> `_write_stop` мимо защёлки | HA | 56 | 2: test_job_in_motion_process_stop_one_write_tick_exits_fast[confirms], [silent] | test_job_in_motion_process_stop_one_write_tick_exits_fast | yes |
| n28-last | повтор on_progress: `if False:` | HA | 56 | 1: test_program_stop_after_g0_then_progress_does_not_repeat_stop | то же | yes |
| a-I28pp-last | повтор on_progress не срабатывает (`level = 0`) | SC | 24 | 1: test_s16_stop_between_stopping_check_and_run_chunks_still_aborts (test_robot_v2_scope.py) | S16 | yes |
| n29-last | `_latch_reset_locked()` на каждом request_stop (`if not self._shutdown:` -> `if True:`) | HA | 56 | 18: acceptance a1_jog, a1_program, a2, a2b (x2), a3, a4, a5; hazards one_silent_robot_one_stop_write_within_deadline, second_request_stop_all_after_scope_close, echo_check_bounded_when_peer_read_is_held, echo_reads_stop_at_budget_boundary, second_process_stop_while_motion_alive, plugin_shutdown_scope_closed_spawn, plugin_shutdown_two_idle, idle_robot_disconnect_after_process_stop, idle_robot_shutdown_after_operator_stop, shutdown_after_jog_release_long_ago | second_request_stop_all_after_scope_close; idle_robot_disconnect_after_process_stop; one_silent_robot_one_stop_write_within_deadline | partial (3 из 3 предсказанных красные; 15 лишних) |
| n30-last | оба сброса поколения на выключении убраны (request_stop и disconnect) | HA | 56 | 2: test_idle_robot_shutdown_after_operator_stop_still_writes, test_shutdown_after_jog_release_long_ago_writes_one_stop | то же два теста | yes |
| n31-last | `_process_stop` elif простого робота `level = 0`; ветка простого SOFT в `_request_stop` `if False:` | HA | 56 | 7: test_a5_idle_robot_gets_one_soft_stop_write, test_plugin_shutdown_two_idle_robots_one_soft_write_each, test_individual_disconnect_stops_only_that_idle_robot, plus hazards: second_request_stop_all_after_scope_close, idle_robot_disconnect_after_process_stop, idle_robot_shutdown_after_operator_stop, shutdown_after_jog_release_long_ago | T:A5 test_a5_idle_robot_gets_one_soft_stop_write, test_plugin_shutdown_two_idle_robots_one_soft_write_each, test_individual_disconnect_stops_only_that_idle_robot | partial (3 из 3 предсказанных красные; 4 лишних) |

## Что осталось открытым / ненадёжно
- Прогон один на строку; тесты на сроках (echo_check_bounded, echo_reads_stop_at_budget_boundary в n29) могут быть временными, повтор не делался.
- Лишние красные в n29/n31 (и n1) — не из прогноза; предсказания в задании узкие, это расхождение, а не проверка.
- Числа collected (56 HA, 24 SC) на 630e158ec; в matrix_final (8e20f67f0) HA был 51, сравнивать напрямую нельзя.
- Откат через git show пишет LF; git warning «LF will be replaced by CRLF» — ожидаемо, git status после каждого отката пуст.
- n29 заменил условие на `if True:`, n30 заменил сброс на `pass` (блоки сохранены), n31 трактовал «ветку простого SOFT в disconnect» как `_request_stop`, где стоит `if not (job_active or stop_jog or prog_alive) and self.is_connected:`.
