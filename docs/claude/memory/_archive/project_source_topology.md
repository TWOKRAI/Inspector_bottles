---
name: SourceTopology two-layer architecture
description: Sources (Layer 1) and Processing (Layer 2) are separate registers connected by shared region keys
type: project
originSessionId: 1223cca6-a6d2-4550-a4ca-364f8450e68a
---
Two-layer architecture for source/processing configuration (implemented 2026-04-28):

- **Layer 1 — SourceTopology** (SOURCES_REGISTER): cameras, processes, SHM, regions. Consumer: ProcessManager.
- **Layer 2 — ProcessingConfig** (PROCESSING_REGISTER): processing nodes per region. Consumer: ProcessorProcess.
- Layers connected by shared region keys (e.g. `camera_0_main`, `camera_0_roi1`).
- Camera and regions are linked (camera_ref), not nested. In UI shown nested for UX.

**Why:** Pipeline was monolithic (sources + processing in one structure). Separating allows independent evolution — sources change rarely, processing changes often. Different dispatch targets.

**How to apply:** SourcesTabWidget writes to SOURCES_REGISTER. Future PipelineTabWidget writes to PROCESSING_REGISTER. Sync bridge (`layers_to_pipeline`) maintains backward compatibility with ProcessorService until it migrates to Layer 2 directly.

Key files:
- `registers/sources/schemas.py` — SourceTopology, CameraSourceConfig, RegionSourceConfig
- `registers/processing/schemas.py` — ProcessingConfig, RegionPipelineConfig
- `registers/sources/converters.py` — layers_to_pipeline, pipeline_to_layers
- `registers/sources/topology_commands.py` — diff_topologies, diff_to_commands
- `multiprocess_framework/.../topology_manager.py` — universal TopologyManager in PM (composition)
