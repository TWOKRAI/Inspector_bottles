---
description: Сгенерировать changelog из Conventional Commits между двумя refs
---

Сгенерируй changelog из git-истории (Conventional Commits):

```bash
# Markdown с последнего tag до HEAD
python scripts/changelog_gen/changelog_gen.py

# Конкретный диапазон + имя релиза
python scripts/changelog_gen/changelog_gen.py --from v1.0.0 --to v1.1.0 --release-name v1.1.0

# Plain text без хэшей (для email / issue)
python scripts/changelog_gen/changelog_gen.py --no-hashes --style plain

# JSON для роботизированной обработки
python scripts/changelog_gen/changelog_gen.py --style json
```

Что делает: парсит `git log <from>..<to>` → ищет коммиты формата `type(scope)?!?: subject` → группирует по `type` в секции (Features, Bug Fixes, Documentation, ...) → агрегирует breaking changes (по `!` или `BREAKING CHANGE:`) в отдельную секцию.

Конфиг: [scripts/changelog_gen/changelog_gen.toml](../../scripts/changelog_gen/changelog_gen.toml). Детали — [README.md](../../scripts/changelog_gen/README.md).

**Хорошо работает в паре с** [`/validate_commit`](../../scripts/validate_commit/) — там валидируется формат, тут собирается отчёт.

Полезные варианты:
- `--from v1.0.0 --to HEAD` — релиз-нотa
- `--include-unknown` — захватить коммиты не в conventional-формате (legacy)
- `--authors` — приписать `by <author>` к каждому коммиту
- `--no-breaking` — отключить секцию BREAKING CHANGES (если она пугает читателей)

**Когда использовать:**
- Перед релизом — черновик CHANGELOG для ревью.
- В CI после merge в `main` — обновить `CHANGELOG.md`.
- Для большого PR — увидеть, что в нём реально сделано.

**Замечания:**
- Без тегов `--from` берёт весь git log — указывай явно на свежих репо.
- Не модифицирует `CHANGELOG.md` — выдаёт текст в stdout. Объединение/CI-flow — на тебе.
- Merge-коммиты пропускаются (`--no-merges`).

$ARGUMENTS
