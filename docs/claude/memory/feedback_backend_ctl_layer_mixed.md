---
name: feedback_backend_ctl_layer_mixed
description: backend_ctl-коммиты используют Layer:mixed (не tools) — commit-hook не знает значения tools
metadata:
  type: feedback
---

План backend-ctl-debug-console помечает задачи `**Layer:** tools`, но commit-msg hook (`scripts/validate_commit`) отклоняет `Layer: tools` — allowlist: docs/framework/infra/mixed/plugins/prototype/scripts/services/tests.

**Why:** backend_ctl — dev-инструмент вне слоёв framework/Services/Plugins; в whitelist «tools» нет. Прецедент прошлых backend_ctl-коммитов — `Layer: mixed` (11×) или `framework` (4×).

**How to apply:** для backend_ctl-коммитов (код драйвера + его тесты) ставить `Layer: mixed`, игнорируя «tools» из плана. Если владелец захочет — можно добавить `tools` в allowlist `scripts/validate_commit/validate_commit.py`, но это отдельное решение по конвенции.
