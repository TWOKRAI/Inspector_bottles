# MEMORY.md — индекс памяти проекта

## Пользователь и окружение
- [graphify-MCP setup](project_graphify_mcp_setup.md) — uv tool install --with mcp; .graphifyignore
- Окружение: [uv sync сносит необъявленное](feedback_uv_sync_prunes_venv.md) → --inexact · [venv держит MCP](project_venv_locked_by_mcp.md) → закрыть VS Code · [всегда project .venv](feedback_always_project_venv.md) · [пакеты ставит пользователь](feedback_package_install_by_user.md)
- [RU-вывод и wc врут](feedback_ru_output_encoding_and_wc.md) — cp866; 0xA0 · [Think EN, speak RU](feedback_think_en_speak_ru.md)
- [monotonic Win = 15.6 мс](project_monotonic_resolution_windows.md) — разности <100 мс на сетку
- [No global taskkill](feedback_no_global_taskkill.md) — только TaskStop или PID
- [CUDA torch](project_cuda_torch_setup.md) — cu124 колесом; PyPI даёт +cpu
- qex: [таймаут реиндекса](project_qex_reindex_timeout.md) — свежесть по last_indexed · [бюджет = выгрузка эмбеддера](feedback_qex_reindex_budget.md) — keep_alive=-1 → 12 мин

## Стоящие правила владельца
- [Приоритет: ДВИЖОК первым](project_priority_engine_first.md) — прототип = параллельный стенд
- [Framework-first](feedback_framework_first.md) — framework универсален, прототип расходный · [Fix forward](feedback_fix_framework_forward.md) — улучшение, не удаление
- [Fewer layers](feedback_fewer_layers.md) — меньше слоёв строго лучше · [всё через BaseManager](feedback_all_components_base_manager.md) · [три менеджера — одна база](feedback_three_managers_share_base.md) · [Logger/Error/Stats через менеджеры](feedback_logger_error_stats_managers.md) — ObservableMixin
- [Constructor modularity](feedback_constructor_modularity.md) — pluggable/testable/composable
- [MVP для GUI-вкладок](feedback_mvp_pattern.md) — всегда полный · [Tab order](feedback_tab_order.md) — Settings → Recipes → функциональные
- [Services vs Plugins](project_services_vs_plugins.md) — крупный SDK vs мелкая обработка
- [Флаги не костыли](feedback_flags_must_not_become_crutches.md) — закрыт когда УДАЛЁН · [FW_* реестр](project_feature_flags_registry.md) — ctor>env>default
- [Фичи после доказательства](feedback_tool_features_before_validation.md) — минимум → реальная задача → фичи
- [Model economy](feedback_model_economy_scheme.md) — Fable на вердикты; финдеры Sonnet/Opus
- [Один пишущий логгер](feedback_one_log_writer.md) — остальное вид поверх · [std_facade не используется](project_std_facade_unused.md) — 76 файлов в пустоту

## Активные проекты и долги
- [line_sim: план создан](project_line_sim_vision.md) — буквы первыми; встроенная сборка; правда в v1; plans/line-sim/ Ф0–Ф6 (19 задач), ветка feat/line-sim
- [backend_ctl](project_backend_ctl_framework_module.md) — Phase 0+2 в main, 8.0/10; резидуалы в backend-ctl-hardening · [ловушки](project_backend_ctl_signal_integrity.md) — ложный success/timeout; сокет мимо receive-мидлвари · [MCP только через RouterManager](project_backend_control_mcp.md)
- [Диагностика — через backend_ctl](feedback_diagnose_live_system_with_backend_ctl.md) — соседи как контроль
- [GUI-стенд боевым входом](project_gui_stand_production_entry_only.md) — INSPECTOR_GUI_UNATTENDED=1; harness виснет в initialize
- [Command-engine audit](project_command_engine_audit.md) — ActionBus мёртв; RBAC дыра
- [Pipeline узлы](project_pipeline_node_plugin_containers.md) — нода=плагин в контейнере; MovePlugin долг · [reuse по plugin_name](feedback_pipeline_reuse_plugins_widgets.md) — gui protected
- [Workers runtime](project_processes_workers_runtime.md) — live-телеметрия DONE; assigned_worker PENDING · [архитектура](project_workers_architecture.md) — WorkerManager · [timing](project_worker_cycle_timing.md)
- [Transport hub](project_transport_router_hub.md) — P0-P2 DONE; P3 отложен
- [Graceful-stop debt](project_graceful_stop_debt.md) — 5с-ханг; stop_all_workers/put()
- [Camera settings](project_camera_settings_feature.md) — пресеты+actual; MJPG-долг · [Hikvision 4:3](project_hikvision_aspect_ratio.md) — иначе эллипсы
- [Line filter](project_line_filter_feature.md) — 0-3 DONE; overlay_draw пишет frame
- [Device hub](project_device_hub.md) — always-on, YAML-протоколы, Ф0-5 DONE; NEXT device-tree-recipe
- Рецепты: [save/load FIXED×2](project_recipe_save_load_arch.md) — долги on_result/switch≠boot · [join key FIXED](project_recipe_inspector_join_key.md) · [hikvision_letter ROI](project_hikvision_letter_robot.md) — 560,240,800,600
- [Draw mode rework](project_draw_mode_rework.md) — feat/draw-mode-rework; hardware pending
- [Pult panel](project_pult_control_panel.md) — контролы→сигналы; robot_draw live
- [Phone gateway](project_phone_gateway_service.md) — v1 готов, GUI follow-up
- [VFD bridge](project_vfd_bridge_robot_reboot.md) — зависший ПЧ лечится перезагрузкой РОБОТА
- [ML-сервисы](project_ml_train_service.md) — ml_train v1, dataset-gen (центр (size-1)/2), буква+угол 33/33
- [app_module Win test debt](project_app_module_windows_test_debt.md) — 2 красных только на Windows
- [Kind-channels мёртвая ветка](project_kind_channels_dead_evict_branch.md) — send блокирует 1с вместо drop_oldest
- [Гейт топологии state](project_state_topology_gate.md) — FW_STATE_TOPOLOGY_GATE, пара ON/OFF
- [macOS SHM](project_macos_shm.md) — 15 skipped; user на Win+Mac
- [Gorynych PyPI deferred](project_gorynych_pypi_deferred.md) — триггеры: ок работодателя + потребитель + прод
- [Component Design System](project_component_scoped_styles.md) — DEFERRED
- [Live-находки webcam 07](project_live_findings_webcam_2026_07.md) — ротация молчит; 23% ошибок невидимы
- [fw_version из git](project_fw_version_from_git.md) — 2.0.0+hash[.dirty]; nosec последним

## Закрытые треки (сводно)
- Observability: [Ф2–Ф8 + роадмап](project_f8_review_and_stitching.md) — актуальное в plans/observability-roadmap.md · [хвост-ремонт](project_observability_tail_repair.md) — гейт 6855×3; вход в этап 6 открыт · [telemetry read-model ADR-136](project_gui_telemetry_read_model.md) · [self-publish DB-sink](project_telemetry_self_publish.md) · [webcam фриз](project_webcam_sketch_freeze.md) — IPC-шторм · [gui задушен очередью](project_gui_system_queue_storm.md) — грабли: гонка тихой потери
- Конструктор/GUI: [фазы DONE](project_generic_process_vision.md) — GenericProcess deprecated · [Ф7 Phase G 8.0](project_phase_g_final_review.md) — seqlock, QoS-кольца SHM, флип-лесенка · [Registries v2](project_service_registry.md) — ADR-129…132 · [Pipeline recipe-launch](project_pipeline_recipe_driven_launch.md) — hot-apply не подключён · [Switch stale](project_switch_routing_stale.md) — live через PM-хаб
- [Fencing-тест ADR-SS-019](project_fencing_test_race.md) — ghost-гонка закрыта

## Канон тестирования
- [Три роли авторства](feedback_test_authorship_three_roles.md) — tester от acceptance, ревьюер запуском · [тестер всегда + инъекции против него](feedback_tester_always_and_inject_against_it.md) — его зелёный не результат
- [Три объектива — три класса](feedback_three_lenses_three_defect_classes.md) — тесты=механика, прогон=проводка, ревью=связки
- [Ревью ловит стык своих кусков](feedback_review_finds_the_seam_between_own_pieces.md) · [ревью спеки — независимым](feedback_spec_review_needs_independent_agent.md) — автор находит карту, не форму
- [Правдоподобное ≠ проверенное](feedback_plausible_is_not_verified.md) · [вердикт по одному маркеру врёт](feedback_single_marker_verdict_lies.md) — пара маркеров + признак жизни
- [Subagent live = синхронно](feedback_subagent_live_test_monitor_hang.md)
- [Красный — сперва на main](feedback_check_red_on_main_first.md) · [подпись гейта живёт на HEAD](feedback_gate_signature_lives_on_a_head.md) — коммит после подписи = пере-прогон

## Инъекции поломок
- [Тест не доказан без красного](feedback_prove_test_red_without_fix.md) — откат stash, счёт арифметикой
- [Предсказание — после всех тестов](feedback_predict_injections_after_writing_tests.md) · [на общем корпусе — MUST поимённо](feedback_injection_prediction_on_a_shared_corpus.md) + потолок красных
- [Покрывать ВСЕ точки правила](feedback_injection_must_cover_all_check_sites.md) · [слишком грубая не доказывает](feedback_injection_too_coarse_proves_nothing_specific.md) · [негодная ≠ вакуум](feedback_broken_injection_is_not_a_vacuous_test.md) — ERROR vs FAILED
- [Откат — восстановлением](feedback_injection_rollback_by_restore_not_replace.md) — обратная замена задевает соседа · [дубль обязан блокировать](feedback_double_must_block_like_the_original.md)
- [Тест, переживший свой слом](feedback_test_survived_its_own_break.md) — шов сквозь RLock · [ноль красных = лишний слой](feedback_zero_reds_can_mean_a_useless_layer.md)

## Вакуумные тесты и ассерты
- [Молчащий детектор](feedback_silent_detector_proves_nothing.md) — сперва покажи красным · [тест, поднимающий ошибку сам](feedback_test_raising_the_error_itself_guards_the_branch.md) — сторожит except
- [Ассерт по подстроке](feedback_substring_assert_passes_on_the_wrong_branch.md) — текст+уровень, инъекция в соседнюю ветку · [отсутствие при extra=ignore](feedback_absence_assertion_under_extra_ignore_is_vacuous.md) — model_fields_set
- [Числа рядом с дефолтом](feedback_test_values_near_defaults_test_the_default.md) · [совпадение констант](feedback_coinciding_constants_hide_opposite_implementations.md) — брать где расходятся · [одна функция — две позиции](feedback_one_function_two_positions.md)
- [Дубль фикстуры](feedback_duplicate_fixture_verifies_itself.md) — расходится с conftest молча · [параметризация из испытуемого](feedback_parametrization_built_from_the_subject_collapses_with_it.md)
- [Фальшивка-всегда-успех](feedback_fake_that_always_succeeds_mutes_the_gate.md) — дубль обязан уметь отказывать · [нет получателя — нет суда](feedback_absent_receiver_lets_a_test_pin_an_impossible_input.md)
- [Одиночное чтение](feedback_single_reader_test_misses_multi_reader_defect.md) · [второй потребитель вскрывает](feedback_second_consumer_reveals_the_defect.md) — зелено поодиночке
- [mp.Queue асинхронна](feedback_mp_queue_is_async_in_tests.md) — учёт на queue.Queue · [порог по часам меряет кучу](feedback_wallclock_threshold_measures_the_heap.md) — окно с gc.disable
- [Глобальный патч часов = флейк](feedback_global_clock_patch_flake.md) — часы — зависимость объекта
- [Дельта, а не размер](feedback_measure_delta_not_file_size.md) · [счёт строк не ловит петлю](feedback_row_count_never_catches_the_loop.md) — судить серии внутри записи
- [Тесты-невидимки](feedback_tests_invisible_to_testpaths.md) — судить по конфигу прогона · [выключатель дискриминатора](feedback_discriminator_switch_must_be_verified.md) — счётчик collected
- [Зелёный прогон и синхронность](feedback_green_run_hides_synchronous_only_correctness.md) — замыкание дефолт-аргументом
- [Барьер на входе ≠ гонка](feedback_barrier_at_entry_does_not_reproduce_the_race.md) — рандеву на операцию
- [Транзитивный GUI-backend](feedback_transitive_gui_backend_in_tests.md) — matplotlib+PySide6=qtagg; Agg-страховка

## Предохранители и механизмы
- [Два предохранителя](feedback_two_safeguards_hide_which_one_holds.md) — снимай все кроме проверяемого · [новый страж ослабляет старого](feedback_a_new_guard_can_weaken_an_old_one.md)
- [Защита достижима](feedback_guard_must_be_reachable.md) — TypeError раньше защиты · [защита базы мертва у наследника](feedback_base_guard_dead_in_heir.md) — config=None обходит
- [Страж существования ≠ содержимого](feedback_guard_on_existence_is_not_a_guard_on_content.md) — ложь прожила 3 месяца · [зонный страж не закрывает класс](feedback_zone_guard_never_closes_the_class.md) — реестр исключений
- [Порог-сумма прячет слепоту](feedback_guard_threshold_hides_partial_blindness.md) — судить поимённо · [процессный счётчик — не по ключу](feedback_process_counter_is_not_per_key.md) — атрибуция эмитентом
- [Предохранитель-НЕ-операция](feedback_safeguard_can_be_a_noop_with_green_units.md) · [названный механизм — не обязательство](feedback_named_mechanism_is_not_a_commitment.md) — проверка отказом · [докстринг vs регистрация](feedback_docs_assert_what_registration_never_set.md)
- [Сверка копий не видит оригинал](feedback_mirror_check_never_reads_the_original.md) — читать из источника · [«упоминаний = 0» стирает причину](feedback_zero_mentions_criterion_erases_the_reason.md)
- [Одна дверь — две дороги](feedback_one_door_two_roads_needs_two_guards.md) — запрет на обеих · [одна ручка из пары](feedback_test_setting_one_handle_of_a_pair_measures_priority.md) — чистить соседнюю
- [Защищать единицу конкуренции](feedback_protect_the_unit_of_contention.md) · [шов при ПОЛНОМ отпускании](feedback_seam_must_fire_on_full_release.md) — RLock: счёт глубины
- [Алиас держит объект](feedback_alias_keeps_the_object_alive.md) — владение единственному · [поток в target держит владельца](feedback_thread_target_pins_its_owner.md) — 23 утечки, AV прекратился
- [Цена хука на горячем пути](feedback_hot_path_hook_must_be_priced.md) — дельтой против цены эмиссии
- [Кэш прячет однократность](feedback_cache_hides_the_once_only_property.md) — варьировать по ключу кэша

## Классы дефектов (живьём)
- [«Проглоченный сбой»](feedback_swallowed_failure_class.md) — следствие без причины хуже отсутствия · [тревога ↔ тихая потеря](feedback_false_alarm_traded_for_silent_loss.md) — тестируй ПОСЛЕДОВАТЕЛЬНОСТЬ
- [drop_oldest отвечает success](feedback_drop_oldest_reports_success.md) — потеря видна счётчиком, не статусом
- [Побочный эффект и транзакция](feedback_side_effect_must_not_undo_the_transaction.md) — раздача в своём try · [отказ после записи травит соседа](feedback_refusal_after_the_write_poisons_the_neighbour.md)
- [«Готов» означал меньше](feedback_ready_signal_meant_less_than_read.md) — окно до регистрации · [идемпотентность ≠ монотонность](feedback_idempotent_is_not_monotonic.md) — признак свежести
- [Сигнал в ветке слепнет](feedback_signal_placed_in_a_branch_goes_blind.md) — где известен результат · [отметка после публикации](feedback_post_publication_mark_breaks_collapsing.md) — страж КЛАССА
- [Дефект на одном пути из трёх](feedback_defect_fixed_on_one_path_only.md) — воскрешения на развилках
- [Рождён неверным, починен после](feedback_born_wrong_then_fixed_looks_like_working.md) — чинить в точке создания
- [Шаговая операция требует вычерпывания](feedback_stepwise_statement_needs_draining.md) — 1 шаг из 2116 = «успех»
- [«Главный источник» может быть 3%](feedback_named_main_cause_may_be_a_minor_share.md) — мерь долю до правки
- [Снос оставляет хвост](feedback_removal_leaves_a_tail_in_the_neighbour.md) — дифф не видит · [уборка переживает разрыв](feedback_cleanup_must_survive_abnormal_disconnect.md) — три формы смерти клиента
- [Модалка ждёт клика](feedback_modal_dialog_waits_instead_of_failing.md) — страж BaseException + прогон-разведка
- [PRAGMA молчит об отказе](feedback_sqlite_pragma_fails_silently.md) — порядок до WAL

## Конфиг и схемы
- [Dict at Boundary GUI](feedback_dict_at_boundary_gui.md) — виджеты только dict, не live SchemaBase
- [model_copy не валидирует](feedback_model_copy_does_not_validate.md) — dict вместо схемы молча · [материализованный дефолт](feedback_materialized_default_hides_absence.md) — сверять с model_fields[].default
- [Merge меняет ФОРМУ](feedback_merge_changes_the_form.md) · [форма доставки различается](feedback_config_delivery_shape_differs.md) — PM плоско, ребёнок весь proc_dict
- [update_config мёртв при живом handler](feedback_config_update_dead_with_handler.md) — читать как потребители
- [Ручка-из-env читает свою запись](feedback_env_knob_reads_its_own_write.md) — снимок env на старте · [runtime-конфиг умирает с процессом](feedback_runtime_config_dies_with_the_process.md) — рестарт берёт с диска
- [Дефолт сверху отключает защиту снизу](feedback_upper_layer_default_disables_the_guard_below.md) — молчание вниз как молчание
- [Фасад — белый список](feedback_facade_is_a_whitelist_not_a_passthrough.md) — три точки: схема, фасад+expand, readback
- [Ручка рецепта — в extras](feedback_recipe_knob_must_be_named_in_from_recipe.md) — metadata не доезжает; доказывать сборкой · [путь сверять с публикатором](feedback_default_path_must_match_publisher.md) — drops_count vs drops
- [Ключ из уже едущей секции](feedback_read_the_key_from_the_section_already_travelling.md) — model_dump выбросит
- [«Не деградировало» = идентичность сборки](feedback_no_regression_proved_by_identical_build.md) — proc_dict ключ-в-ключ

## IPC, роутинг, планы
- [Register routing hang](feedback_register_routing_hang.md) — FieldRouting без канала = фриз GUI
- [No SHM hacks](feedback_no_shm_hacks.md) — только framework middleware · [провод портов ≠ маршрут](feedback_port_wire_is_not_a_process_route.md) — плагин не вызван молча
- [Посылка плана устаревает](feedback_a_plans_premise_expires.md) — блокер воспроизводить, не сверять номера
- [Plan-Driven Dev](project_plan_driven_dev.md) — slug, Refs-trailer · [checkboxes [x]+hash](feedback_plan_checkboxes.md) · [dual-save](feedback_plan_dual_save.md)
- [Один активный план](feedback_one_active_plan_per_tool.md) — иначе воскрешение отменённых задач
- [Спека может врать](feedback_plan_spec_can_lie.md) — имя поля сверять с кодом · [позиционный вызов прячет имена](feedback_positional_call_hides_parameter_name_drift.md) — падало на duration=
- [Commit msg format](feedback_commit_msg_format.md) — хук терпит перенос; ruff → re-stage · [commit забирает весь индекс](feedback_commit_takes_the_whole_index.md) · [agent commit quality](feedback_agent_commit_quality.md) — транслит amend
- [Parallel agents commit race](feedback_parallel_agents_commit_race.md) — макс 2 без worktree; при одном файле — worktree от HEAD

## Qt / GUI
- [Qt widget patterns](feedback_widget_qt_patterns.md) — setFlags recursion, blockSignals, EditTriggers · [qt-mcp smoke+probe](feedback_qt_mcp_smoke_verification.md) — QT_MCP_PROBE=1:9142; чистка по PID
- [qt-mcp: флаг дословно](feedback_qt_mcp_flag_value_is_compared_verbatim.md) — «1:9142» промолчало; рендер не проверялся 3 раунда
- [GUI-save сносит yaml-комменты](feedback_gui_save_strips_yaml_comments.md) — git diff перед add

## Только в git-версии (жив вне локали)
- [pre-commit stash collision 2+ агента](feedback_precommit_stash_collision_2plus_agents.md) — рвётся под конкурентными коммитами; cap 2-3 ретрая; recovery `git show :path > path`
- [fencing-token топологии](project_topology_fencing_token.md) — требование владельца: message-fence по incarnation/epoch
- [авто-рестарт всех процессов](project_all_process_autorestart.md) — идея владельца: default-on + громкая наблюдаемость
- [qex/codegraph/serena/graphify напрямую](feedback_use_graph_semantic_tools.md) — не только через Explore
- [Константа из физики, а не из замера](feedback_constant_from_domain_physics_not_measured.md) — 99.28 % наблюдений ниже первой границы; инъекции такое не ловят
- [Симметрия имён при разных периодах](feedback_symmetric_names_with_different_periods.md) — хуже названной асимметрии; читается неверно молча
