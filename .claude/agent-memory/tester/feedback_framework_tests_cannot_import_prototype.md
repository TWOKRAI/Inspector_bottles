---
name: feedback-framework-tests-cannot-import-prototype
description: A test file under multiprocess_framework/.../tests/ must never import multiprocess_prototype — split acceptance criteria that need boot config (system.yaml) into a companion file under multiprocess_prototype/backend/tests/
metadata:
  type: feedback
---

`.sentrux/rules.toml` blocks `multiprocess_framework/* → multiprocess_prototype/*` with NO
exception for `tests/` directories — the boundary is enforced on the whole glob, test files
included. The PostToolUse hook fires immediately on `Write` the moment a framework-side test
file imports anything under `multiprocess_prototype` (e.g. `load_system_config`,
`build_throttle_rules`).

**Why:** hit this on task RT-2 (telemetry-stage6, 2026-08-18): the orchestrator's brief named
a single file path under `multiprocess_framework/modules/process_module/tests/`, but two of
the six acceptance criteria (A1/A3, plus A2 which builds the gate FROM that config) were
inherently about the PRODUCTION `multiprocess_prototype/backend/config/system.yaml` and
`backend/state/manager_setup.py` — untestable without importing prototype. Writing everything
into the one instructed path tripped the reverse-import guard on the first `Write`.

**How to apply:** when an acceptance criterion needs prototype-layer config/wiring but the
assigned test path is framework-side, split into two files instead of forcing one:
framework-only assertions stay at the instructed path; prototype-dependent assertions move to
a companion file under `multiprocess_prototype/backend/tests/` (prototype → framework is the
allowed forward direction, confirmed safe — no hook fires there). Both dirs already have
`__init__.py`, so reusing the identical basename in both locations is safe (distinct dotted
module paths, no pytest collection collision) and keeps the pair discoverable as one acceptance
suite. Name the split explicitly in both files' module docstrings AND in the report back to
the orchestrator — don't silently relocate without saying why; it's exactly the kind of
discrepancy-between-brief-and-repo that an independent tester is supposed to surface, see also
[[feedback_freeform_brief_without_mode_header]].
