# changelog_gen

Генератор changelog из Conventional Commits. Парсит `git log`, группирует по `type`, выдаёт markdown / plain / json. Stdlib-only, Python 3.12+.

Идеально работает в паре с [`validate_commit/`](../validate_commit/) — там валидируется формат, тут собирается отчёт.

## Быстрый старт

```bash
# С последнего tag до HEAD, markdown
python scripts/changelog_gen/changelog_gen.py

# Конкретный диапазон
python scripts/changelog_gen/changelog_gen.py --from v1.0.0 --to v1.1.0

# Для релизной заметки
python scripts/changelog_gen/changelog_gen.py --release-name v1.1.0 --release-date 2026-05-24

# Без хэшей, plain (для email/issue)
python scripts/changelog_gen/changelog_gen.py --no-hashes --style plain

# Для CI / роботизированной обработки
python scripts/changelog_gen/changelog_gen.py --style json

# Включить commits, не подходящие под known types
python scripts/changelog_gen/changelog_gen.py --include-unknown

# Запись в файл
python scripts/changelog_gen/changelog_gen.py > CHANGELOG_NEXT.md
```

## Формат коммита (Conventional Commits)

```
type(scope)?!?: subject

[body]

[BREAKING CHANGE: explanation]
```

| Часть | Пример | Назначение |
|-------|--------|------------|
| `type` | `feat`, `fix`, `docs`, ... | Категория для группировки |
| `scope` (опц.) | `(api)`, `(auth)` | Подсистема — рендерится `**bold**` |
| `!` (опц.) | `feat!:` | Breaking change |
| `subject` | короткая строка | Что сделано |
| `BREAKING CHANGE:` (опц.) | в body/footer | Альтернатива `!`, объясняет |

## Markdown-выход (пример)

```markdown
## [v1.1.0] — 2026-05-24

### ✨ Features
- (a1b2c3d) **api**: добавить эндпоинт /users
- (e4f5g6h) добавить кэширование

### 🐛 Bug Fixes
- (i7j8k9l) **auth**: исправить login flow

### ⚠ BREAKING CHANGES
- (a1b2c3d) удалён legacy /v1 эндпоинт
```

С `repo_url = "https://github.com/org/repo"` каждый хэш превратится в кликабельную ссылку.

## Что настраивается

| Секция | Параметр | Назначение |
|--------|----------|------------|
| `[git]` | `from`, `to` | Диапазон коммитов. Пустой `from` = последний tag. |
| `[groups]` | `"label" = [types]` | Маппинг type → секция changelog. Порядок секций — порядок ключей. |
| `[format]` | `style`, `release_name`, `release_date`, `include_*`, `hash_length`, `repo_url` | Внешний вид и состав |

CLI флаги перекрывают конфиг: `--from`, `--to`, `--style`, `--release-name`, `--release-date`, `--no-hashes`, `--no-breaking`, `--authors`, `--include-unknown`.

## Exit-коды

| Код | Когда |
|-----|-------|
| `0` | Успех — даже если коммитов в диапазоне 0 (выведется пустой changelog) |
| `2` | Не git-репо / git log упал / плохой конфиг |

## Breaking changes — как ловятся

Любой из двух способов:
1. `!` в header'е: `feat(api)!: drop /v1`
2. Footer/body: `BREAKING CHANGE: legacy /v1 endpoint removed`

Если включён `include_breaking = true` (дефолт) — breaking коммиты дополнительно агрегируются в секцию `⚠ BREAKING CHANGES`. Текст берётся из `BREAKING CHANGE:` footer'а, если есть; иначе из `subject`.

## Когда полезно

- Перед релизом — сгенерировать черновик CHANGELOG для ревью.
- В CI на merge в `main` — обновить `CHANGELOG.md` автоматически.
- Для PR с большим числом коммитов — быстро увидеть «что вообще делали в этой ветке».
- В команде, где `/dev:ship` создаёт GitHub release — джейсон-выход → API.

## Ограничения

- Опирается на **только** subject первой строки. Многострочные subject'ы (без conventional) попадают в `unknown` (отображаются с `--include-unknown`).
- Merge-коммиты исключены (`--no-merges`).
- `--from` по умолчанию = последний tag. На репо без тегов берётся весь git log — может быть очень длинно. Указывай `--from` явно или поставь первый tag.
- Не модифицирует `CHANGELOG.md` — выдаёт текст в stdout. Объединение со старым CHANGELOG — на пользователе (или через CI-обвязку).
- Scope/type — case-insensitive в маппинге; в выводе scope рендерится строчными.
