# Services/device_hub

Центральный реестр устройств и менеджер соединений.

## Назначение

Единое место владения всеми соединениями с устройствами (роботы, ПЧ, камеры,
произвольные Modbus). CRUD реестра, lifecycle (connect/disconnect), dispatch
команд через драйверы.

## Структура

```
__init__.py            — публичный API
errors.py              — иерархия ошибок
registry/
  entry.py             — DeviceEntry (dataclass, to_dict/from_dict)
  store.py             — RegistryStore (atomic YAML)
transports.py          — build_transport (tcp/rtu/bridge)
manager.py             — DeviceManager (BaseManager + ObservableMixin)
drivers/
  base.py              — BaseDeviceDriver (quality codes, stats)
  exchange_log.py      — ExchangeLog + ExchangeLogTransport (журнал обмена, T5.6)
  robot_driver.py      — RobotDriver (feeder CVT + draw)
  vfd_driver.py        — VfdDriver (poll + DRAW-gating)
  hikvision_driver.py  — HikvisionDriver (control-only)
  generic_modbus_driver.py — GenericModbusDriver (универсальный)
tests/
```

## Потокобезопасность (snapshot-API)

Реестр (`_entries`) и драйверы (`_drivers`) мутируются командным потоком и
читаются supervisor-/tick-воркерами. Читать их ИЗВНЕ менеджера — ТОЛЬКО через
публичный snapshot-API под `_registry_lock`:

| Метод | Отдаёт |
|-------|--------|
| `snapshot_registry()` | shallow-копия `list[DeviceEntry]` под локом |
| `get_driver(id)` | живой драйвер или `None` под локом |
| `connected_ids()` | id подключённых (по `is_connected`) |
| `device_count()` / `connected_count()` | счётчики под локом |

IO (connect/disconnect/tick) — ВНЕ лока (короткие критические секции).
Прямой обход приваток из плагина запрещён (гейт `test_no_private_access.py`).
Детали — ADR-DH-008.

## Журнал обмена

`drivers/exchange_log.py` (T5.6): драйвер `RobotDriverV2` пишет читаемый журнал обмена с контроллером робота —
что записал ПК, что он читал, длительность вызова, ошибка. Журнал читают человек и агент и сверяют со строками
журнала симулятора.

**Строка** — `{"seq", "t", "side", "text", "tag", "n", "ms"}`:

| поле | смысл |
|------|-------|
| `seq` | сквозной номер новой строки |
| `t` | `perf_counter` на момент записи строки (монотонен по `seq`) |
| `side` | `in` — ПК -> робот (запись), `out` — робот -> ПК (чтение), у `link` пусто |
| `text` | `W CMD_FLAG = 1` / `W* CMD_OPCODE = 16 (PTP_MOVE)` / `R TLM_PROTO_VER..+32` / `W* SC_BUF[0..29] (30 слов)` |
| `tag` | `""`, `cmd` (запись `CMD_FLAG`), `res`, `err`, `stop` (`STOP_REQ`), `hb` (`HB_PC`, `JOG_LEASE`), `link` |
| `n` | сколько подряд идущих вызовов дали ту же пару `side` + `text` (склейка) |
| `ms` | длительность последнего вызова транспорта |

Имена адресов — из карты `Services/robot_comm/core/protocol_v2.py` (`REG`, блоки — `REG_COUNT`), адрес вне карты —
`0x1234`. Значения — сырые слова десятичным числом, шкал и знаков в карте v2 нет. Чтение читает **запрос**, значения
в текст не пишутся. Исключение: чтение блока `RES` целиком даёт строку `res` с тройкой
`R RES_SEQ..+4 RES_SEQ = 5, RES_STATUS = 0, RES_ERRNO = 0 (ОК)`; она пишется только при смене тройки.

**Ручки** (на ходу, без переподключения; начальные значения — `entry.params["exchange_log"]`):

- `enabled` (по умолчанию `true`) — выключенный журнал стоит один флаг: ни часов, ни форматирования, ни счётчиков;
- `periodic` (по умолчанию `false`) — периодический трафик (`HB_PC`, `JOG_LEASE`, чтения без нового ответа `RES`)
  при `false` строк не даёт, но счётчики считаются; строки `err`, `link`, `stop`, `cmd` пишутся всегда.

**Как читать.** Операции драйвера `exchange_log_get` {since_seq?, limit?} и `exchange_log_set` {enabled?, periodic?,
clear?}; команды плагина `robot_exchange_log_get` / `robot_exchange_log_set` {device_id, ...}. Через `backend_ctl`:
`send_command("devices", "robot_exchange_log_get", {"device_id": "<id>"})`. Команды работают и при неподключённом
роботе (драйвер уже создан) — журнал нужен при сбое связи. Ответ: `status`, `enabled`, `periodic`, `lines`,
`last_seq`, `dropped`, `counters`, `log_errors`. Читатель повторяет запрос с `since_seq = last_seq` и заменяет
строку по `seq` (у последней строки мог вырасти `n`). `counters` — по операциям `read <ИМЯ>`, `write <ИМЯ>`,
`cmd <OP>`: `count`, `errors`, `ms_last`, `ms_max`, `ms_avg`.

**Файл сессии.** Своего писателя на диск нет: каждая новая строка уходит в `logger_module` одной записью
`#<seq> <side> <text>`, закрытая склейка с `n > 1` — записью `#<seq> … ×<n>`. Логгер `mpf.Services.device_hub.drivers.
exchange_log.<id>`; правило `observability.loggers` в `multiprocess_prototype/backend/config/system.yaml` направляет
его в канал `robot_exchange_file` (`logs/<процесс>/robot_exchange.log`). Файл переключается на ходу через
`backend_ctl` `logger_sink_disable` / `logger_sink_enable`.

**Чего журнал не видит и что читать осторожно.**

- `write_register(s)` и `read_holding` транспорта идут мимо журнала. Транспорт робота их сегодня не вызывает.
- Транспорт моста ПЧ — тот же обёрнутый объект (`carrier.transport`); в строке мост от робота не отличается.
  `VfdClient` читает через `RegisterMap.read` -> `read_registers` и пишет через `transaction`
  (`Services/modbus/core/register_map.py`, `Services/vfd_comm/core/client.py`): строки ПЧ в журнал попадают.
- `ms` включает ожидание `RLock` у `ModbusDevice`: это не задержка робота.
- Журнал живёт столько же, сколько драйвер; если `device_upsert` пересоздаёт драйвер, журнал сбрасывается (не проверено).
- Записи в файле от разных потоков могут идти не по порядку (логгер вызывается вне замка журнала); запись
  `#<seq> … ×<n>` может лечь раньше `#<seq>`. Сортировать по `#seq`.
- Открытая склейка (`n > 1` у последней строки) попадает в файл записью `×<n>` только когда закрыта: следующей
  строкой, `clear` или выключением; в кольце (`exchange_log_get`) она видна сразу.

## Зависимости

- `multiprocess_framework.modules.base_manager` (BaseManager + ObservableMixin)
- `Services.modbus` (RegisterTransport, ModbusDevice, protocol_file)
- `Services.robot_comm` (RobotClient, FakeRobotTransport — для RobotDriver)
- `Services.vfd_comm` (VfdClient, VfdConfig — для VfdDriver)
- `Services.hikvision_camera` (lazy import — для HikvisionDriver)

НЕ зависит от: `Plugins/*`, `multiprocess_prototype/*`.
