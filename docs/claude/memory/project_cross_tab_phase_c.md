---
name: project-cross-tab-phase-c
description: Cross-tab architecture Phase C — 4/9 Tasks DONE (C.0/C.1/C.1.5/C.1.6). adapter layer in multiprocess_prototype/adapters/. Remaining C.2-C.7. Key decisions Q1-Q7.
metadata:
  type: project
---

Cross-tab architecture refactor, **Phase C — IN PROGRESS** (4 из 9 Tasks DONE) на ветке `refactor/cross-tab-architecture`.

**Контекст:** adapter-слой `multiprocess_prototype/adapters/` между [[project-cross-tab-phase-b]] domain layer и реальными реестрами фреймворка.

## DONE Tasks

| Task | Commit(ы) | Что |
|------|-----------|-----|
| C.0 | `1f1d28ff` + `210f21a1` | Wire.description, Process.metadata, lazy `register_domain_schemas()` |
| C.1 | `551ebdad` | 3 read-only catalog adapters (Plugin/Service/Display) |
| C.1.5 | `05d86857` + `d710a6a2` | PluginSpec.description + PortSpec.optional/shape + DisplayRegistry preload в app.py |
| C.1.6 | `5b45eab8` + `e4668a69` | ServiceCatalog → ServiceManager Protocol с lifecycle (start/stop/restart/get_lifecycle) |

**Метрики:** domain 240 tests, adapters 53 tests + 2 skipped, ruff 0 errors. 8 коммитов локально, не запушены.

## Pending Tasks

- C.2 — AuthFacade (Junior+, developer)
- C.3 — TopologyRepositoryFromHolder + `suppress_legacy_notify()` cm (Middle+, developer)
- C.4 — RegistersBackendFromManager (Middle+, developer) — variant A: знает Topology+PluginCatalog
- C.5 — RecipeStoreFromManager (Senior, teamlead) — variant A: denormalize meta→top-level
- C.6 — CommandDispatcherOrchestrator (Senior, teamlead) — **БЕЗ suppress_legacy_notify по умолчанию**
- C.7 — adapters/__init__.py + README + integration smoke (Middle, developer)

## Закрытые decisions (Q1-Q7)

- **Q1:** Project = source of truth, holder = derived (Phase D+).
- **Q2:** Recipe YAML variant A — denormalize `meta → top-level` при write.
- **Q3:** Wire.description: str = "" поле + Process.metadata: dict (НЕ source_target_fps).
- **Q4:** RegistersBackend variant A — adapter знает TopologyRepository + PluginCatalog.
- **Q5:** DisplayRegistry — singleton напрямую.
- **Q6:** `suppress_legacy_notify()` cm существует в TopologyRepository API, реализован через toggle-флаг `holder._suppress_notify`.
- **Q7 (user-confirmed после investigator-ревью):** Dispatcher НЕ использует suppress по умолчанию. Double notification (legacy + EventBus) — temporary до Phase F.

## Investigator-ревью 2026-05-27 — выводы

См. [`docs/refactors/2026-05_cross_tab_investigator_followup.md`](../../refactors/2026-05_cross_tab_investigator_followup.md) — полный отчёт.

**Ключевое:** C.1 в исходной форме покрывал 14-35% prod call sites. C.1.5 + C.1.6 + правка C.6 сняли блокеры для Phase E.

**Compromise:** `PluginSpec` НЕ получает `plugin_class: type` / `register_classes: list[type]`. Sandbox.py и command_catalog.py остаются на raw `ctx.plugin_registry()`. Adapter покрывает «catalog read» ~35%, Phase E мигрирует presenters частично — задокументировано.

## Phase D готовность

- 7 Tasks (D.1, D.2, D.2b ConfigStore, D.3-D.6) — APPROVED, ready to start после Phase C END.
- AppServices содержит **10 полей** (с ConfigStore).
- D.5 PoC tab = Settings (low risk). Pipeline = первый в Phase E.

## Key paths

| Что | Путь |
|-----|------|
| Adapter package | `multiprocess_prototype/adapters/` |
| Catalog adapters | `multiprocess_prototype/adapters/catalogs/{plugin,service,display}_catalog.py` |
| Domain protocols | `multiprocess_prototype/domain/protocols/` |
| Phase C plan | [`plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md`](../../../plans/2026-05-27_cross-tab-architecture/phase-c-adapters.md) |
| Phase D plan | [`plans/2026-05-27_cross-tab-architecture/phase-d-app-services.md`](../../../plans/2026-05-27_cross-tab-architecture/phase-d-app-services.md) |
| Investigator followup | [`docs/refactors/2026-05_cross_tab_investigator_followup.md`](../../refactors/2026-05_cross_tab_investigator_followup.md) |
