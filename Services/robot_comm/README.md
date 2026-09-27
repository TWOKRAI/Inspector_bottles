# robot_comm — сервис робота Delta (CVT pick-place + рисование)

Тонкий сервис устройства поверх универсального [`Services/modbus`](../modbus/README.md):
карта регистров + доменные методы. Порт отлаженного на железе
`robot/universal3/pc_full.py` — семантика и байты на проводе 1:1 со скриптом
робота `cvt_universal_full.lua`.

## Топология

```
ПК (RobotClient, Modbus-TCP master)
 │  TCP :502, unit_id=2
 ▼
Робот Delta (cvt_universal_full.lua, Modbus server)
 │  RS-485 (Modbus RTU) — мост в Lua
 ▼
ПЧ INVT GD20 (управляется через Services/vfd_comm поверх этого клиента)
```

`RobotClient` сам реализует `RegisterTransport` — для `vfd_comm` он просто
«пространство регистров» (mailbox ПЧ 0x1200/0x1210 на роботе).

## Быстрый старт

```python
from Services.robot_comm import RobotClient, RobotConfig

bot = RobotClient(RobotConfig(host="192.168.1.7"))
bot.connect()
print(bot.read_position())          # RobotPosition(x_mm=..., y_mm=..., z_mm=..., rz_deg=...)
bot.send_job(150.5, -200.3, bot.read_encoder())   # CVT-задание (атомарно, маркер последним)
bot.set_mode("draw")
bot.draw_circle(10, 20, 5)          # родной MCircle
bot.disconnect()
```

## CLI-smoke (без GUI)

```bash
python -m Services.robot_comm pos                    # позиция (192.168.1.7:502)
python -m Services.robot_comm cal                    # подбор word order энкодера
python -m Services.robot_comm job 150.5 -200.3       # тест-задание
python -m Services.robot_comm --host 127.0.0.1 --port 5021 state   # против sim
```

## Симулятор (разработка/CI без железа)

Два уровня:

1. **`FakeRobotTransport`** (`testing/`) — in-process, без сети и pymodbus.
   Каждое чтение тикает «Motion-цикл» фейк-робота → детерминированные тесты.
2. **TCP `sim_robot`** (`server/`) — настоящий Modbus-slave для E2E и GUI:

```bash
python -m Services.robot_comm.server        # 127.0.0.1:5021, unit 2
```

Оба уровня — одно ядро `RobotSimCore` (семантика mailbox: job accept/free,
echo, энкодер, зеркало ПЧ с heartbeat, draw busy/prog).

## Модель владельца соединения

Один TCP-master на устройство. Владелец — **процесс `devices`** (always-on,
`DeviceHubPlugin` → `RobotDriver`): создаёт `RobotClient`, коннектит,
выполняет команды по IPC из GUI и плагинов. Старый `runtime.py`
(process-local holder, co-location) удалён — соединение полностью в `devices`.

`service.py` — только карточка каталога, соединение НЕ открывает.

## Протокол (карта universal3)

Один источник истины — [`core/registers.py`](core/registers.py). Ключевые
инварианты (подробно — [DECISIONS.md](DECISIONS.md)):

- **маркер-флаг последним** в каждой транзакции; abort на первой ошибке;
- **word_order='little'** для DW (энкодер, E_capture) — поле конфига, подбор
  командой `cal`;
- рисование: чанки **30 регистров** на запись, **100 точек** на проход;
- телеметрия/heartbeat пишутся Lua только в idle — «связь жива» определяется
  по успешности чтений, не по heartbeat;
- зеркало ПЧ обновляется **только по команде** (пульс VFD_FLAG) — см. vfd_comm.

Любая правка протокола = парная правка `cvt_universal_full.lua` + `registers.py`
одним коммитом, с тестом на sim.

## Модель робота (`kinematics.py`, T2.K)

Кинематика (FK/IK/цепочка звеньев) — за интерфейсом `RobotModel`, не жёстко
зашита в симулятор/окно-вида. Сегодня одна реализация — `ScaraModel`
(закрытая формула, звенья `l1`/`l2`). Смена типа робота — `make_model({"type": ..., ...})`
или передача готовой модели в `RobotSimCoreV2(model=...)`; `programs/geometry.py`
(единственная правда о рабочей зоне) не меняется. Шов уже, чем «весь ядро
не меняется» (ревью T2.K, находка 6): набор параметров зоны (`P_WS_*`,
кольцо/сектор SCARA) и правило `R_HAND` — часть прошивки Delta v2, а не
модели, и для другого типа робота переезжают вместе с протоколом.

## Окно-вид симулятора v2 (`gui/sim_view.py`, T2.V)

Read-only вид сверху над `RobotSimCoreV2` (зона, цепи звеньев модели, шлейф
TCP, статус) + `DemoDriver` — единственный писатель мимо окна (тот же
mailbox-паттерн, что и в тестах). Запуск:

```bash
QT_QPA_PLATFORM=offscreen python -m Services.robot_comm.gui.sim_view   # offscreen — для CI/смоук без дисплея
python -m Services.robot_comm.gui.sim_view                              # обычный запуск с окном
```

Клик по виду — `DemoDriver.goto(x, y)`; кнопки «Домой»/«Серво»/«Стоп».
Заглушка (не путать с настоящей геометрией): длины звеньев SCARA в
`kinematics.py` (`l1`/`l2`) — с шильдика робота, ещё не подставлены.

## Тесты

```bash
pytest Services/robot_comm        # 40: карта/клиент/runtime — fake; e2e — TCP sim
```
