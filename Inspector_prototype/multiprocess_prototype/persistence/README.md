# persistence/

Персистентное состояние прототипа **вне** дерева исходников (или с явным путём через env).

## Корень данных

- **`INSPECTOR_DATA_DIR`** — абсолютный или пользовательский путь (`~` допускается).
- Иначе **`~/.inspector_prototype`** (кроссплатформенно).

`get_data_root()` / `ensure_data_root()` — в [`paths.py`](paths.py).

## user_prefs.json

Файл в корне данных. Сейчас хранится **`camera_type`**. API: `get_camera_type()`, `set_camera_type()` в [`user_prefs.py`](user_prefs.py).

## Расширение

Добавляйте новые модули в этом пакете (например `export_paths.py`, `session_cache.py`) и используйте тот же `get_data_root()` для подкаталогов.

## Миграция

Старый файл **`multiprocess_prototype/.inspector_prefs.json`** при первом запросе prefs переносится в `user_prefs.json` и удаляется (если удаление возможно).
