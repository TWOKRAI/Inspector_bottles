---
name: Cross-tab Phase D AppServices
description: Phase D DONE 7/7 (2026-05-27) — AppServices factory + QtEventBus + ConfigStore Protocol + ProjectHolder + deprecation shim + Settings PoC + migration guide
metadata:
  type: project
---

# Cross-tab Phase D — AppServices DI (DONE 7/7)

**Ветка:** `refactor/cross-tab-architecture`
**Дата завершения:** 2026-05-27
**Предшественник:** [[project_cross_tab_phase_c]]

## Коммиты Phase D

| Task | Hash | Что сделано |
|------|------|-------------|
| D.2 | `bfc71c10` | QtEventBus — thread-safe wrapper, Signal(object) + QueuedConnection, 5 тестов |
| D.3 | `12f57c44` | ProjectHolder + Project.from_topology, RLock, 4+3 теста |
| D.2b | `7dfc27fd` | ConfigStore Protocol в domain + ConfigStoreFromManager adapter, glob pub-sub, optional save_callback, 18 тестов |
| D.4 | `79639cc3` | Deprecation shim — 13 deprecated keys в `_DEPRECATED_KEYS_MAP`, 21 тест |
| D.1 | `931461a2` | AppServices factory `build_app_services()`, 14 интеграционных тестов |
| D.5 | `a876f73e` + `94983ed2` | Settings tab PoC на AppServices DI, Qt-MCP smoke PASSED |
| D.6 | *(текущий)* | Migration guide + sentrux baseline + docs updates |

## Тестовое покрытие Phase D

- **~1981 passed**, 3 skipped (macOS SHM — known, T2.1 deferred)
- Qt-MCP smoke: MainWindow + SettingsTab рендерятся, 25 widgets, no Qt warnings
- `grep MagicMock(spec=AppContext)` = 0 в новых/мигрированных тестах

## Волны Phase D

- **Wave 1 (D.2/D.3/D.2b/D.4)** — инфраструктура: QtEventBus, ProjectHolder, ConfigStore, deprecation shim
- **Wave 2 (D.1)** — AppServices factory `build_app_services()` в `app.py:run_gui()`
- **Wave 3 (D.5 PoC)** — Settings tab migration proof-of-concept, паттерн подтверждён
- **Wave Final (D.6 docs)** — migration guide + sentrux baseline + plan/memory updates

## Adapter-слой (Phase C + D): расположение

```
multiprocess_prototype/adapters/
├── catalogs/          PluginCatalogFromRegistry, ServiceManagerFromRegistry, DisplayCatalogFromRegistry
├── stores/            RecipeStoreFromManager, RegistersBackendFromManager, ConfigStoreFromManager
├── auth/              AuthFacadeFromAuthState
├── topology/          TopologyRepositoryFromHolder
├── dispatch/          CommandDispatcherOrchestrator, ProjectHolder
└── __init__.py        build_app_services() factory
```

## Ключевые архитектурные решения (Q1-Q5 closed)

- **Q1:** QtEventBus в `frontend/qt_event_bus.py` — один файл, не отдельный пакет. Domain UI-agnostic.
- **Q2:** ProjectHolder = тупой state-контейнер в `adapters/dispatch/`. Events публикует только CommandDispatcher.
- **Q3:** ConfigStore Protocol добавлен в Phase D (не откладывать в E). Settings сразу на `services.config`.
- **Q4:** `bindings` (GuiStateBindings) остаётся вне AppServices — Qt-signal runtime state, другой слой. 25+ точек через AppContext, ревизия в Phase G.
- **Q5:** `pytest.ini filterwarnings ignore` для DeprecationWarning из `_deprecated_extras` — тесты не падают. `error::` в Phase F.

## Что разблокирует Phase E

- **Pipeline tab** — первый приоритет (21 из 40 топологических чтений по audit). Главный consumer, валидирует архитектуру end-to-end.
- Порядок: Pipeline → Processes → Recipes → Services → Plugins → Displays. Settings уже сделан.
- Migration guide: `docs/refactors/2026-05_phase_e_migration_guide.md`

## Sentrux baseline (post-Phase-D, 2026-05-27)

**Post-Phase-D `sentrux check` + `sentrux gate`:**

| Метрика | Значение |
|---------|----------|
| Quality | **7142** / 10000 |
| Coupling | 0.15 |
| Cycles | **0** |
| God files | **0** |
| Distance from Main Sequence | 0.26 |
| Complex functions | 71 (было 44 до Phase C/D — adapter-слой добавил сложность) |

**Сравнение с baseline'ами:**
- Pre-Phase-B (2026-05-10): quality=6200 (0.62 в шкале 0-1 = 6200/10000)
- Gate baseline (до Phase D docs): 7180
- Post-Phase-D (D.6): **7142** (-38 от gate, +942 от pre-Phase-B)

Деградация 7180→7142 объясняется ростом complex functions (44→71) от adapter-классов Phase C/D — ожидаемо, не архитектурная проблема. Cycles=0 и God files=0 — инварианты соблюдены. Все 28 rules pass.

## Out of scope (Phase E/F/G)

- Удаление `ctx.extras` — Phase F
- Удаление 4 dataclass-обёрток (TopologyContext, StateContext, PluginsContext, ActionsContext) — Phase F
- Live runtime snapshot (PID/FPS) — Phase E/G
- `bindings` в AppServices — Phase G
- `error::DeprecationWarning` в тестах — Phase F
