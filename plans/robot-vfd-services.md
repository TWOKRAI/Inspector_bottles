# План: универсальный Services/modbus + сервисы устройств Робот и ПЧ (CVT + рисование)

## Статус выполнения (2026-06-11)

- [x] **Фаза 0** — универсализация Services/modbus: transaction (abort-семантика),
  RegisterTransport, RegisterMap, TCP_NODELAY; 106 тестов — `92bec98c`
- [x] **Фаза 1** — Services/robot_comm: карта u3, RobotClient, sim_core +
  FakeRobotTransport + TCP sim_robot, runtime (владелец), CLI (вкл. `cal`);
  40 тестов, ADR-RC-001..005 — `85c5186c`
- [x] **Фаза 2** — Services/vfd_comm: VfdClient поверх RegisterTransport,
  poll()-пульс + ensure_alive, BRIDGE_MAP + закладка DIRECT_MAP; 15 тестов,
  ADR-VC-001..003 — `669abbf5`
- [x] **Фаза 3** — плагины robot_io (владелец + feeder + manual_mode) /
  vfd_control (poll-worker + bridge_alive) / robot_draw (async worker);
  31 тест — `345b42bd`
- [x] **Фаза 4** — GUI-секция «Робот Delta» (widget/presenter/controller/section,
  UX-gating CVT-DRAW/VFD); 16 тестов + qt-probe smoke — `d04ac614`
- [x] **Фаза 5** — рецепт robot_demo.yaml (co-location ноды робота), ADR-MB-001/002,
  синхронизация plans/robot-calibration.md — (этот коммит)
- [ ] **Железо** — `python -m Services.robot_comm pos` → X,Y,Z; тест-job; ПЧ Run/Stop
- [ ] **Lua-улучшения** (по приоритету ревью): idle-публикация зеркала ПЧ →
  VFD_FLAG в DRAW → PROTO_VERSION → ack/seq → регистр ручного режима

## Context

В `robot/universal3/` лежат отлаженные на железе программы: `pc_full.py` (ПК-клиент, Modbus
TCP master) + `cvt_universal_full.lua` (скрипт робота). Режимы: **CVT pick-place** и
**рисование** (полилинии/круги), плюс управление **ПЧ INVT GD20** через мост: ПК ↔ робот по
Modbus TCP, робот ↔ ПЧ по RS-485 (Lua ретранслирует mailbox-регистры).

Цель — превратить это в сервисы прототипа по схеме (решение владельца 2026-06-11):

> **`Services/modbus` = универсальный транспортный модуль** (pymodbus, TCP и RS485,
> атомарные транзакции, декларативные карты регистров). **Сервисы устройств** (`robot_comm`,
> `vfd_comm`, будущие) — тонкие надстройки: выбирают тип соединения и задают карту регистров
> своего устройства. Новые сервисы устройств добавляются по этому образцу из одного модуля.

Плюс **плагины** для pipeline (CVT, рисование, ПЧ) и **GUI-вкладка** ручного управления.
Фокус первого захода — **CVT** (тонкий срез на тестовых координатах). Калибровка
(pixel→robot) — отдельный план `plans/robot-calibration.md`, подключается upstream позже.

## Решения владельца (2026-06-11)

- **Универсальный `Services/modbus`:** один транспортный модуль для всех устройств; сервис
  устройства выбирает тип соединения (TCP/RTU/мост) и даёт карту регистров. НЕ делать вторую
  pymodbus-обёртку в robot_comm.
- **Мост ПЧ↔робот — Protocol-транспорт:** `vfd_comm` не импортирует `robot_comm`; зависит от
  абстракции `RegisterTransport`. Реализуют её и `ModbusDevice` (прямое соединение), и
  `RobotClient` (мост через робота). Сменить транспорт = одна строка.
- **Совместимость с Lua:** стартуем 1:1 с рабочим universal3 (функции похожи — удобно
  тестировать против отлаженного робота), но **Lua правится, если это даёт улучшение** —
  рабочий код тестовый, не догма. Каждое улучшение протокола — парная правка
  `cvt_universal_full.lua` + `registers.py`, отдельным коммитом, тест на sim_robot → железо.
- **Объём:** сервисы + плагины **+ GUI-вкладка ручного управления** (MVP как `services/hikvision/`).
- **Симулятор:** `sim_robot` (фейк Modbus-slave с картой робота + зеркало ПЧ) — разработка/CI
  без железа.
- **Вход CVT в срезе:** тестовые/ручные координаты. Калибровка позже.

## Опорные факты (из разведки кода)

- **`Services/modbus/` уже production** (82 теста): `sdk/client.py` (pymodbus 3.x, TCP+RTU),
  `sdk/datatypes.py` (encode/decode int16/int32/float32 c word_order — ровно то, что нужно
  DW-энкодеру робота), `core/device.py` (`ModbusDevice`: state machine, RLock, callbacks),
  `core/config.py` (`ModbusConfig`: transport tcp|rtu, host/port, serial/baudrate/parity,
  unit_id, word_order), `core/poller.py` (`RegisterBlock`/`ModbusPoller`), `server/sim_server.py`
  (фейк-slave), `plugin/`, `service.py`.
- **Чего НЕ хватает в `Services/modbus`** (и что блокировало переиспользование):
  `ModbusDevice` даёт пооперационный Lock, а CVT требует **серию записей под одним Lock**
  (данные+маркер атомарно). Плюс нет `RegisterTransport`-Protocol, декларативной карты
  регистров устройства, TCP_NODELAY и реконнекта.
- **Слои:** `framework → Services → Plugins → prototype`. Плагин может прямо импортировать
  `Services.*` (как `Plugins/sinks/modbus_sink/`). Сервисы устройств зависят от
  `Services.modbus` (внутри слоя Services это допустимо — как `sql` ← другие), но робот↔ПЧ
  развязаны через Protocol.
- **Сервис** = `@register_service` + `IService` (name/start/stop/get_status); реестр хранит
  классы, lifecycle ведёт application-слой. **Плагин** = `ProcessModulePlugin`
  (configure/start/process/shutdown, `register_class`, `commands`). Соединение живёт в
  процессе-воркере; плагины делят клиент через process-local `runtime.py` (модель владельца).
- **pymodbus** — optional-dep `[modbus]`; всё импортируется без него (`MODBUS_AVAILABLE`).

## Карта регистров робота (universal3 — единственный источник истины)

Из `robot/universal3/pc_full.py` (пара к `cvt_universal_full.lua`); уходит в
`Services/robot_comm/core/registers.py`:

| Блок | Адреса | Назначение |
|------|--------|-----------|
| `REG_MODE` | 0x1109 | 0=CVT, 1=DRAW (переключать только когда свободен) |
| CVT job | 0x1100 FLAG, 0x1101 X, 0x1102 Y, 0x1104 ECAP(DW), 0x1106 STOP, 0x1108 SERVO | задание pick-place |
| CVT статус | 0x1110 FREE, 0x1112 ENC(DW), 0x1120..0x1124 ECHO(5) | свободен/энкодер/эхо |
| Телеметрия | 0x1130, 11 слов (X,Y,Z,RZ,MOVING,SPD,CVSPEED,HAND,HB,SERVO,MISS) | поза/состояние |
| **ПЧ команда** | 0x1200 RUN, 0x1201 DIR, 0x1202 FREQ(×100), 0x1203 RESET, 0x1204 FLAG | mailbox → робот → RS-485 |
| **ПЧ статус** | 0x1210, 8 слов (RUN, OUT_FREQ×100, CURRENT×10, DCBUS×10, FAULT, STATUSW, HB, COMM_ERR) | зеркало ПЧ |
| Конфиг | 0x1300 FLAG, 0x1301 +11 (speed, home_xyz, pick_z, place_xyz, grip_ms, zone_max/min) | параметры робота |
| Рисование | 0x1400 FLAG/TYPE/COUNT/BUSY/PROG/ABORT; 0x1406 CX/CY/R; 0x1410 PEN_DOWN/UP/DRAW_SPD/OVERLAP; 0x1420 буфер 100 точек | полилинии/круги |

Константы: `XY_SCALE=10`, `FREQ_SCALE=100`, `CURRENT_SCALE=10`, `DCBUS_SCALE=10`,
`WORD_ORDER="little"`, `WRITE_CHUNK=30` (робот не тянет большие блоки), `unit_id=2`.
**Внимание:** universal3 ≠ universal2 (CFG=11, TLM=11, DCBUS_SCALE=10, REG_MODE, drawing-блок).
Брать только u3; существующий `robot-calibration.md` ссылается на u2 — при слиянии сверить.

## Эталоны

| Что | Путь |
|-----|------|
| Рабочий `Robot`, регистры, `_atomic`, drawing | `robot/universal3/pc_full.py` |
| Структура сервиса + `@register_service` | `Services/modbus/` |
| Плагин с внешним соединением | `Plugins/sinks/modbus_sink/plugin.py` |
| MVP-вкладка + round-trip команды | `multiprocess_prototype/frontend/widgets/tabs/services/hikvision/` |
| Фейк Modbus-slave | `Services/modbus/server/sim_server.py` |

---

## Фаза 0 — Универсализация `Services/modbus` (фундамент для всех устройств)

**Цель:** один модуль покрывает потребности любого устройства: TCP и RS485, атомарные
транзакции, декларативная карта регистров, переносимость транспорта.

**0.1 `ModbusDevice.transaction(ops)` — атомарная серия записей.**
```python
def transaction(self, ops: list[tuple]) -> bool:
    """Серия записей под ОДНИМ Lock: данные → маркер последним.
    ops: ("w", addr, value) | ("wm", addr, [values])"""
    with self._lock:               # RLock уже есть
        for kind, addr, val in ops:
            ...self._client.write_register(s)...
    # телеметрия writes_ok/err, callbacks — как у _write
```
Это снимает главный блокер CVT (координаты+маркер не должны разрываться чужой записью).

**Семантика ошибок (ревью п.3, осознанное отличие от pc_full):** abort на **первой** ошибке —
оставшиеся операции (включая маркер) НЕ пишутся, transaction → False/исключение. У оригинала
латентный баг (`ok = (not rr.isError()) and ok`, pc_full.py:145 — серия продолжается после
ошибки, FLAG может лечь поверх мусора). Инвариант «маркер последним» работает только с
abort-семантикой; частичный mailbox без FLAG=1 инертен. Задокументировать в docstring.

**Конкурентность — подтверждено ревью:** RLock device общий для read/write/transaction;
поллер ходит через те же методы → гонок нет, только ожидание замка. Но transaction держит
Lock на время сетевого I/O — при обрыве это `timeout_sec × retries × len(ops)` блокировки
feeder/телеметрии/GUI. Для робота в `RobotConfig`: `timeout_sec≈0.5–1`, `retries=1`.

**0.2 `RegisterTransport` Protocol → `Services/modbus/interfaces.py`.**
```python
@runtime_checkable
class RegisterTransport(Protocol):
    def read_registers(self, address: int, count: int = 1) -> list[int]: ...
    def transaction(self, ops: list[tuple]) -> bool: ...
    @property
    def is_connected(self) -> bool: ...
```
`ModbusDevice` реализует структурно (добавить alias `read_registers = read_holding`).
Любой сервис устройства зависит только от этого Protocol → транспорт взаимозаменяем
(прямой TCP, прямой RS485, мост через другое устройство).

**0.3 Декларативная карта регистров — `core/register_map.py`.**
Мини-DSL, чтобы сервис устройства описывал карту данными, а не методами с магией:
```python
@dataclass(frozen=True)
class Reg:           # одиночный регистр
    address: int; scale: float = 1; signed: bool = False
@dataclass(frozen=True)
class RegDW:         # 32-бит (2 регистра, word_order)
    address: int; signed: bool = True
@dataclass(frozen=True)
class RegBlock:      # блок слов (телеметрия/статус)
    address: int; count: int; fields: tuple[str, ...] = ()  # имя поля на слово

class RegisterMap:   # device-карта: чтение/запись по именам через RegisterTransport
    def read(self, transport, name) -> int | float | dict: ...
    def write_ops(self, pairs: dict[str, float]) -> list[tuple]:  # → ops для transaction
```
Encode/decode — поверх существующего `sdk/datatypes.py` (ничего не дублируем). `RegBlock`
совместим с `RegisterBlock` поллера. **Масштабирование:** новый регистр устройства = одна
строка в карте.

**0.4 Транспортные мелочи из боевого кода:** TCP_NODELAY (`_enable_nodelay` — снимает ~40 мс
лагов) — опция `ModbusConfig` в `sdk/client.py`. **Reconnect — НЕ в sdk** (ревью п.3): тихий
reconnect+retry посреди серии ломает атомарность. sdk только детектит обрыв
(`ConnectionException` → `ModbusConnectionError`), реконнект — на уровне владельца-плагина
по образцу `Plugins/sinks/modbus_sink/plugin.py:136-146` (`_ensure_connected`, throttled).
Транзакция при обрыве — fail-fast целиком.

**0.5 Документация паттерна** «как добавить сервис нового устройства» в
`Services/modbus/README.md` (шаблон: config → карта → клиент → service.py → sim → тесты).

**Acceptance:** существующие 82 теста зелёные; новые тесты `transaction` (фейк-клиент:
порядок записей, один lock), `register_map` (encode/decode, scale, DW little/big);
`ModbusDevice` проходит `isinstance(..., RegisterTransport)`.

---

## Фаза 1 — `Services/robot_comm` (сервис устройства «робот Delta»)

**Цель:** живой `RobotClient` поверх универсального modbus, API 1:1 с рабочим `Robot`.

```
Services/robot_comm/
  __init__.py            # RobotClient, RobotConfig, Telemetry, VFDStatus, RobotPosition, ROBOT_AVAILABLE
  __main__.py            # CLI-smoke: python -m Services.robot_comm --host 192.168.1.7 pos|cal|job x y
  interfaces.py          # RobotClientProtocol
  README.md  STATUS.md  DECISIONS.md
  core/
    config.py            # RobotConfig: ModbusConfig(transport=tcp, unit_id=2, word_order=little) + лимиты
    registers.py         # КАРТА регистров u3 через RegisterMap (см. таблицу выше)
    client.py            # RobotClient(device: ModbusDevice) — портированный Robot
    datatypes.py         # Telemetry, VFDStatus, RobotPosition, DrawPoint (dataclass)
  service.py             # @register_service("robot_comm") — БЕЗ собственного соединения!
  runtime.py             # process-local holder: set_client/get_client/clear (модель владельца)
  testing/
    fake_transport.py    # FakeRegisterTransport — in-process эмулятор mailbox-семантики
                         # (FLAG-цикл, echo, FREE, heartbeat). Закрывает ~90% тестов без TCP
  server/
    sim_robot.py         # TCP фейк-slave (для E2E и ручной разработки GUI)
    __main__.py          # python -m Services.robot_comm.server
  tests/
    test_registers.py    # карта/кодеки без сети
    test_client.py       # против FakeRegisterTransport (pos/encoder/send_job/draw/config)
    test_sim_e2e.py      # smoke против TCP sim_robot
```

**`service.py` — каталожная карточка, НЕ соединение (ревью п.6).** Эталонный
`ModbusService.start()` создаёт собственный device и коннектится — для робота так НЕЛЬЗЯ:
получится второй TCP-master к одному mailbox (гонка по проводу, Lock каждого клиента
локален). `RobotCommService` — только метаданные/статус для каталога сервисов; владелец
соединения — исключительно плагин `robot_io`, все GUI-операции — round-trip командами к нему.
Зафиксировать в README.

**sim_robot — двухуровневый (ревью п.4).** `Services/modbus/server/sim_server.py` — пассивное
хранилище: в pymodbus 3.13 datastore переписан, хук «override setValues» сервером не
вызывается, а sim_robot нужна реактивная логика (FLAG=1→обработать→FLAG=0, echo,
heartbeat++, зеркало ПЧ). Поэтому:
1. **`FakeRegisterTransport`** (чистый Python, реализует Protocol 0.2) — основной тестовый
   стенд, конечный автомат mailbox без сети;
2. **TCP `sim_robot`** — для E2E/GUI; **spike в начале фазы**: можно ли мутировать datastore
   pymodbus-3.13 из фонового потока; при провале — фоллбэк на классический
   `ModbusServerContext`. Объём — полноценный конечный автомат, не «50-100 строк».

**Порт из `pc_full.py` — транспорт заменяется, семантика остаётся:**
- `_atomic([...])` → `device.transaction([...])`; `_read` → `device.read_registers`;
  кодеки → `sdk/datatypes` + `RegisterMap`. На проводе — те же байты, Lua не трогаем.
- **Берём:** `read_encoder/is_free/job_accepted/read_echo/abort/send_job`, `read_telemetry`,
  `read_position`, `set_mode`, `get_config/set_config` (+ обёртки set_home/set_place/...),
  drawing (`set_pen/set_draw_speed/set_overlap/draw_circle/draw`), `set_servo`.
- **Нюансы порта (ревью п.9):** в `draw()` ДВА уровня чанкования — `WRITE_CHUNK=30` регистров
  на запись (10 точек) И `PTS_MAX=100` точек на проход с `_wait_done` между пачками;
  валидация `XY_LIMIT_MM=3276.7` в `send_job` сохраняется (предел s16×10, границы — в
  RegisterMap); `REG_ECAP` — DW по чётному адресу (assert в `RegDW`); TLM-heartbeat пишется
  Lua только в idle CVT-ветке — во время job/draw телеметрия стоит, индикатор «связь жива»
  на вкладке не должен трактовать это как обрыв.
- **`RobotClient` реализует `RegisterTransport`** (read_registers/transaction делегируют в
  device под его Lock) — это мост для ПЧ.
- **Выбрасываем:** `Console`/REPL/`print`. **`feeder` НЕ выбрасываем** — его логика (очередь
  job + поллинг `is_free`) переезжает в worker плагина `robot_io` (Фаза 3).
- `cal` (подбор word order по живому энкодеру) — остаётся CLI-командой `__main__.py`.

**Модель владельца:** клиент НЕ singleton. Владелец (плагин `robot_io`) создаёт/коннектит/
публикует в `runtime`, закрывает в `shutdown` (+graceful-disconnect сокета). Потребители —
`runtime.get_client()`, бросает `RobotNotConnectedError`.

**Acceptance:** импорт без pymodbus; тесты против sim_robot зелёные;
`python -m Services.robot_comm pos` на железе возвращает X,Y,Z.

---

## Фаза 2 — `Services/vfd_comm` (сервис устройства «ПЧ GD20», транспорт-агностик)

**Цель:** управление ПЧ поверх `RegisterTransport` — сегодня мост через робота, завтра
(если появится прямой RS485 к ПЧ) — `ModbusDevice(transport=rtu)` без правки клиента.

```
Services/vfd_comm/
  __init__.py  interfaces.py  README.md  STATUS.md  DECISIONS.md
  core/
    config.py            # VfdConfig: freq_min/max, scale-константы (БЕЗ host/port — транспорт внешний)
    registers.py         # карта mailbox (0x1200 cmd, 0x1210 status×8) через RegisterMap
                         # + закладка: карта ПРЯМЫХ регистров GD20 (0x2000/0x2001/0x2100/0x3000)
                         #   для будущего прямого RTU-подключения (из мануала goodrive20)
    client.py            # VfdClient(transport: RegisterTransport, config)
    datatypes.py         # VFDStatus
  service.py             # @register_service("vfd_comm")
  tests/test_client.py   # против фейк-RegisterTransport + против sim_robot-зеркала
```

**`VfdClient`:** `run(freq_hz, reverse)` / `set_freq` / `stop` / `reset_fault` — атомарные
`transport.transaction([...])` (freq → dir → run → FLAG последним); `read_status()` →
`transport.read_registers(0x1210, 8)` → `VFDStatus`.

**КРИТИЧНО (ревью п.1, блокер):** в текущем Lua зеркало ПЧ (0x1210+, включая heartbeat)
обновляется **только при обработке команды** (`vfd_poll_publish` зовётся из `handle_vfd`,
а тот — только при `VFD_FLAG=1`). «Периодический read_status» без команд читает замороженный
снимок; heartbeat не растёт даже при живом мосте. Решение:
- `VfdClient.poll()` — пульс `VFD_FLAG=1` без смены команды как poll-триггер (безопасно:
  Lua кэширует `last_cmd`/`last_freq` — лишних записей на RS-485 не будет, только чтение
  статуса ПЧ и публикация зеркала);
- параллельно — Lua-улучшение №1 (см. список кандидатов): публикация статуса ПЧ в idle-цикле.

**`VFDStatus` параметризуется картой (ревью п.10):** при будущем прямом RTU меняется не
только транспорт — карта другая (0x2000/0x2100/0x3000 вместо mailbox) и полей heartbeat/
comm_err нет (они существуют только в мосте) → опциональные поля + `read_status(map)`.

**Подключение через робота (в плагине):** `VfdClient(transport=runtime.get_client())`.
Робот сам ретранслирует на RS-485 и зеркалит статус — со стороны ПК это просто регистры.

**Масштабирование:** новые регистры ПЧ → строки в `registers.py` (+ ретрансляция в Lua, если
через мост). Новые устройства (ещё ПЧ, сканер, датчик) — копия этого паттерна.

**Acceptance:** `VfdClient` против фейк-транспорта пишет корректную серию (маркер последним);
`read_status` парсит зеркало; на железе run/stop крутит ленту.

---

## Фаза 3 — Pipeline-плагины

Все — `ProcessModulePlugin`, `register_class`+`registers.py` (SchemaBase+FieldMeta),
`commands` для GUI round-trip. Эталон — `Plugins/sinks/modbus_sink/plugin.py`.

**ТОПОЛОГИЧЕСКОЕ ТРЕБОВАНИЕ (ревью п.5):** `robot_io`, `robot_draw`, `vfd_control` обязаны
жить в **одном `process_name`** рецепта (список `plugins:` одного узла) — `runtime.py`
process-local, в соседних процессах `get_client()` пуст. Зафиксировать: один процесс-нода
«robot» с тремя плагинами; `RobotNotConnectedError` с сообщением, объясняющим co-location;
мульти-процессный шаринг (робот-нода через IPC/RouterManager) — наследуемый долг из
`robot-calibration.md` (Фаза 4+ того плана).

**`Plugins/io/robot_io/` — владелец соединения + исполнитель CVT.**
- `start()`: `RobotClient(...)`, `connect()`, `runtime.set_client()`; worker «feeder»
  (очередь job + поллинг `is_free` — портированная логика из `Console.feeder`).
  `shutdown()`: disconnect + `runtime.clear()`.
- `process(item)`: CVT-срез — координаты из item/команды/registers (тестовые), `send_job`.
  Каждые N кадров `read_telemetry()` → `ctx.state_proxy.merge("robot/telemetry", {...})`.
- `commands`: `send_test_job{x,y}`, `abort`, `set_mode`, `set_config{...}`, `set_servo`,
  `get_telemetry`, `read_echo`.
- Долг (P2.5): флаг «ручной режим» приостанавливает автo-`send_job` (на ПК-стороне).

**`Plugins/control/robot_draw/` — рисование** (потребитель: `runtime.get_client()`).
- Вход `item["points"]=[{x,y,pen}]` или команда. `commands`: `draw_points`,
  `draw_circle{cx,cy,r}`, `draw_square{x1,y1,x2,y2,z}`, `set_pen{down,up}`,
  `set_draw_speed`, `set_overlap`, `abort_draw`, `get_draw_progress`.
- **Асинхронно (ревью п.7):** `draw()`/`draw_circle()` блокируют до 120 с (`_wait_done`) —
  исполнять в фоновом worker плагина; команда `draw_*` возвращается сразу, состояние
  `drawing/progress/done/failed` — через `state_proxy`.

**`Plugins/control/vfd_control/` — ПЧ** (потребитель: `VfdClient(transport=runtime.get_client())`).
- `commands`: `vfd_run{freq,reverse}`, `vfd_set_freq{hz}`, `vfd_stop`, `vfd_reset_fault`;
  периодический poll через `VfdClient.poll()` (пульс VFD_FLAG — см. Фазу 2) →
  `ctx.state_proxy.merge("vfd/status", {...})`.
- **Ограничение текущего Lua (ревью п.2, безопасность):** команды ПЧ обслуживаются только
  в CVT-ветке между заданиями — в DRAW-режиме и во время job «Stop ПЧ» НЕ сработает.
  До Lua-фикса GUI обязан дизейблить/помечать VFD-кнопки в DRAW-режиме.

**Acceptance:** рецепт `источник → robot_io` шлёт тестовый job на sim_robot (виден в echo);
`vfd_control.vfd_run` меняет зеркало; `robot_draw` заливает буфер точек чанками.

---

## Соответствие REPL-команд `universal3` → плагины/вкладка (тест-команды сохраняются 1:1)

| REPL (pc_full.py) | Куда | Команда/элемент |
|---|---|---|
| `mode cvt\|draw` | robot_io | `set_mode` + переключатель на вкладке |
| `pos`, `enc`, `state/st`, `params` | телеметрия | `state_proxy "robot/telemetry"` → панель |
| `<x> <y>` (job) | robot_io | `send_test_job{x,y}` + поля X/Y |
| `last` | robot_io | `read_echo` |
| `cal` | CLI | `python -m Services.robot_comm cal` |
| `stop/halt/estop` | robot_io | `abort` + кнопки |
| `spd/home/place/zpick/zone/grip` | robot_io | `set_config{...}` |
| `servo on\|off` | robot_io | `set_servo` |
| `r/rev [Гц]`, `f <Гц>`, `s`, `reset`, `mon`, `vfd` | vfd_control | `vfd_run/vfd_set_freq/vfd_stop/vfd_reset_fault/read_status` |
| `square`, `circle`, `file <csv>` | robot_draw | `draw_square/draw_circle/draw_points` |
| `pen`, `dspd`, `overlap`, `dstop`, `prog` | robot_draw | `set_pen/set_draw_speed/set_overlap/abort_draw/get_draw_progress` |

**Улучшения протокола (правки Lua разрешены — рабочий код тестовый).** Порядок: сначала
порт 1:1 (проверка «ничего не сломали» против отлаженного робота), затем улучшения парными
коммитами Lua+`registers.py`, каждый с тестом на sim_robot → железо. Кандидаты —
приоритет уточнён по ревью:

1. **Публикация статуса ПЧ в idle-цикле Motion** (ревью п.1) — снимает заморозку зеркала
   0x1210+ и делает heartbeat настоящим индикатором живости моста. До фикса ПК
   компенсирует пульсом `VFD_FLAG` (`VfdClient.poll()`).
2. **Обслуживание `REG_VFD_FLAG` в DRAW-ветке и во время job** (ревью п.2, безопасность) —
   чтобы «Stop ПЧ» работал всегда, а не только в idle CVT.
3. **`PROTO_VERSION`-регистр** (ревью п.11в — страховка всех остальных правок, дешевле
   ack/seq): ПК сверяет при connect, ловит «залит старый Lua» сразу, а не мусором в данных.
4. **ack/seq для команд ПЧ** — подтверждаемый `vfd_run` вместо fire-and-forget.
5. **Регистр «ручной режим»** (для P2.5 «вкладка/калибровка vs авто-send_job») — защита на
   роботе, не зависит от дисциплины ПК-стороны.
6. **Расширение конфиг-блока / новые регистры ПЧ** — по мере надобности (у GD20 в мануале
   много регистров — добавлять ретрансляцию в Lua точечно).

---

## Фаза 4 — GUI-вкладка ручного управления (MVP)

По эталону `services/hikvision/` (presenter/section/widget/controller, round-trip через
`CommandSender.request_command` + `RequestRunner.submit`). Регистрация в `services/tab.py`.
```
multiprocess_prototype/frontend/widgets/tabs/services/robot/
  presenter.py  section.py  widget.py  controller.py
  tests/test_robot_presenter.py   # view как Protocol/мок, без Qt
```
**Виджет:** статус соединения + телеметрия (X,Y,Z,RZ,FREE,энкодер, servo);
**Робот:** X/Y + «Послать тест-job», стопы, CVT/DRAW, конфиг (spd/home/place/zone/grip);
**Рисование:** круг/квадрат/CSV, pen/dspd/overlap, прогресс, dstop;
**ПЧ:** частота + Run/Reverse/Stop/Reset + статус (out_freq, current, dcbus, fault, heartbeat).

**UX-ограничения от протокола (ревью п.2, п.11):**
- переключатель CVT/DRAW дизейблится при `FREE=0` (Lua применяет режим раз за итерацию
  Motion, при занятом роботе переключение «зависнет»);
- VFD-кнопки дизейблятся/помечаются в DRAW-режиме (Lua не обслуживает VFD_FLAG в DRAW) —
  до Lua-улучшения №2;
- `comm_errors` показывать как динамику (рост за период), не только абсолют — RS-485 к GD20
  медленный, абсолютное число само по себе не информативно;
- индикатор «связь с роботом» — по успешности Modbus-чтений, НЕ по TLM-heartbeat (он стоит
  во время job/draw — это норма, не обрыв).

**Acceptance:** «тест-job» доходит до sim_robot и виден в echo/телеметрии; Run ПЧ меняет
статус; обязательный `qt_snapshot` после правки GUI (memory: qt-mcp smoke).

---

## Фаза 5 — Интеграция + полировка

- Рецепт-пример (`multiprocess_prototype/recipes/`): **один процесс-нода «robot» с тремя
  плагинами в `plugins:`** (`robot_io` + `robot_draw` + `vfd_control` — co-location, ревью
  п.5) + источник `webcam` отдельным узлом. Сервисы в каталоге; вкладка в навигации.
- DECISIONS.md: ADR «универсальный modbus + сервисы устройств» (transaction, RegisterTransport,
  RegisterMap, паттерн нового устройства).
- Возможный рефактор `ModbusPlugin`/`modbus_sink` на `RegisterMap` (не блокирует).
- Улучшения протокола Lua по списку кандидатов (см. приоритеты выше: idle-публикация статуса
  ПЧ → VFD_FLAG в DRAW → PROTO_VERSION → ack/seq → ручной режим) — парные коммиты,
  обновлять `robot/universal3/cvt_universal_full.lua` и копию, заливаемую на робота.
- **Синхронизировать `plans/robot-calibration.md`** (ревью п.12), чтобы планы не противоречили:
  1. Фаза 0 там: убрать «собственный pymodbus-клиент НЕ поверх ModbusDevice» и долг P1.1 —
     транспорт сразу `Services/modbus` + `transaction` (долг закрыт до возникновения);
     убрать `sdk/transport.py`/`sdk/codec.py` из структуры (кодеки = `modbus.sdk.datatypes`
     + `RegisterMap`).
  2. Источник порта: `universal2/pc_robot.py` → `universal3/pc_full.py`; сверить карту
     (CFG=11, TLM=11, DCBUS_SCALE=10, REG_MODE, drawing-блок).
  3. Убрать `vfd_*` из `RobotClientProtocol` — они в `Services/vfd_comm.VfdClient`;
     P2.2 «отдельный план vfd-control.md» → ссылка на этот план.
  4. Фаза 4 калибровки: `robot_io` уже создан здесь — переформулировать как расширение
     (reject → `image_to_robot` → `send_job`), не создание.
  5. sim_robot Фазы 0 там → ссылка на Фазу 1 этого плана (двухуровневый, не «50-100 строк»).
  6. P2.5 «калибровка активна» → связать с Lua-кандидатом «регистр ручного режима».

---

## Советы

1. **`WORD_ORDER="little"`** для DW (энкодер/ECAP) — поле конфига, не хардкод; CLI `cal`
   оставить (первое, что проверяют при «мусорном» энкодере).
2. **Маркер — последним** в каждой `transaction` (инвариант, задокументировать в client.py).
3. **`unit_id=2`** робот; slave id ПЧ (1) — забота Lua, в vfd_comm его нет (SRP моста).
4. **Только universal3** как источник карты (u2 отличается: CFG/TLM/scale/drawing).
5. **sim_robot обязан зеркалить ПЧ** (эхо 0x1200+ → 0x1210+ с heartbeat++), иначе vfd-цепочка
   не тестируется без железа.
6. **Чанки по 30 регистров** при заливке точек рисования — робот не тянет большие блоки.
7. **Мануалы** (`knowledge/raw/books/goodrive20-*`, `delta-ia-robot-*`) — пригодятся в Фазе 2
   для закладки карты прямых регистров GD20 и при расширении регистров; для среза достаточно
   карты из рабочего кода.
8. **Что сломается первым на железе (прогноз ревью):** (а) замороженное зеркало ПЧ без
   команд — закрыто `VfdClient.poll()`; (б) «Stop ПЧ» в DRAW — закрыто дизейблом кнопок;
   (в) рассинхрон Lua↔Python после первой парной правки — закрыто `PROTO_VERSION`;
   (г) медленный RS-485 к GD20 (RX_TRIES=8) — следить за динамикой `comm_errors`.

## Верификация (E2E)

1. **Без железа:** `python -c "import Services.modbus, Services.robot_comm, Services.vfd_comm"`;
   `pytest Services/modbus` (82 старых + новые transaction/register_map);
   `python -m Services.robot_comm.server` + `pytest Services/robot_comm Services/vfd_comm`;
   `pytest Plugins/io/robot_io Plugins/control/vfd_control Plugins/control/robot_draw`.
2. **С железом (срез):** `/run-proto` → вкладка «Робот» → тест-job (рука едет) → DRAW →
   тест-круг → ПЧ Run 50 Гц (лента крутится) → Stop.
3. **Smoke Qt:** `qt_snapshot` после правки вкладки.
4. Из корня: `python scripts/validate.py` + `python scripts/run_framework_tests.py`.

## Конвенции коммитов

Новая ветка `feat/robot-vfd-services`. Conventional Commits + `Why:`/`Layer:` (Фаза 0-2 →
`services`, Фаза 3 → `plugins`, Фаза 4 → `prototype`). `Refs: plans/robot-vfd-services.md`.
Dual-save: копия плана в `plans/robot-vfd-services.md`.
