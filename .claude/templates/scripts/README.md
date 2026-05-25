# `scripts/` — каталог утилит проекта

> **BUNDLE README — НЕ project copy.** Этот README лежит в seed-bundle
> `.claude/templates/scripts/`. При `claude-kit new` / `claude-kit sync`
> весь bundle (включая этот файл) auto-копируется в проектный `scripts/`.
> Project-local правки выигрывают: существующие `scripts/<X>/` НЕ
> перезаписываются. Детали и trade-off — `docs/decisions/0002-script-bundle-delivery.md`
> и [BOOTSTRAP.md](../../BOOTSTRAP.md#scripts-bundle-два-уровня).

Учётный индекс того, что лежит в `scripts/`. Один источник истины: какие скрипты есть, для чего и как запускать.

Все скрипты запускать **из корня проекта**, иначе относительные пути в конфигах могут не сработать. Зависимости — stdlib Python 3.12+ (см. оговорки у конкретных подпакетов).

---

## 1. Метрики и аудит

Самостоятельные подпакеты: `*.py` + `*.toml` (конфиг) + `README.md` (детальная справка). Без внешних зависимостей сверх stdlib (кроме `code_stats_tokei.py` — нужен бинарь `tokei`).

| Подпакет | Slash | Что показывает | README |
|----------|-------|----------------|--------|
| [`code_stats/`](code_stats/) | `/code-stats`, `/code-stats-tokei` | LOC / файлы / символы по расширениям и директориям. Два движка: stdlib (с docstrings и chars) и `tokei` (точный multi-language). | [README](code_stats/README.md) |
| [`test_ratio/`](test_ratio/) | `/test-ratio` | LOC-отношение `tests/` к `code/` на каждый модуль. Дополнение к `/sentrux-gaps` (объёмная метрика). | [README](test_ratio/README.md) |
| [`clean_cache/`](clean_cache/) | `/clean-cache` | Чистка `__pycache__/`, `.pytest_cache/`, `*.pyc`, `.coverage` и т.п. **Dry-run по умолчанию**, реальное удаление — `--apply`. | [README](clean_cache/README.md) |
| [`todo_inventory/`](todo_inventory/) | `/todo-inventory` | Сбор `TODO/FIXME/HACK/XXX/BUG/NOTE` с автором и возрастом через `git blame`. | [README](todo_inventory/README.md) |
| [`secrets_audit/`](secrets_audit/) | `/secrets-audit` | Аудит утечек secrets по regex: AWS / GCP / GitHub PAT / OpenAI / JWT / private keys / generic password assignments. Entropy-фильтр для generic-паттернов. Exit 1 при находках — пригодно для CI/pre-push. | [README](secrets_audit/README.md) |
| [`link_check/`](link_check/) | `/link-check` | Проверка Markdown-ссылок: relative paths, `#anchor`'ы, опционально HTTP-проверка через HEAD. Inline-suppression `<!-- link-check: ignore -->`. | [README](link_check/README.md) |
| [`claude_md_audit/`](claude_md_audit/) | `/claude-md-audit` | Meta-аудит `.claude/`: frontmatter агентов/команд, осиротевшие slash-скрипты, ссылки в MEMORY.md, хуки в settings.json. | [README](claude_md_audit/README.md) |
| [`changelog_gen/`](changelog_gen/) | `/changelog-gen` | Генератор changelog из Conventional Commits: парсит `git log <from>..<to>`, группирует по type, рендерит markdown/plain/json. Breaking changes — отдельной секцией. | [README](changelog_gen/README.md) |

Конфиг подпакета лежит рядом с `*.py` (например, [`code_stats/code_stats.toml`](code_stats/code_stats.toml)) — CLI-флаги перекрывают значения из конфига.

---

## 2. Валидация коммитов

| Подпакет | Запуск | Что делает | README |
|----------|--------|------------|--------|
| [`validate_commit/`](validate_commit/) | git hook `commit-msg` (ставит `install_hook.sh`) | Валидация commit-сообщения: Conventional Commits + обязательные trailers `Why:` / `Layer:`. Формат: `.claude/COMMIT_GUIDE.md`. | [README](validate_commit/README.md) |

---

## 3. Git hooks

| Файл | Slash | Что делает |
|------|-------|------------|
| [`hooks/pre-push`](hooks/pre-push) + [`install_pre_push_hook.sh`](install_pre_push_hook.sh) | `/install-pre-push` | Перед `git push` запускает `sentrux check` (правила) и `sentrux gate` (регрессия vs baseline). Блокирует push при провале. Тихо пропускается если sentrux не установлен. |

Установка хука одной командой:

```bash
bash scripts/install_pre_push_hook.sh
```

Хук работает **локально** (не уезжает в репозиторий) — на новой машине переустановить.

---

## 4. Быстрая навигация по slash-командам

| Slash | Скрипт |
|-------|--------|
| `/code-stats` | [`code_stats/code_stats.py`](code_stats/code_stats.py) |
| `/code-stats-tokei` | [`code_stats/code_stats_tokei.py`](code_stats/code_stats_tokei.py) |
| `/test-ratio` | [`test_ratio/test_ratio.py`](test_ratio/test_ratio.py) |
| `/clean-cache` | [`clean_cache/clean_cache.py`](clean_cache/clean_cache.py) |
| `/todo-inventory` | [`todo_inventory/todo_inventory.py`](todo_inventory/todo_inventory.py) |
| `/secrets-audit` | [`secrets_audit/secrets_audit.py`](secrets_audit/secrets_audit.py) |
| `/link-check` | [`link_check/link_check.py`](link_check/link_check.py) |
| `/claude-md-audit` | [`claude_md_audit/claude_md_audit.py`](claude_md_audit/claude_md_audit.py) |
| `/changelog-gen` | [`changelog_gen/changelog_gen.py`](changelog_gen/changelog_gen.py) |
| `/install-pre-push` | [`install_pre_push_hook.sh`](install_pre_push_hook.sh) |

---

## 5. Конвенции для новых скриптов

Если добавляешь новый скрипт — придерживайся стиля шаблона:

1. **Подпакет, а не один файл.** Если у скрипта есть конфиг, тесты, или больше одной функции — выноси в `scripts/<name>/` с `<name>.py`, `<name>.toml`, `README.md`, опционально `tests/`.
2. **README обязателен.** Минимум: «Что находит / Запуск / Колонки / Когда полезно / Ограничения».
3. **Конфиг через TOML.** CLI-флаги перекрывают значения, дефолтный конфиг рядом с `.py`.
4. **Запуск из корня.** Все пути относительные от корня проекта. Не использовать `cd`.
5. **Stdlib first.** Внешние зависимости — только если без них нельзя. Указать в README раздел «Требования».
6. **Slash-команда для частого.** Если скрипт планируется к регулярному вызову — завести `.claude/commands/<ns>/<name>.md` с однострочным описанием.
7. **Учёт здесь.** После создания добавить строку в подходящий раздел этого README.
