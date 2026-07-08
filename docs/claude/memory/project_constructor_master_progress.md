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
- **Next: Ф3 Supervisor v2** — ветка `feat/constructor-f3` УЖЕ СОЗДАНА (2026-07-08, HEAD aa0fd56f docs-коммит obs-hub; main НЕ содержит его). Порядок 3.1/3.2/3.5 строго до 3.8, GATE G1 за владельцем.
- **Ф3.1 routing-epoch ЗАКРЫТА (2026-07-08, teamlead-Opus, 8 коммитов 2e7c6d74..dce270fe, ADR-PMM-010)**: гибрид A (switch: идемпотентный `routing.refresh` epoch+incarnations полным снимком, выживший сбрасывает стейл-очереди → hub-relay Ф1.7) + B (restart: `reuse_queues=True`, Queue-identity стабильна, hot-path без деградации). Причина гибрида: mp.Queue не пиклится вне spawn; data-plane на тех же очередях. Live RED→GREEN ✓ (`test_routing_epoch_live.py`, switch/restart на РАЗНЫХ портах 8778/8779 — switch необратимо пачкает relay-счётчик соседа). Framework 3558 passed. Откат: FW_ROUTING_REFRESH=0 / restart_reuse_queues=false. **Урок live-тестов**: FullReplacePlanner сносит ВСЕ non-protected при topology.apply → «выжившим» отправителем в live может быть только protected-процесс (`devices`; gui вырезан strip_gui). Next: Ф3.2 self-reported ready (∥ возможны 3.3/3.4).
- **Дыра мастер-плана**: задачи 5.11–5.13 (skeleton app_module) упомянуты в plan.md:194 как предусловие ObservabilityHub, но СТРОК В ТАБЛИЦЕ Ф5 НЕТ — app-template-idea.md не транслирован в задачи. Добавить при триаже G1.
- **ObservabilityHub закреплён в плане** (2026-07-08, коммит aa0fd56f): задачи Ф5.15 (core в channel_routing_module) / 5.16 (wiring в «рыбе», пилот worker+сервис, дренаж heartbeat, per-process hub с module-тегом) / 5.17 опц (разделение hub↔health) + cross-ref Ф7 G.4 (hot-path adoption под флагом/drop-counter, после seqlock). Идея-док observability-hub-idea.md → статус «закреплена». Триаж на G1.
- Ловушка оркестрации: стойло агента + SendMessage-реанимация = ДВА инстанса в одном дереве (оба писали Ф2.2). Перед реанимацией — вахта на mtime файлов зоны агента; спасает «коммить каждый шаг». [[feedback-agent-resume-ghost]]
- Live-пробники с BackendHarness — только файлом (spawn не работает из stdin); порт свой ≥8770, свой INSPECTOR_PID_FILE; leaf-wise health-дельты приходят отдельными пачками (сборщик не должен рваться по первому полю).
- app.yaml — артефакт лаунчера (активный рецепт), в коммиты не брать. FPS-baseline hardware-gated (Ф7 G.1).
- Baseline sentrux: quality 7174 / modularity 5652.
