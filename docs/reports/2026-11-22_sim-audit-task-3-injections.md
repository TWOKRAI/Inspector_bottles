# Task 3 · прогон матрицы инъекций I1…I17 · 2026-11-22

Исполнитель: junior (механический прогон). Worktree `/Users/twokrai/Project_code/Inspector_bottles--lane-sim-audit-inj`, detached, коммит `46c889780`. Код под инъекцией: `scripts/wire_audit/core.py`. Патчи и предсказания — `docs/reports/2026-11-22_sim-audit-task-3-injections-predictions.md`.

Наборы: приёмочный `scripts/wire_audit/tests/test_wire_audit_acceptance.py` (108 тестов), авторский `scripts/wire_audit/tests/test_wire_audit.py` (29 тестов). Всего 137.

Гейт: `machine_gate.sh light simaudit-inspector-bottles-ee` работает, код выхода pytest проходит через гейт (0 — зелёно, 1 — красно). Окно не запрашивалось.

Резервная копия: `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/1928333a-5886-44dd-b6c4-509adeb53f05/scratchpad/inj/core.py.orig`. После каждой инъекции файл восстанавливался `cp`, `diff` был пуст.

## Базовый прогон (без инъекции)

`light simaudit-inspector-bottles-ee … pytest -q --tb=no … (2 файла)` -> `137 passed, 1 warning in 7.30s`, EXIT=0.

## Таблица итога

Колонка «совпало»: да — множество красных совпало с предсказанием; нет — указано, чем отличается (лишние красные — `+`, недостающие — `−`).

| ID | применился | failed | имена упавших | совпало с предсказанием |
|---|---|---|---|---|
| I1 | да | 2 | `acceptance::test_b_args7_off_by_one_quantum_fails[1]`, `[-1]` | да |
| I2 | да | 0 | — (выживший) | нет: `−` авторские тесты с R между CMD_SEQ и CMD_FLAG |
| I3 | да | 2 | `acceptance::test_k_deleted_job_does_not_steal_next_fill_job`; `test_wire_audit.py::test_word_change_cuts_fills_and_upper_bound_stops_theft_of_next_fill_job` | да |
| I4 | да | 77 | `test_a_one_pick_one_job_correct_words_pass` и ещё 76 (полный список в `inj/I4.log`); в т.ч. Реальные (`test_run1_real_files_*`) | да по нижней границе: предсказано «≥ 30», факт 77 |
| I5 | да | 0 | — (выживший) | нет: `−` Реальные 3 (угол 281,5) и `(в)` для 281,5 |
| I6 | да | 1 | `acceptance::test_g_two_jobs_with_same_cmd_seq_fail_as_duplicate` | нет: `−` авторский тест «дубль seq» |
| I7 | да | 2 | `acceptance::test_d_job_without_reply_fails_and_neighbour_reply_is_not_borrowed`; `test_wire_audit.py::test_reply_before_command_flag_is_not_the_answer` | нет: `+` авторский `test_reply_before_command_flag_is_not_the_answer` |
| I8 | да | 3 | `acceptance::test_d_second_reply_with_other_status_or_errno_is_contradictory[other-status]`, `[other-errno]`; `test_wire_audit.py::test_late_reply_with_other_errno_is_contradictory_on_the_right_job_only` | нет: `+` авторский `test_late_reply_with_other_errno_is_contradictory_on_the_right_job_only` |
| I9 | да | 5 | `acceptance::test_r_far_cell_at_zone_500_is_pass_tilde_with_one_warning[0]`, `[8]`; `test_r_zone_default_is_500`; `test_r_zone_threshold_is_hypot_544_06[544-1]`; `test_run1_real_files_zone_500_warns_about_far_cells_but_passes` | нет: `+` `test_r_zone_default_is_500`, `test_run1_real_files_zone_500_warns_about_far_cells_but_passes`; `−` граница 545 (`[545-0]`) не красная. Реальный прогон с 600 не красный, как предсказано |
| I10 | да | 3 | `acceptance::test_z_only_last_incarnation_is_judged_old_one_broken`, `test_z_only_last_incarnation_is_judged_new_one_broken`; `test_wire_audit.py::test_two_incarnations_only_last_is_judged_in_both_logs` | да |
| I11 | да | 4 | `acceptance::test_l_retry_after_refusal_passes_and_counts_one_retry`, `acceptance::test_p_refused_job_is_not_compared_with_sim`; `test_wire_audit.py::test_busy_retry_chain_two_refusals_then_accept_is_two_retries_and_pass`, `test_busy_retry_reusing_the_same_seq_is_not_a_duplicate` | нет: `+` `acceptance::test_p_refused_job_is_not_compared_with_sim` |
| I12 | да | 1 | `acceptance::test_o_sign_flip_on_nine_disks_fails_zero_shift_or_sign` | да |
| I13 | да | 2 | `acceptance::test_pick_words_must_match_layout_line_transfer[4604-False]`, `[4612-False]` | да |
| I14 | да | 1 | `acceptance::test_flags_word_other_than_3_fails` | да |
| I15 | да | 1 | `acceptance::test_column_a_tolerance_is_one_quantum_wide[6-3202-x-False]` | да |
| I16 | да | 4 | `acceptance::test_alpha_window_on_pick_words_boundaries[2-4548-окно-False]`, `[2-4616-окно-False]`, `[3-62095-окно-False]`, `[3-62117-окно-False]` | да |
| I17 | да | 3 | `acceptance::test_z_only_last_incarnation_is_judged_old_one_broken`, `..._new_one_broken`; `test_wire_audit.py::test_two_incarnations_only_last_is_judged_in_both_logs` | да |

Полные строки `FAILED …` для каждой инъекции: `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/1928333a-5886-44dd-b6c4-509adeb53f05/scratchpad/inj/I<N>.log`.

## Выжившие мутанты (failed = 0)

- **I2** (`job.flag_pos < p < limit` → `job.seq_pos < p < limit`): 137 passed. Предсказанные авторские тесты про R между CMD_SEQ и CMD_FLAG не покраснели.
- **I5** (убран `wrap180` в доворот): 137 passed. Предсказанные Реальные 3 и случай (в) для 281,5 не покраснели.

Итого выжило 2 из 17. Выжившие — это результат прогона; оценки здесь нет.

## Совпадение по числу инъекций

- Полностью совпали с предсказанием: I1, I3, I4 (по нижней границе), I10, I12, I13, I14, I15, I16, I17 — 10 из 17.
- Расхождения: I2, I5 (выжившие, недостающие красные); I6 (недостающий авторский); I7, I8, I11 (лишний авторский или приёмочный); I9 (лишние красные и 545 не красная).

## What I left open / unreliable

- Предсказание I4 записано как «≥ 30», не как точное множество; сравнение только по нижней границе.
- Число 137 взято из вывода pytest, а не из `grep -c`. Это надёжно для набора, но не проверено отдельно по файлам сверх вывода гейта.
- Не разбирал, почему I2 и I5 выжили и правы ли предсказания. Это решает лид.
- Строка `FAILED` для ID с параметризацией приведена с кодировкой имени (`окно` = «окно»), полные строки в логах.
- Условие «код 1 при нуле заданий» не включено (по примечанию лида).

## Разбор лида (после прогона)

- Совпали с предсказанием полностью 10 из 17 (I1, I3, I4, I10, I12–I17); остальные — расхождения, каждое разобрано, предсказания не правились.
- **I5 выжил — эквивалентный мутант по спецификации.** DESIGN п.8 требует сравнивать углы как `wrap180(Δ)`; без `wrap180` в ожидаемом доворте строка «М 281,5°» даёт ожидание −381,5° против слова −21,5° (разница ровно 360°) и всё равно PASS (воспроизведено вручную на копии: `| 40 | 1 | М | 281.5 | 4 | 320.0 | 0.0 | -21.5 | … | PASS |`). Моё предсказание «Реальные 3 краснеют» было неверным. Следствие: сдвиг на 360° в слове `ARGS[9]` аудит не отличает от верного (физически та же ориентация; драйвер всегда нормализует доворот). В «Открыто» отчёта.
- **I2 выжил — пробел тестов.** Закрыт тестом автора `test_stale_reply_between_cmd_seq_and_cmd_flag_is_not_an_answer_nor_a_contradiction`; на мутации красный (1 failed), на коде зелёный.
- Лишние красные сверх предсказания (I7, I8, I9, I11) и предсказанные-но-не-красные авторские тесты (I6: авторский «дубль seq» не красный, ловит приёмочный; I9: граница 545 зелёная) — на гарантии не влияют.
