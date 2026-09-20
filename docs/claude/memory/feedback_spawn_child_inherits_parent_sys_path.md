---
name: spawn-child-inherits-parent-sys-path
description: multiprocessing spawn copies the PARENT's sys.path into the child (preparation data) — setting PYTHONPATH inside pytest does not reach child processes; a "run without package X" injection must also touch sys.path of the parent
metadata:
  type: feedback
---

`multiprocessing` with the `spawn` start method sends `sys.path` of the parent to the child
(`spawn.get_preparation_data` → `sys_path`); the child does NOT recompute it from `PYTHONPATH`.
So an env change made after the parent started (e.g. inside a pytest test) never reaches a
child spawned by `SystemLauncher`/`BackendHarness`.

**Why:** measured 2026-09-20 on line-sim Task 1.1, criterion 5 ("without pymodbus the plugin
degrades, the process lives"): the tester put a stub `pymodbus/` first in `PYTHONPATH` and the
test was red — for the WRONG reason. Two harnesses in one process showed the "no-pymodbus" run
had `state=running`: the child imported the real package. A standalone script with the env set
before interpreter start worked, which is what hid the difference.

**How to apply:** for a child-side "package X is missing" injection, put the stub directory into
`sys.path` of the parent (`sys.path.insert(0, stub)`) before building the launcher, and remove it
in `finally`; the already-imported parent is unaffected, the fresh child interpreter sees the
stub first. Always prove an injection injects: assert the target's own status/state reflects the
absence (e.g. plugin `state == "error"`), not only the downstream symptom. Related:
[[feedback-injection-zero-may-mean-the-guards-were-not-collected]].
