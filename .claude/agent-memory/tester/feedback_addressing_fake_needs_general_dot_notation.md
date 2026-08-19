---
name: addressing-fake-needs-general-dot-notation
description: A services fake for a config-addressing acceptance test must implement the SAME dot-notation traversal contract as the real reader (Config._traverse) — a flat dict.get proves the fake's own shape, not the property under test, and stays red/green independent of whether the fix is right
metadata:
  type: feedback
---

When an acceptance test's whole point is "does the reader resolve key X regardless of WHICH
address form it arrives at" (e.g. flat `telemetry` vs nested `config.telemetry`), a
duck-typed services fake with `get_config = lambda key, default: self._config.get(key,
default)` (flat, single-level `dict.get`) is *only* correct for single-part keys. It silently
breaks the moment the real fix needs to try a **dotted fallback key** (`get_config("config.telemetry")`)
— the fake never sees the dot as a path separator, so it always misses, no matter whether the
production code is fixed correctly, fixed wrong, or not fixed at all. The test becomes
"green/red iff the fake happens to shape-match", not "green/red iff the property holds" — the
same failure mode as [[feedback_pydantic_extra_ignore_hides_red]] one level up (a boundary
that silently swallows the thing you meant to exercise).

**Why:** found by the coordinator's review, not by me, on `test_gate_config_address_acceptance.py`
(RT-2, telemetry-stage6, 2026-08-18). Wrote `_AddressingServices.get_config` as flat
`self._config.get(key, default)` — worked fine for B2/B3 (single-part `"telemetry"` key,
where flat and dotted resolution are identical), but B1/B4 tested the NESTED address, and a
verified-correct production fix (confirmed live: `ProcessConfigHandler(...).get("config.telemetry")`
returns the section, `.get("telemetry")` returns `None`) still left my tests red — because
the fake could never resolve a dotted key, independent of what the source code did. Caught
only because the coordinator ran the SAME scenario against the real `ProcessConfigHandler`
and compared.

**How to apply:**
1. Before trusting a fake's `get_config`/`get`-style method in an addressing test, find the
   REAL reader's traversal contract in the code (here: `Config._traverse`,
   `multiprocess_framework/modules/config_module/core/config.py:191-199` — split key on `.`,
   walk nested dicts, any missing level → default) and copy that exact algorithm into the
   fake, generically — not a special case for the one key string mentioned in the brief.
   A fake that only special-cases `"config.telemetry"` would pass today's test and still lie
   about the next key that needs the same fallback.
2. **Still add at least one test against the real object** wherever a fake stands in for a
   config/address resolution boundary — construct the real reader (here `ProcessConfigHandler`,
   built directly from a dict shaped like a real `proc_dict`, no `shared_resources` needed:
   `ProcessConfigHandler(name, config=proc_dict_shaped_dict)`) and run the SAME assertions
   through it. The fake is for cheap coverage of scenarios that don't hinge on the exact
   traversal contract; anything that DOES hinge on it needs the real object at least once,
   per this project's standing rule ("fake-harness test proves the harness" — global
   CLAUDE.md test-authorship section).
3. When a real `proc_dict`-shaped fixture is needed inside a `multiprocess_framework` test,
   do NOT import it from `multiprocess_prototype` (layer boundary, `.sentrux/rules.toml` —
   see [[feedback_framework_tests_cannot_import_prototype]]) — hand-build a dict with the same
   top-level key set, and name the measured source in the docstring instead of importing it.
