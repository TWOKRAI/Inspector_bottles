---
name: project-cross-tab-phase-c
description: Cross-tab architecture Phase C — DONE 9/9 (2026-05-27). multiprocess_prototype/adapters/ — 10 классов, 113 tests, ready for Phase D. Key decisions Q1-Q7 + 4 documented compromises.
metadata:
  type: project
---

Cross-tab architecture refactor, **Phase C — DONE 9/9 Tasks** (2026-05-27) на ветке `refactor/cross-tab-architecture`. Готова к Phase D.

**Контекст:** adapter-слой `multiprocess_prototype/adapters/` между [[project-cross-tab-phase-b]] domain layer и реальными реестрами фреймворка.

## DONE Tasks (все 9)

| Task | Commit(ы) | Что |
|------|-----------|-----|
| C.0 | `1f1d28ff` + `210f21a1` | Wire.description, Process.metadata, lazy `register_domain_schemas()` |
| C.1 | `551ebdad` | 3 read-only catalog adapters (Plugin/Service/Display) |
| C.1.5 | `05d86857` + `d710a6a2` | PluginSpec.description + PortSpec.optional/shape + DisplayRegistry preload в app.py |
| C.1.6 | `5b45eab8` + `e4668a69` | ServiceCatalog → ServiceManager Protocol с lifecycle (start/stop/restart/get_lifecycle) |
| **C.2** | `826d72c0` + `56bc4ff9` | **AuthFacadeFromAuthState** (read-only, 11 tests) |
| **C.3** | `c36b559f` | **TopologyRepositoryFromHolder** + `suppress_legacy_notify()` cm в TopologyHolder (8 tests) |
| **C.4** | `050e68b8` | **RegistersBackendFromManager** Variant A: topology+catalog resolution (13 tests) |
| **C.5** | `a847c0e5` | **RecipeStoreFromManager** denormalize meta→top-level (15 tests) |
| **C.6** | `22f25cb0` | **CommandDispatcherOrchestrator** + ProjectHolder — central orchestrator (10 tests, coverage 100%) |
| **C.7** | `2884b971` + `e8dd0540` | README + integration smoke + sentrux rule (4 tests, 1 skipped Phase D) |
| infra | `6030f44b` | exports update между Wave 2 параллельными агентами |

**Финальные метрики:**
- adapters: **113 tests passed** + 1 skipped (real registry smoke @Phase D TODO)
- domain: **240 tests passed**
- **Всего: 353 passed + 3 skipped, ruff 0 errors**
- 17 локальных коммитов на ветке `refactor/cross-tab-architecture` (origin behind on 16)

## Публичный API пакета

```python
from multiprocess_prototype.adapters import (
    # catalogs/
    AuthFacadeFromAuthState,
    PluginCatalogFromRegistry,
    ServiceCatalogFromRegistry,
    ServiceManagerFromRegistry,
    DisplayCatalogFromRegistry,
    # stores/
    TopologyRepositoryFromHolder,
    RegistersBackendFromManager,
    RecipeStoreFromManager,
    # dispatch/
    CommandDispatcherOrchestrator,
    ProjectHolder,
)
```

10 классов, удовлетворяющих 9 Protocols из `multiprocess_prototype.domain.protocols`.

## Закрытые decisions (Q1-Q7)

- **Q1:** Project = source of truth, holder = derived (Phase D+).
- **Q2:** Recipe YAML variant A — denormalize `meta → top-level` при write.
- **Q3:** Wire.description: str = "" поле + Process.metadata: dict (НЕ source_target_fps).
- **Q4:** RegistersBackend variant A — adapter знает TopologyRepository + PluginCatalog.
- **Q5:** DisplayRegistry — singleton напрямую.
- **Q6:** `suppress_legacy_notify()` cm существует в TopologyRepository API, реализован через toggle-флаг `holder._suppress_notify`.
- **Q7 (user-confirmed после investigator-ревью):** Dispatcher НЕ использует suppress по умолчанию. Double notification (legacy + EventBus) — temporary до Phase F.

## Задокументированные compromises (для Phase E/F)

1. **PluginSpec НЕ имеет `plugin_class: type` / `register_classes: list[type]`** — sandbox.py и command_catalog.py остаются на raw `ctx.plugin_registry()`. Adapter покрывает "catalog read" ~35%, Phase E мигрирует presenters частично (см. investigator-followup).
2. **ServiceManager.discover() не реализован** в adapter — ServicesPresenter мигрирует частично в Phase E.
3. **RecipeStore.set_active(None)** обращается к private `engine._active_name` + `_update_active_in_state(None)` — Phase F refactor когда RecipeManager получит public `deactivate()`.
4. **TopologyHolder import** в `adapters/stores/topology_repository.py` — bridge-исключение из правила "adapters → !frontend" (Q1). TopologyHolder будет удалён в Phase F вместе с миграцией на чистый EventBus. Sentrux правило таргетит `frontend/widgets*` + `PySide6/*`, не frontend целиком.
5. **RegistersManager API**: `register_name == plugin_name` convention (`from_registry`/`build_rm_from_topology`). `FieldInfo.field_type` → `dtype: str` через `type.__name__`.
6. **AuthFacade.has_permission()** делегирует `AuthState.access_context.has_permission(key)` — `IAuthManager.permissions.has()` не существует. `auth_manager` параметр убран из ctor.
7. **Project.apply()** использует `catalogs=` keyword arg, не positional. CommandDispatcherOrchestrator учитывает это: `current.apply(command, catalogs=ctx)`.

## Phase D готовность

- 7 Tasks (D.1, D.2, D.2b ConfigStore, D.3-D.6) — APPROVED, ready to start.
- AppServices содержит **10 полей** (с ConfigStore).
- D.5 PoC tab = Settings (low risk). Pipeline = первый в Phase E.

## Key paths

| Что | Путь |
|-----|------|
| Adapter package | `multiprocess_prototype/adapters/` (README, catalogs/, stores/, dispatch/, auth/, tests/) |
| Phase C plan | [`plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md`](../../../plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md) (status: DONE) |
| Phase D plan | [`plans/2026-05-27_cross-tab-architecture/phase-d-app-services.md`](../../../plans/2026-05-27_cross-tab-architecture/phase-d-app-services.md) |
| Investigator followup | [`docs/refactors/2026-05_cross_tab_investigator_followup.md`](../../refactors/2026-05_cross_tab_investigator_followup.md) |
| Sentrux rule | `.sentrux/rules.toml` (boundaries `adapters → !frontend/widgets*`, `adapters → !PySide6/*`) |
