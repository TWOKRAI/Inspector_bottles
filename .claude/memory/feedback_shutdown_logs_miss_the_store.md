---
name: feedback-shutdown-logs-miss-the-store
description: ProcessModule.stop() unwires the observability store BEFORE shutdown() — anything logged from shutdown() never reaches observability.db
metadata:
  node_type: memory
  type: feedback
  originSessionId: 45b0456c-fb68-4821-bc06-ae5e9cae4302
  modified: 2026-09-26T12:00:20.237Z
---

`ProcessModule.stop()` runs `stop_all_workers()` → `_flush_observability()` (unwires the store tap, `_observability_store = None`) → `shutdown()`. So a log call inside any `shutdown()` override still prints to stderr/files but never lands in `observability.db`. Before lifecycle Task 1.6 this silently dropped PM's own "Stopping all processes" / "дети ВЫЖИЛИ" lines (0 rows in the old store). Fix pattern since 2026-09-26: the hook `_before_observability_teardown()` (ADR-PMM-033) — CTO accepted it as a phase stub, do NOT add a second hook; the next ordering need triggers lifecycle Task 3.1 (named stop phases).

**Why:** my brief for 1.6 assumed "PM's logger is alive in shutdown(), so it writes to the store" — false; the developer caught it only by checking `_observability_store` at runtime, after one whole agent run. Also: structured kwargs of a log record land under `extra["context"]`, not top-level `extra` (second wrong premise in the same brief).

**How to apply:** when a task needs a record in the store at stop time, verify by a live read of `observability.db`, not by reading the logger; write contracts as `extra.context.<key>`. Related: [[feedback_safety_net_masks_primary_fix]].
