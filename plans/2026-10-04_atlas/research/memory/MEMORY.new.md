# MEMORY.md — индекс (≤ 8 КБ, грузится в каждую сессию)
Только правила, что срабатывают до того, как о них вспомнят, и указатели. Остальное — по тегу или триггеру. Канон — `docs/claude/memory/` (git), локальная папка — кэш. Правило не уходит в архив, пока не стало механизмом (hook, skill, команда).
- Планы: `plans/queue/ORDER.md`. Handoff: `ls docs/handoffs`. Закрытые треки: [ARCHIVE.md](ARCHIVE.md).
- Ремесло, читать ПЕРЕД делом: [CRAFT-injection](CRAFT-injection.md) — инъекции, вакуумные ассерты, «ноль красных» · [CRAFT-tests](CRAFT-tests.md) — тесты, дублёры, стражи · [CRAFT-verdict](CRAFT-verdict.md) — вердикт ревью, «не может сломаться», живой дефект · [CRAFT-config-qt](CRAFT-config-qt.md) — конфиг, Pydantic, Qt.
- Поиск по тегу: `grep -l "module: X\|mechanism: X" docs/claude/memory/*.md` или `/core:memory:search`.

## 1. Правила на каждую сессию
- qex: сначала `get_indexing_status`, `last_indexed` числом; возраст — в промпт субагента (project-rules §1).
- Тесты: тестер до кода, инъекция на КАЖДОЕ свойство, ревью запуском (`.claude/CLAUDE.md` «Test authorship»).
- Ноль — результат, когда доказано, что наблюдение шло: [ноль наблюдений](feedback_zero_observations_looks_like_a_result.md), [ноль красных](feedback_injection_zero_may_mean_the_guards_were_not_collected.md). Вердикт без вход→выход — совет: [plausible](feedback_plausible_is_not_verified.md).
- Об ОТСУТСТВИИ — с парной проверкой достижимости: [файл](feedback_an_absence_assertion_needs_a_reachability_check.md). Сторож «хоть раз»/по сумме слеп: [файл](feedback_a_guard_that_counts_at_least_once_is_blind.md). Дублёр верен форме, не протоколу: [файл](feedback_a_faithful_fake_still_lacks_the_protocol.md).
- Одно дерево — один писатель, стейджить явные пути: [чужая сессия](feedback_a_peer_session_shares_the_tree.md), [commit берёт весь индекс](feedback_commit_takes_the_whole_index.md), [pre-commit + 2 агента](feedback_precommit_stash_collision_2plus_agents.md).
- Merge в main: `merge: суть` + Why/Layer/Refs ([грабли](feedback_git_main_merge_hook_traps.md)); нужен оформленный `/code-review`.
- Субагенты: `model` явно; reviewer/tester — `run_in_background: false`; писатель в worktree: [protect-branch](feedback_protect_branch_blocks_worktree_subagents.md).
- Windows: RU-вывод cp866, PYTHONUTF8 ([файл](feedback_ru_output_encoding_and_wc.md)); только проектный `.venv`; `uv sync` лишь с `--inexact` ([файл](feedback_uv_sync_prunes_venv.md)); пакеты ставит владелец; процессы — TaskStop или PID ([файл](feedback_no_global_taskkill.md)); непарный `'` ломает Bash ([файл](feedback_bash_tool_unbalanced_quote_breaks_command.md)).
- Хук жив, только если проверен настоящим входом: [CR](feedback_a_hook_dead_on_windows_by_a_trailing_cr.md). PostToolUse ruff сносит свежий импорт: [файл](feedback_ruff_strips_unused_import.md).
- Посылка плана и причина из плана — гипотезы: [посылка](feedback_a_plans_premise_expires.md), [причина](feedback_the_plans_stated_cause_is_a_hypothesis.md). Число без разброса — наблюдение: [файл](feedback_a_number_without_spread_across_repeats_is_an_observation.md).

## 2. Решения владельца (живые)
- Приоритет — маятник, порядок в `ORDER.md`: [файл](project_priority_engine_first.md). Жизненный цикл — один scope-владелец: [файл](project_universal_lifecycle_decision.md).
- Framework-first, fix-forward, FREEZE не KILL, меньше слоёв: [файл](feedback_framework_first.md). Флаг закрыт, когда удалён: [файл](feedback_flags_must_not_become_crutches.md).
- Ручки наблюдаемости: вкл/выкл на любой границе, ноль нагрузки в выключенном: [файл](feedback_observability_knobs_switchable_at_any_boundary_zero_cost_off.md) (Task 4.15).
- Один пишущий логгер: [файл](feedback_one_log_writer.md). Память одним модулем: [файл](project_memory_module_consolidation.md). Стек: [файл](reference_tech_stack_2026.md). Цель владельца: [файл](user_career_goal.md).

## 3. Окружение (local-only, Windows)
- venv держит MCP — закрыть VS Code [p:venv_locked_by_mcp](project_venv_locked_by_mcp.md); CUDA torch cu124 [p:cuda_torch_setup](project_cuda_torch_setup.md); GPU — nvidia-smi [reference_gpu_monitoring_windows](reference_gpu_monitoring_windows.md); monotonic 15.6 мс [monotonic](project_monotonic_resolution_windows.md).
- qex: [runbook](feedback_qex_full_rebuild_runbook.md), [модель по платформам](project_qex_model.md). graphify MCP: [p:graphify_mcp_setup](project_graphify_mcp_setup.md).
- Живой GUI-стенд — боевым входом, `INSPECTOR_GUI_UNATTENDED=1` [файл](project_gui_stand_production_entry_only.md); бэкенд — через backend_ctl [файл](feedback_backend_ctl_for_agents.md).

## 4. Уроки по тегам (f: = feedback_, p: = project_, без .md)
- backend_ctl: p:backend_ctl_signal_integrity · p:backend_ctl_socket_bypasses_mw · p:live_findings_webcam_2026_07 · f:cleanup_must_survive_abnormal_disconnect
- observability: p:runtime_knob_expires_in_300s · p:config_voice_belongs_to_the_apply_stage · p:observability_store_error_routing · f:a_knob_can_be_applied_and_unverifiable · f:a_shared_throttle_swallows_the_record_not_the_line
- router/switch/state: p:switch_routing_stale · p:switch_delivers_layer · p:kind_channels_dead_evict_branch · p:state_topology_gate
- config/schema: f:facade_is_a_whitelist_not_a_passthrough · f:model_copy_does_not_validate · f:deep_merge_is_not_associative · f:gui_save_strips_yaml_comments
- recipes/gui: f:recipe_knob_must_be_named_in_from_recipe · f:port_wire_is_not_a_process_route · f:widget_qt_patterns · f:modal_dialog_waits_instead_of_failing · p:calibration_gui_progress
- tests/harness: f:mp_queue_is_async_in_tests · f:wallclock_threshold_measures_the_heap · p:fencing_test_race · p:concurrent_backends_trap · p:root_gate_misses_framework_modules
- lifecycle: p:graceful_stop_debt · f:unblocking_signal_at_the_moment_of_fact · f:thread_target_pins_its_owner · f:ready_signal_meant_less_than_read
- git/agents: f:worktree_stale_base · f:agent_resume_ghost · f:walk_skips_worktrees · f:a_diff_based_rescue_omits_untracked_files · f:dual_write_by_copy_destroys_the_other_side
- hardware/perf: p:vfd_bridge_robot_reboot · p:hikvision_aspect_ratio · p:strokes_points_perf

## 5. Как писать
Урок = ловушка + замер (вход→выход) + триггер; теги `module:` и `mechanism:` во frontmatter; `/core:memory:remember`; строка индекса ≤ 170 байт. Состояние плана — в plan.md, не сюда.
