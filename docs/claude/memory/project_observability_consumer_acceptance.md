---
name: observability-consumer-acceptance
description: Independent consumer-side acceptance of observability exists — probe, living checklist, reference protocol 2026-09-08 (45/51 confirmed), the frame-path hop lag is unobservable, run it at phase points not per task
metadata:
  type: project
---

**2026-09-08, owner-commissioned QA pass (Fable agent as a consumer, not the author).** The
observability control plane was accepted from the outside for the first time: a probe drives a
headless `inspection_full` stand through `BackendDriver` and judges by independent arbiters (SQLite
read directly, log files on disk, `perf_counter_ns` at both ends).

- Probe: `backend_ctl/probes/probe_observability_consumer_acceptance.py` (~135 s of stand).
  Slash command: `/core:quality:observability-acceptance`.
- Living checklist with a «статус в плане» column: `multiprocess_framework/docs/observability/ACCEPTANCE_CHECKLIST.md`.
- Reference protocol: `docs/reviews/2026-09-08_observability-consumer-acceptance.md` — 51 rows,
  **PASS 43 / FAIL 1 (probe error, cleared by MCP lens) / PARTIAL 1 / NOT_REACHED 5 / UNVERIFIED 1**;
  run 1 gave 4 FAIL + 8 PARTIAL and **all 4 FAIL and 7 of 8 PARTIAL were the probe's own wrong model**, listed by name in §5.
- Latencies (ms, medians, two runs): RTT to a child 13.8/10.8 (bimodal ~10.5/~21.5), to ProcessManager ~22;
  emit → SQLite 59/83 (drain tick 100 ms); emit → live tail ~21; register write → readback ~41;
  TTL=20 s → revert line 21–22 s; renderer restart to new pid ~5.8 s.
- **The owner's ask «замерять сколько между модулями едут данные» is NOT satisfiable today — but not for
  the reason F1 gave.** The span mechanism exists (`process_module/generic/frame_trace.py`: transport/process/merge
  spans in `item["trace"]`, into `write_event.spans`, plus a `frame_trace_<p>` logger channel); measured
  2026-09-08 with `MULTIPROCESS_FRAME_TRACE=1` for 90 s without rejects: **0 spans reach any consumer** (store,
  logs, dedicated sinks idle). The env flag is read once at import and is not a knob; there are no hop numbers.
  Owner's decision 2026-09-08: **Task 4.15** in closure phase 4 (wave 2, after 4.6) — knob in L1/L2/L3 plus
  per-tick `hop_transport_ms`/`hop_process_ms` aggregates. Lesson: «нет поверхности» was a wrong model; the
  right claim was «поверхность есть, до потребителя не доезжает» — a mechanism you did not switch on is not absent.
- Other new findings for lane closure: `store_evicted` not in readback (F2), a single shared `errors.log`
  for all processes (F3), `first_n` counts from process start (F4), `send_command("all")` silent (F5),
  `logger_sink_enable` leaves an L3 key with a 300 s TTL (F6), driver dataclass vs MCP dict (F7).

**Why:** tests are written by the mechanism's author and prove agreement with the author's model;
the owner needed a map of «what exists and how to control it» from a consumer who does not know that
model. Half of run 1 verdicts were the consumer's own errors — that is the expected cost of the
outside view and is why the probe keeps its §5 «где ошибался я».

**How to apply:** run the probe at phase points (closure, otel, line-sim) and before a merge into
`main`, never per task; compare row by row with the 2026-09-08 protocol — a verdict shift on a row
whose code did not change is a finding. Never treat line counts per run as a baseline (Tasks 4.13/4.14
move them). In every delivery row name the receiver; when it is our own driver, the verdict also checks
the harness ([[feedback_a_stand_with_a_verdict_is_also_a_harness]]). A new observability function
means a new checklist row plus a probe step, with the expected literal written before the run.
Related: [[project_observability_closure_progress]], [[project_otel_export_plan_state]],
[[feedback_test_authorship_three_roles]].
