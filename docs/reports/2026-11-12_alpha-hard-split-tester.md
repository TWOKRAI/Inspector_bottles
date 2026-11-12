# Слепой tester: alpha_sim, Task A (каскад word_line, класс FAIL, `--hard-out`)

Дерево: `.claude/worktrees/alpha-hard-tester` (коммит `495410b13`, до реализации). Файл тестов:
`scripts/alpha_sim/tests/test_alpha_split_acceptance.py` (89 тестов; ничего не коммитил, существующие тесты не правил).
Источник ожидаемого — только DESIGN/REDS/ACCEPTANCE задачи; `logic.py`, `run_alpha.py`, `Plugins/**`, `Services/**` не читал.

## Запуск

```
bash scripts/machine_gate.sh light alpha-hard-tester env PYTHONUTF8=1 PYTHONPATH=<worktree> .venv/bin/python -m pytest -q --tb=short scripts/alpha_sim/tests/test_alpha_split_acceptance.py
=> 86 failed, 3 passed, 1 warning in ~3 s   (ruff check / ruff format --check: чисто)
```

Чтобы настроить фейки (что печатает старый код на моих сценариях, момент снимка регистров), я ЗАПУСКАЛ старый `run()` и смотрел
его вывод (чёрный ящик), исходники не открывал. Эти выводы подтвердили: B#12-сценарий даёт ровно шесть красных проверок
(`B #12`, `jobs.count`, `regs.slots_filled`, `regs.jobs_emitted`, `regs.done`, `feed`), D-сценарий «М #2 без предсказания» —
`D #2`, `D #4` и `D #5` (у двух последних причина только `progress`), те же четыре проверки и `feed`.

## Таблица: тест → красный/зелёный → причина

Причины красного (все ожидаемые): **K** = `AttributeError: 'Row' object has no attribute 'klass'`; **U** = `AttributeError: 'CaseResult' ... 'unrecognized'`;
**H** = `AttributeError: 'CaseResult' ... 'hard'`; **P** = `TypeError: judge_case() got an unexpected keyword argument 'prev_filled'/'hard_angle_thr'`;
**N** = в выводе `run()` нет строк `МЕХАНИЗМ:`/`ТОЧНОСТЬ:`/`класс …` (последняя строка перед `итог:` — `изменено в симе/на стенде: …`);
**F** = `rc == 2`: argparse не знает `--hard-out`; **W** = ожидаемая новая строка D `word_line` (PASS/FAIL по `prev_filled`) не совпала с литеральным поведением.

| Группа (тест → число) | Статус | Причина красного |
|---|---|---|
| `test_a1_d_line_with_filled_8…`, `test_a1_none_means_literal…`, `test_a1_other_word_change…[None/8/9]`, `test_a1_c_line_for_case_d…`, `test_a1_n_is_literal…`, `test_a1_k9_with_prev_filled_8…`, `test_a1_case_c_follows…`, `test_a1_case_b_ignores…` (10) | красные | P |
| `test_a1_run_expected_d_line_carries_register_value_at_start_of_d…`, `test_a1_run_c_gets_prev_filled_from_d_register` (2) | красные | W (литерал ждёт 9/9, плагин печатает 8/9 / 2/3) |
| `test_a1_run_snapshot_after_b_would_be_wrong_pair` (1) | красный | W (k=9 при регистре 8 должен быть FAIL; сегодня литерал даёт PASS) |
| `test_a1_run_missing_or_non_int_register…[no_key]`, `[not_int]`, `test_a1_run_without_flip_literal_still_passes_control` (3) | **зелёные** | контроль, см. ниже |
| `test_a2_*` на `judge_case`: pass_has_no_klass, unrecognized_*, progress_*, `row_reasons_decide_klass[13]`, missing/extra line, checks_*, other_checks[3], lines_count, unreliable_alignment (≈ 34) | красные | K / U / H (нет полей `klass`, `unrecognized`, `hard`) |
| `test_a3_*` на `judge_case` (angle_over_threshold, boundary[5], wraps, truth_from_feed, independent_reasons, below_threshold_alone, no_prediction, not_in_word, ordered_by_index) (12) | красные | P (kwarg `hard_angle_thr`) или H |
| `test_a2_run_*` (all_green, unrecognized_last_disc, lost_disc_in_middle, mechanism_list_order, stop_fail, p0, p1_p3, unexpected_exception_in_p1, word_set, precondition_in_middle_of_b, ctrl_c, home_exception, exchange_dropped, layout_log_dropped) (14) | красные | N |
| `test_a3_run_*` (b12 literal, no_prediction, angle+threshold flag, ml_inference text, order B/D/C, disc without line, file empty, file on P0, file on P1 precondition, file on Ctrl-C, empty flag value, write_error[no_dir, dir_instead_of_file]) (13) | красные | F (rc 2) или N |

Зелёные до реализации (3) — только контрольные пары, все про путь `prev_filled → None → литерал`, который сегодня и есть поведение:
ключ `slots_filled` в регистре отсутствует перед D / значение `"8"` (не int) / регистр не менялся. Они должны остаться зелёными после
реализации: ловят вариант, где реализация падает на `KeyError` или приводит `"8"` к int и ждёт «8/9».

Красных по неверной причине (ошибка самого теста) нет: каждый красный разобран по тексту ошибки (K/U/H/P/N/F/W выше).

## Гарантия и минимальная поломка реализации (для сверки лида с предсказаниями)

| Тест(ы) | Гарантия | Минимальная поломка, которую он ловит |
|---|---|---|
| `a1_d_line_with_filled_8`, `a1_k9_with_prev_filled_8`, `a1_none_means_literal` | k в «было заполнено k/n» берётся из `prev_filled`; `None` → литерал | игнорировать `prev_filled` (всегда литерал) → первый красный; сравнивать только `n` → `k9_…` красный; `None` трактовать как 0 → `none_means_literal` красный |
| `a1_other_word_change[None/8/9]`, `a1_c_line_for_case_d` | другая смена слова — FAIL при любом `prev_filled` | подставлять `k` и не сверять слова → оба красные |
| `a1_n_is_literal` | `n` — литерал, а не `prev_filled` | регэксп «k/k» или `n = prev_filled` → красный |
| `a1_case_c_follows`, `a1_case_b_ignores` | C тоже по `prev_filled`; B параметр игнорирует | обработать только D → `case_c` красный; применить к B (искать «было заполнено» в его строке) → `case_b` красный |
| `a1_run_expected_d_line…`, `a1_run_snapshot_after_b…` | раннер берёт `slots_filled` из регистра, прочитанного ПЕРЕД случаем (T+3,5 с), а не из снимка после B (T) | передавать `prev_filled` из снимка после B → оба красные (D word_line красный при ожидании 8 / зелёный при ожидании 9); передавать литерал → то же |
| `a1_run_missing_or_non_int…` | ключ нет / не int → `None` → литерал | `regs["slots_filled"]` без проверки (KeyError) или `int("8")` → красные |
| `a1_run_c_gets_prev_filled_from_d_register` | `prev_filled` C = регистр после D | брать у C значение, оставшееся от B → красный |
| `a2_pass_has_no_klass…` | PASS-строки `klass is None`, `unrecognized == 0`, `hard == ()` | заполнить `klass` у PASS-строк → красный |
| `a2_unrecognized_last_disc…`, `a2_run_unrecognized_last_disc…` | не признан («ниже порога», как B#12) → ТОЧНОСТЬ у строки и у 4 связанных проверок (+`feed` в run) | не считать `ниже порога` непризнанным (искать только `letter`) → строка МЕХАНИЗМ |
| `a2_unrecognized_by_letter_key_and_by_feed_key` | признак «не признан» — причины с ключами `letter` и `feed` | учитывать только `letter` или только текст пропуска → красный |
| `a2_unrecognized_without_prediction…`, `a2_run_lost_disc_in_middle_of_d…` | потеря в СЕРЕДИНЕ списка D: диск + каскад `progress` на 1 у И и Р — ТОЧНОСТЬ | не вводить каскад progress (`U_before`) → `#4`, `#5` МЕХАНИЗМ |
| `a2_progress_cascade_limited…` | `progress` на 2 меньше при одном непризнанном — МЕХАНИЗМ | допуск «любой progress при U ≥ 1» → красный |
| `a2_progress_cascade_requires_equal_n`, `a2_progress_off_by_one_without…` | допуск только при `n_факт == n_литерал` и только до `U_before` | не сверять `n` / не ограничивать `U_before` (брать общий U) → красные |
| `a2_row_reasons_decide_klass[…]` | таблица причин: pick/cell/place/decision/ARGS[7]/[2]/[3]/res_status/progress без потерь → МЕХАНИЗМ; только `r`, только `ARGS[9]`, `r`+`ARGS[9]` → ТОЧНОСТЬ; `r`+`pick` → МЕХАНИЗМ | считать ТОЧНОСТЬ любую строку, где есть `r` или `ARGS[9]` («ЛЮБАЯ причина» вместо «ВСЕ») → `r_plus_pick` красный; считать `pick` точностью → `pick_right_letter` красный |
| `a2_missing_line…`, `a2_extra_line…` | «нет строки» и «лишняя строка» — МЕХАНИЗМ; в `hard` и `U` не входят | считать «лишнюю строку» непризнанной/трудной → красный |
| `a2_checks_are_mechanism_when_nothing_unrecognized[4]`, `a2_checks_off_by_two…`, `a2_jobs_emitted_uses_growth_over_before` | `jobs.count`/`slots_filled`/`jobs_emitted`(по приросту)/`done`: ТОЧНОСТЬ при расхождении ≤ `U` (done — при `U ≥ 1`), иначе МЕХАНИЗМ | допуск без привязки к `U` (всегда ТОЧНОСТЬ при расхождении) → `nothing_unrecognized` красный; допуск `≤ U+1` или «любой» → `off_by_two` красный; `jobs_emitted` по абсолюту → `uses_growth` красный |
| `a2_other_checks…[3]`, `a2_lines_count…` | `word_line`, `lines.count`, `word_norm`, `slots_total` всегда МЕХАНИЗМ | попустительство этим проверкам при `U ≥ 1` → красные |
| `a2_unreliable_alignment…` | `feed is None` и число строк ≠ числу дисков: все FAIL-строки МЕХАНИЗМ, `U = 0`, `hard` пуст; пара с равным числом строк — надёжно | не вводить правило ненадёжного выравнивания (сдвиг даст `letter` → ложные ТОЧНОСТЬ) → красный |
| `a3_angle_over_threshold…`, `a3_angle_boundary[5]` | `|Δ| > thr` строго; Δ округлена до 0,1° (5,04 → не трудный, 5,06 → трудный); знак не важен | `>=` вместо `>` → `delta_exactly_5_0`; сравнение без округления → `5_04`; `abs` забыт → `minus_5_8` |
| `a3_angle_difference_wraps_around_360` | период 360 (`wrap180`) | вычитание без `wrap180` → красный |
| `a3_truth_comes_from_feed…` | истина = подача из `feed`, иначе литерал | всегда литерал или всегда feed → красный |
| `a3_class_mismatch_and_angle_are_independent_reasons`, `a3_below_threshold_alone…`, `a3_no_prediction_skips…`, `a3_not_in_word_skip…` | порядок и независимость причин; `no_prediction` без `class_mismatch`/`angle`; пропуски «нет в слове» считаются как взятый диск | `no_prediction` + `class_mismatch` (буква `?` ≠ подачи) → красный; игнорировать диски-пропуски → `not_in_word` красный |
| `a3_hard_records_ordered_by_index…` | записи по возрастанию `index`; диск без причин не попадает | порядок по другому ключу → красный |
| `a2_run_all_green…` | пустой блок: `МЕХАНИЗМ: PASS`, `ТОЧНОСТЬ: 0 трудных`, затем `итог:` | печатать `ТОЧНОСТЬ: 0 трудных ()` / после `итог:` → красный |
| `a2_run_unrecognized_last_disc…`, `a2_run_lost_disc_in_middle…` | дословный блок: порядок «диски, затем прочие», код 1, `итог:` последней, блок между `изменено…` и `итог:` | `итог:` напечатать раньше блока, неверный порядок, лишнее `класс D word_line` (каскад word_line не учтён) → красный |
| `a2_run_mechanism_list_follows_case_order…` | единый порядок B, D, C; внутри случая `word_line` → диски; перечень `B #3, D word_line, D #1` | диски до `word_line` или порядок по классу → красный |
| `a2_run_stop_fail…`, `a2_run_home_exception…`, `a2_run_exchange_dropped…`, `a2_run_layout_log_dropped…`, `a2_run_word_set…` | FAIL СТОП / ДОМОЙ / `exchange` / `layout_log` / `word_set` — МЕХАНИЗМ; ключ опускается, если `Row.check` = префиксу | `None`-класс строк раннера трактовать как ТОЧНОСТЬ → красные |
| `a2_run_p0…`, `…p1_p3…`, `…unexpected_exception_in_p1`, `…precondition_in_middle_of_b`, `…ctrl_c…`, `…home_exception…` | метки прогона (`предусловие`, `ошибка`, `прервано`, `ошибка ДОМОЙ/СТОП`) и `не выполнены: …` дословно; уборка в P4 даёт статусы ДОМОЙ/СТОП, в P0–P3 — нет | одна метка на все пути; не добавлять метку → `МЕХАНИЗМ: PASS` при Ctrl-C/`ошибка` → красные; `не выполнены` из всех статусов, а не из `None` → красные |
| `a3_run_b12_record_literal…` | строка JSONL дословно: ключи и порядок (включая `truth`, `pred`), `confidence 0.43`, `conf_thr 0.5`, `delta -174.2`, кириллица без `\u` | другой порядок ключей / ensure_ascii / не округлённая Δ → красный |
| `a3_run_no_prediction_record` | `pred null`, `delta null`, `["no_prediction"]`, `["нет ответа"]`, `conf_thr null` | `pred` с буквой `?` → красный |
| `a3_run_angle_reason_threshold_flag_and_boundary` | `["angle"]` при 5,0 и `delta 5.8`; пустой файл при `--hard-angle-thr 6.0`; Δ ровно 5,0 — пусто; `pred.confidence None`, `below_threshold False` у взятого | флаг не читается (порог зашит) → красный; `>=` → красный |
| `a3_run_below_threshold_with_ml_inference_threshold_text` | `conf_thr null` при тексте «порог ml_inference», `confidence 0.31` | разбор порога как числа без запасного пути → исключение/красный |
| `a3_run_records_ordered_b_d_c…` | порядок B, D, C и `index`; `ТОЧНОСТЬ: 4 трудных (B #3, B #12, D #5, C #2)` (N записей ≠ числу FAIL-строк) | запись по мере случаев без сортировки/по FAIL-строкам → красный |
| `a3_run_disc_without_journal_line…` | диску без строки журнала записи нет; пара с подменённой строкой — запись есть | писать запись по литералу при отсутствии строки → красный |
| `a3_run_file_created_empty…`, `…on_p0_failure`, `…precondition_in_p1`, `…on_ctrl_c` | файл создаётся всегда (0 байт), в том числе P0, `Precondition` в P1, Ctrl-C | запись только в конце штатного пути → красные |
| `a3_run_empty_flag_value…` | `--hard-out ""` = не задан: файл не создаётся, rc тот же, счёт `ТОЧНОСТЬ` печатается и без флага | пытаться открыть `""` → красный |
| `a3_run_write_error…[2]` | ошибка записи: `hard-out: ошибка …` до строк A2, rc прежний, `итог:` последняя | падать исключением / менять rc / печатать ошибку после `ТОЧНОСТЬ` → красные |

## Что оставил открытым / ненадёжно

Неоднозначности задачи (цитата → как прочёл → что тест держит; ничего не выбирал молча):

1. «**Для `Row(None, "ДОМОЙ", …)` ключ опускается: `класс ДОМОЙ: МЕХАНИЗМ`**» и «перечень: сначала `<случай> <ключ>` каждой МЕХАНИЗМ-FAIL-строки». Прочёл:
   ключ опускается и в перечне → `МЕХАНИЗМ: FAIL (ДОМОЙ, ошибка ДОМОЙ/СТОП)`. Альтернатива — `ДОМОЙ ДОМОЙ`. Тест `a2_run_home_exception…` держит мой вариант. Также не проверено,
   создаёт ли исключение `robot_park_all` в хвосте именно `Row(None, "ДОМОЙ")` (старый код печатает только трейсбек и `ДОМОЙ=FAIL`); если строки нет, тест красный по моему допущению, а не по дефекту.
2. «**Формат строки пропуска ниже порога `(<буква> <уверенность> < <порог>)`**». Конкретный текст я взял из `lane-tasks/C-86a…` («пропуск: уверенность ниже порога (<label> <confidence> < <порог>)») и
   записал как `(И 0.43 < 0.50)` / `(Е 0.31 < порог ml_inference)`. Точное число знаков порога плагин мог бы печатать иначе (`0.5`); тест сравнивает `conf_thr == 0.5` как float.
3. «**`CaseResult.hard: tuple[dict, ...] (записи A3)`**». Не сказано, совпадает ли запись по ключам со строкой JSONL (есть ли `case`). В `judge_case`-тестах читаю только `index` и `hard_reasons`;
   полная форма — только через файл `--hard-out`.
4. «**`класс <случай> <ключ>` … по порядку: `word_line`, диски, прочие проверки**». Порядок ВНУТРИ «прочих проверок» не задан; тесты сравнивают их как множество и фиксируют лишь
   «диски перед проверками» и порядок B, D, C.
5. «**`below_threshold` — `true` только у пропуска «ниже порога»**» и «у взятого диска и других пропусков — `confidence`/`conf_thr` `null`». Прочёл: у взятого диска `pred.below_threshold == false`
   (а не отсутствует), `pred.confidence == null`. Держит `a3_run_angle_reason_threshold_flag_and_boundary`.
6. «**`feed is None` и число строк ≠ `len(Case.discs)` — выравнивание ненадёжно**». Проверено только на judge-уровне (`feed=None`, 11 строк). Случай «feed не None, но неполный» (сим дал не весь список) не покрыт.
7. «**Класс `feed` / `exchange` / `layout_log` определяет чистая функция в `logic.py`**». Имя функции мне неизвестно — проверяю только через `run()`. `feed` → ТОЧНОСТЬ покрыт только при `U ≥ 1` (в B#12 и D#2); `feed` при `U = 0` → МЕХАНИЗМ
   отдельного теста не имеет (нужен сценарий потери задания без непризнанного диска — `_LossyWorld` даёт rc 3 до D).
8. «**Сбой в P0–P3 … `listeners → None`**» — взял `infos={8766: None, 8765: None}` (оба порта пустые); одиночное «чужой слушатель» не проверял.

Слабые места тестов:

- **Синхронизация позднего регистра** (`a1_run_expected_d_line…`, `…snapshot_after_b…`): регистр `slots_filled` меняется ровно через 2,0 с (фейковых) после прихода последнего диска B. Это между снимком после B (T, T+0,5)
  и чтением перед D (T+3,5 по тому, что показал старый `run()`). Если реализация сдвинет моменты чтения, тест станет ложно-красным или ложно-зелёным; проверено только на текущем тайминге.
- Тест `a3_run_disc_without_journal_line…` полагается на то, что `run()` при потерянной строке всё равно доходит до конца (проверено старым кодом: rc 1, итог напечатан); много сопутствующих строк B красные из-за порядкового сопоставления заданий — тест смотрит только на файл.
- В `a3_run_below_threshold_with_ml_inference_threshold_text` мир по-прежнему выдаёт задание для этого диска (строка подменена, задание осталось) — остальные строки B красные, тест смотрит только запись B#3.
- Допущения про `?`-строку «нет предсказания» (`диск '?' 0.0°`) — из текста задачи; если разбор строк у реализации не принимает `?`, красный будет «нет строки», а не `no_prediction`.
- Break-injection не делал (по заданию). Все «минимальные поломки» выше — предсказания, не результаты прогона.
- Не покрыто: запись `--hard-out` ДО печати блока A2 (порядок побочных эффектов наблюдаем только косвенно через P0/Ctrl-C); `--dump` и `--hard-angle-thr` с некорректным значением;
  «глубокий каскад» (известное ограничение); Windows-пути; REDS п.4 (существующие тесты) — не моя часть.
