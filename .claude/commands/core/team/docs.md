---
description: Run the Docs-Writer agent (Haiku) — write/update documentation
---

Запусти агента **docs-writer** (subagent_type: "docs-writer", model: haiku).

Передай ему:
1. Какие файлы документировать
2. Что именно: docstrings, README, STATUS.md, DECISIONS.md
3. Контекст: «Прочитай CLAUDE.md для языковых правил»

После выполнения:
- Бегло проверь качество документации
- Покажи пользователю что было обновлено

Что документировать: $ARGUMENTS
