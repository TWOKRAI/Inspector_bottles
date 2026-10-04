---
name: Config-driven architecture status
description: Refactoring to GenericProcess + plugins — phases 0-2 done, Constructor Tab phases 1-4 done, phase 5 (ShmRouteNode + PluginManager) next
type: project
originSessionId: de37c54f-e9cd-447c-bc69-ae7307c9a7c0
---
Config-driven architecture refactoring in progress.

**Done (Phases 0-2):**
- GenericProcess + PluginManager + blueprint-based launch
- 7 plugins in multiprocess_prototype/plugins/ catalog
- Old hardcoded processes kept for fallback

**Constructor Tab — Phase 1 DONE:** WireDefinition + SystemTopology.wires + WireEditorModel + blueprint_io

**Constructor Tab — Phase 2 DONE:** NodeGraphQt canvas — CrossProcessModel, PluginProcessNode, PluginGraphAdapter, GraphBuilder

**Constructor Tab — Phase 3 DONE (2026-05-04):** Right panels — ProcessPluginPanel (reuses ChainEditor/Catalog/ConfigPanel), WireInspectorPanel + ShmConfigPanel, QStackedWidget, Save/Load Blueprint, edge→wire_key mapping. 49 tests.

**Constructor Tab — Phase 4 DONE (2026-05-04):** Apply + Runtime integration — 73 tests total
  - converters.py: diff_wire_configs() + extract_wire_commands() (diff → teardown/setup/modified IPC commands)
  - TopologyBridge: _apply_wires() — 4th transport (IPC) for SECTION_WIRES, after processes/sources/pipeline, before displays
  - ProcessManagerProcess: wire.setup/teardown/status commands — SHM allocate via MemoryManager + IPC wire.configure to child processes
  - ProcessModule: wire.configure/deconfigure — creates FrameShmMiddleware, registers in RouterManager
  - RouterManager: added remove_send_middleware/remove_receive_middleware (via MiddlewarePipeline.remove)
  - WireDataBridge: QTimer polling (2s), WireStatus enum (NOT_APPLIED/PENDING/IDLE/ACTIVE/BROKEN), statuses_changed signal
  - Canvas feedback: WIRE_STATUS_COLORS, _wire_key_to_pipe mapping, update_wire_colors(), Apply button in toolbar
  - Plan: multiprocess_prototype/plans/phase4_constructor_runtime_integration.md

**Why:** User wants zero-code system assembly — visual constructor over framework constructor.

**How to apply:** Phase 5 next — ShmRouteNode (fan-out) + Plugin Manager Tab (catalog, lifecycle, metrics).
