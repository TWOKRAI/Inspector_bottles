# CRAFT.md — ремесло: тесты, инъекции, дефекты, конфиг, Qt

**Читать целиком перед тем, как:** писать тесты · планировать инъекции поломок ·
выносить вердикт ревью · объяснять, почему что-то «не может» сломаться ·
править конфиг/схему Pydantic · трогать Qt-виджеты или гонять qt-mcp.
Ядро (что сработает и без чтения) — в [MEMORY.md](MEMORY.md) и в разделе
«Test authorship» проектного `.claude/CLAUDE.md`. Здесь — детализация, оплаченная
конкретными провалами.

## Канон тестирования и инъекции
- [Две заплаты с одинаковым набором красных = один ассерт](feedback_two_patches_one_red_set_means_one_assert.md) — сверять НАБОРЫ попарно, не числа; совпадение значит «у одного свойства сторожа нет»
- [Тест, закрепляющий ДЫРУ, зелен в обе стороны](feedback_a_test_that_pins_a_hole_is_green_both_ways.md) — не покраснел ни на одной заплате = документация, а не сторож; в покрытие не идёт
- [Замер, упёршийся в свой limit, ничего не доказал](feedback_a_measurement_capped_by_its_own_limit_proves_nothing.md) — три разных вызова дали одинаковое число = потолок зонда; сумма частей обязана сходиться с целым, отсутствие ключа — печатать реальный состав
- [Диагностический ответ считается ПОСЛЕДНЕЙ строкой ленты](feedback_a_diagnostic_answer_must_be_computed_last.md) — посчитанный в середине, он судит по состоянию до правки: два одинаковых config.reload дали разные ответы, первый лгал «потолков нет»
- [pytest владеет threading.excepthook на всю сессию](feedback_pytest_owns_threading_excepthook_for_the_session.md) — «прежний хук печатает в stderr» недостижимо под pytest (0 байт против 648); восстанавливать предпосылку в тесте, проброс проверять спаем, детектор — число PytestUnhandledThreadExceptionWarning

- [Три роли авторства](feedback_test_authorship_three_roles.md) — tester от acceptance, ревьюер запуском · [тестер всегда + инъекции против него](feedback_tester_always_and_inject_against_it.md) — его зелёный не результат
- [Три объектива — три класса](feedback_three_lenses_three_defect_classes.md) — тесты=механика, прогон=проводка, ревью=связки
- [Верный ФОРМЕ дублёр неверен ПРОТОКОЛУ](feedback_a_faithful_fake_still_lacks_the_protocol.md) — настоящая дверь pop-ает служебные ключи; чем проще дублёр, тем надёжнее прячет; одно имя, две двери, два симптома
- [Прототипируй страж до фиксации формулировки](feedback_prototype_the_guard_before_fixing_its_wording.md) — «в одной функции» было методом инвентаря и пережило основание: красно по построению, выход только whitelist
- [Ревью ловит стык своих кусков](feedback_review_finds_the_seam_between_own_pieces.md) · [ревью спеки — независимым](feedback_spec_review_needs_independent_agent.md) — автор находит карту, не форму
- [Правдоподобное ≠ проверенное](feedback_plausible_is_not_verified.md) · [вердикт по одному маркеру врёт](feedback_single_marker_verdict_lies.md) — пара маркеров + признак жизни
- [Зонд, гадающий о темпе, говорит «нет» вместо «не знаю»](feedback_a_probe_that_guesses_tempo_says_no_when_it_means_dont_know.md) — пять ложных опровержений подряд на ИСПРАВНОМ механизме: форма, темп, темп, готовность, вакуум; недобор фактов = «не доказано»
- [Subagent live = синхронно](feedback_subagent_live_test_monitor_hang.md)
- [Красный — сперва на main](feedback_check_red_on_main_first.md) · [подпись гейта живёт на HEAD](feedback_gate_signature_lives_on_a_head.md) — коммит после подписи = пере-прогон
- [Два зелёных гейта прячут красную пару](feedback_two_green_gates_can_hide_a_red_pair.md) — уборка сняла ЧУЖОЕ объявление; нарушитель и жертва в разных testpaths, красное только в совмещённом прогоне
- [Инъектировать место ВЫЗОВА, не только тело](feedback_inject_the_call_site_not_only_the_helper.md) — снял единственный боевой вызов: ноль красных из 4297, тридцать сторожей звали хелпер напрямую
- [Процессный дроссель делает соседей вакуумными](feedback_a_process_wide_throttle_turns_neighbours_vacuous.md) — окно голоса на синглтоне: положительная половина пары краснеет, отрицательная остаётся ЗЕЛЁНОЙ, не проверив ничего; тест про голос обязан владеть окном
- [Заплата на лок вешает ВЫХОД, а не тест](feedback_a_lock_patch_can_hang_the_exit_not_the_test.md) — 1 failed за 6 с, потом минуты висения: logging.shutdown на atexit берёт лок застрявшего обработчика; смотреть код выхода и проверять, что харнесс вернул файл
- [emergency_log доезжает до stderr, не до файлов](feedback_emergency_log_reaches_stderr_not_the_log_files.md) — 0 строк в журнале против 2 у вида; caplog для вопроса об АДРЕСЕ фейковый харнесс, нужен тест сквозь настоящий LoggerManager из файла
- [Тест не доказан без красного](feedback_prove_test_red_without_fix.md) — откат stash, счёт арифметикой
- [Неубиваемая правка — ставь состояние руками](feedback_unkillable_fix_needs_a_hand_set_state.md) — правка, недостижимая после соседних правок ТОГО ЖЕ пакета, инъекцией не красит ничего; предсказывать «ноль» честно, а сторожить белым ящиком
- [Снятие лишней работы красит тесты, мерившие её](feedback_removing_waste_reddens_tests_that_measured_it.md) — красный = вопрос «какое свойство сторожил», а не сигнал откатиться; один из них был зелён на свойстве, которого нет
- [deep_merge не ассоциативен](feedback_deep_merge_is_not_associative.md) — 239 расхождений из 20 000; свернуть дельты можно, лишь если ранняя не кладёт скаляр туда, где поздняя кладёт словарь
- [Дублёр глушит имена, которые код ЧИТАЕТ](feedback_a_stub_silences_the_names_it_is_read_for.md) — переименование читаемого имени: 69 тестов зелены; записываемого — все падают. Контракт-тест на имена, включая `self.<имя> =` по иерархии
- [Предсказание — после всех тестов](feedback_predict_injections_after_writing_tests.md) · [на общем корпусе — MUST поимённо](feedback_injection_prediction_on_a_shared_corpus.md) + потолок красных
- [Генератор инъекций ≠ автор критериев](feedback_injection_generator_must_differ_from_criteria_author.md) — инверсии критериев ловятся гарантированно; обязателен второй род «нуль/тотал» от другой головы
- [Отрицательный критерий требует якоря существования](feedback_negative_criterion_needs_an_existence_anchor.md) — «листа нет» удовлетворяется пустотой; выдавать парой «есть литерал / нет»
- [Живой критерий требует боевого триггера](feedback_acceptance_criterion_needs_a_live_trigger.md) — «на стенде видно X» проверять грепом по вызывающим ДО записи в план; нет вызывающего вне teardown — критерий недостижим
- [База инъекций = число собранных](feedback_injection_base_needs_a_collected_count.md) — 0 collected читается как зелено; дочерний логгер не глушит
- [Покрывать ВСЕ точки правила](feedback_injection_must_cover_all_check_sites.md) · [слишком грубая не доказывает](feedback_injection_too_coarse_proves_nothing_specific.md) · [негодная ≠ вакуум](feedback_broken_injection_is_not_a_vacuous_test.md) — ERROR vs FAILED
- [Покрытие на ПРОВЕРКУ ≠ покрытие на утверждение](feedback_coverage_per_check_is_not_coverage_per_claim.md) — у F2-3 было три утверждения и инъекция у одного; ослабь половину — не покраснел бы никто
- [Вырожденное значение — «неизвестно», а не ноль](feedback_a_degenerate_value_is_not_zero_it_is_unknown.md) — heartbeat 0 законен («выключен»), поэтому страж ставится у ПОТРЕБИТЕЛЯ такта, не у источника
- [Откат — восстановлением](feedback_injection_rollback_by_restore_not_replace.md) — обратная замена задевает соседа; эталон протухает от правок ревью · [дубль обязан блокировать](feedback_double_must_block_like_the_original.md)
- [Тест, переживший свой слом](feedback_test_survived_its_own_break.md) — шов сквозь RLock · [ноль красных = лишний слой](feedback_zero_reds_can_mean_a_useless_layer.md)
- [У нуля красных ТРИ чтения](feedback_a_zero_under_injection_has_three_readings.md) — плохая реплика / промах ВЫБОРКИ тестов / незастережённая ветка; спутал (б) с (в) — завёл ложную находку против верного утверждения. Плюс: у одного выхода бывает несколько стражей, тест покрывает лишь тот, до которого доходит
- [Суффиксное переименование слепо](feedback_suffix_rename_is_a_blind_injection.md) — `foo→foo_RENAMED` оставляет старое ПРЕФИКСОМ нового: 74 passed при предсказанных 5 failed. Брать несовпадающее имя; сторожа имён — по границе слова, не подстрокой
- [Краснеет только от ПАРЫ изломов](feedback_test_reddens_only_under_a_paired_injection.md) — сторож композиции ≠ вакуум; несовпавшее предсказание = находка
- [ttl в config.reload отказывает по своей причине](feedback_config_reload_ttl_addressing_guard.md) — throttle-only + ttl ложно-зелёный
- [Константа из физики, а не из замера](feedback_constant_from_domain_physics_not_measured.md) — 99.28 % наблюдений ниже первой границы; инъекции такое не ловят

## Вакуумные тесты и ассерты
- [coverage держит settrace, не setprofile](feedback_coverage_holds_settrace_not_setprofile.md) — под `--cov` `gettrace()` занят CTracer, `getprofile()` пуст: счётчик на setprofile не конфликтует, а `assert gettrace() is None` даёт ложный красный; базу брать СНИМКОМ
- [Readback, собранный руками, оставляет своего производителя без сторожа](feedback_a_handmade_readback_leaves_its_producer_unguarded.md) — 0 красных из 145 при снятой строке readback: все тесты подавали `effective` литералом. Инъекция в производителя — отдельно от инъекции в сверщик
- [Применяющая команда не измеряет то, что переустанавливает](feedback_an_applying_command_cannot_measure_what_it_reapplies.md) — второй `config.reload` подтверждал собственную запись (3.5 != 9.25); живость такта читать ЧИТАЮЩЕЙ дверью, и её надо зарегистрировать в стенде явно
- [Страж-обходчик не видит удалённого элемента](feedback_a_list_walking_guard_cannot_see_a_removed_item.md) — ключ снят из OBSERVABILITY_LOSS_KEYS, обходчик зелен; держит только литерал «ключ в реестре»; в матрице всегда заплатка «элемент удалён»

- [Молчащий детектор](feedback_silent_detector_proves_nothing.md) — сперва покажи красным · [тест, поднимающий ошибку сам](feedback_test_raising_the_error_itself_guards_the_branch.md) — сторожит except
- [Вечно горящий детектор](feedback_detector_comparing_representation_fires_always.md) — сравнение целых dict'ов сравнивает написание, а не смысл; прогони на «ничего не изменилось» и потребуй тишины
- [Ассерт по подстроке](feedback_substring_assert_passes_on_the_wrong_branch.md) — текст+уровень, инъекция в соседнюю ветку · [отсутствие при extra=ignore](feedback_absence_assertion_under_extra_ignore_is_vacuous.md) — model_fields_set
- [Числа рядом с дефолтом](feedback_test_values_near_defaults_test_the_default.md) · [совпадение констант](feedback_coinciding_constants_hide_opposite_implementations.md) — брать где расходятся · [одна функция — две позиции](feedback_one_function_two_positions.md) · [параметр закрывает окно дефекта](feedback_test_params_hide_defect_window.md) — backoff_sec=0.0, adapter=None
- [Дубль фикстуры](feedback_duplicate_fixture_verifies_itself.md) — расходится с conftest молча · [параметризация из испытуемого](feedback_parametrization_built_from_the_subject_collapses_with_it.md)
- [Фальшивка-всегда-успех](feedback_fake_that_always_succeeds_mutes_the_gate.md) — дубль обязан уметь отказывать · [нет получателя — нет суда](feedback_absent_receiver_lets_a_test_pin_an_impossible_input.md)
- [Одиночное чтение](feedback_single_reader_test_misses_multi_reader_defect.md) · [второй потребитель вскрывает](feedback_second_consumer_reveals_the_defect.md) — зелено поодиночке
- [mp.Queue асинхронна](feedback_mp_queue_is_async_in_tests.md) — учёт на queue.Queue · [порог по часам меряет кучу](feedback_wallclock_threshold_measures_the_heap.md) — по времени лечит gc.disable, по ПАМЯТИ он делает хуже; поднять порог можно лишь от разделения с контролем + инъекция
- [Глобальный патч часов = флейк](feedback_global_clock_patch_flake.md) — часы — зависимость объекта
- [Дельта, а не размер](feedback_measure_delta_not_file_size.md) · [счёт строк не ловит петлю](feedback_row_count_never_catches_the_loop.md) — судить серии внутри записи
- [Baseline снят ПОСЛЕ действия](feedback_baseline_taken_after_the_act_proves_nothing.md) — сторож доказывает идемпотентность повтора, а не само действие; заплата в регистрацию дала 0 красных при контроле 10→11 команд. Состав сторожить ЛИТЕРАЛОМ, не разностью
- [Два теста входят с разных концов провода](feedback_two_tests_enter_from_both_sides_and_miss_the_connector.md) — приёмка дренирует источник, авторский пишет в приёмник руками, сам перенос не зовёт никто; 0 красных при контроле «1 строка в сторе → 0». Грепни функцию переноса: только в проде = сторожа нет
- [Тесты-невидимки](feedback_tests_invisible_to_testpaths.md) — судить по конфигу прогона · [выключатель дискриминатора](feedback_discriminator_switch_must_be_verified.md) — счётчик collected
- [Зелёный прогон и синхронность](feedback_green_run_hides_synchronous_only_correctness.md) — замыкание дефолт-аргументом
- [Барьер на входе ≠ гонка](feedback_barrier_at_entry_does_not_reproduce_the_race.md) — рандеву на операцию
- [Транзитивный GUI-backend](feedback_transitive_gui_backend_in_tests.md) — matplotlib+PySide6=qtagg; Agg-страховка

## Предохранители и механизмы

- [Два предохранителя](feedback_two_safeguards_hide_which_one_holds.md) — снимай все кроме проверяемого · [новый страж ослабляет старого](feedback_a_new_guard_can_weaken_an_old_one.md)
- [Правка по находке не шире находки](feedback_a_fix_on_a_finding_must_not_outgrow_it.md) — фильтр «поднят» срезал и processing, сняв тег not_inspected; файл вне поля Files задачи = сигнал выхода за спеку
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
- [Классифицировать лист по РАЗНИЦЕ двух значений](feedback_classify_a_leaf_by_the_difference_of_two_values.md) — один полюс путает «не потребляется» с «равно дефолту» (24 ложных имени); отпечаток ПЕРЕСЕЧЕНИЕМ полюсов, объединение обвиняет нетронутых соседей

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

- [Сравнивать ВАЛИДИРОВАННЫЕ значения, не сырой YAML](feedback_compare_validated_values_not_raw_config.md) — «равно ли дефолту» спрашивают у модели; замер по сырому файлу занижает (4 вместо 5). Пространств имён два: 5 потерь секции = 9 листьев провенанса

## Qt / GUI

- [Qt widget patterns](feedback_widget_qt_patterns.md) — setFlags recursion, blockSignals, EditTriggers
- [qt-mcp smoke+probe](feedback_qt_mcp_smoke_verification.md) — QT_MCP_PROBE=1:9142; чистка по PID · [зонд только с env](reference_qt_mcp_launch.md) · [стенд всегда с зондом](feedback_qt_mcp_always_probe.md) · [флаг сравнивается дословно](feedback_qt_mcp_flag_value_is_compared_verbatim.md) — «1:9142» промолчало, рендер не проверялся 3 раунда
- [Живость зонда ≠ рендер](feedback_probe_liveness_is_not_render.md) — окно «невидимо»; snapshot=0 виджетов; кадр только ref-грабом
- [GUI-save сносит yaml-комменты](feedback_gui_save_strips_yaml_comments.md) — git diff перед add
- [Инъекция зелёная, когда подмена совпала с фактом](feedback_injection_green_when_the_substitute_equals_the_fact.md) — «зашить константу» ничего не сторожит, пока нет фикстуры с ТРЕТЬИМ значением
- [Критерий, где тест сам преобразует](feedback_a_criterion_that_transforms_observes_the_library.md) — наблюдает библиотеку, неисполним ничем; чинить швом, не подгонкой
- [Зонд обязан перечислить до того, как спросит](feedback_a_probe_must_enumerate_before_it_asks.md) — пустой ответ про несуществующее имя = «ничего нет»
- [Вторую половину пары мог сделать таймер](feedback_the_off_half_of_a_pair_can_be_done_by_a_timer.md) — success подтверждает доставку, не причину; атрибуцию доказывать журналом адресата
- [Выключил писателя — заглушка стала утверждением](feedback_switching_off_a_writer_promotes_its_placeholder_to_a_claim.md) — посев 0.0 при погашенной публикации = уверенное враньё; семь ложных аномалий
- [Дублёры подают конфиг плоским](feedback_fakes_feed_config_flat_so_key_address_defects_are_invisible.md) — класс «ключ по неверному адресу» тестам структурно невидим; нужен тест на настоящем ProcessConfigHandler
- [Решение осиротило то, что кодировало прежнее](feedback_a_decision_orphans_what_encoded_the_previous_one.md) — одна правка конфига дала ТРИ протухших артефакта; корневой гейт был красен две недели
- [Критерий гейта спорит с решением владельца](feedback_gate_criterion_can_contradict_an_owner_decision.md) — три класса провалов, у каждого свой адресат; третий кодом не чинится
- [Контрол воспроизводит дефект, который заведён ловить](feedback_a_control_reproduces_the_defect_it_was_built_to_catch.md) — «значение успеха, не зависящее от факта» трижды за фазу на трёх этажах; новому счётчику задавать ТОТ ЖЕ вопрос, что убил старый
- [Правило избегания может быть ложным предохранителем](feedback_an_avoidance_rule_can_be_a_false_safety_catch.md) — «не гонять два модуля вместе» неверно: гейт держит их в одном процессе и зелен; 20 красных даёт «эти два БЕЗ остального дерева»
- [Общий дроссель роняет запись, а не голос](feedback_a_shared_throttle_swallows_the_record_not_the_line.md) — `_safe_track` внутри `if should_log`: плоскость не получает НИ трассы, ни полей; «зато счётчик считает все» компенсирует только число. Каноничная дорога — ErrorManager, у неё окна нет
- [Сторож ниже заявления охраняет слой, а не заявление](feedback_a_guard_below_the_claim_guards_the_layer_not_the_claim.md) — читал источник напрямую при заявлении «видно в readback»; снятие публикации не убило НИ одного теста из 350; инъекция обязана ломать дорогу, а не только вычисление
- [Маркер дедупа — утверждение о ЧУЖОМ поведении](feedback_a_dedup_marker_is_an_assertion_about_someone_else.md) — ставился безусловно; без адресата промолчали ОБА и инцидент исчез (1 строка → 0). Ловится числом строк, не наличием маркера. Контрольный вопрос: есть ли конфигурация, где промолчали все?


## Перенесено из ядра MEMORY.md 2026-09-05 (сжатие индекса)

Ситуативные записи ядра «Ремесло»: до этого дня индекс был их единственным указателем. Строки дословные.

- [numba без boundscheck: сломанный инвариант = UB, а не красный](feedback_numba_without_boundscheck_turns_a_broken_invariant_into_ub.md) — инъекция дала 104 зелёных и крах 0xC0000374 в соседнем процессе; ядра с буферами по инварианту только под boundscheck=True + явная сверка
- [Проходной блок — не развилка](feedback_a_pass_through_block_is_not_a_fork.md) — тело try/with/цикла продолжает ветку; ошибка модели даёт ТИХИЙ ложный зелёный, обратная (match/except*) — ложный красный без выхода
- [Один владелец ослепляет тест общего состояния](feedback_one_owner_blinds_the_shared_state_test.md) — после переезда «всё через порт» П1/П4 зелены и при приватной копии; держал контракт единственный читатель МИМО владельца
- [Скриптовая заплатка требует уникального якоря](feedback_scripted_patch_needs_a_unique_anchor.md) — `count == 1`, иначе режет соседнюю функцию молча; поймал только гейт фреймворка из трёх
- [Инъекция смотрит ДРУГИМ объективом, чем тест](feedback_injection_must_use_a_different_lens_than_the_test.md) — совпали точки наблюдения (payload/дерево) → красный доказывает согласие двух копий одной модели
- [Неподключённый драйвер = ровный ноль](feedback_unconnected_driver_reads_as_a_clean_zero.md) — подтверждающий ноль засчитывать только в паре с контролем, дающим ненулевое
- [«Сверено» отвечает за вызов, не за охват](feedback_checked_true_answers_for_the_call_not_the_coverage.md) — checked=true с пустым списком: сверщик пропускал класс входа, троттл резал в 40 раз
- [Контрол может существовать и быть мёртвым](feedback_a_control_can_exist_and_be_dead.md) — критерий «строка есть» зелен и у холостого тумблера; писать вторым предложением «и его движение меняет ЧИСЛО»
- [Корневой гейт не видит модули фреймворка](project_root_gate_misses_framework_modules.md) — из 82 новых тестов в него попали 6; сверять прирост сбора, гонять ОБА гейта
- [Ручка применена ≠ подтверждена](feedback_a_knob_can_be_applied_and_unverifiable.md) — под-секция без менеджера идёт мимо сверщика: `unverifiable` при `checked=0` = никто не смотрел
- [Инъекция воспроизводит МЕХАНИЗМ, не форму](feedback_injection_must_reproduce_the_mechanism_not_the_shape.md) — реплика дефекта по форме может не ломать ничего (PEP 570); ноль красных проверять руками
- [Общее дерево делает инъекции флейками](feedback_shared_tree_makes_injections_look_like_flakes.md) — патчи и чужие прогоны в одном дереве врут обеим сторонам; только разные worktree
- Уже были в CRAFT.md, из ядра индекса сняты как дубли: [Фасад — белый список](feedback_facade_is_a_whitelist_not_a_passthrough.md) · [model_copy не валидирует](feedback_model_copy_does_not_validate.md) · [Живость зонда ≠ рендер](feedback_probe_liveness_is_not_render.md) · [флаг сравнивается дословно](feedback_qt_mcp_flag_value_is_compared_verbatim.md)
- [Переезд с мёртвого пути на живой делает предохранители несущими](feedback_a_budget_belongs_to_a_path_not_to_a_mechanism.md) — Task 3.1: `float(value)` в `NumberRecord` сторожил пустоту, пока у класса не было потребителей; после переезда формы внутрь `append_records` снятый предохранитель уносит ВСЮ пачку (репродукция ревью: `ValueError`, 0 строк вместо 3), а заплата по нему давала 0 красных. При переносе кода с холодной дороги на горячую перепроверять его собственные предохранители заплатами — В МОМЕНТ переноса, а не потом
- [Инвентарный греп обязан быть по литералу](feedback_an_inventory_grep_needs_fixed_strings.md) — точка в паттерне ловит `queue_evicted` вместо `queue.evicted`: счёт завышается молча, а завышение читается как находка. Числа для вердикта — только `grep -F`, ненулевой хит показывать строкой
