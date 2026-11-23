# Task A — предсказания инъекций, раунд 2 (после стадии 5 раунд 1; лид, ДО прогона)

Основание: reviewer af3d5bca (CHANGES REQUESTED): blocker rc после `_cleanup_step`; should: `r`/`ARGS[9]` при верном угле журнала — МЕХАНИЗМ, каскад `progress` односторонний.
Спека — редакция 3 (`plans/release-1.0/lane-tasks/alpha-hard-split.md`). Новые тесты пишет developer (автор) в `test_alpha_split_hazards.py`; приёмочные тесты слепого tester,
противоречащие редакции 3, developer правит только по списку лида (каждое изменение — в отчёт). Инъекции — на закоммиченном коде раунда 2.

| № | Инъекция | Ожидаемо КРАСНЫЕ | Ожидаемо ЗЕЛЁНЫЕ |
|---|---|---|---|
| I21 | `_disc_klass`: убрать условие «угол журнала расходится с истиной > `_R_TOL`» (`r`/`ARGS[9]` всегда объяснены) | новые тесты S1 (нет `ARGS[9]` при `argc=10`), S2 (`ARGS[9]` сдвинут на +1000 при верном угле), S3 (знак `r` перевёрнут при верном угле): все три дают `МЕХАНИЗМ: FAIL` на коде и `PASS` при инъекции | контроль «угол журнала вне допуска → ТОЧНОСТЬ» (зелёный на обоих) |
| I22 | `_cleanup_step`: `mark(..., precond=True)` (вернуть блокер) | новый тест: `word_set` unverified в B + исключение `robot_park_all` в уборке → rc 1 (при инъекции 3) | остальные |
| I23 | каскад `progress`: `0 ≤ k_лит − k` → `abs(k_лит − k)` | новый тест: `k` больше литерала (`[4/3]` при литерале `[3/3]`) → МЕХАНИЗМ | `a2_progress_cascade_limited_by_unrecognized_before`, `a2_run_lost_disc_in_middle_of_d_cascades_to_accuracy` |
| I24 | `_cleanup_step`: не ставить метку `ошибка ДОМОЙ/СТОП` | новый тест на метку через уборку (word_set в B + исключение park) | `a2_run_home_exception_in_tail_is_home_error_label` (путь через `normal_tail`) |
| I25 | метка `ошибка` при исключении внутри случая не ставится | новый тест исключения внутри случая | `a2_run_unexpected_exception_in_p1_is_error_label` |
| I26 | метка `прервано` при Ctrl-C в `normal_tail` не ставится | новый тест Ctrl-C в хвосте | `a2_run_ctrl_c_in_case_is_interrupted_label` |
| I27 | `_hard_record`: `below_threshold` из regex, как до nit 6 | новый тест: пропуск `уверенность ниже порога` без скобок → `pred.below_threshold is True`, `confidence None` | остальные |

Правило чтения: как в `..-injection-predictions.md`. После раунда — полный набор зелёный на откате, `git diff --stat` пуст.
