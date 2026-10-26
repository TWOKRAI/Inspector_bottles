# SPI хаба — приёмка (вход слепого tester), ред. 2

База main `9b6645546`. Бриф — `tasks/SPI.md` (tester его не читает).

## Правила

- Тесты пишутся ТОЛЬКО по строкам этого файла; ожидаемые значения — литералы отсюда.
- Не читать: `Services/device_hub/spi.py`, `manager.py`, `errors.py`, `robot_data_ops.py`, `Services/device_hub/drivers/**`,
  `Plugins/hub/device_hub/plugin.py`, файлы `plans/robot-protocol-v2/tasks/SPI*.md`, кроме этого, диффы ветки.
  Исключение — А8: AST-скан исходника плагина (только имена узлов, без чтения тел).
- Читать можно: тесты и `conftest.py` каталогов `Services/device_hub/tests`, `Plugins/hub/device_hub/tests`; тесты
  фреймворка `multiprocess_framework/modules/{process_module,router_module,command_module}/tests` (образцы цепочки).
- Файлы tester: `Services/device_hub/tests/test_spi_acceptance.py`, `Plugins/hub/device_hub/tests/test_spi_commands_acceptance.py`,
  `multiprocess_framework/modules/process_module/tests/test_plugin_command_options_acceptance.py` (А26, А27).
- Сторож `Services/device_hub/tests/test_no_private_driver_state.py` сканирует все `*.py` двух каталогов хаба: приватные
  имена драйвера (`_client`, `_ready`, `_epoch`, `_transport`, …) в файлах tester — красный сторож. Нужен клиент — через
  публичные фикстуры `conftest.py`; нельзя без приватного — стоп, вопрос лиду.
- Пути импорта: `from Services.device_hub.spi import OpSpec, OpSource, command_table, DEFAULT_SOURCES, ROBOT_V1_OPS,
  ROBOT_V2_OPS, ROBOT_DATA_OPS, VFD_OPS, DeviceDriver, StopAwareDriver`;
  `from Plugins.hub.device_hub.plugin import DeviceHubPlugin, install_op_commands`;
  `from Services.device_hub.errors import RegisterTransportUnavailable`.
- Метка `[c2]`, `[d]` — строка проверяется после подзадачи c2 / d2 (до неё тест помечается `xfail(strict=True)` лидом).

## Команды и генерация

- [ ] А1. `set(DeviceHubPlugin.commands)` == 72 имени: `device_list, device_describe, device_upsert, device_upsert_many,
  device_sync_set, device_remove, device_protocols, device_connect, device_disconnect, device_read, device_write,
  robot_enqueue_job, robot_return_job, robot_send_test_job, robot_abort, robot_set_mode, robot_jog, robot_jog_abort,
  robot_set_servo, robot_set_robot_config, robot_get_robot_config, robot_get_telemetry, robot_read_echo,
  robot_set_manual_mode, robot_clear_queue, robot_set_encoder_offset, robot_toolchange, robot_exchange_log_get,
  robot_exchange_log_set, robot_param_get_all, robot_point_list, robot_point_save, robot_point_delete, robot_frame_list,
  robot_frame_teach, robot_program_list, robot_program_get, robot_program_save, robot_program_delete, robot_param_set,
  robot_param_apply, robot_stop, robot_servo, robot_do_set, robot_jog_step, robot_jog_hold, robot_jog_release,
  robot_point_capture, robot_program_run, robot_program_abort, robot_draw_polyline, robot_draw_circle, robot_draw_square,
  robot_draw_set_pen, robot_draw_set_speed, robot_draw_set_travel, robot_draw_set_accel, robot_draw_set_pass_size,
  robot_draw_set_overlap, robot_draw_abort, robot_draw_progress, vfd_run, vfd_set_freq, vfd_stop, vfd_reset_fault,
  vfd_get_status, hik_enum, hik_open, hik_close, hik_get_params, hik_set_params, hik_release`.
- [ ] А2. `_do_configure` + `_do_start` с настоящим `CommandManager`: у всех 72 `get_command_info(имя)` не `None`; в логе
  нет `already exists` и `Failed to register command`.
## Описания в каталоге

- [ ] А3. После `_do_start` — `get_command_info(имя)["metadata"]["description"]` равно литералу. 21 команда робота v2:
  `robot_param_get_all` «Робот v2: все параметры из файла {device_id} -> params{raw, value}, epoch, rev»;
  `robot_point_list` «Робот v2: список точек {device_id} -> points, rev»; `robot_point_save` «Робот v2: сохранить точку
  {device_id, point{name, x, y, z, rz, hand, frame?}, base_rev}»; `robot_point_delete` «Робот v2: удалить точку
  {device_id, name, base_rev}»; `robot_frame_list` «Робот v2: список систем координат {device_id} -> frames, rev»;
  `robot_frame_teach` «Робот v2: обучить СК по трём точкам {device_id, name, origin, on_x, in_plane, base_rev}»;
  `robot_program_list` «Робот v2: имена программ {device_id} -> programs»; `robot_program_get` «Робот v2: прочитать
  программу {device_id, name} -> program, rev»; `robot_program_save` «Робот v2: сохранить программу {device_id,
  program{name, steps}, base_rev}»; `robot_program_delete` «Робот v2: удалить программу {device_id, name, base_rev}»;
  `robot_param_set` «Робот v2: записать параметр {device_id, name, value, base_rev}»; `robot_param_apply` «Робот v2:
  применить параметры класса reinit {device_id}»; `robot_stop` «Робот v2: стоп {device_id, level: SOFT|HARD|HALT}»;
  `robot_servo` «Робот v2: серво {device_id, on: bool}»; `robot_do_set` «Робот v2: дискретный выход {device_id,
  ch: 1..16, on: bool}»; `robot_jog_step` «Робот v2: шаг jog {device_id, dx, dy, dz?, drz?, spd: 1..100}»;
  `robot_jog_hold` «Робот v2: удержание jog {device_id, dir: 1..8, spd: 1..100}»; `robot_jog_release` «Робот v2:
  отпустить jog {device_id}»; `robot_point_capture` «Робот v2: запомнить текущую позу как точку {device_id, name,
  base_rev}»; `robot_program_run` «Робот v2: запустить программу {device_id, name}»; `robot_program_abort` «Робот v2:
  прервать программу {device_id}».
  `[c2]` 34 остальных: `robot_enqueue_job` «Поставить CVT-задание: {device_id, x_mm, y_mm, e_capture?}.»;
  `robot_return_job` «Возврат буквы на ленту: {device_id, x_mm, y_mm, z_mm} (координата слота).»; `robot_send_test_job`
  «Тестовое CVT-задание: {device_id, x, y}.»; `robot_abort` «Стоп робота: {device_id, mode: 1|2|3}.»; `robot_set_mode`
  «Режим робота: {device_id, mode: cvt|draw|manual}.»; `robot_jog` «Ручной ход: {device_id, dx, dy, spd?, absolute?} —
  смещение мм + Override %.»; `robot_jog_abort` «Прервать ручной ход: {device_id}.»; `robot_set_servo` «Серво:
  {device_id, on: bool}.»; `robot_set_robot_config` «Конфиг робота: {device_id, ...fields}.»; `robot_get_robot_config`
  «Прочитать конфиг-блок робота.»; `robot_get_telemetry` «Телеметрия робота.»; `robot_read_echo` «Эхо последнего
  задания.»; `robot_set_manual_mode` «Ручной режим: {device_id, on: bool}.»; `robot_clear_queue` «Очистить очередь
  заданий.»; `robot_set_encoder_offset` «Подстройка компенсации конвейера: {device_id, lead_mm} (мм вдоль ленты,
  знаковое).»; `robot_toolchange` «Смена инструмента: {device_id, target: 0|1|2, timeout?}.»; `robot_exchange_log_get`
  «Журнал обмена драйвера: {device_id, since_seq?, limit?}. Работает и при разрыве связи (T5.6).»;
  `robot_exchange_log_set` «Ручки журнала обмена: {device_id, enabled?, periodic?, clear?} (T5.6).»;
  `robot_draw_polyline` «Нарисовать полилинию: {device_id, points, ...}.»; `robot_draw_circle` «Нарисовать окружность:
  {device_id, cx, cy, r}.»; `robot_draw_square` «Нарисовать квадрат по двум углам: {device_id, x1, y1, x2, y2, z?}.»; `robot_draw_set_pen`
  «Установить перо: {device_id, down?, up?} (мм, можно одно из двух).»; `robot_draw_set_speed` «Установить скорость рисования (перо по бумаге):
  {device_id, pct}.»; `robot_draw_set_travel` «Установить скорость переезда (перо вверх): {device_id, pct}.»;
  `robot_draw_set_accel` «Установить ускорение рисования: {device_id, accel} (мм/с²).»; `robot_draw_set_pass_size`
  «Установить размер пачки рисования: {device_id, n} (точек на проход).»; `robot_draw_set_overlap` «Установить overlap:
  {device_id, mm}.»; `robot_draw_abort` «Прервать рисование: {device_id}.»; `robot_draw_progress` «Прогресс
  рисования: {device_id}.»; `vfd_run` «Пуск ПЧ: {device_id, direction?, freq_hz?}.»; `vfd_set_freq` «Установить частоту:
  {device_id, freq_hz}.»; `vfd_stop` «Стоп ПЧ: {device_id}.»; `vfd_reset_fault` «Сброс аварии ПЧ: {device_id}.»;
  `vfd_get_status` «Статус ПЧ: {device_id}.».
  До c2 у этих 34 ключа `description` в `metadata` нет.
## Маршруты и генерация

- [ ] А4. Вызов метода плагина без `device_id` (`cmd_robot_stop`, `cmd_robot_point_list`, `cmd_robot_exchange_log_get`,
  `cmd_vfd_run`, аргумент `{}`) → `{"status": "error", "message": "device_id обязателен"}`.
- [ ] А5. `cmd_robot_stop` для устройства вида `vfd` → `status == "error"`, `message` содержит `ожидается 'robot'`;
  `cmd_vfd_run` для робота → содержит `ожидается 'vfd'`.
- [ ] А6. `cmd_robot_exchange_log_get` у созданного, не подключённого робота `delta_v2` → `status == "ok"`; у робота без
  созданного драйвера → `{"status": "error", "message": "журнала нет: драйвер не создан"}`.
- [ ] А7. `cmd_robot_point_list` у не подключённого робота `delta_v2` с хранилищем → `status == "ok"`, ключи `points`,
  `rev`; `cmd_robot_servo` у него же → `status == "error"`, `message == "Устройство '<id>' не подключено"`.
- [ ] А8. AST `Plugins/hub/device_hub/plugin.py`, класс `DeviceHubPlugin`: ровно 17 `FunctionDef` с именем `cmd_*`
  (11 `cmd_device_*` + 6 `cmd_hik_*`); ни одного `FunctionDef`, `Assign`, `AnnAssign` с именем `cmd_robot_*` /
  `cmd_vfd_*`; в литерале словаря `commands` в теле класса нет ключей `robot_*` и `vfd_*`.
- [ ] А9. `class Sub(DeviceHubPlugin): pass`; `install_op_commands(Sub, [OpSource(prefix="fake", kind="fake",
  route="driver", ops=(OpSpec(name="ping", description="Фейк: пинг"),))])` → `"fake_ping" in Sub.commands`;
  `set(DeviceHubPlugin.commands)` — по-прежнему 72 имени А1, `hasattr(DeviceHubPlugin, "cmd_fake_ping") is False`. Фабрика
  `fake` в менеджере экземпляра `Sub` возвращает подключённый драйвер-наследник `BaseDeviceDriver` с
  `call("ping", {}) -> {"status": "ok", "pong": 1}`; `Sub.cmd_fake_ping({"device_id": <id>})` → `{"status": "ok", "pong": 1}`.
- [ ] А10. `ValueError`: (а) `install_op_commands` с именем, уже лежащим в `commands` класса; (б) `command_table` с двумя
  `OpSource` одного префикса и одноимёнными `OpSpec`, разными по `description`; (в) то же, разными по `needs_link`;
  (г) `OpSpec(name="x", executor="device_io", immediate=True)`.
- [ ] А19. Фейк-драйверы видов `robot` (протокол `delta_v2` и v1) и `vfd` пишут `(op, args)` в `call`; каждая из 40
  команд робота маршрута «драйвер» и 5 `vfd_*` с `{"device_id": <id>, "k": 1}` вызывает `call` с `op` == имя команды
  без префикса `robot_` / `vfd_` (например `robot_jog_hold` → `"jog_hold"`, `vfd_set_freq` → `"set_freq"`) и
  `args == {"k": 1}`.

## Контракт драйвера

- [ ] А11. `VfdDriver` и `HikvisionDriver` (запись реестра, без подключения): `disconnect_pending is False`,
  `stop_unconfirmed is False`, `stop_unconfirmed_text is None`, `transport is None`, `last_io is None`,
  `request_disconnect()` → `None` без исключения; `HikvisionDriver.set_degraded()` → `False`.
- [ ] А12. Множество `{(источник, s.name) : s.immediate}` по каталогам: `immediate=True` ровно у
  `ROBOT_V2_OPS`: `stop, abort, jog_hold, jog_release, program_abort`; `ROBOT_V1_OPS`: `abort, jog_abort, draw_abort,
  clear_queue, set_servo`; `VFD_OPS`: `stop`. `executor == "device_io"` ровно у 10 `ROBOT_DATA_OPS` `[d]` (до d2 —
  ни у одной); ни у одной операции нет одновременно `executor` и `immediate`.
- [ ] А13. `device_read` у подключённого драйвера вида `vfd` — наследника `BaseDeviceDriver` с протоколом и без
  транспорта → `{"status": "error", "message": "у устройства нет транспорта регистров"}`;
  `issubclass(RegisterTransportUnavailable, DeviceHubError)`.
- [ ] А16. Классы `RobotDriver`, `RobotDriverV2`, `VfdDriver`, `HikvisionDriver`, `GenericModbusDriver`; экземпляр
  каждого создаётся с записью реестра своего вида без подключения. На КЛАССЕ: `kind`, `OP_SPECS`, `stop_aware`, методы
  `connect, disconnect, tick, call, reset_reconnect, request_disconnect, set_degraded`; `cls.stop_aware ==
  hasattr(cls, "request_stop")`; `stop_aware` истинно только у `RobotDriverV2`. На ЭКЗЕМПЛЯРЕ: `entry, protocol,
  desired_connected, reconnect_exhausted, transport, disconnect_pending, stop_unconfirmed, stop_unconfirmed_text,
  last_io, is_connected, stats` (N8 р.2).
- [ ] А20. Носитель моста отключается (`device_disconnect` носителя): зависимый драйвер с `set_degraded()` → `True`
  получает публикацию `devices.state.<dep>.conn` = `{"conn": "disconnected"}`; зависимый-наследник базы без своего `set_degraded` — такой публикации нет, его `disconnect()` не вызван. Два
  зависимых, первый — простой объект без `set_degraded` (бросает `AttributeError`): второй (`set_degraded() -> True`) всё
  равно получает `{"conn": "disconnected"}`, `device_disconnect` носителя отвечает без исключения.
- [ ] А21. Подкласс `BaseDeviceDriver`, присваивающий в `__init__` `self.transport`, `self.disconnect_pending`,
  `self.stop_unconfirmed`, `self.last_io`, создаётся без исключения и отдаёт присвоенные значения.

## Остановка, «Отключить», изоляция

- [ ] А14. `device_disconnect` у робота `delta_v2` посреди `connect` (барьер, как в `test_c29_disconnect_acceptance.py`)
  → `disconnect_pending` драйвера `True` до разбора очереди; итог `conn` = `disconnected`. У `MagicMock`-драйвера (без
  `spec`) `connect` → `False` публикует `{"conn": "error"}`, не `disconnecting`.
- [ ] А15. Остановка плагина с роботом `delta_v2` и ПЧ: поток `stop-<id>-<k>` создан только для робота.
- [ ] А24. Остановка плагина, в реестре два устройства: драйвер-фейк — простой объект без атрибутов `stop_unconfirmed`
  и `stop_aware`, и наследник базы. `shutdown(ctx)` завершается без исключения; `disconnect()` наследника вызван; реестр
  сохранён.
- [ ] А25. `device_disconnect` у устройства, чей `request_disconnect()` бросает `RuntimeError`: ответ
  `{"status": "ok", "conn": "disconnecting"}`; supervisor доводит до `conn` = `disconnected`; `health.report_error`
  вызван с `context="device_hub.request_disconnect"`.

## Исполнитель и хук фреймворка `[d]`

- [ ] А17. Процесс с `config["executors"] = {"device_io": {}}` → `_do_configure` + `_do_start` плагина → запрос
  `robot_point_list` `{"device_id": <робот delta_v2>}` по пути роутера: `reply_to_request` вызван ровно один раз,
  результат `status == "ok"`; обработчик исполнен не на потоке роутера. `metadata` читается после `_do_start`.
- [ ] А18. После `_do_start` с исполнителем `device_io`: у `robot_point_list` `metadata` содержит `executor ==
  "device_io"`, `key_from == "device_id"` и `description` (А3) одновременно; у `robot_stop`, `robot_jog_hold`,
  `vfd_stop` ключа `executor` нет.
- [ ] А22. Тот же процесс: `robot_point_list` по пути роутера без `device_id` → ответ `{"success": False,
  "error": "key_missing", "command": "robot_point_list"}`.
- [ ] А23. Процесс без секции `executors`: `robot_point_list` зарегистрирована, вызов без `reply` отвечает синхронно
  `status == "ok"`; в логе на эту команду ровно одна строка WARNING `CommandManager` с текстом
  `Command 'robot_point_list' не зарегистрирована: исполнитель 'device_io' не найден`; строк WARNING с `исполнитель не
  принят` нет (хук пишет её на INFO).
- [ ] А26. Плагин без `command_options`: `register_command` вызывается с ровно двумя позиционными аргументами
  `(имя, метод)` и без именованных (как до правки); плагин с `command_options(name) -> {"handler": 1}` — команда
  зарегистрирована без опции, одна строка ERROR.
- [ ] А27. `command_options` плагина возвращает исполнитель для имени, уже зарегистрированного другим плагином: повтора
  регистрации нет, одна строка ERROR, строки `исполнитель не принят` нет.
