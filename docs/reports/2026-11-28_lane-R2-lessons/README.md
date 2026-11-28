# Уроки полосы Р2, ждущие места в памяти проекта

Это уроки в формате `docs/claude/memory/`, но лежат здесь: указатель `BY-MODULE-mechanism.md` упёрся в предел
`MAX_FILE_BYTES = 80000` (`scripts/memory/by_module.py:16`). На `main` 2026-11-28 он 79 513 байт, и каждый новый урок
любой полосы роняет `scripts/validate.py`, проверку 9.

Что сделать: разделить указатель по частям (или поднять предел), перенести файлы обратно в `docs/claude/memory/`,
поправить метки (`services` → `services/device_hub`; `coordination`, `state`, `ipc` нет в `TAGS.yaml`) и выполнить
`python scripts/memory/search.py --by-module --write`.

| Файл | О чём |
|---|---|
| `feedback_a_late_test_edit_needs_the_whole_test_dir.md` | после поздней правки теста прогонять весь каталог |
| `feedback_gate_extend_adds_minutes.md` | `machine_gate.sh extend` прибавляет минуты к остатку |
| `feedback_operator_stop_is_tested_while_the_robot_moves.md` | «Стоп» проверять, пока робот движется |
| `feedback_robot_v2_params_need_a_config_epoch_change.md` | параметры робота v2 требуют смены `config_epoch` |
| `feedback_save_the_full_test_log_of_a_gate_run.md` | сохранять полный журнал прогона |
| `feedback_shared_store_row_cap_evicts_rare_kinds.md` | общий потолок строк вытесняет редкие записи |
| `feedback_state_merge_cannot_delete_keys.md` | `merge` в состоянии не удаляет ключи |
| `feedback_taskstop_may_leave_a_gate_waiter_alive.md` | TaskStop не убивает дочерние процессы |
