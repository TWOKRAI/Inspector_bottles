# code_stats

Универсальный счётчик файлов / папок / строк / слов / символов на stdlib (Python 3.12+).

## Быстрый старт

```bash
# Дефолтный конфиг (scripts/code_stats/code_stats.toml), сканирует "."
python scripts/code_stats/code_stats.py

# Несколько конкретных папок сразу
python scripts/code_stats/code_stats.py multiprocess_framework Services Plugins

# Зоны проекта верхнего уровня (одна строка на папку верхнего уровня)
python scripts/code_stats/code_stats.py --group-by directory --dir-depth 1

# Чистый SLOC: комментарии и docstring не считаются кодом
python scripts/code_stats/code_stats.py --no-comments --no-docstrings

# JSON вместо таблицы
python scripts/code_stats/code_stats.py --format json

# Топ-20 директорий (TOTAL всё равно считается по всем)
python scripts/code_stats/code_stats.py --group-by directory --limit 20

# Свой конфиг
python scripts/code_stats/code_stats.py --config path/to/other.toml
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
`--no-comments`, `--no-docstrings`.

`[scan] paths` принимает несколько папок; пересекающиеся пути (`.` и `./scripts`)
не дают двойного учёта — дедупликация по resolved-пути.

## Правдивость цифр

Три решения, из-за которых числа отличаются от наивного обхода:

1. **`git_tracked = true` (по умолчанию).** Считаются только файлы, известные git
   (tracked + untracked, не попавшие в `.gitignore`). Без этого сгенерированные кэши
   забивают отчёт: в этом репозитории `graphify-out/cache` давал +914 000 строк `.json` —
   в 2 раза больше, чем весь Python-код проекта. Вне git-репозитория режим сам падает
   обратно на обход ФС **с предупреждением в stderr** (тихая подмена метода = вранью).
2. **TOTAL считается по всем группам**, даже когда вывод обрезан `--limit`.
3. **`chars` — символы, а не байты.** `wc -c` на UTF-8-кириллице даёт примерно вдвое
   больше. И осторожно с `wc -w` как «эталоном»: в C-локали он режет UTF-8-кириллицу по
   байту `0xA0` — слово `РРРР` он считает как 4 слова, поэтому на русских комментариях
   его цифра завышена.

## Колонки отчёта

- `group` — расширение / папка / файл (зависит от `group_by`)
- `files` — количество файлов в группе
- `dirs` — количество **уникальных папок**, в которых лежат учтённые файлы
  (в строке TOTAL папки объединяются, а не суммируются: `.py` и `.md` в одной папке → 1)
- `lines` — все физические строки
- `code` — эффективные строки (см. «Что считается кодом» ниже)
- `blank` — пустые строки
- `comment` — строки-комментарии (`#`, `<!-- -->`)
- `docstr` — строки внутри `"""..."""` / `'''...'''` для `.py`
- `words` — слова по правилу `wc -w`: последовательности непробельных символов
- `chars` — суммарное число символов

`words` и `chars` считаются по **полному тексту файла** и не подчиняются
`--no-comments` / `--no-docstrings` — эти флаги влияют только на `code`. То есть
`code` может упасть втрое, а `words` останется прежним: это не ошибка, а разные
вопросы («сколько строк логики» против «сколько текста написано»).

При нескольких выбранных папках ключи строк строятся от их **общего родителя**,
иначе `a/same.py` и `b/same.py` схлопнулись бы в одну строку `same.py`.

## Что считается кодом (`code`)

`code` = все строки минус то, что выключено флагами `[count]`:

| Конфиг | Что получается в `code` | Когда так честнее |
|--------|-------------------------|-------------------|
| `comments = true`, `docstrings = true` (**дефолт**) | все непустые строки, включая комментарии и docstring | «сколько всего написано руками» |
| `comments = false`, `docstrings = false` (`--no-comments --no-docstrings`) | чистый **SLOC** — только исполняемые строки | сравнение с cloc/tokei/scc, оценка объёма логики |

Общепринятый в индустрии SLOC (cloc, tokei, scc) — это **второй** вариант: комментарии
кодом не считаются, они идут отдельной колонкой. Дефолт здесь другой осознанно: в этом
проекте комментарии и docstring — 24% строк `.py`, и для оценки проделанной работы их
выкидывать неправильно. Для сравнения с внешними инструментами бери `--no-comments
--no-docstrings`, для «объёма написанного» — дефолт. Обе цифры честные, врёт только
та, у которой не назван режим.

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
python scripts/code_stats/code_stats_tokei.py --root multiprocess_framework
python scripts/code_stats/code_stats_tokei.py --format json
```

**Особенности tokei:**
- Группировка всегда по языку (расширению-семейству), не по директории.
- `chars` и `docstr` колонки = 0 (tokei их не предоставляет; docstring уходит в `comment`).
- В plain-text форматах (`.md`, `.txt`) `code` = 0, а вся прозра считается `comment` — это модель tokei, не баг. Смотри колонку `lines`.

**Когда что:**
- stdlib `code_stats.py` — без зависимостей, группировка по директориям, есть `chars`.
- `code_stats_tokei.py` — точнее на C/JS/Rust, быстрее на больших репо.
