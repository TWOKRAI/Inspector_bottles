# code_stats

Универсальный счётчик файлов / папок / строк / слов / символов на stdlib (Python 3.11+).

## Быстрый старт

```bash
# Дефолтный конфиг (scripts/code_stats/code_stats.toml), сканирует "."
uv run --no-project python scripts/code_stats/code_stats.py

# Конкретная папка (или несколько сразу)
uv run --no-project python scripts/code_stats/code_stats.py src tests

# Зоны верхнего уровня (одна строка на папку верхнего уровня)
uv run --no-project python scripts/code_stats/code_stats.py --group-by directory --dir-depth 1

# Чистый SLOC: комментарии и docstring не считаются кодом
uv run --no-project python scripts/code_stats/code_stats.py --no-comments --no-docstrings

# JSON вместо таблицы
uv run --no-project python scripts/code_stats/code_stats.py --format json

# Группировка по директориям, топ-20
uv run --no-project python scripts/code_stats/code_stats.py --group-by directory --limit 20

# Свой конфиг
uv run --no-project python scripts/code_stats/code_stats.py --config path/to/other.toml
```

## Что настраивается в `code_stats.toml`

| Секция | Параметр | Назначение |
|--------|----------|------------|
| `[scan]` | `paths`, `recursive`, `follow_symlinks`, `git_tracked` | Какие папки обходить и чем ограничить набор файлов |
| `[formats]` | `include` | Список расширений (`[]` = все файлы) |
| `[exclude]` | `dirs`, `file_patterns`, `path_patterns` | Glob-паттерны пропуска |
| `[count]` | `blank_lines`, `comments`, `docstrings`, `chars`, `words`, `encoding` | Что считать как «строка кода» и считать ли слова |
| `[output]` | `format`, `group_by`, `dir_depth`, `sort_by`, `sort_order`, `show_total`, `limit` | Как показать |

CLI перекрывает конфиг: позиционные пути, `--root`, `--git-tracked` / `--no-git-tracked`,
`--format`, `--group-by`, `--dir-depth`, `--sort-by`, `--limit`, `--no-total`,
`--no-comments`, `--no-docstrings`. Пересекающиеся пути (`.` и `./scripts`) не дают
двойного учёта — дедупликация по resolved-пути.

## Правдивость цифр

1. **`git_tracked = true` (по умолчанию).** Считаются только файлы, известные git
   (tracked + untracked не из `.gitignore`). Без этого сгенерированные кэши (`graphify-out/`,
   дампы) раздувают отчёт в разы. Вне git-репозитория — обход ФС с предупреждением в stderr.
2. **TOTAL считается по всем группам**, даже когда вывод обрезан `--limit`.
3. **`chars` — символы, а не байты**; `words` — по правилу `wc -w`, но без байтовой
   резки UTF-8-кириллицы, которой страдает `wc -w` в C-локали.

## Колонки отчёта

- `group` — расширение / папка / файл (зависит от `group_by`)
- `files` — количество файлов в группе
- `dirs` — уникальные папки с учтёнными файлами (в TOTAL объединяются, не суммируются)
- `lines` — все физические строки
- `code` — эффективные строки кода (с учётом флагов `blank_lines`/`comments`/`docstrings`)
- `blank` — пустые строки
- `comment` — строки-комментарии (`#`, `<!-- -->`)
- `docstr` — строки внутри `"""..."""` / `'''...'''` для `.py`
- `words` — слова по правилу `wc -w`
- `chars` — суммарное число символов

`words` и `chars` считаются по полному тексту файла и не подчиняются
`--no-comments` / `--no-docstrings` — те влияют только на `code`.

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
uv run --no-project python scripts/code_stats/code_stats_tokei.py
uv run --no-project python scripts/code_stats/code_stats_tokei.py --root src
uv run --no-project python scripts/code_stats/code_stats_tokei.py --format json
```

**Особенности tokei:**
- Группировка всегда по языку (расширению-семейству), не по директории.
- `chars` и `docstr` колонки = 0 (tokei их не предоставляет; docstring уходит в `comment`).
- В plain-text форматах (`.md`, `.txt`) `code` = 0, а вся прозра считается `comment` — это модель tokei, не баг. Смотри колонку `lines`.

**Когда что:**
- stdlib `code_stats.py` — без зависимостей, группировка по директориям, есть `chars`.
- `code_stats_tokei.py` — точнее на C/JS/Rust, быстрее на больших репо.
