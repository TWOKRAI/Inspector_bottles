# gui-graceful-close 1.1: отчёт teamlead (стадия 2, GREEN)

Роль: teamlead, исполнитель. Дерево: `.claude/worktrees/op-1.1`, ветка `feat/gui-close-1.1`, база HEAD `265c1b0a3`. Ничего не закоммичено и не запушено. Сообщение коммита: `docs/reviews/2026-11-07_gui-graceful-close_task-1.1-teamlead.commitmsg.txt`.

memory hits: n/a (поиск по памяти не запускался; задача шла по готовому DESIGN, итерация одна).

## Итог

- Слепой набор tester: 31 красный на заглушке → 31 зелёный. Итераций RED→GREEN: одна. Тесты tester не правил.
- Набор из брифа: **122 passed** (команда и вывод ниже). Страж `test_root_close_order_golden`: зелёный.
- Инъекции: 12 из 12 по таблице дали предсказанный красный. В 5 случаях красных больше, чем предсказано (это надмножество, не расхождение). Дополнительная инъекция по Esc показала слабость теста H (ниже, «Находки»).
- ESCALATION нет: ни одного красного теста, который я считаю неверным.

## Что сделано по шагам DESIGN

| Шаг | Где | Что |
|---|---|---|
| 1 | `multiprocess_prototype/frontend/shutdown/close_coordinator.py` | Тело заглушки заменено. Сигнатуры и состояния не менялись. Добавлено (аддитивно): свойство `restart_requested`, функция `ask_force_stop_dialog(parent, on_answer)` (настоящий вопрос), константа `FORCE_STOP_QUESTION`. `__init__.py` пакета не менялся. |
| 2 | там же, `request_close` / `_confirm` | `RUNNING → CONFIRMING` → `confirm_discard()`. Сбой → ERROR, `RUNNING`. «Отмена» → `RUNNING`. После возврата состояние проверяется заново: не `CONFIRMING` → ничего. Затем `send_shutdown()`; сбой → ERROR, `commit_close()` без `on_shutdown_sent`. Успех → `t_send`, `on_shutdown_sent()`, `STOPPING`, прогресс, старт `QTimer`. |
| 3 | `_StopProgressDialog` | `QProgressDialog`, `WindowModal`, `show()`, `setCancelButton(None)`, `setMinimumDuration(0)`, `setAutoClose(False)`, `setAutoReset(False)`, `reject()` ничего не делает, `closeEvent` игнорируется до `finish()`. Заголовок и текст: «Остановка системы…», после первого успешного ответа «Остановка системы… k из N». |
| 4 | `_on_tick` / `_on_poll_result` | Тик `QTimer` (`poll_interval_ms`): сторож, затем `poll_status(1.0)` в `RequestRunner.submit`, если запроса в полёте нет. Ответ — только `success is True`. «Все остановлены»: непустой `processes`, среди имён вне `ignore_names` нет `alive is True`; `alive: None` не ждём; запись не-dict не ждём. N = записи вне `ignore_names` с `alive` не `None`. |
| 5 | `_check_silence` / `_on_operator_answer` / `_do_force` | Формула `last = max(t_send, t_last_success, t_wait_click, t_force)` на каждом тике. Вопрос → ручка + токен; ответ на уже закрытый вопрос отбрасывается по токену. «Остановить» → `force_stop()` + WARNING, `t_force`. «Подождать» → `t_wait_click`. После force и ещё `no_answer_s` тишины → WARNING + `commit_close()`. Ответ PM при открытом вопросе → ручка закрывается, `t_wait_click` не сдвигается. `unattended` → force без вопроса. Сбой `ask_force_stop` → ERROR и force (как без присмотра). |
| 6 | `multiprocess_prototype/frontend/windows/main_window.py` `closeEvent` | Без координатора — прежний путь (confirm + геометрия). С координатором: `CLOSING` → `_save_geometry()` + `super().closeEvent()` без вопроса; иначе `event.ignore()` + `request_close()`. |
| 7 | `multiprocess_prototype/frontend/app.py` `_request_ui_restart` | Однострочный вызов `close_coordinator.request_restart()`. Координатор задаёт вопрос, ставит `restart_requested`, зовёт `commit_close()` без `system.shutdown`. `_restart_ui = True` ставит `quit_app` в `app.py` ДО `app.quit()` (флаг читает `aboutToQuit`). Цикл `GuiProcess.run` не менялся. |
| 8 | `app.py` `_setup_timers` | Замыкание `_check_stop` = `close_coordinator.on_safety_tick(process.should_stop())`. `app.quit()` из таймера убран. Комментарий переписан. `_setup_timers` получил обязательный параметр `close_coordinator`. Новая функция `_build_close_coordinator` собирает настоящие эффекты: `confirm_discard` → `window.confirm_discard_topology_changes`, `send_shutdown` → `process_manager_proxy.shutdown_system`, `poll_status` → `command_sender.request_system_command({"cmd": "supervision.status"}, timeout=t)`, `ignore_names = {process.name, "ProcessManager"}`, `force_stop` → `set()` общего `system_stop_event` + WARNING, `quit_app` → `window.close()` + `app.quit()`, `unattended` → `unattended.is_unattended()`. |
| 9 | `multiprocess_prototype/frontend/process.py` | `_request_system_shutdown`: `shutdown_sent is True` → INFO и выход, без события и без IPC-fallback. `TestRequestSystemShutdown` сужен: докстринг класса и `assert process.shutdown_sent is False` в трёх прежних тестах. Тест tester не тронут. |
| 10 | `close_coordinator.py`, логгер `get_std_logger("gui")` | INFO: «закрытие: подтверждено», «закрытие: system.shutdown отправлен», «закрытие: все процессы остановлены (N)», «закрытие: окно скрыто» (после `quit_app()`, то есть после `window.close()`). |
| 11 | чтение | См. раздел «Шаг 11». |

## Прогоны

Путь импорта (из того же cwd, что pytest):

```
$ PYTHONPATH=$PWD .venv/bin/python -c 'import multiprocess_prototype; print(multiprocess_prototype.__file__)'
/Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/op-1.1/multiprocess_prototype/__init__.py
```

Набор из брифа (через `machine_gate.sh medium op-1.1`, `QT_QPA_PLATFORM=offscreen`, Darwin), последний прогон после всех правок:

```
... test_close_coordinator.py test_gui_process.py test_process_root_acceptance.py
    test_close_layout_unsaved_blind.py test_topology_dirty_indicator.py test_main_window.py
======================== 122 passed, 1 warning in 6.70s ========================
$ pytest -q test_process_root_acceptance.py::test_root_close_order_golden
1 passed, 1 warning in 0.42s
```

`ruff check -q` по 5 изменённым файлам: код возврата 0.

Дымовая проверка проводки `app._build_close_coordinator` (настоящий `MainWindow`, фейковые `command_sender` / `process_manager_proxy`, скрипт `scratchpad/smoke_build.py`, вне дерева):

```
after X: state stopping shutdown calls 1 shutdown_sent True visible True
final: state closing poll args call({'cmd': 'supervision.status'}, timeout=1.0) window visible False app.quit calls 1 _restart_ui False
restart: state closing shutdown calls 0 _restart_ui True window visible False app.quit calls 1
```

## Инъекции: наблюдено против предсказанного

Копия дерева: `git archive HEAD` + мои 5 файлов в scratchpad; рабочее дерево не откатывалось. Скрипт патчит одну строку, гонит `test_close_coordinator.py` + `test_gui_process.py` (75 тестов), восстанавливает файл. После матрицы копия сверена с деревом (`diff -q`: совпадает).

| № | Патч | Предсказано | Наблюдено красные | Совпало |
|---|---|---|---|---|
| I5 | `closeEvent` без `event.ignore()` | CC test_x_on_running… | test_x_on_running_ignores_event_and_sends_shutdown_once, test_second_x_in_stopping…, test_close_event_in_closing… | да (+2) |
| I6 | «Отмена» не возвращает `RUNNING` | test_cancel… | test_cancel…[cancel], test_cancel…[raises], test_ui_restart…[declined] | да (+1: общий `_confirm`) |
| I7 | all → any (`len(alive) < len(children)`) | test_quit_app_called_only_after_all_children_dead | то же, 1 | да |
| I8 | `closeEvent` в `CLOSING` зовёт confirm | test_backend_gone_never_prompts, test_close_event_in_closing… | test_backend_gone_never_prompts[backend_gone], [safety_tick_true], test_close_event_in_closing… | да |
| I10 | `force_stop()` не вызывается | polling[no_answer_asks_operator_then_sets_event] | polling[no_answer…], polling[unattended…], polling[dead_pm_tail…] | да (+2) |
| I11 | `_request_system_shutdown` игнорирует `shutdown_sent` | test_no_event_when_coordinator_sent_shutdown | то же, 1 | да |
| I12 | `request_restart` шлёт shutdown | test_ui_restart_quits_without_shutdown | test_ui_restart…[confirmed], 1 | да |
| I13 | кнопка отмены вместо `setCancelButton(None)` | test_progress_dialog… | то же, 1 | да |
| I14 | без защиты «один в полёте» | polling[one_request_in_flight] | то же, 1 | да |
| I15 | любой dict считается ответом | polling[timeout_is_not_an_answer] | polling[timeout…], polling[answer_while_question_open], test_empty_or_unsuccessful…[no_success_key], […][success_false] | да (+3) |
| I16 | без хвоста после force | polling[dead_pm_tail_commits_after_force] | то же, 1 | да |
| I17 | `ignore_names` без PM | test_quit_app… | test_quit_app…, test_safety_tick_true_in_stopping…, test_close_event_in_closing…, polling[poll_off_main_thread…] | да (+3) |
| I9 | `_check_stop` зовёт `app.quit()` | не покрыто | не прогонялась (по брифу) | — |
| доп. | `reject()` и `closeEvent` диалога не переопределены | (не предсказывалось) | **0 красных, 75 passed** | см. «Находки» |

Сырые строки сводок: I5 `3 failed, 72 passed`; I6 `3 failed, 72 passed`; I7 `1 failed, 74 passed`; I8 `3 failed, 72 passed`; I10 `3 failed, 72 passed`; I11–I14, I16 `1 failed, 74 passed`; I15 `4 failed, 71 passed`; I17 `4 failed, 71 passed`; доп. `75 passed`.

## Решения лида а)–з): как реализованы

- **а)** `_confirm` и `request_close`: `except Exception` → `_log.error(...)` с типом и текстом исключения (логгер `gui`). Тестом не проверено, только чтением.
- **б)** `_confirm`: после возврата `confirm_discard` первой идёт проверка `state is not CONFIRMING → return False`, до анализа ответа. Если safety-тик перевёл в `CLOSING`, ответ False ничего не откатывает, `send_shutdown` не зовётся. Повторного `quit_app` нет: `commit_close` в `CLOSING` выходит сразу.
- **в)** `request_restart` → `commit_close()` → состояние `CLOSING`.
- **г)** После «Остановить» стоит `_forced = True`: ветка вопроса больше не достижима, следующая тишина ведёт к `commit_close`. После «Подождать» и после закрытия ручки ответом PM `_question = None`, вопрос снова задаётся по формуле шага 5.
- **д)** Сторож вызывается из `_on_tick` того же `QTimer`, что и опрос, на каждом тике, до отправки запроса.
- **е)** `commit_close`: `if state is CLOSING: return`; таймер останавливается, поздние результаты опроса отбрасываются (`state is not STOPPING`).
- **ж)** `_show_progress`: `show()` сразу при переходе в `STOPPING`, `setMinimumDuration(0)`.
- **з)** `process.py`: проверка `shutdown_sent` стоит ДО получения события и до fallback-ветки. Отдельного теста на «нет IPC-fallback» нет (тест tester проверяет только событие; новый тест вне FILES не добавлял).

## Шаг 11: кто пишет `_stop_requested` у gui

Поиск `git grep -n "_stop_requested = True\|\"_stop_requested\", True"` по `multiprocess_framework/modules/process_module` и `multiprocess_prototype/frontend` (без тестов) — три записи:

- `multiprocess_framework/modules/process_module/core/process_module.py:1417` — `ProcessModule.stop()` (в DESIGN указано `:1406`; на текущем дереве строка 1417). Раннер зовёт `stop()` ПОСЛЕ возврата `run()`: `multiprocess_framework/modules/process_manager_module/runner/process_runner.py:189` (`process_instance.run()`), `:192-197` (проверка `stop_event`/`system_stop_event`, затем `process_instance.stop()`).
- `multiprocess_prototype/frontend/app.py:1322` — хук `aboutToQuit` (уже после `quit`).
- `multiprocess_prototype/frontend/process.py:330` — `GuiProcess.run` после выхода из цикла `run_gui` (уже после Qt). Ещё есть сброс `= False` в `process.py:325` (рестарт UI).

Вывод DESIGN подтверждён: пока `GuiProcess.run` блокирован в Qt, ни одна запись не срабатывает, в `STOPPING` `should_stop()` ложен. Остальной `multiprocess_prototype/frontend` проверен тем же `git grep` по `_stop_requested\s*=`: других записей нет (два совпадения — имена Qt-сигналов `belt_stop_requested` / `force_stop_requested`, не атрибут).

## Находки

1. **Тест H слабый по Esc.** `test_progress_dialog_has_no_cancel_and_ignores_escape` остаётся зелёным, когда защита от Esc убрана (инъекция «доп.»: 75 passed). Причина (проба в копии дерева): Esc прячет голый `QProgressDialog`, но следующий успешный опрос зовёт `setValue()`, и диалог показывается снова до проверки через 100 мс. Наблюдение пробы без защиты: `[alive] right after Esc visible: False`, через 100 мс `True`; `[timeout] right after Esc visible: False`, через 100 мс `False`. С защитой — `True` во всех четырёх точках. Нагружает защиту только `reject()` (без него Esc прячет диалог; без `closeEvent` — нет). В проде при молчании PM диалог после Esc остался бы скрытым. Тест неверным не считаю, он слабый: сильная форма — `poll_gate.clear()` (ответов нет) или проверка `isVisible()` сразу после `keyClick`. Решение за лидом (тест tester я не правлю).
2. **Режим без присмотра: сторож модалок и диалог прогресса.** `unattended.install_modal_watchdog` (`multiprocess_prototype/frontend/unattended.py:98-115`) каждые 250 мс берёт `QApplication.activeModalWidget()` и зовёт `reject()`. Диалог прогресса окно-модальный, поэтому, скорее всего, сторож будет видеть его на каждом тике ожидания: `reject()` ничего не сделает (диалог не закроется), но в журнал gui каждые 250 мс уйдёт WARNING `unattended.modal_closed … дефект сценария`, а `auto_answers()` вырастет. Не проверено запуском (нужен `INSPECTOR_GUI_UNATTENDED=1` на стенде). Влияет на heavy-приёмку на Windows (журнал gui, по которому работает зонд). Варианты: диалог `NonModal` при `unattended`, или сторож пропускает `_StopProgressDialog`. `unattended.py` вне FILES — решение за лидом.
3. **Текст вопроса при рестарте UI.** Раньше рестарт спрашивал «Сохранить их перед перезапуском интерфейса?». Теперь `confirm_discard` один на оба пути и спрашивает «…перед выходом?». Причина: `request_restart()` без аргументов, а `confirm_discard` — `Callable[[], bool]`. Поведение (один вопрос, «Отмена» отменяет) сохранено, текст хуже. Исправить можно флагом в замыкании `app.py` или параметром — решение за лидом.
4. **Аддитивные публичные имена в `close_coordinator.py`:** `restart_requested`, `ask_force_stop_dialog`, `FORCE_STOP_QUESTION`. Существующие сигнатуры заглушки не менялись. `restart_requested` нужен, потому что координатор не знает `process`, а `_restart_ui` ставить надо только при подтверждённом рестарте (не при `backend_gone` во время вопроса о рестарте).

## Что осталось открытым / ненадёжно

- **Windows не проверялся.** Живая форма ответа `supervision.status` через `request_system_command` (плоский dict, ключи `success`/`processes`/`alive`) взята из DESIGN, на живом PM я её не видел. Неверная форма даст: ни одного «все остановлены» → окно ждёт до сторожа тишины, затем вопрос. Проверка — heavy-приёмка лида.
- **`QProgressDialog` и `QMessageBox.open()` на реальном дисплее** не проверены: offscreen на Darwin. Не проверено: модальность поверх окна, фокус кнопки «Остановить» по умолчанию, поведение крестика самого вопроса (по коду: Esc и крестик = «Подождать»).
- **Настоящий `ask_force_stop_dialog` тестом не покрыт** (тесты идут на фейке). Порядок «координатор сбрасывает токен до `close()`, поздний `finished` отбрасывается» проверен только чтением кода.
- **I9 не прогонялась** (по брифу): замыкание `_check_stop` вызывает только `on_safety_tick`, это видно чтением; поведения тестом не закреплено.
- **Решение з) без теста** на ветку «события нет и `shutdown_sent=True` → IPC-fallback не уходит». Нужен один тест в `test_gui_process.py` (`get_system_stop_event` → `None`, `shutdown_sent=True`, `send_message.assert_not_called()`); по FILES я добавлять его не стал.
- **Зонд** `backend_ctl/probes/probe_gui_close_order_live.py` — не мой, не писал.
- Полный набор тестов не гонял (радиус: 6 файлов из брифа, 122 теста). Другие вызовы `MainWindow.closeEvent` с координатором вне этих файлов не искал: координатор ставится только в `run_gui`.
- Отрицательные утверждения слепого набора ждут 100–150 мс реального времени; под нагрузкой они слабеют (см. отчёт tester), прогон под нагрузкой не делал.

## Раунд 2 (после коммита `e53efdb20`)

Задача лида: находка 2. Без присмотра прогресс остановки немодальный, с оператором остаётся `WindowModal`.

### Правка

- `multiprocess_prototype/frontend/shutdown/close_coordinator.py`: `_StopProgressDialog(parent, *, modal=True)`. Модальность: `WindowModal if modal else NonModal`. `_show_progress` передаёт `modal=not self._unattended`.
- Вопрос без присмотра не открывается: в `_check_silence` ветка `if self._unattended` вызывает `_do_force` и выходит ДО `ask_force_stop`. Это закреплено тестом (3): `ask_calls == 0`, `force_calls == 1`.
- Новый файл `multiprocess_prototype/frontend/tests/test_close_coordinator_hazards.py` (авторский, файл tester не тронут):
  1. `test_unattended_progress_is_not_active_modal` — `unattended=True`, `STOPPING`, диалог виден, `QApplication.activeModalWidget() is None`;
  2. `test_attended_progress_is_window_modal` — без `unattended` диалог `WindowModal` и `activeModalWidget() is dialog` (страж против безусловной правки);
  3. `test_real_unattended_watchdog_never_hits_progress` — настоящий `unattended.install_modal_watchdog` (`_UNATTENDED`, `_log`, `_answers` подменены через `monkeypatch`, `interval_ms=50`), ожидание 650 мс: записей `unattended.modal_closed` нет, `auto_answers() == ()`, диалог виден. Затем часы +2,0 с: `force_calls == 1`, `ask_calls == 0`, записей сторожа всё так же нет.

### Прогоны

```
$ ruff check -q close_coordinator.py test_close_coordinator_hazards.py   -> код 0
$ python -c 'import multiprocess_prototype; print(multiprocess_prototype.__file__)'
/Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/op-1.1/multiprocess_prototype/__init__.py
$ machine_gate.sh medium op-1.1 ... pytest -q --tb=short test_close_coordinator_hazards.py
3 passed, 1 warning in 1.87s
$ machine_gate.sh medium op-1.1 ... pytest -q --tb=short <радиус раунда 1: 6 файлов> + test_close_coordinator_hazards.py
125 passed, 1 warning in 7.46s
```

125 = 122 из раунда 1 + 3 новых. Страж `test_root_close_order_golden` входит в радиус.

### Инъекции: наблюдено против предсказанного

Копия дерева в scratchpad, прогон `test_close_coordinator_hazards.py` + `test_close_coordinator.py` (33 теста). После прогона файл копии сверен с деревом (`cmp`: совпадает).

| Инъекция | Предсказано (лид, до прогона) | Наблюдено | Совпало |
|---|---|---|---|
| диалог всегда `WindowModal` | красные (1) и (3), (2) зелёный | `2 failed, 31 passed`: (1), (3) | да |
| диалог всегда `NonModal` | красный только (2) | `1 failed, 32 passed`: (2) | да |

Причины красных при «всегда `WindowModal`» (`--tb=line`):
- (1): `assert <..._StopProgressDialog(...)> is None` — `activeModalWidget()` возвращает диалог прогресса;
- (3): `assert ['unattended....й путь.', ...] == []` — сторож пишет `modal_closed`.

Так находка 2 из раунда 1 воспроизведена запуском (offscreen, Darwin): окно-модальный прогресс попадает под сторож. В раунде 1 это была гипотеза по чтению.

Слепой набор tester модальность не закрепляет: при «всегда `NonModal`» его 30 тестов зелёные. Модальность держит только авторский тест (2).

### Текст вопроса при рестарте UI (находка 3, принято как есть)

При рестарте UI с несохранёнными правками графа (`dirty` или `layout_unsaved`) диалог «несохранённые правки» показывает вопрос «Сохранить их перед выходом?» (`app.py`, `_build_close_coordinator`: `confirm_discard_topology_changes(reason="Сохранить их перед выходом?")`). Без несохранённых правок вопрос не показывается.

### Что осталось открытым (раунд 2)

- Немодальный прогресс без присмотра не блокирует ввод в главное окно. На стенде без присмотра оператора нет, это допустимо. Поведение на реальном дисплее Windows не проверено.
- Тест (3) подменяет приватные атрибуты модуля `unattended` (`_UNATTENDED`, `_log`, `_answers`): `_UNATTENDED` снимается при импорте, публичной ручки нет. При переименовании этих атрибутов тест (3) упадёт на `monkeypatch.setattr` (атрибута нет), а не пройдёт молча.
- В `unattended=True` вопрос `ask_force_stop` закреплён только на фейке. Настоящий `ask_force_stop_dialog` (окно-модальный `QMessageBox`) без присмотра не вызывается, поэтому сторож его не видит.

## Раунд 3 (ревью стадии 5, итерация 1 из 2; база HEAD `e609f70f4`)

### Правки по пунктам ревью

| П. | Файл | Что сделано |
|---|---|---|
| 1 (блокер) | `multiprocess_prototype/frontend/app.py` | Новая функция уровня модуля `_unwrap_status_reply(reply)` разворачивает конверт ровно на один уровень: не dict или внешний `success is not True` → как есть; `result` — dict с ключом `processes` → `result` (решает его `success`); иначе как есть. `_poll_status` в `_build_close_coordinator` возвращает `_unwrap_status_reply(reply)`. |
| 2 | `multiprocess_prototype/frontend/windows/main_window.py` | `closeEvent` с координатором вне `CLOSING`: сначала `request_close()`, затем состояние `CLOSING` → `_save_geometry()` + `event.accept()`, иначе `event.ignore()`. Причина: `quit_app` зовёт `window.close()` внутри этого же `closeEvent`, и Qt вложенный `close()` отбрасывает. |
| 3 | `app.py` | `ignore_names=frozenset({process.name, ORCHESTRATOR_PROCESS_NAME})`. Константа импортируется из `multiprocess_framework/modules/process_module/configs/observability_layers.py:107`, это направление prototype → framework. |
| 4 | `tests/test_close_coordinator_hazards.py` | Тест (4) `test_progress_hidden_after_commit_close_from_stopping`. |
| 5 | там же | Тест (5) `test_progress_shows_k_of_n_children`: 5 записей (gui, PM живы; worker_a мёртв; worker_b, worker_c живы) → текст «Остановка системы… 1 из 3». У фикстуры `make_coord` появился параметр `response`. |
| 6b | `multiprocess_prototype/frontend/shutdown/close_coordinator.py` | Докстринг `ask_force_stop_dialog`: оборванная фраза заменена («если координатор закрыл вопрос сам… `finished` всё равно вызовет `on_answer`; координатор этот ответ отбрасывает»). |
| 6d | `main_window.py` | `_close_coordinator = None` перенесён в начало класса, сразу после докстринга. |
| 6e | `close_coordinator.py` `_update_progress` | Диалог берётся в локальную `dialog` до `setValue()`. После `setValue()` проверка `self._progress is not dialog → return`: `setValue` модального диалога крутит `processEvents`, и внутри может прийти `commit_close`. |
| 6c | — | Литерал «за 2 с» в тексте вопроса оставлен, так требует спека. |

Новый файл `multiprocess_prototype/frontend/tests/test_close_coordinator_wiring.py`. Объекты настоящие: `app._build_close_coordinator` и `MainWindow`; `QSettings` во временном ini. Фейковые: `command_sender`, `process_manager_proxy`, процесс и `app` (`quit` — счётчик). Крестик — `window.close()`.
- `test_live_envelope_children_dead_quits_once` — конверт в живой форме: верхние ключи command, queue_type, request_id, result, sender, success, targets, type; в `result` — epoch, processes, success; процессы ProcessManager (жив), console_sink и ticker (мертвы). Проверки: `app.quit` ровно 1 раз, `CLOSING`, окно не видно, `shutdown_system` 1 раз, `shutdown_sent`, команда `{"cmd": "supervision.status"}`.
- `test_envelope_without_success_is_not_all_dead[inner_success_false | outer_success_false]` — контроль: за ≥ 4 опроса нет `quit`, состояние `STOPPING`, окно видно.
- `test_ignore_names_are_own_name_and_process_manager` (п. 3) — живы только `gui` и `ProcessManager` → окно закрывается.
- `test_x_that_commits_at_once_hides_window[send_shutdown_fails | backend_gone_during_confirm]` (п. 2) — после крестика `CLOSING`, `app.quit` 1 раз, окно не видно, геометрия сохранена.

### Прогоны

```
$ ruff check -q <5 файлов: close_coordinator.py, app.py, main_window.py, оба авторских теста>   -> код 0
$ python -c 'import multiprocess_prototype; print(multiprocess_prototype.__file__)'
/Users/twokrai/Project_code/Inspector_bottles/.claude/worktrees/op-1.1/multiprocess_prototype/__init__.py
$ machine_gate.sh medium op-1.1 ... pytest -q --tb=short test_close_coordinator_hazards.py test_close_coordinator_wiring.py
11 passed, 1 warning in 4.57s
$ machine_gate.sh medium op-1.1 ... pytest -q --tb=short <радиус раунда 1: 6 файлов> + hazards + wiring
134 passed, 1 warning in 10.20s
```

134 тестов, из них 5 в hazards и 6 в wiring. Остальное — радиус раунда 1 в состоянии `e609f70f4`: лид в раунде 2 дописал тесты в `test_close_coordinator.py` и `test_gui_process.py`, поэтому число не равно 125 + 8. Страж `test_root_close_order_golden` входит в радиус.

### Инъекции: предсказано против наблюдено

Копия дерева `scratchpad/inj3`: `git archive HEAD` + мои изменённые `.py`. Прогон 61 теста: `test_close_coordinator.py`, hazards, wiring, `test_main_window.py`. После матрицы копия сверена с деревом (`cmp` по всем изменённым `.py`: совпадает). Предсказания записаны до прогона: п. 1–2 — лид, полные списки красных — мои.

| Инъекция | Предсказано | Наблюдено | Совпало |
|---|---|---|---|
| п. 1: `_poll_status` без разворачивания (`return reply`) | test_live_envelope… (лид); я добавил test_ignore_names… (тот же путь через конверт) | `2 failed, 59 passed`: test_live_envelope_children_dead_quits_once, test_ignore_names_are_own_name_and_process_manager | да |
| п. 2: «всегда ignore» (`event.ignore()` вместо `accept`) | оба случая test_x_that_commits_at_once_hides_window | `2 failed, 59 passed`: [send_shutdown_fails], [backend_gone_during_confirm] | да |
| п. 3: `ignore_names` без PM | test_ignore_names…, test_live_envelope… | `2 failed, 59 passed`: те же два | да |
| п. 4: `finish()` убран из `commit_close` | hazards (4) | `1 failed, 60 passed`: test_progress_hidden_after_commit_close_from_stopping | да |
| п. 5: k и N местами | hazards (5) | `1 failed, 60 passed`: test_progress_shows_k_of_n_children | да |

Контрольные тесты конверта (внутренний и внешний `success False`) при инъекции п. 1 остаются зелёными. Это ожидаемо: без разворачивания закрытия нет ни в каком случае. Ловят они другую ошибку — разворачивание, которое не смотрит на `success`. Отдельной инъекцией это не проверял.

### Что осталось открытым (раунд 3)

- **Путь ответа GUI через `router.request` подтверждён только чтением кода.** `multiprocess_framework/modules/router_module/core/router_manager.py:1303-1313` (`reply_to_request`) собирает ответ `{"type": "response", "command": …, "sender": …, "targets": […], "queue_type": "system", "request_id": cid, "success": success, "result": result}` — те же ключи, что в живой форме ревьюера. Форма снята ревьюером через `backend_ctl`-драйвер, не через GUI. Живой `CommandSender.request_system_command` из процесса `gui` на Windows не запускался.
- Тест п. 2 [backend_gone_during_confirm] подменяет метод экземпляра `window.confirm_discard_topology_changes`. Работает это потому, что `confirm_discard` в `app.py` — лямбда, которая читает атрибут при вызове. Если лямбду заменить связанным методом, подмена перестанет действовать, и тест покраснеет на `CLOSING`.
- `_unwrap_status_reply` разворачивает ровно один уровень. Если PM когда-нибудь вложит конверт глубже, сработает только сторож тишины: успешные ответы есть, `processes` нет — окно ждёт без вопроса, пока PM отвечает. Сейчас такой формы нет.
- Проверка 6e (возврат после `setValue`, если диалог сменился) тестом не воспроизведена: нужен повторный вход через `processEvents` внутри `setValue`. Закреплена только чтением.
