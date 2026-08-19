---
name: observability-provenance-witness-keys
description: Picking К1/К2-style witness keys for ObservabilityLayers.provenance() tests — scalar leaves only, plus a safe real fixture topology for hot-rebuild tests
metadata:
  type: feedback
---

When a test needs one "definitely framework-layer" key and one "definitely
app-layer" key against a real `system.yaml` (e.g. hot-rebuild provenance
acceptance tests, the Task 5.x observability-layers family), prefer **scalar
schema leaves** (`log_level`, `session_ttl_sec`) over container-type schema
fields (`documents`, `errors`, `stats`, `channels`).

**Why:** `ObservabilityLayers._provenance_leaves()` builds its "explicit" map
from the RAW app/recipe/session sections, while `_schema_keys()` builds its
candidate list from `ObservabilityConfig()`'s SCHEMA DEFAULT dump. When a
container field's schema default is an empty dict (`{}`, a leaf by the
`_is_layer_leaf` rule) but the real file sets a NON-empty dict under it, the
two flattenings disagree in granularity: the schema-default path
(`documents.config`, measured on 2026-08-18's system.yaml) shows up
`framework`-tagged from step 1 of `provenance()`, while the real deeper
leaves it actually contains (`documents.config.db_path`,
`documents.config.retention_sec.audit`, ...) show up `app`-tagged from step
2, as SEPARATE dict keys — both present at once, neither wrong, just
confusing if you didn't expect it. A container key picked as a witness would
make the test's premise ("this key is untouched by system.yaml") look false
even though the file DOES configure that area, just one level deeper. Scalar
leaves don't have this ambiguity — pick those.

**Fixture topology tip:** `multiprocess_prototype/backend/topology/base.yaml`
is a good minimal REAL production topology for exercising the hot-rebuild
seam (`orchestrator_hooks.configure_topology_engine` → `_build_proc_dicts`):
one process (`devices`), no recipe-level `observability:` section (keeps L1
app vs. L0 framework clean, no L2 recipe noise), and empty `wires: []` (the
blueprint validates regardless of `PluginRegistry`/discovery ordering, since
wire-port resolution is the only thing that consults the registry).

**How to apply:** before hardcoding a witness key in a provenance test, grep
the real `system.yaml` for the key's TOP-LEVEL name and confirm it is a
scalar (not a dict) in `ObservabilityConfig`'s field list
(`multiprocess_framework/modules/process_module/configs/observability_config.py`).
Measure the actual `provenance()` output on the current file rather than
assuming — the framework-vs-app split shifts whenever `system.yaml` or the
schema's field set changes (same "query the live behavior before asserting"
discipline as [[feedback_config_reload_ttl_addressing_guard]], one door over
on `config.reload`).
