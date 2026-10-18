# code-reader-gui — Фаза 2 — история: Task 2.2a (сделана) и Task 2.2b (заменена)

Шапка плана: [`../code-reader-gui.md`](../code-reader-gui.md). Вынесено из [`phase-2.md`](phase-2.md) 2026-10-18 без правки текста.
Task 2.2b не выполнять: её заменяет `plans/2026-10-18_camera-device-service/plan.md` (Task 2.4, 3.2).

### Task 2.2a — Режим съёмки из рецепта: trigger_mode / trigger_source / trigger_period_ms → прибор при старте
**Level:** Middle+ (три потока: вызывающий `start()` пишет, поток захвата возвращает, `produce()`/`_snapshot` читают `stats()`) ·
**Assignee:** `developer` (sonnet; владелец 2026-10-16: сегодня только Sonnet/Haiku) · **Gate:** `light` / `medium`
**Handoff:** `reviewer`(stage 0, раунд 1 сделан, правки внесены) → `tester`(RED, worktree) → `developer`(GREEN + hazard-тесты) → инъекции → стенд → `reviewer`
**Dependencies:** 2.2b строго ПОСЛЕ 2.2a (те же файлы: `sdk_reader.py`, `sdk_plugin.py`, `sdk_registers.py`, снимок каталога).
**Goal:** рецепт задаёт режим съёмки прибора (`trigger_mode: "On"`, `trigger_source: "SelfTrigger"`,
`trigger_period_ms: 40`), плагин пишет его при старте и возвращает прежнее при остановке. Опыт стенда 2026-10-16:
камера 2 в `Line0` снимает только по аппаратному триггеру; в `SelfTrigger` с периодом 32 мс обе камеры дают 25 кадров/с.
**Module contract:** меняется публичное: `SdkCodeReader.__init__(…, trigger: Mapping[str, Any] | None = None)`,
`stats()["param_errors"]`, ключ снимка плагина `param_errors`, три поля и одно readonly-поле register'а.
**Решение владельца 2026-10-17 (после ревью r1 и Opus-прохода):** запись режима вынесена в ОТДЕЛЬНЫЙ рецепт `qr_reader_sdk_dual_selftrigger`; основной `qr_reader_sdk_dual_demo` (`pipeline` по умолчанию, `app.yaml:44`) режим в приборы не пишет — штатный выход убивает читателей до возврата режима. Прежняя редакция этого пункта (запись режима в рецепте по умолчанию) снята.
**Что НЕ входит (остаётся в 2.2b):** живая правка из GUI (`register_update` → перезахват), `exposure_time`/`gain`/
`quality_enable`, публикация `params` в дереве, `RunningMode`, `UserSetSave`. Одиночный рецепт `qr_reader_sdk_demo.yaml` не меняется.
#### DESIGN
**DESIGN:**
- `plugin/sdk_registers.py`: `trigger_mode: str = ""` (`""` = не трогать; иначе `"Off"`/`"On"`), `trigger_source: str = ""`
  (`""` = не трогать; иначе имя: `"Line0"`, `"SelfTrigger"`), `trigger_period_ms: int = 0` (`0` = не трогать). `FieldMeta`
  БЕЗ `min=32` (дефолт 0 ниже минимума — register не построится, воспроизведено ревью); `max=180000`, `min=0`; диапазон 32..180000
  судит прибор (`0x80020102` → `param_errors`). `info`: «пишется в прибор при захвате». Плюс readonly `param_errors: str = ""`.
- `core/sdk_reader.py`: `SdkCodeReader(..., trigger=None)`; ключи `trigger` — имена register'а `trigger_mode`,
  `trigger_source`, `trigger_period_ms`, отображаются на узлы `TriggerMode`, `TriggerSource`, `TriggerSelfTriggerPeriod`;
  неизвестный ключ → `ValueError` в `__init__`. В `_start_locked` между `open` и `start_grabbing`, строго по порядку
  режим → источник → период, для каждого заданного узла: (1) прочитать исходное `get_enum(h, узел)["cur"]` /
  `get_int(h, узел)["cur"]`; не прочиталось → узел НЕ пишется, `param_errors[узел]` = код/текст, потомки пропущены
  (прецедент зонда `mvcr_probe.py`: нечитаемое не пишем); (2) записать (`set_enum_str` для режима и источника,
  `set_int` для периода); отказ записи = «не применилось», в `restore` узел не попадает; (3) успех → `restore.append((узел, тип, исходное))`.
  **Правило потомков:** потомок (источник — потомок режима, период — потомок источника) пропускается с записью
  `param_errors[узел] = "пропущен: родитель не записан"`, если его родитель был в рецепте и не записался; родитель
  не в рецепте → потомок пробуется.
- **Любое исключение узла** (не только `SdkError`: `UnicodeEncodeError` от `set_enum_str` с не-ASCII, `TypeError`
  от `set_int`) ловится на узле (`except Exception`): в `param_errors` — `0x…: текст` для `SdkError`, ТОЛЬКО
  `type(exc).__name__` для остальных (в `str(exc)` может быть значение из рецепта); `start()` не падает. Весь блок записи — в
  `try`: любой выход → возврат записанного + `close` (handle не утекает).
- **Исходные значения в лог INFO до записи** (`узел исходное → новое`): если возврат откажет, оператор сможет вернуть руками.
- **Отказ `start_grabbing`** (путь в `_start_locked`, сессии/потока нет): возврат записанного в обратном порядке, каждый в своём
  `try`, затем `close` всегда (`stop_grabbing` там не зовётся — как сейчас).
- **Возврат при штатной остановке:** в `_release` (поток захвата; сейчас это цикл по `("stop_grabbing","close")` — разбить),
  после `stop_grabbing` и до `close`: `restore` в ОБРАТНОМ порядке (период → источник → режим), каждый в своём `try`;
  отказ → `_note_error` (растит `errors`), остальные всё равно возвращаются, `close` всегда. Возврат пробуется ВСЕГДА,
  даже если `stop_grabbing` упал (запись при идущем захвате даст `0x80020106` — это просто ещё одна запись в `_note_error`).
  `_Session.restore: list = field(default_factory=list)` (общего изменяемого дефолта нет).
- `stats()["param_errors"]` — копия dict, запись и копия под `self._lock`; очищается в начале `_start_locked` (после
  проверки «поток жив»), чтобы повторный `start()` не нёс старые ошибки. Ошибка узла НЕ идёт через `_emit`/`_note_error`:
  пишется прямо `_log.warning`; `last_error` не трогается, `errors` не растёт, `on_error` не вызывается.
- `plugin/sdk_plugin.py`: в `configure` собрать `trigger` из НЕпустых/ненулевых полей `ctx.config`; в `reader_factory`
  `trigger=` передаётся ТОЛЬКО когда он непуст (иначе существующий `test_sdk_plugin_hazards.py:227` с точным
  `kw == {"device_ip": None, "timeout_ms": 250}` краснеет). В `_snapshot`: `reg.param_errors = <строка>` под
  `self._lock` рядом с `reg.last_error` И ключ `"param_errors"` в возвращаемый dict (оттуда в дерево через `proxy.merge`
  и в `get_status`). Строка: `узел: текст; …`, порядок вставки (режим, источник, период), `""` если пусто.
- Рецепт `qr_reader_sdk_dual_demo.yaml`: у обоих читателей `trigger_mode: "On"`, `trigger_source: "SelfTrigger"`,
  `trigger_period_ms: 40` (≈25 кадров/с); строку 26 «боевой триггер аппаратный и через ПК не идёт» заменить на описание нового режима.
- ADR-CR-010 в `Services/code_reader/DECISIONS.md` («режим пишется на start, возвращается в `_release`; отказ узла не
  роняет start; ошибка узла остаётся в `param_errors`, `last_error` не затирается») и строка в `README.md` сервиса.
**Files:** 1. `Services/code_reader/core/sdk_reader.py` 2. `Services/code_reader/plugin/sdk_registers.py`
3. `Services/code_reader/plugin/sdk_plugin.py` 4. `multiprocess_prototype/recipes/qr_reader_sdk_dual_demo.yaml`
5. `multiprocess_prototype/frontend/forms/tests/snapshots/catalog_register_fields.txt` — ВРУЧНУЮ ровно четыре строки (скрипта пересъёмки
нет): `code_reader_sdk.param_errors` (после `no_reads`), `code_reader_sdk.trigger_mode`, `code_reader_sdk.trigger_period_ms`,
`code_reader_sdk.trigger_source` (после `total_reads`) — снимок сравнивает отсортированный список всех полей, включая readonly.
6. `Services/code_reader/DECISIONS.md`, `Services/code_reader/README.md`
7. `multiprocess_prototype/recipes/tests/test_qr_reader_sdk_dual_demo.py` (новый тест рецепта, см. REDS)
8. `Services/code_reader/tests/test_sdk_trigger_hazards.py` (автор). Тесты `tester`: `Services/code_reader/tests/test_sdk_trigger.py`
(фейк API с состоянием строит тестер там же: узел закрыт `0x80020106`, пока родитель не сменён; запись при идущем захвате → `0x80020106`).
**REDS:** `test_sdk_trigger.py::*`; новый `test_qr_reader_sdk_dual_demo.py::test_режим_съёмки_у_обоих_читателей` (литералы
`"On"`, `"SelfTrigger"`, `40` у `reader_1` и `reader_2`; ключи рецепта ⊆ `CodeReaderSdkRegisters.model_fields`);
`test_catalog_kind_roundtrip.py` краснеет после появления полей, пока снимок не правлен (правка — часть GREEN).
Остаются зелёными: `test_sdk_plugin_hazards.py` (в т.ч. `:227`), `test_blueprint_проходит_check_загрузчика`, `test_qr_reader_sdk_demo.py`.
#### Приёмка
**Команда:** `pytest Services/code_reader/tests/test_sdk_trigger.py Services/code_reader/tests/test_sdk_trigger_hazards.py -q`
и `pytest multiprocess_prototype/frontend/forms/tests/test_catalog_kind_roundtrip.py multiprocess_prototype/recipes/tests -q`.
**Acceptance criteria:**
- [ ] Без полей режима (пусто/0) фейковый API не получил ни одного `get_*`/`set_*` узлов; `kw` читателя в плагине не содержит `trigger`.
- [ ] Все три поля → вызовы фейка по порядку (литерал): `open`, `get_enum(TriggerMode)`, `set_enum_str(TriggerMode,"On")`,
      `get_enum(TriggerSource)`, `set_enum_str(TriggerSource,"SelfTrigger")`, `get_int(TriggerSelfTriggerPeriod)`,
      `set_int(…,40)`, `start_grabbing`.
- [ ] `stop()` при идущем захвате → после `stop_grabbing`, до `close`: `set_int(период, исходное)`, `set_enum(TriggerSource, исходное)`,
      `set_enum(TriggerMode, исходное)`. Исходные берутся ЛИТЕРАЛОМ `0` у режима и источника (камера 1: Off, Line0) — возврат `0` не пропускается.
- [ ] Исходное `TriggerSource` и периода читается только ПОСЛЕ записи родителя (фейк: до этого узел отвечает `0x80020106`) — в
      `restore` попадает прочитанное значение для источника И для периода.
- [ ] Исходное зависимого узла не прочиталось (`0x80020106` и после записи родителя) → узел не пишется, `param_errors[узел]` содержит
      `0x80020106`, потомки пропущены, возврат остальных идёт.
- [ ] `set_enum_str(TriggerMode)` отказал (`0x80020102`) → вызовов источника и периода НЕТ, `param_errors` = `{TriggerMode: …0x80020102…,
      TriggerSource: "пропущен…", TriggerSelfTriggerPeriod: "пропущен…"}`, `state == "running"`, `restore` пуст.
- [ ] `trigger_source` задан, `trigger_mode` не задан → источник пробуется (родителя в рецепте нет).
- [ ] `trigger_period_ms: 10` → register строится, `configure` проходит, фейк получает `set_int(…,10)` и отвечает `0x80020102` →
      `param_errors` содержит `0x80020102`.
- [ ] `set_enum_str` бросает `UnicodeEncodeError` (не-ASCII в `trigger_mode`) → `start()` возвращает True, `close` не потерян,
      `param_errors[TriggerMode]` непуст и НЕ содержит самой строки значения (только `UnicodeEncodeError`).
- [ ] После отказа узла: `stats()["last_error"] is None`, `stats()["errors"] == 0`, `on_error` не вызван; в логе WARNING.
- [ ] Отказ возврата одного узла не мешает возврату остальных и вызову `close`; `errors` растёт на число отказавших, `on_error` зван.
- [ ] Отказ `start_grabbing` после записи → литеральный порядок: `open`, записи, `start_grabbing`(fail), возврат в обратном
      порядке, `close`; `close` ровно один.
- [ ] `start → stop → start` даёт ту же литеральную последовательность вызовов; `param_errors` второго (чистого) запуска пуст.
- [ ] `stats()["param_errors"]` — копия (правка копии не меняет читателя); hazard-тест: параллельный `stats()` во время `start()` в
      daemon-потоке с дедлайном не бросает `RuntimeError`.
- [ ] Два `SdkCodeReader` на одном фейке с разными handle: каждый возвращает СВОИ исходные, `param_errors` независимы.
- [ ] Плагин: после отказа узла `plugin._reg.param_errors`, `cmd_get_status({})["param_errors"]` и `ctx.state_proxy.tree()["param_errors"]`
      содержат `0x80020102`; чистый запуск → `""` во всех трёх. Один тест связывает настоящие `SdkCodeReaderPlugin.configure` и
      `SdkCodeReader` на фейковом API (рецептная конфигурация → записи в прибор).
- [ ] СТЕНД (владелец + я, окно координатора не требуется по распоряжению владельца): до и после прогона `mvcr_probe.py --params --ip
      <камера> --node TriggerMode --node TriggerSource --node TriggerSelfTriggerPeriod` показывают ОДИНАКОВОЕ состояние (возврат
      сработал); обе камеры ≥ 20 кадров/с; срок от `stop()` до `close` измерен и записан.
**Break-injection:** запись после `start_grabbing`; потомок пишется раньше родителя; нет возврата; возврат в прямом порядке;
исходное зависимого читается до записи родителя; `if orig:` вместо `is not None`; `_emit`/`_note_error` вместо прямого лога
(затирает `last_error`); `param_errors` не очищается на старте; потомок пишется после отказа родителя; узел с нечитаемым
исходным пишется; не-`SdkError` роняет `start()` с утечкой handle; в пути отказа `start_grabbing` возврат после `close`;
отказ возврата одного узла пропускает остальные / `close`; ключ снимка `param_errors` не добавлен; `trigger=` передаётся пустой.
#### Ловушки
**TRAPS:** прибор сам режим не возвращает до выключения питания (опыт 2026-10-16) — без возврата стенд оставляет камеру в
самотриггере и подсветка бьёт ~25 раз в секунду; жёсткое убийство процесса возврат не выполнит (защиты нет — только INFO-лог
исходных). Параметры триггера не пишутся при запущенном захвате (`0x80020106`) — запись строго до `start_grabbing`, возврат
строго после `stop_grabbing`. Прибор закрывает только поток захвата (правило в docstring `sdk_reader.py`, не ADR-CR-008) —
возврат идёт в его `_release`, не из `stop()` вызывающего. `daemon=True` поток при выходе процесса обрывается посреди
возврата → камера может остаться в самотриггере (срок возврата — в стенд-приёмку). Отказ возврата + следующий `start()`
прочитает оставшийся самотриггер как «исходное» и потеряет Off — отсюда INFO-лог. Правка поля в GUI до 2.2b не доходит до
прибора (читатель создаётся в `configure` один раз).
**Out of scope:** см. «Что НЕ входит».

### Task 2.2b — (остаток прежней 2.2) Живая правка параметров из GUI, `exposure_time`/`gain`/`quality_enable`, `params` в дереве — ЗАМЕНЕНА `plans/2026-10-18_camera-device-service/plan.md` (Task 2.4, 3.2), не выполнять
**Level:** Senior+ (три потока: команды, захват, источник; перезахват прибора) · **Assignee:** `teamlead` (opus);
3-я итерация → `cto` · **Gate:** `light` / `medium`
**Handoff:** `reviewer`(stage 0) → `tester`(RED) → `teamlead`(GREEN + hazard-тесты) → `reviewer`
**Goal:** поле register'а `code_reader_sdk`, заданное в рецепте или изменённое в инспекторе Pipeline,
доходит до прибора; фактическое значение видно в дереве.
**Что переиспользуем:**
- механизм «регистр → применение в SDK» из `Services/hikvision_camera/plugin/plugin.py::_apply_parameters_from_register`
  и `registers.py` (`FieldMeta` с `min/max/unit`);
- живую доставку правки из GUI: `register_update` → `RegistersManager.set_field_value` →
  `RegistersManager.subscribe` (готово во framework, `registers_module/core/manager.py:151`);
- перезахват — существующие `cmd_release_device` / `cmd_take_device` и `SdkCodeReader.start/stop`;
- публикацию `_publish_state` → `processes.<proc>.state.code_reader_sdk`.
**Что НЕ пишем и почему:** команды `set_exposure`/`set_gain`/`set_parameters` (GUI уже шлёт `register_update`
— отдельные команды дублировали бы путь); свой опрос register'а в `produce()` (есть `subscribe`; `produce()`
не должен блокировать на перезахвате); свой поток применения; автопереподключение (ADR-CR-009).
#### DESIGN
**DESIGN:**
- `core/sdk_reader.py`: `SdkCodeReader(..., params: Mapping[str, Any] | None = None)` и
  `set_params(params)` (заменяет desired, действует со следующего `start()`). В `_start_locked` между
  `open` и `start_grabbing` — запись desired (решение 7), затем чтение фактических значений тех же узлов +
  `TriggerSource` → `stats()["params"]` (`{узел: {cur, min, max}}` или `{cur, supported}`),
  `stats()["param_errors"]` (`{узел: "0x8002…: текст"}`). Узел → метод API — таблица в модуле
  (`ExposureTime: float`, `Gain: float`, `TriggerMode: enum_str`, `QualityEnable: bool`; типы — по таблице
  стенда 2.1).
- `plugin/sdk_registers.py`: поля решения 4 (`FieldMeta` с `unit`, `info` «пишется в прибор при захвате»).
- `plugin/sdk_plugin.py`: в `configure` — `explicit = {f for f in _PARAM_FIELDS if f in ctx.config}`;
  desired = эти поля → в `reader_factory(..., params=…)`. Подписка `ctx.registers.subscribe(self.name, f,
  cb)` на каждое поле (нет `ctx.registers` → без подписки, лог). `cb`: поле → в `explicit`, `set_params`,
  если прибор был `running` — `cmd_release_device` + `cmd_take_device`; `released: false` → `last_error`
  «параметр применится при следующем take_device», без повтора. В снимок — `params`, `param_errors`.
- **Инвариант:** callback не держит `self._lock` при вызове читателя (как `_snapshot`); два быстрых
  изменения → не больше одного перезахвата одновременно (замок перезахвата).
**Files:** 1. `Services/code_reader/core/sdk_reader.py` 2. `Services/code_reader/plugin/sdk_registers.py`
3. `Services/code_reader/plugin/sdk_plugin.py` 4. `multiprocess_prototype/recipes/qr_reader_sdk_demo.yaml`
(явно `trigger_mode: "On"` — боевой режим; экспозиция/усиление не задаются)
5. `multiprocess_prototype/frontend/forms/tests/snapshots/catalog_register_fields.txt`
6. `Services/code_reader/tests/test_sdk_params_hazards.py` (автор). Тесты `tester`: `Services/code_reader/tests/test_sdk_params_plugin.py`.
**REDS:** `test_sdk_params_plugin.py::*`; `test_catalog_kind_roundtrip.py::test_resolve_kind_stable_across_json_roundtrip_for_all_register_fields`;
`multiprocess_prototype/recipes/tests/test_qr_reader_sdk_demo.py::test_ноды_совпадают_с_плагинами[reader_sdk]` — до появления полей `trigger_mode` в register'е.
#### Приёмка
**Acceptance criteria:**
- [ ] Рецепт без полей параметров → фейковый API не получил ни одного `set_*` (прибор не тронут), `params`
      в дереве заполнен прочитанными значениями.
- [ ] Рецепт с `exposure_time: 1200` → ровно один `set_float("ExposureTime", 1200.0)`, вызван **после** `open`
      и **до** `start_grabbing` (порядок вызовов фейка — литерал).
- [ ] `register_update exposure_time = 900` при `running` → `stop_grabbing`, `close`, `open`,
      `set_float(900.0)`, `start_grabbing` — в этом порядке; `params.ExposureTime.cur == 900.0` в дереве;
      кадры до и после доставлены, `close` ровно один на одно `open`.
- [ ] Тот же `register_update` при `stopped` → прибор не открывается; значение запишется при `take_device`.
- [ ] `set_float` вернул `0x80020102` → `param_errors.ExposureTime` содержит `0x80020102`, `device_state ==
      running`, остальные узлы записаны.
- [ ] Два `register_update` подряд из двух потоков → не больше одного открытого handle одновременно
      (фейк считает открытые), итог `cur` = последнее значение (тест с дедлайном в daemon-потоке).
- [ ] `produce()` во время перезахвата возвращает за < 50 мс.
- [ ] Один тест связывает **настоящие** `RegistersManager` и `PluginOrchestrator._on_register_update` с
      плагином на фейковом API (не фейк подписки).
**Break-injection:** запись после `start_grabbing`; запись всех полей, а не `explicit`; подписка снята;
callback без замка перезахвата; ошибка узла роняет `start()`; `params` не публикуются.
#### Ловушки
**TRAPS:** callback `subscribe` идёт в потоке обработчика команд — не в потоке захвата; поток захвата и
только он закрывает handle (ADR-CR-008), перезахват идёт через `stop()`/`start()`, не мимо них. Плагин —
**первый** пользователь `RegistersManager.subscribe` в бэкенде: если callback не зовётся на живом пути — это
дефект framework, чинить вперёд (принцип №2), `ESCALATION -> teamlead`, не обходить опросом.
**Out of scope:** `UserSetSave`, запись `TriggerSource`, программный триггер, `RunningMode`, перевод
`nOverQuality` в буквы (шкала не снята — `quality_enable` лишь включает расчёт).
