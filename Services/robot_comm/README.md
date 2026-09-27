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

## Окно-вид симулятора v2 (`gui/sim_view.py` + `gui/z_view.py`, T2.V/T2.W)

**Это ОТЛАДОЧНЫЙ вид** (решение владельца, 2026-09-27), не продуктовый GUI —
продуктовые виджеты робота строятся в Ф6 на GUI-конструкторе
(`plans/robot-protocol-v2/tasks-2.md` T6.x), и на тот момент этот модуль
заменяется виджетами конструктора, а не расширяется.

Три независимых read-only виджета, каждый со своим `QTimer` перерисовки —
останавливается в `closeEvent` (закрытие окна) И в `hideEvent`/`showEvent`
(скрытие/повторный показ; ревью T2.W, F4): Qt доставляет `closeEvent` только
окну верхнего уровня, а не виджетам, встроенным в него `build_window()`'ом —
без пары `hideEvent`/`showEvent` каждый виджет продолжал бы тикать после
`window.close()` (переиспользование вида в T2.3 `--view` завязано на оба
события, не только на `closeEvent`):

- `SimView` (`gui/sim_view.py`) — вид сверху над `RobotSimCoreV2`: зона, цепи
  звеньев модели, шлейф TCP, статус, **стрелка направления инструмента**
  (T2.W) — отрезок от TCP по углу `TLM_RZ` (цвет `#ffb86c`), рисуется всегда,
  даже когда модель не строит цепь (`joints() is None`) — RZ ось позы
  протокола, от модели не зависит. Единственный из трёх, кто читает зону и
  суставы через `core._workspace()`/`core.joints()` (T2.V, вне зоны T2.W).
- `ZScale` (`gui/z_view.py`, T2.W) — вертикальная шкала `TLM_Z`: границы
  рабочей зоны (`P_WS_Z_MIN`/`P_WS_Z_MAX`), отметки pick/place/home
  (`P_PICK_Z`/`P_PLACE_Z`/`P_HOME_Z`) и текущий Z — **читает ТОЛЬКО регистры**
  (телеметрия `TLM_Z` + зеркало параметров `PMIR`, ревью T2.W F5 — ни
  `core._workspace()`, ни `core._values` не трогает), перечитывается на
  каждый `refresh()` (параметры меняются в рантайме через `PARAM_SET`).
  Развёртка шкалы — по домену, пересчитанному на каждый `refresh()` как
  `min`/`max` над границами зоны, текущим Z и всеми тремя отметками (F1): Z
  или отметка вне зоны, либо инвертированная зона (`z_min > z_max`), получают
  свою отдельную строку вместо слияния с границей.
- `TimeTape` (`gui/z_view.py`, T2.W) — лента Z(t)/RZ(t) за последнее окно
  времени (по умолчанию 10 с), часы — параметр `clock` (зритель, не ядро —
  вид должен работать поверх настоящего робота, где времени ядра нет).
  **Читает ТОЛЬКО регистры** — телеметрия `TLM_Z`/`TLM_RZ` + зеркало `PMIR`
  для `P_WS_Z_MIN`/`P_WS_Z_MAX`/`P_WS_RZ_MIN`/`P_WS_RZ_MAX` (F5); та же
  домен-по-кадру логика (F1), что и у `ZScale`, отдельно для Z и для RZ.

`DemoDriver` — единственный писатель мимо окна (тот же mailbox-паттерн, что
и в тестах). Запуск:

```bash
python -m Services.robot_comm.gui.sim_view    # обычный запуск с окном
```

Клик по виду — `DemoDriver.goto(x, y)`; кнопки «Домой»/«Серво»/«Стоп».
Заглушка (не путать с настоящей геометрией): длины звеньев SCARA в
`kinematics.py` (`l1`/`l2`) — с шильдика робота, ещё не подставлены.

Смоук без дисплея (`--quit-after` закрывает окно само через N секунд —
`QTimer.singleShot` -> `app.quit()`, живой человек не нужен):

```bash
QT_QPA_PLATFORM=offscreen python -m Services.robot_comm.gui.sim_view --quit-after 2
```

## Тесты

```bash
pytest Services/robot_comm        # 40: карта/клиент/runtime — fake; e2e — TCP sim
```
