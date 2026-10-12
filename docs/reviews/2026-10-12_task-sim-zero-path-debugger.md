# sim-zero-path: ход нулевой длины роняет тик (debugger)

STATUS: FIXED (ветка `fix/robot-sim-zero-path`).

## Корневая причина

`Services/robot_comm/server/sim_core_v2.py:1016` (`pose_at` внутри `_joint_tick_capped`):
`frac = travelled / active["path_len"]`. `path_len` (`_start_move`, :693/:704/:709) равен 0,
когда цель хода совпадает с текущей позой и суставы не различаются («Домой» в HOME,
повторный MOVE в ту же точку). Деление на ноль -> `ZeroDivisionError` на каждом тике.

Воспроизведено до фикса (стек совпал с отчётом владельца):
`sim_core_v2.py:744 tick -> :971 _progress -> :1124 _progress_move -> :1043 _joint_tick_capped -> :1016 pose_at`.

## Фикс (1 строка + 2 строки комментария)

`frac = travelled / active["path_len"] if active["path_len"] > 0 else 1.0`.
При `path_len == 0` и `j_start == j_end` значение `frac` не влияет на суставы. Финал
`_progress_move` (`new_travelled >= path_len - 1e-9`) снэпит в target и идёт тем же
`_finish_done`, что обычный ход (DONE_SEQ, ACTIVITY=0, MOVING=0).

Второе место деления (:992, `_cartesian_step`): `frac = step / path_len` достижимо только
при `step < path_len`, то есть `path_len > 0` (при `path_len == 0` срабатывает `step >= path_len`
и возвращается target). Правка не нужна. Других делений на `path_len` нет
(`grep -n path_len`: строки 693/703/704/709/988/990/992/1016/1123/1129, из них делят 703 (на `speed`), 992, 1016).

## Тесты

`Services/robot_comm/tests/test_sim_v2_zero_length_move.py`:
- `test_move_to_current_pose_completes` (красный до фикса)
- `test_home_twice_does_not_raise` (красный до фикса)
- `test_fresh_core_starts_at_home_literal` (замер литерала HOME, зелёный всегда)
- `test_nonempty_joint_move_still_takes_many_ticks` (контроль: 100 мм JOINT = 6 тиков, тайминг не тронут)

## Инъекция

Предсказание: при откате охраны красные ровно `test_move_to_current_pose_completes` и
`test_home_twice_does_not_raise`. Наблюдено: `2 failed, 2 passed` (те же два). С охраной: `4 passed`.

## Счётчики

`Services/robot_comm/tests -k "sim_v2 or sim_core"`: до фикса 236 passed; после 240 passed
(236 + 4 новых), новых падений нет. `ruff check` и `ruff format --check` по двум файлам чисты.

## Что истолковано, а не выполнено буквально

- Охрана поставлена в одном месте (`pose_at`), а не в двух: второе место (:992) уже защищено
  условием `step >= path_len`.
- Ветка «path_len == 0, но j_start != j_end» (эскалация по брифу): через протокол недостижима.
  `P_SPD_J` min = 1, `speed > 0` -> при различных суставах `joint_time > 0` -> `path_len > 0`.
  Эскалацию не пишу; это вывод из чтения кода, прогоном не подтверждён.

## Что оставлено открытым / ненадёжно

- Живая кнопка «Домой» в `sim_view` не прогонялась (Qt вне FILES); проверен только core на ограниченном цикле тиков.
- Литерал 6 тиков в контроле замерен на коде до фикса; он хрупок к изменению `MAX_STEP_MM`/тика (и должен ломаться при изменении тайминга).
- `speed == 0` при `path_len == 0` не проверялся (достижима ли скорость 0 через опкоды, не проверял).
