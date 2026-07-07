---
name: project-constructor-master-progress
description: "constructor-master: Ф0-Ф1+трек F в main; Ф2.1/2.2 закрыты, debug-plane v1 готова; next = Ф2.3 и волны C"
metadata: 
  node_type: memory
  type: project
  originSessionId: 05a29a24-fbc4-4241-8e6f-a55d2a6b5db0
---

Мастер-план `plans/2026-07-06_constructor-master/` в исполнении с 2026-07-06.
**Актуальный handoff: docs/handoffs/2026-07-07_constructor-master-f2-debugplane.md** — читать первым.

- В main: Ф0, Ф1 (backend_ctl v2 целиком, вкл. 1.6 verify-probe с багфиксом set_register), трек F (god-split, MERGE-GATE F закрыт владельцем; урок: repo-wide modularity не видит разрез god-файлов — для таких гейтов мерить max-LOC зоны).
- На `feat/constructor-f2` (HEAD abfea5a9): Ф2.1 ctx.health (ADR-PM-010), Ф2.2 честный breaker (ADR-PM-011, live-acceptance 5×report→open+degraded), 1.10 UI-tap, 1.11 debug-plane v1.
- **Debug-plane — главный инструмент отладки**: `drv.debug_session()` включает всё (жесты+команды GUI через перехват двери CommandSender + log_tail всех процессов + state_subscribe) → единый поток `events()` «клик(seq) → команда(seq+1) → лог → state-дельта». MCP 24 инструмента. Дизайн/ревью: plans/2026-07-06_constructor-master/debug-plane-idea.md (v2: ActionBusTap, автоустановка в «рыбу» Ф5).
- **Next: Ф2.3** (discovery WARNING + failed-list, S) → волны C 2.4∥2.5 (~30 сайтов `ctx.health.report_error` в Plugins/ — one-liner, breaker приезжает бесплатно) → Ф3 (порядок 3.1/3.2/3.5 строго до 3.8).
- Ловушка оркестрации: стойло агента + SendMessage-реанимация = ДВА инстанса в одном дереве (оба писали Ф2.2). Перед реанимацией — вахта на mtime файлов зоны агента; спасает «коммить каждый шаг». [[feedback-agent-resume-ghost]]
- Live-пробники с BackendHarness — только файлом (spawn не работает из stdin); порт свой ≥8770, свой INSPECTOR_PID_FILE; leaf-wise health-дельты приходят отдельными пачками (сборщик не должен рваться по первому полю).
- app.yaml — артефакт лаунчера (активный рецепт), в коммиты не брать. FPS-baseline hardware-gated (Ф7 G.1).
- Baseline sentrux: quality 7174 / modularity 5652.
