---
name: backend-ctl-state-transport-path
description: backend_ctl state.changed rides the Ф1.1b direct-socket-bridge, not the {name}_state drop_oldest queue — so the FW_STATE flip is transport-neutral for the driver; read-model has no revision-gap detection (truth-hole)
metadata:
  type: project
---

# backend_ctl state-plane transport is the direct socket bridge, not the state queue

**Fact (VERIFIED 2026-07-23, branch fix/truth-holes-closure):**

The driver subscribes with `sender="backend_ctl"` (driver.py:116). `state.changed`
is published by `DeltaDispatcher._send_state_changed` with `targets=[subscriber]`,
`queue_type="state"` (delta_dispatcher.py:387). But the driver is an EXTERNAL socket
subscriber with NO `backend_ctl_state` queue. In `RouterManager._deliver_by_targets`
(router_manager.py:489-493) the Ф1.1b bridge fires: `_channel_registry.get("backend_ctl")`
returns the SocketChannel AND `_queue_absent("backend_ctl","state")` is True →
`_deliver_via_channel` → `SocketChannel.send()` = direct synchronous `sendall` write
(socket_channel.py:167-211). No `{name}_state` queue, no `drop_oldest`, no `data_evicted`.

**Why: consequence for the b284c561/f22435ed flip.**
- COALESCE (b284c561) DOES apply — it batches deltas upstream in the dispatcher before
  routing, so the driver gets batched envelopes (fewer, larger). Wire shape unchanged:
  `data.deltas` was ALWAYS a list with `revision`/`first_revision`.
- FW_STATE_QUEUE deletion (f22435ed, drop_oldest 'state' queue) is N/A to the driver —
  it never rode a per-subscriber queue. **The flip is transport-neutral for the driver.**

**How to apply:** When auditing whether a state/queue transport change hit backend_ctl,
check the Ф1.1b bridge path first — the driver is NOT a queue subscriber like GUI. The
"gui storm fix" neither protects nor degrades the driver socket. Two live risks remain:
(1) `SocketChannel.send` has no send-timeout; a stalled driver reader blocks the shared
AsyncSender thread (HOL risk to other async router sends). (2) `_ingest_state_changed`
(driver.py:1039) ignores `revision`/`first_revision` entirely — unlike GUI StateProxy
(gui_state_proxy.py:84-118) which detects gaps and resyncs. Any lost envelope (socket
hiccup/reconnect) = silent staleness in telemetry_snapshot/history + missed
await_condition crossing, with NO gap signal. This is a residual truth-hole the closure
branch did not cover for the driver's own read-model. See [[project_gui_system_queue_storm]].
