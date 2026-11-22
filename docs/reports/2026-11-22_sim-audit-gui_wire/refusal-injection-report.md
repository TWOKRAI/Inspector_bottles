# Матрица инъекций: привязка отказов hub (parse_system / _bind_refusals)

Сессия гейта: simaudit-gui-inspector-bottles-bd. Режим: механический прогон по предсказаниям лида, код не правился.

## Условия

- Исходное дерево `/Users/twokrai/Project_code/Inspector_bottles--sa-gui` не менялось (проверено: `git status --short` до и после — тот же набор файлов).
- Мутанты применялись в копии `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/40618340-ede3-42ee-88a0-833aff631458/scratchpad/inj_wa/` (скопирован каталог `scripts/` без `.git` и данных). Эталон копии: `pytest scripts/wire_audit/tests -q -p no:cacheprovider` → `259 passed in 8.06s`.
- Чистый файл сохранён как `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/40618340-ede3-42ee-88a0-833aff631458/scratchpad/inj_wa_core.pristine.py`. Перед каждым мутантом файл копии возвращался `cp` из этой копии; после всех прогонов `cmp` подтвердил совпадение байт в байт.
- Каждый прогон:
  `bash "$(git -C …/Inspector_bottles--sa-gui rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" medium simaudit-gui-inspector-bottles-bd env PYTHONPATH=<копия> /Users/twokrai/Project_code/Inspector_bottles/.venv/bin/python -m pytest scripts/wire_audit/tests/test_refusal_acceptance.py scripts/wire_audit/tests/test_refusal_hazards.py -q --tb=no -p no:cacheprovider`
  Гейт отработал во всех прогонах (код выхода 0 или 1, ни одного 75 и ни одного «NO WINDOW»).
- Эталон для этих двух файлов (M0): `46 passed in 1.56s`, gate_exit=0.

## Таблица

Счёт «красных» — из строки `N failed` pytest; имена — из строк `FAILED` того же прогона (их число совпало со счётом).

| Мутант | Предсказано лидом | Получено: число красных и имена | Совпало? |
|---|---|---|---|
| M1 убрать сравнение буквы | красный `test_a4…[other-letter]` (возможно, ещё) | 1 красный: `test_a4_non_matching_refusal_keeps_lost_fail[other-letter]` | да |
| M2 убрать сравнение ячейки | красный `test_a4…[other-cell]` | 1 красный: `test_a4_non_matching_refusal_keeps_lost_fail[other-cell]` | да |
| M3 убрать нижнюю границу (отказ не раньше диска) | `test_a4…[earlier-28ms]` и `[much-earlier]` | 4 красных: `test_a4…[earlier-28ms]`, `test_a4…[much-earlier]`, `test_refusal_hazards::test_refusal_a_millisecond_before_the_disk_does_not_close_it`, `test_refusal_hazards::test_refusal_of_the_previous_day_with_a_later_clock_time_does_not_close_the_disk` | да (плюс 2 hazard-теста) |
| M4 убрать верхнюю границу (раньше следующего диска той же ячейки) | `test_a5_refusal_after_second_disk_binds_only_to_the_second` | 4 красных: `test_a5_refusal_after_second_disk_binds_only_to_the_second`, `test_refusal_hazards::test_refusal_of_the_second_disk_does_not_close_the_first`, `test_refusal_hazards::test_refusal_with_the_next_same_cell_disk_timestamp_belongs_to_the_next_disk`, `test_refusal_hazards::test_refused_disk_with_a_repeated_cell_in_the_fill_keeps_its_fail_and_shows_the_refusal` | да (плюс 3 hazard-теста) |
| M5 отказ можно использовать повторно (снять `taken[ri] = True`) | `test_a5_one_refusal_closes_exactly_one_of_two_same_cell_disks`; разработчик утверждал, что мутант ничего не ловит | 3 красных: `test_refusal_hazards::test_refusals_in_reverse_file_order_still_bind_by_time`, `test_refusal_hazards::test_double_refusal_for_one_disk_closes_one_and_notes_the_other`, `test_refusal_hazards::test_same_refusal_line_twice_is_two_refusals_one_disk`. `test_a5_one_refusal_closes_exactly_one_of_two_same_cell_disks` зелёный | нет по имени. Утверждение разработчика «ничего не ловит» опровергнуто: мутант ловится 3 тестами |
| M6 не писать примечание «отказ без диска» | не менее 1 красного `test_a6_*` | 8 красных: `test_a6_unbound_refusal_is_a_note_and_does_not_change_exit_code`, `test_a6_unbound_refusal_does_not_turn_failing_run_into_other_code`, `test_a9_out_report_has_same_rows_and_summary_as_stdout[with-flag]`, `test_refusal_hazards::test_double_refusal_for_one_disk_closes_one_and_notes_the_other`, `test_refusal_hazards::test_same_refusal_line_twice_is_two_refusals_one_disk`, `test_refusal_hazards::test_refusal_a_millisecond_before_the_disk_does_not_close_it`, `test_refusal_hazards::test_refusal_of_the_previous_day_with_a_later_clock_time_does_not_close_the_disk`, `test_refusal_hazards::test_refusal_of_a_disk_that_has_a_job_is_a_note_not_a_warning` | да (две a6 красные) |
| M7 битая строка отказа (без `)`) считается отказом (вариант: `\)` → `\)?`, двоеточие обязательно) | `test_a7_noise_around_a_real_refusal_does_not_hide_it` и/или `test_a7_unrelated…` | 0 красных (46 passed, gate_exit=0) | нет |
| M7b то же, точный вариант: `\)?:?` (скобка и двоеточие необязательны) | то же | 0 красных (46 passed, gate_exit=0) | нет |
| M8 при отсутствии флага всё равно писать «, отказов hub 0» в ИТОГ | не менее 3 красных из `test_a1_*`, `test_a3_without_layout_system_*`, `test_a9…[no-flag]`, `test_a10` | 6 красных: `test_a1_without_layout_system_disk_without_job_is_lost_fail`, `test_a1_run1_with_one_job_block_removed_is_lost_fail`, `test_a3_without_layout_system_no_hub_field_old_format`, `test_a9_out_report_has_same_rows_and_summary_as_stdout[no-flag]`, `test_a10_run1_with_empty_layout_system_same_table_and_summary_plus_hub_zero`, `test_refusal_hazards::test_summary_without_system_has_no_hub_field_and_with_system_has_it` | да |
| M9 привязка даёт предупреждение, но FAIL остаётся (потеря) | не менее 4 красных `test_a2_*` | 25 красных; из них 5 `test_a2_*`: `…[plus-28ms]`, `…[same-timestamp]`, `…[plus-5s]`, `test_a2_reason_is_text_after_colon_of_refusal_line`, `test_a2_layout_line_in_production_format_without_word_layout_prefix`. Прочие: `test_a3_summary_has_hub_field_and_warnings_include_refusal`, `test_a5_one_refusal_closes_exactly_one_of_two_same_cell_disks`, `test_a5_refusal_after_second_disk_binds_only_to_the_second`, `test_a7_noise_around_a_real_refusal_does_not_hide_it`, `test_a9…[with-flag]`, и 14 hazard-тестов (полный список — в `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/40618340-ede3-42ee-88a0-833aff631458/scratchpad/inj_wa_out/M9.txt`) | да (5 из ≥4) |

Файлы выходов каждого прогона: `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/40618340-ede3-42ee-88a0-833aff631458/scratchpad/inj_wa_out/<M>.txt`.

Последние строки реальных выходов (пример, по одному на каждый вид результата):
- M0: `46 passed in 1.56s`, gate_exit=0
- M1: `1 failed, 45 passed in 1.54s`, gate_exit=1
- M5: `3 failed, 43 passed in 1.89s`, gate_exit=1
- M7: `46 passed in 1.65s`, gate_exit=0
- M7b: `46 passed in 1.61s`, gate_exit=0
- M9: `25 failed, 21 passed in 1.69s`, gate_exit=1

## Точные диффы мутантов

Все диффы сняты через `diff -u` от чистого файла. В строках `-`/`+` — ровно применённые замены (патчер `inj_wa_patch.py` проверял, что каждый якорь встречается в файле ровно один раз: `PATCH_OK` для всех).

M1 (`_bind_refusals`, убрано сравнение буквы):
```
-            if taken[ri] or ref.cell != disk.cell or ref.letter.upper() != disk.letter.upper() or ref.t < disk.t:
+            if taken[ri] or ref.cell != disk.cell or ref.t < disk.t:
```

M2 (`_bind_refusals`, убрано сравнение ячейки):
```
-            if taken[ri] or ref.cell != disk.cell or ref.letter.upper() != disk.letter.upper() or ref.t < disk.t:
+            if taken[ri] or ref.letter.upper() != disk.letter.upper() or ref.t < disk.t:
```

M3 (`_bind_refusals`, убрана нижняя граница «не раньше времени диска»):
```
-            if taken[ri] or ref.cell != disk.cell or ref.letter.upper() != disk.letter.upper() or ref.t < disk.t:
+            if taken[ri] or ref.cell != disk.cell or ref.letter.upper() != disk.letter.upper():
```

M4 (`_bind_refusals`, убрана верхняя граница `upper`; удалены две строки):
```
-            if upper is not None and ref.t >= upper:
-                continue
```

M5 (`_bind_refusals`, отказ не помечается использованным):
```
-            taken[ri] = True
```

M6 (`core.py`, примечания для непривязанных отказов не пишутся):
```
-    for ref in orphans:
+    for ref in []:
```

M7 (`_SYS_REFUSAL`, закрывающая скобка и двоеточие стали необязательными по-разному; здесь — только `\)?`, двоеточие обязательно):
```
-    r"\[health\] ResourceUnavailable @ robot_io\.forward\.refused: hub отказ \(буква '(.+?)', ячейка (\d+)\):\s*(.*)$"
+    r"\[health\] ResourceUnavailable @ robot_io\.forward\.refused: hub отказ \(буква '(.+?)', ячейка (\d+)\)?:\s*(.*)$"
```

M7b (`_SYS_REFUSAL`, точный вариант «без закрывающей скобки»: скобка и двоеточие необязательны):
```
-    r"\[health\] ResourceUnavailable @ robot_io\.forward\.refused: hub отказ \(буква '(.+?)', ячейка (\d+)\):\s*(.*)$"
+    r"\[health\] ResourceUnavailable @ robot_io\.forward\.refused: hub отказ \(буква '(.+?)', ячейка (\d+)\)?:?\s*(.*)$"
```

M8 (сводка ИТОГ; см. замечание о месте ниже):
```
-        hub = "" if self.hub_refusals is None else f", отказов hub {self.hub_refusals}"
+        hub = ", отказов hub 0" if self.hub_refusals is None else f", отказов hub {self.hub_refusals}"
```

M9 (потеря остаётся FAIL даже при привязке):
```
             if k in closed:
                 row.hub_reason = closed[k].reason
-            else:
-                row.add("потеря")
+            row.add("потеря")
```

## Что оставил открытым / ненадёжным

1. Правило «битая строка отказа без закрывающей скобки» (M7, M7b) тестами не защищено: оба мутанта зелёные. Причина установлена по коду: единственная битая строка в фикстуре — `test_refusal_acceptance.py`, строка 486 (`"#185 не-дата не-время [WARNING] … hub отказ (буква 'Р', ячейка 2"`). Её метка времени нечитаема, и `_LAY_LINE` (`core.py:62`) отбрасывает строку раньше `_SYS_REFUSAL`. Ни один тест не содержит строку с корректной меткой и без скобки. Настоящее доказательство потребовало бы фикстуру с корректной меткой и битым хвостом. Такой тест я не добавлял: это правка тестов, не входящая в задачу.
2. M8: в предписании место указано как `__main__.py`, но строки ИТОГ в `__main__.py` нет. Сводка формируется в `core.py`, метод `AuditResult.summary`; `__main__` печатает её. Мутант применён туда. Эквивалентность по наблюдаемому выводу подтверждена прогоном, но буквального совпадения места нет.
3. M5: предсказание лида по имени не подтвердилось. Тест `test_a5_one_refusal_closes_exactly_one_of_two_same_cell_disks` под M5 зелёный. Мутант ловится тремя hazard-тестами. Утверждение «ничего не ловит» опровергнуто фактом прогона.
4. Каждый мутант применён один раз, по одному. Комбинации мутантов и порядок не проверялись.
5. Прогоны ограничены двумя файлами (46 тестов), как предписано. Полный каталог `scripts/wire_audit/tests` (259) проверен только как базовый эталон копии, не под мутантами.
6. Гейт работал через скрипт главного checkout (`Inspector_bottles/.git/../scripts/machine_gate.sh`), потому что `--git-common-dir` у `--sa-gui` указывает на общий `.git` главного checkout.
7. Исходное дерево `--sa-gui` содержит незакоммиченные изменения до начала работы (в том числе в `scripts/wire_audit/core.py`, `__main__.py`, `README.md`, и неотслеживаемые `test_refusal_*.py`). Эти изменения не мои. Я только копировал файлы. Статус набора файлов до и после совпал: `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/40618340-ede3-42ee-88a0-833aff631458/scratchpad/inj_wa_src_status_before.txt` и `…/inj_wa_src_status_after.txt`.
8. Перед каждым мутантом в копии удалялись `__pycache__` в `scripts/wire_audit`, чтобы не получить устаревший байткод. Это касалось только копии.
