# Ревью ветки «SPI хаба» перед слиянием (полоса Р2) — reviewer (Opus), фазовое

Дерево `.claude/worktrees/robot-v2-spi`, ветка `feat/robot-v2-spi`, HEAD `9402aab38`, дифф `main...HEAD` (25 коммитов,
72 файла). Код и тесты дерева я не менял; записан только этот отчёт (не закоммичен). Пробы — скрипты в scratchpad
(`opus_spi/`), к дереву не относятся. Вход (не повторял): бриф `SPI*.md`, стадия 0 (2 круга), ревью Sonnet (2 круга,
APPROVED), матрица 38 инъекций и вердикт лида, ADR-DH-012, ADR-PM-056, C-47.
Память: `scripts/memory/search.py executor device_io shutdown plugin stop` → 8 уроков, к SPI не относятся.

## Вердикт: CHANGES REQUESTED (итерация 1 из 2)

Код держится: имена и методы 72 команд не изменились, слои зелёные, путь стопа и отключения не сдвинут, тесты радиуса
зелёные. Причина вердикта — один дефект дизайна (два источника истины каталога операций и ложное утверждение ADR о пути
роста) и известное условие слияния (CAPABILITIES). Исправления дешёвые: текст ADR/README и один тест (или удаление поля).

## Замечания

### 1. [architecture, major] `OP_SPECS` драйвера никто не читает: команды строятся из `DEFAULT_SOURCES`; путь роста в ADR ложный

Где: `Services/device_hub/drivers/{base.py:56, robot_driver.py:48, robot_driver_v2/__init__.py:33, vfd_driver.py:35}`
(`OP_SPECS`); `Plugins/hub/device_hub/plugin.py:1010` (`install_op_commands(DeviceHubPlugin, DEFAULT_SOURCES)` при
импорте); `ADR-DH-012.md:69-70`, `Services/device_hub/README.md:50-54`.

- `git grep` по `OP_SPECS`, `DEFAULT_SOURCES`, `install_op_commands(` вне тестов и документов: `OP_SPECS` только
  присваивается (4 строки), прод-читателя нет. Команды ставит один вызов при импорте модуля плагина по `DEFAULT_SOURCES`.
- Тест полноты (`test_spi_contract.py`) связывает `OP_SPECS` с `_OPS` драйвера, но ни один тест не связывает
  `DEFAULT_SOURCES` с `OP_SPECS` драйверов (в тестах `DEFAULT_SOURCES` встречается только в `command_table(DEFAULT_SOURCES)`).
  Сегодня это одни и те же объекты-кортежи, живого расхождения нет; дрейф тихий.
- Проба `opus_spi/probe_design.py` (гейт light, PYTHONPATH = корень дерева), вывод дословно:
  ```
  1 upsert new kind: DeviceEntry lamp
  1 lamp_on in DeviceHubPlugin.commands: False
  1 commands with prefix lamp_: []
  2 robot_new_op in commands after OP_SPECS change: False
  ```
  Вход: класс `LampDriver(BaseDeviceDriver)` с `kind="lamp"` и одной операцией в `OP_SPECS` + `register_driver_factory`.
  Выход: вид принят менеджером, команд `lamp_*` нет. Вход: `RobotDriverV2.OP_SPECS` дополнен операцией. Выход: команды
  `robot_new_op` нет.
- Плюс: менеджер создаётся только внутри `DeviceHubPlugin.configure` и сразу зовёт `initialize()`
  (`plugin.py:171-174`). Зарегистрировать фабрику нового вида «до `initialize()`», как требует ADR, извне нельзя.
  Фактически набор видов — по-прежнему 4 фабрики `_register_defaults` (замороженный `VALID_KINDS` — их копия без читателей).

Утверждение ADR «Новый вид = класс драйвера с `OP_SPECS` + `register_driver_factory`; в `manager.py` и `plugin.py`
ничего не правится; команды ставит `install_op_commands`» не выполняется. На него опрётся следующий вид (миграция
`hik_*`, новые устройства). По принципу «меньше слоёв» `OP_SPECS` на драйвере — лишний слой: указатель на тот же
кортеж каталога без потребителя.

Исправить (одно из двух, решение лида):
- (а) убрать `OP_SPECS` с драйверов (поле новое, в main его нет — FREEZE не нужен); сторож полноты перевести на каталог:
  имена `ROBOT_V2_OPS` == ключи `RobotDriverV2._OPS` и т. д.; `OP_SPECS` из `Protocol` `DeviceDriver` снять;
- (б) оставить `OP_SPECS` и добавить сторож: для каждого вида фабрик по умолчанию объединение `OP_SPECS` его классов
  == операции `DEFAULT_SOURCES` того же `kind` с `route="driver"`; инъекция — `RobotDriverV2.OP_SPECS` + операция при
  неизменном `DEFAULT_SOURCES` → красный.
В обоих случаях поправить ADR-DH-012 «Последствия» и README:50-54: новый вид = драйвер + фабрика в
`_register_defaults` + `OpSource` в `DEFAULT_SOURCES` (правка хаба); шов «фабрика до `initialize()`» есть только у
прямого `DeviceManager` (тесты), не у процесса.

### 2. [spec, blocker, процессный, известно] CAPABILITIES не перегенерированы

`git diff --stat main...HEAD -- docs/contracts` — пусто. Ревью Sonnet п.1 открыт; без регенерации
`backend_ctl/tests/test_capabilities.py::test_dump_matches_committed` красный (вывод Sonnet по чтению; я тоже не гонял —
окно heavy). Условие слияния: регенерация в окне heavy лида (~17:20), оба файла в ветку до слияния.

### 3. [quality, minor] Список видимых изменений IPC не полон

Сверено: 72 имени и имена методов совпадают с main (AST литерала `commands` в `main:plugin.py` против
`DeviceHubPlugin.commands` HEAD: `main 72 head 72 names equal True methods equal True`). Текст отказа регистров —
действительно только у ПЧ: у робота v2 свойство `transport` есть (`_RobotDriverCore.transport`), путь чтения регистров
v2 не изменился — эта строка списка верна.
Не записано в ADR-DH-012 «Последствия»:
- 10 команд данных в окне остановки процесса получают `{"success": False, "error": "system_stopping"}`: фаза 1
  закрывает приём исполнителя до остановки плагинов (`process_module.py:536-540`, `keyed_executor.py:251-256`); до SPI
  такая команда исполнялась на потоке роутера. Форма — как у `key_missing` / `executor_busy` (без `status`).
- В `metadata` команды (`get_command_info`, introspect) добавились ключи: `args` у 55, `executor` и `key_from` у 10.
  Аддитивно, но видно `backend_ctl`.
- Вызов команды данных без `reply` (прямой `handle_command`) — исполнение на вызывающем потоке и один WARNING на имя
  (`command_manager.py:469-475`).
Исправить: три строки в «Последствия» ADR-DH-012.

### 4. [совет, не воспроизводилось] Операция данных в полёте при остановке — вне области потоков хаба

По чтению: потоки `device_io` принадлежат `ExecutorManager` процесса, не корню `device_hub` (ADR-DH-009 «потоки у
области плагина»). Порядок: фаза 1 — `request_stop` исполнителя (ждущие получают `system_stopping`), затем
`DeviceHubPlugin.shutdown` (срок хаба), фаза 2 — `join_until` исполнителя после `workers`. Операция в полёте идёт
параллельно `shutdown` хаба и ждётся вне его срока. Вреда по коду нет: операции данных трогают только `RobotDataStore`
(замок на документ, `_atomic_write` tmp + `os.replace`, сверка `base_rev` под замком, `Services/robot_comm/store.py:208-283`)
и чтение реестра под `_registry_lock`; драйверы, `_workers_lock` и порядок ADR-DH-010/011 не затронуты; `immediate` идут
на потоке роутера и исполнителя не ждут. Совет: одна строка в ADR-DH-012 — исключение из ADR-DH-009 и его основание.

### 5. [совет] Имя исполнителя — строковый контракт через три слоя

`"device_io"` записан в `Services/device_hub/spi.py` (каталог Services), передаётся плагином, объявляется в
`multiprocess_prototype/backend/topology/base.yaml`. Сторож — только со стороны прототипа
(`test_devices_executors.py`); без объявления команды уходят запасным путём (WARNING менеджера команд + INFO хука) —
деградация мягкая, принцип 5 соблюдён. Политика размещения (исполнитель процесса) лежит в каталоге Services. Не блокирует;
при переносе среды робота в `Services/robot_comm` — вынести имя исполнителя в плагин (`command_options`).

## Что проверено по фокусу брифа

1. **Дизайн.** `Protocol` + умолчания-атрибуты класса + `__init_subclass__` (громкий отказ в обе стороны) + `stop_aware`
   — без `getattr`/`hasattr` по драйверу в `manager.py`/`plugin.py`. `command_table` строгий. `driver_options` — шов
   тестов в публичном API менеджера с ограничением на весь `kind` (принято лидом, Sonnet п.7; не повторяю). Дефект — п.1.
2. **Конкурентность.** `_safe_call`: оба счётчика и `last_error` под `_counters_lock` (`plugin.py:595-614`); других
   держателей замка нет, цикла замков нет. Исполнитель keyed по `device_id`, 4/64; операции разных роботов параллельны,
   одного — последовательны; гонки с операциями драйвера v2 (`point_capture`, `param_set` на потоке роутера) по одному
   документу закрывает замок документа хранилища и `base_rev`. Путь стопа и отключения — п.4.
3. **Framework.** Хук `command_options`: без опций — вызов байт в байт прежний; белый список ключей; запасной путь без
   исполнителя. Регистрация — в `_do_configure` после `configure` (`base.py:1581-1584`); снятие команды снимает привязку
   исполнителя (`command_manager.py:638`). C-45: блок `set_config` в диффе — только контекст. `blueprint.py`: поле
   `executors` с умолчанием `{}`, ключ в `base_kwargs` только при непустом значении; `executors:` в yaml — только
   `base.yaml:37`. Ф 1.9b: пересечение файлов `main...feat/lifecycle-pm-keyed-executor` и `main...HEAD` — пусто.
   Слияние с текущим main (+34 коммита, в т. ч. `blueprint.py` C-25/C-28): `git merge-tree --write-tree --name-only main HEAD`
   → только хэш дерева, конфликтов нет.
4. **IPC.** П.3.
5. **Слои.** `sentrux check .` (CLI, дерево ветки): `sentrux check — 41 rules checked ... ✓ All rules pass`, rc=0.

## Прогоны (гейт light, сессия inspector-bottles-00, PYTHONPATH = корень дерева, PYTHONUTF8=1)

| Что | Результат |
|---|---|
| `Services/device_hub/tests/{test_spi_contract,test_spi_acceptance,test_manager}.py`, `Plugins/hub/device_hub/tests/{test_spi_hazards,test_op_commands,test_spi_commands_acceptance}.py`, `multiprocess_prototype/backend/tests/test_devices_executors.py` | `331 passed, 1 warning in 20.84s` |
| cwd `multiprocess_framework/modules`: `process_module/tests/test_plugin_command_options{,_acceptance}.py`, `process_manager_module/tests/test_blueprint_executors.py` | `16 passed, 1 warning in 1.14s` |
| `pyright` на `manager.py`, `spi.py`, `plugin.py`, `drivers/base.py` | `0 errors, 1 warning` — `manager.py:467`, строка 2026-10-19, не SPI |
| проба `opus_spi/probe_design.py` | вывод — п.1 |

## Стадия 0

Дефект ДИЗАЙНА, который должна была поймать стадия 0: **да, частично**. Два источника каталога — в самом брифе: D2
вешает `OP_SPECS` на драйверы, D4/D5 строят команды из `DEFAULT_SOURCES`, сторож D4 связывает `OP_SPECS` только с `_OPS`.
Вопрос «кто читает `OP_SPECS` во время работы» (класс «настройка введена, но не читается») стадия 0 не задала.
Ложный путь роста («вид = фабрика, без правок хаба») появился позже, в отступлении c1b и ADR, — это не стадия 0.

## Что оставил открытым / ненадёжным

- П.4 — только чтением (`process_module.py:536-540`, `keyed_executor.py:251-281`, `store.py`); живой остановки с
  операцией данных в полёте не гонял: нужен процесс `devices` с исполнителем и медленной записью.
- Не гонял: `test_dump_matches_committed`, весь `Services/device_hub/tests`, `Plugins/**`, `process_module/tests`
  целиком, стенд v2 — окно heavy у лида. Тесты на дереве слияния с main не гонял: проверено только отсутствие
  конфликтов (`merge-tree`), не совместимость поведения с 34 коммитами main.
- Матрицу инъекций не повторял; инъекцию для сторожа из п.1 (б) не писал — это работа исполнителя.
- Ф 1.9b: сверил только ветку `feat/lifecycle-pm-keyed-executor`; `tests/lifecycle-1.9b-*`, `docs/lane-F-1.9b-pause`,
  `origin/atlas/1.9b` — нет.
- `pyright` не отметил `drv.request_stop` на `DeviceDriver` (`manager.py`, отбор стопа): в `Protocol` `DeviceDriver` метода
  нет. Почему проверка молчит (режим конфигурации) — не выяснял; статический контракт `Protocol` поэтому слабее, чем
  заявлено в D1.
- Граница охраны `__init_subclass__` (метод `request_stop` на экземпляре; `stop_aware` как `property`) — из ревью Sonnet,
  не перепроверял.
- Тела тестов `test_spi_*` построчно не читал; качество их проверок держится на матрице лида и выборочных инъекциях Sonnet.
