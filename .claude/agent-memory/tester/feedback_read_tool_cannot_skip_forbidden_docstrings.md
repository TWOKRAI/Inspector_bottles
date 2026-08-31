---
name: read-tool-cannot-skip-forbidden-docstrings
description: A brief that forbids reading specific docstrings inside an otherwise-readable file (e.g. "signatures OK, declare_metric/publish_metric docstrings not") cannot be honored with the Read tool — it returns the whole file. Use Bash + inspect.signature (or black-box execution/introspection) to get signatures without the prose, and disclose prominently if the full file was already read.
metadata:
  type: feedback
---

When an independent-tester brief allows reading a module's PUBLIC SIGNATURES
but explicitly forbids specific methods' DOCSTRINGS (to avoid absorbing the
author's stated contract/reasoning and defeating the independence of the
acceptance test), the `Read` tool cannot honor that split — it returns the
file text wholesale, docstrings included. Confirmed the hard way
(`telemetry-stage6`, S-31/quartet acceptance, 2026-08-19): `Read` on
`plugins/base.py` to check `PluginContext` method signatures pulled in the
full prose of `declare_metric`/`publish_metric`, which the brief had named
explicitly as off-limits.

**Why:** this is a structural tool limitation, not a one-off mistake — any
future brief with the same "signatures yes, these docstrings no" shape hits
the identical problem. The mitigation used afterward worked well: `python -c
"import inspect; print(inspect.signature(Class.method))"` (or a small script
via Bash) gets the callable signature WITHOUT the docstring text, and more
generally, black-box **execution** (constructing objects, calling
private-but-precedented methods, observing return values/side effects) can
substitute for reading forbidden source entirely — it was how the actual
mechanism (ownership check, gate, retraction propagation) got reverse-engineered
for this task without reading the two heartbeat files or the orchestrator
that were explicitly forbidden.

**How to apply:**
1. When a brief splits "signature OK, docstring not" on a specific method
   inside an otherwise-allowed file, do NOT use `Read` on that file. Use
   `Bash` + `python -c "import inspect; print(inspect.signature(...))"` (or
   `dir()` for a member list) to get just the callable surface.
2. If `Read` already happened before this was noticed (as it did here — the
   whole file, prose included, entered context), do not pretend otherwise.
   State the violation prominently at the top of the deliverable (test file
   docstring) AND in the final report: name exactly which forbidden prose was
   seen and what specific implementation details it revealed, so whoever
   scores the "independence" of the acceptance tests can weigh the finding
   accordingly instead of assuming a clean-room result.
3. Prefer building the whole test harness by RUNNING code (constructing real
   objects from non-forbidden modules, calling private-but-precedented
   methods the way sibling test files already do, observing outputs) rather
   than reading forbidden source — this is not just a workaround, it produced
   MORE trustworthy findings here than reading would have, because every
   claim ended up backed by an actual reproduction instead of an assumption
   from prose.
