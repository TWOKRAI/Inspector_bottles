# Phase G — ActionBus→domain commands, typed events, удаление AppContext + UX

- **Slug:** cross-tab-architecture / phase-g
- **Дата:** 2026-05-28
- **Статус:** G.0 DONE (`ffeca3ba`), G.1 DONE (`75a6c41f`+`64bd2cd1`), G.2 DONE (`c30cc91f`, RuntimeDeps), G.3 DONE (TopologyHolder removed, store-publishes, reviewer APPROVED); **G.4 DETAILED** (Wave 5 ниже — 4 под-волны; **G.4.1 DONE** `e5aaa862`; **G.4.2 DETAILED**); G.4.2b/G.4.3/G.4.4 NOT DETAILED; G.5–G.6 NOT DETAILED.
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
| **G.5** | AppContext removal: отвязать TabFactory/sections/factory от ctx, удалить AppContext + `_deprecated_extras` | M (5-7) | G.4 | NOT DETAILED |
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
| **G.4.2** | **Pilot Pipeline topology:** `add_process_from_plugin`/`remove_selected`/`add_wire` → `dispatch(AddProcess/RemoveProcess/ConnectWire/DisconnectWire)`; undo/redo кнопки (`tab.py`) → `services.commands`; убрать оптимистичные scene-апдейты (reload из `TopologyReplaced`). Чинит desync-баг (находка #2). **Scope сужен:** только process-node + process→process wire; display-node remove + wire-to-display → G.4.2b (domain не моделирует wire-to-display). | L (живой editor) | G.4.1 | **DETAILED** (см. Task G.4.2 ниже) |
| **G.4.2b** | **Display = binding (Idea, design LOCKED):** убрать wire-to-display из live-модели; output→display = `BindDisplay`/`UnbindDisplay`; scene рисует ребро из binding; единица связи = пара (выход, дисплей-канал) → fan-out; схлопнуть io.py-конвертер. Закрывает остаток desync-бага. | M | G.4.2 | **DESIGN LOCKED** (task-spec после approval G.4.2) |
| **G.4.3** | **FIELD_SET → SetPluginConfig:** pipeline/plugins/settings `field_changed` → domain `SetPluginConfig` + маппинг `register_name → (process, plugin_index)` + IPC через bridge. Тонкий: runtime register (RegistersManager) vs editor config (domain). | L | G.4.1 | NOT DETAILED |
| **G.4.4** | **Recipe + History + cleanup:** RECIPE_APPLY→`ActivateRecipe`; `HistoryPresenter` на domain history; удалить мёртвый `services.commands.action_bus()` bridge; решить судьбу `frontend/actions/` (NODE_MOVE — GUI-only undo отдельно; ROLE_UPDATE — auth-шина отдельно). | M | G.4.2, G.4.3 | NOT DETAILED |

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

**Acceptance criteria:**
- [ ] `grep 'action_bus' pipeline/` → 0 в presenter.py/tab.py (мёртвый bridge удалён из Pipeline)
- [ ] process add/remove + process→process wire идут через `services.commands.dispatch(...)`; в production персистятся (desync-баг #2 закрыт для process-пути)
- [ ] undo/redo (кнопки + Ctrl+Z/Y) работают через `services.commands.undo()/redo()`
- [ ] после dispatch ноды в scene имеют корректные port_schemas (находка #7 — wire-ы рисуются)
- [ ] DomainError (цикл/dangling) при `add_wire` → graceful `return False` + лог, repo не мутирован
- [ ] display-ветка remove + wire-to-display НЕ тронуты (старый путь), регрессионный тест зелёный; ограничение задокументировано комментарием + строкой плана (долг G.4.2b)
- [ ] `python -m pytest multiprocess_prototype/` зелёные (без регрессий); ruff clean; sentrux `check_rules` 9/9, quality без падения
- [ ] live boot-smoke Pipeline tab (qt-mcp/ручной): drop процесса → виден + персист; delete → исчез; wire → нарисован; Ctrl+Z откатывает (известный caveat — qt-mcp может быть недостижим; тогда явно отметить «не выполнено» в отчёте, [[feedback-qt-mcp-smoke-verification]])
- [ ] Commit с `Refs: plans/2026-05-27_cross-tab-architecture/phase-g.md`, `Layer: prototype`, `Why:`+`Tested:`

**Out of scope:** display-node remove + wire-to-display (G.4.2b); FIELD_SET (G.4.3); NODE_MOVE/recipe/удаление `action_bus()` accessor в orchestrator (G.4.4); гранулярные scene-апдейты из `ProcessAdded`/`WireConnected` (G.6 — пока full reload).
**Edge cases:** пустой palette/plugins=None → AddProcess не валидирует plugin (invariant skip), но нода без портов; дубликат wire → presenter-guard `return False`; undo сразу после load (пустой стек) → no-op; reload во время собственного dispatch — синхронный, `_suppress` не выставлять вокруг dispatch (reload нужен).
**Риск:** **HIGH** — живой editor + scene-reload + port-reconstruct + undo/redo. Митигация: tight scope (process-only), сохранение `_validate_wire_ports`, регрессионный тест на display-путь, live-smoke перед merge, snapshot-undo сохраняет семантику ActionBus.
**Module contract:** behaviour-change (presenter mutation-path: optimistic→unidirectional); public API presenter не меняется.

---

### G.4.2b — Design LOCKED: display = binding (Idea), не wire

> Решение владельца (2026-05-28): «как лучше и полагается, без костылей» → **Idea (binding-not-wire)**. Вариант B (учить domen wire-формату) **отклонён**. Полный task-spec — после approval G.4.2 (правило плана), здесь фиксируется зафиксированное архитектурное решение, чтобы не потерять контекст обсуждения.

**Обоснование (из разбора реальности 2026-05-28):**
- display физически = SHM ring-buffer в `ui_process` (`DisplayRegistry` + [`bind_displays_to_blueprint`](../../multiprocess_prototype/backend/displays/blueprint_binding.py)); в топологии — только привязка `node_id→display_id`. Это **routing-значимо** (роутер адресует кадр по `display_id`), не косметика → display принадлежит domain.
- **durable-слои УЖЕ binding-центричны:** domain `DisplayInstance.node_id` = выходной endpoint ([display.py](../../multiprocess_prototype/domain/entities/display.py)); на диске рецепт хранит `display_bindings: [{node_id: <выход>, display_id}]` ([io.py `graph_to_blueprint`](../../multiprocess_prototype/frontend/widgets/tabs/pipeline/io.py#L75) вырезает display-wire). **wire-to-display живёт ТОЛЬКО в in-memory `PipelineModel`** — это и есть рассинхрон.
- B = добавить в domen «диалект», которым диск/домен не пользуются (запах). **Idea = выровнять редактор по durable-слоям** (убрать рассинхрон). **Миграции на диске НЕ нужно** — там уже binding.

**Что делает G.4.2b:**
1. Убрать wire-to-display из live `PipelineModel`/presenter: соединение output→display = `dispatch(BindDisplay(node_id=<выход>, display_id))`; удаление = `UnbindDisplay`. `wires` держит только process→process.
2. **Scene:** ребро к display-боксу **выводится из `displays` (binding)** отдельным проходом, не из Wire. Display-боксы остаются на canvas — **визуально для юзера без изменений** (те же боксы, те же линии).
3. **Единица связи = пара (источник-выход + дисплей-канал).** Fan-out одного выхода на N дисплеев = N независимых binding'ов с раздельным undo. ⚠️ `UnbindDisplay(node_id)` сейчас keyed одним id → слишком грубый для fan-out (снесёт все). Уточнить идентичность: ключ по паре `(source, display_id)` или собственный id связи. Затрагивает domain `BindDisplay`/`UnbindDisplay` + `find_display_bindings_for`.
4. Схлопнуть конвертер wire⇄binding в `io.py` (`graph_to_blueprint`/`blueprint_to_graph` упрощаются — display-wire больше нет в in-memory).
5. Закрывает остаток desync-бага для display-ветки (находка #2 G.4.2).
6. **ADR** «display = binding, не wire» — написать при реализации G.4.2b (архитектурный выбор, меняет domain-модель display).

**Открытый под-вопрос (не блокирует):** нужен ли реально fan-out одного выхода на много экранов, или достаточно «разные стадии → разные дисплеи» (кейс А). Идентичность по паре покрывает оба, поэтому решение от ответа не зависит.

---

## Риски Phase G (общие)

| Риск | Уровень | Митигация |
|---|---|---|
| Удаление holder ломает scene reload без ошибки (`getattr(_holder)`) | **HIGH** | G.1 вводит typed-метод TopologyRepository ДО удаления holder (G.3) |
| Big-bang: смешать typed events + ActionBus + removal | **HIGH** | строгая цепочка G.1→G.3→G.4→G.5; G.4 детализируется отдельно |
| undo/redo регрессия при ActionBus→commands | **HIGH** | G.4 — отдельная audit-like подготовка; snapshot-based undo сохраняет текущую семантику |
| Удаление «dead» AdministrationSection при скрытом потребителе | **LOW** | G.0.2 Step 1 — broad grep + тест перед удалением, эскалация если живой |
| commit race >2 параллельных агентов | **MEDIUM** | макс 2 агента/волна, непересекающиеся файлы (память) |
