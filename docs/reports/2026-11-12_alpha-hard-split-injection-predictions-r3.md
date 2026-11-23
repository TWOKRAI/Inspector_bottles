# Task A — предсказания инъекций, раунд 3 (после Opus-ревью ветки; лид, ДО прогона)

Основание: Opus-ревью (`docs/reports/2026-11-12_opus-arch-review.md`) — CHANGES REQUESTED, blocker B1: число не признанных дисков `U` включало диски, которые литерал и так
пропускает; воспроизведено лидом (`probe_u.py`: D#1 «П» ниже порога + `done=False` → `МЕХАНИЗМ: PASS`). Should S3: не признанный диск целиком уходил в ТОЧНОСТЬ и прятал причины механики.
Спека — редакция 4. Новые тесты — developer (автор, `test_alpha_split_hazards.py`); приёмочные тесты слепого tester, противоречащие редакции 4, developer правит только по списку лида
и перечисляет поимённо. Сознательно НЕ делаем в этом раунде (записать в отчёт): S1 (assert results/shown), S2 (вынос фейков в `_fakes.py` — правит файл tester), nit-ы.

| № | Инъекция | Ожидаемо КРАСНЫЕ | Ожидаемо ЗЕЛЁНЫЕ |
|---|---|---|---|
| I28 | `U`/`unrecognized`/`U_before` снова считают ВСЕ не признанные диски (откат B1) | новые тесты B1: (а) D#1 «П» ниже порога + `done=False` → `МЕХАНИЗМ: FAIL`; (б) D#1 «П» ниже порога + сдвиг счётчика `jobs_emitted` на 1 → `МЕХАНИЗМ: FAIL` | `a2_unrecognized_last_disc_below_threshold_is_accuracy_with_cascade_checks` (там ожидался взят, строка — пропуск: сдвигает) |
| I29 | `U` считает диски, у которых «взят/пропущен» СОВПАЛ, вместо сдвигающих (перевёрнутое условие) | `a2_unrecognized_last_disc_below_threshold_is_accuracy_with_cascade_checks`, `a2_run_unrecognized_last_disc_of_b_block_and_exit_code`, `a2_run_lost_disc_in_middle_of_d_cascades_to_accuracy`, новый тест B1 (контроль «потеря взятого диска остаётся ТОЧНОСТЬ-каскадом») | `a2_checks_are_mechanism_when_nothing_unrecognized` |
| I30 | `_disc_klass`: не признанный диск всегда ТОЧНОСТЬ (убрать исключения S3) | новые тесты S3: не признанный диск (ошибка буквы) с `pick` вне окна → МЕХАНИЗМ; с `res_status 0` → МЕХАНИЗМ; с `ARGS[2]` вне окна → МЕХАНИЗМ | A2-тесты «не признан → ТОЧНОСТЬ целиком» (причины `cell/place/decision/ARGS[7]/r/ARGS[9]`) |
| I31 | `_disc_klass`: исключения S3 расширены на `cell` и `place` (слишком строго) | `a2_unrecognized_by_letter_key_and_by_feed_key` и/или `a2_unrecognized_without_prediction_whole_row_accuracy_even_with_other_reasons` (если в их причинах есть `cell`/`place`; если ни один не краснеет — находка: класс причин `cell/place` у не признанного диска не покрыт) | новые тесты S3 (`pick`, `res_status`, `ARGS[2]`) |

Правило чтения: красный сверх набора или зелёный внутри набора — находка. После раунда — полный набор зелёный на откате (число назвать), `ruff check scripts/alpha_sim`, `git diff --stat` пуст.
