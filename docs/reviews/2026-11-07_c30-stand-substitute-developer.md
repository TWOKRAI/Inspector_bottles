# C-30: замена живого стенда M1/M2 на настоящих Qt-виджетах (developer)

Это ЗАМЕНА стенда, а не стенд. Код продукта не менялся. Новый файл:
`multiprocess_prototype/frontend/widgets/tabs/pipeline/tests/test_stand_substitute_m1_m2.py` (не закоммичен, не добавлен в индекс).

## Что сделано

Пять тестов, QApplication offscreen, настоящие объекты: `RecipeManager` + `RecipeStoreFromManager` + `InspectorRecipeFormatHook`
на tmp-копии `bridge_synth_head.yaml`, `TopologySession` с базой и `capture_foundation(["devices"])`, живой граф
(`base.yaml` + рецепт). Обвязка (`_bridge_synth_setup`, `_Repo`, `_OLD_MTIME_NS`) импортируется из `test_save_conflict_rev.py`, не копируется.

- Путь Pipeline: настоящий `PipelineTab(services, topology_session=session)`, кнопка «Сохранить» ищется среди `QPushButton` и нажимается `click()`.
- Путь Recipes: настоящий `RecipesTab`, рецепт выбирается публичным `select_item`, нажимается «Сохранить». Оба пути достижимы с виджетом; презентер как замена не понадобился.
- `QMessageBox.information/warning/critical/question/exec` подменены до клика на захват `(вид, заголовок, текст)`; ассерты на полный список вызовов (число и точный текст).
- M1 (2 теста, pipeline и recipes): клик, байты == исходные, `st_mtime_ns` == прежний; второй клик то же; список диалогов ровно два «Рецепт сохранён: bridge_synth».
- M2 (2 теста): после первого Save во внешний файл дописано `# external edit\n`; клик даёт диалог конфликта с литералом «Рецепт изменён снаружи — перезагрузите его» (Pipeline: `critical`, «Сохранение рецепта»; Recipes: `warning`, «Ошибка»), байты файла и mtime == ручная правка.
- 1 тест характеризации (см. находку ниже).

## Находка, влияющая на трактовку M1

В `bridge_synth_head.yaml` нет раскладки. Первый Save настоящей Pipeline-вкладки дописывает в рецепт блок `metadata.gui_positions` (узел `synthetic_source.synthetic_frame_source` -> 400.0, 100.0), +5 строк, дифф не `0/0`. Presenter-тест `test_pipeline_and_recipes_save_without_edits_are_zero_diff` этого не видит: у него нет живой сцены. Живая сцена переопределяет позиции (`scene.get_all_node_positions()` в `LayoutController.save_to_active_recipe`).
Следствие: «M1 = 0/0» для Pipeline верно, когда раскладка уже в файле (как в рабочем файле стенда, судя по его истории; рабочий файл я не открывал и не трогал). Поэтому M1 снят на «осевшем» рецепте (HEAD + этот блок как литерал, база сессии переснята). Отдельный тест `test_pipeline_first_save_of_recipe_without_layout_adds_default_positions` фиксирует поведение первого Save; он характеризация, не требование C-30. Если владелец считает это дефектом, тест надо менять вместе с продуктом. Решение лида: это дефект или норма.

## Запуски

Путь импорта (cwd = worktree): `.../.claude/worktrees/lane-d-c30/multiprocess_framework/__init__.py`.
Шлюз `light`, сессия `inspector-bottles-c7`: `5 passed, 1 warning in 1.11s`.
`ruff check`: `All checks passed!`; `ruff format --check`: `1 file already formatted`.
Первые прогоны были красными (4 failed): сначала клик шёл в daemon-потоке через `_within` (Qt-виджеты в чужом потоке, диалоги не вызывались), потом M1 pipeline упал на блоке раскладки (находка выше). Оба случая исправлены в тесте.

## Мутации (detached worktree `lane-d-c30-inj2` на HEAD cfb5f16fb, удалён после прогона)

Первая попытка с `sed -i` на macOS не применилась (5 passed) — повторено через Python-правку строки; в таблице второй прогон.

| Мутация | Прогноз (красные) | Наблюдено |
|---|---|---|
| A1: у `LayoutController.save_to_active_recipe` убран `foundation=` | M1[pipeline], M2[pipeline], тест характеризации | те же 3; 3 failed, 2 passed |
| A2: у `RecipesPresenter.on_save` убран `foundation=` | M1[recipes], M2[recipes] | те же 2; 2 failed, 3 passed |
| B1: у `LayoutController` `expected_rev=None` | только M2[pipeline] | только он; 1 failed, 4 passed |
| B2: у `RecipesPresenter` `expected_rev=None` | только M2[recipes] | только он; 1 failed, 4 passed |

Причина красного B1 проверена: вместо диалога конфликта показан «Рецепт сохранён: bridge_synth» (тихая перезапись), а не побочный сбой.

## Замер стенда -> что заменено -> чего нет

| Замер стенда | Что проверено заменой | Чего нет |
|---|---|---|
| M1: Save без правок `0/0`, повтор, mtime | клик по настоящей кнопке Pipeline и Recipes; байты и `st_mtime_ns` прежние дважды; ровно два диалога «сохранён» | ProcessManager, `run_gui` с `capture_foundation` из app.py (имена фундамента заданы тестом), настоящее окно и хуки MainWindow, граф из живого бэкенда, рабочий `bridge_synth.yaml` |
| M2: правка снаружи -> диалог конфликта | дописанная строка; клик; захвачен диалог с точным литералом; байты и mtime == ручная правка; для обоих путей | настоящий показ диалога на экране (проверен вызов, не пиксели), закрытие окна с конфликтом, автосохранение раскладки (покрыто `test_save_conflict_rev.py` на уровне презентера) |
| M3/M5 | не заменялись | нужна живая камера: ожидает камеры/стенда |

## Что я оставил открытым / ненадёжным

- Клик в основном потоке без дедлайна: зависший Save повесит тест (на практике диалоги подменены, а `pytest-timeout` стоит в окружении). Daemon-поток для Qt-виджетов неприменим.
- Кнопки ищутся по тексту «Сохранить» (ровно одна на вкладку, проверено ассертом); смена подписи кнопки сломает тест, а не продукт.
- Литерал `_POSITIONS_BLOCK` (400.0 / 100.0) снят с наблюдаемого вывода; он зависит от алгоритма стартового размещения узла и поменяется вместе с ним.
- M1 снят на «осевшем» файле, не на чистых байтах HEAD (см. находку); утверждение «рабочий файл стенда уже с раскладкой» выведено из логики, не проверено чтением рабочего файла (запрещено).
- Тесты Recipes-пути берут граф из `_Repo(live)`, а не из живого `services.topology` редактора; связь «редактор -> TopologyRepository» не проверяется.
- Находка про первый Save Pipeline: вопрос лиду, в `OPEN_QUESTIONS.md` я не писал (файл вне FILES).
