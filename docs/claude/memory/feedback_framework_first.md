---
name: Framework-first decision rule
description: "Правило владельца (owner rule): framework — мощный и универсальный, prototype — одноразовый тонкий потребитель; конструктор модулей и изоляция сбоев (fault isolation), меньше слоёв (fewer layers), fix-forward, FREEZE вместо KILL"
mechanism: [owner-decision, architecture]
merged_from: [feedback_constructor_modularity, feedback_fewer_layers, feedback_fix_framework_forward, feedback_freeze_over_kill]
metadata:
  type: feedback
---
Owner's standing rule for framework-vs-prototype decisions (adopted 2026-06-18). North star: make `multiprocess_framework` powerful and universal (best patterns, once, correctly); `multiprocess_prototype` is disposable (always re-doable). **When in doubt ask "what makes the FRAMEWORK more universal?" — not "what's least code in the prototype."**

**Why:** the framework serves projects simple→complex; the prototype is just ONE (medium) consumer. Optimizing decisions around the prototype quietly narrows the framework. The rule ends re-litigating every boundary call.

**How to apply:**
1. Mechanism wanted by ≥2 projects → framework; app-domain (vision pipeline, recipes, Inspector widgets) → prototype. Doubt → treat as framework concern.
2. In framework: program to a **CONTRACT** (Protocol/ABC), allow multiple implementations — never "one true class."
3. **Duplication** = same contract, same tier, no distinguishing value. Different tiers (simple/complex) or concerns (IPC/undo/events) → NOT duplicates; keep both, name the boundary.
4. "unused ≠ unneeded" applies to **framework blocks behind a contract**; prototype dead-wiring is just cleanup (remove it).
5. Prototype = **thin consumer** of framework contracts; domain specifics stay a thin layer.

Worked example (undo): undo is a framework concern → contract `UndoRedoController` (already exists, `tab_layout_protocol.py:29`) + 2 impls (ActionBus=patch for simple/complex, SnapshotHistory=snapshot for medium/immutable-aggregate) — keep both; prototype stops instantiating the unused one. Full decision + diagrams: `docs/audits/2026-06-18_command-undo-system.md`. Related: [[feedback_constructor_modularity]].

## Слито из feedback_constructor_modularity (_archive/feedback_constructor_modularity.md)

All layers (framework, prototype, GUI, bridge) must follow the constructor/building-blocks pattern. Each component is an independent module: pluggable, replaceable, independently testable, composable.

**Why:** This is the core architectural philosophy of the entire project — from ProcessModule plugins to GUI primitives to topology YAML. The bridge layer (Phase 12) is no exception.

**How to apply:** When designing new subsystems (bridge, command protocol, bindings), ensure:
- Each class is a standalone unit with clear interface (Protocol or ABC)
- Dependencies via DI, never hardcoded
- Pure Python core, Qt only at edges (lazy import)
- Can be tested without spinning up the full app
- Can be replaced or extended without touching other modules
- Follows same pattern as existing primitives: small composable blocks → assembled into bigger structures

**No hacks rule:** When something doesn't work — stop and think about root cause. Never patch with workarounds. Decompose the problem into parts, understand each part, then assemble the solution like a constructor. If a piece doesn't fit — the piece is wrong, not the assembly.

**Runtime fault isolation (owner refinement, 2026-06-18):** modularity must ALSO mean blast-radius containment — if one module/process/worker/plugin fails or crashes, siblings keep running and degradation is graceful. The framework is a constructor of *fault-isolated* blocks, not just decoupled code. First-class roadmap criterion, on par with sentrux modularity.

**How to apply (fault isolation):**
- A failing plugin/worker must not crash its process or the supervisor (e.g. device_hub supervisor-tick exception killing the always-on hub worker — wrap per-item, never let one item down the whole loop).
- Contain → report → degrade: errors surface (log + status=error + counter), never silent-swallow AND never cascade.
- Bulkheads: process boundaries (mp) + per-worker/per-plugin guards + RestartPolicy + bounded queues/back-pressure; add health-gate / circuit-breaker where a sibling failure would propagate.
- Acceptance: one block down ≠ whole pipeline down.

Relates to [[feedback_logger_error_stats_managers]] and the device_hub supervisor-crash + hot-path produce() swallow findings.

## Слито из feedback_fewer_layers (_archive/feedback_fewer_layers.md)

Владелец (2026-06-05): «чем меньше слоёв при той же функциональности, тем лучше».
Сказано при выборе дизайна P4.4 command-bus: предпочёл вариант B (один диспетчер,
CommandManager = чистая библиотека) над вариантом A (kind-router + второй слой-резолвер),
потому что B убирает целый слой диспетчеризации, сохраняя всю функциональность.

**Why:** дублирующие/лишние уровни косвенности — главный источник «невозможно
поддерживать»; меньше звеньев = меньше мест для ошибки, проще читать и менять. Это
конкретизация плановых принципов «Fewer links» и «Один диспетчер».

**How to apply:** при выборе между двумя решениями с одинаковым результатом — брать то,
где меньше слоёв/обёрток/резолверов. Не добавлять pipeline/менеджер/адаптер, если задача
решается context-manager'ом или прямой регистрацией. Перед вводом новой сущности спросить:
«это новый слой при той же функциональности?» — если да, искать способ без него.
Связано с [[feedback-fix-framework-forward]] (правки на улучшение, не на вырезание
функционала), [[project-transport-router-hub]] (один вход router.send), [[feedback-constructor-modularity]].

## Слито из feedback_fix_framework_forward (_archive/feedback_fix_framework_forward.md)

Владелец (2026-06-04): «если нужно починить баги во framework — делай. Главное что на улучшение, а не удаление».

**Why:** уточняет [[project_priority_engine_first]] — приоритет (тогда «продукт > движок», с 2026-07-26 развёрнут на «движок первым») НЕ означает «не трогать движок». Framework-баги, блокирующие фичу, чинить разрешено и нужно. Граница — в *направлении* правки: улучшать/чинить-вперёд, а не решать проблему вырезанием рабочего (или задуманного) функционала.

**How to apply:**
- Наткнулся на латентный/реальный баг framework, мешающий задаче → чини, не обходи и не оставляй (даже если план говорил «без правок framework»).
- При выборе «оживить сломанный механизм правильным фиксом» vs «удалить мёртвый код» → по умолчанию **fix-forward** (пример: `_publish_state` плагинов оживили фиксом `with_config`/`merge`, а не погасили — см. [[project_telemetry_db_sink]]).
- Удаление функционала — только с явного согласия владельца, не как способ «закрыть» баг.
- Не путать с осторожностью к прод-эффектам: чинить — да, но прод-влияние (напр. GUI-телеметрия) всё равно проверять живьём (qt-mcp), см. [[feedback_qt_mcp_smoke_verification]].

## Слито из feedback_freeze_over_kill (_archive/feedback_freeze_over_kill.md)

Владелец при выборе судьбы мёртвого/дремлющего кода стабильно выбирает **FREEZE (сохранить), а не KILL (удалить)**.

Прецеденты:
- `actions_module` (2026-07-08): решил сохранить, хотя ActionBus не прод-путь undo (ADR-COMM-002 не исполняется) — [[project_actions_module_keep]].
- GATE G2 форм (2026-07-10, «я бы не удалял»): 4 механизма схема→виджет — 7b binding-aware / 7c entity_editor / 7d WidgetRegistry все dead-in-prod (верифицировано), но НЕ удалять; активный = 7a legacy, остальные → frozen-tier. См. [[project_forms_mechanism_g2]] / `plans/2026-07-06_constructor-master/e4-forms-mechanism-diff.md`.

**Why:** дремлющий рабочий+тестированный код — капитал/опциональность (напр. 7b — готовый reactive/undoable write, если ADR-COMM-002 оживёт). Цена хранения ниже риска потери.

**How to apply:** не предлагать удаление dead-кода как дефолт. Для мёртвого/дремлющего механизма предлагать FREEZE-ярус (core/optional/**frozen** карты H.1 + `.sentrux/rules.toml` boundaries: заморожённое НЕ обрастает новыми зависимостями, новые фичи туда не текут). KILL — только если владелец явно санкционировал (per-item одобренный коммит, GATE G4/H.2). «Унификация N→1» = сузить АКТИВНЫЙ путь до одного, а не физически удалить остальные.
