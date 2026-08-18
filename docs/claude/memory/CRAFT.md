# CRAFT.md — ремесло: тесты, инъекции, дефекты, конфиг, Qt

**Читать целиком перед тем, как:** писать тесты · планировать инъекции поломок ·
выносить вердикт ревью · объяснять, почему что-то «не может» сломаться ·
править конфиг/схему Pydantic · трогать Qt-виджеты или гонять qt-mcp.
Ядро (что сработает и без чтения) — в [MEMORY.md](MEMORY.md) и в разделе
«Test authorship» проектного `.claude/CLAUDE.md`. Здесь — детализация, оплаченная
конкретными провалами.

## Канон тестирования и инъекции

- [Три роли авторства](feedback_test_authorship_three_roles.md) — tester от acceptance, ревьюер запуском · [тестер всегда + инъекции против него](feedback_tester_always_and_inject_against_it.md) — его зелёный не результат
- [Три объектива — три класса](feedback_three_lenses_three_defect_classes.md) — тесты=механика, прогон=проводка, ревью=связки
- [Ревью ловит стык своих кусков](feedback_review_finds_the_seam_between_own_pieces.md) · [ревью спеки — независимым](feedback_spec_review_needs_independent_agent.md) — автор находит карту, не форму
- [Правдоподобное ≠ проверенное](feedback_plausible_is_not_verified.md) · [вердикт по одному маркеру врёт](feedback_single_marker_verdict_lies.md) — пара маркеров + признак жизни
- [Subagent live = синхронно](feedback_subagent_live_test_monitor_hang.md)
- [Красный — сперва на main](feedback_check_red_on_main_first.md) · [подпись гейта живёт на HEAD](feedback_gate_signature_lives_on_a_head.md) — коммит после подписи = пере-прогон
- [Тест не доказан без красного](feedback_prove_test_red_without_fix.md) — откат stash, счёт арифметикой
- [Снятие лишней работы красит тесты, мерившие её](feedback_removing_waste_reddens_tests_that_measured_it.md) — красный = вопрос «какое свойство сторожил», а не сигнал откатиться; один из них был зелён на свойстве, которого нет
- [deep_merge не ассоциативен](feedback_deep_merge_is_not_associative.md) — 239 расхождений из 20 000; свернуть дельты можно, лишь если ранняя не кладёт скаляр туда, где поздняя кладёт словарь
- [Предсказание — после всех тестов](feedback_predict_injections_after_writing_tests.md) · [на общем корпусе — MUST поимённо](feedback_injection_prediction_on_a_shared_corpus.md) + потолок красных
- [База инъекций = число собранных](feedback_injection_base_needs_a_collected_count.md) — 0 collected читается как зелено; дочерний логгер не глушит
- [Покрывать ВСЕ точки правила](feedback_injection_must_cover_all_check_sites.md) · [слишком грубая не доказывает](feedback_injection_too_coarse_proves_nothing_specific.md) · [негодная ≠ вакуум](feedback_broken_injection_is_not_a_vacuous_test.md) — ERROR vs FAILED
- [Откат — восстановлением](feedback_injection_rollback_by_restore_not_replace.md) — обратная замена задевает соседа; эталон протухает от правок ревью · [дубль обязан блокировать](feedback_double_must_block_like_the_original.md)
- [Тест, переживший свой слом](feedback_test_survived_its_own_break.md) — шов сквозь RLock · [ноль красных = лишний слой](feedback_zero_reds_can_mean_a_useless_layer.md)
- [Краснеет только от ПАРЫ изломов](feedback_test_reddens_only_under_a_paired_injection.md) — сторож композиции ≠ вакуум; несовпавшее предсказание = находка
- [ttl в config.reload отказывает по своей причине](feedback_config_reload_ttl_addressing_guard.md) — throttle-only + ttl ложно-зелёный
- [Константа из физики, а не из замера](feedback_constant_from_domain_physics_not_measured.md) — 99.28 % наблюдений ниже первой границы; инъекции такое не ловят

## Вакуумные тесты и ассерты

- [Молчащий детектор](feedback_silent_detector_proves_nothing.md) — сперва покажи красным · [тест, поднимающий ошибку сам](feedback_test_raising_the_error_itself_guards_the_branch.md) — сторожит except
- [Ассерт по подстроке](feedback_substring_assert_passes_on_the_wrong_branch.md) — текст+уровень, инъекция в соседнюю ветку · [отсутствие при extra=ignore](feedback_absence_assertion_under_extra_ignore_is_vacuous.md) — model_fields_set
- [Числа рядом с дефолтом](feedback_test_values_near_defaults_test_the_default.md) · [совпадение констант](feedback_coinciding_constants_hide_opposite_implementations.md) — брать где расходятся · [одна функция — две позиции](feedback_one_function_two_positions.md) · [параметр закрывает окно дефекта](feedback_test_params_hide_defect_window.md) — backoff_sec=0.0, adapter=None
- [Дубль фикстуры](feedback_duplicate_fixture_verifies_itself.md) — расходится с conftest молча · [параметризация из испытуемого](feedback_parametrization_built_from_the_subject_collapses_with_it.md)
- [Фальшивка-всегда-успех](feedback_fake_that_always_succeeds_mutes_the_gate.md) — дубль обязан уметь отказывать · [нет получателя — нет суда](feedback_absent_receiver_lets_a_test_pin_an_impossible_input.md)
- [Одиночное чтение](feedback_single_reader_test_misses_multi_reader_defect.md) · [второй потребитель вскрывает](feedback_second_consumer_reveals_the_defect.md) — зелено поодиночке
- [mp.Queue асинхронна](feedback_mp_queue_is_async_in_tests.md) — учёт на queue.Queue · [порог по часам меряет кучу](feedback_wallclock_threshold_measures_the_heap.md) — по времени лечит gc.disable, по ПАМЯТИ он делает хуже; поднять порог можно лишь от разделения с контролем + инъекция
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
- [Цена хука на горячем пути](feedback_hot_path_hook_must_be_priced.md) — дельтой против цены эмиссии; «только чтение» ≠ дёшево (11→56 мс), контроль — сосед на старом коде
- [Кэш прячет однократность](feedback_cache_hides_the_once_only_property.md) — варьировать по ключу кэша
- [Симметрия имён при разных периодах](feedback_symmetric_names_with_different_periods.md) — хуже названной асимметрии; читается неверно молча

## Классы дефектов (живьём)

- [«Проглоченный сбой»](feedback_swallowed_failure_class.md) — следствие без причины хуже отсутствия · [тревога ↔ тихая потеря](feedback_false_alarm_traded_for_silent_loss.md) — тестируй ПОСЛЕДОВАТЕЛЬНОСТЬ
- [drop_oldest отвечает success](feedback_drop_oldest_reports_success.md) — потеря видна счётчиком, не статусом
- [Побочный эффект и транзакция](feedback_side_effect_must_not_undo_the_transaction.md) — раздача в своём try · [отказ после записи травит соседа](feedback_refusal_after_the_write_poisons_the_neighbour.md)
- [«Готов» означал меньше](feedback_ready_signal_meant_less_than_read.md) — окно до регистрации · [идемпотентность ≠ монотонность](feedback_idempotent_is_not_monotonic.md) — признак свежести
- [Штамп чтения ≠ свежесть чисел](feedback_read_timestamp_is_not_data_freshness.md) — замерший датчик: числа те же, ts растёт; проверка — остановить источник и опросить дважды
- [Закрытый гейт обнуляет ДЕЛЬТЫ, не сообщения](feedback_gate_off_zeroes_deltas_not_messages.md) — always-on поля идут мимо гейта; мерить state.changed по путям
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

## Qt / GUI

- [Qt widget patterns](feedback_widget_qt_patterns.md) — setFlags recursion, blockSignals, EditTriggers
- [qt-mcp smoke+probe](feedback_qt_mcp_smoke_verification.md) — QT_MCP_PROBE=1:9142; чистка по PID · [зонд только с env](reference_qt_mcp_launch.md) · [стенд всегда с зондом](feedback_qt_mcp_always_probe.md) · [флаг сравнивается дословно](feedback_qt_mcp_flag_value_is_compared_verbatim.md) — «1:9142» промолчало, рендер не проверялся 3 раунда
- [Живость зонда ≠ рендер](feedback_probe_liveness_is_not_render.md) — окно «невидимо»; snapshot=0 виджетов; кадр только ref-грабом
- [GUI-save сносит yaml-комменты](feedback_gui_save_strips_yaml_comments.md) — git diff перед add
- [Инъекция зелёная, когда подмена совпала с фактом](feedback_injection_green_when_the_substitute_equals_the_fact.md) — «зашить константу» ничего не сторожит, пока нет фикстуры с ТРЕТЬИМ значением
