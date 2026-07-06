---
description: Check architectural invariants from .sentrux/rules.toml
---

Запусти проверку правил `.sentrux/rules.toml`:

1. Проверь, существует ли `.sentrux/rules.toml` в корне проекта. Если нет — сообщи пользователю, что файл нужно создать (см. https://github.com/sentrux/sentrux и [`.claude/plugins/mcp-sentrux/rules.template.toml`](../../.claude/plugins/mcp-sentrux/rules.template.toml) если есть), и покажи минимальный generic-шаблон:

```toml
[constraints]
max_cycles   = 0
no_god_files = true

# Пути в [[boundaries]] — ЛИТЕРАЛЬНЫЕ префиксы директорий: `*` подставляет имя файла
# и НЕ раскрывает сегмент-директорию ("src/*/domain" не матчит ничего). Используй
# полный путь src/<pkg>/<layer> без хвостового слэша. Ключи: from/to/reason
# (ключа `forbidden` НЕТ — sentrux молча игнорирует неизвестные ключи).
[[boundaries]]
from   = "src/your_package/domain"
to     = "src/your_package/adapters"
reason = "domain не должен зависеть от adapters (DIP)"
```

> Это generic-пример. Подгони пути под реальную архитектуру (см. `.claude/modes/_stack.md` → "Layers") или возьми готовый архетип из `.claude/plugins/mcp-sentrux/templates/` (`.sentrux/rules.toml` обычно уже развёрнут `claude-kit-project new`).

2. Если файл есть — вызови `mcp__sentrux__check_rules` с `path` = абсолютный путь к корню проекта.

Покажи пользователю:
- Какие правила прошли ✅, какие упали ❌.
- По каждому failure — конкретные файлы/импорты, нарушающие правило.
- Подсказку как фиксить (вынести в общий слой, инвертировать зависимость, применить DI).

$ARGUMENTS
