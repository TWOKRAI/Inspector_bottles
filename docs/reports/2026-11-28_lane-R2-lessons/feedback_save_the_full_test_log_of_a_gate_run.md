---
name: feedback-save-the-full-test-log-of-a-gate-run
description: "Прогон набора писать в файл целиком, не через tail: tail -30 потерял единственный traceback плавающего красного / save full pytest log, tail lost the only traceback of a flaky red"
metadata:
  type: feedback
  module: [scripts]
  mechanism: [test-infra, flaky-tests]
---

**Trap.** A gate script that pipes pytest through `tail` keeps the summary and drops the traceback. A race-dependent red does not come back on demand.

**Measured (2026-11-27).** Full `Services/device_hub/tests`: 1213 passed, 6 skipped, 1 failed against a prediction of 1214 / 0. The script ended in `tail -30`; the traceback was gone, and an investigator had to rebuild the race (tick closed the transport before the waiting STOP took the lock).

**How to apply.** Redirect each suite to its own log file, print only the summary line and the `FAILED` lines from it, and run with `--tb=long -rfE`.

**Trigger.** Writing a script or a command that runs a test suite once and shows a shortened output.
