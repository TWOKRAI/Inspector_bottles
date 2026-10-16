# code-reader-gui — Фаза 2 — настройки

Шапка плана, решения, общие правила и лимит итераций: [`../code-reader-gui.md`](../code-reader-gui.md). Статус задач пишется один раз — в разделе «Порядок выполнения» шапки.

### Task 2.1 — Get/set узлов GenICam в `sdk/` (+ зонд с опытом «свободный режим»)
**Level:** Senior (ctypes, ABI `float`/`int64`/`bool`), спека закрывает ABI до буквы · **Assignee:** `developer` (sonnet;
владелец 2026-10-16: сегодня Sonnet/Haiku; эскалация → `teamlead`) · **Gate:** `light` / `medium`
**Handoff:** `reviewer`(stage 0, сделан 2026-10-16, 13 правок приняты) → `tester`(RED) → `developer`(GREEN) → `reviewer`
**Goal:** читать и писать узлы прибора по имени через тот же `MvCodeReaderApi`, без нового слоя; зондом снять на
новой камере, что даёт свободный режим (`TriggerMode=Off`) при `RunningMode` Normal/Raw/Test.
**Что переиспользуем:** `MvCodeReaderApi._call/_check` и ленивую загрузку (`sdk/api.py:82–90`); `SdkError` /
`unsigned` (`sdk/errors.py`); `FakeLib` из `tests/test_sdk_layer.py` (форма фейка); `tools/mvcr_probe.py` — флаги
вместо нового зонда; позиционный `seconds` зонда.
**Что НЕ пишем и почему:** класс параметров/фасад поверх API (решение 2 плана Ф6: один класс, без обёрток);
`Services/hikvision_camera` для параметров (MVS SDK не видит GEV-прибор — 0 устройств); обход XML-дерева узлов;
`XML_GetNodeInterfaceType` (в `Development.zip` нет объявления сигнатуры — ставка на ABI); `argtypes`/`restype`
(конвенция `api.py`: обёртка значения на месте вызова, `argtypes` менял бы общий объект функции DLL).
#### DESIGN
**Заголовок SDK** (для тестера и исполнителя): `C:\Program Files (x86)\IDMVSSTD\Development\Development.zip` →
`Modules/MvCodeReaderSDK/Include/MvCodeReaderParams.h`, `MvCodeReaderCtrl.h`, `MvCodeReaderErrorDefine.h`.
**`sdk/structures.py`:** `ENUMVALUE` (Params.h:382–388: `nCurValue, nSupportedNum, nSupportValue[64], nReserved[4]`),
`INTVALUE_EX` (401–408: `nCurValue, nMax, nMin, nInc` — `int64`, `nReserved[16]` — `uint32`), `FLOATVALUE`
(411–417: `fCurValue, fMax, fMin` — порядок именно такой, `nReserved[4]`). `INTVALUE` (391–398) НЕ использовать:
`GetIntValue` принимает `INTVALUE_EX*`.
**`sdk/api.py`, методы `MvCodeReaderApi`:** `get_int(h, key) -> {"cur","min","max","inc"}`,
`get_float(h, key) -> {"cur","min","max"}`, `get_enum(h, key) -> {"cur","supported"}` где
`supported = nSupportValue[:min(nSupportedNum, 64)]`, `get_bool(h, key) -> bool`; `set_int(h, key, int)`,
`set_float(h, key, float)`, `set_enum(h, key, int)`, `set_enum_str(h, key, str)`, `set_bool(h, key, bool)`.
Ключ передаётся голым `bytes` (`key.encode("ascii")`), без `c_char_p`; не-ASCII ключ → `UnicodeEncodeError` до вызова
DLL. Значения — явные обёртки: `C.c_float`, `C.c_int64`, `C.c_uint`, `C.c_bool`; `set_enum_str` передаёт значение
`bytes`. Без обёрток ctypes отвергает `float`; `c_double` вместо `c_float` молча даёт 0.0; голый `int` теряет знак и
бросает `OverflowError` выше 2**31; `str` уходит как UTF-16 и даёт неверное имя узла. Проверок диапазона в Python нет —
судья SDK (`E_GC_RANGE`). Ненулевой код → `SdkError(rc, f"MV_CODEREADER_{name}[{key}]")` (ключ — в `where`, не через
`add_note`: `add_note` не меняет `str(exc)`); код приходит и знаковым, и беззнаковым — как уже обрабатывает `unsigned()`.
`E_NODATA` в этих методах — ошибка, не `None` (особая ветка только у `get_frame`).
**`sdk/errors.py`:** `E_GC_RANGE = 0x80020102`, `E_GC_ACCESS = 0x80020106`; оба доступны и в `sdk.errors`, и в `sdk`
(добавить в импорт и `__all__` в `sdk/__init__.py`). Структуры наружу не экспортируются (как сейчас).
**`tools/mvcr_probe.py`:** шов для фейка: `main(argv: list[str] | None = None, *, api: MvCodeReaderApi | None = None) -> int`
(`api is None` → создаётся как сейчас); режимы принимают `api` первым параметром: `run_params(api, names)`,
`run_session(api, sets, seconds, out)`; первый прибор — `api.enum_devices()[0]`.
- `--params`: для каждого из 7 узлов (`ExposureTime`, `Gain`, `TriggerMode`, `TriggerSource`, `QualityEnable`,
  `LightBrightness`, `RunningMode`) результат ВСЕХ четырёх getter'ов:
  `NODE <имя> enum=OK(cur=…)|0x8002… int=… float=… bool=…`. «Тип» узла = множество getter'ов, ответивших 0 (угадывание
  по чтению не делаем: что делает `GetEnumValue` на int-узле, в SDK не записано). Ничего не пишет. `--params` вместе
  с `--set` → `parser.error`.
- `--set УЗЕЛ=ТИП:ЗНАЧЕНИЕ` (повторяемый; ТИП ∈ `enum|int|float|bool`; без `ТИП:` → `parser.error`, код 2).
  enum: ЗНАЧЕНИЕ целое → `set_enum`, иначе строка → `set_enum_str`, целое < 0 → код 2; bool: `0|1|true|false`;
  float: `nan`/`inf` → код 2.
- Время: отдельного флага `--seconds` НЕТ — позиционный `seconds` (float). Без `--set` по умолчанию 60, как сейчас;
  с `--set` по умолчанию 10; значение вне `(0, 30]` → `parser.error` (отказ, не обрезка: 30 с — защита от нагрева).
- Протокол с `--set`: после `open` исходные значения всех `--set`-узлов читаются тем же типизированным getter'ом, что
  задан в ТИП (нечитаемый узел → выход до первой записи, `start_grabbing` не вызывается); печатается
  `ORIG <узел>=<ТИП>:<значение>`; запись по порядку до `start_grabbing`; отказ любой записи → `start_grabbing` не
  вызывается, записанное восстанавливается, код выхода 1; затем приём кадров `seconds` секунд;
  `finally`: `stop_grabbing` (его `SdkError` печатается, не прерывает) → для КАЖДОГО узла с прочитанным оригиналом
  независимая запись оригинала (enum → `set_enum(cur)` числом) с чтением обратно → `RESTORED <узел> <значение>` либо
  `RESTORE MISMATCH`, либо `RESTORE FAILED <узел> orig=<значение> 0x…` (код выхода 3, без повторов) → `close` всегда.
  Свободный режим греет прибор, оставлять его включённым нельзя; `finally` не защищает от жёсткого убийства процесса —
  для этого строка `ORIG`.
- Итог: `ИТОГ кадров: N с_кодом: M read: R noread: Q fps: F.F`; `с_кодом` — кадры с ≥1 записью кода, `read` — записи с
  `nBarType != BAR_TYPE_NOREAD`, `noread` — записи с `nBarType == BAR_TYPE_NOREAD`, `fps = кадров / seconds`.
  Существующий префикс `ИТОГ кадров:` сохраняется.
**Files:** 1. `Services/code_reader/sdk/api.py` 2. `Services/code_reader/sdk/structures.py`
3. `Services/code_reader/sdk/errors.py` 4. `Services/code_reader/sdk/__init__.py` 5. `Services/code_reader/tools/mvcr_probe.py`.
Тесты `tester`: `Services/code_reader/tests/test_sdk_params.py` (SDK-слой и зонд в одном файле).
**REDS:** `Services/code_reader/tests/test_sdk_params.py::*` (методов, структур и шва `api=` нет).
#### Приёмка
**Acceptance criteria:**
- [ ] Размеры структур — литералы, посчитанные tester'ом по заголовку вручную: `INTVALUE_EX` 96 Б, `FLOATVALUE` 28 Б,
      `ENUMVALUE` 280 Б (tester перепроверяет и фиксирует своё число).
- [ ] Аргументы фейковой `lib`: ключ `type(args[1]) is bytes` и `== b"ExposureTime"`; значение `SetFloatValue` —
      `isinstance(args[2], C.c_float)` и `.value == 880.0`; `SetIntValue` — `c_int64`; `SetEnumValue` — `c_uint`;
      `SetEnumValueByString` — `bytes`; `SetBoolValue` — `c_bool`; `args[0]` — `c_void_p`.
- [ ] Чтение, фейк пишет по байтовым смещениям: `get_float` `fCurValue@0=880.0, fMax@4=10000.0, fMin@8=15.0` →
      `{"cur": 880.0, "min": 15.0, "max": 10000.0}`; `get_int` `nCurValue@0=880, nMax@8=10000, nMin@16=15, nInc@24=5` →
      `{"cur":880,"min":15,"max":10000,"inc":5}`; `get_enum` `nCurValue@0=1, nSupportedNum@4=3, nSupportValue@8=[0,1,7]` →
      `{"cur":1,"supported":[0,1,7]}`, при `nSupportedNum=70` в списке ровно 64 элемента; `get_bool` байт 1 → `True`.
- [ ] Ошибки: код `0x80020106` и знаковый `-2147352314` → `SdkError` с `code == 0x80020106`, в `str(e)` лежат
      `"SetFloatValue"`, `"ExposureTime"` и `"0x80020106"`; `returns={"GetFloatValue": 0x80020006}` (`E_NODATA`) →
      `SdkError` с `code == 0x80020006`, не `None`.
- [ ] `import Services.code_reader.sdk` без IDMVS по-прежнему не грузит DLL (регрессия; уже покрыта `test_sdk_layer.py`).
- [ ] Зонд на фейковом `MvCodeReaderApi` через `main([...], api=fake)` с `seconds=0.2`; журнал вызовов — список имён.
      Сценарий 1 (`--set TriggerMode=enum:Off`, исходный `TriggerMode=1`): `[open, get_enum, set_enum_str, start_grabbing,
      get_frame…, stop_grabbing, set_enum, get_enum, close]`, где `set_enum` с `value == 1` ровно один, после
      `stop_grabbing` и до `close`. Сценарий 2: `get_frame` бросает `RuntimeError("boom")` (не `SdkError` — его цикл
      ловит) → восстановление выполнено один раз, исключение вышло наружу. Сценарий 3: запись второго из двух узлов
      бросает `SdkError(0x80020102)` → `start_grabbing` не вызывался, первый узел восстановлен, код выхода 1.
      Сценарий 4: `set_enum` при восстановлении бросает `SdkError` → `close` всё равно вызван, второй узел восстановлен,
      код выхода ≠ 0. Без `--set` в журнале нет ни одного `set_*`.
- [ ] Итог: фейк отдаёт 3 кадра (1 с кодом `b"QR"`, 1 с NoRead, 1 пустой) → в stdout ровно префикс
      `ИТОГ кадров: 3 с_кодом: 2 read: 1 noread: 1 fps:`.
- [ ] Разбор аргументов: `--set X=1` (без типа), `nan`, `--params` вместе с `--set`, `seconds=31`, `seconds=0` →
      код выхода 2, фейковый API не вызван.
- [ ] Стенд (лидер; окно координатора или явное разрешение владельца; триггер не нужен): `mvcr_probe.py --params` на
      новой камере — в «Итоги» плана для каждого из 7 узлов строка со всеми четырьмя getter'ами (от неё зависят типы полей
      Task 2.2; если `ExposureTime` окажется Int — DESIGN 2.2 правится до стадии 1, не после); опыт `--set
      TriggerMode=enum:Off --set RunningMode=enum:<Normal|Raw|Test>` по прогону на значение, `seconds=10` — числа
      (кадров, с кодом, fps) в «Итоги»; после каждого прогона отдельный `--params`: `TriggerMode` и `RunningMode` равны
      исходным (числа до и после — рядом).
**Break-injection:** `c_float` → `c_double` (молчаливый вариант); `c_float` → голый `float`; ключ `str` вместо `bytes`;
пропуск `nReserved` в структуре; `fMin`/`fMax` местами; `supported` без клампа; `E_NODATA` → `None`; восстановление
вне `finally`; восстановление до `stop_grabbing`; одна неудача восстановления пропускает остальные узлы; запись после
`start_grabbing`; `close` не вызывается при отказе восстановления.
**Out of scope:** `SetCommandValue`/`TriggerSoftware`, `UserSetSave`, строковые узлы, XML-узлы, угадывание типа узла.

#### Итоги стенда Task 2.1 (2026-10-16, лидер, без окна координатора — разрешение владельца; IDMVS закрыт, стенд остановлен)
`mvcr_probe.py --params --ip <адрес>` — результат четырёх getter'ов (`OK(cur=…)` — узел этого типа; `0x80020106` = узел
этого типа существует, но доступ закрыт сейчас; `0x80020100` = не этот тип):

| Узел | Камера 1 `.10` (WBPF) | Камера 2 `.11` (SENSOTEC) | Тип |
|---|---|---|---|
| `ExposureTime` | float 799.0 | float 1035.0 | **float** |
| `Gain` | float 0.0 | float 4.8 | **float** |
| `TriggerMode` | enum cur=0 (Off) | enum cur=1 (On) | enum |
| `TriggerSource` | enum, доступ закрыт (`0x80020106`) | enum cur=0 (Line0) | enum |
| `QualityEnable` | bool, доступ закрыт | bool, доступ закрыт | bool |
| `LightBrightness` | int, доступ закрыт | int, доступ закрыт | int |
| `RunningMode` | enum cur=2 | enum cur=0 | enum |

Типы полей Task 2.2 подтверждены: `ExposureTime`/`Gain` — float, `TriggerMode`/`RunningMode` — enum.
Опыт на камере 1 (`TriggerMode=0`, окно 10 с, `--set RunningMode=enum:N`, значение возвращено и перечитано):

| `RunningMode` | кадров за 10 с | с кодом | fps |
|---|---|---|---|
| 2 (исходный) | 570 | 0 | 57.0 |
| 1 | 32 | 0 | 3.2 |
| 0 | 0 | 0 | 0.0 |

Этот прогон шёл при расфокусированной камере 1 и без кода в поле зрения — кодов не было, фокус не наведён.
Повтор после наводки фокуса и с QR в поле зрения (`TriggerMode=0`, 10 с на режим, значение возвращено и перечитано):

| `RunningMode` | кадров за 10 с | с кодом | read | fps |
|---|---|---|---|---|
| 2 | 29 | 29 | 29 | 2.9 |
| 1 | 24 | 24 | 24 | 2.4 |
| 0 | 25 | 25 | 25 | 2.5 |

**Вывод:** при `TriggerMode=0` и сфокусированной камере прибор постоянно снимает и декодирует (~2.5–3 кадра/с) в ЛЮБОМ
`RunningMode`; кадров без кода в этом тесте не было, так что в `Normal` кадр, видимо, уходит только при прочтении кода
(0 кадров при расфокусе объясняются этим). Предыдущий прогон `RunningMode=2` на 57 к/с остаётся необъяснённым.
Для требования «камера 1 снимает постоянно» запись параметров из рецепта (Task 2.2) НЕ нужна: достаточно состояния
прибора (`TriggerMode=0`), которое уже стоит; Task 2.2 нужна только для воспроизводимости настройки после сброса прибора.
Исходное состояние камеры 1 (`TriggerMode=0`, `RunningMode=2`) выставлено не зондом — записано до опыта и возвращено после.

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
