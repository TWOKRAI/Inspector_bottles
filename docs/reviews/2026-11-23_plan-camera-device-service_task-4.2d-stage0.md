# Ревью стадии 0 — Task 4.2d (хвосты W4: gain_auto, enabled_if, m3)

- Режим: `MODE: plan` на одну Task. Файл задачи: `plans/2026-10-18_camera-device-service/tasks/4.2d.md` (в git не отслеживается, `??`).
- Дерево: `main`, `b57349f68`. Грязные файлы дерева не мои: `command_panel.py`, `OPEN_QUESTIONS.md`.
- Код и тесты не правил, не коммитил. Создан только этот отчёт (и скрипт репро в scratchpad).
- Сессия гейта: `camera-K-4.2d-stage0`.

## Вердикт: CHANGES REQUESTED

Часть A (gain_auto, enabled_if): DESIGN достаточен, developer не принимает решений сам.
Часть B (m3): дыра. Проводка контроллера не имеет ни источника, ни теста.
Гейт в записанном виде не запустится.

## Что проверил запуском (в main, до правки)

Скрипт: `scratchpad/repro_4_2d.py`, запуск через `machine_gate.sh light`.

| Вход | Наблюдаемый результат |
|---|---|
| `HikvisionCameraRegisters.model_fields` | 31 поле; `gain_auto` нет; индексы: `exposure_auto`=15, `exposure_time`=16, `gain`=22 |
| `get_all_fields_meta()`, поле `enabled_if` у `gain` и `exposure_time` | `None`, `None` |
| `build_plan(R, {..., exposure_auto: Off/Once/Continuous}, BINDINGS)` | `exposure_time.skip = None` во всех трёх случаях. Половина дефекта (запись экспозиции при `ExposureAuto != Off`) воспроизведена на уровне плана |
| `build_plan(...)`, порядок шагов | `exposure_auto, exposure_time, gain, frame_rate_enable, frame_rate` |
| Копия DESIGN A на подклассе `CameraDeviceRegisters` (`exposure_time`+`enabled_if`, `gain_auto`, `gain`+`enabled_if`) | `Off`: четыре шага `skip=None`, `parent` у потомков = `exposure_auto` / `gain_auto`. `Continuous`: `exposure_time.skip = "не нужен: exposure_auto=Continuous"`, `gain.skip = "не нужен: gain_auto=Continuous"`. `Once`: тексты "не нужен: ...=Once" у обоих |
| `check_bindings(R, BINDINGS, vendor_fields=set(fields)-set(BINDINGS))` | не бросает (для `missing` тавтологично) |

Вывод: тексты `skip` из ACCEPTANCE (строки 57-58) совпадают с тем, что даёт `params._skip_reason`. Порядок «родитель раньше потомка» работает.
Половина про `gain` в main невоспроизводима: поля `gain_auto` нет. Ни `FakeMvCamera` (`tools/mvs_probe.py`, `_set`), ни `FakePort` не моделируют запрет записи `Gain` при `GainAuto != Off` (по чтению кода). Дефект наблюдаем только на приборе.

Проверено чтением (не запуском): `plugin_base._changed_steps` при правке `gain` с `gain_auto=Continuous`. Шаг был `skip` и остался `skip`, `_needs_apply` ложно, `steps=[]`, сеанс не трогается. При смене `gain_auto` с `Continuous` на `Off` возвращаются `[gain_auto, gain]` в порядке плана.

Запуск тестов не удался. Команда `machine_gate.sh medium ... pytest <3 пути>` дала `reclassified medium -> heavy (pytest_multi_dir)`, затем `NO WINDOW - skipped`. Один каталог `Services/hikvision_camera/tests` дал `STAND WINDOW - skipped` (чужое окно). Базовые числа «зелёно на main» не получены.

## Ответы на пункты брифа

### 1. Ссылки и допущения

| Ссылка из задачи | Результат |
|---|---|
| `driver.BINDINGS`, образец `exposure_auto` | Верно (`driver.py:67-77`). Добавляется `"gain_auto": Binding("genicam", "GainAuto", "enum")` |
| `plugin/registers.py`, `gain` на строке 32, перед ним вставлять | Верно. `exposure_time` переобъявлен (`apply="restart"`), `enabled_if` ему добавить можно |
| `params.build_plan`, `_skip_reason`, `Step.parent` | Верно, см. таблицу запуска |
| `check_bindings` | Сигнатура `(register_cls, bindings, vendor_fields)`. В коде вендора не вызывается (только тесты ядра). Для REDS 6 нужен литерал `vendor_fields`, в задаче его нет (N5) |
| `registers_base.py`: порядок, `exposure_auto` | Верно: `exposure_auto` перед `exposure_time` в базе; в классе вендора позиции 15 < 16 |
| `fake_port.py`: умеет ли фейк узлы | **По-разному.** Умолчательный `make_port()`: узлы только `TriggerMode, TriggerSource, TriggerSelfTriggerPeriod, ExposureTime`; `_node()` на чужой ключ бросает `PortError("other")`. Запись `mvs_MV-CS020-10GC.json` содержит `GainAuto`, `Gain`, `ExposureAuto`. `FakeMvCamera` (`tools/mvs_probe.py:195-197`) тоже. Журнал есть у обоих: `FakePort.calls` (`("set_param", (key, value), tid)`) и `FakeMvsCamera.journal` через `core_rig._quiet(cam)`. **REDS 4 реализуем без правки фейка** (N1) |
| `presenter.py`, `controller.py`: откуда `registers_manager` | Services-вкладка: `section.py:60` вызывает `build_hikvision_controls(runtime=self._runtime)`; у `RuntimeDeps` поле `registers_manager` есть (`runtime_deps.py:118`). **Встройка инспектора** (`pipeline/inspector/hikvision_embed.py:35`): `runtime = SimpleNamespace(command_sender=..., topology_bridge=...)`, `registers_manager` нет (B1) |
| `app.py:882`, порядок `set_value` -> IPC | Верно: `set_value` (881-889), затем `send_command` (894+). `set_value` - псевдоним `set_field_value`, возвращает `bool` (`manager.py:452`) |

### 2. Сломает ли поле другие снимки и тесты

- `test_driver_mvs.py:301 test_bindings_набор_ключей` - точное равенство словаря «ключ -> узел». С новым ключом станет красным (по чтению). FILES это предусматривает условно. Занести в предсказания лида как ожидаемый красный (N5).
- `catalog_register_fields.txt`: `test_catalog_kind_roundtrip.py` сравнивает `sorted(found)` и `sorted(snapshot)`. Добавить строку обязательно; порядок строк тест не проверяет. Других потребителей `hikvision.gain` в снимке нет (`git grep`: одна строка, 198).
- `test_plugin_on_core_contract.py`: `set(driver.BINDINGS) <= set(model_fields)` остаётся зелёным; число полей register-а нигде не пинится (по `git grep`).
- `test_hikvision_recipes.py:54` берёт `set(model_fields)`: добавление поля безопасно.
- Тесты на `cam_cls=_gated_cam()` (`FakeMvCamera`) получат лишнюю запись `GainAuto=Off`; узел там есть. Тесты на `port=make_port(), bindings=FAKE_BINDINGS` не затронуты. Тест с умолчательным `make_port()` и `driver.BINDINGS` не нашёл (`git grep "bindings="` в тестах hikvision: только `FAKE_BINDINGS`).
- Не проверено запуском: что ни один тест не пинит полный журнал записей.

### 4. Размер

Оценка в ходах Sonnet (суждение, не замер):
- Часть A (driver 1 строка, registers 2 правки, снимок, `test_driver_mvs`, прогон каталогов): ~10-12.
- Часть B (презентер: kw + цикл с внутренним try + warning; контроллер 1 строка; регрессия; прогон): ~10-12.
- Hazard-тесты автора + ruff + гейт по каталогам: ~6-8.
- Патчи инъекций P1-P7 (и недостающие, N6): ещё ~7-10.

Итого ~33-42 при одном исполнителе, выше предела 30. Если патчи инъекций уходят Haiku-прогону по предсказаниям лида, остаётся ~26-32: на пределе. После B1 (проводка + тест контроллера) ещё +4-6.
**Рекомендация:** разрезать на 4.2d-A (driver, registers, снимок, `test_driver_mvs`) и 4.2d-B (presenter, controller, их тесты). `Files:` не пересекаются, каждая ~15-20 ходов.

## Блокеры

### B1. Часть B: цель m3 не проверяется, проводка контроллера не обеспечена

Вход 1: `build_hikvision_controls(services, runtime=SimpleNamespace(command_sender=cs, topology_bridge=tb), request_runner=r)` (так вызывает встройка инспектора, `hikvision_embed.py:35`) -> `getattr(runtime, "registers_manager", None)` даёт `None` -> `set_parameters` не зовёт `set_value` -> форма инспектора показывает старое значение. Дефект m3 остаётся именно там, где «форма инспектора» и есть цель (заголовок задачи, DESIGN B).
Вход 2: убрать из `controller.py` передачу `registers_manager` целиком -> все тесты из REDS, ACCEPTANCE и P1-P7 остаются зелёными: они проверяют только презентер со шпионом. Контроллер в FILES, но у него нет ни REDS, ни ACCEPTANCE, ни P. Свойство «Применить обновляет форму» не имеет теста.

Что исправить:
1. Решить явно. Вариант (а): только Services-вкладка (`section.py`, `RuntimeDeps`), а встройка инспектора уходит строкой в `OPEN_QUESTIONS`. Вариант (б): `hikvision_embed.py` в FILES и сказано, откуда он берёт менеджер (какой аргумент ему передаёт вызывающий; я это не читал).
2. Добавить ACCEPTANCE и REDS: `build_hikvision_controls` передаёт `registers_manager` из `runtime` презентеру. Проверка по наблюдаемому эффекту: `controller._on_apply_params(30, 900, 2)` при `runtime.registers_manager` = шпион, и шпион получил три `set_value`.
3. Один тест на настоящих объектах (правило «фейк-набор + один настоящий»): `RegistersManager(registers={"hikvision": HikvisionCameraRegisters()})` + презентер со шпионом на `command_sender`. После `set_parameters(30, 900, 2)` значения `frame_rate/exposure_time/gain` в менеджере равны `30.0/900.0/2.0` (литералы).
4. Добавить мутацию P8: убрать передачу в контроллере.

### B2. Гейт medium по четырём каталогам не запустится

Вход: `machine_gate.sh medium camera-K-4.2d-stage0 python -m pytest Services/hikvision_camera/tests <ещё пути>` -> `reclassified medium -> heavy (pytest_multi_dir)` -> `NO WINDOW - skipped`. Строка ACCEPTANCE «Gate medium по четырём каталогам зелёный» недоказуема; предотчётный гейт developer-а получит тот же отказ.
Что исправить: записать гейт отдельными командами `medium`, по одному каталогу на команду: `Services/hikvision_camera/tests`, `Services/camera_device/tests`, `multiprocess_prototype/frontend/widgets/tabs/services/hikvision/tests`. Для форм взять один файл `multiprocess_prototype/frontend/forms/tests/test_catalog_kind_roundtrip.py` (целый `forms/tests` вероятно больше medium; число файлов не считал). Если `Services/camera_device/tests` (29 файлов) сам окажется `timed` или `heavy`, вписать окно в бриф. Пометить: код 75 - не красный.

## Замечания

### N1. Назвать фейк для REDS 4 и двух строк ACCEPTANCE про живой сеанс
Сейчас «сеанс на фейке» допускает `make(FAKE_PORT_CFG, port=make_port())` с `driver.BINDINGS` по умолчанию. Узлов `ExposureAuto/Gain/GainAuto` там нет, `PortError("other")`, непустой `param_errors` с первой записи (по чтению `_node()`, не прогонял). Слепой тестировщик получит красный не от того. Указать: либо `core_rig.make(cfg, cam_cls=_gated_cam())` и журнал `_quiet(cam)` (узлы есть), либо `from_recording(mvs_MV-CS020-10GC.json)` с `bindings=driver.BINDINGS` и журнал `port.calls`. DESIGN A.6 остаётся верным: правка фейка не нужна.

### N2. `param_errors == {}` на фейке не различает «до» и «после»
Фейки принимают запись `Gain` при `GainAuto=Continuous` (`FakeMvCamera._set` запирает только `locked`-узлы при захвате). Различает только журнал: нет `("MV_CC_SetFloatValue", ("Gain", ...))` в `_quiet(cam)` (или `("set_param", ("Gain", ...))` в `port.calls`). Сейчас условие только в REDS 4; в двух строках ACCEPTANCE (живой сеанс, правка `gain` по `register_update`) его нет. Без него P2 и P3 убивает только план-тест. Внести литерал в обе строки. Для правки `gain`: после `register_update("gain", ...)` в журнале нет `StopGrabbing` (перезахвата не было).

### N3. Режим `Once` не определён
Копия DESIGN даёт для `Once`: `gain` и `exposure_time` получают `skip` "не нужен: ...=Once". Поведение: каждый `take_device` снова пишет `GainAuto=Once` и никогда не пишет значение `gain` из рецепта; прибор сам возвращает узел в `Off`, register остаётся `Once`. В «Hazard-тестах автора» `Once` назван без ожидаемого результата, в ACCEPTANCE его нет. Лид решает и записывает литералом (оставить как есть допустимо, но сказать словами и вписать ожидание).

### N4. Текст про порядок строк снимка противоречит файлу
DESIGN A.5 и ACCEPTANCE: «строка `hikvision.gain_auto` перед `hikvision.gain`». Файл отсортирован (`sort -c` молчит), а `sort` ставит `hikvision.gain` перед `hikvision.gain_auto` (проверено запуском). Тест порядок игнорирует (`sorted` с обеих сторон) и не упадёт, но буквальное исполнение ломает сортировку. Заменить на «после `hikvision.gain`, перед `hikvision.packet_delay`».

### N5. REDS 6 не красный; предсказания лида не совпадут
- `check_bindings` для вендора уже не бросает на main (`BINDINGS` входит в поля), значит пункт 6 до реализации зелёный, а не «должен упасть». Чтобы он убивал P1, тесту нужен литерал `vendor_fields` (задачей не задан; вычисление `fields - BINDINGS` тавтологично для `missing`).
- Ожидаемый красный `test_driver_mvs.py::test_bindings_набор_ключей` в REDS нет. Вписать в предсказания.

### N6. Дыры в Break-injection P1-P7
Свойство без мутации:
- Часть B: `set_value -> False` подавляет IPC (в ACCEPTANCE есть, в P нет); `fps <= 0` всё же зовёт `set_value("frame_rate")`; значение не приведено к `float` (шпион-литерал `30.0`); контроллер (B1).
- Часть A: умолчание и значения `gain_auto` (`Literal` без `Once`, умолчание не `Off`): REDS 2 есть, P нет. `Continuous` только у одного из родителей: P2 и P3 надо убивать раздельно, а в ACCEPTANCE сейчас сценарий «оба сразу». `apply` поля не `restart`.
- Менеджер `None`: регрессия опирается на существующий `test_hikvision_commands.py`; мутации нет (P9: убрать проверку на `None`).
- Hazard «повторный `take_device` после смены `gain_auto` с `Continuous` на `Off`» без P.
- P4 покрыт строкой ACCEPTANCE 55 («стоит раньше»): тут дыры нет.

### N7. FILES неполон и неточен
- В TESTS назван новый файл `multiprocess_prototype/frontend/widgets/tabs/services/hikvision/tests/test_hikvision_presenter_m3.py`. В шапке FILES его нет (там только `test_hikvision_commands.py`). Правило «файл вне FILES -> стоп» остановит исполнителя. Внести.
- Module contract: `public-api-change`. README и STATUS `Services/hikvision_camera` в FILES нет. В README упоминания `gain` общие (строки 32, 112, 149, 171, 189), перечня полей register-а не нашёл. Вероятно правка не нужна, но решение лида не записано.

### N8. DESIGN B.2: двусмысленность
Фраза «значение в лог не писать целиком не требуется (число допустимо)» содержит двойное отрицание. Написать прямо: в `warning` идут имена регистра и поля; значение допустимо. Порядок «перед `send_command` каждого поля» записать точной последовательностью событий (`set_value(frame_rate), send(frame_rate), set_value(exposure_time), send(exposure_time), ...`), иначе тест может принять «все `set_value`, потом все `send`». Внутренний `try` вокруг `set_value` нужен отдельно от внешнего: иначе P7 даёт `(False, [])` и теряет оставшиеся поля.

### N9. Часть C уже в рабочем дереве
`command_panel.py` изменён (`M`): добавлен абзац `FROZEN (4.2d, A1): ...` и лишняя пустая строка после модульного docstring (шум форматтера, вне «одной строки»). Не блокер. Коммитит только лид, вместе с остальным.

### N10. Эхо `set_value` -> IPC не проверено
Путь `app.py:882` опирается на то, что у GUI-менеджера нет `send_callback` (комментарий 850-860). Для вкладки Hikvision не проверено, что подписчики поля в форме инспектора на `set_value` не порождают второй `register_update` (двойная отправка). Проверить на живом объекте в стадии 5.

## Пересечения с чужими полосами

- `plans/queue/inbox/2026-11-23_inspector-bottles-53_*`: совпала только строка «presenter.py» в пункте про Пульт; файлы 4.2d не затронуты (прочитан один пункт из 53_1; по двум другим файлам только `grep -l`, совпадений нет).
- Общий файл `catalog_register_fields.txt`: любая полоса, добавляющая поле плагина, правит его; возможен конфликт слияния.

## Что я оставил открытым / ненадёжно

1. **Тесты не запускал.** Гейт отдал отказ (`reclassified medium -> heavy`, `NO WINDOW`; затем `STAND WINDOW - skipped`). Утверждение, что `test_bindings_набор_ключей` станет красным и остальные тесты не пострадают, основано на чтении кода. Базовые зелёные числа main не получены.
2. **Копия DESIGN проверена на подклассе `CameraDeviceRegisters`, не на настоящем `HikvisionCameraRegisters`.** Позиция `gain_auto` перед `gain` в `model_fields` настоящего класса и работа `get_all_fields_meta()` для переобъявленного `exposure_time` с `enabled_if` не прогонялись.
3. **Дефект «`Gain` при `GainAuto != Off` -> `param_errors`» не воспроизведён нигде.** Воспроизведена только половина про `exposure_time`, на уровне плана. Реакция настоящего прибора неизвестна (пункт 4 `OPEN_QUESTIONS`: не проверено). Решение скипать при `Once` - гипотеза лида, на приборе не проверена.
4. **Живую правку `gain` при `Continuous` и смену `Continuous -> Off` проверил чтением `_changed_steps`, не запуском.**
5. **N1: поведение умолчательного `FakePort` при записи `GainAuto` вывел из кода `_node()`, не запуском.**
6. **B1: не читал, как `hikvision_embed` получает аргументы у вызывающего**, поэтому не знаю, есть ли у него `registers_manager` выше по цепочке. Не проверил, показывает ли встройка инспектора ту же форму, что и вкладка.
7. **Оценка размера** - суждение, не замер.
8. **Не читал:** `Services/camera_device/session.py` (как сеанс обрабатывает шаг `skip` при перезахвате), README, STATUS и DECISIONS вендора целиком, два из трёх файлов inbox 53_*.
9. **Записи `OPEN_QUESTIONS` пунктов (1)-(5) читал частично:** прочитаны (6), (7) и итоговый абзац «не проверено».

---

# Раунд 2 (2 из 2 максимум): задачи 4.2d (часть A) и 4.2e (часть B)

Тот же ревьюер. Читал `plans/2026-10-18_camera-device-service/tasks/4.2d.md` и `tasks/4.2e.md` (обе в git не отслеживаются, `??`). Код, тесты и фейки не правил, не коммитил. Скрипты репро в scratchpad: `repro_4_2e.py`, `repro_4_2d_session.py`.

## Вердикты

- **Task 4.2d: APPROVED** (три замечания для брифа tester; блокеров нет).
- **Task 4.2e: APPROVED** (три замечания; блокеров нет).

Блокеры раунда 1 закрыты: B1 (охват и тесты контроллера), B2 (гейт по одному каталогу). Новых блокеров не нашёл.

## Что проверено запуском

### 4.2d, REDS 4-6 через путь пункта 7 (FakeMvCamera + core_rig)

Скрипт `repro_4_2d_session.py` (через `machine_gate.sh light`; настоящий плагин, `core_rig._Rig(MonkeyPatch(), cfg, cam_cls=_gated_cam())`). Поля `gain_auto` в main ещё нет, поэтому прогон идёт на `exposure_auto` как заместителе; механика журнала та же.

| Вход | Наблюдаемый результат (main, до правки) |
|---|---|
| `cfg = {exposure_auto: Continuous, gain: 5.0}`, `take()` | `ok`; записи: `SetEnumValueByString(ExposureAuto, Continuous)`, `SetFloatValue(ExposureTime, 10000.0)`, `SetFloatValue(Gain, 5.0)`, `SetBoolValue(AcquisitionFrameRateEnable, False)`. `param_errors == {}` |
| `register_update("gain", 6.0)` при захвате, окно журнала сразу после возврата | **0 записей**. Через 1.0 с в окне весь перезахват: `StopGrabbing, CloseDevice, DestroyHandle, EnumDevices, CreateHandle, OpenDevice, ...`, затем `SetFloatValue(ExposureTime, ...)` |
| `cmd_release_device`, затем `rm.set_field_value("hikvision", "exposure_auto", "Off")` -> `(True, None)`, затем `take()` | `ok`; записи: `ExposureAuto Off`, `ExposureTime 10000.0`, `Gain 6.0` (значение из register-а, внесённое правкой выше) |

Выводы:
1. Журнал записи у `FakeMvCamera` через `_quiet(cam)` есть и показывает `ExposureTime` и `Gain` при `Continuous`. До правки `param_errors == {}` тоже пуст: решение N2 раунда 1 (журнал, а не `param_errors`) верное и необходимое.
2. REDS 4 и REDS 6 исполнимы без правки фейка. Цикл release -> смена поля register-а -> take работает (сеанс в `closed` правку не принимает, значение входит в план следующего `take`).
3. REDS 5 исполним, но с ловушкой (N1 ниже): перезахват асинхронный, сразу после возврата `register_update` окно пусто.

Узел `GainAuto` у `FakeMvCamera` есть (`tools/mvs_probe.py:197`). Запись `GainAuto` с чтением обратно на настоящем коде не прогонял: поля ещё нет; вывод по аналогии с `ExposureAuto`.

### 4.2e, REDS 5-6

Скрипт `repro_4_2e.py` (`QT_QPA_PLATFORM=offscreen`, настоящие объекты, спаи sender, runner, topology):

| Вход | Наблюдаемый результат (main, до правки) |
|---|---|
| `build_hikvision_controls(services=SimpleNamespace(topology=FakeTopology()), runtime=SimpleNamespace(command_sender=spy, topology_bridge=None, registers_manager=настоящий RegistersManager), request_runner=SyncRunner())` | Собирается без исключений; `sender.sent == []`, `sender.requests == []` после сборки |
| `controller._on_apply_params(30.0, 900.0, 2.0)` | Метод есть (`controller.py:79`). `sender.sent` = ровно три `register_update` (`frame_rate 30.0`, `exposure_time 900.0`, `gain 2.0`) в процесс `camera` |
| `RegistersManager(registers={"hikvision": HikvisionCameraRegisters()}).set_value("hikvision", f, v)` для `frame_rate 30.0`, `exposure_time 900.0`, `gain 2.0` | `True`, `True`, `True`; `get_register("hikvision")` даёт `30.0 900.0 2.0`. Sender после трёх `set_value` новых сообщений не получил (у менеджера нет пути к sender) |

Выводы: REDS 5 (контроллер) и REDS 6 (настоящий менеджер) исполнимы без обходов. Фикстура `qapp` берётся из `pytest-qt` (`pyproject.toml:61`, `qt_api = "pyside6"`); локальной в каталоге нет.

## Размер (оценка, не замер)

- **4.2d: ~18-22 хода Sonnet** на GREEN + hazard + гейт: чтение `driver.py`, `registers.py`, файла tester (3-4); правки `driver.py`, `registers.py` (2-3), снимок и `test_driver_mvs` (2); прогоны `test_4_2d_acceptance` (2-3), три гейта по одному каталогу (3), ruff (1); hazard-тесты автора (3-4). Патчи инъекций P1-P7 (семь пар «правка, прогон, откат») по цепочке идут Haiku-прогону, не автору; если автор делает их сам, выходит ~34-38: больше 30.
- **4.2e: ~14-18 ходов:** презентер (kw, внутренний `try`, `warning`: 1-2 правки), контроллер (1), чтение файла tester (1-2), красный и зелёный прогон (2-3), гейт одного каталога (1), ruff (1), hazard-тесты автора (2-3). Патчи P1-P8 идут Haiku-прогону.

## Замечания (не блокируют)

### 4.2d

- **N1. REDS 5: отрицательное утверждение пусто без ожидания.** Измерено: сразу после возврата `register_update("gain", 6.0)` окно журнала содержит 0 записей, полный перезахват виден через 1.0 с. Тест «в журнале нет `StopGrabbing` и нет `Gain`», проверенный сразу, зелёный и без правки; красный-гейт tester его отбросит как не красный. Записать в бриф tester: отсутствие проверять после ожидания не меньше 1.0 с (или после положительного барьера по следующему событию очереди владельца), не сразу.
- **N2. REDS 6: общий register с REDS 5 даёт другое значение.** В моём прогоне после правки `gain=6.0` второй `take` писал `Gain 6.0`, а не исходное `5.0`. Если REDS 5 и REDS 6 делят один `rig`, литерал REDS 6 равен `6.0`. Рекомендация: отдельный `rig` на каждый REDS, литерал `5.0`.
- **N3. Мутации.** P1-P7 покрывают REDS 1-4 (P1-P3 убивают REDS 3 по плану и REDS 4 по журналу). Не покрыто: `exposure_time` при `Once` (аналог P6: добавить `"Once"` в `enabled_if` у `exposure_time`); у REDS 6 нет убийцы (любая мутация, пишущая `Gain` всегда, например P2, оставляет его зелёным). Допустимо назвать REDS 6 регрессионным стражем без мутации, но сказать это в предсказаниях лида. Остальное из раунда 1 учтено: порядок снимка (N4), `test_bindings_набор_ключей` в FILES (N5, N7).

### 4.2e

- **N4. P6 выживет при проверке равенством.** REDS 1 ждёт `set_value(hikvision, frame_rate, 30.0)`, вызов идёт с целыми `30, 900, 2`. В Python `30 == 30.0` истинно, поэтому после удаления `float(...)` (P6) тест на равенство остаётся зелёным; то же в REDS 6 (`30.0 == 30` в настоящем менеджере). Нужна проверка типа: `type(v) is float` для аргумента `set_value` и для значения в payload sender-а. Иначе предсказание лида «P6 убивается» не сойдётся.
- **N5. «Эхо `set_value` второй отправки не создаёт»: REDS 6 это не проверяет.** В моём прогоне у менеджера нет пути к sender: три `set_value` не добавили ни одного сообщения. Значит «ровно три `register_update`» истинно для любой реализации и не может упасть из-за эха. REDS 6 доказывает другое и нужное: значения проходят настоящую валидацию менеджера (`30.0`, `900.0`, `2.0` в границах) и ложатся в него, а sender получает ровно три. Свойство «в живом приложении у GUI-менеджера нет `send_callback`, подписчики формы не шлют второй IPC» остаётся на комментарии `app.py` и в `OPEN_QUESTIONS`. Переписать фразу в DESIGN п. 4 и REDS 6: убрать «эхо» из того, что проверяет тест.
- **N6. Записи в `OPEN_QUESTIONS` про встройку инспектора нет.** Задача говорит «вопрос в `OPEN_QUESTIONS`», но `grep -F hikvision_embed docs/claude/OPEN_QUESTIONS.md` пуст. Без записи вопрос потеряется: внести строку («Применить» во встройке инспектора не зовёт `set_value`: у `hikvision_embed.py` нет `registers_manager`) до слияния.

## Что я оставил открытым / ненадёжно

1. **Тесты не запускал.** Оба одиночных каталога (`Services/hikvision_camera/tests`, `multiprocess_prototype/frontend/widgets/tabs/services/hikvision/tests`) через `machine_gate.sh medium` дали `STAND WINDOW - skipped` (чужое окно). `Services/camera_device/tests` и `test_catalog_kind_roundtrip.py` в раунде 2 не запускал. Базовые зелёные числа и ожидаемый красный `test_bindings_набор_ключей` основаны на чтении. Окно не ждал и в цикле не опрашивал.
2. **REDS 4-6 для 4.2d прогнаны на заместителе** (`exposure_auto`) на текущем коде, не на реализованном `gain_auto`. Что `GainAuto` через `FakeMvCamera` пишется и читается так же, как `ExposureAuto`, вывел по аналогии (узел в таблице есть), не запуском.
3. **Скип при `Once`** (решение лида, DESIGN п. 4) остаётся гипотезой: реакция прибора на запись `Gain` при `Once` не воспроизведена нигде. Задача страхует планом, не лечит наблюдённый отказ (так и записано в DESIGN).
4. **Асинхронность REDS 5:** 1.0 с измерено на `FakeMvCamera` с `_gated_cam()`, один прогон; на загруженной машине запас может быть другим. Число не пинить, называть барьер.
5. **Не проверял**, что `DevicesPresenter` и `DeviceComboController` внутри `build_hikvision_controls` не шлют сообщений при других `runtime` и `services` (мой набор спаев их не вызвал: `sent` и `requests` после сборки пусты). Тест REDS 5-6 должен фильтровать `sent` по `command == "register_update"`.
6. **Пересечения 4.2d и 4.2e по файлам** сверял по спискам `Files:` в текстах, не по дереву; общий файл `catalog_register_fields.txt` остаётся точкой конфликта с другими полосами (раунд 1).
7. **Оценка размера** — суждение, не замер.
