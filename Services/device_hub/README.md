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
spi.py                 — SPI: Protocol DeviceDriver, OpSpec/OpSource, каталоги операций (ADR-DH-012)
kinds.py               — таблица видов: фабрики драйверов менеджера и источники команд из OP_SPECS (ADR-DH-012)
transports.py          — build_transport (tcp/rtu/bridge)
manager.py             — DeviceManager (BaseManager + ObservableMixin)
drivers/
  base.py              — BaseDeviceDriver (quality codes, stats)
  exchange_log.py      — ExchangeLog + ExchangeLogTransport (журнал обмена, T5.6)
  robot_driver.py      — RobotDriver (feeder CVT + draw)
  robot_driver_v2/     — RobotDriverV2 (протокол Delta v2), пакет; раскладка — ниже
  vfd_driver.py        — VfdDriver (poll + DRAW-gating)
  hikvision_driver.py  — HikvisionDriver (control-only)
  generic_modbus_driver.py — GenericModbusDriver (универсальный)
tests/
```

## SPI драйвера и команды хаба (ADR-DH-012)

`spi.py` (только stdlib) — контракт:

- `DeviceDriver` / `StopAwareDriver` — `Protocol` (статический контракт; `isinstance` во время работы не зовётся).
  Умолчания — атрибуты класса `BaseDeviceDriver`: `OP_SPECS`, `stop_aware`, `transport`, `disconnect_pending`,
  `stop_unconfirmed(_text)`, `last_io`, методы `request_disconnect()` и `set_degraded() -> bool`. Менеджер и плагин
  читают драйвер напрямую, без `getattr`. `stop_aware = True` — драйвер получает стоп фазы 1 остановки
  (`request_stop`), поток рассылки заводится только таким.
- `OpSpec(name, description, args_schema, needs_link, executor, immediate)` — одна операция; `OpSource(prefix, kind,
  route, ops, key_from)` — набор операций одного префикса. Каталоги: `ROBOT_V2_OPS` (19), `ROBOT_V1_OPS` (27),
  `ROBOT_DATA_OPS` (10, офлайн, `executor="device_io"`), `VFD_OPS` (5). Драйвер ссылается на свой каталог
  (`OP_SPECS = ROBOT_V2_OPS`). Всего 56 команд. `command_table` строгий: одно имя из двух мест с неравными `OpSpec` или разным `kind` / `route` / `key_from`
  источника — `ValueError`.
- `kinds.py` — таблица видов, один источник: строка `DeviceKind(kind, drivers, prefix, data_ops, build)` — классы
  драйверов по протоколу записи (`"*"` — любой другой), префикс команд, операции данных вида, сборка драйвера. Из
  `DEFAULT_KINDS` выводятся фабрики по умолчанию `DeviceManager` (допустимый вид = вид с фабрикой) и источники команд
  `command_sources` / `DEFAULT_SOURCES` — из `OP_SPECS` классов драйверов, не из кортежей `spi.py`. Импорты пакета:
  `spi` <- `drivers` <- `kinds` <- `manager` / плагин.
- Команды `robot_*` / `vfd_*` ставит `install_op_commands(DeviceHubPlugin, command_sources(device_kinds))` при импорте
  модуля плагина (copy-on-write `commands`); вручную остались 11 `device_*`, 6 `hik_*` и `robot_park_all` (T5.3e.5;
  опции регистрации — ветка `command_options`, не `OpSpec`). Имена прежних 72 команд не менялись; 73-я — `robot_park`
  (T5.3e), 74-я — `robot_park_all`. Всего 74 команды: 56 из каталогов и 18 вручную.

**Новый вид устройства = класс драйвера + одна строка `DeviceKind` в `DEFAULT_KINDS` (правка хаба в одну строку
`kinds.py`):** класс с `kind`, `OP_SPECS` и методом `call`; из строки менеджер получает фабрику, плагин — команды
`<префикс>_<операция>`; `manager.py` и `plugin.py` не правятся. Вне дерева — один шаг: подкласс плагина с
`device_kinds = (*DEFAULT_KINDS, строка)`; команды новых строк ставит `DeviceHubPlugin.__init_subclass__` (родитель не
меняется; снять или изменить команду родителя нельзя — `ValueError`). Подстановка класса драйвера (тесты) — тоже
своей строкой таблицы (`dataclasses.replace(строка, drivers={..., "delta_v2": Подкласс})`); строка с классом не
драйвером или с чужим `kind` не строится (`TypeError`). `register_driver_factory(kind, factory)` — шов прямого
использования `DeviceManager` (тесты): фабрику регистрировать ДО `initialize()` (записи реестра проверяются по фабрикам
при загрузке; неизвестный вид — `ValueError`). Процесс хаба создаёт менеджер в `configure` плагина и сразу зовёт
`initialize()` — его виды только из таблицы. Класс драйвера, у которого `request_stop` и `stop_aware` не совпадают, не
определяется (`TypeError` в `BaseDeviceDriver.__init_subclass__`); `stop_aware` — только простой `bool` атрибут
класса (стоп — способность класса, не экземпляра).

**`command_options` и исполнитель `device_io`.** Хук плагина `command_options(name)` отдаёт при регистрации
`{"metadata": {"description", "args"}, "executor", "key_from"}`. Операции данных робота (`robot_point_list` и ещё 9)
идут на именованный исполнитель `device_io` процесса `devices` (`base.yaml`, `executors.device_io: {max_workers: 4,
max_pending: 64}` — умолчания `ExecutorSpec`, не замер), ключ порядка — `device_id`. Операции `immediate` в очередь
исполнителя не ставятся. Без исполнителя в процессе команда идёт запасным путём на потоке роутера (INFO в логе).

**`driver_options`.** `DeviceManager(..., driver_options={kind | (kind, protocol): {имя: значение}})` и
`set_driver_options(kind, protocol=None, **opts)` — именованные аргументы конструктора драйверов. Ключ `kind` — все
протоколы вида, ключ `(kind, protocol)` — только записи с этим протоколом, его опции перекрывают видовые. Для тестов:
`client_factory` робота v2 (класс клиента `(transport, cfg) -> RobotClientV2`) по ключу `("robot", "delta_v2")` — v1 в
том же реестре его не получает. Действует на драйверы, создаваемые ПОСЛЕ вызова; неизвестная драйверу опция —
`TypeError` его конструктора. Тестовый помощник — `ClientRecorder` в `tests/conftest.py`.

## Драйвер робота v2 — пакет

`drivers/robot_driver_v2/` (T5.3f, ADR-DH-010). Путь импорта `Services.device_hub.drivers.robot_driver_v2` прежний
(`manager.py` не менялся). Всё состояние драйвера — один `RobotState` под одним листовым замком; ввод-вывод идёт под
`_jog_tx_lock` и `_param_lock`, не под замком состояния. `RobotDriverV2` собирается в `__init__.py` из ядра
`_RobotDriverCore` и миксинов (сборка там, а не в `driver.py`: иначе fan-out `driver.py` 17 > 15 и красный
`sentrux no_god_files`).

| модуль | назначение |
|---|---|
| `__init__.py` | сборка `RobotDriverV2(StopMixin, JogMixin, ProgramMixin, JobMixin, ParamMixin, OpsMixin, _RobotDriverCore)`, `_OPS = OPS`, реэкспорт шести имён |
| `driver.py` | ядро `_RobotDriverCore`: `__init__`, подключение и отключение, тик, телеметрия, `call`, `snapshot`; `request_disconnect` (C-29: «Отключить» прерывает `connect`; плагин зовёт через `getattr` под `_workers_lock` до очереди, без ввода-вывода) и `disconnect_pending` («Отключить» нажато, `disconnect` не кончился) |
| `state.py` | `RobotState` (28 полей + 4 поля `_JogRun`, 62 перехода + `view()` под одним замком), `RobotStateView`, `JogView`, `_JogRun` |
| `stop.py` | `StopMixin`: `request_stop`, стоп процесса, защёлка, эхо стопа (ADR-DH-009) |
| `jog.py` | `JogMixin`: удержание, отпускание, поводок и стоп jog |
| `programs.py` | `ProgramMixin`: запуск программы в потоке исполнителя, возврат, смена инструмента |
| `jobs.py` | `JobMixin`: очереди заданий и возвратов, дренаж тиком |
| `park.py` | `ParkMachine`: автомат основной остановки в тике (T5.3e), единственный писатель `devices.state.<id>.park` |
| `params.py` | `ParamMixin`: синхронизация параметров, `param_set` / `param_apply`, откат значения |
| `ops.py` | `OpsMixin` и таблица `OPS` (имя операции -> функция), операции оператора и журнала обмена |
| `args.py` | проверка аргументов операций, отказы хранилища |
| `tlm.py` | разбор блока телеметрии (`_parse_tlm`) |
| `texts.py` | сроки, тексты отказов, ответы «занято», счётчик номеров потоков |

**Рисунок `draw_polyline` (T5.5).** Операция общая для v1 и v2 (один `OpSpec`). На v2 рисунок идёт программой: точки v1
`{x_mm, y_mm, pen}` -> штрихи (`programs._draw_strokes`) -> генератор `draw` -> путь `program_run`; прогресс — в
`devices.state.<id>.program`. Высоты и скорости — ключи `entry.params`, как у v1: `pen_down_mm` (по умолчанию -50),
`pen_up_mm` (-40), `lift_mm` (10), `draw_speed_pct` (30), `draw_travel_pct` (100), `draw_accel` (25000); аргумент `z`
задаёт `pen_down`, `pen_up = z + lift_mm`. Потолок `draw_max_points` (по умолчанию 5000) считает точки, не штрихи;
замер одного прогона на Mac: 5000 одиночных штрихов ≈ 0,26 с на потоке приёма. Второй рисунок во время первого —
отказ «робот занят программой» (у v1 — очередь `_draw_queue`); плагин `robot_draw` считает такой отказ в `jobs_dropped`
и рисунок не повторяет. Рисунок кончается заездом домой (паритет RETURN / TOOLCHANGE). `pen` — только int 0 или 1
(bool, float и прочее — «неверные точки рисунка»; нет ключа — перо вниз). `pen=0` начинает новый штрих; одиночная
точка `pen=0` (в том числе последняя) — штрих из одной точки. Остальные `draw_*` на v2 — «неизвестная операция»
(решение владельца О2); `robot_draw_abort` на v2 не работает — остановить рисунок можно `robot_program_abort` или
`robot_abort`. Предпросмотр плагина `robot_draw` (проходы по `_PASS_LIMIT` = 100, заезд домой между проходами)
показывает поведение v1; на v2 рисунок идёт одной программой без проходов.

**Чтение состояния в тестах.** `drv.state.view()` — замороженный `RobotStateView` (23 поля, присваивание поля даёт
`FrozenInstanceError`); состояние строят переходами `drv.state.<переход>()`. Присваивать поля состояния (бывшие приватные поля драйвера) нельзя.
Переходы `RobotState` — внутренние, не SPI хаба: код вне пакета и вне тестов их не зовёт.

**Сторож.** `tests/test_no_private_driver_state.py` (AST): тесты (все файлы двух каталогов, кроме тестов других драйверов; 40 файлов) не трогают бывшие
поля состояния и приватные атрибуты `.state` (0); прочие приватные имена драйвера и базы — литеральный белый список
`_SEAMS` (112 обращений: `_client` 37, `_param_lock` 20, `_epoch` 16, ...), снятие швов — задача SPI хаба; вне пакета нет импорта
`RobotState` / `RobotStateView` / `JogView` / `_JogRun` и вызовов переходов. Новый тест другого драйвера вносится в
`_OTHER_DRIVER_TESTS` сторожа.

## Долгая операция устройства

Операция, которая идёт дольше запроса. Пока она одна — `robot_park` (основная остановка робота v2, T5.3e, ADR-DH-013);
все роботы разом — `robot_park_all` (ниже, ADR-DH-014). Контракт `robot_park` для потребителя (GUI, `backend_ctl`):

- **Запрос.** Ответ команды — только допуск `{"status": "ok", "accepted": true, "seq": k, "timeout_s": t}` или отказ
  `{"status": "error", "message": ...}`: идёт останов или отключение, park уже идёт, синхронизация, неверные аргументы,
  устройство не подключено. `seq` растёт на каждый допущенный park; ход идёт после ответа.
- **Ход.** Шаги ведёт тик драйвера (`ParkMachine`, `drivers/robot_driver_v2/park.py`): `activity` (jog отпускается,
  программе пользователя — SOFT, текущие задание и возврат доезжают сами, новые тик не берёт) -> `idle` ->
  `home` (поза в допуске 0,5 мм / 0,5° — `already`, иначе программа `park_home` — `moved`) -> `servo` (SERVO 0). Нового
  потока и исполнителя `device_io` нет. Срок `timeout_s`: аргумент, иначе `entry.params["park_timeout_s"]`, иначе
  30 с; допустимо 1..60.
- **Итог** — `devices.state.<id>.park`: `{seq, state: parking | done | failed, step, home: moved | already | null,
  servo, dropped: {jobs, returns}, reason, elapsed_s}`; `dropped` — очереди заданий и возвратов, снятые на терминале.
  Писатель один (`ParkMachine`). Терминал (`done` / `failed`) на `seq` один и ставится сравнением по `seq`
  (`RobotState.park_end`): опоздавший шаг прежнего park ничего не пишет.
  `parking` пишется при смене шага. Публикация `merge`: дельты по листьям и в первой публикации, в порядке ключей
  хаба (`seq` первым); целиком приходит только вложенный `dropped`; ждущий не должен зависеть от порядка.
  Подписка — `devices.state.<id>.park.**`. Ждущий берёт последнее значение с `seq` из ответа и чужие `seq` отбрасывает.
- **Что переводит park в `failed`:** срок («срок вышел»); стоп оператора любого уровня (`robot_stop`, `robot_abort`);
  «Отключить» (`disconnect`); потеря связи; ход домой не вышел; `request_stop` (выключение процесса) — итог ставится
  после записи аварийного стопа. `done` не получить после начала выключения.
- **После `done`** робот остановлен: jog, программы, задания и возвраты отказывают «робот остановлен: включите
  серво», пока не пришёл `robot_servo {on: true}` (`failed` защёлку не ставит). Команды `stop`, `abort`,
  `program_abort` park не блокирует.
- **Реконнект после `done`.** Контроллер после перезапуска поднимается с серво ON; если `on_connect.servo` не `null` и
  `TLM_SERVO` не 0, драйвер при подключении сам шлёт SERVO 0 (при `servo: null` записи нет: серво остаётся ON, а защёлка
  держит только команды хаба). Защёлка «остановлен» переживает реконнект; снимает её только «серво ON».
- **Ход домой.** Исход `done` при позе вне допуска получает один тик отсрочки (TLM этого тика мог быть прочитан до
  DONE); затем `failed` «после хода робот не дома». В цикле программы дома любое исключение, кроме `RobotCommError` и
  `ValueError`, а `RobotNotConnectedError` всегда, даёт «связь с роботом потеряна» (правило `_run_next_job`, одно на
  драйвер). Ответ робота, в том числе `RobotTimeout`, даёт «ход домой не выполнен». Ошибка в коде драйвера (`RuntimeError`,
  `KeyError`) тоже даст «связь потеряна»: тип исключения виден в `.program.error` и в логе.

### Все роботы: `robot_park_all`

Команда хаба для шага `pre_stop` остановки процесса (ADR-DH-014): шлёт `robot_park` каждому подключённому роботу v2 и
ждёт итоги всех; итог каждого — в **ответе команды**, а не в сторе (шаг `pre_stop` ждёт ответ). Код:
`DeviceManager.robot_park_all` (`manager.py`), ожидание — `ParkMachine.wait_terminal` (хранит 8 последних терминалов,
итог пишется до публикации: сбой `publish` итог ждущему не отнимает), обвязка — `DeviceHubPlugin.cmd_robot_park_all`.

- **Запрос.** `robot_park_all {timeout_s?}`: число 1–32 с, умолчание 30; его же получает каждый `robot_park`. Лишние
  ключи игнорируются. Отказ всей команды (роботы не тронуты): нет исполнителя `device_io` («robot_park_all: нет
  исполнителя device_io»), хаб останавливается («идёт остановка хаба»), `timeout_s` не число, `bool` или вне диапазона
  («timeout_s: число от 1 до 32»). Порядок проверок — такой же.
- **Ответ.** `{status: ok | error, timeout_s, elapsed_s, robots: {<id>: R}}`; при `error` ещё `message`: «основная
  остановка не выполнена: <id>, <id>» (id по возрастанию). `R.result`:
  - `done` — `{seq, home: moved | already, elapsed_s}`;
  - `failed` — `{seq, step, reason}`: терминал park с `failed`;
  - `timeout` — `{seq}`: терминала нет к сроку ожидания, park робота идёт дальше по своему сроку;
  - `skipped` — `{reason}`, робот не тронут: `not_v2` (протокол не `delta_v2`), `not_connected`, `stopping` (хук
    `request_stop` пришёл до его отправки), `no_time` (срок вышел до его отправки);
  - `refused` — `{message}`: `robot_park` отказал (кроме «park уже идёт»);
  - `error` — `{message: "<Тип>: <текст>"}`: исключение вызова.

  `status` — `ok`, только если у каждого робота `done` либо `skipped` с `not_v2` / `not_connected`; роботов нет — `ok` и
  `robots: {}`. `timeout`, `stopping`, `no_time`, `failed`, `refused`, `error` дают `error`. Park, уже идущий (оператор
  нажал раньше), — присоединение: хаб ждёт его `seq`, в `R` ещё `joined: true` (только у исходов `done` и `failed`; у `timeout` и `error` признака нет); тот park живёт по своему сроку (до 60 с),
  хаб ждёт только свой, поэтому итог может быть `timeout`.
- **Сроки.** `robot_park` уходят роботам последовательно по `id`. Ответ не позже `t0 + timeout_s + 1,5 с` (запас — тик
  0,5 с) плюс остаток одной идущей отправки (по чтению кода до ~3,0 с при удержанном jog, не замер): при умолчании
  ≤ 31,5 с, при 32 с ≤ 33,5 с. Хук `request_stop` во время ожидания: ответ ≤ 1,0 с после хука (плюс остаток идущей
  отправки), неотправленные роботы — `skipped/stopping`, ожидающие — `timeout` или итог, успевший прийти; сам аварийный
  стоп роботам пишет хук (ADR-DH-014).
- **Исполнитель и цена.** `command_options` отдаёт `executor: "device_io"`, `targets: "all"` — ключ «все»: операция
  ждёт всех поданных раньше и задерживает всех поданных позже (`worker_module/keyed_executor.py`). Цена: второй
  `robot_park_all` встаёт за первым и идёт со своим `t0` (роботам уйдёт `park` ещё раз — `already`; после хука его
  отсекает «идёт остановка хаба»); 10 операций данных всех роботов (`robot_point_list` и др.) ждут до ~33,5 с — не
  дефект, плата за один вызов на выключение. Без исполнителя в процессе команда отказывает, а не встаёт на поток
  приёма.
- **Шаг `pre_stop`.** Манифест ProcessManager: `{process: "devices", command: "robot_park_all", args: {}, timeout_s:
  35}` (35 с > 31,5 с плюс остаток отправки). Шаг вписывает полоса Оператор (gui-graceful-close, задача 1.4,
  `plans/2026-10-20_gui-graceful-close/tasks/1.4.md`); на дату записи в коде PM `pre_stop` нет, манифест пуст. Ответ
  `status: "error"` — PM пишет WARNING и идёт к `process.stop`: аварийный стоп роботам запишет хук `request_stop`.

Общего механизма хаба для долгих операций нет, пока потребитель один: форма ответа и путь стора заданы `park`
(`robot_park_all` — оболочка над `robot_park`, не вторая долгая операция). Второй потребитель — повод выделить общее.

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
