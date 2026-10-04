---
name: Constructor modularity principle
description: Everything must be modular constructor + RUNTIME FAULT ISOLATION — one module/process/worker/plugin failing must not break siblings (blast-radius containment)
type: feedback
originSessionId: 6e904387-9338-4f96-8a85-5ecea4c5bba6
---
All layers (framework, prototype, GUI, bridge) must follow the constructor/building-blocks pattern. Each component is an independent module: pluggable, replaceable, independently testable, composable.

**Why:** This is the core architectural philosophy of the entire project — from ProcessModule plugins to GUI primitives to topology YAML. The bridge layer (Phase 12) is no exception.

**How to apply:** When designing new subsystems (bridge, command protocol, bindings), ensure:
- Each class is a standalone unit with clear interface (Protocol or ABC)
- Dependencies via DI, never hardcoded
- Pure Python core, Qt only at edges (lazy import)
- Can be tested without spinning up the full app
- Can be replaced or extended without touching other modules
- Follows same pattern as existing primitives: small composable blocks → assembled into bigger structures

**No hacks rule:** When something doesn't work — stop and think about root cause. Never patch with workarounds. Decompose the problem into parts, understand each part, then assemble the solution like a constructor. If a piece doesn't fit — the piece is wrong, not the assembly.

**Runtime fault isolation (owner refinement, 2026-06-18):** modularity must ALSO mean blast-radius containment — if one module/process/worker/plugin fails or crashes, siblings keep running and degradation is graceful. The framework is a constructor of *fault-isolated* blocks, not just decoupled code. First-class roadmap criterion, on par with sentrux modularity.

**How to apply (fault isolation):**
- A failing plugin/worker must not crash its process or the supervisor (e.g. device_hub supervisor-tick exception killing the always-on hub worker — wrap per-item, never let one item down the whole loop).
- Contain → report → degrade: errors surface (log + status=error + counter), never silent-swallow AND never cascade.
- Bulkheads: process boundaries (mp) + per-worker/per-plugin guards + RestartPolicy + bounded queues/back-pressure; add health-gate / circuit-breaker where a sibling failure would propagate.
- Acceptance: one block down ≠ whole pipeline down.

Relates to [[feedback_logger_error_stats_managers]] and the device_hub supervisor-crash + hot-path produce() swallow findings.
