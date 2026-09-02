---
name: knobs-universal-manager
description: Owner direction 2026-09-02 — knobs need a universal framework-level mechanism (own manager/inspector), observability is only the first consumer; Task 4.9 of observability-closure, own plan if ≥3 consumers
metadata:
  type: project
---

Owner's direction (2026-09-02, after phase Ф2 review): a knob must be ONE declaration
(`KnobSpec`: path, schema, apply, readback, doc) and a framework-level `KnobManager` on
`BaseManager` must provide layers L0→L3, TTL, audit, provenance, 3-valued verdict and
`introspect.knobs` for free. Observability is the first consumer, NOT the only one: registers
(`set_register_verified`, commit-confirmed), `telemetry.*`, `FW_*` flags, camera presets and
recipe params are further consumers. Spec: `plans/observability-closure/phase-4-scale-and-form.md`
Task 4.9; threshold — ≥3 consumers by inventory → own plan `knobs-universal-manager`.

**Why:** Ф2 review measured that one new knob (`heartbeat_interval_sec`) cost 7 hand-edited
places and the same phase that fixed such gaps for neighbours missed 2 of them; the verifier
answered identically to `{}` and to the strongest key of the phase. `ObservabilityLayers` is
already the generic layered store, named after its first consumer; registers and telemetry
re-implement the same apply→verify→rollback road.

**How to apply:** do Task 2.9 first (generic `expected` + schema-named readback, one day) and
merge; then 4.3 (Protocol readback) → inventory → 4.9. Extract the manager from the three
existing copies, never design it ahead of a second consumer ("universal with one consumer is a
rename"). Live object keeps ownership of the value (apply/readback are callbacks); verdict only
from live readback, never from the store; knob ≠ state — knobs are operator-set config with
layers/TTL, `state_store_module` stays the runtime-values store; old commands stay as thin
aliases. See [[feedback-all-components-base-manager]], [[feedback-fewer-layers]],
[[feedback-tool-features-before-validation]], [[project-observability-closure-progress]].
