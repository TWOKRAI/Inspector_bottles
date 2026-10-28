# SPI хаба — исполнитель по имени (D7) и правка framework (SPI.d)

Бриф — `tasks/SPI.md`. Лид согласует правку framework с координатором ДО правки (SPI.d1). База main `9b6645546`.

## D7. Поля `OpSpec.executor` и `OpSpec.immediate`

- `executor: str | None = None` — имя исполнителя процесса. Не `None` → команда регистрируется с
  `executor=<имя>`, `key_from=<OpSource.key_from>` (умолчание `"device_id"`), `command_manager.py:205-298`.
- `immediate: bool = False` — «никогда не в очередь»: операция останавливает, прерывает, снимает работу или продлевает
  окно с дедлайном. `executor` и `immediate` вместе → `ValueError` в `OpSpec.__post_init__` (при импорте `spi.py`).
- Плагин не держит списков имён: `command_options(name)` читает `(source, spec)` из таблицы команд класса.

### Какие операции `immediate` — из кода (база `9b6645546`)

| вид / операция | основание | строки |
|---|---|---|
| robot `stop` (v2) | пишет `STOP_REQ` через `_write_stop`, «занятость не проверяет» | `robot_driver_v2/ops.py:106-111`, :80-100 |
| robot `abort` (v2 и v1) | v2 — то же тело `_operator_stop`; v1 — `client.stop(mode)` | `ops.py:73-78`; `robot_driver.py:603-606` |
| robot `jog_hold` (v2) | продление окна удержания (`_last_hold`, окно `_HOLD_WINDOW_S`): ожидание в очереди дольше окна → поводок пишет SOFT | `jog.py:39-105`; `state.py:28, 667, 685, 698`; `T5.3d2.amend-2026-10-20.md` (окно 0,2 с) |
| robot `jog_release` (v2) | явный стоп своего jog | `jog.py:107-130` |
| robot `jog_abort` (v1) | `client.jog_abort()` (man_abort) | `robot_driver.py:624-627` |
| robot `program_abort` (v2) | запись SOFT при идущей программе | `programs.py:143-150` |
| robot `draw_abort` (v1) | прерывание прохода, домой, очистка очереди рисования | `robot_driver.py:804-839` |
| robot `clear_queue` (v1) | снимает задания, которые иначе возьмёт дренаж очереди | `robot_driver.py:663-666` |
| robot `set_servo` (v1) | пишет серво без проверки занятости: OFF посреди хода — останов осей | `robot_driver.py:629-632` |
| vfd `stop` | `_vfd_client.stop()` | `vfd_driver.py:227` |

**Не `immediate`** (код не делает их путём остановки): `servo` v2 — отказ при движении (`ops.py:118-120`); `do_set` —
отказ при движении (`ops.py:136-138`); `toolchange` v1 — блокирует до handshake с таймаутом (`robot_driver.py:714-743`),
длинная операция, не стоп; `jog_step` v2 (`ops.py:144-159`) и `jog` v1 (`robot_driver.py:614-622`) начинают движение;
`set_mode`, `set_manual_mode`, `param_*`, `program_run`, `point_capture`, `draw_*` кроме `draw_abort`, `vfd_run`,
`vfd_set_freq`, `vfd_reset_fault`, `vfd_get_status`, `get_*`, `read_echo`, журнал обмена.

### Какие операции на исполнителе сейчас

`executor="device_io"` литералом в `spi.py` — у 10 записей `ROBOT_DATA_OPS` (файловый ввод-вывод `RobotDataStore`, связь
не нужна). Остальные — `executor=None` (как сегодня, поток роутера). Причина «сейчас» — масштабирование: файловый ввод-
вывод одного робота не держит поток роутера процесса `devices`; выигрыш не измерен (в ADR так и записать).

**Видимое изменение (принято лидом 2026-10-26):** у этих 10 команд по IPC без `device_id` ответ —
`{"success": False, "error": "key_missing", "command": <имя>}` (`command_manager.py:426-434`) вместо
`{"status": "error", "message": "device_id обязателен"}`; при переполнении очереди — отказ `executor_busy`. Это единый
отказ фреймворка.

### Исполнитель процесса (SPI.d3, прототип)

`multiprocess_prototype/backend/topology/base.yaml` (процесс `devices`, :27): `executors: {device_io: {max_workers: 4,
max_pending: 64}}` — это умолчания `ExecutorSpec` (`worker_module/executor_manager.py:56-60`; `kind`, `serial` имеют
умолчания), не замер. Проверка — загрузкой `ExecutorManager.load_config` в тесте, не только чтением yaml. Запись попадает в
снимок процесса (`process_launch_config.py:178-181` убирает только пустые) → перегенерировать
`multiprocess_prototype/backend/tests/snapshots/phone_sketch.build.json`, `hikvision_letter_robot.build.json`; проверить
`hot_rebuild_framework_keys.txt`, `test_hot_rebuild_parity_acceptance.py`, `test_hot_rebuild_parity_hazards.py`.
Нет записи в конфиге → команды регистрируются без исполнителя (запасной путь хука). Отказ пишет сам
`CommandManager.register_command` — WARNING `Command '<имя>' не зарегистрирована: исполнитель 'device_io' не найден`
(`command_manager.py:263`, :308); хук повторяет регистрацию и пишет одну строку INFO — второго WARNING нет (N1 р.2).

## Правка framework (SPI.d1)

Почему нужна. `_auto_register_commands` (`multiprocess_framework/modules/process_module/plugins/base.py:1657-1676`)
зовёт `register_command(cmd_name, method)` без `executor` и `metadata`. Иного публичного пути нет: повторная регистрация
имени отклоняется диспетчером, `overwrite_command` исполнитель снимает (`command_manager.py:627-638`),
`update_command_metadata` **заменяет** словарь (`dispatch_module/strategies/exact_match.py:89`) и стирает
`metadata.executor`, а роутер передаёт `reply` только при `metadata.executor` (`router_manager.py:1359`) — команда молча
шла бы на потоке роутера (стадия 0 п.1). Обход в плагине (подмена `self.commands`, переопределение приватного метода) —
костыль, не делаем.

Что меняется (только цикл :1670-1676; `set_config` :1678-1693 и `cmd_set_config` — не трогать, C-45):
1. `ProcessModulePlugin.command_options(self, command_name: str) -> Mapping[str, Any]` — публичный хук, умолчание `{}`.
   Докстринг: Pre — имя из `self.commands`; Post — подмножество ключей `{"executor", "key_from", "targets", "metadata"}`.
2. В цикле: `options = self.command_options(cmd_name)`; ключи вне белого списка → `ctx.log_error` и регистрация без них.
   Пустые `options` → вызов `register_command(cmd_name, method)` **байт в байт как сегодня** (у всех остальных плагинов
   ничего не меняется, в том числе то, что видит `process_manager_module`).
3. Непустые `options` и `result is False` (не `not result`: `testing.py:101` возвращает `None`): если
   `get_command_info(cmd_name)` уже есть — имя занято, одна строка ERROR, повтора нет; иначе одна строка INFO `команда <имя>: исполнитель не принят — регистрация без исполнителя` (WARNING уже записал
   `register_command`, `command_manager.py:263`) и повтор с одним `metadata`. `get_command_info` — через
   `getattr(cm, "get_command_info", None)`, как `base.py:1690` (заглушки менеджера команд без метода).
4. `testing.py` (`register_command(name, handler, **kwargs)`, :101) и `plugin_test_bench.py` (`_capture_command`, :117) —
   принимать и сохранять `**kwargs` (проверить сигнатуры).
5. Тест хука в `multiprocess_framework/modules/process_module/tests/` (образец — `test_process_executors_acceptance.py`);
   строка в README `process_module`, ADR в `process_module/DECISIONS.md` (tech-writer).

Для лида → координатору (C-45): `process_manager_module` не правится; для плагинов без `command_options` поведение
регистрации не меняется. Новое: у 10 команд данных робота в `metadata` команды (`get_command_info`) появятся `executor = "device_io"`,
`key_from = "device_id"`. Дамп CAPABILITIES их не содержит: `_command_dump` (`backend_ctl/dump_capabilities.py:47-60`)
читает `name / description / tags / params_schema` (ADR-CMD-006: вывод в `introspect.capabilities` не сделан) (N7 р.2). Запасной путь меняет только то, что команда без
исполнителя остаётся в каталоге (сегодня такой команды с исполнителем нет вовсе).

## Тест настоящей цепочки (А17)

Процесс с `config["executors"] = {"device_io": {}}` (как `process_module/tests/test_process_executors_acceptance.py`) →
`DeviceHubPlugin._do_configure` + `_do_start` → запрос `robot_point_list` через путь роутера (`router_manager.py:1355-1372`,
образец — `router_module/tests/test_reply_success_honesty.py`) → `reply_to_request` вызван ровно один раз, `status == "ok"`,
обработчик исполнен на потоке исполнителя (имя потока не равно потоку роутера). `metadata` читается ПОСЛЕ `_do_start`.
