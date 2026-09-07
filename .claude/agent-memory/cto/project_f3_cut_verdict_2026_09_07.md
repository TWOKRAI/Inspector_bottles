---
name: f3-cut-verdict-2026-09-07
description: CTO verdict 2026-09-07 on cutting Ф3 of observability-closure 9→6 (3.4, 3.6, 3.7 cut; "shrink 3.4 to signature" rejected) with the conditions and the F3 mis-parking I own
metadata:
  type: project
---

Verdict 2026-09-07 (base `aa1b91d1`): cut 3.4, 3.6, 3.7 entirely; the lead's "shrink 3.4 to
`declare_metric(..., unit, description, kind)` + record_timing guard" REJECTED as the crutch.
Conditions: (i) ADR line — number metadata lives on the numbers plane, key `metric_identity`,
slot `NumberRecord.unit`; levels catalog never carries unit/kind; (ii) unit writer re-homed to Ф4.6
(renames the five framework levels) or to the first consumer's plan (otel v2); (iii) otel corrects
Р-8/:123/:638 in its own file; (iv) purge voice with count (3.7's only framework residual, ~3 lines,
`sweep_observability_history` discards the report at `process_heartbeat.py:535`) — solo, said aloud,
pair 0/N injected, before or inside 3.8.

**Why:** reproduced, not read — catalog keeps first owner silently; ctx refuses dotted names;
module-level accepts them and pollutes `gated_metrics()`; live store 2026-09-05 has 0 stats rows
with a metric identity (only 3 observation identities), so 3.6's timing metrics would be invisible
to `history_query(metric=)` without the "unpack snapshot" decision (horizon 47.5 h → 1.4 h).

**F3 I mis-parked in my Ф2 verdict**: premise "declared name bounds the set structurally" is false
on HEAD — `ObservationPolicy` cache grew to 3000 on 3000 undeclared names with `declared_metrics()`
empty; gate uses `set(gated_metrics()) | extra`. F3 needs its own ceiling+voice home (Ф4.1/4.10).

**How to apply:** at Ф3 acceptance (3.8) check the four conditions landed; take the Task 3.5
`limit=100` vs 12 000 B open question there; expect 3.8 to also close 3.3's and 3.1's stand debts.
