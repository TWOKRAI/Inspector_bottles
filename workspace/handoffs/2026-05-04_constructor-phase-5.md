---
date: 2026-05-04
topic: Constructor Tab — Phase 5 (ShmRouteNode + PluginManagerTab)
machine: Windows
branch: main
---

## Session goal
Реализовать Фазу 5 визуального конструктора — ShmRouteNode (fan-out на канвасе) + PluginManagerTab (новая вкладка MVP).

## Done
- **Phase 5 Part A (ShmRouteNode):** кастомная нода fan-out (1→N), auto-insert/remove route nodes при fan-out≥2 в PluginGraphAdapter, GraphBuilder.build() → 3-tuple, route nodes чисто визуальные (wire model не меняется) — **20 тестов**
- **Phase 5 Part B (PluginManagerTab):** полный MVP (view.py Protocol + presenter.py + widget.py), PluginManagerModel (агрегация PluginRegistry, filter/search, enable/disable, reload), PluginCatalogTable (QTableWidget + фильтры), PluginDetailPanel (порты, метрики placeholder, конфиг), зарегистрирована в TabFactory + TabsConfig — **53 теста**
- Все **146 тестов** (Phase 2-5) зелёные
- Планы: `multiprocess_prototype/plans/phase5_shm_route_node_plugin_manager.md` (DONE)
- Коммиты: `76164a5` (Phase 3-4 leftover), `4b3e789` (Phase 5)

## What did NOT work
- **RuntimeWarning в PySide6 disconnect()** — `signal.disconnect()` без аргументов генерирует RuntimeWarning если сигнал не подключён. Решение: флаг `_item_changed_connected` + disconnect конкретного слота.
- **.gitignore блокировал models/** — правило `**/Models/` на case-insensitive Windows блокировало `models/`. Решение: `!multiprocess_prototype/**/models/` в .gitignore.

## Key decisions made
- **MVP-паттерн для новых вкладок** — пользователь выбрал полный MVP (presenter + view Protocol + widget) вместо упрощённого widget-only подхода. Записано в memory: `feedback_mvp_pattern.md`.
- **ShmRouteNode — чисто визуальный** — wire model не меняется, route node автогенерируется на канвасе при fan-out≥2 и удаляется при снижении до 1.
- **Enable/disable плагинов — конфигурационный флаг** — не IPC runtime, применяется при Apply/Restart.
- **Runtime метрики — отложены** — модель подготовлена для polling, но IPC `plugins.metrics` — будущая задача.

## Next step
Фаза 6 конструктора: Display assignment + Live мониторинг (fps, latency, buffer fill на wire overlay, SHM dashboard). Мастер-план: `~/.claude/plans/twinkling-wiggling-beacon.md`.

## Files changed

### Commits by agents (Phase 5):
- `55ee0d6` — ShmRouteNode (Task 1.1)
- `bd85ace`, `b5e3325` — PluginManagerModel (Task 2.1)
- `867b486` — PluginCatalogTable + PluginDetailPanel (Task 2.2-2.3)
- `9163bb3` — Auto-insert route node (Task 1.2)
- `823aa22` — MVP view/presenter/widget (Task 2.4)

### Director commits:
- `76164a5` — Phase 3-4 leftover (framework wire commands + constructor panels + tests)
- `4b3e789` — Phase 5 registration + tests + plan + bugfix

### New files (Phase 5):
- `constructor_tab/canvas/shm_route_node.py` — ShmRouteNode + RouteNodeItem
- `plugin_manager_tab/__init__.py`, `schemas.py` — пакет + TabItemConfig
- `plugin_manager_tab/models/__init__.py`, `models/plugin_manager_model.py` — модель
- `plugin_manager_tab/plugin_catalog_table.py` — таблица каталога
- `plugin_manager_tab/plugin_detail_panel.py` — панель деталей
- `plugin_manager_tab/view.py` — PluginManagerViewProtocol
- `plugin_manager_tab/presenter.py` — PluginManagerPresenter
- `plugin_manager_tab/widget.py` — PluginManagerTabWidget
- `tests/unit/test_constructor_phase5_route_node.py` — 20 тестов
- `tests/unit/test_constructor_phase5_plugin_manager.py` — 53 теста
- `plans/phase5_shm_route_node_plugin_manager.md` — план (DONE)

### Modified:
- `constructor_tab/canvas/plugin_graph_adapter.py` — auto-insert route nodes, _route_nodes dict
- `constructor_tab/canvas/graph_builder.py` — build() → 3-tuple, fan-out detection
- `constructor_tab/widget.py` — register_node(ShmRouteNode)
- `constructor_tab/canvas/__init__.py` — экспорт ShmRouteNode
- `tabs_config.py` — +plugin_manager вкладка
- `tab_factory.py` — case "plugin_manager"
- `test_constructor_phase2.py` — распаковка build() 2→3
