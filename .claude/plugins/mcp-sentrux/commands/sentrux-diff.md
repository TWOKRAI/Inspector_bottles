---
description: Compare current state against the recorded baseline (session_end)
---

Сравни текущее качество с baseline, который был сохранён через `/mcp-sentrux:sentrux-baseline`:

1. Вызови `mcp__sentrux__rescan` с `path` = абсолютный путь к корню проекта (или `mcp__sentrux__scan` если rescan недоступен).
2. Вызови `mcp__sentrux__session_end` (без параметров).

Покажи пользователю:
- `signal_before` → `signal_after` (с дельтой и направлением: ✅ улучшилось / ⚠️ без изменений / ❌ деградация).
- Какая метрика двинулась сильнее всего и в какую сторону.
- Краткое резюме: можно ли коммитить или стоит откатить часть правок.

Если pass=false (деградация) — рекомендуй `/mcp-sentrux:sentrux-dsm` чтобы найти, где появились новые связи/циклы.

$ARGUMENTS
