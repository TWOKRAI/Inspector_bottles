# План: сервис «Пульт» (control_panel)

**Ветка:** `feat/pult-control-panel`
**Slug:** `pult-control-panel`
**Статус:** фазы 1–5 закрыты (5.4 `monitor` отложена и перенесена в Phase 6); **Phase 6 «Пульт оператора 1.0» — на утверждении владельца** (ORDER #15–#17, 2026-11-15).

> Smoke (pult_demo): Services-таб грузится, 4 контрола рендерятся, нажатие «Старт» →
> `out_1 = True` в логе ноды. Поймал баг: секция без `action_buttons()` роняла весь
> Services-таб (unit-тесты спеки не ловили — добавлен регресс-тест на поверхность
> SectionProtocol). Добавлено подтверждение удаления контрола (защита от случайного ✕).

## Цель

Отдельный сервис-пульт: пользователь во вкладке **Services → «Пульт»** создаёт контролы
(кнопка / тумблер / слайдер / поле числа-текста), а нода `control_panel` в pipeline
**эмитит сигналы** с этих контролов на выходные порты. Порты вяжутся к потребителям
в редакторе Pipeline (например: координаты роботу, слово, триггер).

Решения владельца (2026-06-15):
- GUI пульта живёт **во вкладке «Пульт» в Services** (там и создаёшь контролы, и нажимаешь их).
  Нода в pipeline — только источник сигналов.
- Контролы v1: **кнопка (триггер), тумблер (вкл/выкл), слайдер (число в диапазоне),
  поле числа/текста**.
- **Рецептность:** контролы хранятся **в рецепте** (поле `controls` ноды `control_panel`
  в `blueprint`). У каждого рецепта свой набор кнопок/слайдеров. При старте плагин читает
  `controls` из конфига; GUI-правки (add/remove/update) **сохраняются обратно в рецепт**
  при save (Phase 2) — а не только live-командой в рантайм.

## Архитектура

Обобщение сигнального механизма `phone_camera` (signal_1..3 уже работают end-to-end):
вместо хардкод-кнопок — контролы, заданные конфигом, и динамический GUI.

- **Слой:** `Services/control_panel/` (как `phone_gateway`, но **без HTTP** — чисто GUI + плагин-источник).
- **Порты:** фиксированный пул выходных портов `out_1..out_8` (dtype `any`), как сигнальный
  пул телефона. Каждый контрол ссылается на свой `out_N`. Динамические именованные порты
  (через `port_schemas` ноды) — **follow-up Phase 2+**, чтобы не трогать редактор в v1.
- **Контракт на границе:** контролы — `list[dict]` (Dict-at-Boundary), Pydantic внутри.

```
Services/control_panel/
  __init__.py
  interfaces.py        # тип контрола + протокол
  controls.py          # ControlSpec (id,type,label,port,min,max,step,value) + валидация + дефолт-значение
  README.md  STATUS.md
  plugin/
    __init__.py
    plugin.py          # ControlPanelPlugin (source): produce() дренит pending-эмиты
    config.py          # ControlPanelConfig: panel_id + controls: list[dict] + N портов
    registers.py       # ControlPanelRegisters (hold_last=True)
  tests/
    test_controls.py
    test_plugin.py
```

## Фазы

### Phase 1 — Backend-плагин `control_panel`
**Assignee:** Director/teamlead · **Layer:** services

- `controls.py`: `ControlSpec` (тип∈{button,toggle,slider,number,text}, label, port=out_N,
  min/max/step/default для числовых, value). Валидация + коэрция значения по типу.
- `plugin.py`: `ControlPanelPlugin(ProcessModulePlugin)`, `category="source"`, `name="control_panel"`.
  - `outputs` = пул `out_1..out_8` (Port, dtype `any`).
  - `produce()`: `items = self._drain_emits()` → `{port: value, "data_type":"signal", "control_id":...}`
    (по образцу `phone._drain_signals`). Без живого источника кадров.
  - Команды: `get_controls`, `set_control{id,value}` (обновить+эмитнуть), `emit_control{id}`
    (кнопка-триггер), `add_control{spec}`, `remove_control{id}`, `update_control{id,patch}`.
  - Публикация в state: `control_panel.controls` (специи + значения) для реактивного GUI.
- `config.py`: `panel_id`, `controls: list[dict]`, `port_count` (дефолт 8).
- `registers.py`: `hold_last=True`.
- **Тесты:** валидация ControlSpec; set→эмит один раз; кнопка-триггер; add/remove; коэрция типов.
- **Acceptance:** `pytest Services/control_panel/` зелёный; ruff чист.

### Phase 2 — Вкладка «Пульт» (GUI Services)
**Assignee:** Director/teamlead · **Layer:** prototype

- `multiprocess_prototype/frontend/widgets/tabs/services/control_panel/`:
  - `widget.py`: `ControlPanelWidget` — рендерит контролы **динамически** из state
    (`control_panel.controls`): кнопка→`QPushButton`, тумблер→`QCheckBox`, слайдер→`QSlider`+label,
    поле→`QLineEdit`/`QSpinBox`. Каждое действие → сигнал виджета `control_changed(id, value)`.
    Секция «Добавить контрол»: тип + label + порт + диапазон → `control_add`.
  - `presenter.py`: `set_control/emit_control/add_control/remove_control` через
    `bridge.on_action_command("control_panel", ...)` (live в рантайм) **+ персист в рецепт**:
    запись `controls` в конфиг ноды через config/topology-write (как list[dict]-инспектор),
    чтобы набор контролов сохранялся в рецепт при save (рецептный сервис).
  - `section.py`: `_ControlPanelSection` + `build_control_panel_section()`; bind `control_panel.controls`
    по glob `processes.*.state.control_panel.*`.
  - регистрация в `_sections.py` (после «Телефон»).
- **Тесты:** presenter роутит команды; виджет строит контролы из спеки; add-форма эмитит.
- **Acceptance:** `pytest .../control_panel/` зелёный; ruff чист.
- **Открытый вопрос Phase 2:** точка персиста — переиспользовать generic list[dict]-инспектор
  для поля `controls` в карточке ноды (Pipeline) ИЛИ свой save-путь из вкладки «Пульт».
  Решить в начале Phase 2 (см. память про list[dict]-виджет inspector, ca631b7f).

### Phase 3 — Демо-рецепт + проводка
**Assignee:** Director · **Layer:** prototype

- `recipes/pult_demo.yaml`: нода `control_panel` → потребитель (оверлей-дисплей или robot_draw),
  пара контролов на `out_1`/`out_2`.
- Проверить headless: порты ноды видны, wire разворачивается.
- **Acceptance:** рецепт грузится; `build_*` корректны.

### Phase 4 — Docs + memory + smoke
- `README.md`/`STATUS.md` сервиса; запись памяти (dual-write).
- qt-mcp smoke: запустить прототип, активировать `pult_demo`, добавить контрол, нажать —
  убедиться, что сигнал уходит (qt_snapshot + лог эмита).

## Phase 5 — Дашборд: параметры/сигналы ДРУГИХ нод в пульте (направление 2026-06-15)

**Цель:** вынести в пульт **только выбранные** параметры/сигналы других нод, чтобы
настраивать НУЖНОЕ в одном месте, не прыгая по нодам. Не «все настройки» — пользователь
добавляет по одному нужному полю через пикер.

Решения владельца:
- Сборка — **GUI-пикер «Добавить из ноды»** (нода → поле/сигнал из списка → proxy-контрол).
  Набор хранится в рецепте (как обычные контролы).
- Выносим: **параметры (правка)** + **мониторинг (чтение)** + **действия/сигналы**.
- **Только выбранные поля**, не весь набор ноды.

**Дизайн (переиспользует существующее, без дублирования логики):**
- `ControlSpec.source ∈ {local, param, monitor, action}` (дефолт `local` = текущий
  pipeline-сигнал на свой порт). Доп. поля: `target_process`, `target_plugin_index`,
  `target_field` (param/monitor), `target_command` (action).
- **param** (правка поля чужой ноды): чтение текущего значения из `registers_manager`;
  запись — через **готовый live field-write** (`SetPluginConfig(target_process, idx, field,
  value)` → `_on_plugin_config_changed` в app.py → `register_update` IPC владельцу). Тот же
  путь, что инспектор ноды Pipeline. Только register-поля (live-tunable).
- **monitor** (чтение): bind к state/значению регистра целевой ноды (read-only виджет).
- **action** (триггер): `bridge.on_action_command(target_plugin, target_command)` (как «Рисовать»).
- **Пикер**: список нод — из топологии; список полей — из схемы регистров плагина
  (`registers_manager`/каталог, те же FieldInfo, что строят инспектор); список команд — из
  `plugin.commands`. Добавление → proxy-контрол → персист в `controls` ноды пульта (рецепт).
- **Роутинг operate**: секция смотрит `source` контрола (по id из `current_controls`) и
  направляет: local→set_control, param→SetPluginConfig, action→on_action_command, monitor→read-only.

**Фазы:** 5.1 модель `ControlSpec.source`+target (backend, тесты) · 5.2 роутинг presenter/section
(param-write через services.commands; action через bridge) · 5.3 GUI-пикер «Добавить из ноды»
(нода/поле/команда из реестра) · 5.4 monitor-binding (read-only из state) · 5.5 qt-mcp smoke.

**Статус Phase 5 (2026-06-16):** 5.1 DONE · **5.2 DONE** (роутинг presenter по `source`:
local→set_control, param→`SetPluginConfig` live field-write, action→`on_action_command`,
monitor→read-only) · **5.3 DONE** (`catalog.py` NodeCatalog + `picker.py` NodePickerDialog:
процесс→плагин→param/action→поле(`extract_fields`)/команда(`PluginRegistry`); тип контрола по
типу поля; стартовое значение из config ноды, не min) · 5.4 monitor — отложено (deferred) ·
**5.5 smoke DONE** (live: пикер открывается, 11 нод видны, 4 угла `robot_scale` правят лист
вживую, значения 0/144/192/0 из рецепта). 53 теста зелёных, ruff чист.

**Грабли Phase 5 (важно):** топологию в GUI брать из `services.topology.load().to_dict()`
(канон, как Pipeline/Processes), НЕ из `bridge.topology` — у конкретного `TopologyBridge` нет
такого свойства (вернул бы None → пустой пикер). Заодно так же починен legacy `_resolve_node`
(персист контролов читал мёртвый `bridge.topology`). action со значением (speed): фреймворк
хранит команды как `{имя: метод}` БЕЗ схемы аргументов → GUI не авто-открывает аргументы,
пользователь задаёт `value_arg`+`command_args` вручную (углы/param — полностью авто из схемы).

**Узел `robot_scale` вписан в phone_sketch (шаг «а», DONE):** strokes_to_points → identity
(px), `robot_scale` первым в процессе `points` (углы листа 0/144/192/0, Y-вверх), wire
`lines.strokes_to_points.draw_points → points.robot_scale.draw_points`. blueprint check 0 ошибок,
live точки рисуют портрет. 4 угла вынесены в pult `controls` (дашборд).

**Вне scope Phase 5:** не-register config-поля (только live-tunable регистры); группировка/вкладки.

## Phase 6 — Пульт оператора 1.0 (ORDER #15–#17; приёмка β8, `plans/release-1.0/design.md` §3)

**Статус:** DRAFT, на утверждении владельца. Сверено с кодом `main` = `506eea281`. Ветка — от лида.
**Цель:** в рецепте 1.0 оператор видит пульт: поле «Слово» (смена на ходу без перезапуска), старт/стоп ленты, «Домой»,
статус (связь робота, последняя буква, собранная часть слова). Новых IPC и каналов нет: `param` — live field-write
(`SetPluginConfig` → `frontend/app.py:867` → `register_update`), `action` — `TopologyBridge.on_action_command`
(`topology_bridge.py:230`), `monitor` — подписка `bindings.bind` (`frontend/state/bindings.py:225`) на state.
**Сверка команд с кодом:** лента — `vfd_run {device_id, direction?, freq_hz?}` / `vfd_stop {device_id}` (`Services/device_hub/spi.py:457-460`),
устройство `vfd_belt` есть в обоих рецептах 1.0 (`letter_robot_sim.yaml:86`); «Домой» — `robot_park {device_id}` (`spi.py:240`; итог в
`devices.state.<id>.park`, после `done` серво OFF и защёлка до `robot_servo {on: true}` — `Services/device_hub/README.md` «Долгая операция»).
Отдельной команды «домой без серво OFF» в коде нет. `system.run.*` — команды PM (`process_manager_process.py:1541-1550`), не плагина:
маршрута `action` к ним нет (`on_action_command` валидирует плагин-команды).

### Задачи 6.0–6.2: smoke, «Слово», прогресс слова
- Task 6.0: **smoke пульта на текущем `main`** [backend-путь DONE 2026-11-15 на `506eea281`; GUI-путь — ждёт qt-mcp] — отчёт `docs/reports/2026-11-15_R2_lane.md`: 59 тестов зелёные (31 + 28), `pult_demo` check() = [], `set_control start=true` → `out_1 = True` ровно 1 раз, `speed 250` → 100.0 (clamp); процесс `devices` в `pult_demo` ЕСТЬ (подтянут из `base.yaml`), `robot_*` отвечают «не подключено» — до сим-робота не доходило (нужно окно `stand`); не проверено: нажатие в Qt, пикер, `SetPluginConfig` из вкладки
  - Level Junior · Assignee haiku + qt-mcp · Layer prototype · Depends — · FILES нет (только прогон)
  - ACCEPTANCE: `pult_demo` — Services → «Пульт» грузится, 4 контрола видны, «Старт» → строка `out_1 = True` в логе `pult`;
    `action` к `device_hub` — **в `pult_demo` процесса `devices` нет** (`pult_demo.yaml:21-50`): проверять на `phone_sketch`
    (`robot_set_mode`, `phone_sketch.yaml:310-330`) — ответ команды без ошибки; `param` — одно поле, readback `introspect_registers`.
  - REDS: n/a — прогон без кода; красный → находка в отчёт, не правка.
- Task 6.1: **[VERTICAL SLICE] поле «Слово» в рецептах 1.0** [PENDING] (после 6.0)
  - Level Middle+ · Assignee developer · Layer prototype · Module contract n/a · Handoff `developer`(REDS) → `reviewer`
  - FILES: `recipes/letter_robot_sim.yaml`, `recipes/hikvision_letter_robot.yaml`, новый `frontend/widgets/tabs/services/control_panel/tests/test_recipe_1_0.py`
  - DESIGN: процесс `pult` (`ControlPanelPlugin`, `category: source`, как `phone_sketch.yaml:303-310`) **дописать последним** в оба рецепта
    одинаково — иначе краснеет `recipes/tests/test_letter_robot_sim_diff.py` (индексы `processes[N]` и `_EXPECTED_DIFFS:52-62`).
    Контрол `{id: word, type: text, label: "Слово", source: param, target_process: layout, target_plugin_index: 0, target_field: target_word}`.
    Код пульта не меняется: путь `presenter.operate` → `_write_param` → `SetPluginConfig` уже есть.
  - ACCEPTANCE: тест — оба рецепта грузятся `SystemBlueprint`, `parse_controls` даёт 1 контрол `param`, `operate(spec, "МИР")` шлёт
    `SetPluginConfig(layout, 0, target_word, "МИР")`; стенд GUI — ввод «МИР» + Enter → `introspect_registers("layout")`
    `word_layout.target_word == "МИР"` за ≤ 2 с, на первом диске строка `смена слова '…' → 'МИР' (источник: регистр)`.
  - REDS: `test_recipe_1_0.py::test_word_control_writes_target_word`, `::test_pult_node_last_in_both_recipes`;
    `recipes/tests/test_letter_robot_sim_diff.py` — зелёный без новых строк `_EXPECTED_DIFFS`.
- Task 6.2: **`word_layout` — прогресс в state на решении + собранная часть слова** [PENDING] (параллельно 6.1)
  - Level Middle+ · Assignee developer · Layer plugins · Module contract impl-only · Handoff `developer`(REDS) → `reviewer`
  - FILES: `Plugins/processing/word_layout/plugin.py`, `registers.py`, `tests/test_p3_disk_journal.py` (или новый `tests/test_state_progress.py`), `README.md`
  - DESIGN: сейчас state `processes.layout.state.word_layout` пишется только в `process()` не чаще 1 с (`plugin.py:29, 159-162`) —
    после последнего диска не обновится (design.md §1). Исправить вперёд: `_publish_state()` и сразу на решении (ячейка, смена слова,
    возврат), период 1 с остаётся для прочего. Новое readonly-поле `assembled` (строка длины `slots_total`: буква заполненной
    ячейки, `·` — пустой; из `WordAssembler.slots`) — в регистр и в state. `last_label` уже есть (`registers.py:143`, `plugin.py:617`).
  - ACCEPTANCE: случай D (§2.5) на фейке — после диска «Р 300°» state сразу `assembled "МИР"`, `slots_filled 3`, `done true`
    без следующего `process()`; на §2.6 после трёх «Е» `assembled "·Е·Е····Е"`; журнал дисков не изменился (тесты P3 зелёные).
  - REDS: `test_state_progress.py::test_publish_on_decision_without_next_tick`, `::test_assembled_mask_case_c`, `::test_word_change_resets_assembled`.
### Задачи 6.3–6.6: monitor, лента и «Домой», приёмка, документы
- Task 6.3: **`monitor` — показ состояния чужой ноды, только чтение** (бывшая 5.4) [PENDING] (после 6.0)
  - Level Middle+ · Assignee developer · Layer services + prototype · Module contract public-api-change (`ControlSpec`) ·
    Handoff `developer`(INTERFACE) → `tester`(RED) → `developer`(GREEN) → `reviewer`
  - FILES: `Services/control_panel/controls.py`, `Services/control_panel/tests/test_controls.py`, `control_panel/widget.py`,
    `control_panel/section.py`, `control_panel/tests/test_dashboard.py`
  - DESIGN: в `ControlSpec` — `state_path: str` (полный путь StateStore: `devices.state.robot_main.conn`, `processes.layout.state.word_layout.last_label`;
    у хаба корень `devices.*`, не `processes.*` — `Plugins/hub/device_hub/plugin.py:12-15`) и `value_key: str` (ключ в dict-значении, `conn`).
    Виджет: `monitor` → `QLabel` без операции (`is_operable()` уже `False`). Секция: на каждый monitor-контрол `bindings.bind(state_path, label, "setText",
    formatter=…)`, `unbind` при перестроении набора (сейчас один handle — `section.py:171`). Пикер — не трогать (вопрос В3).
  - ACCEPTANCE: тест — дельта `devices.state.robot_main.conn = {"conn": "connected", "ts": 7}` → подпись «connected»; replay при
    ленивом открытии вкладки даёт последнее значение; операция над monitor не шлёт команд (0 вызовов bridge и `SetPluginConfig`).
  - REDS: `test_controls.py::test_monitor_state_path_roundtrip`, `test_dashboard.py::test_monitor_label_follows_state_delta`,
    `::test_monitor_replay_on_lazy_bind`, `::test_monitor_rebind_drops_old_handles`, `::test_monitor_never_dispatches`.
- Task 6.4: **кнопки ленты, «Домой», строка статуса в рецептах 1.0** [PENDING] (после 6.1, 6.2, 6.3; ответы В1, В2)
  - Level Middle · Assignee developer · Layer prototype · Module contract n/a · Handoff `developer`(REDS) → `reviewer`
  - FILES: `recipes/letter_robot_sim.yaml`, `recipes/hikvision_letter_robot.yaml`, `control_panel/tests/test_recipe_1_0.py`
  - DESIGN: `action`-контролы на `devices`/0: «Лента пуск» `vfd_run {device_id: vfd_belt}`, «Лента стоп» `vfd_stop {device_id: vfd_belt}`,
    «Домой» `robot_park {device_id: robot_main}`; `monitor`: `devices.state.robot_main.conn`/`conn`, `devices.state.robot_main.park.state`,
    `system.run.state`, `processes.layout.state.word_layout.{last_label, assembled, done}`. Оба рецепта — одинаково.
  - ACCEPTANCE: тест — набор из 3 action и 6 monitor, команды есть в `DeviceHubPlugin.commands`; стенд — «Лента стоп» → сим
    `belt_mm_s 0` за ≤ 1 с, «пуск» → > 0; «Домой» → `devices.state.robot_main.park.state == "done"`, `home ∈ {moved, already}`.
  - REDS: `test_recipe_1_0.py::test_belt_and_home_commands_exist`, `::test_status_monitors_paths`.
- Task 6.5: **живая приёмка β8 на симе** [PENDING] (после 6.4; окно `stand`)
  - Level Senior · Assignee tester (опись — haiku) · Layer prototype · Module contract n/a · Handoff `tester` → лид
  - FILES нет (стенд §2.1 design.md + GUI с qt-mcp)
  - ACCEPTANCE: S6 через пульт вместо `set_register_verified`: «МИР» → журнал §2.5 (строка смены + 5 строк дисков, 3 `CVT_JOB`,
    `jobs_emitted 12`), пульт показывает `assembled "МИР"` и последнюю букву «Р»; без перезапуска «ПЕРЕМИРИЕ» → §2.6; лента стоп/пуск и
    «Домой» по 6.4. Матрица инъекций — предсказания лида до прогона.
- Task 6.6: **README/STATUS пульта и строка ORDER** [PENDING] (после 6.5)
  - Level Junior · Assignee docs-writer · Layer docs · Handoff `docs-writer` → `reviewer`(express)
  - FILES: `Services/control_panel/README.md`, `STATUS.md` (дубль «Известные ограничения v1» — убрать), этот план.

### Связи Phase 6
`plans/2026-10-27_system-run-state/` — Task 2.2 там: STOP останавливает ленту, `resume()` ленту не пускает — пуск лентой
пульта (6.4); Task 2.3 там — кнопки ЗАПУСТИТЬ/ОСТАНОВИТЬ/Квитировать в главном окне (вопрос В4). ORDER #21 (R4, полоса К) правит
`hikvision_letter_robot.yaml` — с 6.1/6.4 один файл, порядок слияния ставит лид. `plans/word-layout.md` — владелец `word_layout` (6.2).

### Открытые вопросы владельцу (Phase 6)
- В1. «Домой» = `robot_park`: робот после него с серво OFF и защёлкой «включите серво». Нужна кнопка «Серво ВКЛ» (`robot_servo {on: true}`)?
  Разрешать «Домой» во время «работает»? (run-state В3: «домой» — только по ОСТАНОВИТЬ.) Блокировки по состоянию у контрола нет.
- В2. «Старт/стоп ленты» = прямые `vfd_run`/`vfd_stop` (как в run-state 2.2) или ЗАПУСТИТЬ/ОСТАНОВИТЬ системы? Рекомендация — прямые.
- В3. `monitor` в 1.0 — только контролы из рецепта, без режима пикера «Наблюдение»? Рекомендация — да, пикер после 1.0.
- В4. ЗАПУСТИТЬ/ОСТАНОВИТЬ/Квитировать дублировать в пульте (нужен новый маршрут к PM) или хватит главного окна (run-state 2.3)?
- В5. Слово оператора пишется и в editor-топологию (`SetPluginConfig`) — рецепт станет «изменён», при Save `target_word` уйдёт в файл. Так и надо?
- В6. «Собранная часть слова» — маска `·Е·Е····Е` (рекомендация) или счёт `3/9`?

### Что осталось ненадёжно (Phase 6)
`vfd_run` через мост `gd20_bridge` на `delta_v2`-симе live не проверен (сим ленты есть —
`Services/robot_comm/server/belt.py`, `apps/line_sim/pipeline.yaml:58`); форма дельты `devices.state.robot_main.conn` у GUI (лист
`conn.conn` или dict) не сверена — решит тест 6.3 на стенде; принимает ли валидатор GUI сгенерированные `vfd_*` — по аналогии с
`robot_set_mode` в `phone_sketch`, не прогоном; лишний процесс `pult` в `letter_robot_sim` — влияние на скрипт α и на готовность
run-state (`readiness()` плагина пульта) не проверено; `ControlSpec.value` поля «Слово» не читает регистр обратно — правду показывает monitor.

## Вне scope (v1)
- Динамические именованные порты (по label контрола) — пул `out_N` в v1.
- Кнопки пульта на HTML-странице телефона (порты `phone_camera` уже есть для будущего).
- Персист набора контролов вне рецепта; группы/вкладки внутри пульта.

## Грабли (из опыта phone_camera)
- `produce()` источника: items НЕ требуют ключа `frame`; per-item `target` опц.
- Эмит ровно один раз на нажатие (drain под lock), иначе сигнал «залипает» каждый тик.
- Новый корень state (`control_panel.**`) — GUI должен быть подписан (glob bind в секции).
- `register_schema` фолбэк на `register_class` — приёмник регистров обязателен, иначе кэш.
