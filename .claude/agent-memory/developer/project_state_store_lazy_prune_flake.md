---
name: project-state-store-lazy-prune-flake
description: state_store_module/tests/test_throttle.py::TestLazyPrune is intermittently red ONLY inside the full ~5150-test scripts/run_framework_tests.py run, never in isolation — pre-existing, unrelated to logger/command_module/process_module work
metadata:
  type: project
---

Discovered 2026-07-21 while verifying an unrelated logger/command_module change (plan
`backend-ctl-proof-discipline`, commits `02720ef7`/`cc6b781e`). Ran the full
`scripts/run_framework_tests.py` suite 3 times back-to-back on the exact same code:

- Run 1: clean, 5150 passed, 6 skipped, 0 failed.
- Run 2: 1 failed — `TestLazyPrune::test_lazy_prune_bounds_pending_under_block_rule_stream`.
- Run 3: 1 failed — `TestLazyPrune::test_lazy_prune_bounds_growth_under_unique_path_stream`
  (a DIFFERENT test in the same class).

Both failing tests pass 6/6 and 3/3 respectively when run in isolation (single test, whole
class). Also confirmed via `git stash`/`stash pop` round-trip that this reproduces with
`state_store_module` code completely unmodified (I never touched that module this session) —
it's about running inside the full ~5150-test single pytest process, not about any specific
code change. Both tests use `patch("time.monotonic", side_effect=[...])` with a
FIXED-length list sized to the exact expected call count — a pattern that's fragile to ANY
extra/missing call to the patched function, which is plausible if something upstream in a
huge shared pytest session affects GC timing or dict-iteration count in
`ThrottleMiddleware`'s lazy-prune path.

**Why this matters:** if you see `TestLazyPrune` (or possibly siblings in the same file) fail
in a full-suite run and you did NOT touch `state_store_module`/`ThrottleMiddleware`, do not
assume your unrelated change caused it — re-run in isolation first (near-instant, `-q` single
test or single class) to confirm it's this pre-existing flake before spending time
investigating your own diff. Not fixed here — out of scope for the task that found it,
belongs to whoever owns `state_store_module`'s test suite next.
