# План: считыватель ID3000 в GUI прототипа — показ в дисплее рецепта + настройки (slug `code-reader-gui`)

- **Slug:** `code-reader-gui` · **Ветка:** `feat/code-reader-gui` · **Дата:** 2026-10-15 · **Статус:** DRAFT
- **Родители:** [`qr-code-reader.md`](qr-code-reader.md) (заменяет его Ф3: Task 3.1–3.4),
  [`code-reader-sdk.md`](code-reader-sdk.md) (строит на Ф6: `sdk/`, `core/sdk_*`, плагин `code_reader_sdk`).
- **Решение владельца 2026-10-15:** первая итерация = (1) кадр + код (обводка по углам, текст, статус
  ok/no_code/bad_code, счётчики) в **существующих дисплеях рецепта** через pipeline; (2) настройки
  считывателя из GUI — минимум режим триггера, экспозиция, усиление. ПЛК, Modbus, FTP — отложены.
- **Директива владельца (через координатора, 2026-10-15):** максимум готовых механизмов, кода меньше,
  функция та же (принципы №1, №4, ponytail). Каждая задача несёт «Что переиспользуем» и «Что НЕ пишем».

## Обзор

Источник `code_reader_sdk` уже отдаёт item с кодами (углы, статус) и серым кадром через SHM. Показ
собирается из готового: источник добавляет в item данные отрисовки `overlay` (числа, не картинку), готовый
плагин `overlay_draw` рисует их на кадре, готовый механизм `displays:` выводит результат. Настройки —
поля register'а `code_reader_sdk` с `FieldMeta`: их **уже** рисует и живьём шлёт в процесс инспектор ноды
Pipeline. Новый код — только там, где готового нет: get/set узлов GenICam в `sdk/api.py` и применение
параметров к прибору.

## Что проверено кодом (2026-10-15, manager)

| Факт | Источник |
|---|---|
| В `MvCodeReaderCtrl.dll` (каталог плагина IDMVS, 95 экспортов, разбор PE-таблицы без загрузки DLL) есть `MV_CODEREADER_Get/Set{Int,Float,Enum,Bool,String}Value`, `SetEnumValueByString`, `SetCommandValue`, `XML_GetNodeInterfaceType`, `XML_GetNodeAccessMode` | `C:\Program Files (x86)\IDMVSSTD\Applications\Win64\plugins\mvsidcamctrl\MvCodeReaderCtrl.dll` |
| Сигнатуры (V1.5.3): `GetIntValue(h, char*, MV_CODEREADER_INTVALUE_EX*)` (int64 cur/max/min/inc + 16 uint резерва); `SetIntValue(h, char*, int64_t)`; `GetFloatValue(h, char*, MV_CODEREADER_FLOATVALUE*)` (float cur/max/min + 4 uint); `SetFloatValue(h, char*, float)`; `GetEnumValue(h, char*, MV_CODEREADER_ENUMVALUE*)` (cur, num, 64 значения, 4 резерва); `SetEnumValue(h, char*, unsigned)`; `Get/SetBoolValue(h, char*, bool*/bool)`; всё `__stdcall` | `Development.zip` → `Modules/MvCodeReaderSDK/Include/MvCodeReaderCtrl.h:603–739`, `MvCodeReaderParams.h:382–417` |
| Ошибки GenICam `0x80020100–0x800201FF`: `E_GC_RANGE 0x80020102`, `E_GC_ACCESS 0x80020106` | `MvCodeReaderErrorDefine.h:34–44` |
| Узлы `ExposureTime`, `Gain`, `TriggerMode`, `TriggerSource`, `TriggerSoftware`, `RunningMode`, `QualityEnable`, `LightBrightness`, `UserSetSave` существуют в каталоге IDMVS (только имена, типов там нет) | `C:\ProgramData\IDMVSSTD\Local\Features.xml` |
| На **старой** камере (MVS SDK): `ExposureTime = 880`, `Gain = 0`, `TriggerMode = 1`, `TriggerSource = 0` (Line0, список `[7,0,1,2,4,5,6,8,9,10,12,15]`); **параметры триггера при запущенном захвате не пишутся** (`0x80000106`) | `Services/code_reader/docs/GENICAM.md` |
| Новая камера `Manufacturer = GEV`: общий MVS SDK видит 0 устройств, MvCodeReader SDK — видит и отдаёт кадры; IDMVS без `encryption.key` её не показывает | `docs/claude/memory/reference_idmvs_gev_reader_needs_encryption_key.md` |
| Инспектор ноды Pipeline рисует типизированные редакторы по `FieldMeta` любого register'а (`rm.get_fields(plugin_name)` → `CardsFieldFactory`), правка → `SetPluginConfig` → `PluginConfigChanged` → `register_update` IPC → `PluginOrchestrator._on_register_update` → `RegistersManager.set_field_value` | `frontend/widgets/tabs/pipeline/inspector/params_form_section.py:138–182`, `pipeline/mutations.py:94`, `frontend/app.py:729–774`, `generic/plugin_orchestrator.py:422–457` |
| `RegistersManager.subscribe(register, field, callback)` зовёт callback при `set_field_value`; плагин держит тот же экземпляр (`ctx.registers.get_register`) — **ни один плагин этим ещё не пользуется** | `registers_module/core/manager.py:151,190`, `plugins/base.py:1476–1482`, `git grep` по `Plugins/`, `Services/` — 0 вызовов |
| `overlay_draw`: вход `frame` (`image/bgr`) + `overlay` (`dict`: `lines[{p1,p2,color}]`, `points[{xy,label,color}]`), выход `frame`; шрифт подписи зашит `0.4`; `image/gray → image/bgr` несовместимы по `are_ports_compatible` | `Plugins/render/overlay_draw/plugin.py:33–41,140–152`, `multiprocess_framework/modules/process_module/plugins/port.py:27–29` |
| Дисплей GUI принимает серый 2D (`Format_Grayscale8`) | `frontend/widgets/displays/preview_window.py:423–427` |
| Ни один рецепт не держит processing-плагин в одном процессе после source | скан 21 рецепта (скрипт в scratchpad, вывод пуст) |
| Снапшот всех полей register'ов: новые поля `code_reader_sdk`/`overlay_draw` его меняют | `frontend/forms/tests/snapshots/catalog_register_fields.txt:73–86,251+` ← `test_catalog_kind_roundtrip.py` |

## Решения плана (входят в DESIGN задач)

1. **`code_view` не пишем.** Отрисовка — готовый `overlay_draw`; источник кладёт в item `overlay` (данные:
   4 отрезка по углам каждого кода, цвет по статусу; подпись с текстом кода; строка «статус + счётчики» в
   левом верхнем углу). Прецедент «источник данных выдаёт `overlay`» — `line_filter`. Картинка по-прежнему
   только под `frame` (ADR-CR-007 не задет).
2. **`overlay_draw` расширяем, не копируем:** вход `frame` → `image/*`, серый 2D переводится в BGR перед
   рисованием (иначе цвет статуса теряется); поле register'а `label_scale` (по умолчанию `0.4` — прежнее
   поведение у всех рецептов). Существующие провода `image/bgr → image/*` остаются валидными.
3. **Рецепт — расширяем `qr_reader_sdk_demo.yaml`**, третьего не заводим: процесс `draw` (`overlay_draw`),
   провод `reader_sdk.code_reader_sdk.frame → draw.overlay_draw.frame`, `blueprint.displays:
   draw.overlay_draw.frame → main`, top-level `displays: [main]` 1280×1024. `overlay` едет в том же item —
   второго провода и join-режима нет.
4. **Настройки — поля register'а `CodeReaderSdkRegisters`:** `trigger_mode: Literal["On","Off"]`,
   `exposure_time: float` (мкс), `gain: float` (дБ), `quality_enable: bool`. Пределы `FieldMeta` — широкие;
   настоящие пределы прибор отдаёт в `Get*Value` (min/max) и они публикуются в дерево.
5. **Прибор не трогаем без явного желания:** пишутся только поля, заданные в рецепте (ключ есть в
   `ctx.config`) или изменённые живьём из GUI. Иначе значения по умолчанию register'а затёрли бы настройку
   прибора, сделанную в IDMVS. Фактические значения после открытия читаются и публикуются
   (`state.code_reader_sdk.params`).
6. **Запись — только между `OpenDevice` и `StartGrabbing`** (параметры триггера при захвате не пишутся).
   Живая правка = перезахват прибора тем же путём, что `release_device` + `take_device`. Названный потолок:
   правка стоит ~0,5–1 с, срабатывания в это окно теряются. Триггер вернуться — линия, где это окно
   мешает (тогда запись экспозиции/усиления без перезахвата, если прибор её примет).
7. **Ошибка записи одного узла не роняет сессию:** код — главный продукт; отказ → `param_errors[узел]`
   с кодом в hex + `last_error`, остальные узлы пишутся, захват стартует.
8. **Сохранение в `UserSet` прибора — вне объёма:** записи живут до перезапуска питания (на старой камере
   `TriggerMode` переживал Close/Open, в `UserSet` не сохранялся). Источник правды — рецепт.
9. **Программный триггер с ПК не делаем** (решение владельца: боевой триггер аппаратный). `TriggerSource`
   только читается и публикуется.

## Порядок выполнения

Спеки задач (Level / Assignee / Goal / Что переиспользуем / Что НЕ пишем / DESIGN / Files / REDS /
Acceptance criteria / Out of scope): [Фаза 1](code-reader-gui/phase-1.md) ·
[Фаза 2](code-reader-gui/phase-2.md) · [Фаза 3](code-reader-gui/phase-3.md). Раскладка многофайловая:
одним файлом план — 48 КБ при лимите 32 КБ.

### Фаза 1 — показ
- Task 1.1: ⚑ Базовый прогон `qr_reader_sdk_demo` на новой камере [PENDING]
  - **Module contract:** n/a
- Task 1.2: **[VERTICAL SLICE]** Кадр с обводкой и текстом в дисплее рецепта [PENDING] (после 1.1)
  - **Module contract:** public-api-change (`overlay_draw`: тип входного порта, поле register'а; `code_reader_sdk`: ключ item)

### Фаза 2 — настройки
- Task 2.1: Get/set узлов GenICam в `sdk/` [PENDING] (параллельно с 1.2 — файлы не пересекаются)
  - **Module contract:** public-api-change (`sdk.api.MvCodeReaderApi`)
- Task 2.2: Параметры в сессии и плагине: register → прибор → дерево [PENDING] (после 2.1, 1.2)
  - **Module contract:** public-api-change (`SdkCodeReader(params=…)`, `stats()["params"]`, поля register'а)
- Task 2.3: Секция «Считыватель кодов» во вкладке Services [PENDING — только по слову владельца, см. ESCALATION]
  - **Module contract:** impl-only

### Фаза 3 — стенд и приёмка
- Task 3.1: ⚑ Живой стенд: показ + настройки на новой камере [PENDING] (после 1.2, 2.2)
  - **Module contract:** n/a
- Task 3.2: Документы сервиса + ревью фазы + приёмка `cto` [PENDING] (после 3.1)
  - **Module contract:** n/a

**Критический путь:** 1.1 → 1.2 → 2.2 → 3.1 → 3.2 (2.1 идёт параллельно 1.2).

## Общие правила для всех задач

- **Конвейер (CLAUDE.md «Task launch convention»):** стадия 0 — `reviewer` `MODE: plan` на тексте задачи
  (синхронно) → стадия 1 — `tester` вслепую, один раз на механизм, в worktree на коммите до кода, приёмочные
  строки ниже **финальные** → стадия 2 — исполнитель → стадия 3 — break-injection (предсказания лидера
  записываются в план ДО прогона; прогон матрицы — `haiku`) → стадия 4 — живой стенд числами → стадия 5 —
  `reviewer` синхронно, вердикт на фиксированный SHA.
- **Лимит итераций: 2** на любой цикл (тест ↔ код, ревью ↔ правка); 3-я — эскалация на уровень выше
  (`developer` → `teamlead` → `cto`) форматом `ESCALATION -> <роль>`. Лимит повторяется в брифе каждого
  вложенного агента.
- **Все тест- и стенд-команды — через гейт:** `bash "$(git rev-parse --path-format=absolute
  --git-common-dir)/../scripts/machine_gate.sh" <класс> <session> <cmd…>`; `<session>` — имя из брифа
  лидера. Классы: один файл тестов — `light`; `pytest Services/code_reader/tests` или
  `pytest multiprocess_prototype/recipes/tests` — `medium`; стенд, матрица инъекций — `heavy` (только в окне).
- **Порог исполнителя:** 1–3 файла — лидер сам (сказать вслух); 4–9 — `developer` → `teamlead`; 10+ —
  `manager`. Агенты не коммитят и не пушат — это пишется в каждом брифе.
- Слои: `Services/code_reader` не импортирует `Plugins`/`multiprocess_prototype`; `Plugins/render/overlay_draw`
  не импортирует `Services`/`multiprocess_prototype` (ADR-120). Между процессами — только dict.
- Шаги с ⚑ требуют руки владельца (нажать кнопку триггера, поднести код, подтвердить глазом). Перед любым
  стендом: IDMVS закрыт, VPN выключен, ПК `192.168.1.100/24`, прибор `192.168.1.10`.

---

---

## Сводка: задача → что переиспользуем → сколько нового

| Задача | Переиспользуем | Новый код (оценка) |
|---|---|---|
| 1.1 | рецепт как есть, `backend_ctl`, `mvcr_probe.py` | 0 |
| 1.2 | `overlay_draw`, `displays:`, SHM, `CodeRead.corners` | ~30 строк в `sdk_plugin.py`; ~10 в `overlay_draw`; ~25 строк YAML; тесты |
| 2.1 | `_call/_check`, `SdkError`, форма `hikvision_camera/core/parameters.py`, `mvcr_probe.py` | ~70 строк `api.py`; ~30 `structures.py`; ~30 `mvcr_probe.py` |
| 2.2 | `register_update` → `RegistersManager.subscribe`, `take/release_device`, `_publish_state` | ~50 строк `sdk_reader.py`; ~30 `sdk_registers.py`; ~50 `sdk_plugin.py` |
| 2.3 (условно) | `ParamsFormSection`, `SetPluginConfig`, поиск процесса из `hikvision/presenter.py` | 1 файл ≤ 100 строк + 1 строка регистрации |
| 3.1 | `backend_ctl`, `qt-mcp`, GUI unattended | 0 |
| 3.2 | шаблоны документов сервиса | только документы |

Без 2.3: **0 новых файлов кода, 0 новых виджетов, 0 новых плагинов, 0 новых рецептов**; ~13 правленых
файлов кода/данных (порог 10+ — план manager'а).

## ESCALATION -> owner (через лидера)

```
ESCALATION -> owner
Question: Достаточно ли для первой итерации настроек в инспекторе ноды Pipeline (готовая форма по FieldMeta, 0 строк GUI-кода), или секция во вкладке Services обязательна (Task 2.3: 1 файл ≤ 100 строк)?
Tried: проверил кодом — инспектор Pipeline уже рисует поля любого register'а и живьём шлёт register_update в процесс (params_form_section.py:138, app.py:729); общей register-формы во вкладке Services нет, секции там ручные по устройствам (_sections.py:209–233).
Blocked on: решение 2 владельца («секция в Services») и директива «ноль новых виджетов» расходятся.
Files: plans/code-reader-gui.md (Task 2.3), multiprocess_prototype/frontend/widgets/tabs/services/_sections.py
```
Рекомендация плана: Task 2.3 не делать в первой итерации; вернуться, если оператор не находит настройки в Pipeline.

## Риски и ограничения

- **H1 (Task 1.2):** item доезжает до `draw` целиком — не проверено чтением framework. Ложь → нужен второй
  провод + join (как `line_filter_inspect`), +1 правка рецепта, без нового кода.
- **Первый пользователь `RegistersManager.subscribe` в бэкенде** — живой путь не прогонялся ни одним плагином.
- **Типы узлов на новой камере не сняты** (GEV, `V4.0.2.R`); на старой сняты через MVS SDK, которого GEV-прибор
  не видит. Закрывается стендом 2.1 до стадии 1 задачи 2.2.
- **Пишутся ли экспозиция/усиление при захвате — неизвестно** (снято только про триггер); выбран перезахват
  для всех — дороже на ~0,5–1 с, зато одно правило.
- **Записи не переживают питание прибора** (решение 8); IDMVS на этом приборе без `encryption.key` не работает
  — настраивать прибор вне прототипа сейчас нечем.
- Каждое срабатывание теперь кодирует кадр `(1024,1280,3)` BGR (~3,9 МБ) в SHM процесса `draw` — на ручных
  нажатиях не нагрузка; на скорости линии не мерилось.

## Что я оставил открытым / ненадёжно

- H1 и H2 (Task 1.2) — гипотезы; первый шаг developer'а их проверяет.
- Размеры структур в приёмке 2.1 (96 / 28 / 280 Б) посчитаны мной в уме по заголовку; tester обязан
  пересчитать независимо — моё число не эталон.
- Как секция Services достаёт диспетчер `SetPluginConfig` — не проверял (Task 2.3).
- Шрифт: `label_scale 1.2` на дисплее 1280×1024 «читаем» — предположение; подбирается на стенде 3.1.
- Дисплей `main` 1280×1024 — по кадру старой камеры; фактическое разрешение новой снимается в 1.1.
- Задержка «триггер → экран» не измеряется (на ПК нет метки времени аппаратного триггера) — как и в Ф6.

## Итоги (заполняются по ходу)

_пусто_

---

## Дополнение 2026-10-15 (по итогам стенда с видимым GUI) — владелец

**Пожелания владельца к показу (входят в Task 1.2, не отдельный план):**
1. **Рамка кода цветом по состоянию:** зелёная — код прочитан (`ok`), красная — не прочитан / плохой (`no_code`, `bad_code`); при необходимости третий цвет (код есть, но не читается). Рамка — по четырём углам `codes[].pt` из item (уже приходят от SDK-ноды), рисует готовый `overlay_draw`.
2. **Результат писать в GUI:** текст кода и статус не только в инспекторе, а на экране (подпись у рамки на кадре и/или строка результата рядом с дисплеем + счётчики `ok / no_code / bad_code`). Где именно — решить в Task 1.2 по готовым механизмам (подпись `overlay_draw`, существующая панель состояния), без нового виджета, если хватает.

**Дефекты, найденные на стенде (нужны задачи/проверка, до слияния любой правки по ним — tester, инъекция, reviewer):**
- **D1. Падение GUI на сером кадре — ИСПРАВЛЕНО в рабочем дереве, не закоммичено, не принято.** `multiprocess_prototype/frontend/widgets/image_panel/presenter.py::on_frame` читал любой кадр как 3-канальный BGR; серый `image/gray` → нативное падение `0xC0000005` (faulthandler: `presenter.py:97`). Исправление и 4 теста автора (`image_panel/tests/test_on_frame_shapes.py`, 28 passed в каталоге). **Не сделано по конвенции:** независимый `tester` (до кода — уже поздно, значит `reviewer` + инъекция), инъекция «вернуть всегда BGR» → какие из 4 тестов краснеют (предсказать до прогона; старая ветка роняет интерпретатор, а не ассерт — тест уходить в подпроцесс), ревью `reviewer`.
- **D2. Кадр не идёт на дисплей сразу после старта**, пока рецепт не активирован заново (`routing={'reader_sdk': 'main'}` при старте, при перезагрузке рецепта кадр пошёл). В карточке рецепта «Дисплеи: 0» при одной привязке. Порядок инициализации дисплея/подписки не разобран.
- **D3. Нативное падение процесса не видно в наблюдаемости:** в логах только `ProcessManager: gui crashed exitcode=3221225477`; `faulthandler` только по `INSPECTOR_STALL_DUMP=1` в `frontend/app.py`. Предложение: включать `faulthandler` в `process_runner` для каждого процесса в его лог-каталог, supervisor ссылается на файл. Решение — владелец (framework).
- **D4. Живой прогон с терминатором `\n` и `NoRead` без `;` не сняли:** счётчики SDK-ноды против TCP-ноды после смены рецептов на стенде не собраны (см. `Services/code_reader/docs/SETUP_GEV_V4.0.2.R.md` §10). Повторить в окне stand.

Принцип владельца: один надёжный механизм передачи кадра источник → дисплей для всех рецептов (образец — `Services/hikvision_camera` в `hikvision_letter_robot.yaml`: кадр BGR через `color_convert`); форма/формат кадра не должны ронять GUI.

---

## Дополнение 2026-10-15: механизм надёжности кадров (запрос владельца — постоянная автоматическая защита от падений GUI)

Владелец: хочет механизм, который **постоянно и в реальном времени** выясняет и не допускает такие падения, и **пишет в логи, какой формат пришёл, какой ожидался** и т. п. Задачи ниже не входят в вертикальный срез 1.2, идут отдельной фазой после ревью спеки; исполнители и порядок — по конвенции проекта (тестер до кода, инъекция на каждое свойство, `reviewer` после каждой).

### Task R.1 — Проверка кадра на входе дисплея в реальном времени (frame guard)
**Level:** Senior (Opus teamlead) · **Layer:** prototype/frontend (+ framework, если проверка живёт в display_module)
**Goal:** любой кадр, пришедший на слот дисплея, проверяется до отрисовки; несовпадение не роняет процесс, а пишется в лог и в метрики.
**Что пишем в лог (одна строка на слот, троттлинг, как у `неизвестный slot_id`):** `slot_id`, источник (процесс.плагин.порт), **ожидали** (`format` дисплея из рецепта, ожидаемая форма W×H), **пришло** (`shape`, `dtype`, число каналов, contiguous/нет, nbytes), действие (показан / заглушка «Ошибка кадра»). Счётчики в статистику: принято, показано, отброшено по форме — по слоту.
**Что переиспользуем:** `image_panel/presenter.py::on_frame` (точка входа, 4 ветки формы уже есть), логер `get_std_logger`, `StatsManager`/телеметрия для счётчиков, `FieldMeta`-описание `format` из `domain/entities/display.py`. **Не пишем:** второй путь отрисовки, новый логер.
**Acceptance:** кадр каждого типа из таблицы R.2 → ожидаемый результат, процесс жив; в логе строка с ожидали/пришло; счётчик отброшенных растёт; повтор того же несоответствия не заливает лог (одна строка, затем счётчик).
**Out of scope:** автоконвертация форматов между портами (это решение о контракте портов).

### Task R.2 — Контрактный тест форм кадров (в подпроцессе)
**Level:** Middle (Sonnet tester, ДО R.1) · **Goal:** красный тест вместо мёртвого pytest.
Параметризация: gray `(H,W)`, `(H,W,1)`, BGR, BGRA, `uint16`, `float32`, не-непрерывный срез (`frame[:, ::2]`), пустой, `None`, очень большой. Каждый кейс — в подпроцессе (`multiprocessing`/`subprocess`) с join-дедлайном; код выхода ≠ 0 или таймаут = провал. Форма и ожидаемый результат — литералы в тесте, не выводятся из кода.
**Break-injection:** вернуть «всегда BGR» → предсказать набор красных ДО прогона (минимум: gray, `(H,W,1)`); убрать проверку `ndim` → предсказать.

### Task R.3 — Правило рецепта: тип порта ↔ формат дисплея (до запуска)
**Level:** Middle (Sonnet developer) · **Goal:** `image/gray` на дисплей с несовместимым форматом — ошибка загрузки рецепта (gate-валидатор), а не падение в рантайме.
**Переиспользуем:** существующий gate-валидатор рецептов (его проверяет `test_qr_reader_sdk_demo.py`), `dtype` порта у `PortSpec` (`image/gray`, `image/bgr`). **Acceptance:** `qr_reader_sdk_demo` с `format: GRAY` — проходит; с `BGR` на серый порт — отказ с текстом «порт X отдаёт image/gray, дисплей Y ждёт BGR».

### Task R.4 — `faulthandler` в каждом процессе + проверка самой наблюдаемости
**Level:** Senior (Opus teamlead) · **Layer:** framework (`process_manager_module/runner/process_runner.py`) — решение владельца.
**Goal:** нативное падение оставляет стек в лог-каталоге процесса; supervisor в строке `crashed` ссылается на файл. **Тест:** дочерний процесс намеренно падает (`ctypes` обращение по нулевому адресу в подпроцессе-фикстуре) → в логе есть `Windows fatal exception` и стек. Выключается флагом (ручка наблюдаемости: вкл/выкл, ноль нагрузки выключенной).

### Task R.5 — Дымовой прогон GUI без железа (offscreen)
**Level:** Senior · **Goal:** поднять GUI с `QT_QPA_PLATFORM=offscreen`, подать источником-симулятором кадры каждого типа, проверить счётчик показанных кадров (`R.1`) и что `gui` не упал, **и что кадр идёт сразу после старта, без перезагрузки рецепта** (дефект D2). Запуск — через `scripts/machine_gate.sh`, класс по замеру.

**Порядок:** R.2 (тестер, красные) → R.1 → R.3 → R.4 → R.5; R.1 и R.3 независимы после R.2. Критический вопрос владельцу: R.4 меняет framework (универсальность — принцип №1), подтвердить, что включение по умолчанию допустимо.
