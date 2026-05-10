---
description: Проверка архитектурных инвариантов из .sentrux/rules.toml
---

Запусти проверку правил `.sentrux/rules.toml`:

1. Проверь, существует ли `.sentrux/rules.toml` в корне проекта. Если нет — сообщи пользователю, что файл нужно создать (см. https://github.com/sentrux/sentrux), и покажи минимальный шаблон:

```toml
[constraints]
max_cycles = 0
no_god_files = true

[[layers]]
name = "framework"
paths = ["multiprocess_framework/*"]
order = 0

[[layers]]
name = "prototype"
paths = ["multiprocess_prototype/*"]
order = 1

[[boundaries]]
from = "multiprocess_framework/modules/process_module/*"
to = "multiprocess_framework/modules/frontend_module/*"
reason = "process не зависит от frontend"
```

2. Если файл есть — вызови `mcp__sentrux__check_rules` с `path` = абсолютный путь к корню проекта.

Покажи пользователю:
- Какие правила прошли ✅, какие упали ❌.
- По каждому failure — конкретные файлы/импорты, нарушающие правило.
- Подсказку как фиксить (вынести в общий слой, инвертировать зависимость, применить DI).

$ARGUMENTS
