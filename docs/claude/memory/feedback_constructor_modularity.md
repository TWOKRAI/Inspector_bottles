---
name: Constructor modularity principle
description: Everything must be modular constructor — bridge, commands, bindings — same as framework and GUI primitives
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
