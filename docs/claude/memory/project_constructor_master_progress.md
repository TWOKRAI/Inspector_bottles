---
name: project-constructor-master-progress
description: "constructor-master: Ф0-Ф2 + трек F + debug-plane В MAIN (merge 2f4e212c); next = Ф3 Supervisor v2 на feat/constructor-f3"
metadata: 
  node_type: memory
  type: project
  originSessionId: 05a29a24-fbc4-4241-8e6f-a55d2a6b5db0
---

Мастер-план `plans/2026-07-06_constructor-master/` в исполнении с 2026-07-06.
**Актуальный handoff: docs/handoffs/2026-07-07_constructor-master-f2-close.md** — читать первым.

- В main ВСЁ (merge 2f4e212c, гейт 3536 passed): Ф0, Ф1 (backend_ctl v2), трек F (god-split), Ф2 целиком (health+breaker+discovery+волны C), debug-plane v1, MCP 25. feat/constructor-f2 можно удалить. Урок MERGE-GATE F: repo-wide modularity не видит разрез god-файлов — мерить max-LOC зоны.
- Состав Ф2 (уже в main): Ф2.1 ctx.health (ADR-PM-010), Ф2.2 честный breaker (ADR-PM-011), Ф2.3 discovery честный (failed_imports + introspect.plugins + счётчик отказов ObservableMixin), волны C (см. ниже), 1.10 UI-tap, 1.11 debug-plane v1. Ф2.6 (JSONL-sink) — опц, не делалась.
- **Debug-plane — главный инструмент отладки**: `drv.debug_session()` включает всё (жесты+команды GUI через перехват двери CommandSender + log_tail всех процессов + state_subscribe) → единый поток `events()` «клик(seq) → команда(seq+1) → лог → state-дельта». MCP 25 инструментов. Дизайн/ревью: plans/2026-07-06_constructor-master/debug-plane-idea.md (v2: ActionBusTap, автоустановка в «рыбу» Ф5).
- Волны C 2.4∥2.5 закрыты (2026-07-07, два агента в worktree параллельно, merge чистый): M-err-1/2 + 31 report_error в 16 файлах, конвенция тега `# no-health: <причина>`, ПОСТОЯННЫЙ AST-гейт `Plugins/tests/test_no_silent_swallows.py` (except-handler обязан: report_error | raise | тег). `SubPluginContext.health` добавлен (log-only fallback + проброс родителя).
- **Next: Ф3 Supervisor v2** на новой ветке `feat/constructor-f3` (/plan-конвенция) (порядок 3.1/3.2/3.5 строго до 3.8, GATE G1 за владельцем). Идея владельца зафиксирована: `plans/2026-07-06_constructor-master/observability-hub-idea.md` (фасад модуля с каналами err/log/stats через слоты ObservableMixin) — триаж на ближайшем гейте, слот Ф5/Ф7.
- Ловушка оркестрации: стойло агента + SendMessage-реанимация = ДВА инстанса в одном дереве (оба писали Ф2.2). Перед реанимацией — вахта на mtime файлов зоны агента; спасает «коммить каждый шаг». [[feedback-agent-resume-ghost]]
- Live-пробники с BackendHarness — только файлом (spawn не работает из stdin); порт свой ≥8770, свой INSPECTOR_PID_FILE; leaf-wise health-дельты приходят отдельными пачками (сборщик не должен рваться по первому полю).
- app.yaml — артефакт лаунчера (активный рецепт), в коммиты не брать. FPS-baseline hardware-gated (Ф7 G.1).
- Baseline sentrux: quality 7174 / modularity 5652.
