# Design: recipe-save-noise (C-30) — один дельта-движок записи рецепта

ТЗ для слепого тестера и исполнителей. Контракт плана — [`plan.md`](plan.md).
Факты сверены 2026-10-26 на `main` = `9b6645546` (раунд 3 — на `2bd24aa22`); пробы стадии 0 — папка [`probes/`](probes/)
(запуск — из папки плана, `PYTHONPATH` = корень репозитория; пути входных файлов — аргументами).
Директива владельца 2026-10-26: «Главное чтоб костылей не было, а делалось к лучшей и правильной архитектуре!!!!
Которая позволяет масштабировать и улучшать систему».

**Слепому тестеру:** читать только §2, §6 и блоки ACCEPTANCE задач. Остальное — не для него (см. `plan.md` «Конвейер»).

## 1. Факты (file:line)

| # | Факт | Где |
|---|---|---|
| F1 | `update_yaml_preserving` делает `data[key] = value` plain dict → поддерево заменяется целиком: комментарии внутри и flow-стиль теряются | `multiprocess_framework/modules/recipe/yaml_io.py:84-85` |
| F2 | `RecipeStoreFromManager.write` пишет `_denormalize(recipe.to_dict())` — все секции модели с умолчаниями | `multiprocess_prototype/adapters/stores/recipe_store.py:72-83`; `domain/entities/recipe.py:259-261` |
| F3 | `save_raw` пишет переданные top-level ключи целиком | `recipe_store.py:98-109` |
| F4 | `Topology.from_dict` прячет `name/description` в `metadata` только из-за `extra="forbid"`; читатель `metadata.name/description` в проде — 0 (единственный — тест `domain/tests/test_entities_roundtrip.py:765`); `SystemBlueprint` их уже типизирует | `domain/entities/topology.py:146-176`; `process_manager_module/topology/blueprint.py:383,388` |
| F5 | порядок `metadata` зависит от hash seed (цикл по множеству) | `topology.py:172` |
| F6 | Recipes/Pipeline/closeEvent-Save: `save_editor_topology_to_recipe` → `build_recipe_v3_raw` → `save_raw` | `recipes/save.py:71-140, 175-211`; `frontend/widgets/tabs/pipeline/layout_controller.py:388-446` |
| F7 | Явный Pipeline-Save делает `self._gui_positions.update(scene…)` — позиции узлов вне сцены СОХРАНЯЮТСЯ; карту заменяет только `_sync_positions_from_scene` (автосохранение раскладки / экспорт) | `layout_controller.py:434`; `:251-262` |
| F8 | Позиции и фиксация в контроллер грузит `load_topology_from_config()`; без этого override `gui_positions={}` стирает 11 позиций фикстуры | `layout_controller.py:170-176` |
| F9 | Канон Pipeline-пути (`Topology` → `PipelineModel` → `graph_to_blueprint` → `Topology`) == канон файла на всех 22 рецептах `multiprocess_prototype/recipes/*.yaml`; дельта на фикстуре — 0 | проба `probes/probe_r1.py`, `probe_r1b.py` (перепроверено 2026-10-26) |
| F10 | 6 рецептов без `blueprint.metadata` (`bridge_synth`, `dualcam_synth`, `dualcam_webcam`, `g1_perf_probe`, `region_pipeline`, `robot_demo`): Pipeline-Save добавит `locked_nodes: []` и позиции | `probe_r1b.py` |
| F11 | Дисплеи → `DisplayCatalogFromRecipe` → `store.write(slug, Recipe)`; `update(phone, enabled=True)` даёт нормализованную дельту ровно `/displays[3]/enabled` | `adapters/catalogs/display_catalog_recipe.py:201,239,274,308`; `probe_r2.py` |
| F12 | Камера: `read_raw` → мутация → `save_raw(slug, raw)`; Устройства: `save_raw(slug, {"devices": …})` | `camera/presenter.py:91-111`; `devices_common/recipe_devices.py:118,130` |
| F13 | Автосохранение раскладки: `save_layout` → `update_blueprint_metadata_preserving` | `recipe_store.py:111-123`, `yaml_io.py:128-167` |
| F14 | Миграции полагаются на замену поддерева (удаление ключей внутри) | `recipes/migrations/drop_display_name.py:88`, `displays_to_recipe.py:240` |
| F15 | Дерево — CRLF (`core.autocrlf=true`). Нынешний писатель переводит файл в LF. `yaml.load(bytes)` CRLF-файла + замена `\n`→`\r\n` даёт `\r\r\n` (76 шт.); чтение текстом + замена → исходные байты | `probe3.py` (не сохранён); `probes/probe_gui_add.py` |
| F16 | ruamel хранит комментарий НАД следующим соседом в хвосте предыдущего (ключ map, элемент списка, вложенный лист): удаление уносит его (`del procs[1]` уносит `# --- C ---`). Спайк ≈25 строк (перенос на хвост предыдущего соседа) работает на ruamel 0.19.1; не решено: лишняя пустая строка, удаление элемента 0 — первый шаг Task 1.1a (§2.3) | `probes/probe_ruamel.py`, `probe_spike.py` |
| F17 | Правило «префикс/суффикс + поиндексно» ломается на несмежных удалениях: `[b1,b2,b3,b4]→[b1,b3]` пишет b3 в слот b2; `difflib.SequenceMatcher(autojunk=False)` даёт два `delete` | `probes/probe_listrule.py` |
| F18 | `Recipe.from_dict` верхний `gui_positions` не переносит: у `Recipe` своё поле (`extra="forbid"`), значение берётся как есть; канон (`canonicalize_gui_positions`, хук `recipe_format_hook.py:35-41`) кладёт его в `blueprint.metadata`. Чтение `read()` из raw и запись из канона расходятся на 3 legacy-рецептах → `read()` стора — из канона (Task 1.1c). Проверено чтением, не прогоном | `domain/entities/recipe.py:91,220-257` |
| F19 | Каталог хаба — `ManifestStore(manifest).load().recipes`, относительный путь от каталога манифеста (`manifest.py:146,159`); `app.yaml:48` `recipes: recipes` → `multiprocess_prototype/recipes`. Каталог GUI — константа `PROJECT_ROOT / "multiprocess_prototype" / "recipes"` (`frontend/app.py:495`, `main.py:28`). Для единственного манифеста с `recipes:` в репозитории — один каталог; для другого манифеста хаб пойдёт за ним, GUI — нет (давнее расхождение, вне C-30; строка в OPEN_QUESTIONS, Task 1.3). Лок привязан к пути файла, поэтому корректен в обоих случаях | `orchestrator.py:139-159`; `frontend/app.py:495` |
| F20 | Межпроцессный лок уже есть в `app_module`: `_FileLock` (`msvcrt.locking` байта 0 с неблокирующими попытками и дедлайном на Windows; `fcntl.flock` без дедлайна на POSIX), sidecar `<manifest>.lock`; `.gitignore:150` игнорирует `*.yaml.lock` | `multiprocess_framework/modules/app_module/store.py:36-53,337-420` |

## 2. Дельта-движок (framework, `recipe/yaml_io.py`) — один на все записи

### 2.1 Публичный API (module-contract: public-api-change)

> **Сигнатура `patch_recipe(slug, before, after) -> bool` ниже заменена §9.1–9.2, §9.5:** `patch_recipe(slug, after, *,
> expected_rev, layout=None) -> str`. Движок (`patch_yaml_preserving`, `apply_delta`, `YamlPatchConflict`) — как здесь.

```python
def patch_yaml_preserving(path: str | Path, before: dict[str, Any], after: dict[str, Any]) -> bool
def apply_delta(target: dict[str, Any], before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]
class YamlPatchConflict(ValueError)
# RecipeManager (manager.py) и RecipeManagerProtocol (interfaces.py):
def patch_recipe(self, slug: str, before: dict, after: dict) -> bool
```

- `patch_yaml_preserving` — дельта `before → after` (plain-dict) применяется к ruamel-документу файла.
  `True` — файл записан; `False` — дельта пуста, файл не открывался на запись (байты и `st_mtime_ns` прежние).
- `apply_delta` — та же дельта на plain-dict `target`; `target` не мутируется (возврат — новая глубокая копия).
- `YamlPatchConflict` — путь дельты не ложится на цель (§2.4); бросается до записи, файл цел.
- `RecipeManager.patch_recipe` — путь `engine.recipes_dir / f"{slug}.yaml"` → инжектируемый `yaml_patcher`
  (параметр `__init__`, симметричен `yaml_updater`, по умолчанию `patch_yaml_preserving`). Писатель файлов
  рецепта — API фреймворка; прототип только делегирует. **Pre:** `slug` непустой и `Path(slug).name == slug`
  (нет разделителей пути, `..`), иначе `ValueError` до любого обращения к файлу. **Post:** возврат движка.
  Метод — в классе и в `RecipeManagerProtocol` (`recipe/interfaces.py:114`, `@runtime_checkable` у `:113`).
- `update_yaml_preserving(path, updates)` и `update_blueprint_metadata_preserving(path, metadata_updates)` —
  замороженные тонкие контракты над тем же движком: `before` = текущее поддерево файла по ключам `updates`
  (plain), `after` = `before` с заменёнными значениями. Итоговое содержимое — как раньше (значение ключа
  заменено целиком, ключи внутри, которых нет в новом значении, удалены — F14), но равные части не
  трогаются. **Изменение поведения для всех вызывающих (в ADR):** пустая дельта — без записи; EOL файла
  сохраняется. `update_blueprint_metadata_preserving` сохраняет no-op без файла / без `blueprint`.

### 2.2 Правила дельты

1. **Mapping ↔ Mapping.** Ключ только в `before` → удалить; только в `after` → добавить (в конец, в порядке
   `after`); в обоих → рекурсия. Перестановка ключей при равных значениях — пустая дельта.
2. **list ↔ list.** Равны → не трогать. Иначе — `difflib.SequenceMatcher(None, kb, ka, autojunk=False)`,
   где `kb`/`ka` — ключ элемента `json.dumps(x, sort_keys=True, ensure_ascii=False, default=str)`.
   Опкоды применяются к цели с конца списка к началу: `equal` — не трогать; `delete` — удалить элементы;
   `insert` — вставить на место; `replace` — поиндексная рекурсия на перекрытии, остаток — вставка/удаление.
   Сопоставления по `id`/`process_name` нет.
3. **Скаляры** равны, если `a == b` И совпадает вид: `bool` / `int` / `float` / `str` / `None` / прочее (`bool`
   проверяется раньше `int`; подклассы ruamel — того же вида, что база). `1 ≠ True ≠ 1.0`. Ключ JSON в п. 2 это
   же различение соблюдает (`1`, `1.0`, `true`).
4. **Разные типы** (map ↔ list ↔ скаляр) → значение заменяется целиком.

### 2.3 Применение к цели

- Изменённый лист — присваивание в существующий узел (комментарий ключа сохраняется).
- Ключа нет в цели (нормализованный `before` шире файла) → `node[key] = deepcopy(after[key])`; отсутствующие
  промежуточные контейнеры создаются (6 рецептов без `blueprint.metadata`, F10); удаление отсутствующего ключа — no-op.
- **Якорь и алиас** (`dataset_circle_capture.yaml:319` `gui_positions: &id001`, `:396` `*id001`): узел с якорем
  меняется на месте, только если `after` во всех местах ссылок одинаков (правка видна во всех); иначе
  `YamlPatchConflict` с путём — алиас не разрывается молча.
- **Удаление ключа map, элемента списка или вложенного листа не уносит комментарий следующего соседа:**
  полнострочные комментарии из хвоста удаляемого (его самый глубокий последний лист) переносятся в хвост
  предыдущего соседа; удаляется первый → в комментарий-заголовок контейнера. Собственный EOL-комментарий
  удаляемого уходит вместе с ним. Проверка: комментарий присутствует ровно один раз и стоит перед следующим
  элементом. Два случая спайка не решены — первый шаг Task 1.1a (teamlead), критерий там. Известные варианты
  (`probes/probe_spike.py`): лишняя пустая строка — спайк склеивает `old.value + keep`, где оба несут пустую строку →
  склеивать без ведущего `
`; элемент 0 — у спайка нет ветки (`pos == 0` → выход) → перенос в комментарий-заголовок
  контейнера (`ca.comment`) или в слот ключа родителя (`parent.ca.items[key][2]`). Не укладывается → эскалация `cto`;
  потеря комментария не принимается.
- **EOL:** файл читается текстом (universal newlines) — в ruamel байты не подаются (F15). EOL определяется
  отдельно по сырым байтам: терминатор первой строки (`\r\n` или `\n`); файл без терминатора → `\n`.
  Смешанный EOL нормализуется к EOL первой строки (правило записано в ADR). Дамп пишется с этим EOL через
  `_dump_atomic` (приватный параметр `newline`).
- Файла нет → создать из `after` целиком, `True`. Запись атомарная, права файла сохраняются (ADR-RCP-008).

### 2.4 Конфликт

Индекс вне списка цели; на пути в цели скаляр/список там, где дельта ждёт mapping (кроме §2.2.4) →
`YamlPatchConflict` с путём в сообщении, файл не пишется.

## 3. Почему before/after

Вызывающий строит `before` тем же нормализатором, что `after`; шум модели — с обеих сторон и сокращается.
В движке нет эвристики про умолчания.

## 4. Подключение (prototype)

### 4.1 `RecipeStoreFromManager` — только делегирует (Task 1.1c)

> **Заменено §9–§10 и `tasks/1.1c.md` DESIGN 1** (чтение `read_canonical`, `expected_rev`, `layout`); текст ниже — история.

- `save_raw(slug, data)`: «желаемое состояние, минимальная правка». `raw = self._rm.read_recipe(slug) or {}`;
  `before = {k: raw[k] for k in data if k in raw}`; `self._rm.patch_recipe(slug, before, data)`. Ключи вне
  `data` не трогаются. Сигнатура Protocol и `FakeRecipeStore` не меняются.
- `write(slug, recipe)`: `raw = read_raw(slug) or {}`; `before = _denormalize(Recipe.from_dict(raw).to_dict())`
  (`{}` при пустом raw); `after = _denormalize(recipe.to_dict())`; `self._rm.patch_recipe(slug, before, after)`.
- `save_layout(...)`: `raw = read_raw(slug)`; нет файла или `raw["blueprint"]` не dict → no-op; иначе `after` =
  копия raw с заменёнными `blueprint.metadata.{gui_positions,locked_nodes}` → `patch_recipe(slug, raw, after)`.
- Камера, Устройства, Дисплеи кода не меняют.

### 4.2 Корневая правка `Topology` (Task 1.7, бывшая 1.1d)

`name: str | None = None`, `description: str | None = None` — типизированные поля `Topology`. Удаление этих двух
ключей при `None` — в `@model_serializer(mode="wrap")` на `Topology` (не в `to_dict`): `Recipe.to_dict()` =
`model_dump(mode="json")` (`recipe.py:259-261`) сериализует вложенный `Topology` мимо его `to_dict`, и новый файл
получил бы `name: null` (проба `probes/probe_nested_none.py`). `to_dict` остаётся `model_dump(mode="json")`. Не
`exclude_none` — у процессов есть законные `null`. Цикл переноса в `from_dict` — только для `display_definitions`
(один ключ — порядок детерминирован). `blueprint.name` файла теперь в модели там же, где в файле.

**Изменение поведения:** `topology.apply` несёт имя блюпринта из файла вместо умолчания `"default"`. Читатели
проверены (стадия 0): читатели `metadata` берут только `gui_positions`/`locked_nodes`; `SystemBlueprint` типизирует
`name`/`description` (`blueprint.py:383,388`); `topology_diff` читает только `processes`/`wires`/`displays`.

### 4.3 `recipes/save.py` (Task 1.2)

> **Заменено §10 п. 3 и `tasks/1.2.md` DESIGN 0, 3** (`topology_to_canonical`, раскладка той же записью); ниже — история.

```
raw = recipes.read_raw(slug)                        # None → RecipeNotFoundError
canon = _canonical_topology                         # Topology.from_dict(x).to_dict(), только processes/wires/displays
before = build_recipe_v3_raw(raw, canon(raw.get("blueprint") or {}))
after  = build_recipe_v3_raw(raw, canon(topology), gui_positions=…, locked_nodes=…)
validate_recipe_blueprint(after.get("blueprint", {}))
recipes.save_raw(slug, apply_delta(raw, before, after))
```

- `ValidationError` нормализатора на любой стороне → `RecipeValidationError`, записи нет (GUI показывает
  `QMessageBox.critical`, как сейчас). Сообщения — из `exc.errors(include_input=False, include_url=False)`:
  строка на ошибку `"<loc через точку>: <msg>"`. Не `str(exc)` — он содержит входные значения конфига.
- `build_recipe_v3_raw`, правка контракта Post: override-коллекция, пустая (`{}`/`[]`), НЕ создаёт ключ
  `gui_positions`/`locked_nodes`, которого не было в `blueprint.metadata` рецепта; непустые позиции — содержимое
  пользователя, пишутся (F10).
- Новые элементы (процесс/провод/дисплей, добавленные в GUI) пишутся в канонической форме модели — решение
  плана, не владельца (это содержимое пользователя в форме модели).

## 5. Не GUI

`RecipeManager.duplicate` (дельта `{name}`), миграции (F14), `Plugins/sim/scene_source/plugin.py:754` — идут
через `update_yaml_preserving`, т.е. через тот же движок; их код не меняется. Бэкенд `recipe_engine.py` (`save`,
миграция в `load`) и `service.py` (`recipe.save`) — через движок, Task 1.4 (§8.2). FREEZE: `layout_controller.py:200`, `topology/presenter.py:77`.

## 6. Матрица приёмки

Фикстура A — `multiprocess_prototype/recipes/tests/fixtures/letter_robot_sim_pre_c30.yaml` =
`git show efc2612c3^:multiprocess_prototype/recipes/letter_robot_sim.yaml` (600 строк; комментарии T3.7 ×2, Task 5.3b,
Ф3.8/G1; flow `{P_ZONE_MAX: 6000}`, `{enabled: true, max_retries: 3, window_sec: 60}`; `blueprint.name: default`
на верху blueprint). **Байты строит тест:** `src = fixture.read_bytes().replace(b"\r\n", b"\n")` → LF-копия в
`tmp_path`; CRLF-вариант — `src.replace(b"\n", b"\r\n")`. Сравнение — байты копии до/после; строки диффа — литералы.
Фикстура B — литерал в тесте: рецепт без `blueprint.metadata`, два процесса, один провод.
Файлы тестов — по одному на задачу (коммит задачи не краснеет от тестов следующих): framework —
`recipe/tests/test_yaml_patch.py` (1.1a), `recipe/tests/test_thin_contracts.py` (1.1b); prototype —
`recipes/tests/test_save_noise_store.py` (1.1c: Дисплеи, Камера, Устройства, раскладка, CRLF),
`recipes/tests/test_save_noise_topology.py` (1.7), `recipes/tests/test_save_noise_save.py` (1.2: Recipes, Pipeline).

| Путь (вызов как у GUI) | Сценарий | Ожидание |
|---|---|---|
| Дисплеи `persist()` | без правок | байты и `st_mtime_ns` прежние |
| Дисплеи `update(spec phone, enabled=True)` | одна правка | дифф ровно `-    enabled: false` / `+    enabled: true` |
| Дисплеи `update` True → False | пара | байты прежние |
| Дисплеи `register(DisplaySpec(display_id="c30_tmp", display_name="C30 tmp"))` → `unregister("c30_tmp")` | пара | байты прежние |
| Дисплеи `unregister("phone")` | удаление | дифф = 16 строк блока `- id: phone` + 2 строки привязки `phone` в `blueprint.displays` |
| Recipes «Сохранить» (`RecipesPresenter.on_save` или `save_editor_topology_to_recipe` с `Topology.from_dict(A.blueprint).to_dict()`) | без правок | байты прежние |
| Recipes «Сохранить» | `protected` у `camera_0` → `true` | дифф ровно `-      protected: false` / `+      protected: true` |
| Pipeline «Сохранить» (`PipelinePresenter.save_to_active_recipe`; модель из A, раскладка через `presenter._layout.load_topology_from_config()`) | без правок | байты прежние (жёсткая строка) |
| Pipeline «Сохранить» на B | без правок | нет строки с `locked_nodes`; добавленные строки — только `metadata:`/`gui_positions:` и позиции узлов B |
| Recipes «Сохранить», топология не парсится `Topology` | ошибка | `RecipeValidationError`, байты прежние |
| Камера `save()` | `pending` = значения файла | байты прежние |
| Устройства `upsert(robot_main как в файле)` | без правок | байты прежние |
| Устройства `upsert(robot_main, transport.port=5022)` | одна правка | дифф `-      port: 5021` / `+      port: 5022`; оба `# T3.7` на месте; секция `blueprint` не тронута |
| Устройства `remove("vfd_belt")` | удаление | дифф = 12 строк `vfd_belt` |
| Раскладка `save_layout` (позиции и фиксация из файла) | без движения | байты и `st_mtime_ns` прежние |
| Дисплеи `update` True → False в подпроцессе | `PYTHONHASHSEED` 0..3 | байты одинаковы (1.1c `test_displays_toggle_byte_identical_across_hash_seed`) |
| CRLF-вариант A | галочка дисплея | только `\r\n`, нет `\r\r\n`, дифф — одна строка (1.1c `test_displays_toggle_one_line_then_pair_byte_identical[crlf]`) |

## 7. Риски

- **Р3 (гонка / устаревший `after`) — закрыт §9.1 (ревизия, `RecipeConflict`); текст ниже — почему.** `before` берётся из файла в момент записи, `after` — из снимка, прочитанного
  раньше. Устаревший `after` откатывает ВСЕ поля, где снимок ≠ файлу на момент записи (пример: правка руками
  `port` 5021 → 5022 между чтением и записью будет откачена), а не только поля, изменённые вызывающим. Сейчас
  откатывается весь файл. Правильное решение — 3-way merge с базой = снимок при чтении (`patch_recipe` уже
  принимает `before` от вызывающего) — строка в `docs/claude/OPEN_QUESTIONS.md` (Task 1.3).
- **Р4 (YAML 1.1 ↔ 1.2).** `read_recipe` — PyYAML `safe_load` (1.1: `yes` → `True`), документ — ruamel (1.2:
  `yes` → строка). Неизменённый лист не пишется (дельта считается в одном пространстве), но в тонких контрактах
  (`before` из документа, `after` от вызывающего) `yes` перепишется как `true`. Как и сейчас (сейчас — всё
  поддерево). RED на неизменённый лист — в Task 1.1c.
- **Р5.** Перенос комментария (§2.3) — внутренности ruamel; спайк есть, два открытых случая (F16) — первый шаг 1.1a.
- **Р6 (база `rev` редактора).** На старте база берётся с тех же байтов, из которых строится топология (одно чтение,
  Task 1.8 DESIGN 2) — риска нет. Двойное чтение — только на пути активации: `rev` вторым чтением на `RecipeActivated`, после
  `Project._apply_activate_recipe` (`domain/entities/project.py:920-960`); правка файла между двумя чтениями не видна
  как конфликт. Остаточный риск, принят (Task 1.8).

## 8. Охрана одного писателя (Task 1.5; решение владельца 2026-10-26: «Надо решать и делать, чтобы не обходили его»)

### 8.1 Механизм

AST-тест-страж `multiprocess_framework/modules/recipe/tests/test_single_writer_guard.py` — по образцу уже живущего
`multiprocess_framework/modules/logger_module/tests/test_std_logger_guard.py` (AST, а не греп; весь Python репозитория
(`git ls-files '*.py'`), кроме тестов, `.venv`, `.claude/worktrees`, кэшей сборки и `EXEMPT_DIRS` «каталог → причина»; allowlist «файл → причина»; мёртвая строка
allowlist — тоже красный). Почему не sentrux и не ruff: `.sentrux/rules.toml` выражает границы модулей, а не
функций; ruff в проекте — только `E`, `F` (`pyproject.toml:387`), `TID251` banned-api — правка общей конфигурации
ради одного правила, и он не ловит `yaml.safe_dump` в рецепт. Тесты (`*/tests/*`, `test_*.py`, `conftest.py`) не сканируются.

Сопоставление — по паре «разрешённый модуль + имя», не по листовому имени: относительный импорт разрешается через
`node.level` от пути файла (`recipe/manager.py:28`, `recipe/__init__.py:19` импортируют относительно); ложное
срабатывание, которого быть не должно: `multiprocess_prototype/frontend/widgets/tabs/settings/yaml_io.py`
(`from ..yaml_io import load_settings` — другой модуль). Формы, которые сканер обязан ловить (самопроверка, ids):
`yaml_dump`, `safe_dump_alias`, `from_yaml_import`, `module_alias` (`import yaml as y`), `star_import`
(`from yaml import *`, `from multiprocess_framework.modules.recipe import *`), `dump_all` (`dump_all`/`safe_dump_all`),
`relative_import`, `ruamel_dump`, `ruamel_alias` (`from ruamel.yaml import YAML as Y`), `shim_import`, `engine_import_alias`.

Каталоги вне сканирования (`EXEMPT_DIRS`, причина обязательна): `apps/`, `scripts/`, `tools/`, `examples/`, `Utils/`,
`workspace/`, `robot/`, `docs/`, `plans/` — исполнитель решает «сканировать или исключить» по каждому, с причиной в
словаре (по умолчанию — сканировать). `backend_ctl/probes/` каталогом НЕ исключается: `probe_5_13_orchestrator_layer.py:89`
и `probe_basket2_live.py:89` пишут `multiprocess_prototype/recipes/_probe_*.yaml` (`RECIPES` — `:52`, `:60`), т.е.
внутрь каталога рецептов; условие лида для исключения каталога («пишут вне `recipes/`») не выполнено → пофайловые
строки R2 с причиной «стендовый зонд: временный рецепт прогона `_probe_*.yaml`, не рецепт репозитория».

Два правила:
- **R1 — писатели движка.** Импорт (любая форма: `import … as`, `from … import … as`, атрибут модуля) имён
  `patch_yaml_preserving`, `update_yaml_preserving`, `update_blueprint_metadata_preserving`, `_dump_atomic`,
  `_make_yaml` из `multiprocess_framework.modules.recipe[.yaml_io]` или из шима `multiprocess_prototype.recipes.yaml_io`
  — разрешён только в самом движке `multiprocess_framework/modules/recipe/yaml_io.py` и в allowlist R1 (весь модуль
  `recipe` больше не исключён: `manager.py`, `service.py`, `recipe_engine.py` — строками allowlist R1 с причиной).
- **R2 — любой YAML-дамп.** Вызовы `yaml.dump`, `yaml.safe_dump`, `safe_dump`/`dump`, импортированные из `yaml`
  (с алиасами), и `.dump(` в файле, импортирующем `ruamel.yaml` или `_make_yaml`, — разрешены только в
  `multiprocess_framework/modules/recipe/yaml_io.py` и в allowlist R2 (храповик: каждый файл, пишущий YAML, объявлен с причиной
  «что за файл он пишет»). Статически «цель — рецепт» не определить; новый пишущий YAML файл краснит тест, и его
  причина видна на ревью. Цена: новый законный писатель YAML добавляет одну строку.

Публичная поверхность: `recipe/__init__.py` экспортирует `apply_delta` (чистая функция, без IO) и `YamlPatchConflict`;
`patch_yaml_preserving` НЕ экспортируется — путь записи рецепта для прототипа — `RecipeManager.patch_recipe`.
Существующие экспорты `update_yaml_preserving` / `update_blueprint_metadata_preserving` остаются (принцип 3: публичный
путь — контракт, заморозить, не удалять); их использование ограничивает R1. `yaml_io` остаётся общим YAML-писателем по
пути модуля (второй потребитель — пресет `scene_source`, ADR-RCP-008), поэтому охрана — по использованию, не по приватности.

### 8.2 Инвентаризация писателей файлов рецепта (`git grep`, 2026-10-26)

| Писатель | Что пишет | Решение |
|---|---|---|
| `multiprocess_framework/modules/recipe/yaml_io.py` | движок | сам писатель |
| `…/recipe/manager.py` (`patch_recipe`, `duplicate` → `update_yaml_preserving`) | рецепт | API писателя |
| `…/recipe/recipe_engine.py:159-196` `save` (через `manager.py:137-143`), `:262-280` перезапись после миграции | снимок config-store (envelope v1/v2) | **маршрутизировать** (Task 1.4): дельта только по путям snapshot; затем allowlist R1 «snapshot через движок» |
| `…/recipe/service.py:309-330` `save` (`safe_dump`, `recipe.save` хаба, ADR-RCP-007; docstring `:96` признаёт потерю комментариев) | нормализованный рецепт с `rev` | **маршрутизировать** (Task 1.4): `before` = нормализованный текущий файл, `after` = нормализованное тело; затем allowlist R1 |
| `multiprocess_framework/modules/state_store_module/recipes/recipe_engine.py` | — | реэкспорт класса из `recipe` (19 строк), сам не пишет; вне полосы Д, правки нет |
| `multiprocess_prototype/backend/state/recipes/recipe_engine.py` | — | доменная обёртка прототипа (composition root: миграции v1→v2 и `DEFAULT_CONFIG_PATHS`), переопределяет только `__init__`; пишет унаследованный `save` модуля `recipe` → покрыта Task 1.4; правки нет |
| `multiprocess_prototype/adapters/stores/recipe_store.py` | рецепт из GUI | через `RecipeManager.patch_recipe` (1.1c) |
| `multiprocess_prototype/recipes/save.py` | рецепт из GUI | через `save_raw` → `patch_recipe` (1.2) |
| `multiprocess_prototype/recipes/migrations/drop_display_name.py:88`, `displays_to_recipe.py:240` | каталог рецептов офлайн | allowlist R1: офлайн-миграция по пути, через тонкий контракт движка (нет slug/engine) |
| `multiprocess_prototype/recipes/migrations/canonicalize_gui_positions.py:214` (ruamel `yaml.dump` напрямую) | каталог рецептов офлайн | **маршрутизировать** через `patch_yaml_preserving` (до/после — plain); затем allowlist R1 с той же причиной |
| `multiprocess_prototype/recipes/yaml_io.py` | реэкспорт | allowlist R1: шим, публичный путь импорта (FREEZE) |
| `multiprocess_framework/modules/recipe/__init__.py:19` | реэкспорт `update_*_preserving` | allowlist R1: публичный экспорт модуля, заморожен (принцип 3) |
| `backend_ctl/probes/probe_5_13_orchestrator_layer.py:89`, `probe_basket2_live.py:89` (`safe_dump`) | временный `_probe_*.yaml` в `multiprocess_prototype/recipes/` | allowlist R2 пофайлово: стендовый зонд, не рецепт репозитория; остальные дампы `backend_ctl/probes/` — сверяет исполнитель |
| `multiprocess_prototype/frontend/widgets/tabs/pipeline/layout_controller.py:206` (`save_topology_to_file`) | топология в произвольный файл | allowlist R2: FREEZE, нет живого вызывающего; не формат рецепта v3 |
| `multiprocess_prototype/frontend/widgets/topology/presenter.py:81` (`save_to_file`) | `SystemBlueprint` в произвольный файл | allowlist R2: FREEZE, нет живого вызывающего; не формат рецепта v3 |
| `Plugins/sim/scene_source/plugin.py:754` (`update_yaml_preserving`) | пресет слоёв `line_sim` | allowlist R1: не рецепт |

Не-рецептные писатели YAML (allowlist R2 с причиной «что пишет»; список уточняет исполнитель AST-сканом):
`Plugins/calibration/camera_robot/store.py`, `Services/auth/storage/yaml_users.py`, `Services/device_hub/registry/store.py`,
`Services/layer_render/metadata.py`, `Services/layer_render/preset.py`, `Services/ml_train/config.py`,
`Services/ml_train/export.py`, `Services/robot_comm/store.py`, `multiprocess_framework/modules/app_module/store.py`,
`…/data_schema_module/container/registers_container.py`, `…/data_schema_module/serialization/converter.py`,
`…/data_schema_module/serialization/io.py`, `…/display_module/registry.py`,
`…/frontend_module/managers/{config_snapshot_manager,theme_presets_manager,yaml_persistence_store}.py`,
`…/message_module/core/message.py`, `…/process_module/configs/observability_companion.py`,
`…/state_store_module/persistence/persistence_manager.py`, `multiprocess_prototype/frontend/managers/theme_presets_manager.py`,
`multiprocess_prototype/frontend/prefs/store.py`, `…/tabs/plugins/presenter.py`, `…/tabs/services/presenter.py`,
`…/tabs/services/neural/dataset_gen_section.py`, `…/tabs/settings/yaml_io.py`. Эти файлы только перечисляются в тесте —
не правятся (часть — вне полосы Д: `Services/device_hub/**`, `process_manager_module/**` не трогаются).

## 9. На перспективу: ревизия, `before` у менеджера, изоляция ruamel, только slug, `save_layout` (решение владельца 2026-10-26)

Цитата: «да, все добавляй и закладывай на перспективу развития». Целевая форма — рецепт-папка ADR-RCP-006
(`recipes/<name>/topology.yaml` + `params/*.yaml`) и раскладка отдельным файлом (решение очереди №20). C-30 не делает
ни то, ни другое, но после C-30 оба перехода — правка ТОЛЬКО внутри `RecipeManager`.

### 9.1 (а) Оптимистичная ревизия и межпроцессный лок — Tasks 1.1b, 1.1h, 1.1e, 1.7, 1.8

- `compute_rev(raw: bytes) -> str` — одна функция модуля: переезжает из `service.py:399` в `recipe/format.py`; `service.py`
  импортирует её оттуда (имя `service.compute_rev` остаётся — публичный путь, FREEZE).
- `RecipeManager.read_recipe_rev(slug) -> tuple[dict | None, str | None]` — тело и `rev` одного чтения байтов.
- Запись: `patch_recipe(slug, after, *, expected_rev: str | None, layout=None) -> str` и `save_layout(..., *, expected_rev) -> str | None`
  возвращают новый `rev`. `expected_rev` ≠ `rev` файла → `RecipeConflict(slug, expected_rev, current_rev)` (типизированное,
  экспортируется из `recipe/__init__.py`), файл не тронут. `expected_rev=None` — только для нового файла (файла нет);
  для существующего — `ValueError` (запись без базы запрещена). Пустая дельта → прежний `rev`, без записи.
- Сравнение и запись — под межпроцессным локом (решение владельца 2026-10-26, F1 ревью раунда 3). `service._lock` —
  `threading.Lock` экземпляра `RecipeService` (`service.py:235-250`): между процессами (хаб — `orchestrator.py:139-159`,
  GUI — `frontend/app.py:501-524`) он не значит ничего. Механизм — одна функция модуля `recipe`:
  `recipe/file_lock.py` `recipe_file_lock(path, *, timeout=5.0)` (контекстный менеджер, Task 1.1h). Lock-файл
  `<slug>.yaml.lock` рядом с рецептом (уже в `.gitignore:150`). Windows — `msvcrt.locking(LK_NBLCK)` байта 0, POSIX —
  `fcntl.flock(LOCK_EX | LOCK_NB)`; оба — неблокирующие попытки до дедлайна, затем `RecipeLockTimeout(TimeoutError)`
  (бесконечного ожидания нет). Stale lock-файл не удаляется: ОС снимает лок при смерти держателя, `unlink` дал бы гонку
  по inode. Нереентерабелен: лок берёт внешний публичный метод один раз. Пользуются `RecipeService.save/delete` (1.1h)
  и `RecipeManager.patch_recipe/save_layout` (1.1e); `RecipeEngine.save` (снимок без `rev`) — нет (вне C-30). Каталоги
  хаба и GUI — F19. Образец платформенных веток — `app_module._FileLock` (F20), не импортируется. Тот же лок нужен
  переходу на папку (несколько записей атомарно, §9.6).
- GUI: операции «прочитал → изменил → записал» в одном вызове (Дисплеи, Камера, Устройства) берут `rev` своего чтения;
  редактор (Recipes/Pipeline-Save, closeEvent, автосохранение раскладки) берёт базовый `rev` из `TopologySession`
  (слот `(slug, base_rev)`, захват на `RecipeActivated` через `read_raw_with_rev`; база отдаётся, только если slug
  записи = slug базы; после записи база = возвращённый `rev`; `on_create` — без базы; Р6; Task 1.8). В сторе базу
  не хранить: чтения Дисплеев/Камеры/Устройств молча обновляли бы её. `RecipeConflict` → существующий путь `QMessageBox` с текстом
  «Рецепт изменён снаружи — перезагрузите его» (без записи). Закрывает Р3.

### 9.2 (б) `before` строит менеджер

> **Заменено §10 (канон через `read_canonical` и один адаптер) и задачами 1.1e, 1.1f, 1.1g**; «апдейт вызывающим» ниже — история.

- Публичный API: `patch_recipe(slug, after, *, expected_rev)`. `before = N(текущий файл)`, `after' = N(after)`, движок
  применяет дельту `before → after'`. `N` — инжектируемый `format_hook.normalize` (параметр `RecipeManager.__init__`,
  тот же Protocol, что хук сервиса `service.py`); по умолчанию — тождество (форма файла, `yaml.safe_load`).
- Одного канонического нормализатора для всех GUI-путей НЕТ (факт): Дисплеи — модель `Recipe` (умолчания процессов), Save —
  канон `Topology` внутри `build_recipe_v3_raw`, Камера/Устройства — raw. Минимальный контракт: `N` работает в форме
  файла; вызывающий в модельном пространстве сам переводит правку в форму файла чистой `apply_delta(raw, M(raw), M(edited))`
  и передаёт результат как `after`. Доказательство — пробы F9/F11 (канон сокращается) и матрица §6; плюс приёмка 1.1e: для
  каждого из 22 рецептов `patch_recipe(slug, read(slug), expected_rev=rev)` → `rev` прежний, записи нет (оба `N`: тождество и
  хук сервиса).
- `patch_yaml_preserving(path, before, after)` — приватный движок модуля (не экспортируется, §8.1).

### 9.3 (в) ruamel изолирован — Tasks 1.1a, 1.6

Всё, что знает о внутренностях ruamel (`CommentedMap/Seq`, `ca.items`, `CommentToken`, `_make_yaml`, перенос
хвостового комментария), — в одном приватном модуле `recipe/_ruamel_doc.py`; `yaml_io.py` вызывает только его функции.
Зависимость: `pyproject.toml:13` сейчас `ruamel.yaml>=0.18` (lock — 0.19.1) → `ruamel.yaml>=0.19.1,<0.20` (минорная
линия, на которой проверена форма токенов); `uv.lock` — `uv lock`. Тест `recipe/tests/test_ruamel_contract.py` громко
краснеет на версии вне `0.19.x` и на неожиданной форме токена комментария (длина `ca.items[k]`, тип и позиция токена).

### 9.4 (г) Только slug — Tasks 1.1c, 1.5

Вызывающие адресуют рецепт по slug; путь к файлу видит только `RecipeManager` (`recipes_dir` у Protocol `:170` — публичный,
заморожен, его использование ограничивает R3). Инвентаризация вне модуля `recipe` (`git grep`, 2026-10-26):

| Где | Что | Решение |
|---|---|---|
| `multiprocess_prototype/adapters/stores/recipe_store.py:59,87` (`glob`, `unlink` по `self._dir`) | список, удаление | через `RecipeManager.list()/delete()` (1.1c); параметр `recipe_dir` конструктора — FREEZE, для IO не используется |
| `multiprocess_prototype/frontend/app.py:501-524`, `frontend/app_services_factory.py:63` | composition root создаёт `RecipeManager` с каталогом | R3 allowlist: место сборки |
| `multiprocess_prototype/frontend/app.py:859` (`set_pipeline(f"recipes/{slug}.yaml")`) | указатель манифеста | R3 allowlist: формат указателя `app_module` (C-21(б)), вне полосы Д |
| `multiprocess_prototype/backend/launch.py:718-764`, `backend/assembly/assembler.py:81-186`, `backend/orchestrator_hooks.py:97-193`, `orchestrator.py:142`, `main.py:38`, `backend/state/bootstrap.py:155-243` | чтение на загрузке/запуске | R3 allowlist: читатели запуска; перенос — вне полосы Д |
| `multiprocess_framework/modules/app_module/{builder,orchestrator,interfaces}.py` | адрес рецепта для наблюдаемости | R3 allowlist: `app_module`, вне полосы Д |
| `multiprocess_framework/modules/process_manager_module/process/process_manager_process.py:824-964,2465` | адрес рецепта | R3 allowlist: запрещённая для правки область (`process_manager_module/**`) |
| `backend_ctl/probes/*` (≈ 25 файлов, `RECIPE = …/recipes/<x>.yaml`) | стенды читают рецепты | R3: `EXEMPT_DIRS` «стендовые зонды, чтение рецептов по пути»; два пишущих — пофайлово в R2 (§8.1) |

R3 (в страже 1.5): вне модуля `recipe` — строковый литерал/f-строка с сегментом `recipes/`, `Path / "recipes"`,
f-строка вида `f"{…}.yaml"` рядом с `slug`/`name`, атрибут `.recipes_dir` — только в allowlist R3 с причиной. Храповик:
статически «это путь рецепта» не доказать; новая строка видна на ревью.

### 9.5 (д) Раскладка — одной записью с топологией — Tasks 1.1e, 1.2, 1.8

Решение владельца 2026-10-26 (F2 ревью раунда 3): одна запись. Сегодня позиции пишутся вместе с топологией
(`layout_controller.py:434, 438-443`); две записи теряли бы `rev` первой при сбое второй. Писатель раскладки один —
приватный `RecipeManager._apply_layout(doc, positions, locked)`: хранит в `blueprint.metadata.{gui_positions,locked_nodes}`,
пустые коллекции, которых не было в файле, не создаёт (F10). Его зовут `patch_recipe(slug, after, *, expected_rev,
layout=(positions, locked_nodes))` (Pipeline-Save — топология и раскладка одной записью) и публичный
`save_layout(slug, positions, locked_nodes, *, expected_rev) -> str | None` (автосохранение при перетаскивании). Решение №20
(раскладка отдельным файлом папки) меняет только `_apply_layout` и запись внутри `RecipeManager`; вызывающие не меняются.

### 9.6 Что меняет переход на папку (для ADR-RCP-009, Task 1.3)

Внутри `RecipeManager`: разрешение slug → файл(ы); `read_recipe_rev` и `rev` (функция байтов всех файлов папки);
`patch_recipe` раскладывает дельту по файлам папки под одним `recipe_file_lock`; `_apply_layout` пишет sidecar раскладки. Вызывающие сохраняют: slug,
`after` в форме файла (для папки — объединённое тело), `expected_rev`, `RecipeConflict`, `save_layout`.

## 10. Политика канонической формы — ADR-RCP-010 «Каноническая форма рецепта: кто под кого подстраивается»

Владелец 2026-10-26: «продумать политику, кто под кого подстраивается, чтобы нормализатор подходил всем и было согласовано
со всеми». ADR пишет Task 1.3; реализуют 1.1f, 1.1g, 1.1c, 1.2, 1.9, 1.10, 1.4, 1.5. Уточняет §9.2 (там — «апдейт вызывающим»;
здесь перевод в каноническую форму — только через один адаптер).

1. **Владелец формы — модуль `recipe`.** Один нормализатор на приложение — `RecipeFormatHook.normalize` (`service.py:137`,
   Protocol уже есть); он диспетчеризует по форме (`InspectorRecipeFormatHook.normalize`, `recipe_format_hook.py:35-41`);
   конверт `meta`/`data` проходит насквозь; запись snapshot (`RecipeEngine.save`) нормализатор не использует (В-П3); приложение регистрирует его одной фабрикой, и `RecipeManager` (GUI), и `RecipeService`
   (хаб, `multiprocess_prototype/orchestrator.py:157-159`) получают экземпляры одного класса (процессы разные — один
   экземпляр невозможен). Реализация v3 сегодня — `InspectorRecipeFormatHook` (`multiprocess_prototype/backend/recipe_format_hook.py:31`).
   Других нормализаторов целых рецептов нет: правило R4 стража (§10.7).
2. **Контракт нормализатора** (общий набор проверок `recipe` + прогон на 22 рецептах и hypothesis): идемпотентен
   `N(N(x)) == N(x)` (проба `probes/probe_hook.py`: 23/23 — подтверждено ревьюером, сам не запускал); тотален на любом
   валидном файле (невалидный → типизированная `RecipeFormatError`, частичного результата нет); детерминирован (hash seed
   0..3); без правок дельта `N(file) → N(file)` пуста.
3. **Вызывающие подстраиваются под форму.** Чтение — `RecipeManager.read_canonical(slug) -> (doc, rev)`: `doc = N(файл)`.
   Вызывающий меняет только свою часть `doc` и отдаёт `patch_recipe(slug, after, expected_rev=rev)`. Сущности прототипа
   (`Recipe`, `Topology`, граф редактора) переводятся в/из канона ОДНОЙ парой адаптеров на границе
   (`multiprocess_prototype/adapters/recipe_canonical.py`, Task 1.1g): `recipe_from_canonical(doc) -> Recipe`,
   `recipe_to_canonical(recipe, base_doc) -> doc`, `topology_to_canonical(topology, base_doc) -> doc`. `*_to_canonical`
   переносит правку модели на `base_doc` через `apply_delta(base, M(base), M(edited), on_insert=minimize)` — поэтому
   `recipe_to_canonical(recipe_from_canonical(d), d) == d` для любого канонического `d` (свойство, тест на 22 рецептах).
   Камера и Устройства тоже читают `read_canonical` (Tasks 1.10, 1.9).
4. **Форма подстраивается под вызывающих только через фреймворк.** Нужно поле/форма, которой в каноне нет, — правка схемы
   или нормализатора в `recipe` + версия + шаг `@migration` (ADR-RCP-003) с ревью; обход в вызывающем — нарушение (R4).
5. **Форма на диске ≠ каноническая.** Файл хранит форму автора (комментарии, flow-стиль, опущенные умолчания); канон живёт
   только в памяти; мост — дельта-писатель. Программа умолчаний не пишет: вставляемое поддерево проходит `on_insert`
   (`minimize` адаптера — `model_dump(exclude_defaults=True)` по типу сущности пути: процесс, провод, дисплей). Это ОТМЕНЯЕТ
   прежнее решение плана «новые элементы — в полной форме модели». Правка пользователя НА значение-умолчание — изменённый
   лист, пишется явно (это выбор пользователя).
6. **Папка (ADR-RCP-006 v4).** Тот же контракт: `read_canonical` соберёт `doc` из `topology.yaml` + `params/*.yaml` +
   sidecar раскладки; вызывающие не замечают (§9.6).
7. **R4 стража (Task 1.5):** вне модуля `recipe` и `adapters/recipe_canonical.py` — вызовы `normalize_recipe_v3_raw`,
   `build_recipe_v3_raw`, `canonicalize_gui_positions` (кроме хука и миграций), `Recipe.from_dict(...)`/`.to_dict()` в
   цепочке записи — только в allowlist R4 с причиной.

### 10.1 Текущие нарушения политики и кто чинит

| Путь | Нарушение | Задача |
|---|---|---|
| Дисплеи → `RecipeStoreFromManager.write` | строит рецепт целиком из модели `Recipe` | 1.1c (через `read_canonical` + `recipe_to_canonical`) |
| Recipes/Pipeline-Save, closeEvent → `save.py` `build_recipe_v3_raw` | собирает рецепт целиком из raw + модели | 1.2 (`topology_to_canonical`); `build_recipe_v3_raw` — FREEZE, без живого вызова записи |
| Камера `save()` | мутирует весь raw `read_raw` | 1.10 (`read_canonical`) |
| Устройства `upsert/remove` | список из raw, запись секции | 1.9 (`read_canonical`) |
| Автосохранение раскладки | свой писатель `update_blueprint_metadata_preserving` | 1.1e/1.1c (`save_layout` → `_apply_layout`) |
| `service.save` (хаб) | `safe_dump` нормализованного тела целиком | 1.4 (хук — тот же класс, движок) |
| `RecipeEngine.save` (snapshot, другой `doc_type`) | конверт целиком | 1.4 (дельта по путям snapshot; нормализатор не используется — В-П3) |
| Миграции `recipes/migrations/*` | переписывают форму | разрешены политикой п. 4 (это и есть путь изменения формы); пишут через движок — 1.1b/1.5 |

### 10.2 Точки политики — закрыты (ревью раунда 3, 2026-10-26)

- В-П1 (GUI импортирует хук из `backend/`) — **можно, хук не переносится.** `.sentrux/rules.toml` запрещает только
  `backend/* → frontend/*`; `frontend/app.py:155,172,260,474,510,516` уже импортируют `backend`; хук без Qt
  (`recipe_format_hook.py:16`). Проверка в 1.1g — нет цикла импорта `recipes.save ↔ adapters.recipe_canonical`.
- В-П2 (`minimize` знает только умолчания pydantic) — **допустимо с условием:** файл читает backend-модель
  `SystemBlueprint`, минимизирует доменная. `extras` проверен (`process_manager_module/topology/blueprint.py:287`);
  `restart_policy`, `priority`, `enabled` — RED 1.1g `backend_load(minimize(x)) == backend_load(x)` по типам сущностей на
  22 рецептах; расхождение → `minimize` это поле не опускает.
- В-П3 (хук-тождество для snapshot) — **не нужно:** `RecipeEngine.save` нормализатор не использует (1.4 DESIGN 3),
  диспетчеризация по форме уже в `InspectorRecipeFormatHook.normalize`. §10 п. 1 переформулирован; RED 1.1g
  `test_v3_hook_is_identity_on_snapshot_envelope` (конверты — `recipe_engine.py:159-196`).

## 11. Журнал решений (перенесён из plan.md)

Раунды стадии 0: 1–2 — записи ниже; 3 — `review_stage0_r3.md` и запись «раунд 3»; 4 — запись «раунд 4» (в конце).

- **2026-10-26 (директива владельца):** без обходных путей — один движок, писатель — API фреймворка, корневая
  правка `Topology`.
- **2026-10-26:** дельта before/after, не «пропуск умолчаний» — шум сокращается без эвристики.
- **2026-10-26 (стадия 0):** списки — `difflib.SequenceMatcher(autojunk=False)`, поиндексно только внутри `replace`
  (контрпример префикс/суффикс — несмежные удаления, F17).
- **2026-10-26 (стадия 0):** `update_yaml_preserving`/`update_blueprint_metadata_preserving` — тонкие замороженные
  контракты над движком; миграции и `duplicate` идут через него; пустая дельта и сохранение EOL — для всех (ADR).
- **2026-10-26 (стадия 0):** Protocol `RecipeStore.save_raw` и `FakeRecipeStore` не меняются; `save.py` строит
  `before`/`after` и зовёт `apply_delta`. Шим `recipes/yaml_io.py` не расширяется (слой без вызывающего).
- **2026-10-26 (стадия 0):** непарсимая топология на Save → `RecipeValidationError`, без записи (не «запасной путь»).
- **2026-10-26:** EOL — свойство файла, сохраняется; смешанный → EOL первой строки. Новые элементы — в
  канонической форме модели; пустые `gui_positions`/`locked_nodes`, которых в файле не было, не создаются.
- **2026-10-26 (поправка факта В2):** явный Pipeline-Save сохраняет позиции узлов вне сцены
  (`layout_controller.py:434`); карту заменяет только автосохранение раскладки (`:251-262`) — нынешняя семантика,
  не шум писателя.
- **2026-10-26 (владелец, утверждение плана):** «Надо решать и делать, чтобы не обходили его» — Task 1.5: AST-страж по
  образцу `test_std_logger_guard.py` (не ruff `TID251` и не sentrux: те не выражают «вызов функции» / «YAML-дамп»),
  храповик всех YAML-писателей с причиной; `patch_yaml_preserving` не экспортируется из `recipe/__init__.py`, прежние
  экспорты заморожены (принцип 3); `canonicalize_gui_positions` маршрутизирован через движок; `recipe_engine`/`service`
  — переведены на движок в этом плане (Task 1.4; поправка координатора: «вне охраны» директива не допускает),
  исключение стража сужено до `yaml_io.py`.
- **2026-10-26 (владелец):** «да, все добавляй и закладывай на перспективу развития» — (а) ревизия `rev` у `RecipeManager`,
  `RecipeConflict` (Р3 закрыт); (б) `before` строит менеджер через инжектируемый `format_hook`, вызывающие в модельном
  пространстве переводят правку в форму файла `apply_delta` (одного модельного нормализатора на все пути нет — факт);
  (в) ruamel в `_ruamel_doc.py`, пин `<0.20`, тест формы токенов; (г) только slug, R3 в страже; (д) `save_layout` —
  единственный писатель раскладки. Задачи 1.6, 1.1e, 1.7, 1.8 (`design.md` §9).
- **2026-10-26 (стадия 0):** потеря комментария соседа при удалении не принимается — не укладывается → эскалация.
- **2026-10-26 (стадия 0, раунд 2):** `name/description` при `None` убирает `@model_serializer(mode="wrap")` на
  `Topology` (вложенный дамп `Recipe` идёт мимо `to_dict`); `RecipeValidationError` — из `errors(include_input=False)`;
  `patch_recipe` отвергает slug с путём; 1.1 разделена на движок / тонкие контракты + API / store / Topology; один
  файл тестов на задачу; заглушка `RecipeManager` — одна (`test_integration_assembly.py:118`).

- **2026-10-26 (владелец, политика формы):** ADR-RCP-010 (§10); отменено «новые элементы — в полной форме модели» (§10 п. 5).

- **2026-10-26 (стадия 0, раунд 3; решения владельца и лида, не пересматриваются):** (F1) межпроцессный лок сразу —
  `recipe/file_lock.py` `recipe_file_lock`, stdlib, `<slug>.yaml.lock`, таймаут → `RecipeLockTimeout`, файл не удаляется;
  им пользуются `RecipeService` и `RecipeManager` (новая Task 1.1h, teamlead: в FILES 1.1b не помещается — 8 файлов);
  (F2) одна запись — `patch_recipe(..., layout=)`, `_apply_layout`, `save_layout` зовёт его же; цепочка `rev1 → save_layout`
  убрана; (F3) база `rev` редактора — `TopologySession`; (F4) 1.1a — teamlead, пробы в `probes/`, F16 — первый шаг 1.1a;
  слияния 1.8 + 1.9, 1.1d + 1.7 (под номером 1.7); стадия 5 у 1.6 — express; порядок 1.1g → 1.7 → 1.1c; В-П1…В-П3 закрыты
  (§10.2); F5–F15 — по ревью (F7 подтверждён чтением `Recipe.from_dict` — F18; каталоги хаба и GUI — F19). 14 задач,
  33 запуска, ≈ 8,4M.
- **2026-10-26 (стадия 0, раунд 4; решения лида, не пересматриваются):** (G1) база `rev` захватывается и на старте — одно
  чтение байтов в `app.py`, `compute_rev` с них, slug из имени файла манифеста; Р6 остаётся только для активации;
  (G2) 1.9 возвращена отдельной задачей; из-за трёх локальных фейков `_DictRecipeStore` (`test_add_page.py`,
  `test_crud_actions.py`, `test_master_detail.py`), найденных грепом, Устройства (1.9, 6 файлов) и Камера (1.10, 2 файла)
  разделены; 1.8 — только редактор (5 файлов); (G3) шпион-счётчик записи в Pipeline-Save на B; (G4) строки §6 seed и CRLF
  получили владельца — 1.1c; (G5) тесты «вне лимита REDS» названы и получили INJECT; (G6) `list()` — `tuple`; (G7) TRAPS 1.7
  про pyright; (G8) повтор `os.replace` в `service._atomic_write` (общий для сервиса и `RecipeManager`); (G9) маркеры
  «заменено»; (G10) `cwd`/`PYTHONPATH` подпроцессов 1.1f; (G11) отказ на любом новом корневом ключе. 16 задач, 38 запусков,
  ≈ 9,5M.
