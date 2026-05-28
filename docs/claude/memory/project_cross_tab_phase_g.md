---
name: project-cross-tab-phase-g
description: "Phase G (финальная: ActionBus→commands, typed events, удаление AppContext, UX) cross-tab-architecture — PLANNED 2026-05-28 (audit + decomposition G.0–G.6), G.0 DONE (ffeca3ba)"
metadata:
  node_type: memory
  type: project
  originSessionId: f448a3e1-419b-4868-aed1-42b320b47f3c
---

**Phase G — финальная под-фаза** рефакторинга cross-tab-architecture (ветка `refactor/cross-tab-architecture`). Предшественник: [[project-cross-tab-phase-f]] (Phase F DONE).

**СТАТУС (2026-05-28): Phase G IN PROGRESS.** Audit (investigator, Phase A-style) + decomposition G.0–G.6 записаны в `plans/2026-05-27_cross-tab-architecture/phase-g.md`. **G.0 DONE** (`ffeca3ba`), **G.1.1 DONE** (`75a6c41f`). G.1.2 + G.2–G.6 NOT DETAILED (детализируются по очереди — избегаем premature planning большого G.4).

**G.1.1 (DONE `75a6c41f`):** Pipeline scene reload переведён с `getattr(services.topology,"_holder").on_changed` на typed EventBus. Решение: TopologyRepository Protocol намеренно минимален (load/save) → подписка через `services.events.subscribe(TopologyReplaced, ...)`, НЕ через метод repo. Publisher-мост в app.py (composition root): `topology_holder.on_changed(lambda _t: app_services.events.publish(TopologyReplaced(reason="topology_changed")))` — ловит ВСЕ set_topology (включая ActionBus). Handler `_on_topology_replaced` тянет dict из `services.topology.load().to_dict()` (TopologyReplaced несёт только reason). 🔴 silent-failure закрыт. Гранулярные события (ProcessAdded/WireConnected) — G.4. Helper `make_pipeline_services(events=...)` добавлен для wiring-тестов. Caveat: live multiprocess-GUI smoke не делался (qt-mcp недостижим), unit+wiring зелёные.
**Урок коммитов:** commit-msg hook ОТКЛОНЯЕТ эмодзи (🔴 и т.п.) в теле сообщения — писать commit-messages только ASCII-текстом.

**G.1.2 (next, NOT DETAILED):** TopologyBridge IPC sync (app.py:224 `topology_holder.on_changed(topology_bridge.on_topology_changed)`) → `services.events.subscribe(TopologyReplaced)`. После — единственный holder.on_changed-подписчик = publisher-мост → G.3 удаляет holder.

**Why:** Phase G вобрала отложенный F.1 (suppress_legacy_notify), ActionBus→domain commands (#9, Q-F4), typed events вместо broadcast `holder.on_changed`, удаление TopologyHolder + AppContext/extras, 6 пунктов handoff-долга ретро-ревью F, UX-фишки brief §5.

**Ключевая находка audit (хорошие новости):** domain-слой УЖЕ полностью готов — все 14 typed-событий в `domain/events.py` (включая `TopologyReplaced` для broadcast-refresh) и все 14 domain-команд существуют. Phase G = ПОДКЛЮЧЕНИЕ готового domain-слоя, не написание с нуля. Production-подписчиков на `holder.on_changed` всего **2** (app.py:224 IPC-sync через topology_bridge, pipeline/presenter.py:74 scene reload); recipe_handler — writer, не subscriber. CommandDispatcher.dispatch() и EventBus — ноль production-использования (подтверждено).

**Декомпозиция G.0–G.6 (цепочка зависимостей):**
- **G.0 DONE** (`ffeca3ba`) — quick-wins без зависимостей: G.0.1 public `RecipeEngine.deactivate()` (framework) + manager на него; G.0.2 удалён dead `AdministrationSection` (composite section.py — нигде не инстанцировался, заменён фабриками `settings/_sections.py` с `(services, auth_ctx)`); G.0.3 16 «TODO Phase F»→Phase G(G.2/G.4/G.5)/by-design; G.0.4 bindings = Q4 Phase D resolved в RuntimeDeps (Q-F1=B). Verify: 2025 passed/3 skipped, sentrux 7136 (+1), 9/9.
- **G.1 (фундамент, M-L)** — typed events в production: подписать PipelinePresenter + TopologyBridge на EventBus; typed-метод в TopologyRepository Protocol. 🔴 ЗАКРЫВАЕТ silent-failure risk `pipeline/presenter.py:72` `getattr(services.topology,"_holder",None)` (при удалении holder вернёт None молча → scene reload сломается без ошибки). Зависит от G.0.
- **G.2 (M, независим)** — RegistersBackend Protocol alignment: 3 `getattr(services.registers,"_rm")` (pipeline/presenter.py:108, inspector_panel.py:513, plugins/presenter.py:48). Пробел: Protocol адресует `(process,plugin_index)`, legacy — по register_name (flat).
- **G.3 (M)** — holder removal: активировать suppress_legacy_notify (F.1) / редуцировать-удалить TopologyHolder. Зависит от G.1.
- **G.4 (L, риск HIGH)** — ActionBus→domain commands: 11 call-sites `bus.execute/undo/redo` (7 файлов) + undo-менеджер поверх domain (snapshot-based сохраняет текущую семантику) + маппинг register_name→(process,plugin_index) для FIELD_SET. NODE_MOVE/ROLE_UPDATE — не topology-domain. Зависит G.1+G.2+G.3. Детализируется ОТДЕЛЬНО (возможно свой subplan), сопоставимо со всей Phase E. Подсистема `frontend/actions/` (builder V2ActionBuilder, bus_factory, middleware, handlers).
- **G.5 (M)** — AppContext removal: отвязать TabFactory (ctx.auth для permissions), administration, interface (ctx.process), app_services_factory (peek-bridge) от ctx; удалить AppContext + `_deprecated_extras`. Зависит G.4.
- **G.6 (S-M)** — UX: auto-reveal, real-time validation (в Project.apply), cross-tab linking (RecipeActivated event→Services tab), diff-view (Topology.diff). Зависит G.1.

**How to apply (следующий заход):**
- Перед стартом G.x: прочитать `plans/2026-05-27_cross-tab-architecture/phase-g.md` (полный audit + decomposition), `grep` актуальных call-sites (память может устареть).
- Владелец выбрал заходить с G.0 quick-wins (сделано). Дальше — G.1 (фундамент) ИЛИ G.2 (независим). Решение по очередности — за владельцем.
- Big-bang запрещён (brief §8): строгая цепочка G.1→G.3→G.4→G.5. G.4 — отдельный audit-like заход.
- Тест-стратегия: builder/Fake, НЕ `MagicMock(spec=AppContext)` (см. [[feedback-qt-mcp-smoke-verification]]).

**Артефакты:** subplan `plans/2026-05-27_cross-tab-architecture/phase-g.md`; master `plan.md` (G IN PROGRESS); G.0 commit `ffeca3ba`.
