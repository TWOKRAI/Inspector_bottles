# Падающие тесты Plugins/sim + Services/line_sim (замер 2026-09-29)

Замер после слияния `feat/line-sim-f6` и `feat/line-sim-layer-editor` в main (`f8d39a89`).
Команда: `PYTHONPATH=$PWD python -m pytest -q --tb=no Plugins/sim Services/line_sim` из корня worktree, Windows.
Результат: 13 failed / 549 passed / 3 skipped. Повторный прогон упавших: 10 упали снова, 3 прошли.

**Слияния новых падений не внесли.** Те же 10 падают на main до слияний (`8441b531`, там всего 28 падений). Они существовали и раньше, чинятся отдельно.

## Стабильные (10), упали в обоих прогонах и на базе

| Тест | Симптом | Похоже на |
|------|---------|-----------|
| `robot_host/tests/test_acceptance_time_wait.py::test_precondition_plain_bind_on_time_wait_port_raises_eaddrinuse` | DID NOT RAISE OSError | семантика bind на TIME_WAIT у Windows |
| `robot_host/tests/test_faults_hazards.py::test_start_listener_raises_when_port_taken_by_foreign` | DID NOT RAISE RuntimeError | то же, сокет на Windows |
| `robot_host/tests/test_acceptance_wire.py::test_a3_collapse_runs` | AssertionError | журнал wire, схлопывание повторов |
| `robot_host/tests/test_journal_wire.py::test_wire_collapses_consecutive_repeats` | AssertionError, запись `n=303` не схлопнута | то же |
| `scene_source/tests/test_scene_source_hazards_1_2a.py::test_commit_keeps_file_mode` | tmp остаётся 0600 | POSIX-права на Windows |
| `scene_source/tests/test_scene_source_hazards_3_6.py::test_h8_relative_background_texture_resolved_from_repo_root_not_cwd` | ValueError: path is on mount 'C:', start on mount 'D:' | `os.path.relpath` между дисками (temp на C:, репо на D:) |
| `scene_source/tests/test_scene_source_task_3_6.py::test_texture_channel_order_in_frame` | ValueError: mount 'C:' / 'D:' | то же |
| `line_sim/tests/test_acceptance_1_1b_font_tool.py::test_font_tool_writes_centered_black_letters_per_font` | не разбирался | не разбирался |
| `line_sim/tests/test_hazards_1_0_paths.py::test_save_as_on_windows_writes_forward_slashes` | не разбирался | не разбирался |
| `line_sim/tests/test_lead_1_1b.py::test_font_tool_rejects_letter_wider_than_canvas_and_writes_nothing` | не разбирался | не разбирался |

Колонка «Похоже на» — предположение по тексту ошибки, причины не проверялись.

## Плавающие (3), упали один раз из двух

- `pult_web/tests/test_acceptance_5_3a.py::test_truth_routes_forbidden_host_403`
- `pult_web/tests/test_pult_web_hazards.py::test_non_json_content_type_rejected_415`
- `robot_host/tests/test_hazards.py::test_watchdog_holds_lock_across_mailbox_read_and_stop`

Первые два — из семейства флейка радиуса pult_web (дренаж тела на ранних отказах, `OPEN_QUESTIONS.md`). В базовом замере плавали и другие тесты этого файла, в финальном их уже нет. Пока это наблюдение, а не подтверждение, что 1.2h флейк вылечила.

## Не охвачено

Прогон только `Plugins/sim` и `Services/line_sim`. Остальной репозиторий не гонялся.
