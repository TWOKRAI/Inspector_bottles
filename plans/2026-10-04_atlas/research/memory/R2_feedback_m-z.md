# R2 — feedback_[m-z]*.md (138 файлов) — классификация

Источник: `merged/`. Индекс qex не использовался (только чтение файлов и `git grep`). Сокращения: имена файлов даны без префикса `feedback_` и без `.md`.
Сверки по репо (2026-10-04): `pre-commit-session-log` в `.claude/settings.json` и `.pre-commit-config.yaml` — 0 хитов (хук снят, `.claude/CLAUDE.md` это подтверждает); `codegraph` — нет в `.mcp.json`, `enabled.yaml` и в списке MCP из `.claude/CLAUDE.md`; deny-правила на `taskkill` в `.claude/settings.json` нет; `QT_QPA_PLATFORM` выставлен только в части тестовых файлов, централизованного `conftest.py` на корне нет.

## 1. Таблица (часть 1: файлы 1–72)

| file | kind | action | target | tags | hook | reason |
|---|---|---|---|---|---|---|
| materialized_agents_drift_from_plugin_source | REDUNDANT | ARCHIVE | `.claude/CLAUDE.md` «Standing rules» (абзац History) | mech: materialized-mirror | зеркало агентов правили без источника — sync снёс бы | тот же факт и правило уже в `.claude/CLAUDE.md` |
| materialized_default_hides_absence | LESSON | KEEP | — | mod: config_module; mech: schema-defaults | машинная раскладка материализует дефолты: «ключ не задан» не выразим | ErrorManager manager_name B3, вход→выход есть |
| mcp_tool_api_drift | STALE | ARCHIVE | — | mech: mcp-routing | ROUTING.md описывал tool, которого в пакете нет | пример про codegraph; codegraph не подключён; общий смысл — одна строка |
| measure_delta_not_file_size | LESSON | KEEP | — | mech: measurement | объём логов — дельта размеров, не размер файла | замер 9 МБ vs дельта, 2026-08-03 |
| merge_changes_the_form | LESSON | KEEP | — | mod: config_module/recipe; mech: config-forms | мерж машинной формы в человеческую переключает парсер | воспроизведённый дефект observability.persist |
| mirror_check_never_reads_the_original | LESSON | KEEP | — | mod: recipe/blueprint; mech: drift-guard | сверка двух рукописных копий не видит оригинал | `_pick`-ключи не покраснели в Ф7 G.4.b |
| modal_dialog_waits_instead_of_failing | LESSON | KEEP | — | mod: frontend_module; mech: qt-tests | тест с модальным диалогом ждёт клика, не падает | три виновных теста, владелец жал ОК |
| model_copy_does_not_validate | LESSON | KEEP (мягкий merge с pydantic_assignment_keeps_rejected_value) | см. группу G-pydantic | mod: data_schema_module; mech: pydantic-v2 | model_copy(update=) кладёт dict вместо схемы молча | два случая Ф2.2/2.3a, потребитель получает None |
| model_economy_scheme | STALE | ARCHIVE | survivor: model_split_impl_vs_review → в роли ростер в `.claude/CLAUDE.md` | mech: model-selection | схема моделей Opus 4.8/Fable на 2026-07-14 | модели устарели (Sonnet 5.5 сейчас); ростер ролей в `.claude/CLAUDE.md` |
| model_split_impl_vs_review | DUP | MERGE → explicit_model_per_agent_role (чужая доля, a-l) | `.claude/CLAUDE.md` «Roles → models» | mech: model-selection | исполнители Sonnet по умолчанию, Opus — верхний край | ростер моделей по ролям уже в `.claude/CLAUDE.md` |
| mp_queue_is_async_in_tests | LESSON | KEEP | — | mod: shared_resources_module/queues; mech: flaky-tests | mp.Queue после get/put ведёт себя недетерминированно: брать queue.Queue | 164/178 вместо 200 на том же коде |
| mvp_pattern | RULE | MOVE | `.rules/` (path-scoped для `frontend_module`/`multiprocess_prototype/frontend`) | mod: frontend_module | новая GUI-вкладка — полный MVP | решение стиля; должно срабатывать при правке frontend |
| named_main_cause_may_be_a_minor_share | LESSON | KEEP | — | mech: measurement | «главный источник» мерить долей до правки: 3–8 %, не 92 % | таблица замера logs_live, гейт недостижим |
| named_mechanism_is_not_a_commitment | LESSON | KEEP (группа G-plan) | — | mech: spec-review | «процессор X» в заголовке не обязывает делать X процессором | 3 из 6 задач Ф4 закрылись другим механизмом |
| negative_criterion_needs_an_existence_anchor | LESSON | KEEP | — | mech: tester-brief | критерий-отсутствие выдавать парой «есть литерал / нет» | тестер переводит «листа нет» в вакуумный assert |
| no_global_taskkill | RULE | MOVE | `.claude/settings.json` deny: `Bash(taskkill /F /IM*)`, `Bash(pkill*)`, `Bash(killall*)` | mech: process-kill | не убивать процессы по имени образа | правило должно срабатывать до того, как о нём вспомнят; deny-правила нет |
| no_qt_popups_offscreen | RULE | MOVE | `.claude/settings.json` env `QT_QPA_PLATFORM=offscreen` для агентов ИЛИ корневой conftest | mod: frontend_module; mech: qt-tests | агентские прогоны тестов — только offscreen | централизованного выставления нет; окна вешали G.1-агента |
| no_regression_proved_by_identical_build | LESSON | KEEP | — | mech: acceptance-proof | «не деградировало» — идентичность сборки ключ-в-ключ | D8: шумные живые прогоны не различают регресс |
| no_shm_hacks | RULE | MOVE | `.rules/` для `Plugins/` (путь-scoped) + строка в CLAUDE.md правило 9 | mod: Plugins; mech: layering | плагин не читает SHM напрямую, только middleware | ADR-120 даёт слой импортов, но не запрет SHM |
| numba_without_boundscheck_turns_a_broken_invariant_into_ub | LESSON | KEEP | — | mod: Plugins (trace_skeleton); mech: break-injection | numba без boundscheck: сломанный инвариант — 104 зелёных, затем 0xC0000374 | 29 красных в Python vs 104 зелёных в numba |
| observability_knobs_switchable_at_any_boundary_zero_cost_off | RULE | MOVE | `docs/direction/` или DECISIONS модуля observability + строка в `project-rules` | mod: observability; mech: knobs | каждый параметр наблюдаемости: вкл/выкл на любой границе, ноль нагрузки | стоячая планка владельца 2026-09-08; Task 4.15 ещё впереди |
| one_active_plan_per_tool | RULE | MOVE | `.claude/CLAUDE.md` «Plan-Driven Development» (одна строка) | mech: planning | на инструмент один активный план | семь файлов backend_ctl дали воскрешение отменённой задачи |
| one_control_proves_sufficiency_not_exclusivity | LESSON | KEEP | — | mech: controls | контроль доказывает «A достаточно», не «B не влияет» | layer-render 6.4: 6.78° vs сетка 2×2 20.4°/42.2° |
| one_door_two_roads_needs_two_guards | DUP | MERGE → property_unchecked_at_the_second_party | см. G-second-site | mod: config_module; mech: config.reload | у двери конфига две дороги: запрет и тест на каждой | тот же класс «проверено на одном call-site»; унести пример hub_stats |
| one_function_two_positions | LESSON | KEEP | — | mod: channel_routing_module (levels.py); mech: coinciding-constants | одна функция на две позиции держится на совпадении констант | `level_rank` Ф3.1; код `levels.py` это подтверждает |
| one_log_writer | RULE | MOVE | `channel_routing_module/DECISIONS.md` + `logger_module` ADR (проверить есть ли), в памяти одна строка | mod: logger_module; mech: architecture | пишущий логгер-менеджер один, остальное — вид | решение владельца 2026-07-27; в DECISIONS уже ссылаются на правило |
| one_owner_blinds_the_shared_state_test | LESSON | KEEP | — | mech: test-resolution | единый владелец делает тест общего состояния слепым | рефактор «под одного владельца» обнуляет разрешающую способность |
| package_install_by_user | REDUNDANT | ARCHIVE | `.claude/settings.json` deny `Bash(python -m pip install*)` | mech: deps | pip/uv install запускает пользователь | deny-правило уже в settings |
| parallel_agents_commit_race | STALE | MERGE → precommit_stash_collision_2plus_agents | G-precommit | mech: parallel-commits | 5 агентов без worktree склеили коммиты | хук `pre-commit-session-log` снят; правило «один worktree на писателя» в `.claude/CLAUDE.md` |
| parametrization_built_from_the_subject_collapses_with_it | DUP | MERGE → injection_zero_may_mean_the_guards_were_not_collected (a-l) | G-injection | mech: break-injection | параметризация из реестра исчезает вместе с испытуемым | 59→47 случаев, пороги ≥25/≥8 пройдены |
| pipeline_reuse_plugins_widgets | RULE | MOVE | `.rules/` (путь `frontend/.../pipeline/`) | mod: frontend_module (pipeline); mech: DRY | pipeline переиспользует виджеты вкладки Plugins | директива владельца 2026-05-30; нужна при правке pipeline |
| plan_checkboxes | RULE | MOVE | команда `/dev:implement` / `/dev:ship` (шаг «отметить [x] + hash») | mech: plan-driven | отмечать [x] и hash после каждой задачи | процесс; `/dev:ship` уже сверяет Refs |
| plan_dual_save | REDUNDANT | ARCHIVE | `.claude/commands/dev/plan.md`, CLAUDE.md «Plan-Driven Development» | mech: plan-driven | план сохранять в plans/ рядом с внутренним | то же самое сказано в команде `/dev:plan` и CLAUDE.md |
| plan_spec_can_lie | DUP | MERGE → the_plans_stated_cause_is_a_hypothesis | G-plan | mech: spec-review | имя поля в спеке плана может врать — сверять с кодом | `manual_restarts` → `instance_restarts`; уникум: пример |
| plausible_is_not_verified | LESSON | KEEP (ужать до 3 KB) | — | mech: verification | вердикт без вход→выход — совет | четыре ошибки одного происхождения; правило «honesty» уже в `project-rules` |
| port_wire_is_not_a_process_route | LESSON | KEEP | — | mod: chain_module/recipe; mech: wiring | провод портов не создаёт маршрута между процессами | Ф8.7: `chain_targets` без `processor`, плагин не вызван |
| positional_call_hides_parameter_name_drift | LESSON | KEEP | — | mod: Plugins (SubPluginContext); mech: stubs | позиционный вызов не видит дрейфа имён параметров | `duration=` → TypeError у заглушки |
| post_publication_mark_breaks_collapsing | LESSON | KEEP | — | mod: observability (ObservabilityAudit); mech: dedup | отметка после публикации выключает схлопывание — на отказе | Ф8.5, воспроизведено ревьюером |
| precommit_rollback_drops_unstaged_edits | DUP | MERGE → precommit_stash_collision_2plus_agents | G-precommit | mech: pre-commit | откат pre-commit теряет незастейдженные правки | один писатель + ruff format: тот же механизм патч-стеша |
| precommit_stash_collision_2plus_agents | LESSON | KEEP (survivor) | — | mech: pre-commit, parallel-commits | два агента в одном дереве: pre-commit-стеш откатывает чужие правки | независимо воспроизведено двумя агентами 2026-07-20 |
| predict_injections_after_writing_tests | RULE | MOVE | `.claude/CLAUDE.md`, bullet «Break-injection is the proof» (+ одна фраза) | mech: break-injection | ожидаемый набор падений называть после ВСЕХ тестов | 3 из 7 инъекций разошлись; уточнение к правилу |
| priority_belongs_to_the_receiver | LESSON | KEEP | — | mod: telemetry/config layers; mech: replay-order | приоритет у приёмника: воспроизводить порядок записи | last-write-wins приёмник, 2026-08-16 |
| probe_liveness_is_not_render | LESSON | KEEP (мягкий merge → qt_mcp_smoke_verification) | G-qtmcp | mod: frontend_module; mech: qt-mcp | три маркера живости пробы не доказывают рендер | `Widgets: 0`, `skip_hidden` по умолчанию |
| process_counter_is_not_per_key | LESSON | KEEP | — | mod: observability; mech: measurement | счётчик процесса не вычитать как «мой» | 2000 записей, ожидали 1992 подавлено — фон |
| property_unchecked_at_the_second_party | LESSON | KEEP (survivor G-second-site) | — | mech: break-injection, call-sites | свойство проверено у правленого и на одном call-site — не у соседа | дважды в 3.4 telemetry-stage6, ноль погибших |
| protect_branch_blocks_worktree_subagents | DUP | MERGE → git_main_merge_hook_traps (a-l/g) | G-gitmain | mech: protect-branch hook | субагент в worktree не может commit: хук видит main | 5 из 5 писателей заблокированы; унести совет «stage + файл сообщения, лид коммитит» |
| protect_the_unit_of_contention | LESSON | KEEP | — | mod: logger_module (FileChannel); mech: backpressure | предел ставить на единицу конкуренции — сток, не канал | Ф7.2: лок канала, делят хэндлер |
| prototype_the_guard_before_fixing_its_wording | LESSON | KEEP | — | mech: spec-review, guards | формулировка стража красна по построению: прототип 40 строк до старта | 1.3c: 3 функции/4 адреса красных |
| prove_test_red_without_fix | REDUNDANT | ARCHIVE | `.claude/CLAUDE.md` «Break-injection is the proof» | mech: break-injection | тест не доказан без красного без правки | дословно то же правило в `.claude/CLAUDE.md` |
| pydantic_assignment_keeps_rejected_value | LESSON | KEEP (мягкий merge с model_copy_does_not_validate) | G-pydantic | mod: data_schema_module, config_module; mech: pydantic-v2 | validate_assignment: отказ, но значение осталось | `max_export_batch_size=20480` остался после ValidationError |
| pytest_import_order_hides_a_cycle | LESSON | KEEP | — | mech: import-cycles | зелёный pytest не доказывает отсутствие цикла: чистый процесс | layer-render 2.4a: 14 красных точечно, цикл виден только в `import X` |
| pytest_owns_threading_excepthook_for_the_session | LESSON | KEEP | — | mech: pytest-internals | под pytest threading.excepthook — коллектор pytest, stderr пуст | pytest 9.x `threadexception.py`; якорь приёмки недостижим |
| qex_full_rebuild_runbook | REFERENCE | KEEP, local-only; выделить в `/mcp-qex:qex-rebuild` | `.claude/plugins/mcp-qex/` команда | mod: qex; mech: runbook | полный реиндекс qex на Windows без провалов | пошаговый порядок, первый прогон убит на 94 % |
| qex_query_english_code_bias | REDUNDANT | ARCHIVE | корневой `CLAUDE.md` раздел «MCP: qex» | mech: qex | запросы qex по-английски лексикой кода | дословно в корневом `CLAUDE.md` |
| qex_reindex_budget | STALE | MERGE → qex_full_rebuild_runbook | G-qex | mech: qex, VRAM | таймауты реиндекса — выгрузка эмбеддера из VRAM; keep_alive=-1 | написано под 4b, теперь 0.6b; унести только keep_alive и число 47 с |
| qt_mcp_always_probe | DUP | MERGE → qt_mcp_flag_value_is_compared_verbatim | G-qtmcp | mod: frontend_module; mech: qt-mcp | smoke-запуск всегда с QT_MCP_PROBE=1 | та же ручка; унести строку запуска `run.py` |
| qt_mcp_flag_value_is_compared_verbatim | LESSON | KEEP (survivor G-qtmcp) | — | mech: qt-mcp, env-flags | QT_MCP_PROBE сверяется с «1» дословно; «1:9142» молчит | рендер GUI не проверялся три раунда |
| qt_mcp_smoke_verification | RULE | MOVE | `.rules/` путь `frontend/` + шаг в `/dev:implement` чек-листе | mod: frontend_module; mech: smoke | после Qt-задачи — запуск и qt_snapshot | pytest-qt с mock ctx не доказывает реальную сборку |
| read_the_key_from_the_section_already_travelling | DUP | MERGE → recipe_knob_must_be_named_in_from_recipe | G-recipe-key | mod: recipe/blueprint; mech: config-delivery | новый ключ класть в секцию, которая уже едет | два BlueprintAssembler: boot и switch |
| read_timestamp_is_not_data_freshness | LESSON | KEEP | — | mod: telemetry; mech: freshness | штамп чтения не говорит о свежести данных | замерший датчик + свежий `snapshot_ts`, Task 3.2 |
| ready_signal_meant_less_than_read | LESSON | KEEP | — | mod: process_module; mech: readiness | `ready_event` = initialize(), читали как «принимает команды» | команда в окне читается и выбрасывается |
| recipe_knob_must_be_named_in_from_recipe | LESSON | KEEP (survivor G-recipe-key) | — | mod: recipe, process_module; mech: config-delivery | ключ в `metadata:` до процесса не доезжает | `_pick` + `extra=ignore` |
| red_tests_manufacture_the_appearance_of_new_diagnostics | LESSON | KEEP | — | mech: measurement, pytest | pytest печатает stderr только у упавших: «0 → 12» — артефакт | closure Task 3.2, `idle_sinks` |
| refusal_after_the_write_poisons_the_neighbour | LESSON | KEEP | — | mod: telemetry/config layers; mech: layer-L3 | отказ после записи в общий слой ломает соседнюю плоскость | ключ живёт 300 с, следующий reload падает |
| register_routing_hang | LESSON | KEEP (проверить актуальность) | — | mod: frontend_module/registers; mech: FieldRouting | FieldRouting без канала — фриз GUI на set_field_value | проверить, нет ли fail-fast в FrontendRegistersBridge |
| removal_leaves_a_tail_in_the_neighbour | LESSON | KEEP | — | mod: logger_module; mech: deletion-refactor | снос секции оставляет хвост в теле соседа | Ф2.6: каждый CRITICAL чистил карты решений |
| removing_waste_reddens_tests_that_measured_it | LESSON | KEEP | — | mech: test-resolution | убрал лишнюю работу — красные тесты, мерившие её | 20 конвертов → 1; один тест зелёный на несуществующем свойстве |
| review_economy_tiers | STALE | ARCHIVE | `.claude/CLAUDE.md` «Task launch convention» (ревью после каждой задачи) | mech: review | три уровня ревью: полное 8-угловое только на рисковые | частично вытеснено решением 2026-08-13 и `reviewer.md` |
| review_finds_the_seam_between_own_pieces | DUP | MERGE → three_lenses_three_defect_classes | G-lenses | mech: review | ревью ловит стык двух правильных кусков одной задачи | то же утверждение «ревью — связки»; унести пример 5.11 d+f |
| row_count_never_catches_the_loop | LESSON | KEEP | — | mod: telemetry; mech: feedback-loop | счёт строк не ловит петлю подачи — судить по сериям | строки 1,2,3,4,5 — рост без геометрии, ADR утверждал обратное |
| ru_output_encoding_and_wc | REFERENCE | KEEP, local-only (Windows) | — | mech: encoding | русский вывод в cp866/cp1251 = «инструмент молчал» | подтвердилось в этом аудите: UnicodeEncodeError cp1251 |
| ruff_strips_unused_import | LESSON | KEEP | — | mech: PostToolUse formatter hook | импорт и использование — одним Edit | PostToolUse ruff --fix удаляет «неиспользуемый» импорт |

## 1. Таблица (часть 2: файлы 73–138)

| file | kind | action | target | tags | hook | reason |
|---|---|---|---|---|---|---|
| runtime_config_dies_with_the_process | LESSON | KEEP | — | mod: config_module (config.reload); mech: measurement | рестарт сбрасывает config.reload: замер до/после меряет одно | 1972 Б при count=392 в обеих строках |
| safeguard_can_be_a_noop_with_green_units | LESSON | KEEP | — | mod: backend_ctl (harness.strip_gui); mech: synthetic-input | предохранитель на синтетике может быть no-op на реальной конфигурации | D8: пять зелёных юнитов, strip_gui ничего не резал |
| scripted_patch_needs_a_unique_anchor | LESSON | KEEP | — | mech: break-injection tooling | скриптовая замена: assert count == 1, не >= 1 | якорь дважды, заплата ушла в соседнюю фикстуру |
| seam_must_fire_on_full_release | DUP | MERGE → test_survived_its_own_break | G-seam | mech: break-injection, RLock | шов на RLock считает глубину, иначе тест зелен всегда | тот же класс «тест пережил слом»; унести признак 5.43 с vs 0.36 с |
| second_consumer_reveals_the_defect | LESSON | KEEP | — | mod: logger_module; mech: singleton lifecycle | дефект общего механизма виден только с третьим потребителем | `LoggerManager._instance` пережил shutdown, Ф6.8 |
| sentrux_depth_opaque | REFERENCE | KEEP | — | mod: sentrux | depth-метрика sentrux не равна каталогам и цепочке импортов | замер 2026-07-10: depth=6 при удалении 7-уровневого пакета |
| sentrux_gate_narrowed | REDUNDANT | ARCHIVE | `scripts/hooks/pre-push` (git-tracked), `.claude/plugins/mcp-sentrux/README.md` | mod: sentrux | pre-push блокирует только рост циклов и god-файлов | хук в git — источник истины; файл на него сам ссылается |
| shared_tree_makes_injections_look_like_flakes | DUP | MERGE → a_peer_session_shares_the_tree (a-l) | G-sharedtree | mech: shared-tree, break-injection | инъекции и чужие прогоны в одном дереве дают ложные факты | `restore` затёр правку агента; унести оба ложных факта |
| side_effect_must_not_undo_the_transaction | LESSON | KEEP | — | mod: recipe/orchestrator (switch); mech: transactions | побочный эффект success-пути — в свой try | 5.11: чтение адреса рецепта откатывало успешный switch |
| signal_placed_in_a_branch_goes_blind | LESSON | KEEP | — | mod: logger_module; mech: detector-placement | сигнал в одной ветке слепнет, когда решение берёт соседняя | Ф2.4: `_scope_schema` не вызывается при правиле имени |
| silent_detector_proves_nothing | DUP | MERGE → zero_observations_looks_like_a_result | G-zero-detector | mech: detectors | ноль детектора ничего не значит, пока он не показан стреляющим | 5.11-R4: `No handler for key` дал ложный ноль дважды; унести оба случая |
| single_marker_verdict_lies | LESSON | KEEP | — | mod: backend_ctl (process_restart_verified); mech: verdicts | вердикт по одному маркеру врёт в обе стороны | pid сменился, но процесс умер; pid переиспользован ОС |
| single_reader_test_misses_multi_reader_defect | LESSON | KEEP | — | mod: observability readback; mech: shared-baseline | тест одного читателя не видит общей базы отсчёта | 15 тестов и зонд 7/7 зелёные, два читателя портят друг друга |
| spawn_child_inherits_parent_sys_path | LESSON | KEEP | — | mod: process_module (SystemLauncher/BackendHarness); mech: spawn | spawn копирует sys.path родителя, PYTHONPATH в тесте не доезжает | измерено line-sim Task 1.1, 2026-09-20 |
| spec_review_needs_independent_agent | REDUNDANT | ARCHIVE | `.claude/CLAUDE.md` «Task launch convention», стадия 0 | mech: spec-review | автор ловит ошибки карты, не формы задачи | правило стадии 0 уже закреплено; пример 5.13 остаётся в плане |
| sqlite_pragma_fails_silently | LESSON | KEEP (survivor G-sqlite) | — | mod: Services/sql, observability store; mech: sqlite | PRAGMA молча не срабатывает: порядок и недошагнутый оператор | Ф5.2: auto_vacuum читается как 0 после WAL |
| stepwise_statement_needs_draining | DUP | MERGE → sqlite_pragma_fails_silently | G-sqlite | mod: Services/sql; mech: sqlite | incremental_vacuum делает один шаг: курсор вычерпывать | таблица форм вызова 2116 → 2115; унести её |
| subagent_live_test_monitor_hang | DUP | MERGE → background_reviewer_loses_the_verdict (a-l) | G-bg | mech: subagent-sync | субагент уводит live-тест в Monitor и виснет | тот же класс «фон теряет вердикт»; унести «лид забирает на 2-й заминке» |
| substring_assert_passes_on_the_wrong_branch | LESSON | KEEP | — | mod: observability; mech: test-assert | ассерт по общей подстроке зеленеет на чужой ветке | `documents` есть в тексте обеих веток, Task 4.2 |
| suffix_rename_is_a_blind_injection | LESSON | KEEP | — | mech: break-injection tooling | foo → foo_RENAMED: старое имя — префикс, сторожа молчат | S-29, `_get_protected_names`; подстрочные проверки не краснеют |
| swallowed_failure_class | LESSON | KEEP | — | mod: process_module/middleware; mech: swallowed-exceptions | искать except/pass и debug на отказе: следствие видно, причина нет | четыре экземпляра за один день 2026-07-21 |
| switching_off_a_writer_promotes_its_placeholder_to_a_claim | LESSON | KEEP | — | mod: telemetry; mech: placeholders | выключив писателя, заглушка становится утверждением | РТ-2, `logs_live/rt2_blocker1` |
| symmetric_names_with_different_periods | LESSON | KEEP | — | mod: telemetry (get_stats); mech: naming | одноимённые величины с разными периодами читаются неверно молча | `window_series_dropped` 4 → flush → 0 |
| tab_order | RULE | MOVE | `.rules/gui.md` | mod: frontend_module | вкладки: Settings → Recipes → функциональные | порядок проверяем по коду TabFactory; правило path-scoped |
| test_authorship_three_roles | REDUNDANT | ARCHIVE | `.claude/CLAUDE.md` «Test authorship» | mech: test-authorship | три роли авторства тестов | таблица дословно в `.claude/CLAUDE.md` |
| test_params_hide_defect_window | LESSON | KEEP (survivor G-testvalues) | — | mech: test-params | параметр теста закрывает окно дефекта: backoff_sec=0.0 | два HIGH ревью 2026-07-10 под зелёными тестами |
| test_raising_the_error_itself_guards_the_branch | LESSON | KEEP | — | mod: code_version; mech: test-mechanism | тест, сам поднимающий исключение, сторожит except, не механизм | `code_version()` timeout=5, найдено Fable |
| test_reddens_only_under_a_paired_injection | LESSON | KEEP (survivor G-pair) | — | mech: break-injection | переживший одиночную инъекцию тест может сторожить композицию | как отличить — сломать пару |
| test_setting_one_handle_of_a_pair_measures_priority | DUP | MERGE → test_params_hide_defect_window | G-testvalues | mod: config_module; mech: legacy-alias | тест одной ручки пары мерит приоритет чтения | D4: MULTIPROCESS_LOG_DIR и алиас; унести пример |
| test_survived_its_own_break | LESSON | KEEP (survivor G-seam) | — | mech: break-injection, concurrency | тест, переживший слом, не существует: два способа шва не туда | Task 5.8: окно гонки два байткода, переключение раз в 5 мс |
| test_values_near_defaults_test_the_default | DUP | MERGE → test_params_hide_defect_window | G-testvalues | mod: logger_module; mech: test-params | числа теста у дефолта проверяют дефолт | 0.25 ≥ 0.25; после разведения 2/2 |
| tester_always_and_inject_against_it | REDUNDANT | ARCHIVE | `.claude/CLAUDE.md` «Independent tester — on every task» | mech: test-authorship | тестера звать на каждой задаче, инъекции и против его файла | решение 2026-08-13 переписано в `.claude/CLAUDE.md` дословно |
| tester_blindness_needs_a_worktree | REDUNDANT | ARCHIVE | `.claude/CLAUDE.md` «Blindness is enforced by the worktree» | mech: tester | слепоту тестера даёт worktree, не проза | тот же абзац и те же две утечки в `.claude/CLAUDE.md` |
| tester_once_per_mechanism_before_the_code | REDUNDANT | ARCHIVE | `.claude/CLAUDE.md` «Stage 1 refined 2026-08-20» | mech: tester | тестер один раз на механизм и до кода | число 479k/16 мин уже в `.claude/CLAUDE.md` |
| tests_invisible_to_testpaths | DUP | MERGE → zone_guard_never_closes_the_class | G-testpaths | mod: framework tests (pytest.ini); mech: testpaths | три каталога tests/ с 58 тестами не в testpaths | первый случай серии; унести 5361 passed и имена каталогов |
| the_off_half_of_a_pair_can_be_done_by_a_timer | LESSON | KEEP | — | mod: backend_ctl, config L3 TTL; mech: ON/OFF-proof | вторую половину ON/OFF мог сделать таймер | success=true подтверждает доставку, не эффект |
| the_plans_stated_cause_is_a_hypothesis | LESSON | KEEP (survivor G-plan) | — | mod: process_manager; mech: spec-review | план называет причину — она может быть неверной | closure 1.2: две дороги вместо «пишет раньше регистрации» |
| the_sentence_is_wider_than_the_command_it_quotes | LESSON | KEEP | — | mech: report-honesty | проза шире команды: «framework не тронут» по *.py | `61bb7496` +34 строки CONNECTORS.md, otel Ф0 |
| think_en_speak_ru | REDUNDANT | ARCHIVE | `.claude/CLAUDE.md` «Language policy» | mech: language | думать по-английски, говорить по-русски | политика языка уже в `.claude/CLAUDE.md` (internal reasoning any language) |
| thread_target_pins_its_owner | LESSON | KEEP | — | mod: state_store_module, app_module; mech: thread-GC | bound-method в target делает забытый стенд бессмертным | 23 теста, access violation гейта ушёл 5/5 |
| three_lenses_three_defect_classes | LESSON | KEEP (survivor G-lenses) | — | mech: test/live/review | тесты ловят механику, прогон — проводку, ревью — связки | 5.12: 6368 зелёных пропустили обе живые находки |
| three_managers_share_base | DUP | MERGE → logger_error_stats_managers (a-l) | G-managers | mod: channel_routing_module, base_manager; mech: inheritance | logger/error/stats — одна база ChannelRoutingManager | то же решение владельца; унести факт иерархии 2026-07-26 |
| tool_features_before_validation | LESSON | KEEP | — | mod: backend_ctl; mech: scope-discipline | отладочный инструмент доказывать задачей до наращивания фич | ultra-ревью 4.5/10, 844 строки тестов потеряны |
| transitive_gui_backend_in_tests | LESSON | KEEP (низкая ценность) | — | mech: qt-in-tests | matplotlib с PySide6 резолвит qtagg — мина, в деле AV не причина | сам файл говорит, что мина не взорвалась |
| transport_arbitrates_what_it_cannot_understand | LESSON | KEEP | — | mod: telemetry (ThrottleMiddleware); mech: single-owner leaf | два писателя в один лист: троттл вырезает молча | воспроизведено вход→выход, proceed=true без rejection_reason |
| two_green_gates_can_hide_a_red_pair | LESSON | KEEP | — | mod: framework tests (declarations); mech: testpaths | нарушитель и жертва в разных testpaths: оба гейта зелёные | `forget_declarations("metric", {"fps"})` ломает каталог |
| two_patches_one_red_set_means_one_assert | LESSON | KEEP | — | mech: break-injection | две заплаты — один набор красных: один ассерт на два свойства | матрица Task 3.0a, S3 и S4 |
| two_safeguards_hide_which_one_holds | DUP | MERGE → test_reddens_only_under_a_paired_injection | G-pair | mod: observability (frame trace); mech: break-injection | два предохранителя: тест сторожит совпадение | Ф7.5: 0 красных вместо 1; унести пример sampling_max_level |
| two_tests_enter_from_both_sides_and_miss_the_connector | LESSON | KEEP | — | mod: observation_port; mech: connector-test | приёмка и авторский тест входят с двух сторон, разъём ничей | Ф3/3.2: записи порта не доехали до стора |
| unblocking_signal_at_the_moment_of_fact | LESSON | KEEP | — | mod: process_manager (stop_many); mech: lifecycle | сигнал, отпускающий соседей, ставить в момент факта | 13 тестов зелёные, живой SIGKILL gui = 5.7 с как до правки |
| unconnected_driver_reads_as_a_clean_zero | LESSON | KEEP | — | mod: backend_ctl driver; mech: measurement | неподключённый драйвер плюс .get(default) даёт ровный ноль | delta=0 в приёмке 3.3 неотличима от «трафика нет» |
| unkillable_fix_needs_a_hand_set_state | LESSON | KEEP | — | mod: observation_port; mech: white-box pin | правку, недостижимую после соседних, пинить белым ящиком | Ф0 Task 0.2, правка 3 |
| unparsed_is_not_absent | LESSON | KEEP | — | mod: scripts/sync, validate.py; mech: silent-parser | парсер, молча пропускающий строку, делает «не разобрал» = «нет» | `## ADR-DS-009 (S-27)` не сматчился, validate зелёный |
| unused_paths_are_contracts | RULE | MOVE | agent `reviewer` (чек-лист) + `project-rules` | mech: review | публичный путь без вызывающих — контракт: чинить или отклонять громко | решение владельца 2026-07-13; должно срабатывать в ревью |
| upper_layer_default_disables_the_guard_below | LESSON | KEEP | — | mod: logger_module (log_paths); mech: defaults-materialization | дефолт верхнего слоя отменяет защиту нижнего | три точки подставляют `Path("logs")` вместо temp |
| use_graph_semantic_tools | REDUNDANT | ARCHIVE | корневой `CLAUDE.md` «qex-first / sentrux-first» | mech: mcp-routing | владелец ждёт активного qex/graphify/serena | правило уже в корневом `CLAUDE.md`; codegraph не подключён |
| uv_sync_prunes_venv | RULE | MOVE | `.claude/settings.json` `ask` для `Bash(uv sync*)` + текст про `--inexact` | mech: env, local-only | uv sync только с --inexact | 27 пакетов снесено (torch+cu124 и др.), час восстановления |
| walk_skips_worktrees | LESSON | KEEP | — | mech: worktrees, bulk-replace | массовая замена по проекту исключает `.claude/worktrees/` | os.walk залез в полные чекауты чужих агентов |
| wallclock_threshold_measures_the_heap | LESSON | KEEP | — | mod: state_store_module; mech: flaky-tests | порог по стенным часам меряет кучу чужих тестов | 113.2 и 158.5 мс против 100 в общем гейте |
| widget_qt_patterns | LESSON | KEEP (+ копия в `.rules/gui.md`) | `.rules/gui.md` | mod: frontend_module; mech: QTreeWidget | setFlags вызывает itemChanged: blockSignals вокруг | рекурсия, exitcode 0xC000001D на Windows |
| worktree_for_parallel_samefile | DUP | MERGE → a_peer_session_shares_the_tree (a-l) | G-sharedtree | mech: worktrees | параллельная правка одного файла — worktree от committed HEAD | `git checkout -b` утащил бы чужую работу; унести пример driver.py |
| worktree_stale_base | LESSON | KEEP | — | mech: worktrees | worktree агента может быть на 76 коммитов позади main | волна 2026-07-11: два из трёх на `a50d1f74` |
| zero_mentions_criterion_erases_the_reason | LESSON | KEEP | — | mech: acceptance-criteria | критерий «упоминаний = 0» стирает причину решения | ADR о снятом механизме обязан называть его |
| zero_observations_looks_like_a_result | LESSON | KEEP (survivor G-zero-detector) | — | mech: detectors, measurement | ноль наблюдений неотличим от результата: требовать ненулевой знаменатель | трижды за день 2026-08-23, включая два мёртвых агента |
| zero_reds_can_mean_a_useless_layer | DUP | MERGE → a_zero_under_injection_has_three_readings (a-l) | G-zero-injection | mech: break-injection | ноль красных: код может быть лишним слоем | Ф2.7: сравнение уже в Pydantic `__eq__`; добавить как четвёртое чтение |
| zone_guard_never_closes_the_class | LESSON | KEEP (survivor G-testpaths) | — | mod: framework tests; mech: testpaths | страж своей зоны не закрывает класс «тесты-невидимки» | 4.0: 114 файлов, 1464 теста, четыре красных |

## 2. Группы слияния (survivor ← файлы; что уникального переносит каждый)

Имена без префикса `feedback_`. Метка `(a-l)` — файл из чужой доли, смотрел только начало; решение там принимает владелец той доли.

- **G-precommit.** `precommit_stash_collision_2plus_agents` ← `precommit_rollback_drops_unstaged_edits` (вариант с одним писателем: ruff format + незастейдженный хвост; правило «дерево без хвостов перед коммитом»), `parallel_agents_commit_race` (случай 5 агентов 2026-05-24; хук `pre-commit-session-log` снят — оставить одну строку как историю). Соседи из доли a-l: `a_hook_that_writes_a_shared_file_deadlocks_two_writers`, `commit_takes_the_whole_index`.
- **G-sharedtree.** `a_peer_session_shares_the_tree` (a-l) ← `shared_tree_makes_injections_look_like_flakes` (инъекция `restore` затёрла правку агента — два ложных факта; вывод «инъекции только в своём worktree»), `worktree_for_parallel_samefile` (не делать `git checkout -b` поверх чужих незакоммиченных правок; пример `backend_ctl/driver.py`). Отдельно остаётся `worktree_stale_base` (числа 76 коммитов).
- **G-testvalues.** `test_params_hide_defect_window` ← `test_values_near_defaults_test_the_default` (0.25 ≥ 0.25 → разнести числа 0.60/0.45), `test_setting_one_handle_of_a_pair_measures_priority` (чистить соседнюю форму ручки: MULTIPROCESS_LOG_DIR/INSPECTOR_LOG_DIR).
- **G-pair.** `test_reddens_only_under_a_paired_injection` ← `two_safeguards_hide_which_one_holds` (0 красных вместо 1; пример `sampling_max_level: DEBUG`; «снимай второй предохранитель в стенде»).
- **G-seam.** `test_survived_its_own_break` ← `seam_must_fire_on_full_release` (шов на RLock считает глубину; сигнатура: файл 5.43 с вместо 0.36 с = `join(timeout=5)`).
- **G-zero-detector.** `zero_observations_looks_like_a_result` ← `silent_detector_proves_nothing` (5.11-R4: детектор смотрел не в тот лог, ложный ноль дважды подряд; «покажи детектор стреляющим»). Рядом, но не сливать: `unconnected_driver_reads_as_a_clean_zero` (конкретная ловушка backend_ctl).
- **G-zero-injection.** `a_zero_under_injection_has_three_readings` (a-l) ← `zero_reds_can_mean_a_useless_layer` (четвёртое чтение: код лишний, Pydantic `__eq__`; исход — удалить слой).
- **G-injection.** `injection_zero_may_mean_the_guards_were_not_collected` (a-l) ← `parametrization_built_from_the_subject_collapses_with_it` (59→47 случаев; пороги ≥25/≥8 пройдены).
- **G-lenses.** `three_lenses_three_defect_classes` ← `review_finds_the_seam_between_own_pieces` (пример 5.11 d+f: каждый кусок верен, стык нет).
- **G-plan.** `the_plans_stated_cause_is_a_hypothesis` ← `plan_spec_can_lie` (`manual_restarts` → `instance_restarts`, ревью Fable). Мягкая связь, не слияние: `a_plans_premise_expires` (a-l) — обоснование отсрочки живёт как факт; `named_mechanism_is_not_a_commitment`.
- **G-testpaths.** `zone_guard_never_closes_the_class` ← `tests_invisible_to_testpaths` (первый случай: три каталога, 58 тестов, 5361 passed; `modules/pytest.ini`). Рядом, не сливать: `two_green_gates_can_hide_a_red_pair`.
- **G-second-site.** `property_unchecked_at_the_second_party` ← `one_door_two_roads_needs_two_guards` (`channels.hub_stats.enabled`: `_setup_channels` против пересборки после `config.reload`).
- **G-recipe-key.** `recipe_knob_must_be_named_in_from_recipe` ← `read_the_key_from_the_section_already_travelling` (два `BlueprintAssembler`: boot `launch.py` и switch `orchestrator_hooks.py`; ключ внутри уже едущей секции).
- **G-sqlite.** `sqlite_pragma_fails_silently` ← `stepwise_statement_needs_draining` (таблица форм вызова `incremental_vacuum`: 2116 → 2115 страниц).
- **G-qtmcp.** `qt_mcp_flag_value_is_compared_verbatim` ← `qt_mcp_always_probe` (строка запуска `QT_MCP_PROBE=1 python multiprocess_prototype/run.py <recipe>`). Необязательно: `probe_liveness_is_not_render` → `qt_mcp_smoke_verification`.
- **G-qex.** `qex_full_rebuild_runbook` ← `qex_reindex_budget` (только `keep_alive=-1` и 47 с против 1.9 с; модель 4b снята). `qex_query_english_code_bias` — ARCHIVE (дословно в корневом `CLAUDE.md`).
- **G-gitmain.** `git_main_merge_hook_traps` (a-l) ← `protect_branch_blocks_worktree_subagents` (5 из 5 писателей заблокированы; «субагент делает stage и пишет файл сообщения, лид коммитит»).
- **G-managers.** `logger_error_stats_managers` (a-l) ← `three_managers_share_base` (факт иерархии `ChannelRoutingManager` ← `BaseManager`+`ObservableMixin`, тонкая база).
- **G-bg.** `background_reviewer_loses_the_verdict` (a-l) ← `subagent_live_test_monitor_hang` (developer уводит live-тест в Monitor и виснет; лид забирает проверку на 2-й заминке).
- **G-model.** `explicit_model_per_agent_role` (a-l) ← `model_split_impl_vs_review`, `model_economy_scheme` (унести одну строку: главный чат без `[1m]` и fast mode; Fable только на вердикты). Остальное уже в `.claude/CLAUDE.md` «Roles → models». `review_economy_tiers` — ARCHIVE отдельно (частично вытеснено).
- **G-pydantic (необязательно).** Один файл «pydantic v2 не стережёт изменение»: `model_copy_does_not_validate` + `pydantic_assignment_keeps_rejected_value`.

## 3. RULE-файлы: механизм и точная строка

| file | механизм | строка правила |
|---|---|---|
| no_global_taskkill | `.claude/settings.json` → `permissions.deny` | `Bash(taskkill /F /IM*)`, `Bash(taskkill /IM*)`, `Bash(pkill*)`, `Bash(killall*)`; убивать только `TaskStop` или `taskkill /PID <n>` |
| no_qt_popups_offscreen | `.claude/settings.json` → `env` (и `conftest.py` корня, если нужен для ручного pytest) | `QT_QPA_PLATFORM=offscreen` для всех агентских прогонов тестов и харнесса |
| uv_sync_prunes_venv | `.claude/settings.json` → `permissions.ask` | `Bash(uv sync*)` — запрос подтверждения; в тексте: «`uv sync` только с `--inexact`: без него сносит всё, что поставлено через `uv pip install` (torch+cu124 и др.)» |
| mvp_pattern, tab_order, pipeline_reuse_plugins_widgets, qt_mcp_smoke_verification | `.rules/gui.md` (путь-scoped) | «Новая GUI-вкладка — полный MVP (presenter.py + view.py Protocol + widget.py). Порядок вкладок: Settings → Recipes → функциональные. Инспектор ноды pipeline переиспользует виджеты вкладки Plugins, поля резолвятся по `plugin_name`. После Qt-задачи — запуск прототипа с `QT_MCP_PROBE=1` и `qt_snapshot`.» |
| no_shm_hacks | `.rules/plugins.md` | «Плагин не читает SHM напрямую: только через RouterManager middleware и менеджеры; не хватает — допиливать framework.» |
| one_log_writer | `.rules/logging.md` | «Пишущий логгер-менеджер один; остальные — виды поверх него или доказанное исключение.» |
| observability_knobs_switchable_at_any_boundary_zero_cost_off | skill `project-rules` (раздел observability) + `docs/` модуля | «Каждый параметр наблюдаемости включается и выключается в рантайме на любой границе, читается по запросу и в выключенном виде не даёт нагрузки.» |
| one_active_plan_per_tool | корневой `CLAUDE.md` «Plan-Driven Development» | «На один инструмент или модуль — один активный план; новую задачу вносить в него фазой, а не отдельным файлом.» |
| plan_checkboxes | команда `/dev:implement` (шаг закрытия задачи) | «После задачи: `[ ]` → `[x]`, хэш коммита рядом, ✅ в заголовке фазы.» |
| predict_injections_after_writing_tests | `.claude/CLAUDE.md`, bullet «Break-injection is the proof» | «Name the expected failing set AFTER the last test is written; a prediction counted before a later test is added is wrong arithmetic.» |
| unused_paths_are_contracts | agent `reviewer` + `project-rules` | «A public API or envelope form with no live caller is a contract: fix it or reject it loudly in review, never dismiss it as a dead path.» |

## 4. Кандидаты в новый `MEMORY.md` (≤ 12 из моей доли)

Приоритет: первые шесть — если места мало. Остальное уходит в `CRAFT.md` по триггеру.

1. [Русский вывод и wc врут](feedback_ru_output_encoding_and_wc.md) — cp866/cp1251, PYTHONUTF8=1; сработало на этом аудите
2. [PostToolUse ruff сносит свежий импорт](feedback_ruff_strips_unused_import.md) — импорт и использование одним Edit
3. [Ноль наблюдений ≠ результат](feedback_zero_observations_looks_like_a_result.md) — сторож требует ненулевой знаменатель
4. [pre-commit стеш и 2+ агента](feedback_precommit_stash_collision_2plus_agents.md) — откат стирает чужие правки; один worktree на писателя
5. [Проверено на одном call-site — не проверено у соседа](feedback_property_unchecked_at_the_second_party.md) — ноль от инъекции воспроизводить руками
6. [Причина из плана — гипотеза](feedback_the_plans_stated_cause_is_a_hypothesis.md) — тянуть нить до замера
7. [Тест пережил свой слом — не существует](feedback_test_survived_its_own_break.md) — шов не там; гонки и RLock
8. [Параметр теста закрывает окно дефекта](feedback_test_params_hide_defect_window.md) — backoff=0.0, значения у дефолта
9. [Не разобрал ≠ данных нет](feedback_unparsed_is_not_absent.md) — молчащий парсер, зелёный validate
10. [Страж своей зоны не закрывает класс](feedback_zone_guard_never_closes_the_class.md) — тесты-невидимки, testpaths
11. [Не убивать процессы по имени образа](feedback_no_global_taskkill.md) — только пока нет deny-правила в settings
12. [uv sync сносит необъявленное](feedback_uv_sync_prunes_venv.md) — только `--inexact`; пока нет `ask`-правила

Пункты 11 и 12 уходят из индекса сразу, как только правила попадут в `settings.json`.

## 5. Счётчики

| kind | файлов |
|---|---|
| LESSON | 82 |
| DUP | 21 |
| RULE | 14 |
| REDUNDANT | 13 |
| STALE | 5 |
| REFERENCE | 3 |
| STATE | 0 |
| **всего** | **138** |

Действия: KEEP (survivor или одиночный) — 82 LESSON и 3 REFERENCE (local-only: `ru_output_encoding_and_wc`, `qex_full_rebuild_runbook`); MERGE — 21 DUP (плюс STALE-файлы `parallel_agents_commit_race`, `qex_reindex_budget` вливаются в survivor); MOVE в механизм (память оставляет одну строку-указатель) — 14 RULE; ARCHIVE — 13 REDUNDANT и 5 STALE.

Ссылки на мою долю в текущем `MEMORY.md` лежат в ~40 строках, около 13.0 KB (замер по именам файлов; часть строк общая с чужими долями, поэтому это верхняя граница). Если оставить 12 строк кандидатов (~2.4 KB), экономия индекса от моей доли — до ~10 KB; реально меньше, пока владельцы других долей решают общие строки. Самые дорогие строки на вынос: блок qex (881 Б, три файла), `zero_observations` (717 Б), `parallel_agents_commit_race` и pre-commit (560 Б), `unparsed_is_not_absent` (541 Б), `observability_knobs` (510 Б).

## 6. Что ненадёжно в моей классификации

- Каждый файл читал только по заголовку и первым ~380 символам тела (скрипт-дайджест). Полностью не читал ни одного. Файлы 5–7 KB (`plausible_is_not_verified` 7.2 KB, `parallel_agents_commit_race` 5.4 KB, `qex_reindex_budget` 5.4 KB) оценены по началу.
- Слияния с файлами из чужих долей (a-l: `a_peer_session_shares_the_tree`, `git_main_merge_hook_traps`, `background_reviewer_loses_the_verdict`, `a_zero_under_injection_has_three_readings`, `injection_zero_may_mean_the_guards_were_not_collected`, `logger_error_stats_managers`, `explicit_model_per_agent_role`) решены по 300–900 символам их начала; survivor там может оказаться слабее, чем кажется. `git_main_merge_hook_traps` и `explicit_model_per_agent_role` вообще не открывал целиком по телу.
- Пары с одной осью, но разным механизмом, слил осторожно: `one_door_two_roads` → `property_unchecked_at_the_second_party`, `zero_reds_can_mean_a_useless_layer` → `a_zero_under_injection_has_three_readings`, `three_managers_share_base` → `logger_error_stats_managers`. Каждую перечитать целиком перед слиянием.
- REDUNDANT-вердикты по `.claude/CLAUDE.md` (`test_authorship_three_roles`, `tester_*`, `spec_review_needs_independent_agent`, `think_en_speak_ru`) сверены с текстом этого файла по смыслу, не построчно. Проверить, нет ли в архивируемых файлах чисел, которых нет в `.claude/CLAUDE.md` (479k токенов там есть, остальное не сверял).
- `register_routing_hang` и `transitive_gui_backend_in_tests` не проверены на актуальность по коду (возможен fail-fast в `FrontendRegistersBridge`). Оставлены как LESSON.
- `parallel_agents_commit_race` помечен STALE по факту снятого хука (`git grep` 0 хитов в `.claude/settings.json` и `.pre-commit-config.yaml`; снятие подтверждает `.claude/CLAUDE.md`). Механизм гонки остаётся в survivor.
- Не проверял по репо существование планов, на которые ссылаются LESSON-ы (`observability-*`, `telemetry-stage6`, `observation-port`). Вердикты от этого не зависят.
- `.claude/settings.json`: проверил только отсутствие `taskkill`; полный список `permissions.deny/ask` не читал. Правила `uv sync*` и `pkill*` могут уже существовать в другой форме.
- Пути `.rules/gui.md`, `.rules/plugins.md`, `.rules/logging.md` существуют (`ls .rules`); их содержимое не читал, строки правил могут уже там быть.
- Сборку «mod:»-тегов делал по тексту дайджеста; имена модулей (`observation_port`, `process_manager`, `telemetry`) взяты из заголовков файлов, а не сверены с `multiprocess_framework/modules/`.
