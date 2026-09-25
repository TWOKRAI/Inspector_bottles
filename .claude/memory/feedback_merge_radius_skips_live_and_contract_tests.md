---
name: merge-radius-skips-live-and-contract-tests
description: A test radius picked by "changed directories" misses cross-module contract tests, and backend_ctl live tests silently skip without --backend-live — both happened on the gui-service 1.3a/1b.2a merge 2026-09-25
metadata:
  type: feedback
  last-verified: 2026-09-25
---

Before merging to main, a radius built from "directories the diff touched" is not enough, and
"backend_ctl/tests passed" does not mean the live stands ran.

**Why:** gui-service 1b.2a merged to main with two red contract tests that live in modules it
never touched — `statistics_module` A6 (introspect.* dictionary pinned at 10 names) and
`app_module/tests/test_contract.py` (no framework module imports app_module, test files
included). A neighbour session found them, not the radius. The same report claimed "live
stands included" — `backend_ctl/tests` without `--backend-live` puts every live test into
`skipped` (58 skipped went unread).

**How to apply:**
- A new builtin command or a new import in framework tests → also run
  `statistics_module/tests`, `app_module/tests`, `modules/tests` (order-independence cascade).
- Live claims need `pytest --backend-live` (or `make test-ctl`) and a look at the skip count.
- Live test ports are hard-coded per file (8860–8905 for gui-service); agree the range with any
  parallel session before running, see [[feedback_unblocking_signal_at_the_moment_of_fact]].
