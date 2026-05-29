# Phase G — ActionBus→domain commands, typed events, удаление AppContext + UX

- **Slug:** cross-tab-architecture / phase-g
- **Дата:** 2026-05-28
- **Статус:** G.0 DONE (`ffeca3ba`), G.1 DONE (`75a6c41f`+`64bd2cd1`), G.2 DONE (`c30cc91f`, RuntimeDeps), G.3 DONE (TopologyHolder removed, store-publishes, reviewer APPROVED); **G.4 IN PROGRESS** (Wave 5: **G.4.1 DONE** `e5aaa862`; **G.4.2 DONE** `dedb4a1f`+`05b1d3f7`, reviewer APPROVED; **G.4.2b DONE** (2026-05-29, reviewer APPROVED — display=binding + рендеринг display-боксов на scene, fan-out/fan-in, ADR DOM-001); **G.4.3 DONE** (2026-05-29, `5dc97751` + nit, Y1, reviewer **APPROVED** — FIELD_SET → SetPluginConfig в Pipeline Inspector + rm-sync listener + Plugins dead-ветка убрана; 2048 passed / sentrux 9-9 / quality 7133); **G.4.4 DONE** (2026-05-29, `171f1d8f`, verify ✓ 2055 passed / sentrux 9-9 / quality 7134, reviewer **APPROVED** — scope переопределён reality-аудитом: domain undo/redo UX + единая шина undo + fix dual-undo bug #2 + phantom-cleanup; удаление `frontend/actions/`/RECIPE_APPLY live отложены как big-bang); **G.5 DETAILED** (2026-05-29, Wave 6: G.5.1–G.5.3 после reality-аудита composition root — AppContext = scratch-extras + carrier + accessor-фасад; InterfaceSection мёртв в prod; `process._app_context` write-only); **G.5.1 DONE** (`63e303b6`, build_app_services → AppServicesDeps); **G.5.2 DONE** (`a4691aaf`, TabFactory(app_services,auth_ctx,runtime) + InterfaceSection request_ui_restart callback — мёртвая фича UI-restart восстановлена); **G.5.3 DONE** (`ea8f0f8d`, AppContext + _deprecated_extras удалены, composition root на локалах + AppServicesDeps/RuntimeDeps; 2012 passed / sentrux 9-9 / quality **7135** +2 / import_edges −15 / −919 LOC). **G.5 ЗАВЕРШЁН — reviewer APPROVED + live boot-smoke PASS** (qt-mcp: MainWindow 1577×941 + QTabWidget отрендерены в живом multiprocess-GUI; 0 трейсбэков). **G.6 (UX) DETAILED** (Wave 7, 2026-05-29, reality-аудит investigator: 3/4 премис brief §5 ложны): G.6.1 auto-reveal + G.6.2 validation-feedback + G.6.3 selection-persist + G.6.4 diff-view (safe trio+diff); G.6.5 RECIPE_APPLY live-миграция (HIGH/IPC) → G.6.6 cross-tab linking; granular scene-updates → deferred post-merge.
- **Ветка:** `refactor/cross-tab-architecture` (та же, что A–F)

## Назначение

Детализированный subplan Phase G master-плана `cross-tab-architecture`.
Phase G — финальная и крупнейшая под-фаза (~35-45 production-файлов). Она вбирает:
отложенный F.1 (suppress_legacy_notify), ActionBus→domain commands (#9 Phase F, Q-F4),
typed events вместо broadcast `holder.on_changed`, полное удаление TopologyHolder + AppContext/extras,
6 пунктов handoff-долга из ретро-ревью Phase F и UX-фишки из brief §5.

**Премиса (хорошие новости из audit):** domain-слой уже ПОЛНОСТЬЮ готов —
все 14 typed-событий в `domain/events.py` (включая `TopologyReplaced` для broadcast-refresh)
и все 14 domain-команд существуют. Phase G — это **подключение** готового domain-слоя,
а не написание с нуля.

## Источники истины

| Документ | Что содержит |
|---|---|
| [`plan.md`](plan.md) | master-плана, статусы фаз A–G |
| [`phase-f-legacy-removal.md`](phase-f-legacy-removal.md) | Phase F + Phase G handoff-долг (ретро-ревью Opus, ~стр.808-816), Q-F1..Q-F4 |
| [`docs/refactors/2026-05_cross_tab_architecture.md`](../../docs/refactors/2026-05_cross_tab_architecture.md) | brief: §4 target, §5 Phase G, §7 success criteria, §8 антипаттерны (запрет big-bang) |
| Раздел «Audit (Phase A-style)» ниже | факты investigator-аудита 2026-05-28 (file:line) |

> **Правило (из master-плана):** под-фаза G.x не детализируется до approval'а предыдущей.
> Перед стартом каждой G.x — `grep` актуального состояния call-sites (память может устареть).

---

## Audit (Phase A-style) — факты на 2026-05-28

Investigator read-only audit (ретро-ревью Phase F прямо требовал «audit как Phase A» для ActionBus).

### ActionBus → domain commands (риск HIGH, → G.4)
- Подсистема `frontend/actions/`: `action_types.py` (8 констант), `builder.py` (`V2ActionBuilder`,
  8 static-методов; topology-мутации хранят полный topology dict в `forward_patch`/`backward_patch`
  → undo = `set_topology(backward_patch)`), `bus_factory.py`, `middleware/` (PreAuthGuard, AuditMiddleware),
  `handlers/` (TopologyMutationHandler, RecipeApplyHandler, FieldSetHandler, NodeMoveHandler, RoleUpdateHandler).
- **11 production call-sites** `bus.execute/undo/redo` в 7 файлах: `pipeline/presenter.py` (128 field_set,
  364 process_add, 401 process_remove, 438 wire_add, 606 node_move), `pipeline/tab.py` (272 undo, 276 redo),
  `plugins/_sections.py:259`, `settings/system/presenter.py:165`, `settings/administration/roles_panel.py:206`,
  `services/tab.py:59-62`. + 5 косвенных `getattr(services.commands, "action_bus")`.
- **`CommandDispatcher.dispatch()` в production НЕ используется** (только тесты); EventBus — ноль production-подписчиков. Подтверждено.
- Дельта: 14 domain-команд есть; нужен undo-менеджер поверх domain (snapshot-based или reverse-command)
  + маппинг `register_name → (process, plugin_index)` для FIELD_SET. `NODE_MOVE`/`ROLE_UPDATE` — не topology-domain (могут остаться отдельно).

### holder → typed events (фундамент, → G.1/G.3)
- **2 production-подписчика** `holder.on_changed`: `app.py:224` (topology_bridge IPC sync), `pipeline/presenter.py:74`
  (scene reload — полный refresh `model.from_topology_dict` + `scene.load_from_data`). `recipe_handler` — это **writer** (`set_topology`), не подписчик.
- 🔴 `pipeline/presenter.py:72` — `holder = getattr(services.topology, "_holder", None)` — **silent-failure risk**:
  при удалении holder вернёт None молча, scene reload сломается без ошибки. Заменить на typed-метод TopologyRepository Protocol ДО удаления holder.
- `domain/events.py`: 14 событий готовы (`ProcessAdded/Removed/Renamed`, `PluginInserted/Removed/ConfigChanged`,
  `WireConnected/Disconnected`, `DisplayBound/Unbound`, `TargetProcessAssigned`, `RecipeActivated/Deactivated`, `TopologyReplaced`).
- `suppress_legacy_notify()` реализован (`topology_repository.py:62-85`, флаг `topology_holder.py:27`), НЕ активирован. Это отложенный F.1.

### 6 пунктов handoff-долга (текущее состояние)
1. **RegistersBackend Protocol** (→ G.2): 3 `getattr(services.registers, "_rm")` — `pipeline/presenter.py:108`
   (`get_register` для old_value), `pipeline/inspector/inspector_panel.py:513` (`get_fields`), `plugins/presenter.py:48`.
   Пробел: Protocol адресуется `(process, plugin_index)`, legacy — по register_name (flat).
2. **RecipeEngine.deactivate()** (→ G.0): `recipes/manager.py:228` пишет `self._engine._active_name = None` напрямую
   в framework `recipe_engine.py`. У framework есть `set_active`/`get_active`, нет public `deactivate()`.
3. **administration/section.py** (→ G.0): композит `AdministrationSection` (ctx + прямая Qt-signal подписка) —
   **dead code**: нигде не инстанцируется (settings tab использует фабрики `_sections.py` с `(services, auth_ctx)`).
   Живые панели легитимно получают rich `auth_ctx` для мутаций (by-design, не AuthFacade).
4. **16 TODO Phase G** + 2 by-design (Q-F1=B runtime-deps) в 7 файлах (→ G.0 переквалификация). Классификация — в G.0.3.
5. **AppContext removal readiness** (→ G.5): потребители `ctx` после Phase F — `tab_factory.py` (ctx.auth для permissions,
   RuntimeDeps-сборка), `administration/section.py` (dead), `interface/section.py` (ctx.process для UI restart),
   `app_services_factory.py` (peek-bridge ctx→AppServices). Удаление — после миграции всех (G.5).
6. **GuiStateBindings → AppServices** (Q4 Phase D) — **уже решён через Q-F1=B**: bindings живёт в `RuntimeDeps.bindings`,
   не в AppServices (это runtime-объект). Отдельной работы нет; `ctx.extras["bindings"]` уйдёт вместе с ctx (G.5).

### UX-фишки (brief §5, → G.6)
- auto-reveal новых нод (сейчас hardcoded позиция → `ProcessAdded` event + centerOn), real-time validation
  (встроить в `Project.apply()`), cross-tab linking (`RecipeActivated` event → Services tab highlight),
  diff-view (`Topology.diff` из to_dict; `RecipeEngine.is_dirty()` уже есть). Все упрощаются после typed events/commands.

---

## Декомпозиция под-фаз и цепочка зависимостей

```
G.0 quick-wins ──┐
G.2 Registers  ──┤ (независимы)
G.1 typed events (ФУНДАМЕНТ) ──┬──> G.3 holder removal ──┐
                               │                          ├──> G.4 ActionBus→commands ──> G.5 AppContext removal
                               └──> G.6 UX ───────────────┘
```

| Под-фаза | Описание | Scope | Зависит от | Статус |
|---|---|---|---|---|
| **G.0** | Quick-wins: RecipeEngine.deactivate(), удаление dead AdministrationSection, переквалификация 16 TODO, документирование bindings/RuntimeDeps | S (~10 файлов, мелкие) | — | **DONE** (`ffeca3ba`) |
| **G.1** | Typed events в production: PipelinePresenter + TopologyBridge на EventBus (закрывает 🔴 `getattr(_holder)`) | M-L (5-8) | G.0 | **DONE** (G.1.1 `75a6c41f` + G.1.2) |
| **G.2** | RegistersManager → RuntimeDeps (Q-F1=B): убрать 3 `_rm` getattr. **NB:** не «расширить Protocol» (domain не может FieldInfo) — provide RegistersManager как runtime-dep | M (8 prod + 3 test) | — | **DONE** (reviewer APPROVED) |
| **G.3** | TopologyHolder removal → TopologyRepositoryStore (Design 2, store-publishes TopologyReplaced). suppress_legacy_notify оказался мёртв → удалён | **L (28 файлов)** | G.1 | **DONE** (reviewer APPROVED) |
| **G.4** | ActionBus→domain commands: 11 call-sites + undo/redo поверх domain + register→domain mapping | **L (15-20)** | G.1, G.2, G.3 | **DETAILED** (Wave 5: G.4.1–G.4.4). G.4.1 foundation в работе |
| **G.5** | AppContext removal: отвязать TabFactory/sections/factory от ctx, удалить AppContext + `_deprecated_extras` | M (5-7) | G.4 | **DETAILED** (Wave 6: G.5.1–G.5.3) |
| **G.6** | UX: auto-reveal, real-time validation, cross-tab linking, diff-view | S-M каждая | G.1 | NOT DETAILED |

**Антипаттерн brief §8 (запрет big-bang):** G.4 — самый рискованный, сопоставим со всей Phase E.
Детализируется только когда G.1–G.3 завершены (тогда станет ясна реальная форма undo-менеджера).
Возможно выделение G.4 в отдельный subplan при детализации.

---

## Wave 1 — G.0 (quick-wins, низкий риск, без зависимостей)

> Тест-стратегия (acceptance каждого G.0.x): builder/Fake, **НЕ** `MagicMock(spec=AppContext)` (память `feedback_qt_mcp_smoke_verification`).

---

### Task G.0.1 — RecipeEngine.deactivate() public метод (framework + prototype)

**Level:** Middle (developer, Sonnet)
**Assignee:** developer / director-direct
**Goal:** Добавить public `deactivate()` на framework `RecipeEngine`, устранив прямой доступ
`self._engine._active_name = None` в prototype `RecipeManager.deactivate()`.
**Context:** Ретро-ревью Phase F п.3 — F.4 сдвинул приватный доступ в `RecipeManager.deactivate()`,
но не устранил (manager.py:228 пишет в framework private `_active_name`). У framework engine есть
`set_active()`/`get_active()`, симметричного `deactivate()` нет.

**Files:**
- `multiprocess_framework/modules/state_store_module/recipes/recipe_engine.py` — добавить public
  `deactivate()` (сброс `_active_name = None`, `_loaded_snapshot = None`, `_loaded_paths = None` —
  зеркало active-reset блока в `delete()` стр.289-292; обновить `state.recipes.active` если engine это делает)
- `multiprocess_framework/modules/state_store_module/recipes/tests/` — тест на `deactivate()` (idempotent, is_dirty после)
- `multiprocess_prototype/recipes/manager.py:228` — `self._engine._active_name = None` → `self._engine.deactivate()`
- framework module README/STATUS — если фиксируют public API recipe_engine

**Steps:**
1. Pre-investigation: прочитать `recipe_engine.py` целиком вокруг `set_active`/`delete`/`is_dirty` —
   понять полный набор полей, которые сбрасывает active-reset.
2. Добавить `deactivate()` (idempotent), симметрично `set_active`.
3. Заменить прямой доступ в `manager.py:228`. Проверить, что `_update_active_in_state(None)` остаётся.
4. Тест framework recipe_engine + prototype recipe тесты.

**Acceptance criteria:**
- [ ] `grep -rn "_engine\._active_name\|\._active_name =" multiprocess_prototype/recipes/` → 0
- [ ] `RecipeEngine.deactivate()` существует, покрыт тестом (idempotent)
- [ ] `python -m pytest multiprocess_framework/modules/state_store_module/recipes/ multiprocess_prototype/recipes/ multiprocess_prototype/adapters/` зелёные
- [ ] Commit с `Refs: plans/2026-05-27_cross-tab-architecture/phase-g.md`, `Layer: framework` (или mixed)

**Out of scope:** RecipeStore rich API (Phase F закрыто); recipe YAML формат.
**Edge cases:** deactivate когда нет активного — no-op (state → None). Не сломать `is_dirty()` после deactivate.
**Module contract:** public-api-change (additive, framework recipe_engine).

---

### Task G.0.2 — Удалить dead AdministrationSection (composite)

**Level:** Middle (developer, Sonnet) — с осторожной верификацией dead-ности
**Assignee:** developer / director-direct
**Goal:** Удалить неиспользуемый композит `AdministrationSection` (section.py) — единственный остаток
с прямой Qt-signal подпиской и `ctx`-зависимостью в administration.
**Context:** Ретро-ревью п.4. Audit: `AdministrationSection` нигде не инстанцируется (grep `AdministrationSection(`
= только class def). Settings tab строит секции admin через фабрики `_sections.py` (`_users_factory` и т.д.)
с сигнатурой `(services, auth_ctx)`. Композит — устаревший подход, заменён пер-секционными фабриками.
Прямая подписка `access_context_changed.connect` и `ctx.auth`/`ctx.action_bus()` живут ТОЛЬКО в этом dead-файле.

**Files:**
- `multiprocess_prototype/frontend/widgets/tabs/settings/administration/section.py` — **удалить файл**
- `multiprocess_prototype/frontend/widgets/tabs/settings/administration/__init__.py` — убрать импорт/экспорт `AdministrationSection`
- `administration/sessions_panel.py:9`, `audit_log_panel.py:8` — docstring «Используется ... в AdministrationSection» → «... через фабрики `_sections.py`»

**Steps:**
1. **Верификация dead-ности (критично перед удалением):** broad grep `AdministrationSection` по ВСЕМУ репо
   (не только prototype) + проверить нет ли string-based/registry ссылки, нет ли теста на section.py.
2. Если подтверждено dead → удалить файл + экспорт + поправить docstring-ссылки.
3. Если НЕ dead (нашёлся потребитель) → эскалация: переквалифицировать в полную миграцию ctx→services
   (тогда это уже не G.0, а отдельная задача с auth-context dependency).
4. Прогнать settings/administration тесты.

**Acceptance criteria:**
- [ ] `grep -rn "AdministrationSection" .` → 0 (или только в git-истории)
- [ ] `import` из `administration` не ломается (экспорт убран чисто)
- [ ] `python -m pytest .../settings/` зелёные
- [ ] Commit с Refs, `Layer: prototype`

**Out of scope:** `getattr(services.commands, "action_bus")` в `_roles_factory` (это G.4 ActionBus); миграция auth_ctx панелей (by-design).
**Edge cases:** если AdministrationSection окажется живым → НЕ удалять, эскалировать (см. Step 3).
**Module contract:** public-api-change (удаление публичного класса из administration `__init__`).

---

### Task G.0.3 — Переквалификация 16 TODO Phase F → Phase G / by-design

**Level:** Junior+ (developer, Sonnet) — comment-only, judgment по классификации из audit
**Assignee:** developer / director-direct
**Goal:** Привести 18 «TODO Phase F» в production к корректной маркировке: 16 → «TODO Phase G (G.x)»,
2 → «By design (Q-F1=B): runtime layer, не AppServices».
**Context:** Ретро-ревью п.5 — TODO неоднородны. Audit-классификация (file:line → категория):

| Файл:строка | Категория |
|---|---|
| `pipeline/presenter.py:65,69` | Phase G (G.4 ActionBus / G.1 events) |
| `pipeline/presenter.py:104` | Phase G (G.2 Registers) |
| `pipeline/presenter.py:358` | Phase G (G.4) |
| `pipeline/presenter.py:852` | **By design** (Q-F1=B process_manager_proxy) |
| `pipeline/tab.py:106,270,274` | Phase G (G.4) |
| `pipeline/inspector/inspector_panel.py:94,524` | Phase G (G.4/G.1) |
| `pipeline/inspector/inspector_panel.py:510` | Phase G (G.2) |
| `plugins/_sections.py:213` | Phase G (G.4 form_context) |
| `plugins/_sections.py:235` | Phase G (G.4) |
| `plugins/presenter.py:46` | Phase G (G.2) |
| `plugins/tab.py:100` | Phase G (G.4) |
| `services/tab.py:50` | Phase G (G.4) |
| `processes/presenter.py:52` | **By design** (Q-F1=B command_sender/topology_bridge) |
| `settings/_sections.py:109-110` | Phase G (G.4) |

**Steps:**
1. Перед стартом: `grep -rn "TODO Phase F" multiprocess_prototype/` — сверить с таблицей (актуализировать строки).
2. Для каждого: «Phase G» → пометить целевой под-фазой (G.1/G.2/G.4). «By design» → переформулировать
   как `# By design (Q-F1=B): runtime layer, не AppServices` (убрать слово TODO).
3. Проверить: после правок `grep "TODO Phase F"` = 0.

**Acceptance criteria:**
- [ ] `grep -rn "TODO Phase F" multiprocess_prototype/` → 0
- [ ] By-design (2 шт.) не содержат слова TODO; Phase G (16 шт.) указывают под-фазу
- [ ] Никаких логических изменений (только комментарии); тесты не затронуты
- [ ] Commit с Refs, `Layer: prototype`

**Out of scope:** реализация самих TODO (это G.1/G.2/G.4).
**Edge cases:** строки могли сдвинуться после G.0.1/G.0.2 — делать G.0.3 последним в волне или сверять grep.
**Module contract:** n/a (комментарии).

---

### Task G.0.4 — Документировать решённость bindings через RuntimeDeps

**Level:** Junior (docs) — подтверждение, не код
**Assignee:** director-direct / docs
**Goal:** Зафиксировать, что Q4 Phase D (GuiStateBindings → AppServices) **закрыт** через Q-F1=B:
bindings — runtime-объект, живёт в `RuntimeDeps.bindings`, не в AppServices. Остаток (`ctx.extras["bindings"]`)
уходит вместе с ctx в G.5.
**Context:** Audit п.6 — отдельной работы нет, но в нескольких местах (plan, adapters README, runtime_deps)
bindings числится как Phase G долг. Снять неоднозначность.

**Files:**
- `multiprocess_prototype/frontend/runtime_deps.py` — docstring `bindings`: пометка «Q4 Phase D resolved here (Q-F1=B)»
- этот phase-g.md (уже зафиксировано в audit п.6 и G.5)
- (опц.) adapters README / migration guide — если ссылаются на bindings как open Phase G

**Acceptance criteria:**
- [ ] `runtime_deps.py` docstring уточняет статус bindings
- [ ] Нет открытых TODO «bindings → AppServices» (либо переквалифицированы в G.0.3)
- [ ] Commit с Refs (можно объединить с docs-коммитом G.0)

**Out of scope:** удаление `ctx.extras["bindings"]` (G.5).
**Module contract:** n/a (docs).

---

## G.0 cumulative acceptance + verification — ✅ DONE (2026-05-28, `ffeca3ba`)

- [x] `python -m pytest multiprocess_prototype/` + recipe_engine: **2025 passed, 3 skipped, 0 failed**
- [x] `grep "TODO Phase F"` = 0; `grep "AdministrationSection"` = 0 (исходники); `grep "_engine._active_name"` (prototype) = 0
- [x] `mcp__sentrux__check_rules` 9/9, 0 нарушений; quality **7136** (+1 vs F 7135)
- [x] ruff clean на всех затронутых файлах
- [x] Commit `ffeca3ba` с `Refs: phase-g.md`, `Layer: mixed`, `Why:`
- [x] master plan.md (G → PLANNED, G.0 DONE) + память обновлены

---

## Wave 2 — G.1 (typed events foundation)

Закрывает 🔴 silent-failure `getattr(services.topology, "_holder")` ([pipeline/presenter.py:72](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L72))
и переводит scene-reload Pipeline на typed EventBus (`TopologyReplaced`), сохраняя поведение
(полный refresh при замене топологии). Гранулярные события (`ProcessAdded`/`WireConnected` для
инкрементального обновления вместо полной перерисовки) — **G.4** (когда ActionBus→commands начнёт их публиковать).

**Архитектурные факты (audit):**
- `TopologyRepository` Protocol намеренно минимален (load/save); подписки — через **EventBus** (решение phase-b). 🔴 закрываем через `services.events`, НЕ методом repo.
- Production-путь мутаций: ActionBus handlers (`TopologyMutationHandler`/`RecipeApplyHandler`) → `holder.set_topology()`. `CommandDispatcher.dispatch()` и EventBus **без production-публикаторов**.
- Поэтому publisher-мост `holder.on_changed → events.publish(TopologyReplaced)` ставится в composition root (app.py) — это ловит ВСЕ `set_topology` (включая ActionBus). consumer'ы переходят на `services.events.subscribe`.
- `EventBus.subscribe` держит **сильную** ссылку на handler (не weakref) — подписка не умирает; `QtEventBus` публикует синхронно на main thread (сохраняется `_suppress`-guard семантика).
- `TopologyReplaced(reason: str)` несёт только reason → handler тянет dict через `services.topology.load().to_dict()` (консистентно с F.2b, где presenter уже читает топологию из `services.topology.load()`).

### Task G.1.1 — Publisher-мост + PipelinePresenter на EventBus

**Level:** Senior (teamlead — трогает живой scene-reload Pipeline)
**Goal:** presenter перестаёт читать `_holder` через getattr; подписывается на `TopologyReplaced` через
`services.events`; app.py публикует `TopologyReplaced` при любом `holder.set_topology`.
**Files:**
- `frontend/app.py` — после `build_app_services` + создания `topology_holder`:
  `topology_holder.on_changed(lambda _t: app_services.events.publish(TopologyReplaced(reason="topology_changed")))`
  (тот же экземпляр `app_services.events`, что получает presenter).
- `frontend/widgets/tabs/pipeline/presenter.py` — убрать `getattr(services.topology, "_holder", None)` + `on_changed` (72-74);
  `self._topology_sub = services.events.subscribe(TopologyReplaced, self._on_topology_replaced)`;
  переименовать `_on_topology_changed_external(new_topology: dict)` → `_on_topology_replaced(event: TopologyReplaced)`,
  тянуть `new_topology = self._services.topology.load().to_dict()`, сохранить `_suppress`-guard + `_block_signals`.
- `frontend/widgets/tabs/pipeline/tests/` (`_helpers.py` + presenter-тесты) — topology-change через `events.publish(TopologyReplaced(...))` (Fake/builder EventBus), НЕ `holder.on_changed`/getattr.

**Acceptance:** — DONE (2026-05-28, commit `75a6c41f`)
- [x] `grep 'getattr(services.topology, "_holder"' pipeline/` = 0 (🔴 закрыт)
- [x] presenter подписан через `services.events`; scene reload при `publish(TopologyReplaced)` (test_topology_replaced_via_eventbus, реальный EventBus)
- [x] топология тянется из `services.topology.load().to_dict()` (test_on_topology_replaced)
- [x] pipeline 321 + frontend/adapters 423 passed; sentrux 7135 / 9-9; ruff clean
- [x] Commit `75a6c41f`, `Layer: prototype`

> **Верификация цепочки (closed `1411ee57`):** обвязка вынесена в `frontend/topology_events.py`
> (`wire_topology_events`) и покрыта интеграционным тестом `frontend/tests/test_topology_events_wiring.py`
> на РЕАЛЬНЫХ компонентах: `TopologyHolder.set_topology()` → publisher → `QtEventBus` →
> `PipelinePresenter` scene-model reload (+ bridge cache invalidation). Это детерминированно доказывает
> полную цепочку (включая ранее непокрытый publisher-мост) без GUI-окна.
> **Остаётся manual:** только визуальный рендер окна в живом multiprocess-GUI (qt-mcp недостижим до
> дочернего процесса) — рекомендован перед merge, но логика цепочки уже доказана тестом.

**Out of scope:** TopologyBridge IPC sync (G.1.2); granular events ProcessAdded/WireConnected (G.4); удаление holder (G.3).
**Edge cases:** пустая топология → load() даёт пустой Topology; `_suppress` во время собственных мутаций presenter'а — publish синхронный, guard срабатывает как раньше.

### Task G.1.2 — TopologyBridge IPC sync на EventBus — DONE (2026-05-28)

**Done:** `app.py` подписка `topology_holder.on_changed(topology_bridge.on_topology_changed)` перенесена
и заменена на `services.events.subscribe(TopologyReplaced, lambda _e: topology_bridge.on_topology_changed())`
в блоке 3h.1 (после сборки app_services). `on_topology_changed(_new_topology=None)` — аргумент сделан
опциональным (handler только инвалидирует кэш slider-полей, dict не использует). Находка: handler
игнорировал topology dict → round-trip не нужен, миграция тривиальна.
**Результат:** production `holder.on_changed` теперь = ОДИН подписчик (publisher-мост) → разблокирует **G.3**
(замена хука на публикацию в преемнике set_topology + удаление holder).
**Verify:** bridge+frontend+pipeline 805 passed; sentrux 7135 / 9-9; ruff clean. +test_clears_slider_cache_no_arg.

---

## Wave 3 — G.2 (RegistersBackend / RegistersManager alignment)

> Детализировано 2026-05-28 после grep актуальных call-sites + investigator-разбора FieldInfo-зависимости.

### Исправление премисы (важно)

Исходная формулировка («расширить domain `RegistersBackend` Protocol, убрать 3 getattr») **не работает** и была бы костылём. Факты grep:

1. `RegistersManager` (framework) — **плоский** `{name: model_instance}` dict (`core/manager.py:77`). Координатная адресация `(process_name, plugin_index)` в domain Protocol — спекулятивная абстракция Phase C с **0 production-вызовами** (`get_field_specs`/`get_value`/`set_value` встречаются только в адаптере + тестах).
2. Три реальных call-site используют **flat register_name** + требуют rich framework `FieldInfo`:
   - `pipeline/inspector/inspector_panel.py:513` — `rm.get_fields(process_name)` → `CardsFieldFactory.create(field_info)` (строит виджеты).
   - `plugins/presenter.py:48,115` — `rm.get_fields(plugin_name)` → `RegisterView(fields)` (строит виджеты).
   - `pipeline/presenter.py:107` — `rm.get_register(process_name)` (old_value) + fallback `rm.set_value` (no-bus путь).
3. Весь `forms/`-слой (~1100 строк: `CardsFieldFactory`, `RegisterView`, `form_builder`, `field_editor`) построен на framework `FieldInfo`. Domain `FieldSpec` (name/dtype/label/metadata) — **lossy** проекция, её недостаточно для построения виджетов.
4. **Domain-слой по правилам импортов не может импортировать framework `FieldInfo`** (`.sentrux/rules.toml`). ⇒ FieldInfo-доступ к регистрам **в принципе не может** идти через domain `AppServices.registers`.

### Решение (правильная архитектура, без костылей)

`RegistersManager` держит **live-инстансы** регистров с runtime-значениями и observer'ами — это **runtime-объект** (брат `topology_bridge`, который сам его оборачивает, и `command_sender`), а не editor-state. Это ровно разделение **Q-F1=B**: `AppServices` = editor-state (типизированные domain Protocol'ы), `RuntimeDeps` = runtime-layer (IPC-мосты, discovery-менеджеры, live-менеджеры).

⇒ `RegistersManager` проводится как **явная типизированная runtime-зависимость через `RuntimeDeps`** (точно тем же путём, что `plugin_manager`), а 3 `getattr(services.registers, "_rm")` заменяются на explicit `self._registers_manager`. Никакой Protocol-обёртки над `RegistersManager` — это была бы церемония (он уже стабильный framework API, forms-слой и так импортирует `FieldInfo` напрямую; слой `prototype → framework` разрешён).

Domain `RegistersBackend` Protocol + `RegistersBackendFromManager` adapter **остаются нетронутыми** — это контракт **записи значений для domain-команд** (FieldSetHandler → domain command в G.4), вид другого слоя, не дубликат. После G.2 у `services.registers` 0 frontend-потребителей — он зарезервирован под G.4. Его координатная адресация — тоже вопрос G.4 (когда появятся реальные потребители).

**Site #1 (ActionBus-entangled):** в G.2 мигрируется только **read-path** (old_value через `get_register` + no-bus fallback `set_value`) на explicit `registers_manager`. Сам `bus.execute(V2ActionBuilder.field_set...)` путь остаётся для **G.4** (затаскивать ActionBus→commands в G.2 = big-bang, запрещён brief §8).

### Task G.2.1 — registers_manager в RuntimeDeps + проводка в 3 консьюмера

**Level:** Senior (teamlead/director-direct — трогает живые Pipeline/Plugins табы, DI-проводку)
**Goal:** Убрать 3 `getattr(services.registers, "_rm", None)`, заменив на явный typed `registers_manager` через `RuntimeDeps` (Q-F1=B).

**Files:**
- `frontend/runtime_deps.py` — добавить поле `registers_manager: "RegistersManager | None" = None` (TYPE_CHECKING import из `multiprocess_framework.modules.registers_module`) + docstring.
- `frontend/tab_factory.py:_build_runtime_deps()` — `registers_manager=ctx.registers_manager() if hasattr(ctx, "registers_manager") else None`.
- `pipeline/tab.py` — `create()` → `cls(services, registers_manager=runtime.registers_manager)`; `__init__(services, *, registers_manager=None, ...)` → `PipelinePresenter(services, registers_manager=registers_manager)`.
- `pipeline/presenter.py` — `__init__(services, *, registers_manager=None)` хранит `self._registers_manager`; `set_inspector` пробрасывает в panel; `_on_inspector_field_changed` использует `self._registers_manager` вместо getattr.
- `pipeline/inspector/inspector_panel.py` — `set_services(services, *, registers_manager=None)` хранит `self._registers_manager`; `_try_build_cards_editors` использует его вместо getattr.
- `plugins/tab.py` — `create()` → `cls(..., registers_manager=runtime.registers_manager)`; `__init__` → `PluginsPresenter(..., registers_manager=...)` + `build_plugin_sections(..., registers_manager=...)`.
- `plugins/presenter.py` — `__init__(services, *, plugin_manager=None, registers_manager=None)` хранит `self._registers_manager` (вместо getattr).
- `plugins/_sections.py` — `build_plugin_sections(..., registers_manager=None)` → `_make_plugin_factory(..., registers_manager=...)` → `_PluginSection(..., registers_manager=...)` → `PluginsPresenter(services, registers_manager=...)` в `_build_widget`.

**Тесты:**
- `pipeline/tests/_helpers.py` (104-106), `plugins/tests/_helpers.py` (46-48) — убрать `registers._rm = registers_manager` bridge-хак, провести `registers_manager` через конструктор таба/презентера/RuntimeDeps.
- `pipeline/tests/test_inspector.py` — `_make_services_with_rm`/`_make_services_no_rm` → инъекция через panel.set_services(registers_manager=...).

**Acceptance criteria:** — ✅ DONE (2026-05-28, reviewer APPROVED)
- [x] `grep 'getattr(.*services.registers.*_rm'` → 0 (production)
- [x] `grep 'registers\._rm ='` (вне адаптера) → 0
- [x] `registers_manager` типизирован в RuntimeDeps как `RegistersManager | None` (не `Any`)
- [x] domain `RegistersBackend` Protocol + adapter не изменены
- [x] site #1 `bus.execute` путь не тронут (остаётся G.4); мигрирован только read-path
- [x] pytest pipeline+plugins+adapters **532 passed/2 skipped**, frontend **283 passed**; ruff clean; sentrux check_rules **9/9**, quality 7133
- [x] +позитивный тест `test_registers_manager_via_runtime_builds_register_view` (полная цепочка RuntimeDeps→RegisterView)
- [x] Commit с `Refs: phase-g.md`, `Layer: prototype`

**Verify-замечание (reviewer, non-blocking):** leaf-консьюмеры (`_sections.py`, `inspector_panel.py`, plugins `presenter.py`) аннотируют `registers_manager` как `Any` — консистентно с существующим `plugin_manager: Any`. Унификация типизации → G.4/G.5.

**Out of scope:** ActionBus→domain commands (G.4); удаление/переделка domain RegistersBackend coordinate-адресации (G.4); form_context (G.4); удаление services.registers (G.4 решит).
**Edge cases:** `registers_manager=None` (табы без регистров / тесты) → методы возвращают [] / no-op как сейчас; кэш `_PATHS_SECTION_CACHE` по id(services) — registers_manager в _PathsSection не нужен (только пути).

---

## Wave 4 — G.3 (TopologyHolder removal — store-publishes)

> Детализировано 2026-05-28 после grep актуальных writers/readers. **Scope: L (не M)** — затрагивает composition root (app.py assembly) + IPC-мост. Выбран **Design 2** (владелец: «как лучше и правильнее, без костылей»).

### Факты (grep production)

Все записи topology воронкой идут в `holder.set_topology`:
- `pipeline/presenter.py:378` → `services.topology.save()` → repo → `holder.set_topology`
- ActionBus: framework `TopologyMutationHandler` (`actions_module/handlers/topology_handler.py`, интерфейс `TopologyHolderProtocol.set_topology(dict)->None`) + prototype `RecipeApplyHandler` → `holder.set_topology(dict)` напрямую
- `holder.on_changed` → publisher-мост (`topology_events.wire_topology_events`) → `TopologyReplaced`

Читатели: `topology_bridge` (`self._holder.topology.get(...)` ×3, через `IBridgeTopologyHolder.topology`), `topology_repository.load()`, presenter/processes presenter (`services.topology.load()`).

`suppress_legacy_notify` — **мёртв**: его смысл (гасить двойную нотификацию от unused CommandDispatcher) не реализуется в production-пути.

### Design 2 — store владеет dict и публикует domain-события

`TopologyHolder` сливается в `TopologyRepository`-adapter (`TopologyRepositoryStore`): владеет topology dict, при каждой мутации **публикует `TopologyReplaced` через injected EventBus** (никаких on_changed-callback'ов, никакого publisher-моста). Store удовлетворяет:
- domain `TopologyRepository` Protocol — `load()->Topology`, `save(Topology)` (presenter, processes, RegistersBackend, ProjectHolder bootstrap, CommandDispatcher);
- framework `TopologyHolderProtocol` — `set_topology(dict)->None` (ActionBus handlers, без изменений в них);
- `IBridgeTopologyHolder` — `.topology` property (bridge reads, без изменений в bridge).

`save()` делегирует в `set_topology()` → одна публикация на мутацию. adapters больше **не импортируют frontend** (закрывается Q1-исключение). EventBus создаётся **рано** в app.py (QApplication уже создан на app.py:54), store создаётся с bus.

### Task G.3.1 — TopologyHolder removal

**Level:** Senior (teamlead/director — composition root + IPC-мост)
**Files (prod):**
- `adapters/stores/topology_repository.py` — переписать: `TopologyRepositoryStore(initial: dict, events: EventBusProtocol)`; `topology` property, `set_topology(dict)` (publishes), `load()/save(Topology)`. Убрать `frontend.topology_holder` import + `suppress_legacy_notify`.
- `adapters/stores/__init__.py`, `adapters/__init__.py` — rename `TopologyRepositoryFromHolder`→`TopologyRepositoryStore`; убрать Q1-exception из docstring.
- `frontend/app.py` — создать `QtEventBus` + `TopologyRepositoryStore` рано; `ctx.extras["event_bus"]`/`["topology_store"]`; убрать `TopologyHolder`; передать store в `TopologyBridge` + `create_action_bus`; заменить блок `wire_topology_events` на `event_bus.subscribe(TopologyReplaced, lambda _e: topology_bridge.on_topology_changed())`.
- `frontend/app_services_factory.py` — читать `event_bus`+`topology_store` из `ctx.extras` (не создавать QtEventBus / не строить из holder).
- `frontend/actions/bus_factory.py`, `actions/handlers/recipe_handler.py` — type hints holder→store (логика без изменений).
- DELETE `frontend/topology_holder.py`, `frontend/topology_events.py`.
- `frontend/app_context.py` — убрать `topology_holder()` accessor + import.
- `frontend/_deprecated_extras.py` — убрать `topology_holder` entry.
- `.sentrux/rules.toml` — убрать упоминание TopologyHolder-исключения (lines ~143-149).
- `adapters/README.md` — Q1/Q6 обновить (holder удалён).

**Tests:** rewrite `adapters/tests/test_topology_repository.py` (store+publish), `frontend/tests/test_topology_events_wiring.py` (store.save→presenter reload+bridge cache на реальном QtEventBus), `test_phase15_smoke.py`, `app_services_factory` tests, `test_integration_assembly.py` (rename). bridge/recipe_handler тесты — MockHolder duck-types, минимально.

**Acceptance:** — ✅ DONE (2026-05-28, reviewer APPROVED)
- [x] нет runtime-импортов удалённых модулей (`topology_holder import`/`topology_events`/`TopologyRepositoryFromHolder`/`suppress_legacy_notify`/`wire_topology_events` = 0; остатки только в комментариях-истории)
- [x] store публикует `TopologyReplaced` на save/set_topology (одна публикация: save→set_topology→publish×1)
- [x] adapters не импортируют frontend (Q1 закрыт, .sentrux/rules.toml обновлён); domain не тронут
- [x] pytest multiprocess_prototype/ **2003 passed, 3 skipped**; ruff clean; sentrux check_rules **9/9**, quality 7131
- [x] store duck-types 3 интерфейса (TopologyRepository / TopologyHolderProtocol / IBridgeTopologyHolder) → bridge+ActionBus handlers без логических правок
- [ ] live boot-smoke (qt-mcp/ручной) перед merge — IPC-мост нельзя проверить только pytest-qt (known caveat)
- [x] Commit `Refs: phase-g.md`, `Layer: mixed`

**Out of scope:** ActionBus→domain commands (G.4); ProjectHolder как единственный SoT (G.4); удаление CommandDispatcher double-notify compromise (G.4).
**Риск:** medium — composition root reorder + IPC bridge wiring; митигация: store duck-types все 3 интерфейса (handlers/bridge без логических правок), live-smoke перед merge.

---

## Wave 5 — G.4 (ActionBus → domain commands + undo/redo поверх domain)

> Детализировано 2026-05-28 после grep+qex актуальной реальности. **Премиса исходного аудита устарела** — см. находки ниже. G.4 разбит на 4 под-волны (no-big-bang, brief §8). Этим заходом делается только **G.4.1 (foundation)** — он самодостаточен, не трогает живые табы, низкий риск регрессии.

### Audit-уточнение (2026-05-28, grep+qex реальности)

Подтверждённые находки (grep `bus.execute/dispatch`, qex, чтение orchestrator/factory/app.py):

1. **`commands.dispatch()` — 0 production call-sites** (только тесты). Domain-путь `Project.apply → CommandDispatcherOrchestrator → topology_repo.save → publish` полностью построен и покрыт тестами, но **не подключён** ни к одному презентеру.
2. **ActionBus в табах МЁРТВ.** `CommandDispatcherOrchestrator` НЕ имеет метода `action_bus` → `getattr(services.commands, "action_bus", None)` = **None** во всех табах (pipeline, plugins, settings-секции `_sections.py`, services/tab). Реальная шина (`app.py:414`) жива только в `window.set_action_bus` (Ctrl+Z/Y shortcuts) и доступна через `ctx.action_bus()` (`settings/presenter.py:242`, AppContext-coupled → забота G.5). ⇒ доступ к шине несогласован: часть путей мёртвые (`services.commands`), часть живые (`ctx`).
3. **Латентный desync-баг:** при `bus=None` `pipeline/presenter.remove_selected` и `add_wire` обновляют только `PipelineModel` + scene, но **НЕ** сохраняют в `topology_repo`. `add_process_from_plugin` сохраняет (`services.topology.save`). ⇒ в production удаление процесса и добавление wire не персистятся. **G.4.2 чинит это как побочный эффект.**
4. **Domain НЕ имеет undo/redo.** Framework `ActionBus` — snapshot-based (forward/backward patch dict, coalescing по `coalesce_key`, `max_history=50`). Topology-мутации хранят полный topology dict в патчах; field_set — `{value}`.
5. **Две SSOT:** `PipelineModel._topology` (editor) и `ProjectHolder`/`topology_repo` (domain). Презентер уже подписан на `TopologyReplaced` (G.1) и делает полный reload модели из repo на событие.
6. **NODE_MOVE** — GUI-only (позиции в `_gui_positions`/metadata), **не** topology-domain. **ROLE_UPDATE** — auth-домен (`roles_panel` со своей шиной), не topology-domain. Оба остаются на отдельной шине (решение в G.4.4).

**Вывод:** G.4 — это не «миграция работающей шины», а **подключение готового domain-пути + постройка undo/redo поверх domain + унификация доступа** (удаление мёртвого `action_bus` bridge).

### Целевая архитектура (unidirectional / CQRS-ish)

Презентер: намерение-мутация → `services.commands.dispatch(DomainCommand)` → orchestrator: `Project.apply` (чистая функция) → `topology_repo.save` (store публикует `TopologyReplaced`, G.3) → `holder.set` → publish granular events. View обновляется **из событий** (`_on_topology_replaced` — full reload; granular `ProcessAdded/WireConnected` — инкрементально, G.6). undo/redo — **снимки Project** поверх dispatch (snapshot-based, сохраняет семантику ActionBus). `PipelineModel` перестаёт быть SSOT мутаций → производная проекция domain.

### Декомпозиция G.4 (no-big-bang)

| Под-волна | Описание | Scope | Зависит | Статус |
|---|---|---|---|---|
| **G.4.1** | **Foundation:** `ProjectHistory` (snapshot undo/redo + coalescing + max_history) + методы orchestrator `undo/redo/can_undo/can_redo/history/clear_history` + расширение domain `CommandDispatcher` Protocol + обновление `FakeCommandDispatcher`. Без миграции call-sites. | M (~7, adapters+domain+tests) | G.1–G.3 | **DONE** (`e5aaa862`, reviewer APPROVED) |
| **G.4.2** | **Pilot Pipeline topology:** `add_process_from_plugin`/`remove_selected`/`add_wire` → `dispatch(AddProcess/RemoveProcess/ConnectWire)`; undo/redo (Ctrl+Z/Y) → `services.commands`; убраны оптимистичные scene-апдейты (reload из `TopologyReplaced`). Чинит desync-баг (находка #2). **Scope сужен:** только process-node + process→process wire; display → G.4.2b. | L (живой editor) | G.4.1 | **DONE** (`dedb4a1f`+`05b1d3f7`, reviewer APPROVED) |
| **G.4.2b** | **Display = binding (Idea) + рендеринг:** output→display = `BindDisplay`/`UnbindDisplay`; **реализовать рендеринг display-узлов+binding-рёбер на scene** (преisting gap — никогда не было в v3); fan-out по паре `(node_id, display_id)`; схлопнуть io.py-конвертер; ADR. Закрывает desync #2 display. | **M-L** (scope expanded) | G.4.2 | **DETAILED** (full task-spec ниже) |
| **G.4.3** | **FIELD_SET → SetPluginConfig (только Pipeline Inspector):** `_on_inspector_field_changed` → `dispatch(SetPluginConfig)` + persist + undo; rm-sync listener (IPC уже в `rm`); `_suppress` reload + coalesce. Plugins-таб = превью (убрать dead-ветку). Settings/System+Roles вне scope. | M | G.4.1 | **DETAILED** (task-spec ниже) |
| **G.4.4** | **Domain undo/redo UX + единая шина + phantom-cleanup:** observer на orchestrator + framework `UndoRedoController` Protocol (кнопки undo/redo, долг G.4.2); HistoryPresenter→domain history; **fix dual-undo (новый баг #2)**; убрать фантом `services.commands.action_bus()` (×9). RECIPE_APPLY live + удаление `frontend/actions/`/dead handlers — **отложено (big-bang, brief §8)**. | M | G.4.2, G.4.3 | **DONE** (`171f1d8f`, verify ✓ 2055/sentrux 9-9/7134, reviewer APPROVED) |

### Task G.4.1 — ProjectHistory + orchestrator undo/redo + Protocol

**Level:** Senior (teamlead/director — расширяет domain Protocol + центральный orchestrator)
**Goal:** Построить snapshot-based undo/redo поверх готового domain-пути, не трогая презентеры. Это keystone — G.4.2/G.4.3 подключают call-sites к этому механизму.

**Файлы (prod):**
- NEW `adapters/dispatch/history.py` — `ProjectHistory` (snapshot-стек) + `HistoryEntry` (frozen dataclass: `label`, `command_type`, `timestamp`). API: `record(before, after, label, command_type, coalesce_key=None)`, `take_undo()->Project|None`, `take_redo()->Project|None`, `can_undo()/can_redo()`, `entries(n)->list[HistoryEntry]`, `clear()`. Coalescing: одинаковый `coalesce_key` с вершиной undo-стека → merge (keep `before` старого, `after` нового). `max_history` (default 50, как ActionBus). Новая запись чистит redo-стек. Без Qt/IPC — чистый стек.
- EDIT `adapters/dispatch/command_dispatcher.py` — orchestrator владеет `ProjectHistory`; `dispatch(cmd, *, coalesce_key=None, undoable=True)` дополнительно `record(before=current, after=new, ...)`; новые методы `undo()/redo()->bool` (восстановление снимка через `holder.set` + `topology_repo.save` → store публикует `TopologyReplaced` → презентеры reload), `can_undo()/can_redo()`, `history(n)->list[HistoryEntry]`, `clear_history()`. Конструктор: `+ max_history=50` (default — старые тесты не ломаются). DomainError в apply → ничего не записано (rollback-семантика сохранена).
- EDIT `domain/protocols/command_dispatcher.py` — расширить Protocol: `undo/redo/can_undo/can_redo/clear_history` + `history(n=...)`. `HistoryEntry` — sidecar dataclass в этом же файле (domain-чистый, без framework-импортов).
- EDIT `domain/tests/_fakes.py` — `FakeCommandDispatcher` реализует новые методы (in-memory: undo/redo → no-op `False`, can_* → `False`, history → `[]`).
- EDIT `adapters/dispatch/__init__.py`, `adapters/__init__.py` — экспорт `ProjectHistory`, `HistoryEntry`.

**Тесты:**
- NEW `adapters/tests/test_project_history.py` — record/undo/redo round-trip, coalescing merge, redo-clear-on-new-record, max_history overflow, empty-stack no-op.
- EDIT `adapters/tests/test_command_dispatcher.py` — orchestrator undo/redo: dispatch→undo восстанавливает прошлый Project + публикует TopologyReplaced (реальный store); redo; can_undo/can_redo; DomainError не пишет в history.

**Acceptance criteria:** — ✅ DONE (2026-05-28, `e5aaa862`, reviewer APPROVED)
- [x] `ProjectHistory` покрыт unit-тестами (coalescing, overflow, redo-clear, empty no-op) — `test_project_history.py` (8 тестов).
- [x] orchestrator `undo()` восстанавливает предыдущий Project, `topology_repo.save` публикует `TopologyReplaced` (проверено на реальном `TopologyRepositoryStore`+`EventBus`).
- [x] `CommandDispatcher` Protocol расширен; `FakeCommandDispatcher`/`_FakeDispatcher`/`_FakeDispatcherWithBus` satisfies (pyright 0 ошибок).
- [x] Старые тесты `test_command_dispatcher.py` (4-арг конструктор) не сломаны.
- [x] `python -m pytest multiprocess_prototype/` → **2018 passed, 3 skipped, 0 failed**; ruff clean; sentrux `check_rules` **9/9**, quality 7131 (без регрессии).
- [x] Commit `e5aaa862` (+ план `c432574a`) с `Refs: phase-g.md`, `Layer: prototype/docs`.

**Out of scope:** миграция презентеров (G.4.2/G.4.3); удаление `action_bus` bridge (G.4.4); NODE_MOVE/ROLE_UPDATE; FIELD_SET register-mapping.
**Edge cases:** undo на пустом стеке → `False` (no-op); coalescing field-burst → один undo откатывает всю серию; DomainError при apply → history не тронут.
**Module contract:** public-api-change (additive: расширение domain `CommandDispatcher` Protocol + новый `ProjectHistory`).

---

### Task G.4.2 — Pilot: Pipeline topology-мутации → domain dispatch + undo/redo

> Детализировано 2026-05-28 после grep+чтения реальности (presenter.py, tab.py, model.py, domain/commands.py, domain/entities/project.py). Премиса G.4 уточнена двумя **критическими находками** (см. ниже). Scope сознательно сужен (no-big-bang, brief §8).

**Level:** Senior (teamlead/director — трогает живой Pipeline editor: scene-reload, undo/redo, валидация)
**Assignee:** teamlead (после approval — реализация), затем reviewer
**Goal:** Перевести **process-node** мутации Pipeline editor (`add_process_from_plugin`, process-ветка `remove_selected`, process→process `add_wire`) и кнопки **undo/redo** с мёртвого `action_bus` на `services.commands.dispatch(...)` / `services.commands.undo()/redo()`. Как побочный эффект чинит латентный desync-баг (находка #3 Wave 5). Pilot — образец для G.4.3/G.4.4.

#### Audit-находки (grep+read 2026-05-28, file:line)

1. **`self._action_bus` мёртв в production** — `getattr(services.commands, "action_bus", None)` = None (orchestrator не имеет метода `action_bus`). Подтверждено в [presenter.py:78-79](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L78) и [tab.py:115-117](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py#L115). ⇒ все `bus.execute/undo/redo` ветки в Pipeline — dead branches.
2. **Desync-баг подтверждён:** [presenter.py:364-378](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L364) `add_process_from_plugin` при bus=None **сохраняет** в `services.topology.save(...)`; а [remove_selected:388](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L388) и [add_wire:416](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L416) при bus=None обновляют только `PipelineModel`+scene, **НЕ** персистят. В production удаление процесса и добавление wire теряются. Dispatch чинит это (orchestrator всегда `topology_repo.save`).
3. **🔴 КРИТИЧНО — domain `ConnectWire` НЕ поддерживает wire-to-display.** [project.py:_apply_connect_wire:624-630](../../multiprocess_prototype/domain/entities/project.py#L624): `_extract_process_from_node("display.<node_id>.frame")` = `"display"` ∉ process_names → **DomainError**. `PipelineModel.add_wire` ([model.py:209-219](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py#L209)) обрабатывает display-target специально (skip cycle/self-loop, проверка display node_id). ⇒ wire-to-display **нельзя** гнать через `ConnectWire` как есть.
4. **🔴 КРИТИЧНО — нет domain-команды «удалить display-узел».** Есть только `UnbindDisplay(node_id)` (убирает binding из `displays`). `PipelineModel.remove_display` ([model.py:157](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py#L157)) дополнительно каскадит wire-ы `display.<id>.*`. Семантика не идентична.
5. **Domain не отвергает дубликаты wire-ов** (`_apply_connect_wire` не проверяет); `PipelineModel.add_wire` бросает ValueError на дубликат ([model.py:204-207](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py#L204)). После миграции этот guard на process→process исчезнет, если не сохранить его в presenter перед dispatch.
6. **Port-type валидация — GUI-concern.** `_validate_wire_ports` ([presenter.py:458](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L458)) с `QMessageBox` остаётся в presenter **до** dispatch (domain `ConnectWire` несёт `src_dtype/tgt_dtype`, но не делает QMessageBox).
7. **Port-schemas теряются при reload.** `_topology_to_graph` ([presenter.py:686](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L686)) строит `NodeData` **без** `port_schemas`. Целевая арх. («убрать оптимистичные scene-апдейты, reload из `TopologyReplaced`») требует **реконструировать port_schemas из `services.plugins.resolve(plugin_name).ports`** при reload, иначе после dispatch ноды лишатся портов и wire-ы нельзя будет тянуть. Это **обязательный** под-шаг.
8. **Синхронный double-apply.** `QtEventBus` публикует синхронно: `dispatch()` внутри себя вызовет `_on_topology_replaced` (full reload) ДО возврата. ⇒ оптимистичный `scene.add_node/remove_node/add_edge` после dispatch станет вторым применением → надо **убрать** оптимистичные scene-апдейты (целевая арх.). `_on_topology_replaced` guard `if self._suppress: return` — при dispatch `_suppress=False`, reload сработает (нужное поведение).

#### Решение по scope (tight pilot, no-big-bang)

Мигрируются ТОЛЬКО **process-node** операции + **process→process** wire:
- `add_process_from_plugin` → `dispatch(AddProcess(process_name, plugins=(PluginInstance(plugin_name, category=...),)))`. AddProcess **обязан** нести плагин (иначе нода пустая; domain валидирует plugin по catalog — дроп из палитры гарантирует наличие).
- process-ветка `remove_selected` → `dispatch(RemoveProcess(process_name))` (domain каскадит wires+displays сам).
- process→process `add_wire` → port-валидация (QMessageBox) → guard дубликата → `dispatch(ConnectWire(source, target, src_dtype, tgt_dtype))`. DomainError (цикл/dangling) → лог + `return False`.
- undo/redo кнопки + Ctrl+Z/Y ([tab.py:277-284](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py#L277)) → `services.commands.undo()/redo()`.

**Откладывается (НЕ в G.4.2)** — фиксируется как явный долг:
- display-ветка `remove_selected` (`remove_display`) и wire-to-display (`add_wire` с `display.*` target) — остаются на старом `PipelineModel`+save пути (находки #3/#4: domain-модель wire-to-display иная, нет симметричной команды). Миграция — отдельная под-волна **G.4.2b** (или в G.4.4 вместе с recipe/cleanup) после решения, как domain представляет display-wire/ display-node-remove. `log()` этого ограничения в коде комментарием + строкой плана.
- `_on_inspector_field_changed` (FIELD_SET) → **G.4.3**. `on_node_moved` (NODE_MOVE, GUI-only) → **G.4.4**.

> ⚠️ Последствие отложенного display-пути: display-ветка `remove_selected`/wire-to-display **сохранят** desync-баг (находка #2) до G.4.2b. Это не регрессия (так уже сейчас), но должно быть явно записано, чтобы не выглядело «всё починили».

**Файлы (prod):**
- `frontend/widgets/tabs/pipeline/presenter.py`:
  - `__init__` — убрать `self._action_bus` (78-79) + лишние ленивые импорты `V2ActionBuilder`. Хранить `self._services.commands` (уже есть через `self._services`).
  - `add_process_from_plugin` — заменить `self._model.add_process(...)` + bus/save-ветки на `dispatch(AddProcess(...))`; убрать оптимистичный `scene.add_node`; `self._gui_positions[name]=(x,y)` оставить ДО dispatch (reload читает позиции). Имя-уникальность — по `self._model.get_process_names()` (модель синхронна после прошлого reload).
  - process-ветка `remove_selected` — `dispatch(RemoveProcess(node_id))`; убрать оптимистичный `scene.remove_node` для process-нод; display-ветка — оставить старый путь (с пометкой-комментарием G.4.2b).
  - `add_wire` — оставить `_validate_wire_ports`; добавить guard дубликата (или вынести в presenter); process→process → `dispatch(ConnectWire(...))` в try/except DomainError → `return False`; убрать оптимистичный `scene.add_edge`; wire-to-display — старый путь.
  - `_on_topology_replaced` — **реконструировать port_schemas** в `_topology_to_graph` (или в reload): для каждой process-ноды `services.plugins.resolve(plugin_name).ports → PortSchema`. Передать в `scene.load_from_data(...)` (проверить сигнатуру `load_from_data` — поддерживает ли port_schemas; если нет — расширить или дергать `scene.add_node(..., port_schemas=)` поэлементно).
- `frontend/widgets/tabs/pipeline/tab.py`:
  - убрать `self._action_bus` (115-117); `enable_undo_redo` — пробросить адаптер поверх `services.commands` (метод `undo/redo` + `can_undo/can_redo` для enable-состояния) ИЛИ убрать аргумент и завязать кнопки на `_on_toolbar_action("undo"/"redo")`. Уточнить контракт `DiffScrollTabLayout.enable_undo_redo` (что он ожидает от объекта).
  - `_on_toolbar_action("undo"/"redo")` → `self._services.commands.undo()/redo()`.
  - убрать TODO Phase G(G.4) комментарии (278/282) — заменить фактом.

**Зависимости/проводка:** `services.commands` — это `CommandDispatcherOrchestrator` (уже в AppServices, см. G.4.1). `apply_context_factory` уже строит `ApplyContext(plugins/displays/recipes)` — проверить, что `plugins` каталог НЕ None в production (иначе AddProcess/ConnectWire не провалидируют ссылки, но и не упадут — None пропускает invariant). Wire reload port-reconstruct требует `services.plugins`.

**Тесты:**
- `pipeline/tests/test_presenter*.py` (+ `_helpers.py`): мутации через реальный orchestrator+store+QtEventBus (builder `make_pipeline_services(events=...)` + commands). Проверить: (a) `add_process_from_plugin` → процесс в `services.topology.load()` (персист) + нода в scene после reload + **порты у ноды** (находка #7); (b) `remove_selected([proc])` → процесс удалён из repo (desync-fix, находка #2) + каскад wires; (c) `add_wire(proc→proc)` → wire в repo; цикл → `return False`, repo не изменён; дубликат → `return False`; (d) undo/redo через `services.commands` восстанавливает/повторяет (round-trip на реальном store).
- `pipeline/tests/test_tab*.py`: кнопки/Ctrl+Z/Y дёргают `services.commands.undo/redo`; permission-gating не сломан.
- Регрессия: display-ветка `remove_selected` + wire-to-display всё ещё работают по старому пути (тест-страховка, что не сломали).

**Acceptance criteria:** — ✅ DONE (2026-05-28, `dedb4a1f` + nits `05b1d3f7`, reviewer APPROVED)
- [x] `grep 'action_bus' pipeline/` → 0 в presenter.py/tab.py (мёртвый bridge удалён из Pipeline)
- [x] process add/remove + process→process wire идут через `services.commands.dispatch(...)`; в production персистятся (desync-баг #2 закрыт для process-пути)
- [x] undo/redo через `services.commands.undo()/redo()` — Ctrl+Z/Y работают. ⚠️ КНОПКИ disabled (`enable_undo_redo(None)`) — идентично prod ДО G.4.2 (там action_bus=None); обвязка enable-состояния кнопок требует `add_change_callback` в Protocol → **G.4.4**
- [x] после dispatch ноды в scene имеют корректные port_schemas (находка #7 — `test_port_schemas_on_node_after_dispatch`)
- [x] DomainError (цикл/dangling) при `add_wire` → graceful `return False` + лог, repo не мутирован
- [x] display-ветка remove + wire-to-display НЕ тронуты (старый путь), регрессионный тест зелёный (`TestDisplayLegacyPath`); ограничение задокументировано комментариями `# G.4.2b` + строкой плана
- [x] `python -m pytest multiprocess_prototype/` **2035 passed, 3 skipped**; ruff clean; sentrux `check_rules` 9/9, quality 7129 (delta -2, шум)
- [ ] live boot-smoke Pipeline tab (qt-mcp/ручной) — **НЕ выполнен** (qt-mcp недостижим до дочернего процесса, known caveat фазы как G.1/G.3); рекомендован перед merge ([[feedback-qt-mcp-smoke-verification]])
- [x] Commit `dedb4a1f` (+nits `05b1d3f7`) с `Refs`, `Layer: prototype`, `Why:`+`Tested:`

**Verify-замечание (reviewer APPROVED, 5 nits — все quality, исправлены в `05b1d3f7`):** `load_from_data(port_schemas_map)` единый источник layout (убрано дублирование); `load_scene_with_ports` публичный; `_port_schemas_cache` в `__init__`; устаревшие упоминания ActionBus убраны. Блокеров нет.

**Out of scope:** display-node remove + wire-to-display (G.4.2b); FIELD_SET (G.4.3); NODE_MOVE/recipe/удаление `action_bus()` accessor в orchestrator (G.4.4); гранулярные scene-апдейты из `ProcessAdded`/`WireConnected` (G.6 — пока full reload).
**Edge cases:** пустой palette/plugins=None → AddProcess не валидирует plugin (invariant skip), но нода без портов; дубликат wire → presenter-guard `return False`; undo сразу после load (пустой стек) → no-op; reload во время собственного dispatch — синхронный, `_suppress` не выставлять вокруг dispatch (reload нужен).
**Риск:** **HIGH** — живой editor + scene-reload + port-reconstruct + undo/redo. Митигация: tight scope (process-only), сохранение `_validate_wire_ports`, регрессионный тест на display-путь, live-smoke перед merge, snapshot-undo сохраняет семантику ActionBus.
**Module contract:** behaviour-change (presenter mutation-path: optimistic→unidirectional); public API presenter не меняется.

---

### Task G.4.2b — display = binding (Idea) + рендеринг display-узлов на scene

> **DESIGN LOCKED** (владелец 2026-05-28): «как лучше и полагается, без костылей» → **Idea (binding-not-wire)**. Вариант B (учить domain wire-формату) **отклонён**.
> **DETAILED + SCOPE EXPANDED** (2026-05-28 после grep+investigator-аудита). Премиса исходного дизайн-лока «display-боксы остаются на canvas, визуально без изменений» **оказалась НЕВЕРНОЙ** — см. audit-находки ниже. Владелец выбрал **полный охват** (domain-миграция + реализация рендеринга), а не split с переносом рендеринга в G.6.

**Level:** Senior (teamlead — живой Pipeline editor: scene, domain-модель display, undo/redo)
**Assignee:** teamlead (реализация), затем reviewer
**Goal:** Перевести display-связи Pipeline editor на binding-представление: соединение output→display = `dispatch(BindDisplay)`, удаление = `dispatch(UnbindDisplay)`; **реализовать рендеринг display-узлов и binding-рёбер на scene из `topo["displays"]`** (сейчас отсутствует); схлопнуть wire⇄binding-конвертер в `io.py`; ADR. Закрывает desync-баг display-ветки (находка #2 G.4.2) и доводит до конца незавершённую v3-фичу «display на canvas».

#### Обоснование архитектуры (binding-not-wire)
- display физически = SHM ring-buffer в `ui_process` (`DisplayRegistry` + [`bind_displays_to_blueprint`](../../multiprocess_prototype/backend/displays/blueprint_binding.py)); в топологии — привязка `node_id→display_id`. **routing-значимо** (роутер адресует кадр по `display_id`) → display принадлежит domain.
- **durable-слои УЖЕ binding-центричны:** domain [`DisplayInstance.node_id`](../../multiprocess_prototype/domain/entities/display.py#L33) = выходной endpoint источника; на диске рецепт хранит `display_bindings: [{node_id: <выход>, display_id}]` ([io.py `graph_to_blueprint`](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/io.py#L75) срезает display-wire). **wire-to-display живёт ТОЛЬКО в in-memory `PipelineModel`** — источник рассинхрона. **Миграции на диске НЕ нужно.**

#### Audit-находки рендеринга (investigator 2026-05-28, file:line)
1. **🔴 Display-узлы НИКОГДА не рендерились на scene в v3** (преisting gap, НЕ регрессия G.4.2). [`DisplayNodeItem`](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/display_node_item.py#L41) инстанцируется только в тестах; [`graph_scene.add_node:84`](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/graph_scene.py#L84) всегда строит generic `NodeItem`, метода `add_display_node` нет.
2. **`_topology_to_graph` игнорирует `topo["displays"]`** ([presenter.py:690](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L690)) — и при первичной загрузке, и при reload. Display-wire (`target="display.<id>.frame"`) даёт `EdgeData(target_id="display")` → `add_edge` молча дропает (нет узла "display").
3. **`io.py:blueprint_to_graph` зовёт `model.add_display`** ([io.py:226](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/io.py#L226)) — мутирует только `PipelineModel` (dict), мостика model→scene нет.
4. **Интерактивный display-путь фактически недостижим:** нет UI-точки создания display-узла (context-menu = «Add Process», drag-drop = process-only). `remove_selected`/`add_wire`-to-display требуют выделить/дотянуться до display-узла, которого на canvas нет. ⇒ display-bindings попадают в модель **только через загрузку рецепта**. Desync-баг #2 для display почти нерепродуцируем интерактивно сегодня — но станет достижим, когда G.4.2b нарисует узлы.
5. **Тесты display покрывают только data-layer** (`model`/`repo`), не scene (`TestDisplayLegacyPath` — ни одного assert на scene; presenter без `_scene`). Рендеринг-пробел тестом не закрыт.
6. **`tab._on_selection_changed`** ([tab.py:320](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py#L320)) уже умеет читать `topo["displays"]` при выделении `DisplayNodeItem` → inspector-путь готов, не хватает только создания узлов на scene.

#### 🔴 Domain-находка (fan-out identity)
[`_apply_unbind_display`](../../multiprocess_prototype/domain/entities/project.py#L696) фильтрует `d.node_id != cmd.node_id`, а [`UnbindDisplay`](../../multiprocess_prototype/domain/commands.py#L153) keyed одним `node_id`. Если один выход (`node_id`) привязан к N дисплеям → `UnbindDisplay(node_id)` снесёт ВСЕ. Для fan-out нужен ключ по паре `(node_id, display_id)`. Затрагивает `UnbindDisplay` + `_apply_unbind_display` + `DisplayUnbound` event. `BindDisplay` (node_id, display_id) — без изменений.

#### Решение по scope (полный: domain + рендеринг)

**Концепция:** единица display-связи = пара `(source_output, display_id)` = один `DisplayInstance`. На scene: один **display-бокс на display_id** (канал), binding-рёбра = по одному на `DisplayInstance` (source-узел → display-бокс). Это закрывает и fan-out (один выход → N дисплеев = N bindings), и fan-in (N выходов → один дисплей = N рёбер к одному боксу).

**1. Domain (fan-out identity):**
- `UnbindDisplay` — добавить `display_id: str` (ключ по паре). `_apply_unbind_display` фильтрует `not (d.node_id == cmd.node_id and d.display_id == cmd.display_id)`. `DisplayUnbound` event несёт пару.
- `BindDisplay` — без изменений; `_apply_bind_display` уже валидирует display по catalog.
- Дубль-guard: bind одной и той же пары дважды → DomainError или idempotent (решить в реализации, по умолчанию — DomainError, как ConnectWire-цикл).

**2. Рендеринг (scene + presenter) — НОВОЕ:**
- `graph_scene.py` — новый метод `add_display_node(DisplayNodeData) -> DisplayNodeItem`, кладёт в `self._nodes[node_id]` (чтобы `add_edge` находил target). `load_from_data` — принять отдельный список display-узлов (сигнатура расширяется: `display_nodes: list[DisplayNodeData] | None = None`) ИЛИ presenter рисует их поэлементно после `load_from_data` (как port_schemas). Выбрать в Step 0 — рекомендация: расширить `load_from_data` (один источник layout).
- `presenter._topology_to_graph` — итерировать `topo["displays"]`: бокс keyed по `display_id` (один на канал), `DisplayNodeData(node_id=<box_id=display_id>, display_id, display_name, x,y из gui_positions)`; binding-ребро `EdgeData(source_id=<DisplayInstance.node_id>.split(".")[0], target_id=<box_id>)`. Вернуть третий элемент (display_nodes) или влить в общий проход.
- `load_scene_with_ports`/`_on_topology_replaced` — прокинуть display-узлы в scene.

**3. Мутации presenter → domain dispatch:**
- `add_wire` display-ветка ([presenter.py:403](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L403)) — тянуть провод source→display-бокс = `dispatch(BindDisplay(node_id=<source endpoint>, display_id=<box display_id>))`; убрать `_model.add_wire`+save. DomainError → лог + `return False`.
- `remove_selected` display-ветка ([presenter.py:365](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L365)) — удаление display-бокса = `dispatch(UnbindDisplay(node_id, display_id))` для каждого binding на этот бокс (каскад рёбер). Убрать `_model.remove_display`+save.
- `_on_display_id_changed` ([presenter.py:182](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L182)) — смена display у бокса: Unbind старого + Bind нового (или решить как single ребиндинг). Убрать прямую мутацию `_model._topology`.
- undo/redo — уже на `services.commands` (G.4.2), display-команды автоматически undoable.

**4. Схлопнуть конвертер io.py:** `graph_to_blueprint`/`blueprint_to_graph` ([io.py](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/io.py)) — убрать wire⇄binding-конвертацию: `displays` идут напрямую (in-memory модель больше не держит display-wire). `PipelineModel.add_wire` display-ветка ([model.py:209](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/model.py#L209)) + `remove_display` каскад display-wire — упростить/удалить (display-wire больше нет).

**5. ADR** «display = binding, не wire» — `multiprocess_prototype/domain/DECISIONS.md` (или frontend/pipeline DECISIONS): фиксирует binding-представление, fan-out по паре, рендеринг из `displays`. Запустить `python -m scripts.sync` если индекс ADR затронут.

**Step 0 (pre-investigation, обязателен перед кодом):** подтвердить выбор scene-API (`load_from_data` расширить vs `add_display_node` поэлементно); проверить, как `add_edge` соединяется с `DisplayNodeItem.input_port_pos()` (порт «frame»); убедиться, что `gui_positions` сохраняют позицию display-бокса (ключ = display_id box_id).

**Файлы (prod):** `domain/commands.py` (UnbindDisplay+display_id), `domain/events.py` (DisplayUnbound), `domain/entities/project.py` (_apply_unbind_display), `domain/__init__.py`; `frontend/widgets/tabs/pipeline/graph/graph_scene.py` (add_display_node/load_from_data), `presenter.py` (_topology_to_graph + 3 мутации + reload), `model.py` (display-wire упрощение), `io.py` (конвертер), `tab.py` (если меняется сигнатура load); ADR-файл.

**Тесты:**
- domain: `UnbindDisplay(node_id, display_id)` снимает ТОЛЬКО нужную пару (fan-out: 2 binding на один node_id → unbind одного оставляет второй); bind-dup → DomainError/idempotent.
- presenter (реальный orchestrator+store+QtEventBus): `add_wire`-to-display → `BindDisplay` в repo (персист, desync-fix); remove display-box → `UnbindDisplay` каскад; undo/redo round-trip.
- **scene-рендеринг (НОВОЕ, закрывает находку #5):** после reload display-узлы есть на scene как `DisplayNodeItem` + binding-ребро `source→box`; fan-in (2 source→1 box) = 2 ребра 1 бокс; fan-out (1 source→2 box) = 2 бокса.
- io round-trip: `graph_to_blueprint`/`blueprint_to_graph` сохраняют bindings без wire-конвертера; обратная совместимость со старыми рецептами (display_bindings формат не меняется на диске).

**Acceptance criteria:** — реализовано 2026-05-29 (verify ✓, ожидает reviewer)
- [x] `UnbindDisplay` keyed по паре `(node_id, display_id)`; fan-out не сносит лишние bindings (`test_unbind_display_fan_out_keeps_others`, `test_bind_display_fan_out_allowed`, `test_bind_display_duplicate_pair_raises`)
- [x] display output→box идёт через `dispatch(BindDisplay)`, удаление — `dispatch(UnbindDisplay)`; персистятся (`TestDisplayBindingDispatch`: bind/remove/fan-in/undo на реальном store) — desync-баг #2 закрыт для display
- [x] `grep "model.add_wire\|remove_display" presenter.py` (display-ветки) → 0; wire-to-display убран из in-memory модели (`remove_display` + display-ветка `add_wire` удалены из model.py)
- [x] **display-боксы рендерятся на scene** (`DisplayNodeItem`) из `topo["displays"]` при load И reload; binding-ребро source→box (`TestDisplaySceneRendering`: box, edge, fan-in 1 box/2 edges, fan-out 2 boxes)
- [x] undo/redo display-команд через `services.commands` (`test_bind_undo`; snapshot-undo)
- [x] io.py конвертер схлопнут (displays↔bindings напрямую); рецепты на диске — формат не изменён (`test_io_roundtrip.py` зелёный, node_id=source endpoint)
- [x] ADR «display = binding» написан — `multiprocess_prototype/domain/DECISIONS.md` (DOM-001); индекс framework не затронут → `scripts.sync` не нужен
- [x] `python -m pytest multiprocess_prototype/` **2039 passed, 3 skipped**; ruff clean; sentrux `check_rules` **9/9** (quality 7133, без регрессии)
- [ ] live boot-smoke Pipeline (qt-mcp/ручной) — **НЕ выполнен** (qt-mcp недостижим до дочернего процесса, known caveat фазы как G.1/G.3/G.4.2); рекомендован перед merge ([[feedback-qt-mcp-smoke-verification]])
- [x] Commit с `Refs: phase-g.md`, `Layer: mixed` (domain+prototype+docs) — reviewer **APPROVED** (4 nit'а, 3 закрыты: get_node тип, coalesce-undo ребиндинга, комментарий; #2 strict-unbind → next-iteration)

**Out of scope:** FIELD_SET (G.4.3); recipe/HistoryPresenter/удаление action_bus accessor (G.4.4); гранулярные scene-апдейты из `DisplayBound`/`DisplayUnbound` (G.6 — пока full reload); интерактивное создание display-бокса с нуля без источника (если в v3 не было — не добавлять, только bind существующих каналов).
**Edge cases:** один display_id привязан к нескольким источникам (fan-in) → один бокс, N рёбер; удаление source-процесса (RemoveProcess) уже каскадит display-bindings через `find_display_bindings_for` (G.4.2, не дублировать); пустой `displays` → нет боксов; `gui_positions` для нового бокса отсутствует → auto-layout.
**Риск:** **HIGH** — живой editor + НОВЫЙ слой рендеринга (ранее не существовавший) + domain-модель + undo/redo. Митигация: Step 0 pre-investigation, scene-тесты на реальной QGraphicsScene, live-smoke перед merge, snapshot-undo сохраняет семантику, формат диска не меняется.
**Module contract:** public-api-change (domain `UnbindDisplay` сигнатура — breaking для вызовов с 1 арг; scene `add_display_node`/`load_from_data` additive); behaviour-change (display рендерится впервые).

**Открытый под-вопрос (не блокирует):** реально ли нужен fan-out (1 выход → N экранов) или достаточно fan-in (кейс «разные стадии → разные дисплеи»). Идентичность по паре покрывает оба — решение от ответа не зависит.

---

### Task G.4.3 — FIELD_SET → SetPluginConfig (только Pipeline Inspector)

> **DESIGN LOCKED** (владелец 2026-05-29, обсуждение): scope = **только Pipeline Inspector** (карточки параметров ВЫБРАННОЙ ноды под графом — `NodeInspectorPanel`). «Карточки всех плагинов» НЕ нужны — только выбранный.
> Вкладка **Plugins = превью/песочница без привязки к топологии** → в домен НЕ тащим, только убираем мёртвую `bus.execute`-ветку (dead-code cleanup). **Settings/System** (конфиг приложения) и **Roles** (auth-домен) — вне scope G.4.3. Идея «убрать/объединить вкладку Plugins с Pipeline» — отдельная UI-задача после Phase G (зафиксирована как долг ниже).
> **DETAILED** (2026-05-29 после grep+investigator-аудита). Премиса старого плана «маппинг register_name → (process, plugin_index)» **оказалась неактуальной для in-scope части** — см. находки.

**Level:** Senior (teamlead — живой inspector field-editing + возможная additive-правка центрального orchestrator), затем reviewer
**Assignee:** teamlead (после approval — реализация)
**Goal:** Перевести field-editing Pipeline Inspector (`_on_inspector_field_changed`) с прямого `rm.set_value` на `dispatch(SetPluginConfig(...))` — добавляя персист в editor-топологию + undo/redo, сохраняя работающий IPC и плавность UI. Убрать мёртвую `bus.execute`-ветку field_set во вкладке Plugins.

#### Audit-находки (grep+read 2026-05-29, file:line)

1. **IPC уже работает через `rm`.** `rm.set_value(process_name, field, value)` ([manager.py:329](../../multiprocess_framework/modules/registers_module/core/manager.py#L329)) — алиас `set_field_value` ([manager.py:147-184](../../multiprocess_framework/modules/registers_module/core/manager.py#L147)), который при наличии `send_callback` резолвит dispatch-targets и **шлёт IPC в живой процесс**. ⇒ отдельный `TopologyBridge.on_field_set` дёргать НЕ надо. Не хватает только domain-части (персист + undo).
2. **Маппинг тривиален.** В pipeline-контексте регистр keyed по **`process_name`** (= node_id): inspector берёт поля `rm.get_fields(process_name)` ([inspector_panel.py:531](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py#L531)), сигнал `field_changed(process_name, field, value)` ([inspector_panel.py:59](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py#L59), эмиттер с `_current_process`). ⇒ `SetPluginConfig(process_name=<сигнал>, plugin_index=0, field, value)`. Никакого reverse-маппинга register→coordinate (он был нужен только для каталожной вкладки Plugins).
3. **Текущий путь** ([presenter.py:116-146](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L116)): `_on_inspector_field_changed` → `rm.set_value`. Нет dispatch, нет save в repo, нет undo. ⇒ значение поля **не попадёт в рецепт** при сохранении и не откатывается.
4. **🔴 undo ломает синхронизацию `rm`.** Orchestrator `_restore` ([command_dispatcher.py:198-207](../../multiprocess_prototype/adapters/dispatch/command_dispatcher.py#L198)) при undo/redo переигрывает только `TopologyReplaced` (full reload), granular-события (`PluginConfigChanged`) — НЕ переигрывает (строки 203-204). А inspector читает значения из `rm` (`rm.get_fields`). ⇒ если поле редактируется через domain, а `rm` синхронится только на прямую правку — после undo `rm` (и форма, и живой процесс) останутся со старым значением. **Синхронизация `rm` из домена обязана работать и на undo.**
5. **Reload-регрессия.** Store публикует `TopologyReplaced` на КАЖДЫЙ save → presenter делает full scene reload ([presenter.py:604](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L604)). Сейчас field-edit делает `rm.set_value` БЕЗ reload (плавно). Наивный dispatch → мерцание/потеря фокуса при slider-drag (десятки правок/сек).
6. **Plugins dead-ветка** ([_sections.py:242-262](../../multiprocess_prototype/frontend/widgets/tabs/plugins/_sections.py#L242)): `_on_field_changed` → `bus.execute(field_set_timed)`, но `_get_bus()` = `getattr(services.commands, "action_bus", None)` = **None** → `if bus is None: return`. Правки молча теряются (prod-баг). Каталог, привязки к процессу нет → домену там делать нечего.

#### Целевая архитектура (унификация с G.4.2)

```
Inspector field_changed(process, field, value)
  → presenter._on_inspector_field_changed:
      with _suppress:                                  # гасит СВОЙ full-reload (граф не меняется)
          services.commands.dispatch(
              SetPluginConfig(process, 0, field, value),
              coalesce_key=f"set_config:{process}:{field}")  # slider-burst → 1 undo-запись
  → orchestrator: Project.apply → topology_repo.save → publish TopologyReplaced + PluginConfigChanged
  → rm-sync listener (НЕ suppressed) → rm.set_value(process, field, value) → IPC в живой процесс
undo/redo → orchestrator._restore → (см. Решение по rm-sync) → rm синхронится → IPC + форма
```

**Editor-топология (domain) = SSOT** (персист в рецепт + undo). `rm` = runtime-проекция (форма читает + IPC). Один слушатель синхронит проекцию из домена.

#### Решение по rm-sync (Step 0 финализирует) — два варианта

- **Вариант Y1 (рекомендуемый, event-driven, precise):** rm-sync listener подписан на **`PluginConfigChanged`** → `rm.set_value(e.process_name, e.field, e.value)`. Для undo/redo — расширить orchestrator: `_restore` диффит config `current` vs `target` и **переигрывает `PluginConfigChanged`** по изменившимся полям (additive-правка центрального orchestrator, малая, покрыта тестом). Плюс: точечно, без сканов, IPC только на реальные изменения. Минус: трогает orchestrator (additive).
- **Вариант Y2 (fallback, zero-orchestrator-change):** rm-sync listener подписан на **`TopologyReplaced`**, реконсилит config домена против текущих значений `rm` (итерация `topology.processes[*].plugins[0].config` vs `rm.get_fields(process)`), шлёт `rm.set_value` только на диффы. Один подписчик покрывает edit/undo/redo/recipe-apply единообразно, orchestrator не трогаем. Минус: скан топологии на каждый save (дёшево — топологии маленькие).

> Step 0 выбирает Y1 vs Y2 по факту (предпочтение — Y1, если diff-on-restore выходит чистым; иначе Y2). Оба чистые, не костыли. Решение зафиксировать комментарием + строкой в этом плане.

**Где вешать listener:** composition root `frontend/app.py` рядом с существующей подпиской bridge (`event_bus.subscribe(TopologyReplaced, lambda _e: topology_bridge.on_topology_changed())`, ~app.py:446) — там доступны и `event_bus`, и `registers_manager`. Listener — отдельный подписчик, НЕ зависит от `_suppress` презентера.
**Порядок подписчиков (reviewer iter1 #3, задокументировать комментарием при wiring):** EventBus вызывает handler'ы в порядке регистрации. orchestrator публикует `TopologyReplaced` (шаг 4, `save`) ДО granular `PluginConfigChanged` (шаг 6). ⇒ при field-set: `TopologyReplaced` → presenter reload (suppressed) + bridge cache reset → затем `PluginConfigChanged` → rm-sync → IPC. Порядок корректен, но зафиксировать в комментарии, чтобы не сломать перестановкой.

**Step 0 (pre-investigation, обязателен перед кодом):**
1. Выбрать Y1 vs Y2 (прочитать `_restore` + прикинуть config-diff helper для Y1). **Для Y1 (reviewer iter1 #2):** `_restore(target)` сейчас принимает только target, а config-diff требует ДОСТУПА к current project ДО save+set. Проверить: либо взять `current = self._holder.get()` в начале `_restore` перед `save`, либо расширить signature `_restore(target, *, previous=None)`. Эмитить `PluginConfigChanged` по дифф-полям ПОСЛЕ `save`+`set` (порядок как в `dispatch`).
2. Подтвердить, что `rm` (RegistersManager) доступен в `app.py` на момент wiring (он строится для RuntimeDeps, G.2) — проверить порядок сборки.
3. Подтвердить контракт `_suppress`-обёртки presenter ([presenter.py:243-252](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L243)) — что full-reload в `_on_topology_replaced` корректно гасится при синхронном dispatch.
4. Проверить, что field_changed приходит ТОЛЬКО для plugin-config полей (а `target_process`/`display_id` идут по своим сигналам — `target_process_changed`/`display_id_changed`, presenter.py:113-114), чтобы `SetPluginConfig` не получил не-config поле.

**Файлы (prod):**
- `frontend/widgets/tabs/pipeline/presenter.py`:
  - `_on_inspector_field_changed(process_name, field_name, new_value)` — **на входе** `if self._suppress: return` (по аналогии с `_on_target_process_changed`:158 / `_on_display_id_changed`:203 — защита от ре-входа: listener обновит `rm` → rm-observer → signal → re-enter); убрать прямой `rm.set_value`; обернуть dispatch в `_suppress`-guard (`with self._block_signals():`) и `dispatch(SetPluginConfig(process_name, plugin_index=0, field=field_name, value=new_value), coalesce_key=f"set_config:{process_name}:{field_name}")`; DomainError (process/index не найден) → лог + graceful return (не падать). Убрать TODO G.4.3-комментарии (124-128). **(reviewer iter1 #1)**
- `frontend/app.py` — добавить rm-sync listener (Y1: на `PluginConfigChanged`; Y2: на `TopologyReplaced` с реконсилом) рядом с bridge-подпиской.
- (только Y1) `adapters/dispatch/command_dispatcher.py` — `_restore` (или `undo`/`redo`) переигрывает `PluginConfigChanged` по config-диффу `current` vs `target`. Helper-дифф — domain-чистый (по `topology.processes[*].plugins[*].config`).
- `frontend/widgets/tabs/plugins/_sections.py` — убрать мёртвую `_on_field_changed` → `bus.execute` ветку + `_get_bus()` + `_on_bus_changed`/`bus_change_callback` (если они только под мёртвый bus); `field_changed.connect` — отцепить или оставить no-op с комментарием «Plugins = превью, без topology-привязки (G.4.3)». Проверить, не сломается ли `SectionWithEvents`-контракт (`bus_change_callback`).

**Тесты:**
- `pipeline/tests/test_inspector.py` (+ `_helpers.py`): мутация поля через реальный orchestrator+store+QtEventBus. Проверить: (a) `field_changed(process, field, value)` → `SetPluginConfig` → значение в `services.topology.load()` (персист, чего раньше НЕ было); (b) `rm.set_value` вызван listener'ом → значение в `rm` (форма консистентна) + IPC-callback дёрнут (mock send_callback); (c) full scene reload НЕ происходит на field-edit (`_suppress` сработал — счётчик reload не вырос / scene не перестроена); (d) **undo/redo**: после undo и `rm`, и domain-config откатаны (round-trip на реальном store) — закрывает находку #4; (e) slider-burst (N правок одного поля) → одна undo-запись (coalesce_key).
- (только Y1) `adapters/tests/test_command_dispatcher.py`: undo field-config переигрывает `PluginConfigChanged` (подписчик получает откатанное значение).
- `plugins/tests/`: после удаления dead-ветки field-edit во вкладке Plugins ничего не ломает (секции строятся, permission-gating цел); регрессия отсутствует.

**Acceptance criteria:** — ✅ DONE (2026-05-29, `5dc97751` + nit, Y1, reviewer **APPROVED** — 1 non-blocking nit закрыт: plugin_index=0 assumption задокументирован)
- [x] `grep "rm.set_value" pipeline/presenter.py` (в `_on_inspector_field_changed`) → 0 (только в docstring; прямой путь убран, rm синхронится listener'ом)
- [x] field-edit Pipeline Inspector → `dispatch(SetPluginConfig)`; значение **персистится** в topology_repo (`test_field_edit_persists_in_topology`) — находка #3 закрыта
- [x] IPC в живой процесс работает (rm-sync listener `app.py` → `registers_manager.set_value` → send_callback)
- [x] **undo/redo field-config**: и domain, и `rm` откатываются согласованно (`test_undo_redo_field_roundtrip`, `test_undo_field_emits_plugin_config_changed`; orchestrator `_emit_config_diff` на реальном store) — находка #4 закрыта
- [x] full scene reload НЕ происходит на field-edit (`test_field_edit_no_scene_reload`, `_suppress`-guard, находка #5); slider-burst = одна undo-запись (`test_coalesce_slider_burst`)
- [x] `grep "bus.execute\|_get_bus\|action_bus" plugins/_sections.py` → 0 (только в комментарии; dead-ветка field_set + tab.py bridge убраны)
- [x] `python -m pytest multiprocess_prototype/` **2048 passed, 3 skipped, 0 failed** (+10 тестов); ruff clean; sentrux `check_rules` **9/9**, quality **7133** (без регрессии vs G.4.2b)
- [ ] live boot-smoke Pipeline Inspector (qt-mcp/ручной) перед merge — known caveat фазы как G.1/G.3/G.4.2/G.4.2b ([[feedback-qt-mcp-smoke-verification]])
- [x] Commit `5dc97751` с `Refs: phase-g.md`, `Layer: prototype`, `Why:`+`Tested:`

**Out of scope:**
- Вкладка Plugins как config-surface (она превью, без привязки) — только cleanup dead-ветки.
- **Settings/System** (конфиг приложения, нужна отдельная команда `SetSystemConfig`, не `SetPluginConfig`) и **Roles** (auth-домен) — остаются как есть.
- **NODE_MOVE** (GUI-only) / **RECIPE_APPLY** / удаление `action_bus`-accessor → **G.4.4**.
- Гранулярное scene-обновление из `PluginConfigChanged` (вместо full reload при undo) — **G.6**.
- Multi-plugin процессы (`plugin_index > 0`) — текущая convention = один плагин (AddProcess, G.4.2); задокументировать assumption, не реализовывать.
- «Убрать/объединить вкладку Plugins с Pipeline» — отдельная UI-задача после Phase G.

**Edge cases:**
- DomainError (process/index не найден) при dispatch → лог + graceful return, `rm`/repo не мутированы.
- Поле — не plugin-config (process-метаданные) → приходит по `target_process_changed`/`display_id_changed`, не сюда; убедиться, что `field_changed` несёт только config (Step 0 п.4).
- undo сразу после load (пустой стек) → no-op.
- field-edit во время собственного dispatch — синхронный QtEventBus, `_suppress` гасит reload, listener (отдельный подписчик) НЕ suppressed → синк `rm` происходит.
- Plugins-секция без регистров (`PluginInfoCard` fallback) → нет `RegisterView`, нечего отцеплять.

**Риск:** **MEDIUM** (ниже G.4.2/G.4.2b — граф не трогаем, IPC уже работает). Главные точки: (а) синхронизация `rm` на undo (находка #4 — обязательна, иначе форма/процесс врут); (б) `_suppress` корректно гасит reload без побочных эффектов на другие подписчики; (в) Y1 трогает центральный orchestrator (additive). Митигация: Step 0, тесты на реальном store+EventBus (включая undo round-trip + reload-счётчик), live-smoke перед merge.
**Module contract:** behaviour-change (presenter field-path: direct rm → domain dispatch + listener-sync); public API presenter не меняется. Y1: additive-расширение orchestrator `_restore` (re-emit granular config events).

---

### Task G.4.4 — Domain undo/redo UX + единая шина undo + phantom-cleanup

> **DETAILED** (2026-05-29 после reality-аудита investigator+grep+qex+serena). **Премиса плана уточнена (5-й повтор урока G.2/G.4/G.4.2/G.4.2b/G.4.3):** исходная формулировка G.4.4 («RECIPE_APPLY→ActivateRecipe; HistoryPresenter; удалить мёртвый bridge; судьба `frontend/actions/`») частично устарела — см. находки. Scope **переопределён** под реальность: финализировать domain undo/redo как единственную шину + закрыть НОВЫЙ найденный баг; крупный rip-out `frontend/actions/` отложен (big-bang, brief §8).

**Level:** Senior (teamlead/director — центральный orchestrator + framework layout Protocol + живой MainWindow + 5 табов), затем reviewer
**Assignee:** director-direct (реализация), затем reviewer
**Goal:** Сделать domain `CommandDispatcher` (`services.commands`) **единственной** шиной undo/redo в GUI: подключить кнопки undo/redo (закрыть долг G.4.2), перевести History-вкладку на domain-историю, **устранить конфликт двух параллельных undo** (MainWindow legacy ActionBus vs Pipeline domain), и убрать фантомные обращения `services.commands.action_bus()` (метода нет — всегда None). Без удаления `frontend/actions/` (отложено).

#### Audit-находки (investigator+grep+qex 2026-05-29, file:line)

1. **`services.commands.action_bus()` — ФАНТОМНЫЙ метод.** `CommandDispatcherOrchestrator` ([command_dispatcher.py](../../multiprocess_prototype/adapters/dispatch/command_dispatcher.py)) НЕ имеет `action_bus`. Все **9 call-sites** `getattr(services.commands, "action_bus", None)` всегда дают None → dead-reach: `services/tab.py:51`, `settings/tab.py:51`, `settings/_sections.py:114` (roles), `settings/system/presenter.py:140`, `settings/history/presenter.py:60`. Это «костыль-фантом», который план G.2/G.4 обещал убрать.
2. **🔴 НОВЫЙ БАГ (не было в плане) — два параллельных undo на разных историях.** `MainWindow.set_action_bus(legacy_bus)` ([main_window.py:269-300](../../multiprocess_prototype/frontend/windows/main_window.py#L269)) вешает **глобальные** `QShortcut` Ctrl+Z/Y → `legacy_bus.undo()/redo()` (legacy ActionBus, в prod ПУСТ — через него ничего не execute'ится). А `PipelineTab.keyPressEvent` ([tab.py:361-364](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py#L361)) → `services.commands.undo()/redo()` (domain). Глобальный `QShortcut` (WindowShortcut-контекст) перехватывает Ctrl+Z раньше keyPressEvent виджета → в живом GUI domain-undo Pipeline затеняется пустым legacy-undo. (В тестах не ловится — они зовут handler напрямую; вскрылось бы на live qt-mcp smoke, который отложен во всех G.4.x.)
3. **Кнопки undo/redo disabled (долг G.4.2).** `pipeline/tab.py:118` `enable_undo_redo(None)`. Framework `_AbstractColumnarTabLayout.enable_undo_redo(action_bus)` ([_abstract_columnar.py:69-94](../../multiprocess_framework/modules/frontend_module/widgets/tabs/tab_layouts/_abstract_columnar.py#L69)) ожидает объект с `can_undo/can_redo/undo/redo/add_change_callback`. У orchestrator есть всё, КРОМЕ `add_change_callback` → нельзя передать как есть.
4. **HistoryPresenter в prod показывает ПУСТУЮ таблицу.** [history/presenter.py](../../multiprocess_prototype/frontend/widgets/tabs/settings/history/presenter.py) читает `_get_action_bus()` (фантом) → None → пустой `set_table_data([])`. Domain `services.commands.history(n)` (реальная история `HistoryEntry`: label/command_type/timestamp) не задействован. Формат view — 4 колонки (legacy `Action`), domain `HistoryEntry` — 3 поля.
5. **Legacy ActionBus полностью мёртв в prod.** Все production-формы строят `RegisterView(..., form_ctx=None)` (pipeline inspector:539, plugins:214, system:95) → binding-aware `FormContext.write`-путь (единственный, кто execute'ит FIELD_SET на legacy bus) НЕ задействован. `ctx.action_bus()`/`ctx.form_context()` — НЕТ production-вызовов. system/roles используют фантом (services.commands.action_bus=None), а НЕ `ctx`. ⇒ единственные живые потребители legacy-шины — `window.set_action_bus` (баг #2) и осиротевший `ctx.extras["action_bus"]`.
6. **Удаление мёртвых handlers = big-bang.** `grep` символов (`RecipeApplyHandler/TopologyMutationHandler/V2ActionBuilder/PROCESS_ADD/...`) = **42 файла**, включая framework `actions_module` + ~10 тестов (`test_handlers`, `test_topology_mutation_handler`, framework `test_topology_handler`, forms `*_form_ctx`, `test_action_bus_v2`, `test_phase12_integration`, `test_phase15_smoke`). Рип-аут запрещён brief §8. **Отложено.**
7. **Dead-leftover в Pipeline tab.** `tab.py:210` дублирует `inspector.field_changed.connect(self._on_inspector_field_changed)` (tab-метод [tab.py:346-349](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/tab.py#L346) — только `logger.debug` + stale `# TODO: через ActionBus в Phase 13+`), тогда как реальный dispatch вешает presenter ([presenter.py:113](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L113), G.4.3). Tab-ветка — мёртвый дубль-коннект.

#### Scope-решение (no-big-bang, no-hacks)

**В scope G.4.4 (high-value, low-risk):**
- **A. Observer на orchestrator** — `add_change_callback(cb)`/`remove_change_callback`/`_notify_change()` в `CommandDispatcherOrchestrator`; вызов после `dispatch`/`undo`/`redo`(при True)/`clear_history` (зеркало framework `ActionBus`). Расширить domain `CommandDispatcher` Protocol + `FakeCommandDispatcher` (no-op). Закрывает находку #3.
- **B. Framework структурный Protocol `UndoRedoController`** (`undo()->object`, `redo()->object`, `can_undo()->bool`, `can_redo()->bool`, `add_change_callback(cb)`) в `_abstract_columnar.py`; `enable_undo_redo(controller: UndoRedoController | None)` вместо `ActionBus | None` (program-to-interface; ActionBus и orchestrator удовлетворяют структурно; framework НЕ импортирует prototype). Tighten `BaseTreeNavTab.enable_undo_redo(object|None)` → `UndoRedoController | None`.
- **C. Кнопки undo/redo → domain.** `pipeline/tab.py` `enable_undo_redo(self._services.commands)`; `services/tab.py`, `settings/tab.py` — `bus = services.commands` (убрать фантом-getattr), `bus_change_subscriber=lambda cb: services.commands.add_change_callback(cb)`, `enable_undo_redo(services.commands)`. Глобальная история одна — кнопки во всех табах работают консистентно.
- **D. HistoryPresenter → domain history.** Убрать `_get_action_bus`; `refresh()` ← `services.commands.history(50)` (HistoryEntry → 3-tuple `Время/Тип/Описание`); `clear()` ← `clear_history()`; `save_to_csv()` ← `history(0)` (все). View+section: 3 колонки (`set_table_data(list[tuple[str,str,str]])`, `_HISTORY_COLUMNS=["Время","Тип","Описание"]`, resize-modes). Закрывает находку #4.
- **E. Dual-undo fix (находка #2).** `MainWindow.set_action_bus` → переименовать в `set_undo_controller(controller)`; `_on_undo/_on_redo` → `controller.undo()/redo()` (bool) + generic статус («Отменено»/«Повторено»). `app.py` — `window.set_undo_controller(ctx.app_services.commands)`. Убрать дублирующие Ctrl+Z/Y из `PipelineTab.keyPressEvent` (+ мёртвые ветки `_on_toolbar_action("undo"/"redo")` + из `_MUTATING_ACTIONS`) — теперь глобально через MainWindow→domain. **Единая шина undo.**
- **F. Phantom-cleanup (находка #1).** `_sections._roles_factory` → `RolesPanel(auth_ctx, None)` + коммент «ROLE_UPDATE — auth-домен, миграция отложена». `system/presenter._get_action_bus` → `return None` + коммент «SystemSettings field-undo отложен — нужна `SetSystemConfig`; у `services.commands` нет `action_bus()`». Методы `on_field_changed_action_bus`/`on_bus_undo_redo_sync` — documented no-op (не удалять — section-проводка вне scope).
- **G. Dead-leftover (находка #7).** Убрать `tab.py:210` дубль-коннект + tab-метод `_on_inspector_field_changed` (presenter уже dispatch'ит, G.4.3).

**Отложено (явный долг Phase G+, НЕ трогать в G.4.4):**
- **RECIPE_APPLY → ActivateRecipe (live).** Production recipe-apply идёт `RecipesPresenter.on_set_active → store.set_active → RecipeManager → engine` + IPC `replace_blueprint_fn` ([recipes/presenter.py:275](../../multiprocess_prototype/frontend/widgets/tabs/recipes/presenter.py#L275)), МИМО domain. Domain `ActivateRecipe`/`_apply_activate_recipe` есть, но НЕ dispatch'ится; миграция требует event-driven IPC-hook (`RecipeActivated → replace_blueprint`) — отдельная задача (риск IPC).
- **Удаление `frontend/actions/`** (legacy ActionBus + dead handlers `RecipeApplyHandler`/`TopologyMutationHandler` + `V2ActionBuilder`-методы + `action_types`-константы) — big-bang (находка #6). Legacy-шина остаётся как инфраструктура отложенных доменов (forms binding, roles auth, system settings, node-move GUI-undo). `create_action_bus` в app.py сохраняется (отвязан от undo через E), документирован.
- **SystemSettings undo** (нужна domain-команда `SetSystemConfig`), **ROLE_UPDATE** (auth-домен, своя шина/прямой `auth_manager`), **NODE_MOVE** (GUI-only, undo позиций не реализован — и не нужен), **forms FormContext binding-aware** — отдельные доменные миграции.

**Файлы (prod):**
- `adapters/dispatch/command_dispatcher.py` — observer (A).
- `domain/protocols/command_dispatcher.py` — `add_change_callback` в Protocol (A).
- `domain/tests/_fakes.py` — `FakeCommandDispatcher.add_change_callback` no-op (A).
- `multiprocess_framework/modules/frontend_module/widgets/tabs/tab_layouts/_abstract_columnar.py` — `UndoRedoController` Protocol + `enable_undo_redo` (B).
- `multiprocess_framework/.../base_tree_nav_tab.py` — annotation tighten (B, опц.).
- `frontend/widgets/tabs/pipeline/tab.py` — enable_undo_redo(commands) (C); keyPressEvent/`_on_toolbar_action`/`_MUTATING_ACTIONS` (E); dead-leftover (G).
- `frontend/widgets/tabs/services/tab.py`, `settings/tab.py` — bus=services.commands (C).
- `frontend/widgets/tabs/settings/history/presenter.py` + `view.py` + `section.py` — domain history + 3 колонки (D).
- `frontend/windows/main_window.py` — set_undo_controller (E).
- `frontend/app.py` — window.set_undo_controller(commands) + коммент о retained legacy bus (E).
- `frontend/widgets/tabs/settings/_sections.py`, `settings/system/presenter.py` — phantom-cleanup (F).

**Тесты:**
- `adapters/tests/test_command_dispatcher.py` — `add_change_callback` вызывается после dispatch/undo/redo/clear_history; remove работает; исключение в одном cb не валит остальные.
- `frontend/widgets/tabs/pipeline/tests/` — кнопки undo/redo enabled после dispatch (через реальный orchestrator); refresh enable-состояния по change-callback.
- `settings/history/tests/test_history_presenter.py` — refresh из `services.commands.history` (реальный orchestrator+store): строки = HistoryEntry, 3 колонки; clear → clear_history; save_to_csv пишет реальные записи; пустая история → save/clear disabled.
- `frontend/tests/` — MainWindow.set_undo_controller: Ctrl+Z/Y → controller.undo/redo (тест на реальном orchestrator или Fake с счётчиком); единый путь (нет legacy-undo).
- `settings/tests/` — settings/services tab строится с `services.commands` как bus (без фантома); roles_factory(None) не падает.

**Acceptance criteria:** — ✅ DONE 2026-05-29 (`171f1d8f`, verify ✓, reviewer **APPROVED**)
- [x] `grep -rn 'getattr(.*services.commands.*action_bus' multiprocess_prototype/` → 0 (фантом убран везде; остался только legacy `ctx.action_bus()` — другая шина).
- [x] `CommandDispatcherOrchestrator.add_change_callback` есть, вызывается после dispatch/undo(True)/redo(True)/clear_history; domain Protocol + Fake расширены (pyright 0). Тесты: `test_change_callback_*` (fires, not-on-empty, remove, exception-isolated).
- [x] Кнопки undo/redo в Pipeline (и services/settings) **enabled** через `enable_undo_redo(services.commands)`; refresh по change-callback (layout `_refresh_undo_redo` — не мутирует историю, цикла нет).
- [x] History-вкладка показывает domain-историю (3 колонки Время/Тип/Описание); clear → `clear_history`; CSV-экспорт (`history(0)`=все). `test_history_presenter.py` переписан.
- [x] **Единая шина undo:** MainWindow Ctrl+Z/Y → `services.commands` (`set_action_bus`→`set_undo_controller`); дубль Ctrl+Z/Y из PipelineTab.keyPressEvent + мёртвые undo/redo-ветки `_on_toolbar_action` убраны. Конфликт #2 закрыт. Тест `test_set_undo_controller_delegates_undo_redo`.
- [x] dead-leftover `tab._on_inspector_field_changed` + дубль-коннект убраны (field-edit dispatch'ится presenter'ом, G.4.3).
- [x] `frontend/actions/` НЕ тронут (handlers/builder/bus_factory целы); legacy bus в app.py сохранён + документирован как отложенная инфраструктура (forms/roles/system).
- [x] `python -m pytest multiprocess_prototype/` → **2055 passed, 3 skipped, 0 failed** (+7 vs G.4.3 2048); ruff clean; pyright 0 errors (7 warnings — pre-existing `_sections.py` object→Protocol + DiffScrollTabLayout→TabLayoutProtocol); sentrux `check_rules` **9/9**, quality **7134** (+1). NB: 2 framework `test_controls_v2_hooks` падают из корня (`patch("frontend_module...")` короткий путь) — pre-existing, проходят из `multiprocess_framework/modules`.
- [ ] live boot-smoke (qt-mcp/ручной) — **НЕ выполнен** (qt-mcp недостижим, known caveat фазы); особенно важен (баг #2 виден только в живом GUI) — рекомендован перед merge ([[feedback-qt-mcp-smoke-verification]]).
- [x] Commit `171f1d8f` с `Refs: phase-g.md`, `Layer: mixed` (framework+prototype), `Why:`+`Tested:`.

**Reviewer (Opus) APPROVED** — без блокеров; согласие со scope-решением (defer handler-deletion 42-файла + RECIPE_APPLY live = big-bang). Отмечено: размещение `UndoRedoController` в `tab_layout_protocol.py` (рядом с `TabLayoutProtocol`), а не в `_abstract_columnar.py` (как в task-spec) — более чистое (Protocol рядом с Protocol); observer-isolation + dual-undo fix элегантны; no-op плейсхолдеры (system) приемлемы как deferred.

**Out of scope:** RECIPE_APPLY live-миграция; удаление `frontend/actions/`/dead handlers; SetSystemConfig; ROLE_UPDATE auth; NODE_MOVE undo; FormContext binding-path; гранулярные scene-апдейты (G.6).
**Edge cases:** пустая история → undo/redo no-op (False), кнопки disabled, History-таблица пуста, save/clear disabled; change-callback с исключением в одном подписчике не валит остальные; QShortcut Ctrl+Z при фокусе в QLineEdit — поведение как с legacy (глобальный перехват, не регрессия); undo сразу после load (стек пуст).
**Риск:** **MEDIUM** — трогает центральный orchestrator (additive observer), framework layout Protocol (структурный, обратно совместим), живой MainWindow shortcuts + 5 табов. Главное: (а) рефреш кнопок не должен зацикливаться (change-callback → refresh не мутирует историю); (б) единый undo-путь не ломает per-tab поведение (глобальная история — by design); (в) live-smoke важен (#2). Митигация: тесты на реальном orchestrator, структурный Protocol сохраняет ActionBus-совместимость, явный defer big-bang.
**Module contract:** public-api-change (additive: domain `CommandDispatcher.add_change_callback`, framework `UndoRedoController` Protocol, `enable_undo_redo` тип; `MainWindow.set_action_bus`→`set_undo_controller` rename — внутренний API); behaviour-change (единая шина undo; History на domain).

---

## Follow-up из независимого ревью G.4 (2026-05-29)

> Повторное независимое ревью всей G.4 (3 reviewer-агента Opus + ручная проверка ядра undo/redo, rm-sync diff, dual-undo): **APPROVED, 0 блокеров.** Подтверждены snapshot-undo/redo (frozen Project), rm-sync diff на undo (Y1), fan-out identity по паре `(node_id, display_id)`, единая шина undo (баг #2 закрыт), phantom-cleanup (0 `getattr action_bus`), слои framework→prototype не нарушены. Тесты 208 (ядро) + 345 (pipeline) + 24 (cross-tab) зелёные. Ниже — единственная содержательная находка (LOW) и сделанная мелкая правка.

**Сделано в ходе ревью:** [presenter.py `_on_inspector_field_changed`](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/presenter.py#L133) — переписан вводящий в заблуждение комментарий re-entry guard (описывал несуществующий путь `rm-observer → field_changed → re-enter`; проводки rm→inspector нет). Comment-only, 63 теста зелёные, ruff clean.

**Нит-долг (low, не блокирует, можно закрыть пакетно при случае):** `_describe()` `if val:` → `is not None` ([command_dispatcher.py:53](../../multiprocess_prototype/adapters/dispatch/command_dispatcher.py#L53)); Protocol `CommandDispatcher` без `remove_change_callback`; коммент про `min(len)` plugin-tail в `_emit_config_diff`; коммент-контракт «change-callback не мутирует историю»; idempotent-no-op `_apply_unbind_display` (асимметрия с `DisconnectWire`) — задокументировать; подписка `_topology_sub` без `unsubscribe`/dispose (утечки нет при текущем lifetime таба, всплывёт при динамическом создании табов).

### Task G.4.5 (deferred) — Сохранение выделения ноды через scene reload + refresh inspector

**Level:** Senior (teamlead — живой Pipeline editor, центральный путь reload)
**Assignee:** teamlead (после approval), затем reviewer
**Goal:** При undo/redo (и любом dispatch с reload) сохранять выделение ноды и обновлять inspector «на месте», а не сбрасывать в placeholder.
**Контекст (находка ревью, severity LOW — данные корректны, UX-полировка):** `_on_topology_replaced` → `load_scene_with_ports` → `graph_scene.load_from_data` → `clear_all()` ([graph_scene.py:60](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/graph/graph_scene.py#L60)) чистит сцену → теряется выделение → `tab._on_selection_changed` → `inspector.clear()`. Карточки читают значения из `rm` (синхронного на undo через `PluginConfigChanged`), поэтому после переселекта значение корректно — но без переселекта форма очищается. `inspector_panel.update_field` ([inspector_panel.py:588](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/inspector/inspector_panel.py#L588), помечен «programmatically (undo/redo)») — **мёртвый код**, не вызывается. Поведение общее для любого undo (топология тоже), не специфично для поля.
**Files:** `pipeline/presenter.py` (`_on_topology_replaced` — capture selected node_ids ДО reload, restore ПОСЛЕ), `pipeline/tab.py` / `graph/graph_scene.py` (API восстановления выделения). Решить судьбу `update_field` (подключить для in-place refresh либо удалить как dead code).
**Acceptance criteria:**
- [ ] undo/redo сохраняет выделение существующей ноды; inspector показывает откатанные значения без переселекта
- [ ] re-select удалённой ноды (после undo RemoveProcess) → graceful (placeholder, не падение)
- [ ] `update_field` либо подключён (in-place refresh), либо удалён как dead code
- [ ] pytest pipeline зелёные + 🔴 **live qt-mcp boot-smoke ОБЯЗАТЕЛЕН** — поведение видно только в живом GUI ([[feedback-qt-mcp-smoke-verification]])
**Риск:** MEDIUM — трогает центральный путь reload (каждый dispatch/undo/redo). Митигация: тесты на реальной QGraphicsScene + обязательный live-smoke.
**Out of scope:** гранулярные scene-апдейты вместо full reload (G.6). Может быть свёрнут в G.6 (UX), если та берётся раньше.

---

## Wave 6 — G.5 (AppContext removal)

> Детализировано 2026-05-29 после reality-аудита (grep+read композиционного корня `app.py`). Премиса аудита 2026-05-28 (audit п.5) частично устарела — см. находки. Scope **M-L** (composition root + 3 consumer + 2 удаления + ~6 тестов). Декомпозиция на 3 под-волны (no-big-bang, brief §8).

### Audit-уточнение (2026-05-29, grep+read реальности)

1. **AppContext после G.4 = 3 роли:** (a) `ctx.extras` — scratch-dict аккумуляции 15 зависимостей в `app.py`, читается `build_app_services(ctx)`; (b) carrier `ctx.app_services`; (c) accessor-фасад (`ctx.auth` + runtime-аксессоры) для `tab_factory` + `app.py`.
2. **`app.py` уже держит все зависимости в локальных переменных** (`_plugin_manager`, `_service_registry`, `event_bus`, `topology_store`, `bindings`, `topology_bridge`, `_recipe_manager`, `_auth_manager`, `_auth_state`, `action_bus`, `registers_manager`). `ctx.extras[...]` = копия локалов. `run_gui` блокируется на `app.exec()` → локалы живы весь lifetime приложения. ⇒ «GC-hold» назначение extras **избыточно**.
3. **`build_app_services(ctx)` читает 8 ключей extras** (event_bus, topology_store, plugin_registry, display_registry, recipe_manager, service_registry, registers_manager, auth_state) + `ctx.config`. Единственный реальный bridge extras→AppServices.
4. **TabFactory читает ctx:** `ctx.app_services` ([tab_factory.py:191,230](../../multiprocess_prototype/frontend/tab_factory.py#L191)), `ctx.auth` (244,264 permissions + 313 RuntimeDeps), `_build_runtime_deps` → `ctx.topology_bridge()/bindings()/plugin_manager()/registers_manager()/command_sender`.
5. **InterfaceSection (`ctx.process` для `_restart_ui`) — МЁРТВ в prod:** [`_sections.py:165`](../../multiprocess_prototype/frontend/widgets/tabs/settings/_sections.py#L165) инстанцирует `InterfaceSection(ctx=None)` → кнопка «Обновить UI» = graceful no-op (logs warning) с D.5.
6. **Фантом/GC-hold ключи без prod-потребителей** (уходят с ctx без миграции): `command_catalog` (accessor есть, 0 вызовов), `tab_factory` (self-ref, 0 чтений), `action_bus` (только в `ctx.form_context()` — 0 prod-вызовов, G.4.4 #5), `service_state_adapter`/`recipe_state_adapter` (locals достаточно).
7. **`process._app_context` ([app.py:538](../../multiprocess_prototype/frontend/app.py#L538)) — write-only:** 0 prod-читателей. Удаляется.
8. **`ctx.auth` property** строит `AuthContext` из extras (auth_manager+auth_state). После G.5 — app.py строит `AuthContext(manager=_auth_manager, state=_auth_state, audit=...)` напрямую из локалов.

### Решение по InterfaceSection (без костылей)
Восстановить мёртвую фичу через **узкий callback**, не таща весь `GuiProcess`: `RuntimeDeps.request_ui_restart: Callable[[], None] | None`. app.py: `request_ui_restart=lambda: (setattr(process, "_restart_ui", True), app.quit())`. `InterfaceSection(request_ui_restart=...)` вместо `ctx`; None → graceful no-op (как сейчас). Interface Segregation — секция знает только «перезапусти UI», не GuiProcess.

### Декомпозиция G.5 (no-big-bang)

| Под-волна | Описание | Scope | Зависит | Статус |
|---|---|---|---|---|
| **G.5.1** | `build_app_services` отвязан от AppContext: frozen `AppServicesDeps` (explicit deps). app.py передаёт локалы напрямую; фабрика не импортирует AppContext, не читает extras. | M (factory + app.py + 2 теста) | — | **DETAILED** |
| **G.5.2** | TabFactory + InterfaceSection отвязаны от ctx: `TabFactory(app_services, auth_ctx, runtime)`; app.py строит RuntimeDeps + AuthContext напрямую; InterfaceSection ← `request_ui_restart` callback (восстановление фичи #5). | M (tab_factory + _sections + interface/section + app.py + тесты) | G.5.1 | **DETAILED** |
| **G.5.3** | Удаление: `app_context.py`, `_deprecated_extras.py`, `build_app_context`, `process._app_context`, все `ctx.extras[...]` из app.py (только локалы). Delete `test_app_context`/`test_extras_deprecation`, rewrite остальные. ARCHITECTURE.md. | M (2 delete + app.py cleanup + ~4 теста) | G.5.2 | **DETAILED** |

---

### Task G.5.1 — build_app_services отвязан от AppContext (AppServicesDeps)

**Level:** Senior (teamlead/director — центральный composition step + signature change)
**Goal:** `build_app_services` перестаёт зависеть от `AppContext`/`ctx.extras` — принимает explicit frozen `AppServicesDeps`. Снимает coupling factory→AppContext (предпосылка удаления AppContext в G.5.3), без изменения собранного AppServices.

**Файлы (prod):**
- `frontend/app_services_factory.py` — NEW frozen `AppServicesDeps` dataclass (event_bus, topology_store, plugin_registry, display_registry, service_registry, registers_manager — required; recipe_manager, auth_state — `| None = None`; config: dict). `build_app_services(deps: AppServicesDeps) -> AppServices`: читать поля deps вместо `ctx.extras.peek*`; сохранить fail-loud RuntimeError для `recipe_manager is None` / `auth_state is None`. Убрать `if TYPE_CHECKING: import AppContext`.
- `frontend/app.py` — `_recipe_manager = None` инициализировать ДО try (3g); собрать `AppServicesDeps(...)` из локалов; `ctx.app_services = build_app_services(deps)`. `ctx.extras[...]` оставить как есть (удаляются в G.5.3).

**Тесты:**
- `frontend/tests/test_app_services_factory.py` — фикстура строит `AppServicesDeps` напрямую (mock-deps), без `build_app_context`. Fail-loud: оставить 2 теста (recipe_manager=None → RuntimeError, auth_state=None → RuntimeError); KeyError-on-extras тесты убрать (контракт extras уходит). `TestAppContextAppServicesField` — оставить (тестирует поле AppContext, не factory).
- `frontend/tests/test_phase15_smoke.py` — если зовёт build_app_services — обновить на AppServicesDeps.

**Acceptance criteria:** — ✅ DONE (2026-05-29, `63e303b6`)
- [x] `grep "AppContext\|ctx.extras\|build_app_context" frontend/app_services_factory.py` → 0
- [x] `build_app_services(AppServicesDeps(...))` собирает AppServices с 10 не-None полями (`test_all_10_fields_not_none`)
- [x] fail-loud: recipe_manager/auth_state None → RuntimeError (`test_missing_recipe_manager`/`test_missing_auth_state`)
- [x] dispatch(AddProcess) round-trip через собранный AppServices зелёный (`test_dispatch_add_process`)
- [x] frontend+adapters **446 passed / 2 skipped**; ruff clean; sentrux check_rules **9/9**, quality 7133
- [x] Commit `63e303b6` с `Refs: phase-g.md`, `Layer: prototype`

**Out of scope:** TabFactory/InterfaceSection отвязка (G.5.2); удаление AppContext (G.5.3).
**Edge cases:** recipe-build упал в app.py try → `_recipe_manager=None` → RuntimeError fail-loud (как сейчас).
**Module contract:** public-api-change (signature `build_app_services`: ctx → AppServicesDeps).

---

### Task G.5.2 — TabFactory + InterfaceSection отвязаны от ctx

**Level:** Senior (teamlead/director — живой TabFactory + permission-проводка + composition root)
**Goal:** `TabFactory` принимает `(app_services, auth_ctx, runtime)` вместо `ctx`; app.py строит `RuntimeDeps` + `AuthContext` напрямую из локалов; `InterfaceSection` получает `request_ui_restart` callback (восстановление мёртвой фичи #5). После — `tab_factory.py` не импортирует/не читает AppContext.

**Файлы (prod):**
- `frontend/runtime_deps.py` — поле `request_ui_restart: "Callable[[], None] | None" = None` + docstring.
- `frontend/tab_factory.py` — `__init__(self, app_services, auth_ctx, runtime)` (или `(services, *, auth_ctx, runtime)`); убрать `self._ctx`, `_build_runtime_deps` (runtime приходит готовый); `_apply_permissions`/`_wire_auth_state` читают `auth_ctx` (не `ctx.auth`); `create_tabs/create_tab` используют `self._services` + `self._runtime`.
- `frontend/app.py` — построить `RuntimeDeps(...)` напрямую из локалов (command_sender, topology_bridge, bindings, plugin_manager, registers_manager, auth_ctx, request_ui_restart); `auth_ctx = AuthContext(...)` из `_auth_manager`/`_auth_state`; `TabFactory(ctx.app_services, auth_ctx=auth_ctx, runtime=runtime)`.
- `frontend/widgets/tabs/settings/interface/section.py` — `InterfaceSection(request_ui_restart=None)` вместо `ctx`; `_on_rebuild_ui` зовёт callback.
- `frontend/widgets/tabs/settings/_sections.py:165` — `InterfaceSection(request_ui_restart=runtime.request_ui_restart)` (проводка через section-фабрику; проверить как _interface_factory получает runtime).

**Тесты:** `test_tab_factory.py` (rewrite на app_services+auth_ctx+runtime), `interface/section` тест (callback вызывается / None no-op).

**Acceptance criteria:** — ✅ DONE (2026-05-29, `a4691aaf`)
- [x] `grep "AppContext\|self._ctx\|ctx.auth\|ctx.app_services" frontend/tab_factory.py` → 0 (TabFactory без AppContext)
- [x] permission-фильтрация работает через `auth_ctx` (`test_tab_factory.py` login/logout видимости — 5 permission-тестов зелёные)
- [x] InterfaceSection «Обновить UI» вызывает `request_ui_restart` (фича восстановлена); None → no-op (`test_interface_section.py`, 3 теста)
- [x] prototype **2054 passed / 3 skipped**; ruff clean; sentrux **9/9**, quality 7133
- [x] Commit `a4691aaf` с `Refs`, `Layer: prototype`

**Out of scope:** удаление AppContext (G.5.3).
**Note (G.5.2):** app.py пока сохраняет `ctx` (источник `ctx.app_services`/`ctx.auth`/`ctx.command_sender` для сборки runtime) + `ctx.extras[...]` — удаляются в G.5.3.
**Module contract:** public-api-change (TabFactory + InterfaceSection ctor).

---

### Task G.5.3 — Удаление AppContext + _deprecated_extras

**Level:** Senior (teamlead/director — финальная чистка composition root)
**Goal:** Удалить `AppContext`, `_DeprecatedExtrasDict`, `build_app_context`, `process._app_context`, все `ctx.extras[...]` из app.py (зависимости — только локалы). Удалить осиротевшие тесты, переписать зависящие. Обновить ARCHITECTURE.md.

**Файлы (prod):**
- DELETE `frontend/app_context.py`, `frontend/_deprecated_extras.py`.
- `frontend/app.py` — убрать `build_app_context` import + вызов; убрать ВСЕ `ctx.extras[...]` (локалы достаточно); убрать `process._app_context = ctx`; `command_sender` строить локально (`CommandSender(process)`); `ctx.app_services` → локальная `app_services`; `ctx.auth` (493,527) → локальный `auth_ctx`.
- `frontend/auth_context.py` — если re-export AppContext (line 8 в app_context) — проверить, что AuthContext самодостаточен (он отдельный модуль, ок).
- `multiprocess_prototype/ARCHITECTURE.md` — обновить раздел «AppContext (DI-контейнер)» → AppServices + RuntimeDeps.

**Тесты:** DELETE `test_app_context.py`, `test_extras_deprecation.py`; rewrite `test_phase15_smoke.py`, `test_phase10_integration.py` (если используют build_app_context).

**Acceptance criteria:** — ✅ DONE (2026-05-29, `ea8f0f8d`)
- [x] real `import`/usage `AppContext`/`build_app_context`/`_DeprecatedExtrasDict`/`ctx.extras`/`_app_context` → 0 в `multiprocess_prototype/` (остались только комментарии-археология «AppServices вместо AppContext»; файлы app_context.py + _deprecated_extras.py удалены)
- [x] `python -m pytest multiprocess_prototype/` **2012 passed / 3 skipped, 0 failed** (−42 vs G.5.2: удалены test_app_context + test_extras_deprecation + TestAppContextAppServicesField); ruff clean; sentrux check_rules **9/9**, quality **7135** (+2 vs 7133, import_edges −15)
- [x] **live boot-smoke ВЫПОЛНЕН (2026-05-29):** `python multiprocess_prototype/run.py` с dev auto-login — полный multiprocess-boot (ProcessManager + pilot + gui) без трейсбэков/errors.log/sys.exit; GUI-процесс отработал run_gui до auth.auto_login (маркеры service discovery / display_registry preload / recipe_manager); **qt-mcp probe (QT_MCP_PROBE=1) подтвердил рендер: MainWindow 1577×941 + QTabWidget 1577×399** → build_app_services вернул + TabFactory.create_tabs + window.show() сработали в живом дочернем процессе. Закрывает накопленный live-smoke долг Phase G (composition root reorder G.3+G.5)
- [x] Commit `ea8f0f8d` с `Refs`, `Layer: prototype` (+docs ARCHITECTURE.md)

**Out of scope:** UX (G.6); удаление `frontend/actions/` (отложено G.4.4).
**Риск:** **MEDIUM-HIGH** — финальный composition root reorder; митигация: G.5.1/G.5.2 уже сняли coupling, остаётся механическое удаление + live-smoke.
**Module contract:** public-api-change (удаление публичного `AppContext`/`build_app_context`).

---

## Wave 7 — G.6 (UX-фишки)

> **DETAILED** (2026-05-29 после reality-аудита investigator). **Премиса brief §5 СИСТЕМАТИЧЕСКИ ложна (6-й повтор урока G.2/G.4.x/G.5):** из 4 UX-фич у 3 премиса не соответствует коду. Аудит-находки ниже встроены в task-specs. Scope-решение владельца: тройка (G.6.1–G.6.3) + diff-view (G.6.4) сейчас; cross-tab linking «как полагается» = сначала RECIPE_APPLY live-миграция (G.6.5) → потом подписка Services (G.6.6); granular scene-updates → deferred post-merge (отдельный план, performance-only).

### Audit-находки (investigator 2026-05-29, file:line) — исправление brief §5

| Фича | Премиса brief §5 | Реальность (find) |
|---|---|---|
| Auto-reveal | «сейчас hardcoded позиция» | ❌ ЛОЖНА. Позиция = drop-координаты курсора (`tab.py:290` `scene_pos.x/y` → `presenter.add_process_from_plugin`, `_gui_positions[name]`). `ProcessAdded` **публикуется** в prod (`command_dispatcher.py:132`), но **0 подписчиков**. Реальная задача: подписаться → centerOn/ensureVisible новой ноды (после full reload она может быть вне viewport при zoom-out). |
| Real-time validation | «встроить в `Project.apply()`» | ❌ ЛОЖНА. Валидация **УЖЕ встроена** (`project.py:127-244`: unique names, no-dangling-wires, no-cycles DFS, plugin/display refs). Каждый dispatch её проходит, `DomainError` отклоняет. Реальная дыра: presenter ловит `DomainError` и **молча логирует** (`presenter.py:155,360,392,400,438,455`) — пользователь видит «ничего не произошло». Задача: UI-feedback. |
| Cross-tab linking | «`RecipeActivated` event → Services tab» | ❌ ЛОЖНА. `RecipeActivated` **НЕ публикуется** в prod: `RecipesPresenter.on_set_active` (`recipes/presenter.py:275`) → `store.set_active` + `replace_blueprint_fn`, **мимо domain dispatch**. `ActivateRecipe`/`_apply_activate_recipe` (`project.py:747`) есть, но 0 dispatch. RECIPE_APPLY live-миграция явно отложена G.4.4 (IPC-риск). ⇒ блокер: нужна сначала миграция. |
| Diff-view | «`Topology.diff` из to_dict; `RecipeEngine.is_dirty()` уже есть» | ⚠️ ЧАСТИЧНО. `Topology.diff` **не существует** (`topology.py` — только find_*/from_dict/to_dict) → писать с нуля. `RecipeEngine.is_dirty()`/`diff()` есть (`recipe_engine.py:320,336`), НО в GUI-процессе бесполезны (изолированный пустой `TreeStore`, всегда False). ⇒ своя dict-утилита diff из двух to_dict. |

**Архитектурный факт (важен для всех G.6.x):** prod-подписчиков EventBus всего 3 — `PipelinePresenter._on_topology_replaced` (presenter.py:100), `topology_bridge.on_topology_changed` (app.py:455), rm-sync `PluginConfigChanged` (app.py:481). Cross-tab подписок 0. Порядок dispatch: `save`→TopologyReplaced (шаг 4) ДО granular events (шаг 6) ⇒ при `ProcessAdded`-handler'е scene уже перерисована. undo/redo НЕ переигрывает granular (только `_emit_config_diff` PluginConfigChanged, G.4.3) ⇒ auto-reveal сработает только на прямой dispatch(AddProcess), не на undo (корректно).

| Под-задача | Описание | Scope | Риск | Статус |
|---|---|---|---|---|
| **G.6.1** | Auto-reveal: tab подписан на `ProcessAdded` → `view` центрирует новую ноду | S (2-3) | LOW | DETAILED |
| **G.6.2** | Validation-feedback: `DomainError` в presenter → `notify`-callback → statusBar | S (2-3) | LOW | DETAILED |
| **G.6.3** | Selection-persist через scene reload (бывш. G.4.5) | S (2) | MEDIUM | DETAILED |
| **G.6.4** | Diff-view: утилита `topology_diff()` + UI-диалог «Изменения» | M (4-6) | MEDIUM | DETAILED |
| **G.6.5** | RECIPE_APPLY live-миграция: `recipes/presenter`→dispatch(ActivateRecipe) + IPC-hook на RecipeActivated | L (8-12) | HIGH | DETAILED (отдельный заход) |
| **G.6.6** | Cross-tab linking: Services tab подписка на `RecipeActivated` + highlight API | M (4-6) | MEDIUM | DETAILED (после G.6.5) |
| **deferred** | Гранулярные scene-апдейты (ProcessAdded/WireConnected → инкремент вместо full reload) | L (10+) | HIGH | POST-MERGE (отдельный план, performance-only) |

---

### Task G.6.1 — Auto-reveal новых нод

**Level:** Middle (developer/director-direct) — pure View-concern (камера).
**Goal:** При добавлении процесса вид центрируется/раскрывает новую ноду (не теряется за viewport при zoom-out/scroll).
**Дизайн (no-crutch):** reveal — это View-concern (камера/скролл), а не presenter (модель/scene-data). ⇒ **tab** подписывается на `ProcessAdded` через `services.events`, `view` раскрывает. Presenter (TopologyReplaced) уже перерисовал scene к моменту ProcessAdded (порядок dispatch).
**Files:**
- `pipeline/graph/graph_view.py` — метод `reveal_node(item)` → `self.ensureVisible(item, 50, 50)` (мягко: скроллит только если нода вне viewport; не пере-зумит). Convenience поверх QGraphicsView API.
- `pipeline/tab.py` — `_connect_signals`: `self._process_added_sub = self._services.events.subscribe(ProcessAdded, self._on_process_added)` (хранить ref — EventBus держит сильную ссылку, GC-симметрия с presenter `_topology_sub`); `_on_process_added(event)`: `item = self._scene.get_node(event.process_name)`; if item → `self._view.reveal_node(item)`.
**Acceptance:**
- [ ] dispatch(AddProcess) → новая нода видима в viewport (reveal_node вызван с её item)
- [ ] undo/redo НЕ центрирует (ProcessAdded не переигрывается — проверить, что handler не дёргается на undo)
- [ ] тест: Fake/реальный EventBus publish(ProcessAdded) → reveal_node вызван с корректным item (spy)
- [ ] pytest pipeline зелёные; ruff; sentrux 9/9
**Out of scope:** анимация центрирования; auto-reveal для display-боксов (BindDisplay — отдельный UX, не в scope).
**Edge cases:** item не найден (нода уже удалена синхронно) → no-op; пустой scene.

### Task G.6.2 — Validation-feedback (DomainError → пользователь)

**Level:** Middle (developer/director-direct).
**Goal:** Отклонённая доменная мутация (цикл, dangling, дубликат имени, несовместимость) даёт видимую обратную связь, а не тихий лог.
**Дизайн (no-crutch):** presenter не знает про Qt/statusBar. ⇒ инъекция `notify: Callable[[str], None] | None = None` в `PipelinePresenter.__init__`; в 5 `except DomainError` — `if self._notify: self._notify(str(exc))` (+ оставить logger). Tab передаёт `notify=self._show_status`, который зовёт `self.window().statusBar().showMessage(msg, 5000)` (MainWindow.statusBar существует — app.py:488).
**Files:**
- `pipeline/presenter.py` — `__init__(..., notify=None)` хранит `self._notify`; helper `_report(msg)`; вызвать в catch-сайтах (`add_process_from_plugin`, `remove_selected`, `add_wire` ConnectWire+BindDisplay, `_on_inspector_field_changed`, `_on_display_id_changed`). Port-incompat QMessageBox (`_validate_wire_ports`) — уже UI-feedback, не трогать.
- `pipeline/tab.py` — `_show_status(msg)` через `self.window().statusBar()` (guard на None — окно может быть не QMainWindow в тестах); передать `notify=self._show_status` в `PipelinePresenter(...)`. **NB:** presenter создаётся в `__init__` ДО добавления в окно → callback вызывается lazily (в рантайме окно уже есть), сам callback резолвит `self.window()` в момент вызова.
**Acceptance:**
- [ ] ConnectWire с циклом → statusBar показывает текст ошибки (не только лог)
- [ ] notify=None (default) → старое поведение (тихий лог), без падения
- [ ] тест: presenter с Fake notify → при DomainError notify вызван с сообщением
- [ ] pytest зелёные; ruff; sentrux 9/9
**Out of scope:** перманентный валидационный индикатор всей топологии (apply и так не даёт создать невалидную); подсветка проблемной ноды на canvas.
**Edge cases:** `self.window()` не QMainWindow/без statusBar в тесте → guard, no-op.

### Task G.6.3 — Selection-persist через scene reload (бывш. G.4.5)

**Level:** Senior (центральный путь reload).
**Goal:** undo/redo и любой dispatch с reload сохраняют выделение ноды; inspector показывает откатанные значения без ручного переселекта.
**Находки (подтверждены investigator):** `_on_topology_replaced`→`load_scene_with_ports`→`graph_scene.load_from_data`→`clear_all()` (graph_scene.py:60,198) теряет выделение → `tab._on_selection_changed`→`inspector.clear()`. `inspector_panel.update_field` (inspector_panel.py:588) — **мёртвый код** (только 3 теста).
**Дизайн (no-crutch):** в `_on_topology_replaced` (presenter.py:620) — capture `selected_ids` ДО reload, restore ПОСЛЕ `load_scene_with_ports` (внутри `with _block_signals()` — гасит спурьёзные field-dispatch при программном populate формы). `item.setSelected(True)` → selectionChanged → tab показывает inspector с актуальной моделью+rm. `update_field` — **удалить как dead code** (re-select через сигнал достаточен; убрать 3 теста-вызова или переписать).
**Files:**
- `pipeline/presenter.py` — `_on_topology_replaced`: capture selected (через `self._scene.selectedItems()` + hasattr node_id) до `from_topology_dict`; после `load_scene_with_ports` — restore (`get_node(id).setSelected(True)`).
- `pipeline/inspector/inspector_panel.py` — удалить `update_field` (dead).
- тесты inspector — убрать/переписать вызовы `update_field`.
**Acceptance:**
- [ ] undo/redo сохраняет выделение существующей ноды; inspector показывает откатанные значения без переселекта
- [ ] re-select удалённой ноды (после undo RemoveProcess вернулась с тем же id=process_name) → graceful (нода есть → выделится; если нет → placeholder, не падение)
- [ ] `update_field` удалён, grep = 0 (или только git-история); inspector-тесты зелёные
- [ ] pytest pipeline зелёные; 🔴 **live qt-mcp smoke рекомендован** (поведение видно в живом GUI) — known caveat
- [ ] ruff; sentrux 9/9
**Out of scope:** in-place refresh формы без re-select (update_field-путь — удалён); гранулярные scene-апдейты (deferred).
**Риск:** MEDIUM — центральный путь reload (каждый dispatch). Митигация: тесты на реальной QGraphicsScene + live-smoke.

### Task G.6.4 — Diff-view (несохранённые изменения vs активный рецепт)

**Level:** Middle+ (developer).
**Goal:** Кнопка «Изменения» в Pipeline показывает дифф текущей editor-топологии vs blueprint активного рецепта.
**Дизайн (no-crutch):** НЕ через framework `RecipeEngine.is_dirty()` (бесполезен в GUI — изолированный TreeStore). Чистая domain-утилита: `topology_diff(current: dict, saved: dict) -> TopologyDiff` сравнивает processes (added/removed/config-changed по `process_name`), wires (added/removed по `(source,target)`), displays (added/removed по `(node_id,display_id)`). metadata/gui_positions игнорируются (не семантика). `current = services.topology.load().to_dict()`, `saved = store.read_raw(active)["data"]["blueprint"]` (или `["blueprint"]` fallback — оба формата встречаются, см. presenter.py:973).
**Files:**
- `pipeline/diff.py` (NEW) — `@dataclass TopologyDiff` (processes_added/removed/changed, wires_added/removed, displays_added/removed; `is_empty` property; `summary()` → list[str] человекочитаемо) + `topology_diff(current, saved)`. Pure Python, без Qt — тестируется без QApplication.
- `pipeline/presenter.py` — `compute_active_recipe_diff() -> TopologyDiff | None` (None если нет активного рецепта): читает current + saved blueprint через `services.recipes`, зовёт `topology_diff`.
- `pipeline/tab.py` — кнопка `("diff", "Изменения")` в action-toolbar (после "Валидация"); `_on_toolbar_action("diff")`: diff=presenter.compute_active_recipe_diff(); None→QMessageBox «Нет активного рецепта»; is_empty→«Нет несохранённых изменений»; иначе QMessageBox/диалог со `summary()`.
**Acceptance:**
- [ ] `topology_diff` корректен: added/removed/config-changed процессы, added/removed wires/displays (unit-тесты на чистых dict)
- [ ] нет активного рецепта → сообщение; нет изменений → «нет изменений»; есть → список
- [ ] gui_positions/metadata не дают ложных diff
- [ ] pytest зелёные; ruff; sentrux 9/9
**Out of scope:** визуальная подсветка diff на canvas; two-way merge; diff между двумя произвольными рецептами; dirty-индикатор в реальном времени (можно follow-up).
**Edge cases:** активный рецепт без blueprint-секции → пустой saved (всё current = added); рецепт нечитаем → None + лог.

### Task G.6.5 — RECIPE_APPLY live-миграция (prerequisite cross-tab, «как полагается»)

> **HIGH risk / IPC.** Отдельный аккуратный заход (G.4.4 отложил именно это). Делается ПОСЛЕ G.6.1–G.6.4 (зелёные), верифицируется изолированно. Цель — «как полагается, без костылей»: recipe-активация становится domain-командой, IPC-replace-blueprint вешается слушателем на `RecipeActivated`, persistence `set_active` сохраняется.

**Level:** Senior+ (teamlead) — центральный recipe-flow + IPC + composition root. Затем reviewer (Opus).
**Goal:** `RecipesPresenter.on_set_active` идёт через `services.commands.dispatch(ActivateRecipe(slug))` → domain заменяет editor-топологию blueprint'ом рецепта + эмитит `TopologyReplaced`+`RecipeActivated`; IPC `replace_blueprint` (горячая замена живых процессов) выполняется отдельным listener'ом на `RecipeActivated`; `store.set_active` (persist активного флага) сохраняется.
**Аудит-факты:** `_apply_activate_recipe` (project.py:747) читает `catalogs.recipes.read(slug).blueprint`, валидирует все invariants, model_copy(topology=blueprint, active_recipe=slug), эмитит `[TopologyReplaced(reason=f"recipe:{slug}"), RecipeActivated(slug)]`. **Открытые вопросы детализации (grep ДО старта):** (1) populated ли `ApplyContext.recipes` в prod `apply_context_factory` (app.py) — иначе DomainError; (2) `RecipesPresenter` НЕ имеет AppServices (только store/view/replace_blueprint_fn/logger) → как провести `services.commands`+`services.events` (через TabFactory/конструктор); (3) сейчас replace_blueprint вызывается синхронно внутри on_set_active с обработкой success/rollback в view.show_error — при переносе в listener сохранить error-feedback; (4) undo активации рецепта (ActivateRecipe undoable?) — снапшот заменит editor-топологию, но IPC уже переключил живые процессы → решить: ActivateRecipe `undoable=False` (recipe-switch не откатывается через Ctrl+Z) либо отдельная семантика.
**Дизайн (предв., уточнить аудитом перед кодом):**
- `recipes/presenter.on_set_active`: `store.set_active(slug)` (persist) → `services.commands.dispatch(ActivateRecipe(slug), undoable=False)` (domain topology+events). Убрать прямой `replace_blueprint_fn` из on_set_active.
- IPC listener (app.py, рядом с topology_bridge): `services.events.subscribe(RecipeActivated, lambda e: _do_replace_blueprint(e.slug))` — читает blueprint, зовёт `replace_blueprint_fn`, success/rollback → статус/лог. Узкий callback, не таскает весь proxy в presenter.
- `ApplyContext.recipes` — убедиться populated (если нет — провести RecipeStore в factory).
**Files (предв.):** `recipes/presenter.py`, `recipes/tab.py` (проводка services), `frontend/app.py` (IPC listener + apply_context recipes), возможно `frontend/tab_factory.py`/`runtime_deps.py`.
**Acceptance (предв.):**
- [ ] активация рецепта → dispatch(ActivateRecipe) → editor-топология = blueprint; `TopologyReplaced`+`RecipeActivated` опубликованы
- [ ] IPC replace_blueprint выполняется listener'ом; success/error feedback сохранён
- [ ] `store.set_active` persist сохранён (активный флаг переживает рестарт)
- [ ] тесты на реальном orchestrator+store+EventBus: активация эмитит оба события; IPC listener дёрнут; rollback при ошибке IPC
- [ ] 🔴 live qt-mcp smoke (recipe switch на живой системе) — критичен (IPC)
- [ ] pytest зелёные; ruff; sentrux 9/9; reviewer APPROVED
**Out of scope:** undo recipe-switch (undoable=False); удаление `frontend/actions/` (отложено).
**Риск:** HIGH — IPC hot-swap + recipe-flow + composition root. Митигация: отдельный заход, аудит ДО кода, тесты на реальном store, обязательный live-smoke, reviewer.

### Task G.6.6 — Cross-tab linking (RecipeActivated → Services tab)

> После G.6.5 (RecipeActivated публикуется). Services tab реагирует на активацию рецепта.

**Level:** Middle+ (developer), затем reviewer.
**Goal:** При активации рецепта Services tab подсвечивает/выделяет сервисы, относящиеся к активному рецепту (`active_services` из рецепта).
**Дизайн:** Services tab presenter подписывается на `services.events.subscribe(RecipeActivated, ...)`; читает `active_services` рецепта через store; view получает highlight API (выделить/проскроллить к сервисам). Нужно добавить highlight-метод в Services view/presenter (сейчас 0 cross-tab API).
**Files:** `services/presenter.py` (подписка + reaction), `services/view.py`/`tab.py` (highlight API), тесты.
**Acceptance:**
- [ ] активация рецепта → Services tab подсвечивает active_services рецепта
- [ ] нет active_services / сервис не в списке → graceful
- [ ] тест: publish(RecipeActivated) → presenter дёргает highlight с корректными сервисами
- [ ] pytest зелёные; ruff; sentrux 9/9; reviewer APPROVED
**Out of scope:** двусторонний linking (Services→Pipeline); навигация-переключение вкладки (только highlight).
**Риск:** MEDIUM — новый cross-tab паттерн (первая cross-tab подписка в prod).

### deferred (post-merge) — Гранулярные scene-апдейты

`_on_topology_replaced` (full `clear_all`+rebuild на КАЖДУЮ мутацию) → набор гранулярных handler'ов (ProcessAdded→add_node, WireConnected→add_edge, ...). События уже публикуются (0 подписчиков). **Scope L (10+ файлов, ~200+ строк), риск HIGH.** Ортогонально UX-фичам, выигрыш только performance (при 50+ нодах; текущие графы 5-20 нод — full reload быстр). ⇒ **отдельный план post-merge**, не в Phase G (иначе big-bang, brief §8).

---

## Риски Phase G (общие)

| Риск | Уровень | Митигация |
|---|---|---|
| Удаление holder ломает scene reload без ошибки (`getattr(_holder)`) | **HIGH** | G.1 вводит typed-метод TopologyRepository ДО удаления holder (G.3) |
| Big-bang: смешать typed events + ActionBus + removal | **HIGH** | строгая цепочка G.1→G.3→G.4→G.5; G.4 детализируется отдельно |
| undo/redo регрессия при ActionBus→commands | **HIGH** | G.4 — отдельная audit-like подготовка; snapshot-based undo сохраняет текущую семантику |
| Удаление «dead» AdministrationSection при скрытом потребителе | **LOW** | G.0.2 Step 1 — broad grep + тест перед удалением, эскалация если живой |
| commit race >2 параллельных агентов | **MEDIUM** | макс 2 агента/волна, непересекающиеся файлы (память) |
