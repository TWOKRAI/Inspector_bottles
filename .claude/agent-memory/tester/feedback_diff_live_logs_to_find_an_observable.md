---
name: diff-live-logs-to-find-an-observable
description: when a RED criterion needs "an observable, not code reading" and the implementation files are forbidden, run both paths live and diff their per-process log files instead of guessing a marker name
metadata:
  type: feedback
---

Task 1.1 of `lifecycle-stop-ownership` (2026-09-24) needed criterion 2: "children's exit
hook ran in system-stop mode — observable, not by reading code." `process_manager_process.py`
and `reader_gone.py` were FORBIDDEN, and a first grep pass (stdout/stderr capture + the
`observability.db` sqlite file) found **zero** occurrences of `system_stop` anywhere — the
plan's own wording ("system_stop=True") is aspirational language for the target state, not
literal text emitted today.

**What worked:** wrote two tiny throwaway scripts (`BackendHarness(...).start()` /
`.stop()`, and the same with `drv.system_command({"cmd": "system.shutdown"})`), ran both
live against the real recipe on scratch ports, and grepped the resulting
`<log_dir>/<child>/messages.log` files for the word "stop" (not "system_stop" — a broader
net). Found `"<name>: Stop signal received (system-wide)"` on the harness.stop() path and
the same line **without** the suffix on the system.shutdown path, for all 6 children —
a real, already-existing, per-process INFO-level log line, confirmed by literally diffing
two live runs, not guessed by naming convention.

**Why this beats guessing a symbol name:** the "one guessed hook" technique
([[feedback_red_without_interface_needs_one_named_guessed_hook]]) works when a new symbol
must be wired in and the only cost of a wrong guess is a rename. Here the guess would be a
*log string* the tester cannot verify without seeing the diff — a wrong guess produces a
test that stays red forever even after a correct fix (false RED), and the tester would
never know until the lead reports back. Running both paths live and diffing real output
turns "guess a string" into "read a fact off two live runs" — same cost (one extra live
run per candidate), strictly more reliable, and stays within FORBIDDEN (no source files
opened, only runtime logs the tester's own scripts produced).

**How to apply:** when a RED criterion demands "observable, not by reading code" and grep
for the obvious candidate name (here `system_stop`) comes up empty in stdout/stderr AND any
on-disk state (log files, sqlite/observability stores) — don't fall back to guessing a
plausible name. Instead: (1) run the KNOWN-GOOD path live (here `harness.stop()`) with a
scratch `log_dir`, capture everything under it; (2) run the SUSPECTED-BUGGY path live with
a second scratch `log_dir`; (3) diff the two directory trees / grep both for a broad
keyword (the noun from the acceptance criterion, e.g. "stop", not the exact guessed
identifier). The differing line, if any, is the real observable — and running it also
satisfies the brief's separate "prove the observable is present on the good path (sanity)"
requirement for free, since you already have the good-path capture in hand.

**Residual risk, disclosed in the report rather than hidden:** the found string is still
*this tester's* choice of channel — if the implementer's fix changes behavior through a
different channel (a counter in `get_stats()`, a new store record) rather than the same log
line, the RED test can stay red after a correct fix (false RED). State this explicitly; it
is not fully closable without reading the forbidden implementation file.

See also [[feedback_red_without_interface_needs_one_named_guessed_hook]],
[[feedback_freeform_brief_without_mode_header]].
