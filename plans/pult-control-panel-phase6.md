# План: сервис «Пульт» — Phase 6 «Пульт оператора 1.0»

Продолжение [`plans/pult-control-panel.md`](pult-control-panel.md) (фазы 1–5 и общая архитектура — там). Выделено в отдельный файл из-за бюджета размера документа (32 КБ).
**Ветка:** `docs/pult-operator-phase6` · **Slug:** `pult-control-panel`

## Phase 6 — Пульт оператора 1.0 (ORDER #15–#17; приёмка β8, `plans/release-1.0/design.md` §3)

**Статус:** 6.1–6.4 влиты в main; 6.5 живая приёмка проведена на симе 2026-11-21 (GUI offscreen — через пробу qt-mcp); 6.6 документы — готовы. Открыто: β (R4), DRAW, русские подписи значений — `docs/claude/OPEN_QUESTIONS.md`.
Сверено с кодом `main` = `ad3dc7b72`. Ветка — от лида. Все вопросы закрыты (ниже); код — после их ответа и слота писателя.
**Не путать:** «пульт» здесь — вкладка Services → «Пульт» (`control_panel`). Виджет `RunControlWidget` (ЗАПУСТИТЬ/ОСТАНОВИТЬ/Квитировать, S5 `b778b9503`) —
главное окно, полоса Ф; пульт его не дублирует.
**Цель:** в рецепте 1.0 оператор видит пульт: поле «Слово» (смена на ходу без перезапуска), старт/стоп ленты, «Домой»,
статус (связь робота, последняя буква, собранная часть слова). Новых IPC и каналов нет: `param` — live field-write
(`SetPluginConfig` → `frontend/app.py:867` → `register_update`), `action` — `TopologyBridge.on_action_command`
(`topology_bridge.py:230`), `monitor` — подписка `bindings.bind` (`frontend/state/bindings.py:232`) на state.
**Сверка команд с кодом:** лента — `vfd_run {device_id, direction?, freq_hz?}` / `vfd_stop {device_id}` (`Services/device_hub/spi.py:457-460`),
устройство `vfd_belt` есть в обоих рецептах 1.0 (`letter_robot_sim.yaml:86`); «Домой» — `robot_park {device_id}` (`spi.py:240`; итог в
`devices.state.<id>.park`, после `done` серво OFF и защёлка до `robot_servo {on: true}` — `Services/device_hub/README.md` «Долгая операция»).
Отдельной команды «домой без серво OFF» в коде нет. `system.run.*` — команды PM (`process_manager_process.py:1721-1730`), не плагина:
маршрута `action` к ним нет (`on_action_command` валидирует плагин-команды).
**Протокол робота:** `robot_park` и `robot_servo` — операции v2 (`spi.py:181-259`). Сим-рецепт — `delta_v2` (`letter_robot_sim.yaml:74`), боевой β —
`delta_universal3` = v1 (`hikvision_letter_robot.yaml:58`), там драйвер отвечает «Неизвестная операция робота» (`drivers/robot_driver.py:589`).
Поэтому «Домой» и «Серво ВКЛ» (6.4) — сначала только в `letter_robot_sim.yaml`; в β — после R4 (ORDER #21, полоса К, перевод β на `delta_v2`).

### Задачи 6.0–6.2: smoke, «Слово», прогресс слова
- Task 6.0: **smoke пульта на текущем `main`** [backend-путь DONE 2026-11-15 на `506eea281`; GUI-путь — ждёт qt-mcp] — отчёт `docs/reports/2026-11-15_R2_lane.md`: 59 тестов зелёные (31 + 28), `pult_demo` check() = [], `set_control start=true` → `out_1 = True` ровно 1 раз, `speed 250` → 100.0 (clamp); процесс `devices` в `pult_demo` ЕСТЬ (подтянут из `base.yaml`), `robot_*` отвечают «не подключено» — до сим-робота не доходило (нужно окно `stand`); не проверено: нажатие в Qt, пикер, `SetPluginConfig` из вкладки
  - Level Junior · Assignee haiku (backend_ctl; GUI — qt-mcp после починки `.mcp.json` или GUI-стенд) · Layer prototype · Module contract n/a · Depends — · FILES нет (только прогон)
  - GUI-путь: qt-mcp не стартует из-за `.mcp.json` (`uvx qt-mcp`, пакета нет на PyPI; в `.venv` стоит `qt-mcp` из git) и в приложении нет пробы `qt_mcp`.
    Без него: backend-путь + тесты вкладки; GUI — стендом `BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1` (`backend_ctl/AGENTS.md:41`), годность под пульт проверить в 6.0.
  - ACCEPTANCE: `pult_demo` — Services → «Пульт» грузится, 4 контрола видны, «Старт» → строка `out_1 = True` в логе `pult`;
    `action` к `device_hub` — процесс `devices` в `pult_demo` ЕСТЬ (из `base.yaml`, отчёт R2), но роботов нет («не подключено»): ответ команды
    без ошибки проверять на `phone_sketch` (`robot_set_mode`, `phone_sketch.yaml:310-330`); `param` — одно поле, readback `introspect_registers`.
  - REDS: n/a — прогон без кода; красный → находка в отчёт, не правка.
- Task 6.1: **[VERTICAL SLICE] поле «Слово» в рецептах 1.0** [DONE 2026-11-20, ветка `feat/pult-word-field`, ревью Sonnet APPROVED; стенд «МИР» → `target_word` не гонялся — нужно окно `stand`] (6.0 GUI-путь не блокирует)
  - Level Middle+ · Assignee developer · Layer prototype · Module contract n/a · Handoff `developer`(REDS) → `reviewer`
  - FILES: `recipes/letter_robot_sim.yaml`, `recipes/hikvision_letter_robot.yaml`, новый `frontend/widgets/tabs/services/control_panel/tests/test_recipe_1_0.py`,
    `backend/tests/snapshots/hikvision_letter_robot.build.json` (перегенерация `UPDATE_BUILD_SNAPSHOTS=1`, diff просмотреть: `process_count` 10 → 11, в `process_names` добавится `pult`;
    R4 правит тот же снапшот — порядок слияния ставит лид)
  - DESIGN: процесс `pult` **дописать последним** в оба рецепта одинаково — иначе краснеет `recipes/tests/test_letter_robot_sim_diff.py`
    (индексы `processes[N]` и `_EXPECTED_DIFFS:52-64`; порядок процессов в рецептах совпадает, подтверждено ревью). Блок целиком, как `phone_sketch.yaml:303-310`:
    `ControlPanelPlugin`, `category: source`, `chain_targets: [gui]`, **`run_gated: false`** (иначе при `run_gate: true` источник гейтится, а `local`-эмиты встанут).
    Контрол `{id: word, type: text, label: "Слово", source: param, target_process: layout, target_plugin_index: 0, target_field: target_word}`.
    Код пульта не меняется: путь `presenter.operate` → `_write_param` → `SetPluginConfig` уже есть.
  - ACCEPTANCE: тест — оба рецепта проходят `SystemBlueprint.check() == []` (та же проверка, что у загрузчика, не облегчённая), `parse_controls` даёт ровно 1 контрол
    `param` с id `word` (`parse_controls` молча роняет битую запись — этот пин ловит опечатку в YAML); **тест на реальных объектах**: рецепт → `parse_controls` →
    реальный `ControlPanelPresenter.operate(spec, "МИР")` → реальный `CommandDispatcher` → `PluginConfigChanged(layout, 0, target_word, "МИР")`
    и `resolve_plugin_register(topology, "layout", 0) == "word_layout"`; стенд GUI — ввод «МИР» + Enter → `introspect_registers("layout")`
    `word_layout.target_word == "МИР"` за ≤ 2 с, на первом диске строка `смена слова '…' → 'МИР' (источник: регистр)`.
  - REDS: `test_recipe_1_0.py::test_word_control_writes_target_word` (реальные объекты), `::test_pult_node_last_in_both_recipes`, `::test_recipes_pass_blueprint_check`;
    `recipes/tests/test_letter_robot_sim_diff.py` и `backend/tests/test_build_characterization.py` — зелёные (снапшот β перегенерирован осознанно).
- Task 6.1b: **тесты «рецепт как есть» и слово оператора (следствие В5)** [DONE] (после слияния 6.1; решение лида, найдено ревью 6.1)
  - Level Junior+ · Assignee developer · Layer prototype + plugins-tests · Module contract n/a · Handoff `developer`(REDS) → `reviewer`(express)
  - Суть: после Save рецепта со словом оператора красными станут не только `recipes/tests/test_letter_robot_sim_diff.py:149`
    (`.blueprint.processes[6].plugins[0].config.target_word`), но и (воспроизведено на копии рецепта с `target_word: МИР`)
    `Plugins/processing/word_layout/tests/test_p3_disk_journal.py::test_recipe_default_empty_word_says_so` («рецепт как есть: target_word ''») и
    `scripts/alpha_sim/tests/test_p4_alpha_real_plugin.py::test_real_plugin_lines_judged_b_d_c` («рецепт как есть: слово пусто»);
    для β — golden-снапшот держит `target_word: ""`. Красного сегодня нет, он возникает только после реального Save.
  - FILES: те три теста, `_recipe_cfg()` в двух последних — явный `target_word=''`; diff-тест — не считать `target_word` расхождением; снапшот β по решению лида. Чужие тесты — только с ведома владельцев (word_layout P3 — `plans/word-layout.md`, alpha — полоса α).

- Task 6.2: **`word_layout` — прогресс в state на решении + собранная часть слова** [DONE 2026-11-20, влита 69c40c3a6] (параллельно 6.1)
  - Level Middle+ · Assignee developer · Layer plugins · Module contract impl-only · Handoff `developer`(REDS) → `reviewer`
  - FILES: `Plugins/processing/word_layout/plugin.py`, `registers.py`, новый `tests/test_state_progress.py` (один файл, не `test_p3_disk_journal.py`), `README.md`
  - DESIGN: сейчас state `processes.layout.state.word_layout` пишется только в `process()` не чаще 1 с (`plugin.py:29, 159-162`) —
    после последнего диска не обновится (design.md §1). Исправить вперёд: `_publish_state()` и сразу на решении (ячейка, смена слова,
    возврат, **и `cmd_reset` (`plugin.py:137`)** — он обнуляет `slots_filled/done/next_letter` без публикации), период 1 с остаётся для прочего.
    Новое readonly-поле `assembled` (строка длины `slots_total`: буква заполненной ячейки, `·` — пустой; из `WordAssembler.slots`) — в регистр и в state.
    `last_label` уже есть (`registers.py:143`, `plugin.py:617`), но присваивается до `offer` (`plugin.py:206`): показывает последнюю РАСПОЗНАННУЮ букву, в том числе
    отвергнутого диска; для отвергнутых публикации на решении нет (значение отстаёт до 1 с) — оговорить в README, не чинить.
  - ACCEPTANCE: случай D (§2.5) на фейке — после диска «Р 300°» state сразу `assembled "МИР"`, `slots_filled 3`, `done true`
    без следующего `process()`; на §2.6 после трёх «Е» `assembled "·Е·Е····Е"`; журнал дисков не изменился (тесты P3 зелёные).
    Фейк `state_proxy` — **записывающий**, с `merge(path, dict)`; сверка по литералам, не `MagicMock().merge.called` (с `MagicMock` проходит любая логика).
  - REDS: `test_state_progress.py::test_publish_on_decision_without_next_tick`, `::test_assembled_mask_case_c`, `::test_word_change_resets_assembled`, `::test_reset_publishes_state`.

### Задачи 6.3–6.4: monitor, лента, «Домой», «Серво ВКЛ»
- Task 6.3: **`monitor` — показ состояния чужой ноды, только чтение** (бывшая 5.4) [DONE 2026-11-21, влита e836b2db5] (после 6.0)
  - Level Middle+ · Assignee developer · Layer services + prototype · Module contract public-api-change (`ControlSpec`) ·
    Handoff `developer`(INTERFACE) → `tester`(RED) → `developer`(GREEN) → `reviewer`
  - FILES: `Services/control_panel/controls.py`, `Services/control_panel/tests/test_controls.py`, `control_panel/widget.py`,
    `control_panel/section.py`, `control_panel/tests/test_dashboard.py`
  - DESIGN: в `ControlSpec` — `state_path: str` (полный путь StateStore: `devices.state.robot_main.conn`, `processes.layout.state.word_layout.last_label`;
    у хаба корень `devices.*`, не `processes.*` — `Plugins/hub/device_hub/plugin.py:12-15`) и `value_key: str` (ключ в dict-значении, `conn`).
    Виджет: `monitor` → `QLabel` без операции. **Это отдельная правка виджета:** `is_operable()` (`controls.py:117`) сейчас нигде не вызывается, виджет по `type`
    строит редактируемые поля (`widget.py:259-306`). Секция: на каждый monitor-контрол `bindings.bind(state_path, label, "setText", formatter=…)`.
    Форма значений сверена: `conn` — атомарный dict `{"conn": …}` на точном пути (`device_hub/plugin.py:853-869`, `value_key: conn`); `park` — листья
    (`devices.state.robot_main.park.state`, `value_key` не нужен). Форматтер **обязан принимать dict, str и None** — исключение в нём ломает цикл дельт (`bindings.py:507`).
    Перепривязка при пересборке набора: набор строится через `bind("processes.*.state.control_panel.controls", widget, "set_controls")` (`section.py:171`);
    `unbind`/`bind` прямо из слота внутри цикла дельт пропускает соседний handle (`bindings.py:447` итерирует без копии, `unbind` меняет список на месте) —
    пересвязку **откладывать** (queued-сигнал или `QTimer.singleShot(0)`) либо опираться на авто-уборку `destroyed` → `unbind_widget` (`bindings.py:395-396`, переприсваивает список).
    Пикер — не трогать (В3).
  - ACCEPTANCE: тест — дельта `devices.state.robot_main.conn = {"conn": "connected", "ts": 7}` → подпись «connected»; replay при
    ленивом открытии вкладки даёт последнее значение; в строке monitor нет `QLineEdit`/`QPushButton`; эмит операции из виджета monitor не шлёт команд
    (0 вызовов bridge и `SetPluginConfig`). Тесты привязок — на реальном `GuiStateBindings` (паттерн `frontend/state/tests/test_bindings.py:35`, нужен qtbot), не только на фейках.
  - REDS: `test_controls.py::test_monitor_state_path_roundtrip`, `test_dashboard.py::test_monitor_label_follows_state_delta`,
    `::test_monitor_replay_on_lazy_bind`, `::test_monitor_rebind_drops_old_handles`, `::test_monitor_row_has_no_editable_widgets`,
    `::test_monitor_formatter_tolerates_non_dict`, `::test_monitor_never_dispatches` (через эмит виджета: `presenter.operate` для monitor уже возвращает False — `presenter.py:45`,
    поэтому тест через него красным до кода не будет).
- Task 6.4: **кнопки ленты, «Домой», «Серво ВКЛ», строка статуса в рецептах 1.0** [DONE 2026-11-21, влита 519db0930; ревью Sonnet APPROVED, отчёт docs/reports/2026-11-21_pult_6.4.md] (после 6.1, 6.2, 6.3; В1, В2, В8 решены)
  - Level Middle+ · Assignee developer · Layer prototype · Module contract n/a · Handoff `developer`(REDS) → `reviewer`
  - FILES: `recipes/letter_robot_sim.yaml` (все контролы), `recipes/hikvision_letter_robot.yaml` (лента и мониторы; «Домой»/«Серво ВКЛ» — после R4), `control_panel/tests/test_recipe_1_0.py`,
    снапшот `backend/tests/snapshots/hikvision_letter_robot.build.json` — перегенерирован (изменились `controls` блока `pult`); также тронуты в 6.4 (в плане не были): `Services/control_panel/plugin/plugin.py`, `Services/control_panel/tests/test_plugin_monitor_readonly.py`, `recipes/tests/test_letter_robot_sim_diff.py`
  - DESIGN: `action`-контролы на `devices`/0: «Лента пуск» `vfd_run {device_id: vfd_belt}`, «Лента стоп» `vfd_stop {device_id: vfd_belt}`,
    «Домой» `robot_park {device_id: robot_main}`, **«Серво ВКЛ»** `robot_servo {device_id: robot_main, on: true}` (без кода: `type: button, source: action,
    target_command: robot_servo, value_arg: on, command_args: {device_id: robot_main}`, `ControlSpec.action_args` — `controls.py:121-130`).
    Зачем «Серво ВКЛ»: ОСТАНОВИТЬ при `run_gate: true` выполняет `pre_stop` = `robot_park_all` (`backend/config/system.yaml:344`; `process_manager_process.py:1975-1990`),
    после `done` серво OFF и защёлка, `resume()` её не снимает (`device_hub/plugin.py:461`, README хаба «После done») — без кнопки цикл ОСТАНОВИТЬ → ЗАПУСТИТЬ → слово встанет.
    При `run_gate: false` (`system.yaml:10`) парковки нет — тогда нужен «Домой». Блокировок по состоянию у контрола нет (`robot_park` в «работает» роняет очередь заданий) —
    для 1.0 так и оставляем, описать в README; блокировка по `system.run.state` — после 1.0.
    `monitor` (5 шт.): `devices.state.robot_main.conn` (`value_key: conn`), `devices.state.robot_main.park.state`, `processes.layout.state.word_layout.{last_label, assembled, done}`.
    Монитор `system.run.state` **не делаем**: статус системы уже показывает `RunControlWidget` главного окна по-русски (`windows/main_window.py:676`).
  - ACCEPTANCE: тест — набор из 4 action и 5 monitor, команды есть в `DeviceHubPlugin.commands`; **реальный** `CommandCatalog` + `CommandValidator.validate_action_command("device_hub", "vfd_run").ok`
    (по `DeviceHubPlugin.commands` одной проверяется только класс, а не путь GUI-валидатора); стенд — «Лента стоп» → сим `belt_mm_s 0` за ≤ 1 с, «пуск» → > 0;
    «Домой» → `devices.state.robot_main.park.state == "done"`, `home ∈ {moved, already}`; «Серво ВКЛ» после «Домой» → джог/задание снова принимаются.
  - REDS: `test_recipe_1_0.py::test_belt_home_servo_commands_exist`, `::test_status_monitors_paths`, `::test_gui_validator_accepts_belt_and_home`.

### Задачи 6.5–6.6: приёмка и документы
- Task 6.5: **живая приёмка β8 на симе** [DONE 2026-11-21, окно stand 12:30–12:53, tester sonnet; отчёты `docs/reports/2026-11-21_pult_6.5.md` и `…_pult_6.5_tester.md`; красных по механизму нет, три находки C-103…C-105 в `plans/queue/defects.md`] (после 6.4; окно `stand`)
  - Level Senior · Assignee tester (опись — haiku) · Layer prototype · Module contract n/a · Handoff `tester` → лид
  - FILES нет (стенд §2.1 design.md + GUI с qt-mcp)
  - ACCEPTANCE: S6 через пульт вместо `set_register_verified`: «МИР» → журнал §2.5 (строка смены + 5 строк дисков, 3 `CVT_JOB`,
    `jobs_emitted 12`), пульт показывает `assembled "МИР"` и последнюю букву «Р»; без перезапуска «ПЕРЕМИРИЕ» → §2.6; лента стоп/пуск и
    «Домой» по 6.4. Матрица инъекций — предсказания лида до прогона.
- Task 6.6: **README/STATUS пульта и строка ORDER** [DONE 2026-11-21: README/STATUS/шапки влиты `7318ca414`, итоги приёмки и строки ORDER — ветка `docs/pult-6.5-acceptance`] (после 6.5)
  - Level Junior · Assignee docs-writer · Layer docs · Handoff `docs-writer` → `reviewer`(express)
  - FILES: `Services/control_panel/README.md`, `STATUS.md` (дубль «Известные ограничения v1» — убрать), этот план.

### Связи Phase 6
`plans/2026-10-27_system-run-state/` — Task 2.2 там: STOP останавливает ленту, `resume()` ленту не пускает — пуск лентой
пульта (6.4); Task 2.3 там — кнопки ЗАПУСТИТЬ/ОСТАНОВИТЬ/Квитировать в главном окне, **влита** (`widgets/chrome/run_control.py:297`; решение Ф, В4 закрыт).
Для полосы Ф (не правим): `run-state/plan.md:45, 170, 182` всё ещё говорят «кнопки — в пульте», на :107 Task 2.3 — PENDING.
ORDER #21 (R4, полоса К) правит `hikvision_letter_robot.yaml` и тот же golden-снапшот — с 6.1/6.4 один файл, порядок слияния ставит лид;
R4 — **зависимость** для «Домой»/«Серво ВКЛ» в β (протокол v1). `plans/word-layout.md` — владелец `word_layout` (6.2).
6.1 и 6.2 идут «параллельно» только в разных worktree (один писатель на дерево); файлы не пересекаются.

### Решения по вопросам Phase 6
- В1. **Решено (рекомендация лида, 2026-11-20):** «Серво ВКЛ» — да (6.4). «Домой» без блокировки по состоянию в 1.0, запись в README; блокировка по `system.run.state` — после 1.0.
- В2. **Решено кодом:** прямые `vfd_run`/`vfd_stop` — маршрута `action` к `system.run.*` нет (`command_validator.py:116-135`).
- В3. **Решено:** `monitor` в 1.0 — только контролы из рецепта; пикер «Наблюдение» (в `catalog.py` билдера `monitor` нет) — после 1.0.
- В4. **Закрыто (владелец, полоса Ф):** кнопки run-state — только главное окно, пульт не дублирует.
- В5. **Решено владельцем 2026-11-20: принять как есть.** Слово пишется и в editor-топологию (`SetPluginConfig`, `frontend/app.py:867-912`) — рецепт станет «изменён», при Save `target_word` уйдёт в файл,
  а `test_letter_robot_sim_diff.py:149` (точное равенство `_EXPECTED_DIFFS`) покраснеет на `.blueprint.processes[6].plugins[0].config.target_word`; шире — см. Task 6.1b (ещё два теста и снапшот β). Слово — часть рецепта; в 6.1 diff-тест `test_letter_robot_sim_diff.py` не должен считать `target_word` расхождением (учесть в тесте, не в рецепте).
- В6. **Решено (лид):** маска `·Е·Е····Е`; счёт `3/9` читается из `slots_filled`/`slots_total`, они уже в state.
- В7. **Решено владельцем 2026-11-20: «режим оператора» — после 1.0.** У каждой строки пульта «✕» (`widget.py:225-240`) и форма «Добавить контрол» — оператор может удалить «Слово» (подтверждение удаления есть).
  Сейчас в «Вне scope Phase 6».
- В8. **Решено:** сим-рецепт — всё сразу; β — «Домой»/«Серво ВКЛ» после R4.
- В9. **Принято:** слово — только Enter (`widget.py:288`), запись без подтверждения (`frontend/app.py:893-905`), пустое слово регистр откатывает; правду показывает monitor.

### Что осталось ненадёжно (Phase 6)
`vfd_run` через мост `gd20_bridge` на `delta_v2`-симе live не проверен (сим ленты есть — `Services/robot_comm/server/belt.py`, `apps/line_sim/pipeline.yaml:58`);
принимает ли валидатор GUI сгенерированные `vfd_*` и `robot_park` — по аналогии с `robot_set_mode`, не прогоном (6.4 вводит тест реального валидатора);
GUI-путь smoke 6.0 не пройден (qt-mcp, см. 6.0); лишний процесс `pult` в рецептах — влияние на скрипт α (`scripts/alpha_sim/run_alpha.py:567`),
на готовность run-state (`readiness()`, `process_module/plugins/base.py:1574`), `test_recipes_join_contract.py` и `test_run_launcher_c55.py` не проверено;
`robot_park` при `run_gate: true` и работающей ленте не проверен; перепривязка monitor (6.3) и падение golden-снапшота (6.1) выведены чтением, не воспроизведены;
`ControlSpec.value` поля «Слово» не читает регистр обратно — правду показывает monitor.

## Вне scope Phase 6
- Пикер «Наблюдение» для monitor; блокировка контролов по состоянию системы; «режим оператора» без ✕ и формы (В7); дубли кнопок run-state (главное окно);
  перевод β на `delta_v2` (полоса К, R4).
