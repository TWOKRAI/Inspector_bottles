---
name: project_telemetry_coherence_remediation
description: Ревью телеметрии (Fable 24→42/60) + план telemetry-coherence-remediation; Фаза 1 закрыта, дальше Task 1.4 → Фаза 4 GUI
metadata:
  type: project
---

Ревью двух планов телеметрии ([[project_telemetry_self_publish]], [[project_gui_telemetry_read_model]])
пайплайном Sonnet-флот → Opus кросс-срез → Fable (вердикт **24→42/60**) вскрыл долг **когерентности
частотного контракта**. Оформлен в `plans/telemetry-coherence-remediation.md` (11 задач, 3 фазы).

**Ветка:** `feat/telemetry-coherence` (от `feat/telemetry-publish-control`). Handoff:
`docs/sessions/2026-07-17-handoff-telemetry-coherence.md`.

**Фаза 1 ЗАКРЫТА** (blockers Фазы 4 GUI), заревьюена, зелёная (framework 4909 passed):
- Task 1.1 — delta-семантика `mode: merge|replace`, оживил мёртвый `update_rule`/`remove_rule`.
- Task 1.2 — `publish.tick_sec` (тик в контракте вместо захардкоженного heartbeat 5с); **ADR-PM-016**
  (один heartbeat-воркер `min(interval, tick)`, liveness-сообщение по time-gate — частота heartbeat к
  ProcessMonitor НЕ меняется).
- Task 1.3 — три плоскости частоты согласованы: heartbeat-tick → publisher-gate (**авторитет частоты**)
  → центральный троттл (**только IPC-страховка**, дефолт мягкий 0.05с). `capped_by_throttle`-флаг вместо
  auto-relax. **ADR-PM-017**.

**Дальше (рекомендация):** **Task 1.4** (cap-детекция на адресном per-process пути — **БЛОКЕР per-process
крутилки частоты в Фазе 4 GUI**; broadcast-путь уже покрыт) → **Фаза 4 GUI** плана telemetry-publish-control
(крутилки/тумблеры). Приоритет продукт>движок ([[project_priority_product_over_engine]]) → GUI важнее
Фаз 2/3 remediation (когерентность/простота — фоновый долг).

**Урок:** per-subsystem ревью НЕ видит межподсистемных стыков — Opus/Fable кросс-срез поверх флота нашёл
HIGH (throttle full-apply сносил все правила) и design-critical (heartbeat=третья неуправляемая плоскость
частоты), которые 5 подсистемных ревьюеров пропустили. Ценность многоуровневого ревью — в разных линзах,
не в повторении.
