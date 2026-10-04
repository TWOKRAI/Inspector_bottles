# CRAFT-tests — читать, когда: пишешь тест, дублёр, фикстуру, сторожа; гейт зелёный подозрительно
Ядро — в [MEMORY.md](MEMORY.md) и в `.claude/CLAUDE.md` «Test authorship»; здесь детали, оплаченные конкретными провалами.
Соседи: [CRAFT-injection](CRAFT-injection.md) · [CRAFT-verdict](CRAFT-verdict.md) · [CRAFT-config-qt](CRAFT-config-qt.md) · [CRAFT-by-module](CRAFT-by-module.md)

## Канон тестов
- [Две заплаты с одинаковым набором красных = один ассерт](feedback_two_patches_one_red_set_means_one_assert.md) — сверять НАБОРЫ попарно, не числа; совпадение значит «у одного свойства сторожа нет»
- [Тест, закрепляющий ДЫРУ, зелен в обе стороны](feedback_a_test_that_pins_a_hole_is_green_both_ways.md) — не покраснел ни на одной заплате = документация, а не сторож; в покрытие не идёт
- [Замер, упёршийся в свой limit, ничего не доказал](feedback_a_measurement_capped_by_its_own_limit_proves_nothing.md) — три разных вызова дали одинаковое число = потолок зонда; сумма частей обязана сходиться с целым, отсутствие ключа — печатать реальный состав
- [Диагностический ответ считается ПОСЛЕДНЕЙ строкой ленты](feedback_a_diagnostic_answer_must_be_computed_last.md) — посчитанный в середине, он судит по состоянию до правки: два одинаковых config.reload дали разные ответы, первый лгал «потолков нет»
- [pytest владеет threading.excepthook на всю сессию](feedback_pytest_owns_threading_excepthook_for_the_session.md) — «прежний хук печатает в stderr» недостижимо под pytest (0 байт против 648); восстанавливать предпосылку в тесте, проброс проверять спаем, детектор — число PytestUnhandledThreadExceptionWarning
- [Верный ФОРМЕ дублёр неверен ПРОТОКОЛУ](feedback_a_faithful_fake_still_lacks_the_protocol.md) — настоящая дверь pop-ает служебные ключи; чем проще дублёр, тем надёжнее прячет; одно имя, две двери, два симптома
- [Прототипируй страж до фиксации формулировки](feedback_prototype_the_guard_before_fixing_its_wording.md) — «в одной функции» было методом инвентаря и пережило основание: красно по построению, выход только whitelist
- [Процессный дроссель делает соседей вакуумными](feedback_a_process_wide_throttle_turns_neighbours_vacuous.md) — окно голоса на синглтоне: положительная половина пары краснеет, отрицательная остаётся ЗЕЛЁНОЙ, не проверив ничего; тест про голос обязан владеть окном
- [emergency_log доезжает до stderr, не до файлов](feedback_emergency_log_reaches_stderr_not_the_log_files.md) — 0 строк в журнале против 2 у вида; caplog для вопроса об АДРЕСЕ фейковый харнесс, нужен тест сквозь настоящий LoggerManager из файла
- [Снятие лишней работы красит тесты, мерившие её](feedback_removing_waste_reddens_tests_that_measured_it.md) — красный = вопрос «какое свойство сторожил», а не сигнал откатиться; один из них был зелён на свойстве, которого нет
- [deep_merge не ассоциативен](feedback_deep_merge_is_not_associative.md) — 239 расхождений из 20 000; свернуть дельты можно, лишь если ранняя не кладёт скаляр туда, где поздняя кладёт словарь
- [Отрицательный критерий требует якоря существования](feedback_negative_criterion_needs_an_existence_anchor.md) — «листа нет» удовлетворяется пустотой; выдавать парой «есть литерал / нет»
- [Живой критерий требует боевого триггера](feedback_acceptance_criterion_needs_a_live_trigger.md) — «на стенде видно X» проверять грепом по вызывающим ДО записи в план; нет вызывающего вне teardown — критерий недостижим
- [Вырожденное значение — «неизвестно», а не ноль](feedback_a_degenerate_value_is_not_zero_it_is_unknown.md) — heartbeat 0 законен («выключен»), поэтому страж ставится у ПОТРЕБИТЕЛЯ такта, не у источника
- [ttl в config.reload отказывает по своей причине](feedback_config_reload_ttl_addressing_guard.md) — throttle-only + ttl ложно-зелёный
- [Константа из физики, а не из замера](feedback_constant_from_domain_physics_not_measured.md) — 99.28 % наблюдений ниже первой границы; инъекции такое не ловят

## Предохранители и механизмы
- [Два предохранителя](feedback_test_reddens_only_under_a_paired_injection.md) — снимай все кроме проверяемого · [новый страж ослабляет старого](feedback_a_new_guard_can_weaken_an_old_one.md)
- [Правка по находке не шире находки](feedback_a_fix_on_a_finding_must_not_outgrow_it.md) — фильтр «поднят» срезал и processing, сняв тег not_inspected; файл вне поля Files задачи = сигнал выхода за спеку
- [Защита достижима](feedback_guard_must_be_reachable.md) — TypeError раньше защиты · [защита базы мертва у наследника](feedback_base_guard_dead_in_heir.md) — config=None обходит
- [Страж существования ≠ содержимого](feedback_zone_guard_never_closes_the_class.md) — ложь прожила 3 месяца · [зонный страж не закрывает класс](feedback_zone_guard_never_closes_the_class.md) — реестр исключений
- [Порог-сумма прячет слепоту](feedback_a_guard_that_counts_at_least_once_is_blind.md) — судить поимённо · [процессный счётчик — не по ключу](feedback_process_counter_is_not_per_key.md) — атрибуция эмитентом
- [Предохранитель-НЕ-операция](feedback_safeguard_can_be_a_noop_with_green_units.md) · [названный механизм — не обязательство](feedback_named_mechanism_is_not_a_commitment.md) — проверка отказом · [докстринг vs регистрация](feedback_docs_assert_what_registration_never_set.md)
- [Сверка копий не видит оригинал](feedback_mirror_check_never_reads_the_original.md) — читать из источника · [«упоминаний = 0» стирает причину](feedback_zero_mentions_criterion_erases_the_reason.md)
- [Защищать единицу конкуренции](feedback_protect_the_unit_of_contention.md) · [шов при ПОЛНОМ отпускании](feedback_test_survived_its_own_break.md) — RLock: счёт глубины
- [Алиас держит объект](feedback_alias_keeps_the_object_alive.md) — владение единственному · [поток в target держит владельца](feedback_thread_target_pins_its_owner.md) — 23 утечки, AV прекратился
- [Цена хука на горячем пути](feedback_hot_path_hook_must_be_priced.md) — дельтой против цены эмиссии; «только чтение» ≠ дёшево (11→56 мс), контроль — сосед на старом коде
- [Кэш прячет однократность](feedback_cache_hides_the_once_only_property.md) — варьировать по ключу кэша
- [Симметрия имён при разных периодах](feedback_symmetric_names_with_different_periods.md) — хуже названной асимметрии; читается неверно молча

## Ситуативные
- [Проходной блок — не развилка](feedback_a_pass_through_block_is_not_a_fork.md) — тело try/with/цикла продолжает ветку; ошибка модели даёт ТИХИЙ ложный зелёный, обратная (match/except*) — ложный красный без выхода
- [Один владелец ослепляет тест общего состояния](feedback_one_owner_blinds_the_shared_state_test.md) — после переезда «всё через порт» П1/П4 зелены и при приватной копии; держал контракт единственный читатель МИМО владельца
- [Тест — через дверь, которой пользуется боевой вызывающий](feedback_test_the_door_the_production_caller_uses.md) — тест, входящий другой дверью, зелен при мёртвой боевой дороге
