# MEMORY.md — индекс памяти проекта

Три уровня. Здесь только **живое**: правила, окружение, открытые долги.
- [CRAFT.md](CRAFT.md) — ремесло: тесты, инъекции, предохранители, классы дефектов, конфиг/схемы, Qt (~110 записей)
- [ARCHIVE.md](ARCHIVE.md) — история закрытых фаз и треков; спящие треки перенесены туда 2026-09-05

**Новая сессия начинает отсюда: `docs/sessions/2026-09-07_handoff-parallel-start.md`** — карта четырёх полос (ветка, worktree, следующая задача, что не трогать), два решения владельца с числами, три команды уборки. Полос независимых четыре, дерево общее одно: **одно дерево — один писатель**.

Ни один из них не грузится сам — читать по триггеру, указанному в блоке-указателе.
Правило не архивируется никогда: оно обязано сработать раньше, чем о нём вспомнят.

## Пользователь и окружение
- [Стек 2026](reference_tech_stack_2026.md) — сверяться с docs/direction/TECH_STACK_2026.md при правках стека/перфа/зависимостей
- [graphify-MCP setup](project_graphify_mcp_setup.md) — uv tool install --with mcp; .graphifyignore
- Окружение: [uv sync сносит необъявленное](feedback_uv_sync_prunes_venv.md) → --inexact · [venv держит MCP](project_venv_locked_by_mcp.md) → закрыть VS Code · [всегда project .venv](feedback_always_project_venv.md) · пакеты ставит пользователь (архив)
- [RU-вывод и wc врут](feedback_ru_output_encoding_and_wc.md) — cp866; 0xA0; PYTHONIOENCODING=utf-8 · Think EN, speak RU (архив)
- [monotonic Win = 15.6 мс](project_monotonic_resolution_windows.md) — разности <100 мс на сетку · [No global taskkill](feedback_no_global_taskkill.md) — только TaskStop или PID
- [CUDA torch](project_cuda_torch_setup.md) — cu124 колесом; PyPI даёт +cpu · GPU-мониторинг Win (запись только в локальной папке) — Task Manager прячет CUDA, смотреть nvidia-smi
- qex: **СНАЧАЛА сверить свежесть (архив)** — last_indexed vs сегодня, устаревший отвечает уверенно · **[RUNBOOK полного реиндекса (Win)](feedback_qex_full_rebuild_runbook.md)** — Ollama вне харнесса, тег -qex, PYTHONUTF8, timeout=7200000; «без таймаутов» = мой дефект запуска · [таймаут реиндекса](feedback_qex_full_rebuild_runbook.md) · [бюджет реиндекса (под 4b)](feedback_qex_full_rebuild_runbook.md) — keep_alive=-1 · запросы по-английски (архив) — RU-перефраз мимо · [модель по платформам](project_qex_model.md) — macOS 8b-qex/4096 с 2026-09-13, Win 0.6b; ловушка Ollama.app молча на CPU

- [Жёсткий потолок агентов выключен по умолчанию](feedback_agent_hard_budget_is_off_by_default.md) — soft 100k лишь предупреждает; hard — файл `<id>.budget` или env; developer ушёл до 401k 2026-09-20

- [spawn копирует sys.path родителя](feedback_spawn_child_inherits_parent_sys_path.md) — PYTHONPATH из pytest до ребёнка не доезжает; заглушку «без пакета X» класть в sys.path родителя

## Стоящие правила владельца
- [Приоритет — маятник по свободному времени](project_priority_engine_first.md) — 2026-08-18: к стенду за видимым результатом; фреймворк — вторая полоса; окно codemod — по паузе, не по дате
- [Framework-first](feedback_framework_first.md) — framework универсален, прототип расходный · [Fix forward](feedback_framework_first.md) — улучшение, не удаление · [FREEZE, не KILL](feedback_framework_first.md) — мёртвый код замораживать
- [Fewer layers](feedback_framework_first.md) — меньше слоёв строго лучше · [всё через BaseManager](feedback_logger_error_stats_managers.md) · [три менеджера — одна база](feedback_logger_error_stats_managers.md) · [Logger/Error/Stats через менеджеры](feedback_logger_error_stats_managers.md) — ObservableMixin
- [Constructor modularity](feedback_framework_first.md) — pluggable/testable/composable · [неиспользуемый путь = контракт](feedback_unused_paths_are_contracts.md) — «нет вызывающих» ≠ «не нужен», квалифицировать громко
- [MVP для GUI-вкладок](feedback_mvp_pattern.md) — всегда полный · [Tab order](feedback_tab_order.md) — Settings → Recipes → функциональные · [конвенции диалогов](feedback_dialog_conventions.md) — Сохранить (default)/Не сохранять/Отмена
- [Флаги не костыли](feedback_flags_must_not_become_crutches.md) — закрыт когда УДАЛЁН · FW_* реестр (архив) — ctor>env>default
- [Ручки наблюдаемости: вкл/выкл на любой границе, ноль нагрузки в выключенном](feedback_observability_knobs_switchable_at_any_boundary_zero_cost_off.md) — решение владельца 2026-09-08: планка для КАЖДОГО параметра; замер: sink disable снимает запись, но не эмиссию (records_without_channels растёт); frame_trace — только env при импорте → Task 4.15
- [Фичи после доказательства](feedback_tool_features_before_validation.md) — минимум → реальная задача → фичи
- [Один пишущий логгер](feedback_one_log_writer.md) — остальное вид поверх · std_facade не используется (архив) — 76 файлов в пустоту
- [Память одним модулем](project_memory_module_consolidation.md) — фасад/интерфейс, не размазывать по framework

## Агенты, ревью, git
- [Непарный апостроф ломает Bash-команду](feedback_bash_tool_unbalanced_quote_breaks_command.md) — heredoc не спасает; скрипты с прозой — через Write и файлом
- Model economy (архив) — Fable на вердикты; финдеры Sonnet/Opus · [сплит исполнение/ревью](feedback_explicit_model_per_agent_role.md) — Sonnet 5 дефолт, Opus верх, Fable план/свод · три уровня ревью (архив) — полное только на рисковые
- [claude-cli бэкенд = полная сессия за вызов](feedback_claude_cli_backend_costs_a_full_session.md) — 53 вызова съели дневной лимит; вызовы × ~50k ДО запуска; мельчить батчи = множить накладные
- [Оформленное ревью до merge](feedback_formal_review_before_merge.md) — без /code-review в транскрипте merge блокируется
- [Отлаживать через backend_ctl](feedback_backend_ctl_for_agents.md) — не GUI, не qt-mcp · [Layer: mixed](feedback_backend_ctl_layer_mixed.md) — хук не знает tools · [Оффскрин для агентов](feedback_no_qt_popups_offscreen.md) — QT_QPA_PLATFORM=offscreen
- [Резюм агента родит призрака](feedback_agent_resume_ghost.md) — SendMessage может дать ДВА инстанса, проверять mtime зоны
- worktree: [стейл-база](feedback_worktree_stale_base.md) — проверять базу до старта · [при одном файле](feedback_a_peer_session_shares_the_tree.md) — от committed HEAD · [walk исключает .claude/worktrees](feedback_walk_skips_worktrees.md)
- [Чужая сессия в том же дереве](feedback_a_peer_session_shares_the_tree.md) — `git add -A` затянул чужие 98 строк; сверять ListAgents, стейджить явные пути · [Parallel commit race](feedback_precommit_stash_collision_2plus_agents.md) — макс 2 без worktree · [pre-commit stash collision](feedback_precommit_stash_collision_2plus_agents.md) — recovery `git show :path > path` · [откат pre-commit ест незастейдженное](feedback_commit_takes_the_whole_index.md)
- [Грабли merge в main](feedback_git_main_merge_hook_traps.md) — **единый формат merge: `merge: суть` + Why/Layer/Refs у всех (владелец 2026-10-03)**; `git merge -F -` не читает stdin; protect-branch блокирует commit на main · [stash pop чужого стеша](feedback_a_peer_session_shares_the_tree.md) — маркеры конфликта в дереве
- [Commit msg format](feedback_commit_takes_the_whole_index.md) — хук терпит перенос; ruff → re-stage · [commit забирает весь индекс](feedback_commit_takes_the_whole_index.md) · [agent commit quality](feedback_agent_commit_quality.md) · [ruff сносит свежий импорт](feedback_ruff_strips_unused_import.md) — импорт и использование ОДНИМ Edit
- API MCP дрейфует (архив) — ROUTING.md может врать · [sentrux depth непрозрачна](feedback_sentrux_depth_opaque.md) · sentrux gate сужен (архив) — блок только циклы↑/god↑
- [Атрибутируй источник до реза](feedback_attribute_the_source_before_cutting.md) — агенты/команды с ДВУХ уровней (.claude/ и ~/.claude/); сверять состав множеств; экономию заявлять после прогона
- [Спасение патчем теряет untracked](feedback_a_diff_based_rescue_omits_untracked_files.md) — «патчи сохранены» умолчало о тесте на 454 строки; спасать веткой от HEAD, пересечение считать числом
- [Хук, пишущий в общий файл, блокирует двух писателей](feedback_precommit_stash_collision_2plus_agents.md) — три коммита подряд отбиты; pathspec строит ВРЕМЕННЫЙ индекс из HEAD, и пустой git diff этого не видит; MM = обе стороны есть, а не обе целы
- [Хук мёртв на Windows из-за
](feedback_a_hook_dead_on_windows_by_a_trailing_cr.md) — `read < <(...)` оставляет `
`, `$(...)` снимает; autoformat молчал с 2026-05-15; живость хука доказывать настоящим входом, вывод агенту — только `additionalContext`
- [Dual-write разъехался по содержимому](feedback_dual_write_by_copy_destroys_the_other_side.md) — правды нет ни в одной копии; **правку вносить в обе копии отдельно, `cp` затирает молча**, diff ДО записи
- [devseed перетирает .claude/](project_devseed_overwrites_claude_dir.md) — preserved: CLAUDE.md, modes/_stack.md, settings.local · [миграция на claude-kit](project_devseed_overwrites_claude_dir.md)

## Ремесло: тесты, инъекции, дефекты, конфиг, Qt → [CRAFT.md](CRAFT.md)
**Читать CRAFT.md целиком ПЕРЕД тем, как** писать тесты · планировать инъекции · выносить вердикт ревью · писать «не может сломаться» · править конфиг/схему Pydantic · трогать Qt-виджеты или гонять qt-mcp. Ядро, которое обязано сработать и без чтения:
- [Сторож «хотя бы раз» слеп к точечной поломке](feedback_a_guard_that_counts_at_least_once_is_blind.md) — за сломанный метод лок брал СОСЕД; литералы по дорогам · [разность прячет то, что по обе стороны](feedback_a_delta_benchmark_hides_what_sits_on_both_sides.md) · [«не разобрал» ≠ «данных нет»](feedback_unparsed_is_not_absent.md) — молчащий парсер дал зелёный validate
- [Бюджет принадлежит ДОРОГЕ, не механизму](feedback_a_budget_belongs_to_a_path_not_to_a_mechanism.md) — «+5 мкс» Task 3.3 написан на лог-запись у эмитента, числа едут пачкой; перенеся бюджет на соседний путь, я едва не закрепил три ветки навсегда; мерить по дорогам и всегда рядом с ТЕМПОМ
- [Фикстура миграции, собранная сегодняшним писателем, проверяет писателя](feedback_a_migration_fixture_built_by_todays_writer_tests_the_writer.md) — заплата «засыпки нет вовсе» убила 1 тест из ожидаемых 3; легаси-строки вписывать сырым INSERT, и чинить ВСЕ строки фикстуры, а не одну
- [Транспорт арбитрирует то, чего не понимает](feedback_transport_arbitrates_what_it_cannot_understand.md) — два писателя в один лист; троттл вырезает молча (proceed=true без rejection_reason)
- [Приоритет у приёмника](feedback_priority_belongs_to_the_receiver.md) — нет модели слоёв → доигрывать порядок ЗАПИСИ, не лестницу уровней · [свойство не проверено у соседа](feedback_property_unchecked_at_the_second_party.md) — и на втором call-site; ноль от инъекции воспроизводить руками
- [Ноль наблюдений = результат наблюдения](feedback_zero_observations_looks_like_a_result.md) — сторож требует passed>0/mtime/собранность, не только failed==0 · [Ноль в инъекции = сторожа не собрались](feedback_injection_zero_may_mean_the_guards_were_not_collected.md) — база матрицы БЕЗ -k, collected числом до заплат · [Инъекция обязана доказать живость оси](feedback_injection_zero_may_mean_the_guards_were_not_collected.md) — пятое прочтение нуля: `round`/`int` совпали на 0 из 144, ось пуста; traceback тоже не ось
- [Утверждение об ОТСУТСТВИИ требует парной проверки достижимости](feedback_an_absence_assertion_needs_a_reachability_check.md) — тест-негатив сверял голые имена с qualname'ами: предмет красный, тест зелёный
- Три роли авторства (архив) — tester от acceptance, ревьюер запуском · тестер всегда + инъекции против него (архив) — его зелёный не результат
- Тестер один раз на механизм и ДО кода (архив) — второй заход нашёл ноль за 479k; красный набор до кода = ТЗ · слепоту даёт worktree, не проза (архив)
- [Число без разброса по повторам — наблюдение, не замер](feedback_a_number_without_spread_across_repeats_is_an_observation.md) — три прогона одного кода: 118.7, 48.8, 0.5 мкс; контроль ловит неверную ПРИЧИНУ, повтор ловит ОТСУТСТВИЕ эффекта
- [Один контроль доказывает «достаточно», не «единственно»](feedback_one_control_proves_sufficiency_not_exclusivity.md) — A7 6.4: replicate вернул 6.78°, а «не формула стороны» опровергнуто сеткой 2×2 (20.4° vs 42.2°); перед «X, а не Y» — перекрёстный контроль + «ни того, ни другого»
- [pytest-порядок импорта прячет цикл](feedback_pytest_import_order_hides_a_cycle.md) — i5 2.4a: 14 точечных красных вместо цикла, а `import layer_render` первым → ImportError; объяснение расхождения — только после прогона, импорты — чистый процесс в обоих порядках
- Тест не доказан без красного (архив) — инъекция на КАЖДОЕ свойство, предсказание до прогона · [молчащий детектор](feedback_zero_observations_looks_like_a_result.md) · [Коммит ПЕРЕД инъекциями](feedback_inject_only_after_the_work_is_committed.md) — `git checkout` в харнессе съел незакоммиченное
- [Правдоподобное ≠ проверенное](feedback_plausible_is_not_verified.md) — вердикт без вход→выход = совет · [Три объектива — три класса](feedback_three_lenses_three_defect_classes.md) — тесты=механика, прогон=проводка, ревью=связки · [Фраза шире команды, которую цитирует](feedback_the_sentence_is_wider_than_the_command_it_quotes.md) — прогон настоящий, `--include=*.py` во фразе стал `**`
- [Сигнал «отпусти соседа» — в момент факта](feedback_unblocking_signal_at_the_moment_of_fact.md) — 13 тестов зелёные, живой стоп как до правки
- [Стенд с вердиктом — тоже оснастка](feedback_a_stand_with_a_verdict_is_also_a_harness.md) — приёмником был наш `http.server`, отвечавший 200 на любой путь; настоящий otelcol дал 404, 102 теста из 214 пинили форму, не доставившую ничего

## Активные проекты и долги
- [Универсальный жизненный цикл — решение владельца](project_universal_lifecycle_decision.md) — 2026-10-03: один scope-владелец для подписок/потоков/процессов/виджетов; план 2026-10-03_lifecycle-owner-scope — первый приоритет; 5.5d не вливать как тест-фикс
- [Укороченный период ждёт старый срок](feedback_a_shortened_interval_waits_out_the_old_deadline.md) — 298 с при заказанных 5; срок пишется только внутри свипа, config.reload при этом отвечает success
- [Голос конфига принадлежит стадии «применяю»](project_config_voice_belongs_to_the_apply_stage.md) — config.reload разбирает секцию ШЕСТЬ раз тремя стадиями; окно маскирует; дом — Task 4.11
- Универсальный механизм ручек — KnobManager (архив) — 2026-09-02: ручка = одно объявление; observability первый потребитель; Task 4.9, при ≥3 потребителях свой план · Сначала наблюдаемость, потом ponytail-audit (архив) — узкий проход после merge Ф2, полный после Ф5
- [GUI-конструктор: слои и эталоны 2026-09-26](project_gui_constructor_layers_2026_09_26.md) — fw = конструктор (оболочка, подключения, виджет, раскладка), Services = срезы с пакетами виджетов, прототип тонкий; эталоны minimal_app + minimal_gui; Р-E T4.1 развёрнут
- constructor-master (архив) — Ф0–Ф3 + трек F + Ф5-ядро закрыты; NEXT C1-C8 + app_module 5.11-5.13 · чистка границ C1-C8 (архив) — движок миграций идёт в recipe, НЕ generic
- backend_ctl (архив) — 8.0/10; резидуалы в backend-ctl-hardening · [ловушки](project_backend_ctl_signal_integrity.md) — ложный success/timeout · [сокет мимо receive-мидлвари](project_backend_ctl_socket_bypasses_mw.md) · [строгий край protocol.py](project_backend_ctl_signal_integrity.md) — missing/None/null = три факта · MCP только через RouterManager (архив) · [Диагностика — через backend_ctl](feedback_backend_ctl_for_agents.md) — соседи как контроль
- [Рантайм-правка умирает через 300 с](project_runtime_knob_expires_in_300s.md) — L3 TTL молча снимает гейт · [GUI-стенд боевым входом](project_gui_stand_production_entry_only.md) — INSPECTOR_GUI_UNATTENDED=1 · [два бэкенда конфликтуют](project_concurrent_backends_trap.md) — PID-реестр и SHM-cleanup
- [Command-engine audit](project_command_engine_audit.md) — ActionBus мёртв; RBAC дыра · [Kind-channels мёртвая ветка](project_kind_channels_dead_evict_branch.md) — send блокирует 1с вместо drop_oldest · [Гейт топологии state](project_state_topology_gate.md) — FW_STATE_TOPOLOGY_GATE
- Pipeline узлы (архив) — нода=плагин в контейнере; MovePlugin долг · [reuse по plugin_name](feedback_pipeline_reuse_plugins_widgets.md) — gui protected
- [Workers runtime](project_processes_workers_runtime.md) — assigned_worker PENDING · архитектура (архив) · timing (архив) · [Graceful-stop debt](project_graceful_stop_debt.md) — 5с-ханг PM = выход ждёт feeder mp.Queue; 1 из 2 источников снят
- [Camera settings](project_camera_settings_feature.md) — пресеты+actual; MJPG-долг · [Hikvision 4:3](project_hikvision_aspect_ratio.md) — иначе эллипсы
- Рецепты: save/load FIXED×2 (архив) — долги on_result/switch≠boot · [switch обязан раздать L2](project_switch_delivers_layer.md) — четыре живых дефекта · join key FIXED (архив) · hikvision_letter ROI (архив) — 560,240,800,600
- [app_module Win test debt](project_app_module_windows_test_debt.md) — 2 красных только на Windows · macOS SHM (архив) — 15 skipped · fw_version из git (архив) — 2.0.0+hash[.dirty]
- [Live-находки webcam 07](project_live_findings_webcam_2026_07.md) — ротация молчит; 23% ошибок невидимы

## Домен: робот, зрение, ML
- ML-сервисы (архив) — ml_train v1, буква+угол 33/33 · dataset_gen (архив) — cut-and-paste, пресет ru_letters_disk · обучение буква+угол (архив) — пресеты manual_letters
- Рисование портрета роботом (архив) — 3 дисплея + заморозка кадра · [FPS-просадка на детальных кадрах](project_strokes_points_perf.md) — O(n²) sort, trace_skeleton не векторизуется
- Робот Delta + ПЧ GD20 (архив) — универсальный modbus через Protocol · [VFD bridge](project_vfd_bridge_robot_reboot.md) — зависший ПЧ лечится перезагрузкой РОБОТА
- Sources ⊥ Processing (архив) — разные регистры, связь по ключам региона · display_module (архив) — реестр именованных SHM-каналов

## IPC, роутинг, планы
- [Register routing hang](feedback_register_routing_hang.md) — FieldRouting без канала = фриз GUI · [No SHM hacks](feedback_no_shm_hacks.md) — только framework middleware · [провод портов ≠ маршрут](feedback_port_wire_is_not_a_process_route.md) — плагин не вызван молча
- [Посылка плана устаревает](feedback_a_plans_premise_expires.md) — блокер воспроизводить, не сверять номера · [Один активный план](feedback_one_active_plan_per_tool.md) — иначе воскрешение отменённых задач
- [Новый план — среди соседей](feedback_a_new_plan_must_be_placed_among_its_neighbours.md) — таблица владения + обратные ссылки в чужие планы
- Plan-Driven Dev (архив) — slug, Refs-trailer · [checkboxes [x]+hash](feedback_plan_checkboxes.md) · dual-save (архив)
- [Причина из плана — гипотеза](feedback_the_plans_stated_cause_is_a_hypothesis.md) — симптом верен до числа, причина нет; зонд мимо подозреваемой плоскости · [Спека может врать](feedback_the_plans_stated_cause_is_a_hypothesis.md) — имя поля сверять с кодом · [позиционный вызов прячет имена](feedback_positional_call_hides_parameter_name_drift.md)
- [Железо владельца и роли машин](project_hardware_roles_2026_09_23.md) — RTX 3050 4 ГБ = симулятор, Orin NX 16 = линия
- [Широкий except в кадровом цикле прячет мёртвый механизм](feedback_broad_except_in_frame_loop_hides_dead_mechanism.md) — лента едет, объектов нет, тесты зелёные
- [Bash heredoc схлопывает `\\`](feedback_bash_tool_unbalanced_quote_breaks_command.md) — такие файлы через Write · [ctypes setattr по чужому имени молчит](feedback_ctypes_setattr_unknown_field_is_silent.md) — проверять _fields_
- [protect-branch блокирует коммиты субагентов в worktree](feedback_protect_branch_blocks_worktree_subagents.md) — стейдж + файл сообщения, коммитит лид
- [pydantic assignment keeps the rejected value](feedback_model_copy_does_not_validate.md) — model_validator(after) raise doesn't roll back; snapshot+restore, not full revalidation
- [Всегда последние модели](feedback_always_latest_models.md) — сейчас Opus 5.5 / Sonnet 5.5; алиасы ярусов вместо версий; при выходе новой модели обновить список линтера
- [Явная модель на роль агента](feedback_explicit_model_per_agent_role.md) — `model` в каждом вызове Agent: reviewer/teamlead opus, developer/tester sonnet, cto (суперревьювер) fable
