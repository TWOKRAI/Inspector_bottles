# gui-graceful-close, Task 1.1a, tester (слепые приёмочные тесты, RED)

STATUS: DONE_WITH_CONCERNS

Файл: multiprocess_framework/modules/process_manager_module/tests/test_pm_responsive_during_children_stop.py (8 тестов).
Запуск (через гейт, из корня worktree, import-путь внутри worktree доказан):
`bash $MAIN/scripts/machine_gate.sh medium operator-1.1a-tester env PYTHONPATH=<worktree> $MAIN/.venv/bin/python -m pytest -q --tb=short -p no:cacheprovider <файл>`
Итог трёх прогонов подряд: `5 failed, 3 passed` (те же тесты, ~25 с).

## Обвязка
Живой GenericProcessManagerApp + настоящий SharedResourcesManager; команды кладутся в системную очередь PM, ответы читает зонд Probe.
«Раннер» воспроизведён как в run_process_function (ждать stop_event/system_stop_event -> stop() -> close_root()).
Дети — фейковые OS-процессы (is_alive/terminate/kill), выход управляется тестом (таймер 3,0 с после сигнала / смерть на terminate()).
Группа детей — настоящие ProcessRegistry.children_stop -> ChildProcessStop; прокси только журналирует.

## Результат по тестам
| тест | сейчас | причина |
|---|---|---|
| test_supervision_status_answers_while_child_stops_slowly | RED | assert len(good) >= 5: 0 из 12 запросов получили быстрый успешный ответ в окне 3,0 с. Ответ на system.shutdown приходит (эта часть зелёная) |
| test_message_processor_closes_after_children | RED | journal.index("children.join_end") = 7 не меньше journal.index("workers.stop_all") = 3 |
| test_restart_during_system_stop_is_refused | RED | reply is None: process.restart в окне не получил ответа (message_processor закрыт) |
| test_plugins_stop_requested_before_children_join | GREEN (страж) | plugins.request_stop уже раньше children.join_start (запись plugins-stop регистрируется последней, LIFO) |
| test_slow_child_needing_terminate_leaves_no_survivors | GREEN (страж, гипотеза подтверждена) | survivors == (), shutdown() True, state_store 1, сводка 1 |
| test_repeated_system_shutdown_during_children_stop_is_idempotent | RED | reply is None: второй system.shutdown не получил ответа в окне |
| test_summary_published_after_children_workers_and_state_store | RED | порядок первых вхождений начинается с workers.stop_all, а не с children.join_end |
| test_restart_refused_at_spawn_layer_after_system_stop | GREEN (страж) | restart_process напрямую уже отказан слоем спавна (_spawn_refused_after_system_stop) |

Тест 5 станет красным, если хвост (workers/state_store/сводка) после ожидания детей останется без времени. Проверено инъекцией в памяти
(`_WorkersStop.join_until -> False`): survivors = ('proc/ProcessManager/work/workers',), тест красный. Реальный риск — при переносе workers ПОСЛЕ детей
эскалация terminate (graceful g + окна) съедает бюджет work-сегмента.
Тест 8: инъекция `_spawn_refused_after_system_stop -> False` даёт красный (child.stop_signals = 2).

## What I interpreted rather than followed
- Тесты 4 и 8 в брифе числились в REDS, но на текущем коде они зелёные (порядок plugins-stop и отказ слоя спавна уже верны) — оставлены стражами, не искусственно красными.
- «Журнал порядка закрытия message_processor» = первый вызов worker_manager.stop_all_workers (так _WorkersStop закрывает воркер message_processor); журнала самого потока нет.
- «Ожидание детей началось/закончилось» = вход в join_until / выход из него у настоящей группы детей (прокси).
- Критерий 6, force: проверены ответ (mode=force, deadline_s=0.5) и учёт pm._force_deadline_s; сокращение идущего ожидания не утверждается.
- Критерий 3: «отвергается» = ответ success=False + create_and_register не вызван + ребёнок не заменён и не остановлен повторно; текст ошибки не пинится.

## What I left open / unreliable
- Тест 4 (plugins-stop раньше join) — страж без инъекции: оркестратор в тесте фейковый, сломать его порядок из памяти без правки src не удалось. Красным он станет, только если реализация поставит request_stop плагинов после начала ожидания детей.
- Красные 3 и 6 падают на «ответа нет вообще» (message_processor закрыт), а не на содержимом отказа; ассерты содержимого (success=False / success=True / mode=force) RED не достигает и проверятся только после реализации.
- Тест 1: допуск 0,3 с и 5 ответов за 3,0 с замерены на Darwin на красном коде; на корректной реализации не проверялось (её нет) — флак не исключён. Каденс запросов 0,25 с, окно — до смерти ребёнка.
- Фейковый ребёнок не проходит через spawn/хук выхода (exit_report -> «not reported» в сводке): сводка в тестах всегда WARNING, порядку не мешает.
- Живой ProcessMonitor работает на фейковых детях без жалоб, его поведение в окне не изучалось.
- lifecycle-guards G4: 13 QueueFeederThread без scope path от SharedResourcesManager (у соседних тестов с SRM — то же, не проверял).

memory hits: scripts/memory/search.py "process manager shutdown children stop" -> project_graceful_stop_debt.md и др.; по существу задачи не применимы.
