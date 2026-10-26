# ADR-DH-012 — полный текст

> Вынесено из [DECISIONS.md](../../DECISIONS.md) по образцу ADR-DH-009..011: в `DECISIONS.md` остались заголовок, статус, суть и ссылка.

## ADR-DH-012: Явный SPI драйвера и команды хаба из описаний операций

**Дата:** 2026-10-26
**Статус:** accepted (SPI хаба, подзадачи a–g; решения лида inspector-bottles-00 и владельца 2026-10-26)
**Контекст задачи:** `plans/robot-protocol-v2/tasks/SPI.md` (бриф, ред. 2), `SPI.seams.md`, `SPI.deviations.md`; ADR-DH-009..011 не меняются.

### Контекст

После T5.3f (ADR-DH-010) менеджер и плагин хаба читали драйвер через `getattr` / `hasattr` (13 строк счёта в
`SPI.debts.md`): контракт драйвера нигде не был записан. 72 команды плагина (`robot_*`, `vfd_*`, `device_*`, `hik_*`)
были 55+17 ручных однострочников; описание команды получали только 21 из них, у остальных каталог GUI и
`docs/contracts/CAPABILITIES.yaml` описания не имели. Тесты хаба для подмены клиента робота писали приватный
`drv._client` (43 места). Затвор переподключения жил в трёх копиях.

### Решение

1. **Контракт драйвера — `Services/device_hub/spi.py`** (только stdlib): `DeviceDriver` и `StopAwareDriver` (`Protocol`,
   статический контракт; `isinstance` во время работы не вызывается). Умолчания — атрибуты класса `BaseDeviceDriver`
   (`OP_SPECS`, `stop_aware`, `transport`, `disconnect_pending`, `stop_unconfirmed(_text)`, `last_io`) и методы
   `request_disconnect()` / `set_degraded() -> bool`. Менеджер и плагин зовут контракт напрямую; отказ одного драйвера
   не роняет соседей (`try` на драйвер в рассылке стопа, каскаде моста, отчёте о неподтверждённом стопе).
2. **`OpSpec`** описывает операцию (`name`, `description`, `args_schema`, `needs_link`, `executor`, `immediate`;
   `executor` и `immediate` вместе — `ValueError`). Каталоги: `ROBOT_V2_OPS` (17), `ROBOT_V1_OPS` (27),
   `ROBOT_DATA_OPS` (10 офлайн-операций, `executor="device_io"`), `VFD_OPS` (5); общие операции v1 и v2 (`abort`,
   `enqueue_job`, `get_telemetry`, `return_job`) — один объект. Итого 55 команд, описание и `args_schema` у каждой.
3. **Команды хаба генерируются из каталогов:** `install_op_commands(cls, sources)` ставит 55 методов `cmd_robot_*` /
   `cmd_vfd_*` (copy-on-write `commands`), вручную остались 11 `device_*` и 6 `hik_*`. Имена 72 команд не менялись
   (FREEZE: GUI-каталог читает `DeviceHubPlugin.commands` с класса).
4. **Описание и аргументы — при регистрации:** хук плагина `command_options(name)` (SPI.d1, framework) возвращает
   `{"metadata": {"description", "args"}, "executor", "key_from"}`; пустые ключи не кладутся. Операции данных робота
   идут на именованный исполнитель `device_io` (Task 1.9m), ключ порядка — `device_id`; операции `immediate` — никогда
   не в очередь исполнителя.
5. **Исполнитель `device_io` объявлен в топологии:** `executors.device_io: {max_workers: 4, max_pending: 64}` у
   процесса `devices` в `base.yaml` (SPI.d3; значения — умолчания `ExecutorSpec`, не замер). Чтобы ключ дошёл до
   процесса, `ProcessConfig` чертежа получил поле `executors` (SPI.d0, C-47).
6. **Швы тестов вместо приватных имён:** `RobotDriverV2(client_factory=...)` (класс клиента, не экземпляр) и опции
   драйверов вида в менеджере — `DeviceManager(driver_options=...)` / `set_driver_options(kind, **opts)`
   (SPI.f1, f2a). `ClientRecorder` в `Services/device_hub/tests/conftest.py` строит настоящий клиент и хранит ссылку.
   `drv._client` в тестах хаба вне v1/ПЧ/сторожа: 43 → 0; AST-дифф узлов `assert` изменённых файлов пуст.
7. **Затвор переподключения в базе (SPI.g):** `BaseDeviceDriver.RECONNECT_THROTTLE_S` и `_reconnect_due()`; тела
   `_attempt_reconnect` / `_ensure_connected` (в т. ч. `_param_lock` v2) остались у драйверов.

### Отступления от брифа (фиксируем, чтобы не открывать заново)

| # | В брифе | Сделано | Почему |
|---|---|---|---|
| 1 | `command_table` сверяет `OpSpec` целиком | то же, и строго: одноимённая операция из второго источника равна первой, только если совпали `kind`, `route`, `key_from` источника — иначе `ValueError` | молчаливое слияние двух разных путей исполнения под одним именем скрыло бы ошибку каталога |
| 2 | допустимый вид устройства — `VALID_KINDS` | допустимый вид = зарегистрированная фабрика драйвера (`DeviceManager._check_kind`, SPI.c1b) | новый вид = драйвер + `register_driver_factory`, без правок хаба |
| 3 | `executors` из топологии «уже работает» | не работал: `ProcessConfig` отбрасывал ключ (C-47) — добавлено поле и проброс в `as_generic_config` (SPI.d0, framework) | проверено экспериментом: `build_configs()[0].executors == {}` |
| 4 | литералы описаний `draw_square`, `draw_set_pen`, `draw_set_overlap` (А3) | описания и `args_schema` по коду `robot_driver.py` (`x1, y1, x2, y2, z?` / `down?, up?` / `mm`) (SPI.c2b) | литералы брали старые докстринги плагина, расходившиеся с драйвером; описание — правда о контракте (решение лида) |
| 5 | `client_factory` внедряется в менеджер | универсальные `driver_options` по виду, менеджер не знает про клиента робота (SPI.f2a) | менеджер не связывается с конкретным драйвером; для v2 опция даёт `client_factory` |

### Альтернативы

- `client=` экземпляром вместо фабрики: драйвер строит `ClientV2Config` из `entry.params` по закрытому списку ключей;
  тест дублировал бы это отображение или расходился с боевой сборкой. Отвергнуто.
- Публичное свойство `client` у драйвера: даёт чтение приватного состояния всем потребителям, не только тестам.
  Отвергнуто.
- `register_driver_factory("robot", ...)` в каждом тесте менеджера: пришлось бы повторять сборку драйвера из приватных
  `_publish`, `_spawn`, `_robot_store` менеджера (`publish` менеджера оборачивает обратный вызов). Отвергнуто.
- `command_table` без проверки `kind` / `route` / `key_from`: см. отступление 1. Отвергнуто.

### Последствия

- Новый вид устройства = класс драйвера с `OP_SPECS` + `register_driver_factory(kind, factory)`; в `manager.py` и
  `plugin.py` ничего не правится; команды `<вид>_<операция>` ставятся `install_op_commands`.
- Видимые изменения: описания 34 команд и `args` в каталоге и `CAPABILITIES.yaml` / `.md` (регенерация командой
  `python -m backend_ctl.dump_capabilities`, headless-бэкенд, окно `heavy`); `key_missing` / `executor_busy` у 10
  команд данных; текст отказа регистров у ПЧ; каскад моста по `set_degraded() -> bool`.
- **Ограничение `driver_options`:** опции действуют на весь `kind`, на драйверы, создаваемые после вызова. Опции вида
  `robot` получает и v1 `RobotDriver`; `client_factory` он не знает, так что в реестре с роботами обоих протоколов
  v1 упадёт `TypeError` конструктора (не глушится). v1 заморожен (FREEZE) и не меняется.
- `immediate` защищает от очереди исполнителя, но не от потока роутера: длинная синхронная операция (`toolchange` v1,
  `stop` v2 ждёт эхо до 0,8 с) по-прежнему задерживает следующие команды процесса. Вне SPI.
- Значения исполнителя `4/64` — умолчания, не замер; живой стенд для SPI не гонялся.

### Связь

ADR-DH-009 (потоки у области плагина), ADR-DH-010 (`RobotState`, пакет), ADR-DH-011 (линеаризация `connect` /
`request_stop`); C-47 (`plans/queue/defects.md`); `plans/robot-protocol-v2/tasks/SPI.md`, `SPI.seams.md`,
`SPI.acceptance.md`, `SPI.deviations.md`.
