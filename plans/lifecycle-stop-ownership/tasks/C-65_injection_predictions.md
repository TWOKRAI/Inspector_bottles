# C-65 — прогноз инъекций (лид, записано до прогона, новых тестов ещё не читал)

Наборы: F1 = test_pm_marks_gone_reader_acceptance.py, F2 = test_pm_marks_gone_reader_hazards.py. Файл под правкой: core/process_registry.py.

| № | Инъекция | Свойство | Ожидаемые красные минимум |
|---|---|---|---|
| J1 | снять метку уже мёртвого имени (ветка `not process.is_alive()` в `_build_child_stop`) | метка мёртвому до ожидания | test_stop_many_unblocks…[dead-reader-first], […dead-reader-last], test_stop_many_marks_already_dead_child |
| J2 | `on_confirmed_dead=None` | метка после подтверждённой смерти | test_stop_many_unblocks…[reader-exits-on-stop-listed-last], test_killed_reader_writer_exits_before_deadline, test_mark_only_after_confirmed_death |

Новая мера обязана краснеть на J1 и J2, срок 10 с: прогон дольше базы, это ожидаемо.
Прочие красные — журнал поимённо, разбор причины за лидом.
