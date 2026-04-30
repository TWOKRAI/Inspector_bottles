# file_comments

Универсальный инструмент для обработки текстовых файлов:

- **Добавление комментария с путём** — вставляет в начало каждого файла строку с его путём (относительным или абсолютным)
- **Подсчёт статистики** — строки, символы, пустые/непустые строки

Поддерживает конфигурацию через JSON-файл с учётом операционной системы (Windows, Linux, macOS).

## Установка

Модуль является частью проекта. Запуск из корня репозитория:

```bash
python -m Utils.file_comments comment .
python -m Utils.file_comments stats .
```

Или из папки `file_comments`:

```bash
cd Utils/file_comments
python -m file_comments comment ..
```

## Команды

### `comment` — добавить комментарии

Добавляет в начало каждого файла комментарий с путём.

```bash
python -m file_comments comment <root_dir> [опции]
```

**Опции:**

| Опция | Короткая | Описание |
|-------|----------|----------|
| `--extensions` | `-e` | Расширения файлов (например `.py .md`) |
| `--comment-symbols` | `-c` | Пары «расширение символ» (например `.py '#' .md '<!--'`) |
| `--use-absolute` | `-a` | Использовать абсолютные пути |
| `--ignore-dirs` | `-i` | Папки для игнорирования (например `.git __pycache__`) |
| `--dry-run` | `-n` | Не изменять файлы, только показать план |
| `--path-base` | `-b` | База для пути в комментарии (путь будет относительным к DIR, напр. `multiprocess_prototype\processes\file.py`) |

### `stats` — статистика

Подсчитывает статистику по файлам.

```bash
python -m file_comments stats <root_dir> [опции]
```

**Опции:**

| Опция | Короткая | Описание |
|-------|----------|----------|
| `--extensions` | `-e` | Расширения файлов |
| `--ignore-dirs` | `-i` | Папки для игнорирования |
| `--output` | `-o` | Формат вывода: `table` (по умолчанию) или `json` |

### `both` — комментарии + статистика

Сначала добавляет комментарии, затем выводит статистику.

```bash
python -m file_comments both <root_dir> [опции]
```

Поддерживает все опции команд `comment` и `stats`.

## Конфигурация

Общая опция `--config` / `-C` задаёт путь к JSON-файлу конфигурации.

### Структура конфигурации

```json
{
    "default": {
        "extensions": [".py", ".md"],
        "comment_symbols": {
            ".py": "#",
            ".md": "#"
        },
        "use_absolute_path": false,
        "ignore_dirs": [".git", "__pycache__", "venv"]
    },
    "windows": { ... },
    "linux": { ... },
    "darwin": { ... }
}
```

- **default** — базовая конфигурация
- **windows**, **linux**, **darwin** — переопределения для конкретной ОС (объединяются с `default`)

Пример: `config.example.json`

### Параметры

| Параметр | Тип | Описание |
|----------|-----|----------|
| `extensions` | `string[]` | Расширения обрабатываемых файлов |
| `comment_symbols` | `object` | Словарь `{".py": "#", ".md": "<!--"}` |
| `use_absolute_path` | `boolean` | Использовать абсолютные пути в комментариях |
| `path_base` | `string` | Каталог, относительно которого строится путь в комментарии (напр. родитель `root_dir`) |
| `ignore_dirs` | `string[]` | Папки, которые не обходим |

## Структура модуля

```
file_comments/
├── __init__.py       # Публичный API
├── __main__.py       # Точка входа (python -m file_comments)
├── cli.py            # Парсинг аргументов, main()
├── config.py         # OSType, Config, ConfigLoader
├── commenter.py      # PathCommenter
├── stats.py          # FileStatsCounter
├── facade.py         # FileProcessorFacade
├── file_utils.py     # iter_files()
├── models.py         # FileStats
├── config.example.json
└── README.md
```

## Использование как библиотеки

```python
from pathlib import Path
from Utils.file_comments import (
    Config,
    ConfigLoader,
    FileProcessorFacade,
)

config = Config(extensions=[".py"], ignore_dirs=[".git", "__pycache__"])
facade = FileProcessorFacade(Path("."), config)

# Добавить комментарии
facade.add_comments(dry_run=True)

# Получить статистику
stats = facade.get_stats()
for path, stat in stats.items():
    print(f"{path}: {stat.total_lines} строк, {stat.chars} символов")
```

## Требования

- Python 3.10+
- Стандартная библиотека (без внешних зависимостей)
