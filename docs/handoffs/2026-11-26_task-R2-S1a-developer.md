# Передача: R2-S1a, часть 2 (драйвер робота v2) — разработчик

Дата: 2026-11-26, ~22:30. Причина: мягкий бюджет контекста (хук проекта), работы осталось больше 30 вызовов.

## Состояние

- Дерево `.claude/worktrees/r2-modbus`, ветка `fix/modbus-link-drop`, HEAD `24f204f13` (часть 1 закоммичена и принята).
- **По части 2 не изменён ни один файл.** Прогонов части 2 не было, базовый прогон слепого файла не снят. Окно гейта не запрашивал.
- Не коммитить, не пушить. Не открывать папки scratchpad `r2s1a_plan`, `cto`, `r2s1a_tester`. Реального робота и не-loopback адресов не касаться. Имя сессии: `inspector-bottles-8d`.

## Читать первым

1. `plans/robot-protocol-v2/tasks/R2-S1a.md` — Д4-Д7, уточнения лида, A11-A16, инъекции, остатки.
2. `docs/reviews/2026-11-26_task-R2-S1a-tester.md` — заметки слепого тестера.
3. Этот файл.

FILES части 2: `Services/robot_comm/core/client_v2.py`; `Services/device_hub/drivers/robot_driver_v2/` (driver, ops, jobs, programs, jog, stop); `Services/device_hub/drivers/exchange_log.py`; новый `Services/device_hub/tests/test_r2s1a_hazards.py`; доки тронутых модулей при смене контракта. Что-то вне списка — остановиться и сообщить лиду.

Слепой файл `Services/device_hub/tests/test_r2s1a_link_drop_acceptance.py` (40 тестов) не менять. Спорный красный — лиду со входом и наблюдаемым выходом. Файл переформатирован после последнего прогона, поэтому сначала снять базу на неизменённом коде.

## Дизайн (продуман по чтению, прогоном не проверен)

**client_v2.py**
- Допуск — thread-local на клиенте: контекст `client.admitted(session)` и чтение `client.admission()`. Свойство `probed` (сейчас `_probed`).
- Новый `class SessionChanged(RobotNotConnectedError)`.
- `_wr_admitted(ops)`: допуска нет или у транспорта нет `session` -> прежний `_wr` (Д7). Иначе `self._t.transaction(ops, expected_session=...)`; `ModbusConnectionError` -> `_mark_stale()`, `SessionChanged` (на провод ничего не ушло: ошибка провода в части 1 даёт `ModbusIOError`).
- `_wr_admitted` только в трёх местах: `cmd()` (~строка 513), `_upload` (~986), `jog_lease` (~482). `kick_heartbeat`, `_issue_stop_locked` остаются на `_wr` (Д5), даже внутри контекста.
- В `cmd()`: `except SessionChanged: self._inflight = None; raise` — метка ставится до записи (~512).

**driver.py**
- Помощник: `getattr(self._transport, "session", None)`. `ExchangeLogTransport.__getattr__` его уже пропускает.
- Один центральный допуск в `call()` (~645): значение читается ДО обработчика, обработчик идёт внутри `client.admitted(...)`. Это покрывает servo, do_set, jog_step, jog_cont, param_set, param_apply, calib_belt без правки `params.py` (его нет в FILES). `client` может быть None или дублёром без `admitted` -> `nullcontext`.
- `_park_servo_off` (~615): под `admitted(self._park_session)`.
- `_run_on_connect` (~400): SERVO и DO под значением, снятым сразу после `transport.connect()`.

**Асинхронные пути (значение переносится явно)**
- `jog.py`: в `_op_jog_hold` взять `client.admission()`, передать в `_lease_loop` (`spawn(lambda ev: ...)`), там весь цикл под `admitted`.
- `programs.py`: `_launch` берёт `client.admission()`; если None (прямой вызов `start_program` / `start_toolchange`) — текущий `session` в начале `_launch`, до `admit_launch`. Проверять `is None`: 0 — годное значение. `_program_loop` оборачивает `run_chunks` один раз. `start_park_home` — под `admitted(self._park_session)`.
- `ops.py`: `_op_park` сохраняет `self._park_session` ДО `self._park.accept(...)` (инициализировать поле в `driver.__init__`).
- `jobs.py`: `_op_enqueue_job` / `_op_return_job` кладут значение допуска в запись очереди (6-я и 4-я позиция кортежа; `requeue_*` его сохраняют). `_run_next_job`: `cvt_job` под `admitted`; отдельная ветка `except SessionChanged` ДО общей `except Exception` — задание считается неудачным, `_link_lost()` НЕ звать (иначе оборвётся уже новое соединение). `_start_next_return`: `start_return` под `admitted(значение)`.
- `state.py` не в FILES: алиас `_Job` останется с 5 полями (только аннотация). Проверить, что тесты не разбирают очередь по форме (`grep job_queue Services/device_hub/tests`); сообщить лиду.

**exchange_log.py (Д7)**: `transaction(self, ops, *, expected_session=None)`, внутреннему передавать только если не None. Проверить тесты, подменяющие `transaction` атрибутом экземпляра (`grep "\.transaction = "`): с новым аргументом они упадут.

**stop.py (Д6)**
- Предикат `client is not None and (self.is_connected or getattr(client, "probed", False))`.
- Передать его вместо `lambda: self.is_connected` в `process_stop_plan` (~91) и `disconnect_soft_plan` (~210). `state.py` править не нужно.
- STOP при job / jog / программе (`_request_stop`, ~184-205) от флага связи не зависит.

## Открытые вопросы дизайна — измерить и сообщить лиду, не изобретать

1. **STOP после того, как тик заметил обрыв.** `_link_lost` зовёт `transport.disconnect()` -> `ModbusSdkClient._client = None`; запись STOP тогда даёт «Клиент не подключён» и не уходит. Переподключать ли ради стопа — решение лида. A13 тестера обрыв замечает чтением, не тиком, и этот случай не покрывает.
2. После штатного `disconnect()` клиент остаётся проверенным: `request_stop` будет пытаться писать в закрытый транспорт (две попытки, WARNING). Посмотреть, не красит ли это существующие тесты.

## Тесты и приёмка

- Свои опасности: метка «в полёте» на `jog_step` и `jog_hold`; STOP при программе, jog, задании; `param_apply` после обрыва.
- Каждый прогон через гейт: `PYTHONPATH=<корень дерева> PYTHONUTF8=1 PYTHONDONTWRITEBYTECODE=1`, python — `.venv` основной копии.
- Пути `Services/device_hub`, `Services/robot_comm` timed: нужно окно. `bash /d/PROJECT_INNOTECH/Inspector_vision/Inspector_bottles/scripts/machine_gate.sh request inspector-bottles-8d heavy <мин> <что>`, затем `wait inspector-bottles-8d --timeout <мин>`, прогон, сразу `release inspector-bottles-8d`. Чужое heavy-окно — до ~22:46. Пока пишется код, окно не держать.
- В окне: слепой файл, свои тесты, весь `Services/robot_comm/tests` (в нём `test_client*.py`, не прогнанные в части 1 — назвать в отчёте), весь `Services/device_hub/tests`, `scripts/validate.py`, ruff.
- Инъекции, прогноз записать до прогона: убрать передачу из `cmd` / `_upload` / `jog_lease` по отдельности; брать значение в момент записи; вернуть проверку флага в `stop.py`; убрать снятие метки «в полёте». Исходники восстановить и сверить sha256. Скрипт матрицы части 1 был во временной папке: резервная копия, замена с `count == 1`, восстановление, сравнение поимённых множеств; `bash` из Python не звать (это WSL).
- Остатки в отчёт, дешёвые проверить на коде до правки: STOP непроверенного клиента после переподключения; `UnboundLocalError` стопа рисования v1 (`robot_driver.py:812-845`); прямой ПЧ не подключается.
- Отчёт: дописать часть 2 в `docs/reviews/2026-11-26_task-R2-S1a-developer.md` (цифры первыми, раздел «что открыто»).

## Из части 1, важное здесь

- `ModbusDevice.session` читается без замка; `expected_session` только по имени; отказ = `ModbusConnectionError`, счётчики не трогаются.
- Читать `session` ДО проверки `is_connected`, не после.
- Счётчик живёт в объекте. Драйвер v2 транспорт не пересоздаёт: присваивания только `driver.py:217` (обёртка) и `355-356` (если None) — по чтению и grep.
- Без `expected_session` pymodbus сам открывает новый TCP на следующем вызове.
