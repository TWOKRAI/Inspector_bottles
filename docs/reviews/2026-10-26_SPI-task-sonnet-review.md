# Ревью задачи «SPI хаба» (полоса Р2), стадия 5 — reviewer (Sonnet)

Дерево `.claude/worktrees/robot-v2-spi`, ветка `feat/robot-v2-spi`, HEAD `af90240a9`, дифф `main...HEAD` (20 коммитов, 65 файлов).
Файлы дерева я не менял; единственный записанный файл — этот отчёт. Пробы и инъекции — в памяти процесса, скрипты в каталоге
scratchpad (`rev_spi/`), к коду дерева не прикасались. Память: `search.py device_hub SPI executor stop` — 8 уроков, к SPI не относятся.

## Вердикт: CHANGES REQUESTED (итерация 1 из 2)

Код по пунктам 1–6 брифа держится: воспроизведения зелёные, путь стопа и отключения не сдвинут. Причина вердикта — один
незакрытый пункт приёмки c2 (CAPABILITIES) и один тихий отказ на пути стопа для будущего вида драйвера. Остальное — мелочь.

## Список замечаний (серьёзность по шкале роли)

1. **[spec, blocker, процессный] `docs/contracts/CAPABILITIES.yaml` / `.md` не перегенерированы.**
   Вход: в закоммиченном `CAPABILITIES.yaml` у 34 команд пустое поле `description` (например строки 1659–1666: `robot_draw_set_travel`, `robot_draw_square`, `robot_enqueue_job`);
   после SPI.c2 `DeviceHubPlugin` отдаёт непустые описания, значит `backend_ctl/tests/test_capabilities.py::test_dump_matches_committed`
   (marker `harness_smoke`, «CI-gate: дрейф = красный») красный. Подтверждено чтением файла, теста и `_command_dump`;
   сам тест я не гонял (headless-бэкенд, окно `heavy`). Автор признаёт: сообщение коммита a368ea393 и `STATUS.md`, раздел «Открыто».
   Исправить: `python -m backend_ctl.dump_capabilities` в окне `heavy`, оба файла — в коммит c2, до слияния. Без окна исполнитель этого сделать не мог — решение лида по окну.

2. **[architecture, major] Стоп процесса молча не уходит драйверу, у которого есть `request_stop`, но нет `stop_aware = True`.**
   Вход (проба `test_p3`): подкласс `FakeDriver` с методом `request_stop(self, deadline=None)` без флага, `DeviceManager.request_stop_all()` →
   наблюдение `stop delivered: []` (до SPI такой драйвер получал стоп по `getattr`). Обратное направление (флаг без метода) — громкое:
   проба `test_p2` — сосед получил стоп, `AttributeError` ушёл в лог. Охрана `cls.stop_aware == hasattr(cls, "request_stop")`
   (`test_spi_acceptance.py:286`, `test_spi_contract.py:329`) перебирает ровно 5 вписанных классов, а ADR-DH-012 «Последствия» сам называет
   путь роста «новый вид = класс драйвера + `register_driver_factory`» — шестой драйвер охраной не покрыт, а это путь остановки (ADR-DH-009..011).
   Решение «флаг способности» принято лидом; замечание только про тихое направление.
   Исправить (любое одно): (а) `BaseDeviceDriver.__init_subclass__`: `hasattr(cls, "request_stop") != cls.stop_aware` → `TypeError` при создании класса;
   (б) тест на замыкание `BaseDeviceDriver.__subclasses__()` вместо списка из 5 имён; (в) отбор в `request_stop_all` пишет WARNING, если у драйвера без флага есть `request_stop`.

3. **[quality, minor] ADR-DH-012, «Последствия» (строка 71), и `SPI.md`, «Требует слова владельца», говорят, что `args` попадут в CAPABILITIES — по коду не попадут.**
   `backend_ctl/dump_capabilities.py:_command_dump` пишет только `name / description / tags / params_schema` (сам `SPI.framework.md`, N7, это знает).
   `metadata["args"]` (из `OpSpec.args_schema`) в промышленном коде никто не читает (`git grep` по `args_schema` и `metadata["args"]` — только запись
   `plugin.py:254`); `OpSpec.immediate` тоже ничего не меняет сверх запрета `executor + immediate` в `__post_init__`. Это то, что базовый чек-лист
   называет «настройка введена, но не читается»: данные описательные, потребителя пока нет.
   Исправить: поправить строку ADR и брифа (args — только в `get_command_info` и introspect; что introspect их отдаёт, я не проверял);
   решить, нужен ли потребитель (например, `params_schema`), или оставить заделкой и записать это в STATUS.

4. **[quality, minor] `DeviceManager.initialize()` оставляет частично загруженный реестр при неизвестном виде.**
   Вход (проба `test_p4`): файл реестра из двух записей (`ok1` вид robot, `bad` вид camera) → `ValueError` (как и раньше), но `snapshot_registry()` даёт `[ok1]`,
   `is_initialized` = `False`. До SPI.c1b `store.load()` бросал до первого присваивания (всё или ничего). Исправить: сначала проверить все записи
   (`_check_kind`), потом присвоить. Побочно: порядок «фабрика регистрируется ДО `initialize()`» для нового вида в `devices.yaml` нигде не записан —
   одна строка в докстринг `register_driver_factory` или в ADR.

5. **[tests, minor] SPI.g: критерий «интервалы и начальные метки — литералы в тесте, по классу» выполнен наполовину.**
   Интервалы — литералы по классам (`test_spi_contract.py:517-520`). Начальные метки — нет. Инъекции (в памяти, после `__init__`):
   ПЧ `-inf → 0.0` → красный один `test_vfd_driver.py::TestVfdDriverDesiredReconnect::test_tick_reconnects_when_desired_true` (случайный страж);
   v1 `0.0 → -inf` → красный один `test_robot_driver.py::TestRobotDriverReconnect::test_disconnected_reconnect_throttle`;
   **v2 `0.0 → -inf` → 178 passed, красных 0** (наборы t53g, t53h, ops, driver_v2, reconnect_exhausted, spi_contract). В проде часы — `monotonic`, практического
   вреда метка v2 не даёт, но критерий SPI.seams не закрыт. Исправить: по одному тесту на класс с литералом метки (через публичный `tick` и управляемые часы: при часах = 0.0
   первая попытка у v1 и v2 — отказ затвора, у ПЧ — проходит).

6. **[quality, minor] Порядок команд в `DeviceHubPlugin.commands` изменился (вопрос 7а лида).**
   Было: `device_*`, `robot_*`, рисование, `vfd_*`, `hik_*`. Стало (проба `test_p6`): 11 `device_*`, 6 `hik_*`, затем 55 сгенерированных в порядке `command_table` (первым идёт `robot_jog_hold` v2).
   `command_catalog.py:113` копирует словарь как есть и порядок не использует; `CommandCatalog.list_commands` в промышленном коде не вызывается; дамп CAPABILITIES сортирован (`dump_capabilities.py:85`).
   **Но порядок виден оператору:** `multiprocess_prototype/frontend/widgets/tabs/services/control_panel/catalog.py:133` отдаёт `list(cmds.keys())` в выпадающий список пикера
   (`picker.py:153`, `_cmd_combo`) без сортировки — команды хаба там теперь в другом порядке. Имена не менялись, функции не теряются.
   Исправить (по желанию, прототип — расходный слой): `sorted(...)` в `catalog.py:133` либо принять и записать в STATUS.

7. **[architecture, minor, принято лидом] `driver_options` действуют на весь `kind`.** Опции вида `robot` получает и v1, поэтому `client_factory` даёт `TypeError` на v1
   (записано в ADR, в `set_driver_options`, в STATUS). Прод передаёт `None`, вреда нет. Совет: ключ `(kind, protocol)` или отдельный ключ для v2, чтобы ограничение
   не жило в докстринге. Не блокирует.

8. **[quality, пометка]** Критерий `SPI.seams.md` «`git grep` по `\._client\b` → ровно 16 строк» буквально не выполняется: 20 строк. Лишние 4 — не код:
   `conftest.py:22` (докстринг `ClientRecorder`) и три строки текста самого сторожа `test_no_private_driver_state.py:297-301`. Формула ADR-DH-012 п.6 «вне v1/ПЧ/сторожа» верна. Правки не нужны.

## Воспроизведения по пунктам брифа

Команды: через гейт `machine_gate.sh light inspector-bottles-00 …`, PYTHONPATH = корень дерева, PYTHONUTF8=1. Пропусков гейта (код 75) не было.

| № | Что | Результат |
|---|---|---|
| 1 | `Services/device_hub/tests/{test_spi_contract,test_spi_acceptance,test_no_private_driver_state,test_manager,test_entry}.py` | 233 passed |
| 1 | `Plugins/hub/device_hub/tests/{test_spi_commands_acceptance,test_op_commands,test_robot_v2_commands,test_robot_v2_commands_acceptance,test_t53r2_stop_hazards}.py` | 170 passed |
| 1, 6 | `test_c29_disconnect_acceptance`, `t53g_blind`, `t53g_windows`, `t53h_blind`, `test_robot_driver`, `test_vfd_driver`, `test_robot_v2_state_acceptance`, `ops_timing_acceptance` | 301 passed |
| 3 | framework: `test_plugin_command_options`, `test_plugin_command_options_acceptance`, `test_blueprint_executors`, `test_process_executors_acceptance` | 27 passed |
| 3 | другие плагины, зовущие `_auto_register_commands` (`capture/test_plugin`, `camera_service/test_commands`) + `backend/test_devices_executors`, `test_build_characterization` | 38 passed |
| 3 | `test_hot_rebuild_parity_acceptance`, `test_hot_rebuild_parity_hazards`, `test_hot_rebuild_provenance_acceptance` (снимок ключей слоя framework — ключи системы, не процесса) | 24 passed |
| 7в | `sentrux check .` | `All rules pass` (41 правило) |

**1. Путь стопа и отключения.** Дифф `plugin.py` и `manager.py`: порядок фаз и замков не менялся (`shutdown` не тронут; в `request_stop_all` изменён только отбор целей; `_stop_one` прежний).
Проба `test_p1` (моя, scratchpad): `request_disconnect` бросает **и** `health.report_error` бросает `OSError` → ответ `{"status": "ok", "conn": "disconnecting"}`; внутри
`request_disconnect` `_workers_lock.locked() == True`; внутри `report_error` — `False`, `qsize() == 0` (put ещё не было: отчёт между выходом из замка и put, как в D3);
после `drain` статус `disconnected`, драйвер отключён — put выполняется всегда (`finally`). Проба `test_p2`: драйвер с `stop_aware=True` без `request_stop` не мешает соседу (сосед получил стоп; `AttributeError` — в лог).
Счёт `getattr|hasattr(driver|drv|dep_driver, "…")` в `manager.py` и `plugin.py`: `git grep` → 0 строк (rc=1). Замечание 2 — обратное направление.

**2. Исполнитель.** Проба `test_p5` (настоящий `CommandManager` + `ExecutorManager` с `device_io`, после `_do_start`): `metadata.executor` есть **ровно** у 10 команд данных (список сравнён литералом).
У `robot_point_save` после старта: description, args = point и base_rev, executor = device_io, key_from = device_id — не стёрты. У 10 операций `immediate` (`robot_stop`, `robot_abort`, `robot_jog_hold`, `robot_jog_release`, `robot_program_abort`,
`robot_jog_abort`, `robot_draw_abort`, `robot_clear_queue`, `robot_set_servo`, `vfd_stop`) ключа `executor` нет. А17, А18, А22, А23 (путь роутера, один `reply`, имя потока не равно роутерному, `key_missing`, запасной путь)
зелёные в прогоне 170. `update_command_metadata` и `overwrite_command` в промышленном коде вызовов не имеют (`git grep`) — стереть `executor` после регистрации некому.

**3. Framework.** Плагин без хука: `register_command(cmd_name, method)` — два позиционных, без именованных (`base.py:1680-1683`; тест `test_without_hook_exactly_two_positional_args_literal` зелёный);
имя `command_options` ни у одного другого плагина не занято (`git grep`). C-45: `set_config` и `cmd_set_config` в диффе — только контекстные строки. `blueprint.py`: ключ `executors` кладётся в `base_kwargs` только при непустом значении
(`test_no_executors_key_config_as_before`: ключа нет и при `executors: {}`); `registry.py` не снимает `commands` при декорировании — мутация класса после `@register_plugin` видна каталогу.

**4. c1b.** Пути записи в `_entries`: `initialize()` (через `store.load`, `_check_kind` в цикле) и `upsert` (`_check_kind` после `from_dict`, на обеих ветках — новая запись и merge; зовётся из `start()`, `cmd_device_upsert`,
`cmd_device_upsert_many`, `cmd_device_sync_set`). Промышленных мест вне менеджера, создающих `DeviceEntry` хаба, нет (`Services/code_reader/sdk/api.py:153` и `hikvision_camera/tools` — другие классы).
Мимо `_check_kind` проходят только прямой конструктор `DeviceEntry(kind="camera")` и `RegistryStore.load()` (проба `test_p4`: отдают запись с `camera`) — потребитель один, менеджер. `VALID_KINDS` остался замороженным множеством без читателей
(комментарий в `entry.py`; «FREEZE не KILL» соблюдено). Замечание 4 — частичная загрузка.

**5. f.** `ClientRecorder` (`conftest.py`) строит настоящий `RobotClientV2(transport, cfg)` — вызов совпадает с боевой сборкой `driver.py:344`. Независимый AST-дифф (`rev_spi/astdiff_f.py`: множества `ast.dump(Assert)`, константы внутри них, число `test_*`)
по коммитам f1–f2b (`3df2ed656^..41b5b7009`): SAME у `test_robot_v2_scope`, `test_t53f_m6_guard`, `test_t53r2_stop_hazards` (97 до и после), `test_c29_disconnect_acceptance` (107), `test_robot_driver_v2` (136), `test_robot_v2_ops` (134),
`test_robot_v2_state_acceptance`, `t53g_blind`, `t53g_windows`, `t53h_blind`, `ops_timing`, `lease_log`, `no_private_driver_state`; DIFF — только `conftest.py` (+1 assert нового помощника) и `test_manager.py` (+4 assert, +2 теста `TestDriverOptions`).
Ослабленных assert нет. По всей ветке существующие файлы с дрейфом: 6, везде число assert и тестов растёт (43→47, 16→17, 30→41, 10→15, 273→282). Замена `test_invalid_kind` на `test_kind_is_not_checked_by_entry` в `test_entry.py` осознанная:
проверку вида принял `TestKindByFactory`.

**6. g.** Интервалы: база 2.0, v1 2.0 (`robot_driver.py:30`), v2 2.0 (`texts.py:72`), ПЧ 3.0 (`vfd_driver.py:20`) — сохранены; начальная метка ПЧ `-inf` стоит после `super().__init__` (`vfd_driver.py:66`) — база её не перетирает; v1 и v2 — `0.0` из базы, как было.
Часы читаются один раз на вызов (`_reconnect_due`), как в трёх прежних копиях; тела `_attempt_reconnect` и `_ensure_connected` (в т. ч. `_param_lock` v2) не тронуты. Охрана начальных меток — замечание 5.

**7а.** Замечание 6. **7б.** `self._reg.last_error = str(exc)` (`plugin.py:421`) — **не дефект.** Это чистое присваивание, а не чтение-изменение-запись; `_counters_lock` нужен только для `commands_ok` и `commands_err` (`+= 1`).
Но «листовость» регистра я проверил пробой, не доводом: `DeviceHubRegisters` — `SchemaBase` с `validate_assignment=True` (`schema_base.py:58`), pydantic-core при присвоении подменяет `__dict__`, поэтому проверял потерянное обновление между полями.
`race_reg.py`: поток А — `commands_ok += 1` под замком ×20000, поток Б — `devices_connected = …; last_error = …` **без замка**, `sys.setswitchinterval(1e-6)`, 5 прогонов → `commands_ok == 20000` каждый раз.
Контроль чувствительности `race_ctl.py` (два писателя `+= 1` без замка) → 35623–36233 из 40000, то есть проба гонку ловит. Побочные записи супервизора счётчики не затирают. Остаётся «последняя запись побеждает» между супервизором и `_safe_call` по одному `last_error` —
как и до SPI (супервизор и поток роутера уже были двумя писателями).
**7в.** `Services/device_hub/spi.py` импортирует только `collections.abc`, `dataclasses`, `typing`; `git grep` по `Services/device_hub` (без тестов) на `Plugins` и `multiprocess_prototype` → 0; изменённые файлы framework не импортируют Services, Plugins, prototype;
`sentrux check .` — все правила проходят.

## Что оставил открытым / ненадёжным

- **Не гонялось:** `test_dump_matches_committed` и любой `harness_smoke` (нужен headless-бэкенд, окно `heavy`) — вывод по замечанию 1 сделан чтением закоммиченного файла и кода дампа, не прогоном. Стенд и живой процесс не запускались. Весь набор `process_module/tests` и весь `Plugins/` — нет, только радиус:
  плагины, зовущие `_auto_register_commands` (2 набора), хук, чертёж, hot-rebuild.
- **Матрицу из 34 инъекций лида я не повторял.** Свои инъекции — три (метка затвора ПЧ, v1, v2), в памяти; прогнозы лида не сверял.
- **Таблица `immediate` (SPI.framework.md) не перечитана по телам драйверов:** проверил, что множество совпадает с А12 и что у этих команд нет `executor`; обоснование каждой строки (`set_servo` v1 — решение лида, пометка владельцу) оставил лиду.
- **`args_schema` и код драйверов:** ключи 38 из 55 команд с телами операций не сверял; поле описательное и тестами соответствия не охвачено (дрейф тихий).
- **Не проверено:** (а) отдаёт ли `introspect.*` `metadata.args` наружу; (б) судьба потоков исполнителя `device_io` при остановке плагина (операция данных в полёте, когда плагин уходит в `shutdown`) — тесты цепочки покрывают живую работу, не остановку;
  (в) повторный `_auto_register_commands` на том же `CommandManager` (хук пишет ERROR «уже зарегистрирована» вместо прежнего WARNING «Failed to register», итог «не регистрировать» тот же; в проде повтора не видел, вызовов не искал);
  (г) значения `device_io` 4/64 не измерены (так записано и в ADR).
- **Слабая проба 7б:** одна микро-нагрузка, одна версия pydantic дерева; «не дефект» держится на ней и на том, что запись `last_error` — присваивание; аудит `pydantic-core` не делал.
- **Доверие к автору:** тесты `test_spi_contract.py` и `test_op_commands.py` запускал (зелёные), тела не читал построчно — качество их проверок (кроме выборочных инъекций) не оценено.

---

# Круг 2 (последний) — правки р.1: коммиты c313a2c85, 1eb8fcdd8, 0ceb235eb; HEAD fe5014ee8

Проверял в дереве `robot-v2-spi-inj` (HEAD тот же, что у ветки; чисто). Файлы кода и тестов не менял. П.1 (CAPABILITIES) по просьбе лида в этом круге не проверялся.

## Вердикт круга 2: APPROVED

П.2, п.4, п.5, п.3 закрыты по коду с воспроизведением; новых дефектов правки не внесли. Условие слияния, не относящееся к этому кругу: п.1 (регенерация `docs/contracts/CAPABILITIES.yaml` / `.md` в окне heavy, лид) остаётся открытым — без неё `test_dump_matches_committed` красный.

## Что проверено

- **П.2 закрыт.** `BaseDeviceDriver.__init_subclass__` (`base.py:107-119`). Моя прежняя проба (подкласс `FakeDriver` с `request_stop` без флага) теперь падает при определении класса: `TypeError: NoFlag: stop_aware=False, а метод request_stop есть — задай stop_aware = True ровно драйверу с request_stop` (текст без входных значений, только имя класса). Флаг без метода — `TypeError`. Миксин с `request_stop` без флага (`class D(Mix, FakeDriver)`) — `TypeError`; с флагом — определяется. Драйвер с обоими признаками получает стоп (`request_stop_all` → `["b"]`).
  Вред для существующего кода: `git grep` по всем подклассам `BaseDeviceDriver` и по подклассам конкретных драйверов (`RobotDriver`, `RobotDriverV2`, `VfdDriver`, `HikvisionDriver`, `GenericModbusDriver`, `_RobotDriverCore`, `FakeDriver`) — 17 определений в `Services/device_hub/**` и `Plugins/hub/device_hub/tests`; других подклассов в Plugins/** и Services/** нет (`Services/auth`, `Services/sql` и `Services/modbus/sdk/client.py` ссылаются на имя строкой или в докстринге; `backend_ctl` `FakeDriver` — другой класс). Все определения проходят: `RobotDriverV2` (флаг в самом классе, метод из `StopMixin`) и промежуточный `_RobotDriverCore` (ни того, ни другого) — оба в паре.
  Зелёные прогоны (гейт light, поимённо): 375 passed (`test_spi_contract`, `test_spi_acceptance`, `test_manager`, `test_manager_template_1_2b_3`, `test_reconnect_exhausted_notice`, `test_no_private_driver_state`, `test_vfd_driver`, `test_robot_driver`, `test_robot_driver_v2`, `test_c29_disconnect_acceptance`, `test_entry`); 171 passed (`Plugins/hub/device_hub/tests/{test_spi_commands_acceptance,test_op_commands,test_t53r2_stop_hazards,test_robot_v2_commands}.py` + `Services/auth` и `Services/sql` `test_manager_template_1_2b_3.py`).
  Зубы новых тестов (инъекция в памяти): `__init_subclass__` заменён пустым → красные ровно `test_class_with_request_stop_without_stop_aware_raises` и `test_class_with_stop_aware_without_request_stop_raises` (2 failed, 43 passed).
- **П.4 закрыт.** `manager.py:112-120`: все записи проверяются, потом присваиваются. Проба: файл `[ok1 robot, bad camera]` → `ValueError`, `snapshot_registry() == []`, `is_initialized is False` (до правки было `[ok1]`); валидный файл из двух записей грузится целиком. Инъекция (старый цикл с перемежающимся присваиванием) → красный ровно `TestInitializeAllOrNothing::test_unknown_kind_in_file_loads_nothing` (1 failed, 32 passed). Строка про «фабрику ДО `initialize()`» — в докстринге `register_driver_factory` и в ADR.
- **П.5 закрыт.** `test_spi_contract.py::test_reconnect_initial_mark_per_class_is_literal` (часы 0.0: v1 и v2 — отказ затвора, ПЧ — проходит). Инъекции в отдельных процессах на файле `test_spi_contract.py`: v2 `0.0 → -inf` теперь **красный** (было 178 passed); v1 `0.0 → -inf` красный; ПЧ `-inf → 0.0` красный; в каждом случае 1 failed, 44 passed, красный — именно этот тест.
- **П.3 закрыт.** ADR-DH-012 строка 71 и `SPI.md` строка 282: `args` в дамп не попадают, только в `metadata` / `get_command_info`; в ADR добавлен раздел «Открыто»: `immediate` без рантайм-потребителя, `args` в `metadata` никто в проде не читает; п.6 (порядок пульта) и п.7 (`driver_options`) записаны как принятые. Осталось в `SPI.md` (строки 188, 244, 303) «`args` + CAPABILITIES» — в таблице ответа на стадию 0 и в списке шагов, то есть история и план, не утверждение результата; строка 303 — сам открытый вопрос. Не мешает.

## Что оставил открытым / ненадёжным (круг 2)

- **П.1 не проверялся** (по просьбе лида): регенерация CAPABILITIES до слияния; `test_dump_matches_committed` по-прежнему красный, пока её нет; heavy-прогон не делал.
- **Остаточный путь мимо охраны класса:** метод `request_stop`, повешенный на ЭКЗЕМПЛЯР (не в классе), `__init_subclass__` не видит, и менеджер стоп ему не шлёт (проба: `instance-level request_stop delivered: []`). В дереве так не делает никто (`git grep "\.request_stop = "` пуст вне тестов SPI), поэтому не замечание, а граница охраны; в ADR она не записана. Ещё граница: `bool(cls.stop_aware)` при `stop_aware` как `property` вернёт истину от самого объекта-свойства — в базе это атрибут класса (тест А21 краснеет на `@property`), но подкласс может нарушить.
- **Тест начальных меток — один тест на три класса:** первый упавший `assert` скрывает остальные; инъекции я гонял по классам раздельно, и каждая красная. Раздельные тесты дали бы точнее диагностику; не блокирует.
- **Не гонялось:** весь набор `Services/device_hub/tests` целиком (heavy), `Plugins/**` целиком, стенд; проверил поимённо радиус `__init_subclass__` (все подклассы базы, найденные `git grep`) и три затронутые правкой области. Динамически созданные классы (`type(...)`) — `git grep` по `type(.*BaseDeviceDriver` пуст.
- **Отчётный файл:** этот раздел дописан и в `robot-v2-spi-inj`, и в `robot-v2-spi`; не закоммичен (по просьбе лида).
