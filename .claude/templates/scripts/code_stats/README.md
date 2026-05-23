# code_stats

Универсальный счётчик файлов / строк / символов на stdlib (Python 3.12+).

## Быстрый старт

```bash
# Дефолтный конфиг (scripts/code_stats/code_stats.toml), сканирует "."
python scripts/code_stats/code_stats.py

# Конкретная папка
python scripts/code_stats/code_stats.py --root src

# JSON вместо таблицы
python scripts/code_stats/code_stats.py --format json

# Группировка по директориям, топ-20
python scripts/code_stats/code_stats.py --group-by directory --limit 20

# Свой конфиг
python scripts/code_stats/code_stats.py --config path/to/other.toml
```

## Что настраивается в `code_stats.toml`

| Секция | Параметр | Назначение |
|--------|----------|------------|
| `[scan]` | `root`, `recursive`, `follow_symlinks` | Что обходить |
| `[formats]` | `include` | Список расширений (`[]` = все файлы) |
| `[exclude]` | `dirs`, `file_patterns`, `path_patterns` | Glob-паттерны пропуска |
| `[count]` | `blank_lines`, `comments`, `docstrings`, `chars`, `encoding` | Что считать как «строка кода» |
| `[output]` | `format`, `group_by`, `sort_by`, `sort_order`, `show_total`, `limit` | Как показать |

CLI-флаги (`--root`, `--format`, `--group-by`, `--sort-by`, `--limit`, `--no-total`)
перекрывают значения из конфига.

## Колонки отчёта

- `group` — расширение / папка / файл (зависит от `group_by`)
- `files` — количество файлов в группе
- `lines` — все физические строки
- `code` — эффективные строки кода (с учётом флагов `blank_lines`/`comments`/`docstrings`)
- `blank` — пустые строки
- `comment` — строки-комментарии (`#`, `<!-- -->`)
- `docstr` — строки внутри `"""..."""` / `'''...'''` для `.py`
- `chars` — суммарное число символов

## Поддерживаемые типы файлов

Для подсчёта комментариев и docstring используется стратегия по расширению:

- `.py` — комментарии `#`, docstring `"""`/`'''`
- `.md` — HTML-комментарии `<!-- ... -->` (многострочные)
- `.sh`, `.bash`, `.zsh`, `.toml`, `.yaml`, `.yml` — комментарии `#`
- Остальные — просто строки и символы

Расширить можно, добавив новый `Counter` в `_COUNTERS` в `code_stats.py`.

## tokei-вариант: `code_stats_tokei.py`

Рядом лежит обёртка над [`tokei`](https://github.com/XAMPPRocky/tokei) с тем же `code_stats.toml`. Используй её, когда нужен **точный** подсчёт LOC с настоящими токенайзерами по 200+ языкам.

```bash
# Требуется: brew install tokei (или cargo install tokei)
python scripts/code_stats/code_stats_tokei.py
python scripts/code_stats/code_stats_tokei.py --root src
python scripts/code_stats/code_stats_tokei.py --format json
```

**Особенности tokei:**
- Группировка всегда по языку (расширению-семейству), не по директории.
- `chars` и `docstr` колонки = 0 (tokei их не предоставляет; docstring уходит в `comment`).
- В plain-text форматах (`.md`, `.txt`) `code` = 0, а вся прозра считается `comment` — это модель tokei, не баг. Смотри колонку `lines`.

**Когда что:**
- stdlib `code_stats.py` — без зависимостей, группировка по директориям, есть `chars`.
- `code_stats_tokei.py` — точнее на C/JS/Rust, быстрее на больших репо.
