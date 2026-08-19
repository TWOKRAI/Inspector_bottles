---
name: do-shutdown-on-unbooted-plugin-is-a-silent-noop
description: ProcessModulePlugin._do_shutdown() on a plugin still in IDLE (never taken through _do_configure/_do_start) does not raise but also skips real teardown (e.g. PluginLevels.retract never fires) — always drive the full configure->start->shutdown lifecycle in acceptance tests for shutdown-triggered effects
metadata:
  type: feedback
---

`ProcessModulePlugin` is a GStreamer-style state machine (`IDLE → READY →
RUNNING → STOPPED`, `plugins/base.py`). Calling `plugin._do_shutdown(ctx)`
directly on an instance that was only constructed — never run through
`plugin._do_configure(ctx)` + `plugin._do_start(ctx)` — does not raise and
looks like it "worked" (no exception, `plugin.state` may still read `IDLE`
afterward with no error), but skips whatever teardown work is gated on the
prior state. Confirmed concretely for plugin-level metrics
(`telemetry-stage6`, S-31/quartet acceptance, 2026-08-19): shutting down an
un-booted "impostor" plugin did not visibly retract anything until the full
lifecycle was driven first.

**Why:** an early version of a Д1/Д3-style acceptance probe called
`_do_shutdown` on plugins that were only `Plugin("name")`-constructed, and
produced ambiguous results (couldn't tell "no defect" from "shutdown never
really ran"). Re-running with `plugin._do_configure(ctx); plugin._do_start(ctx)`
before `plugin._do_shutdown(ctx)` (confirmed via `plugin.state` transitioning
IDLE→READY→RUNNING→STOPPED, observable and asserted) gave a reproducible,
trustworthy result.

**How to apply:** any acceptance/hazard test that exercises "a plugin shuts
down and something should happen as a result" (retraction, resource release,
unregistration) must drive the full boot sequence first — a small shared
helper (`_boot(plugin, ctx): plugin._do_configure(ctx); plugin._do_start(ctx)`)
and assert the resulting `plugin.state` at least once, so a broken boot fails
loudly instead of producing a silent false negative in the shutdown
assertion. See also
[[feedback_reused_heartbeat_required_for_retraction_ticks]] for the sibling
trap found in the same exploration.
