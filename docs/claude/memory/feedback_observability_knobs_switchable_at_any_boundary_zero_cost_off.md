---
name: observability-knobs-switchable-at-any-boundary-zero-cost-off
description: Owner's standing rule 2026-09-08 — every observability parameter must be switchable on/off at any boundary (process, hop, sink, metric) at runtime for debugging, viewable on demand, and cost nothing when off; measured gaps — sink disable still pays emission, frame_trace is import-time only
metadata:
  type: feedback
---

**Owner, 2026-09-08 (verbatim intent):** «мне главное чтоб это можно было включать и выключать на любой
границе и смотреть при необходимости, а когда не нужно выключать чтоб нагрузки не было. Короче для
отладки. И так все параметры наблюдаемости.»

This is the acceptance bar for EVERY observability parameter, not only frame trace: (1) runtime on/off
without restart, addressable to one process / one hop / one sink / one metric; (2) observable on demand
through the consumer surfaces (readback, store, tail); (3) **zero cost when off — measured, not asserted**.

**Measured state on 2026-09-08 (consumer acceptance, `docs/reviews/2026-09-08_observability-consumer-acceptance.md`):**
- Meets the bar at runtime: log level per process and per source (K1/K2), TTL with voiced revert (K4),
  numbers policy by glob path (K6), store threshold (K7), publisher gate per metric (K5), plugin registers (K10).
- **Sink disable (K3) does NOT remove the cost**: the record is still built and routed, and shows up as
  `records_without_channels` — it removes the write, not the emission. Cost is removed by LEVEL and by the
  numbers policy at the source, not by the sink switch. Say this to the owner when they ask «выключил — нагрузки нет».
- **frame_trace** is import-time env only (no L1/L2/L3, no per-boundary addressing) → Task 4.15 makes it a
  knob addressable per process and per hop, with a road-cost measurement for the OFF state.
- Cost-when-off has a measuring instrument only for the emitter road (`_road_cost.py`, Task 3.3: +1.52 µs at
  585k rec/s); there is no per-knob «OFF costs nothing» proof yet for the other families.

**Why:** the owner's use is debugging a live line: switch a boundary on, look, switch it off, and trust that
the production path is untouched. A knob whose OFF still pays emission silently steals the frame budget.

**How to apply:** every new knob (Task 4.9 `KnobManager`, Task 4.15, otel v2) ships with three literals in its
acceptance: addressable scope (process/hop/sink/metric), consumer-visible effect ON and OFF (paired check),
and a measured OFF cost with spread. The consumer acceptance probe (`/core:quality:observability-acceptance`)
gets a column «цена в выключенном» once the instrument exists. Related:
[[project_observability_consumer_acceptance]], [[feedback_a_budget_belongs_to_a_path_not_to_a_mechanism]],
[[project_knobs_universal_manager]].
