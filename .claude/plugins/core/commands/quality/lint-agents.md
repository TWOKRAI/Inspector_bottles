---
description: Check agent .md files for consistency (frontmatter, model, tools, cross-ref with CLAUDE.md)
---

# /quality:lint-agents — линтер агентских определений

Запускает `python .claude/plugins/core/scripts/lint_agents.py` против `.claude/plugins/*/agents/`.
Проверяет YAML-frontmatter, наличие обязательных полей, валидность модели,
соответствие имён файлам и кросс-ссылки из CLAUDE.md.

## Когда использовать

- После переименования / добавления нового агента
- Периодически (раз в месяц или в pre-merge ревью)
- При обновлении списка моделей (Opus/Sonnet/Haiku versions)
- В CI как gate перед merge изменений в `.claude/plugins/*/agents/`

## Что проверяет

1. Frontmatter присутствует и парсится
2. Обязательные ключи: `name`, `description`, `model`, `tools`
3. `name` совпадает с именем файла
4. `model` — известный Claude ID (claude-opus-4-7, claude-sonnet-5, и т.д.)
5. `tools` — непустой список через запятую
6. `description` ≤ 500 символов
7. Тело имеет хотя бы один markdown-заголовок
8. Cross-check: имена ролей в CLAUDE.md имеют соответствующие файлы

## Выходные коды

- `0` — всё зелёное
- `1` — есть ERROR'ы (CI блокирует merge)
- `2` — только WARN'ы (review рекомендуется, но не блокер)

С флагом `--strict`: предупреждения тоже становятся `exit 1`.

## Запуск

```bash
# Из корня проекта:
python .claude/plugins/core/scripts/lint_agents.py

# Строгий режим (warns также fail):
python .claude/plugins/core/scripts/lint_agents.py --strict

# Конкретный путь:
python .claude/plugins/core/scripts/lint_agents.py path/to/agents
```

## Реализация

Чистый Python 3.9+, **без внешних зависимостей** (нет `pyyaml` — свой
минимальный парсер для flat key:value). 200 строк, легко читать и
расширять. См. `.claude/plugins/core/scripts/lint_agents.py`.

Альтернатива (рассмотрена в ROADMAP § B.1): `agnix` — comprehensive
линтер агентских файлов от внешнего автора. Решили писать свой минимальный,
потому что:
- Node-based, добавляет лишнюю зависимость
- Наш use-case узкий (10 файлов, чёткая структура)
- Свой = можем добавлять project-specific правила (threshold rules из CLAUDE.md)

Если в будущем потребуется расширение (lint complex YAML, multi-line
descriptions, etc.) — можно переключиться на agnix или добавить `pyyaml`.
