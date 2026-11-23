# Task A — предсказания break-injection (лид, ДО прогона)

Код: `feat/alpha-hard-split` на `4115ad9b9`. Наборы: приёмочный `test_alpha_split_acceptance.py` (слепой tester, 89) и существующие
`scripts/alpha_sim/tests` (123) + `Plugins/processing/word_layout/tests/test_p3_disk_journal.py`. Каждая инъекция ломает ОДНУ гарантию на
закоммиченном коде; после прогона файл откатывается копией. Ожидаемый красный набор записан до запуска; несовпадение — находка.
Имена — функции `test_…` из приёмочного файла (префикс `test_alpha_split_acceptance.py::`) и существующие тесты по имени.

| № | Инъекция (одна поломка) | Ожидаемо КРАСНЫЕ (полный набор по приёмочному; «+ex» — существующие) | Ожидаемо ЗЕЛЁНЫЕ (контроль) |
|---|---|---|---|
| I1 | `judge_case`: игнорировать `prev_filled` (ожидаемая `word_line` всегда литерал) | `a1_d_line_with_filled_8_passes_when_prev_filled_8`, `a1_k9_with_prev_filled_8_fails`, `a1_run_expected_d_line_carries_register_value_at_start_of_d_not_snapshot_after_b`, `a1_run_c_gets_prev_filled_from_d_register`; + ex `test_g14_lost_disk_in_b_does_not_hide_d_and_c` | `a1_none_means_literal_as_today`, `a1_case_b_ignores_prev_filled`, `a1_run_without_flip_literal_still_passes_control`, `a1_other_word_change_fails_for_any_prev_filled` |
| I2 | раннер берёт `prev_filled` из регистров ПОСЛЕ случая (не перед) | `a1_run_expected_d_line_carries_register_value_at_start_of_d_not_snapshot_after_b`; других нет | все `judge_case`-тесты A1; `a1_run_without_flip…`; `a1_run_missing_or_non_int_register_falls_back_to_literal`; существующие |
| I3 | `_unrecognized`: не считать пропуск «ниже порога» непризнанным | `a2_unrecognized_last_disc_below_threshold_is_accuracy_with_cascade_checks`, `a2_run_unrecognized_last_disc_of_b_block_and_exit_code` | A3-тесты (`hard_reasons` независима); `a2_unrecognized_by_letter_key_and_by_feed_key` |
| I4 | `_check_klass`, `jobs.count`: допуск `<= u` → `<= u + 1` | `a2_checks_off_by_two_with_one_unrecognized_are_mechanism`; и `a2_checks_are_mechanism_when_nothing_unrecognized`, если расхождение `jobs.count` в нём равно 1 (при `u = 0` допуск `u + 1` его пропустит; если в тесте расхождение ≥ 2 — зелёный) | остальные |
| I5 | `_check_klass`: `u` принудительно 0 (каскад проверок отключён) | `a2_unrecognized_last_disc_below_threshold_is_accuracy_with_cascade_checks`, `a2_jobs_emitted_uses_growth_over_before`, `a2_run_unrecognized_last_disc_of_b_block_and_exit_code`, `a2_run_lost_disc_in_middle_of_d_cascades_to_accuracy` | `a2_checks_are_mechanism_when_nothing_unrecognized`, `a2_checks_off_by_two…`, `a2_lines_count…` |
| I6 | `_disc_klass`: убрать условие `n == n_exp` каскада `progress` | `a2_progress_cascade_requires_equal_n`; других нет | остальные `a2_progress_*` |
| I7 | `_disc_klass`: каскад `progress` без ограничения `u_before` (любой `|k−k_exp|`) | `a2_progress_off_by_one_without_unrecognized_before_is_mechanism`, `a2_progress_cascade_limited_by_unrecognized_before` | `a2_progress_cascade_requires_equal_n`, `a2_run_lost_disc_in_middle_of_d_cascades_to_accuracy` |
| I8 | `judge_case`: `reliable = True` всегда | `a2_unreliable_alignment_all_mechanism_no_u_no_hard` | остальные |
| I9 | `hard_reasons`: `>` → `>=` для `angle` | `a3_angle_boundary_is_strict_and_rounded_to_tenth`, `a3_run_angle_reason_threshold_flag_and_boundary` | `a3_angle_over_threshold_is_hard_and_threshold_is_a_parameter` |
| I10 | `hard_reasons`: убрать ранний возврат `no_prediction` | `a3_no_prediction_skips_class_and_angle_reasons`, `a3_run_no_prediction_record` | прочие a3 |
| I11 | `_delta_deg`: убрать `wrap180` (сырая разность) | `a3_angle_difference_wraps_around_360`; прочие a3 зелёные (проверяем: пример B#12 даёт −174,2 и без обёртки) | прочие |
| I12 | `_delta_deg`: убрать округление до 0,1° | `a3_angle_boundary_is_strict_and_rounded_to_tenth`; других нет | прочие |
| I13 | `finish()`: печатать блок A2 ПОСЛЕ строки `итог:` | все `a2_run_*`, печатающие блок (≥ 10 тестов), `a3_run_write_error_prints_line_before_a2_and_keeps_exit_code`; + ex: тесты `lines[-1] == итог` (`runner:668,716`, `hazards:274,303,358,708,794`) | `judge_case`-тесты, A1, A3-логика |
| I14 | `mark()`: не ставить метку `прервано` при Ctrl-C | `a2_run_ctrl_c_in_case_is_interrupted_label`; других нет | остальные метки |
| I15 | `runner_check_klass`: `feed` всегда МЕХАНИЗМ | хотя бы один из `a2_run_unrecognized_last_disc_of_b_block_and_exit_code`, `a2_run_lost_disc_in_middle_of_d_cascades_to_accuracy` (если ни один не краснеет — находка: класс `feed` при U≥1 не покрыт) | A3, A1 |
| I16 | `exit_code`/`finish()`: код 0, когда FAIL только класса ТОЧНОСТЬ | `a2_run_unrecognized_last_disc_of_b_block_and_exit_code`; + ex: ни один (в существующих FAIL — механизм) | остальные |
| I17 | `judge_case`: писать запись `hard` и для диска без строки журнала | `a3_run_disc_without_journal_line_is_not_in_file_pair`, `a2_missing_line_is_mechanism_and_not_hard_and_not_unrecognized` | прочие |
| I18 | `--hard-out ""` считать заданным путём | `a3_run_empty_flag_value_means_not_set` | прочие |
| I19 | `write_hard_out` вызывать из `_end` (после `finish()`), не внутри `finish()` | `a3_run_file_created_on_p0_failure`, `a3_run_write_error_prints_line_before_a2_and_keeps_exit_code` | `a3_run_file_created_on_ctrl_c`, `a3_run_file_created_on_precondition_in_p1` (`_end` их тоже вызывает) |
| I20 | `_finish_case`: потерять `unrecognized`/`hard` (пересобрать `CaseResult` без них) | все `a2_run_*` с классом ТОЧНОСТЬ в каскаде, все `a3_run_*` с непустым файлом | `judge_case`-тесты |

Правило чтения: красный сверх набора или зелёный внутри набора — находка (сначала диагноз: тест слаб или инъекция задела больше, чем задумано).
После последней инъекции — полный набор зелёный на откате (212 passed) и `git diff --stat` пуст.
