# План: сервис «Пульт» (control_panel)

**Ветка:** `feat/pult-control-panel`
**Slug:** `pult-control-panel`
**Статус:** Phase 1-3 DONE + qt-mcp smoke verified; остался Phase 4 (память).

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

## Вне scope (v1)
- Динамические именованные порты (по label контрола) — пул `out_N` в v1.
- Кнопки пульта на HTML-странице телефона (порты `phone_camera` уже есть для будущего).
- Персист набора контролов вне рецепта; группы/вкладки внутри пульта.

## Грабли (из опыта phone_camera)
- `produce()` источника: items НЕ требуют ключа `frame`; per-item `target` опц.
- Эмит ровно один раз на нажатие (drain под lock), иначе сигнал «залипает» каждый тик.
- Новый корень state (`control_panel.**`) — GUI должен быть подписан (glob bind в секции).
- `register_schema` фолбэк на `register_class` — приёмник регистров обязателен, иначе кэш.
