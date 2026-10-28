# SPI хаба — бриф: явный контракт драйвера, `OpSpec`, команды из описаний операций (ред. 2)

Автор: manager полосы Р2 (лид inspector-bottles-00), 2026-10-26. База: `feat/robot-v2-spi` от main `9b6645546`; строки —
по базе. Ред. 2 — по стадии 0 р.1 (`tasks/SPI.stage0.md`, CHANGES REQUESTED, 19 пунктов) и решениям лида 2026-10-26
(В1–В6, `stop_aware`). Принцип владельца 2026-10-26: «Главное чтоб костылей не было, а делалось к лучшей и правильной
архитектуре, которая позволяет масштабировать и улучшать систему». Уровень **Senior+**, исполнитель `teamlead` (Opus).
Р.2 APPROVED, N1–N8 внесены (`SPI.stage0-r2.md`). Путь: слепой tester по `SPI.acceptance.md` → teamlead по подзадачам → инъекции лида → ревью → стенд.

Файлы задачи: этот бриф; `SPI.debts.md` — сверка 4 долгов и счёт хуков; `SPI.framework.md` — D7 (исполнитель,
`immediate` из кода), правка framework, тест цепочки IPC; `SPI.seams.md` — SPI.f и SPI.g; `SPI.acceptance.md` —
приёмка А1–А27 (вход tester); `SPI.injections.md` — свойства для инъекций и стенд.

## Goal

Контракт драйвера хаба — явный: `Protocol` и умолчания базы вместо `getattr` / `hasattr` (после SPI в менеджере и
плагине таких обращений к драйверу **0**), `OpSpec` — описание каждой операции. Команды `robot_*` и `vfd_*` генерируются
из описаний; **имена 72 команд не меняются** (FREEZE: GUI-каталог читает `DeviceHubPlugin.commands` с класса,
`command_catalog.py:113`; `backend_ctl`; пресентер робота). Описание и аргументы команды кладутся при регистрации.
Операции с `executor` исполняются на именованном исполнителе процесса (Task 1.9m), операции с `immediate` — никогда.
Прод-код и тесты хаба не читают `drv._client`.

## DESIGN

### D1. `Services/device_hub/spi.py` — модуль контракта (Module contract: **new-lite**)

Один файл, импорт только stdlib (его импортирует класс плагина, а класс плагина — GUI). Отступление от `module-contract`:
каталога `tests/contract/` в репозитории нет — контракт-тесты в плоском `Services/device_hub/tests/test_spi_contract.py`
(записать в докстринге модуля). Докстринг модуля: `Purpose`, `Public API`, `Stability: lite`; у `command_table`,
`install_op_commands` — `Pre:` / `Post:` / `Raises:`.

```python
@dataclass(frozen=True, slots=True)
class OpSpec:
    name: str                          # имя операции драйвера; команда = f"{prefix}_{name}"
    description: str = ""              # текст каталога; "" — описание не пишется (SPI.c1)
    args_schema: tuple[str, ...] = ()  # ключи аргументов кроме key_from; "?" в конце — необязательный; только описание
    needs_link: bool = True            # True: manager.call (отказ «не подключено»); False: driver.call без связи
    executor: str | None = None        # имя исполнителя процесса (D7, SPI.framework.md)
    immediate: bool = False            # никогда не в очередь; вместе с executor -> ValueError в __post_init__

@dataclass(frozen=True, slots=True)
class OpSource:
    prefix: str                        # "robot" | "vfd"
    kind: str                          # ожидаемый entry.kind
    route: Literal["driver", "data"]
    ops: tuple[OpSpec, ...]
    key_from: str = "device_id"

DEFAULT_SOURCES: tuple[OpSource, ...]  # robot/v2, robot/v1, robot/data, vfd
def command_table(sources: Sequence[OpSource]) -> dict[str, tuple[OpSource, OpSpec]]
```

`Protocol`-ы — статический контракт и предмет теста соответствия; во время работы `isinstance` по ним не вызывается
(ловушка Т1):

```python
class DeviceDriver(Protocol):
    kind: str; entry: Any; protocol: Any; desired_connected: bool; reconnect_exhausted: bool
    OP_SPECS: ClassVar[tuple[OpSpec, ...]]
    stop_aware: ClassVar[bool]          # драйвер получает стоп фазы 1 остановки (request_stop)
    transport: Any                       # транспорт регистров или None
    disconnect_pending: bool             # C-29
    stop_unconfirmed: bool
    stop_unconfirmed_text: str | None
    last_io: dict | None
    @property
    def is_connected(self) -> bool: ...
    @property
    def stats(self) -> dict[str, Any]: ...
    def connect(self) -> bool: ...
    def disconnect(self) -> None: ...
    def tick(self, stop_event: Any = None) -> dict | None: ...
    def call(self, op: str, args: dict) -> dict: ...
    def reset_reconnect(self) -> None: ...
    def request_disconnect(self) -> None: ...   # без ввода-вывода
    def set_degraded(self) -> bool: ...         # True — драйвер перешёл в деградацию (носитель моста отключён)

class StopAwareDriver(DeviceDriver, Protocol):
    def request_stop(self, deadline: float | None = None) -> None: ...
```

`manager.py`: `_drivers: dict[str, DeviceDriver]`; `get_driver`, `_get_driver`, `_get_connected_driver`,
`_get_or_create_driver` возвращают `DeviceDriver` (`| None`, где сегодня возможен `None`) — у `Protocol` есть потребитель.

### D2. Умолчания в `BaseDeviceDriver` (`base.py`)

**Атрибуты класса**, не `property` (подкласс вправе присваивать имя в `__init__` — ловушка Т2):
`OP_SPECS = ()`, `stop_aware = False`, `transport = None`, `disconnect_pending = False`, `stop_unconfirmed = False`,
`stop_unconfirmed_text = None`, `last_io = None`. Методы: `request_disconnect() -> None` — ничего; `set_degraded() -> bool`
— `return False` (без `disconnect()`: у зависимого на мосте транспорт общий с носителем, `transports.py:136`). `request_stop`
умолчания **не получает**: поток `stop-<id>-<k>` нужен только драйверу со стопом (`manager.py:131-148`).
Подклассы: `RobotDriverV2.stop_aware = True`, `RobotDriverV2.OP_SPECS = ROBOT_V2_OPS` (рядом с `_OPS`,
`robot_driver_v2/__init__.py:33`); `RobotDriver.OP_SPECS = ROBOT_V1_OPS`; `VfdDriver.OP_SPECS = VFD_OPS`;
`VfdDriver.set_degraded` (`vfd_driver.py:123-125`) возвращает `True`. Свойства подклассов (`driver.py:249, 305`,
`stop.py:69, 74`, `robot_driver.py:159`, `generic_modbus_driver.py:52`) перекрывают умолчания без правок.

### D3. Менеджер и плагин зовут контракт напрямую; отказ одного драйвера не роняет соседей

Все 13 строк счёта (`SPI.debts.md`) — прямые обращения:
- `manager.py:131`: цели — `drv.stop_aware` (истинность, не `is True`); отбор и вызов — внутри `try` на драйвер
  (`_stop_one` уже ловит; отбор перенести внутрь). Флаг без метода → `AttributeError` → `logger.exception`, соседи
  получают стоп.
- `manager.py:425`, `plugin.py:446`: `driver.disconnect_pending is True` (`is True` остаётся — MagicMock).
- `plugin.py:907-916`: `driver.request_disconnect()` — в `try/except Exception` внутри `_workers_lock`, исключение
  сохраняется в локальной переменной; `ctx.health.report_error(exc, context="device_hub.request_disconnect",
  device_id=…)` — после выхода из `_workers_lock` и до `put` (нет ребра `_workers_lock` → health; supervisor берёт замок
  на :434, :442 и не ждёт ввод-вывод отчёта) (N3 р.2); `self._conn_queue.put(("disconnect", dev_id))` выполняется всегда. Порядок прежний: `_workers_lock` → `desired=False` → `request_disconnect` → выход из замка → `put`.
- `plugin.py:364-375` `_report_unconfirmed_stops`: чтения `driver.stop_unconfirmed`, `driver.stop_unconfirmed_text` —
  внутри существующего `try` на драйвер (сегодня `try` начинается после чтения, :370).
- `manager.py:450-455` каскад моста: на каждого зависимого — `try/except Exception` с `logger.exception`;
  `if dep_driver is not None and dep_driver.set_degraded(): publish disconnected`. Отказ одного зависимого не лишает
  деградации остальных (N4 р.2; А20).
- `plugin.py:454-456`: `driver.reset_reconnect()`; `plugin.py:551, 553, 562`: `drv.is_connected`,
  `drv.reconnect_exhausted`, `drv.last_io` (тело тика уже в `try`, :541-571).
- `manager.py:564, 597`: помощник `DeviceManager._register_transport(driver) -> Any`: `driver.transport`, при `None` —
  `raise RegisterTransportUnavailable(dev_id)`; класс в `Services/device_hub/errors.py`
  (`RegisterTransportUnavailable(DeviceHubError)`, постоянный текст `"у устройства нет транспорта регистров"` без входных
  значений). Исключение ловит прежний `except Exception` → ответ прежней формы `{"status": "error", "message": …}`.
Замки и порядок ADR-DH-009..011 не меняются; новых окон нет.

### D4. Каталоги операций (`spi.py`)

- `ROBOT_V2_OPS` — 17 ключей `robot_driver_v2/ops.py:216-239`; `exchange_log_get/set` — `needs_link=False`.
- `ROBOT_V1_OPS` — 27 ключей `RobotDriver._OPS` (`robot_driver.py:857`): 16 «старых» и 11 `draw_*`.
- `ROBOT_DATA_OPS` — 10 офлайн-операций (`param_get_all` … `program_delete`), `needs_link=False` литералом,
  `executor="device_io"` (с SPI.d2; в c1 — `None`).
- `VFD_OPS` — 5 ключей `vfd_driver.py:245`.
- `abort`, `enqueue_job`, `get_telemetry`, `return_job` объявляются **один раз** (`_SHARED_ROBOT_OPS`) и входят в оба
  кортежа v1 и v2 одним объектом.
- `immediate` — по таблице `SPI.framework.md` (из кода, с file:line).
`command_table`: одно имя команды из двух источников → `ValueError`, если `OpSpec` не равны по всем полям (`description`,
`args_schema`, `needs_link`, `executor`, `immediate`); при равенстве — одна строка. Сторож в `test_spi_contract.py`: для
каждого драйвера `{s.name for s in cls.OP_SPECS} == set(cls._OPS)`, литерал исключений пуст (на базе 27/27, 17/17, 5/5).

### D5. Генерация команд плагина

`install_op_commands(cls, sources)` (функция `Plugins/hub/device_hub/plugin.py`, зовётся сразу после класса;
`register_plugin` не копирует `commands`, `registry.py:294-327`):
- copy-on-write: `if "commands" not in cls.__dict__: cls.commands = dict(cls.commands)` — родитель не мутирует;
- для каждой строки `command_table(sources)` ставит метод `cmd_<имя>` (фабрика замыкания над `(source, spec)`;
  `__name__ = "cmd_<имя>"`, `__doc__ = spec.description or f"{source.prefix}: {spec.name}"` — N6 р.2; каталог не меняется:
  туда пишутся только непустые описания), `cls.commands[<имя>] = "cmd_<имя>"`, и запоминает
  `cls._op_commands[<имя>] = (source, spec)` (свой словарь класса, copy-on-write так же);
- имя уже в `cls.commands` или атрибут `cmd_<имя>` уже есть → `ValueError`.
Тело — `_op_command(self, data, source, spec)`: `route == "data"` → `_robot_data`; `needs_link is False` → `_driver_call`;
иначе `_kind_call` (тела и тексты отказов прежние). 55 однострочников `cmd_robot_*` / `cmd_vfd_*` (`plugin.py:938-1168`) и
их строки в литерале `commands` удаляются. Ручными остаются 11 `device_*` (жизненный цикл; `device_disconnect` — точка
линеаризации C-29, ей нельзя в очередь) и 6 `hik_*` (префикс ≠ виду `hikvision`; `hik_enum` без устройства).

Описание и аргументы в каталоге:
- **c1** (строгий перенос): `_apply_robot_v2_descriptions` → `_apply_op_descriptions`: в `start()` пишет
  `{"description": spec.description}` только для `OpSpec` с непустым описанием (это те же 21, без списка имён).
- **d2** (после хука фреймворка): `DeviceHubPlugin.command_options(name)` → для имён из `_op_commands`
  `{"metadata": {"description": …, "args": [...]}}` (пустые ключи не кладутся) плюс `executor` / `key_from` при
  `spec.executor`; `_apply_op_descriptions` и запись в `start()` удаляются (замена словаря стёрла бы `executor`,
  стадия 0 п.1).
- **c2** (видимое): описания 34 старых команд (литералы в `SPI.acceptance.md`, А3) и `args_schema` всех 55;
  регенерация `docs/contracts/CAPABILITIES.yaml` / `.md` (`python -m backend_ctl.dump_capabilities`, headless-бэкенд —
  окно `heavy`); гейт `backend_ctl/tests/test_capabilities.py:186-203` (`test_dump_matches_committed`).

### D6. Потоки исполнителя и учёт команд (d2)

`_safe_call` (`plugin.py:657-674`) правит `self._reg.commands_ok/commands_err/last_error` — с исполнителем это несколько
потоков. Счётчики — под замком плагина `_counters_lock`. Проверка детерминированная (N5 р.2): регистр-заглушка, чей сеттер
`commands_ok` уступает поток (`time.sleep(0)` / событие) между чтением и записью, либо проверка удержания замка в момент
записи (`_counters_lock.locked()` в сеттере заглушки). «Листовой» не проверен: если `__setattr__` регистра
(`DeviceHubRegisters`) уведомляет подписчиков, это вызов внутри замка — исполнитель проверяет и сообщает лиду. `RobotDataStore` —
замки по ключам (`store.py:202`); операции данных разных роботов параллельны, одного — по одной (ключ `device_id`).

### D8. Оракул защёлки (долг 1, SPI.a)

Строка `_LATCH_ROWS` — `(row_id, transition, setup, action, resets)`: `transition` — имя публичного метода `RobotState`
(`take_job` → `take_next_action`), `setup(st)` выполняется ДО `_dirty_latch` (так `connect_begin_shutdown` получает
выключение через `request_stop_begin`, не сбрасывая «грязную» защёлку после). Новые строки: `connect_begin_go` (сброс),
`connect_begin_shutdown` (setup `request_stop_begin`), `connect_begin_cancelled` (setup `disconnect_request`),
`connect_begin_busy` (setup — задание взято), `connect_link_up`, `connect_restore`, `connect_finish`, `connect_end`,
`set_ready`, `connect_check`, `is_shutdown` (без сброса). Литерал `_RESET_TRANSITIONS = {"admit_launch", "connect_begin",
"connect_reset", "disconnect_begin", "jog_started", "request_stop_begin", "take_next_action"}`. Тесты: (1) AST `state.py` —
публичные методы, достигающие `_latch_reset_locked` через приватные помощники, == литерал; (2) `transition` строк с
`resets=True` == литерал; (3) каждый публичный метод `RobotState` (AST) — либо `transition` строки, либо в литерале
`_LATCH_EXEMPT`; `_LATCH_EXEMPT ∩ _RESET_TRANSITIONS = ∅`. Исполнитель выписывает `_LATCH_EXEMPT` из `state.py` базы.

## Ответ на стадию 0 (р.1)

| п. | что сделано |
|---|---|
| 1 | Описание и `args` — при регистрации через `command_options` (D5 d2); запись в `start()` удалена; А17 — через `_do_start` и путь роутера (`SPI.framework.md`); свойство 20 |
| 2 | c1 строгий перенос / c2 описания 34 + `args` + CAPABILITIES; гейт и оба файла — в FILES c2 |
| 3 | `test_robot_v2_commands.py` — в FILES c1 и d2; ожидания литералом (21 при c1; при d2 тест отказа каталога переписывается на отказ регистрации) |
| 4 | copy-on-write `commands` и `_op_commands`; А9 проверяет родителя; свойство 19 |
| 5 | Отбор стопа и чтения `stop_unconfirmed*` — внутри `try` на драйвер; `request_disconnect` в `try`, `put` всегда (D3); А24, А25 |
| 6 | `executor` + `immediate` + `ValueError`; список `immediate` из кода с file:line (`SPI.framework.md`): `clear_queue` (v1) входит; `do_set`, `toolchange` — нет, по коду (А12); `key_missing` записан видимым изменением; цепочка IPC; FILES d3 со снимками |
| 7 | `set_degraded() -> bool`, публикация при `True`, умолчание без `disconnect()`; А20 |
| 8 | `RegisterTransportUnavailable(DeviceHubError)` + `_register_transport`, форма ответа прежняя; А13 |
| 9 | SPI.f, но шов — `client_factory`, не `client=` (несогласие ниже) |
| 10 | SPI.g — только затвор, последней |
| 11 | D8: setup-элемент, поле `transition`, литерал 7 сбросов, AST-проверка |
| 12 | А19 (55 имён → операция), А21 (присваивание умолчаний в подклассе), тест соответствия 5 фабрик, равенство `OP_SPECS == _OPS`; типизация `get_driver`. D6 ред. 1 (`store_refusal`) вычеркнут — вне целей (п.14) |
| 13 | Пути импорта литералом; tester знает про сторож приватных имён; 34 литерала описаний (c2); А8 запрещает и присваивания, и ключи `robot_*`/`vfd_*` в литерале `commands` |
| 14 | D6 ред. 1 вычеркнут → Out of scope |
| 15 | Общие операции объявлены один раз; одно имя из двух источников при неравных `OpSpec` → `ValueError` по всем полям; `needs_link=False` у данных литералом |
| 16 | REDS переписаны: новая часть (в) сторожа — новый тест; счёт строк → AST-проверка по получателю; названы затронутые гейты |
| 17 | Файлы ≤ 32 КБ: долги, D7/framework, SPI.f/g вынесены |
| 18 | Коммиты: a / b1 / b2 / c1 / d1 / d2 / c2 / d3 / f / g |
| 19 | Отступление `tests/contract/` записано; `Stability: lite`, `Pre/Post` названы (D1) |

Несогласие (п.9, принято в р.2 с уточнением довода): шов `RobotDriverV2(…, client=None)` хуже фабрики. Драйвер
создаёт клиент один раз в `connect` (`driver.py:338-339`), а `cfg` строит в конструкторе из `entry.params` по закрытому
списку `_CLIENT_KEYS` (`driver.py:150-153`): с `client=` тест дублировал бы это отображение или брал умолчания и
расходился с боевой сборкой. Шов — класс (фабрика), а не экземпляр: сборка остаётся в драйвере, подмена — у теста
(`client_factory(transport, cfg)`, `SPI.seams.md`). Обёртка журналом (:335-337) в тестовом пути не ставится
(транспорт внедрён) — к доводу не относится. Прочие пункты приняты без возражений.

## FILES (по коммитам; файл вне списка — стоп, вопрос лиду; на запуск ≤ 6 — лид делит)

```
a : Services/device_hub/tests/test_robot_v2_state_acceptance.py
b1: Services/device_hub/spi.py (новый); drivers/base.py; drivers/robot_driver.py, drivers/vfd_driver.py,
    drivers/robot_driver_v2/__init__.py (строки OP_SPECS / stop_aware); Services/device_hub/tests/test_spi_contract.py
b2: Services/device_hub/manager.py; Services/device_hub/errors.py; drivers/vfd_driver.py (set_degraded -> True);
    Plugins/hub/device_hub/plugin.py (D3); Services/device_hub/tests/test_no_private_driver_state.py (часть (в),
    _SCANNED_FILES); drivers/robot_driver_v2/driver.py (докстринг :290-301)
c1: Plugins/hub/device_hub/plugin.py (D5); Plugins/hub/device_hub/tests/test_robot_v2_commands.py
d1: multiprocess_framework/modules/process_module/plugins/{base.py, testing.py, plugin_test_bench.py};
    тест хука в process_module/tests; README + DECISIONS process_module
d2: Plugins/hub/device_hub/plugin.py (command_options, D6); Services/device_hub/spi.py (executor у данных);
    Plugins/hub/device_hub/tests/test_robot_v2_commands.py
c2: Services/device_hub/spi.py (34 описания, args_schema); docs/contracts/CAPABILITIES.yaml, CAPABILITIES.md
d3: multiprocess_prototype/backend/topology/base.yaml; multiprocess_prototype/backend/tests/snapshots/
    {phone_sketch.build.json, hikvision_letter_robot.build.json, hot_rebuild_framework_keys.txt}
f, g: SPI.seams.md
docs: Services/device_hub/{README.md, STATUS.md}; ADR-DH-012 — черновик tasks/SPI.adr-draft.md до слияния параллельной
    правки Services/device_hub/DECISIONS.md (пишет tech-writer)
```

## Шаги (коммит на подзадачу; перенос без смены поведения — отдельно от видимого)

1. **SPI.a** — оракул защёлки (D8), только тест.
2. **SPI.b1** — поведение 0: `spi.py`, умолчания базы, `OP_SPECS` / `stop_aware`, `test_spi_contract.py`.
3. **SPI.b2** — видимое (в теме коммита): D3; изменения — текст отказа регистров у ПЧ (`RegisterTransportUnavailable`),
   каскад моста по `set_degraded() -> bool`, изоляция отказа фейк-драйвера в остановке и «Отключить».
4. **SPI.c1** — строгий перенос: генерация, удаление 55 однострочников, описания — те же 21.
5. **SPI.d1** — хук framework (после согласования лида с координатором). **SPI.d2** — `command_options`, исполнитель у 10
   команд данных, D6. **SPI.c2** — описания 34 + `args` + CAPABILITIES. **SPI.d3** — прототип и снимки.
6. **SPI.f**, **SPI.g** — отдельные запуски (`SPI.seams.md`). **SPI.docs** — README/STATUS, черновик ADR.

## REDS (прогноз; факт — проба лида до запуска исполнителя)

```
T = Services/device_hub/tests, P = Plugins/hub/device_hub/tests
a : T/test_robot_v2_state_acceptance.py::test_latch_reset_transitions_ast (connect_begin нет в строках)
    ::test_latch_rows_cover_public_methods. Строки connect_* сами ЗЕЛЁНЫЕ (оракул к готовому коду).
b1: T/test_spi_contract.py::* — ImportError Services.device_hub.spi
b2: T/test_no_private_driver_state.py::<новый тест части (в)> — manager.py:564, :597
    T/test_spi_contract.py::test_no_duck_typing_on_drivers — 13 узлов. Получатель определяется ПОТОКОМ ДАННЫХ, не
    списком имён: имена, связанные с вызовом get_driver / _get_driver / _get_connected_driver / _get_or_create_driver,
    переменные цикла по _drivers / его снимку, параметры с аннотацией DeviceDriver (и замыкания, куда они переданы,
    как make_tick_fn(did, drv)); переименование переменной сторож не обходит (N4 р.2)
    tester: А11, А13, А20, А21, А24, А25
c1: tester: А8 (55 def), А9, А19 (нет install_op_commands)
d1/d2: tester: А17, А18 (нет хука / executor в metadata)
c2: tester: А3 (34 описания пусты); backend_ctl/tests/test_capabilities.py::test_dump_matches_committed — красный до
    регенерации файлов (ожидаемо, регенерация в том же коммите)
d3: снимки build.json — красные до перегенерации (в том же коммите)
Стражи, зелёные до и после: P/test_robot_v2_commands_acceptance.py (72 имени, :418-420), test_c29_*.py,
  test_robot_v2_t53g_*.py, test_robot_v2_t53h_*.py, P/test_t53r2_stop_hazards.py, P/test_t53r2_stop_acceptance.py,
  P/test_no_private_access.py, P/test_reply_envelope_acceptance.py, А1.
Ломаются и правятся в своём коммите: P/test_robot_v2_commands.py:23, 246-250 (c1, d2).
```

## Out of scope

- T5.3e / C-33, C-38, C-39; перенос среды робота в `Services/robot_comm` (вариант B) — после SPI, с `sentrux check .`.
- Один путь `store_refusal` (D6 ред. 1): вне целей SPI, поведенческого красного нет (стадия 0 п.12, п.14).
- Проверка аргументов по `args_schema` на границе (тексты отказов операций — контракт).
- `getattr(carrier, "mode" / "busy")` в `vfd_driver.py:332, 334` и `transports.py:125, 133` — вне менеджера и плагина.
- Исполнитель для `toolchange` v1 и прочих длинных операций драйверов (сейчас `executor=None`).

## Требует слова владельца

- Видимые изменения (лид принял, владельцу показаны): `key_missing` / `executor_busy` у 10 команд данных; описания 34
  команд в CAPABILITIES (`args` — в metadata); текст отказа регистров у ПЧ; каскад моста по `set_degraded() -> bool`.
- SPI.f меняет слепые приёмочные тесты стопа (только способ получить клиент; критерий — пустой AST-дифф `assert`).
- `set_servo` v1 — `immediate`: решение лида по коду (`robot_driver.py:629-632`, серво без проверки занятости);
  `servo` v2 — не `immediate` (`ops.py:118-120`). Пометка для владельца.

## Ловушки исполнителя

- Т1. Python 3.12: `isinstance` по `runtime_checkable`-протоколу идёт через `inspect.getattr_static` — `MagicMock()` без
  `spec` его не проходит. Во время работы — умолчания базы и флаг `stop_aware`, не `isinstance`.
- Т2. Умолчания базы — атрибуты класса (А21 краснеет на `@property` без сеттера).
- Т3. `disconnect_pending is True` — оставить; `stop_aware` — истинность (MagicMock как сегодня).
- Т4. Замыкание генерации — фабрикой, не переменной цикла.
- Т5. Новые тестовые файлы входят в сторож приватных имён (`_SCANNED_FILES`); приватные имена драйвера в них —
  красный сторож.
- Т6. Worktree: главный `.venv` + `PYTHONPATH=<worktree>`; не `uv sync`; тесты — `scripts/machine_gate.sh`, сессия
  `inspector-bottles-00`; регенерация CAPABILITIES и стенд — окно `heavy`/stand; `ruff check -q` на каждый `.py`.

## Что осталось открытым

1. REDS — прогноз чтения; проба не гонялась, тестов я не запускал. Строки — по `9b6645546`.
2. Что `register_plugin` не копирует `commands` — проверено чтением `registry.py:294-327`, не прогоном каталога GUI.
3. Влияние ключа `args` на дамп CAPABILITIES (`dump_capabilities.py:47-60` читает `name/description/tags/params_schema`;
   карточку строит `builtin_commands.py:873`) — выяснится регенерацией в c2.
4. `immediate` защищает от очереди исполнителя, но не от потока роутера: длинная синхронная операция (`toolchange` v1,
   `stop` v2 ждёт эхо до 0,8 с, `ops.py:97`) по-прежнему задерживает следующие команды процесса. Вне SPI.
5. Тело `client_factory` не примерено к каждому из 43 мест (часть тестов, возможно, создаёт драйвер через менеджер —
   там фабрику не передать без шва фабрики хаба); объём SPI.f — оценка.
6. Значения `max_workers: 4, max_pending: 64` — умолчания `ExecutorSpec`, не замер.
7. `_LATCH_EXEMPT` (56 имён) здесь не выписан — исполнитель показывает его лиду до коммита SPI.a.
8. (р.2, откр. 2) Строки D8 `connect_begin_cancelled` и `connect_begin_busy`: сочетание `setup` + `_dirty_latch` не
   проверено — после `disconnect_request` или взятого задания `_dirty_latch` может не дать «грязной» защёлки (его
   `assert before != _CLEAN_LATCH`). Прецедент — только `request_stop_begin`. Выяснит исполнитель SPI.a; не выходит —
   стоп и вопрос лиду.
9. (р.2, откр. 5) `set_servo` v1 — `immediate` по решению лида по коду: `robot_driver.py:629-632` пишет серво без
   проверки занятости. Код подтверждает только отсутствие проверок, не необходимость обхода очереди — пометка для
   владельца.
10. (р.2, откр. 4) Из 25 вызовов `get_driver(` в тестах не посчитано, сколько ведут к `drv._client`; правило SPI.f —
   в `SPI.seams.md`.
