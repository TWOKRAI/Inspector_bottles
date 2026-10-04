---
name: project-sentrux-baseline-2026-05
description: Baseline-метрики sentrux после seed-апгрейда 0.2.0 (2026-05-23) — точка отсчёта для будущих рефакторингов
metadata:
  type: project
---

Зафиксированный baseline после коммитов 887c0a0 + d5b2a44 (seed-template 0.2.0).

**Quality signal: 7161 / 10000**

| Метрика | Значение | Score |
|---|---|---|
| Modularity (bottleneck) | 0.265 | 5100 |
| Acyclicity | 0 циклов | 10000 ✓ |
| Depth | 4 уровня | 6667 |
| Equality | 0.380 | 6195 |
| Redundancy | 0.106 | 8943 |
| Cross-module edges | 1633 | — |

**DSM:** 1321 узел, 2404 edges, все ниже диагонали (clean layering ✓), 7 уровней, propagation cost 28.

**Rules:** 9/9 проверенных правил pass (всего в `.sentrux/rules.toml` 26 правил, остальные — Pro).

**Test gaps:** 2306 source / 554 test, coverage ratio **24.9%** — 1732 untested файла (включая legacy/internal).

**Git stats (30 дней):** 394 commits, 943 файла с churn, 30 hotspots, 91.9% solo-files.

**Why:** Любой рефакторинг или Phase X должен сравниваться с этим baseline через `mcp__sentrux__session_start` → правки → `session_end`. Деградация Quality signal > 200 пунктов или появление новых циклов = stop-line.

**How to apply:** Перед началом крупной задачи (рефакторинг 10+ файлов, новый модуль, миграция) — запустить `mcp__sentrux__session_start` чтобы заморозить текущее состояние. После `/ship` — `session_end` для diff.
