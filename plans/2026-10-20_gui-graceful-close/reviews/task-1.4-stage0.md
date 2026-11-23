# Ревью стадии 0 — Task 1.4 (`pre_stop`, `force` прерывает шаг, честный итог в `backend_ctl system_shutdown`)

- **Режим:** `MODE: plan` на одном файле `plans/2026-10-20_gui-graceful-close/tasks/1.4.md`; reviewer, раунд 1 из 2.
- **Дерево:** `main` = `2d663a497` (задача 1.3 влита: `61faf8f0e`). Чтение, `git grep`, `Read`; тесты и стенд не запускались, ничего в репозитории не правилось.
- **Вердикт: CHANGES REQUESTED** (17 находок: 5 блокеров, 9 major, 3 minor).
- **Главный итог.** Бриф описывает шаг `pre_stop` как «`_send_child_command` с `timeout_s`», а этот метод не ждёт ответа и таймаута не знает. Требование п. 4 к LSO 1.9b в коде нет и в плане LSO нет ни одного упоминания `pre_stop`; закрыть его нужно в самом `process_manager_process.py`, и оно спорит с выбором исполнителя шагов (п. 2). Шаг 6 останавливает опрос по `alive is False`, а контракт ADR-PMM-042 прямо говорит, что так итог последнего ребёнка не виден. Живой пункт приёмки ждёт Task 2.2, которая сама ждёт 1.4.

## 1. Чек-лист (для файла задачи: a, d, f, i, ii, iii)

| Пункт | Ответ | Где |
|---|---|---|
| (a) приёмка несёт команду/литерал | частично | SM REDS 6/7, FL REDS 9/10 — литералы есть; для `deadline_at` в `pre_stop`, `accepted`/`phase`, границ `timeout_s` и для DESIGN п. 4 литералов нет (пп. 5, 11); живой пункт ждёт чужой задачи (п. 4) |
| (d) `Module contract`, `Handoff`, `Gate`, `Dependencies` | частично | `Dependencies` без 1.1a (шаг 6 ссылается на «Task 1.1», ответ весь стоп даёт 1.1a, ADR-PMM-040); `Gate: medium + heavy`, а `TESTS` — класс `medium` и путь Windows (п. 16) |
| (f) `OUT OF SCOPE` не пуст и не повтор `Goal` | да | |
| (i) у каждого решения DESIGN есть причина | нет | п. 1 (зачем явный `initiator`), п. 2 (почему `KeyedExecutor`, ключ `"system"`, события после шагов), п. 5 (почему отказ старта, почему 60 с) — причин нет (пп. 7, 9) |
| (ii) решение не ломает инвариант модуля | нет | п. 5 ломает «один сбой не роняет соседа» (п. 9); п. 4 в варианте «общий предикат» меняет семантику `stop_abort` и отказа спавна (п. 2); п. 1 ломает точные `==` пяти существующих тестов (п. 10) |
| (iii) тексты ошибок без входных значений | да, с оговоркой | формат «`pre_stop[<i>]: <поле> — <причина>`» годен, если причина — `msg` pydantic без `input_value` (образец `ExecutorManager.create`, `worker_module/README.md:264`); в брифе это не сказано (п. 9) |

## 2. Якоря: «в брифе → сейчас» (`main` `2d663a497`)

| В брифе | Сейчас | Примечание |
|---|---|---|
| `_cmd_system_shutdown` ~:939 | **:939-1007**; события взводятся безусловно **:1002-1004**; `_begin_system_stop` вызов :999 | порядок «ход стопа до событий» уже есть (:997) |
| `_begin_system_stop`/`_escalate_system_stop`/`_set_pre_stop_step` ~:597-670 | :597 / :623 / **:662**; от 1.3 добавлены `_shift_system_stop_deadline` :637, `_set_system_stop_phase` :651 | `phase` по умолчанию `"children"` (:597) |
| DESIGN 1: «новый аргумент `initiator` (по умолчанию `sender`)» | **значение по умолчанию уже есть**: `_EnvelopeSender` :73-79, :961-966 → `system_stop.initiator` (1.2a) | нового — только явный аргумент (п. 7) |
| DESIGN 3: `system_stop.pre_stop_step` | поле :615, помощник `_set_pre_stop_step` :662 — **есть** | «ставит Task 1.4» — вызов, не новое поле |
| DESIGN 6: `stop_outcome` в `supervision.status` | **есть**, :1094 (Task 1.2), плюс `stop_wave` :1096, `stop_deadline_at` :1097 | |
| шаг 6: `supervision_status` (`:1042`) | **`backend_ctl/driver.py:1105`** | якорь устарел (лид знает) |
| `driver.system_shutdown` ~:680 | **:681-742** | `accepted` считается из `success` (:717-720) |
| исполнитель | `pm-lifecycle`: `serial=True`, `should_reject=self._pm_stopping` — **:557-561**; предикат **:568-575** | п. 2 |
| `_send_child_command` | **:3265-3288**, «Fire-and-forget … НЕ подтверждение применения» (:3269-3273) | п. 1 |
| `_run_when_child_ready` | :1965-2033, возвращает `bool` «поставлено в очередь / выполнено сразу» | п. 1 |
| ADR | заняты 038–043 (`DECISIONS.md:2325` = 043); следующий свободный — **ADR-PMM-044** | бриф без номера (п. 15) |
| внешний срок спавнера | `ProcessSpawner.stop()` `launcher/spawner.py:~199-212` (`outer_s` = 8,5 / 10,5 с) | `pre_stop` в него не входит (п. 12) |

## 3. Числа ACCEPTANCE против кода

- SM REDS 6 («ответ ≤ 100 мс при шаге 5 с»): достижим, если `_cmd_system_shutdown` возвращается до шагов. `system.shutdown` — класс R/S (в `_LIFECYCLE_COMMANDS`/`_TRANSITION_COMMANDS` его нет, `process_manager_process.py:716-735`), исполняется на потоке приёма и отвечает после возврата функции (`_handle_process_command`, :3810-3818). Условие — ни одного блокирующего вызова до `return`.
- SM REDS 7 («`supervision.status` ≤ 300 мс во время шага»): `message_processor` в фазе `pre_stop` жив (события ещё не взведены), поэтому достижим, если шаг не на потоке приёма.
- FL REDS 9 (`elapsed_s ≤ 3,5`): в Task 0.2 тот же сценарий (`_hung_child_plugin`, `force` 1,0 с) принимался как «выход PM < 4,0 с, медиана ≤ 2,5 с» (`test_system_shutdown_force_live.py:5-9`). Граница 3,5 для **одного** прогона жёстче собственной огибающей 0.2, а `elapsed_s` теперь меряет другое (до конца опроса, не до выхода PM). Прогонов «N из N» в брифе нет (п. 13).
- FL REDS 10 (`inspection_full`, 7 из 7 `"exited"`): зависит от пп. 3 и 13.
- Окна `5,0 / 7,0 / 9,0 / 8,5 / 10,5` (ADR-PMM-031/043) `pre_stop` не меняет: область `children` открывается после шагов, внешние часы спавнера идут от `spawner.stop()`, который сам взводит событие и шаги обходит. Это верно, но в DESIGN не записано (п. 12).

## 4. Находки

### Блокеры (`spec`)

**1. [DESIGN 2, TRAPS] Шаг «запрос с `timeout_s` через `_send_child_command`» нереализуем: метода-запроса с ожиданием ответа нет.**
`_send_child_command` (`process_manager_process.py:3265-3288`) кладёт билет в очередь ребёнка и возвращает `bool` доставки; docstring :3269-3273: «Fire-and-forget … НЕ подтверждение применения — синхронный сбор ответа ребёнка в хендлере PM заблокировал бы message_processor».
Вход: `pre_stop: [{process: devices, command: robot_park_all, args: {}, timeout_s: 35}]`, graceful `system.shutdown`. Наблюдаемый результат по DESIGN: шаг «выполнен» за миллисекунды (`True`), события взводятся, `process.stop` идёт, пока робот едет домой. Это ровно тот вариант «ответ-допуск», который заявка Р2 отвергает (`Services/device_hub/DECISIONS.md:231-239`: «шаг `pre_stop` ждёт ответ»). `timeout_s` не к чему привязать.
Единственный запрос-ответ во фреймворке — `RouterManager.request(message, timeout)` (`router_module/core/router_manager.py:1048-1135`: блокирует поток, `correlation_id`, при таймауте `{"success": False, "error": "timeout"}`; с потока приёма бросает `RouterReentrantRequestError`, :1040-1046; ответ разбирает `receive()` на `message_processor`) и `request_async` (:1139). Ответ ребёнка придёт через `reply_to_request` (:1274).
TRAPS предлагает `_run_when_child_ready` (:1965-2033): он возвращает «поставлено в очередь / выполнено сразу», а не результат действия; действие, отложенное на воркер готовности, не вернёт ответ потоку исполнителя, который его ждёт. Два механизма из брифа вместе не работают.
Замена DESIGN 2: «Шаг: (а) дождаться готовности ребёнка (`_child_ready_event(name)`, не дольше остатка `timeout_s`; ребёнок в переходе — тот же ожидатель, не `_run_when_child_ready`); (б) `RouterManager.request_async`/`request` с остатком `timeout_s` с потока исполнителя шагов (не с потока приёма); (в) ожидание — `Event.wait` по событию отмены и по ответу, НЕ слепой `request(timeout)`; ответ `success: False`/`error` → WARNING, следующий шаг; ответ после таймаута — «опоздавшая почта» в системной очереди PM, это записать в ADR». Добавить RED на «шаг ждёт ответ ребёнка» (ответ приходит через 1,0 с — события взводятся не раньше).

**2. [DESIGN 4, 2] Требования п. 4 к LSO 1.9b в коде нет; это не требование к 1.9b; «ESCALATION -> cto» адресована не тому; исполнитель шагов спорит с предикатом.**
`design.md` → «Соседи» (строка Task 1.9b) называет требование «в фазе `pre_stop` очередь отклоняет новые команды жизненного цикла с `reason: "system_stopping"`». В плане LSO упоминаний `pre_stop` нет (`git grep pre_stop -- plans/lifecycle-stop-ownership.md plans/lifecycle-stop-ownership` — 0). В коде `should_reject` задаёт сам PM: `manager.create("pm-lifecycle", {... "serial": True, "max_pending": _L_CAP + _T_CAP}, should_reject=self._pm_stopping)` (:557-561); `_pm_stopping()` = `_system_stop_event.is_set() or _children_stopping` (:568-575). По DESIGN 2 события взводятся **после** шагов, значит всю фазу `pre_stop` предикат `False`.
Вход: во время шага `robot_park_all` (35 с) пришли `process.stop devices`, `process.restart camera_0`, `topology.apply`. Наблюдаемый результат: ни одна не отклонена, все встают в очередь/идут; `process.restart devices` убивает ребёнка, чей шаг ждёт ответа; `topology.apply` пересоздаёт набор процессов под шагом. (Монитор тоже может перезапустить упавшего `devices` во время шага.)
Правка — в `process_manager_process.py` (он в FILES), и она сталкивается с п. 2 DESIGN двумя способами:
- если шаги идут в **тот же** `pm-lifecycle` (ключ `"system"`), сам исполнитель, отклоняющий всё в `pre_stop`, отклонит и шаги (`submit` зовёт `should_reject`, `worker_module/README.md:188`); а при `serial=True` шаг 35 с занимает единственного рабочего и все `process.*` встают за ним до `max_pending`, потом `executor_busy`;
- если расширить общий `_pm_stopping()` фазой `pre_stop`, поведение меняется у семи потребителей предиката: `stop_abort` (:226), отказ спавна (`_spawn_refused_after_system_stop` :4167 — `create_process` :4154, `start_process` :4174, `restart_process` :4262), циклы ожидания (:4663, :4684, :4819), ветка :2322 — ADR-PMM-039 D4 (`DECISIONS.md:1983-1998`) читает их как «системный стоп начат».
Замена: «(а) шаги идут в **отдельном** `KeyedExecutor` (`executor_manager.create("pm-pre-stop", {"serial": True, "max_pending": N})`, собственный `should_reject` = флаг отмены); (б) в `pm-lifecycle` передать новый предикат `_lifecycle_rejected() = _pm_stopping() or <фаза хода стопа == "pre_stop">` (:560); `stop_abort` и отказ спавна не трогать, если лид не решит иначе — записать в ADR; (в) из DESIGN 4 убрать «если 1.9b не даёт — ESCALATION -> cto»: требование закрывается в 1.4, а вопрос «нужен ли отказ спавна/`stop_abort` в `pre_stop`» — к лиду». RED на п. 4 в REDS нет вообще (п. 11).

**3. [DESIGN 6] Условие выхода из опроса `alive is False` противоречит контракту ADR-PMM-042; итог последнего ребёнка опросом не виден; строка PM в `processes`.**
ADR-PMM-042 «Предел контракта» (`DECISIONS.md`, раздел 042): «между реальной смертью и её наблюдением группой (<= `STOP_POLL_S`) бывает `alive=false, stop_outcome=null`»; «все остановлены» = `stop_outcome` ∈ {`exited`, `terminated`, `killed`}; итог последнего медленного ребёнка опросом не виден (`plan.md`, запись 2026-11-08 о 1.2).
Вход: шаг 6 опрашивает каждые 100 мс до «`alive is False` у всех детей». Ребёнок X умер, группа ещё не подтвердила → `alive False` у всех → цикл выходит → `outcomes[X] = None`. Если подтвердила, но `message_processor` закрывается раньше следующего опроса (100 мс; в окне между концом области `children` и `_WorkersStop`), опрос не успевает: `outcomes` берётся из «последнего снимка», где у X `null`.
Отсюда FL REDS 9 (`outcomes[hung]`) и FL REDS 10 (7 из 7 `"exited"`) — недетерминированно красные: чем медленнее ребёнок, тем вероятнее `null` именно у него.
Второе: `_cmd_supervision_status` выдаёт запись PM (`alive: True`, :1075-1080; имя входит в `names` :1055). «alive False у всех» при строке PM не наступает никогда — цикл идёт до разрыва сокета или `wait_timeout` 20 с.
Замена DESIGN 6 (нужно решение лида, три варианта): (А) конец опроса — у каждого ребёнка (имена без PM) `stop_outcome` ∈ {`exited`,`terminated`,`killed`} либо `system_stop.phase == "done"`, либо разрыв; `outcomes[name]` — последнее **не-`null`**, виденное по имени (объединение снимков, не только последний); имя без итога — `None` и в результат поле `unconfirmed: [имена]`; FL REDS 10 переформулировать в «все, у кого итог подтверждён, — `exited`; `unconfirmed` пуст на здоровом графе»; (Б) сузить окно: опрос 25–50 мс после первого `alive False`; (В) PM публикует итоги в стор при `done` (вне 1.4: новая запись контракта). Рекомендую (А)+(Б). Без этого приёмка FL 9/10 не воспроизводима.

**4. [ACCEPTANCE] Живой пункт требует Task 2.2, а 2.2 идёт после 2.1, которая идёт после 1.4: круг; сам пункт про GUI, не про код 1.4.**
«Живьём после Task 2.2 (GUI-стенд, dirty граф, БЕЗ `INSPECTOR_GUI_UNATTENDED`, 5 из 5) … модальных окон 0 (журнал `gui`)» — `plan.md`: 2.1 «после 1.2, 1.4», 2.2 «после 2.1». `Dependencies` 1.4 об этом молчит.
Вход: Task 1.4 закрыта по всем REDS. Наблюдаемое: статус остаётся `[PENDING]` до 2.2 (требование стенда). Кроме того, «модальных окон 0» зависит от реакции GUI на стоп извне (design.md E: «Никаких вопросов»; H1 — `app.quit()` → `closeEvent`), которую делают 1.1/2.1/2.2, а не `pre_stop` и не `driver.system_shutdown`.
Замена: из ACCEPTANCE 1.4 убрать «после Task 2.2» и «модальных окон 0»; оставить «дерево погашено ≤ 3,5 с» на headless `inspection_full` (FL REDS 9/10); критерий «GUI-стенд, 5 из 5, модальных окон 0» перенести в Task 2.3 (живая приёмка), добавить в её строку. Если лид хочет сохранить живой пункт в 1.4 — строка `Dependencies: …, 2.2` и порядок 2.1/2.2 не после 1.4.

**5. [DESIGN 1-3] `deadline_at` в фазе `pre_stop` не определён; значение `started_at + pm_graceful_s` нарушает контракт `design.md` и лжёт Task 2.1.**
`design.md` («Контракт хода»): `deadline_at` — «конец graceful-окна текущей фазы». `_begin_system_stop` кладёт `started_at + pm_graceful_s` (:606-614) независимо от фазы; при переходе `pre_stop → children` его никто не переставляет (`_shift_system_stop_deadline` :637 — из 1.3, для `last`).
Вход: `pre_stop` с шагом 35 с; Task 2.1 «зависание по шагу» считает порог по `deadline_at` (`design.md` C). Наблюдаемое: через 5,0 с GUI видит «шаг идёт дольше срока» и предлагает «Закрыть принудительно» на шаге, которому разрешено 35 с. После последнего шага `deadline_at` уже в прошлом, окно `children` стартует с отрицательным остатком.
Замена: «граф с непустым списком шагов: `phase = "pre_stop"`, `deadline_at = started_at + Σ timeout_s`; на переходе `pre_stop → children` — `deadline_at = time.time() + pm_graceful_s` под `_system_stop_lock` (помощник по образцу `_shift_system_stop_deadline`); `force` — срок `started_at + deadline_s` без сдвигов (:628). Пустой список: `phase` сразу `"children"` (сказать явно — от этого зависит поле `phase` ответа)». RED: `pre_stop`-фаза несёт `deadline_at − started_at == Σ timeout_s`, после шагов — `deadline_at − now ≈ 5,0`.

### Major

**6. [DESIGN 1-3, `_cmd_system_shutdown`] Порядок событий, отмена и повторный `graceful` не определены; в коде события взводятся безусловно.**
- :1002-1004 взводят `_system_stop_event` и `stop_event` после любого `_begin_system_stop`, в том числе когда он вернул `False`. Вход: второй `graceful` во время шага. Наблюдаемое при прямой правке «добавить `accepted: False`»: ответ `already_stopping`, а события уже взведены, корень PM начинает стоп детей и бросает оставшиеся шаги. Нужен ранний `return` до :1001 для повтора `graceful`; REDS 5 должен проверять «события не взведены, шаг идёт».
- Граф с шагами не должен взводить события в :1002-1004; их взводит поток шагов после последнего шага **в `finally`**. Вход: исключение в потоке шагов → события не взведены никогда, система не гаснет. Замена: `try/finally` и WARNING.
- Отмена шага идёт только по `force` (DESIGN 3). Вход: `harness.stop()` / запасной путь GUI / `ProcessSpawner.stop()` взводят `system_stop_event` сами во время шага. Наблюдаемое: корень PM закрывается (фаза 1 → `request_stop` исполнителей), `join_until` ждёт идущий шаг до `timeout_s` (≤ 60 с); спавнер даёт PM `outer_s` 8,5/10,5 с и шлёт `terminate`. Замена: флаг отмены = `force` ИЛИ `_system_stop_event.is_set()` не от этого потока. TRAPS называет `harness.stop()` только как «`initiator` event».
- Срок `force` идёт от команды (`set_force_deadline(time.monotonic() + deadline_s)`, :987); задержка отмены съедает его. Вход: `deadline_s = 0.1`, ожидание ответа шага шагами по 0,25 с → к моменту пустого цикла срок области уже в прошлом → `terminate` всем на первом проходе (класс дефекта R2-1 из ревью 1.3). Замена: ожидание отмены — `Event.wait` с потолком 50 мс; `RouterManager.request` без отмены не годится (:1121 — слепой `pending.event.wait`), см. п. 1.

**7. [DESIGN 1, ADR] Явный аргумент `initiator`: причины нет, контракт доверия не описан, потребителя нет.**
`_EnvelopeSender` (:73-79, :961-966) сделан, чтобы клиент не мог подделать инициатора через `data["_sender"]`. Свободный `initiator` из `data` открывает эту дверь: любой IPC-клиент пишет `"gui"`. Тип, предел длины (`_SHUTDOWN_INITIATOR_MAX` = 64, :70), текст ошибки без значения — не сказаны. Потребителя нет: `git grep initiator -- multiprocess_prototype` — 0 (CloseCoordinator его не шлёт), `driver.system_shutdown` параметра `initiator` не принимает (:681), MCP-схема тоже (`mcp_tools.py:854-876`). FILES п. 4 просит описать `initiator` в `AGENTS.md`, а вызвать его нечем.
Замена: либо убрать аргумент (по умолчанию уже `sender`, значение `design.md` покрыто 1.2a), либо записать: «`initiator` — необязательная строка ≤ 64, ошибка «initiator: str ≤ 64» без значения; метка для журнала и GUI, не удостоверение; `driver.system_shutdown(..., initiator=None)` и поле MCP-схемы; приоритет — конверт, если он дан; клиентский `initiator` фиксируется как `<sender>/<initiator>`».

**8. [DESIGN 1, 6] Форма ответа и `accepted` в драйвере не согласованы.**
Драйвер считает `accepted = bool(reply.get("success"))` (`driver.py:717-720`). Повтор `graceful`: ответ DESIGN 1 `{"success": True, "accepted": False, "reason": "already_stopping"}` → драйвер вернёт `accepted: True`. Для `force` поверх `graceful` (эскалация) значение `accepted`, `phase` и `mode` не названы; `graceful` без `mode` в ответе сегодня (:969, тест `test_system_shutdown_force_author.py:124`). Замена: «драйвер читает `reply.get("accepted", reply.get("success"))`; `force`-эскалация — `accepted: True`, `escalated: True`; `phase` — `"pre_stop"` либо `"children"` (п. 5); `graceful` отдаёт `mode`». Для `accepted False` драйвер ждёт или нет — решить и записать (рекомендую: ждёт — стоп идёт, `outcomes` честные).

**9. [DESIGN 5] Отказ старта PM за ошибку схемы необязательного хука нарушает «один сбой не роняет соседа»; причины нет.**
Прецеденты 1.11 и 1.3: негодное `stop_window_s`/`stop_wave` → WARNING без значения, поле игнорируется (`reviews/task-1.3-stage0.md`, п. 8). Здесь опечатка в `timeout_s` одного шага `pre_stop` не даёт подняться всему бэкенду (`initialize()` возвращает `False`, :328-333 как для отказа исполнителя). Вход: `timeout_s: 0` у второго шага из трёх. Наблюдаемое: PM не стартует, 7 процессов не запущены.
Замена: «негодная запись `pre_stop[<i>]` — ERROR `pre_stop[<i>]: <поле> — <причина>` (причина = `msg` pydantic, без `input_value`), запись пропускается, остальные работают». Если лид хочет fail-fast — записать причину («шаг «домой» нельзя тихо потерять») и оставить отказ только для шагов с неверными `process`/`command`. Дополнительно: нет `executor_manager` (:551-553) → что с шагами: ERROR и граф без шагов (рекомендую) либо отказ. `args: dict = {}` — изменяемое значение по умолчанию; `timeout_s` — `float` с `gt=0, le=60` пропустит `True` (→ 1.0): нужен `StrictFloat`/отказ `bool`. Суммарного потолка шагов нет (п. 17).

**10. [FILES] Список неполон; существующие тесты соседей станут красными и в брифе не названы.**
- Точные `==` по ответу: `process_manager_module/tests/test_system_shutdown_force.py:160,254`, `test_system_shutdown_force_author.py:87,92,114,124,132` (`{"success": True, "message": "Shutdown initiated", ...}` без `accepted`/`phase`) — красные после DESIGN 1.
- Драйвер: `backend_ctl/tests/test_system_shutdown_driver.py:8-9,93,119` (`outcomes is None`, опрос `connection_lost` ≥ 3 раза) и `…_driver_author.py:53,87` — красные после шага 6.
- Публичная поверхность: `backend_ctl/mcp_tools.py:855-860` (описание «outcomes=null», нет полей `initiator`, `wait_timeout`) и `:308-314` — тип `public-api-change`, файла в FILES нет.
- Долг документации ADR-PMM-042 («`README.md` модуля и `backend_ctl/AGENTS.md` — Task 1.4») — `process_manager_module/README.md:537-542` в FILES нет; `AGENTS.md:147` описывает `system_shutdown` с `outcomes`/20 с.
- `amendments.md` §4: литерал `parent_death` и «4 записи за стоп» в `design.md` «правит Task 1.4» — файла в FILES нет.
- Контракт-lite: новый публичный `process/pre_stop.py` (схема шага, исполнитель) — `tests/contract/test_pre_stop.py` и docstring `Purpose/Public API/Stability` не названы.
Замена FILES: + `backend_ctl/mcp_tools.py`, + `process_manager_module/README.md`, + список тестов соседей к правке (или явное «стражи правит teamlead»), + `design.md` либо снять обязанность; ADR: `ADR-PMM-044` + строки в ADR-038 (режимы) и ADR-041 (`pre_stop_step`, `parent_death`).

**11. [REDS] Девять ячеек из десяти не покрывают DESIGN 1, 4, 5, 6; две ячейки не красные до правки.**
- SM 3 `force_skips_pre_stop`: до правки ключ `pre_stop` игнорируется и шагов нет — «не отправлен» истинно без реализации. Зелёная до; страж, не RED. Сделать парой с SM 1 в одной ячейке (graceful отправляет, force нет) или пометить «страж».
- SM 8 `invalid_pre_stop_schema_refuses_start` — единственная про схему. Нет ячеек: границы `timeout_s` (0, 60, 60,0001, NaN, `True`, отрицательное), лишний ключ, пустой `process`/`command`, не-dict `args`, неизвестный `process`; текст ошибки без значения (iii).
- Нет RED на DESIGN 4 (`process.stop`/`restart`/`topology.apply` в `pre_stop` → отказ), на `accepted`/`phase`/`mode` в ответе (SM 5 — только повтор), на пустой список («события сразу, задержка 0»), на `pre_stop_step` (имя → `null`), на `deadline_at` в `pre_stop` (п. 5), на внешнее событие во время шага (п. 6), на ребёнка в переходе (TRAPS), на `initiator` (п. 7).
- Нет ячейки драйвера на unit-уровне: `outcomes` = `{name: stop_outcome}` без PM, объединение снимков, `BackendUnavailable` посреди опроса, `wait_timeout`.
- Break-injection заявлена одна пара. Добавить предсказания: исполнитель шагов = `pm-lifecycle` → SM 7 и RED по п. 4; события взведены до шагов → SM 1 и «шаг ждёт ответа»; `alive` вместо `stop_outcome` как условие выхода → FL 10 (недетерминированно, см. п. 3); флаг отмены без `_system_stop_event` → RED п. 6.
Предел 10: перераспределить — слить SM 3 в SM 1, SM 6+7 в одну ячейку с двумя утверждениями, освободить 3 места под пп. 4, 5, 8.

**12. [DESIGN 6, ACCEPTANCE] `wait_timeout` 20 с и бюджет `pre_stop` не сведены; «честный итог» врёт молчанием.**
`driver.system_shutdown(wait_timeout=20.0)`, MCP не передаёт его (`mcp_tools.py:308-314`). Шаг Р2 — 35 с, плюс 5,0 и 2,0 с. Вход: `drv.system_shutdown()` при `robot_park_all` на 35 с. Наблюдаемое: возврат на 20 с, `pm_gone False`, `outcomes` почти все `None` без пометки «ожидание вышло». Добавить в результат `timed_out: bool`, в DESIGN — как `wait_timeout` связан с Σ `timeout_s` (`system_stop.deadline_at` в `pre_stop`, п. 5, даёт драйверу срок). Суммарный потолок шагов отсутствует (п. 17).

**13. [FL REDS 9, 10] Предсказания «красные до» и достижимость чисел.**
FL 9, 10 красные до правки (`outcomes` — `None`) — да. Достижимость при текущем DESIGN 6 — см. п. 3. `elapsed_s ≤ 3,5` на одном прогоне против «< 4,0 / медиана 2,5» из 0.2: либо «N из N», либо граница по медиане. `inspection_full` без окон (`stop_window_s` в прототипе — 0 вхождений вне тестов): сигнал зависшему идёт на `kill()` области, итог `terminated` или `killed` (оба в допустимом наборе, какой именно — зависит от платформы; не прогонялось). Указать `deadline_s` в FL 9 (в брифе нет).

**14. [ЗАЯВКА Р2] Абзац устарел и перегружает задачу.**
Условие «пока условная, манифест пустой» устарело: `robot_park_all` влита (`Plugins/hub/device_hub/plugin.py`, `tests/test_robot_park_all_command.py`). Но `docs/handoffs/2026-11-08_R2-T5.5.md:6` и `docs/reports/2026-11-08_robot-protocol-v2_T5.5.md:39`: шаг «не передан, ждёт слова владельца»; решение «не дома к сроку → PM всё равно в аварийный стоп» без ответа (`Services/device_hub/DECISIONS.md:277-280`). Файл манифеста в FILES не назван (слой `multiprocess_prototype/`, принцип «приложение правим только там»). Живая проверка шага требует `devices` и sim v2 — это отдельный стенд.
Замена: вычеркнуть заявку из 1.4; завести отдельную Task 1.4m (манифест + живая проверка пути PM → `robot_park_all` → `process.stop`) после влития 1.4. В 1.4 оставить тестовый шаг-заглушку (`_hung_child_plugin`-образец) и ссылку.

### Minor (`quality`)

**15. [шапка, DESIGN] Якоря и номера.** Таблица якорей п. 2 вместо `:1042`; ADR — **ADR-PMM-044** (043 занят); `Dependencies`: «Task 1.1» → «1.1a (ADR-PMM-040)», добавить 1.3 как «в `main` `61faf8f0e`», убрать «ждёт» там, где влито; DESIGN 1 «по умолчанию `sender`» и DESIGN 3 поле/помощник уже есть (п. 2 таблицы) — переписать как «ставит значения помощникам 1.2a».

**16. [TESTS, Gate] Путь интерпретатора и класс окна.** `.venv/Scripts/python.exe` — Windows; на Darwin `.venv/bin/python`. FL-тесты идут с `--backend-live` и в порт-диапазоне брони (Task 0.2: 7920–7929), это окно стенда `heavy`, а команда `TESTS` — класс `medium` без флага. Написать обе команды и бронь портов; в `Gate` сказать, какие ячейки идут в `medium`, какие в `heavy`.

**17. [DESIGN 5] Суммарного потолка шагов нет.** `timeout_s ≤ 60` на шаг, шагов сколько угодно. Вход: 10 шагов × 60 с — стоп до 10 минут без единого окна, которое бы это показало (`outer_s` спавнера и `wait_timeout` драйвера об этом не знают). Замена: «Σ `timeout_s` ≤ 120 с (константа), превышение — запись пропускается, ERROR» либо явное «потолка нет, причина …».

## 5. FILES: полнота

Бриф: 5 путей. Нужно: 1–5 как есть (с правками пп. 2, 3, 6, 7) + `backend_ctl/mcp_tools.py` (п. 10) + `process_manager_module/README.md` (п. 10; долг ADR-042) + решение по `design.md`. `process/__init__.py` экспортов не проверен (Public API нового `pre_stop.py`). Тесты соседей к правке (пп. 10): `test_system_shutdown_force.py`, `test_system_shutdown_force_author.py`, `test_system_shutdown_driver.py`, `test_system_shutdown_driver_author.py`. Файл `tests/conftest.py` (`MockProcessRegistry`) не нужен, если PM читает шаги из конфига через `get_config`. `presentation.yaml`/`ProcessLaunchConfig` для ключа `pre_stop` не нужны: ключи оркестратора идут через `orchestrator_config` напрямую (`launcher/spawner.py:95-96`) — но источник «манифест приложения» (откуда `orchestrator_config` берётся в `multiprocess_prototype`) в брифе не назван, это часть п. 14.

## 6. Пересечения с чужими работами

- `git status` главного дерева: изменены `.claude/memory/*`, `docs/reports/2026-10-26_stage0-eval.md`; не отслеживаются `plans/robot-protocol-v2/tasks/T5.4*.md`. Путей FILES среди них нет. `tasks/1.4.md` не изменён.
- Открытые ветки/worktree против FILES (`git diff main...<ветка>`) **не сверялись** (бюджет контекста) — в отличие от отчёта 1.3. Лиду: сверить `process_manager_process.py`, `driver.py`, `DECISIONS.md` перед стартом тестера.

## 7. Итоговый список правок (для лида)

| Пункт чек-листа | Находка | Что исправить |
|---|---|---|
| (i)/(ii) DESIGN 2 | 1 | механизм шага: готовность ребёнка + `request_async`/`request` с потока исполнителя; `_run_when_child_ready` из TRAPS убрать |
| (ii)/(i) DESIGN 4, 2 | 2 | отдельный исполнитель шагов; предикат `_lifecycle_rejected()` для `pm-lifecycle`; убрать «ESCALATION -> cto»; RED на п. 4 |
| (a)/(ii) DESIGN 6 | 3 | условие выхода по `stop_outcome`/`done`/разрыву; PM исключён; объединение снимков; `unconfirmed`; FL 9/10 переформулировать |
| (d)/(a) ACCEPTANCE | 4 | живой пункт «GUI-стенд» в Task 2.3; из 1.4 убрать «после 2.2» |
| (a)/(ii) DESIGN 1-3 | 5 | `deadline_at` в `pre_stop` и перебазирование на `children`; `phase` при пустом списке |
| (ii) DESIGN 1-3 | 6 | ранний `return` для повтора `graceful`; события в `finally`; отмена по `_system_stop_event`; ожидание отмены ≤ 50 мс |
| (i) DESIGN 1 | 7 | убрать `initiator` или описать доверие, тип, предел, параметр драйвера |
| (a) DESIGN 1, 6 | 8 | `accepted` в драйвере из `accepted`; форма ответа для `force`-эскалации |
| (ii)/(iii) DESIGN 5 | 9 | WARNING+пропуск вместо отказа старта (или записанная причина); `bool`, `args`, нет `executor_manager` |
| (d) FILES | 10 | + `mcp_tools.py`, `README.md`; стражи соседей; номер ADR-044; контракт-lite `pre_stop.py` |
| (a) REDS | 11 | перераспределить 10 ячеек; пары для RED/страж; предсказания инъекций |
| (a) | 12 | `timed_out`, связь `wait_timeout` с `pre_stop` |
| (a) | 13 | `deadline_s` в FL 9; «N из N»; медиана вместо одного прогона |
| (f) | 14 | заявку Р2 вычеркнуть → Task 1.4m |
| — | 15-17 | якоря, `Dependencies`, `TESTS`, потолок Σ |

## 8. Что осталось открытым / ненадёжно

1. Ничего не запускал (по заданию). Все сценарии «вход → результат» (пп. 1-6, 8-9, 12) — вывод из чтения кода и ADR, не прогон. «Красный до правки» (п. 11, 13) — рассуждение по тексту, тестов 1.4 ещё нет.
2. Недоступность итога последнего ребёнка (п. 3) выведена из текста ADR-PMM-042 («Предел контракта») и записи `plan.md` 2026-11-08, а не из трассы. Длина окна между подтверждением смерти и остановкой `message_processor` не измерена; при ширине окна > 100 мс угроза слабее, но условие `alive is False` остаётся неверным независимо от неё.
3. Что `RouterManager.request`/`request_async` способен доставить запрос ребёнку `devices` и вернуть ответ `robot_park_all` через `reply_to_request`, проверено только по сигнатурам (`router_manager.py:1048-1274`) и Р2-документам; конец-в-конец путь PM → ребёнок → ответ → PM не проверял. Форма конверта (`sender`, `reply_to`, `queue_type`) в PM → ребёнок для `request` не сверена с `_send_child_command`.
4. Влияние расширения `_pm_stopping()` фазой `pre_stop` (п. 2) на семь потребителей прочитано выборочно (:226, :2322, :4154-4174, :4262, :4663, :4684, :4819); тесты, которые их проверяют, не читал.
5. Ответ `reason: "system_stopping"` в виде именно поля `reason` не проверял: `worker_module/README.md:188` и `command_module/DECISIONS.md:90` говорят «отказ `system_stopping`», форма ответа CommandManager на пути `process.command` может быть `error`, а не `reason`.
6. `process/__init__.py` и `modules/process_manager_module/__init__.py` на экспорты не открывал (п. 5 раздела FILES). Монитор процессов во время `pre_stop` (рестарт упавшего `devices`) не исследовал.
7. Ветки и worktree против FILES не сверял (раздел 6). `memory hits:` — `scripts/memory/search.py` не запускал, qex не использовал (индекс не проверял), поиск только `git grep`/`Read`.
8. Решения лида, которых здесь нет: нужен ли отказ спавна и `stop_abort` в `pre_stop` (п. 2); вариант (А)/(Б)/(В) в п. 3; fail-fast или WARNING для схемы (п. 9); потолок Σ шагов (п. 17); судьба заявки Р2 (п. 14).

---

# Раунд 2 (последний)

- **Читано:** `tasks/1.4.md` целиком (212 строк, не закоммичено) и `git diff` по `design.md`, `amendments.md` §5, `plan.md`, `tasks/2.3.md`, `docs/claude/OPEN_QUESTIONS.md` против кода `main` `2d663a497`. Сверено по коду: `router_manager.py` :1023-1046, :1139-1272, :1274-1321, :1375-1395, :1450-1506; `command_envelopes.py` :20-50; `socket_bridge_adapter.py` :72-98; `Plugins/hub/device_hub/client.py` :110-137; `process_manager_process.py` :1896-1935; `driver.py` :1105, :1223; тесты соседей по `git grep`. Хэши слияний (`0f1883a64`, `68884237c`, `61faf8f0e`, `4d2a2f522`) существуют; `ADR-PMM-044` свободен (`git grep` — только ссылки самого плана и `OPEN_QUESTIONS.md`). Ничего не запускалось.
- **Вердикт: CHANGES REQUESTED (итерация 2 из 2).** Блокеров нет. Из 17 пунктов раунда 1 закрыто 12 по существу, 5 — не полностью (пп. 3, 6, 10, 11, 12). Новых находок 9: 4 major (`tests`/`spec`), 5 minor. Все — правки текста задачи, механизм путей PM → ребёнок → ответ сходится с кодом. Замены даны дословно: если лид применит их и проверит `git diff`, стадию 0 считаю закрытой без третьего раунда.

## 1. Пункты раунда 1: закрыты ли

| № | Пункт | Статус | Замечание |
|---|---|---|---|
| 1 | запрос с ожиданием ответа | **закрыта** | DESIGN 1 (а)-(д) выполним по коду (раздел 2, проверка 1); остаток — R2-6 |
| 2 | отдельный исполнитель, `_lifecycle_rejected()`, снять «ESCALATION -> cto» | **закрыта** | DESIGN 2; решение лида принято; в DESIGN 2 фраза «классы L и T» неточна (R2-5); предсказание инъекции (1) неполно (R2-2) |
| 3 | условие выхода драйвера, строка PM, итог последнего ребёнка | **закрыта не полностью** | вариант (А) записан верно (`stop_outcome`/`done`/разрыв, PM исключён, объединение снимков, `unconfirmed`); не определены `pm_gone` при раннем конце (R2-1) и форма снимка на пути вызова (R2-4) |
| 4 | живой GUI-пункт | **закрыта** | убран из 1.4; `2.3.md` A6 несёт его с `unconfirmed`/`timed_out`; `plan.md` согласован; круг зависимостей снят |
| 5 | `deadline_at` в `pre_stop` | **закрыта** | DESIGN 4 + REDS 6 + инъекция (8) согласованы с :606-614, :628, :637; числа 1,2 ± 0,05 и [4,8; 5,0] верны |
| 6 | порядок событий, отмена, повтор `graceful` | **закрыта не полностью** | ранний `return`, события в потоке шагов, отмена по `_system_stop_event`, срез 50 мс — в тексте есть; `try/finally` ни одной ячейкой не проверяется (R2-2) |
| 7 | аргумент `initiator` | **закрыта** | убран; `design.md` :78, :172, заголовок задачи, `plan.md`, `OUT OF SCOPE` согласованы; `git grep initiator` по плану — остатков в 1.1/2.1/2.2 нет (в 2.1 — только подзаголовок диалога из `system_stop.initiator`) |
| 8 | форма ответа, `accepted` драйвера | **закрыта** | `reply.get("accepted", reply.get("success"))`; DR(г); `force` поверх `force` — `already_set` + `accepted: False` |
| 9 | отказ старта PM за схему | **закрыта** | ERROR + пропуск записи; `bool`/`"5"` не принимаются; `default_factory`; нет `executor_manager` — ERROR (ячейки нет, R2-3) |
| 10 | FILES, стражи соседей | **закрыта не полностью** | строки стражей проверены (раздел 2, проверка 4); пропущен страж `test_system_shutdown_force_live.py:195-196` (R2-1) |
| 11 | REDS: красные до, покрытие, инъекции | **закрыта не полностью** | 10 ячеек красные до правки (раздел 2, проверка 2); пробелы покрытия — R2-3; инъекции — R2-2 |
| 12 | `wait_timeout` и бюджет `pre_stop` | **закрыта не полностью** | формула `max(20,0; deadline_at − now + 12,0)` верна по ADR-043 (`pm_total_s` 9,0 + 3,0); ячейки на неё нет (R2-3) |
| 13 | числа FL 9/10 | **закрыта** | `< 4,0` и медиана `≤ 2,5` — огибающая Task 0.2 (`test_system_shutdown_force_live.py:5-9`); «5 из 5» есть |
| 14 | заявка Р2 | **закрыта** | вычеркнута → Task 1.4m (`plan.md`, `OUT OF SCOPE`, `OPEN_QUESTIONS.md`) |
| 15 | якоря, `Dependencies`, ADR-номер | **закрыта** | якоря сверены выборочно (раздел 2, проверка 5); 044 свободен |
| 16 | `TESTS`, класс окна | **закрыта** | обе платформы, `medium`/`light`/`heavy`, порты 7920-7929, `--backend-live` |
| 17 | потолок Σ | **закрыта** | `PRE_STOP_TOTAL_MAX_S = 120,0`, `PRE_STOP_STEP_MAX_S = 60,0`; REDS 7 + инъекция (9б) |

## 2. Особые проверки

**(1) Путь PM → ребёнок → ответ через `request_async` с потока `pm-pre-stop`: выполним по коду.**
- `request_async` (`router_manager.py:1139-1195`) не вызывает `_assert_not_receive_thread` (проверка только в `request`, :1023-1046, :1048+) — с потока исполнителя шагов вызов допустим; синхронный отказ отправки приходит колбэком в том же вызове (:1185-1193), что DESIGN 1 (г) называет `ошибка отправки`.
- Конверт: `build_command_message(target, command, args, sender=self.name)` (`command_envelopes.py:20-50`) ставит `targets=[target]`, `sender`, `data`; `request_id` и `correlation_id` в `data` добавляет `request_async` (:1174-1178). Адресат ответа — `sender` (`reply_to_request` :1297-1298): PM, значит `reply_to` не нужен (в `SocketBridgeAdapter.on_inbound` его подставляют только потому, что sender драйвера — не процесс, :72-98).
- Ответ: `{"type": "response", "targets": [PM], "queue_type": "system", "request_id", "success", "result"}` (:1304-1313); приёмный цикл PM резолвит только `type == "response"` (:1497-1501), снимает слот и зовёт колбэк на потоке приёма (:1248-1272); подметание просроченных — на такте `receive()` (:1457-1458). Описание в DESIGN 1 (б), (д) совпадает с кодом дословно. Авто-ответ ребёнка на команду с `request_id` — :1382-1391, отложенный (executor) ответ — через `DEFERRED` и `reply` ровно один раз (:1375-1380).
- Прецеденты того же пути: `SocketBridgeAdapter.on_inbound` (`router.request` из роутера PM к ребёнку — рабочий путь `driver.send_command`), `DeviceHubClient.request` (ребёнок → ребёнок). `message_processor` PM в фазе `pre_stop` жив (события не взведены) — условие выполнено.
- Не проверено прогоном: конец-в-конец с настоящим `robot_park_all`; соответствие `_result_is_success(result)` ответа хаба «`success is True`» (шаг Р2, Task 1.4m).

**(2) 10 ячеек REDS красные до правки? Да, с указанными стражами.** SM 1 (а) — сегодня событие сразу, ответ ребёнка не отправлен → красная; (б), (в) — стражи (заявлены). SM 2, 3, 4, 5, 6, 7 — красные (нет шагов, нет `accepted`/`phase`, нет фазы `pre_stop`, нет отказа, нет ERROR при негодной записи). SM 5: страж «без стопа принимаются» (заявлен). DR 8 — красная (нет `unconfirmed`, `timed_out`); подслучай (д) («ошибка аргументов → без опроса») зелёный и до правки — в ACCEPTANCE не назван (R2-9). FL 9, 10 — красные (`outcomes` — `None`). Покрытие DESIGN 1-7 — в R2-3: пробелы по 1 (а)/(д), 5 (нет `executor_manager`), 6 (формула `wait_timeout`).

**(3) Предсказания инъекций против ячеек: согласованы не все** (R2-2). Верно предсказаны (4), (5), (6), (7), (8), (9), (9б), (11), (13).

**(4) Стражи соседей: строки верны, один страж пропущен.** Сверено `git grep`: `test_system_shutdown_force.py:160, :254`; `…_force_author.py:87, :92, :114, :124, :132`; `test_system_shutdown_driver.py:8-9, :93, :119, :133`; `…_driver_author.py:53, :87` — все есть, правки описаны («прежние поля равны прежним литералам + новые поля»). Пропущено: `backend_ctl/tests/test_system_shutdown_force_live.py:195-196` (L-smoke, тот же файл, куда идут FL 9/10): `"pm_gone is True"` и `"outcomes is None"` (R2-1). Фикстура `_driver` (`test_system_shutdown_driver.py:65-76`) подменяет только `system_command` — после замены опроса нужна подмена `supervision_status` в одном месте, а не на :119.

**(5) Внутренние противоречия.** Числа: `Σ` 120/60, `deadline_at` 1,2 и [4,8; 5,0], `wait_timeout` 12,0 = 9,0 + 3,0, порты 7920-7929, `elapsed_s < 4,0 / медиана ≤ 2,5` — согласованы между DESIGN, REDS, ACCEPTANCE. Имена: `pm-pre-stop`, `_lifecycle_rejected()`, `PRE_STOP_*_S`, `parse_pre_stop`, `ADR-PMM-044` — одинаковы везде; `design.md` и `plan.md` не расходятся с задачей. Расхождения — только R2-5 и R2-6.

## 3. Новые находки

### Major

**R2-1. [DESIGN 6, FILES, стражи] [spec] `pm_gone` при раннем конце опроса не определён; страж `test_system_shutdown_force_live.py:195-196` пропущен.**
Опрос кончается «первым из»: все итоги / `done` / разрыв / `wait_timeout`. Вход: здоровый граф, `drv.system_shutdown()`; все дети подтверждены, PM ещё держит сокет. Наблюдаемый результат: конец по итогам, `pm_gone False`, `timed_out False`, `accepted True`. Контракт Task 0.2 (ADR-PMM-038, `driver.py:681-742`): `pm_gone` — «PM закрыл сокет»; MCP-описание (`mcp_tools.py:855`): «дождаться, пока PM закроет сокет» — DESIGN 6 их переписывает только про `outcomes`. L-smoke Task 0.2 (`test_system_shutdown_force_live.py:195-196`) проверяет `pm_gone is True` и `outcomes is None` → красный после правки, в списке стражей его нет. Потребитель: любой вызывающий, который после `system_shutdown()` считает `pm_gone` признаком «PM ушёл».
Замена: «после конца по итогам/`done` драйвер ДОЖИДАЕТСЯ закрытия сокета ещё не больше `min(остаток wait_timeout, 3,0 с)` (`pm_gone` — как в 0.2); не дождался — `pm_gone False`, `timed_out False`; `elapsed_s` — до конца ожидания сокета». Либо явно: «`pm_gone` может быть `False` при `timed_out False`; MCP-описание и `AGENTS.md` говорят это словами». В список стражей добавить `test_system_shutdown_force_live.py:195-196` и :`_driver` (:65-76). ACCEPTANCE FL 9 (`elapsed_s < 4,0`) при ожидании сокета остаётся верным: огибающая 0.2 меряла выход PM.

**R2-2. [ACCEPTANCE, break-injection] [tests] Предсказания (1), (3), (10), (12), (14) не совпадают с REDS.**
- (1) шаги в `pm-lifecycle`: предикат `_lifecycle_rejected()` уже ложь только до фазы `pre_stop`; шаг подаётся ПОСЛЕ `_begin_system_stop(phase="pre_stop")`, `submit` отклоняется (`system_stopping`), шаги не исполняются, события не взведены. Красные: 1(а), 2, 3, 4 (`pre_stop_step` не ставится), 5, 6 — не только «5 и 1(а)». Если имелась в виду подача в `pm-lifecycle` с прежним `_pm_stopping` — это инъекция (7), не (1).
- (3) шаг через `_send_child_command`: шаг кончается за миллисекунды (`True`) — красные 1(а), 2, 3, 4, 5, 6 (все ячейки, которым нужен идущий шаг 0,5-30 с), не «1(а), 2».
- (10) шаги синхронно на потоке приёма: ответ ребёнка резолвит тот же поток, который заблокирован шагом → все запросы кончаются таймаутом; красные 1(а), 2, 3, 4, не «REDS 4».
- (12) `outcomes` из последнего снимка: 8(б) — разрыв после 2-го снимка, где у `a` уже `exited`, — даёт те же значения при объединении и без него; красной станет 8(б) только если в её последовательности значение «снимается» после непустого. Либо поменять ячейку, либо убрать 8(б) из предсказания.
- (14) события не в `finally`: в REDS 2 третий шаг «бросает исключение в запросе» — исключение ловится ПО ШАГУ (DESIGN 1 (г): причина `исключение <ИмяКласса>`), цикл идёт дальше, события взводятся после цикла и без `finally` → REDS 2 зелёная под инъекцией. Свойство «исключение вне обработки шага не оставляет систему живой» ячейкой не проверено.
Замена: переписать предсказания по перечню выше; для (14) добавить в SM 2 четвёртый шаг, у которого падает ВНЕ обработки шага (подмена `_set_pre_stop_step` бросающей функцией на этом шаге) — тогда события взведены (`finally`), ERROR с именем класса; (14) красит SM 2. В список стражей-частей ACCEPTANCE добавить 8(д).

**R2-3. [REDS] [tests] Три положения DESIGN без ячейки.**
- DESIGN 1 (а) и TRAPS «ребёнок в переходе (рестарт)»: ожидание готовности (`ev.wait`, причина `ребёнок не готов`), `процесс не найден`, `ошибка отправки` — ни одной ячейки и ни одной инъекции (убрать (а) → красных нет). Это сценарий из исходного брифа.
- DESIGN 6: формула `wait_timeout=None → max(20,0; deadline_at − now + 12,0)` и поведение «без `wait` — `outcomes`/`unconfirmed` — `None`, `timed_out False`» — в DR 8 нет.
- DESIGN 5: «нет `executor_manager` — ERROR, граф без шагов» — ячейки нет (3 строки в DR/SM 7).
Предел 10 исчерпан. Замена: SM 2 расширить пятым шагом с ребёнком «не готов» (событие готовности не взведено, `timeout_s` 0,5 → `ребёнок не готов`, ровно одна WARNING) и записью несуществующего процесса (`процесс не найден`); DR 8 дополнить (е) `wait_timeout=None`, `deadline_at` первого снимка = `now + 30` → срок ≥ 42 с (`wait_timeout` проверяется по подмене часов или по значению аргумента, переданному в цикл) и (ж) `wait=False`; пункты `executor_manager` и запоздавший ответ (1 (д)) — авторские тесты исполнителя, записать в `FILES`/`ACCEPTANCE` как обязательные «hazard» (project-rules §9).

**R2-4. [DESIGN 6, REDS 8] [tests] Форма ответа `supervision_status` на пути вызова не названа.**
`driver.supervision_status` возвращает сырой ответ `send_command` (`driver.py:1105-1126`); `AGENTS.md:145`: «Читать из `r["result"]["system_stop"]`». Образец: `process_restart_verified` разворачивает ответ `_leaf_result(...)` (`driver.py:1223`). Урок плана (`plan.md`, запись 2026-11-07 о 1.1): форма на пути вызова, а не у обработчика. DR 8 подменяет `supervision_status` — какой формой, не сказано.
Вход: тестер строит фейк с плоским `{"processes": {...}}`, исполнитель читает `_leaf_result(...)["processes"]` (или наоборот). Результат: DR зелёная, живой FL 9/10 (heavy, последний шаг) падает на `KeyError`/пустом словаре.
Замена: в DESIGN 6 — «ответ `supervision_status` разворачивается `_leaf_result` (как `driver.py:1223`); разбираются `processes` и `system_stop`»; в DR 8 — «фейк `supervision_status` возвращает конверт `send_command` с вложенным `result`, форма снята с `process_restart_verified`-теста или живого снимка».

### Minor (`quality`)

**R2-5.** DESIGN 2: «все команды классов L и T получают отказ». Команды T идут через `_TransitionGate` и попадают в `pm-lifecycle` только если цель в переходе (`process_manager_process.py:716-718`); для остальных исполняются на месте. Отказ в фазе `pre_stop` получают команды L (`_LIFECYCLE_COMMANDS`, :719-727) и T только для цели в переходе. REDS 5 перечисляет только L — верно; исправить фразу, иначе исполнитель «поправит» шлюз.

**R2-6.** DESIGN 1 (а): «`ev is None` — действовать сразу» и «Процесса нет в реестре — причина `процесс не найден`» перекрываются: `_child_ready_event` (:1899-1932) отдаёт `None` и для «сигнала нет», и для «процесса нет». Порядок проверок не назван. Замена: «сначала `self._process_registry.get_process_by_name(process) is None` (`process_registry.py:160`) → `процесс не найден`; затем `_child_ready_event`».

**R2-7.** REDS 7 собирает ≥ 13 случаев в один конфиг, а потолок Σ 120 с зависит от порядка: годная запись `60` + третья «по 60» + другие годные записи — какие исполняются, зависит от последовательности. Разбить на два PM (схема / потолок) внутри одной ячейки и назвать ожидаемый список исполняемых. Плюс (iii): `loc` pydantic при `extra="forbid"` — имя лишнего ключа, то есть входное значение; сказать, разрешено ли его печатать (рекомендую: `<поле>` = `loc` только для известных полей, лишний ключ — `поле — неизвестный ключ` без имени).

**R2-8.** REDS 3 (а), (б): наблюдаемое «поток шагов завершён ≤ 0,1 с» привязано к потоку исполнителя (деталь реализации, project-rules §9). Заменить на `pre_stop_step is None`, `system_stop.phase == "children"` и отсутствие запросов шагу 2. Для (а) в тестовом PM `_children_stop` должен быть зарегистрирован: при `None` команда `force` уходит в ветку «выполняю graceful» (`process_manager_process.py:983-985`), эскалации и отмены нет; DESIGN 3 об этом молчит — одна строка в TRAPS.

**R2-9.** ACCEPTANCE: список «частей-стражей» (1(б), 1(в), страж в 5) неполон — зелёные и до правки ещё 8(д) и, в зависимости от ячейки, 8(в) (без `timed_out` — `KeyError`, красная); перечислить.

## 4. Итоговый список правок (для лида)

| Находка | Что исправить |
|---|---|
| R2-1 | `pm_gone` при раннем конце: ждать сокет ≤ `min(остаток, 3,0 с)` либо записать `pm_gone False` словами в MCP/`AGENTS.md`; страж `force_live.py:195-196` и фикстура `_driver` в список |
| R2-2 | переписать предсказания (1), (3), (10), (12); для (14) — четвёртый шаг, падающий вне обработки шага |
| R2-3 | ячейки/авторские тесты: готовность ребёнка и `процесс не найден`; `wait_timeout=None`; `wait=False`; `executor_manager` None; запоздавший ответ |
| R2-4 | `_leaf_result` в DESIGN 6 и форма фейка в DR 8 |
| R2-5…R2-9 | правки текста (T-класс, порядок проверок, REDS 7, REDS 3, список стражей-частей) |

## 5. Что осталось открытым / ненадёжно (раунд 2)

1. Ничего не запускал. Выполнимость пути PM → ребёнок → ответ (проверка 1) — чтение `router_manager.py`, `command_envelopes.py`, прецедентов `SocketBridgeAdapter`/`DeviceHubClient`; конец-в-конец прогона нет. `_result_is_success` для ответа `robot_park_all` не читал (это 1.4m).
2. «Красные до правки» (проверка 2) и предсказания инъекций (R2-2) — рассуждение по тексту; тестов 1.4 ещё нет, если тестер построит ячейки иначе, колонка изменится. В частности R2-2 (14): вывод «исключение ловится по шагу» следует из DESIGN 1 (г), а не из кода.
3. Вариант (А) драйвера по-прежнему оставляет окно «итог последнего ребёнка опросом не виден» (ADR-PMM-042, вариант (В) в `OPEN_QUESTIONS.md`); ширина окна «`done` → закрытие приёма» не измерена. FL 9 допускает `unconfirmed` для зависшего, FL 10 требует пустой `unconfirmed` — на Windows (heavy) может быть периодически красным; порога повторов нет.
4. `ExecutorManager.create(..., {"max_pending": 1, "serial": True})` и ключ `"system"` (строка, а не `frozenset`) в `KeyedExecutor.submit` — по `worker_module/README.md:243-244`, :188, :196-198; код нормализации ключа не читал.
5. Монитор во время `pre_stop` (рестарт упавшего ребёнка) принят как ограничение (ADR-044, `OPEN_QUESTIONS.md`); не исследовал, насколько вероятен сценарий.
6. Ветки и worktree против FILES не сверял (бюджет контекста); `memory hits:` — `scripts/memory/search.py` не запускал; qex не использовал.
