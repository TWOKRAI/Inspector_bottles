# CRAFT-verdict — читать, когда: выносишь вердикт ревью или приёмки; пишешь «не может сломаться»; разбираешь живой дефект
Ядро — в [MEMORY.md](MEMORY.md) и в `.claude/CLAUDE.md` «Test authorship»; здесь детали, оплаченные конкретными провалами.
Соседи: [CRAFT-injection](CRAFT-injection.md) · [CRAFT-tests](CRAFT-tests.md) · [CRAFT-config-qt](CRAFT-config-qt.md) · [CRAFT-by-module](CRAFT-by-module.md)

## Канон вердикта
- [Три объектива — три класса](feedback_three_lenses_three_defect_classes.md) — тесты=механика, прогон=проводка, ревью=связки
- [Стенд с вердиктом — тоже оснастка](feedback_a_stand_with_a_verdict_is_also_a_harness.md) — приёмником был наш `http.server`, отвечавший 200 на любой путь; настоящий otelcol дал 404, 102 теста из 214 пинили форму, не доставившую ничего
- [Правдоподобное ≠ проверенное](feedback_plausible_is_not_verified.md) · [вердикт по одному маркеру врёт](feedback_single_marker_verdict_lies.md) — пара маркеров + признак жизни
- [elementsFromPoint не видит псевдоэлементы](feedback_elements_from_point_misses_pseudo_elements.md) — артефакт стенда списан на курсор, рисовал `::details-content` закрытого `<details>`
- [Зонд, гадающий о темпе, говорит «нет» вместо «не знаю»](feedback_a_probe_that_guesses_tempo_says_no_when_it_means_dont_know.md) — пять ложных опровержений подряд на ИСПРАВНОМ механизме: форма, темп, темп, готовность, вакуум; недобор фактов = «не доказано»
- [Subagent live = синхронно](feedback_subagent_live_test_monitor_hang.md)
- [Красный — сперва на main](feedback_check_red_on_main_first.md) · [подпись гейта живёт на HEAD](feedback_gate_signature_lives_on_a_head.md) — коммит после подписи = пере-прогон
- [Два зелёных гейта прячут красную пару](feedback_two_green_gates_can_hide_a_red_pair.md) — уборка сняла ЧУЖОЕ объявление; нарушитель и жертва в разных testpaths, красное только в совмещённом прогоне

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
- [«Главный источник» может быть 3%](feedback_named_main_cause_may_be_a_minor_share.md) — мерь долю до правки
- [Снос оставляет хвост](feedback_removal_leaves_a_tail_in_the_neighbour.md) — дифф не видит · [уборка переживает разрыв](feedback_cleanup_must_survive_abnormal_disconnect.md) — три формы смерти клиента
- [Модалка ждёт клика](feedback_modal_dialog_waits_instead_of_failing.md) — страж BaseException + прогон-разведка
- [PRAGMA молчит об отказе](feedback_sqlite_pragma_fails_silently.md) — порядок до WAL

## Ситуативные
- [Контрол может существовать и быть мёртвым](feedback_a_control_can_exist_and_be_dead.md) — критерий «строка есть» зелен и у холостого тумблера; писать вторым предложением «и его движение меняет ЧИСЛО»
- [Корневой гейт не видит модули фреймворка](project_root_gate_misses_framework_modules.md) — из 82 новых тестов в него попали 6; сверять прирост сбора, гонять ОБА гейта
- [Ручка применена ≠ подтверждена](feedback_a_knob_can_be_applied_and_unverifiable.md) — под-секция без менеджера идёт мимо сверщика: `unverifiable` при `checked=0` = никто не смотрел
- [Переезд с мёртвого пути на живой делает предохранители несущими](feedback_a_budget_belongs_to_a_path_not_to_a_mechanism.md) — Task 3.1: `float(value)` в `NumberRecord` сторожил пустоту, пока у класса не было потребителей; после переезда формы внутрь `append_records` снятый предохранитель уносит ВСЮ пачку (репродукция ревью: `ValueError`, 0 строк вместо 3), а заплата по нему давала 0 красных. При переносе кода с холодной дороги на горячую перепроверять его собственные предохранители заплатами — В МОМЕНТ переноса, а не потом
- [Инвентарный греп обязан быть по литералу](feedback_an_inventory_grep_needs_fixed_strings.md) — точка в паттерне ловит `queue_evicted` вместо `queue.evicted`: счёт завышается молча, а завышение читается как находка. Числа для вердикта — только `grep -F`, ненулевой хит показывать строкой
- [getattr с дефолтом прячет призрачный атрибут](feedback_getattr_default_hides_a_phantom_attribute.md) — читатель с дефолтом молчит о несуществующем поле; проверять, что атрибут объявлен
