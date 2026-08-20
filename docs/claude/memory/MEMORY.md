# MEMORY.md — индекс памяти проекта

Три уровня. Здесь только **живое**: правила, окружение, открытые долги.
- [CRAFT.md](CRAFT.md) — ремесло: тесты, инъекции, предохранители, классы дефектов, конфиг/схемы, Qt (~110 записей)
- [ARCHIVE.md](ARCHIVE.md) — история закрытых фаз и треков

Ни один из них не грузится сам — читать по триггеру, указанному в блоке-указателе.
Правило не архивируется никогда: оно обязано сработать раньше, чем о нём вспомнят.

## Пользователь и окружение
- [Цель владельца](user_career_goal.md) — ведущий инженер-электроник, соло с Claude; Inspector_bottles = ключевое портфолио, цель стать программистом
- [Стек 2026](reference_tech_stack_2026.md) — сверяться с docs/direction/TECH_STACK_2026.md при правках стека/перфа/зависимостей
- [graphify-MCP setup](project_graphify_mcp_setup.md) — uv tool install --with mcp; .graphifyignore
- Окружение: [uv sync сносит необъявленное](feedback_uv_sync_prunes_venv.md) → --inexact · [venv держит MCP](project_venv_locked_by_mcp.md) → закрыть VS Code · [всегда project .venv](feedback_always_project_venv.md) · [пакеты ставит пользователь](feedback_package_install_by_user.md)
- [RU-вывод и wc врут](feedback_ru_output_encoding_and_wc.md) — cp866; 0xA0 · [Think EN, speak RU](feedback_think_en_speak_ru.md)
- [monotonic Win = 15.6 мс](project_monotonic_resolution_windows.md) — разности <100 мс на сетку
- [No global taskkill](feedback_no_global_taskkill.md) — только TaskStop или PID
- [CUDA torch](project_cuda_torch_setup.md) — cu124 колесом; PyPI даёт +cpu · [GPU-мониторинг Win](reference_gpu_monitoring_windows.md) — Task Manager прячет CUDA, смотреть nvidia-smi/Compute_0
- qex: [таймаут реиндекса](project_qex_reindex_timeout.md) — свежесть по last_indexed · [бюджет = выгрузка эмбеддера](feedback_qex_reindex_budget.md) — keep_alive=-1 → 12 мин

## Стоящие правила владельца
- [Приоритет — маятник по свободному времени](project_priority_engine_first.md) — 2026-08-18: к стенду за видимым результатом; фреймворк — вторая полоса; окно codemod — по паузе, не по дате
- [Framework-first](feedback_framework_first.md) — framework универсален, прототип расходный · [Fix forward](feedback_fix_framework_forward.md) — улучшение, не удаление · [FREEZE, не KILL](feedback_freeze_over_kill.md) — мёртвый код замораживать
- [Fewer layers](feedback_fewer_layers.md) — меньше слоёв строго лучше · [всё через BaseManager](feedback_all_components_base_manager.md) · [три менеджера — одна база](feedback_three_managers_share_base.md) · [Logger/Error/Stats через менеджеры](feedback_logger_error_stats_managers.md) — ObservableMixin
- [Constructor modularity](feedback_constructor_modularity.md) — pluggable/testable/composable · [неиспользуемый путь = контракт](feedback_unused_paths_are_contracts.md) — «нет вызывающих» ≠ «не нужен», квалифицировать громко
- [MVP для GUI-вкладок](feedback_mvp_pattern.md) — всегда полный · [Tab order](feedback_tab_order.md) — Settings → Recipes → функциональные · [конвенции диалогов](feedback_dialog_conventions.md) — Сохранить (default)/Не сохранять/Отмена
- [Services vs Plugins](project_services_vs_plugins.md) — крупный SDK vs мелкая обработка
- [Флаги не костыли](feedback_flags_must_not_become_crutches.md) — закрыт когда УДАЛЁН · [FW_* реестр](project_feature_flags_registry.md) — ctor>env>default
- [Фичи после доказательства](feedback_tool_features_before_validation.md) — минимум → реальная задача → фичи
- [Один пишущий логгер](feedback_one_log_writer.md) — остальное вид поверх · [std_facade не используется](project_std_facade_unused.md) — 76 файлов в пустоту
- [Память одним модулем](project_memory_module_consolidation.md) — фасад/интерфейс, не размазывать по framework
- [qex/codegraph/serena/graphify напрямую](feedback_use_graph_semantic_tools.md) — не только через Explore

## Агенты, ревью, git
- [Model economy](feedback_model_economy_scheme.md) — Fable на вердикты; финдеры Sonnet/Opus · [сплит исполнение/ревью](feedback_model_split_impl_vs_review.md) — Sonnet 5 дефолт, Opus 4.8 верхний край, Fable план/свод · [три уровня ревью](feedback_review_economy_tiers.md) — полное 8-угловое только на рисковые
- [Оформленное ревью до merge](feedback_formal_review_before_merge.md) — классификатор блокирует merge без /code-review в транскрипте
- [Отлаживать через backend_ctl](feedback_backend_ctl_for_agents.md) — не через GUI и не через qt-mcp · [Layer: mixed](feedback_backend_ctl_layer_mixed.md) — хук не знает значения tools
- [Оффскрин для агентских прогонов](feedback_no_qt_popups_offscreen.md) — QT_QPA_PLATFORM=offscreen, иначе Qt-окно вешает агента
- [Резюм агента родит призрака](feedback_agent_resume_ghost.md) — SendMessage может дать ДВА инстанса, проверять mtime зоны
- worktree: [стейл-база](feedback_worktree_stale_base.md) — проверять базу до старта · [при одном файле](feedback_worktree_for_parallel_samefile.md) — от committed HEAD · [walk обязан исключать .claude/worktrees](feedback_walk_skips_worktrees.md)
- [Parallel agents commit race](feedback_parallel_agents_commit_race.md) — макс 2 без worktree · [pre-commit stash collision 2+](feedback_precommit_stash_collision_2plus_agents.md) — recovery `git show :path > path` · [откат pre-commit ест незастейдженное](feedback_precommit_rollback_drops_unstaged_edits.md) — потеря выглядит как чистый статус
- [Грабли merge в main](feedback_git_main_merge_hook_traps.md) — `git merge -F -` не читает stdin; protect-branch блокирует commit на main · [stash pop чужого стеша](feedback_git_stash_pop_wrong_stash.md) — маркеры конфликта в дереве
- [Commit msg format](feedback_commit_msg_format.md) — хук терпит перенос; ruff → re-stage · [commit забирает весь индекс](feedback_commit_takes_the_whole_index.md) · [agent commit quality](feedback_agent_commit_quality.md) — транслит amend
- [ruff сносит свежий импорт](feedback_ruff_strips_unused_import.md) — импорт и его использование ОДНИМ Edit
- [API MCP дрейфует](feedback_mcp_tool_api_drift.md) — ROUTING.md может врать · [sentrux depth непрозрачна](feedback_sentrux_depth_opaque.md) · [sentrux gate сужен](feedback_sentrux_gate_narrowed.md) — блок только циклы↑/god↑
- [Атрибутируй источник до реза](feedback_attribute_the_source_before_cutting.md) — агенты/команды идут с ДВУХ уровней (.claude/ и ~/.claude/); сверять состав множеств, а не факт присутствия; экономию заявлять после прогона в новой сессии
- [Dual-write разъехался по содержимому](feedback_plan_dual_save.md) — 64 записи различаются в ОБЕ стороны, правды нет ни в одной копии; сверять перед доверием старой записи
- [devseed перетирает .claude/](project_devseed_overwrites_claude_dir.md) — preserved: CLAUDE.md, modes/_stack.md, settings.local; перетираются settings.json и остальные modes/* · [миграция на claude-kit](project_claude_kit_migration.md)

## Ремесло: тесты, инъекции, дефекты, конфиг, Qt → [CRAFT.md](CRAFT.md)
**Читать CRAFT.md целиком ПЕРЕД тем, как** писать тесты · планировать инъекции · выносить
вердикт ревью · писать «не может сломаться» · править конфиг/схему Pydantic · трогать
Qt-виджеты или гонять qt-mcp. Ядро, которое обязано сработать и без чтения:
- [Три роли авторства](feedback_test_authorship_three_roles.md) — tester от acceptance, ревьюер запуском · [тестер всегда + инъекции против него](feedback_tester_always_and_inject_against_it.md) — его зелёный не результат
- [Тестер один раз на механизм и ДО кода](feedback_tester_once_per_mechanism_before_the_code.md) — второй заход по тому же механизму нашёл ноль за 479k; красный набор до кода = ТЗ · [слепоту даёт worktree, не проза](feedback_tester_blindness_needs_a_worktree.md) — оба тестера признались в утечке, проверить нельзя
- [Тест не доказан без красного](feedback_prove_test_red_without_fix.md) — инъекция на КАЖДОЕ заявленное свойство, предсказание до прогона · [молчащий детектор](feedback_silent_detector_proves_nothing.md)
- [Инъекция смотрит ДРУГИМ объективом, чем тест](feedback_injection_must_use_a_different_lens_than_the_test.md) — совпали точки наблюдения (payload/дерево) → красный доказывает согласие двух копий одной модели
- [Правдоподобное ≠ проверенное](feedback_plausible_is_not_verified.md) — вердикт без воспроизведения вход→выход = совет, не факт
- [Транспорт арбитрирует то, чего не понимает](feedback_transport_arbitrates_what_it_cannot_understand.md) — два писателя в один лист; троттл вырезает молча (proceed=true без rejection_reason)
- [Приоритет у приёмника](feedback_priority_belongs_to_the_receiver.md) — нет модели слоёв → доигрывать порядок ЗАПИСИ, не лестницу уровней · [свойство не проверено у соседа](feedback_property_unchecked_at_the_second_party.md) — и на втором call-site; ноль от инъекции воспроизводить руками
- [Неподключённый драйвер = ровный ноль](feedback_unconnected_driver_reads_as_a_clean_zero.md) — подтверждающий ноль засчитывать только в паре с контролем, дающим ненулевое
- [Три объектива — три класса](feedback_three_lenses_three_defect_classes.md) — тесты=механика, прогон=проводка, ревью=связки
- [Корневой гейт не видит модули фреймворка](project_root_gate_misses_framework_modules.md) — из 82 новых тестов в него попали 6; сверять прирост сбора, гонять ОБА гейта
- [Фасад — белый список](feedback_facade_is_a_whitelist_not_a_passthrough.md) — правка схемы/конфига: три точки (схема, фасад+expand, readback) · [model_copy не валидирует](feedback_model_copy_does_not_validate.md) — dict вместо схемы молча
- [Ручка применена ≠ подтверждена](feedback_a_knob_can_be_applied_and_unverifiable.md) — под-секция без менеджера идёт мимо сверщика: `unverifiable` при `checked=0` = никто не смотрел
- [Инъекция воспроизводит МЕХАНИЗМ, не форму](feedback_injection_must_reproduce_the_mechanism_not_the_shape.md) — реплика дефекта по форме может не ломать ничего (PEP 570); ноль красных проверять руками
- [Общее дерево делает инъекции флейками](feedback_shared_tree_makes_injections_look_like_flakes.md) — патчи и чужие прогоны в одном дереве врут обеим сторонам; только разные worktree
- [Живость зонда ≠ рендер](feedback_probe_liveness_is_not_render.md) — qt-mcp: «зонд жив» ≠ «отрисовано» · [флаг сравнивается дословно](feedback_qt_mcp_flag_value_is_compared_verbatim.md) — «1:9142» промолчало

## Активные проекты и долги
- [line_sim: план создан](project_line_sim_vision.md) — буквы первыми; встроенная сборка; правда в v1; plans/line-sim/ Ф0–Ф6 (19 задач), ветка feat/line-sim
- [constructor-master прогресс](project_constructor_master_progress.md) — Ф0–Ф3 + трек F + Ф5-ядро закрыты; NEXT C1-C8 + app_module 5.11-5.13 · [чистка границ C1-C8](project_arch_boundaries_plan.md) — движок миграций 4.5 идёт в recipe, НЕ generic
- [backend_ctl](project_backend_ctl_framework_module.md) — Phase 0+2 в main, 8.0/10; резидуалы в backend-ctl-hardening · [ловушки](project_backend_ctl_signal_integrity.md) — ложный success/timeout · [сокет мимо receive-мидлвари](project_backend_ctl_socket_bypasses_mw.md) — драйвером нельзя проверять фильтры приёма · [строгий край protocol.py](project_backend_ctl_missing_contract.md) — missing/None/null = три РАЗНЫХ факта · [MCP только через RouterManager](project_backend_control_mcp.md)
- [Диагностика — через backend_ctl](feedback_diagnose_live_system_with_backend_ctl.md) — соседи как контроль
- [Рантайм-правка умирает через 300 с](project_runtime_knob_expires_in_300s.md) — L3 TTL молча снимает гейт; посылка «гейт закрыт» имеет срок годности
- [GUI-стенд боевым входом](project_gui_stand_production_entry_only.md) — INSPECTOR_GUI_UNATTENDED=1; harness виснет в initialize · [два бэкенда конфликтуют](project_concurrent_backends_trap.md) — PID-реестр и SHM-cleanup
- [Command-engine audit](project_command_engine_audit.md) — ActionBus мёртв; RBAC дыра
- [Pipeline узлы](project_pipeline_node_plugin_containers.md) — нода=плагин в контейнере; MovePlugin долг · [reuse по plugin_name](feedback_pipeline_reuse_plugins_widgets.md) — gui protected
- [Workers runtime](project_processes_workers_runtime.md) — live-телеметрия DONE; assigned_worker PENDING · [архитектура](project_workers_architecture.md) — WorkerManager · [timing](project_worker_cycle_timing.md)
- [Transport hub](project_transport_router_hub.md) — P0-P2 DONE; P3 отложен · [иерархический адрес](project_hierarchical_addressing.md) — целевое: процесс → воркер → глубже
- [Авто-рестарт всех процессов](project_all_process_autorestart.md) — механизм исполнен Ф4-добор (ADR-PMM-015); хаб+chain-health → Ф5
- [Graceful-stop debt](project_graceful_stop_debt.md) — 5с-ханг; stop_all_workers/put()
- [Camera settings](project_camera_settings_feature.md) — пресеты+actual; MJPG-долг · [Hikvision 4:3](project_hikvision_aspect_ratio.md) — иначе эллипсы
- [Line filter](project_line_filter_feature.md) — 0-3 DONE; overlay_draw пишет frame
- [Device hub](project_device_hub.md) — always-on, YAML-протоколы, Ф0-5 DONE; NEXT device-tree-recipe
- Рецепты: [save/load FIXED×2](project_recipe_save_load_arch.md) — долги on_result/switch≠boot · [switch обязан раздать L2](project_switch_delivers_layer.md) — R6, четыре живых дефекта · [join key FIXED](project_recipe_inspector_join_key.md) · [hikvision_letter ROI](project_hikvision_letter_robot.md) — 560,240,800,600
- [Draw mode rework](project_draw_mode_rework.md) — feat/draw-mode-rework; hardware pending
- [Pult panel](project_pult_control_panel.md) — контролы→сигналы; robot_draw live
- [Phone gateway](project_phone_gateway_service.md) — v1 готов, GUI follow-up
- [app_module Win test debt](project_app_module_windows_test_debt.md) — 2 красных только на Windows
- [Kind-channels мёртвая ветка](project_kind_channels_dead_evict_branch.md) — send блокирует 1с вместо drop_oldest
- [Гейт топологии state](project_state_topology_gate.md) — FW_STATE_TOPOLOGY_GATE, пара ON/OFF
- [macOS SHM](project_macos_shm.md) — 15 skipped; user на Win+Mac
- [Gorynych PyPI deferred](project_gorynych_pypi_deferred.md) — триггеры: ок работодателя + потребитель + прод
- [Component Design System](project_component_scoped_styles.md) — DEFERRED
- [Live-находки webcam 07](project_live_findings_webcam_2026_07.md) — ротация молчит; 23% ошибок невидимы
- [fw_version из git](project_fw_version_from_git.md) — 2.0.0+hash[.dirty]; nosec последним

## Домен: робот, зрение, ML
- [ML-сервисы](project_ml_train_service.md) — ml_train v1, dataset-gen (центр (size-1)/2), буква+угол 33/33 · [dataset_gen](project_dataset_gen_service.md) — cut-and-paste, пресет ru_letters_disk · [обучение буква+угол](project_letter_angle_training.md) — пресеты manual_letters
- [Рисование портрета роботом](project_sketch_robot_draw.md) — 3 дисплея + заморозка кадра + отправка кнопкой · [FPS-просадка на детальных кадрах](project_strokes_points_perf.md) — O(n²) sort, trace_skeleton не векторизуется
- [Робот Delta + ПЧ GD20](project_robot_vfd_services.md) — универсальный modbus через Protocol · [VFD bridge](project_vfd_bridge_robot_reboot.md) — зависший ПЧ лечится перезагрузкой РОБОТА
- [Sources ⊥ Processing](project_source_topology.md) — разные регистры, связь по ключам региона · [display_module](project_display_registry.md) — реестр именованных SHM-каналов

## Закрытые треки — открытые концы
Полная история — в [ARCHIVE.md](ARCHIVE.md). Здесь только то, из чего ещё торчит хвост.
- Observability: [Ф2–Ф8 + роадмап](project_f8_review_and_stitching.md) — актуальное в plans/observability-roadmap.md · [хвост-ремонт](project_observability_tail_repair.md) — гейт 6855×3; вход в этап 6 открыт · [ошибки идут в logger, не error_manager](project_observability_store_error_routing.md) — store-tap нужен на ОБА, live-boot вскрыл · [telemetry read-model ADR-136](project_gui_telemetry_read_model.md) · [self-publish DB-sink](project_telemetry_self_publish.md) · [webcam фриз](project_webcam_sketch_freeze.md) — IPC-шторм · [gui задушен очередью](project_gui_system_queue_storm.md) — гонка тихой потери
- Конструктор/GUI: [фазы DONE](project_generic_process_vision.md) — GenericProcess deprecated · [Ф7 Phase G 8.0](project_phase_g_final_review.md) — seqlock, QoS-кольца SHM, флип-лесенка · [Registries v2](project_service_registry.md) — ADR-129…132 · [Pipeline recipe-launch](project_pipeline_recipe_driven_launch.md) — hot-apply не подключён · [Switch stale](project_switch_routing_stale.md) — live через PM-хаб
- [Fencing-тест ADR-SS-019](project_fencing_test_race.md) — ghost-гонка закрыта · [fencing-token топологии](project_topology_fencing_token.md) — исполнено Ф4.2: дроп по per-sender incarnation, НЕ epoch

## IPC, роутинг, планы
- [Register routing hang](feedback_register_routing_hang.md) — FieldRouting без канала = фриз GUI
- [No SHM hacks](feedback_no_shm_hacks.md) — только framework middleware · [провод портов ≠ маршрут](feedback_port_wire_is_not_a_process_route.md) — плагин не вызван молча
- [Посылка плана устаревает](feedback_a_plans_premise_expires.md) — блокер воспроизводить, не сверять номера
- [Plan-Driven Dev](project_plan_driven_dev.md) — slug, Refs-trailer · [checkboxes [x]+hash](feedback_plan_checkboxes.md) · [dual-save](feedback_plan_dual_save.md)
- [Один активный план](feedback_one_active_plan_per_tool.md) — иначе воскрешение отменённых задач
- [Спека может врать](feedback_plan_spec_can_lie.md) — имя поля сверять с кодом · [позиционный вызов прячет имена](feedback_positional_call_hides_parameter_name_drift.md) — падало на duration=
