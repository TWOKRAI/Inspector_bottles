# Ревью стадии 5: feat/pult-belt-speed (c1f96f954 поверх d42f188ac)

Вердикт: CHANGES REQUESTED (итерация 1 из 2).
Железо не трогал: все прогоны на фейках (StubTransport, FakeRobotTransport на RobotSimCore), COM/TCP не открывались.
Worktree lane-g-belt чист (git status --short = 0 строк после всех прогонов). Мутанты в копии в scratchpad.

## Окружение и базовый прогон
- Services.vfd_comm.__file__ лежит в worktree lane-g-belt (проверено).
- pytest Services/vfd_comm/tests через machine_gate medium: 38 passed (18 test_client + 20 test_protocol_parity). Код 75 не возникал.
- memory hits: search.py vfd run frequency last -> релевантных vfd уроков нет (хиты про qex, стенд, плагины).

## Находки

1. [major, tests] Рецепты (строка belt_freq) -> пины и golden не обновлены.
   Вход: оба рецепта получили 5-й action-контрол. Выход (статический расчёт scratchpad/recipe_static_check.py, не pytest): pult controls len=11, actions=5 в обоих.
   - multiprocess_prototype/frontend/widgets/tabs/services/control_panel/tests/test_recipe_1_0_belt_monitors.py:166-170 (test_sim_recipe_has_four_actions_and_five_monitors ждёт ровно 4 action и len(raw)==10) расходится (5 и 11).
   - multiprocess_prototype/backend/tests/snapshots/hikvision_letter_robot.build.json: два блока controls (строки ~340 и ~4190), в каждом len=10, belt_freq нет. Расходятся test_build_characterization.py::test_build_matches_snapshot[hikvision_letter_robot] и test_operator_word_in_recipe_does_not_change_snapshot.
   - Прецедент: коммит f1865200f (controls 8 -> 10) обновлял golden, test_recipe_1_0_belt_monitors, test_letter_robot_sim_diff. Здесь ни одного из них нет в диффе.
   - Слова коммита «контрактов рецептов зелёные» этому противоречат (либо модули не гонялись).
   - Сами pytest этих модулей не запускал (бриф: только vfd_comm). Лиду прогнать: test_build_characterization.py -k hikvision, control_panel/tests/test_recipe_1_0*.py, recipes/tests.
   Исправить: пересобрать golden (UPDATE_BUILD_SNAPSHOTS=1, дифф только блок pult, дважды), поправить пины (5 action, 11 контролов), test_letter_robot_sim_diff если пинит число.

2. [major, spec] Services/device_hub/drivers/vfd_driver.py:87-124 (connect/disconnect/set_degraded) + client.py:56 -> последняя частота теряется при переподключении.
   Вход: set_freq(31) -> stop -> disconnect()+connect() (или set_degraded()+connect(): отпал робот-носитель), затем run({}).
   Выход (probe_driver.py D1/D3/D4): на проводе cmd_freq=1000 (10 Гц), не 3100. VfdDriver при disconnect()/set_degraded() ставит _vfd_client=None, connect() создаёт новый VfdClient с _last_freq=None.
   Это ровно баг, который чинит коммит («Лента пуск» затирает скорость оператора), но после любого реконнекта. В сообщении коммита заявлено «до рестарта процесса devices», это неточно.
   Исправить: держать последнюю частоту в драйвере (переживает пересоздание клиента) и передавать клиенту, либо не пересоздавать клиента; тест «run после реконнекта»; либо явно записать в DECISIONS/README, что память живёт до реконнекта.

3. [major, quality] Services/vfd_comm/core/client.py:77 (is not None) -> 0 Гц запоминается и подменяет частоту пуска.
   Вход: set_freq(0.0) (freq_min_hz=0.0 допускает) или run(0.0), затем run() без частоты.
   Выход (probe_client.py P3a/P3b): уходит cmd_freq=0, cmd_run=1; драйвер отвечает status ok. «Лента пуск» молча не едет.
   Реальный источник: Plugins/calibration/camera_robot/plugin.py:413 _do_belt_run берёт args.get("freq", args.get("freq_hz", 0.0)) и всегда передаёт частоту явно, то есть вызов без частоты там даёт run(0.0) и запоминает 0.
   Исправить: не запоминать значения <= 0 (или считать их «нет последней»), тест на ноль.

4. [major, safety, решение владельца] client.py:77-89 -> старт на последней без верхней границы.
   Вход: любой вызывающий (калибровка, backend_ctl, другой процесс через хаб) делает run(50.0) или set_freq(50.0); затем оператор жмёт «Лента пуск» (контрол belt_freq в пульте показывает свой value 10.0, не последнюю).
   Выход: лента стартует на 50 Гц, в 5 раз выше прежней уставки default_freq_hz=10, при том что в пульте написано 10. _validate_freq проверяет только [freq_min, freq_max]. После stop()/reset_fault() память не сбрасывается (P8: run(30), stop, reset_fault, run() -> 3000).
   Выбор осознанный, запуск на реальном ПЧ коммит оставил владельцу; фиксирую как риск. Нужен сброс памяти по reset_fault/смене рецепта, либо порог старта из памяти, либо запись решения владельца в DECISIONS.

5. [minor, tests] Services/vfd_comm/tests/test_client.py:94-115 -> выжившие мутанты (см. таблицу). Тесты не ловят
   (a) запоминание до/без проверки результата записи (M5, M6): StubTransport.transaction всегда True, нет теста ни с False, ни с исключением;
   (b) or вместо is not None (M7): нет теста на 0;
   (c) нет теста «новый клиент» и «реконнект драйвера» (находка 2).
   Исправить: StubTransport с режимами False/raise; тесты «неудачная запись не меняет последнюю» (литерал 2000), «ноль», «свежий клиент -> 1000».
   Поведение сейчас корректно (P4a/P4b: last остаётся 20.0; реальные транспорты бросают ModbusDriverError до присваивания), но не закреплено тестом.

6. [minor, concurrency] client.py:79-97 -> _last_freq без блокировки, запись и присваивание не атомарны.
   Вход: T1 set_freq(20) вернулся с транспорта, но не успел присвоить; T2 run(30) целиком выполнился.
   Выход (probe_client.py P10, детерминированно через шлюз в стабе): на проводе 3000 (последняя команда), _last_freq=20.0, следующий run() стартует на 20 Гц.
   Окно узкое: транзакции сериализует замок транспорта; VFD-операции не идут через executor device_io (spi.py: executor только у ROBOT_DATA_OPS). Однопоточность диспетчера команд devices не доказал.
   Исправить: RLock в VfdClient вокруг «записать + запомнить» (или документ «один вызывающий»), hazard-тест с join-дедлайном.

7. [minor, quality] Документация не обновлена: Services/vfd_comm/README.md (пример vfd.run(50.0), «Тесты 15» при 38), STATUS.md (дата 2026-06-11, «Тесты: 15»), DECISIONS.md (нет ADR про память частоты: per-клиент, в памяти процесса, не переживает реконнект), core/config.py:20-22 (docstring default_freq_hz «Частота по умолчанию для run() без аргумента в UI», теперь это только стартовая уставка до первой записи). Дифф не трогает ни одного .md.

8. [minor, quality] Services/device_hub/drivers/vfd_driver.py:214-219: _op_run возвращает freq_hz: None (запрошенное), а не применённую частоту (D2), по ответу команды не узнать, на какой скорости пошла лента. pre_existing: _op_run/_op_set_freq игнорируют bool-результат run()/set_freq() и отвечают ok.
   Исправить: отдавать применённую частоту (свойство клиента last_freq), учитывать False.

9. [nit] Рецепты: value: 10.0 совпадает с default_freq_hz=10.0, max: 50.0 с freq_max_hz=50.0 (params vfd_belt: строки 80-81 и 95-96) — совпадение литералов, не связь. Если params изменят, контрол допустит значение выше предела; драйвер откажет (VfdFrequencyError -> status error), не зажмёт, это безопасно.
   Виджет (frontend control_panel widget.py:314): number эмитит по editingFinished; в Qt оно срабатывает и на потере фокуса без правки, значит клик в поле и уход вызовут set_freq(10.0) на идущей ленте. По чтению кода, под Qt не гонял. Поле всегда стартует с 10.0 и не отражает последнюю частоту.

## Проверенное без замечаний
- Пункт 1: первый run() без последней -> cmd_freq=1000 (10 Гц) (P1). set_freq(31) -> run() -> 3100 (P2; на проводе фейка D1 3100). Ошибка записи: исключение и False оставляют last=20.0 (P4a, P4b). Два клиента на один ПЧ: A.set_freq(31), B.run() -> 1000 (P7): память per-клиент, не per-ПЧ (не регрессия, но не лечит).
- Пункт 2: nan, inf, -1.0, 50.01 дают VfdFrequencyError (P9). Единицы: Гц float, на проводе round(value*100) (Services/modbus/core/register_map.py:132), 31.0 -> 3100, усечения нет.
  belt_freq в рецепте: это id контрола ControlSpec (Services/control_panel/controls.py), не ключ рецепта; git grep -F belt_freq даёт только две строки yaml, потребителей по имени нет. ControlSpec не extra=forbid. parse_controls: raw 11 / parsed 11 в обоих рецептах; action_args(31) -> {device_id: vfd_belt, freq_hz: 31.0}; coerce зажимает в [1,50] (0 -> 1.0, 999 -> 50.0). Списки контролов sim и β идентичны. Без belt_freq в рецепте контрола нет, пуск идёт на last/default (совместимо). Форма совпадает с прецедентом phone_sketch.yaml act_robot_speed.
- Пункт 6: вызывающие VfdClient.run/set_freq: только VfdDriver (vfd_driver.py:214, 227) и тесты; camera_robot шлёт частоту явно через хаб vfd_run (явная частота приоритетна, контракт не сломан). Явный run(f) теперь тоже обновляет память (согласуется с докстрингом).
- Безопасность по пяти классам (десериализация, IPC, shared memory, инъекции, секреты): дифф их не касается; secrets_audit не гонял (изменены два yaml без секретов и клиентский код ПЧ).

## Таблица break-injection
Мутанты в копии: scratchpad/mut (vfd_comm из копии, остальное из worktree). Контроль M0: 18 passed. Предсказание записано в черновике ДО прогонов.

| # | Мутант | Предсказано (красных) | Получено | Совпало |
|---|--------|----------------------|----------|---------|
| M1 | run(): fallback только default_freq_hz | last_set_freq, last_run_freq, rejected_freq_does_not_replace_last (3) | те же 3 (3 failed, 15 passed) | да |
| M2 | set_freq() не запоминает | last_set_freq, rejected_freq_does_not_replace_last (2) | те же 2 (2 failed, 16 passed) | да |
| M3 | run() не запоминает | last_run_freq (1) | он же (1 failed, 17 passed) | да |
| M4 | set_freq() запоминает до валидации | rejected_freq_does_not_replace_last (1) | он же (1 failed, 17 passed) | да |
| M5 | запоминание до _write (run и set_freq) | 0 | 0 (18 passed) | да, выживший |
| M6 | убран if ok | 0 | 0 (18 passed) | да, выживший |
| M7 | or вместо is not None | 0 | 0 (18 passed) | да, выживший |

Вывод: гарантии «берёт последнюю», «run тоже запоминает», «отклонённая не затирает» держатся тестами; «неудачная запись не запоминается» и «0 не последняя» не защищены (находка 5).

## Что я оставил открытым / ненадёжным
- Pytest модулей рецептов и golden (находка 1) не запускал (ограничение брифа); красные имена получены чтением и данными. Лид прогоняет три модуля до слияния.
- P5 (частичная запись: freq записан, flag нет): на проводе остаётся cmd_freq=3000, клиент помнит 20.0. Подействует ли следующий пульс poll() (flag=1) на этот cmd_freq, зависит от Lua робота; на фейке не проверить. Гипотеза.
- Однопоточность диспетчера команд процесса devices (находка 6) не доказал: ROBOT_DATA_OPS идут в executor device_io, VFD_OPS нет.
- Поведение number-контрола под Qt (editingFinished на потере фокуса) не воспроизводил, только чтение widget.py:314.
- Перезапускается ли процесс devices при смене рецепта (устаревшая last после смены рецепта) не выяснил.
- FakeRobotTransport/RobotSimCore повторяют семантику Lua частично; на реальном ПЧ ничего не проверялось (запрещено). «Проверено на проводе (пуск на 3100)» из коммита — слова автора, не моя проверка.
- Мутанты прогнаны только на test_client.py (18); test_protocol_parity.py (20) мутантам не подвергал, только базовый прогон.
- qex не использовал (свежесть индекса не проверял), поиск через git grep по worktree. sentrux check не запускал: дифф не меняет импорты и слои.
- MEMORY LESSON не пишу. Кандидат лиду: «добавление контрола в рецепт = обновить golden сборки и пины числа контролов (прецедент f1865200f), иначе красный гейт».

## Артефакты (scratchpad)
recipe_static_check.py, probe_client.py, probe_driver.py, mutate2.py, mut/ (копия), pristine/client.py.

---

# РАУНД 2 (правки developer, не закоммичены в worktree; reviewer, итерация 2 из 2)

Вход: git diff sha256 = 4042b74cc5177042089817e10672651608930f2c82b93c05482912db3c6032f9, test_vfd_driver_reconnect.py sha256 = c31171f0b2cb80132a1f0b80f5361acf35655610f089afb7c31e80abb48e41f1 (должны совпасть в конце).

## Предсказание раунда 2 (записано ДО прогонов мутантов)
Мутанты в оверлее scratchpad (vfd_comm и device_hub из копии новых файлов). Набор: test_client.py (27) + test_vfd_driver_reconnect.py (6).
| # | Мутант | Предсказанный красный набор |
|---|--------|------------------------------|
| N1 | убран _freq_lock (nullcontext) | test_concurrent_set_freq_and_run_keep_last_in_wire_order (1); устойчивость проверить 20 прогонами |
| N2 | запоминание ДО _write (run и set_freq); бывший M5 | failed_write[false], failed_write[raise] (2) |
| N3 | убран `ok and` (if freq > 0); бывший M6 | failed_write[false] (1); [raise] зелёный: исключение вылетает до присваивания |
| N4 | `or` вместо `is not None` в fallback; бывший M7 | 0 в наборе; НЕ эквивалентен: VfdClient(stub, last_freq=0.0).run() даёт 0 против 1000 |
| N5 | убран `freq > 0` только в run() | zero_freq_is_not_remembered_by_run (1) |
| N6 | убран `freq > 0` только в set_freq() | zero_by_set_freq, zero_without_memory_falls_back_to_default (в test_client) + zero_is_not_carried_across_reconnect (в reconnect) = 3 |
| N7 | fallback без памяти (бывший M1) | test_client: last_set_freq, last_run_freq, rejected_freq, kwarg_seeds_run, zero_by_set_freq, zero_by_run, failed_write[false], failed_write[raise], concurrent = 9; reconnect: survive_disconnect, survive_set_degraded, two_reconnects, zero_not_carried, disconnect_without_client = 5; итого 14 |
| D1 | VfdDriver.disconnect не вызывает _remember_last_freq | reconnect: survive_disconnect, two_reconnects, zero_not_carried, disconnect_without_client (4) |
| D2 | VfdDriver.set_degraded не вызывает _remember_last_freq | reconnect: survive_set_degraded, two_reconnects (2) |
| D3 | connect() не передаёт last_freq клиенту | reconnect: survive_disconnect, survive_set_degraded, two_reconnects, zero_not_carried, disconnect_without_client (5) |
| D4 | _remember_last_freq без охраны is not None | 0 (ветка недостижима: клиент всегда засеян памятью драйвера; эквивалент/мёртвая охрана) |

## Раунд 2: вердикт APPROVED (замечания только minor/nit; находка 4 остаётся решением владельца)

Состояние дерева на выходе: git diff sha256 = 4042b74cc5177042089817e10672651608930f2c82b93c05482912db3c6032f9, test_vfd_driver_reconnect.py sha256 = c31171f0b2cb80132a1f0b80f5361acf35655610f089afb7c31e80abb48e41f1 (совпало со входом). Мутанты только в scratchpad/mut2, worktree не правил.

### Закрытие находок раунда 1 (воспроизведено прогоном)
- Н1 (golden и пины): ЗАКРЫТА. Скрипт golden_probe.py: actual-сборка hikvision_letter_robot == golden(HEAD c1f96f954) -> False (старый golden красный), == golden(worktree) -> True; блоки controls в сборке [11, 0, 11], belt_freq есть в обоих непустых. Дифф golden: только два блока belt_freq (16 строк каждый), ничего ослабленного.
  Пины test_recipe_1_0_belt_monitors.py: 4 -> 5 action, 10 -> 11 контролов, плюс _FREQ_ACTION с типом number и test_belt_freq_control_literals (оба рецепта, литералы 1.0/50.0/10.0). Проверку не ослабили: добавлена проверка типа (control_type) и литералов. test_pult_controls_identical_in_both_recipes держит равенство sim и β.
  Другие пины: git grep по test*.py/json: belt-контролы упоминаются в Plugins/calibration/camera_robot, Plugins/sim/*, Services/robot_comm/tests/test_sim_v2_cvt_wdg_vfd.py, calibration_presenter (это команды vfd_*, не списки контролов этих рецептов). Golden для letter_robot_sim нет (в snapshots только hikvision, phone_sketch, hot_rebuild_framework_keys.txt). Прогнано по файлам, все зелёные: test_recipe_1_0_belt_monitors 17, test_recipe_1_0 7, test_letter_robot_sim_diff 2, test_recipe_format_hook 26, test_build_characterization 4, test_recipes_join_contract 88, test_devices_executors 5. gate medium на трёх последних вернул 75 (STAND WINDOW), их прогнал как light (один pytest-процесс на файл).
- Н2 (реконнект): ЗАКРЫТА. test_vfd_driver_reconnect.py (6 тестов) зелёный; сценарии D3/D4 из раунда 1 (set_freq(31), stop, disconnect+connect / set_degraded+connect, run({})) теперь дают 3100. Реальные VfdDriver+VfdClient, наблюдаемый эффект — записанный cmd_freq.
- Н3 (ноль): ЗАКРЫТА. set_freq(0) и run(0) уходят на провод (cmd_freq=0), память не меняют; без памяти ноль её не создаёт.
- Н5 (тесты): ЗАКРЫТА. Выжившие M5/M6 стали красными (N2, N3 ниже).
- Н6 (замок): ЗАКРЫТА. Порядок захвата _freq_lock -> замок транспорта, обратного нет: _write замка клиента не берёт; poll/stop/reset_fault замок не берут; исключение из _validate_freq освобождает замок через with. Взаимоблокировки не вижу.
  Hazard-тест, 20 прогонов: с замком красных 0 из 20 без нагрузки (6,21 с суммарно, около 0,31 с на прогон из-за t2.join(0.3)) и 0 из 20 под 6 потоками нагрузки; без замка (N1) красных 20 из 20 в обоих режимах. Ложных красных нет. Слабость теоретическая: если T2 стартует позже 0,3 с, безлоковый мутант мог бы выжить.
- Н7 (документация): ЗАКРЫТА с одной неточностью (Р2-1). 47 тестов верно: test_client.py + test_protocol_parity.py = 47 passed (27 + 20). Docstring config.py, README, STATUS соответствуют поведению.

### Новые замечания раунда 2
Р2-1. [minor, quality] Services/vfd_comm/DECISIONS.md (ADR-VC-004, абзац про эквивалентный мутант) и client.py:49,57 (kwarg last_freq без нормализации).
   Вход: VfdClient(stub, last_freq=0.0).run(). Выход (stability.py): cmd_freq=0 на текущем коде, 1000 при мутанте с or вместо is not None. Значит мутант НЕ эквивалентен, а утверждение «_last_freq == 0 недостижим через публичный путь» ложно для публичного kwarg конструктора. Через драйвер недостижимо (драйвер хранит только client.last_freq: None либо больше 0). last_freq=-5, 500, nan падают лениво в run() с VfdFrequencyError (громко, безопасно); 0.0 молча даёт старт на 0 Гц.
   Исправить: в __init__ принимать last_freq только если он больше 0, иначе None, и тест «last_freq=0.0, run() даёт 1000»; тогда мутант и правда эквивалентен. Либо поправить текст ADR.
Р2-2. [minor, architecture] Services/vfd_comm/interfaces.py:11-39: VfdClientProtocol не объявляет last_freq, VfdDriver читает его через Any. Публичный контракт расширен (README), Protocol нет. Исправить: добавить свойство last_freq в Protocol (runtime_checkable не ломается).
Р2-3. [nit] vfd_driver.py:303-309: _remember_last_freq читает client.last_freq без замка клиента. Disconnect параллельно с идущим set_freq(40) на старом клиенте может запомнить 31 при уже записанных на провод 4000: потерянное обновление при реконнекте. По чтению кода, не воспроизводил, окно узкое. Охрана is not None фактически недостижима (D4 выжил: клиент всегда засеян памятью драйвера), это безвредная защитная ветка.
Р2-4. [nit] test_no_private_driver_state.py: добавление test_vfd_driver_reconnect.py в _OTHER_DRIVER_TESTS не требовалось: в файле нет ни одного обращения к приватным полям драйвера (точечный grep по приватным атрибутам пуст; файл работает только через call, connect, disconnect, set_degraded и StubTransport.holding), робота-драйвера v2 в нём нет вовсе. Без исключения сторож сканировал бы файл, и _SCANNED_FILES стал бы 74 (литерал 73 пришлось бы поднять). Решение лида допустимо и совпадает с прецедентом test_vfd_driver.py (VFD-драйвер тоже в исключениях). Цена: файл вне сторожа, будущая правка с обращением к приватному полю робота не поймается. Не блокер. Контрфакт «74» выведен по коду, не прогонялся.
Р2-5. [info, усиление находки 4] Память теперь переживает реконнект. Раньше реконнект случайно сбрасывал старт к default_freq_hz=10; теперь высокая частота, заданная любым вызывающим, живёт до рестарта процесса devices или manager.remove(dev_id). По коду DeviceManager: upsert существующего id (manager.py около строк 560-607) драйвер не пересоздаёт, remove (611-637) драйвер удаляет; recipe-apply плагина (plugin.py 1015-1062) удаляет только recipe-устройства, которых нет в новом списке. Значит при смене рецепта letter_robot_sim и hikvision_letter_robot (оба с vfd_belt) память переживает смену рецепта: при меньшем freq_max_hz старая память выше предела даёт громкий VfdFrequencyError (run не стартует), при меньшем default_freq_hz старт идёт на старой частоте. По чтению кода, через DeviceManager не воспроизводил. ADR-VC-004 держит открытым «сброс после stop/reset_fault» и «верхнюю границу», но не «смену рецепта»: дописать строку, решение оставить владельцу вместе с находкой 4.
Н8 (_op_run отдаёт freq_hz: None) и Н9 (editingFinished, литералы): без изменений, правки их не ухудшили. Свойство last_freq теперь позволяет починить Н8 одной строкой.

### Таблица break-injection раунда 2 (набор test_client.py 27 + test_vfd_driver_reconnect.py 6 = 33; контроль N0: 33 passed)
| # | Мутант | Предсказано | Получено | Совпало |
|---|--------|-------------|----------|---------|
| N1 | убран _freq_lock | concurrent (1) | concurrent (1 failed, 32 passed); 20 из 20 красных, в т.ч. под нагрузкой | да |
| N2 | запоминание до _write (бывший M5) | failed_write[false], failed_write[raise] (2) | те же 2 | да |
| N3 | убран ok and (бывший M6) | failed_write[false] (1) | он же (1) | да |
| N4 | or вместо is not None (бывший M7) | 0 в наборе, не эквивалент через kwarg | 0 в наборе (33 passed); probe: last_freq=0.0 даёт 0 против 1000 | да |
| N5 | убран freq > 0 в run() | zero_by_run (1) | он же (1) | да |
| N6 | убран freq > 0 в set_freq() | zero_by_set_freq, zero_without_memory, reconnect::zero_not_carried (3) | те же 3 | да |
| N7 | fallback без памяти (бывший M1) | 14 (9 в test_client + 5 в reconnect) | ровно те 14 | да |
| D1 | disconnect без _remember_last_freq | 4: survive_disconnect, two_reconnects, zero_not_carried, disconnect_without_client | 3, без two_reconnects | НЕТ: промах предсказания. Во втором звене цепочки set_degraded запоминает 25 и спасает тест; D1 ломает только первое звено |
| D2 | set_degraded без _remember_last_freq | survive_set_degraded, two_reconnects (2) | те же 2 | да |
| D3 | connect не передаёт last_freq | 5 reconnect-тестов | те же 5 | да |
| D4 | _remember_last_freq без охраны is not None | 0 (недостижимая ветка) | 0 (33 passed) | да, эквивалент (мёртвая охрана) |

Бывшие выжившие M5, M6 теперь красные (N2, N3). M7 по-прежнему выживает в наборе, но по причине Р2-1 это не эквивалент, а пробел (нет теста на kwarg last_freq=0.0).

## Что я оставил открытым / ненадёжным (раунд 2)
- Р2-3 и Р2-5 получены чтением кода (DeviceManager.upsert/remove, recipe-apply плагина), не воспроизведены через DeviceManager.
- Контрфакт сторожа (74 файла без исключения) не прогонялся.
- Hazard-тест: 20+20 прогонов на этой машине; при другой нагрузке порог 0,3 с мог бы дать выживание безлокового мутанта (ложно-зелёный); ложно-красных быть не может.
- Мутанты прогнаны на test_client.py и test_vfd_driver_reconnect.py; test_protocol_parity.py (20) и test_vfd_driver.py мутантам не подвергал (только зелёный прогон).
- Не гонял Plugins/hub/device_hub/tests и camera_robot-тесты (они на фейках хаба, VfdClient напрямую не зовут).
- Находка 4 (верхняя граница и сброс памяти) остаётся нереализованной по решению владельца; правки её слегка усилили (Р2-5). Запуск на реальном ПЧ не выполнялся и не проверялся.
- qex и sentrux не использовал. Новый урок не пишу; кандидат уже записан в раунде 1.
- Эскалации не нужно: итог APPROVED, итерация 2 из 2 использована.
