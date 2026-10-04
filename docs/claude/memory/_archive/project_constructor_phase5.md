---
name: Constructor Phase 5 status
description: Phase 5 done — ShmRouteNode (fan-out canvas) + PluginManagerTab (MVP, registered in TabFactory)
type: project
originSessionId: 8df591d7-a341-42e1-8969-5444903c41a4
---
Constructor Phase 5 — DONE (2026-05-04).

**Part A — ShmRouteNode:**
- ShmRouteNode: custom NodeGraphQt node for fan-out visualization (1 input → N outputs)
- Auto-insert: PluginGraphAdapter automatically inserts/removes route nodes when fan-out >= 2
- GraphBuilder.build() returns 3-tuple now: (node_map, addr_to_wire_key, route_nodes_map)
- Route nodes are purely visual — wire model (WireEditorModel) is unchanged

**Part B — PluginManagerTab:**
- Full MVP: view.py (Protocol) + presenter.py + widget.py
- PluginManagerModel aggregates PluginRegistry data, filter/search, enable/disable, reload
- PluginCatalogTable: QTableWidget with filter/search/checkbox
- PluginDetailPanel: info, ports, metrics placeholder, default config editor
- Registered in TabFactory (widget_key="plugin_manager") and TabsConfig (after "Процессы")

**Tests:** 73 new tests (20 route node + 53 plugin manager), total 146 Phase 2-5

**Why:** Visual constructor needs fan-out visualization for clarity; plugin management tab provides centralized plugin lifecycle control.
**How to apply:** Phase 6 = Display assignment + Live monitoring (per master plan). Runtime metrics IPC (plugins.metrics command) is deferred — model is ready for polling.
