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

## Программы (T3.3, `programs/program.py`)

Программа описывает смысл, не провод: точки (`Point`, мм и °, рука 0/1, СК или
база), системы координат (`FrameDef` по трём точкам — обёртка над
`geometry.Frame`), шаги `Move` (точка + вид хода `LINE`/`LINE_PASS`/`JOINT`) и
`Action` (`DO_ON`/`DO_OFF`/`DELAY_MS`/`SPEED_PCT`/`ACCEL`/`ACCUR` + параметр).
Имена видов и действий — ключи `KIND`/`ACT` из `core/protocol_v2`. Модели —
Pydantic, неизменяемые, `to_dict()`/`from_dict()`; версия формата — на `Program`.

`compile_program(program, points, frames, params) -> Scenario` — чистая функция:
записи в базе (float, без квантования ×0.1) и `step_of` — индекс шага на каждую
запись. Действие сливается в предыдущую запись без действия и не `LINE_PASS`,
иначе даёт дубль-запись `LINE` в той же точке. Проверки — через
`programs/geometry.py`; отказ — `CompileError` (`step`, `reason` — код `REASON`,
0 — ошибка уровня программы). Упаковка в регистры, `SC_CAP` и загрузка
сценария — клиент v2 (T3.1/T3.2). Решение — ADR-RC-018.

## Генераторы (T3.4, `programs/generators/`)

Генератор — чистая функция «штрихи или точки + параметры → `GeneratedProgram`».
`GeneratedProgram` — именованный кортеж `(program, points)`: в `points` все
точки, на которые ссылаются ходы программы, и только они, поэтому
`compile_program(gp.program, gp.points, frames, params)` работает без склейки
словарей. Генератор сам `compile_program` не вызывает: зону, руку и отрезки
проверяет вызывающий одной компиляцией. Ошибка аргументов — `GeneratorError`
(подкласс `ValueError`). Общие правила всех генераторов: первый ход — JOINT,
действие — только после EXACT-хода (`LINE`/`JOINT`), последний ход — не
`LINE_PASS`.

- `draw(strokes, *, frame, hand, rz, pen_down, pen_up, lift_mm=10.0,
  draw_speed_pct=30, travel_speed_pct=100, accel=None, max_pass_run=26,
  name="draw", home=None)` — штрихи XY в СК `frame`: подвод JOINT над началом,
  опускание, штрих (внутри `LINE_PASS`, конец штриха `LINE`), подъём, переезд на
  `pen_up` (пропуск, если штрих начат в конце прошлого), финальный подъём на
  `pen_up + lift_mm`. Соседние точки штриха с равными XY схлопываются.
  **Правило 26:** ряд `LINE_PASS` подряд не длиннее `max_pass_run` = `SC_CAP // 2 − 1`
  (каждая 27-я точка подряд — `LINE`), иначе `wire_v2.plan_chunks` не режет
  сценарий на куски пинг-понга. Здесь это параметр, а не импорт `SC_CAP`
  (программы не знают провода); связь держит тест автора.
- `circle_stroke(cx, cy, r, *, segments=64)`, `square_stroke(x1, y1, x2, y2)` —
  готовые замкнутые штрихи (О-4: круг на v2 — полилиния с ПК, не `MCircle`).
- `return_slot(slot, *, lift_mm=20.0, push_dx_mm=100.0, push_dy_mm=0.0,
  grip_do=1, grip_delay_ms=400, name="return_slot", approach=None, home=None)` —
  v1 RETURN: над слотом → захват (`DO_ON`, пауза) → подъём → сдвиг → отпуск
  (`DO_OFF`, пауза). Подъём и сдвиг — по осям СК слота.
- `toolchange(current, target, points, *, tools=TOOL_POINTS_V1,
  transit=TRANSIT_V1, seat_delay_ms=1000, name="toolchange", approach=None,
  home=None)` — v1 TOOLCHANGE по библиотеке обученных точек `tN_over/tN_pick/tN_exit`;
  инструмент 2 — всегда через «над 1». Нехватка точек — одна ошибка
  «обучите точки: …» со всеми недостающими именами.
- `approach` (`return_slot`, `toolchange`; ответ владельца В1): задан — первым
  ходом JOINT в `approach`, весь маршрут `LINE` (путь v1 от `GL_HOME`); `None` —
  JOINT сразу в первую точку маршрута. `home` (все три; В2): задан — последним
  ходом JOINT в `home`. `approach` и `home` не схлопываются с соседними точками.
  Паритет с v1 «RETURN и TOOLCHANGE всегда кончаются домом» — забота драйвера T5.1.

Имена точек в текстах «обучите точки: …», «конфликт имён точек: …» и «ключ
библиотеки не совпадает с именем точки: …» —
намеренное исключение из правила T3.3 «без входных значений в тексте ошибки»:
оператору нужно знать, какую точку обучить. Файл — `drawing.py`, а не
`generators/draw` из ADR-RC-011: иначе функция `draw` в `__init__` перекрыла бы
одноимённый подмодуль.

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

## Клиент v2 (`core/client_v2.py`, T3.1)

`RobotClientV2(transport, ClientV2Config, *, rng, clock, sleep)` — клиент протокола Delta v2
(`plans/robot-protocol-v2/protocol-spec.md`). Транспорт внедряется (`ModbusDevice` / `FakeRobotTransport`),
собственных потоков нет: расписание пульса и поводка держит вызывающий (драйвер). Экспорт — из
`Services.robot_comm.core`.

| метод | что делает |
|---|---|
| `probe()` | только чтения: 0x1010..0x105F, `TLM_PROTO_VER` (0 или старший байт ≠ 0x02 -> `WrongFirmware`), слоты `PMIR` сторожа и поводка |
| `cmd(op, args) -> CmdResult` | транзакция mailbox под `_mailbox_lock`; NAK -> `RobotNak(errno, reason, text, index, rvals)` |
| `wait_done(seq, *, on_poll=None)` | завершение последней команды `done_seq`; `on_poll(tlm)` после каждого чтения блока TLM; `RobotAborted` / `RobotCommandError` / `RobotTimeout("done")` |
| `poll_errors()` | асинхронные события `ERR_EVT` (`ErrorEvent`, `missed`) |
| `stop(level) -> StopResult` | `STOP_REQ = stop_seq*4 + level`, ждёт эхо; `mailbox` не берёт |
| `kick_heartbeat()` / `jog_lease()` | `HB_PC` / `JOG_LEASE` = прежнее + 1, одна запись FC6; периоды `heartbeat_period_s` / `jog_lease_period_s` |
| `sync_params(values, epoch)` | синхронизация по метке и отпечатку словаря (params.md §11.4 п.3), метка пишется последней |

Правила:

- **probe до записи.** Первый пишущий вызов (`cmd`, `stop`, `sync_params`, `kick_heartbeat`, `jog_lease`) на клиенте без
  `probe()` выполняет `probe()` сам (только чтения; единое место — `_ensure_probed`). Прошивка не v2 -> `WrongFirmware`
  без единой записи; транспорт не подключён -> `RobotNotConnectedError` (клиент при этом помечает базы устаревшими,
  и следующий вызов после переподключения проверит прошивку заново). **Исключение — `stop()` проверенного клиента:**
  он пишет всегда и `is_connected` не проверяет (`ModbusDevice` после одной случайной ошибки считает связь оборванной);
  если связи правда нет, транспорт бросит ошибку, и вызывающий узнаёт, что стоп не доставлен. Ловушка
  `RobotNotConnectedError` остаётся для непроверенного клиента и для клиента, чей последний `probe()` провалился.
- **Правило драйвера: `probe()` после каждого `transport.connect()`.** Клиент ловит переподключение двумя способами:
  любое исключение транспорта внутри клиента помечает базы устаревшими (следующий вызов сам делает `probe()`), и
  идентификатор соединения `get_status()["connected_since"]` (у `ModbusDevice` меняется при каждом `connect()`; у
  транспортов без этого ключа сравнение пустое). Счётчика соединений у `ModbusDevice` нет, поэтому тихое
  переподключение между двумя вызовами на транспорте без `connected_since` клиент не увидит — драйвер обязан звать
  `probe()` сам. `stop()` проверенного клиента пишет и на устаревших базах. `probe()` в начале сбрасывает «probed»: неудачный
  probe не оставляет клиента проверенным. **Быстрый разрыв и переподключение между двумя вызовами клиент не видит** —
  после переподключения транспорта вызывающий обязан сам вызвать `probe()` (базы пульса, стопа и событий снимаются заново).
- **Нет ответа.** После `RobotTimeout("response")` вызвать `stop()`. Следующий `cmd()` сначала досматривает ответ на
  прежний seq (не дольше `res_timeout_s`; метка «в полёте» ставится до записи CMD, поэтому и сбой транспорта на записи
  её оставляет); не дождался — `RobotTimeout("response")` без записи, потом пишет сразу. Исключение: команда `done_seq`,
  когда после её записи проходил стоп, а слот CMD ещё жив (`CMD_SEQ` в роботе — наш seq): метка остаётся, и когда робот
  наконец ответит, следующий `cmd()` повторит стоп и поднимет `RobotAborted`. Слот мёртв (`CMD_SEQ` другой — регистры
  сброшены) — метка снимается. Перед снятием метки `done_seq` после прошедшего стопа клиент один раз повторяет стоп
  (HALT, если был HALT, иначе HARD; без ожидания эха): если команда стартовала позже тайм-аута, она будет оборвана, а на простаивающем роботе стоп даст только эхо. Если поздний ответ — ACK команды
  `done_seq`, а между её записью и ответом проходил стоп, следующий `cmd()` тоже применяет О5: повторяет стоп (HALT, если
  был HALT, иначе HARD) и поднимает `RobotAborted`, не записывая свою команду. Метка команды `done_seq` снимается только
  после разбора ответа и сверки поколения стопа; при исключении (ошибка чтения RES, ошибка записи повторного стопа)
  она остаётся, и следующий `cmd()` сверит поколение заново. `probe()` метку `done_seq` не снимает (метку
  мгновенного опкода — снимает).
- **Уровень стопа не понижается до эха.** Пока более сильный стоп не подтверждён эхом, новый пишется с уровнем
  `max(запрошенный, сильнейший неподтверждённый)` (SOFT после неподтверждённого HARD уходит как HARD). Ожидающий
  получает `SUPERSEDED` только от эха новее с уровнем не ниже своего; иначе ждёт дальше или `RobotTimeout("stop_echo")`.
  После неподтверждённого HALT следующий стоп любого уровня пишется как HALT (серво OFF), пока робот не подтвердит.
  Эхо учитывается везде, где клиент и так читает `TLM_STOP_ACK` (база `cmd()`, `wait_done`, ожидание стопа); лишних
  чтений нет. Если после `RobotTimeout("stop_echo")` робот эха так и не дал, вызвать `probe()`.
- **Стоп и команда `done_seq` (О5).** Если стоп прошёл между чтением базы и ACK команды `done_seq`, клиент повторяет
  стоп (HALT, если в окне был HALT, иначе HARD) и поднимает `RobotAborted`. Мгновенные опкоды (`SERVO`, `DO_SET`,
  `PARAM_*`) возвращают свой результат.
- **Замки.** `_mailbox_lock` только в `cmd()`; `stop`, `wait_done`, `kick_heartbeat`, `jog_lease`, `poll_errors` его не
  берут. Задержка стопа ограничена одной операцией транспорта (`ModbusDevice` держит `RLock` на операцию; при обрыве —
  до `timeout_sec × (1 + retries)`).
- **Ошибки.** Тексты исключений без входных значений; значения — в полях (`errno`, `seq`, `stage`, ...).
- Конфиг: `ClientV2Config.from_dict({...})`; `res_timeout_s` и `soft_echo_timeout_s` не меньше `longest_gap_s`.

## Клиент v2: обёртки, буфер сценария и пинг-понг (`core/client_v2.py`, `core/wire_v2.py`, T3.2)

- **Обёртки опкодов.** На каждый опкод `OP` — метод клиента, аргументы в порядке `OP_SPEC`; таблица
  `RobotClientV2.WRAPPERS` («опкод -> имя метода», ключи == `set(OP)`): `ping() -> rvals`, `clear_err()`,
  `ptp_move(x, y, z, rz, kind, spd_pct)`, `home(spd_pct)`, `jog_step(dx, dy, dz, drz, spd_pct)`,
  `jog_cont(direction, speed)`, `cvt_job(ecap, pick_x, pick_y, pick_z, flags, place_x, place_y, place_z, place_rz)`
  (`ecap` u32 делится на `dw_lo`/`dw_hi`), `sc_run(count, sc_id, offset)`, `servo(on)`, `do_set(channel, on)`,
  `param_set(name, raw)`, `param_get(name) -> int` (знаковый параметр — s16), `param_apply()`. Координаты обёрток — в мм и °, кодируются шагом
  провода (×`WIRE_SCALE`, половина от нуля), не `round_step`; `kind` — имя из `KIND`, параметр — имя из `PARAM_ID`.
  Обёртки — только `cmd()`: ждать завершения — вызывающему (`wait_done(result.seq)`).
- **Кодировщик — `core/wire_v2.py`** (чистые функции): `quantize`, `encode_scenario(scenario, *, params, round_step)`
  -> по 6 слов u16 на запись (§7.1), `decode_record`, `plan_chunks`. После округления зона проверяется заново
  (`check_point` каждой записи, `check_segment` от предыдущей округлённой для не-JOINT): точка у границы может выйти
  за зону — отказ `CompileError(шаг, 4/5)` на ПК, до записи в робота.
- **Шаг округления `ClientV2Config.round_step`** (мм и °, по умолчанию 0.1 — шаг провода): кратен 0.1 и не меньше его
  (0.1, 0.2, 0.5 — да; 0.05, 0.15 — `ValueError`, через `from_dict` — «некорректные поля: round_step»). Путь
  GUI -> конфиг -> бэкенд — T5.1/T6.1.
- **`upload(records, offset)`** — слова записей в `SC_BUF` блоками FC16 по <= `WRITE_CHUNK` (30) регистров, `& 0xFFFF`;
  проверка до записи (`ValueError`). `_mailbox_lock` не берёт. Адреса и размеры — из `CONSTANTS` в момент вызова.
- **`run_chunks(scenario, *, params, on_progress=None) -> RunReport`** — сценарий кусками по половинам буфера
  (`SC_CAP // 2` = 27 записей, смещения 0, 27, 0, …; запись 54 не используется). Кодирование и нарезка — целиком до
  первой записи. Кусок k: метка стопа -> `SC_RUN` -> метка после ACK (взведена -> `stop(HARD)` и `RobotAborted`) ->
  загрузка куска k+1 в другую половину -> `wait_done`. `on_progress(done, total)` — по `TLM_SC_INDEX` (пишется только
  на EXACT-точках) и `(total, total)` в конце. `RunReport.chunks` — `(start, count, offset)`. `RunReport` не
  экспортируется из `core` — импорт из `Services.robot_comm.core.client_v2`.
- **Граница куска — только EXACT-запись** (KIND ≠ LINE_PASS). Ряд из 27 и более LINE_PASS подряд не делится на куски:
  `CompileError` до любой записи. Генераторам (T3.4): EXACT не реже чем через 26 записей.
- **Метка стопа.** Снимок поколения стопа клиента и `TLM_STOP_ACK` в начале; метка — поколение сменилось или
  `TLM_STOP_ACK` другой. **Стоп другого клиента виден только на чтениях TLM — до загрузки и после ACK SC_RUN**; внутри
  загрузки сверяется только поколение (без чтений), поэтому за чужим стопом может уйти вся загрузка k+1 — SC_RUN после
  неё не будет, кусок k оборвёт сам робот. **Стоп во время загрузки: один блок FC16 может уже быть в полёте**, дальше
  ни блока, ни SC_RUN; итог — `RobotAborted`.
- **Исключения.** `RobotAborted` и `RobotNak` на SC_RUN (команда не начата; HARD оборвал бы чужой ход при `E_BUSY`)
  — наружу без стопа. Любое другое исключение после первого SC_RUN (`RobotTimeout("response"/"done")`,
  `RobotCommandError`, ошибка транспорта, исключение `on_progress`) -> `stop(HARD)`, его ошибка — заметка к исходному,
  затем исходное наружу (`cmd()` не повторяется).
- **`RobotAborted` из `run_chunks` = робот уже остановлен.** Метка после ACK: `stop(HARD)`, затем `wait_done` этого
  SC_RUN (DONE — всё равно `RobotAborted`). О5 внутри `sc_run` (стоп повторён без ожидания эха): опрос TLM до
  `TLM_ERR_SEQ == seq` с `E_ABORTED` или простоя/ошибки, не дольше `done_timeout_s`, иначе `RobotTimeout("done")`.
  **Недоставленный стоп не прячется за `RobotAborted`:** если `stop(HARD)` после метки падает (транспорт,
  `RobotTimeout("stop_echo")`), наружу уходит эта ошибка с заметкой «кусок принят» — робот, возможно, исполняет кусок.
- **Pre: на время `run_chunks` никаких `done_seq`-`cmd()` на этом клиенте** — `wait_done` держит один слот последней
  команды. Второй `run_chunks` на том же клиенте -> `RuntimeError` (флаг `_sc_active`; замок на весь прогон не держится).
- **Пульс во время сценария — поток вызывающего** (драйвер T5.1): `run_chunks` не пульсирует, а кусок может идти
  дольше `P_WDG_TIMEOUT_MS` (3000 мс) — вызывающий зовёт `kick_heartbeat()` из своего потока с периодом
  `heartbeat_period_s`.

## Тесты

```bash
pytest Services/robot_comm        # карта/клиент/runtime — fake; e2e — TCP sim
pytest Services/robot_comm/tests/test_client_v2.py                # клиент v2: гонки, порядок, seq, О3, О5 (fake + один настоящий стек)
pytest Services/robot_comm/tests/test_client_v2_acceptance.py     # приёмка против настоящего sim v2 (TCP)
pytest Services/robot_comm/tests/test_client_v2_chunks.py         # T3.2: порядок пинг-понга, метка стопа, исключения
pytest Services/robot_comm/tests/test_client_v2_chunks_acceptance.py  # T3.2: слепая приёмка, golden tests/golden/t32_run_chunks.log
```
