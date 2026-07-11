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
