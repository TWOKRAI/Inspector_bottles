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

---

## Передача 2 (второй разработчик, тот же день): снова мягкий бюджет контекста

**Сделано:** прочитаны все файлы части 2, дизайн сверен с кодом чтением. **Исходники не менялись, прогонов не было** (ни базы слепого файла, ни замера STOP), окно гейта не запрашивал. HEAD `4599cd497`, в дереве изменён только этот файл.

Следующему: не перечитывать план и отчёт тестера. Открыть только 7 исходников из FILES и применить список правок ниже. Базу и замер STOP (механика) можно отдать `test-runner` или haiku до запуска разработчика.

### СНАЧАЛА решение лида: два теста вне FILES покраснеют (по чтению, не прогнано)

- `Services/device_hub/tests/test_robot_driver_v2.py:886-897`: `device = drv.transport` (это обёртка `ExchangeLogTransport`), `device.transaction = transaction`, у подмены сигнатура `(ops)`.
- `Services/device_hub/tests/test_robot_driver_v2_jobs_acceptance.py:366-380` (`_install_cvt_barrier`): то же. Это слепая приёмка прежней задачи.
- Обе подмены ловят `JOG_CONT` / `CVT_JOB`, то есть путь `cmd()`. Клиент, зовущий `transaction(ops, expected_session=s)`, получит `TypeError`.

Варианты:
- (а) лид разрешает в обеих подменах принять `**kw` и передать в `original` (рекомендую: по две строки, смысл тестов тот же);
- (б) клиент смотрит сигнатуру и зовёт по-старому: тихий обход проверки в пути движения, не рекомендую;
- (в) отдельный метод транспорта вместо аргумента: подмены не сработают, барьеры не взведутся, тесты тоже покраснеют.

`test_t56_exchange_log_acceptance.py:608` (`lambda ops`): проверить прогоном.

### Уточнения дизайна по коду

1. `issue_stop` (`client_v2.py:730-731`) у проверенного клиента уже пишет без оглядки на `is_connected`. Для Д6 в клиенте нужно только свойство `probed`.
2. `probe()` сбрасывает `_probed` на входе (`client_v2.py:357`). Неудачная перепроба = «не проверен», STOP не пишется. Это остаток из задачи.
3. `ModbusIOError` и `ModbusConnectionError` — соседи (`Services/modbus/sdk/errors.py:24,28`): `except ModbusConnectionError` ошибку провода не поймает.
4. Следствие Д6 (по чтению `state.py:461-496, 528-538`), **сообщить лиду**: после штатного `disconnect()` и после «тик заметил обрыв» запись STOP будет пытаться и падать. Было: уровень 0, тишина. Станет: до двух попыток, `stop_unconfirmed=True`, `last_error` «стоп не подтверждён роботом» (виден в health, в том числе у робота, отключённого оператором, при выключении процесса). Ограничить через `desired_connected` нельзя: `request_disconnect` снимает его ДО `disconnect()`, и Д6 на пути «Отключить» пропадёт.
5. Дублёры клиента (`client_factory`, `_fake_driver`) могут не иметь `admission` / `admitted` / `probed`: миксины идут только через помощники драйвера.
6. Форма очереди v2: по grep тесты v2 берут только длину (`test_robot_v2_ops.py:679`) или работают с `RobotState` напрямую; распаковка 5 полей в `test_encoder_offset.py` — это v1. 6 и 4 поля безопасны.

### Список правок (номера строк на `4599cd497`)

**`client_v2.py`**
- Импорт `ModbusConnectionError` из `Services.modbus.sdk.errors`, `contextmanager`.
- `class SessionChanged(RobotNotConnectedError)` рядом с `SyncCancelled` (:230).
- `__init__`: `self._admission = threading.local()`.
- `admitted(session)` (контекст: прежнее значение восстановить в `finally`), `admission() -> int | None`, свойство `probed` (`return self._probed`).
- `_wr_admitted(ops)` рядом с `_wr` (:413): `s = self.admission()`; если `s is None` или `getattr(self._t, "session", None) is None` -> `return self._wr(ops)`; иначе `self._t.transaction(ops, expected_session=s)`; `except ModbusConnectionError` -> `_mark_stale()`, `raise SessionChanged(...) from exc`; прочее -> `_mark_stale()`, `raise`.
- Только три вызова: `jog_lease` (:482), `cmd` (:513), `_upload` (:986). В `cmd` вокруг него `except SessionChanged: self._inflight = None; raise`.

**`driver.py`**
- `from contextlib import nullcontext`; в `__init__` поле `self._park_session: int | None = None`.
- Помощники: `_session_now()` = `getattr(self._transport, "session", None)`; `_admission()` = `client.admission()` если метод есть, иначе None; `_admitted_as(s)` = `client.admitted(s)` если есть, иначе `nullcontext()`.
- `call()` (:649-653): `with self._admitted_as(self._session_now()): return handler(self, args)` внутри `try`.
- `_park_servo_off` (:623): `with self._admitted_as(self._park_session)`.
- `_run_on_connect` (:400): всё тело под `_admitted_as(self._session_now())`.

**`ops.py`** `_op_park`: `self._park_session = self._admission()` перед `self._park.accept(...)` (:162).

**`programs.py`**
- `_launch`: `session = self._admission()`; `if session is None: session = self._session_now()` — до `admit_launch` (:90; 0 — годное значение, проверять `is None`).
- `_program_loop(..., session)`: `run_chunks` (:162) под `_admitted_as(session)`.
- `start_park_home`: `_launch` под `_admitted_as(self._park_session)`. `_launch` читает `_admission()` внутри этого контекста.

**`jog.py`** `_op_jog_hold`: `session = self._admission()`; `spawn(lambda ev: self._lease_loop(run, ev, session))`; в `_lease_loop` весь `try` под `_admitted_as(session)` (`threading.local` в новый поток не переходит).

**`jobs.py`**
- `_op_enqueue_job`: 6-е поле записи = `self._admission()`; `_run_next_job` распаковывает 6, `requeue_job(job)` сохраняет всё.
- `_op_return_job`: 4-е поле; `_start_next_return`: распаковать 4, `start_return` под `_admitted_as(session)`.
- `cvt_job` под `_admitted_as(session)`; ветка `except SessionChanged` ДО общей `except Exception`: `jobs_failed += 1`, `_publish_error(...)`, `_link_lost()` НЕ звать.

**`exchange_log.py`** `transaction(self, ops, *, expected_session=None)` (:442): `kw = {} if expected_session is None else {"expected_session": expected_session}`, передать в оба вызова `self._inner.transaction`.

**`stop.py`**: метод `_stop_reachable()` = `client is not None and (self.is_connected or getattr(client, "probed", False))`; передать вместо `lambda: self.is_connected` в `process_stop_plan` (:93) и `disconnect_soft_plan` (:210). `_transport_up` не менять.

### Замер STOP после тика (сначала на неизменённом коде; скрипт не прогонялся)

Положить в scratchpad, запускать с `PYTHONPATH=<корень дерева>` через гейт в окне:

```python
import time
from Services.device_hub.tests import test_r2s1a_link_drop_acceptance as t

for how in ("request_stop", "disconnect"):
    for kind in ("fin", "rst"):
        for prep in ("idle", "jog_step"):
            for point in ("heartbeat", "tlm"):
                with t._v2() as rig:
                    if prep == "jog_step":
                        assert rig.call("jog_step", t._JOG_STEP)["status"] == "ok"
                        rig.wait_robot_idle()
                    pred = (lambda f: True) if point == "heartbeat" else (lambda f: f.fc == 3)
                    rule = rig.srv.on_next(pred, kind)
                    t.run(lambda: rig.drv.tick(None), 30.0)
                    link = (rig.drv.is_connected, rig.drv.transport.is_connected)
                    mark = rig.srv.mark()
                    if how == "request_stop":
                        t.run(lambda: rig.drv.request_stop(time.monotonic() + 20.0), 30.0)
                    else:
                        t.run(rig.drv.disconnect, 30.0)
                    time.sleep(0.5)
                    n = len(t._writes_at(rig.srv.frames(mark), t._STOP_REQ))
                    print(how, kind, prep, point, "dropped", rule.entered.is_set(), "link", link, "STOP_REQ", n)
```

Прогноз по чтению: 0 кадров во всех случаях и до, и после (`_link_lost` закрыл клиента). Меньше после — стоп и лиду.
