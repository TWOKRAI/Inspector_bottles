# developer: alpha_sim Task A (каскад word_line, класс FAIL, `--hard-out`)

Ветка `feat/alpha-hard-split`. Не коммитил, не пушил.

## Что сделано (path:line)

A1, каскад `word_line`:
- `scripts/alpha_sim/logic.py` `judge_case(..., prev_filled=None, hard_angle_thr=5.0)`: ожидаемая строка слова = литерал с «было заполнено k/» ← `prev_filled` (re.sub; у B в литерале нет «было заполнено», параметр не действует).
- `scripts/alpha_sim/run_alpha.py:~524-526, 572`: `prev_filled` из регистров, прочитанных ПЕРЕД случаем (тот же вызов, что `before`); не int или bool — `None`.

A2, класс FAIL:
- `logic.py`: `Row.klass`, `CaseResult.unrecognized` / `.hard` (с умолчаниями в конце); `_unrecognized`, `_disc_klass` (:418), `_check_klass` (:432), `runner_check_klass` (:448, класс `feed`/`exchange`/`layout_log`), `format_split_block` (:910).
- Ненадёжное выравнивание: `reliable = use_feed or len(disks) == n_exp` в `judge_case`; тогда U=0, все FAIL диска МЕХАНИЗМ, `hard` пуст.
- `run_alpha.py`: `mark()` (:285) — метки прогона (`предусловие` / `ошибка` / `прервано` / `ошибка ДОМОЙ/СТОП`, без дублей) на всех путях P0, P1–P3, случай, `normal_tail`, шаги уборки; `show()` (:291) печатает строку и запоминает префикс (все `format_row` идут через неё); `_finish_case` использует `dataclasses.replace` (сохраняет `unrecognized`/`hard`); `finish()` печатает блок между `изменено…` и `итог:`.

A3, `--hard-out`:
- `logic.py:352` `hard_reasons(...)` — единственная реализация правила «трудного» (docstring: правило принадлежит DS-1 §6 / `join_frame_truth`, 1.1c; строка `# ponytail: дубль правила DS-1 §6, заменить импортом после DS-1 1.1c`). `_hard_record` (:375) только собирает запись JSONL и вызывает `hard_reasons`.
- Подтверждаю: других мест, считающих «трудность», нет. `git grep` по `angle_thr|hard_reasons|no_prediction|class_mismatch` вне `logic.py` и тестов: только `run_alpha.py:573`, передача порога. README описывает правило словами, без копии.
- `run_alpha.py`: флаги `--hard-out`, `--hard-angle-thr` (:928), `write_hard_out` (:824) вызывается внутри `finish()` до блока A2; байтовая запись `\n`; ошибка — строка `hard-out: ошибка …`, rc прежний.
- README.md (опции, каскад, класс FAIL, `--hard-out`, отличия от DS-1 §5, ограничение глубокого каскада, «N записей ≠ числу ТОЧНОСТЬ-FAIL») и STATUS.md обновлены.

Единственная правка существующих тестов: `_lossy_cases` в `test_p4_alpha_hazards.py` (D word_line → «8/9»).

## Тесты (cwd — worktree, `machine_gate.sh light`, python главного `.venv`, `PYTHONPATH=<worktree>`)

База до правок (приёмочный файл отклонён `--deselect`): `123 passed, 89 deselected`.
Приёмочные 89 до правок: 86 красных, 3 зелёные (отчёт tester).
После A1+A2 (на judge-уровне) и до правки `_lossy_cases`: `1 failed, 211 passed` — красный ровно `test_g14_lost_disk_in_b_does_not_hide_d_and_c` (ассерт `D случай: PASS`, как и предсказано).
После правки `_lossy_cases`: `212 passed, 1 warning` (89 приёмочных + 123 существующих).
Путь импорта: `scripts.alpha_sim.logic` → `.../worktrees/alpha-hard-split/scripts/alpha_sim/logic.py` (внутри worktree).
`ruff check scripts/alpha_sim` — чисто; `ruff format --check` по трём изменённым py-файлам — чисто.

`git status --short`:
```
 M scripts/alpha_sim/README.md
 M scripts/alpha_sim/STATUS.md
 M scripts/alpha_sim/logic.py
 M scripts/alpha_sim/run_alpha.py
 M scripts/alpha_sim/tests/test_p4_alpha_hazards.py
```
(плюс этот отчёт, не отслеживается; приёмочный файл tester уже в коммите `4c4f9540c`).

## Решения там, где DESIGN молчит

1. Старый тестовый `argparse.Namespace` в hazards (`:76`) не содержит новых флагов, а править тест нельзя: раннер читает их через `getattr(self.args, "hard_out", None)` / `getattr(..., "hard_angle_thr", 5.0)`.
2. «Ненадёжно» = `not use_feed and len(disks) != n_exp`, а не буквально `feed is None`: отличается только при непустой подаче неверной длины (раннер такой не даёт: он передаёт `None`), там позиционное сопоставление так же ненадёжно.
3. Метки без дублей (один раз на путь), порядок — по появлению. Исключение в шаге уборки ДОМОЙ/СТОП (`_cleanup_step`) ставит метку `ошибка ДОМОЙ/СТОП` и строку в блок класса.
4. Печать блока строится в `logic.format_split_block` из пар `(префикс, Row)` в порядке печати (`self.shown`), а не из `self.results` — иначе префикс строк ДОМОЙ/СТОП не восстановить.
5. `no_prediction` определяется по `skip.startswith("нет предсказания")`, «ниже порога» — по `startswith("уверенность ниже порога")`; разбор `(<буква> <уверенность> < <порог>)` при несовпадении формата даёт `confidence`/`conf_thr` = `null`.
6. Δ в записи: `round(wrap180(сеть − истина), 1) + 0.0` (без `-0.0`); `angle_deg` истины — float.
7. Ключ строки-исключения: `Row.check == префикс` → ключ опущен (допущение tester 1); `CaseResult.hard` — те же dict'ы, что JSONL, включая `case` (допущение 2).

## Красные, которые считаю ошибкой теста

Нет. Все 89 зелёные без правок приёмочного файла.

## Что оставил открытым / ненадёжно

- Живой стенд не запускался: проверено только на фейках; формат строки пропуска «ниже порога» (`(И 0.43 < 0.50)`) взят из допущения tester / `C-86a`, а не из выхода настоящего плагина. Если плагин печатает иначе, `confidence`/`conf_thr` станут `null`, а `below_threshold` останется `true`.
- Break-injection не делал (за лидом); слабость, о которой говорит tester: тесты A1 «до, а не после» привязаны к фейковому тайму (+2,0 с после последнего диска B, чтение перед D на +3,5 с).
- `ТОЧНОСТЬ` для проверки `feed` при `U = 0` (→ МЕХАНИЗМ) отдельным тестом не покрыто (отмечено tester, п.7); реализовано по DESIGN.
- Глубокий каскад (misread-диск занял чужую ячейку) классифицируется как МЕХАНИЗМ — известное ограничение, записано в README.
- `scripts/alpha_sim/tests/test_p4_alpha_runner.py` не проходит `ruff format --check` ещё до моих правок (файл не менял; в ограничениях — только `_lossy_cases`).
- Правило `hard_reasons` — временный дубль DS-1 §6: после влития DS-1 1.1c нужно заменить импортом (строка `# ponytail:` в `logic.py:361`); совпадение с `join_frame_truth` по коду не сверялось (его кода в main нет), только с текстом `design.md` §6.
- Предсказание в брифе «первый ассерт падает раньше» подтверждено только для первого ассерта `:700` (`D случай: PASS`); второй (`:708`) отдельно не прогонялся.
- Сообщение `DESIGN: … starting edits` перед первой правкой `src/` отдельно не отправлял (нет канала кроме финального отчёта).
