# Task 2.3d — слепой tester до кода

Файл тестов: `Services/camera_device/tests/test_plugin_device_commands.py` (30 тестов). Дерево: detached `b41f1575f`, до реализации. Код приложения не менялся, коммитов нет.
memory hits: n/a (поиск по памяти не запускался: задача — только тесты по готовому ACCEPTANCE).

## Тесты -> строки ACCEPTANCE

| Строка ACCEPTANCE | Тесты |
|---|---|
| 2 (`list_devices` без сеанса) | `test_list_devices_без_сеанса_отвечает_списком_приборов`; `..._журнал_порта_acquire_enum_release_без_open`; `..._не_оставляет_ссылку_на_sdk`; `..._не_создаёт_сеанс_и_не_ставит_мост_логов` (есть контроль: `take_device` мост ставит); `test_list_devices_дважды_и_take_device_используют_один_порт` (`create_port` == 1, `refs == 1`) |
| 3 (`list_devices` при захвате) | `..._при_захвате_отвечает_тем_же_списком`; `..._в_журнале_только_enum_devices_без_acquire_и_release`; `..._enum_devices_идёт_в_потоке_владельца` (== поток `open`, не поток теста); `..._ссылка_sdk_одна_до_и_после_кадры_идут` |
| 4 (`opening`, `stopping`) | `test_list_devices_при_opening_отказывает_и_порт_не_вызван` (`open_delay_s=0.3`); `test_list_devices_при_stopping_отказывает_и_порт_не_вызван` |
| 5 (`describe_params` при захвате) | `..._exposure_time_по_таблице_фейка`; `..._есть_все_поля_привязок`; `..._trigger_mode_entries_список_и_доступ_ro`; `..._каждый_describe_param_идёт_в_потоке_владельца`; `..._вызывает_describe_param_ровно_по_разу_на_привязку` (счёт от длины журнала до команды) |
| 6 (без `node_describe`, `PortError`, без захвата) | `..._без_node_describe_пустая_карта_и_порт_не_вызван_при_захвате`; `..._без_node_describe_и_без_захвата_пустая_карта_порт_не_вызван` (`port.calls == []`); `..._отказ_узла_даёт_none_для_поля_остальные_заполнены` (подмена `port.describe_param` на экземпляре); `..._без_захвата_с_capability_отказывает` |
| 7 (`trigger_software`) | `..._без_capability_отказывает_и_сеанс_не_создан`; `..._с_capability_без_захвата_отказывает`; `..._при_захвате_успех`; `..._execute_triggersoftware_в_потоке_владельца` |
| 8 (хук привязки) | `test_хук_software_trigger_binding_команда_берёт_привязку_из_хука` (подкласс `_OtherTriggerPlugin`) |
| 9 (набор команд) | `test_набор_команд_плагина_девять_команд_р7`; `..._вместе_с_set_config_и_register_update_одиннадцать_для_4_2a`; `test_каждая_команда_из_набора_указывает_на_существующий_метод`; `test_регистрация_команд_плагином_отдаёт_девять_и_generic_set_config` (через `_auto_register_commands` и `MockCommandManager`, вызов зарегистрированного `list_devices`) |
| 10, 11, 12 (hazard автора, сторож `call`) | не мои: пишет автор кода в `test_live_apply_hazards.py` и `test_plugin_commands_port_hazards.py` |
| 13 (страж потоков) | `test_страж_plugin_base_не_создаёт_потоков_и_исполнителей` — построчный regexp по тексту `plugin_base.py`, эквивалент `git grep -nE`; зелёный уже сейчас (по ACCEPTANCE красного до кода нет) |

## Красные / зелёные

Дерево тестера (до кода), команда: `machine_gate.sh light inspector-bottles-20 <venv python> -m pytest Services/camera_device/tests/test_plugin_device_commands.py -q --tb=line -p no:cacheprovider`

```
28 failed, 2 passed
```

Причины красных (подсчёт по выводу): 11 x `AttributeError: 'CameraDevicePlugin' object has no attribute 'cmd_list_devices'`, 9 x `... 'cmd_describe_params'`, 4 x `... 'cmd_trigger_software'`, 1 x `'_OtherTriggerPlugin' ... 'cmd_trigger_software'`, 3 x `AssertionError` про набор команд (в `commands` нет шести команд). Ошибок настройки теста среди красных нет: все падения — отсутствующая команда или реальное расхождение набора.
Два зелёных: страж потоков (по ACCEPTANCE) и «каждая команда из набора указывает на существующий метод» (сегодня набор из трёх команд, проверка станет содержательной после кода).

`ruff check -q` и `ruff format --check` по файлу — чисто.

## Валидность: черновик реализации вне дерева

`/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/422fbc6b-1296-4c1b-8072-6402b3628f21/scratchpad/proto23d/` — копия `Services`, `multiprocess_framework`, `scripts`, корневых `conftest.py` и `pyproject.toml`; черновик накладывает `scratchpad/apply_draft.py` на `plugin_base.py` (`_ensure_port`, хук `software_trigger_binding`, три новые команды, заглушки `reset_stats`/`read_params`/`apply_params`, `session.call`). Импорт проверен: `Services.camera_device.__file__` указывает в `proto23d`.

- С черновиком: `30 passed`, 6 прогонов подряд, флаков нет (2,6–2,9 с на прогон).
- Матрица инъекций (`scratchpad/matrix.py`), 18 мутаций черновика, все пойманы (CAUGHT 18 из 18): утечка `release`; `acquire` при захвате; проверка `state != grabbing` вместо `device_held` (ловят `opening`/`stopping`); порт без кэша; `list_devices` создаёт сеанс; нет проверки capability в `describe_params`/`trigger_software`; порт в потоке вызывающего (`describe`, `execute`); `PortError` не ловится; `entries` кортежем; двойной `describe_param`; хук игнорируется; нет `describe_params` в наборе; `min`/`max` местами; нет `name`; отказ без сеанса стал успехом; `call` заменён прямым вызовом. Каждая падает на тесте, названном под неё (список — в выводе `matrix.py`).

## Вопросы лиду

Противоречий и неисполнимых строк в ACCEPTANCE не нашёл. Допущения, которых в ACCEPTANCE нет дословно (при несовпадении — сказать, поправлю тест):

1. Сигнатура хука: `software_trigger_binding(self) -> Binding` (по образцу `bindings(self)`); тест подкласса так и вызывает.
2. Ответ `list_devices` при отказе `call`-пути и прочие тексты берутся только из ACCEPTANCE; для хука «чужой ключ» проверяется лишь `success is False`.
3. `describe_params` без захвата (с capability): дополнительно утверждаю, что `describe_param` в журнале нет (вывод из «порт трогает только владелец»; ACCEPTANCE говорит об этом только для варианта без `node_describe`).
4. Регистрация команд проверена через приватный `plugin._auto_register_commands(ctx)` + `MockCommandManager.commands` (единственная наблюдаемая точка «11 команд» без `PluginOrchestrator`); `register_update` в набор плагина не входит (его ставит оркестратор), поэтому 11 = 9 + `set_config` + `register_update` проверено как арифметика множеств плюс 9 + `set_config` реально зарегистрированных.

## Что я оставил открытым / ненадёжно

- **`stopping` и `opening` ловятся реальными окнами, не подменой `DeviceSession.state`.** `opening`: жду записи `open` в журнале (а не 0,05 с, как в ACCEPTANCE), окно держит `open_delay_s=0.3`. `stopping`: `arm_hang(0.8)` + `time.sleep(0.1)`, затем `release_device` в daemon-потоке; окно ~0,7 с. Оба теста после команды перепроверяют `state` через `get_status` (окно не закрылось). Слабое место: сон 0,1 с и предположение, что висящий `get_frame` уже взят; на сильно загруженной машине окно может не наступить, тогда тест упадёт на проверке `state`, а не даст ложный зелёный.
- Проверка «порт не вызван» в `opening`/`stopping` — равенство длины журнала до/после команды; в `stopping` после окончания зависания владелец сам пишет вызовы очистки — тест укладывается в окно, на медленной машине это узкое место.
- «Мост логов не поставлен» проверяю и атрибутом `plugin._log_bridge` (приватный), и числом хендлеров `_SessionLogBridge` на логгере `camera_device.session` (наблюдаемо, относительно значения до теста).
- «Один `call` на `describe_params`» не проверяется напрямую (журнал не различает вызовы `call`): проверены счёт по привязкам и поток; прямое доказательство даст hazard автора или шпион на `session.call`, которого я не ставил (запрет шпионов на имя API).
- Страж потоков (строка 13) — тест по тексту файла, не `git grep`: порядок и номера строк в выводе при падении свои; семантика та же (построчный regexp, комментарии и docstring тоже считаются).
- Строки 10–12 ACCEPTANCE (сторож `call`, медленный `close`, `call` против `stop`) не покрыты мной по брифу.
- Черновик реализации — не продакшн-код: отдельная блокировка гонки `take_device` против прямого `acquire` в `list_devices` в нём не реализована, поэтому тесты не доказывают её отсутствие (hazard автора).
- Не запускал остальные тесты пакета `camera_device` (не требовалось: файл самостоятельный; общих fixtures с соседями нет).
