---
description: Inventory of TODO/FIXME/HACK with git blame (author, age)
---

Запусти инвентаризацию техдолга:

```bash
python scripts/todo_inventory/todo_inventory.py
```

Что собирает: `TODO/FIXME/HACK/XXX/BUG/NOTE` (теги настраиваются) с привязкой к автору и дате последнего изменения строки через `git blame`.

Конфиг: [scripts/todo_inventory/todo_inventory.toml](../../scripts/todo_inventory/todo_inventory.toml). Детали в [README.md](../../scripts/todo_inventory/README.md).

Полезные варианты:
- `python scripts/todo_inventory/todo_inventory.py --no-blame` — быстрый скан без git (без авторов/возраста).
- `python scripts/todo_inventory/todo_inventory.py --group-by author` — кто оставил больше всего.
- `python scripts/todo_inventory/todo_inventory.py --sort-by age --limit 20` — топ-20 старейших.
- `python scripts/todo_inventory/todo_inventory.py --format json` — для CI/нотификаций.

**Когда использовать:**
- Перед спринтом уборки техдолга: что есть, кто оставил, насколько старо.
- Поиск HACK/XXX старше N дней — критичные пометки на ревизию.
- Сводка по автору — кому возвращать «свои» TODO.

**Замечания:**
- `git blame` медленный на большом числе хитов — используй `--no-blame` для быстрого скана.
- Скрипт может находить TODO в собственном [todo_inventory.py](../../scripts/todo_inventory/todo_inventory.py) — это не баг, добавь `scripts/todo_inventory/*` в `exclude.path_patterns` своего конфига.

$ARGUMENTS
