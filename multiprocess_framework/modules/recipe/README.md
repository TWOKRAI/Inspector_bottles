# recipe — управление рецептами (snapshot config-ветвей, detect, миграции, CRUD)

## Purpose

Крыша фреймворка над рецептами. Рецепт — это либо **config-snapshot** (envelope
`{meta, data}`, реплеится в реактивный store), либо **v3-blueprint** (плоская
топология для recipe-driven backend). Модуль консолидирует generic-механизмы:
движок snapshot/restore, распознавание формата, реестр step-миграций (+ точку
инъекции callbacks) и CRUD-менеджер. Доменных схем (cameras/robot/…) модуль НЕ
знает — доменные пути и миграции инжектируются прикладным слоем (ADR-SS-003,
ADR-SS-011, ADR-RCP-001, ADR-RCP-003).

## Public API

Реэкспорт из `__init__.py` (совпадает с `__all__`):

- `RecipeEngine` — движок snapshot/restore config-ветвей; см. `interfaces.py::RecipeEngineProtocol`.
- `RecipeManager` — CRUD-обёртка + синхронизация `state.recipes.active`; см. `interfaces.py::RecipeManagerProtocol`.
- `is_v3_recipe` — распознать v3-blueprint vs config-snapshot; см. `detect.py`.
- `has_top_level_blueprint` / `nested_blueprint_data` — единая «форма» v3-blueprint
  (top-level / вложенный в `data`), используемая is_v3_recipe и прикладными
  call-sites (unwrap_recipe, recipe_io.py, RecipesPresenter, RecipeStore); см. `detect.py`.
- `normalize_recipe_v3_raw` — единая сборка v3-raw на запись; см. `format.py`.
- `migration` / `registered_steps` / `run_chain` — реестр step-миграций
  (ADR-RCP-003); см. `migrations.py`.
- `StoreProtocol` / `RecipeEngineProtocol` / `RecipeManagerProtocol` — контракты (`interfaces.py`).

## Usage

1. Generic-движок с инъекцией доменных путей и миграций:

```python
from multiprocess_framework.modules.recipe import RecipeEngine

engine = RecipeEngine(
    store=tree_store,                       # StoreProtocol (TreeStore)
    recipes_dir=Path("recipes"),
    migration_fn=migrate_v1_to_v2,          # доменная миграция (прикладной слой)
    migration_check_fn=is_v1_recipe,
    default_paths=["cameras", "renderer"],  # доменные ветви (ADR-RCP-001)
)
engine.save("prod")                          # snapshot default_paths
engine.load("prod")                          # применить к store через 1 Transaction
```

2. Распознавание формата (v3-blueprint не реплеится в store):

```python
from multiprocess_framework.modules.recipe import is_v3_recipe

is_v3_recipe({"blueprint": {...}})           # True  → топология
is_v3_recipe({"meta": {"version": 2}, "data": {}})  # False → config-snapshot
```

3. CRUD-менеджер с comment-preserving duplicate:

```python
from multiprocess_framework.modules.recipe import RecipeManager

manager = RecipeManager(engine, state_proxy=proxy)  # comment-preserving writer по умолчанию
manager.duplicate("prod", "prod_copy")       # комментарии сохранены (ruamel round-trip)
manager.set_active("prod_copy")              # state.recipes.active обновлён
```

`duplicate()` по умолчанию использует `recipe.yaml_io.update_yaml_preserving`
(C3/ADR-RCP-005) — writer generic и живёт в модуле; инъекция `yaml_updater=`
нужна лишь для подмены (напр. plain-PyYAML в окружении без ruamel).

4. Реестр step-миграций (ADR-RCP-003) — декоратор регистрирует шаг, раннер
   прогоняет цепочку in-memory (READ-путь, файлы не переписывает):

```python
from multiprocess_framework.modules.recipe import migration, run_chain

@migration("recipe.config_snapshot", from_=1, to=2)
def migrate_regions(data: dict) -> dict:
    ...  # domain-specific dict-трансформация

migrated = run_chain("recipe.config_snapshot", data, from_version=1, to_version=2)
```

Инъекция callbacks (`migration_fn`/`migration_check_fn`, ADR-SS-003) остаётся
рабочим механизмом RecipeEngine — реестр её не заменяет, а становится дефолтным
источником шагов (декоратор прозрачен, декорированная функция инжектируется как
`migration_fn` без изменений).

## Boundaries

- **НЕ знает доменных схем**: ветви (`cameras`/`robot`/…) и миграции инжектируются.
- **Comment-preserving YAML — свой** (`recipe.yaml_io`, ruamel round-trip, C3): writer
  доменно-нейтрален, RecipeManager использует его по умолчанию; `yaml_updater=` —
  опциональная подмена.
- **Реестр миграций (`@migration`/`run_chain`) — generic, doc_type-namespaced**:
  сами шаги (domain dict-трансформации) живут в прикладном слое, модуль их не
  знает — только каталогизирует и прогоняет цепочкой (ADR-RCP-003, C2).
- **Зависит от:** stdlib + PyYAML. Store типизирован через `StoreProtocol` — модуль
  НЕ импортирует `state_store_module` (нет цикла recipe ↔ state_store).
- **Импортируют его:** `state_store_module.recipes` (шим-реэкспорт `RecipeEngine`),
  прототип (`recipes/manager.py`, `recipes/format.py`,
  `backend/state/recipes/recipe_engine.py`, `backend/launch.py`,
  `frontend/widgets/tabs/pipeline/recipe_io.py`,
  `frontend/widgets/tabs/recipes/presenter.py`, `adapters/stores/recipe_store.py`,
  `backend/state/recipes/migrations/v1_to_v2.py`,
  `recipes/migrations/format_v1_to_v2.py`).

## Stability

stable — full-scaffold (README + interfaces + contract-тесты + DECISIONS + STATUS)
присутствует; реестр миграций (C2, ADR-RCP-003) и `yaml_io`/duplicate-consolidation
(C3, ADR-RCP-005) — сделаны. Смежный хвост вне модуля: физперенос assembler/planner
в `process_manager/topology` (ADR-RCP-005, отдельная задача).
