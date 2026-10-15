# code-reader-gui — Фаза 2 — настройки

Шапка плана, решения, общие правила и лимит итераций: [`../code-reader-gui.md`](../code-reader-gui.md). Статус задач пишется один раз — в разделе «Порядок выполнения» шапки.

### Task 2.1 — Get/set узлов GenICam в `sdk/`
**Level:** Senior (ctypes, ABI `float`/`int64`/`bool`) · **Assignee:** `teamlead` (opus) · **Gate:** `light` / `medium`
**Handoff:** `reviewer`(stage 0) → `tester`(RED) → `teamlead`(GREEN) → `reviewer`
**Goal:** читать и писать узлы прибора по имени через тот же `MvCodeReaderApi`, без нового слоя.
**Что переиспользуем:** `MvCodeReaderApi._call/_check` и ленивую загрузку (`sdk/api.py:82–90`); `SdkError` /
`unsigned` (`sdk/errors.py`); форму «узел по имени» из `Services/hikvision_camera/core/parameters.py`;
`tools/mvcr_probe.py` — флаг вместо нового зонда.
**Что НЕ пишем и почему:** класс параметров/фасад поверх API (решение 2 плана Ф6: один класс, без обёрток);
`Services/hikvision_camera` для параметров (MVS SDK не видит GEV-прибор — 0 устройств); обход XML-дерева
узлов (имена известны).
#### DESIGN
**DESIGN (`sdk/api.py`, методы `MvCodeReaderApi`):**
`get_int(h, key) -> dict(cur,min,max,inc)`, `get_float(h, key) -> dict(cur,min,max)`,
`get_enum(h, key) -> dict(cur, supported: list[int])`, `get_bool(h, key) -> bool`,
`set_int(h, key, int)`, `set_float(h, key, float)`, `set_enum(h, key, int)`, `set_enum_str(h, key, str)`,
`set_bool(h, key, bool)`. Ключ — `key.encode("ascii")` как `c_char_p`; значения — **явно** `C.c_float`,
`C.c_int64`, `C.c_uint`, `C.c_bool` (без `argtypes` ctypes передал бы `float` как `double`: на x64 приём
`float` по XMM — мусор). Ненулевой код → `SdkError(code, "MV_CODEREADER_<имя>")` + в тексте ключ узла.
`sdk/structures.py`: `INTVALUE_EX`, `FLOATVALUE`, `ENUMVALUE` строго по `MvCodeReaderParams.h:382–408`.
`sdk/errors.py`: `E_GC_RANGE = 0x80020102`, `E_GC_ACCESS = 0x80020106`.
`tools/mvcr_probe.py --params`: открыть прибор, напечатать тип/текущее/min/max для `ExposureTime`, `Gain`,
`TriggerMode`, `TriggerSource`, `QualityEnable`, `LightBrightness`, `RunningMode`, закрыть. Ничего не пишет.
**Files:** 1. `Services/code_reader/sdk/api.py` 2. `Services/code_reader/sdk/structures.py`
3. `Services/code_reader/sdk/errors.py` 4. `Services/code_reader/sdk/__init__.py` (экспорт, если нужен)
5. `Services/code_reader/tools/mvcr_probe.py`. Тесты `tester`: `Services/code_reader/tests/test_sdk_params.py`.
**REDS:** `Services/code_reader/tests/test_sdk_params.py::*` (методов и структур нет).
#### Приёмка
**Acceptance criteria:**
- [ ] Размеры структур — литералы, посчитанные tester'ом по заголовку вручную: `INTVALUE_EX` 96 Б,
      `FLOATVALUE` 28 Б, `ENUMVALUE` 280 Б (tester перепроверяет и фиксирует своё число).
- [ ] Фейковая `lib` получает `SetFloatValue` с аргументом типа `c_float` и значением `880.0`, `SetIntValue` —
      `c_int64`, `SetBoolValue` — `c_bool`, ключ — `bytes` `b"ExposureTime"`.
- [ ] `get_float` на фейке, заполнившем структуру `(880.0, 15.0, 10000.0)` → `{"cur": 880.0, "min": 15.0, "max": 10000.0}`.
- [ ] Код `0x80020106` → `SdkError` с `code == 0x80020106`, в тексте `GetFloatValue`/`SetFloatValue` и имя узла.
- [ ] `import Services.code_reader.sdk` без IDMVS по-прежнему не грузит DLL.
- [ ] Стенд (лидер, `heavy`, без ⚑ — триггер не нужен): `mvcr_probe.py --params` на новой камере печатает
      тип и значения всех 7 узлов; таблица — в «Итоги» плана. **От неё зависят** типы полей Task 2.2
      (если `ExposureTime` окажется Int — DESIGN 2.2 правится до стадии 1, не после).
**Break-injection:** `c_float` → голый `float`; ключ `str` вместо `bytes`; пропуск поля `nReserved` в
структуре; `E_NODATA`-ветка, подменяющая ошибку на `None`.
**Out of scope:** `SetCommandValue`/`TriggerSoftware`, `UserSetSave`, строковые узлы, XML-узлы.

### Task 2.2 — Параметры в сессии и плагине: register → прибор → дерево
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

### Task 2.3 — Секция «Считыватель кодов» во вкладке Services (только по слову владельца)
**Level:** Middle · **Assignee:** `developer` (sonnet) · **Gate:** `light`
**Handoff:** `developer`(REDS в брифе) → `reviewer`
**Goal:** те же поля register'а `code_reader_sdk` — в дереве вкладки Services, рядом с камерами.
**Что переиспользуем:** `ParamsFormSection` инспектора (`frontend/widgets/tabs/pipeline/inspector/params_form_section.py`)
как виджет формы; отправку правки — тот же `SetPluginConfig`, что `pipeline/mutations.py::_on_inspector_field_changed`;
поиск процесса по `plugin_name` — как `services/hikvision/presenter.py::hikvision_process_name`; регистрация
секции — одна строка в `services/_sections.py::build_services_sections`.
**Что НЕ пишем и почему:** тройку presenter/section/widget по образцу `services/camera/` (форма по `FieldMeta`
уже есть); свои команды прибору (правка идёт `register_update`, как из инспектора).
**Files:** 1. `multiprocess_prototype/frontend/widgets/tabs/services/code_reader/__init__.py`
2. `multiprocess_prototype/frontend/widgets/tabs/services/code_reader/section.py` (оценка ≤ 100 строк)
3. `multiprocess_prototype/frontend/widgets/tabs/services/_sections.py` 4. тест в `services/tests/`.
**REDS:** `services/tests/test_code_reader_section.py::*`.
#### Приёмка
**Acceptance criteria:**
- [ ] Рецепт с `code_reader_sdk` активен → секция показывает 4 редактора полей решения 4 с единицами.
- [ ] Правка экспозиции в секции → в шину уходит `SetPluginConfig(process="reader_sdk", field="exposure_time", value=…)`
      (тот же объект команды, что из инспектора).
- [ ] Рецепт без считывателя → секция с текстом «в активном рецепте нет считывателя кодов», без падения.
**Не проверено при планировании:** как секция Services достаёт диспетчер команд (`AppServices`) — проверяет
стадия 0; нет доступа → `ESCALATION -> teamlead`.
**Out of scope:** дисплей в секции (кадр — в дисплее рецепта), кнопки take/release (команды есть, доступны из инспектора).
