# todo_inventory

Сбор `TODO/FIXME/HACK/XXX/BUG/NOTE` (настраивается) с автором и возрастом через `git blame`.

## Запуск

```bash
python scripts/todo_inventory/todo_inventory.py                       # все теги, с git blame
python scripts/todo_inventory/todo_inventory.py --no-blame            # быстро, без авторов
python scripts/todo_inventory/todo_inventory.py --group-by author     # сводка по авторам
python scripts/todo_inventory/todo_inventory.py --sort-by age --limit 20  # топ-20 старейших
python scripts/todo_inventory/todo_inventory.py --format json         # для парсинга
```

## Вывод

Две части:
1. **Сводка** по `group_by` (`tag` / `file` / `author` / `none`).
2. **Список находок**: `tag | age | author | file:line | text`.

Возраст — дни с момента коммита, в котором последний раз менялась строка с тегом.
Если git blame отключён или файл не в репо — `age` и `author` будут `—`.

## Регулярное выражение

```
\b(TODO|FIXME|HACK|XXX|BUG|NOTE)\b\s*[:\-(]?\s*(.*)
```

Сопоставляет тег целым словом + опциональные `:`, `-`, `(` после. Текст после — содержимое для отчёта (обрезается до `max_text`).

## Когда полезно

- Перед спринтом уборки техдолга: топ-N старейших TODO с авторами.
- Сводка по автору: кто оставил больше всего открытых пометок.
- CI-нотификация: `--format json` → пайплайн → алёрт если HACK старше 90 дней.

## Замечания

- **Свои хиты внутри скрипта**: docstring [todo_inventory.py](todo_inventory.py) сам содержит слово `TODO/FIXME` как часть описания. Если они мешают — добавь `scripts/todo_inventory/*` в `exclude.path_patterns` своего конфига.
- `git blame` — это subprocess на каждый файл с хитами. На репозитории на 100k файлов и десятки тысяч TODO будет медленно — используй `--no-blame` для быстрого скана.
- Регистрозависимо. Чтобы ловить `todo` строчными — добавь его в `detect.tags`.
