---
name: feedback-flags-must-not-become-crutches
description: "FW_*-флаги — временные леса; план не закрыт, пока флаг не УДАЛЁН, а не только флипнут в default-ON"
metadata:
  node_type: memory
  type: feedback
  originSessionId: eb5d9310-9e1d-4131-828f-22a2d14ad694
  modified: 2026-07-22T17:43:14.560Z
---

Правило перенесено в `.claude/commands/dev/ship.md` (шаг 2) (2026-10-04).

**Why:** dark-launch-флаг легитимен только с полным жизненным циклом
`OFF → замер → default-ON → **удалить флаг и OFF-ветку**`. Если остановиться на флипе
дефолта, OFF-ветка живёт в коде вечно, тест-матрица удваивается, и реестр (уже 18 флагов)
становится памятником нерешённым спорам. «Переключить дефолт» ≠ «убрать флаг».


Связано: [[project-feature-flags-registry]] (реестр FW_*), [[project-f7-g7-flip-ladder]]
(прецедент: 9 флагов флипнуты по одному с замером).
