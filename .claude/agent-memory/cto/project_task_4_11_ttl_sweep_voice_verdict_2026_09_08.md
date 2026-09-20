---
name: task-4-11-ttl-sweep-voice-verdict
description: Task 4.11 (observability-closure F4 wave 1) escalation verdict 2026-09-08 — ADR-PM-046 voice must be gated by origin; ttl-sweeper is the only authorless rebuild; six call sites reach the voice, not two
metadata:
  type: project
---

Verdict 2026-09-08 on the Task 4.11 fork: option (b) — the ADR-PM-046 voice stays silent when the rebuild origin is `ttl-sweeper`; all other origins (boot birth, boot:layers/companion, watcher:*, command:config.reload, switch:*) voice. Closure of 4.11 conditioned on this gating + docstring naming six call sites + a tester pair on the sweep road.

**Why:** `_voice_repurposed_stats_enabled` is a STATE predicate at the rebuild seam (`compose_managers_payload`), so it counts rebuilds, not actions. Reproduced on a real LoggerManager: an unrelated L3 key (`log_level`) expiring re-applies L1 `stats.enabled: false` and takes a window slot; the next real `config.reload` then reads "подавлено: 1" where the 1 is a timer. On a stuck rebuild (`rebuild_pending`) the sweeper retries every tick and the voice fires every window — 3 lines for 3 retries with window 0.2 s. The sweep already has its own WARNING (`_announce_revert`) naming the reverted key, so silencing the migration hint there loses nothing except one corner (L3 true masks L1 false at the time L1 is applied, then expires) — the hint's home for that corner is `_announce_revert`, not the rebuild seam.

**How to apply:** any "once per operator action" claim must be checked against the ORIGIN inventory, not the call-site count alone — grep `apply_observability_layers(` (5 production sites) plus the direct `compose_managers_payload` birth road (`process_managers.py`), then classify by `origin`; `observability_ttl.AUDIT_ORIGIN` is the only origin with no human behind it (the module says so itself). A voice whose text is advice to the AUTHOR of a key belongs on authored roads only.
