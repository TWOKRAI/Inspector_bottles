# Task 2.3c — стадия 0 (reviewer, MODE: plan на файле задачи, раунд 1, 2026-11-16): CHANGES REQUESTED

Дерево `cam-w3`, `main` = `e925ddb85` (2.3a, 2.3b, 2.4a, 2.4b внутри). Читал `tasks/2.3c.md`, `plan.md`, `tasks/4.2a.md`, `tasks/1.3.md`, `amendments.md`, README и DECISIONS ядра,
`session.py`, `plugin_base.py`, `profiles.py`, `params.py`, `registers_base.py`, `testing/fake_port.py`, `Services/hikvision_camera/driver.py`, цепочку диспетчеризации команд framework.
Пробы — `scratchpad/probe23c.py` (настоящие `RegistersManager`, `PluginOrchestrator._on_register_update`, `WorkerManager`, фейк-порт; через `machine_gate.sh light inspector-bottles-20`). memory hits: none (поиск по `camera device plugin commands call` — ни одного релевантного урока).

Чек-лист стадии 0 на файле задачи: (a) команда или литерал — частично (см. 8); (d) `Module contract` — см. N1; (f) `Out of scope` непуст и отличается от `Goal` — да;
(i) причины решений — не у всех (Р1-исключение, «второго порта не строить», формат `status` vs `success` без причины); (ii) инварианты модуля — задет Р1 (README «Boundaries»); (iii) тексты ошибок — `неизвестное поле: <имя>` печатает имя из ввода.

## Блокеры (текст нельзя отдавать слепому тестеру, пока не исправлен)

**B1. `list_devices`: порта нет до первого `take_device`; исключение из Р1 не решено и не доказано.**
- `plugin_base.py:158` `self._port = None`, порт создаётся только в `_ensure_session` (`:514`, `:530`). Проба: `idle plugin._port: None session: None`. DESIGN «порт для `list_devices` — `self._port` плагина (2.3a), второго не строить» не выполним в главном сценарии (список нужен ДО захвата, чтобы выбрать серийник). Нужно решение: вынести `_ensure_port()` из `_ensure_session` (порт под `_session_lock`, сеанс строится из него) — тогда `list_devices` не создаёт сеанс, мост логов и воркеры; тот же `_ensure_port()` нужен `trigger_software` (capability известны только у порта).
- Исключение из Р1 (`acquire/enum_devices/release` из потока команды при идущем захвате) не доказано безопасным на MVS: в `Services/hikvision_camera/driver.py` `MvsSdk.enum_devices` = голый `MV_CC_EnumDevices` (`_enumerate`, `:150-165`), замок `MvsSdk._lock` охраняет только `refs`, с вызовами владельца (`GetImageBuffer`) не связан. В репозитории нет замера «перечисление при открытом/захватывающем handle»: открытый вопрос плана (`plan.md`, «Открытые вопросы»: «перечисление при занятом приборе — 0.5/6.2») ответа не получил (`0.5.result.md`, `6.2.result.md` его не содержат), `DECISIONS.md:114`: «Шторм `EnumDevices` из трёх процессов не проверен». Это ещё и межпроцессный случай: в `hikvision_dual.yaml` процесс B перечисляет, пока процесс A держит GigE-прибор. Прецедент: старый `cmd_enum_devices` (`hikvision_camera/plugin/plugin.py:335`) звал перечисление из потока команды при идущем захвате — сбоев в записях нет, но и замера нет. Владелец исключение не подтвердил; записи о нём в `OPEN_QUESTIONS.md` по grep `list_devices` нет.
- **Рекомендация (убирает зависимость от владельца): Р1 не нарушать.** `list_devices`: если `session.state == "grabbing"` — `session.call(lambda: sdk.enum_devices(), T)` (исполняет владелец, `acquire` не нужен — владелец его держит); иначе (потока-владельца нет, команды идут одним потоком) — `acquire / enum_devices / release` из потока команды: одновременного второго потока у SDK нет. Цена: на время перечисления (GigE — порядка секунды, не измерено) владелец не читает кадры; зато нет предположения о потокобезопасности SDK. `opening`/`stopping` -> `{"success": False, "error": "сеанс не в захвате"}` (литерал из `call`). Если лид оставляет вариант текста — в DESIGN нужны: запрос владельцу, строка в `OPEN_QUESTIONS.md`, поправка ADR-CAM-002, замер 0.5/6.2.
- Формулировка для README/ADR-CAM-002 при варианте текста: «Единственное исключение из Р1: `list_devices` зовёт `DeviceSdk.acquire/enum_devices/release` из потока команды без handle. Безопасность на MVS при открытом handle не измерена (0.5/6.2); исключение действует до замера, снимается, если замер покажет сбой кадров». При рекомендованном варианте: «`list_devices` исполняет перечисление потоком-владельцем (через `call`); без захвата — потоком команды, пока владельца нет».

**B2. `trigger_software`: у плагина нет `Binding` командного узла.**
`DevicePort.execute(b: Binding)` требует привязку; `bindings()` = «поле register'а -> узел» (`plugin_base.py:269`), `check_bindings` (`params.py:102`) отвергает лишние ключи, поля «TriggerSoftware» в register'е нет. Фейк принимает только `b.key == "TriggerSoftware"` (`fake_port.py:332`). В DESIGN нет ни хука, ни умолчания: разработчик будет придумывать. Нужно: хук `software_trigger_binding(self) -> Binding` (умолчание `Binding("genicam", "TriggerSoftware", "command")`, вендор переопределяет) и строка в DESIGN. Проверка capability — `self._port.capabilities` (статично на жизнь порта, не вызов порта; после `_ensure_port()` из B1).

**B3. `apply_params`: смысл «applied» и ответ не определены, а эффект на прибор асинхронен.**
Проба на настоящих объектах (`register.set_field_value` -> колбэк 2.4b -> `session.apply`):
```
grabbing set_field_value -> (True, None) returned after 0.0001s; set_param in journal after 0.0244s
journal: [('set_param', ('ExposureTime', 777.0)), ('get_param', ('ExposureTime',))]
same value again -> (True, None)   journal after: []                # план не изменился -> прибор не трогается
refused write (read_offset): set -> (True, None); param_errors: {'exposure_time': 'не подтвердилось чтением'}
same again -> (True, None); sets in journal: [set_param 900.0, set_param 900.0]   # R2-1 работает
```
Выводы для текста:
1. Колбэк подписки — ЕДИНСТВЕННЫЙ путь на прибор. DESIGN должен прямо запретить в `apply_params` вызов `session.apply` (удвоение; «на прибор — по Р12 через ящик» читается двояко).
2. «applied» = «принято register'ом»; результат на приборе в ответ не входит (приходит позже: `param_errors` в `read_params`). Это надо написать, плюс признак `"on_device": <сеанс в opening/grabbing на момент ответа>`; ждать владельца в команде нельзя (см. B6).
3. Ответ при `device_held`/без захвата: значение в register'е сохранено, `session.apply` лишь пишет INFO «правка не принята» (`session.py:381-382`); ответ `success: True` с `"on_device": False` — зафиксировать литералом.
4. Поля. `set_field_value` пропускает `timeout_ms`, `watchdog_s`, `device_serial`, `driver`, `camera_id` (проба: `timeout_ms 900 -> (True, None)`, `device_serial` при захвате -> `(True, None)`): `applied: ["timeout_ms"]` солжёт (политика `None`/`config`, колбэка на прибор нет; `timeout_ms` заморожен при создании сеанса, `README` «Цикл сеанса»). Более того, `timeout_ms=6000` нарушает `watchdog_s > timeout_ms/1000`, проверяемый только в `configure`. Решить: «неизвестное поле» = нет в `bindings()` (симметрично `read_params`, ключи — поля из привязок) либо `applied` делит на `applied` (прибор) и `stored` (только register). Рекомендация: отказ для полей вне `bindings()` — `{"success": False, "error": "поле не параметр прибора: <имя>"}`; флаги групп (`trigger_managed`) — исключение, надо назвать (у них нет подписки 2.4b: `_subscribe_fields` подписывается на `bindings()`, флаги `*_managed` туда не входят — прочитано, `plugin_base.py:195`).
5. Readonly: `set_field_value("frames", 5) -> (False, 'Недостаточно прав доступа: требуется уровень 0, передан 0')` — текст register'а вводит в заблуждение; нужна своя проверка `FieldMeta.readonly` и литерал `поле только для чтения`.
6. Несколько полей: порядок = порядок словаря; зависимые поля (`trigger_managed` -> `trigger_mode`) работают только в этом порядке; «неизвестное поле» в середине пакета оставит первые поля записанными. Требовать: сперва проверить ВСЕ поля (`RegistersManager.validate_field_value` есть), потом писать; в ACCEPTANCE — `{"exposure_time": 900.0, "nope": 1}` -> `success False`, `exposure_time == 10000.0`, в журнале нет `set_param`. Склейка пакета в один перезахват — как получится (каждое поле = отдельный `set_field_value` -> отдельный `apply`), литерал «один перезахват» в ACCEPTANCE не писать.
7. `ctx.registers is None` (бывает: `plugin_base.py:192`) — ответ в тексте не описан: `{"success": False, "error": "нет RegistersManager"}`.
8. ACCEPTANCE:24 нельзя проверять сразу после ответа: запись на прибор — через 24 мс (проба), тест обязан ждать с дедлайном и проверять тем же путём, что `test_live_apply_wiring.py` (`_wait`, журнал без шума `get_frame`/`describe_param`).
9. `ApplyParamsArgs`: `extra="forbid"`, пустой `params` -> `{"success": True, "applied": []}`.
10. До задачи 1.3 фреймворк не валидирует `data` команды: обработчик сам делает `ApplyParamsArgs.model_validate(data)`; ошибка -> `{"success": False, "error": <текст без значения>}`.
11. Соседняя команда `set_config` (generic `cmd_set_config`, `base.py:1839`) пишет через `reg.apply_values` и подписчиков НЕ будит (прочитано, не запускалось): в список 4.2a она входит, на прибор не доходит. Строка в README «Команды»: на прибор — только `apply_params`/`register_update`.

**B4. `reset_stats`: простое «обнулить `frames`» ломает `fps` и даёт гонку.**
- Проба (эмуляция DESIGN: `_frames = 0; _reg.frames = 0` после 5 кадров):
```
frames after 5: 5 status: 5 seq: 5
tick after naive reset: [('fps', -4.9999954200071555), ('frames', 0)]
next item seq_id: 6 frames: 1
```
  `_tick_frames` (`plugin_base.py:371`, `:379`) остаётся 5 -> следующее окно публикует отрицательный `fps`. Сброс обязан трогать `_tick_frames` (и `_tick_t0`).
- Гонка: `produce()` делает `self._frames += 1; self._reg.frames = self._frames` без замка (`:464-465`), `reset_stats` пойдёт из потока команд. Чередование «produce прочитал N, reset записал 0, produce записал N+1» возвращает счётчик (сброс потерян); окно микросекунды, пробой не воспроизводил — чтение кода. Нужен замок на пару «инкремент + запись поля» и на сброс (`_stats_lock`; `self._lock` слота не годится, его держит `_on_frame` из потока владельца).
- Объём «stats» не определён: `dropped` (`:164`), `errors` сеанса (`session._errors`/`node_errors` сбросить нечем — публичного сброса нет), `_item_error`, метрики `frames`/`fps`/`dropped`. Решить: сбрасываются `frames`, `dropped`, `_item_error`, окно `fps`; `errors` — нет (счётчик жизни сеанса), записать в README; сразу после сброса `publish_metric("frames", 0)` (иначе уровень в дереве держит старое до 1 с).
- ACCEPTANCE:22 «seq_id продолжает счёт» без литерала. С живым сеансом число кадров недетерминировано (слот вытесняет кадры). Детерминированная форма: `_on_frame` + `produce()` пять раз -> `seq_id` 1..5; `reset_stats` -> `{"success": True}`, `get_status()["frames"] == 0`, `reg.frames == 0`, следующее окно `fps >= 0`, следующий item `seq_id == 6`.

**B5. `describe_params`: форма ответа не определена; положительный путь не принят; источник `params_meta` не решён.**
- Значение `ParamInfo` (`interface.py:45`) — frozen dataclass с `entries: tuple`; ответ — только dict (Dict at Boundary). Формат: `{"params_meta": {<поле>: {"min","max","inc","entries": list | None,"access"}}}`; узел, у которого `describe_param` вернул `None`/бросил, — пропущен или `null`? Решить и записать.
- ACCEPTANCE:20 проверяет только пустой путь (порт без `node_describe`). Нужен положительный: фейк по умолчанию (есть `node_describe`) при захвате -> `params_meta["exposure_time"]` с литералами `min/max/inc/access` узла `ExposureTime` из таблицы фейка (тестер берёт из `fake_port.py`), журнал: `describe_param` в потоке владельца (`calls[i][2] == ` потоку `open`). Без захвата: `{"success": False, "error": "сеанс не в захвате"}` (литерал из `session.call`, проба: `call after release: (False, 'сеанс не в захвате')`).
- Привязки для опроса — `bindings()` целиком (включая поля с `skip` в текущем плане), одним `call`, не по одному на узел; `PortError` на одном узле не должен ронять остальные.
- **Рекомендация по `params_meta` (решение лида): запрос через ящик (вариант Б), не сохранение в `ProfileRunner._step_of`.** Довод по коду: (1) `_step_of` (`profiles.py:168-178`) вызывается лениво при ПЕРВОЙ записи узла и кладёт только `info.inc`; шаги со `skip` и поля вне плана не описываются — `params_meta` была бы неполна по построению; (2) `ProfileRunner` создаётся заново на каждом цикле (`session.py:566`) и недоступен вызывающему — нужен новый публичный доступ в `session.py` и правка `profiles.py`, которых нет в FILES (+2 файла, +ловушка с замком профиля); (3) `describe_param` даёт текущее состояние (границы и `access` у узлов зависят от соседних, у фейка `TriggerMode` при захвате RO — `README` «Boundaries»), снимок при первой записи устареет; (4) вариант Б целиком в `plugin_base.py`, `call` уже сделан в 2.4a именно для этого. Минус Б: нужен захват (до `take_device` ответ — отказ; у варианта А до первой записи тоже пусто).

**B6. Срок, блокировка потока сообщений и сторож для команд через `call` не определены.**
- Все команды плагина без `executor` исполняются прямо в системном потоке `_message_processing_loop` (`system_threads.py:60-85` -> `router.receive` -> `_dispatch_command` `router_manager.py:1323-1380`, `handle_command` без `reply`); `register_update` (колбэк 2.4b) идёт тем же потоком (`plugin_orchestrator.py:743-750`, обычная команда). Значит блокирующий `call` в обработчике задерживает `register_update`, `state.changed` и остальной приём процесса. Дедлока нет (владелец не ждёт системный поток), но `call` ждёт до `timeout`, а если владелец уже исполняет `fn` — ещё до `watchdog_s` (`session.py:356-359`).
- Замер (`probe23c.py`, порт без кадров, `timeout_ms=500`): `call latencies: [0.397, 0.501, 0.501, 0.505]`; `call(…, 0.05) -> (False, 'срок') 0.054s`; при потоке кадров 0.020 с (`call while grabbing: (True, 42) 0.010s`). Итого: срок обязан быть больше `timeout_ms/1000` и больше окна перезахвата; в DESIGN нужна константа (рекомендация: `_CALL_TIMEOUT_S = 2.0` рядом с `_START_TIMEOUT_S`, `plugin_base.py:64`) и строка в README «Команды»: «блокирует приём команд процесса до срока».
- Сторож слеп к `fn` из `call`: `_execute` (`session.py:681-692`) вызывает `cmd.fn()` напрямую, не через `_port_call`, поэтому `_current` не выставляется и `on_stall` не сработает на зависший `describe_param`/`execute`; docstring `call` (`:356`) и README («дольше — зависание, ловит сторож») этого не выполняют. Исправление в одну строку: в `call()` ставить в ящик `lambda: self._port_call("call", fn)` (не в `_execute`: вложенный `_port_call` из `_drain` сбросил бы `_current`). Это `session.py` — его нет в FILES. Либо добавить файл (+ тест в hazards), либо исправить docstring/README и записать зазор.
- `TakeDeviceArgs(timeout_s)`/`ReleaseDeviceArgs(timeout_s)`: `cmd_take_device`/`cmd_release_device` данные игнорируют (`plugin_base.py:568`, `:584` — константы). Модель, объявляющая параметр, которого обработчик не читает, лжёт в `params_schema` (1.3 R-a). Либо обработчики читают `timeout_s` с границами (`gt=0`, `le` не больше `watchdog_s`: `timeout_s=3600` держит системный поток час), и в ACCEPTANCE строка `take_device {"timeout_s": 0.5}` -> `session.start(0.5)`; либо модели в 2.3c не вводить. Сейчас в тексте это не сказано.

**B7. FILES неполон; ссылки текста устарели или неверны.**
- DESIGN требует записать исключение в ADR-CAM-002 — это `Services/camera_device/DECISIONS.md`, его нет в FILES. `STATUS.md` ядра (README «Решения и план» на него ссылается) тоже. `session.py` — если принимается правка сторожа (B6).
- Раздела «Команды» в README нет (grep по `Services/camera_device/README.md`: заголовка нет, слово — только в docstring плагина); текст «записать в README («Команды»)» — создать раздел.
- Устаревшие ссылки: `fake_port.py:304-305` -> теперь `:321-322` (`_require_opened` до проверки capability — верно, строки сдвинулись); `README.md:130` (Р1) -> `:124`; `tasks/4.2a.md:30-31` (список команд) -> `:37`; `(имена фиксирует tasks/1.3.md R-a)` — НЕВЕРНО: `1.3.md` имён `TakeDeviceArgs`/`ReleaseDeviceArgs`/`ApplyParamsArgs` не содержит (`git grep -F TakeDeviceArgs -- plans Services` -> только `2.3c.md:14`), R-a требует лишь, чтобы `command_contracts` брался из `commands.py`. Кто вешает атрибут `command_contracts` на класс — 2.3c или 1.3 — не сказано; OUT OF SCOPE «`command_contracts` в реестре (1.3)» читается как «1.3», но тогда это стоит назвать (иначе разработчик добавит мёртвый атрибут или не добавит).

## Размер и разрез

Оценка (экспертная, не замеренная): как написано — 34–42 хода Sonnet при пределе ~30: 6 новых обработчиков с ответами, `_ensure_port` и хук привязки, замок статистики, модели + проводка `timeout_s`, README-раздел, ADR, два тестовых файла (≈ 12 + 6 тестов), break-injection hazards, плюс `plugin_base.py` уже 602 строки. Рекомендую разрез по механизму:
- **2.3c-A (≈ 22–26 ходов):** `commands.py` (три модели) + проводка `timeout_s`, `read_params`, `reset_stats` (замок, `fps`, объём stats), `apply_params`. Не требует ни ящика, ни SDK, ни решений владельца. Зависимость 1.3 (R-a, имена моделей) — только от A.
- **2.3c-B (≈ 24–28 ходов):** `_ensure_port`, `list_devices` (решение B1), `describe_params`, `trigger_software` (хук привязки), правка сторожа `call`, ADR-CAM-002, README. 4.2a и 1.3 (если нужны B-команды) зависят от обеих.
Если лид режет иначе — любой разрез должен держать `reset_stats`/`apply_params` отдельно от команд через `call`.

## Конфликты

- **readiness (Ф):** общие места — только словарь `commands` (`plugin_base.py:141-145`) и docstring класса «Команды:» (`:122-126`); метод `readiness` отдельным блоком конфликтует, если 2.3c и Ф правят эти строки. Развести: команды Р7 — одним новым разделом «# Команды Р7» после `cmd_release_device`, Ф — отдельным разделом ниже `cmd_get_status`. Если Ф читает `self._port`/`capabilities` — после `_ensure_port()` (B1) они доступны и до захвата, а `_sync_events` (`:410`) продолжит давать `[]` до первого создания порта.
- **4.2a:** список команд сходится: девять Р7 (`decisions.md:16`) = три базы + шесть новых, плюс `set_config` (generic, `base.py:1792`) и `register_update` (`plugin_orchestrator.py:743`) = ровно 11 из ACCEPTANCE 4.2a (`:37`). `trigger_software` регистрируется всегда (ответ-отказ без capability) — совпадает. Риск: «ровно» означает, что 2.3c не добавляет других команд (хелперов с `cmd_`-именами). 4.2a:`produce()` при `apply_params` < 50 мс: `apply_params` идёт в системном потоке, `apply` не блокирует — совместимо, при условии что замок статистики (B4) не держится вокруг чего-то медленного.

## Прочие замечания (не блокеры)

- N1. `Module contract: impl-only`, но `commands.py` — новый публичный модуль с моделями, которые импортируют 1.3 и 4.2a. Либо объявить «без `__all__`, < 50 строк» (правило пропуска), либо `lite` (docstring `Purpose/Public API/Stability`, `__all__`, контрактный тест).
- N2. Формат ответов: `status` (take/release/get_status) против `success` (новые) — потребителю (вкладка 4.4) нужны обе формы; причина — Р7, записать в README «Команды» одной таблицей, иначе тест 4.4 споткнётся.
- N3. `read_params` — снимок `session.params` последнего цикла, не живое чтение: после `release_device` вернёт старые значения (сброс — при следующем `start`, `session.py:558`). Назвать в README; ACCEPTANCE:19 корректен: на фейке после `take` `{"exposure_time": 10000.0}` (группа триггера не управляется -> шагов нет), `param_errors` пуст.
- N4. `неизвестное поле: <имя>` — имя из ввода попадает в ответ и (через логи) в журнал; сам `set_field_value` делает то же (`Поле 'nope' не найдено…`). Допустимо, но укоротить/`repr`, если лид хочет следовать пункту (iii) буквально.
- N5. ACCEPTANCE:25 (`git grep -nE "threading\.Thread|KeyedExecutor|ThreadPoolExecutor"`) сегодня пуст (запуск: `rc=1`) — красного до кода нет, это страж регрессии, не проверка новой логики; слепому тестеру пометить.
- N6. «Один тест с реальными объектами»: для `apply_params` явно потребовать проводку `RegistersManager` + `PluginOrchestrator._on_register_update` (образец — `Services/camera_device/tests/test_live_apply_wiring.py::_Rig`); с заглушкой `ctx.registers` колбэка 2.4b нет, и тест на журнал фейка окажется вакуумным.
- N7. `list_devices` на фейке: `журнал фейка без open` и `sdk.refs` назад — слабо: счётчик равен и когда `acquire` не звали. Сильнее: журнал `[acquire, enum_devices, release]` по порядку (вариант текста) или `enum_devices` в потоке `open` без лишнего `acquire` (рекомендованный вариант); `_FakeSdk.refs += 1` (`fake_port.py:164`) без замка — гонка hazard-теста «`list_devices` во время цикла старт/стоп» возможна на самом фейке, замок в фейк — вне FILES (`fake_port.py` добавить, если hazard нужен).
- N8. Литералы ACCEPTANCE:18 сверены с `_FakeSdk.enum_devices` (`fake_port.py:172-174`): `DeviceIdentity("serial", "FAKE-0001")`, `name=""` — верно.

## Вердикт

CHANGES REQUESTED. Блокеры B1–B7 (B1 — решение лида/владельца; B2–B6 — недостающие решения DESIGN и литералы ACCEPTANCE; B7 — FILES и ссылки) и разрез на A/B. Рекомендации: `params_meta` — через ящик (B5); `list_devices` — без исключения из Р1 (B1); сброс `fps` и замок статистики (B4). Раунд 2 стадии 0 после правки текста — тем же агентом (`SendMessage`).

## Что я оставил открытым / ненадёжно

- Безопасность `MV_CC_EnumDevices` при открытом/захватывающем handle на MVS: в репозитории замера нет, документацию вендора не читал, интернета не использовал. Все утверждения о ней — «не доказано», не «безопасно» и не «опасно». Нужен замер на стенде (0.5/6.2) или решение не нарушать Р1 (рекомендация).
- Гонку `reset_stats` с `produce()` (B4) не воспроизводил: окно микросекунды; воспроизведено только отрицательное `fps` на эмуляции наивного сброса (`_frames = 0; _reg.frames = 0` руками), а не на реализации — реализации ещё нет.
- Блокировку системного потока командой с `call` вывел по чтению (`system_threads.py`, `router_manager.py:1323-1380`, `plugin_orchestrator.py:743-750`), в живом процессе не запускал; замеры `call` — на фейке с `frame_period_s=5.0`, не на камере (README уже говорит: GigE `open` перезахвата 1–3 с).
- «`set_config` не будит подписчиков» — чтение `base.py:1839-1874` и `manager.py` (`_notify_observers` только в `set_field_value`), не запуск.
- Оценку ходов (34–42; A 22–26, B 24–28) дал экспертно: прошлые замеры по задачам ядра у лида, у меня их нет.
- Чего не успел: не проверял, что `Module contract: lite` потребовал бы по правилам репозитория для `commands.py` без `__all__`; не смотрел `tasks/2.3a.md`/`2.3b.md` на предмет уже занятых имён хелперов; `.sentrux/rules.toml` (граница ядра) не запускал — `commands.py` тянет `pydantic`, тест слоёв запрещает только вендорские импорты (`test_fake_port_hazards.py:160-210`), но README «Boundaries» («ядро импортирует только `multiprocess_framework` и stdlib») придётся поправить.
- Пробы лежат в scratchpad: `/private/tmp/claude-501/-Users-twokrai-Project-code-Inspector-bottles/422fbc6b-1296-4c1b-8072-6402b3628f21/scratchpad/probe23c.py` (запуск: `PYTHONUTF8=1 PYTHONPATH=<дерево> machine_gate.sh light inspector-bottles-20 <venv>/bin/python probe23c.py`; OSError 28 не встретился).

---

# Раунд 2 (reviewer, 2026-11-16): тексты `ca66c0bdd` (+ `588b0879a`)

Перечитал `tasks/2.3c.md` (19,8 КБ), новую `tasks/2.3d.md` (22,1 КБ), диф `e925ddb85..HEAD` по `plan.md`, `matrix.md`, `wave-protocol.md`, `amendments.md` (амендмент 8), `tasks/1.3.md`, `4.2a.md`, `2.4.md`, `2.4a.md`; номера строк кода из текстов сверены с деревом (`plugin_base.py:64-65, 122, 141, 238, 243, 359-379, 464-465, 510, 568, 584`; `session.py:55, 200-202, 335, 558, 566, 681`; `fake_port.py:108, 155, 164, 170, 321-322`; `README.md:124, 154, 160`) — совпадают.
Пробы: `scratchpad/probe23c_r2.py`, `probe23c_r2b.py` (настоящие `RegistersManager`, `PluginOrchestrator._on_register_update`, `WorkerManager`, фейк-порт; через `machine_gate.sh light inspector-bottles-20`).

## Вердикты

- **2.3c — CHANGES REQUESTED.** Два блокера (оба — правка нескольких строк текста), замечания R-1…R-7.
- **2.3d — CHANGES REQUESTED.** Один блокер (выбор пути `list_devices` по `state`), замечания R-8…R-14.
Правки механические; если лид внесёт их дословно, третий раунд не нужен (проверка `git grep` по тексту, как в раунде 2 стадии 0 Task 1.5, `amendments.md` §5а).

## Закрытие блокеров раунда 1

| # | Статус | Где закрыт / что осталось |
|---|---|---|
| B1 `list_devices`: порта нет до `take_device`; исключение из Р1 | закрыт, кроме выбора пути (см. 2.3d-B1) | `2.3d.md:18` `_ensure_port()`, `:22-28` три пути, исключение из Р1 снято; ловушка `_session_lock` — `:72` (верно: `plugin_base.py:511` `with self._session_lock` + вызов `create_port` внутри) |
| B2 `trigger_software`: нет `Binding` | закрыт | `2.3d.md:32` хук `software_trigger_binding`, ACC `:52-53` (в т.ч. чужой ключ -> `execute("Other")` в журнале; фейк так и ведёт: `fake_port.py:331-333` пишет вызов до проверки ключа) |
| B3 `apply_params` | закрыт частично (2.3c-B1 ниже) | `2.3c.md:30-33`, ACC `:50-54`; `session.apply` запрещён, `on_device`, порядок проверок, `extra="forbid"`, `registers is None` — есть |
| B4 `reset_stats` | закрыт, кроме мелочей (R-2, R-3, 2.3c-B2) | `2.3c.md:27-28` `_tick_frames/_tick_t0`, `_stats_lock`, `publish_metric` вне замка, ACC `:49, :55` |
| B5 `describe_params` | закрыт | `2.3d.md:30`, ACC `:50-51`; литералы фейка сверены запуском (ниже) |
| B6 срок, блокировка, сторож | закрыт | `_CALL_TIMEOUT_S = 2.0` `2.3d.md:20`; обёртка в `call()` `:34` (`session.py:335`; `_execute` `:681` не трогается — верно, вложенный `_port_call` из `_drain` сбросил бы `_current`); `timeout_s` с границами `2.3c.md:20, :23` |
| B7 FILES и ссылки | закрыт | DECISIONS/STATUS/`session.py`/`fake_port.py` в FILES 2.3d (`:41`); имена моделей 1.3 теперь согласованы (`1.3.md` R-a: атрибут `command_contracts` вешает 1.3); `4.2a.md` Dependencies +2.3c +2.3d, `matrix.md`, `plan.md`, `wave-protocol.md` согласованы |

Литералы 2.3d ACC 50 сверены запуском (`describe_param` при захвате, фейк по умолчанию): `exposure_time ParamInfo(min=6.0, max=9999746.0, inc=1.0, entries=None, access='RW')`; `trigger_mode entries=('Off','On'), access='RO'`; `trigger_source access='NA'`; `trigger_period_ms min=32 max=180000 inc=1 access='NA'` — совпадает с текстом (`entries` в ответе надо перевести в `list`, как записано). ACC 47: журнал фейка `[acquire, enum_devices, release]` — подтверждено (`p3.calls` имена). ACC 48 «`read_params` после `release_device` — те же `params`»: `{'exposure_time': 10000.0}` остаётся, `param_errors == {}` — подтверждено.

## 2.3c — блокеры

**2.3c-B1. Проверка (5) `validate_field_value` типы НЕ проверяет; «всё ДО первой записи» не выполняется.**
`2.3c.md:32` (5): «значение: `ctx.registers.validate_field_value` -> отказ -> …». Запуск (настоящий `RegistersManager`):
```
validate exposure_time 'abc'        -> (True, None)
validate trigger_mode 'SECRET-42'   -> (True, None)
validate frames 5                   -> (False, 'Недостаточно прав доступа: требуется уровень 0, передан 0')
```
Он проверяет только права. Типы и `Literal` проверяет запись (`apply_values` внутри `set_field_value`). Итог на пакете «хорошее, затем плохое»: `set_field_value(exposure_time, 900.0) -> (True, None)`, `set_field_value(trigger_mode, "SECRET-42") -> (False, "trigger_mode: Input should be 'Off' or 'On'")`, после чего `reg.exposure_time == 900.0` — частичная запись, против `2.3c.md:32` («ничего не записано при отказе») и ACC `:52`, `:54` (проверены только одиночные поля: `"abc"` -> прежнее значение верно лишь потому, что оно единственное).
Исправление: на фазе проверок прогнать пакет «пробной записью» на копии register'а: `reg.model_copy(deep=True).apply_values(params)` — атомарно (всё или ничего, ADR-DS-010), оригинал не меняется. Запуск: `copy.apply_values({"exposure_time": 900.0, "trigger_mode": "SECRET-42"}) -> (False, "trigger_mode: Input should be 'Off' or 'On'")`, `copy exposure after: 10000.0  original: 10000.0`; `{"exposure_time": "abc"} -> (False, 'exposure_time: Input should be a valid number, unable to parse string as a number')` — тексты pydantic без введённого значения. Ветку «отказ на фазе записи» (`:33`) оставить как остаточную (между пробой и записью значение register'а изменить может только другой писатель). ACC добавить: `{"params": {"exposure_time": 900.0, "trigger_mode": "SECRET-42"}}` -> `success False`, `"SECRET-42" not in error`, `reg.exposure_time == 10000.0`, в журнале нет `set_param`; контроль не вакуумный — следующий корректный `apply_params` доходит.

**2.3c-B2. ACC `:49`: литерал `seq_id == 6` противоречит соседней фразе про битый кадр.**
`:49` требует после пяти кадров «следующий item `seq_id == 6`» и, в той же строке, «отброшенный битый кадр до сброса». Битый кадр тоже получает номер: `_on_frame` увеличивает `_seq` до разбора (`plugin_base.py:326-328`). Запуск: 5 хороших кадров, 1 кадр `pixel_format="weird_fmt"` (`produce() -> []`, `dropped: 1`, `last_error: неподдерживаемый pixel_format weird_fmt`, `seq: 6`), потом хороший: `next good item seq_id: 7`. Слепой тестер, выбравший порядок «5 хороших, 1 битый, сброс, хороший», напишет 6 и получит красный от правильной реализации. Исправить: два явных литерала — без битого кадра `seq_id == 6`; с битым кадром между пятью хорошими и сбросом `seq_id == 7` (сброс `seq_id` не трогает, Р10).

## 2.3c — замечания (не блокеры)

- **R-1.** `_drop_frame` (`plugin_base.py:469-473`) делает `self._dropped += 1` и пишет `_item_error` из `produce()` без замка, а сброс обнуляет оба из потока команд: тот же класс гонки, что у `_frames`. `2.3c.md:28` называет под `_stats_lock` только пару `_frames`/`reg.frames` и окно fps — добавить `_dropped` и `_item_error`.
- **R-2.** Hazard ACC `:55` (и BREAK-INJECTION `:62`, «шанс гонки мал») по правилам проекта не доказывает ничего: тест, который почти никогда не краснеет без замка. Сделать перебив детерминированным: подменить `plugin._reg` прокси, у которого сеттер `frames` блокируется на `Event` (производитель между `self._frames += 1` и `self._reg.frames = …`), и из другого потока вызвать `reset_stats`: с замком `reset_stats` ждёт (проверка — `join` с коротким сроком и `is_alive`), без замка — возвращается сразу и итог `reg.frames != get_status()["frames"]`. Не проверял на реализации (её нет).
- **R-3.** `on_device` (`:33`) = «сеанс в `opening`/`grabbing`» врёт для поля с политикой `config` (или `None`): колбэк 2.4b на прибор ничего не шлёт (`plugin_base.py:251-252`), а ответ скажет `on_device: True`. Считать `on_device = сеанс идёт И хотя бы у одного поля политика live|restart` (`_apply_policy`, `:238`); ACC: поле с `apply="config"` в подклассе -> `on_device False`.
- **R-4.** Отказ на фазе записи (`:33`): в ответе не сказано, какие поля уже записаны. Добавить `"applied": [<уже записанные>]` к `success: False` (ранее записанные остаются — как записано).
- **R-5.** ACC `:50` («без сеанса») не говорит, на какой проводке: `ctx.registers` нужен настоящий (иначе ветка `registers is None`). Написать «на проводке `_Rig`, до `take_device`».
- **R-6.** Ошибка валидации `take_device`/`release_device` (`:23`): «текст» без правила; взять тот же построитель из `loc`+`msg`, что в `apply_params` (`:30`). Ключ словаря `params` с нестроковым именем попадёт в `loc` — это имя, не значение, допустимо.
- **R-7.** README: флаги групп (`trigger_managed`) `apply_params` отвергает (вне `bindings()`), а подписки на них нет (`_subscribe_fields` берёт ключи `bindings()`, `plugin_base.py:195`): флаг действует со следующего `take_device`; поэтому порядок «флаг -> поле» через `register_update` работает только для полей, остальное — после `take_device`. Одна строка в «Команды».

Размер 2.3c: текст 19,8 КБ, ≈ 7 тыс. токенов на чтение — не проблема. Ходы: правка `plugin_base.py` (проводка `timeout_s` x2, три обработчика, `_stats_lock` в четырёх местах, словарь и docstring) 8–10 правок + `commands.py` 1–2 + README 2 + красный/зелёный прогоны 5–6 + hazard 2 + чтение 4 + ruff/гейт 2 = **26–31 ход** (экспертная оценка, не замер). На пределе; в ограничителе — «по режиму волн break-injection не обязателен», его делать выборочно (3 строки из 5: удвоение `session.apply`, пакет без пробы, `_tick_frames`). Разрез не нужен.

## 2.3d — блокер

**2.3d-B1. Путь `list_devices` выбирается по `state`; при `closed` с живым владельцем путь 2 нарушает Р1.**
`2.3d.md:24`: «сеанса нет / `closed` (потока-владельца нет…) -> `acquire`, `enum_devices`, `release` из потока команды». Но `closed` не значит «владельца нет»: `stop()` на отказном состоянии ставит `closed` СРАЗУ (`session.py:314-316`), пока владелец ещё в `_cleanup`, и возвращается по сроку `timeout + timeout_ms/1000`. Запуск (фейк, `get_frame_errors=3`, `close` спит 2,0 с):
```
take: {'status': 'ok', 'device_state': 'error'}
after 3 get_frame errors: state=error held=True
after stop(0.05) (0.55s): state=closed held=True     <- владелец ещё внутри close/release
later: state=closed held=False
```
В окне `state=closed held=True` путь 2 звал бы `sdk.acquire/enum_devices/release` из потока команды параллельно `port.close()`/`sdk.release()` владельца — ровно то исключение из Р1, которое текст снял. Так же и для вопроса `:26` (отказные `busy`/`not_found`/`error`): правило «по состоянию» неверно, нужно правило по `device_held` (`session.py:227-230`, снимается вместе с финальным состоянием, `:590`):
1. `session is None` или `not session.device_held` -> путь 2 (потока-владельца нет): сюда же `idle`, `closed`, отказные состояния после выхода владельца;
2. `device_held` и `state == "grabbing"` -> путь 1 (`call`);
3. `device_held`, любое другое состояние (`opening`, `stopping`, отказ или `closed` при живом владельце) -> `{"success": False, "error": "сеанс не в захвате"}`.
ACC `:56` (первый hazard: «`list_devices` вплотную после `release_device`») при исправной `release_device` окна не достигает: `stop()` ждёт `exited` (`session.py:322`), владелец к возврату уже вышел — тест зелёный при любой реализации (ни одной красной под инъекцией «путь 2 по `state == closed`»). Заменить детерминированным: `close` фейка спит 1–2 с (`port.close = slow`), три ошибки `get_frame` -> `error`, `session.stop(0.05)` -> `state == "closed"`, `device_held` истинно; в этом окне `list_devices` -> `{"success": False, "error": "сеанс не в захвате"}`, в журнале нет `acquire`/`enum_devices` до выхода владельца. Добавить к BREAK-INJECTION: выбор пути по `state` -> красный этот тест. Остаточный риск (не блокер, записать в README/ADR): между проверкой `device_held` и `acquire` поток команды не конкурирует с `start()` только пока `start()` зовёт тот же системный поток (`cmd_take_device`); хук `start()` плагина (`auto_start`) может идти из другого потока — не проверялось.

## 2.3d — замечания (не блокеры)

- **R-8.** Путь 2 (`:24`): `release` в `finally` должен начинаться только ПОСЛЕ успешного `acquire` (иначе падающий `acquire` у `MvsSdk.acquire` — `PortError("other")` при `available() == False`, `driver.py` — потянет `release` и `RuntimeError("release without acquire")`). И отказ `enum_devices`/`release` на пути 2 (`PortError`) в тексте не описан: ответ `{"success": False, "error": describe_error(exc)}`.
- **R-9.** README/ACC про срок (`:20`, `:57`): худший случай блокировки команды — `_CALL_TIMEOUT_S + watchdog_s` = 2 + 5 = 7 с, когда владелец взял `fn` и завис (`session.py:353-359`), а не «до срока». Записать оба числа.
- **R-10.** ACC `:50` («вызовов `describe_param` ровно по числу привязок»): журнал уже содержит `describe_param` от `ProfileRunner._step_of` при открытии (`profiles.py:168-178`; на фейке по умолчанию — для `exposure_time`, группа триггера выключена); считать от длины журнала ДО команды.
- **R-11.** ACC `:51` («узел, у которого `describe_param` бросает `PortError`»): как получить — не сказано. Запуск: `describe_param` по неизвестному ключу узла бросает `PortError describe_param: other`, закрытый порт — `PortError describe_param: closed`. Предложить: подмена `port.describe_param` одним ключом после `take_device`.
- **R-12.** Размер. Девять файлов, код в трёх (`plugin_base.py`: `_ensure_port` с ловушкой замка, три обработчика, хук; `session.py` — одна строка; `fake_port.py` — замок), три тестовых файла (≤ 10 + hazards + 1 в существующем) и три документа плюс `python -m scripts.sync`, `scripts/validate.py` (оба есть) и `git grep`-проверки: **32–40 ходов** (экспертная оценка), выше предела ~30. Рекомендация: документы — отдельным шагом цепочки `tech-writer` после GREEN (README «Команды», ADR-CAM-002, `STATUS.md`, sync/validate; файлы документов код-автор не правит, одного исполнителя на файлы это не нарушает); у `developer` остаётся ≈ 24–30. Либо оставить как есть и заранее принять риск 3-й итерации -> `teamlead`.
- **R-13.** Hazard ACC `:56`, второй: `list_devices` при захвате параллельно `release_device` из другого потока допустимо, но в живом процессе оба идут одним системным потоком (последовательно) — тест проверяет `call` против `stop`, а не боевой порядок; переписать цель: «`call` против `stop` даёт один из трёх текстов» (как записано) без утверждений о продакшн-порядке.
- **R-14.** Заготовка readiness (Ф): конфликт только по `commands` и docstring (оба — добавление строк, `2.3c.md:36`, `2.3d.md:16`) — приемлемо; `_ensure_port()` делает `capabilities` доступными до захвата, а `_sync_events` (`:410`) продолжает давать `[]`, пока порт не создан — записано (`2.3d.md:74`).

## Противоречия между 2.3c/2.3d, Ф и 4.2a

Новых нет. Набор команд: 3 прежние + 3 (2.3c) + 3 (2.3d) = 9 Р7 (`decisions.md:16`); с `set_config` (generic, `base.py:1792`) и `register_update` (`plugin_orchestrator.py:743`) — ровно 11 из `4.2a.md:37`; `trigger_software` регистрируется всегда (ответ-отказ) — совпадает. Порядок 2.3b -> 2.4a -> 2.4b -> 2.3c -> 2.3d одинаков в `plan.md`, `2.4.md`, `wave-protocol.md`, `matrix.md`; `1.3.md` зависит только от части A; в `4.2a.md` обе. ACC 2.3c `:56` и 2.3d `:54` не пересекаются (3 + 3 + 3). `commands` по `expects_full_message`: `CommandManager.register_command` по умолчанию `False` (`command_manager.py:209`) — обработчик получает `data`, как `cmd_set_config`; значит `{"timeout_s": 0.5}` — реальная форма аргументов.

## Что я оставил открытым / ненадёжно (раунд 2)

- Реализаций нет: все утверждения о коде — по чтению и по пробам на ТЕКУЩИХ объектах (`validate_field_value`, `apply_values` на копии, `closed + held`, литералы `describe_param`, номер `seq_id`); поведение будущих `_stats_lock`, `_ensure_port`, `call`-обёртки не проверял.
- Окно `state=closed held=True` воспроизвёл с искусственно медленным `close` (2,0 с) и `stop(0.05)`: в живом процессе длина окна зависит от вендорского `close`; что `release_device` в таком окне возвращает «ещё закрывает» — прочитано (`plugin_base.py:585-588`), в этой пробе не запускалось.
- Гонку `reset_stats`/`produce()` не воспроизводил (R-2 — предложение, не проверенное).
- Остаточный риск «`start()` хука из другого потока при `list_devices` на пути 2» — не проверялся (порядок запуска хука и цикла сообщений процесса я не читал).
- Оценки ходов (2.3c 26–31, 2.3d 32–40) экспертные, не замеры.
- Безопасность `MV_CC_EnumDevices` в межпроцессном случае по-прежнему не доказана и не опровергнута (в тексте честно записана как открытая, не блокер — согласен).
- Не проверял `python -m scripts.sync`/`validate.py` запуском (только что скрипты существуют: `scripts/sync`, `scripts/validate.py`).
