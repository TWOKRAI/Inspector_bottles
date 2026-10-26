# SPI хаба — стадия 0: ревью брифа (reviewer)

Дата: 2026-10-26. База: `feat/robot-v2-spi` = main `9b6645546` + файлы брифа. Проверено чтением и `git grep`; тесты не гонялись, `sentrux check .` не запускался.
memory hits: `search.py device_hub driver SPI contract` -> `docs/claude/memory/project_device_hub.md`.

## Вердикт: CHANGES REQUESTED (итерация 1 из 2)

Идея верна. Счёт хуков подтверждён: 13 строк (`plugin.py:368, 372, 446, 454, 551, 553, 562, 912`; `manager.py:131, 425, 453, 564, 597`). Бриф не готов к слепому tester: два дефекта ломают SPI.d молча, два ломают CI. Метка **[Δ]** — пункт, где ответ лида на В1–В6 меняет дизайн брифа.

## Список правок

**1. [spec, блокер] D5 `_apply_op_descriptions` стирает `metadata.executor`; SPI.d обойдён молча.**
Где: `plugin.py:316-321`, `dispatch_module/strategies/exact_match.py:89`, `router_manager.py:1359`.
Вход: SPI.d, команда `robot_point_list` зарегистрирована с `executor="device_io"`; `start()` зовёт `update_command_metadata(name, {"description", "args"})`. Наблюдение: `update_handler_metadata` ЗАМЕНЯЕТ словарь (`handlers_storage[key].metadata = new_metadata`; README command_module: «Заменить метаданные»). После `start()` в `get_command_info(name)["metadata"]` нет ключа `executor`. Роутер решает, передавать ли `reply`, по `metadata.executor` (`router_manager.py:1359`): без ключа команда по IPC идёт на потоке роутера, один WARNING (`command_manager.py:469-475`). Исполнитель не используется, ошибки нет.
Исправить: описание и `args` класть при регистрации (через `command_options` -> `metadata`) либо делать read-merge-write: `{**(get_command_info(n) or {}).get("metadata", {}), "description": …, "args": …}`. А17: вызвать `_do_start` ДО чтения `metadata` и проверить путь роутера (`reply` передан), не только `handle_command(..., reply=r)` — он берёт исполнителя из `_executors`, не из `metadata`, и остаётся зелёным при дефекте. Добавить свойство инъекции; заглушку `_RefusingCatalogue` (`test_robot_v2_commands.py:226-236`) дополнить `get_command_info`.

**2. [spec] SPI.c — не «перенос без смены поведения»; затронут CI-гейт CAPABILITIES.**
Где: бриф «SPI.c», «Что осталось открытым» п.3 и п.6; `docs/contracts/CAPABILITIES.yaml`; `backend_ctl/tests/test_capabilities.py:186-203`.
Вход -> наблюдение: сегодня у 34 старых команд описания НЕТ. `register_command(cmd_name, method)` кладёт `metadata={}`; из докстринга описание нигде не выводится (`git grep __doc__` по `command_module`, `dispatch_module`: 0). В `CAPABILITIES.yaml`: `robot_enqueue_job` -> `description: ''`. После SPI.c у всех 55 команд есть `description` и ключ `args`. Рантайм-свод `introspect.capabilities` меняется; `test_dump_matches_committed` («дрейф = красный») краснеет. Файлы `CAPABILITIES.yaml` / `.md` не в FILES. Открытый п.6 брифа («гейт не найден») ошибочен: гейт есть, искали не в тех каталогах. Открытый п.3 закрыт: описаний нет.
Исправить: (а) строгий перенос c1 (описания только у 21, как сейчас), затем c2 — описания 34 + `args` + регенерация `python -m backend_ctl.dump_capabilities` (нужен headless-бэкенд: окно `heavy`/стенд) + оба файла в FILES; или (б) признать изменение видимым и сделать то же одним коммитом. Рекомендую (а). Строку «единственное видимое изменение — В2» заменить полным списком: В2, В4, +description/+args, строгие чтения.

**3. [tests, FILES] `test_robot_v2_commands.py` ломается и нигде не назван.**
Где: `Plugins/hub/device_hub/tests/test_robot_v2_commands.py:23, 246-250`.
Вход: бриф удаляет `_ROBOT_V2_DESCRIPTIONS`. Наблюдение: `ImportError` на всём модуле; тест `test_descriptions_refused_by_catalogue_only_warn` утверждает `set(updated) == set(_ROBOT_V2_DESCRIPTIONS) - {"robot_stop"}`, `len(...) == 21`, ровно одно предупреждение. Файла нет ни в FILES, ни среди «стражей переноса».
Исправить: добавить в FILES SPI.c; ожидаемое множество — литерал (21 при c1, 55 при c2).

**4. [architecture] `install_op_commands` мутирует `commands` родителя.**
Где: бриф D5 («дописывает `cls.commands[<имя>] = …`»), А9; `base.py:1377` (`commands: dict = {}` общий).
Вход: `class Sub(DeviceHubPlugin)` без своего `commands`; `install_op_commands(Sub, [fake…])`. Наблюдение: `Sub.commands is DeviceHubPlugin.commands`, поэтому в боевом классе появляется `fake_ping` без метода `cmd_fake_ping` (метод — на `Sub`). А1 (`== 72`) краснеет в зависимости от порядка тестов; `_auto_register_commands` боевого класса пишет «метод не найден». Для плагина вообще без `commands` — мутация базового словаря всех плагинов.
Исправить: copy-on-write: `if "commands" not in cls.__dict__: cls.commands = dict(cls.commands)`. В А9 добавить: после установки на `Sub` у `DeviceHubPlugin.commands` те же 72 имени. Свойство инъекции.

**5. [IPC, путь стопа] Строгие чтения в `shutdown` и `cmd_device_disconnect` снимают изоляцию драйверов.**
Где: `plugin.py:368, 372` (чтения вне `try`, который начинается на :370), `plugin.py:907-915`, `manager.py:131`.
Вход: драйвер без члена контракта (простые фейки есть: `test_health_fault._FaultyDriver/_HealthyDriver` без `stop_unconfirmed`; `Boom/Fine` в `test_robot_v2_scope.py:515` без `request_stop`). Наблюдение после D3: `driver.stop_unconfirmed` -> `AttributeError` из `plugin.shutdown` между `request_stop_all` и фазой 4: `_manager.shutdown()` (disconnect всех, `_save`) не выполняется; сегодня `getattr(..., False)` терпит. В `cmd_device_disconnect` `AttributeError` из `driver.request_disconnect()` летит под `_workers_lock` после `_desired_connected[dev_id] = False` и до `_conn_queue.put` — полусостояние: желаемое False, disconnect не поставлен. У реальных драйверов (наследники Base) невозможно; риск — фейки и принцип 5 (отказ одного не роняет соседей).
Исправить: чтения по драйверу в `_report_unconfirmed_stops` — внутрь существующего `try` (на драйвер); фейки доводятся до контракта (наследовать `BaseDeviceDriver`) или тест «драйвер без члена не роняет shutdown». Записать в D3 отдельным требованием к пути стопа. Новых гонок ADR-DH-009..011 D3 не добавляет: порядок и замки (`_workers_lock` -> `_registry_lock` -> состояние; `request_disconnect` до `put`) прежние.

**6. [Δ В1][architecture] D7: `threaded: bool` -> поле исполнителя в `OpSpec`; безопасность стопа — структурой, не списком имён.**
Где: D1 (`OpSpec`), D7, А12, А17, А18, инъекция 17.
По ответу лида (SPI.d сейчас, исполнитель из поля `OpSpec`) бриф меняется так:
- `OpSpec.executor: str | None = None` вместо `threaded`; `key_from` по умолчанию `"device_id"` — в `OpSource`. `command_options(name)` плагина читает таблицу команд и не держит списков имён. Записи `ROBOT_DATA_OPS` несут `executor="device_io"` литералом в `spi.py`.
- Нужно поле «не в очередь»: `OpSpec.immediate: bool` (стоп, аборты, jog, серво); `executor` вместе с `immediate` — `ValueError` при импорте. Сейчас знание «что нельзя в очередь» живёт только в А12, а он перечисляет 7 имён: `draw_abort`, `program_abort`, `servo`, `set_servo` не охвачены. А12 переписать: литерал полного множества `immediate`-операций + «у операций с `executor` нет `immediate`».
- Форма ответа: без `device_id` по IPC придёт `{"success": False, "error": "key_missing", …}` вместо `device_id обязателен`; при переполнении — `executor_busy` (`command_manager.py:426-434`). Принять письменно.
- Первый боевой пользователь именованных исполнителей (`executor=` в `Plugins`, `multiprocess_prototype` — 0). Нужен тест «настоящая цепочка»: процесс с `config["executors"]` -> регистрация -> роутер -> `reply` ровно один раз.
- FILES SPI.d неполон: `executors:` в `base.yaml` попадает в снимок процесса (`process_launch_config.py:178-181` убирает только пустые) -> перегенерировать `multiprocess_prototype/backend/tests/snapshots/phone_sketch.build.json`, `hikvision_letter_robot.build.json`, проверить `hot_rebuild_framework_keys.txt` и `test_hot_rebuild_parity_*`. Значения `max_workers: 4, max_pending: 64` ничем не измерены; запись без `kind` / `serial` (поля из `process_launch_config.py:106`) — проверить загрузкой `ExecutorManager.load_config`, не только yaml.
- Хук фреймворка нужен (иного публичного пути нет: `register_command` — единственная точка с `executor=`; `overwrite_command` исполнителя снимает, `command_manager.py:627-638`). Замечания: (i) условие «регистрация отклонена» — `result is False`, не `not result`: `testing.py:101` возвращает `None`; (ii) ключи `options` — белый список `{executor, key_from, targets, metadata}`, иначе плагин передаст `handler` / `expects_full_message`; (iii) отличать отказ «исполнитель не принят» от «имя уже есть» — иначе повтор даёт второе предупреждение; (iv) C-45: не трогать `set_config` (`base.py:1693`) и `cmd_set_config` (:1700-1727); правка только в цикле :1670-1676; `command_options` на `set_config` не действует.
- Польза не измерена (замера блокировки роутера файловым вводом-выводом в брифе нет): в ADR записать причину «сейчас» — масштабирование.

**7. [Δ В4][architecture] Общий каскад `set_degraded`: пустое умолчание публикует ложное `disconnected`.**
Где: D2, D3 (`manager.py:453`), В4.
Вход: каскад «носитель отключён» для зависимого драйвера, у которого `set_degraded` — умолчание базы (ничего не делает). Наблюдение: менеджер публикует `conn=disconnected`, драйвер остаётся подключённым, следующий тик (`plugin.py:551-559`) публикует `connected` -> мерцание и ложное состояние. Сегодня `hasattr` этого не допускает. Практически мост есть у одного `VfdDriver`: `GenericModbusDriver` строит транспорт как `build_transport(self.entry, lambda _: None)` (`generic_modbus_driver.py:63`), для bridge это `TransportBuildError`.
Исправить: `set_degraded() -> bool` («драйвер перешёл в деградацию»): база возвращает `False`, `VfdDriver` — `True` (`vfd_driver.py:123`); менеджер публикует `disconnected` только при `True`. В Protocol — `-> bool`. Умолчание не должно звать `disconnect()`: у зависимого на bridge транспорт общий с носителем (`transports.py:136`), закрытие оборвало бы связь робота. Добавить А20 (зависимый с `set_degraded() -> True`: после disconnect носителя публикуется `disconnected`; с умолчанием — не публикуется) и свойство.

**8. [Δ В2][architecture] Типизированный отказ: исключение внутри существующего `try`, не новый dict.**
Где: D3 `manager.py:564, 597`, А13.
Исправить: `RegisterTransportUnavailable(DeviceHubError)` в `Services/device_hub/errors.py` с постоянным текстом; один помощник `DeviceManager._register_transport(driver)` для `read_register` и `write_registers`; исключение ловит прежний `except Exception` и возвращает тот же `{"status": "error", "message": …}` — форма ответа не меняется, тип виден тесту менеджера. Текст — константа без входных значений (требование (iii) выполнено). А13: ожидаемое — литерал `"у устройства нет транспорта регистров"`; фейк «вида vfd» должен наследовать `BaseDeviceDriver` (иначе `driver.transport` -> `AttributeError`, а не отказ).

**9. [Δ В3][tests] Снятие швов `_client` — подзадача SPI.f.**
Где: `test_no_private_driver_state.py:79-80` (`_SEAMS["_client"] = 40`); драйвер v2 `driver.py:156, 339`.
Факты: сторож считает 40 обращений; `git grep` по обоим каталогам — 59, из них 16 в тестах v1 и ПЧ (вне сторожа, остаются). Из остальных 43: 6 присваиваний, прочее — чтения `drv._client` ради подмены `client.run_chunks` / `client.cmd`.
Дизайн: внедрение клиента через конструктор `RobotDriverV2(…, client=None)` рядом с `transport=`; не публичное свойство `client`. Тест подменяет клиент до подключения и держит свою ссылку. Правятся ~13 файлов, среди них слепые приёмочные тесты стопа (`test_c29_disconnect_acceptance`, `t53g_blind`, `t53h_blind`, `test_t53r2_stop_hazards`). Критерий: AST-дифф узлов `assert` и литералов ожиданий пуст; затем выборочная инъекция по 3 свойствам стопа (прогноз пишет лид). Убрать ключ `_client` из `_SEAMS`; `_SCANNED_FILES` и сторож (в) обновить в том же коммите. Файлов >6 — отдельный бриф-запуск.

**10. [Δ В6][architecture] Дроссель переподключения: выносить только затвор.**
Где: `robot_driver.py:548-552`, `vfd_driver.py:264-268`, `robot_driver_v2/driver.py:499-505`.
Три копии различаются: v1 и ПЧ возвращают `False` / снимок, v2 — внутри `_param_lock` с повторной проверкой `desired_connected` (T5.3h) и закрытием хвоста при отмене. Общая часть — «прочитать часы, сравнить, поставить метку, `_record_reconnect`». Вынести в базу `_reconnect_due(throttle_s) -> bool` и константу класса `RECONNECT_THROTTLE_S`; тело `_attempt_reconnect` v2 не двигать. Швы тестов `_last_reconnect` (5), `_reconnect_attempts` (6) — имена остаются в базе. Делать последним, отдельным коммитом, с гвардами T5.3g/T5.3h/C-29 и стендом S0–S3 (ADR-DH-011).

**11. [tests] D8: оракул защёлки слеп к новому сбросу.**
Где: `test_robot_v2_state_acceptance.py:804-826`, `state.py`.
(i) `_LATCH_EXEMPT` — свободный кортеж: переход, который сбрасывает защёлку, можно вписать в исключения, тест зелёный. Измерено по AST `state.py` (с замыканием через приватные помощники): до `_latch_reset_locked` доходят 7 публичных методов: `admit_launch, connect_begin, connect_reset, disconnect_begin, jog_started, request_stop_begin, take_next_action`; в оракуле 6 (нет `connect_begin`). Всего публичных методов 63 (бриф: «~60»). Требование: тест строит это множество из AST и требует равенство множеству методов со строкой `resets=True`; остальные 56 — исключения, им достаточно списка.
(ii) Строки `connect_begin_shutdown / _cancelled / _busy` (`resets=False`) нельзя записать в форме `(имя, lambda st: …, bool)`: чтобы получить shutdown / busy, действие вызывает `request_stop_begin` / `take_next_action` — сами строки сброса. Наблюдение: `after == _CLEAN_LATCH != before` — красная строка при верном коде. Нужен четвёртый элемент `setup`, выполняемый до `_dirty_latch`. Указать в D8. Имя строки не равно имени перехода (`take_job` -> `take_next_action`): нужно явное поле.

**12. [tests] Гарантии DESIGN без приёмки или свойства.**
- D5 «каждая из 55 команд зовёт свою операцию»: подмена `op` у одной команды (`robot_jog_hold` зовёт `jog_release`) не красит ни одну А-строку (А4/А5 — ранние отказы, А6/А7 — две команды). Добавить А19: фейк-драйвер видов `robot` и `vfd` пишет `(op, args)`; таблица 55 имён -> литерал `op`; `args` без `device_id`.
- D2/Т2 (умолчания — атрибуты класса, не `property`): А11 проверяет значения; откат на `@property` без сеттера её не краснит. Добавить: подкласс Base присваивает `self.transport / disconnect_pending / stop_unconfirmed / last_io` в `__init__`.
- Свойство 15 (`store_refusal`, А14) не падает: оба пути на базе уже отвечают одинаково (`args.py:139-145`, `robot_data_ops.py:305-309`); REDS `test_store_refusal_single_path` проверяет имя API, не поведение (правило §9).
- Свойство 6 (`OP_SPECS ⊆ _OPS`) слабее факта: на базе имена совпадают полностью (27/27, 17/17, 5/5). Требовать равенство + пустой литерал исключений, иначе новая операция в `_OPS` без `OpSpec` остаётся без команды молча.
- Protocol без потребителя: `manager.get_driver -> Any` (`manager.py:266`). Типизировать `get_driver`, `_get_connected_driver`, `_get_or_create_driver`, `_drivers`. Тест соответствия — все пять фабрик по умолчанию (`robot` v1/v2, `vfd`, `hikvision`, `generic_modbus`) против литерала имён членов (`typing.get_protocol_members` — только Python 3.13; проект на 3.12).

**13. [tests] Приёмка: что не проверяется литералами слепого tester.**
- А9, А10, А12: не названы пути импорта (`install_op_commands` — «функция модуля плагина»; `OpSource`, `OpSpec`, `command_table`, каталоги — `Services.device_hub.spi`). Tester не читает `plugin.py` / `spi.py`. Дать строки `from … import …` литералом.
- Файлы tester входят в сторож: `_scanned_test_files` берёт все `*.py` двух каталогов (`_SCANNED_FILES` 46 -> 49). Приватное имя драйвера (`_client`, `_ready`, `_epoch`…) в них даёт `seen != _SEAMS`. А15 велит повторить барьер из `test_c29_disconnect_acceptance.py` — проверить, что он без приватных имён; сказать tester про сторож.
- А3: 34 описания — только «непусто»; «дословно» не защищено. Дать 34 литерала (первые строки докстрингов `cmd_*` на базе; лид выписывает из `git show 9b6645546:Plugins/hub/device_hub/plugin.py`). Действует при c2.
- А8 запрещает `def cmd_robot_*`, но пропускает 55 присваиваний `cmd_robot_stop = _op(…)` в теле класса. Запретить также `Assign` / `AnnAssign` с целью `cmd_robot_*`, `cmd_vfd_*` и ключи `"robot_*"`, `"vfd_*"` в литерале `commands`.

**14. [quality] D6 не следует из цели и долгов.** D6 нет в таблице долгов (1–4) и нет поведенческого красного (п.12). «Прочее -> None» не определено для обёртки драйвера: сегодня `_store_refusal` на любое иное исключение отвечает `str(exc)` (`args.py:145`) — обёртка обязана это сохранить. Вынести D6 в отдельный коммит или убрать из SPI.

**15. [quality] D4: правило объединения неполное.** «Первое вхождение побеждает (v2 -> v1 -> данные)» сверяет `needs_link` / `threaded` (после п.6 — `executor`, `immediate`), но не `description` и `args_schema`: у `abort`, `enqueue_job`, `get_telemetry`, `return_job` расхождение молча решается порядком. Требовать равенства -> `ValueError`. `needs_link` у `ROBOT_DATA_OPS` не задан (при `route == "data"` игнорируется): задать `False` литералом. Порядок ключей `commands` меняется (`command_catalog.py:321` отдаёт `list(pc.commands.keys())`) — безвредно.

**16. [quality] REDS: названо неверно или пропущено.**
- `test_no_private_driver_state.py::test_hub_code_has_no_driver_private_access` — такого теста нет (в файле четыре); это новая часть (в), красный после написания.
- `test_duck_hooks_count` (счёт строк) обходится переименованием переменной; вне шаблона остались `vfd_driver.py:332, 334` (`getattr(carrier, "mode"/"busy")`) и `transports.py:125, 133`. Заменить AST-проверкой «нет `getattr`/`hasattr` по значению `get_driver(...)`, кроме объявленного места».
- Верно: `test_spi_contract::*`; `test_base_defaults` (в `base.py:33-131` нет `disconnect_pending` / `transport`); `test_plugin_source_has_no_handwritten_op_commands` (18 + 21 + 11 + 5 = 55); `test_device_read_without_transport` (у `VfdDriver` только `_vfd_client`).
- Не названы среди затронутых: `test_robot_v2_commands.py` (п.3), `backend_ctl/tests/test_capabilities.py::test_dump_matches_committed` (п.2), снимки топологии (п.6).

**17. [quality] Размер: `SPI.md` 33 164 байта** (32 КБ = 32 768: превышение 396; при КБ = 1000 — 1 164). Вынести: «Долги из плана» (2 610 байт) -> `SPI.debts.md`; D7 и «Правки framework» (2 541 байт) -> `SPI.framework.md` (там то же). Итого −4,7 КБ -> ≈ 28,4 КБ.

**18. [quality] Коммиты.** SPI.a (оракул) первым и отдельно — верно. SPI.b разделить: b1 — `spi.py`, умолчания Base, строки `OP_SPECS`, `test_spi_contract.py` (поведение 0); b2 — D3 с видимыми изменениями (В2, В4, строгие чтения) в теме; D6 отдельно или вне SPI. SPI.c: c1 перенос, c2 описания + CAPABILITIES (п.2). SPI.d: фреймворк (хук + тест) -> плагин -> прототип + снимки. SPI.f (швы) и SPI.g (дроссель) — отдельные запуски.

**19. [quality] Контракт модуля.** `spi.py` — lite, верно. `module-contract` требует `tests/contract/`; в репозитории таких каталогов нет — плоский `test_spi_contract.py` допустим, отступление записать. `Stability: lite` и `Pre:` / `Post:` для `install_op_commands`, `command_table` не названы.

## Вопрос лида: остаётся ли `getattr(driver, "request_stop")` (`manager.py:131`) костылём

Да, как написано — остаётся, и это единственное опасное место. Имя проверяется строкой: переименование или опечатка в драйвере даёт `getattr -> None`, цель стопа отфильтрована, ошибки нет — отказ без звука на пути стопа (ADR-DH-009). `@runtime_checkable StopAwareDriver` с `isinstance` этого не лечит: проверка тоже по именам, переименование так же молча даёт `False`. Кроме того (Т1) `MagicMock` без `spec` не проходит `isinstance` в 3.12, а сегодня проходит `callable(getattr(...))`.

Рекомендую явную способность в дескрипторе вида:
- `stop_aware: bool` в `DeviceDriver` (умолчание `False` в Base); `RobotDriverV2.stop_aware = True`. `StopAwareDriver` (Protocol с `request_stop`) остаётся типом вызова после проверки флага.
- `request_stop_all` отбирает цели по `drv.stop_aware` (истинность, не `is True`: `MagicMock` ведёт себя, как сегодня) внутри `try` на драйвер; флаг без метода -> `AttributeError` в `_stop_one` -> `logger.exception` (громко).
- Тест соответствия: для каждого класса драйвера по умолчанию `stop_aware == hasattr(cls, "request_stop")`; инъекция «переименовать метод» краснит его.
- `request_stop` по-прежнему без умолчания в Base (поток `stop-<id>-<k>` только у робота; А16 и свойство 18 остаются).
- Простые фейки (`Boom`, `Fine`, `test_robot_v2_scope.py:515-524`) идут через `request_stop_all`: отбор внутри `try` обязателен (иначе один фейк роняет стоп всем; принцип 5). Выборкой: `test_t53r2_stop_hazards.py` работает с настоящими драйверами; тестов, ждущих `request_stop` у `MagicMock`, не нашёл (проверка не исчерпывающая).
Если лид оставит `getattr`: ввести тест «`request_stop_all` зовёт `request_stop` у каждого класса, где он определён» с инъекцией переименования и записать место как объявленное исключение со ссылкой на ADR.

## Пункты, где ответы лида меняют дизайн брифа

В1 и В5 -> п.6 (`executor` + `immediate` вместо `threaded`; FILES SPI.d со снимками топологии; п.1 обязателен). В2 -> п.8. В3 -> п.9 (SPI.f). В4 -> п.7 (`set_degraded() -> bool`, А20). В6 -> п.10 (SPI.g). «Без костылей» -> раздел про `request_stop` (флаг способности). Прочие пункты (1–5, 11–19) от ответов не зависят.

Какой ответ ломал бы дизайн: В1 «все операции на исполнителе» — стоп встанет в очередь за медленной операцией того же `device_id` (спасает только `immediate` с `ValueError`). В4 «нет» — остаётся `hasattr`, тест «остался один» не пройдёт.

## Что оставил открытым / ненадёжным

Раздел перенесён дословно в `SPI.stage0-r1-tail.md` (лимит размера файла 32 КБ).
