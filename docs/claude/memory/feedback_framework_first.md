---
name: Framework-first decision rule
description: Framework = powerful/universal (contract + impls, get it right once); prototype = disposable (thin consumer). When in doubt optimize the FRAMEWORK, not prototype convenience.
metadata:
  type: feedback
---
Owner's standing rule for framework-vs-prototype decisions (adopted 2026-06-18). North star: make `multiprocess_framework` powerful and universal (best patterns, once, correctly); `multiprocess_prototype` is disposable (always re-doable). **When in doubt ask "what makes the FRAMEWORK more universal?" — not "what's least code in the prototype."**

**Why:** the framework serves projects simple→complex; the prototype is just ONE (medium) consumer. Optimizing decisions around the prototype quietly narrows the framework. The rule ends re-litigating every boundary call.

**How to apply:**
1. Mechanism wanted by ≥2 projects → framework; app-domain (vision pipeline, recipes, Inspector widgets) → prototype. Doubt → treat as framework concern.
2. In framework: program to a **CONTRACT** (Protocol/ABC), allow multiple implementations — never "one true class."
3. **Duplication** = same contract, same tier, no distinguishing value. Different tiers (simple/complex) or concerns (IPC/undo/events) → NOT duplicates; keep both, name the boundary.
4. "unused ≠ unneeded" applies to **framework blocks behind a contract**; prototype dead-wiring is just cleanup (remove it).
5. Prototype = **thin consumer** of framework contracts; domain specifics stay a thin layer.

Worked example (undo): undo is a framework concern → contract `UndoRedoController` (already exists, `tab_layout_protocol.py:29`) + 2 impls (ActionBus=patch for simple/complex, SnapshotHistory=snapshot for medium/immutable-aggregate) — keep both; prototype stops instantiating the unused one. Full decision + diagrams: `docs/audits/2026-06-18_command-undo-system.md`. Related: [[feedback_constructor_modularity]].
