# R3 — не-feedback файлы memory (project_*, reference_*, user_*, handoff_*, индексы)

Доля: 157 файлов + разбор MEMORY.md, CRAFT.md, ARCHIVE.md. Только чтение; ничего в репо и в memory не менялось.

## 1. Таблица (формат: file | kind | action | target | tags | hook | reason)

Сокращения: AR = ARCHIVE (убрать из индекса, файл оставить в архиве). Факты о планах: `plans/queue/ORDER.md` (сверка 2026-10-03), таблица закрытых планов (строки ~261-283), `plans/_archive/`.

### Пачка 1
handoff_sources_widget_refactor | STALE | AR | git; docs/refactors/2026-04_widgets_reorg.md | frontend/sources | handoff 2026-04-28, SourcesTabWidget inline-edit | git grep SourcesTabWidget = 0
project_all_process_autorestart | STATE | AR | ADR-PMM-015 в process_manager_module/DECISIONS.md; флаг FW_AUTORESTART в config_module/feature_flags.py | process_manager | авто-рестарт default-on, откат FW_AUTORESTART=0 | механизм исполнен 8ac43361, факт в ADR
project_app_module_windows_test_debt | STATE | KEEP как REFERENCE local-only; перепроверить, красны ли тесты сейчас | - | app_module; windows | 2 теста app_module красные только на Windows | os.replace в store.py есть; текущий статус не проверен
project_arch_boundaries_plan | REDUNDANT | AR | plans/2026-07-06_constructor-master/plan.md (Ф5-добор C1-C8); ADR-RCP-001 | recipe | движок миграций в recipe, не в doc_migration_module | решение уже в плане и ADR
project_archives_removed | REDUNDANT | AR | корневой CLAUDE.md, раздел "История версий" | repo | архивы прототипа удалены e128b930 | CLAUDE.md говорит то же
project_backend_control_mcp | STALE | AR; одну строку "MCP-драйвер говорит с бэкендом только через RouterManager" перенести в backend_ctl/README | plans/_archive/2026-05-31_backend-control-mcp | backend_ctl | MCP идёт только через RouterManager | "Следующее: P3" давно сделано, план в _archive
project_backend_ctl_d1_session_isolation | STATE | AR (18 КБ) | plans/_archive/2026-07-19_backend-ctl-d1-session-isolation.md | backend_ctl; router | изоляция сессий через иерархический адрес | план в _archive
project_backend_ctl_framework_module | STATE | AR | plans/_archive/2026-07-21_backend-ctl-framework-module.md | backend_ctl | Phase 0/2 на текущей раскладке | план в _archive
project_backend_ctl_gaps_2026_07 | STALE | AR | коммиты 857ed851, 6b9d4e1f | backend_ctl | дыры, найденные живой работой 07-20 | пункты 1-2 помечены закрытыми
project_backend_ctl_missing_contract | LESSON | MERGE в project_backend_ctl_signal_integrity | survivor: signal_integrity | backend_ctl; mechanism: missing-vs-zero | отсутствие ключа, ноль и null — три факта | тот же класс болезни
project_backend_ctl_recorder_kept | STATE | AR после переноса решения в plans/queue/decisions.md или BCTL-ADR-006 | - | backend_ctl | flight recorder оставлен вердиктом 07-22 | grep "recorder" в queue/decisions.md = 0: решение не записано
project_backend_ctl_signal_integrity | LESSON | KEEP (survivor) | - | backend_ctl; mechanism: false-signal | ложный success/timeout/ноль у инструмента | три дефекта = одна болезнь, коммиты в таблице
project_backend_ctl_socket_bypasses_mw | LESSON | KEEP | - | backend_ctl; router_module; mechanism: receive-middleware | сокет backend_ctl обходит receive-мидлварь | fence проверять только через peer-канал
project_backend_ctl_ultra_review | STATE | AR | plans/_archive/2026-07-20_backend-ctl-hardening.md | backend_ctl | ultra-ревью 07-20, баги закрыты | файл сам говорит "закрыты"
project_calibration_gui_progress | LESSON | KEEP; переименовать (имя про прогресс, суть — урок) | - | gui_process; state_store; mechanism: state-root subscribe | новый state-корень = подписка в GuiProcess | есть тест test_gui_process::test_subscriptions_*
project_camera_settings_feature | STATE | AR | код Services/camera_service | camera_service | настройки камеры реализованы | "uncommitted, 5 фаз" 2026-06; код — источник
project_claude_kit_migration | REFERENCE | MERGE в project_devseed_overwrites_claude_dir; mark mac-path | survivor: devseed_overwrites | claude-kit | как обновить .claude/ от devseed | пути /Users/twokrai (Mac); пересекается
project_comm_system_p0 | STATE | AR | plans/_archive/comm-system-*.md | router; message_module | P0 comm-system закрыт 06-05 | план в _archive
project_command_bus_p4_4 | STATE | AR | plans/_archive/2026-05-31_transport-router-hub | command_manager | P4.4 command-bus | план в _archive
project_command_engine_audit | LESSON | KEEP; перепроверить, что ActionBus всё ещё сирота | - | actions_module; command_manager | ActionBus мёртв в проде; "два движка" ложь | ActionBus есть в framework/DECISIONS.md; сироту не пере-проверял
project_command_result_bridge | STATE | AR | plans/_archive/2026-06-06_command-result-bridge | command_manager; gui | request/response GUI→PM готов | план в _archive
project_component_scoped_styles | STATE | AR | multiprocess_prototype/plans/component_scoped_styles.md | frontend/styles | отложенный план стилей компонентов | файл плана существует; память — указатель

### Пачка 2
project_concurrent_backends_trap | LESSON | KEEP | - | process_manager; shm; mechanism: global-resource-in-tests | два бэкенда в тесте убивают PID друг друга | PID-реестр исправлен в harness; SHM-cleanup латентен
project_config_driven_arch | STALE | AR | - | generic_process | GenericProcess+plugins фазы 0-2 | Constructor-слой удалён 2026-05 (phase6)
project_config_voice_belongs_to_the_apply_stage | LESSON | KEEP; обновить: Task 4.11 DONE (ORDER) | - | config_module; mechanism: IO-in-parser | голос оператору звучит 6 раз на config.reload | корень = ввод-вывод внутри парсера
project_constructor_master_progress | STATE | AR (39 КБ); уроки вынуть отдельным проходом | plans/2026-07-06_constructor-master/plan.md; docs/handoffs/2026-07-11_constructor-waves-handoff.md | constructor-master | прогресс Ф0-Ф5 | чистый прогресс; по ORDER осталось H.3/H.5/H.6
project_constructor_phase5 | STALE | AR | git | prototype/constructor | ShmRouteNode + PluginManagerTab | Constructor-слой удалён 261b90f
project_constructor_phase6 | STALE | AR | git show 9885bb88 | prototype/constructor | компоненты Phase 6 удалены | файл сам DEPRECATED
project_cross_tab_phase_b | STATE | AR | plans/_archive/2026-05-27_cross-tab-architecture | domain layer | Phase B domain skeleton | план в _archive
project_cross_tab_phase_c | STATE | AR | то же | adapters | Phase C adapters, 113 тестов | план в _archive
project_cross_tab_phase_d | STATE | AR | то же | AppServices DI | Phase D AppServices | план в _archive
project_cross_tab_phase_e | STATE | AR | то же | per-tab migration | Phase E миграция вкладок | план в _archive
project_cross_tab_phase_f | STATE | AR | то же | legacy removal | Phase F удаление legacy | план в _archive
project_cross_tab_phase_g | STATE | AR (35 КБ) | то же | ActionBus; AppContext | Phase G финал | план в _archive
project_cuda_torch_setup | REFERENCE | KEEP local-only | - | ml_train; gpu | RTX 3050 4GB, torch cu124 | факт машины
project_dataset_gen_service | REDUNDANT | AR | Services/dataset_gen/STATUS.md:58 | dataset_gen | cut-and-paste генератор DONE | единственная находка (центр (size-1)/2) уже в STATUS.md
project_device_hub | STATE | AR; сверить блок "контракты НЕ ломать" с Services/device_hub/README | plans/_archive/device-hub.md; plans/device-tree-recipe.md | device_hub | always-on процесс devices | Фазы 0-5 DONE; контракты из ревью не сверены
project_devseed_overwrites_claude_dir | RULE | KEEP (survivor); цель: 1 строка в .claude/CLAUDE.md | .claude/CLAUDE.md | claude-kit | claude-kit upgrade молча затирает .claude/ | должно сработать до upgrade
project_display_registry | REDUNDANT | AR | display_module ADR-DM-001 | display_module | реестр SHM-каналов отображения | решения в ADR модуля
project_draw_mode_rework | STATE | AR | plans/draw-mode-rework/plan.md (A,C,D DONE) | robot draw | ветка draw-mode-rework | план в таблице закрытых
project_f2_4_scope_is_a_string | STATE | AR | plans/observability-unified-routing.md | logger_module | LogScope = строка | план DONE
project_f2_closed_2026_08 | STATE | AR | то же | observability | Ф2 закрыта | план DONE
project_f3_external_review | STATE | AR | docs/reviews/2026-08-05_f3_review.md | observability | ревью Ф3 8/10 | отчёт в docs/reviews
project_f4_processors_closed | STATE | AR | plans/observability-unified-routing.md | observability | Ф4 цепочка процессоров закрыта | план DONE
project_f5_cross_review | STATE | AR | docs/reviews/2026-08-01_f5-cross-review.md | observability | ревью Ф5 7.5/10 | отчёт в docs/reviews
project_f6x_review_basket | STATE | AR | коммиты 7e3eabae..f258a200 | observability | корзина Ф6.х закрыта | план DONE
project_f7_cross_review | STATE | AR | docs/reviews/2026-08-06_f7-cross-review.md | observability | ревью Ф7 7.5/10 | отчёт в docs/reviews
project_f7_g3_handoff | STATE | AR; флаги FW_SHM_* уже в feature_flags_registry | plans/2026-07-06_constructor-master/g3-review-2026-07-14.md | shm; frame | G.3 seqlock, merge b54b4689 | закрыто; флаги в реестре

### Пачка 3
project_f7_g4_done | STATE | AR | plans/2026-07-06_constructor-master/g4-execution-plan.md | frame_pool; shm | G.4 QoS-профили, merge e6b1bcca | закрыто, правда в плане
project_f7_g7_flip_ladder | STATE | AR | plans/2026-07-06_constructor-master/g7-flip-plan.md, baseline.md | shm; feature_flags | флип-лесенка G.7, числа в baseline.md | числа уже в baseline.md
project_f7_g7_num_consumers | LESSON | KEEP | - | frame_pool; process_module/generic; mechanism: loan-protocol | две роли loan-протокола, не путать | урок с корнем и фиксом fe0f4d41
project_f8_review_and_stitching | STATE | AR | ADR-PM-028 (process_module/DECISIONS.md); docs/reviews/2026-08-08_f8-review.md | process_module | Ф8 плоскость документов сшита | итог фазы = ADR
project_feature_flags_registry | REDUNDANT | AR | config_module/feature_flags.py + README | config_module | реестр FW_* флагов | код и тесты — источник; список флагов устаревает
project_fencing_test_race | LESSON | KEEP | - | topology fencing; mechanism: test-asserts-race-outcome | тест требует исхода гонки; механизм исправен | флейк по построению, замер 3/3 красный, 1/3 проба
project_fw_version_from_git | REDUNDANT | AR | multiprocess_framework/version.py (docstring про .dirty) | framework | fw_version из git 2.0.0+hash[.dirty] | docstring в version.py говорит то же
project_g5_ownership_decision | STATE | AR | plans/2026-07-06_constructor-master/g5-execution-plan.md | frame_pool | G.5 владелец: оба примитива владения | решение исполнено в G.5
project_generic_process_vision | STALE | AR | git (GenericProcess реализован) | generic_process | замена hardcoded процессов на GenericProcess | видение реализовано, три слоя уже в CLAUDE.md
project_gorynych_pypi_deferred | REFERENCE | KEEP (вне индекса) | - | packaging | публикация на PyPI "gorynych" отложена | решение владельца с 3 условиями возврата
project_graceful_stop_debt | LESSON | KEEP | plans/lifecycle-stop-ownership.md | process_manager; mechanism: mp.Queue feeder at exit | 5-секундный ханг stop — feeder-треды mp.Queue | диагноз верифицирован дампом; опровергнутое записано
project_graphify_mcp_setup | REFERENCE | KEEP | - | graphify | mcp вшивать через uv tool install --with mcp | рантайм --with ломает коннект; числа графа датированы
project_gui_constructor_layers_2026_09_26 | LESSON (решение владельца) | KEEP, вне индекса | plans/gui-constructor/plan.md (DRAFT) | gui-constructor | framework=конструктор, Services=срезы, prototype=тонкий | решение; перекрывается планом gui-constructor — сверить
project_gui_stand_production_entry_only | RULE | KEEP; цель: .claude/commands observability-acceptance + строка в project-rules | .claude/commands (core:quality:observability-acceptance) | gui; backend_ctl; mechanism: live-stand | стенд GUI только боевым входом + INSPECTOR_GUI_UNATTENDED=1 | через BackendHarness gui виснет; headless занижает нагрузку
project_gui_system_queue_storm | LESSON | KEEP; перепроверить: чинено ли | - | gui; router; state_store; mechanism: never-drop queue | PM топит system-очередь gui дельтами state.changed | диагноз 2026-07-22; в defects.md не найден — статус неясен
project_gui_telemetry_read_model | STATE | AR | plans/gui-telemetry-read-model.md; ADR-136 | telemetry_readmodel | read-model телеметрии закрыт 07-16 | план DONE, ADR-136
project_hardware_roles_2026_09_23 | REFERENCE | KEEP local-only | - | hardware | ноутбук RTX 3050 + Jetson Orin Nano/NX | факт владельца
project_hierarchical_addressing | REDUNDANT | AR | message_module/addressing/address.py; ADR-COMM | message_module; router | адрес получателя иерархический | реализовано (P0.2), цитируется в backend_ctl d1
project_hikvision_aspect_ratio | LESSON | KEEP | - | Services/hikvision_camera | resize ломает аспект — задавать 4:3 | эллипс = target_aspect/sensor_aspect, фикс конфигом
project_hikvision_letter_robot | REDUNDANT | AR | multiprocess_prototype/recipes/hikvision_letter_robot.yaml | recipes | боевой тракт укладчика | рецепт yaml — источник правды
project_honest_verdict_2026_09 | STATE | AR; число "шина 0.3/0.6 мс/хоп" перенести в docs/audits (уже там) | docs/audits/2026-09-04_honest-verdict-bus-and-niche.md; plans/queue/decisions.md №12 | product | вердикт 6.5/10, доказанность 4/10 | отчёт и очередь уже в docs/plans
project_kind_channels_dead_evict_branch | LESSON | KEEP; MERGE с .claude/agent-memory/teamlead/project_live2_release_on_evict.md | survivor: этот файл | router; frame_pool; mechanism: dead-branch-behind-flag | при FW_USE_KIND_CHANNELS=1 вытеснение мертво | флаг ещё в backend_ctl/README и пробах
project_knobs_universal_manager | STATE | AR | plans/observability-closure/plan.md Task 4.9 | observability; knobs | KnobManager — универсальный механизм ручек | направление записано в плане
project_letter_angle_training | STATE | AR | plans/letters-retrain/plan.md | ml_train | обучение буква+угол, пресеты manual_letters | план жив и ведёт состояние
project_line_filter_feature | STATE | AR | plans/_archive/2026-06-08_line-filter-virtual.md | line_filter | фильтр виртуальной линии, план завершён | план в _archive
project_line_sim_vision | STATE | AR (11 КБ) | plans/line-sim/vision.md, plans/line-sim/plan.md | line_sim | line_sim автономный стенд | видение и план в репо, DONE Ф0-Ф3,Ф5
project_live_findings_webcam_2026_07 | LESSON | KEEP | - | backend_ctl; mechanism: swallowed-cause | сбой есть, счётчик растёт, причина проглочена | три находки, ни одну не ловили 504 теста
project_live_verification_2026_07_21 | STATE | AR | docs/audits/2026-07-20_bug-hunt.md §9-10 | audit | охота на баги, 17 находок починены | закрыто, отчёт в docs/audits
project_macos_shm | STATE | AR или REFERENCE; перепроверить число skipped | plans/_archive/framework_assessment_2026_05_07.md | memory_module; macos | 15 skipped тестов MemoryManager на macOS | дата 2026-05, источник — план в _archive
project_memory_module_consolidation | RULE (решение владельца) | KEEP вне индекса | plans/2026-07-06_constructor-master/h-memory-consolidation-plan.md | memory_module | память одним модулем с фасадом | директива жива до закрытия H
project_ml_train_service | REDUNDANT | AR | Services/ml_train/STATUS.md | ml_train | ml_train v1 DONE | план в _archive/ml-train-service.md
project_monotonic_resolution_windows | LESSON | KEEP local-only | - | tests; windows; mechanism: clock-resolution | monotonic на Windows шаг 15.6 мс | разности <100 мс недостоверны, замер get_clock_info
project_observability_audit | STATE | AR | plans/observability-unified-routing.md | observability | 5.9 аудит смен наблюдаемости | план DONE
project_observability_closure_progress | STATE | AR (54 КБ); вынуть "главное число Ф3 не взято" в OPEN_QUESTIONS, если ещё нет | plans/observability-closure/plan.md; docs/claude/OPEN_QUESTIONS.md | observability | observability-closure Ф0-Ф3, Ф4 начата | чистый прогресс, ORDER: Ф4 4.4/4.11/4.13 DONE
project_observability_config_layers | STATE | AR | plans/observability-unified-routing.md; ADR | observability | 5.12 четыре слоя конфига L0-L3 | план DONE; схема слоёв в ADR
project_observability_consumer_acceptance | REDUNDANT | AR; "гонять на фазовых точках, не на задачах" проверить в команде | .claude/commands core:quality:observability-acceptance | observability | приёмка наблюдаемости потребителем | зонд и чек-лист стали командой
project_observability_control_plane | STATE | AR | plans/_archive/2026-06-03_observability-control-plane | observability | control-plane plan DONE | план в _archive
project_observability_namespace_symmetry | STATE | AR; урок "точки в паттернах троттла ломают плоский namespace" проверить в logger_module DECISIONS | plans/observability-unified-routing.md | logger_module | 5.10 симметрия namespace | план DONE; один мелкий урок
project_observability_session_ttl | STATE | AR | ADR наблюдаемости | observability | 5.8 слой L3 временный по построению | план DONE
project_observability_stdlib_migration | STATE | AR | plans/observability-unified-routing.md | logger_module | Ф6 100 файлов на вид логгера | план DONE
project_observability_store_error_routing | LESSON | KEEP | - | observability_store; logger_module; mechanism: tap-on-both-managers | store-tap нужен на ОБА менеджера | live-boot вскрыл, юниты прятали (0 error из 60)
project_observability_subscription_broker | STATE | AR | plans/observability-unified-routing.md | observability | 5.11 брокер подписки | план DONE
project_observability_tail_repair | STATE | AR | docs/reviews/2026-08-12_observability-hard-review.md | observability | хвост-ремонт Т-1…Т-5 закрыт | закрыто
project_observation_port_progress | STATE | AR | plans/observation-port/plan.md | observation_port | Ф0-Ф5 закрыты | план DONE (ORDER: шапка "черновик" врёт)
project_otel_export_plan_state | STATE | AR | plans/otel-export.md; docs/reviews/2026-09-05_otel-export-plan-review.md | otel | otel-export ред. 4 | план живёт и сам ведёт состояние
project_phase5_data_pipeline | STALE | AR | git | generic_process | GenericProcess refactor Phase 5 | путь multiprocess_prototype_2/ удалён
project_phase5_progress | STALE | AR | git | generic_process | Phase 5 Tasks 5.1-5.9 DONE 2026-05-06 | старая нумерация фаз, всё в git
project_phase_g_final_review | STATE | AR | docs/reviews | constructor-master | директива: финальное Fable-ревью фазы G | исполнено, фаза G закрыта
project_phone_gateway_service | REDUNDANT | AR (12 КБ) | Services/phone_gateway/README.md, STATUS.md | phone_gateway | сервис фото+слово с телефона | v1 готов, состояние в STATUS
project_pipeline_demo | STALE | AR | git | pipeline_tab | демо-рецепт webcam→split→merge | Phase 7a/7b 2026-05, UI с тех пор переписан
project_pipeline_editor_runtime_decoupled | STALE | AR | plans/_archive/2026-05-31_pipeline-live-control | pipeline | редактор и бэкенд развязаны | план pipeline-live-control в _archive, мост достроен
project_pipeline_live_control_stage1 | STATE | AR | то же | pipeline | этап 1 IPC-мост GUI→PM | план в _archive
project_pipeline_live_control_stage2 | STATE | AR | то же | pipeline | этап 2 live field-write | план в _archive
project_pipeline_live_incremental_vision | STALE | AR | то же | pipeline | live-применение инкрементально per-process | видение владельца 05-31 реализовано планом

### Пачка 4
project_pipeline_node_plugin_containers | STALE | AR; проверить долг "MovePlugin" в плане pipeline-color/gui | git | pipeline_tab | нода = плагин в контейнере процесса | запись 2026-05-30 "НЕ закоммичено"; UI переписан
project_pipeline_node_process_worker | STALE | AR | git | pipeline_tab | назначение ноды в процесс/воркер, Phase A+B | план лежит в prototype/frontend/..., "uncommitted"
project_pipeline_recipe_driven_launch | REDUNDANT | AR; принцип "GUI формирует топологию, бэкенд исполняет headless" уже в корневом CLAUDE.md (Frontend = только PySide6-слой, Dict at Boundary) | plans/_archive/2026-05-31_pipeline-live-control | pipeline; recipes | редактор даёт топологию, бэкенд запускает рецептом | направление владельца 05-31 исполнено
project_plan_driven_dev | REDUNDANT | AR | корневой CLAUDE.md, раздел Plan-Driven Development | process | slug, Refs-trailer | CLAUDE.md говорит то же
project_plugin_system_phase6 | STALE | AR | git | processes_tab | Phase 6 UI плагинов в SystemTopology | 2026-04-30, SystemTopology заменён
project_priority_engine_first | RULE | KEEP, свернуть в 1 строку; цель: plans/queue/ORDER.md (правило маятника уже там, строка 62) | plans/queue/ORDER.md | priorities | приоритет — маятник по свободному времени | ORDER.md ссылается на правило; файл можно сжать до ссылки
project_processes_tab | STALE | AR | git | processes_tab | вкладка Процессы Phase 1-7b | 2026-04-28
project_processes_workers_runtime | STATE | AR; долг "assigned_worker PENDING" сверить | git | processes_tab; worker_module | вкладка Процессы: CRUD воркеров | план в репо отсутствует, ветка закрыта
project_prototype_audit_2026_06 | STALE | AR | docs/audits/2026-06-13_prototype-services-plugins-audit.md | audit | аудит prototype+Services+Plugins 06-13 | часть находок починена с тех пор; отчёт сам хранит ID
project_prototype_carveout | STALE | AR | plans/_archive/prototype-carveout.md; корневой CLAUDE.md (Phase 4/5 carve-out) | framework; Services; Plugins | carve-out прототипа во framework, пилот SystemBuilder | Services/ и Plugins/ вынесены (CLAUDE.md)
project_pult_control_panel | STATE | AR; урок "секция Services обязана реализовать action_buttons(), иначе весь Services-таб падает" вынести отдельной LESSON-записью | plans/pult-control-panel.md (Phase 1-3 DONE) | Services tab; SectionProtocol | Пульт control_panel + robot_scale | единственный урок спрятан в 8.6 КБ статуса
project_qex_model | REFERENCE | KEEP (per-platform); дубль части с корневым CLAUDE.md | .claude/plugins/mcp-qex/qex-launcher.py | qex; ollama | mac 8b/4096, Windows 0.6b/1024; Ollama silent-CPU | уникальна ловушка silent-CPU и раздельные индексы
project_qex_reindex_timeout | LESSON | KEEP; MERGE с feedback_qex_full_rebuild_runbook / feedback_qex_reindex_budget (другая доля аудита) | survivor: решить в доле feedback_qex_* | qex; windows | реиндекс падает по таймауту 10 с зашитому в бинарь | CLAUDE.md пишет, что тормозили BM25-сегменты — причина могла устареть
project_recipe_hotswap | STATE | AR | plans/_archive/2026-06-06_replace-blueprint-hotswap.md | recipe; process_manager | hot-swap replace_blueprint Task 1-7 | план в _archive
project_recipe_inspector_join_key | LESSON | KEEP как короткий; ловушка обезврежена (_hoist_inspector_from_metadata), но docs/audits/2026-07-04 называет её костылём | - | recipes; mechanism: silent-disable | inspector(join) — прямой ключ процесса, не под metadata | fix-forward 2026-06-16; git grep в коде 0 попаданий — перепроверить имя функции
project_recipe_save_load_arch | STATE | AR; долги "on_result / switch≠boot" перепроверить | plans/_archive/2026-06-06_recipe-orchestrator-unify.md | recipe | save/load рецептов: корни багов | FIXED x2, план в _archive
project_recipes_manager | REDUNDANT | AR | ADR-131; multiprocess_prototype/recipes/manager.py | recipes | RecipesManager + replace_blueprint с rollback | решения в ADR-131
project_robot_vfd_services | STATE | AR | ADR-MB-001/002; plans/_archive/robot-vfd-services.md | Services/modbus | сервисы Робот Delta + ПЧ GD20 | Фазы 0-5 DONE
project_root_gate_misses_framework_modules | LESSON | KEEP, но обновить: test-fw в `make gate` уже стоит (Makefile:80, Ф6.х.1в) | Makefile gate | tests; pytest; mechanism: coverage-of-the-gate | корневой pytest не видит тесты framework — нужен второй гейт | контрмера в Makefile есть; урок общий: сверять testpaths
project_runtime_knob_expires_in_300s | LESSON | KEEP | - | telemetry; observability; mechanism: session-TTL | telemetry_set живёт 300 с и умирает молча | L3 TTL снимает гейт; ключ system.yaml:176-182
project_sentrux_baseline_2026_05 | STALE | AR | mcp__sentrux__evolution | sentrux | baseline 7161 на 2026-05-23 | цифра 4 месяца как мертва; evolution даёт ряд
project_sequencing_observability_then_audit | STATE | AR после Ф5 closure; пока 1 строка в plans/queue/decisions.md | plans/observability-closure/review-phase-2-cto.md:208 | ponytail-audit | наблюдаемость, потом ponytail-audit | решение владельца 09-02, исполняется по плану closure
project_service_registry | REDUNDANT | AR | service_module ADR-SVC-001 | service_module | реестр сервисов, singleton | решения в ADR модуля
project_services_vs_plugins | REDUNDANT | AR; carry: "side-effect-процесс = плагин в GenericProcessApp + фрагмент топологии" в ADR-120, если его там нет | ADR-120; корневой CLAUDE.md (Слои импортов) | Services; Plugins | Services — крупный SDK, Plugins — мелкая обработка | CLAUDE.md и ADR-120 описывают границу
project_settings_mvp_refactor | STALE | AR | plans/_archive/settings-mvp | settings tab | рефакторинг Settings на MVP | план в _archive, план-файл в ~/.claude/plans
project_sketch_robot_draw | STATE | AR | multiprocess_prototype/recipes/webcam_sketch.yaml | robot draw | 3 дисплея + заморозка кадра | рецепт — источник правды
project_source_topology | STALE | AR | код registers/ | sources; processing | Layer1 SourceTopology / Layer2 ProcessingConfig | 2026-04-28, реестры с тех пор переделаны
project_state_topology_gate | LESSON | KEEP | ADR-SS-019 | state_store; mechanism: topology-gate | fencing не закрывает снятый switch-ем процесс | гейт и флаг есть; урок: призраки после switch
project_std_facade_unused | STALE | AR | git grep get_std_logger -- *.py = 142 файла | logger_module | get_std_logger: 2 файла из 78 | Ф6 stdlib-миграция (100 файлов) устранила; число устарело
project_strokes_points_perf | LESSON | KEEP (сжать) | - | Plugins; numpy; mechanism: O(n^2)-per-frame | O(n²) sort + пересчёт каждый кадр, мемоизация по маске | фикс сделан; урок — искать пересборку массива в цикле
project_switch_delivers_layer | LESSON | KEEP | - | recipe switch; observability L2; mechanism: switch-redelivers-state | switch обязан раздать слой L2 пережившим | R6 закрыт, четыре дефекта проверены живьём
project_switch_routing_stale | LESSON | KEEP; ссылка на project_switch_delivers_layer (группа "switch") | - | recipe switch; process_state_registry; mechanism: stale-copy-after-switch | параметры молча не доходят после switch — стейл-PSR | копия pickle у каждого процесса; фикс через PM-хаб не сверён
project_system_topology_phase1 | STALE | AR | git | system_topology | статус фаз SystemTopology | ветка refactor/flatten-structure, 2026-04
project_team_mode_agent_teams | REDUNDANT | AR | .claude/CLAUDE.md, раздел Team mode | team | Agent Teams, cto=Fable, junior=Haiku | CLAUDE.md описывает; "живой прогон не делался" устарело (пилот v2, 4.7d)
project_telemetry_coherence_remediation | STATE | AR | plans/telemetry-coherence-remediation.md (DONE) | telemetry | ревью телеметрии 24→42/60 | план DONE
project_telemetry_dashboard | STATE | AR | plans/telemetry-dashboard.md (DONE) | telemetry; pyqtgraph | PyQtGraph как единая система графиков | план DONE; решение pyqtgraph в коде
project_telemetry_db_sink | STATE | AR | plans/_archive/2026-06-04_telemetry-db-sink.md | telemetry; Services/sql | DB-sink телеметрии, Phase 0-3 | план в _archive
project_telemetry_gui_controls | STATE | AR | plans/telemetry-publish-control.md (DONE) | telemetry; gui | Ф4.1 GUI-контролы телеметрии | план DONE
project_telemetry_publish_control | STATE | AR | ADR-PM-018 | telemetry | управляемая публикация, publisher-gate | план DONE, ADR
project_telemetry_self_publish | STATE | AR; одну строку "bug cycle_metrics monotonic дал FPS=0" вынести в project_monotonic_resolution_windows | plans/_archive/telemetry-self-publish-redesign.md | telemetry; monotonic | self-publish метрик + баг monotonic FPS=0 | план в _archive
project_telemetry_subscription_bug | STATE | AR (10 КБ) | git (16e14084) | telemetry; state_store | вкладка Процессы "—": серверный корень закрыт | остаток (late-binding) решён ADR-136
project_topology_fencing_token | STATE | AR | ADR-PMM-014, ADR-MSG-009 | message_module/fencing | fencing по incarnation, не epoch | исполнено e16e2ea8
project_transport_router_hub | STATE | AR | plans/_archive/2026-05-31_transport-router-hub; plans/transport-single-policy | router | RouterManager = единый хаб | план в _archive; продолжение — transport-single-policy
project_universal_lifecycle_decision | RULE (решение владельца) | KEEP до закрытия плана; индекс: 1 строка на план | plans/2026-10-03_lifecycle-owner-scope/DESIGN.md | lifecycle; subscriptions; mechanism: scope-owner | один scope-владелец для подписок/потоков/процессов/виджетов | план активен (полоса Ж), решение живёт в DESIGN.md
project_universal_object_generator | STATE | AR | plans/layer-render/plan.md | layer_render | слои+аугментация = универсальный генератор | план layer-render APPROVED, ведёт сам
project_venv_locked_by_mcp | LESSON | KEEP local-only | - | venv; backend_ctl MCP; windows | MCP держит numpy .pyd, респавнится | kill по PID гонку не выигрывает, замер 07-31 трижды
project_vfd_bridge_robot_reboot | LESSON | KEEP local-only (железо) | - | Services/vfd; robot; mechanism: bridge-carrier | зависший ПЧ лечится перезагрузкой робота | ≥2 раза; сначала проверять носителя
project_webcam_sketch_freeze | STATE | AR | ADR-136; plans/gui-telemetry-read-model.md | gui; telemetry | фриз Процессов = IPC-шторм в main thread | закрыто ADR-136, инвариант-тест 0 блокирующего IPC
project_work_order_2026_09_22_line_sim_then_pult | STATE | AR | plans/queue/ORDER.md ("единственное место порядка") | priorities | порядок line-sim → gui-service | ORDER.md объявлен единственным местом порядка
project_worker_cycle_timing | STALE | AR | worker_module (effective_hz в system_overview, 6b9d4e1f) | worker_module | вывод частоты цикла воркера + target_interval | пожелание реализовано
project_workers_architecture | REDUNDANT | AR | worker_module/README.md | worker_module | воркеры = потоки в WorkerManager | описание кода
reference_gpu_monitoring_windows | REFERENCE | KEEP local-only | - | gpu; ollama; windows | Task Manager прячет CUDA, смотреть nvidia-smi | факт машины
reference_qt_mcp_launch | REFERENCE | KEEP; дубль с .claude/plugins/mcp-qt/SETUP_GUIDE.md (там упомянут QT_MCP_PROBE) | .claude/plugins/mcp-qt/SETUP_GUIDE.md | qt-mcp | qt-mcp только с QT_MCP_PROBE=1 | MCP README уже требует чтения перед использованием; можно в AR
reference_tech_stack_2026 | REFERENCE | KEEP | docs/direction/TECH_STACK_2026.md | stack | сверяться с TECH_STACK_2026 перед новой зависимостью | указатель на живой документ владельца
user_career_goal | REFERENCE (user) | KEEP вне индекса или 1 строка | - | owner | цель: АСУТП + робототехника + CV, не программист | решение владельца 2026-08-20

## 2. Группы слияния (survivor ← файлы, что приносит каждый)

1. **backend_ctl: сигнал ≠ реальность.** survivor `project_backend_ctl_signal_integrity` ← `project_backend_ctl_missing_contract` (правило "missing / ноль / null — три факта", поле `missing`). Соседи без слияния: `project_live_findings_webcam_2026_07` (сбой есть, причина проглочена), `project_backend_ctl_socket_bypasses_mw`.
2. **switch рецепта оставляет устаревшее или недостающее состояние.** Новый общий файл (survivor `project_switch_routing_stale`) ← `project_switch_delivers_layer`. Первый: pickle-копия PSR у процесса устаревает. Второй: слой L2 не доходит до пережившего процесса. Один триггер ("после switch что-то молча не работает"), два механизма.
3. **qex.** survivor выберет доля feedback_* (`feedback_qex_full_rebuild_runbook`) ← `project_qex_reindex_timeout` (таймаут 10 с в бинаре), `project_qex_model` (разные модели по платформам, silent-CPU). В `CLAUDE.md` часть уже есть; причина "тормозят несмёрженные BM25-сегменты" противоречит "таймаут зашит в бинарь" — решить, что верно.
4. **claude-kit.** survivor `project_devseed_overwrites_claude_dir` ← `project_claude_kit_migration` (как обновлять; пути Mac пометить).
5. **kind-channels / release-on-evict.** survivor `project_kind_channels_dead_evict_branch` ← `.claude/agent-memory/teamlead/project_live2_release_on_evict.md` (вне моей доли, нашёл git grep) + строка LIVE-2 из `project_live_verification_2026_07_21`.
6. **monotonic.** `project_monotonic_resolution_windows` ← одна строка "cycle_metrics monotonic дал FPS=0" из `project_telemetry_self_publish`.
7. **Закрытые планы наблюдаемости (22 файла: f2..f7, 5.8-5.12, tail_repair, stdlib_migration, config_layers, session_ttl, subscription_broker, namespace_symmetry, audit, closure_progress, otel_state, observation_port).** Не слияние, а одна строка в `ARCHIVE.md` на план + ссылка `plans/<slug>`. ARCHIVE.md уже имеет раздел "Observability Ф2–Ф8".
8. **Закрытые телеметрийные планы (7 файлов)** и **cross-tab B..G (6 файлов)**, **pipeline этапы (6 файлов)** — то же: одна строка ARCHIVE на группу.

Уроки, которые стоит вынуть из STATE-файлов до архивации (проверить, что их нет в ADR/README):
- `project_pult_control_panel`: секция Services обязана реализовать `action_buttons()`, иначе падает весь Services-таб (тест спеки не ловит).
- `project_observability_namespace_symmetry`: точки в паттернах троттла ломают плоский namespace.
- `project_backend_control_mcp`: MCP говорит с бэкендом только через RouterManager.
- `project_backend_ctl_recorder_kept`: решение владельца 07-22 "recorder оставить" — в `plans/queue/decisions.md` его нет.
- `project_observability_closure_progress`: "главное число Ф3 не взято" (горизонт 2.6 ч против 24) — нет в OPEN_QUESTIONS? не проверял.

## 3. RULE-файлы (5) — механизм и текст одной строкой

| Файл | Механизм | Строка |
|---|---|---|
| `project_devseed_overwrites_claude_dir` | `.claude/CLAUDE.md`, раздел про `.claude/` | "`claude-kit upgrade --apply` молча затирает .claude/: ценное класть только в preserved-места (CLAUDE.md, modes/_stack.md, settings.local), сверять diff до upgrade." |
| `project_gui_stand_production_entry_only` | команда `core:quality:observability-acceptance` + `project-rules` | "Живой GUI-стенд поднимать только боевой точкой входа с INSPECTOR_GUI_UNATTENDED=1 и настоящими окнами; через BackendHarness процесс gui виснет, headless занижает нагрузку." |
| `project_priority_engine_first` | `plans/queue/ORDER.md` (правило маятника уже ссылается) | "Приоритет — маятник по свободному времени: к стенду за видимым результатом, фреймворк второй полосой; порядок работ только в plans/queue/ORDER.md." |
| `project_memory_module_consolidation` | `plans/2026-07-06_constructor-master/h-memory-consolidation-plan.md` | "Память (SHM, пул, реестр) — один модуль с фасадом и взаимозаменяемой реализацией; не размазывать по framework." |
| `project_universal_lifecycle_decision` | `plans/2026-10-03_lifecycle-owner-scope/DESIGN.md` | "Подписки, потоки, процессы, окна, виджеты — один scope-владелец; чинить корень, не симптом; 5.5d не вливать как тест-фикс." После закрытия плана Ж файл в ARCHIVE. |

Заметка: хук-кандидат нашёл один — `devseed`-правило можно проверять в `claude-kit upgrade` обёртке; остальные четыре — решения владельца, их место в `plans/queue/decisions.md`, не в памяти.

## 4. Кандидаты в новый MEMORY.md из моей доли (12)

- [claude-kit upgrade затирает .claude/](project_devseed_overwrites_claude_dir.md) — ценное только в preserved-места, diff до upgrade
- [Универсальный жизненный цикл](project_universal_lifecycle_decision.md) — один scope-владелец; план lifecycle-owner-scope (до закрытия плана)
- [Приоритет — маятник](project_priority_engine_first.md) — порядок только в plans/queue/ORDER.md
- [backend_ctl: сигнал связан с реальностью?](project_backend_ctl_signal_integrity.md) — ложный success/timeout/ноль; missing != 0 != null
- [GUI-стенд боевым входом](project_gui_stand_production_entry_only.md) — INSPECTOR_GUI_UNATTENDED=1, не BackendHarness
- [Рантайм-правка умирает через 300 с](project_runtime_knob_expires_in_300s.md) — L3 TTL молча снимает гейт телеметрии
- [Сбой есть, причина проглочена](project_live_findings_webcam_2026_07.md) — три находки, ни одну не ловили 504 теста
- [Новый state-корень = подписка в GuiProcess](project_calibration_gui_progress.md) — иначе плагин не достигнет GUI
- [monotonic Windows = 15.6 мс](project_monotonic_resolution_windows.md) — разности <100 мс на сетку (local-only)
- [venv держит MCP backend_ctl](project_venv_locked_by_mcp.md) — переустановка numpy/cv2: закрыть VS Code (local-only)
- [Стек 2026](reference_tech_stack_2026.md) — сверяться с docs/direction/TECH_STACK_2026.md перед новой зависимостью
- [Switch рецепта: устаревшее состояние](project_switch_routing_stale.md) — стейл-PSR и слой L2 после switch (после слияния групп)

Остальные 31 KEEP-файла — по тегам модулей (раздел 6), не по строке в индексе.

## 5. Счётчики и экономия

Файлов в доле: 157 (160 минус MEMORY, CRAFT, ARCHIVE; эти три разобраны в разделе 6).

| Kind | N |
|---|---|
| STATE | 73 |
| LESSON | 27 |
| STALE | 24 |
| REDUNDANT | 18 |
| REFERENCE | 10 |
| RULE | 5 |
| DUP | 0 как отдельный kind (слияния — отдельной колонкой action) |

Действия: KEEP или MERGE-в-survivor — 43; ARCHIVE — 114 (597 КБ из 741 КБ моей доли).

Индекс (merged/MEMORY.md = 33 392 байт, 24 067 символов; кириллица 2 байта на символ, поэтому "8 КБ" = около 4 000 русских символов):
- 33 строки индекса ссылаются только на мои ARCHIVE-файлы: **4 827 байт** уходит сразу.
- Весь раздел "Активные проекты и долги" (8 063 байт, 42 ссылки): из 42 ссылок 14 STATE, 3 STALE, 5 REDUNDANT, 15 LESSON, 2 RULE, 3 не мои. Заменяется одной строкой "состояние планов — plans/queue/ORDER.md" и 4-5 строками LESSON. Экономия до **7 КБ**.
- Раздел "Домен: робот, зрение, ML" (1 097 байт) — указатели на STATE/REDUNDANT (`ml_train`, `dataset_gen`, `sketch_robot_draw`, `letter_angle_training`, `robot_vfd_services`): 1 КБ в ноль.
- С учётом секций "Агентская/ревью/git" (6.2 КБ) и "Ремесло" (7.1 КБ) — их режет доля feedback_*; моя доля даёт 11-12 КБ из нужных 25 КБ сжатия.

## 6. Обзор индексных файлов

### 6.1 `merged/MEMORY.md` — разделы

| Раздел | Байт | Что это | Вердикт |
|---|---|---|---|
| Шапка (3 буллета + абзац "Новая сессия начинает отсюда") | ~1 500 | чистые указатели: CRAFT, ARCHIVE, `docs/sessions/2026-09-07_handoff-parallel-start.md` | указатель на handoff 4 недели назад, лежит рядом `docs/handoffs/2026-10-03_*`; оставить одну строку "последний handoff: ls docs/handoffs" |
| Пользователь и окружение | 2 921 | 21 ссылка, REFERENCE и окружение; много local-only (Windows, cp866, GPU) | оставить 6 строк, остальное в одну REFERENCE-строку "окружение Windows → файл" |
| Стоящие правила владельца | 3 244 | правила владельца; многие дублируют решения в `plans/queue/decisions.md` | свернуть в 8-10 строк; приоритет-маятник = ссылка на ORDER.md |
| Агенты, ревью, git | 6 212 | 36 ссылок; 17 из них — git/worktree/pre-commit ловушки | сгруппировать по механизму (worktree, hooks, commit) 6-8 строк |
| Ремесло → CRAFT | 7 099 | 27 ссылок "ядро, что сработает без чтения"; 8 ссылок те же, что в CRAFT (дубль) | оставить 5-6 строк ядра, остальное — только в CRAFT |
| Активные проекты и долги | 8 063 | 42 ссылки; 40% STATE, почти весь раздел — указатели на планы | удалить, заменить ORDER.md |
| Домен: робот, зрение, ML | 1 097 | указатели на STATE | удалить |
| IPC, роутинг, планы | 3 096 | 20 ссылок; смесь feedback и STATE | оставить 3-4 урока |

**Дубль между MEMORY и CRAFT.** Одинаковые ссылки (8): `feedback_a_budget_belongs_to_a_path_not_to_a_mechanism`, `feedback_a_stand_with_a_verdict_is_also_a_harness`, `feedback_plausible_is_not_verified`, `feedback_prove_test_red_without_fix`, `feedback_silent_detector_proves_nothing`, `feedback_test_authorship_three_roles`, `feedback_tester_always_and_inject_against_it`, `feedback_three_lenses_three_defect_classes`. Семантический дубль больше: "три роли авторства", "тестер один раз на механизм", "инъекция на каждое свойство", "ноль в инъекции" — одни и те же идеи стоят в обоих местах с разными заголовками, и они же дословно в `.claude/CLAUDE.md` раздел "Test authorship". Оставить в индексе только указатель на CRAFT плюс 2 строки.

**Ссылки на STATE/STALE/REDUNDANT-файлы.** В MEMORY.md 67 из моих 157 файлов; 33 из них — AR (список в таблице 1: все `project_f*`, `project_observability_*` кроме store_error_routing, `project_telemetry_*`, `project_pipeline_*`, `project_cross_tab_*`, `project_phase5_*`, `project_otel_export_plan_state`, `project_observability_closure_progress`, `project_honest_verdict_2026_09`, `project_line_sim_vision`, `project_work_order_2026_09_22_line_sim_then_pult` и др.). В MEMORY они стоят 4 827 байт строками только про них. Побочные свидетельства устаревания индекса: строка "порядок 2026-09-09: line-sim → наблюдаемость+otel → робот" устарела (ORDER.md 10-03: Ж первым); строка "std_facade не используется — 76 файлов в пустоту" опровергнута (`get_std_logger` теперь в 142 файлах); "Командный режим... живой прогон не делался" опровергнуто пилотом v2.

Мёртвых ссылок в MEMORY.md и CRAFT.md нет (проверил: все 179 + 173 цели есть в merged/).

### 6.2 `merged/CRAFT.md` (40 233 байт, 164 строки, 173 ссылки)

| Раздел | Байт | Что |
|---|---|---|
| Канон тестирования и инъекции | 12 588 | 49 ссылок; ядро ремесла, нужно, но тяжёлое; часть дублирует `.claude/CLAUDE.md` "Test authorship" |
| Вакуумные тесты и ассерты | 6 188 | 31 ссылка, чистые указатели с однострочным смыслом |
| Предохранители и механизмы | 3 486 | 23 ссылки |
| Классы дефектов (живьём) | 2 970 | 19 ссылок |
| Конфиг и схемы | 2 850 | 16 ссылок |
| Qt / GUI | 5 357 | 20 ссылок |
| Перенесено из ядра MEMORY.md 2026-09-05 | 5 697 | 18 ссылок, "строки дословные" — ситуативные записи, не доказавшие ценность |

CRAFT.md — весь указатель (в нём нет собственных уроков), все ссылки ведут на `feedback_*`. Он загружается "по триггеру", то есть цена 40 КБ платится только при чтении, но 12.5 КБ раздела "Канон" агент читает целиком перед каждым тестом. Предложение: разбить на 3 файла по триггеру (tests, review/verdict, qt/config), чтобы читать 8-12 КБ вместо 40 КБ; последний раздел ("Перенесено из ядра") отдать доле feedback_* на проверку.

### 6.3 `merged/ARCHIVE.md` (10 581 байт)

Правильный дом для 87 моих файлов (на них ссылается только ARCHIVE). 25 ссылок из раздела "Перенесено из индекса 2026-09-05" — те же STATE-файлы, что в моей таблице. Добавить 1 строку на группу из раздела 2.7-2.8.

### 6.4 Скелет нового MEMORY.md ≤ 8 KB (≈4 000 русских символов, ≈45 строк по 170 байт)

1. **Шапка (0.6 КБ):** 3 указателя — `CRAFT.md` (когда читать: тесты / инъекции / вердикт ревью / конфиг / Qt), `ARCHIVE.md`, "состояние планов — `plans/queue/ORDER.md`, последний handoff — `ls docs/handoffs`". Одна фраза: "правило не архивируется, пока не стало механизмом".
2. **Правила, что должны сработать до того, как о них вспомнят (2.0 КБ, 10-12 строк):** qex: сверить `last_indexed`; тестер до кода + инъекция на каждое свойство; один писатель — одно дерево, стейджить явные пути; `uv sync --inexact`, venv проекта, пакеты ставит пользователь; no global taskkill; RU-вывод (cp866, PYTHONIOENCODING); fix-forward / FREEZE, не KILL; флаг закрыт, когда удалён; решения владельца — ORDER.md/decisions.md. Каждое — строка из доли feedback_*, не из моей.
3. **Окружение, local-only (0.8 КБ, 5 строк):** venv и MCP (`project_venv_locked_by_mcp`), monotonic 15.6 мс, CUDA torch/GPU (`project_cuda_torch_setup`, `reference_gpu_monitoring_windows`), qt-mcp `QT_MCP_PROBE=1`, цель владельца (`user_career_goal`, 1 строка).
4. **Решения владельца с живым планом (0.7 КБ, 3-4 строки):** lifecycle-owner-scope, приоритет-маятник, framework-first / FREEZE, TECH_STACK_2026.
5. **Живые уроки по модулю/механизму (2.5 КБ, 12 строк-тегов):** строка = тег + 2-4 имени файлов без описаний. Теги из моей доли: `backend_ctl` (signal_integrity, socket_bypasses_mw, live_findings), `router/switch` (switch_routing_stale, kind_channels_dead_evict_branch, state_topology_gate), `observability` (store_error_routing, runtime_knob_300s, config_voice), `gui/state` (calibration_gui_progress, gui_system_queue_storm, gui_stand), `recipes` (recipe_inspector_join_key), `tests/harness` (concurrent_backends_trap, fencing_test_race, root_gate_misses), `process lifecycle` (graceful_stop_debt, universal_lifecycle), `hardware` (vfd_bridge_robot_reboot, hikvision_aspect_ratio), `perf` (strokes_points_perf).
6. **Тест-ядро (1.0 КБ, 5 строк):** вместо 7 КБ — три роли авторства; ноль наблюдений/ноль инъекции = результат наблюдения; утверждение об отсутствии требует проверки достижимости; правдоподобное != проверенное; число без разброса — наблюдение.
7. **Служебное (0.4 КБ):** как создать запись (`/core:memory:remember`), формат тегов `module:` / `mechanism:`, лимит строки 170 байт.

Итого ≈ 8.0 КБ. Условие: 31 KEEP-LESSON моей доли и ~110 feedback-ядра получают `module:` / `mechanism:` во frontmatter, а находятся поиском (`/core:memory:search`), а не строкой индекса.

## 7. Что в моей классификации ненадёжно

- **Читал только начало** (frontmatter + 3-4 строки тела) у всех 157 файлов; целиком не читал ни одного. Для файлов STATE с большим телом (`project_constructor_master_progress` 39 КБ, `project_cross_tab_phase_g` 35 КБ, `project_observability_closure_progress` 54 КБ, `project_backend_ctl_d1_session_isolation` 18 КБ, `project_phone_gateway_service` 12 КБ) в хвосте могут лежать уроки; я предложил "вынуть отдельным проходом", не вынул.
- **Статус "план закрыт" взят из ORDER.md и списка `plans/_archive/`**, а не из чтения самих планов. ORDER.md сам пишет, что шапки планов врали минимум в пяти случаях; я доверил его таблице закрытых планов (строки ~261-283), датированной 2026-10-03.
- **Не проверил живьём** (стоит перепроверить до архивации): `project_app_module_windows_test_debt` (красны ли 2 теста сейчас), `project_command_engine_audit` (ActionBus сирота ли), `project_gui_system_queue_storm` (чинено ли), `project_switch_routing_stale` (фикс через PM-хаб сделан?), `project_recipe_save_load_arch` (долги on_result и switch≠boot), `project_processes_workers_runtime` (assigned_worker PENDING), `project_macos_shm` (15 skipped), `project_device_hub` (контракты из ревью есть в README?), `project_recipe_inspector_join_key` (имя `_hoist_inspector_from_metadata` не найдено в коде git grep по `*.py`; найдено только в docs/audits и в памяти — возможно, функция переименована или удалена).
- **Неясные границы REDUNDANT и STATE:** `project_services_vs_plugins`, `project_hierarchical_addressing`, `project_pipeline_recipe_driven_launch` отнёс к REDUNDANT по общему смыслу ("то же говорит CLAUDE.md / ADR"), не сверяя текст ADR-120 и CLAUDE.md построчно.
- **Слияние qex** (`project_qex_reindex_timeout` против CLAUDE.md "тормозили BM25-сегменты"): противоречие нашёл, решения нет.
- **Размеры индекса.** В задании "~21.5k chars"; `merged/MEMORY.md` — 24 067 символов / 33 392 байт (merge взял более новую версию). Цель "8 KB" я трактовал как байты; в символах русского текста это в два раза плотнее.
- **feedback_*-ссылки индекса не оценивал** (чужая доля); цифры экономии по индексу касаются только ссылок на мои файлы.
