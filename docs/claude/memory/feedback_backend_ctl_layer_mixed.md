---
name: feedback_backend_ctl_layer_mixed
description: backend_ctl-коммиты используют Layer:mixed (не tools) — commit-hook не знает значения tools
metadata:
  type: feedback
---

Правило перенесено в `docs/claude/COMMIT_GUIDE.md` и `.claude/COMMIT_GUIDE.md` (2026-10-04).

**Why:** backend_ctl — dev-инструмент вне слоёв framework/Services/Plugins; в whitelist «tools» нет. Прецедент прошлых backend_ctl-коммитов — `Layer: mixed` (11×) или `framework` (4×).
