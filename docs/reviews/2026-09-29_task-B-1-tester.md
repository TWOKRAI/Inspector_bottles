# B-1 tester (RED acceptance) — 2026-09-29

STATUS: RED ready — 4 of 5 tests fail on measured rates (AssertionError), 1 green (stop latency). Not committed.

File: multiprocess_framework/modules/process_module/tests/test_source_producer_pacing_acceptance.py
(generic/ has no tests/ dir; process_module/tests/ holds its tests.)

| Test | Criterion | Bound | Run 1 / 2 / 3 | State |
|---|---|---|---|---|
| test_30fps_delivers_28_5_to_31_5 | 1 | [28.5, 31.5] it/s | 21.35 / 21.39 / 21.43 | RED |
| test_60fps_delivers_55_to_63 | 2 | [55, 63] it/s | 32.13 / 32.15 / 32.07 | RED |
| test_cycle_effective_hz_matches_30fps | 3 | median [27, 33] | 21.33 / 21.34 / 21.33 | RED |
| test_cycle_duration_ms_matches_30fps | 3 | median [30.0, 36.7] ms | 47.00 / 47.00 / 47.00 | RED |
| test_stop_returns_within_0_1s | 4 | < 0.1 s | 0.1 / 3.2 / 7.8 ms | GREEN |

Spread is under 0.1 it/s between runs; RED is deterministic here, not load noise.
Rates = (n-1)/(last-first produce() perf_counter stamp) over a 3 s window.
Threads are daemon, join deadline 2 s, pytest.mark.timeout(30) per test.

Interpreted rather than followed:
- Criterion 3 split into two tests (effective_hz and cycle_duration_ms): one test, one check.
- cycle_duration_ms is a last-cycle sample; the test takes the median of 20 snapshots (0.1 s apart, after 1 s warm-up) to avoid single-sample flake. Keys effective_hz / cycle_duration_ms / target_interval_ms / cycles found in generic/cycle_metrics.py docstring.
- cycle_duration_ms bound = 33.3 ms +-10%.
- Brief allowed reading source_producer.py: I read all of it, incl. run_loop's sleep code (10 ms sleep slices). Bounds come from the criteria only; still, I was not blind to the mechanism.

Left open / unreliable:
- No green control for the harness at a rate where pacing works (e.g. a precise pacer); the only evidence the harness is sound is that the stop test is green and rates repeat to 0.1.
- Not run on non-Windows; bounds are only proven RED here. Whether 28.5-31.5 is stable on a loaded CI box after the fix is unmeasured (a 3 s window gives ~1% edge error, the margin is 5%).
- 60 fps upper bound 63 and lower 55 after the fix depend on the fix achieving sub-16 ms granularity on Windows; if the fix uses a busy-wait the 4 tests still pass but CPU cost is not asserted.
- Break-injection against this file is the lead's job; not done.
