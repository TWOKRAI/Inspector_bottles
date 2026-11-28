---
name: feedback_shared_store_row_cap_evicts_rare_kinds
description: Общий потолок строк в сторе (ObservabilityStore.purge max_rows) вытесняет редкие роды объёмом stats / shared row cap evicts rare kinds, journal, audit, retention per kind
metadata:
  type: feedback
module: [channel_routing_module]
mechanism: [persistence]
---

`ObservabilityStore.purge(max_rows)` deletes the oldest rows across ALL kinds.

Probe (investigator, 2026-11-26): 1 log row + 1 custom-kind row + 1000 `stats` rows, `purge(max_rows=500)` → `log=0 custom=0 stats=500`.

**Why:** a rare record (error, device command, audit) is lost because a noisy kind fills the shared cap.

**How to apply:** before reusing a shared store as a journal or audit store, check retention per kind. The documents plane (`Services/documents`) keeps per-kind time retention and never purges a kind that has none.
