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
  `run_migration()` (ruamel round-trip file-writer, паттерн
  `drop_display_name.py`) для будущего одобренного применения.
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
