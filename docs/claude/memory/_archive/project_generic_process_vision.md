---
name: GenericProcess constructor vision
description: Strategic direction — replace hardcoded process classes with GenericProcess + pluggable modules + declarative config (YAML). Three layers: Multiprocess Framework → Vision Framework → App config.
type: project
originSessionId: 332af62b-d010-4685-939f-b2282dda5016
---
User wants to evolve from hardcoded process classes (camera/, processor/, renderer/ etc. — each 6 files with same pattern) to a config-driven constructor architecture.

**Three-layer architecture:**
1. Multiprocess Framework — GenericProcess + ModuleRegistry + IPC/SHM/Router/Worker/Topology
2. Domain Framework (Vision Framework) — pluggable modules: CaptureModule, DetectorModule, RendererModule, DBModule
3. Application — declarative config (YAML/JSON), zero code, UI-editable via SystemTopology

**Key abstraction: ProcessModulePlugin**
- name, config_schema (SchemaBase), shm_inputs/outputs, ipc_commands
- Lifecycle: init(config, adapter) → tick() → shutdown()
- Modules composable via pipeline within a process

**Evolution path:**
1. GenericProcess in framework — loads modules by config
2. Pilot — migrate CameraProcess → GenericProcess + CaptureModule
3. Remaining processes — one by one, module extraction
4. YAML config — replace code-based AppConfig with declarative
5. Vision Framework — extract modules into separate package

**Why:** Current pattern is repetitive (6 files per process, same structure). SystemTopology already supports runtime diff/apply but processes are still hardcoded. New process = new config, not new folder.

**How to apply:** Vision doc at `workspace/dev/vision_generic_process_constructor.md`. Don't start implementing until detailed plan exists. Current Phase 1 work (ProcessEditorModel, SystemTopology) is correct foundation.
