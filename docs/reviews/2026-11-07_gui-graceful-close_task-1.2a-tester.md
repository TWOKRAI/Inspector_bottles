# gui-graceful-close, задача 1.2a: отчёт слепого tester (стадия 1)

Дерево: `.claude/worktrees/op-1.2a-tester` (коммит 1df9a4164, без правок кода). Ничего не закоммичено.
Файл тестов: `multiprocess_framework/modules/process_manager_module/tests/test_supervision_status_system_stop.py`.
Эталонная реализация и запуск инъекций (вне репозитория): `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/e2edcaee-7aad-4901-9110-64aff4d27ddb/scratchpad/ref_impl.py` и `run_ref.sh`.
memory hits: поиск по памяти не запускался.

## 1. Список тестов (17 функций, 34 случая)

Два стенда. «Лёгкий» — PM через `__new__`, настоящий `_ChildrenStop`, двойники группы, монитора, исполнителя и стора. «Живой» — `Rig` из `test_pm_responsive_during_children_stop.py` (настоящие PM, SRM, `StateStoreManager`/`TreeStore`, `ProcessRegistry.children_stop`); команды идут конвертом `build_system_command_message(...)` в `_handle_process_command`.

| Тест | Случаи | Стенд | Критерий |
|---|---|---|---|
| S1 `test_no_stop_gives_null` | bare-new-pm, light-rig, live-rig | оба | A |
| (страж) `test_per_process_fields_unchanged_by_system_stop_field` | 1 | `__new__` | A (поля процесса прежние) |
| S2 `test_shutdown_command_records_initiator_from_real_sender` | gui, backend_ctl | живой | B |
| S2b `test_no_sender_or_direct_command_gives_unknown` | конверт без sender, прямой send_command в очередь, прямой вызов метода | живой | B |
| S2c `test_second_graceful_during_stop_changes_nothing` | 1 | живой | B (первый выигрывает) |
| S2d `test_bad_args_do_not_start_stop` | mode-x, deadline 0.05, deadline 5.1 | лёгкий | B |
| S2e `test_stop_state_fields_at_start` | 1 | лёгкий | A, B (шесть ключей, phase=children, время) |
| S3 `test_event_only_stop_reports_initiator_event` | before-request-stop, after-request-stop | лёгкий | D |
| S4 `test_deadline_at_graceful_and_force` | 8 (graceful: бюджет 5.0 и 8.0, graceful с лишним deadline_s; force: 0.5, 3.0 при бюджете 8.0, границы 0.1 и 5.0, без deadline_s) | лёгкий | C |
| S5 `test_force_escalates_mode_and_deadline_keeps_started_and_initiator` | 1 | живой | C |
| S6 `test_state_store_gets_five_deltas_for_graceful_stop` | 1 | живой | G |
| S6a `test_force_over_graceful_adds_one_mode_delta` | 1 | живой | G (шестая запись `mode=force`) |
| S6b `test_store_failure_or_missing_store_does_not_break_shutdown` | raises, none | лёгкий | G |
| S7 `test_phase_children_announced_before_lifecycle_executor_stops` | 1 | лёгкий | E |
| S8 `test_done_phase_set_before_message_processor_and_state_store_close` | child-exits-in-time, child-needs-terminate | живой | F |
| S8b `test_force_after_done_changes_nothing_and_publishes_nothing` | 1 | лёгкий | F |
| S8c `test_close_with_survivors_sets_done` | 1 | лёгкий | F (выжившие) |

Сверх списка брифа (8 тестов) добавлено 9 функций: каждая закрывает строку критерия, которой в брифе нет отдельного теста. Такие тесты помечены S2b-S2e, S6a, S6b, S8b, S8c и страж.

Дельты S6 считаются по ответу настоящего `handle_state_set` (`changed: true`), а не по числу вызовов шпиона. S8 берёт порядок из журнала Rig (`child.dead`, `store.done`, `workers.stop_all`, `state_store`).

## 2. Красный на текущем коде (коммит 1df9a4164, без эталона)

Прогон: `33 failed, 1 passed`. Единственный зелёный — страж `test_per_process_fields_unchanged...` (зелёный до и после).

| Тест | Красный по | Сообщение |
|---|---|---|
| S1 (3 случая) | поведению | в ответе supervision.status нет ключа system_stop; ключи `['epoch','processes','success']` |
| S2, S2b, S2c, S2e, S3, S4, S5, S8b | поведению | то же сообщение: ключа `system_stop` нет |
| S2d (3 случая) | поведению, но слабо | то же сообщение. Тест красен из-за отсутствия ключа, а не из-за ошибки аргументов |
| S6 | поведению | `AssertionError: []`: ни одного вызова `handle_state_set` по `system.stop.*` |
| S6a | поведению | `AssertionError: []`, записей на старте 0, а не 4 |
| S6b[raises] | поведению | «стоп не пытался писать в стор» |
| S6b[none] | поведению | нет ключа `system_stop` |
| S7 | поведению | журнал `['executor.request_stop','executor.join_until','monitor.stop','group.request_stop']`, записи `phase=children` нет |
| S8 (2 случая) | поведению | «phase=done не записан в стор вовсе»; в журнале видны `child.dead`, `workers.stop_all`, `state_store` |
| S8c | поведению | нет ключа `system_stop` |

Красных по ошибке теста, импорта или стенда нет. Предусловия стенда (ребёнок получил сигнал стопа, окно открыто) проходят на текущем коде: команда доходит до PM.

## 3. Эталон и инъекции

Эталон — мой пересказ блока ПОВЕДЕНИЕ в виде pytest-плагина (monkeypatch). Чистый эталон: `34 passed` (три прогона подряд, без флейков). Существующие тесты на нём: `test_system_shutdown_force.py`, `test_supervision_instance_truth.py`, `test_pm_responsive_during_children_stop.py`, `test_process_manager_process.py` зелёные, кроме двух `test_backend_ctl_socket_*` (`Address already in use`). Эти два падают и без эталона, это среда.

В брифе названо 11 инъекций, а не 12. Одиннадцать прогнаны по списку, ещё восемь добавлены мной (строки 12-19).

| # | Инъекция | Предсказано | Наблюдено |
|---|---|---|---|
| 1 | нет заполнения в `request_stop` | S3 | S3[after-request-stop], S7 (S7 я не предсказывал; он верно красный: `phase=children` не объявлена) |
| 2 | done в `_stop_summary` вместо `join_until == True` (и без done при закрытии области) | S8 | S8 (оба случая), S8b, S8c. Первый прогон показал, что инъекция не была верной: эталон оставлял done при закрытии области, S8 был зелёным. Инъекция исправлена в эталоне, S8 стал красным |
| 3 | не публиковать в стор | S6, S8 | S3[after], S6, S6a, S6b[raises], S7, S8 (оба), S8c |
| 4 | `deadline_at` для force без `deadline_s` | S4 | S4: force-0.5, force-3.0-budget-8, force-lower-bound, force-default-deadline_s (force-upper-bound зелёный: срок 5.0 совпал с константой инъекции) |
| 5 | force не меняет mode | S5 | S5, S6a |
| 6 | `phase=children` после остановки исполнителя | S7 | S7 |
| 7 | sender не доставляется (всегда unknown) | S2 | S2[gui], S2[backend_ctl], S2c, S5, S6 |
| 8 | дефолт `_system_stop_info` в `__init__` вместо класса | S1 и существующие тесты на `__new__`-PM | S1[bare-new-pm], S1[light-rig] и все лёгкие тесты; существующие: 5 в `test_process_manager_process.py`, 7 в `test_supervision_instance_truth.py`, 9 в `test_system_shutdown_force.py`. Первый прогон был зелёным: эталон читал атрибут через `getattr(..., None)`, который прячет отсутствие. Исправлено на прямой доступ |
| 9 | нет ленивого begin в status при внешнем событии | S3 | S3[before-request-stop] |
| 10 | begin до проверки аргументов | S2 | S2d (все 3 случая); имя S2d, не S2 |
| 11 | done на любом возврате `join_until` | S8 | S8[child-needs-terminate], S8c |
| 12 | сбой стора пробрасывается в `system.shutdown` | (мой) | S6b[raises] |
| 13 | второй graceful перезаписывает стоп | (мой) | S2c |
| 14 | force после done меняет mode | (мой) | S8b |
| 15 | graceful `deadline_at` с константой 5.0, не из бюджета | (мой) | S4[graceful-budget-8] |
| 16 | force сбрасывает `started_at` и `initiator` | (мой) | S5 |
| 17 | при закрытии области с выжившими done не ставится | (мой) | S8c |
| 18 | инициатор события «unknown» вместо «event» | (мой) | S3 (оба случая) |
| 19 | status не отдаёт ключ при отсутствии стопа | (мой) | S1 (3 случая), S2d |

## 4. Неоднозначности критериев (что пришлось додумать)

1. Ключ отправителя: `msg["sender"]` на верхнем уровне конверта (так делает `build_system_command_message`). Другое место отправителя (`data.sender`, `reply_to`) я не проверял.
2. Пустой или `None` отправитель: «без отправителя» понят как отсутствие ключа. Случай `sender=""`/`None` не проверен.
3. Основа времени `deadline_at`: `time.time()` и для graceful, и для force (так же, как `started_at`). Критерий C этого прямо не говорит.
4. Окно `started_at` для события без команды: `[момент взведения события, момент возврата request_stop или status]`. Если реализация поставит `started_at` раньше (хук на событие), тест S3 упадёт.
5. Первый force как первый стоп (без graceful): `deadline_at` проверен (S4), `mode` в этом случае не проверяется. Подразумеваю force, критерий молчит.
6. Форма вызова стора: тест принимает `handle_state_set({"data": {path, value, source}})` и плоский `{path, value, source}`. Вызов с kwargs не поддержан.
7. Порядок первых четырёх дельт S6 не задан (любой), пятая — `phase=done`. Это моё прочтение «при начале 4, при done 1».
8. S6 берёт одного быстрого ребёнка. Сколько дельт при нуле детей, не проверено.
9. Выжившие (S8c): я утверждаю, что после `join_until == False` и `kill` фаза не `done` и становится `done` при `close()`. Прямая формулировка критерия F: «если ещё не стоит, при закрытии области».
10. Фазы `pre_stop` и `last_wave` не проверяются (в этой задаче их никто не выставляет); `pre_stop_step` всегда `None`.
11. S6b[none] требует `system_stop` не `None` при отсутствии стора. Критерий A: «иначе словарь», и стоп начат в памяти. Это вывод, не прямая строка.
12. S8b: после done force отвечает успехом и не меняет `mode`/`deadline_at`. Критерий F говорит только «не меняет mode и ничего не публикует».
13. Исполнение `system.shutdown` из `_handle_process_command`: тест предполагает, что отправитель доходит до обработчика любым способом; способ (поток, kwargs) тесту не важен.

## 5. Что я оставил открытым / ненадёжно

- Эталон — моё чтение критериев. Зелёный эталон доказывает согласие тестов с моим чтением, а не с реализацией developer. Первый прогон двух инъекций (№2, №8) был зелёным из-за дыр в самом эталоне. Тела тестов проверены только после их исправления.
- Связность со стендами: `Rig` импортирован из соседнего теста `test_pm_responsive_during_children_stop.py`; смена его журнала (`child.dead`, `workers.stop_all`, `state_store`) сломает S8. Лёгкий стенд трогает внутренние имена `_stop_budget`, `_lifecycle_executor`, `_process_monitor`, `_children_stop`, `_state_store_manager`. Эти имена существуют сегодня.
- S7 считает «объявление фазы» записью `system.stop.phase=children` в стор до `executor.request_stop`. Реализация, объявляющая фазу только в памяти и пишущая в стор позже, не пройдёт. Критерий G требует запись при начале, поэтому я это принял. Опрос status внутри двойников намеренно убран: ленивый begin из status маскировал бы инъекцию №6.
- S2d красен на текущем коде только из-за отсутствующего ключа. Реальную силу тест получает после реализации (инъекция №10).
- S4: «force-upper-bound» не ловит инъекцию №4 (константа 5.0 совпадает с границей); это ожидаемо, остальные случаи ловят.
- Временные допуски: окна `time.time()` с допуском 0.01 с, держащий ребёнок живёт 4 с. На загруженной машине S2, S5 и S6a могут стать нестабильными. Три прогона эталона дали 34 из 34 без флейков.
- Две проверки среды падают без моего участия: `test_process_manager_process.py::...::test_backend_ctl_socket_accepts_while_children_stop` и `...::test_backend_ctl_socket_closed_even_if_stop_all_raises` (`Address already in use`). Другая сессия держит сокет. Это нужно учесть при чтении итогов regression.
- Отчёт lifecycle-guards G4 (незакрытые `QueueFeederThread`) — тот же шум, что у соседнего теста на Rig; закрытие корней G3 — 0.
- Живые тесты идут по несколько секунд (весь файл около 10 с). Прогон файла — через шлюз `medium`.
