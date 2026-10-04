# R1 — аудит памяти, доля `feedback_[a-l]*.md` (135 файлов)

Метод: frontmatter + первые ~1000-1500 знаков каждого файла (head); 6 файлов прочитаны шире (commit_msg_format, git_main_merge_hook_traps, injection_zero_may_mean..., a_zero_under_injection..., плюс шапки спорных). Факты сверены `git grep` по репозиторию (не grep -r). Индекс qex не использовался. Имена в таблице без префикса `feedback_` и без `.md`.

Легенда групп слияния: G1…G14 (см. раздел 2). Действие: KEEP / MERGE / MOVE (в механизм) / ARCHIVE.

## 1. Таблица

| file | kind | action | target | tags | hook | reason |
|---|---|---|---|---|---|---|
| a_budget_belongs_to_a_path_not_to_a_mechanism | LESSON | KEEP | - | mod: telemetry/observability; mech: perf-budget | Бюджет мкс написан на дорогу данных, не на механизм | Замер 1.35 против 3.53 мкс; верное решение отвергли по чужой дороге |
| a_control_can_exist_and_be_dead | LESSON | KEEP | - | mod: telemetry, config.reload; mech: acceptance-criteria | Строка пульта есть, а тумблер холостой | Стенд: success, но лист шагает 5.0 с |
| a_control_reproduces_the_defect_it_was_built_to_catch | LESSON | KEEP (выживший G7) | - | mod: observation_port; mech: success-value-vs-fact | Контрол против «успех без факта» сам стал таким | Три этажа одного дефекта; delivered=5 без приёмников |
| a_criterion_that_transforms_observes_the_library | LESSON | KEEP | - | mod: config_module (pydantic); mech: acceptance-criteria, tester | Тест сам преобразует и наблюдает pydantic, не систему | Критерий неисполним ни одной реализацией; S-24 |
| a_decision_orphans_what_encoded_the_previous_one | LESSON | KEEP | - | mod: telemetry config, golden snapshots; mech: decision-change checklist | Смена решения осиротила golden и приёмочные тесты | cb79d884 осиротил 3 артефакта; гейт две недели красный |
| a_dedup_marker_is_an_assertion_about_someone_else | LESSON | KEEP | - | mod: logger_module, error_module; mech: dedup | origin=error_manager врёт, когда ErrorManager нет | Харнес: 1 строка до правки, 0 после |
| a_degenerate_value_is_not_zero_it_is_unknown | LESSON | KEEP | - | mod: process_module telemetry; mech: validation-at-consumer | Ноль у источника законен, у потребителя вырожден | tick=0.0 вернул тот же отчёт; heartbeat min=0.0 |
| a_delta_benchmark_hides_what_sits_on_both_sides | LESSON | KEEP | - | mod: observation_port; mech: perf-measurement, test-doubles | Тест-разность не видит механизм, общий у обеих дорог | Мерился двойник; бюджет 2 -> 5 мкс поднят зря |
| a_diagnostic_answer_must_be_computed_last | LESSON | KEEP | - | mod: process_module (config.reload); mech: stage-ordering | Диагноз считать последней строкой ленты стадий | Два одинаковых reload дали разные caps |
| a_diff_based_rescue_omits_untracked_files | LESSON | KEEP | - | mech: git, worktree | Патч не спасает untracked: спасать веткой от HEAD | Тест на 454 строки не попал в патч |
| a_faithful_fake_still_lacks_the_protocol | LESSON | KEEP (выживший G3) | - | mech: test-doubles; mod: error_module | Дублёр верен форме, но не протоколу ErrorManager | track_error pop-ает message; сторож зелёный на лжи |
| a_fix_on_a_finding_must_not_outgrow_it | LESSON | KEEP | - | mod: pipeline/plugin_module; mech: review-fix scope | Правка шире находки сняла соседний предохранитель | Фильтр RUNNING срезал processing; батч поехал молча |
| a_guard_below_the_claim_guards_the_layer_not_the_claim | DUP | MERGE | a_handmade_readback_leaves_its_producer_unguarded (G8) | mod: logger_module; mech: guard-layer | Сторож читает источник, а не readback | Заплата pass убила 0 из 350; тот же класс, что G8 |
| a_guard_that_counts_at_least_once_is_blind | LESSON | KEEP (выживший G5) | - | mech: guard-design, lock-discipline | Сторож «хоть раз» слеп; прокси-лок считает входы по дорогам | RLock в 7 позициях снят: 12 тестов зелёные |
| a_handmade_readback_leaves_its_producer_unguarded | LESSON | KEEP (выживший G8) | - | mod: observability_wiring; mech: guard-layer, hand-built-fixture | Тест собирает readback руками: производитель без сторожа | 145 зелёных при снятой строке readback |
| a_hook_dead_on_windows_by_a_trailing_cr | LESSON | KEEP | local-only (Windows/Git Bash) | mech: hooks | read < <(...) оставляет CR: хук молчит месяцами | autoformat мёртв с 2026-05-15; 68 отказов ruff |
| a_hook_that_writes_a_shared_file_deadlocks_two_writers | STALE | ARCHIVE | перенести «MM не значит обе стороны целы» в precommit_stash_collision_2plus_agents (из доли m-z) | mech: git, pre-commit | Хук session-log, писавший в общий файл | Хук снят 2026-10-03; в .git/hooks/pre-commit его нет |
| a_knob_can_be_applied_and_unverifiable | LESSON | KEEP | - | mod: process_module (observability_verified); mech: config_reload_verified | Под-секция без менеджера идёт мимо сверщика | events.*: unverifiable при checked=0; соседняя ручка 8/8 |
| a_list_walking_guard_cannot_see_a_removed_item | DUP | MERGE | a_guard_that_counts_at_least_once_is_blind (G5) | mod: backend_ctl protocol; mech: guard-design | Обходчик реестра слеп к удалённой записи | I16: ключ удалён, тест зелёный; держит один литерал-тест |
| a_lock_patch_can_hang_the_exit_not_the_test | DUP | MERGE | inject_only_after_the_work_is_committed (G2) | mod: logger_module; mech: break-injection harness | Заплата на лок вешает выход через logging.shutdown | 1 failed, 162 passed, затем pytest завис минутами |
| a_measurement_capped_by_its_own_limit_proves_nothing | LESSON | KEEP | - | mod: backend_ctl (history_query); mech: probe-design | Замер упёрся в limit: три разных вызова дали 500 | С limit=20000: 8788 = 2298 + 6490 |
| a_migration_fixture_built_by_todays_writer_tests_the_writer | DUP | MERGE | a_handmade_readback_leaves_its_producer_unguarded (G8) | mod: observability store; mech: migration-test | Легаси-файл строить сырым INSERT, не сегодняшним писателем | Заплата убила 1 тест из 3 ожидаемых; унести: чинить ВСЕ строки |
| a_new_guard_can_weaken_an_old_one | LESSON | KEEP | - | mod: process_module commands; mech: guard-design, type-coercion | Слой, приводящий значение, узаконил ttl=True | bool -> 1.0 дошёл до хендлера; нашёл старый тест |
| a_new_plan_must_be_placed_among_its_neighbours | RULE | MOVE | команда /dev:plan + агент manager | mech: plans | План не готов, пока не поставлен среди соседей (QUEUE + двусторонние ссылки) | Правило процесса; поправка владельца 2026-09-22 |
| a_number_without_spread_across_repeats_is_an_observation | LESSON | KEEP | - | mod: BoundedChannel/telemetry; mech: perf-measurement | Число без разброса по >=3 повторам — наблюдение | 118.7, 48.8, 0.5 мкс на одном коде |
| a_pass_through_block_is_not_a_fork | LESSON | KEEP | - | mod: scripts static guards (AST); mech: AST-rules | Тело try/with не развилка; ошибка даёт тихий зелёный | Три редакции обходчика, ошибки нашла только инъекция |
| a_peer_session_shares_the_tree | LESSON | KEEP | - | mech: git, parallel-sessions | git add -A затянул чужие 98 строк | Автор найден через ListAgents; стейджить явные пути |
| a_plans_premise_expires | LESSON | KEEP | - | mech: plans, deferred-tasks | Условие разблокировки в плане устаревает — воспроизводить запуском | 2.3b: коллизия жива после 2.4/2.5 |
| a_probe_must_enumerate_before_it_asks | LESSON | KEEP | - | mod: config_module (defaults_for_category); mech: probe-design | Пустой ответ на несуществующее имя читается как «ничего нет» | Категорий sources/utility нет вовсе; нашло ревью |
| a_probe_that_guesses_tempo_says_no_when_it_means_dont_know | LESSON | KEEP | - | mod: otel-export; mech: probe-design | Пять ложных опровержений на исправном механизме | Все пять — дефекты зонда: форма, темп, готовность |
| a_process_wide_throttle_turns_neighbours_vacuous | LESSON | KEEP | - | mod: logger_module (windowed_voice); mech: test-isolation | Процессный дроссель делает соседние тесты порядко-зависимыми | Два соседа сломаны правкой в 8 строк; вакуумный зелёный |
| a_shared_throttle_swallows_the_record_not_the_line | LESSON | KEEP | - | mod: process_module/health, error_module; mech: throttle | Общий дроссель роняет запись, счётчик компенсирует число | Повтор в окне: плоскость ошибок не получила ничего |
| a_shortened_interval_waits_out_the_old_deadline | LESSON | KEEP | - | mod: observability_wiring (history purge); mech: live-stand | Укороченный период ждёт срок по старому периоду | Ждали 14 с: ноль голоса; ручка отвечала success |
| a_stand_with_a_verdict_is_also_a_harness | LESSON | KEEP | - | mod: otel-export; mech: live-stand, test-doubles | Стенд с нашим приёмником доказывает оснастку | Своя заглушка 200 на любой путь; otelcol дал 404 |
| a_stub_silences_the_names_it_is_read_for | DUP | MERGE | a_faithful_fake_still_lacks_the_protocol (G3) | mech: test-doubles | Дублёр глушит имена, которые код у него читает | И6 писаемое имя: 5 красных; И10 читаемое: молчит |
| a_test_that_pins_a_hole_is_green_both_ways | LESSON | KEEP | - | mod: backend_ctl (history_query); mech: break-injection | Тест, закрепляющий дыру, зелен до и после | Заплата И5 его не покраснила; это документация |
| a_zero_under_injection_has_three_readings | DUP | MERGE | injection_zero_may_mean_the_guards_were_not_collected (G1) | mech: break-injection | Ноль красных: реплика, выборка или незастережённая ветка | Тот же ноль, те же чтения; унести: у выхода несколько стражей |
| absence_assertion_under_extra_ignore_is_vacuous | DUP | MERGE | an_absence_assertion_needs_a_reachability_check (G6) | mod: config_module (pydantic extra=ignore); mech: absence-assertion | not hasattr на схеме extra=ignore держится сам | Тот же класс; унести: переписать на model_fields_set |
| absent_receiver_lets_a_test_pin_an_impossible_input | LESSON | KEEP | - | mod: config_module (MetricRule); mech: test-doubles | Харнесс без получателя не судит форму входа | Тест годами зелёный на {fps: True}, прод отвергает |
| acceptance_criterion_needs_a_live_trigger | LESSON | KEEP | - | mod: observation_port (plugin shutdown); mech: acceptance-criteria | «Наблюдать X на стенде» без ручки, вызывающей X | _do_shutdown вызывается из одного места; ручки нет |
| agent_commit_quality | RULE | MOVE | skill project-rules §4 (одна строка) | mech: agents, commits | В брифе developer: тема коммита без транслита | Правило процесса; в агентах/плагине слова translit нет |
| agent_hard_budget_is_off_by_default | REFERENCE | KEEP | - | mod: hooks (agent_context_ceiling); mech: agents | Жёсткий потолок агента выключен: включать .budget | developer ушёл на 401k токенов; хук и файл есть |
| agent_resume_ghost | LESSON | KEEP | - | mech: agents, SendMessage | Реанимация агента может родить второй инстанс | Watchdog не смерть; проверять mtime зоны |
| alias_keeps_the_object_alive | LESSON | KEEP | - | mod: channel_routing_module/router_module; mech: dead-code grep | Grep по методам не видит присваивания объекта | После сноса 204 красных; channel_dispatcher = self._dispatcher |
| all_components_base_manager | DUP | MERGE | logger_error_stats_managers (G12) | mod: base_manager; mech: ObservableMixin | Все компоненты наследуют BaseManager+ObservableMixin | Тот же принцип; унести: цена — lifecycle-церемония, принято |
| always_latest_models | RULE | MOVE | skill project-rules §5 + lint-agents allow-list | mech: agents, models | Алиасы opus/sonnet/haiku/fable, без версий в прозе | Правило процесса; закреплено lint allow-list |
| always_project_venv | REFERENCE | KEEP | local-only (Windows, пути .venv) | mech: env | Интерпретатор — проектный .venv; uv run без флагов нет | uv run падает на extras ml-torch; qt-mcp висел в cfg |
| an_absence_assertion_needs_a_reachability_check | LESSON | KEEP (выживший G6) | - | mod: scripts static guards; mech: absence-assertion | Утверждение об отсутствии — в паре с достижимостью | Тест-негатив зелёный при красном предмете |
| an_applying_command_cannot_measure_what_it_reapplies | LESSON | KEEP | - | mod: process_module (config.reload); mech: probe-design | Применяющей командой живость не измерить | Второй reload вернул 3.5 вместо 9.25: переустановил |
| an_avoidance_rule_can_be_a_false_safety_catch | LESSON | KEEP | - | mod: scripts/run_framework_tests.py; mech: inherited-rules | Унаследованное «не гонять X вместе с Y» проверять замером | Раннер уже гоняет оба в одном процессе |
| an_injection_must_prove_its_axis_is_live | DUP | MERGE | injection_zero_may_mean_the_guards_were_not_collected (G1) | mod: otel-export; mech: break-injection | Ноль: заплата легла туда, где свойство не меняется | round vs int совпали на 0 из 144; унести: показать изменение выхода ДО подсчёта |
| an_inventory_grep_needs_fixed_strings | RULE | MOVE | skill project-rules §1/§2 (одна строка: счёт имён только grep -F) | mech: grep, inventory | Счёт имён с точками — grep -F | queue.evicted дал 3 вместо 0; точка = любой символ |
| attribute_the_source_before_cutting | LESSON | KEEP | local-only (два уровня .claude/ и ~/.claude/) | mech: context-audit | Имя из двух источников: сверять состав множеств | Резал не тот источник; экономия заявлена до прогона |
| backend_ctl_for_agents | RULE | MOVE (выживший G10) | CLAUDE.md, раздел MCP routing, строка backend-ctl | mod: backend_ctl; mech: agents, live-stand | Бэкенд отлаживать через backend_ctl, не GUI и не qt-mcp | Директива владельца 2026-07-06 |
| backend_ctl_layer_mixed | RULE | MOVE | skill project-rules §4 или docs/claude/COMMIT_GUIDE.md | mod: backend_ctl; mech: commits | Коммиты backend_ctl: Layer: mixed, не tools | Allowlist validate_commit.py не знает tools (grep 0) |
| background_reviewer_loses_the_verdict | REDUNDANT | ARCHIVE | правило уже в .claude/CLAUDE.md «Subagents are background by default» | mech: agents, review | Фоновый ревьюер без Handback не оставляет ни строки | Правило записано; унести одну фразу про сутки без следа |
| barrier_at_entry_does_not_reproduce_the_race | LESSON | KEEP | - | mod: state_store_module (_make_room); mech: concurrency-tests, break-injection | Барьер на входе гонку не воспроизводит | Стенд зелёный 6/6 под собственной инъекцией |
| base_guard_dead_in_heir | LESSON | KEEP | - | mod: channel_routing_module (Logger/Error/Stats/Router); mech: inheritance | Защита в базе мертва у наследника, резолвящего своё | LoggerCore передаёт config=None: слепок пуст |
| baseline_taken_after_the_act_proves_nothing | LESSON | KEEP | - | mod: backend_ctl BuiltinCommands; mech: acceptance-tests | Baseline после действия — проверка идемпотентности | commands_before снят после регистрации |
| bash_heredoc_collapses_backslashes | DUP | MERGE | bash_tool_unbalanced_quote_breaks_command (G9) | local-only (Windows Bash tool); mech: tooling | Bash tool схлопывает обратные слэши даже в heredoc | Три раза 2026-09-29; тот же обход: Write/Edit |
| bash_tool_unbalanced_quote_breaks_command | LESSON | KEEP (выживший G9) | - | local-only (Windows Bash tool); mech: tooling | Непарный апостроф ломает Bash даже в heredoc | Дважды 2026-09-02; скрипты с прозой — через Write |
| born_wrong_then_fixed_looks_like_working | LESSON | KEEP | - | mod: stats_module, orchestrator L0; mech: config-layers | Создан на дефолтах и починен позже — кричит на каждом старте | StatsManager предупреждал о своём конфиге при верном yaml |
| broad_except_in_frame_loop_hides_dead_mechanism | LESSON | KEEP | - | mod: line_sim (SceneSourcePlugin), frame loops; mech: live-run | Широкий except в кадровом цикле: поломка тиха | set_flow сбросил порог в None; лог — одна строка |
| broken_injection_is_not_a_vacuous_test | DUP | MERGE | injection_zero_may_mean_the_guards_were_not_collected (G1) | mech: break-injection | Инъекция, ломающая импорт, даёт ERROR, а не FAILED | 0 красных читалось как вакуум; унести: считать ERROR |
| cache_hides_the_once_only_property | LESSON | KEEP | - | mod: logger_module (gate dedup); mech: test-data | Кэш гасит повторы: тест однократности вакуумен | Три одинаковые записи; снятие дедупа не краснело |
| check_qex_freshness_before_use | REDUNDANT | ARCHIVE | root CLAUDE.md раздел qex + project-rules §1 + .claude/CLAUDE.md | mech: qex | Перед qex сверять last_indexed с сегодня | Правило уже в 3 местах; убрать строку из индекса |
| check_red_on_main_first | RULE | MOVE (выживший G13) | агент debugger + skill systematic-debugging | mech: debugging, git | Красный тест сначала прогнать на main | 6 падений жили и на main; вариант с worktree вместо stash |
| checked_true_answers_for_the_call_not_the_coverage | DUP | MERGE | a_control_reproduces_the_defect_it_was_built_to_catch (G7) | mod: process_module (detect_throttle_caps); mech: success-value-vs-fact | checked: true при пустом списке — факт вызова, не охвата | continue на правиле без interval_sec; троттл резал в 40 раз |
| classify_a_leaf_by_the_difference_of_two_values | LESSON | KEEP | - | mod: process_module (expand_observability); mech: probe-design | Лист классифицировать разностью двух значений | Одно значение путает «не читается» и «равно дефолту» |
| claude_cli_backend_costs_a_full_session | REDUNDANT | KEEP файл как источник; убрать из индекса | root CLAUDE.md абзац «Цена бэкендов claude-cli» (ссылается на файл) | mech: cost, graphify | claude-cli = полная сессия за вызов: вызовы x 50k | 53 вызова съели дневной лимит; суть уже в CLAUDE.md |
| cleanup_must_survive_abnormal_disconnect | LESSON | KEEP | - | mod: backend_ctl (SocketChannel); mech: resource-cleanup | Уборку проверять и RST-обрывом, не только close | 0 из 12 вежливых; RST воспроизвёл с 1-й попытки |
| coinciding_constants_hide_opposite_implementations | LESSON | KEEP | - | mod: state_store_module (throttle prune); mech: test-data | Константы, на которых две реализации совпадают | floor(now/1.0)==now: 18 тестов зелёные под инъекцией |
| commit_msg_format | DUP | MERGE | commit_takes_the_whole_index (G14) | mech: git, pre-commit | ruff-format правит файлы: re-stage и новый commit | Пункт 1 (trailer в одну строку) устарел: хук терпит перенос |
| commit_takes_the_whole_index | LESSON | KEEP (выживший G14) | - | mech: git, pre-commit | git commit берёт весь индекс; откат pre-commit ест правки | 34 удаления D2 уехали в fix(store): D3 |
| compare_validated_values_not_raw_config | LESSON | KEEP | - | mod: config_module; mech: defaults-audit | Равенство дефолту — по валидированной модели | Сырой YAML занижает счёт; S-26 |
| config_delivery_shape_differs | DUP | MERGE | fakes_feed_config_flat_so_key_address_defects_are_invisible (G4) | mod: process_module (spawner, process_runner); mech: config-delivery | get_config у ребёнка молча None; нужен read_process_config | Тот же факт; унести: исправление read_process_config(svc,key) |
| config_reload_ttl_addressing_guard | LESSON | KEEP | - | mod: process_module (config.reload); mech: test-writing | Отказ ttl на throttle-only — старый guard, не предмет теста | Низкая ценность: узкая ловушка; кандидат в архив при чистке |
| config_update_dead_with_handler | LESSON | KEEP | - | mod: process_module (Config.update); mech: test-doubles | update_config падал TypeError у всех живых процессов | Тест строил объект без config_handler |
| constant_from_domain_physics_not_measured | LESSON | KEEP | - | mod: telemetry histograms; mech: constants-vs-emission | Пороги из физики сверять с тем, что система эмитит | 99.28 % значений ниже выбранной границы |
| constructor_modularity | RULE | MERGE | framework_first (G11) -> root CLAUDE.md блок «Принципы владельца» | mech: architecture | Pluggable/testable/composable + изоляция отказов | Принцип владельца; в корневой CLAUDE.md одной строкой |
| coverage_holds_settrace_not_setprofile | LESSON | KEEP | - | mod: framework tests (_road_cost.py); mech: coverage, tracing | Под --cov занят settrace; setprofile свободен | _road_cost.py использует setprofile — живо |
| coverage_per_check_is_not_coverage_per_claim | DUP | MERGE | a_guard_that_counts_at_least_once_is_blind (G5) | mod: scripts/docs_verify; mech: guard-design | Страж «у проверки есть инъекция»: проверка несёт 3 утверждения | F2-3: инъекции только у первого; унести: инъекция на утверждение |
| ctypes_setattr_unknown_field_is_silent | LESSON | KEEP | - | mod: Services/code_reader (ctypes); mech: test-data | setattr неизвестного поля ctypes молчит | Слепой тестер угадал nX/nY; нули прошли бы |
| deep_merge_is_not_associative | LESSON | KEEP | - | mod: config layers (deep_merge); mech: property-testing | deep_merge не ассоциативен: складывать дельты нельзя | 20 000 троек: 239 расхождений |
| default_path_must_match_publisher | LESSON | KEEP | - | mod: alerts, Plugins/sources/capture; mech: config-defaults | Дефолтный путь сверять с реальным публикатором | drops_count никто не публикует; 26 тестов зелёные |
| defect_fixed_on_one_path_only | LESSON | KEEP | - | mod: process_module (config.reload, telemetry.reconfigure); mech: review | Дефект закрыт на одном пути воскресает на соседнем | Ревью 5.10: два воскресших дефекта |
| detector_comparing_representation_fires_always | LESSON | KEEP | - | mod: prototype backend/assembly (planner); mech: detectors | Детектор сравнивает представление и горит всегда | Повторный apply той же топологии: protected_conflicts не пуст |
| diagnose_live_system_with_backend_ctl | DUP | MERGE | backend_ctl_for_agents (G10) | mod: backend_ctl; mech: live-stand | Живую систему — штатным backend_ctl, не psutil | Тот же принцип; унести: system_overview+supervision_status+get_status за 3 вызова |
| dialog_conventions | RULE | MOVE | path-scoped .rules/gui.md | mod: frontend; mech: GUI conventions | Диалог: Сохранить (default) / Не сохранять / Отмена | Конвенция владельца 2026-07-13, RS-4 |
| dict_at_boundary_gui | REDUNDANT | ARCHIVE | .rules/gui.md и корневой CLAUDE.md правило 1 (Dict at Boundary) | mod: frontend | Виджеты работают с dict, не с живым SchemaBase | Правило уже в .rules/gui.md; git grep подтвердил |
| discriminator_switch_must_be_verified | LESSON | KEEP | - | mech: experiment-control, pytest testpaths | --ignore не выключил testpaths-зону | «Без Qt» прогон исполнил 2411 Qt-тестов |
| docs_assert_what_registration_never_set | LESSON | KEEP | - | mod: worker_module (heartbeat_sender, worker_type); mech: docs-vs-code | Три докстринга утверждали SYSTEM, воркер создан APPLICATION | Флап unresponsive<->running каждые 5 с |
| double_must_block_like_the_original | DUP | MERGE | a_faithful_fake_still_lacks_the_protocol (G3) | mech: test-doubles | Дубль обязан воспроизводить темп оригинала | Мгновенный receive: инъекция дала разгон по памяти |
| drop_oldest_reports_success | LESSON | KEEP | - | mod: observability hub (BoundedChannel); mech: success-value-vs-fact | drop_oldest отвечает success, вытеснив чужое | Судить по приросту счётчика, не по статусу |
| dual_write_by_copy_destroys_the_other_side | RULE | MOVE | раздел Memory в .claude/CLAUDE.md + скрипт сверки diff перед записью | mech: memory, git | Dual-write — две правки; перед cp обязателен diff | cp затёр 22 строки уникального; копии расходятся в обе стороны |
| duplicate_fixture_verifies_itself | LESSON | KEEP | - | mod: backend_ctl tests (conftest); mech: fixtures | Приватная копия общей фикстуры проверяет сама себя | Три счётчика в conftest, копия осталась прежней |
| emergency_log_reaches_stderr_not_the_log_files | LESSON | KEEP | - | mod: logger_module (_fallback); mech: voice-address | emergency_log доезжает до stderr, не до файла | 0 строк в файле против 2 у FallbackLogger |
| env_knob_reads_its_own_write | LESSON | KEEP | - | mod: prototype build(); mech: env-config | Ручка из env читает свою же запись | Второй build() принял свой setdefault за волю оператора |
| explicit_model_per_agent_role | RULE | MOVE | skill project-rules §5 + одна строка в .claude/CLAUDE.md | mech: agents, models | В каждом Agent-вызове передавать model явно | Журнал не пишет модель; ревью ушло не на Opus |
| facade_is_a_whitelist_not_a_passthrough | LESSON | KEEP | - | mod: process_module (observability_config, expand_observability); mech: config-facade | Поле в схеме менеджера не делает ручку управляемой | log_line_max_bytes: тест зелёный, из конфига не управляется |
| fake_that_always_succeeds_mutes_the_gate | DUP | MERGE | a_faithful_fake_still_lacks_the_protocol (G3) | mod: queue_registry; mech: test-doubles | Дубль «успех на любой вход» глушит гейт | Инъекция I-12: 0 красных вместо 1 |
| fakes_feed_config_flat_so_key_address_defects_are_invisible | LESSON | KEEP (выживший G4) | - | mod: process_module config; mech: test-doubles, config-delivery | Дублёры подают конфиг плоско, прод вложенно | Класс «ключ по неверному адресу» тестам невидим |
| false_alarm_traded_for_silent_loss | LESSON | KEEP | - | mod: observability (sink.disable, config.reload); mech: operator-sequence | Снимая ложную тревогу, проверь последовательность оператора | config.reload поднял снятый канал: все классы потерь = 0 |
| fewer_layers | RULE | MERGE | framework_first (G11) | mech: architecture | Меньше слоёв при той же функциональности строго лучше | Принцип владельца 2026-06-05 |
| fix_framework_forward | RULE | MERGE | framework_first (G11) | mech: architecture | Баги framework чинить; улучшать, а не удалять | Принцип владельца 2026-06-04 |
| flags_must_not_become_crutches | RULE | MOVE | команда /dev:ship + шаблон Task (критерий «флаг удалён») | mech: feature-flags | Флаг закрыт, когда УДАЛЁН, а не флипнут | Владелец 2026-07-22; реестр уже 18 флагов |
| formal_review_before_merge | RULE | MOVE | команда /dev:ship (проверка артефакта /code-review) | mech: review, git | Merge в main — только после оформленного /code-review | Классификатор блокирует merge без артефактов ревью |
| framework_first | RULE | MOVE (выживший G11) | root CLAUDE.md, блок «Принципы владельца» (5 строк) | mech: architecture | Framework универсален, прототип расходный | Принцип владельца 2026-06-18; сводит 5 файлов |
| freeze_over_kill | RULE | MERGE | framework_first (G11) | mech: architecture, dead-code | Мёртвый код замораживать, не удалять | Прецеденты actions_module, GATE G2 форм |
| gate_criterion_can_contradict_an_owner_decision | LESSON | KEEP | - | mod: telemetry gate; mech: acceptance | Проваленный пункт гейта: может спорить критерий | Ф6: 6 из 16 пунктов; два — критерий против решения |
| gate_off_zeroes_deltas_not_messages | LESSON | KEEP | - | mod: state_store/telemetry (publisher gate); mech: measurement | Закрытый гейт обнуляет дельты, не число IPC | status идёт мимо гейта; мерить state.changed |
| gate_signature_lives_on_a_head | RULE | MOVE | команда /dev:ship + агент cto (приёмка гоняет гейт сама) | mech: gates, acceptance | Подпись гейта живёт на конкретном HEAD | 21 красный сутки на HEAD после 6 хвостовых коммитов |
| git_main_merge_hook_traps | RULE | MOVE (разделить) | единый формат merge -> docs/claude/COMMIT_GUIDE.md и корневой CLAUDE.md; грабли 1-6 остаются LESSON | mech: git, hooks, merge | Merge: «merge: суть» + Why/Layer/Refs; merge -F - не читает stdin | Решение владельца 2026-10-03; два вида содержимого в одном файле |
| git_stash_pop_wrong_stash | DUP | MERGE | check_red_on_main_first (G13) | mech: git | stash -u на чистом дереве: pop берёт чужой стеш | Тот же приём; унести: stash@{0} — не «мой» |
| global_clock_patch_flake | LESSON | KEEP | - | mod: state_store_module (throttle tests); mech: test-flake, clock-injection | patch(time.monotonic) с конечным списком — флейк | Чужие потоки доедают список: StopIteration в чужом тесте |
| green_run_hides_synchronous_only_correctness | LESSON | KEEP | - | mod: router_module (_log_debug); mech: lazy-eval | Лямбда с except-именем жива только пока синхронна | 30 тестов и 6950 гейт зелёные; мину нашёл линтер |
| guard_must_be_reachable | LESSON | KEEP | - | mod: plugin_module (PluginContext.write_document); mech: guard-design | Защита верна и недостижима: TypeError раньше тела | kind как обычный параметр: запись теряется исключением |
| guard_on_existence_is_not_a_guard_on_content | DUP | MERGE | a_guard_that_counts_at_least_once_is_blind (G5) | mod: pytest testpaths; mech: guard-design | Страж проверял существование пути, не содержимое | Пустой каталог после carve-out: ложь о покрытии три месяца |
| guard_threshold_hides_partial_blindness | DUP | MERGE | a_guard_that_counts_at_least_once_is_blind (G5) | mod: tests (thread deadlines); mech: guard-design | Страж по сумме («файлов >= 40») слеп к потере одной записи | Инъекция и-3; унести: проверять каждую запись списка отдельно |
| gui_save_strips_yaml_comments | LESSON | KEEP | - | mod: frontend settings (yaml_io.py); mech: config files | GUI Settings-Save сносит все комментарии system.yaml | yaml.safe_dump(model_dump) на yaml_io.py:58 |
| hot_path_hook_must_be_priced | LESSON | KEEP | - | mod: logger_module (redaction); mech: perf-measurement | Перехватчик на эмиссии сравнивать с ценой эмиссии | +5.64 мкс при цене 4.04 мкс — удвоил log() |
| idempotent_is_not_monotonic | LESSON | KEEP | - | mod: process_module (fan-out delivery); mech: ordering | Идемпотентность не защищает от «стейл после свежего» | Отложенная досылка перекрыла свежий конверт |
| inject_only_after_the_work_is_committed | LESSON | KEEP (выживший G2) | - | mech: break-injection harness, git | Харнесс инъекций git checkout-ом съедает незакоммиченное | Три файла вернулись к HEAD до базового прогона |
| inject_the_call_site_not_only_the_helper | LESSON | KEEP | - | mod: process_module (process_monitor); mech: break-injection | Снять боевой вызов: 30 сторожей звали хелпер напрямую | 0 красных из 4297 |
| injection_base_needs_a_collected_count | DUP | MERGE | injection_zero_may_mean_the_guards_were_not_collected (G1) | mech: break-injection | База инъекций — по числу СОБРАННЫХ тестов | Уже целиком внутри выжившего; уникального нет |
| injection_generator_must_differ_from_criteria_author | LESSON | KEEP | - | mech: break-injection, independence | Инъекции из критериев тем же автором ничего не доказывают | Список критериев со знаком минус; нужен род «нуль/тотал» |
| injection_green_when_the_substitute_equals_the_fact | LESSON | KEEP | - | mod: process_module (voice class); mech: break-injection | Константа вместо прочитанного: нужна фикстура с отличием | 0 красных при 11 зелёных: константа = факт |
| injection_must_cover_all_check_sites | LESSON | KEEP | - | mod: still_relevant ready-gate; mech: break-injection | Инъекция снимает ВСЕ точки исполнения правила | Дважды: 1 точка из 3 — 18 passed; полная — красные |
| injection_must_reproduce_the_mechanism_not_the_shape | LESSON | KEEP | - | mod: plugin_module (write_document); mech: break-injection | Инъекция-реплика воспроизводит механизм, не форму | Позиционный-only параметр: 0 на 146 (PEP 570) |
| injection_must_use_a_different_lens_than_the_test | LESSON | KEEP | - | mod: telemetry; mech: break-injection, independence | Инъекция смотрит другим объективом, чем тест | Красный доказывает согласие двух копий одной модели |
| injection_prediction_on_a_shared_corpus | LESSON | KEEP | - | mech: break-injection, prediction | Предсказание: «MUST поимённо + потолок красных» | Равенство множеств тонет в шуме чужих тестов |
| injection_rollback_by_restore_not_replace | DUP | MERGE | inject_only_after_the_work_is_committed (G2) | mech: break-injection harness | Откат инъекции — восстановлением текста, не обратной заменой | str.replace задел соседнее поле; 7 красных нашёл полный гейт |
| injection_too_coarse_proves_nothing_specific | LESSON | KEEP | - | mod: state_store (throttle); mech: break-injection | Грубая инъекция не доказывает частное свойство | Предсказан 1 красный, получено 9, причина другая |
| injection_zero_may_mean_the_guards_were_not_collected | LESSON | KEEP (выживший G1, ужать) | - | mech: break-injection, harness | Ноль красных: не собрались, не легла, не туда, ось пуста | 16, 2, 1 вместо 1, 0, 0; collected 0 вместо 563 |
| logger_error_stats_managers | RULE | MOVE (выживший G12) | корневой CLAUDE.md правило 6 + .rules/logging.md | mod: logger_module, error_module, statistics_module; mech: ObservableMixin | Лог/ошибки/статистика только через менеджеры base_manager | Правило уже в .rules/logging.md; файл — единственное полное изложение |

## 2. Группы слияния (выживший <- файлы; что унести)

| # | Выживший | Поглощает | Уникальное, что унести |
|---|---|---|---|
| G1 | injection_zero_may_mean_the_guards_were_not_collected (8.3 КБ, ужать до разделов) | a_zero_under_injection_has_three_readings, injection_base_needs_a_collected_count, broken_injection_is_not_a_vacuous_test, an_injection_must_prove_its_axis_is_live | у одного выхода несколько стражей (И5: патчить каждого); ERROR при сломанном импорте, считать не только FAILED; ось пуста: float64 > 2^53, round и int совпали на 0 из 144, показать изменение выхода ДО подсчёта красных. injection_base_needs_a_collected_count уже целиком внутри выжившего. Родня из доли m-z (проверить там): zero_reds_can_mean_a_useless_layer, unconnected_driver_reads_as_a_clean_zero, zero_observations_looks_like_a_result |
| G2 | inject_only_after_the_work_is_committed | injection_rollback_by_restore_not_replace, a_lock_patch_can_hang_the_exit_not_the_test | откат = восстановление сохранённого текста (str.replace задел соседнее поле, 7 красных); заплата на лок вешает выход через logging.shutdown (atexit): внешний срок и КОД ВЫХОДА. Это правила харнесса инъекций; лучше превратить в чек-лист скрипта инъекций |
| G3 | a_faithful_fake_still_lacks_the_protocol | a_stub_silences_the_names_it_is_read_for, fake_that_always_succeeds_mutes_the_gate, double_must_block_like_the_original | четыре оси неверности дублёра: протокол (pop служебных ключей), читаемые против писаемых имён (И6/И10), успех на любой вход (I-12), темп (мгновенный receive -> разгон по памяти). Сделать одну таблицу «ось - пример - инъекция» |
| G4 | fakes_feed_config_flat_so_key_address_defects_are_invisible | config_delivery_shape_differs | исправление: read_process_config(svc, key) в process_module/configs/observability_layers.py (git grep: 19 файлов); спавнер мержит orchestrator_config в корень, ребёнок получает весь proc_dict |
| G5 | a_guard_that_counts_at_least_once_is_blind | guard_threshold_hides_partial_blindness, a_list_walking_guard_cannot_see_a_removed_item, guard_on_existence_is_not_a_guard_on_content, coverage_per_check_is_not_coverage_per_claim | приёмы: прокси над настоящим локом считает входы по дорогам; проверка каждой записи списка отдельно; литерал-тест `assert "key" in REGISTRY` рядом с обходчиком; содержимое, не существование; инъекция на утверждение, не на проверку. Общее: агрегатный сторож слеп к точечной потере |
| G6 | an_absence_assertion_needs_a_reachability_check | absence_assertion_under_extra_ignore_is_vacuous | частный случай pydantic extra=ignore: переписать на model_fields_set |
| G7 | a_control_reproduces_the_defect_it_was_built_to_catch | checked_true_answers_for_the_call_not_the_coverage | `checked: true` + пустой список при `continue` на правиле без interval_sec; троттл резал в 40 раз |
| G8 | a_handmade_readback_leaves_its_producer_unguarded | a_guard_below_the_claim_guards_the_layer_not_the_claim, a_migration_fixture_built_by_todays_writer_tests_the_writer | сторож на слое ниже заявления (заплата base_stats.update(voice_counters()) -> pass убила 0 из 350); легаси-строки вписывать сырым INSERT и чинить ВСЕ строки фикстуры |
| G9 | bash_tool_unbalanced_quote_breaks_command | bash_heredoc_collapses_backslashes | обход один: скрипты с прозой и обратными слэшами — через Write/Edit; chr(92) в Python-сниппете; писать в TRAPS брифа субагента. Подтверждено на себе: при записи этого отчёта heredoc с апострофом упал |
| G10 | backend_ctl_for_agents | diagnose_live_system_with_backend_ctl | system_overview + supervision_status + get_status за 3 вызова против самописного psutil; gui жив при боевом запуске |
| G11 | framework_first | fix_framework_forward, freeze_over_kill, fewer_layers, constructor_modularity | пять принципов владельца одним блоком из 5 строк в root CLAUDE.md; прецеденты (actions_module, GATE G2 форм, P4.4 command-bus) оставить по одной строке |
| G12 | logger_error_stats_managers | all_components_base_manager | цена единообразия: lifecycle-церемония initialize/shutdown, принята осознанно (2026-06-07). Родня из m-z: three_managers_share_base — проверить дубль там |
| G13 | check_red_on_main_first | git_stash_pop_wrong_stash | `git stash -u` на чистом дереве ничего не прячет, pop берёт чужой stash@{0}; для проверки на main лучше worktree, чем stash+checkout |
| G14 | commit_takes_the_whole_index | commit_msg_format | пункт 2 (ruff-format правит файлы: re-stage и НОВЫЙ commit, не amend). Пункт 1 (trailer на одной строке) устарел: хук терпит перенос с 2026-07-14 |

Мягкие семьи, которые НЕ предлагаю сливать (разные приёмы, свои доказательства), но которым дать общий тег для поиска:
- probe-design: a_measurement_capped..., a_probe_must_enumerate..., a_probe_that_guesses_tempo..., an_applying_command..., classify_a_leaf...;
- break-injection-design (8 файлов): injection_generator_must_differ..., injection_must_use_a_different_lens..., injection_must_cover_all_check_sites, inject_the_call_site..., injection_must_reproduce_the_mechanism..., injection_too_coarse..., injection_green_when_the_substitute..., injection_prediction_on_a_shared_corpus. Если лид хочет сжать сильнее, лучшая пара — different_lens + generator_must_differ (оба про независимость источника инъекции);
- perf-measurement: a_budget_belongs_to_a_path..., a_delta_benchmark..., a_number_without_spread..., hot_path_hook_must_be_priced, constant_from_domain_physics...;
- throttle и голос: a_shared_throttle_swallows..., a_process_wide_throttle_turns_neighbours_vacuous, a_dedup_marker..., false_alarm_traded_for_silent_loss.

## 3. Файлы RULE: механизм и текст правила

| Файл | Механизм | Правило одной строкой |
|---|---|---|
| a_new_plan_must_be_placed_among_its_neighbours | команда /dev:plan + агент manager | Before closing a plan, read QUEUE.md and the plans that own adjacent mechanisms, and add a two-way link: who owns what, what it takes, what it gives, where the conflict is. |
| agent_commit_quality | project-rules §4 | In a developer brief, state: commit subject in English or Russian, never transliterated Latin; check `git log --oneline -1` before any push. |
| always_latest_models | project-rules §5 | Use tier aliases (opus/sonnet/haiku/fable) in agent files and prose; write a model version only with a stated reason and a comment. |
| an_inventory_grep_needs_fixed_strings | project-rules §1/§2 | Count occurrences of dotted names (metrics, modules, config keys) with `grep -F` only; the dot in a regex inflates the count. |
| backend_ctl_for_agents (+G10) | CLAUDE.md, MCP routing | Debug and test the backend through backend_ctl (it sends the same router messages as the GUI); use qt-mcp only to check the GUI itself; never write ad-hoc psutil scripts. |
| backend_ctl_layer_mixed | project-rules §4 или COMMIT_GUIDE | Commits for backend_ctl use `Layer: mixed`, not `tools` (the validate_commit allowlist has no `tools`). |
| check_red_on_main_first (+G13) | агент debugger + skill systematic-debugging | Before diagnosing a red test as a regression, run it on main (use a worktree, not stash); stale expectations after other people's refactors also fail there. |
| framework_first + constructor_modularity + fewer_layers + fix_framework_forward + freeze_over_kill (G11) | root CLAUDE.md, блок «Принципы владельца» | Framework is universal, prototype is disposable; fix framework bugs by improving, never by deleting; freeze dead code, do not kill it; fewer layers at equal function; every component is a pluggable, testable unit and a failure stays inside its blast radius. |
| dialog_conventions | .rules/gui.md | Unsaved-changes dialog uses Save (default) / Don't Save / Cancel; do not invent wording. |
| dual_write_by_copy_destroys_the_other_side | .claude/CLAUDE.md, раздел Memory | Memory dual-write is two separate edits; run `diff` before any copy; never `cp` one side over the other. |
| explicit_model_per_agent_role | project-rules §5 + .claude/CLAUDE.md | Pass `model` explicitly on every Agent call (reviewer/teamlead opus, developer/tester/debugger sonnet, cto fable) and state it in the brief. |
| flags_must_not_become_crutches | /dev:ship + шаблон Task | A dark-launch flag task is closed only when the flag and its OFF branch are deleted, not when the default flips. |
| formal_review_before_merge | /dev:ship | Run a formal `/code-review` (finders, verify, report) before any merge to main; informal checks do not unblock the classifier. |
| gate_signature_lives_on_a_head | /dev:ship + агент cto | A gate result is valid only for the HEAD it ran on; at acceptance run the gate yourself, do not take the number from a report. |
| git_main_merge_hook_traps | COMMIT_GUIDE + root CLAUDE.md (позже хук) | Merge commits read `merge: <what entered>` plus Why/Layer/Refs; use `git merge --no-ff <branch> -m ... -m ...` (`-F -` does not read stdin). Грабли 1-6 файла остаются LESSON. |
| logger_error_stats_managers (+G12) | root CLAUDE.md правило 6 + .rules/logging.md | Framework code logs, reports errors and counts stats only through the injected managers (ObservableMixin); no print, no logging.getLogger, no local counters. |

## 4. Кандидаты в индекс MEMORY.md (не больше 12)

Критерий: правило срабатывает до того, как о нём вспомнят, или урок настолько дорог, что стоит ~40 токенов в каждой сессии. Остальное достаётся по тегу из CRAFT.md.

1. [Ноль красных под инъекцией](feedback_injection_zero_may_mean_the_guards_were_not_collected.md) — не собрались / не легла / не туда / ось пуста; collected числом до заплат
2. [Агрегатный сторож слеп](feedback_a_guard_that_counts_at_least_once_is_blind.md) — «хоть раз», сумма, существование: проверять поимённо и литералами
3. [Дублёр верен форме, не протоколу](feedback_a_faithful_fake_still_lacks_the_protocol.md) — четыре оси: протокол, читаемые имена, успех на всё, темп
4. [Утверждение об отсутствии](feedback_an_absence_assertion_needs_a_reachability_check.md) — зелено вхолостую без парной проверки достижимости
5. [Число без разброса — наблюдение](feedback_a_number_without_spread_across_repeats_is_an_observation.md) — 118.7 / 48.8 / 0.5 мкс на одном коде
6. [Разность двух дорог не видит общего](feedback_a_delta_benchmark_hides_what_sits_on_both_sides.md) — мерится двойник, бюджет поднят зря
7. [Патч не спасает untracked](feedback_a_diff_based_rescue_omits_untracked_files.md) — спасать веткой от HEAD, пересечение числом
8. [Чужая сессия в том же дереве](feedback_a_peer_session_shares_the_tree.md) — git add -A затянул чужое; ListAgents, явные пути
9. [Грабли merge в main и формат merge](feedback_git_main_merge_hook_traps.md) — merge: суть + Why/Layer/Refs; -F - не читает stdin
10. [Хук мёртв из-за CR](feedback_a_hook_dead_on_windows_by_a_trailing_cr.md) — живость хука доказывать настоящим входом
11. [Посылка плана устаревает](feedback_a_plans_premise_expires.md) — блокер воспроизводить запуском, не сверять номера
12. [Принципы владельца: framework-first](feedback_framework_first.md) — framework универсален; чинить вперёд; морозить, не убивать; меньше слоёв

Убрать из индекса (уже есть в CLAUDE.md и правилах): check_qex_freshness_before_use, claude_cli_backend_costs_a_full_session (файл оставить: на него ссылается root CLAUDE.md), dict_at_boundary_gui.

## 5. Счётчики

| Kind | Файлов |
|---|---|
| LESSON | 85 |
| DUP | 23 |
| RULE | 20 |
| REDUNDANT | 4 (background_reviewer_loses_the_verdict, check_qex_freshness_before_use, claude_cli_backend_costs_a_full_session, dict_at_boundary_gui) |
| REFERENCE | 2 (agent_hard_budget_is_off_by_default, always_project_venv) |
| STALE | 1 (a_hook_that_writes_a_shared_file_deadlocks_two_writers) |
| STATE | 0 |
| Итого | 135 |

Действия: KEEP 88 (включая 14 выживших групп и 2 REFERENCE), MERGE 27 (23 DUP + 4 RULE в G11), MOVE 16, ARCHIVE 4. Файлов после слияний и архива: 135 - 27 - 4 = 104. Из 104 в 16 RULE-файлов тело заменяется строкой-указателем после переноса правила.

Экономия индекса. В `MEMORY.md` 49 ссылок на мою долю, около 7.5 тыс. знаков из ~21.5 тыс. В `CRAFT.md` 89 ссылок, около 15.4 тыс. знаков. Оставляю в `MEMORY.md` 12 кандидатов (~2 тыс. знаков) плюс общую строку-указатель на `CRAFT.md` по тегам. Экономия `MEMORY.md` от моей доли: около 5.5 тыс. знаков (~10 КБ байт UTF-8 до пересчёта: кириллица 2 байта на знак; точный байтовый счёт не делал). `CRAFT.md` сократится ещё примерно на 4 тыс. знаков за счёт 27 слитых файлов и 4 архивных.

## 6. Что ненадёжно в моей классификации

- Все 135 файлов прочитаны ТОЛЬКО по голове (1000-1500 знаков). Целиком открыл лишь commit_msg_format, git_main_merge_hook_traps, injection_zero_may_mean_the_guards_were_not_collected и a_zero_under_injection_has_three_readings. Поле «унести» в слияниях выведено из описания и первых абзацев; перед слиянием надо открыть оба файла целиком.
- Слияния G3, G5, G8 объединяют разные приёмы одного класса. Для поиска «по механизму» сильнее раздельные файлы с тегами; слияние экономит файлы, но удлиняет выжившего. Что полезнее при поиске, не измерял.
- Kind RULE для принципов владельца (G11) и backend_ctl_for_agents: это решения владельца, не измеренные уроки. Перенос в root CLAUDE.md снижает индекс, но поднимает базовую стоимость CLAUDE.md (+5 строк). Решение за лидом.
- STALE поставлен одному файлу (a_hook_that_writes_a_shared_file...): проверил, что в `.git/hooks/pre-commit` нет кода session-log, плюс запись в `.claude/CLAUDE.md` о снятии хука 2026-10-03. Не проверял, что stash-конфликт невозможен и без хука.
- Сверил `git grep` только ~40 имён. Все дали >0, кроме `_full_router_stats` и `test_thread_deadlines` (вероятно исправлены или переименованы; сами уроки общие, оставил LESSON). Номера строк внутри уроков (state.py:290, logger_core.py:2002, observability_wiring.py:1571) не проверял.
- Для RULE-механизмов проверил только: в project-rules нет правил про model и latest models; qex-правило и правило про фоновых агентов уже есть (project-rules §1, `.claude/CLAUDE.md`). Не проверял, нет ли нужных строк в `.rules/gui.md`, `/dev:ship`, COMMIT_GUIDE кроме Dict at Boundary (подтверждено git grep по `.rules`).
- config_reload_ttl_addressing_guard: оставил LESSON, ценность низкая; кандидат в архив при следующей чистке.
- claude_cli_backend_costs: REDUNDANT, но удалять файл нельзя: root CLAUDE.md ссылается на него как на источник.
- Отчёты R2/R3 не читал: возможны дубли между моими G1, G12, G13, G14 и файлами m-z (zero_*, three_managers_share_base, precommit_stash_collision_2plus_agents, parallel_agents_commit_race, ruff_strips_unused_import).
