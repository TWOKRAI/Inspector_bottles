# MEMORY.md — индекс памяти проекта

Три уровня. Здесь только **живое**: правила, окружение, открытые долги.
- [CRAFT.md](CRAFT.md) — ремесло: тесты, инъекции, предохранители, классы дефектов, конфиг/схемы, Qt (~110 записей)
- [ARCHIVE.md](ARCHIVE.md) — история закрытых фаз и треков; спящие треки перенесены туда 2026-09-05

Ни один из них не грузится сам — читать по триггеру, указанному в блоке-указателе.
Правило не архивируется никогда: оно обязано сработать раньше, чем о нём вспомнят.

## Пользователь и окружение
- [Цель владельца](user_career_goal.md) — ведущий инженер-электроник; 2026-08-20: НЕ в программисты, а АСУТП + робототехника + CV; Inspector_bottles = ключевое портфолио
- [Стек 2026](reference_tech_stack_2026.md) — сверяться с docs/direction/TECH_STACK_2026.md при правках стека/перфа/зависимостей
- [graphify-MCP setup](project_graphify_mcp_setup.md) — uv tool install --with mcp; .graphifyignore
- Окружение: [uv sync сносит необъявленное](feedback_uv_sync_prunes_venv.md) → --inexact · [venv держит MCP](project_venv_locked_by_mcp.md) → закрыть VS Code · [всегда project .venv](feedback_always_project_venv.md) · [пакеты ставит пользователь](feedback_package_install_by_user.md)
- [RU-вывод и wc врут](feedback_ru_output_encoding_and_wc.md) — cp866; 0xA0; PYTHONIOENCODING=utf-8 · [Think EN, speak RU](feedback_think_en_speak_ru.md)
- [monotonic Win = 15.6 мс](project_monotonic_resolution_windows.md) — разности <100 мс на сетку · [No global taskkill](feedback_no_global_taskkill.md) — только TaskStop или PID
- [CUDA torch](project_cuda_torch_setup.md) — cu124 колесом; PyPI даёт +cpu · [GPU-мониторинг Win](reference_gpu_monitoring_windows.md) — Task Manager прячет CUDA, смотреть nvidia-smi
- qex: **[СНАЧАЛА сверить свежесть](feedback_check_qex_freshness_before_use.md)** — last_indexed vs сегодня, устаревший отвечает уверенно · [таймаут реиндекса](project_qex_reindex_timeout.md) · [бюджет реиндекса](feedback_qex_reindex_budget.md) — keep_alive=-1 · [запросы по-английски](feedback_qex_query_english_code_bias.md) — RU-перефраз мимо

## Стоящие правила владельца
- [Приоритет — маятник по свободному времени](project_priority_engine_first.md) — 2026-08-18: к стенду за видимым результатом; фреймворк — вторая полоса; окно codemod — по паузе, не по дате
- [Framework-first](feedback_framework_first.md) — framework универсален, прототип расходный · [Fix forward](feedback_fix_framework_forward.md) — улучшение, не удаление · [FREEZE, не KILL](feedback_freeze_over_kill.md) — мёртвый код замораживать
- [Fewer layers](feedback_fewer_layers.md) — меньше слоёв строго лучше · [всё через BaseManager](feedback_all_components_base_manager.md) · [три менеджера — одна база](feedback_three_managers_share_base.md) · [Logger/Error/Stats через менеджеры](feedback_logger_error_stats_managers.md) — ObservableMixin
- [Constructor modularity](feedback_constructor_modularity.md) — pluggable/testable/composable · [неиспользуемый путь = контракт](feedback_unused_paths_are_contracts.md) — «нет вызывающих» ≠ «не нужен», квалифицировать громко
- [MVP для GUI-вкладок](feedback_mvp_pattern.md) — всегда полный · [Tab order](feedback_tab_order.md) — Settings → Recipes → функциональные · [конвенции диалогов](feedback_dialog_conventions.md) — Сохранить (default)/Не сохранять/Отмена
- [Services vs Plugins](project_services_vs_plugins.md) — крупный SDK vs мелкая обработка; side-effect-процесс = плагин в GenericProcessApp + фрагмент топологии
- [Флаги не костыли](feedback_flags_must_not_become_crutches.md) — закрыт когда УДАЛЁН · [FW_* реестр](project_feature_flags_registry.md) — ctor>env>default
- [Фичи после доказательства](feedback_tool_features_before_validation.md) — минимум → реальная задача → фичи
- [Один пишущий логгер](feedback_one_log_writer.md) — остальное вид поверх · [std_facade не используется](project_std_facade_unused.md) — 76 файлов в пустоту
- [Память одним модулем](project_memory_module_consolidation.md) — фасад/интерфейс, не размазывать по framework
- [qex/codegraph/serena/graphify напрямую](feedback_use_graph_semantic_tools.md) — не только через Explore

## Агенты, ревью, git
- [Командный режим: Agent Teams + эскалация](project_team_mode_agent_teams.md) — 2026-09-02: /dev:team, cto=Fable, junior=Haiku, правила в skill project-rules, три хука-гейта; живой прогон не делался
- [Зеркало агентов дрейфует от источника плагина](feedback_materialized_agents_drift_from_plugin_source.md) — правка в .claude/agents/dev/ без plugins/dev/agents/ = claude-kit sync снесёт молча; diff -q до пересборки
- [Непарный апостроф ломает Bash-команду](feedback_bash_tool_unbalanced_quote_breaks_command.md) — heredoc не спасает; скрипты с прозой — через Write и файлом
- [Model economy](feedback_model_economy_scheme.md) — Fable на вердикты; финдеры Sonnet/Opus · [сплит исполнение/ревью](feedback_model_split_impl_vs_review.md) — Sonnet 5 дефолт, Opus верх, Fable план/свод · [три уровня ревью](feedback_review_economy_tiers.md) — полное только на рисковые
- [claude-cli бэкенд = полная сессия за вызов](feedback_claude_cli_backend_costs_a_full_session.md) — 53 вызова съели дневной лимит; вызовы × ~50k ДО запуска; мельчить батчи = множить накладные
- [Оформленное ревью до merge](feedback_formal_review_before_merge.md) — без /code-review в транскрипте merge блокируется
- [Отлаживать через backend_ctl](feedback_backend_ctl_for_agents.md) — не GUI, не qt-mcp · [Layer: mixed](feedback_backend_ctl_layer_mixed.md) — хук не знает tools · [Оффскрин для агентов](feedback_no_qt_popups_offscreen.md) — QT_QPA_PLATFORM=offscreen
- [Резюм агента родит призрака](feedback_agent_resume_ghost.md) — SendMessage может дать ДВА инстанса, проверять mtime зоны
- worktree: [стейл-база](feedback_worktree_stale_base.md) — проверять базу до старта · [при одном файле](feedback_worktree_for_parallel_samefile.md) — от committed HEAD · [walk исключает .claude/worktrees](feedback_walk_skips_worktrees.md)
- [Чужая сессия в том же дереве](feedback_a_peer_session_shares_the_tree.md) — `git add -A` затянул чужие 98 строк; сверять ListAgents, стейджить явные пути · [Parallel commit race](feedback_parallel_agents_commit_race.md) — макс 2 без worktree · [pre-commit stash collision](feedback_precommit_stash_collision_2plus_agents.md) — recovery `git show :path > path` · [откат pre-commit ест незастейдженное](feedback_precommit_rollback_drops_unstaged_edits.md)
- [Грабли merge в main](feedback_git_main_merge_hook_traps.md) — `git merge -F -` не читает stdin; protect-branch блокирует commit на main · [stash pop чужого стеша](feedback_git_stash_pop_wrong_stash.md) — маркеры конфликта в дереве
- [Commit msg format](feedback_commit_msg_format.md) — хук терпит перенос; ruff → re-stage · [commit забирает весь индекс](feedback_commit_takes_the_whole_index.md) · [agent commit quality](feedback_agent_commit_quality.md) · [ruff сносит свежий импорт](feedback_ruff_strips_unused_import.md) — импорт и использование ОДНИМ Edit
- [API MCP дрейфует](feedback_mcp_tool_api_drift.md) — ROUTING.md может врать · [sentrux depth непрозрачна](feedback_sentrux_depth_opaque.md) · [sentrux gate сужен](feedback_sentrux_gate_narrowed.md) — блок только циклы↑/god↑
- [Атрибутируй источник до реза](feedback_attribute_the_source_before_cutting.md) — агенты/команды с ДВУХ уровней (.claude/ и ~/.claude/); сверять состав множеств; экономию заявлять после прогона
- [Dual-write разъехался по содержимому](feedback_dual_write_by_copy_destroys_the_other_side.md) — правды нет ни в одной копии; **правку вносить в обе копии отдельно, `cp` затирает молча**, diff ДО записи
- [devseed перетирает .claude/](project_devseed_overwrites_claude_dir.md) — preserved: CLAUDE.md, modes/_stack.md, settings.local · [миграция на claude-kit](project_claude_kit_migration.md)

## Ремесло: тесты, инъекции, дефекты, конфиг, Qt → [CRAFT.md](CRAFT.md)
**Читать CRAFT.md целиком ПЕРЕД тем, как** писать тесты · планировать инъекции · выносить вердикт ревью · писать «не может сломаться» · править конфиг/схему Pydantic · трогать Qt-виджеты или гонять qt-mcp. Ядро, которое обязано сработать и без чтения:
- [Сторож «хотя бы раз» слеп к точечной поломке](feedback_a_guard_that_counts_at_least_once_is_blind.md) — за сломанный метод лок брал СОСЕД; литералы по дорогам · [разность прячет то, что по обе стороны](feedback_a_delta_benchmark_hides_what_sits_on_both_sides.md) · [«не разобрал» ≠ «данных нет»](feedback_unparsed_is_not_absent.md) — молчащий парсер дал зелёный validate
- [Бюджет принадлежит ДОРОГЕ, не механизму](feedback_a_budget_belongs_to_a_path_not_to_a_mechanism.md) — «+5 мкс» Task 3.3 написан на лог-запись у эмитента, числа едут пачкой; перенеся бюджет на соседний путь, я едва не закрепил три ветки навсегда; мерить по дорогам и всегда рядом с ТЕМПОМ
- [Фикстура миграции, собранная сегодняшним писателем, проверяет писателя](feedback_a_migration_fixture_built_by_todays_writer_tests_the_writer.md) — заплата «засыпки нет вовсе» убила 1 тест из ожидаемых 3; легаси-строки вписывать сырым INSERT, и чинить ВСЕ строки фикстуры, а не одну
- [Транспорт арбитрирует то, чего не понимает](feedback_transport_arbitrates_what_it_cannot_understand.md) — два писателя в один лист; троттл вырезает молча (proceed=true без rejection_reason)
- [Приоритет у приёмника](feedback_priority_belongs_to_the_receiver.md) — нет модели слоёв → доигрывать порядок ЗАПИСИ, не лестницу уровней · [свойство не проверено у соседа](feedback_property_unchecked_at_the_second_party.md) — и на втором call-site; ноль от инъекции воспроизводить руками
- [Ноль наблюдений = результат наблюдения](feedback_zero_observations_looks_like_a_result.md) — сторож требует passed>0/mtime/собранность, не только failed==0 · [Ноль в инъекции = сторожа не собрались](feedback_injection_zero_may_mean_the_guards_were_not_collected.md) — база матрицы БЕЗ -k, collected числом до заплат · [Инъекция обязана доказать живость оси](feedback_an_injection_must_prove_its_axis_is_live.md) — пятое прочтение нуля: `round`/`int` совпали на 0 из 144, ось пуста; traceback тоже не ось
- [Утверждение об ОТСУТСТВИИ требует парной проверки достижимости](feedback_an_absence_assertion_needs_a_reachability_check.md) — тест-негатив сверял голые имена с qualname'ами: предмет красный, тест зелёный
- [Три роли авторства](feedback_test_authorship_three_roles.md) — tester от acceptance, ревьюер запуском · [тестер всегда + инъекции против него](feedback_tester_always_and_inject_against_it.md) — его зелёный не результат
- [Тестер один раз на механизм и ДО кода](feedback_tester_once_per_mechanism_before_the_code.md) — второй заход нашёл ноль за 479k; красный набор до кода = ТЗ · [слепоту даёт worktree, не проза](feedback_tester_blindness_needs_a_worktree.md)
- [Число без разброса по повторам — наблюдение, не замер](feedback_a_number_without_spread_across_repeats_is_an_observation.md) — три прогона одного кода: 118.7, 48.8, 0.5 мкс; контроль ловит неверную ПРИЧИНУ, повтор ловит ОТСУТСТВИЕ эффекта
- [Тест не доказан без красного](feedback_prove_test_red_without_fix.md) — инъекция на КАЖДОЕ свойство, предсказание до прогона · [молчащий детектор](feedback_silent_detector_proves_nothing.md) · [Коммит ПЕРЕД инъекциями](feedback_inject_only_after_the_work_is_committed.md) — `git checkout` в харнессе съел незакоммиченное
- [Правдоподобное ≠ проверенное](feedback_plausible_is_not_verified.md) — вердикт без вход→выход = совет · [Три объектива — три класса](feedback_three_lenses_three_defect_classes.md) — тесты=механика, прогон=проводка, ревью=связки · [Фраза шире команды, которую цитирует](feedback_the_sentence_is_wider_than_the_command_it_quotes.md) — прогон настоящий, `--include=*.py` во фразе стал `**`

## Активные проекты и долги
- [Вердикт 2026-09-04: 6.5/10, доказанность продукта 4/10](project_honest_verdict_2026_09.md) — шина ~0.3/0.6 мс на хоп (<5% кадра, потолок FPS = таймер Windows); балл меняют P-1 инспектор с числами и P-2 второе приложение чужими руками; очередь в QUEUE 5b; ADR про ROS 2 уже есть в TECH_STACK §3
- [otel-export ред. 4](project_otel_export_plan_state.md) — 2026-09-06: **Ф0 закрыта** и влита в closure (`0024b6f7`), 56 зелёных, `validate.py` exit 0; Ф1 разблокирована снимком стенда `1f40ce0d`; трек живёт в своём worktree `.claude/worktrees/otel`, слияние одностороннее closure → otel; 2.4 стартует по признаку «3.3 **принята ревью**», не «закоммичена», и **импортирует** предохранитель closure, свой не пишет
- [observability-closure: Ф0+Ф1+Ф2 закрыты, Ф3 — 4 из 9](project_observability_closure_progress.md) — 2026-09-05: закрыты 3.0, 3.5, 3.1; дубль снапшота снят (A/B 2140→1257 КиБ/ч), форма числа переехала в базу вердиктом CTO (ADR-CRM-017), гейт 9757; за владельцем — merge в main и telemetry.broadcast
- [Голос конфига принадлежит стадии «применяю»](project_config_voice_belongs_to_the_apply_stage.md) — config.reload разбирает секцию ШЕСТЬ раз тремя стадиями; окно маскирует; дом — Task 4.11
- [Универсальный механизм ручек — KnobManager](project_knobs_universal_manager.md) — 2026-09-02: ручка = одно объявление; observability первый потребитель; Task 4.9, при ≥3 потребителях свой план · [Сначала наблюдаемость, потом ponytail-audit](project_sequencing_observability_then_audit.md) — узкий проход после merge Ф2, полный после Ф5
- [line_sim: план создан](project_line_sim_vision.md) — буквы первыми; встроенная сборка; plans/line-sim/ Ф0–Ф6 (19 задач), ветка feat/line-sim
- [constructor-master](project_constructor_master_progress.md) — Ф0–Ф3 + трек F + Ф5-ядро закрыты; NEXT C1-C8 + app_module 5.11-5.13 · [чистка границ C1-C8](project_arch_boundaries_plan.md) — движок миграций идёт в recipe, НЕ generic
- [backend_ctl](project_backend_ctl_framework_module.md) — 8.0/10; резидуалы в backend-ctl-hardening · [ловушки](project_backend_ctl_signal_integrity.md) — ложный success/timeout · [сокет мимо receive-мидлвари](project_backend_ctl_socket_bypasses_mw.md) · [строгий край protocol.py](project_backend_ctl_missing_contract.md) — missing/None/null = три факта · [MCP только через RouterManager](project_backend_control_mcp.md) · [Диагностика — через backend_ctl](feedback_diagnose_live_system_with_backend_ctl.md) — соседи как контроль
- [Рантайм-правка умирает через 300 с](project_runtime_knob_expires_in_300s.md) — L3 TTL молча снимает гейт · [GUI-стенд боевым входом](project_gui_stand_production_entry_only.md) — INSPECTOR_GUI_UNATTENDED=1 · [два бэкенда конфликтуют](project_concurrent_backends_trap.md) — PID-реестр и SHM-cleanup
- [Command-engine audit](project_command_engine_audit.md) — ActionBus мёртв; RBAC дыра · [Kind-channels мёртвая ветка](project_kind_channels_dead_evict_branch.md) — send блокирует 1с вместо drop_oldest · [Гейт топологии state](project_state_topology_gate.md) — FW_STATE_TOPOLOGY_GATE
- [Pipeline узлы](project_pipeline_node_plugin_containers.md) — нода=плагин в контейнере; MovePlugin долг · [reuse по plugin_name](feedback_pipeline_reuse_plugins_widgets.md) — gui protected
- [Workers runtime](project_processes_workers_runtime.md) — assigned_worker PENDING · [архитектура](project_workers_architecture.md) · [timing](project_worker_cycle_timing.md) · [Graceful-stop debt](project_graceful_stop_debt.md) — 5с-ханг; stop_all_workers/put()
- [Camera settings](project_camera_settings_feature.md) — пресеты+actual; MJPG-долг · [Hikvision 4:3](project_hikvision_aspect_ratio.md) — иначе эллипсы
- Рецепты: [save/load FIXED×2](project_recipe_save_load_arch.md) — долги on_result/switch≠boot · [switch обязан раздать L2](project_switch_delivers_layer.md) — четыре живых дефекта · [join key FIXED](project_recipe_inspector_join_key.md) · [hikvision_letter ROI](project_hikvision_letter_robot.md) — 560,240,800,600
- [app_module Win test debt](project_app_module_windows_test_debt.md) — 2 красных только на Windows · [macOS SHM](project_macos_shm.md) — 15 skipped · [fw_version из git](project_fw_version_from_git.md) — 2.0.0+hash[.dirty]
- [Live-находки webcam 07](project_live_findings_webcam_2026_07.md) — ротация молчит; 23% ошибок невидимы

## Домен: робот, зрение, ML
- [ML-сервисы](project_ml_train_service.md) — ml_train v1, буква+угол 33/33 · [dataset_gen](project_dataset_gen_service.md) — cut-and-paste, пресет ru_letters_disk · [обучение буква+угол](project_letter_angle_training.md) — пресеты manual_letters
- [Рисование портрета роботом](project_sketch_robot_draw.md) — 3 дисплея + заморозка кадра · [FPS-просадка на детальных кадрах](project_strokes_points_perf.md) — O(n²) sort, trace_skeleton не векторизуется
- [Робот Delta + ПЧ GD20](project_robot_vfd_services.md) — универсальный modbus через Protocol · [VFD bridge](project_vfd_bridge_robot_reboot.md) — зависший ПЧ лечится перезагрузкой РОБОТА
- [Sources ⊥ Processing](project_source_topology.md) — разные регистры, связь по ключам региона · [display_module](project_display_registry.md) — реестр именованных SHM-каналов

## IPC, роутинг, планы
- [Register routing hang](feedback_register_routing_hang.md) — FieldRouting без канала = фриз GUI · [No SHM hacks](feedback_no_shm_hacks.md) — только framework middleware · [провод портов ≠ маршрут](feedback_port_wire_is_not_a_process_route.md) — плагин не вызван молча
- [Посылка плана устаревает](feedback_a_plans_premise_expires.md) — блокер воспроизводить, не сверять номера · [Один активный план](feedback_one_active_plan_per_tool.md) — иначе воскрешение отменённых задач
- [Plan-Driven Dev](project_plan_driven_dev.md) — slug, Refs-trailer · [checkboxes [x]+hash](feedback_plan_checkboxes.md) · [dual-save](feedback_plan_dual_save.md)
- [Причина из плана — гипотеза](feedback_the_plans_stated_cause_is_a_hypothesis.md) — симптом верен до числа, причина нет; зонд мимо подозреваемой плоскости · [Спека может врать](feedback_plan_spec_can_lie.md) — имя поля сверять с кодом · [позиционный вызов прячет имена](feedback_positional_call_hides_parameter_name_drift.md)
