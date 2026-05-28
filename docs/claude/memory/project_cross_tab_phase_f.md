---
name: project-cross-tab-phase-f
description: "Phase F (удаление legacy + закрытие bridge) cross-tab-architecture — статус 7/9, решения Q-F1..Q-F4, F.1 перенос в G, остаток F.9/F.7/F.10"
metadata:
  type: project
---

**Phase F — Удаление legacy + закрытие bridge-компромиссов** на ветке `refactor/cross-tab-architecture`. Предшественник: [[project-cross-tab-phase-e]] (Phase E DONE).

**Прогресс: 7/9 задач (2026-05-28).** Все закоммичены, дерево чистое.

| Задача | Commit | Что |
|--------|--------|-----|
| F.2a | `01044f62` | dead legacy: extras["topology"], 4 dataclass-обёртки, ServiceCatalogFromRegistry alias (−226) |
| F.2b | `245d533d` | Pipeline topology: config["topology"] snapshot → services.topology.load() (один источник) |
| F.3 | `03ce0fc4` | DisplayCatalog writable Protocol (DisplaySpec +5 полей), развязка displays от framework |
| F.4 | `d46ad247` | RecipeStore Protocol rich API (read_raw/save_raw/duplicate/deactivate, set_active→bool), I/O в adapter |
| F.5 | `3bde8856` | PluginCatalog: has_registers, catalog/wire закрыты; sandbox plugin_class/service — bridge BY DESIGN (Q-F2=C) |
| F.6 | `243927cd` | AuthFacade.on_access_changed (domain-pure callback), 5 табов сняты с services.auth._state |
| F.8 | `957edb33` | Recipe display_bindings v3 (node_id/display_id), удалён live source/display + _normalize_display_binding |

**Остаток (→ новый чат, по решению владельца): F.9, F.7, F.10.**

**Решения владельца Q-F1..Q-F4 (2026-05-28), зафиксированы в плане:**
- **Q-F1=B (блокирует F.9):** runtime-deps (process_manager_proxy, topology_bridge, plugin_manager, command_sender, form_context, router_manager) → frozen dataclass `RuntimeDeps` вторым параметром `create(services, runtime)` **by design**, НЕ пихать в AppServices (разделение editor-state vs runtime-state).
- **Q-F2=C:** plugin_class — bridge accepted by design (sandbox требует живой Python-класс); порты уже в PluginSpec. F.5 закрыл что закрывалось, sandbox оставлен bridge.
- **Q-F3=B:** framework `Base{List,Tree}NavTab` generic `ctx`-слот НЕ трогать; F.9 убирает только prototype-side AppContext-зависимость.
- **Q-F4:** ActionBus→domain commands **вынесен в Phase G** (слишком большой, undo/redo).

**КРИТИЧНО — F.1 ПЕРЕНЕСЁН В PHASE G (находка ревью Director'а):** задача F.1 «активировать suppress_legacy_notify» построена на неверной посылке. Code-grep: `CommandDispatcher.dispatch()` НЕ используется в production (мутации идут через ActionBus-bridge `services.commands.action_bus()`), у EventBus **ноль** production-подписчиков, единственный рабочий путь обновления UI — legacy `holder.on_changed`. Активация suppress сейчас = регрессия. Двойная нотификация станет реальной только после ActionBus→commands (Phase G). Поэтому F.1 + ActionBus = Phase G вместе.

**Урок bridge-vs-Protocol (продолжение E.4/E.5):** закрывать Protocol'ом ТОЛЬКО где adapter реально покрывает API. F.3/F.4/F.6 — полное закрытие (adapter покрывал). F.5 sandbox plugin_class — bridge by design (живой класс ≠ метаданные). Честно с обеих сторон.

**F.8 находка:** формат `source/display` производил И потреблял `pipeline/io.py` (graph_to_blueprint/blueprint_to_graph), не только demo-yaml → F.8 была когерентной миграцией формата (io.py producer+consumer + domain + yaml + format_v1_to_v2). Реализация была найдена uncommitted в дереве + дочинен F.4-хвост (test_recipes_integration на `recipe_manager=` kwarg, F.4 не покрыл recipes/tests/).

**Why:** финальная зачистка legacy после миграции всех табов на AppServices DI (Phase E). Цель: топология читается в одном месте, ctx.extras удалён, табы зависят от domain-Protocol'ов, не от framework.

**How to apply (для нового чата на F.9/F.7/F.10):**
- Перед стартом: прочитать `plans/2026-05-27_cross-tab-architecture/phase-f-legacy-removal.md` (полные ТЗ F.9/F.7/F.10 + Q-F1..Q-F4 решения + графа зависимостей).
- **F.9 (Senior+, самая тяжёлая):** убрать `ctx=None` + `create(ctx)` bridge во всех 6 табах + tab_factory + register_all_tabs; ввести `RuntimeDeps` frozen dataclass (Q-F1=B); framework Base-классы НЕ трогать (Q-F3=B). Зависит от F.3–F.6 (готовы). TabFactory всё ещё нужен ctx.auth для permission-filtering → AppContext редуцируется, не удаляется (полное удаление — Phase G).
- **F.7 (Middle, ПОСЛЕ F.9):** pytest.ini DeprecationWarning `_deprecated_extras` ignore→error:: (узкий фильтр); починить fallout. Сначала прогнать `pytest -W error::DeprecationWarning` собрать список.
- **F.10 (финал):** cumulative grep (extras/config topology = 0, TODO Phase F = только «by design» остатки), sentrux дельта (НЕ обязательно 7161 — Protocol/adapter добавили код), **ручной Qt-MCP smoke** (multiprocess GUI недостижим для MCP → запустить `python -m multiprocess_prototype.run`, проверить рендер 7 табов + dispatch + recipe activation), обновить master plan → Phase F DONE + память.
- Тест-стратегия (enforced): builder/Fake, НЕ `MagicMock(spec=AppContext)` (история ложного green).

**Ключевые артефакты:**
- Plan: `plans/2026-05-27_cross-tab-architecture/phase-f-legacy-removal.md`
- Master: `plans/2026-05-27_cross-tab-architecture/plan.md` (Phase F APPROVED)
- 8 Phase F коммитов: `01044f62`..`957edb33` + `cd9d0c7b`/`5dfe75c7` (docs)
