# Task 1.4 — отчёт слепого тестера (MODE: red)

Заголовок разобран: MODE=red, INTERFACE=none, MODULE_CONTRACT=public-api-change, TASK=1.4,
PLAN=plans/2026-10-20_gui-graceful-close/plan.md. Источник контракта: REDS/ACCEPTANCE/TESTS/OUT OF SCOPE задачи
(строки 163–260) и публичные имена из брифа; interface.py нет — «testing against spec text only». DESIGN/FILES/TRAPS,
reviews/*, design/amendments, handoffs, reports, чужие worktree и git-история после d9fb9d9da не читались.
Реализации `pre_stop` в коде нет и не искалась (при чтении `_cmd_system_shutdown` для обвязки мелькнули заготовки
`pre_stop_step`/`phase` хода стопа от Task 1.2a — это существующий код).

## Файлы

- `multiprocess_framework/modules/process_manager_module/tests/test_system_shutdown_pre_stop.py` (SM, новый): REDS 1–7.
- `multiprocess_framework/modules/process_manager_module/tests/_pre_stop_ack_plugin.py` (новый, хелпер, не тест):
  `AckChild` — настоящий spawn-ребёнок REDS 1(а) (в брифе «`_pre_stop_ack_plugin`»; образец `LifecycleChild`, а не
  `_hung_child_plugin`: тот — `GenericProcessApp` для живого стенда, здесь нужен лёгкий класс для PM в процессе теста).
  Лежит рядом с SM, в списке «три файла + отчёт» его не было — нужен лиду в коммите.
- `backend_ctl/tests/test_system_shutdown_driver_outcomes.py` (DR, новый): REDS 8.
- `backend_ctl/tests/test_system_shutdown_force_live.py` (FL): дописаны ячейки 9 и 10 (+91 строка, чужие тесты не тронуты).

## Команды (все через `machine_gate.sh`, `.venv/bin/python`, `PYTHONPATH=<worktree>`, по файлу)

```
machine_gate.sh medium op-1.4-tester .venv/bin/python -m pytest -q --tb=no -rf <SM>   -> 7 failed in 16.3 s / 16.1 s (2 прогона, одинаково)
machine_gate.sh light  op-1.4-tester .venv/bin/python -m pytest -q --tb=no -rf <DR>   -> 1 failed in 0.23 s / 0.21 s (2 прогона, одинаково)
machine_gate.sh light  op-1.4-tester .venv/bin/python -m pytest -q -rs <FL>           -> 5 skipped (нет --backend-live), собираются 5 ячеек
ruff check + ruff format --check по четырём файлам -> чисто
```
Живой прогон FL (`--backend-live`, heavy, порты 7920–7929, окно стенда) НЕ гонял: нужна бронь окна, в брифе её нет.

## Результат: REDS -> тест -> итог -> причина первой упавшей строки

Ячейки собирают список `problems` и падают одним ассертом в конце (виден каждый подсценарий, а не только первый).

| REDS | тест | итог | причина (что видно в красном до правки) |
|---|---|---|---|
| 1 | SM::test_events_order_by_mode | красный | (а) `AssertionError`: ребёнок увидел `system_stop_event`, но шаг до него не дошёл (в метке только `event_seen`, нет `recv`/`reply_sent`) — событие взведено без ожидания шагов. (б) ответ без `phase: 'children'`: `{'success': True, 'message': 'Shutdown initiated'}`. Время событий в (б) и вся часть (в) — зелёные (стражи) |
| 2 | SM::test_step_failures_warn_and_continue_finally_sets_events | красный | `AssertionError`: для каждого из шагов 1–6 «WARNING 0 шт., ожидалась ровно одна» (шагов нет); «ERROR с RuntimeError: 0 шт.» |
| 3 | SM::test_force_or_external_event_cancels_running_step | красный | `AssertionError`: (а) предусловие «1-й шаг не начался за 0,5 с» и ответ force `{'success': True, 'message': ..., 'mode': 'force', ...}` без `accepted`/`escalated`; (б) предусловие «1-й шаг не начался» |
| 4 | SM::test_reply_immediate_status_responsive_second_graceful_rejected | красный | `AssertionError`: ответ первого graceful без `accepted`/`phase`; `system_stop.phase == 'children'`, `pre_stop_step is None` (шага нет); второй graceful отвечает `Shutdown initiated`, а не `already_stopping`; события уже взведены |
| 5 | SM::test_lifecycle_commands_rejected_during_pre_stop | красный | `AssertionError`: «начало шага не наблюдается: ребёнок-заглушка не получил команду шага». Страж «без стопа принимаются» — зелёный. ВНИМАНИЕ: сами отказы `system_stopping` сегодня уже выдаются (события взводятся сразу), ячейка красная только по предусловию «шаг идёт» — это то, что REDS называет в инъекции (1) «начала шага нет» |
| 6 | SM::test_deadline_at_pre_stop_then_children | красный | `AssertionError`: «фаза pre_stop не наблюдается» (сразу `children`); после перехода `deadline_at - now = 4.002`, ожидалось [4,8; 5,0] |
| 7 | SM::test_pre_stop_schema_skips_invalid_with_error_without_value | красный | `AssertionError`: ERROR `pre_stop[...]` 0 шт., ожидалось 11; для PM-Б ожидалась одна ERROR про сумму; ничего не исполнено (шагов нет) |
| 8 | DR::test_driver_merges_snapshots_unconfirmed_timed_out_accepted | красный | (а) `outcomes=None`; (а'), (в) `KeyError: 'timed_out'`; (б) `TypeError` (`outcomes` None); (г) «supervision.status опрошен 0 раз»; (е) `TypeError` — `wait_timeout=None` сегодня не поддержан (`float(None)`); (ж) `KeyError: 'unconfirmed'`. (д) — страж, зелёный |
| 9 | FL::test_force_with_hung_child_honest_outcomes | не гонял (живой), собирается, в обычном прогоне пропущен | — |
| 10 | FL::test_graceful_wait_returns_all_exited | не гонял (живой), собирается, в обычном прогоне пропущен | — |

Падений ДО тела теста нет: все красные — по содержанию (в теле, на ассертах). TypeError/KeyError допущены только там,
где REDS их называет (8(в), 8(ж)); TypeError в 8(б) и 8(е) — следствие сегодняшнего `outcomes=None` / `wait_timeout=None`.

### Что проверено на обвязке (без зелёной реализации)

Реализации `pre_stop` нет, поэтому «зелёный» путь тестов сам по себе не наблюдался. Проверил механику обвязки скретч-
скриптами вне репозитория (`<scratchpad>/plumbing.py`, `plumbing2.py`):
- заглушка в реестре PM получает запрос из `router_manager.request_async(... targets=[имя])`, ответ ack/nack
  резолвит колбэк PM (ack через 0,21 с при задержке 0,2; nack — 0,01 с; молчащая — `timeout` на 1,01 с); шпион `send`
  видит все три запроса;
- настоящий spawn-ребёнок `AckChild`: ответ через 1,02 с (`success: True`), метка `recv`→`reply_sent`, `event_seen`
  пишется через ~0,6 с после взвода общего события (последнее — в скретче через `system_stop_event.set()`).

## Допущения о контракте (проверьте при реализации; не угадывались молча)

1. `pre_stop` лежит в `config` PM рядом с `shutdown_timeout` (`get_config("pre_stop")`); в тестах это `config={"pre_stop": [...]}`.
2. Запрос шага уходит через `router_manager.send` с `targets=[<process>]` и командой шага на верхнем уровне сообщения
   (допускается `data.command`/`data.target`). От этого зависят шпион, подмена исхода отправки для шагов 3 и 6
   (исключение `ValueError` / `{"status": "error", "reason": ...}`) и вся проверка «запрос не ушёл».
3. Поле итога в записи процесса `supervision.status` — `stop_outcome` (так оно в `test_restart_verified.py`);
   в REDS оно «outcome». Если драйвер читает другое имя, DR (а), (б), (г) красные не по делу.
4. Разрыв в 8(б): `supervision_status` бросает `BackendUnavailable` и `connection_lost` становится `True`.
5. Часы драйвера 8(е): подмена атрибута `time` модуля `backend_ctl.driver` объектом `monotonic/time/sleep`.
6. REDS 2, шаг 3: класс исключения в тексте — `ValueError` (REDS: `исключение <Класс>`); WARNING ищется подстрокой
   `pre_stop: шаг '<process>.<command>' — <причина>`, допускается хвост после причины.
7. REDS 4: «второй graceful → `{"success": True, "accepted": False, "reason": "already_stopping", "phase": "pre_stop"}`»
   проверяется как вхождение этих четырёх пар в ответ, не как равенство словарей.
8. REDS 6: «шаги 0,5 + 0,7 с» = `timeout_s` двух молчащих шагов (сумма 1,2 с даёт `deadline_at − started_at`).
9. Шаги в SM-ячейках 2–7 идут к «заглушкам»-детям (двойник ОС-процесса в реестре PM + поток с очередями SRM), а не к
   настоящим spawn-процессам; настоящий ребёнок — только в 1(а). Решение по цене spawn (около 2–3 с на ребёнка).

## Вопросы к лиду (REDS противоречит сам себе или неоднозначен)

1. **REDS 1(б): «стражи, зелёные и до правки» и «ответ `phase: "children"`» несовместимы.** Сегодняшний ответ
   `{"success": True, "message": "Shutdown initiated"}` поля `phase` не несёт. Я проверяю время событий (зелёное до правки)
   и `phase == "children"` (красное до правки) в одной ячейке. Если страж должен быть зелёным целиком — уберите `phase` из (б)
   (или вынесите в отдельную ячейку).
2. **REDS 5: красным остаётся только предусловие «шаг идёт».** Сами отказы `system_stopping` сегодня уже выдаются
   (взвод событий сразу). Согласно инъекции (7) («`should_reject=self._pm_stopping` прежний → REDS 5 красный») это
   предсказание тоже не выполнится на сегодняшнем коде по отказам: тест различит инъекцию (7) только если в фазе
   `pre_stop` `_system_stop_event` ещё НЕ взведён и `_children_stopping` False. Нужна проверка лидом инъекции (7).
3. **Имя поля итога** (`stop_outcome` или `outcome`) — допущение 3. Назовите литерал.
4. **REDS 7:** запись [3] — `NaN`, запись [4] — `True` проверяются как «ERROR без значения»; слова из запретного списка
   (`60.0001`, `nan`, `True`, `"5"`, `[1]`, `zz_extra`) ищутся подстрокой по тексту ERROR `pre_stop[...]` — допускает ложное
   срабатывание, если причина в тексте (русская) случайно содержит `nan`; такого не вижу, но не доказано.
5. **Живые FL 9–10:** поле `outcomes` в живом результате драйвера — словарь только детей (без `ProcessManager`)? FL 10
   требует `outcomes` непустым и все значения `exited`. Если в нём может быть `ProcessManager` — скажите.

## Что осталось открытым / ненадёжно

- **Ни одна ячейка не видела зелёной реализации.** Красные доказаны по содержанию, обвязка (запрос → заглушка → ответ,
  spawn-ребёнок → метки) проверена скретчем, но полный зелёный путь (потоки `pm-pre-stop`, переход фаз, схема) — только
  после реализации. Любая ошибка в моих допущениях 1–2 даст красное и ПОСЛЕ правки — тогда это вопрос ко мне, не к коду.
- **Флак-риски (macOS, допуски из REDS):** ответ первого graceful ≤ 0,1 с (REDS 4: зонд опрашивает очередь с шагом 0,02 с);
  события ≤ 0,05 с после ответа (REDS 1(б), (в)); отмена шага ≤ 0,1 с (REDS 3: `_wait_until` с шагом 5 мс); окно
  `deadline_at` ± 0,05 с (REDS 6). На загруженной машине возможны ложные красные; зелёной реализации для замера нет.
- **REDS 1(а), верхняя граница `ответ + 0,3 с`:** метка `reply_sent` ставится ДО `queue.put` (нижняя граница `event_seen ≥ reply_sent`
  тем самым соблюдена с запасом); верхняя граница включает время доставки ответа PM и опрос ребёнком события (5 мс).
- **Не покрыто:** подделка `_set_pre_stop_step` в REDS 2 — `getattr(..., None)`: до правки метода нет, подмена тихо
  не срабатывает (красное по другим признакам). Поток `pm-pre-stop` и его счётчик не проверяются (это hazard-тесты автора).
  Публикация `system.stop.*` в стор не проверяется. Значения `args` в логах проверены только по WARNING/ERROR PM.
- **Слабое место:** в SM `process.restart` над заглушкой падает по другой причине (класс `fake.Child` не грузится) —
  страж проверяет лишь «отказ не `system_stopping`»; монитор PM в ячейках с `process.stop` может пытаться перезапустить
  умершую заглушку (шум `Failed to load process class 'fake.Child'` в stderr, на результат не влияет).
- **Живой FL 9 «тот же стенд»:** при зависшем `storage` итог `terminated`/`killed` зависит от того, успеет ли PM
  зафиксировать его до закрытия сокета; тест засчитывает и `unconfirmed` (как в ACCEPTANCE), число подтверждённых
  итогов печатается.
- Существующий live-страж Task 0.2 `test_driver_system_shutdown_live_smoke` требует `res["outcomes"] is None` для
  `force` — после Task 1.4 (`outcomes` — словарь при `wait=True`) он станет красным. Чужой тест не менял; решение лида.
- Break-injection своих ячеек не делал (по брифу — лид).
