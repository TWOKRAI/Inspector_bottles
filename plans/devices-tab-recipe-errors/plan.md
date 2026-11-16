# Plan: вкладка «Устройства» не роняет слот при отказе записи рецепта (F3)

- **Slug:** devices-tab-recipe-errors
- **Дата:** 2026-11-16
- **Статус:** DRAFT (стадия 0, раунд 1: CHANGES REQUESTED 12 пунктов — внесены 2026-11-16; слепой tester дальше)
- **Ветка:** `fix/devices-tab-recipe-errors`
- **Полоса:** Д. Источник: `plans/queue/ORDER.md` строка 3 (F3, решение владельца 2026-10-28: отдельная задача после финального merge C-30), `docs/claude/OPEN_QUESTIONS.md:2061-2065`,
  `multiprocess_framework/modules/recipe/DECISIONS.md` поправка №11 п. 9. Строки F3 в `plans/queue/defects.md` нет; заводит лид при слиянии.
- **Разведка:** агент (haiku) 2026-11-16 по `git grep`, отдельного файла нет; факты со ссылками `путь:строка` проверены стадией 0 ([`docs/reviews/2026-11-16_task-f3-1.1-stage0.md`](../../docs/reviews/2026-11-16_task-f3-1.1-stage0.md)).

## Контекст

Три слота вкладки «Устройства» вызывают запись рецепта через `RecipeDevicesStore` и ловят только `RecipeDevicesError`:
`devices_common/add_page.py:176` (`_on_commit`), `devices_common/crud_actions.py:94` (`on_remove_clicked`), `crud_actions.py:179` (`_persist_and_sync`).
Это единственные три места записи рецепта из вкладок robot/vfd/devices_common: больше никто не пишет (проверено `git grep` стадией 0); слоты общие для robot и vfd.
Цепочка: `RecipeDevicesStore.upsert/remove` (`recipe_devices.py`) → `_write_devices` (`:170-181`) → `save_raw` (`adapters/stores/recipe_store.py:121`) → `RecipeManager.patch_recipe` → `_write`.
`_write_devices` переводит в `RecipeDevicesError` только `RecipeConflict`; чтение внутри `upsert/remove` (`_read_canonical_devices`) ничего не переводит.
Остальное вылетает из Qt-слота. Известно из цепочки (стадия 0):
- `RecipeLockTimeout(TimeoutError, подкласс OSError)` — `file_lock.py:56`, в тексте путь лок-файла;
- `RecipeFormatError(ValueError)` — `manager.py:67` (бросается при чтении и записи; в тексте slug, без пути и содержимого);
- `YamlWriteRefused(ValueError)` — `yaml_io.py:66` (в тексте полный путь, `yaml_io.py:422-424`);
- `YamlPatchConflict(ValueError)` — `yaml_io.py:62,266,336` (общий якорь/алиас YAML в `devices:`; публичный, но в `Raises` у `patch_recipe` не записан; **подозрение по чтению, не воспроизведено** — нужна проба с якорем);
- `OSError`: `PermissionError("файл только для чтения: {path}")` (`yaml_io.py:415-416`), `_atomic_write` (ENOSPC, sharing violation на `os.replace`, `yaml_io.py:435`), `os.open` лок-файла (`file_lock.py:99`), `mkdir` (`manager.py:540`), `read_bytes()` (`manager.py:516-520`).
Общего базового исключения «запись рецепта отказана» во framework нет (четыре несвязанные ветки наследования) — корень, вне этой задачи (решение 2026-10-28; в OPEN_QUESTIONS).
Тестов на эти исключения во вкладке нет (фейки бросают только `RecipeConflict`). Общего декоратора слотов и `sys.excepthook` во frontend нет.

## Решение (лид, 2026-11-16; владелец оставил выбор между двумя вариантами)

**Перевод на границе хранилища, в одном месте: `RecipeDevicesStore` переводит известные отказы записи/чтения рецепта в `RecipeDevicesError` с литералом без пути и без содержимого файла.**
Слоты не меняются: они уже ловят `RecipeDevicesError` и показывают его `str` (`add_page.py:178`, `crud_actions.py:96,181`; `__cause__` нигде не печатается).
Почему граница, а не «общий обработчик слотов» (отвергнуто):
- одна точка вместо каждого слота и всех будущих; закрывает и robot, и vfd;
- контракт хранилища уже обещает `Raises: RecipeDevicesError`, перевод `RecipeConflict` уже сделан на этой границе — новый перевод того же шаблона в той же точке, слой не добавляется (принцип 4);
- ловим ровно типизированный список известных отказов (включая класс `OSError` целиком — известный IO-отказ, не ошибка программиста); `AttributeError`/`KeyError` и прочее не переводятся и выходят наружу.
Не делаем здесь (вне объёма, OPEN_QUESTIONS строкой лида): чтение `list()/get()` (`_read_devices` ловит только `RecipeFormatError`, `OSError` из `read_bytes()` вылетает из `DeviceListPanel.refresh`, `device_list_panel.py:118`, и `robot/section.py:174`);
`multiprocess_prototype/frontend/widgets/tabs/recipes/presenter.py:247-249` (`on_create` ловит только `OSError`); `multiprocess_prototype/frontend/app.py:134-150` (`_save_active_topology` переводит только `RecipeConflict`);
общий базовый класс отказа записи во framework; блокировка GUI-потока до 5 с на ожидании лока (`OPEN_QUESTIONS.md:2063`).

## Принципы владельца

1, 2 (причина на границе хранилища, а не обход в слотах); 4 (слоёв не прибавляется); 5 (отказ записи устройства не валит GUI).

## Задачи

| Task | Суть | Уровень |
|---|---|---|
| 1.1 | Таблица «класс → литерал» и один контекст-менеджер перевода в `RecipeDevicesStore.upsert/remove`, тесты на реальной цепочке и на слотах | Middle (≈ 50 строк кода, ≈ 250 строк тестов) |

Цена: 5 участников × ~56k ≈ 280k + работа ≈ 180k.

## Task 1.1

- **Level:** Middle (минимум: не механический дифф — решения по составу ошибок) · **Assignee:** developer
- **Handoff:** tester (слепой, один раз, до кода) -> developer -> лид (инъекции) -> reviewer (стадия 5)
- **Gate:** light (`devices_common/tests`); medium (`multiprocess_prototype/frontend/widgets/tabs/services`, `multiprocess_framework/modules/recipe/tests`)
- **Module contract:** публичный API `RecipeDevicesStore` не меняется; `upsert/remove` бросают наружу только `RecipeDevicesError` для известных отказов записи/чтения рецепта (раньше — четыре разные ветки исключений)
- **Dependencies:** нет

```
TASK: 1.1 — F3: RecipeDevicesStore переводит отказ записи в RecipeDevicesError          PLAN: plans/devices-tab-recipe-errors/plan.md
ROLE: developer
CHAIN: tester (слепой) -> you -> лид (инъекции) -> reviewer
```

### DESIGN

(decided by the lead — you type it, you do not derive it)

1. `multiprocess_prototype/frontend/widgets/tabs/services/devices_common/recipe_devices.py`: импорт `RecipeLockTimeout`, `YamlWriteRefused`, `YamlPatchConflict` из `multiprocess_framework.modules.recipe` (рядом с `RecipeConflict, RecipeFormatError`).
2. **Одна таблица на уровне модуля** `_WRITE_FAILURES: tuple[tuple[type[BaseException], str], ...]`, порядок существенный (первое совпадение по `isinstance`, подкласс не должен проскочить):
   1. `RecipeLockTimeout` → «Рецепт занят другим процессом — повторите через несколько секунд»;
   2. `RecipeFormatError` → «Файл рецепта не читается или имеет неподдерживаемый формат — устройства не изменены»;
   3. `YamlWriteRefused` → «Не удалось безопасно записать рецепт — файл не изменён»;
   4. `YamlPatchConflict` → «Рецепт нельзя изменить точечно: общий узел YAML (якорь или алиас) — правьте файл вручную»;
   5. `OSError` → «Не удалось прочитать или записать файл рецепта (нет доступа или места на диске) — устройства не изменены».
   `RecipeLockTimeout` — подкласс `OSError`, поэтому он ДО `OSError`. Кортеж для `except` строится из таблицы (`tuple(cls for cls, _ in _WRITE_FAILURES)`), чтобы кортеж и тексты не разъехались.
3. **Один приватный контекст-менеджер** `_translating(self, slug)` (или функция), который оборачивает рабочий блок `upsert` и `remove` ПОСЛЕ `_require_active` и проверки `id` (чтение `_read_canonical_devices` + запись `_write_devices`):
   `except _WRITE_FAILURE_TYPES as exc:` → `logger.warning("Рецепт '%s': операция с устройствами отклонена: %s", slug, type(exc).__name__)` (ТОЛЬКО имя класса: без `str(exc)`, без пути, без содержимого) →
   `raise RecipeDevicesError(<литерал по isinstance-циклу>) from exc`. `RecipeDevicesError` (в т. ч. переведённый `RecipeConflict`) таблицей не ловится (наследует `Exception`) — отдельной ветки `except RecipeDevicesError: raise` НЕ нужно.
4. Обновить docstring `Raises` у `upsert` (`recipe_devices.py:112-115`) и `remove` (`:138-139`): добавить «отказ записи/чтения файла рецепта (блокировка, формат, запрет записи, ввод-вывод)».
5. `_read_devices` (путь чтения для UI) НЕ менять. Слоты (`add_page.py`, `crud_actions.py`), `robot/`, `vfd/`, framework `recipe` НЕ менять.

### FILES

1. `multiprocess_prototype/frontend/widgets/tabs/services/devices_common/recipe_devices.py` — п. 1–4
2. `multiprocess_prototype/frontend/widgets/tabs/services/devices_common/tests/test_recipe_devices_errors.py` (новый, слепой tester)
3. `multiprocess_prototype/frontend/widgets/tabs/services/devices_common/README.md` — строки 20-23: `upsert/remove` → `RecipeDevicesError` также при отказе записи/чтения рецепта (литерал без пути)

Не в FILES, делает лид при слиянии: `docs/claude/OPEN_QUESTIONS.md` (закрыть `:2061-2065`; новые строки — чтение `list()/get()`, `recipes/presenter.py:247-249`, `frontend/app.py:134-150`, нет общего базового класса отказа), `plans/queue/ORDER.md` (строка 3), `plans/queue/defects.md` (строка F3),
одна строка «Закрыто F3» в `multiprocess_framework/modules/recipe/DECISIONS.md` поправка №11 п. 9 (только текст документа; framework-код не трогаем).

Запрещено: слоты, robot/vfd/section, `multiprocess_framework/**` (кроме той одной строки DECISIONS — её делает лид), `Services/**`, `Plugins/**`, `process_manager_process.py`, `launcher/spawner.py`.

### REDS

**Реальная цепочка** (R1–R4, R10): `RecipeDevicesStore(RecipeStoreFromManager(RecipeManager(engine=<объект с recipes_dir>), recipes_dir), active_provider=lambda: slug)` на tmp-рецепте; образец — `build_chain` в `multiprocess_prototype/recipes/tests/test_save_noise_store.py:82-93` (FakeEngine + RecipeManager + RecipeStoreFromManager): скопировать ~12 строк, не импортировать из чужого `test_*`.
Тесты на ожидание лока — в daemon-потоке с join-дедлайном ≥ 8 с.
**Слоты** (R6, R7): слот → РЕАЛЬНЫЙ `RecipeDevicesStore` → внутренний фейк-хранилище, чьи `read_canonical`/`save_raw` бросают нужное исключение; образцы `_DictRecipeStore` (`tests/test_add_page.py:44-62`, `tests/test_crud_actions.py:36-57`). Фейк самого `RecipeDevicesStore` ЗАПРЕЩЁН (такой красный нельзя починить, слоты не меняются).
Qt: `QT_QPA_PLATFORM=offscreen`, `qtbot` нужен только R6; R7 идёт на `MagicMock` и patch.

| # | Свойство | Красное сейчас |
|---|---|---|
| R1 | реальная цепочка, лок рецепта занят чужим держателем (`recipe_file_lock(path, timeout=...)` в тесте), таймаут записи сокращён monkeypatch'ем имени `recipe_file_lock` в модуле `multiprocess_framework.modules.recipe.manager` (имя привязано в `manager.py:38`, по умолчанию `timeout=5.0` из `manager.py:541`) обёрткой с `timeout=0.1`; `upsert` → `RecipeDevicesError`, `str(exc) == литерал 1`, в `str(exc)` нет tmp-каталога; байты файла рецепта прежние (сравнивать файл рецепта, не каталог: рядом создаётся `<имя>.yaml.lock`) | да |
| R2 | то же для `remove` (устройство есть в файле) | да |
| R3 | файл рецепта не парсится (`"a: [\n"` как в `test_recipe_manager_write_api.py:437`, и корень-список `"- a\n"`) → `upsert` и `remove` → `RecipeDevicesError`, `str(exc) == литерал 2`, нет tmp-каталога; файл прежний | да |
| R4 | `RecipeManager(yaml_patcher=...)` (`manager.py:132`) бросает `YamlWriteRefused(f"{path}: …")` и отдельно `YamlPatchConflict(f"{path}: …")` (параметризовать) → `str(exc) == литерал 3` / `литерал 4`; путь из исходного сообщения в `str(exc)` не просочился | да |
| R5 | `RecipeConflict` по-прежнему → `RecipeDevicesError("Рецепт изменён снаружи — перезагрузите его")` (охрана) | нет |
| R6 | слот `AddDevicePage._on_commit` при `RecipeLockTimeout` из хранилища: исключение не выходит; `page._status.text() == литерал 1`, `page._status.styleSheet() == "color: red;"` (`add_page.py:216-219`); после отказа хаб не вызван, `committed == []`, `page._committed is False` | да |
| R7 | `on_remove_clicked` и `_persist_and_sync` (через `on_add_clicked` с патчем `DeviceEditorDialog`, шаблон `_EDITOR` из `test_crud_actions.py`) при `RecipeFormatError` и `YamlWriteRefused`: исключение не выходит; `QMessageBox.warning` (патч `...devices_common.crud_actions.QMessageBox`, как `test_crud_actions.py:79`) получил литерал (`MockMB.warning.call_args[0][2]`); после отказа `device_upsert` не отправлен (`sender.request_command` не вызван), `refresh_cb` не вызван | да |
| R8 | чужое исключение (`AttributeError`, `KeyError` из внутреннего фейка) НЕ переводится и выходит наружу (охрана от «ловим всё») | нет |
| R9 | `list()` с битым рецептом по-прежнему возвращает `[]` (охрана пути чтения) | нет |
| R10 | реальная цепочка, файл рецепта `os.chmod(path, 0o444)` → `upsert` → `RecipeDevicesError`, `str(exc) == литерал 5`, нет tmp-каталога (`PermissionError("файл только для чтения: {path}")`, `yaml_io.py:415-416`); под root (`os.access(path, os.W_OK)` истинно) — `pytest.skip` с явной причиной | да |
| R11 | свойство лога: `caplog` на реальной цепочке R1 — запись WARNING содержит `RecipeLockTimeout` и НЕ содержит tmp-путь | да |

Красных до правки: R1, R2, R3, R4 (×2), R6, R7 (×2), R10, R11 — каждое свойство своим тестом; охранные: R5, R8, R9.

Предсказания инъекций (лид пишет ДО прогона, повторяет после последнего теста):
- убрать `RecipeLockTimeout` из таблицы → красные {R1, R2, R6} (`RecipeLockTimeout` попадёт в пятую строку — тексты не совпадут; R11 зелёный: лог пишет `type(exc).__name__` при любой строке таблицы; R10 зелёный) — поправка лида после слепого tester;
- убрать `RecipeFormatError` → {R3, R7 (FormatError)}; убрать `YamlWriteRefused` → {R4 (Refused), R7 (Refused)}; убрать `YamlPatchConflict` → {R4 (Conflict)}; убрать `OSError` → {R10};
- поменять местами `RecipeLockTimeout` и `OSError` (порядок) → красные {R1, R2, R6}: подкласс получает литерал 5 (R11 зелёный по той же причине);
- `except Exception` вместо кортежа из таблицы → красный {R8};
- в литерал/лог подставить `str(exc)` → красные {R1, R2, R3, R4, R6, R7, R10, R11} (литералы не совпадают, путь просачивается);
- сузить `try` только до `_write_devices` (чтение вне) → красный {R3} (перевод на стороне чтения);
- убрать `from exc` — зелёные все (эквивалентная мутация для чёрного ящика; не заявлять охват).

### ACCEPTANCE

1. R1–R11 зелёные. Команды: `QT_QPA_PLATFORM=offscreen PYTHONPATH=<корень worktree> bash "$(git rev-parse --path-format=absolute --git-common-dir)/../scripts/machine_gate.sh" light D <python> -m pytest -q --tb=short multiprocess_prototype/frontend/widgets/tabs/services/devices_common/tests/test_recipe_devices_errors.py`;
   затем `devices_common/tests` целиком (light), `multiprocess_prototype/frontend/widgets/tabs/services` (medium), `multiprocess_framework/modules/recipe/tests` (medium, контроль: framework не менялся) — без новых красных против `main` (базовый прогон на `main` тем же набором).
2. `ruff check -q` и `ruff format --check` по изменённым файлам; `scripts/validate.py` не хуже `main`; `sentrux check .` не краснее `main`.
3. Проба `YamlPatchConflict` на реальном рецепте с якорем (`transport: &tr` в `devices:`): воспроизведено ли `YamlPatchConflict` при `upsert` — результат (воспроизведено / нет) в отчёт; если нет — R4 для `YamlPatchConflict` остаётся тестом через `yaml_patcher`.
4. Живой слот (лид, Qt offscreen): один запуск `AddDevicePage._on_commit` с реальным хранилищем и занятым локом → статус-строка с литералом 1, процесс не упал. Команда: тот же pytest-файл, R6 (на реальной цепочке — расширение лида, не часть слепого набора).

### OUT OF SCOPE

- Чтение `list()/get()` (`_read_devices`, `DeviceListPanel.refresh`, `robot/section.py:174`), `recipes/presenter.py:247-249`, `frontend/app.py:134-150`, общий базовый класс отказа во framework, блокировка GUI-потока до 5 с — в OPEN_QUESTIONS (лид).
- Общий обработчик слотов (отвергнут, см. «Решение»).

### TRAPS

- `RecipeLockTimeout` — подкласс `OSError`: порядок в таблице существенен; `isinstance`-цикл, не `type(exc)`.
- `RecipeFormatError` и `YamlWriteRefused`/`YamlPatchConflict` — `ValueError`-наследники, но разные классы; не ловить по общему предку `ValueError` (поймает и ошибки программиста).
- `from exc` оставляет исходное исключение в цепочке; GUI показывает только `str(RecipeDevicesError)`. В лог — имя класса, не текст.
- R1/R2 без шва таймаута стоят 5 с каждый (`manager.py:541`) — делать monkeypatch имени `recipe_file_lock` в `manager`.
- Текст литерала 1 обещает «повторите через несколько секунд», а GUI-поток уже простоял до 5 с (`OPEN_QUESTIONS.md:2063`, отложено).

## Журнал

- 2026-11-16 — план написан лидом полосы Д после разведки (haiku); выбран перевод на границе хранилища. Стадия 0 раунд 1 (reviewer, sonnet): выбор подтверждён; CHANGES REQUESTED 12 пунктов — внесены: состав ошибок расширен (`YamlPatchConflict`, `OSError` после `RecipeLockTimeout`), убрана эквивалентная ветка `except RecipeDevicesError: raise`, шов таймаута, описание реальной цепочки и слот-harness, предсказания инъекций, R10 (chmod), R11 (лог), единая таблица и контекст-менеджер, список записей лида.
