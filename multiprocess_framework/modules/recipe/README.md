# recipe — управление рецептами (snapshot config-ветвей, detect, миграции, CRUD)

## Purpose

Крыша фреймворка над рецептами. Рецепт — это либо **config-snapshot** (envelope
`{meta, data}`, реплеится в реактивный store), либо **v3-blueprint** (плоская
топология для recipe-driven backend). Модуль консолидирует generic-механизмы:
движок snapshot/restore, распознавание формата, точку миграции через callbacks и
CRUD-менеджер. Доменных схем (cameras/robot/…) модуль НЕ знает — доменные пути и
миграции инжектируются прикладным слоем (ADR-SS-003, ADR-SS-011, ADR-RCP-001).

## Public API

Реэкспорт из `__init__.py` (совпадает с `__all__`):

- `RecipeEngine` — движок snapshot/restore config-ветвей; см. `interfaces.py::RecipeEngineProtocol`.
- `RecipeManager` — CRUD-обёртка + синхронизация `state.recipes.active`; см. `interfaces.py::RecipeManagerProtocol`.
- `is_v3_recipe` — распознать v3-blueprint vs config-snapshot; см. `detect.py`.
- `normalize_recipe_v3_raw` — единая сборка v3-raw на запись; см. `format.py`.
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
from multiprocess_prototype.recipes.yaml_io import update_yaml_preserving

manager = RecipeManager(engine, state_proxy=proxy, yaml_updater=update_yaml_preserving)
manager.duplicate("prod", "prod_copy")       # комментарии сохранены (ruamel)
manager.set_active("prod_copy")              # state.recipes.active обновлён
```

## Boundaries

- **НЕ знает доменных схем**: ветви (`cameras`/`robot`/…) и миграции инжектируются.
- **НЕ пишет comment-preserving YAML сам**: `yaml_updater` инжектируется (fallback —
  plain PyYAML без комментариев). Consolidation `yaml_io` → задача C3.
- **НЕ содержит реестра миграций** (`@migration`) и property-тестов round-trip — это
  задача C2. Сейчас миграция подключается callbacks-ами (ADR-SS-003).
- **Зависит от:** stdlib + PyYAML. Store типизирован через `StoreProtocol` — модуль
  НЕ импортирует `state_store_module` (нет цикла recipe ↔ state_store).
- **Импортируют его:** `state_store_module.recipes` (шим-реэкспорт `RecipeEngine`),
  прототип (`recipes/manager.py`, `recipes/format.py`,
  `backend/state/recipes/recipe_engine.py` — тонкие шимы).

## Stability

partial — full-scaffold (README + interfaces + contract-тесты + DECISIONS + STATUS)
присутствует; `yaml_io`/duplicate-consolidation (C3) и реестр миграций (C2) —
запланированный добор.
