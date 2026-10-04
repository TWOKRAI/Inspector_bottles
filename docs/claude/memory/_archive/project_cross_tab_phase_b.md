---
name: project-cross-tab-phase-b
description: Phase B Cross-tab архитектуры DONE (2026-05-27) — изолированный domain skeleton multiprocess_prototype/domain/ готов
metadata:
  type: project
---

**Phase B Cross-tab architecture refactor — DONE (2026-05-27).**

Создан изолированный domain слой `multiprocess_prototype/domain/`:
- **7 frozen-entities на SchemaBase** (Wire, PluginInstance, DisplayInstance, Process, RecipeMeta, Recipe, Topology, Project) с `frozen=True, populate_by_name=True, extra="forbid"`. SchemaBase из `data_schema_module` — даёт FieldMeta для permission-aware Inspector.
- **14 типизированных событий** (ProjectEvent union) — frozen dataclass slots, ClassVar дискриминатор.
- **14 типизированных команд** (ProjectCommand union) — данные-«намерения», валидация в `Project.apply()`.
- **9 Protocols** (PluginCatalog, ServiceCatalog, DisplayCatalog, RecipeStore, RegistersBackend, TopologyRepository, CommandDispatcher, EventBusProtocol, AuthFacade) + 6 sidecar-dataclasses.
- **Project.apply(command, *, catalogs: ApplyContext) -> (Project, list[ProjectEvent])** — чистая функция, 5 invariants (unique names, dangling wires, cycles via DFS three-color, plugin/display references). DisconnectWire-not-found и RemovePlugin out-of-range → DomainError (fail fast).
- **EventBus** (pure Python sync, RLock, error_handler с default `logging.exception`) + **AppServices** (frozen dataclass, 9 обязательных полей, никаких Optional) + **`make_test_app_services()`** builder + `_fakes.py` с 9 in-memory implementations Protocols (заменяют MagicMock-anti-pattern из audit Inventory 6).

**Метрики:** 233 теста зелёных, 0 ruff errors, 0 запрещённых импортов (PySide6/PyQt/frontend/backend в domain отсутствуют), полностью изолирован от runtime прототипа.

**Коммиты:** `83274ef8` → `d3c812de` (B.1 + review fix) → `f53b828c` (B.2) → `c8ec137b` (B.3) → `c6e697e9` (B.5) → `24d1fc3f` (B.4 APPROVED) → `e65f7158` (B.6).

**Why:** Audit (Phase A) выявил 40 raw-dict обходов topology, 16 полей без формального контракта, 8 параллельных реестров (включая 8-й DisplayRegistry вне ctx.extras), 53 MagicMock-теста без spec. Phase B — типизированный фундамент, который Phase D подключит вместо `topology.get("processes", [])`-паттернов.

**How to apply:**
- Domain — UI/runtime-agnostic, импортируется ТОЛЬКО собственными тестами в Phase B. Подключение к presenter'ам — Phase D.
- Новые тесты в `domain/tests/` обязаны использовать `make_test_app_services()` builder и Fake-классы из `_fakes.py`, не `MagicMock(spec=AppServices)`. Запрет зафиксирован в acceptance criteria плана.
- Сущности editor-only — runtime-поля (process_class, priority, plugin_class, category) — passthrough для round-trip совместимости с реальными YAML; не интерпретируются domain-логикой.
- `display_bindings`: `Recipe.from_dict` принимает оба формата (`source/display` live + `node_id/display_id` новый). Миграция YAML — Phase F.

**Open questions для Phase C:**
1. TopologyRepository source of truth — live YAML / TopologyHolder / Project? Подтвердить до старта Phase C.
2. SchemaRegistry registration при импорте `multiprocess_prototype.domain` — глобальный side-effect. TODO Phase D: вынести в explicit `register_domain_schemas()` или AppServices factory.
3. Process/PluginInstance runtime-поля — разделить editor/runtime fields или вынести в `metadata`.

**Refs:**
- План: [[project-plan-driven-dev]] / `plans/2026-05-27_cross-tab-architecture/phase-b-domain.md` (статус DONE с чек-боксами)
- Audit: `docs/refactors/2026-05_cross_tab_audit.md` (Inventory 1-6)
- Brief: `docs/refactors/2026-05_cross_tab_architecture.md`
- Связано: [[feedback-dict-at-boundary-gui]] (dict at boundary — entities дают `to_dict`/`from_dict` методы), [[feedback-parallel-agents-commit-race]] (Phase B шёл последовательно из-за пересечения `__init__.py`).
