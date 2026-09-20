---
name: otlp-http-timeout-is-not-a-call-ceiling
description: OTLPLogExporter(timeout=T) bounds the retry schedule, not the call — measured 42 s at T=30 (black hole, Windows) and 4.08 s at T=3; framework graceful budget is 5 s and PM is terminated at 5 s even with a healthy plugin (control measured)
metadata:
  type: project
---

`OTLPLogExporter(timeout=T)` (opentelemetry-exporter-otlp-proto-http 1.44.0) is NOT a ceiling on
`export()`. Measured 2026-09-07 (CTO, otel-export Task 2.2 forks):
- refused localhost, T=30: 23.44 / 24.36 / 22.85 s (three runs; backoff 1-2-4-8-16 with jitter)
- refused localhost, T=3: 4.08 s (overshoot +36%)
- black hole 10.255.255.1, T=30: 42.08 s — `_export` re-POSTs once on `requests.ConnectionError`
  with the original timeout, and Windows connect() gives up at ~21 s (2 SYN retransmits) → 2×21.
- 401 vs refused vs black hole: identical `ExportOutcome.reason` ("приёмник вернул 'FAILURE'");
  the HTTP status lives only in the SDK's stdlib logger → `logging.lastResort` → child stderr.
- SDK-native header path works with zero code: `headers={}` + `OTEL_EXPORTER_OTLP_HEADERS`
  reaches the session; config `${VAR}` placeholders override env with the literal string.

Framework side: `stop_all(timeout=5.0)` / spawner `stop_timeout=5.0`; and `launcher.shutdown()`
takes 5.1 s with "ProcessManager did not stop in 5.0s, terminating" EVEN with an open collector
(control run) — pre-existing graceful-stop debt, not the plugin.

**Why:** any verdict on a synchronous network call in `shutdown()` or on the receive thread must
use these numbers, not the readback's `export_timeout_sec`; and a 5 s terminate at stop must be
compared against the open-collector control before being attributed to the plugin.
**How to apply:** at 2.4 acceptance demand "stop with dead collector inside the 5 s budget, final
counters line present" and measure with a black-hole endpoint, not only refused localhost.
Related: [[lock-hold-time-claims-need-a-lock-free-control-under-the-gil]].
