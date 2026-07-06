---
name: project-constructor-master-progress
description: "constructor-master исполняется с 2026-07-06; Ф0 сделан, G0 ждёт per-item решений владельца"
metadata: 
  node_type: memory
  type: project
  originSessionId: 05a29a24-fbc4-4241-8e6f-a55d2a6b5db0
---

Мастер-план `plans/2026-07-06_constructor-master/` в исполнении с 2026-07-06, ветка `fix/constructor-f0`.

- Ф0.2-0.4, 0.6 — DONE; Ф0.5 (GATE G0) — таблица вердиктов в plan.md ГОТОВА, ждёт галочек владельца (единственный блокер закрытия Ф0)
- Baseline: sentrux quality 7174 / modularity 5652; pytest fw 3401 + proto 2820, 0 красных
- FPS обоих живых рецептов hardware-gated (нет телефона/Hikvision); повтор на железе или Ф7 G.1
- Env-дрейф .venv дважды: watchdog (поставлен) и `[ml]` extras (PyTorch НЕ установлен — решение владельца)
- Находка: BACKEND_CTL=1 не headless (gui спавнит LoginDialog), shutdown-hang 8+ мин → входы Ф1.3/Ф3
- Идея app_module «рыба» — [[project-arch-refactor]], дизайн в plans/2026-07-06_constructor-master/app-template-idea.md (уровни 0-3, prototype_2 отвергнут)
- Стратегия делегирования: Ф0 сам; с Ф1 — developer (sonnet)/teamlead (opus) на M-задачи, ревью на мне
