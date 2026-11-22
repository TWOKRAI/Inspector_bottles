# Диагностика: две записи STOP_REQ при штатной остановке (сим, letter_robot_sim, 2026-11-22)

Автор: `investigator` (opus, только чтение); файл сохранил лид (у агента нет записи). Дерево `../Inspector_bottles--lane-sim-audit`, HEAD `ace79e119`. Прогон `data/chain_check/letter_robot_sim/20261122T150430Z/run1/`. Сокращения: `RX` — `logs_prototype/devices/robot_exchange.log`; `MSG` — `logs_prototype/devices/messages.log`; `PM` — `logs_prototype/ProcessManager/messages.log`.

## Симптом
`alpha.out:65`: `СТОП stop: STOP_REQ [5, 9], строк после seq 652: 13 … → FAIL: STOP_REQ строк 2 ≠ 1`.

## Хронология (строка файла, #id записи, #seq журнала обмена)
| Время | Источник | Событие |
|---|---|---|
| 45,753–45,780 | RX:652–663 | `SC_RUN` (ДОМОЙ), ответ ОК: park 1 от α, шаг p5 (`scripts/alpha_sim/run_alpha.py:672`, `robot_park_all`) |
| 46,757 | RX:667 | `SERVO` 0 |
| 46,758 | MSG:50 | «основная остановка 1 выполнена: дом moved, серво OFF» |
| 46,801 | PM:104–105 | «System shutdown requested via command»; «shutdown из running: шагов pre_stop 1, затем ожидание paused» |
| 47,263–47,285 | RX:674–678 | `SERVO` 0: park 2 от pre_stop (`multiprocess_prototype/backend/config/system.yaml:344`) |
| 47,286 | MSG:51 | «основная остановка 2 выполнена: дом already, серво OFF» |
| **47,296** | **RX:679** | **`STOP_REQ = 5`** (seq 1, SOFT) |
| 47,297 | RX:680–681 | `0x1200 = 0`, `0x1204 = 1`: стоп ПЧ (`VfdClient.stop`, `Services/vfd_comm/core/client.py:87`) |
| 47,841–47,842 | MSG:52–55 | «Stop signal received (system-wide)» … «DeviceHubPlugin: request_stop» |
| **47,842** | **RX:683** | **`STOP_REQ = 9`** (seq 2, SOFT) |
| 47,962–47,963 | MSG:56–58 | «All workers stopped», воркер робота снят |
| 47,963 | RX:684 | `disconnect` |

Других строк `STOP_REQ` в RX нет (только 679 и 683): первые два стопа клиента в этой инкарнации, один счётчик `_stop_seq`.

## Цепочка 1: `STOP_REQ = 5` (пауза системы)
1. `process_manager_process.py:2363–2365`: `_run_shutdown_pass` → `_run_pre_stop_loop()` (park 2) → `_run_apply("shutdown")` → `_wait_all_paused(...)` (PM:105).
2. Оркестратор процесса `devices` вызывает хук `pause` (`process_module/plugins/base.py:1687`, `plugin_orchestrator.py:494`) → `Plugins/hub/device_hub/plugin.py:423` → `self._manager.pause_all(...)`.
3. `Services/device_hub/manager.py:278` `pause_all` → `_pause_pick` (`:361`) → поток → `_pause_one` → `self.call(dev_id, op, args)` (`:398`).
4. Робот v2: `robot_driver_v2/__init__.py:35` `pause_action = ("stop", {"level": "SOFT"})`; ПЧ: `vfd_driver.py:36` `("stop", {})` — отсюда парная запись ПЧ в RX:680–681.
5. `ops.py:284` → `_op_stop` (`:113`) → `_operator_stop` (`:86`) → `_write_stop` (`:101`) → `client_v2.py:721` `issue_stop` → `:745` `_issue_stop_locked`: `_stop_seq`=1, `value = 1·4+1 = 5`.

## Цепочка 2: `STOP_REQ = 9` (стоп процесса, ADR-DH-009)
1. Хук `request_stop` (MSG:55) → `plugin.py:360–376` → `request_stop_all_begin(deadline)`.
2. `manager.py:202` → `_stop_start` → поток → `_stop_one` (`:268`) → `drv.request_stop(deadline)`.
3. `stop.py:34` → `state.request_stop_begin()` (`state.py:439`): первый вызов делает `_latch_reset_locked()` (`:445`); комментарий `:443–444`: «стопы до него (оператор, отпускание jog) стоп выключения не покрывают».
4. `stop.py:89` `_process_stop` → `state.py:461` `process_stop_plan`: робот простой и подключён → `SOFT` (`:485`); защёлка пуста → запись не гасится (`:492`).
5. `stop.py:105` `_write_stop` → `client_v2.py:745–755`: seq 2, `value = 2·4+1 = 9`.
6. `disconnect()` при выключении стоп не пишет (`driver.py:453–456`, ветка `if not shutdown`) — после 9 записей нет (RX:684).

## Вердикт: штатно по действующим решениям, дефекта кода нет; устарел критерий α
- ADR-DH-009: «первый запрос выключения открывает новое поколение защёлки: прежние стопы — оператора, отпускание jog — его не покрывают»; «Стоп оператора выключение не покрывает». Стоп паузы идёт через `_operator_stop` — по смыслу это стоп оператора.
- ADR-PH-004 п.4 (`Plugins/hub/device_hub/DECISIONS.md:42+`): стоп уходит на каждом `pause`; решение владельца 2026-11-16: ОСТАНОВИТЬ для v2 = stop SOFT.
- «Ровно один стоп на выключение» (ADR-DH-009) соблюдено: в выключении одна запись (9); запись 5 — пауза перед ним.
- Шов двух решений: ни один ADR не говорит явно, что штатный стоп из running даёт роботу две SOFT подряд. Это вывод из чтения кода.

## Почему α считал нормой одну запись
- `scripts/alpha_sim/logic.py:860–904` `judge_stop`: `len(stops) != 1` → FAIL (`:892–893`); введён в `588b97be2` (2026-11-10). Тогда стенд видел одну запись: `docs/reports/2026-11-10_word-layout_P4.md:27` — `STOP_REQ [17]`, `[21]`, `[5]`.
- Что изменилось позже: `d96f07655` (11-13, пауза перед событиями стопа), `604d3d071` (11-16, `pause` шлёт роботу стоп), `4207d486f` (11-16), `5429f5f17` (11-17). Связь по `git log -S`, на промежуточных коммитах не воспроизводилась.

## Отвергнутые гипотезы
- О5 клиента (`client_v2.py:621` `_reissue_stop_if_overtaken`): между #660 и #663 нет `CMD_FLAG`.
- Повтор после упавшей записи (`stop.py:99–111`): в логах нет «стоп процесса не записан»; 5 записана до `request_stop`.
- Стоп из `disconnect()`: ветка `if not shutdown`.
- SOFT программе при старте park (`ops.py:160–161`): только при живой программе и до `accept`.
- Команда `robot_stop` оператора/пульта (уверенность средняя): в `performance.log:42` нет команды stop, `robot_park_all` count 2.0.

## Уверенность
- `STOP_REQ = 9` — стоп процесса: HIGH (совпадение по миллисекунде с MSG:55, цепочка доказана кодом).
- `STOP_REQ = 5` — `pause_action` робота: MEDIUM-HIGH (PM:105, запись через 10 мс после итога pre_stop, парная запись стопа ПЧ через 1 мс, нет команды stop; прямой строки лога о вызове `pause` нет).

## Безопасность для робота и прошивки v2
- `plans/robot-protocol-v2/protocol-spec.md` §8 п.1: значение обрабатывается, если отличается от последнего обработанного (5 ≠ 9 — оба); п.4: «Стоп в простое — только эхо в `TLM_STOP_ACK`». Робот простой (серво OFF RX:667, RX:674) — движения нет, `ERR_EVT` не растёт.
- Сим так же: `sim_core_v2.py:771–791` `_handle_stop` при `_active is None` пишет только `TLM_STOP_ACK = value`.
- Реальная прошивка (Lua на Delta): НЕ проверено; ADR-PH-004: «безвредность повторного `stop` v2 … на железе не проверена».
- Риск роста числа записей: если `pause` упадёт, оркестратор повторяет его раз в секунду, и каждый повтор шлёт новый SOFT (ADR-PH-004). В этом прогоне повторов не было.

## Рекомендация (код не правился)
1. Критерий α для стопа из running (признак — строка PM «shutdown из running: … затем ожидание paused»): после последнего `SERVO` pre_stop ровно две записи SOFT (`n % 4 == 1`) с соседними seq; первая до «Stop signal received», вторая после «DeviceHubPlugin: request_stop»; между и после них нет `CMD_FLAG`, нет HARD/HALT; `disconnect` после второй. Для стопа не из running — «ровно одна SOFT». Проще и слабее: «последняя `STOP_REQ` перед disconnect — SOFT, всего ≤ 2, все SOFT, без команд между ними».
2. Норма «одна» или «две» — решение владельца (шов ADR-DH-009 и ADR-PH-004). Если нужна одна запись — правка драйвера: `request_stop_begin` не сбрасывает защёлку, если SOFT паузы уже записан, движения нет, эхо получено; сужает ADR-DH-009, требует ADR; цена — потеря гарантии «выключение всегда пишет свой стоп».
3. Для T4.x на железе: после пары 5 → 9 проверить `TLM_STOP_ACK == 9`, `TLM_ERR_EVT` не вырос, серво и ПЧ в ожидаемом состоянии.

## Что я оставил открытым / ненадёжным
- Вызов `DeviceHubPlugin.pause` в этом прогоне выведен из косвенных признаков; прямое доказательство — лог `pause_all`/trace (сейчас `trace.log` пуст) и повтор прогона.
- Эхо стопа 5 не проверено: журнал обмена не пишет чтения `TLM_STOP_ACK`; `_operator_stop` без эха отвечает `echo: False` без предупреждения (`ops.py:104–107`).
- Связь «вторая запись появилась с 604d3d071» — по `git log -S` и отчёту 11-10; промежуточные коммиты не прогонялись.
- Реальная прошивка v2 на двух SOFT в простое не проверена.
- Был ли 11-10 стоп из running — не выяснено.
- Привязка `0x1204` к `VFD_FLAG` выведена из `client.py:115` и порядка полей.
- Вопрос для `docs/claude/OPEN_QUESTIONS.md`: считать ли две SOFT (пауза + выключение) нормой при стопе из running, или защёлке выключения покрывать SOFT паузы.
