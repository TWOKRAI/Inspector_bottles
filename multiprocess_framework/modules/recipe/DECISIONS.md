# recipe — архитектурные решения (ADR)

---

## ADR-RCP-001: Консолидация управления рецептами в один framework-модуль

**Дата:** 2026-07-11
**Контекст:** Логика рецептов была расщеплена по слоям и модулям: generic-движок
`RecipeEngine` жил в `state_store_module/recipes/`, CRUD-обёртка `RecipeManager` —
в прототипе (`multiprocess_prototype/recipes/manager.py`), distinct-детект формата
v3 — статик-методом доменного wrapper'а (`backend/state/recipes/recipe_engine.py`),
нормализация v3-raw — в `recipes/format.py`. При этом `RecipeEngine` нёс доменную
константу `DEFAULT_CONFIG_PATHS = [cameras, renderer, robot, database]` прямо во
фреймворке — противоречие ADR-SS-003/SS-009 (фреймворк не знает доменных схем).
Аудит дублей 2026-07-10 (D5/D6) зафиксировал «version ×3» и предписал крышу.

**Решение:** Создать framework-модуль `multiprocess_framework/modules/recipe/`,
консолидирующий generic-механизмы:

- `recipe_engine.py::RecipeEngine` — snapshot/restore; доменные ветви инжектируются
  через `default_paths` (паттерн ADR-SS-011), доменные миграции — через
  `migration_fn`/`migration_check_fn` (ADR-SS-003). Доменной константы во фреймворке
  больше нет.
- `detect.py::is_v3_recipe` — единственная точка распознавания v3-blueprint vs
  config-snapshot (была staticmethod доменного wrapper'а).
- `format.py::normalize_recipe_v3_raw` — единая сборка v3-raw на запись.
- `manager.py::RecipeManager` — CRUD + `state.recipes.active`-sync.

Store типизируется через локальный `StoreProtocol` (`interfaces.py`) — модуль НЕ
импортирует `state_store_module`, чем исключается цикл recipe ↔ state_store.
Прототип и `state_store_module` держат тонкие шимы, сохраняя прежние пути импорта.

**Последствия:**
- Фреймворк перестал знать доменные ветви рецептов (ADR-SS-003 восстановлен для
  движка). Прикладной слой обязан передавать `default_paths` явно (breaking для
  save(paths=None) без инъекции → пустой снимок).
- v3-детект generic и сворачивает баг «порча blueprint пустым data» в базовый движок
  (был fix recipe-v3-engine-decouple; доменный wrapper больше не переопределяет load).
- Единая крыша под будущий реестр миграций (C2) и consolidation yaml_io (C3).

**Reversible:** yes — шимы делают перенос обратимым без миграции данных.

**Rejected:** generic `doc_migration_module` (отдельный модуль под миграции dict —
D5/D6) — отвергнут владельцем (2026-07-10): миграции живут в модуле `recipe`, а не в
абстрактном движке миграций; меньше сущностей, миграции остаются рядом с форматом.

**Связанные решения:** ADR-SS-003 (RecipeEngine миграции через callbacks),
ADR-SS-011 (инъекция доменных путей/предикатов), ADR-SS-009 (доменно-нейтральные
публичные классы).

---

## ADR-RCP-002: Инъекция comment-preserving writer в RecipeManager (yaml_updater)

**Дата:** 2026-07-11
**Статус:** Superseded ADR-RCP-005 (2026-07-12) — seam снят, comment-preserving writer стал generic-дефолтом модуля (`recipe.yaml_io.update_yaml_preserving`)
**Контекст:** `RecipeManager.duplicate()` сохраняет комментарии YAML через
`multiprocess_prototype.recipes.yaml_io.update_yaml_preserving` (ruamel round-trip).
Прямой перенос менеджера во фреймворк дал бы reverse-import `framework → prototype`
(нарушение слоёв). Consolidation `yaml_io` во фреймворк — отдельная задача (C3).

**Решение:** `RecipeManager.__init__` принимает `yaml_updater: Callable[[path, dict],
None] | None`. При инъекции duplicate() пишет через него (comment-preserving); без
инъекции — plain-PyYAML fallback (`_plain_yaml_update`, комментарии не сохраняются).
Прототипный шим инжектирует реальный `update_yaml_preserving` — поведение прототипа
не меняется, тесты прототипа зелёные без правок.

**Последствия:**
- Ноль reverse-import: framework-менеджер не знает про прикладной yaml_io.
- Временный дубль механизма записи (fallback vs prototype ruamel) — снимается в C3
  (перенос/дедуп yaml_io + переработка duplicate).

**Reversible:** yes.

**Rejected:** (а) перенести `yaml_io` во фреймворк сейчас — это скоуп C3, раздувает
задачу; (б) оставить `RecipeManager` в прототипе — не выполняет «manager в одном
модуле» и дробит крышу.

**Связанные решения:** ADR-RCP-001, ADR-SS-011 (паттерн инъекции).

---

## ADR-RCP-003: Реестр step-миграций + единый detect формата (C2, дубли D5/D6)

**Дата:** 2026-07-11
**Контекст:** Аудит дублей 2026-07-10 (D5/D6) зафиксировал две проблемы, оставшиеся
после ADR-RCP-001/002 (C1):

1. Определение формата рецепта «по форме» жило независимо в ≥3 местах:
   `detect.is_v3_recipe` (единая точка после C1), `unwrap_recipe`
   (`multiprocess_prototype/backend/launch.py`), `recipe_io.py::recipe_blueprint/
   launch_topology_source`, `RecipesPresenter.on_set_active`,
   `RecipeStoreFromManager._denormalize` — каждый со своей копией
   `"blueprint" in raw` / `raw.get("data", {}).get("blueprint")`.
2. Миграции рецептов существовали как отдельные функции без общего каталога:
   два «v1_to_v2» с одинаковым бытовым именем, но разной семантикой —
   `backend/state/recipes/migrations/v1_to_v2.py::migrate_recipe_data` (regions
   внутри `data.cameras`: processing_blocks → nodes) и
   `recipes/migrations/format_v1_to_v2.py::migrate_v1_to_v2` (файл рецепта целиком:
   slot-based topology → blueprint) — легко перепутать при рефакторинге.

**Решение:**

1. `detect.py` — добавлены `has_top_level_blueprint(raw)` и
   `nested_blueprint_data(raw)`: единая «форма» v3-blueprint (top-level и
   nested-в-data соответственно). `is_v3_recipe` переведён на
   `has_top_level_blueprint`. Все прикладные call-sites (unwrap_recipe,
   recipe_io.py, RecipesPresenter, RecipeStoreFromManager) переведены на эти
   же функции вместо собственных ad-hoc проверок — поведение бит-в-бит
   (`has_top_level_blueprint(x) == isinstance(x, dict) and "blueprint" in x`,
   та же логика, просто в одной точке).
2. `migrations.py` — новый файл: декоратор `@migration(doc_type, from_, to)`
   регистрирует dict→dict шаг в module-level реестре
   `{(doc_type, from_, to): fn}`; `run_chain(doc_type, data, from_version,
   to_version)` прогоняет цепочку шагов v → v+1 → ... → target, in-memory
   (READ-путь — раннер не читает и не пишет файлы, запись результата остаётся
   заботой вызывающего, как и раньше в `RecipeEngine.load()`).
   Namespace (`doc_type`) в ключе реестра различает одноимённые шаги: оба
   существующих `v1_to_v2` зарегистрированы под РАЗНЫМИ `doc_type`
   (`"recipe.config_snapshot"` и `"recipe.file_format"`) — декоратор
   прозрачен для прямого вызова, обе функции по-прежнему инжектируются как
   `migration_fn` (ADR-SS-003) без изменений в вызывающем коде.

**Последствия:**
- Инъекция callbacks (`migration_fn`/`migration_check_fn`, ADR-SS-003)
  остаётся рабочим механизмом RecipeEngine — реестр её не заменяет, а
  становится дефолтным источником шагов (домен регистрирует миграцию
  декоратором вместо ad-hoc функции без общего каталога). Проводка
  RecipeEngine на `run_chain` по умолчанию — вне скоупа C2 (потребовала бы
  публичного параметра `doc_type` в `RecipeEngineProtocol`, breaking public
  API); отложено, если понадобится, на следующую волну.
- `grep '"blueprint" in'` вне `modules/recipe/` — 0 совпадений (было 5).
- Property-тесты `run_chain` (идемпотентность `from_version == to_version` →
  no-op, сохранение неизвестных ключей сквозь цепочку шагов) написаны вручную
  широкой параметризацией — Hypothesis недоступен в `.venv` (пакеты не
  ставим, правило владельца).

**Reversible:** yes — оба механизма (инъекция и реестр) сосуществуют,
откат к прямой инъекции без реестра не требует правок вызывающего кода.

**Rejected:** генерировать единый `RecipeFormat`-enum, поглощающий ВСЕ 4
разных условия (`unwrap_recipe` вдобавок проверяет `"processes" not in raw`,
`is_v3_recipe` — ещё и `version >= 3`) — отвергнуто: разные call-sites решают
разные вопросы поверх одной и той же «формы» (`has_top_level_blueprint`), а не
единый вопрос «какой это формат» — общий enum усложнил бы, не устранив
дублирование локальной логики каждого call-site.

**Связанные решения:** ADR-RCP-001 (консолидация модуля), ADR-SS-003
(инъекция миграций callbacks), fix recipe-v3-engine-decouple (первопричина
детекта v3).

---

## ADR-RCP-004: Канонизация gui_positions — одна секция, doc_type без смены версии рецепта (Ф4.8, mini-GATE)

**Дата:** 2026-07-11
**Контекст:** Аудит дублей 2026-07-10 (`analysis.md`, п.5) зафиксировал два
«дубля записи» рецепта v3: `displays` (bindings в `blueprint.displays` vs
definitions в top-level `displays`) и `gui_positions` ×2. Разбор обоих на
живых рецептах (`phone_sketch`, `hikvision_letter_robot`):

1. **`gui_positions` — настоящий дубль содержимого.** `LayoutController.
   save_to_active_recipe` пишет ОДНИ И ТЕ ЖЕ позиции узлов в ДВА места:
   `blueprint.metadata.gui_positions` (канонический — его же читает
   `load_topology_from_config` и cold-start через `unwrap_recipe`, копирующий
   `raw["blueprint"]` целиком) и top-level `gui_positions` (комментарий в коде:
   «оставляем для обратной совместимости»). Но auto-persist при перетаскивании
   ноды (`_persist_layout_to_recipe`, debounce 400мс — доминирующий путь записи
   при обычной работе) пишет ТОЛЬКО canonical (`store.save_layout` →
   `update_blueprint_metadata_preserving`, точечно `blueprint.metadata.*`) —
   top-level копия обновляется только явным «Сохранить» (`save_to_active_recipe`,
   редкий путь). Отсюда неизбежный дрейф: на `phone_sketch.yaml` разошлись ВСЕ
   14/14 узлов, на `hikvision_letter_robot.yaml` — 2/20. Ни один живой read-путь
   (`unwrap_recipe`, `RecipesPresenter.on_save` через `TopologyRepository.load()`)
   top-level копию не читает — она write-only мёртвый груз.
2. **`displays` — НЕ дубль содержимого, коллизия имени ключа.**
   `blueprint.displays` (bindings: node_id→display_id) и top-level `displays`
   (definitions: id/width/height/format/…) хранят РАЗНЫЕ данные под одинаковым
   именем на двух уровнях вложенности. Слияние в «одну секцию» либо потеряло
   бы данные, либо потребовало бы переименования ключей и правки ~10 читающих
   мест (`unwrap_recipe`, `RecipesPresenter`, `RecipeStoreFromManager.
   _denormalize`, domain `Recipe`/`Topology`) — структурная миграция, не
   dict→dict канонизация одного save-пути. Вне скоупа 4.8, оставлено как
   заметка для отдельной задачи.

**Решение:**

- Новый шаг `multiprocess_prototype/recipes/migrations/
  canonicalize_gui_positions.py::canonicalize_gui_positions`, зарегистрирован
  `@migration("recipe.layout", from_=1, to=2)` (C2, та же инфраструктура, что
  `format_v1_to_v2.py`/`backend/state/recipes/migrations/v1_to_v2.py`).
  Правило: canonical (`blueprint.metadata.gui_positions`) побеждает БЕЗ
  слияния при дрейфе (это единственная копия на живом read-пути); если
  canonical пуст/отсутствует — top-level поднимается в canonical (данные не
  теряются на рецептах, где canonical ещё не заполнен); top-level всегда
  удаляется. Pure dict→dict, не читает/не пишет файлы; отдельно —
  `run_migration()` для будущего одобренного применения: пишет не файл целиком,
  а дельту через `patch_yaml_preserving` (EOL файла сохраняется, пустая дельта —
  без записи); поправка ADR-RCP-009 (C-30, Task 1.5), прежнее описание «ruamel
  round-trip file-writer» устарело.
- `from_=1, to=2` в реестре — ВНУТРЕННЯЯ бухгалтерия «шаг применён/не
  применён», НЕ поле `version:` самого файла рецепта (у `phone_sketch.yaml`
  `version: 1` при этом это v3-blueprint по `has_top_level_blueprint` —
  поле `version` рецепта означает нечто своё, авторское, и не трогается этим
  шагом). Канонизация формы, не смена версии рецепта.
- `displays`-коллизия НЕ канонизируется в рамках 4.8 (см. п.2 выше) —
  задокументирована как отдельный follow-up, а не проигнорирована молча.
- Файлы `phone_sketch.yaml`/`hikvision_letter_robot.yaml` НЕ переписаны в
  рамках 4.8 (mini-GATE владельца) — только байт-diff на одобрение:
  `plans/2026-07-06_constructor-master/f4.8-canonicalization-diff.md`.
  Применение к реальным файлам — отдельный шаг ПОСЛЕ одобрения.

**Последствия:**
- Эквивалентность подтверждена тестами: `unwrap_recipe(raw) ==
  unwrap_recipe(canonicalized)` для обоих живых рецептов (runtime-путь
  запуска бэкенда не меняется — он вообще не читает top-level gui_positions);
  `blueprint.metadata.gui_positions` бит-в-бит не меняется (живой read-путь
  редактора не затронут); идемпотентность (повторное применение — no-op).
- После одобрения и применения diff'а auto-persist перестаёт «протекать»
  устаревшими координатами через мёртвую top-level копию — единственный
  источник истины для позиций узлов.

**Reversible:** yes — top-level `gui_positions` не несёт уникальных данных на
живых рецептах (canonical либо совпадает, либо новее); шаг идемпотентен,
откат — вернуть `.yaml.bak`, создаваемый при будущем применении.

**Rejected:** канонизировать `displays` в рамках той же задачи — отвергнуто:
это не дубль содержимого, а разные данные под одинаковым именем; слияние
потеряло бы информацию либо потребовало бы многофайлового rename, что
непропорционально risk-профилю mini-GATE («миграции только in-memory на
READ; WRITE-канонизация отдельно (4.8) с бэкапом», риск-заметка плана).

**Связанные решения:** ADR-RCP-001 (консолидация модуля), ADR-RCP-003
(реестр step-миграций C2), ADR-SS-003 (инъекция миграций callbacks).

---

## ADR-RCP-005: Финальный carve модуля recipe (C3) + граница assembler/planner

**Статус:** принято (2026-07-12, C3 = 5.3, ветка `refactor/constructor-c3-recipe-carve`).

**Контекст.** C1 создал модуль `recipe` (engine+manager+detect+format), C2 добавил
реестр step-миграций (`migrations.py`, run_chain). Остались хвосты, вынесенные в
C3: (1) generic comment-preserving writer `yaml_io` жил в прототипе, а RecipeManager
инжектировал его через субкласс-шим (seam ADR-RCP-002); (2) run_chain был построен,
но не подключён как дефолтный путь миграции движка; (3) исходная задача 5.3
предписывала перенести `assembler/planner` «→ framework», по инерции — в модуль
`recipe`.

**Решение.**

1. **`yaml_io` → framework-модуль `recipe`** (`recipe/yaml_io.py`). Writer
   доменно-нейтрален (ruamel round-trip, знает лишь форму рецепта — top-level ключи и
   `blueprint.metadata`, не домен Inspector). Прототип `recipes/yaml_io.py` — тонкий
   шим-реэкспорт (путь импорта сохранён для recipe_store/launch/app/миграций).

2. **Снят seam RecipeManager.** Базовый RecipeManager дефолтит `yaml_updater` на
   `recipe.yaml_io.update_yaml_preserving` — субкласс-шим в прототипе больше не нужен,
   `recipes/manager.py` стал чистым реэкспортом. `yaml_updater=` остаётся точкой
   подмены (напр. plain-PyYAML без ruamel). Отменяет инъекцию из ADR-RCP-002.

3. **`duplicate()` — формат-стратегия через `detect`.** Ad-hoc проверка
   `isinstance(recipe_data.get("meta"), dict)` заменена на `is_v3_recipe`: v3-blueprint
   → top-level `name`, config-snapshot envelope → `meta.name`. Место записи имени —
   вопрос формата рецепта, решается единой detect-точкой (C2), не разъехавшейся
   проверкой ключа.

4. **run_chain — дефолтный источник миграции RecipeEngine.** `__init__` принимает
   `doc_type`; при отсутствии `migration_fn` и устаревшей версии `load()` мигрирует
   через `run_chain(doc_type, data, version, recipe_version)`. Явная инъекция
   `migration_fn` (ADR-SS-003) остаётся приоритетной — реестр её не заменяет, а
   становится дефолтом (ADR-RCP-003). `doc_type` добавлен в `RecipeEngineProtocol`.

5. **`assembler`/`planner` — НЕ в модуль `recipe`.** `BlueprintAssembler` валидирует
   `SystemBlueprint` в `{name: proc_dict}` и тянет `data_schema`, `process_module`
   (`merge_managers`), `process_manager_module.topology.blueprint`;
   `FullReplacePlanner` эмитит `process.*`-команды для `TopologyManager`. Это
   **топология**, не управление YAML-рецептами — идентичность модуля `recipe`
   (snapshot config-ветвей / detect / миграции / CRUD) им чужда. Затягивание их в
   `recipe` создало бы grab-bag и связало бы минимальный recipe (сейчас — только
   `StoreProtocol` + yaml) с половиной процесс-пайплайна. Их естественный дом —
   `process_manager_module/topology/`, рядом с `SystemBlueprint` (туда его перенёс
   C6(c), ADR-PMM-016). `normalize.py` — app-glue (`SystemConfig`), остаётся в
   прототипе.

   На момент C3 assembler/planner уже импортируют **только** framework-символы и
   живут в `multiprocess_prototype/backend/assembly/` за ленивым импортом — это НЕ
   reverse-import (прототип легитимно содержит framework-only helper), boot/switch
   работают. Поэтому **физический перенос отложен** как отдельная задача уровня
   `process_manager` (target = `topology/`, не `recipe`): перенос 2 файлов + тесты,
   шимы в `backend/assembly/`, **ноль новых межмодульных рёбер** (`process_manager`
   уже импортирует `process_module` и `data_schema`). Это следует ратифицировать в
   рамках process_manager, а не менять его публичную поверхность в «recipe carve».

**Последствия.**
- Модуль `recipe` остаётся минимальным (stdlib + PyYAML + ленивый ruamel; store —
  через Protocol). Прототип держит только шимы; 0 reverse-import (sentrux чисто).
- Acceptance C3 (boot=switch=duplicate; 0 reverse-import; снапшот 5.1) достигнут без
  переноса assembler/planner — они уже работают и границу не нарушают.

**Reversible:** yes — все переносы за шимами, откат = вернуть тело в прототип.

**Rejected:** `assembler/planner → recipe` (буквальная формулировка 5.3) —
отвергнуто: семантически это топология, перенос связал бы recipe с
data_schema/process_module/process_manager и превратил бы модуль в свалку; правильный
дом — `process_manager/topology`, что выходит за границу задачи «recipe carve» и
ратифицируется отдельно.

**Связанные решения:** ADR-RCP-001 (консолидация), ADR-RCP-002 (снятый seam writer),
ADR-RCP-003 (реестр миграций C2), ADR-PMM-016 (SystemBlueprint → topology, C6c),
ADR-SS-003 (инъекция миграций callbacks), ADR-SS-011 (инъекция доменных путей).

---

## ADR-RCP-006: Форма рецепта — топология отдельно от оверлеев параметров (белый список), папка на приложение

**Статус:** предложено (2026-08-18) — ждёт решения владельца Р-14 плана
[`framework-architecture-rework`](../../../plans/framework-architecture-rework/plan.md)
(раздел Ф2в). Кода нет. Исполнение — Task 2в.2 (sparse-запись) и 2в.3 (разрез + миграция,
в связке с Task 1.0 того же плана).

**Контекст.** Модуль уже различает два рода документа — `v3-blueprint` (топология:
`devices`/`blueprint.processes`/`displays`) и `config-snapshot` (значения, реплеятся в store) —
но в боевом рецепте они **склеены**: `multiprocess_prototype/recipes/hikvision_letter_robot.yaml`
— 576 строк, ~2/3 из них — `config:` плагинов внутри блока топологии (пороги HSV, ROI, веса ML,
калибровка). Следствия, наблюдаемые сегодня:

1. Настроить параметр = править файл топологии. Держать несколько вариантов настройки одной
   линии = держать несколько копий топологии, которые расходятся при первой правке проводки.
2. Плоский каталог из 18 файлов смешивает боевые рецепты, зонды (`g1_perf_probe`, `_s23_probe`)
   и демо (`modbus_demo`, `pult_demo`); GUI-список показывает всё подряд.
3. Нормализатор пишет дефолты на диск: у каждого процесса 8 полей-пустышек (`priority:`,
   `target_process:`, `description:`, `category:`, `metadata: {}`, `workers: []`, …) — шум
   при чтении и в diff.
4. В рантайме уже есть слои значений boot / L2 «рецепт» / L3 «сессия» (R6, закрыт 2026-07-29):
   switch раздаёт L2 «сырой секцией, долька резолвится у получателя тем же
   `resolve_recipe_section`, что и на boot». То есть механизм «именованный набор значений поверх
   топологии» существует — но у него нет **файла-носителя**, отличного от самой топологии.

**Решение.**

1. **Два рода документов — две роли, один каталог-папка на приложение.**

   ```
   recipes/
     hikvision_letter_robot/
       topology.yaml        ← devices, blueprint.processes (без config-значений), displays
       params/
         default.yaml       ← значения, которые сегодня лежат inline
         night_shift.yaml   ← оверлей: только отличия от default
     _probes/               ← вне GUI-списка (префикс `_` = служебное)
     _demos/
   ```
   Единица «рецепта» для GUI и для `RecipeManager` — **папка**; список строится из папок,
   папки с префиксом `_` скрыты (показываются по флагу).

2. **Оверлей параметров — белый список ключей топологии.** Оверлей адресует значение как
   `<process_name>.<plugin_name>.<key>` (и `devices.<id>.params.<key>`) и может менять
   **только значения ключей, которые топология уже объявила** (плагин присутствует, ключ есть в
   `default.yaml` или в схеме плагина). Запрещено: добавлять/убирать процессы и плагины, менять
   `plugin_class`, `process_class`, `chain_targets`, `restart_policy`, `devices`, `displays`.
   Неизвестный ключ, неизвестный плагин, попытка тронуть структурное поле → **адресный отказ**
   при загрузке (`RecipeError` с путём ключа), не молчаливое принятие и не молчаливый пропуск.
   Это делает свойство «при настройке система не меняется» проверяемым инъекцией, а не
   договорённостью. Тот же принцип, что «фасад — белый список» у конфига.

3. **Оверлей едет в L2 той же дорогой, что рецепт при switch — не новой.** Ответ на вопрос (а)
   Task 2в.1: применение оверлея = сборка `topology + params/<name>` в **тот же плоский
   v3-документ**, который сегодня получают `BlueprintAssembler` на boot и `topology.apply` на
   switch. Смена оверлея без смены топологии = тот же `topology.apply` с тем же файлом-адресом и
   новым содержимым L2 (`{}`/`None`-семантика R6 сохраняется). Ни ассемблер, ни получатели
   (`resolve_recipe_section`), ни `state.recipes.active` новых дверей не получают; в
   `state.recipes` добавляется одно поле — `active_params: <name>`. Пятая дверь конфига не
   заводится (правило Б.1 `observability-dx`).

4. **Ответ на вопрос (б) — резидуалы R6.** R6 закрыт 2026-07-29 (переживший процесс получает
   адрес и содержимое L2). Открытые резидуалы R6-C…R6-H наследуются оверлеями **как есть** —
   они про доставку L2, а не про её источник; чинить их «заодно» здесь запрещено (второй
   владелец у одного дефекта). Приёмка 2в.3 обязана включать пару «переживший protected-процесс +
   пересозданный» на смене оверлея — ту же, которой судили R6.

5. **Sparse-запись (2в.2, независимо от разреза).** Writer не пишет поля, равные дефолту схемы;
   загрузка файла без них даёт ту же модель. Comment-preserving (`yaml_io`, ADR-RCP-002/005)
   сохраняется. Это −~30 % строк без нового формата и может ехать раньше разреза.

6. **Формат и миграция.** Разрез — новая версия документа `recipe.v3` → `recipe.v4`
   (`doc_type`-шаг в реестре `@migration`, ADR-RCP-003): старый плоский файл разбирается на
   `topology.yaml` + `params/default.yaml` детерминированно (config → default, структура →
   topology). Файл без миграции — отказ с адресом (`run_chain` без шага → `RuntimeError`, как
   сегодня). Делается **одним заходом с Task 1.0** плана rework (миграция персистентных
   строковых путей): оба меняют один и тот же движок и один и тот же набор рецептов.

7. **Что сознательно НЕ делаем.** Дробить топологию на `devices.yaml`/`processes.yaml`/
   `displays.yaml`: выигрыш в чтении даёт уже разрез «топология / параметры»; три файла на один
   рецепт — три места, где расходится версия, при движке миграций dict→dict над целым документом,
   comment-preserving writer и `duplicate()` по одному документу. Также не заводим наследование
   оверлеев (`extends:`): один уровень «default + один оверлей», иначе вопрос «откуда это
   значение» снова требует чтения трёх файлов. Раскладку (`gui_positions`/`locked_nodes`)
   и прочую косметику тоже не кладём в файл топологии: она идёт отдельным файлом папки
   рецепта по решению владельца №20 (2026-10-26). В C-30 это не делается; писатель раскладки
   сегодня — `RecipeManager.save_layout` (ADR-RCP-009).

**Последствия.**
- Читаемость: топология ~200 строк, оверлей — десятки; варианты настройки перестают плодить
  копии проводки.
- Свойство «параметры не меняют систему» становится тестируемым: инъекция «оверлей добавляет
  плагин / меняет `plugin_class`» → отказ с адресом, топология побайтно не изменена.
- Ломается: плоский `recipes/*.yaml` как единица; `RecipeManager` (list/duplicate/delete по
  папке), вкладка Recipes (список папок + выбор оверлея), `recipe_io`/`launch` (сборка перед
  ассемблером), рецепты в БД (мигрируются шагом v3→v4). Плагины и ассемблер — не трогаются.
- Связка с `line-sim`: его «`sim:` — опциональная секция в том же YAML» — тот же класс
  «база + вариант»; рождается на форме v4, а не мигрирует после.

**Reversible:** yes до 2в.3 (ADR + sparse-запись обратимы правкой writer); после миграции v3→v4
— `migration-needed` (обратный шаг v4→v3 детерминирован: склейка — пишется вместе с прямым).

**Rejected:**
- «Папка на проект, а не на приложение» — не отвечает на вопрос «где параметры этой линии».
- «Оверлей может добавлять плагины» — тогда это не параметры, а вторая топология; свойство
  «система не меняется» исчезает.
- «Отдельный слой L2b для оверлеев» — пятая дверь; W-1 QUEUE (один лист — два владельца).

---

## ADR-RCP-007: Владелец рецепта — бэкенд; `recipe.*` на хабе, оптимистичная ревизия `rev`

**Статус:** принято (2026-09-24, вердикт cto; Task 1b.1 плана
[`gui-service`](../../../plans/2026-09-22_gui-service/plan.md), этап INTERFACE — код-скелет
`service.py`, реализация — GREEN того же Task).

**Контекст.** Рецепты сегодня пишет GUI: `RecipeManager` создаётся только во фронтенде
(`frontend/app.py`), «последний активный» (`app.yaml: pipeline:`) пишет GUI после успешного
`topology.apply`, запись файла рецепта не атомарна (`open(path, "w")` в `yaml_io`). Цель плана —
Пульт и встроенный GUI как равноправные клиенты бэкенда; падение клиента не должно трогать
бэкенд. Значит, чтение/запись/активация рецепта должны быть командами бэкенда, а два редактора
не должны затирать друг друга молча. Разведка — `docs/reviews/2026-09-24_task-1b.1-design.md`.

**Решение.**

1. **Сервис во фреймворке, формат — хук приложения.** `modules/recipe/service.py`
   (`RecipeService`): обработчики `recipe.list / get / save / validate / activate / delete`,
   Qt-free, `dict` на границе, без импорта `PySide6` / `multiprocess_prototype` / `app_module`.
   Формат рецепта — Protocol `RecipeFormatHook` (`normalize`, `validate → [{path, message}]`,
   `to_topology`); применение топологии, запись манифеста и чтение активного — инжектируемые
   вызываемые. Второго менеджера рецептов не появляется.
2. **Хостинг — хаб (ProcessManager).** Проводка — через прототипный `ProcessManagerProcessApp`
   (`orchestrator_hooks`). Хаб уже владеет фактом «активный рецепт» (`_retarget_recipe_address`),
   и только на хабе `recipe.activate` может вызвать `topology.apply` в том же процессе и вернуть
   результат синхронно.
3. **`recipe.activate` синхронный:** normalize → validate → `topology.apply` с
   `topology_dict = hook.to_topology(body)` и **явным абсолютным `recipe_path`** → при success
   `ManifestStore.set_pipeline` → ответ `{success, name, apply: <ответ topology.apply>}`. Персист
   после success — порядок GUI сегодня. Без `recipe_path` хаб ретаргетит адрес L2 по манифесту,
   то есть на старый рецепт — поэтому путь обязателен. Второго пути применения нет.
4. **Оптимистичная ревизия.** `recipe.get` отдаёт `rev`; `recipe.save {name, base_rev, body}`
   сравнивает `base_rev` с ревизией **текущих байтов на диске** под локом на имя; несовпадение →
   `conflict` с `current_rev`, файл не тронут. `body` — полный документ (замена, не merge).
   Запись атомарна: tmp в том же каталоге + `os.replace`.
5. **`rev` — непрозрачная строка** (сегодня `sha256` байтов файла); клиент сравнивает её только
   на равенство и не разбирает.
6. **Любой писатель мимо `recipe.save` инвалидирует `rev` редактора** (сегодня `save_layout`
   GUI — автосохранение позиций при перетаскивании, `recipe_store.py`; а также ручная правка
   файла) — это желаемое поведение: редактор получает `conflict`, а не тихую перезапись.
   Автосохранение позиций решается в Task 1b.3.
7. **Манифест — второй писатель до 1b.3.** `recipe.activate` пишет `app.yaml` тем же
   `ManifestStore` (flock + `os.replace`), GUI-писатель `_persist_active_recipe` остаётся до 1b.3
   (гонки нет, есть дубль записи).

**Последствия.**
- Контракт команд и форма ошибок (`not_found | conflict | invalid | bad_request | io_error |
  apply_failed | active`) зафиксированы докстрингом `service.py`; тесты — независимый tester.
- Вызов `recipe.*` стоит в одной очереди с `topology.apply` на приёмном потоке хаба: пока идёт
  switch (десятки секунд), `recipe.list/get` ждут.
- Команды хаба через сокет `backend_ctl` идут мимо receive-мидлвари — судья прав (G1b) нужен
  Task 1b.4 для всех команд хаба, включая `recipe.*`.
- Единица рецепта — один файл; переход на папку (ADR-RCP-006) поменяет контракт `get/save`.
- Upsert устройств перед apply (GUI, `presenter.py`) сервис не делает — остаётся за GUI до 1b.3.

**Reversible:** yes — новые команды и новый файл; GUI-путь не снят.

**Rejected:**
- Отдельный protected-процесс `recipes` в `base.yaml` — +375 строк golden каждому рецепту
  (решение 08-23), а `activate` вне хаба стал бы асинхронным (`RouterReentrantRequestError`,
  отложенного ответа нет).
- Плагин в процессе `devices` — асинхронный `activate` и второй владелец «активного рецепта»,
  смешение доменов на одном приёмном потоке.
- Блокировка рецепта на время редактирования — повисает при падении Пульта, а падение клиента
  не должно трогать бэкенд (решение 2026-09-23).
- `rev` как счётчик в памяти — не видит ручной правки файла и писателей мимо сервиса.

**Уточнено:** ADR-APP-008 (2026-10-25) — активный рецепт пишется в `<stem>.state.yaml`, `app.yaml` — умолчание.

## ADR-RCP-008: `update_yaml_preserving` пишет атомарно (2026-09-27)

**Решение:** запись с комментариями (`yaml_io.update_yaml_preserving`, `update_blueprint_metadata_preserving`)
идёт через `service._atomic_write` — tmp в том же каталоге + fsync + `os.replace`; права файла возвращаются
`chmod`. Прежние свойства `open("w")` сохранены: запись идёт сквозь симлинк (`realpath`), файл 0444 даёт
`PermissionError`.
**Почему:** прежняя запись поверх файла при сбое посреди оставляла обрезанный рецепт; второй потребитель —
пресет слоёв `line_sim` (`scene_source` `preset.commit`, редактор слоёв Task 1.2a) — правит файл с живой ленты.
**Цена (известные пределы):** жёсткая ссылка рвётся; каталог только для чтения (0555) запись теперь не
пропускает — tmp создаётся рядом; между `os.replace` и `chmod` файл короткое время 0600. На 2026-09-27 таких
файлов 0 (`find`, ревью 1.2a it.2).

## ADR-RCP-009: Один дельта-движок записи рецепта (2026-10-26)

**Статус:** принято (2026-10-26, директива и решения владельца при утверждении плана
[`recipe-save-noise`](../../../plans/2026-10-26_recipe-save-noise/plan.md), дефект C-30). Код — задачи плана
(Tasks 1.1a–1.14, ветка `fix/recipe-save-noise`). Правила дельты, пробы и инвентаризации — в
[`design.md`](../../../plans/2026-10-26_recipe-save-noise/design.md) §2, §8–9; здесь они не дублируются.
Связанные: ADR-RCP-002, -005, -006, -007, -008, -010.

**Контекст.** Сохранение рецепта из GUI (Дисплеи, Устройства, Камера, Recipes/Pipeline-Save, автосохранение
раскладки) и бэкенд-писатели (`recipe.save` хаба, снимок `RecipeEngine`) переписывали файл целиком: терялись
комментарии и flow-стиль, в файл попадали умолчания модели (`extras: {}`, `restart_policy: {}`, `gui_positions: {}`).
Регресс зафиксирован коммитом `efc2612c3` (воспроизведён побайтно путём «Дисплеи», `probes/c30_investigation.md`
плана). Причины две: писатель заменял поддерево целиком (`data[key] = value`), а вызывающие отдавали полный дамп
модели. Директива владельца 2026-10-26: «Главное чтоб костылей не было, а делалось к лучшей и правильной
архитектуре!!!! Которая позволяет масштабировать и улучшать систему».

### Альтернативы

- **A. Пропускать умолчания в каждом вызывающем.** Отвергнуто: это эвристика про умолчания в нескольких местах;
  дельта `before → after` убирает шум без неё, потому что шум модели есть с обеих сторон (design.md §3, §11).
- **B. Один движок по дельте `before → after`.** Выбрано.
- **C. Охрана одного писателя через ruff `TID251` или sentrux.** Отвергнуто: `.sentrux/rules.toml` выражает границы
  модулей, а не вызовы функций; ruff в проекте включает только `E`, `F`, а `TID251` не ловит `yaml.safe_dump` в
  рецепт и требует правки общей конфигурации ради одного правила (design.md §8.1).
- **D. 3-way merge при конфликте вместо отказа.** Отложено, не отвергнуто: сейчас конфликт — отказ и сообщение
  (`docs/claude/OPEN_QUESTIONS.md`).

### Решение

Один движок во framework (`recipe/yaml_io.py`) и один публичный путь записи рецепта для прототипа.

- `patch_yaml_preserving(path, before, after) -> bool` — дельта применяется к ruamel-документу файла; `True` —
  записан, `False` — дельта пуста, файл не открывался на запись (байты и `st_mtime_ns` прежние). Внутренний путь
  модуля; из `recipe/__init__.py` не экспортируется.
- `apply_delta(target, before, after)` — та же дельта на plain-dict, без IO; экспортируется.
- `YamlPatchConflict(ValueError)` — путь дельты не ложится на цель; бросается до записи. `YamlWriteRefused(ValueError)` —
  страховка записи отказала. В обоих случаях байты файла целы.
- `RecipeManager.patch_recipe(slug, after, *, expected_rev, layout=None) -> str` — публичный путь записи рецепта.
  Писатель инжектируется параметром `yaml_patcher` (симметрично `yaml_updater`), по умолчанию `patch_yaml_preserving`.
- `update_yaml_preserving` и `update_blueprint_metadata_preserving` — тонкие замороженные контракты над тем же
  движком: `before` — текущее поддерево файла, `after` — оно же с заменёнными значениями (принцип 3: публичный путь
  заморожен, не удаляется).
- Корневая правка: `Topology.name/description` типизированы (раньше прятались в `metadata` из-за `extra="forbid"`;
  читателей в проде не было, design.md F4).

### Изменения поведения для всех вызывающих движка

- Пустая дельта — файл не записывается (байты и `st_mtime_ns` прежние).
- EOL файла сохраняется: файл читается текстом, EOL берётся из первой строки; смешанный — приводится к EOL первой
  строки, файл без терминатора — `\n`. Раньше запись переводила CRLF-файл в LF.
- Миграции каталога и `duplicate` идут через движок; `run_migration()` канонизации `gui_positions` пишет дельту.
- Создание нового файла (`recipe.save` и `RecipeEngine.save`) — ruamel-дамп: порядок ключей как в словаре
  (у снимка `meta` теперь перед `data`, прежний `yaml.dump` сортировал ключи по алфавиту), кавычки и стиль могут
  отличаться от прежних.

### Изменения поведения `recipe.save` хаба (Task 1.4)

- Комментарии, порядок и стиль YAML сохраняются: пишется дельта `normalize(текущий файл) → normalize(body)`.
  Post: `normalize(файла после записи) == normalize(body)`, кроме ключей, которые `normalize` переносит (legacy top-level
  `gui_positions`: остаются в файле и возвращаются при чтении — `camera_robot_calibration`, `dataset_circle_capture`);
  умолчания, которых нет в файле, не создаются.
- Текущий файл не разбирается, пуст или корень не mapping → `invalid`, файл цел (раньше перезаписывался).
- Рецепт v1 (top-level `topology:`) → `bad_request` «рецепт v1: сначала миграция», файл цел. Критерий — литерал
  `"topology"` в универсальном `service.py`, он дублирует `InspectorRecipeFormatHook.normalize` (OPEN_QUESTIONS).
- Legacy top-level `gui_positions` и другие ключи, которые `normalize` переносит, при `save` остаются в файле
  (раньше стирались); чистка содержимого рецептов — отдельный коммит полосы C.
- Сверка `base_rev` идёт раньше записи: устаревший `base_rev` вместе с несериализуемым телом теперь `conflict`,
  не `bad_request`.
- Тело, которое движок не записывает → `bad_request «body не записывается: <ИмяКласса>»`; текст исключения в ответ
  не кладётся (`RepresenterError` несёт repr значения), файл цел. Наблюдено: `1j`, `object()`, `Decimal`, `Path`,
  `lambda` → `RepresenterError`; `nan` и ключи-кортежи → `YamlWriteRefused`; тело с `bytes` пишется как `!!binary`
  (`success`). `OSError` не ловится и идёт в `io_error` через `_guarded`.
- Файл, который читает PyYAML, но не читает ruamel (например, дубль ключа `a: 1` / `a: 2`) → `bad_request «body не
  записывается: DuplicateKeyError»`, файл цел. Сообщение винит body, хотя виноват файл; раньше такой файл
  перезаписывался. Рецептов с дублем в репозитории нет (22 из 22 проходят `save`). Решение по тексту — OPEN_QUESTIONS.

### Изменения поведения `RecipeEngine` (Task 1.4)

- `save` по существующему файлу пишет дельту только по путям `snapshot_paths`. Ветви `data` вне путей остаются как в
  файле; путь, которого нет в сторе, удаляется вместе с предками, ставшими пустыми (корень `data` остаётся).
  `meta` не переписывается (`created_at`, `name`, `description` как в файле), кроме `meta.version`.
- `meta.version` ставится в текущую, только если метка не число (включая `bool`) или меньше текущей; более новую
  метку `save` не понижает. Это пересмотр решения лида R1-2 («`!=`») по ревью стадии 5, п. 8.
- Ключи путей — строки. Ручной файл с int-ключом `0:` (воспроизведено запуском): для листового пути
  (`paths=["cameras.0.config.fps"]`) int-ключ остаётся со старым значением и комментарием, а рядом дописывается
  второй ключ `'0'` с новым значением (дубль); для пути к родителю (`paths=["cameras"]`) ключ переписывается в
  строку `'0'`, комментарий при нём теряется. Файлы, записанные самим движком, ключи кавычат, поэтому на практике
  это недостижимо (строка в `OPEN_QUESTIONS`).
- Непарсимый файл → `yaml.YAMLError`; корень не mapping, нет `meta` или `meta` не mapping → `ValueError` без
  содержимого файла; в обоих случаях файл цел. `save` без изменений стора файл не трогает.
- Перезапись после миграции в `load` пишет дельту: `before = copy.deepcopy(recipe)` берётся до миграции (при `before`,
  равном `recipe` по ссылке, дельта пуста и `meta.version` не обновился бы). Комментарии сохраняются, `.yaml.bak`
  создаётся как раньше.

### Цена

- **Р3 (устаревший `after`).** Дельта строится от файла на момент записи, `after` — из снимка, прочитанного раньше:
  устаревший `after` откатывает все поля, где снимок не равен файлу, не только поля вызывающего (ручная правка
  `port` 5021 → 5022 между чтением и записью была бы откачена). Закрыто ревизией (раздел ниже); 3-way merge вместо
  отказа не делаем (OPEN_QUESTIONS).
- **Р4 (YAML 1.1 и 1.2).** Рецепт читает PyYAML (`yes` → `True`), документ ведёт ruamel (`yes` → строка). Неизменённый
  лист не пишется, поэтому расхождение видно только на изменённом листе. Страховка `_verify_dump` сверяет
  PyYAML-чтение дампа с ожидаемым в пространстве PyYAML; изменённый лист `On`/`yes`/`1e-05` даёт отказ
  `YamlWriteRefused`, не молчаливую порчу. Остаётся слепое пятно: дельта, неверная в обоих пространствах сразу.
- **Новые элементы** вставляются в канонической форме. Формулировка «в полной форме модели» отменена ADR-RCP-010
  п. 5: вставляемое поддерево проходит `on_insert` (`minimize`), умолчания программа не пишет.
- **Перенос комментария соседа при удалении** (ключ, элемент списка) опирается на внутренности ruamel — риск
  изолирован модулем `_ruamel_doc.py` и пином версии (ниже).
- **Цена охраны:** новый законный писатель YAML добавляет одну строку в allowlist стража.

### Ревизия и конфликт (Tasks 1.1b, 1.1e, 1.1h)

- `compute_rev(raw: bytes) -> str` — одна функция модуля (`recipe/format.py`); `service.compute_rev` остаётся
  публичным путём (импорт оттуда). `RecipeManager.read_recipe_rev(slug)` отдаёт тело и `rev` одного чтения байтов.
- `patch_recipe` и `save_layout` принимают `expected_rev`. Не совпал с файлом → `RecipeConflict(slug, expected_rev,
  current_rev)`, файл не тронут. `expected_rev=None` допустим только для нового файла; для существующего —
  `ValueError` (запись без базы запрещена). Пустая дельта возвращает прежний `rev`.
- Сверка и запись идут под межпроцессным локом `recipe/file_lock.py::recipe_file_lock(path, *, timeout=5.0)`.
  Почему межпроцессным: `service._lock` — `threading.Lock` экземпляра, между хабом и GUI он ничего не значит.
  Lock-файл `<slug>.yaml.lock` лежит рядом с рецептом (игнорируется git). Windows — `msvcrt.locking` байта 0, POSIX —
  `fcntl.flock(LOCK_EX | LOCK_NB)`; попытки неблокирующие до дедлайна, затем `RecipeLockTimeout(TimeoutError)`,
  бесконечного ожидания нет. Файл лока не удаляется: ОС снимает лок при смерти держателя, а `unlink` дал бы гонку по
  inode. Лок нереентерабелен — его берёт внешний публичный метод один раз.
- Пользуются `RecipeService.save/delete` и `RecipeManager.patch_recipe/save_layout`. `RecipeEngine.save`
  (снимок без `rev`) лок не берёт — вне C-30. Закрывает Р3.

### «`before` строит менеджер» (design.md §9.2, уточнено ADR-RCP-010)

`RecipeManager(format_hook=...)`: `before = N(текущий файл)`, `after' = N(after)`, движок применяет дельту
`before → after'`. `N` — `format_hook.normalize` (Protocol `RecipeFormatHook`, тот же, что у `RecipeService`); без
хука — тождество. Если `N(файл)` вводит корневой ключ, которого в файле нет (устаревшая форма), запись отказывает
`RecipeFormatError` «сначала миграция». Вызывающие читают `read_canonical(slug) -> (doc, rev)`; контракт
нормализатора и политика формы — ADR-RCP-010.

### «ruamel изолирован» (Tasks 1.1a, 1.6)

Всё, что знает о внутренностях ruamel (`CommentedMap/Seq`, `ca.items`, токены комментариев, `_make_yaml`, перенос
хвостового комментария), живёт в приватном `recipe/_ruamel_doc.py`; `yaml_io.py` вызывает только его функции.
Зависимость закреплена `ruamel.yaml>=0.19.1,<0.20` (`pyproject.toml`) — минорная линия, на которой проверена форма
токенов. `tests/test_ruamel_contract.py` краснеет на версии вне `0.19.x` и на неожиданной форме токена.

### «Только slug» (R3)

Вызывающие адресуют рецепт по slug; путь к файлу видит только `RecipeManager`. `patch_recipe` отвергает slug с
разделителем пути или `..` (`ValueError` до обращения к файлу). `recipes_dir` в Protocol и параметр `recipe_dir`
store прототипа публичны и заморожены; их использование ограничивает правило R3 стража.

### Переход на папку (ADR-RCP-006 v4) и раскладка отдельным файлом (решение владельца №20)

Раскладка пишется одной записью с топологией: `patch_recipe(..., layout=(positions, locked_nodes))` и
`save_layout(...)` оба идут через приватный `RecipeManager._apply_layout`, который хранит данные в
`blueprint.metadata.{gui_positions,locked_nodes}`. Две записи теряли бы `rev` первой при сбое второй. Пустые
коллекции, которых не было в файле, не создаются.

Переход на папку меняет только внутренности `RecipeManager`: разрешение slug → файл(ы); `read_recipe_rev` и `rev`
(функция байтов всех файлов папки); `patch_recipe` раскладывает дельту по файлам папки под одним `recipe_file_lock`;
`_apply_layout` пишет отдельный файл раскладки. Вызывающие сохраняют: slug, `after` в форме файла (для папки —
объединённое тело), `expected_rev`, `RecipeConflict`, `save_layout`. Ни папку, ни отдельный файл
раскладки C-30 не делает.

### Охрана: страж одного писателя (Task 1.5, design.md §8)

Решение владельца 2026-10-26 при утверждении плана: «Надо решать и делать, чтобы не обходили его».

- Страж `recipe/tests/test_single_writer_guard.py` — AST-тест по образцу `logger_module/tests/test_std_logger_guard.py`.
  Сканирует весь Python репозитория (`git ls-files` и неотслеживаемые неигнорируемые), кроме тестов и
  `.claude/worktrees/`. Сопоставление «модуль + имя», относительные импорты разрешаются через `node.level`. Allowlist —
  «файл → причина»; мёртвая строка allowlist'а краснит так же, как нарушение. `test_no_unscannable_files`: файл не в
  UTF-8 или с `SyntaxError` не пропускается молча. Обход один на сессию (≈1,5 с).
- **R1 — писатели движка.** Импорт `patch_yaml_preserving`, `update_yaml_preserving`,
  `update_blueprint_metadata_preserving`, `_dump_atomic`, `_make_yaml` из `recipe[.yaml_io]` или шима
  `multiprocess_prototype.recipes.yaml_io` разрешён только в самом `yaml_io.py` и в allowlist R1. Модуль `recipe` для
  R1 не исключён: `manager.py`, `service.py`, `recipe_engine.py` — строки allowlist.
- **R2 — любой YAML-дамп** (`yaml.dump`/`safe_dump`/`dump_all`, в том числе через алиасы и `from yaml import …`;
  `.dump(` в файле с ruamel): только `yaml_io.py` и allowlist R2 — храповик «каждый файл, пишущий YAML, объявлен с
  причиной».
- **R3 — только slug.** Вне модуля `recipe`: строка с `recipes/`, `/ "recipes"`, f-строка `{slug|name}.yaml`, атрибут
  `.recipes_dir` — только в allowlist R3.
- **R4 — нормализация целого рецепта** (`normalize_recipe_v3_raw`, `build_recipe_v3_raw`, `canonicalize_gui_positions`,
  `Recipe.from_dict`) вне модуля `recipe` и `adapters/recipe_canonical.py` — только в allowlist R4.
- Публичная поверхность: `recipe/__init__.py` экспортирует `apply_delta` и `YamlPatchConflict`;
  `patch_yaml_preserving` не экспортируется — путь записи рецепта для прототипа `RecipeManager.patch_recipe`.
  Прежние экспорты `update_*_preserving` заморожены, их использование ограничивает R1.

#### Allowlist-ы по факту Task 1.5 (замер 2026-11-06)

Источник истины — словари `ALLOWLIST_R1…R4`, `EXEMPT_DIRS`, `EXEMPT_DIRS_R3` в тесте стража; таблицы `design.md`
§8.2 и §9.4 были прогнозом и с замером расходятся (R2 там без `service.py`, `recipe_engine.py`,
`canonicalize_gui_positions.py`, плюс шесть замеренных файлов).

- **R1 — 9 строк:** `recipe/__init__.py` (публичный экспорт, FREEZE); `recipe/manager.py` (`patch_recipe`,
  `duplicate`); `recipe/service.py` (`recipe.save` хаба); `recipe/recipe_engine.py` (снимок и перезапись после
  миграции); `recipes/yaml_io.py` прототипа (шим-реэкспорт, FREEZE); `recipes/migrations/{drop_display_name,
  displays_to_recipe,canonicalize_gui_positions}.py` (офлайн-миграции каталога по пути: нет slug и менеджера);
  `Plugins/sim/scene_source/plugin.py` (пресет слоёв `line_sim`, не рецепт).
- **R2 — 35 строк**, причина у каждой своя. Группы: не рецепт (калибровка, пользователи, реестры, состояние GUI и
  приложения, prefs, темы, снимки конфигурации, YAML-строки в памяти); FREEZE без живого вызывающего
  (`layout_controller.py` `save_topology_to_file`, `widgets/topology/presenter.py` `save_to_file`); стендовые
  зонды и утилиты, пишущие временный рецепт прогона (четыре файла `backend_ctl/probes/`, `scripts/capacity_bench`,
  `scripts/stand_gate`); `recipe/hook_contract.py:130` — единственный дамп в модуле `recipe` вне движка (временный
  `recipe.yaml` проверки контракта хука в tempdir, не рецепт).
- **R3 — 6 строк:** `backend/launch.py`, `frontend/app.py`, `frontend/app_services_factory.py`, `main.py` (места
  сборки и запуска, адресующие каталог и манифест); `frontend_module/core/prefs_store.py` (ключ prefs
  `recipes/view_mode`, не путь) и `frontend/managers/theme_presets_manager.py` (`<name>.yaml` пресета темы) — ложные
  совпадения по форме.
- **R4 — 2 строки:** `backend/recipe_format_hook.py` (единственный нормализатор целого рецепта, ADR-RCP-010 п. 1);
  `recipes/save.py` (`build_recipe_v3_raw`, FREEZE без живого вызова записи).
- **EXEMPT_DIRS** (R1–R4): `docs`, `plans` — архивные стенды и пробы, не код приложения. **EXEMPT_DIRS_R3:**
  `backend_ctl/probes`, `scripts` — читают рецепты по пути; R1 и R2 их по-прежнему видят.

#### Известные пределы стража

- R3(а) краснит на любую строку с `recipes/` вне docstring, в том числе на лог-сообщение или текст UI; цена — строка
  allowlist.
- R2 `.dump(` в файле, где есть ruamel, ловит и `json.dump`; сейчас файлов с ruamel и `.dump(` вне движка три (`app_module/store.py`, `layout_controller.py`, `dataset_gen_section.py`), `json.dump` среди них нет.
- R1 не видит `getattr(mod, "patch_yaml_preserving")`, `importlib.import_module(...)` и переэкспорт через сторонний
  модуль; переэкспортёр сам импортирует писатель из `ENGINE_MODULES` и ловится как R1, живого переэкспорта нет.
- Остальные неохраняемые формы перечислены в docstring `test_single_writer_guard.py`; ужесточить стража стоит после
  первого ложного красного (OPEN_QUESTIONS). Матрица инъекций и ревью —
  `docs/reviews/2026-11-06_task-1.5-injection.md`, `docs/reviews/2026-11-06_task-1.4-1.5-review.md`.

### Ссылки

- Предыдущее: ADR-RCP-002 (инъекция `yaml_updater`, `duplicate`), ADR-RCP-005 (generic `yaml_io` в модуле),
  ADR-RCP-008 (атомарная запись, на которую опирается `_dump_atomic`).
- Форма рецепта и папка: ADR-RCP-006; `recipe.*` и `rev` сервиса: ADR-RCP-007; политика канона: ADR-RCP-010.
- План: [`plan.md`](../../../plans/2026-10-26_recipe-save-noise/plan.md), [`design.md`](../../../plans/2026-10-26_recipe-save-noise/design.md).

## ADR-RCP-010: Каноническая форма рецепта — кто под кого подстраивается (2026-10-26)

**Статус:** принято (2026-10-26, решение владельца; поправка №11 — вердикт CTO 2026-11-01). Исполняют задачи плана
[`recipe-save-noise`](../../../plans/2026-10-26_recipe-save-noise/plan.md) (1.1f, 1.1g, 1.1c, 1.2, 1.9, 1.10, 1.4,
1.5, 1.14); подробности и пробы — [`design.md`](../../../plans/2026-10-26_recipe-save-noise/design.md) §10. Уточняет
ADR-RCP-009 («`before` строит менеджер»). Связанные: ADR-RCP-003 (миграции), ADR-RCP-006 (папка).

**Контекст.** После ADR-RCP-009 шум записи зависит от одного вопроса: в какой форме вызывающий отдаёт `after`.
Одного модельного нормализатора на все GUI-пути не было: Дисплеи работали через модель `Recipe`, Save — через канон
`Topology`, Камера и Устройства — через raw. Владелец 2026-10-26: «продумать политику, кто под кого подстраивается,
чтобы нормализатор подходил всем и было согласовано со всеми».

### Решение: семь пунктов

1. **Владелец формы — модуль `recipe`.** Один нормализатор на приложение, диспетчеризует по форме; конверт
   `meta`/`data` проходит насквозь; запись snapshot нормализатор не использует (В-П3). Приложение регистрирует его
   одной фабрикой; `RecipeManager` (GUI) и `RecipeService` (хаб) получают экземпляры одного класса — процессы разные,
   один экземпляр невозможен. Сегодняшняя реализация формы v3 — `InspectorRecipeFormatHook`
   (`multiprocess_prototype/backend/recipe_format_hook.py`), протокол — `RecipeFormatHook.normalize` в `service.py`.
   Других нормализаторов целых рецептов нет; это правило R4 стража.
2. **Контракт нормализатора** (общий набор проверок в `recipe` плюс прогон на 22 рецептах и hypothesis):
   идемпотентен `N(N(x)) == N(x)`; тотален на любом валидном файле (невалидный → типизированная `RecipeFormatError`,
   частичного результата нет); детерминирован (hash seed 0..3); без правок дельта `N(файл) → N(файл)` пуста.
3. **Вызывающие подстраиваются под форму.** Чтение — `RecipeManager.read_canonical(slug) -> (doc, rev)`, `doc =
   N(файл)`. Вызывающий меняет только свою часть `doc` и отдаёт `patch_recipe(slug, after, expected_rev=rev)`.
   Сущности прототипа (`Recipe`, `Topology`, граф редактора) переводятся в канон и обратно одной парой адаптеров на
   границе (`multiprocess_prototype/adapters/recipe_canonical.py`): `recipe_from_canonical`, `recipe_to_canonical`,
   `topology_to_canonical`. `*_to_canonical` переносит правку модели на `base_doc` через `apply_delta(..., on_insert=
   minimize)`, поэтому `recipe_to_canonical(recipe_from_canonical(d), d) == d` для канонического `d`.
4. **Форма подстраивается под вызывающих только через фреймворк.** Нужно поле или форма, которой в каноне нет, —
   правка схемы или нормализатора в `recipe` плюс версия плюс шаг `@migration` (ADR-RCP-003) с ревью. Обход в
   вызывающем — нарушение (R4).
5. **Диск ≠ канон, программа умолчаний не пишет.** Файл хранит форму автора (комментарии, flow-стиль, опущенные
   умолчания); канон живёт только в памяти; мост между ними — дельта-писатель. Вставляемое поддерево проходит
   `on_insert` (`minimize` адаптера — `model_dump(exclude_defaults=True)` по типу сущности: процесс, провод,
   дисплей). Это **отменяет** прежнее решение плана «новые элементы — в полной форме модели». Правка пользователя
   НА значение-умолчание — изменённый лист, пишется явно: это выбор пользователя.
6. **Папка (ADR-RCP-006 v4).** Тот же контракт: `read_canonical` соберёт `doc` из `topology.yaml`, `params/*.yaml` и
   файла раскладки; вызывающие этого не замечают (ADR-RCP-009, раздел про папку).
7. **R4 стража (Task 1.5).** Вне модуля `recipe` и `adapters/recipe_canonical.py` вызовы `normalize_recipe_v3_raw`,
   `build_recipe_v3_raw`, `canonicalize_gui_positions` (кроме хука и миграций), `Recipe.from_dict(...)` в цепочке
   записи допустимы только строкой allowlist R4 с причиной.

### Поправка №11 (вердикт CTO 2026-11-01, Task 1.14)

8. **Один владелец секций редактора в GUI.** Секции `blueprint.processes/wires/displays` пишет только редактор;
   остальные вкладки меняют их через его модель (dispatch). Rebase базы без перезагрузки модели редактора допустим
   только для записей вне этих секций. Редактор не пишет в рецепт процессы фундамента — по именам процессов
   фрагментов `manifest.base`, не по флагу `protected` (Task 1.14b, поправка №12). Основание: вердикт CTO
   `docs/reviews/2026-11-01_c30-14of17-cto-verdict.md` (владение секциями; правило по флагу `protected` заменено
   на имена в `docs/reviews/2026-11-02_task-1.14b-cto-F2.md`).
9. **Форма решения F3.** Слоты вкладки «Устройства» ловят только `RecipeDevicesError`: `RecipeLockTimeout`,
   `RecipeFormatError` и `YamlWriteRefused` вылетают из слота Qt, и при занятом локе GUI-поток ждёт до 5 с. Как
   показать эти ошибки пользователю — отдельная задача после merge (решение владельца 2026-10-28), не часть C-30;
   строку в `ORDER` заводит лид, вопрос записан в `docs/claude/OPEN_QUESTIONS.md`.

### Нарушения политики на момент решения и кто их чинит

| Путь | Нарушение | Задача |
|---|---|---|
| Дисплеи → `RecipeStoreFromManager.write` | строил рецепт целиком из модели `Recipe` | 1.1c (`read_canonical` + `recipe_to_canonical`) |
| Recipes/Pipeline-Save, closeEvent → `save.py` | `build_recipe_v3_raw` собирал рецепт целиком | 1.2 (`topology_to_canonical`); `build_recipe_v3_raw` — FREEZE |
| Камера `save()` | мутировала весь raw | 1.10; вердикт CTO 2026-11-01 заменил план: Камера не пишет в файл, а меняет модель редактора командой `SetPluginConfig` (форма `config:`), файл пишет редактор |
| Устройства `upsert/remove` | список из raw, запись секции | 1.9 (`read_canonical`) |
| Автосохранение раскладки | свой писатель `update_blueprint_metadata_preserving` | 1.1e, 1.1c (`save_layout` → `_apply_layout`) |
| `service.save` (хаб) | `safe_dump` нормализованного тела целиком | 1.4 (тот же класс хука, движок) |
| `RecipeEngine.save` (snapshot) | конверт целиком | 1.4 (дельта по путям snapshot; нормализатор не используется) |
| Миграции `recipes/migrations/*` | переписывают форму | разрешены п. 4; пишут через движок (1.1b, 1.5) |

### Решено на стадии 0 (раунд 3, 2026-10-26)

- **В-П1 — GUI импортирует хук из `backend/`:** можно, хук не переносится. `.sentrux/rules.toml` запрещает только
  `backend/* → frontend/*`; `frontend/app.py` уже импортирует `backend`; хук без Qt. Проверка в 1.1g: нет цикла
  импорта `recipes.save ↔ adapters.recipe_canonical`.
- **В-П2 — `minimize` знает только умолчания pydantic:** допустимо с условием. Файл читает backend-модель
  `SystemBlueprint`, минимизирует доменная; RED 1.1g `backend_load(minimize(x)) == backend_load(x)` по типам сущностей
  на 22 рецептах, расхождение → `minimize` это поле не опускает (`restart_policy`, `priority`, `enabled`).
- **В-П3 — хук-тождество для snapshot не нужно:** `RecipeEngine.save` нормализатор не использует,
  диспетчеризация по форме уже в `InspectorRecipeFormatHook.normalize`.

### Последствия и ссылки

- Новый вызывающий запись обязан идти через `read_canonical` и адаптер; иначе R4 краснеет.
- Изменение формы рецепта — всегда правка `recipe` и шаг `@migration`, не правка вызывающего.
- Связанные: ADR-RCP-003, -006, -009. Журнал решений — `design.md` §11.
