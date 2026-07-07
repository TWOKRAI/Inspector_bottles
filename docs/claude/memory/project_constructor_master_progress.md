---
name: project-constructor-master-progress
description: "constructor-master исполняется с 2026-07-06; Ф0 сделан, G0 ждёт per-item решений владельца"
metadata: 
  node_type: memory
  type: project
  originSessionId: 05a29a24-fbc4-4241-8e6f-a55d2a6b5db0
---

Мастер-план `plans/2026-07-06_constructor-master/` в исполнении с 2026-07-06, ветка `fix/constructor-f0`.

- Ф0 ЗАКРЫТ (merge f156589b); Ф1: 1.1/1.1b/1.2/1.3 приняты; трек F: F.1-F.4 приняты (presenter 1860→595). In-flight 1.4/1.5 и F.5 — см. docs/handoffs/2026-07-07_constructor-master-f1-trackF.md
- Baseline: sentrux quality 7174 / modularity 5652; pytest fw 3401 + proto 2820, 0 красных
- FPS обоих живых рецептов hardware-gated (нет телефона/Hikvision); повтор на железе или Ф7 G.1
- Env-дрейф .venv дважды: watchdog (поставлен) и `[ml]` extras (PyTorch НЕ установлен — решение владельца)
- Находка: BACKEND_CTL=1 не headless (gui спавнит LoginDialog), shutdown-hang 8+ мин → входы Ф1.3/Ф3
- Идея app_module «рыба» — [[project-arch-refactor]], дизайн в plans/2026-07-06_constructor-master/app-template-idea.md (уровни 0-3, prototype_2 отвергнут)
- Стратегия делегирования: Ф0 сам; с Ф1 — developer (sonnet)/teamlead (opus) на M-задачи, ревью на мне
