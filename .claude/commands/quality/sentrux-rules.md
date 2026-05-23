---
description: Проверка архитектурных инвариантов из .sentrux/rules.toml
---

Запусти проверку правил `.sentrux/rules.toml`:

1. Проверь, существует ли `.sentrux/rules.toml` в корне проекта. Если нет — сообщи пользователю, что файл нужно создать (см. https://github.com/sentrux/sentrux и [`.claude/mcp/sentrux/rules.template.toml`](../../.claude/mcp/sentrux/rules.template.toml) если есть), и покажи минимальный generic-шаблон:

```toml
[constraints]
max_cycles = 0
no_god_files = true

[[layers]]
name = "domain"
paths = ["src/*/domain/*", "src/*/core/*"]
order = 0

[[layers]]
name = "adapters"
paths = ["src/*/adapters/*", "src/*/io/*"]
order = 1

[[boundaries]]
from = "src/*/domain/*"
to = "src/*/adapters/*"
forbidden = true
reason = "domain не должен зависеть от adapters (DIP)"
```

> Это generic-пример (hexagonal/DDD). Подгони под реальную архитектуру проекта (см. `.claude/modes/_stack.md` → "Layers").

2. Если файл есть — вызови `mcp__sentrux__check_rules` с `path` = абсолютный путь к корню проекта.

Покажи пользователю:
- Какие правила прошли ✅, какие упали ❌.
- По каждому failure — конкретные файлы/импорты, нарушающие правило.
- Подсказку как фиксить (вынести в общий слой, инвертировать зависимость, применить DI).

$ARGUMENTS
