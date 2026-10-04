# CRAFT-injection — читать, когда: планируешь инъекции; видишь «0 красных» или «зелёный под заплатой»; пишешь вакуумный ассерт или негатив
Ядро — в [MEMORY.md](MEMORY.md) и в `.claude/CLAUDE.md` «Test authorship»; здесь детали, оплаченные конкретными провалами.
Соседи: [CRAFT-tests](CRAFT-tests.md) · [CRAFT-verdict](CRAFT-verdict.md) · [CRAFT-config-qt](CRAFT-config-qt.md) · [CRAFT-by-module](CRAFT-by-module.md)

## Инъекции
- [Инъектировать место ВЫЗОВА, не только тело](feedback_inject_the_call_site_not_only_the_helper.md) — снял единственный боевой вызов: ноль красных из 4297, тридцать сторожей звали хелпер напрямую
- [Заплата на лок вешает ВЫХОД, а не тест](feedback_test_survived_its_own_break.md) — 1 failed за 6 с, потом минуты висения: logging.shutdown на atexit берёт лок застрявшего обработчика; смотреть код выхода и проверять, что харнесс вернул файл
- [Неубиваемая правка — ставь состояние руками](feedback_unkillable_fix_needs_a_hand_set_state.md) — правка, недостижимая после соседних правок ТОГО ЖЕ пакета, инъекцией не красит ничего; предсказывать «ноль» честно, а сторожить белым ящиком
- [Предсказание — после всех тестов](feedback_predict_injections_after_writing_tests.md) · [на общем корпусе — MUST поимённо](feedback_injection_prediction_on_a_shared_corpus.md) + потолок красных
- [Генератор инъекций ≠ автор критериев](feedback_injection_generator_must_differ_from_criteria_author.md) — инверсии критериев ловятся гарантированно; обязателен второй род «нуль/тотал» от другой головы
- [Покрывать ВСЕ точки правила](feedback_injection_must_cover_all_check_sites.md) · [слишком грубая не доказывает](feedback_injection_too_coarse_proves_nothing_specific.md) · [негодная ≠ вакуум](feedback_injection_zero_may_mean_the_guards_were_not_collected.md) — ERROR vs FAILED
- [Тест, переживший свой слом](feedback_test_survived_its_own_break.md) — шов сквозь RLock · [ноль красных = лишний слой](feedback_injection_zero_may_mean_the_guards_were_not_collected.md)
- [Суффиксное переименование слепо](feedback_suffix_rename_is_a_blind_injection.md) — `foo→foo_RENAMED` оставляет старое ПРЕФИКСОМ нового: 74 passed при предсказанных 5 failed. Брать несовпадающее имя; сторожа имён — по границе слова, не подстрокой
- [Краснеет только от ПАРЫ изломов](feedback_test_reddens_only_under_a_paired_injection.md) — сторож композиции ≠ вакуум; несовпавшее предсказание = находка

## Вакуумные тесты и ассерты
- [coverage держит settrace, не setprofile](feedback_coverage_holds_settrace_not_setprofile.md) — под `--cov` `gettrace()` занят CTracer, `getprofile()` пуст: счётчик на setprofile не конфликтует, а `assert gettrace() is None` даёт ложный красный; базу брать СНИМКОМ
- [Readback, собранный руками, оставляет своего производителя без сторожа](feedback_a_handmade_readback_leaves_its_producer_unguarded.md) — 0 красных из 145 при снятой строке readback: все тесты подавали `effective` литералом. Инъекция в производителя — отдельно от инъекции в сверщик
- [Применяющая команда не измеряет то, что переустанавливает](feedback_an_applying_command_cannot_measure_what_it_reapplies.md) — второй `config.reload` подтверждал собственную запись (3.5 != 9.25); живость такта читать ЧИТАЮЩЕЙ дверью, и её надо зарегистрировать в стенде явно
- [Молчащий детектор](feedback_zero_observations_looks_like_a_result.md) — сперва покажи красным · [тест, поднимающий ошибку сам](feedback_test_raising_the_error_itself_guards_the_branch.md) — сторожит except
- [Вечно горящий детектор](feedback_detector_comparing_representation_fires_always.md) — сравнение целых dict'ов сравнивает написание, а не смысл; прогони на «ничего не изменилось» и потребуй тишины
- [Ассерт по подстроке](feedback_substring_assert_passes_on_the_wrong_branch.md) — текст+уровень, инъекция в соседнюю ветку · [отсутствие при extra=ignore](feedback_an_absence_assertion_needs_a_reachability_check.md) — model_fields_set
- [Числа рядом с дефолтом](feedback_test_params_hide_defect_window.md) · [совпадение констант](feedback_coinciding_constants_hide_opposite_implementations.md) — брать где расходятся · [одна функция — две позиции](feedback_one_function_two_positions.md) · [параметр закрывает окно дефекта](feedback_test_params_hide_defect_window.md) — backoff_sec=0.0, adapter=None
- [Дубль фикстуры](feedback_duplicate_fixture_verifies_itself.md) — расходится с conftest молча · [параметризация из испытуемого](feedback_a_guard_that_counts_at_least_once_is_blind.md)
- [Фальшивка-всегда-успех](feedback_a_faithful_fake_still_lacks_the_protocol.md) — дубль обязан уметь отказывать · [нет получателя — нет суда](feedback_absent_receiver_lets_a_test_pin_an_impossible_input.md)
- [Одиночное чтение](feedback_single_reader_test_misses_multi_reader_defect.md) · [второй потребитель вскрывает](feedback_second_consumer_reveals_the_defect.md) — зелено поодиночке
- [mp.Queue асинхронна](feedback_mp_queue_is_async_in_tests.md) — учёт на queue.Queue · [порог по часам меряет кучу](feedback_wallclock_threshold_measures_the_heap.md) — по времени лечит gc.disable, по ПАМЯТИ он делает хуже; поднять порог можно лишь от разделения с контролем + инъекция
- [Глобальный патч часов = флейк](feedback_global_clock_patch_flake.md) — часы — зависимость объекта
- [Дельта, а не размер](feedback_measure_delta_not_file_size.md) · [счёт строк не ловит петлю](feedback_row_count_never_catches_the_loop.md) — судить серии внутри записи
- [Baseline снят ПОСЛЕ действия](feedback_baseline_taken_after_the_act_proves_nothing.md) — сторож доказывает идемпотентность повтора, а не само действие; заплата в регистрацию дала 0 красных при контроле 10→11 команд. Состав сторожить ЛИТЕРАЛОМ, не разностью
- [Два теста входят с разных концов провода](feedback_two_tests_enter_from_both_sides_and_miss_the_connector.md) — приёмка дренирует источник, авторский пишет в приёмник руками, сам перенос не зовёт никто; 0 красных при контроле «1 строка в сторе → 0». Грепни функцию переноса: только в проде = сторожа нет
- [Тесты-невидимки](feedback_zone_guard_never_closes_the_class.md) — судить по конфигу прогона · [выключатель дискриминатора](feedback_discriminator_switch_must_be_verified.md) — счётчик collected
- [Зелёный прогон и синхронность](feedback_green_run_hides_synchronous_only_correctness.md) — замыкание дефолт-аргументом
- [Барьер на входе ≠ гонка](feedback_barrier_at_entry_does_not_reproduce_the_race.md) — рандеву на операцию
- [Транзитивный GUI-backend](feedback_transitive_gui_backend_in_tests.md) — matplotlib+PySide6=qtagg; Agg-страховка

## Ситуативные
- [numba без boundscheck: сломанный инвариант = UB, а не красный](feedback_numba_without_boundscheck_turns_a_broken_invariant_into_ub.md) — инъекция дала 104 зелёных и крах 0xC0000374 в соседнем процессе; ядра с буферами по инварианту только под boundscheck=True + явная сверка
- [Скриптовая заплатка требует уникального якоря](feedback_scripted_patch_needs_a_unique_anchor.md) — `count == 1`, иначе режет соседнюю функцию молча; поймал только гейт фреймворка из трёх
- [Инъекция смотрит ДРУГИМ объективом, чем тест](feedback_injection_must_use_a_different_lens_than_the_test.md) — совпали точки наблюдения (payload/дерево) → красный доказывает согласие двух копий одной модели
- [Неподключённый драйвер = ровный ноль](feedback_unconnected_driver_reads_as_a_clean_zero.md) — подтверждающий ноль засчитывать только в паре с контролем, дающим ненулевое
- [Инъекция воспроизводит МЕХАНИЗМ, не форму](feedback_injection_must_reproduce_the_mechanism_not_the_shape.md) — реплика дефекта по форме может не ломать ничего (PEP 570); ноль красных проверять руками
