# Пульт · Phase 6 «Пульт оператора 1.0» — стадия 0 (ревью плана)

Дата: 2026-11-20 · Полоса: Пульт · Ветка: `docs/pult-operator-phase6` (`9ca6e0ead`, в main не влита, отстаёт на 319 коммитов) · Сверка с `main` = `ad3dc7b72`.
Ревьюер: `reviewer` (sonnet, effort xhigh), только чтение. Вердикт: **CHANGES REQUESTED**. Код не писался, слот не занимался.
Ключевые находки лид перепроверил `git grep` по цитируемым строкам (см. «Проверено лидом»).

## 1. Вердикт и что менять в плане

План годен как каркас, но перед кодом нужны правки. Они собраны по задачам; в `plans/pult-control-panel.md` не внесены — ждут слова владельца.

| # | Задача | Правка плана | Основание |
|---|---|---|---|
| 1 | 6.4 | «Домой» и «Серво ВКЛ» в боевом рецепте β сейчас не работают: `hikvision_letter_robot.yaml:58` — `protocol: delta_universal3` (робот v1), а `robot_park`/`robot_servo` — операции v2 (`Services/device_hub/spi.py:181-259`); драйвер v1 отвечает «Неизвестная операция робота» (`drivers/robot_driver.py:589`). Записать R4 (ORDER #21, К) как зависимость или ввести эти два контрола только в сим-рецепт до R4. | проверено лидом |
| 2 | 6.1, 6.4 | В FILES добавить golden-снапшот `backend/tests/snapshots/hikvision_letter_robot.build.json` (`process_count: 10` → 11, `process_names`); `test_build_characterization.py:51` берёт β в `RECIPES`. Перегенерация `UPDATE_BUILD_SNAPSHOTS=1` с просмотром diff; R4 правит тот же снапшот — порядок слияния ставит лид. | проверено лидом |
| 3 | 6.4, «Связи» | Task 2.3 run-state влита (`widgets/chrome/run_control.py:297` — ЗАПУСТИТЬ/ОСТАНОВИТЬ/Квитировать). Убрать монитор `system.run.state` (мониторов 5, не 6; в окне уже есть статус по-русски), закрыть В4, переписать «Связи». Оговорить омоним: «пульт» в S5 (`b778b9503`) — виджет главного окна, не вкладка Services. | проверено лидом |
| 4 | 6.4 | «Серво ВКЛ» (`robot_servo {on: true}`) не опциональна: ОСТАНОВИТЬ при `run_gate: true` выполняет `pre_stop` = `robot_park_all` (`system.yaml:344`), после `done` защёлка до серво ON, `resume()` её не снимает. Контрол без кода: `type: button, source: action, target_command: robot_servo, value_arg: on, command_args: {device_id: robot_main}`. При `run_gate: false` (`system.yaml:10`) парковки нет — тогда нужен «Домой». | `system.yaml`, README хаба |
| 5 | 6.3 | Дыры DESIGN: (а) `is_operable()` нигде не вызывается (`git grep` — только определение `controls.py:117`) — виджет строит редактируемый QLineEdit; нужна правка виджета и тест «в строке monitor нет QLineEdit/QPushButton»; (б) перепривязка при пересборке набора — механизма нет, а `GuiStateBindings._on_state_msg` итерирует `self._bindings` без копии (`bindings.py:447`), `unbind` меняет список на месте — откладывать пересвязку (queued/`singleShot(0)`) или опереться на авто-уборку `destroyed`; (в) `bindings.py:507` форматтер вне try — форматтер обязан принимать dict/str/None, тест `test_monitor_formatter_tolerates_non_dict`; (г) `test_monitor_never_dispatches` зелёный до кода (`presenter.py:45`) — гнать через эмит виджета; (д) форма `conn` сверена: `plugin.py:853-869` пишет атомарно dict `{"conn":…}`, `park` — листья; пункт «Ненадёжно» про форму дельты закрыт. | ревью (б — по чтению, не воспроизведено) |
| 6 | 6.2 | `cmd_reset` (`plugin.py:137`) обнуляет `slots_filled/done/next_letter` без публикации — решить: публиковать или оговорить. REDS обязаны идти через записывающий прокси `state_proxy.merge(path, dict)` с литералами (`assembled == "МИР"`, `slots_filled == 3`, `done is True`), не через `MagicMock` (тест с `MagicMock` зелёный при любой логике). `last_label` присваивается до `offer` (`plugin.py:206`) — показывает и отвергнутые диски. FILES: выбрать один файл теста (`test_state_progress.py`). | ревью |
| 7 | 6.1 | Выписать блок `pult` целиком, включая `run_gated: false` (`phone_sketch.yaml:310`, `pult_demo.yaml:44`) и `chain_targets: [gui]`; «грузятся `SystemBlueprint`» → `SystemBlueprint.check() == []` и та же проверка, что у загрузчика (урок памяти про рецептный тест). Нужен тест на реальных объектах: рецепт → `parse_controls` → реальный `ControlPanelPresenter.operate` → реальный `CommandDispatcher` → `PluginConfigChanged(layout, 0, target_word, "МИР")`, `resolve_plugin_register(...) == "word_layout"`. Для 6.4 — реальный `CommandCatalog` + `CommandValidator.validate_action_command("device_hub", "vfd_run").ok`. | ревью |
| 8 | В5 | Следствие: Save рецепта пишет `target_word` в файл, `test_letter_robot_sim_diff.py:149` (точное равенство `_EXPECTED_DIFFS`) покраснеет на `.blueprint.processes[6].plugins[0].config.target_word`. (вывод по чтению) | ревью |
| 9 | 6.0 и мелочи | 6.0 ACCEPTANCE говорит «в `pult_demo` процесса `devices` нет», отчёт R2 и статус-абзац — «есть» (из `base.yaml`): привести к факту. Устарели ссылки: `bindings.py:225` → `:232`; `process_manager_process.py:1541-1550` → `:1721-1730`. Для 6.1/6.2 «параллельно» — отдельные worktree; заполнить `Dependencies`; у Phase 6 нет собственного «Вне scope». | ревью |

Без замечаний: `_EXPECTED_DIFFS` — дописывание `pult` последним не ломает `test_letter_robot_sim_diff.py` (порядок процессов в рецептах совпадает); слои импортов `word_layout`/`controls.py` чисты; код пульта и `word_layout` с 2026-11-15 не менялся.

Вне полосы Пульт (только фиксирую): `plans/2026-10-27_system-run-state/plan.md:45, 170, 182` до сих пор говорят «кнопки — в пульте»; на :107 Task 2.3 — PENDING, хотя влита. Это для полосы Ф.

## 2. Вопросы владельцу В1–В6 (+ три пропущенных), с рекомендациями

| № | Вопрос | Рекомендация | Почему |
|---|---|---|---|
| В1 | «Домой» (`robot_park`) оставляет серво OFF и защёлку. Нужна «Серво ВКЛ»? Разрешать «Домой» в «работает»? | **«Серво ВКЛ» — да, в 6.4.** «Домой» без блокировки по состоянию в 1.0, запись в README; блокировка по `system.run.state` — после 1.0. | без «Серво ВКЛ» цикл ОСТАНОВИТЬ → ЗАПУСТИТЬ → слово встаёт; `robot_park` в «работает» роняет очередь заданий |
| В2 | Лента: прямые `vfd_run`/`vfd_stop` или ЗАПУСТИТЬ/ОСТАНОВИТЬ системы? | **Прямые.** Закрывается кодом. | маршрута `action` к `system.run.*` нет; run-state 2.2: «лента — кнопкой пульта» |
| В3 | `monitor` в 1.0 — только контролы из рецепта, без пикера «Наблюдение»? | **Да**, пикер после 1.0. | в `catalog.py` билдера `monitor` нет; объём 6.3 и так велик |
| В4 | Дублировать ЗАПУСТИТЬ/ОСТАНОВИТЬ/Квитировать в пульте? | **Нет — закрыт**: решение Ф, кнопки в главном окне, 2.3 влита. | дубль требует нового маршрута к PM |
| В5 | Слово пишется в editor-топологию → рецепт «изменён», при Save слово уйдёт в файл. Так надо? | **Да, но владелец решает со следствием из п. 8:** либо Save рецептов 1.0 со словом не ждём, либо слово исключаем из сравнения diff-теста. | `frontend/app.py:867-912`, `test_letter_robot_sim_diff.py:149` |
| В6 | «Собранная часть слова»: маска `·Е·Е····Е` или счёт `3/9`? | **Маска.** | `slots_filled`/`slots_total` в state уже есть, счёт бесплатен; маска несёт больше |
| В7 (новый) | Вид для оператора: у каждой строки пульта «✕» (`widget.py:225-240`) и форма «Добавить контрол» — оператор может удалить «Слово». Нужен «режим оператора» (скрыть ✕ и форму)? | Для 1.0 — **вынести в «Вне scope»**, режим оператора после 1.0 (есть подтверждение удаления). Решение владельца. | в плане задачи нет |
| В8 (новый) | β зависит от R4 (протокол v1) — «Домой»/«Серво ВКЛ» в боевом рецепте до R4 недоступны. | Сим-рецепт сейчас, β — после R4; зависимость записать. | п. 1 таблицы |
| В9 (новый) | Ввод слова: только Enter (`widget.py:288`), запись fire-and-forget (`frontend/app.py:893-905`), отказ оператору не виден; пустое слово регистр откатывает. | Оставить для 1.0; правду показывает monitor (`last_label`/`assembled`). | план это признаёт |

## 3. Smoke 6.0 — GUI-путь

- **qt-mcp не поднимается** (`CONNECTION_CLOSED`). Причина найдена: `.mcp.json` запускает `uvx qt-mcp`, а пакета с таким именем в PyPI нет (`uvx qt-mcp --help` → «not found in the package registry»). Пакет стоит в `.venv` из git (`pyproject.toml:146`, есть `.venv/bin/qt-mcp`, `import qt_mcp` работает), поэтому правка — вызывать установленный бинарник (`uv run --no-sync qt-mcp` или `.venv/bin/qt-mcp`). `.mcp.json` генерируется из плагина `mcp-qt`, я его не правил; правка — владельцу плагина/координатору. Кроме сервера нужна проба в самом приложении: `qt_mcp` в коде приложения не подключён (`git grep` по `pyproject.toml` и `run.py` — только зависимость).
- Проверяемо без qt-mcp: `check()` рецепта `pult_demo`, `backend_ctl` (`set_control`, клампы, строка `out_1 = True`), `set_register_verified` + `introspect_registers("layout")` для `param`, `send_command` процессу `devices` для `action`, тесты вкладки на фейках (59 зелёных по отчёту R2).
- Недоказуемо без Qt: рендер вкладки и доставка `control_operated` до секции; `TopologyBridge.on_action_command` и валидатор GUI на реальных `vfd_*`/`robot_*`; путь `SetPluginConfig` из вкладки в `register_update`; пикер. Кандидат-замена: GUI-стенд `BACKEND_CTL=1 INSPECTOR_GUI_UNATTENDED=1` (`backend_ctl/AGENTS.md:41`) и `backend_ctl/probes/probe_gui_stand_live.py` — годность под пульт не проверена.
- Вывод: GUI-путь 6.0 остаётся непроверенным; не блокирует 6.1 (код пульта не меняется), но 6.5 (приёмка на сим) требует рабочего GUI-канала.

## 4. Проверено лидом

`git grep` на `main`: `hikvision_letter_robot.yaml:58 delta_universal3` против `letter_robot_sim.yaml:74 delta_v2`; `robot_driver.py:589` «Неизвестная операция робота»; `test_build_characterization.py:51 RECIPES = ["phone_sketch","hikvision_letter_robot"]`, снапшот β `process_count: 10`, `pult` в нём нет; `system.yaml:10 run_gate: false`, `:344 robot_park_all`; `run_control.py:297 Квитировать`; `bindings.py:232 def bind(`, `:447 for handle in self._bindings`; `controls.py:117 is_operable` — единственное вхождение; `run_gated: false` в `phone_sketch.yaml:310`, `pult_demo.yaml:44`.

## 5. Что осталось открытым / ненадёжно

- Ревьюер ничего не запускал, кроме интроспекции `DeviceHubPlugin.commands`; падение golden-снапшота (п. 2) и мина итерации `_bindings` (п. 5б) выведены чтением, не воспроизведены. Лид подтвердил только факты по строкам, не поведение.
- Не проверены: чувствительность `test_recipes_join_contract.py` и `test_run_launcher_c55.py` к лишнему процессу; умолчание `readiness()` для плагина без переопределения (`process_module/plugins/base.py:1574`) — влияние `pult` на готовность run-state; принимает ли валидатор GUI `vfd_*`/`robot_park` на живой топологии; поведение `robot_park` при `run_gate: true` и работающей ленте; `vfd_run` через `gd20_bridge` на `delta_v2`-симе live.
- Урок про golden-снапшоты рецептов («рецепт тянет за собой `snapshots/*.build.json`») в память не писал: поиск дубликатов не делался.
- GUI-путь smoke 6.0 не пройден (см. п. 3).
- Стоимость ревьюера: ~232k токенов, 83 вызова. Оценка всей фазы по ревьюеру ≈ 1,5M токенов — advisory.
- План в `plans/pult-control-panel.md` не правлен; в main не влит. После слова владельца — отдельный `docs(plans):` коммит с правками из §1.
