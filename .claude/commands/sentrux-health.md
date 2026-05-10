---
description: Снимок архитектурного здоровья проекта (scan + health), метрики и bottleneck
---

Запусти sentrux-проверку здоровья проекта:

1. Вызови `mcp__sentrux__scan` с `path` = абсолютный путь к корню проекта.
2. Вызови `mcp__sentrux__health` (без параметров — использует последний scan).

Покажи пользователю:
- **Quality signal** (0–10000) и его интерпретация: <3000 плохо, 3000–6000 средне, 6000–8000 хорошо, >8000 отлично.
- **Bottleneck** — корневая причина просадки.
- Таблицу 5 метрик: modularity, acyclicity, depth, equality, redundancy (raw + score).
- `cross_module_edges` / `total_import_edges`.

Если bottleneck = `acyclicity` (есть циклы) — порекомендуй `/sentrux-dsm` для разбора связей.
Если bottleneck = `modularity` — порекомендуй пересмотреть границы модулей.

$ARGUMENTS
