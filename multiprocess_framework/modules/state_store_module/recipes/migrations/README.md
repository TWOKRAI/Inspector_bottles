# recipes/migrations — Миграции рецептов

Этот пакет зарезервирован под **generic-миграции** формата рецептов между
версиями (например, переименование служебных полей `meta.*`, изменение
структуры самого контейнера рецепта).

## Что НЕ кладётся сюда

Доменные миграции — те, что знают про конкретные ключи прикладного
приложения (`processing_blocks`, `nodes`, `regions.zones` и т.п.) — **не
относятся к фреймворку**. Они должны жить в прикладном слое и подключаться
к `RecipeEngine` через параметры конструктора:

```python
from multiprocess_framework.modules.state_store_module import RecipeEngine
from my_app.recipes.migrations import migrate_recipe_data, needs_migration

engine = RecipeEngine(
    store=tree_store,
    recipes_dir=Path("./recipes"),
    migration_fn=migrate_recipe_data,
    migration_check_fn=needs_migration,
)
```

См. ADR-SS-003 в `DECISIONS.md` модуля.

## Что МОЖЕТ появиться здесь

- Миграция формата `meta.created_at` (например, ISO → epoch).
- Переименование служебных полей самого `recipe.yaml`.
- Любая generic-логика, не зависящая от прикладной схемы рецепта.

Пока таких миграций нет — пакет остаётся пустым.
