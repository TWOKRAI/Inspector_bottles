# SPI хаба — прогнозы инъекций (лид, до прогона)

Записаны лидом inspector-bottles-00 2026-10-26 ДО любого прогона матрицы. Номер = свойство из `SPI.injections.md`.
Слепые файлы: `BS` = `Services/device_hub/tests/test_spi_acceptance.py`, `BP` = `Plugins/hub/device_hub/tests/test_spi_commands_acceptance.py`,
`BF` = `multiprocess_framework/modules/process_module/tests/test_plugin_command_options_acceptance.py`.
Авторские: `TC` = `test_spi_contract.py`, `TO` = `test_op_commands.py`, `TN` = `test_no_private_driver_state.py`,
`TL` = `test_robot_v2_state_acceptance.py`, `TH` = `process_module/tests/test_plugin_command_options.py`,
`TB` = `process_manager_module/tests/test_blueprint_executors.py`, `TD` = `backend/tests/test_devices_executors.py`.
Прогноз = множество красных; «и только» — посторонний красный тоже находка.

| № | Инъекция (одна правка) | Прогноз: красные | Должны остаться зелёными |
|---|---|---|---|
| 1 | `DEFAULT_SOURCES` без `VFD_OPS` | BP А1, BP А19 (vfd), гвард 72 имён `test_robot_v2_commands_acceptance.py`; TO описания 55 | BS целиком |
| 2 | маршрут `needs_link=False` → через `_kind_call` (проверка связи) | BP А6 | BP А4, А5, А7 |
| 3 | маршрут `data` → `_driver_call` | BP А7; TO (если есть тест маршрута данных) | BP А6 |
| 4 | в сгенерированной команде убрать проверку вида | BP А5 | BP А4, А6 |
| 5 | в сгенерированной команде убрать проверку `device_id` (синхронный путь) | BP А4 | BP А22 (путь роутера) |
| 6 | фабрика замыкания → переменная цикла (все команды зовут последнюю операцию) | BP А19 ×3; TO фабрика | BP А1 |
| 7 | убрать одну операцию из `RobotDriver.OP_SPECS` | TC `OP_SPECS == _OPS` | BP А1 (каталог не трогали) |
| 8 | `command_table`: при одноимённых `OpSpec` с разным `description` брать первый молча | BS А10б (ValueError), TC | BS А10г |
| 9 | `OpSpec.__post_init__`: убрать проверку executor+immediate | BS А10г; TC | BS А10б, в |
| 10 | `stop` v2 → `immediate=False` | BS А12 (immediate v2) | BS А12 v1, vfd |
| 11 | описание одной из 34 команд — опечатка | BP А3 (одна параметризация); TO/TC литерал 55 | BP А1 |
| 12 | `disconnect_pending is True` → истинность (`if driver.disconnect_pending`) | BP А14 | test_c29_* (кроме MagicMock-случая — прогноз: красный 1 в А14 и только) |
| 13 | `request_disconnect` вызывать после `put` (вне `_workers_lock`) | test_c29_* (точка линеаризации), BP А14 | BP А25 |
| 14 | убрать `try` вокруг `request_disconnect` | BP А25 | BP А14 |
| 15 | вынести чтение `stop_unconfirmed` из `try` | BP А24 | BP А15 |
| 16 | отбор целей стопа по `True` для всех драйверов (`stop_aware` игнорировать) | BP А15; TC соответствие stop_aware | BS А16 |
| 17 | в `manager.py` вернуть `getattr(d, "last_io", None)` с переменной `d` | TC `test_no_duck_typing_on_drivers` | TN (приватных имён нет) |
| 17b | в `manager.py` вернуть `driver._client` в `_register_transport` | TN часть (в); BP А13 (текст) | TC duck |
| 18 | `RegisterTransportUnavailable` → текст с device_id | BP А13 | BS А13 issubclass |
| 19 | `install_op_commands` без copy-on-write (пишет в `cls.commands` родителя) | BP А9; TO copy-on-write | BP А1 (если порядок тестов не тянет) — прогноз: А1 зелёный |
| 20 | вернуть `_apply_op_descriptions` в `start()` (замена metadata целиком) | BP А17, А18; TO command_options | BP А3 |
| 21 | умолчание `set_degraded` → `True` | BP А20; TC умолчание False | BS А11 Hik False? — прогноз: BS А11 `hikvision_set_degraded_returns_false` красный тоже |
| 22 | `transport` в базе → `@property` | BS А21 (присваивание в подклассе) | BS А16 атрибуты класса — прогноз: красный и он |
| 23 | хук: убрать белый список опций | BF А26 `{"handler": 1}`; TH | BF А26 без опций, А27 |
| 24 | хук: пустые опции → `register_command(name, method, **{})` с именованным `metadata={}` | BF А26 (2 позиционных и без именованных); TH литерал гарантии Ф | BF А27 |
| 25 | `_RESET_TRANSITIONS` без `connect_begin` (литерал) | TL тест (1) AST и тест (2) | TL строки |
| 26 | `state.py`: убрать `_connect_reset_locked()` в `connect_begin` (ветка go) | TL `connect_begin_go`, TL тест (1) AST | TL прочие строки |
| 27 | убрать `_counters_lock` в `_safe_call` | TO свойство 27 (детерминированный) | — |
| 28 | убрать `try` на зависимого в каскаде | BP А20 (первый бросает, второй деградирует) | BP А20 основной |
| 29 | `report_error` внутри `_workers_lock` | TO/TH тест автора «замок свободен» | BP А25 |
| 30 | хук пишет WARNING при отказе исполнителя | BP А23 | BF А26/А27 |
| 31 | `blueprint.py`: убрать проброс executors (C-47) | TB (а), (в); TD ×3; снимки `test_build_characterization` ×2 | TB (б) |
| 32 | `blueprint.py`: класть `executors={}` всегда | TB (б) (гарантия «без ключа — как раньше») | TB (а) |
| 33 | `manager._check_kind` убрать (c1b) | `test_manager.py::TestKindByFactory` литерал отказа | BP А9-2 |
| 34 | `_check_kind` по `VALID_KINDS` вместо фабрик | BP А9-2; TestKindByFactory фабрика | TestKindByFactory 4 вида |

Порядок прогона: база без инъекций (collected числом, без `-k`) → каждая инъекция отдельно → откат `git checkout -- <файл>` → база ещё раз в конце.

## Дополнение после ревью задачи р.1 (лид, 2026-10-26, до прогона)

| № | Инъекция (одна правка) | Прогноз: красные | Должны остаться зелёными |
|---|---|---|---|
| 35 | убрать `BaseDeviceDriver.__init_subclass__` | TC: оба теста направлений (метод без флага, флаг без метода) | TC 5 боевых классов |
| 36 | `initialize()`: присваивать запись за записью (без двухпроходной проверки) | `test_manager.py::TestInitializeAllOrNothing` | `TestKindByFactory` |
| 37 | v2: начальная метка затвора `0.0` → `-inf` | TC `test_reconnect_initial_mark_per_class_is_literal` | TC интервалы |
