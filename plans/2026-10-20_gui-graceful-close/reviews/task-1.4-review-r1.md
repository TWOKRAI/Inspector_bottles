# Task 1.4 — код-ревью, стадия 5, раунд 1 из 2

Ветка `feat/gui-close-1.4`, HEAD `ee6149ea3`, дифф `d9fb9d9da..HEAD`. Ревьюер: reviewer (opus). Код не правился, не коммитился.
Единственная запись — этот файл. Скретч-пробы и копии дерева с инъекциями — вне репозитория:
`/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/bb9f9445-8b5a-44e8-930d-1390dd2123f9/scratchpad/rev14/`
(`repro_driver_nested.py`, `repro_empty.py`, `repro_phase.py`, `inject.py`, `inj_Z/`, `inj_I14/`, `clean2/`).

## Вердикт: CHANGES REQUESTED

Находок: blocker 0, major 2, minor 3. Блокеров нет: PM-часть (потоки, гонки, ход стопа) выдержала проверку;
оба major — про границы: (M1) драйвер читает новые поля ответа не с того уровня конверта, (M2) правка сверх DESIGN
в `_set_system_stop_phase` держит корректность и не охраняется ни одним тестом.

## Что прогнано (воспроизведение)

Гейт `machine_gate.sh medium|light op-1.4-review`, интерпретатор основного `.venv`, `PYTHONPATH` = корень worktree, pytest по файлу.

| набор | итог |
|---|---|
| `test_system_shutdown_pre_stop.py`, 3 раза подряд | 7 passed (18,33 / 17,82 / 18,26 с), exit=0 x3 — флака нет |
| `test_pre_stop_contract.py` | 32 passed |
| `test_pre_stop_author.py` | 4 passed |
| `test_system_shutdown_force.py` / `_force_author.py` | 16 passed / 5 passed |
| `backend_ctl/tests/test_system_shutdown_driver.py` / `_driver_author.py` / `_driver_outcomes.py` | 4 / 2 / 1 passed |
| `python -m scripts.lifecycle_guards check --only g6` | 0 findings (G6 0), allowlist 72 записи — R4 не вырос |
| `sentrux check .` на чистом `git archive HEAD` | 43 rules checked, Quality 6069, `All rules pass`, exit 0 |
| G4 «threads without scope path» | 47 после SM x3; все 47 строк — `QueueFeederThread`, ни `pm-pre-stop`, ни `keyed-pm-pre-stop-0` |

Не гонялись (известно): heavy FL 9–10, Windows.

## Находки

### M1 [major, tests/spec] Драйвер читает `accepted` / `reason` / `mode` с верхнего уровня конверта, а живой ответ вкладывает их в `result`

`backend_ctl/driver.py:746` `raw_accepted = reply_dict.get("accepted", reply_dict.get("success"))`, `:751` `reply_dict.get("reason")`,
`:749` `reply_dict.get("mode", mode)`. `system_command` шлёт `process.command`; ответ PM строит `_handle_process_command.reply`
(`process_manager_process.py`, `reply_to_request(..., success=self._process_command_success(result), response_command="process.command.response")`),
то есть `{"type": "response", "success": <bool>, "result": {<ответ system.shutdown>}}`; `SocketClient.request` отдаёт этот конверт целиком
(`router_manager.py` `request` возвращает `pending.response`; `backend_ctl/protocol.py:43` `unwrap` прямо называет такую форму).
`success` конверта = `result["success"]` = `True` и на отказе `already_stopping` (`{"success": True, "accepted": False, ...}`).
Ввод -> наблюдаемый результат (`python $S/repro_driver_nested.py`):

```
flat (what the DR tests feed)                  -> accepted = False | polls = 1
nested (what PM process.command.response sends) -> accepted = True  | polls = 1
force-over-force nested                         -> accepted = True  mode = graceful (requested mode default graceful)
```

Следствия: (а) повтор `graceful` / `force` поверх `force` у драйвера читается `accepted: True`, хотя PM ответил `False` — противоречит DESIGN 6
и описанию MCP-инструмента (`mcp_tools.py` «False + already_stopping»); (б) `mode` в итоге всегда равен запрошенному; (в) `reason`/`phase`/`escalated`
драйверу не видны. Опрос при этом идёт (читается как `accepted True`), поэтому функционально стоп и итоги работают — дефект в публичном контракте
итога (`public-api-change`) и в слепоте тестов: `_ACCEPTED_REPLY` в `test_system_shutdown_driver_outcomes.py:35`, фейки в
`test_system_shutdown_driver.py` и `_driver_author.py` отдают ПЛОСКИЙ dict, которого вживую нет; L-smoke `test_system_shutdown_force_live.py:193`
(`accepted is True`) проходит через откат на `success` и дефект не ловит. Это урок «набор на фейках нужен хотя бы один тест на настоящих объектах» (project-rules §9).
Fix: брать `payload = _leaf_result(reply)` для `accepted` / `reason` / `mode` (ветку `error == "timeout"` смотреть по плоскому `reply`, как сегодня);
фейки DR и `test_system_shutdown_driver*.py` перевести на вложенную форму `{"success": True, "result": {...}}`, оставив один плоский как страж 0.2;
добавить ячейку: вложенный `already_stopping` -> `accepted is False` и опрос идёт; в L-smoke/FL проверять `res["mode"]` и, где возможно, поле, видимое только во вложенной форме.

### M2 [major, tests] Добавление сверх DESIGN в `_set_system_stop_phase` держит корректность и не охраняется тестом

`process_manager_process.py:675-682`: при выходе из `pre_stop` любым путём (в частности `_ChildrenStop._announce_phase("children", begin=True)` на внешнем событии)
вызывается `_exit_pre_stop_locked`. Без этого блока `_leave_pre_stop` потока шагов (`:783-795`) увидит фазу не `pre_stop`, вернёт `False`, и `pre_stop_step`
останется выставленным, а `deadline_at` не перебазируется. Break-injection Z (блок удалён в копии `inj_Z`, SM + author):
`11 passed` — ни одного красного. Наблюдаемое состояние после внешнего события в `pre_stop` (`python $S/repro_phase.py <корень>`):

```
HEAD:                phase=children pre_stop_step=None      deadline_in=5.0s
injection Z:         phase=children pre_stop_step='p1.home' deadline_in=60.0s
```

SM 3(б) этого не ловит: стенд не запускает корневой стоп (`_ChildrenStop`), переход делает `_finish_pre_stop` потока шагов. Страж `h3` покрывает только `_leave_pre_stop`.
Fix: авторский hazard-тест (в `test_pre_stop_author.py`): ход стопа `pre_stop`, шаг выставлен -> `pm._set_system_stop_phase("children")` -> `pre_stop_step is None`,
`deadline_at - time.time()` в [4,8; 5,0] (graceful) и неизменный срок для `mode == "force"`; имя инъекции Z — в отчёт.

### m1 [minor, quality/tests] Два пути взвода событий после шагов; ACCEPTANCE (1), (2), (10), (14) предсказывают неверно

`_run_pre_stop` (`:804-820`) зовёт `_finish_pre_stop()` в `finally`, и `submit(..., lambda _r: self._finish_pre_stop())` (`:1240`) зовёт его снова из `reply`
(`keyed_executor.py:371-385`: `_execute` зовёт `reply` и на нормальном выходе, и при исключении). На каждом обычном стопе `_finish_pre_stop` выполняется дважды.
Безопасно: `_leave_pre_stop` проверяет фазу под `_system_stop_lock`, `_set_stop_events` идемпотентен, `_publish_system_stop` сериализована
и пишет только изменившиеся ключи из снимка, взятого под её локом (`:846-879`); гонки с `force`-эскалацией на потоке приёма нет (оба под локом, `deadline_at` — по режиму).
Лишний `finally` не вреден, но и не нужен (отказ `submit` без запуска действия покрывает один `reply`). Воспроизведено (копия `inj_I14`, `finally` удалён):
SM `7 passed` (SM 2 не различает пути, как и написал исполнитель), авторский `h2` краснеет ИНАЧЕ — он зовёт `_run_pre_stop` напрямую
(`assert (False, False) == (True, True)`). Значит дефекта, замаскированного страховкой, по (14) нет, но ACCEPTANCE (14) «REDS 2» неверен.
Правка текста ACCEPTANCE (не кода): (1) 3(а) красная (отказ `submit` зовёт `reply` -> события -> предусловие «шаг не начался»); (2) 3 красная (событие -> `should_reject` `pm-pre-stop`);
(10) 7 красная (поток приёма занят шагами, 15 с не хватает); (14) «SM 2 зелёная; красной делает `h2` (прямой вызов)». Решение по коду (убрать `finally` или оставить два пути) — за лидом;
по принципу «меньше слоёв» достаточно `reply`, но тогда `h2` надо перевести на вызов через `submit`.

### m2 [minor, quality] Драйвер кончает опрос по пустому набору детей

`driver.py:820` `all_done = all(outcomes[name] in done_outcomes for name in names)` при `names == []` истинно. Снимок, где есть только `ProcessManager`
(`processes` без детей), даёт конец опроса на 1-м такте с `outcomes == {}`, `unconfirmed == []`: «всё подтверждено» по пустому множеству.
`python $S/repro_empty.py`: `only-PM snapshot -> {'outcomes': {}, 'unconfirmed': [], 'timed_out': False, 'pm_gone': True} polls= 1`.
В здоровом графе дети есть всегда, поэтому minor. Fix: `all_done = bool(names) and all(...)`; пустой набор — пропуск такта (ждать `done`/разрыв/срок).
Тест: ячейка DR с единственной строкой `ProcessManager`.

### m3 [minor, tests] «Настоящий ребёнок» собирает ответ вручную

REDS 1(а) идёт со spawn-процессом `AckChild` (зелёная), но `_pre_stop_ack_plugin.py::_handle` строит конверт ответа сам (`type/command/sender/targets/queue_type/request_id/success/result`)
и кладёт в системную очередь PM. Я сверил поля с `RouterManager.reply_to_request` (`router_manager.py:1304-1313`) — совпадают; запрос уходит без явного `queue_type`
и попадает в `system` по `_select_queue_type` (`router_manager.py:648-675`, `type == "command"`). Но авто-ответ настоящего роутера ребёнка (`_dispatch_command` -> `reply_to_request`)
ни одним тестом этой задачи не пройден; первый настоящий прогон будет в Task 1.4m (манифест). Fix: один тест SM/author с ребёнком на настоящем `ProcessModule` и зарегистрированной командой
(или явная запись в ADR-044 «авто-ответ ребёнка проверен только по коду») — решение лида.

## Слабые места лида 1–10

| № | вопрос | итог |
|---|---|---|
| 1 | повтор `graceful` вне `pre_stop` взводит события и отвечает `accepted: False` | Подтверждено как отклонение от буквы DESIGN 3, но не дефект: исполнитель назвал причину (страж Task 0.2 `test_system_shutdown_force.py:254-255`), ADR-044 п. «Повтор graceful» это фиксирует. Гонки begin ↔ `_set_stop_events` нет: begin под `_system_stop_lock`; повтор в окне между begin и событиями сам взведёт события (идемпотентно). Для драйвера `already_stopping` -> «опрашивать» верно — но живьём не достигается (M1). Та же асимметрия в ветке `force` без `_children_stop` (`:~1165-1175`, только двойники) — не воспроизводил как проблему. |
| 2 | двойной взвод событий (`finally` + `reply`) | Подтверждено (m1): двойной вызов `_finish_pre_stop` на каждом стопе, безопасен (идемпотентен, публикация сериализована, гонки с `_leave_pre_stop` нет). `finally` лишний, не опасный. |
| 3 | `_pre_stop_graceful_s` без лока; окно без перебазирования | Окно не найдено и не воспроизведено: фаза входит в `pre_stop` только из `_begin_system_stop` (None -> dict), для устаревшей подсказки нужен `_set_system_stop_phase` при `info is None`, а `with_steps` требует `not self._pm_stopping()`. Опровергнуто как гонка. НО добавление в `_set_system_stop_phase` не охраняется тестом (M2, воспроизведено). |
| 4 | драйвер: пустой набор, `{"success": False}` без причины, слабые ячейки, честность `unconfirmed`/`timed_out` | Пустой набор — подтверждено (m2). `{"success": False}` без `error`/`reason` = отказ, возврат сразу — по DESIGN 6, корректно. (е) при `now+1` и (г) слабы — подтверждено отчётом `injections-driver` (я его инъекции не повторял); (г) на плоском фейке к тому же слепа к M1. `unconfirmed`/`timed_out` по коду честны (`None` -> в `unconfirmed`, конец по сроку -> `timed_out True`, `pm_gone False`). |
| 5 | слепота инъекций (1), (2), (10), (14) | Предсказания (1), (2), (10), (14) править в ACCEPTANCE (m1); дефекта, замаскированного страховкой, по ним нет. Замаскированное нашлось в другом месте: блок в `_set_system_stop_phase` (M2) — инъекция Z зелёная. |
| 6 | потоки: G4, остановка `pm-pre-stop`, запоздалый ответ | `pm-pre-stop` в G4 не попадает (47 = `QueueFeederThread`). Исполнитель создан `executor_manager.create` -> принадлежит менеджеру (`work.own(... "executors")`, ADR-PM-055), закрывается корнем; шаг видит `_system_stop_event`/флаг `force` за <=50 мс (SM 3 зелёная). Запоздалый ответ: до подметания слот снимает ответ -> колбэк `closed` -> no-op; после подметания `_resolve_pending` не находит слот -> обычный путь `event_dispatcher`; слоты не копятся (`_take_pending` под локом, подметание на такте `receive()`). Остановка `pm-pre-stop` при взводе ТОЛЬКО `stop_event` (без `_system_stop_event`) — не проверена (см. «открытым»). |
| 7 | путь PM -> ребёнок -> ответ | Проверен SM 1(а) со spawn-ребёнком, но ответ ребёнка собран вручную (m3). Конверт: `sender` = имя PM, `queue_type` по умолчанию `system`, ответ адресуется в `sender`. Рестарт ребёнка посреди шага: запрос теряется, шаг кончает `timeout` по `timeout_s` (<=60 с), не виснет (чтением; тестом не покрыто). |
| 8 | публичный API, потребители | GUI шлёт `system.shutdown` без ожидания ответа (`process_manager_proxy.py:118`, `close_coordinator.py`); `probe_gui_stand_live.py:123` читает `res.get("success") is not False` — совместимо (`success` на отказе остаётся `True`). Потребителей, читающих `success` как «принято», нет, кроме драйвера (M1). `mcp_tools.py` (описание, `wait_timeout`) и `AGENTS.md` согласованы с кодом текстом, но обещают недостижимое `False + already_stopping` (M1). |
| 9 | правила проекта | G6 R4: 0 findings, новых `.kill()`/`.terminate()` в production нет (две `proc.kill()` в диффе — в тестовом `FakeProc`-коде SM). Широких `except` два, оба с `noqa: BLE001` на границе шага/потока шагов, не в кадровых циклах. Тексты ошибок без входных значений (`_error_text`, SM 7 зелёная). `sentrux check .` на чистом дереве: 43 rules, все проходят. |
| 10 | объём | Файлов вне FILES в production нет; внешних по списку: `multiprocess_framework/DECISIONS.md` (индекс, генерирует `scripts.sync` по DESIGN 7), `docs/handoffs/*`, отчёты `reviews/*`. Сверх DESIGN: блок в `_set_system_stop_phase` (обоснован, но не охранён — M2) и `window_s` в `_begin_system_stop` (нужен DESIGN 4). Причина `отменён` из словаря DESIGN 1 в коде не используется (отмена — INFO `прерван`), расхождение текста, не поведения. |

## Что осталось открытым / ненадёжно

- Живой путь не проверен: heavy FL 9–10 и Windows не гонялись (известно). M1 именно живой дефект — до FL он невидим для всех зелёных тестов.
- Остановка корня PM при взводе только `stop_event` (без `_system_stop_event`) во время шага не проверена: `_pre_stop_cancel_source` (`:732-742`) смотрит флаг `force` и
  `_system_stop_event`, но не `stop_event` и не `_children_stopping`; в таком пути шаг шёл бы до своего `timeout_s`, а `executor_manager.shutdown` ждал бы операцию.
  Достижимость этого пути в продукте не доказана (спавнер и `_on_parent_death` взводят оба события). Не находка — вопрос лиду.
- Операция `pm-lifecycle`, уже идущая к началу `pre_stop` (например `topology.apply`), работает параллельно шагам: предикат отклоняет только новые и ждущие. Принято DESIGN, не проверено.
- Инъекции драйвера 11–13, 17–19 я не повторял, верил отчёту `injections-driver`. PM-инъекции повторил только две (Z и (14)), в копии `git archive HEAD`, по одному прогону.
- Тайминговые ячейки SM (0,05 / 0,1 / 0,3 с) зелёные 3 из 3 на этой машине; под нагрузкой не мерил.
- Подтвердил вложенную форму ответа чтением кода (`_handle_process_command`, `reply_to_request`, `SocketClient.request`, `unwrap`), а не живым запуском стенда.

---

# Раунд 2 из 2

HEAD `d47465817` (`git diff ee6149ea3..HEAD`: PM `acc5201d9`, `c68061e0e`, `21bebb146`; драйвер `3f2b032c2`). Код не правился, не коммитился.
Скретч вне репозитория: `.../scratchpad/rev14/` (`r2base/` — копия `git archive HEAD`, `inject_r2.py`, `inject_14b_run.py`, `repro_r2_stopevent.py`, `r2_radius.log`).

## Вердикт: APPROVED

Находок раунда 2: blocker 0, major 0, minor 2 (оба — в OPEN_QUESTIONS, правки не требуют). M1, M2, m2 закрыты воспроизведением.

## Закрытие находок раунда 1 (инъекции на копии HEAD, по одному прогону)

Метод: `inject_r2.py` кладёт патч в копию `r2base`, гоняет файл через гейт `light`, возвращает файл. Базовая линия — 14 passed (8 author + 6 envelope).

| находка | инъекция | наблюдено |
|---|---|---|
| M2 (h5) | Z: убрать блок выхода из `pre_stop` в `_set_system_stop_phase` | `test_h5_phase_change_out_of_pre_stop_clears_step_and_rebases_graceful_only` красный, 1 failed / 7 passed |
| отмена по `stop_event` / `_children_stopping` (h6) | S: убрать ветку `own`/`_children_stopping` из `_pre_stop_cancel_source` | `test_h6_own_stop_event_without_system_event_cancels_step` красный, 1 failed / 7 passed |
| m1, путь `finally` (h7) | 14: убрать `finally` | красные h7, а также h2 и h6 (прямой вызов `_run_pre_stop`), 3 failed / 5 passed |
| m1, путь `reply` (h8) | R: `reply` = `lambda _r: None` | красный только h8, 1 failed / 7 passed |
| m1, оба пути | 14б: нет `finally` и `reply` не взводит | SM: красные 6 из 7 ячеек, среди них SM 2 (без событий падает всё, что их ждёт) |
| M1 | D1: драйвер читает плоский `reply_dict` | красные 3 из 6: `..already_stopping..`, `..reads_mode_from_result`, `..real_pm_and_router` |
| m2 | D2: `all_done` по `names` (пустое — истинно) | красный `test_only_process_manager_snapshot_does_not_end_the_poll`, 1 failed / 5 passed |

Каждый хазард-тест краснеет под своей инъекцией и только под ней (h7 и h6 краснеют ещё и под 14 из-за прямого вызова `_run_pre_stop` — безвредно).
Тайминг h5–h8: 6 прогонов author подряд — 8 passed x6 (0,75 с), флака нет. Окно h6 (`elapsed <= 0,1` при срезе 0,05) узкое, на этой машине держится.

## Новые риски, о которых спросил лид

(а) Безопасность `stop_event` / `_children_stopping` как источника отмены. В PM `stop_event` взводит только `_set_stop_events` (`process_manager_process.py:1262`);
вызывается из: `_shutdown_graceful` без шагов (шагов нет), путь `force` и запасной путь без `_children_stop` (оба СНАЧАЛА ставят флаг `_cancel_pre_stop`),
повтор `graceful` вне `pre_stop` (шаги не идут), `_finish_pre_stop` (после выхода из цикла шагов, из того же потока). Гонки «последний шаг идёт, а `stop_event` уже взведён» нет:
фаза выходит из `pre_stop` только после отмены или после цикла. `_children_stopping` ставит один `_ChildrenStop.request_stop` (`:5242`), ни разу не снимает; перед ним
`_announce_phase("children", begin=True)` — между ними мгновенное окно (миллисекунды), отмена видна на ближайшем срезе 50 мс. `stop_event.clear()` для PM в
`process_manager_module/process` и `process_module/core` нет — переиспользования старого взведённого события при рестарте нет. Внешние взводчики (раннер при смерти родителя, спавнер) — легитимный стоп.
Репродукция `repro_r2_stopevent.py`: `stop_event` взведён заранее, общий — нет -> `accepted True, phase 'children'`, запросов шагам 0 (шаг не стартует, без преждевременных запусков).
Вывод: преждевременного прерывания при легитимном `graceful` нет.

(б) Тест на настоящих объектах (`test_driver_reads_envelopes_built_by_real_pm_and_router`): зовёт НАСТОЯЩИЕ `ProcessManagerProcess._handle_process_command`, `_cmd_system_shutdown`,
`_ChildrenStop` и `RouterManager.reply_to_request` (`router.send` перехвачен); подменён только `CommandManager` (шим пробрасывает вложенный `data` в `_cmd_system_shutdown`, `_EnvelopeSender`
ставит настоящий `_handle_process_command`). Копии логики нет. Предусловия теста сами проверяют форму (`command == "process.command.response"`, `second["success"] is True`, `result.accepted is False`).
Тест регрессионный: под D1 краснеет. Не покрыто: звено `SocketBridgeAdapter.on_inbound` -> `SocketClient.request` (подтверждено чтением, см. M1 раунда 1).

(в) ADR-044 п. 4/8 против кода. п. 4 («два пути оставлены намеренно», h7 = `finally`/инъекция 14, h8 = `reply`/инъекция R, 14б — SM 2 красная) — совпадает с моими прогонами.
п. 5 («в фазе `pre_stop` их внутри PM взводит только путь `force` после флага») верно, но неполно: ещё `_finish_pre_stop` после цикла (минор, ниже). п. 8 — повтор `graceful`, `force`, `already_set` без `phase`,
запасной путь без `_children_stop` — совпадает с `_shutdown_graceful` / `_cmd_system_shutdown`. п. 7 (выход из `pre_stop` любым путём) — совпадает с `:675-682`.
Блок Break-injection в `tasks/1.4.md` (факты 1, 2, 10, 14, 14б, R, Z, S) совпадает с моими воспроизведениями.

## Радиус и проверки (гейт `medium`/`light op-1.4-review`, pytest по файлу)

| набор | итог |
|---|---|
| PM: `test_system_shutdown_pre_stop` 7, `test_pre_stop_author` 8, `test_pre_stop_contract` 32, `test_system_shutdown_force` 16, `_force_author` 5 | все passed |
| PM: `test_stop_wave_last` 11, `_guards` 16, `test_stop_budget` 30, `_child_stop_acceptance` 36, `test_process_root_pm_hazards` 20 (+1 xfailed), `test_supervision_status_system_stop` 34, `_hazards` 8, `test_supervision_instance_truth` 14, `test_supervision_strategies` 43 | все passed |
| PM: `test_lifecycle_command_classes` 23, `_fifo_acceptance` 10, `_fifo_hazards` 13, `_restart_reply` 2, `test_parent_death_acceptance` 7, `_hazards` 8 | все passed |
| PM: `test_pm_marks_gone_reader_acceptance` 8, `_hazards` 12, `test_pm_observability_routing` 26, `test_pm_responsive_during_children_stop` 8, `test_pm_stop_drains_own_queue_acceptance` 7 | все passed |
| PM: `test_root_stop_outcome_acceptance` 6, `_hazards` 8, `test_stop_outcome_acceptance` 15, `_hazards` 4 | все passed |
| backend_ctl: `test_system_shutdown_driver` 4, `_author` 2, `_outcomes` 1, `_envelope` 6, `test_mcp_server_sdk` 51, `test_mcp_full_and_rules_doc_parity` 1 | все passed |
| `sentrux check .` на чистом `git archive HEAD` | Quality 6069, `All rules pass` |
| `ruff check -q` и `ruff format --check` по 5 изменённым файлам (`driver.py`, `process_manager_process.py`, `pre_stop.py`, `test_pre_stop_author.py`, `test_system_shutdown_driver_envelope.py`) | exit 0 / `5 files already formatted` |
| `scripts/validate.py` | 2 FAIL — оба известные (память: теги, индекс BY-MODULE); других нет |

## Находки раунда 2 (minor, в OPEN_QUESTIONS)

- m4 [minor, quality] Пустой набор детей: исправление `all_done = bool(outcomes) and all(... outcomes.values())` считает по объединению всех виденных детей, а не по текущему снимку.
  Ребёнок, исчезнувший из реестра без итога, теперь держит опрос до `done` / разрыва / срока (раньше опрос кончался). Это честнее (имя в `unconfirmed`), но на пустом реестре после ухода детей
  без `done` опрос идёт до `wait_timeout`. Воспроизводить как проблему нет оснований (`done` объявляется до закрытия message_processor); пометить в OPEN_QUESTIONS.
- m5 [minor, docs] ADR-044 п. 5 перечисляет внутрисистемных взводчиков `stop_event` в `pre_stop` неполно (нет `_finish_pre_stop`, который взводит его сам после цикла). Не влияет на код.

Не закрыто из раунда 1 и оставлено лидом: m1 (два пути взвода) — принято, охраняется h7/h8; m3 (`AckChild` собирает ответ вручную; авто-ответ настоящего роутера ребёнка тестом этой задачи не пройден) — в OPEN_QUESTIONS, живой прогон придёт с Task 1.4m.

## Что осталось открытым / ненадёжно (раунд 2)

- Heavy FL 9–10 и Windows не гонялись (известно); `test_cv_threads.py` 6 красных — те же, что на чистом main (не гонял, принято со слов лида).
- M1 теперь проверен на конверте из настоящих `_handle_process_command` + `reply_to_request`; звено сокетного моста (`SocketBridgeAdapter` -> `SocketClient.request`, вкладывающее конверт PM в `result`) подтверждено чтением, не живым стендом.
- Инъекции раунда 2 — по одному прогону, на копии `git archive HEAD`; тайминговое окно h6 (0,1 с) тонкое, держится на этой машине (6 из 6), под нагрузкой не мерил.
- Останов корня PM при взводе `stop_event` во время шага теперь покрыт h6 на двойнике; на настоящем корне PM (через `run_process_function`) не проверен.
