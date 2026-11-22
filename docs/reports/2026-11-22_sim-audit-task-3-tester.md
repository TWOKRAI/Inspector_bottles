# Task 3 — отчёт слепого tester (RED)

Parsed: MODE=red (слепой, один раз), INTERFACE=none, MODULE_CONTRACT=n/a, TASK=3, PLAN=нет (спецификация — `docs/reports/sim-audit/tasks/3.md`). Worktree `Inspector_bottles--lane-sim-audit-tester`, коммит a35fe4e18, ничего не закоммичено.

Файл тестов: `scripts/wire_audit/tests/test_wire_audit_acceptance.py` (108 тестов с учётом параметризации). Тесты ходят только через CLI (`sys.executable -m scripts.wire_audit`, cwd = корень, `PYTHONPATH` = корень, таймаут вызова 60 с, при таймауте `pytest.fail`). Читал только текст задачи и три фикстуры `scripts/wire_audit/tests/fixtures/`. Запретные пути (`scripts/alpha_sim/`, предсказания, опись, ревью r1, `3b.md`, `Services/`, `Plugins/`, `multiprocess_*`) не открывал.

## Тесты и пункты текста

| тест (имя, группа) | пункт текста |
|---|---|
| `test_a_one_pick_one_job_correct_words_pass`; `test_a_example_row_has_columns_from_p13`; `test_table_header_is_exact`; `test_a_ecap_column_...` (18178/1 -> 83714, 65297/0, 2041/1 -> 67577) | (а), п.5, п.13 (пример строки, заголовок) |
| `test_header_marks_word_as_not_independent_without_words`, `test_header_has_no_dependence_note_with_words`, `test_header_prints_word_p_pick_and_zone_limit` | п.9, п.13 (шапка) |
| `test_p_pick_rz_defaults_to_minus_100_when_absent`, `test_expectations_come_from_registers_not_from_defaults`, `test_pitch_falls_back_to_twice_disk_radius_when_pitch_mm_zero`, `test_expectations_do_not_come_from_place_fields_of_the_layout_line` | п.8 (регистры, pitch = 2·radius, не из полей `положить`) |
| `test_out_option_writes_report_file` | п.13/CLI `--out` |
| `test_b_args7_off_by_one_quantum_fails[+1,-1]` | (б), п.6 |
| `test_v_rz_word_matches_literal_and_sign_flip_fails[91.9->63617, 281.5->65321]` | (в) |
| `test_column_a_tolerance_is_one_quantum_wide` (rz, place x, place z, pick z: +1 PASS, +2 FAIL) | п.8 допуск ±0,10 + 1e-6 |
| `test_flags_word_other_than_3_fails` | п.8 (flags = 3) |
| `test_alpha_window_on_pick_words_boundaries` (8 границ) ; `test_pick_words_must_match_layout_line_transfer` | п.8 окно α, `передача` |
| `test_g_two_jobs_with_same_args7...`, `test_g_pick_without_job_fails_as_lost`, `test_g_two_jobs_with_same_cmd_seq_fail_as_duplicate` | (г), п.6, п.12 |
| `test_d_job_without_reply...`, `test_d_second_reply_plus80_with_same_status...`, `test_d_second_reply_with_other_status_or_errno...` | (д), п.3 |
| `test_e_only_skip_rows_and_no_jobs_pass`, `test_e_pick_without_any_job_is_code_1_not_3` | (е), п.14 |
| `test_zh_argc_9_fails`, `test_zh_missing_args5_fails` | (ж), п.12 |
| `test_z_only_last_incarnation_is_judged_old_one_broken` / `..._new_one_broken` | (з), п.2, п.4 |
| `test_i_servo_sc_run_stop_req_blocks_are_not_jobs`, `test_noise_lines_are_skipped_silently` | (и), п.2, п.3 |
| `test_k_deleted_job_does_not_steal_next_fill_job` | (к), п.6 верхняя граница |
| `test_bind_job_earlier_than_pick_is_not_a_candidate`, `test_bind_job_at_same_timestamp_as_pick_binds`, `test_extra_job_after_skip_row_is_marked_after_skip`, `test_extra_job_before_first_disk_row_is_marked_before_first_pick`, `test_fill_numbers_zero_before_first_word_then_cut_by_word_change` | п.4, п.6, п.13 |
| `test_l_retry_after_refusal_passes_and_counts_one_retry`, `test_l_refusal_without_retry_fails_with_status`, `test_l_refusal_followed_by_job_with_other_args_is_not_a_retry` | (л), п.7 |
| `test_m_three_e_cells_1_3_8_once_each_and_fourth_e_is_skipped`, `test_m_same_cell_twice_in_one_fill_fails_as_cell`, `test_m_cell_of_another_letter_fails_as_cell` | (м), п.9 |
| `test_n_missing_required_argument_is_code_2[3]`, `test_n_unknown_argument_is_code_2`, `test_n_non_numeric_zone_max_is_code_2_and_text_hides_value`, `test_n_words_count_above/below...`, `test_n_word_with_space_and_no_pitch_is_code_2_and_text_hides_value`, `test_n_unreadable_input_is_code_3_and_text_hides_path[2]`, `test_n_empty_input_is_code_3_and_text_hides_path[2]` | (н), п.14 (тексты отказов без значений аргументов) |
| `test_o_sign_flip_on_nine_disks...`, `test_o_consistent_nine_disks_pass_clean`, `test_o_eight_judged_disks_are_not_enough...`, `test_o_single_outlier_over_30_degrees_is_pass_tilde_not_fail`, `test_o_error_over_15_degrees...[e=-14,-16,-60]`, `test_o_feeds_at_0_and_180_degrees_are_not_judged`, `test_o_disk_without_passport_is_not_a_failure`, `test_o_passport_after_job_time_is_not_used`, `test_o_passports_of_one_letter_go_to_disks_in_time_order_not_file_order`, `test_o_pick_x_against_sim_passport_zones[3]` | (о), п.10 |
| `test_p_sim_saw_every_accepted_job_pass`, `test_p_job_missing_at_sim_fails`, `test_p_extra_cvt_job_at_sim_fails`, `test_p_refused_job_is_not_compared_with_sim` | (п), п.11 |
| `test_r_far_cell_at_zone_500...[0,8]`, `test_r_far_cell_at_zone_600...[0,8]`, `test_r_zone_default_is_500`, `test_r_near_cell...`, `test_r_zone_threshold_is_hypot_544_06[544,545]` | (р), п.8, О4 |
| `test_run1_real_files_zone_600_exact_summary`, `test_run1_real_files_with_words_give_same_summary`, `test_run1_real_files_zone_500_warns_about_far_cells_but_passes` | ACCEPTANCE (run1, итоговая строка `взятий 15, заданий 15, FAIL 0, пропусков 34, повторов 0, предупреждений 0`) |

Ожидаемые слова провода — литералы: ячейки 0…8 в ARGS[7] — 61136, 62236, 63336, 64436, 0, 1100, 2200, 3300, 4400; rz по таблице `RZ` в файле (ручной счёт по формуле п.8, сверено с текстом: 91.9 -> 63617, 281.5 -> 65321 и с реальной фикстурой: 3.3 -> 64503, 32.6 -> 64210).

## Прогон

Команда (через гейт, класс light, сессия simaudit-inspector-bottles-ee), из корня worktree, `PYTHONUTF8=1 PYTHONPATH=<корень>`:

```
bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light simaudit-inspector-bottles-ee \
  /Users/twokrai/Project_code/Inspector_bottles/.venv/bin/python -m pytest -q --tb=line -p no:cacheprovider \
  scripts/wire_audit/tests/test_wire_audit_acceptance.py
```

Результат: `108 failed, 1 warning in 4.22s`, passed 0. Гейт на этой машине сработал (не 75), платформенных проблем нет.

Причина красного у всех 108 одна: `CLI-модуль scripts.wire_audit не найден (ModuleNotFoundError)` — `/Users/twokrai/Project_code/Inspector_bottles/.venv/bin/python: No module named scripts.wire_audit` (хелпер `run_cli` превращает это в явный `pytest.fail`, чтобы код возврата 1 не маскировал «модуля нет» под ожидаемый FAIL-вердикт). Ошибок сборки, импорта или синтаксиса самих тестов нет; `ruff check` и `ruff format --check` на файле чистые. Формат моих сгенерированных строк журналов сверен глазами с реальными строками фикстур (префикс, `#1  connect ok`, `CMD_ARGS[i]`, `out R RES_SEQ..+12`, `диск … → ячейка N: взять(…) → положить …`).

## Неоднозначности текста

1. Выход CLI. Куда идёт отчёт при `--out` (дублируется ли в stdout) и в какой поток (stdout/stderr) пишутся тексты отказов 2 и 3. Тесты читают отчёт из stdout без `--out`, с `--out` смотрят только файл, отказы ищут в stdout+stderr.
2. Что считает «FAIL K» в итоговой строке: строки таблицы или причины. Точные числа FAIL ставлю только там, где строка с одной причиной (тогда оба чтения дают 1); иначе `FAIL >= 1`.
3. «заданий M» в паре «отказ + повтор» (п.7): считается ли отказанный блок. В (л) число M не утверждаю, только `повторов 1`, `FAIL 0`, `взятий 1`.
4. П.13 пример строки содержит `взять(460.2,-341.3)` — по п.8 это ARGS[3] = 62123, вне окна α 62096…62116, т.е. пример из DESIGN сам дал бы FAIL `окно`. Мои фикстуры используют `взять(460.2,-343.2)` (62104, в окне). Лиду/автору: пример текста несогласован с окном.
5. П.8 «Слова с пробелом и `use_pitch=false` — код 2»: условие «и» или «или»? Тест — слово с пробелом И `use_pitch=false` (подходит при любом чтении); слово с пробелом при `use_pitch=true` и `use_pitch=false` без пробела не тестирую. (н) из п.15 говорит «при слове с пробелом» без условия на pitch.
6. Ключи без привязки: причина `слово` (п.13) нигде не определена — не тестирую. Ключ причины для `ARGS[5] != 3` (flags) не задан — тест проверяет только код 1 и `FAIL` в последней ячейке строки. Куда прикрепляется итог прогона `сдвиг нуля или знак` (строка/отдельная строка) не сказано — проверяю наличие фразы в выводе и код 1.
7. `лишнее` «до первого взятия»: у задания нет строки диска, куда его прикрепить; проверяю только наличие обеих фраз (`лишнее`, `до первого взятия`) в выводе и код 1, не строку.
8. Формат `t` в `--sim-journal` не задан (в п.11 стоит многоточие). Использую ту же строку времени, что в логах.
9. Блок `STOP_REQ` как команда: номер опкода неизвестен (взял 99), форматы строк `SC_BUF`, `disconnect`, `W 0x12xx` в моих строках шума — по аналогии с реальными и названиями из п.2, возможно не совпадают с реальными.
10. «(б) ARGS[7]+1 — FAIL `ячейка`/`потеря`»: п.6 даёт `потеря` для взятия и `лишнее` для задания, (б) допускает любой из `ячейка`/`потеря`. Тест принимает любой из двух.
11. Код возврата для нечитаемого/невалидного файла регистров не задан (п.14 говорит про обмен и диск). Не тестирую.
12. «Пустые задания» в (е) прочитано как «ноль заданий в непустом журнале обмена».
13. Допуск `передача` (0,10) в п.8 без «+1e-6». Пограничное «ровно 0,1» не тестирую (float).
14. Столбцы заливка/«#»: нумерация заливок 0, 1, 2… выведена из «заливка 0» и примера; `#` как номер строки не проверяю.

## Что я оставил открытым / ненадёжным

- Ни один тест не проверен против реализации (её нет): гарантирована только красная причина «модуля нет». Часть утверждений опирается на моё прочтение текста (см. выше) и может оказаться ложным красным после реализации; такой красный надо разбирать по строке спецификации, а не молча править код или тест.
- Строгие предположения о выводе, которые можно оспорить: строки таблицы ровно из 14 ячеек для каждой строки диска (включая пропуски) — иначе падают `row_by_net`-тесты; итоговая строка — последняя непустая строка stdout (`test_run1_real_files_zone_600_exact_summary`); значения `p_pick_rz_deg` и `--zone-max-mm` печатаются в шапке в виде `-87.5` / `543.5`; таблица `А` у примера строки равна `PASS`, `Б` равна `-` без `--sim-objects`; у строки без паспорта нет `~`, а при не судимой подаче 0°/180° ячейка итога — просто `PASS`.
- Не покрыто: `ARGS[5]` как отдельный ключ; Pick y против паспорта сима и знак `lateral_px` (п.10 называет знак гипотезой); `angle_valid=False`; слово `слово`; перестановка заданий и строк диска во времени вне случаев (к) и привязки по времени; смена слова посреди прохода сверх (к); регистры `word_gap_slots` и `use_pitch=false` без пробела; границы допусков ровно 1,0/2,0 мм и 15° (float); дубли строк журнала сима как отдельный наблюдаемый эффект (множество не отличает дубль от одной строки — тест только не должен упасть).
- Тест `test_n_word_with_space_and_no_pitch...` и тесты кода 2 по `--words` полагаются на то, что проверка числа слов и «не поддержано» срабатывает раньше чтения содержимого журналов; порядок проверок в тексте не задан.
- Параметризованные 8 границ окна α и допуски столбца А — длинные, но каждая точка — одно утверждение; при пересмотре порогов правятся литералами в тексте параметров.
- Запуск только на macOS, интерпретатор — основной `.venv`; на другой платформе не проверялось.
