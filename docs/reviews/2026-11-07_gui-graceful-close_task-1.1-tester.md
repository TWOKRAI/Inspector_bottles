# gui-graceful-close 1.1: отчёт слепого tester (стадия 1)

Роль: tester, режим RED, слепой (DESIGN не выдан). Дерево: `.claude/worktrees/op-1.1-tester` (detached на `400ef3f00`, заглушка). Ничего не закоммичено и не запушено.

Parsed: MODE=red (слепой), INTERFACE=заглушка `multiprocess_prototype/frontend/shutdown/close_coordinator.py`, MODULE_CONTRACT=n/a (в брифе не указан), TASK=1.1, PLAN=plans/2026-10-20_gui-graceful-close/plan.md.
memory hits: `search.py close coordinator tester blind qt` -> применён `feedback_blind_red_prove_bodies_with_scratch_reference.md` (эталон в scratchpad, см. ниже); остальные попадания не по теме.

Import-путь: `python -c 'import multiprocess_prototype; print(multiprocess_prototype.__file__)'` -> `.../worktrees/op-1.1-tester/multiprocess_prototype/__init__.py`.

## Файлы

1. `multiprocess_prototype/frontend/tests/test_close_coordinator.py` — новый, 30 тестовых случаев (15 функций).
2. `multiprocess_prototype/frontend/tests/test_gui_process.py` — добавлен один тест `TestRequestSystemShutdown::test_no_event_when_coordinator_sent_shutdown`, остальное не тронуто.
3. Этот отчёт.

ruff: `ruff check -q` по обоим файлам чисто.

## Список тестов

Пункты REDS (10 строк брифа):

| REDS | Функция / случаи |
|---|---|
| x_on_running | `test_x_on_running_ignores_event_and_sends_shutdown_once` (настоящее MainWindow: событие не принято, порядок `confirm, send, sent`, STOPPING, есть QProgressDialog) |
| x_on_running (+сбой) | `test_x_on_running_ignores_event_and_sends_shutdown_once_send_failure` (отдельная функция с тем же префиксом: `quit_app` вызван, CLOSING, `on_shutdown_sent` нет) |
| second_x | `test_second_x_in_stopping_is_ignored_without_resend` (настоящее окно, два closeEvent и request_close) |
| cancel | `test_cancel_in_save_prompt_keeps_system_running[cancel\|raises]` (оба случая "+сбой confirm_discard" внутри параметризации; после них повторный крестик работает, значит RUNNING настоящий; опрос не идёт) |
| quit_app после всех | `test_quit_app_called_only_after_all_children_dead` (фазы: все живы / один мёртв / второй `alive None`, PM жив в `ignore_names`) |
| backend_gone | `test_backend_gone_never_prompts[backend_gone\|safety_tick_true]` (настоящее MainWindow + грязная `TopologySession`, спай на `confirm_unsaved_changes`) |
| closeEvent в CLOSING | `test_close_event_in_closing_does_not_ask_again` (настоящее окно, «Не сохранять»: один вопрос, dirty остался, геометрия записана) |
| polling | `test_polling_and_force_flow[...]`, 8 случаев: `no_answer_asks_operator_then_sets_event`, `wait_resets_2s`, `answer_while_question_open`, `timeout_is_not_an_answer`, `one_request_in_flight`, `unattended_sets_event_without_question`, `dead_pm_tail_commits_after_force`, плюс добавленный мной `poll_off_main_thread_result_on_main` |
| restart | `test_ui_restart_quits_without_shutdown[confirmed\|declined\|not_running]` |
| progress | `test_progress_dialog_has_no_cancel_and_ignores_escape` |
| GuiProcess | `test_gui_process.py::TestRequestSystemShutdown::test_no_event_when_coordinator_sent_shutdown` |

Сверх REDS (пункты ПОВЕДЕНИЯ A, B, C, F, которых в списке REDS нет; решение моё, вынесено сюда как находка):

- `test_safety_tick_during_confirm_prevents_send` (A: safety-тик во время вопроса -> `send_shutdown` не вызывается);
- `test_x_outside_running_is_ignored[confirming|closing]` (B: вложенный крестик в CONFIRMING, крестик в CLOSING);
- `test_empty_or_unsuccessful_response_is_not_all_dead[empty_processes|no_processes_key|no_success_key|success_false]` (C);
- `test_safety_tick_false_never_commits`, `test_safety_tick_true_in_stopping_does_not_interrupt_wait` (F).

Брифу "REDS <= 10" это не противоречит по числу пунктов, но число функций больше; при желании лишнее режется без ущерба для десяти основных.

## Запуск на заглушке: красный по поведению или по ошибке теста

Команда (через шлюз): `machine_gate.sh medium op-1.1-tester .venv/bin/python -m pytest -q --tb=no -p no:cacheprovider test_close_coordinator.py test_gui_process.py test_close_layout_unsaved_blind.py test_topology_dirty_indicator.py test_main_window.py`

Результат: `31 failed, 79 passed`. 31 = все новые случаи (30 + 1 в test_gui_process); 79 зелёных — существующие тесты, которых я не менял. Ни один новый случай на заглушке не зелёный, отрицательные утверждения не дают ложной зелени ни у одного (каждый случай сначала проверяет положительный предусловный эффект: состояние, счётчик, `isAccepted`). Ошибок импорта и тестовых ошибок (не-Assertion) нет: все падения — `AssertionError` по ПОВЕДЕНИЮ.

| Тест | Первое падение на заглушке | Вид |
|---|---|---|
| x_on_running | `closeEvent с координатором обязан сделать event.ignore()` (старый closeEvent принимает) | поведение |
| x_on_running_..._send_failure | `send_calls == 1` (0 == 1: заглушка ничего не вызывает) | поведение |
| cancel[cancel], cancel[raises] | `confirm_calls == 1` (0 == 1) | поведение |
| safety_tick_during_confirm | `confirm_calls == 1` (0 == 1) | поведение |
| second_x_in_stopping | `state is STOPPING` (RUNNING) | поведение |
| x_outside_running[confirming] | `вложенный крестик не задаёт второй вопрос` | поведение |
| x_outside_running[closing] | `state is CLOSING` (RUNNING) | поведение |
| quit_app_only_after_all_dead | `state is STOPPING` (RUNNING) | поведение |
| empty_or_unsuccessful x4 | `state is STOPPING` (RUNNING) | поведение |
| backend_gone[backend_gone], [safety_tick_true] | `state is CLOSING` (RUNNING) | поведение |
| safety_tick_false_never_commits | `state is STOPPING` (RUNNING) | поведение |
| safety_tick_true_in_stopping | `state is STOPPING` (RUNNING) | поведение |
| close_event_in_closing | `first.isAccepted() is False` (True: старый closeEvent принял) | поведение |
| polling_and_force_flow x8 | `state is STOPPING` (RUNNING) в общем помощнике `_stop_started` | поведение |
| ui_restart[confirmed] | `confirm_calls == 1` (0 == 1) | поведение |
| ui_restart[declined] | `confirm_calls == 1` (0 == 1) | поведение |
| ui_restart[not_running] | `state is STOPPING` (RUNNING) | поведение |
| progress_dialog | `state is STOPPING` (RUNNING) | поведение |
| test_no_event_when_coordinator_sent_shutdown | `общий system_stop_event взводить нельзя`: event взведён | поведение |

Слабость красного на заглушке: большинство тестов падает на предусловии (`state is STOPPING`), то есть заглушка не доходит до тел с реальными проверками. Поэтому тела проверены отдельно (следующий раздел).

## Проверка тел: эталон и инъекции (scratchpad, мой, не в дереве)

Заглушка не доказывает тела ассертов (урок `feedback_blind_red_prove_bodies_with_scratch_reference`). Я написал одноразовую эталонную реализацию строго по блоку ПОВЕДЕНИЕ (реализаций из других деревьев не читал) и подключил как pytest-плагин `-p refimpl_plugin`, подменяющий в памяти `CloseCoordinator`, `MainWindow.closeEvent` и `GuiProcess._request_system_shutdown`:

`/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/e2edcaee-7aad-4901-9110-64aff4d27ddb/scratchpad/refimpl/refimpl_plugin.py` (инъекции включаются env `REF_BREAK=<имя>`; скрипты `matrix.sh`, `matrix2.sh`, `matrix3.sh`). Это моя реализация, в дерево не попала, не коммитится.

Эталон: 34 passed (30 + 4 существующих `TestRequestSystemShutdown`), три прогона подряд без флейка (~4.4 с).

Инъекции на эталоне (прогнаны, а не предсказаны). Колонка «ожидал» — из таблицы брифа.

| Поломка (REF_BREAK) | Покраснели | Совпало с ожиданием |
|---|---|---|
| closeEvent без ignore (`no_ignore`) | x_on_running, second_x_in_stopping, close_event_in_closing | да (+ два соседа) |
| «Отмена» не возвращает RUNNING (`cancel_stays`) | cancel[cancel] | да |
| all->any в проверке мёртвых (`all_to_any`) | quit_app_only_after_all_dead | да |
| closeEvent в CLOSING зовёт confirm (`closing_asks`) | backend_gone x2, close_event_in_closing | да |
| force_stop не вызывается (`no_force`) | polling[no_answer...], polling[unattended...], polling[dead_pm_tail...] | да |
| нет защиты «один запрос в полёте» (`no_inflight_guard`) | polling[one_request_in_flight] | да |
| timeout считается ответом (`timeout_is_answer`) | polling[timeout_is_not_an_answer], polling[answer_while_question_open], empty_or_unsuccessful[success_false] | да |
| убран хвост после force (`no_tail`) | polling[dead_pm_tail...] | да |
| ignore_names без PM (`ignore_missing_pm`) | quit_app_only_after_all_dead, safety_tick_true_in_stopping, close_event_in_closing, polling[poll_off_main_thread...] | да |
| request_restart шлёт shutdown (`restart_sends`) | ui_restart[confirmed] | да |
| диалог с кнопкой отмены (`progress_with_cancel`) | progress_dialog | да |
| Esc закрывает диалог (`esc_closes`) | progress_dialog | да |
| GuiProcess взводит event при shutdown_sent (`gui_sets_event`) | test_no_event_when_coordinator_sent_shutdown | да |
| сторож проверяется только по приходу результата (`watchdog_on_result_only`) | 6 случаев polling: no_answer, wait_resets, answer_while_open, timeout_not_answer, unattended, dead_pm_tail | да, ровно задуманное |
| успех не двигает t_last_success (`no_t_ok`) | polling[answer_while_question_open] | да |
| ручка вопроса не закрывается по успеху (`no_handle_close`) | polling[answer_while_question_open] | да |
| «Подождать» не двигает t_wait_click (`no_wait_click`) | polling[wait_resets_2s] | да |
| t_force не входит в last (`no_t_force`) | polling[no_answer...], polling[unattended], polling[dead_pm_tail] | да |
| пустой processes засчитан как «все мертвы» (`empty_dead`) | empty_or_unsuccessful[empty_processes\|no_processes_key] | да |
| safety_tick(False) коммитит (`tick_false_commits`) | safety_tick_false_never_commits | да |
| safety_tick(True) в STOPPING коммитит (`stopping_tick_commits`) | safety_tick_true_in_stopping | да |
| нет перепроверки состояния после confirm (`no_recheck_after_confirm`) | safety_tick_during_confirm | да |
| вложенный request_close в CONFIRMING разрешён (`reentrant_confirm`) | x_outside_running[confirming] | да |
| рестарт игнорирует «Отмену» (`restart_ignores_cancel`) | ui_restart[declined] | да |

Не прогонялись на эталоне (предсказания, без доказательства): исключение confirm_discard оставляет CONFIRMING -> cancel[raises] (повторный крестик не пройдёт); сбой send_shutdown не вызывает quit_app -> x_on_running_..._send_failure; closeEvent в CLOSING не пишет геометрию -> close_event_in_closing (проверка `settings.contains("mainwindow/geometry")`); опрос идёт в RUNNING -> cancel (`poll_calls == []`); `request_close` в CLOSING повторяет quit_app -> x_outside_running[closing] (`quit_calls == 1`).

Из-за гонок инъекция «убрать защиту одного запроса» краснеет надёжно только потому, что фейк держит `threading.Event`; без блокировки (быстрый poll) защиту тест не ловит.

## Неоднозначности критериев (мои допущения; каждую решает постановщик)

1. «Ошибку в лог» (A) я НЕ проверяю: logger реализации неизвестен, `caplog` мог бы не увидеть запись (фреймворк-логгер с `propagate=False`) и дал бы ложный красный на корректном коде. Проверяется только эффект (RUNNING, ничего не отправлено / `quit_app`). Класс дефекта «исключение проглочено молча» тестами не закрыт.
2. A, ветка «safety-тик пришёл во время confirm_discard, а confirm вернул False»: куда идёт состояние (остаётся CLOSING или откатывается в RUNNING) критерий не говорит. Покрыта только ветка True ("send_shutdown не вызывается"). Ветку False не пинил.
3. G: состояние после подтверждённого `request_restart()` не задано (CLOSING или RUNNING). Проверяю только `quit_app` вызван и `send_shutdown` не вызван; состояние не проверяю.
4. D: «считается как Подождать БЕЗ сдвига t_wait_click» ненаблюдаемо при монотонных часах: в момент успешного ответа `t_last_success = clock()` совпадает с возможным `t_wait_click`. Пинится только наблюдаемое: ручка закрыта ровно один раз, force нет, новый вопрос через `no_answer_s` ПОСЛЕ успеха, а не после отправки.
5. D: после закрытия вопроса успешным ответом допустил, что вопрос можно задать снова после следующей тишины (из «считается как Подождать»). Если задумано иначе, случай `answer_while_question_open` надо переписать.
6. D: после "Остановить" допустил, что вопрос больше не задаётся (из «(а) ... force не нажат») и `force_stop` вызывается один раз. Проверяю `ask_count == 1`, `force_calls == 1`.
7. D: граница `>= no_answer_s` пинится парой 1.99 / 2.0 на фейковых часах. Допущение: тик сторожа живёт на том же таймере, что и опрос (`poll_interval_ms=20` в тестах). Если реализация держит отдельный тик с большим интервалом, положительные ожидания (2 с) пройдут, а отрицательные ("не спросили за 150 мс") станут слабее.
8. C: `poll_status` принимается и позиционно `poll_status(1.0)`, и как `timeout=1.0` (фейк `poll_status(self, timeout=None, ...)`). Тест фиксирует значение 1.0, не форму вызова.
9. C: ответ `success` не `True`, а truthy (например `1`, `"yes"`) не тестировал: критерий пишет `is True`, но проверка строгого `is` кажется перебором.
10. C: допустил, что в CLOSING опрос прекращается или `commit_close` идемпотентен (`quit_calls == 1` через 100 мс после коммита). Если реализация шлёт `quit_app` на каждый результат, тест краснеет.
11. E: "окно закрывается" проверено прямым вызовом `window.closeEvent(QCloseEvent)` в состоянии CLOSING (как в существующих тестах), `quit_app`-фейк окно не закрывает. Реальную цепочку `quit_app -> закрытие окна` из критериев не вывести.
12. E: геометрия проверяется как наличие ключа `mainwindow/geometry` во временном `QSettings`, подсунутом в приватный `window._settings` (чтобы не писать в настройки владельца). Завязка на имя приватного атрибута существующего кода.
13. H: «прогресс показан» понимаю как `isVisible()`; «нет кнопки отмены» — как отсутствие `QPushButton` среди потомков диалога; «Esc не закрывает» — `QTest.keyClick(Escape)` оставляет диалог видимым. Закрытие диалога крестиком/Alt+F4 и модальность критерий не описывает, не тестировал. Если реализация полагается на `minimumDuration` по умолчанию (4 с), диалог не будет видим: тест красный справедливо (прогресс должен быть показан).
14. I: проверяется только отсутствие взвода `system_stop_event`. Уйдёт ли IPC-fallback `system.shutdown`, когда `shutdown_sent=True`, а event недоступен, критерий не говорит, не пинил.
15. «(+ сбой ...)» в REDS я прочёл как сопутствующие случаи: сбой `confirm_discard` — внутри параметризации cancel; сбой `send_shutdown` — отдельная функция с префиксом имени основного теста (`-k` по префиксу подхватит оба).

## Что я оставил открытым / ненадёжно

- Тела тестов доказаны только моим эталоном (см. выше), а не настоящей реализацией; на реальной реализации возможны красные от моих допущений п.7, п.10, п.13. Каждый такой красный нужно читать как «проверить допущение», не как автоматическую ошибку кода.
- Отрицательные утверждения («не спросили», «не отправили») ждут реальные 100-150 мс и несколько тиков; на очень загруженной машине они могут пройти раньше, чем реализация успела бы ошибиться, то есть слабеют, но ложно-красными не станут. Положительные ожидания имеют 2-секундный потолок; три прогона эталона подряд зелёные (~4.4 с), под нагрузкой потолок не проверялся.
- Опрос идёт на реальном пуле (`RequestRunner` по умолчанию), но «результат в главном потоке» пинится только по потоку `quit_app` (результат -> commit), не по `ask_force_stop`/`on_answer`.
- Модальный страж корня (`conftest.py`) в моих тестах не срабатывает: диалог несохранённых правок подменён спаем, `ask_force_stop` — фейк. Но если реализация вызовет настоящий `confirm_unsaved_changes` мимо спая (например, импортом на уровне модуля вместо `frontend.widgets.dialogs`), спай не сработает и страж остановит тест, а не оператор.
- Сторож тишины тестируется только на отсутствии ответов (блокированный poll) и таймаутах. Смешанные последовательности (успех, потом тишина, потом успех в момент открытого вопроса и "Остановить" одновременно) вне набора.
- Эталон и инъекции — мои, не от реализатора; этап инъекций по таблице реализатора остаётся за ним.

MEMORY LESSON: не требуется (повтор урока `feedback_blind_red_prove_bodies_with_scratch_reference`; новое только то, что `pytest -p <plugin>` с `PYTHONPATH` на scratchpad заменяет `sitecustomize` и работает с qt-тестами без изменений дерева).
