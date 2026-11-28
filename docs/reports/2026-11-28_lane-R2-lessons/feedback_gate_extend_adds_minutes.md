---
name: feedback-gate-extend-adds-minutes
description: "machine_gate.sh extend N прибавляет N минут к остатку окна, а не ставит срок «ещё N» / extend adds to the remaining time; a keep-alive before every step inflates the window by hours"
metadata:
  type: feedback
  module: [scripts]
  mechanism: [test-infra, coordination]
---

**Trap.** A runner script called `extend <session> 30` before each step, as a keep-alive. `extend` adds minutes to what is left (`plan_extend`: `total=$((base + MINUTES))`), so the window grew with every step.

**Measured (2026-11-28, R2-S1d pre-merge run).** Window granted at 15:18 until ~16:33; after seven calls the gate showed `until ~20:03`. A neighbour lane read it and asked for a slot inside a window that in fact needed under an hour.

**How to apply.** Request the window from the measured run time once. Extend only when the remaining time is really short, and by the missing amount. Never put `extend` in a loop or before every step.

**Trigger.** Writing or copying a runner script that waits for a gate window.
