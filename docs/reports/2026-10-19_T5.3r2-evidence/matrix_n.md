# T5.3 круг 2 — матрица инъекций n1..n27, a-I8p, a-I16p

Дерево: worktree robot-v2-t53r2-inj, HEAD a543f6dba (после переноса). Каждая строка: одна инъекция, прогон набора, откат (`git status --porcelain` пуст после каждой строки, `REVERT status: []`).
Базы (без инъекции, все зелёные): HA 47 passed; HAS 55 passed; SC 24 passed; SCAH 71 passed.
Логи: `<scratchpad>/inj/<row>.log`, диффы: `<scratchpad>/inj/<row>.diff`.
Патчи: `<scratchpad>/inj/patches_n.py` (подключён из `patches.py`).

Колонка "collected" = число прогнанных тестов набора (passed + failed) из строки SUMMARY.

| row | change | set | collected | failed names | predicted | match |
|---|---|---|---|---|---|---|
| BASE-HA | без инъекции | HA | 47 | — | зелёный | base |
| BASE-HAS | без инъекции | HAS | 55 | — | зелёный | base |
| BASE-SC | без инъекции | SC | 24 | — | зелёный | base |
| BASE-SCAH | без инъекции | SCAH | 71 | — | зелёный | base |
| n1 | защёлка выключена: два условия `if False` / `elif False` в `_process_stop` | HA | 47 | — (green) | H: one_silent; T:A1, T:A3, T:A4 | no |
| n2 | повтор и после успешной записи (убран `return` в цикле `_process_stop`) | HA | 47 | 16: T:A1 jog/program, T:A2, T:A2b, T:A3, T:A4; H: one_silent, silent_r1_does_not_delay_r2, operator_robot_stop_writes_after_latch, spawn_failure[closed/generic], rehold_after_failed_release, job_in_motion x2, echo_check_bounded, echo_reads_stop_at_budget | как n1 (red) | yes (red; часть имён не была в прогнозе) |
| n3 | повтора нет (`attempt > 1`) | HA | 47 | T:A6 first_write_fails_exactly_one_retry; H: failed_write_retried_exactly_once | H: failed_write_retried_exactly_once; T:A6 | yes |
| n4 | повтор без счётчика, до срока (`time.monotonic() > deadline`) | HA | 47 | T:A2b shutdown_within_budget, T:A2b write_counts; H: jog_lock_held_stop_written_without_lock, jog_cont_in_flight_during_lockless_stop | H: failed_write_retried_exactly_once (>2); T:A6 | no (предсказанные имена не красные) |
| n5 | фаза 1 последовательно в одном потоке (`if True:` в request_stop_all) | HA | 47 | T:A2 second_robot_stop_is_not_held_behind_first; T:A2b second_robot_write_arrives_within_gap; H: silent_r1_does_not_delay_r2 | H: silent_r1; T:A2b; T:A2a зелёный | partial (A2a красный вопреки прогнозу) |
| n6 | partial-injection: в `_write_stop` после `issue_stop` добавлено ожидание эха (`await_stop_echo`), вместо `stop()` | HA | 47 | H: job_in_motion[silent], echo_reads_stop_at_budget_boundary | H: one_silent (время > 2.5); T:A1; T:A3 | no |
| n7 | срок общий заменён на `scope.close(budget_s=2.5)` в plugin.shutdown | HA | 47 | — (green) | T:A2b (сомнительный) | no |
| n8 | не писать last_error при неподтверждённом эхе (`_publish_error` → pass) | HA | 47 | H: missing_echo_sets_last_error | H: missing_echo_sets_last_error | yes |
| n9 | partial-injection: без spawn драйвер сам стартует поток (`threading.Thread`) вместо RuntimeError | HAS | 55 | H: driver_without_spawn_refuses_threaded_ops; H: driver_without_spawn_refuses_return_job...; SC: test_spawnless_driver_keeps_working | H: driver_without_spawn_refuses_threaded_ops; REDS 5 | yes |
| n10 | фабрика delta_v2 без RuntimeError (`if False:` в manager) | HAS | 55 | SC: test_spawnless_driver_keeps_working | REDS 5 часть «фабрика» | partial (имя из SC, не из HA/HAS-гигиены) |
| n11 | partial-injection: не перехватывать ScopeClosedError (`except ZeroDivisionError` вместо `except Exception`) | HA | 47 | H: second_request_stop_all_after_scope_close_does_not_raise; H: spawn_failure[closed], [generic] | H: second_request_stop_all_after_scope_close_does_not_raise | yes |
| n12 | `_jog_tx_lock.acquire()` без срока в request_stop | HA | 47 | H: jog_lock_held_stop_written_without_lock; H: jog_cont_in_flight...; H: spawn_failure[generic] | H: jog_lock_held_stop_written_without_lock | yes |
| n13 | оператор abort через защёлку (`_stop_latched(mode)` вместо `_stop_and_wait`) | HA | 47 | H: abort_rejects_bad_level_with_constant_text (не прогнозирован) | H: operator_robot_stop_writes_after_latch | no |
| n14 | стоящий робот получает стоп (уровень HARD всегда) | HA | 47 | T:A5 idle_robot_gets_no_stop_write; H: second_request_stop_all_after_scope_close | T:A5 | yes |
| n15 | fail-closed при отказе spawn убран (`for ... in []`) | HA | 47 | H: spawn_failure[closed], [generic] | H: spawn_failure_still_writes_one_stop_per_moving_robot | yes |
| n15b | вернуть `break` при отказе spawn | HA | 47 | H: spawn_failure[closed], [generic] | H: spawn_failure (если покрывает закрытую область) | yes |
| n16 | H-A: не сбрасывать защёлку после записи JOG_CONT | HA | 47 | — (green) | H: rehold_after_failed_release_stop_then_process_stop_writes | no |
| n17 | H-B: убрана проверка `stopping` после JOG_CONT | HA | 47 | H: jog_cont_in_flight_during_lockless_stop_gets_its_own_stop | H: то же | yes |
| n18 | повтор без проверки срока (`attempt > 2`) | HA | 47 | T:A2b peer_reply_held_shutdown_within_budget; T:A2b write_counts_one_retry | T:A2b счёт r1; и/или T:A7 | yes |
| n19 | второй request_stop_all без срока берёт новый срок | HA | 47 | — (green) | T:A1/A3 счёт (сомнительный; если защёлка держит — зелёный) | partial (зелёный — ожидаемая ветка условного прогноза) |
| n20 | on_progress повтор через `_stop_and_wait` (ждёт эха) | HA | 47 | — (green) | T:A1 программа время > 2.5 (сомнительный) | partial (сомнительный прогноз, зелёный) |
| n21 | ветка _JobStopped пишет стоп мимо защёлки (`_write_stop`) | HA | 47 | H: job_in_motion[confirms], [silent]; H: spawn_failure[generic] | H: job_in_motion_process_stop_one_write_tick_exits_fast (2 записи) | yes |
| n22 | return_job без отказа при отсутствии spawn | HAS | 55 | H: driver_without_spawn_refuses_return_job_and_tick_keeps_it_visible | H: то же | yes |
| n23 | не звать health.report_error на stop_echo (plugin) | HA | 47 | H: one_silent_robot_one_stop_write_within_deadline | H: missing_echo_sets_last_error (если проверяет health) | no (предсказанный тест зелёный) |
| n24 | partial-injection: `elif True:` в разборе уровня abort (без белого списка) | HA | 47 | H: abort_rejects_bad_level_with_constant_text | H: abort_rejects_bad_level_with_constant_text | yes |
| n25 | не сбрасывать `_latch_value` на поколение (H6) | HA | 47 | H: echo_check_ignores_stop_of_previous_session | H: то же | yes |
| n26 | чтение эха без проверки остатка срока; await с deadline+60 s | HA | 47 | T:A1 shutdown_within_budget x2; T:A2 shutdown; T:A3 shutdown; H: one_silent; H: missing_echo_sets_last_error; H: job_in_motion[silent]; H: echo_reads_stop_at_budget_boundary | H: echo_check_bounded_when_peer_read_is_held (> 2.5 с) | partial (предсказанный тест зелёный; красные — другие имена) |
| n27 | partial-injection: фаза 4 повторно читает эхо (`_echo_checked=None`, deadline+60 s) в disconnect | HA | 47 | T:A1 shutdown x2; T:A2 shutdown; T:A3 shutdown; H: one_silent; H: echo_check_bounded_when_peer_read_is_held; H: echo_reads_stop_at_budget_boundary | H: echo_check_bounded_when_peer_read_is_held; T:A3 время | yes |
| a-I8p | итог публикуется после блока `_flags_lock` (вне замка) | SC | 24 | S: test_s3_final_program_state_published_before_busy_cleared | S3 | yes |
| a-I16p | `_SHUTDOWN_BUDGET_S = 7.5` | SCAH | 71 | S: test_s9_survivor_visible; T:A1 x2, T:A2, T:A2b x2, T:A3; H: one_silent; H: echo_reads_stop_at_budget_boundary | S9 «плагин» (plugin part) | yes (S9 красный; плюс красные HA shutdown-тесты) |

Счёт по классам (30 инъекционных строк): yes 18 (n2, n3, n8, n9, n11, n12, n14, n15, n15b, n17, n18, n21, n22, n24, n25, n27, a-I8p, a-I16p); partial 5 (n5, n10, n19, n20, n26); no 7 (n1, n4, n6, n7, n13, n16, n23); not applied 0.

Partial-injection (приближения, прогоняются как есть): n6, n9, n11, n24, n27 (по просьбе лида); также n26 (await с deadline+60 s) и n4/n13/n23 — иначе не применялись (только форма, без смены смысла).
