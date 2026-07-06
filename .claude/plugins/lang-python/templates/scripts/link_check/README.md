# link_check

Проверка Markdown-ссылок: relative paths, `#anchor`'ы, опционально внешние URL. Stdlib-only, Python 3.12+.

## Быстрый старт

```bash
# Проверка относительных путей + anchor'ов (быстро, без HTTP)
python scripts/link_check/link_check.py

# Включить HEAD-запросы к внешним URL
python scripts/link_check/link_check.py --external

# JSON для CI
python scripts/link_check/link_check.py --format json

# Отчёт без падения
python scripts/link_check/link_check.py --no-strict
```

## Что проверяется

| Тип ссылки | Пример | Проверка |
|------------|--------|----------|
| Relative path | `[x](../foo.md)` | Файл существует относительно .md |
| Anchor only | `[x](#section)` | Slug заголовка есть в **том же** файле |
| Path + anchor | `[x](other.md#section)` | Файл + slug заголовка в нём |
| HTTP(s) | `[x](https://example.com)` | HEAD-запрос (только при `--external`) |
| `mailto:` / `tel:` | `[x](mailto:a@b.c)` | Пропускается |
| Autolink | `<https://example.com>` | Учитывается как обычный URL |

Ссылки внутри inline-кода (`` `[text](url)` ``) и внутри fenced-блоков (` ``` `) **не проверяются** — это примеры синтаксиса, не реальные ссылки.

## Inline-suppression

```text
[broken-on-purpose](./does-not-exist.md) <!-- link-check: ignore -->
```

Маркер `link-check: ignore` в той же строке отключает все проверки для этой строки.

## Exit-коды

| Код | Когда |
|-----|-------|
| `0` | Битых ссылок нет |
| `1` | Найдены битые (под `strict=true`; в `--no-strict` → 0) |
| `2` | Ошибка: scan root не существует, плохой regex в `exclude_url_patterns` |

## Типы issue (`kind`)

- `missing_file` — relative path не найден на диске
- `missing_anchor` — заголовок-якорь отсутствует в целевом `.md`
- `http_error` — HEAD/GET вернул не-2xx/3xx, таймаут, DNS-ошибка
- `bad_scheme` — схема URL (например, `ftp://`) не в `allowed_schemes`

## Slug-формула для anchor'ов

```
heading.lower() → удалить пунктуацию (кроме `-` и `_`) → пробелы/`_` → `-`
```

Совместима с GitHub/GitLab Markdown. **Не** совместима со специфичными slug'ами mkdocs-material (там можно настроить через свой `[check].anchor = false`).

## HTTP-проверка — нюансы

- Дефолт **OFF** (медленно, flaky, требует сети).
- Сначала `HEAD`. Если сервер вернул 403/405 — повтор через `GET` (многие сайты режут HEAD).
- Кеш в памяти на время одного запуска: один URL — одна проверка.
- `exclude_url_patterns` — regex'ы для URL, которые не проверяются никогда (localhost, example.com и т.п.).

## Когда полезно

- В CI как gate на корректность документации.
- После рефакторинга docs / переименования файлов.
- В `pre-commit` (с `--no-external` чтобы не зависеть от сети).
- Регулярно через `/loop` или `/schedule` с `--external` для свежести внешних ссылок.

## Ограничения

- Парсер ссылок regex-based: ловит `[text](url)` и `<url>`. Не парсит reference-style `[text][ref]`.
- Slug'и работают для GitHub-стиля, не для всех генераторов сайтов.
- HEAD/GET не учитывают rate-limiting (большие проекты с тысячами внешних ссылок могут ловить 429).
- Не проверяет содержимое за ссылкой (например, что `https://api.x.com/v1/users` отвечает осмысленным JSON) — только статус-код.
