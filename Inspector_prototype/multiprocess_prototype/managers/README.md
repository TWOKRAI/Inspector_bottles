# managers — прикладные менеджеры прототипа

Не входит во фреймворк. Используется из `frontend/launcher.py`, вкладок настроек/рецептов и тестов.

| Модуль | Роль |
|--------|------|
| `recipe_manager.py` | YAML рецептов: слоты регистров и app, миграция старого формата |
| `access_context.py` | Права редактирования и видимость полей в таблицах рецептов |
| `app_recipe_aggregate.py` | Снимок/дефолты для app-части рецепта (`SchemaBase`) |

Подробнее: [docs/ARCHITECTURE.md](../docs/ARCHITECTURE.md) (раздел «Менеджеры и доступ»), [docs/RECIPES_SYSTEM.md](../docs/RECIPES_SYSTEM.md).

Общие чистые хелперы для нескольких панелей (не доменные менеджеры): [../frontend/coordinators/README.md](../frontend/coordinators/README.md).
