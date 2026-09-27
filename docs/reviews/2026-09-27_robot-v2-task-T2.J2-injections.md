# T2.J2 — матрица инъекций ведущего

Объект: `wt/t2j-dev` @ `5bb6c228` (реализация `1cc29d68` + `860d331b`, правки спеки ведущего `01832a71`, `8755d803`,
`2503e189`, сторож `5bb6c228`). База прогона: `Services/robot_comm/tests` — 793 passed, 5 skipped, 2 xpassed
(`QT_QPA_PLATFORM=offscreen`). Скрипт — scratchpad сессии (`t2j2/inject.py`): текстовая правка закоммиченного файла →
полный прогон → `git checkout`; дерево чистое до и после. Ожидаемый набор записан до прогона.

| # | Поломка | Ожидалось упасть | Итог |
|---|---|---|---|
| I1 | проверка пределов снята | seam_beyond_j1, joint_limits_from_model_spec | ✓ + `test_resolve_joint_target_checks_every_joint_not_only_j4` (тест автора) |
| I2 | нарушение предела уходит в декартов фолбэк | seam_beyond_j1, joint_limits_from_model_spec, j4_no_turn | ✓ точно |
| I3 | `TLM_HAND = P_HAND` только при DONE | hand_after_stop_mid_flip | ✓ точно (первая версия инъекции была неверной формы — без присвоения при DONE — и дала ложное расхождение) |
| I4 | `joints()` через `ik` позы | joints_is_state, hand_after_stop, j4_nearest | ✓ точно |
| I5 | сырой J4 | j4_nearest | ✓ + `test_zone_rz_max_boundary[360-accept]` |
| I5b | J4 ближайший к сырому, не к текущему | j4_nearest | ✓ точно |
| I6a | без суставного члена длительности | duration_follows_slowest_joint | ✓ точно |
| I6b | без декартова пола | тайминг-тесты T2.2 | ✓ 31 тест (core/motion) |
| I7 | без `MAX_STEP_MM` в суставной ветке | explicit_large_dt_capped | ✓ точно |
| I7b | без декартова потолка (бисекции) | seam_other_hand, explicit_large_dt | ✓ + hand_after_stop |
| I8 | пределы захардкожены в sim | тесты с моделью из spec | ✓ 8: joint_limits_from_model_spec, j4_no_turn, 6 тестов зоны на `_NO_JOINT_LIMITS` |
| I9 | состояние не следует LINE | line_keeps_joint_state_in_sync | ✓ + 4 (unreachable/None-пути, hand_after_stop) |
| I10 | без клэмпа позы к зоне в `_progress_move` | seam_other_hand | **✗ ничего не упало** → сторож `test_registered_pose_stays_in_zone_at_stretched_arm` (`5bb6c228`); повтор: ✓ падает только он |
| I11 | (T2.J) конец пути по `TLM_HAND` | stretched_arm, joints_is_state, hand_after_stop | ✓ + 5 |

## Находки по ходу (для ревью)

- **I10:** клэмп реально менял позу 16 раз за прогон, но ни один тест его не держал: тест свойства 1 перестал
  проходить вытянутую руку после того, как потолок шага сдвинул сетку тиков. Поза `(574.1, -174.4)` (r ≈ 600.03 при
  r_max 600) выходила наружу молча в `test_joint_arrival_with_pending_soft_still_updates_hand`.
- **Разрыв RZ в регистрах:** в `test_j4_takes_nearest_turn_within_limits` J4 = -185 (правило cto), поза RZ посреди хода
  -360.7 … -436, при DONE — ровно цель 284. Физически тот же угол (+720), в регистре — скачок; лента RZ(t) T2.W его покажет.
  Промежуточные позы выходят за зону RZ ±360.
- Модель без пределов (`_NO_JOINT_LIMITS`) проводит суставный путь через запретный сектор (`test_jog_cont_zone_edge…`:
  позы с углом ≈ ±170°) — ожидаемо для искусственной модели, но это ровно та прямая, от которой защищают пределы.

## Сам ошибся

- Первая версия I3 была неверной формы (см. таблицу).
- Сторож I10 сначала закоммичен красным: `check_point(ws, p)` вместо `check_point(ws, *p)`, а код возврата pytest съел
  `tail` в конвейере; «I10 OK» в том прогоне был ложным. Исправлено в том же коммите (`--amend`), повтор честный.
