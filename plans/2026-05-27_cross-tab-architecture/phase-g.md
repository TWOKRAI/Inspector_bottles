# Phase G — ActionBus→domain commands, typed events, удаление AppContext + UX

- **Slug:** cross-tab-architecture / phase-g
- **Дата:** 2026-05-28
- **Статус:** G.0 DONE (`ffeca3ba`), G.1.1 DONE (`75a6c41f`); G.1.2 + G.2–G.6 NOT DETAILED (детализируются по очереди, избегаем premature planning большого G.4).
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
| **G.1** | Typed events в production: PipelinePresenter + TopologyBridge на EventBus (закрывает 🔴 `getattr(_holder)`) | M-L (5-8) | G.0 | **G.1.1 DONE** (`75a6c41f`); G.1.2 NOT DETAILED |
| **G.2** | RegistersBackend Protocol alignment: расширить Protocol, убрать 3 `_rm` getattr | M (4-5) | — | NOT DETAILED |
| **G.3** | holder removal: активировать suppress_legacy_notify (F.1) / редуцировать-удалить TopologyHolder | M (3-4) | G.1 | NOT DETAILED |
| **G.4** | ActionBus→domain commands: 11 call-sites + undo/redo поверх domain + register→domain mapping | **L (15-20)** | G.1, G.2, G.3 | NOT DETAILED (+audit-like подготовка) |
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

> **Caveat верификации:** unit + wiring-тест (реальный EventBus) проходят. Полный end-to-end в живом
> multiprocess-GUI (ActionBus→holder.set_topology→publisher→EventBus→scene) НЕ проверен — qt-mcp
> недостижим до дочернего GUI-процесса (см. память feedback_qt_mcp_smoke_verification). Логика publisher-моста
> — однострочник в composition root, тот же экземпляр bus у табов; риск низкий, но live-smoke рекомендован перед merge.

**Out of scope:** TopologyBridge IPC sync (G.1.2); granular events ProcessAdded/WireConnected (G.4); удаление holder (G.3).
**Edge cases:** пустая топология → load() даёт пустой Topology; `_suppress` во время собственных мутаций presenter'а — publish синхронный, guard срабатывает как раньше.

### Task G.1.2 — TopologyBridge IPC sync на EventBus (перед G.3)

**Level:** Middle+ — мигрировать `app.py:224` `topology_holder.on_changed(topology_bridge.on_topology_changed)`
на `services.events.subscribe(TopologyReplaced, ...)` (bridge тянет dict из repo). После G.1.1+G.1.2 единственный
подписчик `holder.on_changed` = publisher-мост → **G.3** заменяет хук на публикацию в преемнике `set_topology` и удаляет holder.
NOT DETAILED (детализируется при подходе очереди).

---

## Риски Phase G (общие)

| Риск | Уровень | Митигация |
|---|---|---|
| Удаление holder ломает scene reload без ошибки (`getattr(_holder)`) | **HIGH** | G.1 вводит typed-метод TopologyRepository ДО удаления holder (G.3) |
| Big-bang: смешать typed events + ActionBus + removal | **HIGH** | строгая цепочка G.1→G.3→G.4→G.5; G.4 детализируется отдельно |
| undo/redo регрессия при ActionBus→commands | **HIGH** | G.4 — отдельная audit-like подготовка; snapshot-based undo сохраняет текущую семантику |
| Удаление «dead» AdministrationSection при скрытом потребителе | **LOW** | G.0.2 Step 1 — broad grep + тест перед удалением, эскалация если живой |
| commit race >2 параллельных агентов | **MEDIUM** | макс 2 агента/волна, непересекающиеся файлы (память) |
